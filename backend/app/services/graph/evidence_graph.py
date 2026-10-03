"""Evidence graph assembled from the persisted analysis of one case (nothing hard-coded)."""
from __future__ import annotations

from datetime import timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Case, CaseTransaction, EvidenceFile, EvidenceRelationship, ExtractedEntity, TimelineEvent
from app.services.extraction.entities import IST

SUBTYPE_LABEL = {
    "UPI_SCREENSHOT": "UPI screenshot", "BANK_SMS": "Bank SMS", "BANK_SMS_SCREENSHOT": "Bank SMS screenshot",
    "CHAT": "Chat", "CHAT_SCREENSHOT": "Chat screenshot", "CALL_RECORDING": "Call recording", "CALL_LOG": "Call log",
    "BANK_STATEMENT": "Bank statement", "PAYMENT_RECEIPT": "Payment receipt", "COMPLAINT": "Complaint",
    "TXN_HISTORY": "Transaction history", "ACCOUNT_LOG": "Account / device log", "SYSTEM_RECORD": "System record",
}


def _a(d):
    return d if d is None or d.tzinfo else d.replace(tzinfo=timezone.utc)


def _t(d):
    return _a(d).astimezone(IST).strftime("%d %b %I:%M %p") if d else None


def build(db: Session, case: Case) -> dict:
    evs = {e.id: e for e in db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == case.id))}
    txns = db.scalars(select(CaseTransaction).where(CaseTransaction.case_id == case.id)).all()
    rels = db.scalars(select(EvidenceRelationship).where(EvidenceRelationship.case_id == case.id)).all()
    ents = db.scalars(select(ExtractedEntity).where(ExtractedEntity.case_id == case.id)).all()
    tl = db.scalars(select(TimelineEvent).where(TimelineEvent.case_id == case.id).order_by(TimelineEvent.seq)).all()
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    def node(nid, kind, label, details=None, sources=None, ev_ids=None, ent_ids=None):
        if nid not in nodes:
            nodes[nid] = {"id": nid, "kind": kind, "label": label, "details": details or {}, "sources": [],
                          "_ev": set(), "_ent": set()}
        n = nodes[nid]
        n["details"].update(details or {})
        n["_ev"] |= set(ev_ids or [])
        n["_ent"] |= set(ent_ids or [])
        return n

    def edge(a, b, rel, basis=None, conf=None):
        if a in nodes and b in nodes and not any(e["source"] == a and e["target"] == b and e["rel"] == rel for e in edges):
            edges.append({"source": a, "target": b, "rel": rel, "basis": basis, "confidence": conf})

    node("customer", "CUSTOMER", "Customer", {"Statement": case.statement, "Claim type": case.claim_type})

    disputed = next((t for t in txns if t.kind == "DISPUTED"), None)
    for t in txns:
        if t.kind == "HISTORICAL":
            continue
        nid = f"txn:{t.id}"
        label = (f"₹{t.amount:,.0f}" if t.amount else "Transaction") + (" · disputed" if t.kind == "DISPUTED" else "")
        node(nid, "TRANSACTION", label, {"Amount": f"₹{t.amount:,.2f}" if t.amount else None, "Time": _t(t.occurred_at),
                                          "Time precision": t.time_precision, "Reference": t.reference, "Status": t.status,
                                          "Channel": t.channel, "Matched by": t.match_basis}, ev_ids=t.sources)
        edge("customer", nid, "DISPUTES" if t.kind == "DISPUTED" else "ALSO_FOUND")
        ben = t.beneficiary_vpa or t.beneficiary
        if ben:
            bid = f"ben:{ben.lower()}"
            node(bid, "BENEFICIARY", ben, {"VPA": t.beneficiary_vpa, "Name": t.beneficiary}, ev_ids=t.sources)
            edge(nid, bid, "PAID_TO")
    hist = [t for t in txns if t.kind == "HISTORICAL"]
    if hist:
        node("history", "HISTORY", f"History · {len(hist)} txns", {"Rows": len(hist)},
             ev_ids={s for t in hist for s in t.sources})
        edge("customer", "history", "HAS_HISTORY")

    for e in evs.values():
        node(f"ev:{e.id}", "EVIDENCE", f"{e.code} · {SUBTYPE_LABEL.get(e.subtype or '', (e.kind or '').title())}",
             {"File": e.original_name, "Type": e.subtype, "Processing": e.status, "Method": e.method,
              "SHA-256": (e.sha256 or "")[:16] + "…"}, ev_ids=[e.id])

    for r in rels:
        a = f"ev:{r.from_id}" if r.from_kind == "evidence" else None
        b = f"txn:{r.to_id}" if r.to_kind == "transaction" else f"ev:{r.to_id}" if r.to_kind == "evidence" else None
        if r.from_kind == "entity":
            continue
        if a and b:
            edge(a, b, r.relation, r.basis, r.confidence)
    if hist:
        for s in {s for t in hist for s in t.sources}:
            edge(f"ev:{s}", "history", "EVIDENCES")

    window = None
    if disputed and disputed.occurred_at:
        d0 = _a(disputed.occurred_at)
        window = (d0 - timedelta(hours=48), d0 + timedelta(hours=24))
    auth_rel = {r.from_id: r for r in rels if r.from_kind == "entity" and r.relation == "AUTHENTICATES"}
    for x in ents:
        at = _a(x.occurred_at)
        in_win = window is None or (at is not None and window[0] <= at <= window[1])
        if x.type == "ACCOUNT_EVENT" and in_win:
            ev = x.attrs.get("event")
            dev = x.attrs.get("device")
            if ev in ("AUTH_SUCCESS", "AUTH_FAILED", "OTP_VERIFIED"):
                nid = f"auth:{x.id}"
                node(nid, "AUTH_EVENT", f"{ev.replace('_', ' ').title()} {_t(at) or ''}".strip(),
                     {"Event": x.value, "Time": _t(at), "Device": dev, "Reference": x.attrs.get("reference")},
                     ev_ids=[x.evidence_id], ent_ids=[x.id])
                if x.id in auth_rel and disputed:
                    edge(nid, f"txn:{disputed.id}", "AUTHENTICATES", auth_rel[x.id].basis)
            elif ev in ("LOGIN", "LOGIN_FAILED"):
                nid = f"session:{x.id}"
                node(nid, "SESSION", f"{'Failed login' if ev == 'LOGIN_FAILED' else 'Login'} {_t(at) or ''}".strip(),
                     {"Time": _t(at), "IP": x.attrs.get("ip"), "Device": dev}, ev_ids=[x.evidence_id], ent_ids=[x.id])
                edge(nid, "customer", "SESSION_OF")
            else:
                nid = f"acct:{x.id}"
                node(nid, "ACCOUNT_EVENT", f"{ev.replace('_', ' ').title()} {_t(at) or ''}".strip(),
                     {"Event": x.value, "Time": _t(at), "Device": dev, "Detail": x.attrs.get("detail")},
                     ev_ids=[x.evidence_id], ent_ids=[x.id])
                edge(nid, "customer", "ON_ACCOUNT")
            if dev:
                did = f"dev:{dev.lower()}"
                node(did, "DEVICE", dev, {"Device": dev}, ev_ids=[x.evidence_id], ent_ids=[x.id])
                edge(did, nid, "USED_FOR")
            node(f"ev:{x.evidence_id}", "EVIDENCE", "")
            edge(f"ev:{x.evidence_id}", nid, "RECORDS")
        elif x.type in ("PHONE", "URL") and evs.get(x.evidence_id) and evs[x.evidence_id].subtype not in ("BANK_SMS", "BANK_SMS_SCREENSHOT", "UPI_SCREENSHOT"):
            nid = f"comm:{x.normalized}"
            node(nid, "COMMUNICATION", x.value, {"Type": "Phone number" if x.type == "PHONE" else "Link", "Value": x.normalized},
                 ev_ids=[x.evidence_id], ent_ids=[x.id])
            edge(f"ev:{x.evidence_id}", nid, "CONTAINS")
            edge(nid, "customer", "CONTACTED")

    # related timeline events per node
    for n in nodes.values():
        n["events"] = [{"time": t.time_label, "description": t.description} for t in tl
                       if (set(t.evidence_ids or []) & n["_ev"]) or (set(t.entity_ids or []) & n["_ent"])][:8]
        n["sources"] = [{"evidence_id": i, "label": evs[i].code, "name": evs[i].original_name} for i in sorted(n["_ev"], key=lambda i: evs[i].seq) if i in evs]
        n["details"] = {k: v for k, v in n["details"].items() if v not in (None, "")}
        del n["_ev"], n["_ent"]
    return {"nodes": list(nodes.values()), "edges": edges}
