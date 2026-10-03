"""Report data assembly (always from the current case state), versioning and the structured export.

Audiences:  VICTIM (plain language) · BANK (detailed investigation) · CYBER (investigation + bank work +
related cases + network + structured export) · EXPORT (structured fields for manual entry / integration).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import (Account, AuditLog, Case, CaseAction, CaseStatusOption, CaseTransaction, EvidenceFile,
                        EvidenceHash, EvidenceRequest, ExtractedEntity, Finding, InvestigatorNote, Report, ReportVersion,
                        TimelineEvent, VictimProfile)
from app.services import crosscase, lifecycle
from app.services.analysis.timeline import SOURCE_KIND
from app.services.audit import audit

NA = "Not available in submitted evidence"
EXPORT_LABEL = ("Structured export for manual entry / integration. This is not an official NCRP / CFCFRMS submission; "
                "no direct integration with government systems exists in this deployment.")


def _txn(t: CaseTransaction | None) -> dict | None:
    if not t:
        return None
    tod = (t.fields or {}).get("time_of_day") or []
    return {"id": t.id, "kind": t.kind, "amount": t.amount, "occurred_at": t.occurred_at, "time_precision": t.time_precision,
            "time_of_day": tod[0]["value"] if tod else None, "reference": t.reference, "beneficiary": t.beneficiary,
            "beneficiary_vpa": t.beneficiary_vpa, "status": t.status, "channel": t.channel, "device": t.device,
            "fields": t.fields, "sources": t.sources, "match_basis": t.match_basis, "match_confidence": t.match_confidence}


def option_labels(db: Session, org: str | None) -> dict[tuple[str, str], str]:
    q = select(CaseStatusOption).where((CaseStatusOption.org.is_(None)) | (CaseStatusOption.org == org))
    return {(o.category, o.code): o.label for o in db.scalars(q)}


def notes_visible(db: Session, case: Case, role: str) -> list[InvestigatorNote]:
    if role == "VICTIM":
        return []
    q = select(InvestigatorNote).where(InvestigatorNote.case_id == case.id).order_by(InvestigatorNote.created_at)
    notes = db.scalars(q).all()
    if role == "BANK":
        notes = [n for n in notes if (n.visibility or "BANK_AND_CYBER") == "BANK_AND_CYBER"]
    return notes


def next_steps(case: Case, d: dict | None, findings: list[Finding], evidence: list[EvidenceFile], related: list[dict],
               phones: list[str]) -> list[dict]:
    codes = {f.code for f in findings}
    out = []

    def add(text, basis):
        out.append({"text": text, "basis": basis})
    if "MISSING_REFERENCE" in codes:
        add("Trace the UTR in the bank's switch / UPI records using the amount and time of the payment.", "No reference in evidence")
    if {"MISSING_DEVICE", "MISSING_AUTH_LOGS"} & codes:
        add("Pull device-binding, login and authentication logs for the 48 hours before the payment.", "Device / authentication records missing")
    if d and (d.get("beneficiary_vpa") or d.get("beneficiary")):
        add(f"Request KYC and account statement for beneficiary {d.get('beneficiary_vpa') or d.get('beneficiary')} from the "
            "beneficiary bank, and request a hold on remaining funds.", "Beneficiary identified in evidence")
    for f in findings:
        if f.code.startswith("SOURCE_CONFLICT"):
            add(f"Resolve the evidence conflict ({f.title.split(': ', 1)[-1]}) against the core banking record.", f.title)
    if related:
        add(f"Review the {len(related)} possible related case(s) that share identifiers with this case.", "Cross-case match")
    for p in phones[:3]:
        add(f"Check the contact number {p} through the telecom operator / fraud-reporting channel.", "Number found in communication evidence")
    if any(e.kind == "AUDIO" and e.status in ("UNAVAILABLE", "FAILED") for e in evidence):
        add("Obtain a transcript of the call recording (automatic transcription was not available).", "Audio not transcribed")
    if "AUTH_EVENT_PRESENT" in codes:
        add("Interview the customer about the authentication event recorded for the payment.", "Authentication record present")
    if any(f.code == "MODUS_PATTERN" and "REMOTE" in (f.data or {}).get("modus", "") for f in findings):
        add("Check the customer's device for an active remote-access app session at the time of the payment.", "Remote access pattern")
    if "MISSING_BANK_CONFIRMATION" in codes:
        add("Attach the core-banking debit record for the disputed transaction.", "No bank confirmation in evidence")
    return out


def assemble(db: Session, case: Case, audience: str) -> dict:
    """Everything a report or export needs, from the current database state."""
    evs = db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == case.id).order_by(EvidenceFile.seq)).all()
    codes = {e.id: e.code for e in evs}
    hashes = {h.evidence_id: h for h in db.scalars(select(EvidenceHash).where(EvidenceHash.evidence_id.in_(list(codes) or [""])))}
    d_row = db.scalar(select(CaseTransaction).where(CaseTransaction.case_id == case.id, CaseTransaction.kind == "DISPUTED"))
    others = db.scalars(select(CaseTransaction).where(CaseTransaction.case_id == case.id, CaseTransaction.kind == "RELATED")).all()
    findings = db.scalars(select(Finding).where(Finding.case_id == case.id).order_by(Finding.seq)).all()
    tl = db.scalars(select(TimelineEvent).where(TimelineEvent.case_id == case.id).order_by(TimelineEvent.seq)).all()
    owner = db.get(Account, case.owner_id) if case.owner_id else None
    prof = db.get(VictimProfile, case.owner_id) if case.owner_id else None
    staff = Account(role="CYBER", org=None, id="", name="") if audience in ("CYBER", "EXPORT") else Account(
        role="BANK", org=case.bank_org, id="", name="")
    related = crosscase.related_for(db, case, staff) if audience != "VICTIM" else []
    clusters = crosscase.clusters_for(db, staff, case.is_synthetic, case.id) if audience != "VICTIM" else []
    labels = option_labels(db, case.bank_org)
    ents = db.scalars(select(ExtractedEntity).where(ExtractedEntity.case_id == case.id)).all()
    comm = {e.id for e in evs if (e.subtype or "") not in crosscase.BANK_SUBTYPES}
    phones = sorted({x.normalized for x in ents if x.type == "PHONE" and x.evidence_id in comm and x.normalized})

    ev_rows = []
    for e in evs:
        items = []
        for x in e.entities:
            if x.type in ("AMOUNT", "DATETIME", "UTR", "UPI_REF", "TXN_ID", "UPI_ID", "PAYEE", "PHONE", "URL", "EMAIL") and len(items) < 6:
                items.append(f"{x.type.replace('_', ' ').title()}: {x.value}")
        claims = [x for x in e.entities if x.type == "CLAIM"]
        if claims:
            items.append(f"{len(claims)} statement(s) extracted" + (" from audio" if e.kind == "AUDIO" else ""))
        h = hashes.get(e.id)
        ev_rows.append({"code": e.code, "original_name": e.original_name, "kind": e.kind, "subtype": e.subtype,
                        "type_label": SOURCE_KIND.get(e.subtype or "", e.kind.title()), "uploaded_at": e.uploaded_at,
                        "uploaded_by_role": e.uploaded_by_role, "sha256": e.sha256, "size_bytes": e.size_bytes, "mime": e.mime,
                        "method": e.method, "status": e.status, "error": e.error, "is_synthetic": e.is_synthetic,
                        "key_items": "; ".join(items), "language": (e.language or {}).get("label"),
                        "integrity": (e.integrity or {}).get("label"),
                        "hash_status": {"MATCH": "Original file preserved"}.get(h.last_result if h else "", "Not verified"),
                        "hash_verified_at": h.last_verified_at if h else None})
    actions = db.scalars(select(CaseAction).where(CaseAction.case_id == case.id).order_by(CaseAction.created_at)).all()
    requests = db.scalars(select(EvidenceRequest).where(EvidenceRequest.case_id == case.id).order_by(EvidenceRequest.created_at)).all()
    notes = notes_visible(db, case, "CYBER" if audience in ("CYBER", "EXPORT") else audience)
    a = case.analysis or {}
    d = _txn(d_row)
    return {
        "audience": audience,
        "generated_at": datetime.now(timezone.utc),
        "case": {"id": case.id, "ref": case.ref, "status": case.status, "status_label": lifecycle.label(case.status, "BANK"),
                 "victim_status": lifecycle.label(case.status, "VICTIM"), "created_at": case.created_at,
                 "submitted_at": case.submitted_at, "escalated_at": case.escalated_at, "claim_type": case.claim_type,
                 "statement": case.statement, "approx_date": case.approx_date, "claimed_amount": case.claimed_amount,
                 "is_synthetic": case.is_synthetic, "bank": case.bank_org,
                 "bank_outcome": labels.get(("BANK_OUTCOME", case.bank_outcome or ""), case.bank_outcome),
                 "reversal_status": labels.get(("REVERSAL", case.reversal_status or ""), case.reversal_status),
                 "account_action": labels.get(("ACCOUNT_ACTION", case.account_action or ""), case.account_action)},
        "victim": {"name": owner.name if owner else None, "code": owner.user_code if owner else None,
                   "email": owner.email if owner else None, "phone": prof.phone if prof else None,
                   "city": prof.city if prof else None, "bank": (prof.bank_name if prof else None) or case.bank_org},
        "analysis": a, "disputed": d, "other_transactions": [_txn(t) for t in others], "codes": codes, "evidence": ev_rows,
        "timeline": [{"time_label": t.time_label, "occurred_at": t.occurred_at, "approximate": t.approximate,
                      "event_type": t.event_type, "description": t.description, "simple": t.simple or t.description,
                      "reliability": t.reliability, "source_kinds": t.source_kinds or [],
                      "sources": [{"evidence_id": i, "label": codes.get(i)} for i in t.evidence_ids]} for t in tl],
        "findings": [{"category": f.category, "code": f.code, "title": f.title, "detail": f.detail, "is_anomaly": f.is_anomaly,
                      "is_conflict": f.is_conflict, "sources": f.sources, "data": f.data, "why": f.why, "certainty": f.certainty,
                      "certainty_basis": f.certainty_basis} for f in findings],
        "notes": [{"created_at": n.created_at, "author": n.author, "role": n.author_role, "body": n.body,
                   "visibility": n.visibility, "finding_title": n.finding_title, "assessment": n.assessment} for n in notes],
        "actions": [{"created_at": x.created_at, "role": x.actor_role, "action": x.action, "label": lifecycle.BY_ACTION[x.action].label
                     if x.action in lifecycle.BY_ACTION else x.action.replace("_", " ").capitalize(),
                     "from": x.from_status, "to": x.to_status, "note": x.note, "detail": x.detail,
                     "victim_message": x.victim_message} for x in actions],
        "requests": [{"created_at": r.created_at, "role": r.requested_role, "target": r.target_role, "items": r.items,
                      "message": r.message, "status": r.status, "fulfilled_at": r.fulfilled_at} for r in requests],
        "related": related, "clusters": clusters, "phones": phones,
        "next_steps": next_steps(case, d, findings, evs, related, phones) if audience != "VICTIM" else [],
        "audit": [{"created_at": x.created_at, "action": x.action, "actor": x.actor, "role": x.actor_role, "result": x.result}
                  for x in db.scalars(select(AuditLog).where(AuditLog.case_id == case.id).order_by(AuditLog.created_at))]
        if audience != "VICTIM" else [],
    }


def structured_export(data: dict) -> dict:
    d = data["disputed"] or {}
    fields = d.get("fields") or {}

    def val(v):
        return v if v not in (None, "", []) else NA

    def srcs(key):
        return sorted({data["codes"].get(x["evidence_id"], "?") for x in fields.get(key, [])})
    c, v = data["case"], data["victim"]
    accounts = sorted({str(x["value"]) for x in fields.get("account", [])})
    when = d.get("occurred_at")
    return {
        "export_type": "UPI Sentinel structured cyber-crime export",
        "label": EXPORT_LABEL,
        "generated_at": data["generated_at"].isoformat(),
        "synthetic_demo_data": c["is_synthetic"],
        "case": {"case_id": c["ref"], "investigation_status": c["status_label"], "submitted_at": val(c["submitted_at"] and c["submitted_at"].isoformat()),
                 "escalated_at": val(c["escalated_at"] and c["escalated_at"].isoformat()), "bank": val(c["bank"]),
                 "bank_outcome": val(c["bank_outcome"]), "account_action": val(c["account_action"]),
                 "reversal_status": val(c["reversal_status"])},
        "victim_details": {"name": val(v["name"]), "user_id": val(v["code"]), "email": val(v["email"]), "phone": val(v["phone"]),
                           "city": val(v["city"]), "bank": val(v["bank"])},
        "transaction": {
            "date": val(when and when.astimezone(timezone.utc).isoformat()), "date_precision": d.get("time_precision") or NA,
            "time_of_day_without_date": d.get("time_of_day") or None,
            "amount_inr": val(d.get("amount")), "amount_sources": srcs("amount"),
            "utr_or_reference": val(d.get("reference")), "reference_sources": srcs("reference"),
            "transaction_id": val(next((str(x["value"]) for x in fields.get("reference", []) if not str(x["value"]).isdigit()), None)),
            "channel": val(d.get("channel")), "status": val(d.get("status")),
            "bank_named_in_evidence": val(sorted({str(x["value"]) for x in fields.get("bank", [])})),
            "beneficiary_upi_id": val(d.get("beneficiary_vpa")), "beneficiary_name": val(d.get("beneficiary")),
            "beneficiary_account": NA, "account_numbers_in_evidence": val(accounts),
        },
        "suspect_contact_numbers": val(data["phones"]),
        "complaint_description": c["statement"],
        "fraud_pattern": val([f"{m['strength']}: {m['label']}" for m in (data["analysis"].get("modus") or [])]),
        "timeline": [{"time": t["time_label"], "event": t["description"], "basis": t["reliability"],
                      "sources": [s["label"] for s in t["sources"] if s.get("label")]} for t in data["timeline"]],
        "evidence_references": [{"code": e["code"], "file": e["original_name"], "type": e["type_label"], "sha256": e["sha256"],
                                 "uploaded_at": e["uploaded_at"].isoformat() if e["uploaded_at"] else None,
                                 "processing": e["status"], "integrity": e["hash_status"]} for e in data["evidence"]],
        "related_cases": [{"case_id": r["ref"], "amount_inr": r["amount"], "status": r["status_label"],
                           "shared": [f"{l['type_label']} {l['value']}" for l in r["links"]],
                           "relationship": "Possible related case" if all(l["status"] == "POSSIBLE" for l in r["links"]) else
                           "Linked by investigator"} for r in data["related"]],
        "clusters": [{"identifier": f"{c_['type_label']} {c_['value']}", "cases": c_["case_count"],
                      "total_disputed_inr": c_["total_amount"], "cases_with_known_amount": c_["amount_known_cases"],
                      "time_window_hours": c_["window_hours"]} for c_ in data["clusters"]],
    }


# ------------------------------------------------------------------ versioning

def latest(db: Session, case_id: str, audience: str) -> tuple[Report | None, ReportVersion | None]:
    r = db.scalar(select(Report).where(Report.case_id == case_id, Report.audience == audience))
    v = r and db.scalar(select(ReportVersion).where(ReportVersion.report_id == r.id).order_by(ReportVersion.version.desc()))
    return r, v


def is_stale(case: Case, v: ReportVersion | None, evidence_count: int) -> bool:
    if v is None:
        return True
    a = v.analyzed_at.isoformat() if v.analyzed_at else None
    b = case.analyzed_at.isoformat() if case.analyzed_at else None
    return a != b or v.evidence_count != evidence_count or v.case_status != case.status


def generate(db: Session, case: Case, audience: str, actor: Account) -> ReportVersion:
    from app.services.reporting import pdf
    data = assemble(db, case, audience)
    r, prev = latest(db, case.id, audience)
    n = (prev.version if prev else 0) + 1
    folder = get_settings().storage_dir / "reports" / case.id
    folder.mkdir(parents=True, exist_ok=True)
    kind = "JSON" if audience == "EXPORT" else "PDF"
    path = folder / f"{case.ref}_{audience.lower()}_v{n}.{kind.lower()}"
    if kind == "JSON":
        path.write_text(json.dumps(structured_export(data), indent=2, ensure_ascii=False, default=str))
    else:
        data["version"] = n
        if audience == "CYBER":
            data["export"] = structured_export(data)
        pdf.build(path, data)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    ev_count = len(data["evidence"])
    changes = []
    if prev:
        if prev.evidence_count != ev_count:
            changes.append(f"evidence {prev.evidence_count} → {ev_count}")
        if prev.case_status != case.status:
            changes.append(f"status {lifecycle.label(prev.case_status or '')} → {lifecycle.label(case.status)}")
        if (prev.analyzed_at and prev.analyzed_at.isoformat()) != (case.analyzed_at and case.analyzed_at.isoformat()):
            changes.append("analysis re-run")
    now = datetime.now(timezone.utc)
    if r is None:
        r = Report(case_id=case.id, audience=audience, storage_path=str(path), sha256=digest, version=n, created_at=now)
        db.add(r)
        db.flush()
    r.storage_path, r.sha256, r.version, r.updated_at = str(path), digest, n, now
    v = ReportVersion(report_id=r.id, case_id=case.id, version=n, kind=kind, storage_path=str(path), sha256=digest,
                      created_by=actor.id, evidence_count=ev_count, case_status=case.status, analyzed_at=case.analyzed_at,
                      changes=("; ".join(changes) or ("first version" if n == 1 else "no changes since previous version"))[:500])
    db.add(v)
    audit(db, "REPORT_GENERATED", actor.name, case_id=case.id, result=f"{audience} v{n} sha256={digest[:12]}",
          actor_id=actor.id, actor_role=actor.role)
    db.commit()
    return v
