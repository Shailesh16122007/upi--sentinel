"""Case analysis orchestration: fuse -> timeline -> context/anomalies -> ML -> findings -> completeness -> summary.

Fully recomputed from extracted evidence each run (idempotent). Results are persisted to their tables.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import (Case, CaseTransaction, EvidenceFile, EvidenceRelationship, ExtractedEntity, Finding,
                        TimelineEvent)
from app.services.analysis import context, explain, findings as findings_, ml as ml_, modus as modus_, summary as summary_, timeline as timeline_
from app.services.audit import audit
from app.services.ingest import _step
from app.services.normalization.fuse import fuse


def _aware(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def load(db: Session, case: Case) -> tuple[dict, dict, list[dict]]:
    evs = db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == case.id).order_by(EvidenceFile.seq)).all()
    evidence = {e.id: {"id": e.id, "code": e.code, "kind": e.kind, "subtype": e.subtype or "OTHER", "status": e.status,
                       "original_name": e.original_name, "error": e.error, "user_time_hint": _aware(e.user_time_hint),
                       "method": e.method, "language": e.language} for e in evs}
    ents = db.scalars(select(ExtractedEntity).where(ExtractedEntity.case_id == case.id)).all()
    entities = [{"id": x.id, "evidence_id": x.evidence_id, "type": x.type, "value": x.value, "normalized": x.normalized,
                 "confidence": x.confidence, "occurred_at": _aware(x.occurred_at), "time_precision": x.time_precision,
                 "locator": x.locator, "context": x.context, "attrs": x.attrs or {}, "method": x.method} for x in ents
                if x.evidence_id in evidence]
    c = {"id": case.id, "ref": case.ref, "statement": case.statement, "approx_date": case.approx_date,
         "claimed_amount": case.claimed_amount, "created_at": _aware(case.created_at), "is_synthetic": case.is_synthetic}
    return c, evidence, entities


def analyze(db: Session, case: Case, actor: str = "system") -> dict:
    c, evidence, entities = load(db, case)
    # absolute times for audio statements when the user told us when the call started
    claims = []
    for x in entities:
        if x["type"] == "CLAIM":
            hint = evidence[x["evidence_id"]]["user_time_hint"]
            st = x["attrs"].get("start")
            x["_abs_time"] = hint + timedelta(seconds=st) if hint and st is not None else None
            claims.append(x)

    fused = fuse(list(evidence.values()), entities, c["approx_date"], c["claimed_amount"], case.disputed_selection)
    disputed = next((f for f in fused if f.kind == "DISPUTED"), None)
    history = [f for f in fused if f.kind == "HISTORICAL"]
    anomalies, ctx_meta = context.anomalies(disputed, history, entities, evidence, claims)
    ml = ml_.assess(disputed, history)
    comp = findings_.completeness(c, disputed, history, evidence, entities)
    fnd = findings_.classify(c, fused, evidence, entities, anomalies, ml, comp)
    modus = modus_.classify(c, evidence, entities)
    if modus:  # report the best-supported pattern(s) only, not every overlapping category
        top = modus[0]["groups"]
        modus = [m for m in modus if m["groups"] >= top - 1][:2]
    for m in modus:
        fnd.append({"category": "CONTEXTUAL", "code": "MODUS_PATTERN", "title": f"{m['strength']}: {m['label']}",
                    "detail": "Signals: " + "; ".join(sorted({s['label'] for s in m["signals"]})) + ". " + m["note"],
                    "sources": [{"evidence_id": s["evidence_id"], "label": s["code"], "entity_id": s["entity_id"]}
                                for s in m["signals"] if s.get("evidence_id")],
                    "is_anomaly": False, "is_conflict": False, "data": {"modus": m["code"], "groups": m["signal_groups"]}})
    explain.enrich(fnd, entities, len(history))
    tl = timeline_.build(c, evidence, entities, fused)
    summary, engine = summary_.build(c, disputed, evidence, fnd, comp, ml)

    for model in (CaseTransaction, TimelineEvent, Finding, EvidenceRelationship):
        db.execute(delete(model).where(model.case_id == case.id))
    db.flush()

    txn_rows: dict[int, CaseTransaction] = {}
    for i, f in enumerate(fused):
        row = CaseTransaction(case_id=case.id, kind=f.kind, amount=f.amount, occurred_at=f.occurred_at,
                              time_precision=f.precision, reference=f.reference, beneficiary=f.beneficiary,
                              beneficiary_vpa=f.beneficiary_vpa, status=f.status, channel=f.channel, device=f.device,
                              fields=_jsonable(f.fields), sources=f.sources,
                              match_basis="; ".join(sorted({l[3] for l in f.links}))[:300] or None,
                              match_confidence=f.confidence if f.links else None)
        db.add(row)
        txn_rows[i] = row
    db.flush()

    rels: list[EvidenceRelationship] = []
    key_to_ev = {m.key: m.evidence_id for f in fused for m in f.mentions}
    for i, f in enumerate(fused):
        if f.kind == "HISTORICAL":
            continue
        for ev_id in f.sources:
            conf = max([l[2] for l in f.links if key_to_ev.get(l[0]) == ev_id or key_to_ev.get(l[1]) == ev_id], default=1.0)
            rels.append(EvidenceRelationship(case_id=case.id, from_kind="evidence", from_id=ev_id, to_kind="transaction",
                                             to_id=txn_rows[i].id, relation="EVIDENCES", confidence=conf,
                                             basis=f"{evidence[ev_id]['code']} contains this transaction"))
        for a, b, conf, basis in f.links:
            ea, eb = key_to_ev[a], key_to_ev[b]
            if ea != eb:
                rels.append(EvidenceRelationship(case_id=case.id, from_kind="evidence", from_id=ea, to_kind="evidence",
                                                 to_id=eb, relation="SAME_TRANSACTION", confidence=conf, basis=basis[:300]))
        for cf in f.conflicts:
            ids = list(dict.fromkeys(v["evidence_id"] for v in cf["values"]))
            for j in range(1, len(ids)):
                rels.append(EvidenceRelationship(case_id=case.id, from_kind="evidence", from_id=ids[0], to_kind="evidence",
                                                 to_id=ids[j], relation="CONFLICTS_WITH", confidence=1.0,
                                                 basis=f"Different {cf['field'].replace('_', ' ')} values"))
    d_row = next((r for r in txn_rows.values() if r.kind == "DISPUTED"), None)
    if d_row:
        for fd in fnd:
            if fd["code"] == "COMMUNICATION_MATCHES_PAYMENT":
                rels.append(EvidenceRelationship(case_id=case.id, from_kind="evidence", from_id=fd["sources"][0]["evidence_id"],
                                                 to_kind="transaction", to_id=d_row.id, relation="MENTIONS", confidence=0.8,
                                                 basis=fd["title"][:300]))
        for a in context.auth_events_for(disputed, entities):
            rels.append(EvidenceRelationship(case_id=case.id, from_kind="entity", from_id=a["id"], to_kind="transaction",
                                             to_id=d_row.id, relation="AUTHENTICATES", confidence=0.9 if a["_basis"] == "same reference" else 0.7,
                                             basis=f"{a['value']} ({a['_basis']})"))
        for ev in evidence.values():  # audio/chat statements linked to the case's payment context
            if ev["kind"] == "AUDIO" and ev["status"] in ("PROCESSED", "PARTIAL") and not any(
                    r.from_id == ev["id"] and r.to_id == d_row.id for r in rels):
                if any(x["evidence_id"] == ev["id"] and x["type"] == "CLAIM" for x in entities):
                    rels.append(EvidenceRelationship(case_id=case.id, from_kind="evidence", from_id=ev["id"], to_kind="transaction",
                                                     to_id=d_row.id, relation="CONTEXT_FOR", confidence=0.5,
                                                     basis="Call recording submitted with this dispute discusses a payment-related action"))
    db.add_all(rels)

    for i, e in enumerate(tl):
        db.add(TimelineEvent(case_id=case.id, seq=i, occurred_at=e["occurred_at"], approximate=e["approximate"],
                             time_label=e["time_label"], event_type=e["event_type"], description=e["description"],
                             evidence_ids=e["evidence_ids"], entity_ids=e["entity_ids"], reliability=e["reliability"],
                             simple=e.get("simple"), source_kinds=e.get("source_kinds")))
    for i, f in enumerate(fnd):
        db.add(Finding(case_id=case.id, seq=i, category=f["category"], code=f["code"], title=f["title"][:200],
                       detail=f["detail"], is_anomaly=f["is_anomaly"], is_conflict=f["is_conflict"], sources=f["sources"],
                       data=_jsonable(f["data"]), why=f.get("why"), certainty=f.get("certainty"),
                       certainty_basis=(f.get("certainty_basis") or None) and f["certainty_basis"][:300]))

    linked = {r.from_id for r in rels if r.from_kind == "evidence"} | {r.to_id for r in rels if r.to_kind == "evidence"}
    for ev in db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == case.id)):
        if ev.status in ("PROCESSED", "PARTIAL"):
            if ev.kind == "STRUCTURED":
                _step(ev, "Evidence linked", "done", "Used as history / account-activity context")
            else:
                _step(ev, "Evidence linked", "done" if ev.id in linked else "none",
                      "Linked to the disputed transaction" if ev.id in linked else "Not matched to any transaction")

    counts = {
        "anomalies": sum(f["is_anomaly"] for f in fnd), "conflicts": sum(f["is_conflict"] for f in fnd),
        "missing": sum(f["category"] == "MISSING" for f in fnd),
        "supporting": sum(f["category"] == "SUPPORTING" for f in fnd),
        "contradictory": sum(f["category"] == "CONTRADICTORY" for f in fnd),
        "contextual": sum(f["category"] == "CONTEXTUAL" for f in fnd),
        "evidence": len(evidence), "history_rows": len(history),
    }
    case.claim_type = findings_.claim_type(findings_.claim_profile(case.statement))
    by_id = {x["id"]: x for x in entities}
    candidates = [f for f in fused if f.kind != "HISTORICAL"]
    case.analysis = _jsonable({
        "counts": counts, "completeness": comp, "ml": ml, "summary": summary, "summary_engine": engine,
        "context": ctx_meta, "claim_profile": findings_.claim_profile(case.statement), "modus": modus,
        "key_findings": explain.key_findings(fnd), "victim": explain.victim_view(fnd, evidence, modus),
        "field_status": field_status(disputed, by_id, evidence, fnd) if disputed else {},
        "candidates": len(candidates), "selection_applied": bool(disputed and disputed.selected),
        "languages": {ev["code"]: ev.get("language") for ev in evidence.values() if ev.get("language")},
    })
    case.analyzed_at = datetime.now(timezone.utc)
    audit(db, "EVIDENCE_LINKED", actor, case_id=case.id, result=f"{len(rels)} relationships")
    audit(db, "ANALYSIS_COMPLETED", actor, case_id=case.id,
          result=f"anomalies={counts['anomalies']} conflicts={counts['conflicts']} missing={counts['missing']}")
    db.commit()
    from app.services import crosscase
    crosscase.refresh(db, case)
    return case.analysis


FIELD_KEYS = ["amount", "time", "reference", "beneficiary_vpa", "beneficiary_name", "status", "channel", "account", "bank"]


def field_status(d, by_id: dict, evidence: dict, fnd: list[dict]) -> dict:
    """Reliability state per disputed-transaction field: CONFIRMED / SINGLE_SOURCE / NEEDS_REVIEW / APPROXIMATE /
    PARTIAL / CONFLICT / NOT_FOUND — with the reason. Nothing is filled in when the evidence does not contain it."""
    from app.services.analysis.timeline import SOURCE_KIND
    conflicts = {f["data"].get("field") for f in fnd if f["code"].startswith("SOURCE_CONFLICT")}
    out = {}
    for k in FIELD_KEYS:
        vals = d.fields.get(k, [])
        if k == "time" and not vals and d.fields.get("time_of_day"):
            out[k] = {"state": "PARTIAL", "label": "Time found — date unavailable"}
            continue
        if not vals:
            out[k] = {"state": "NOT_FOUND", "label": "Not found in submitted evidence"}
            continue
        srcs = list(dict.fromkeys(v["evidence_id"] for v in vals))
        ents = [by_id.get(v.get("entity_id")) for v in vals if by_id.get(v.get("entity_id"))]
        review = [e for e in ents if e["attrs"].get("needs_review") or e["attrs"].get("unlabelled_12_digit")
                  or e["attrs"].get("ocr_symbol_misread") or e["confidence"] < 0.6]
        if k in conflicts:
            out[k] = {"state": "CONFLICT", "label": "Evidence conflict — sources disagree"}
        elif review and len(srcs) < 2:
            e = review[0]
            why = e["attrs"].get("needs_review") or ("Unlabelled 12-digit number — may be a UTR" if e["attrs"].get(
                "unlabelled_12_digit") else "Low-confidence text extraction")
            out[k] = {"state": "NEEDS_REVIEW", "label": f"Needs review — {why}"}
        elif k == "time" and all(v.get("precision") != "EXACT" for v in vals):
            out[k] = {"state": "APPROXIMATE", "label": "Approximate — " + (vals[0].get("precision") or "").replace("_", " ").lower()}
        elif len(srcs) >= 2:
            out[k] = {"state": "CONFIRMED", "label": f"Confirmed by {len(srcs)} sources"}
        else:
            from app.services.analysis.explain import lc
            kind = lc(SOURCE_KIND.get(evidence[srcs[0]]["subtype"], "evidence")) if srcs[0] in evidence else "evidence"
            out[k] = {"state": "SINGLE_SOURCE", "label": f"Extracted from {kind}"}
    return out


def _jsonable(o):
    if isinstance(o, dict):
        return {k: _jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_jsonable(v) for v in o]
    if isinstance(o, datetime):
        return o.isoformat()
    if hasattr(o, "isoformat"):
        return o.isoformat()
    return o
