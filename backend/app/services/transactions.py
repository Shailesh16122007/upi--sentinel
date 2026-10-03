import time
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.graph.network import graph
from app.models import Beneficiary, Device, RiskSignal, Transaction, User
from app.schemas import RiskCheckResponse, SignalOut, TransactionCheckRequest, TransactionOut
from app.services import features as feat
from app.services.audit import audit
from app.services.risk_engine import evaluate


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


def _next_ref(db: Session) -> str:
    n = db.scalar(select(func.count()).select_from(Transaction)) or 0
    return f"TXN-{10001 + n}"


def check(db: Session, req: TransactionCheckRequest, actor: str) -> RiskCheckResponse:
    t0 = time.perf_counter()
    user = db.scalar(select(User).where(User.ref == req.user_ref))
    if user is None:
        raise NotFound(f"Unknown user {req.user_ref}")
    ts = req.timestamp or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    f = feat.extract(db, user, req.beneficiary_vpa, req.amount, req.channel, req.device_ref, ts, req.lat, req.lon)
    result = evaluate(f)
    decide_ms = (time.perf_counter() - t0) * 1000

    bene = db.scalar(select(Beneficiary).where(Beneficiary.vpa == req.beneficiary_vpa))
    if bene is None:
        bene = Beneficiary(vpa=req.beneficiary_vpa, name=req.beneficiary_name or req.beneficiary_vpa,
                           kind="AEPS_TERMINAL" if req.channel == "AEPS" else "UPI", created_at=ts)
        db.add(bene)
        db.flush()

    if result.decision == "ALLOW":
        status = "COMPLETED"
    elif result.can_override:
        status = "PENDING_USER"
    else:
        status = "BLOCKED"

    txn = Transaction(
        ref=_next_ref(db), user_id=user.id, beneficiary_id=bene.id, channel=req.channel, amount=req.amount,
        device_ref=req.device_ref, ip=req.ip, lat=req.lat, lon=req.lon, note=req.note, created_at=ts,
        status=status, risk_score=result.risk_score, risk_level=result.risk_level, decision=result.decision,
        model_score=result.model_score, rule_score=result.rule_score, network_score=result.network_score,
        latency_ms=round(decide_ms, 2),
        warning_shown_at=ts if result.decision != "ALLOW" else None,
    )
    for s in result.signals:
        txn.signals.append(RiskSignal(type=s.type, severity=s.severity, description=s.description,
                                      weight=s.weight, evidence=s.evidence))
    db.add(txn)
    db.flush()

    audit(db, "RISK_CHECK_CREATED", actor, transaction_id=txn.id,
          result=f"score={result.risk_score} decision={result.decision}")
    if result.decision != "ALLOW":
        audit(db, "WARNING_SHOWN", actor, transaction_id=txn.id, result=result.decision)
    if status == "COMPLETED":
        _complete(db, txn, user)
    db.commit()

    return RiskCheckResponse(
        transaction_id=txn.id, transaction_ref=txn.ref, risk_score=result.risk_score,
        risk_level=result.risk_level, decision=result.decision, status=status,
        can_override=result.can_override,
        signals=[SignalOut(type=s.type, severity=s.severity, description=s.description, weight=s.weight,
                           evidence=s.evidence) for s in result.signals],
        model_score=result.model_score, rule_score=result.rule_score, network_score=result.network_score,
        latency_ms=round(decide_ms, 2),
    )


def _complete(db: Session, txn: Transaction, user: User) -> None:
    if txn.device_ref and not db.scalar(
        select(Device).where(Device.user_id == user.id, Device.ref == txn.device_ref)
    ):
        db.add(Device(ref=txn.device_ref, user_id=user.id, first_seen=txn.created_at, last_seen=txn.created_at))
    bene = db.get(Beneficiary, txn.beneficiary_id)
    graph.record_completed(user.ref, bene.vpa, txn.device_ref)


def decide(db: Session, txn_id: str, action: str, actor: str) -> Transaction:
    txn = get(db, txn_id)
    if txn.status != "PENDING_USER":
        raise Conflict(f"Transaction is {txn.status}; no decision pending")
    now = datetime.now(timezone.utc)
    txn.user_decision_at = now
    if action == "CANCEL":
        txn.status = "CANCELLED"
        txn.user_decision = "CANCELLED_AFTER_WARNING"
        audit(db, "USER_CANCELLED", actor, transaction_id=txn.id)
    else:
        txn.status = "COMPLETED"
        txn.user_decision = "PROCEEDED_AFTER_WARNING"
        audit(db, "USER_PROCEEDED", actor, transaction_id=txn.id, result=f"score={txn.risk_score}")
        _complete(db, txn, txn.user)
    db.commit()
    return txn


def get(db: Session, txn_id: str) -> Transaction:
    txn = db.get(Transaction, txn_id) or db.scalar(select(Transaction).where(Transaction.ref == txn_id))
    if txn is None:
        raise NotFound("Transaction not found")
    return txn


def to_out(t: Transaction, with_signals: bool = False) -> TransactionOut:
    sigs = sorted(t.signals, key=lambda s: -s.weight)
    return TransactionOut(
        id=t.id, ref=t.ref, created_at=t.created_at, channel=t.channel, amount=t.amount,
        user_ref=t.user.ref, user_name=t.user.name, beneficiary_vpa=t.beneficiary.vpa,
        beneficiary_name=t.beneficiary.name, device_ref=t.device_ref, status=t.status,
        risk_score=t.risk_score, risk_level=t.risk_level, decision=t.decision, user_decision=t.user_decision,
        warning_shown_at=t.warning_shown_at, user_decision_at=t.user_decision_at,
        model_score=t.model_score, rule_score=t.rule_score, network_score=t.network_score,
        latency_ms=t.latency_ms, top_reason=sigs[0].description if sigs else None,
        signals=[SignalOut(type=s.type, severity=s.severity, description=s.description, weight=s.weight,
                           evidence=s.evidence or {}) for s in sigs] if with_signals else [],
    )
