from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import require_api_key
from app.db import get_db
from app.models import Transaction
from app.schemas import DecisionRequest, RiskCheckResponse, TransactionCheckRequest, TransactionOut
from app.services import transactions as svc

router = APIRouter(prefix="/api/v1/transactions", tags=["System 1 — Risk"])


@router.post("/check", response_model=RiskCheckResponse,
             summary="Score a payment before authorisation (called by PSP app / issuer bank)")
def check(req: TransactionCheckRequest, db: Session = Depends(get_db), actor: str = Depends(require_api_key)):
    try:
        return svc.check(db, req, actor)
    except svc.NotFound as e:
        raise HTTPException(404, str(e))


@router.post("/{txn_id}/decision", response_model=TransactionOut,
             summary="Record the user's choice after a warning (CANCEL / PROCEED)")
def decision(txn_id: str, req: DecisionRequest, db: Session = Depends(get_db), actor: str = Depends(require_api_key)):
    try:
        return svc.to_out(svc.decide(db, txn_id, req.action, actor), with_signals=True)
    except svc.NotFound as e:
        raise HTTPException(404, str(e))
    except svc.Conflict as e:
        raise HTTPException(409, str(e))


@router.get("", response_model=list[TransactionOut])
def list_transactions(
    db: Session = Depends(get_db), _: str = Depends(require_api_key),
    limit: int = Query(50, le=500), include_history: bool = False,
    min_score: int | None = Query(None, ge=0, le=100), user_ref: str | None = None,
):
    q = select(Transaction).options(selectinload(Transaction.signals), selectinload(Transaction.user),
                                    selectinload(Transaction.beneficiary))
    if not include_history:
        q = q.where(Transaction.is_historical.is_(False))
    if min_score is not None:
        q = q.where(Transaction.risk_score >= min_score)
    rows = db.scalars(q.order_by(Transaction.created_at.desc()).limit(limit)).all()
    if user_ref:
        rows = [r for r in rows if r.user.ref == user_ref]
    return [svc.to_out(t) for t in rows]


@router.get("/{txn_id}", response_model=TransactionOut)
def get_transaction(txn_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    try:
        return svc.to_out(svc.get(db, txn_id), with_signals=True)
    except svc.NotFound as e:
        raise HTTPException(404, str(e))
