"""Dispute case lifecycle."""
from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Case, EvidenceFile, ExtractedEntity, Transaction, uid
from app.services.analysis.findings import claim_profile, claim_type
from app.services.audit import audit
from app.services.ingest import _next_seq, _step


def _ref(db: Session, synthetic: bool) -> str:
    year = datetime.now(timezone.utc).year
    prefix = f"{'DEMO' if synthetic else 'UPI'}-{year}-"
    refs = db.scalars(select(Case.ref).where(Case.ref.like(f"{prefix}%"))).all()
    n = max([int(r.rsplit("-", 1)[1]) for r in refs if r.rsplit("-", 1)[1].isdigit()] or [0])
    return f"{prefix}{n + 1:04d}"


def create(db: Session, statement: str, approx_date: date | None, claimed_amount: float | None, actor: str,
           synthetic: bool = False, owner=None, bank_org: str | None = None, status: str = "DRAFT") -> Case:
    now = datetime.now(timezone.utc)
    case = Case(ref=_ref(db, synthetic), statement=statement.strip(), approx_date=approx_date, claimed_amount=claimed_amount,
                status=status, is_synthetic=synthetic, claim_type=claim_type(claim_profile(statement)),
                owner_id=owner.id if owner else None, bank_org=bank_org, created_at=now, last_activity_at=now,
                submitted_at=now if status != "DRAFT" else None)
    db.add(case)
    db.flush()
    audit(db, "CASE_CREATED", actor, case_id=case.id, result=case.ref + (" (synthetic)" if synthetic else ""),
          actor_id=owner.id if owner else None, actor_role=owner.role if owner else None)
    db.commit()
    return case


def create_from_risk_transaction(db: Session, txn: Transaction, statement: str, actor: str) -> Case:
    """Bridge from the real-time risk API: the platform's own record of the payment becomes evidence E1."""
    from app.services.accounts import DEFAULT_BANK
    case = create(db, statement, txn.created_at.date(), txn.amount, actor, bank_org=DEFAULT_BANK, status="SUBMITTED")
    case.linked_risk_txn_id = txn.id
    rec = {
        "record_type": "UPI_SENTINEL_RISK_RECORD", "transaction_ref": txn.ref, "amount": txn.amount,
        "initiated_at": txn.created_at.isoformat(), "beneficiary_vpa": txn.beneficiary.vpa, "beneficiary_name": txn.beneficiary.name,
        "device": txn.device_ref, "ip": txn.ip, "risk_score": txn.risk_score, "risk_level": txn.risk_level, "decision": txn.decision,
        "signals": [s.description for s in txn.signals], "warning_shown_at": txn.warning_shown_at.isoformat() if txn.warning_shown_at else None,
        "user_decision": txn.user_decision, "user_decision_at": txn.user_decision_at.isoformat() if txn.user_decision_at else None,
    }
    data = json.dumps(rec, indent=2, ensure_ascii=False).encode()
    folder = get_settings().storage_dir / "cases" / case.id
    folder.mkdir(parents=True, exist_ok=True)
    eid = uid()
    path = folder / f"{eid}.json"
    with open(path, "xb") as fh:
        fh.write(data)
    os.chmod(path, 0o440)
    ev = EvidenceFile(id=eid, case_id=case.id, seq=_next_seq(db, case.id), kind="SYSTEM", subtype="SYSTEM_RECORD",
                      original_name=f"risk_record_{txn.ref}.json", storage_path=str(path), mime="application/json",
                      size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), source="system", status="PROCESSED",
                      method="SYSTEM", text=data.decode(), steps=[], processed_at=datetime.now(timezone.utc))
    for n in ("File received", "File type detected", "Content extracted", "Entities identified", "Transaction information found"):
        _step(ev, n, "done", "Platform record of the risk check" if n == "Content extracted" else None)
    db.add(ev)
    db.flush()
    from app.services.integrity import record_hash
    record_hash(db, ev)
    t = txn.created_at if txn.created_at.tzinfo else txn.created_at.replace(tzinfo=timezone.utc)
    common = {"case_id": case.id, "evidence_id": eid, "confidence": 1.0, "method": "SYSTEM", "locator": "record"}
    db.add_all([
        ExtractedEntity(type="AMOUNT", value=f"₹{txn.amount:,.2f}", normalized=f"{txn.amount:.2f}", **common, attrs={}),
        ExtractedEntity(type="DATETIME", value=t.isoformat(), normalized=t.isoformat(), occurred_at=t, time_precision="EXACT", **common, attrs={}),
        ExtractedEntity(type="TXN_ID", value=txn.ref, normalized=txn.ref.upper(), **common, attrs={}),
        ExtractedEntity(type="UPI_ID", value=txn.beneficiary.vpa, normalized=txn.beneficiary.vpa, **common, attrs={}),
        ExtractedEntity(type="PAYEE", value=txn.beneficiary.name, normalized=txn.beneficiary.name.lower(), **common, attrs={}),
        ExtractedEntity(type="DEVICE", value=txn.device_ref or "unknown", normalized=(txn.device_ref or "").lower(), **common, attrs={}),
    ])
    if txn.user_decision_at:
        ud = txn.user_decision_at if txn.user_decision_at.tzinfo else txn.user_decision_at.replace(tzinfo=timezone.utc)
        db.add(ExtractedEntity(type="ACCOUNT_EVENT", value=f"User {txn.user_decision.replace('_', ' ').lower()} (risk {txn.risk_score}/100)",
                               normalized="AUTH_SUCCESS" if txn.user_decision == "PROCEEDED_AFTER_WARNING" else "OTHER",
                               occurred_at=ud, time_precision="EXACT", **common,
                               attrs={"event": "AUTH_SUCCESS" if txn.user_decision == "PROCEEDED_AFTER_WARNING" else "OTHER",
                                      "device": txn.device_ref, "reference": txn.ref, "detail": "Confirmed after fraud warning"}))
    audit(db, "SYSTEM_RECORD_ATTACHED", actor, case_id=case.id, transaction_id=txn.id, evidence_id=eid)
    db.commit()
    return case
