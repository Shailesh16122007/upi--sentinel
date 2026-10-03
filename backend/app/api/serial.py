"""Role-aware serialisation. What each role receives is decided here, on the server."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (Account, Case, CaseRelationship, CaseTransaction, EvidenceFile, EvidenceHash, EvidenceRequest,
                        ExtractedEntity)
from app.services import integrity, lifecycle
from app.services.reports import _txn, option_labels


def entity(x: ExtractedEntity) -> dict:
    return {"id": x.id, "evidence_id": x.evidence_id, "type": x.type, "value": x.value, "normalized": x.normalized,
            "confidence": x.confidence, "method": x.method, "locator": x.locator, "context": x.context,
            "occurred_at": x.occurred_at, "time_precision": x.time_precision, "attrs": x.attrs or {}}


def evidence(db: Session, e: EvidenceFile, with_entities: bool = True, h: EvidenceHash | None = None) -> dict:
    if h is None:
        h = db.scalar(select(EvidenceHash).where(EvidenceHash.evidence_id == e.id))
    return {"id": e.id, "code": e.code, "kind": e.kind, "subtype": e.subtype, "original_name": e.original_name, "mime": e.mime,
            "size_bytes": e.size_bytes, "sha256": e.sha256, "source": e.source, "is_synthetic": e.is_synthetic,
            "status": e.status, "method": e.method, "text": e.text, "pages": e.pages, "duration_s": e.duration_s,
            "segments": e.segments, "quality": e.quality, "steps": e.steps or [], "error": e.error,
            "user_time_hint": e.user_time_hint, "user_note": e.user_note, "uploaded_at": e.uploaded_at,
            "processed_at": e.processed_at, "uploaded_by_role": e.uploaded_by_role, "language": e.language,
            "image_check": e.integrity, "integrity": integrity.describe(h, e),
            "entities": [entity(x) for x in sorted(e.entities, key=lambda x: (x.locator or "", x.type))] if with_entities else []}


def _count(db, q):
    return db.scalar(q) or 0


def next_action(c: Case, n_evidence: int) -> str:
    return {
        "DRAFT": "Upload your proof" if not n_evidence else "Review and submit your case",
        "EVIDENCE_REQUESTED": "Upload the evidence your bank asked for",
        "SUBMITTED": "No action needed — waiting for the bank",
        "RESOLVED": "Download your report", "CLOSED": "Download your report",
    }.get(c.status, "No action needed")


def summary(db: Session, c: Case, acc: Account) -> dict:
    n = _count(db, select(func.count()).select_from(EvidenceFile).where(EvidenceFile.case_id == c.id))
    busy = _count(db, select(func.count()).select_from(EvidenceFile).where(
        EvidenceFile.case_id == c.id, EvidenceFile.status.in_(["RECEIVED", "PROCESSING"])))
    d = db.scalar(select(CaseTransaction).where(CaseTransaction.case_id == c.id, CaseTransaction.kind == "DISPUTED"))
    a = c.analysis or {}
    target = "VICTIM" if acc.role == "VICTIM" else "BANK" if acc.role == "BANK" else None
    open_req = _count(db, select(func.count()).select_from(EvidenceRequest).where(
        EvidenceRequest.case_id == c.id, EvidenceRequest.status == "OPEN", EvidenceRequest.target_role == target)) if target else 0
    out = {
        "id": c.id, "ref": c.ref, "status": c.status, "status_label": lifecycle.label(c.status, acc.role),
        "statement": c.statement, "approx_date": c.approx_date, "claimed_amount": c.claimed_amount, "is_synthetic": c.is_synthetic,
        "created_at": c.created_at, "submitted_at": c.submitted_at, "escalated_at": c.escalated_at, "analyzed_at": c.analyzed_at,
        "last_update": max([t for t in (c.last_activity_at, c.analyzed_at, c.created_at) if t]),
        "evidence_count": n, "processing": busy, "disputed_amount": d.amount if d else None,
        "disputed_time": d.occurred_at if d else None, "open_requests": open_req, "bank": c.bank_org,
        "completeness": (a.get("completeness") or {}).get("score"),
    }
    if acc.role == "VICTIM":
        labels = option_labels(db, c.bank_org)
        out["next_action"] = next_action(c, n)
        out["reversal_status"] = labels.get(("REVERSAL", c.reversal_status or ""))
        return out
    owner = db.get(Account, c.owner_id) if c.owner_id else None
    labels = option_labels(db, c.bank_org)
    rel = db.scalars(select(CaseRelationship.related_case_id).where(CaseRelationship.case_id == c.id,
                                                                    CaseRelationship.status != "DISMISSED")).all()
    out.update({
        "victim": {"name": owner.name, "code": owner.user_code} if owner else None, "claim_type": c.claim_type,
        "counts": a.get("counts"), "priority": c.priority or "NORMAL", "related_count": len(set(rel)),
        "disputed_reference": d.reference if d else None, "beneficiary": (d.beneficiary_vpa or d.beneficiary) if d else None,
        "bank_outcome": labels.get(("BANK_OUTCOME", c.bank_outcome or ""), c.bank_outcome),
        "account_action": labels.get(("ACCOUNT_ACTION", c.account_action or ""), c.account_action),
        "reversal_status": labels.get(("REVERSAL", c.reversal_status or ""), c.reversal_status),
        "with_cyber": c.escalated_at is not None and c.authority_status == "ACTIVE",
        "modus": [m["label"] for m in (a.get("modus") or [])][:2],
    })
    return out


def full(db: Session, c: Case, acc: Account) -> dict:
    s = summary(db, c, acc)
    txns = db.scalars(select(CaseTransaction).where(CaseTransaction.case_id == c.id, CaseTransaction.kind != "HISTORICAL")).all()
    d = next((t for t in txns if t.kind == "DISPUTED"), None)
    a = c.analysis or {}
    n = s["evidence_count"]
    s.update({"disputed": _txn(d), "transactions": [_txn(t) for t in txns], "tracker": lifecycle.tracker(c, n),
              "selection": c.disputed_selection,
              "allowed_actions": [{"action": t.action, "label": t.label, "to": t.to, "note_required": t.note_required}
                                  for t in lifecycle.allowed(c, acc.role) if t.action not in lifecycle.INDIRECT]})
    if acc.role == "VICTIM":
        s["analysis"] = {"field_status": a.get("field_status"), "victim": a.get("victim"), "candidates": a.get("candidates"),
                         "counts": {"evidence": (a.get("counts") or {}).get("evidence", n)}} if a else None
        s["can_submit"] = c.status == "DRAFT" and n > 0 and not s["processing"]
    else:
        s["analysis"] = a or None
        s["linked_risk_txn_id"] = c.linked_risk_txn_id
        s["dispositions"] = {"bank_outcome": c.bank_outcome, "reversal_status": c.reversal_status,
                             "account_action": c.account_action, "priority": c.priority or "NORMAL"}
    return s
