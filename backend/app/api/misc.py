from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import demo
from app.api.deps import current_account, require_api_key, roles
from app.models import Account
from app.config import get_settings
from app.db import get_db
from app.graph.network import graph
from app.ml.model import model
from app.models import AuditLog, Beneficiary, RiskSignal, Transaction, User
from app.services import transactions as txsvc
from app.services.audio import stt
from app.services.demo_case import load_demo
from app.services.ocr import engine as ocr

router = APIRouter(prefix="/api/v1")


# ------------------------------------------------------------------ system & demo

@router.get("/system/capabilities", tags=["System"], summary="What this server can actually do right now")
def capabilities(_: Account = Depends(current_account)):
    s = get_settings()
    st = stt.status()
    return {
        "ocr": {"available": ocr.available(), "engine": "tesseract", "languages": ocr.languages()},
        "speech_to_text": {"engine": st["engine"], "loaded": st["loaded"], "error": st["error"],
                           "enabled": s.stt_engine.lower() not in ("none", "off", "disabled")},
        "llm_summary": {"configured": bool(s.anthropic_api_key), "fallback": "deterministic structured summary"},
        "ml": {"model": "IsolationForest", "min_history_rows": s.ml_min_history},
        "limits": {"max_upload_mb": s.max_upload_mb, "max_audio_mb": s.max_audio_mb, "max_files_per_case": s.max_files_per_case},
    }


@router.post("/demo/load", tags=["Demo"], status_code=201,
             summary="Demo customer accounts: create the SYNTHETIC example case and run it through the real pipeline")
def demo_load(db: Session = Depends(get_db), acc: Account = Depends(roles("VICTIM"))):
    if not acc.is_demo:
        raise HTTPException(403, "The synthetic example case is only available to demo accounts.")
    c = load_demo(db, acc)
    return {"id": c.id, "ref": c.ref, "is_synthetic": True}


# ------------------------------------------------------------------ real-time risk module (monitoring)

@router.get("/alerts", tags=["Risk API"])
def alerts(db: Session = Depends(get_db), _: str = Depends(require_api_key), limit: int = 50):
    t = get_settings().thresholds
    rows = db.scalars(select(Transaction).options(selectinload(Transaction.signals))
                      .where(Transaction.is_historical.is_(False), Transaction.risk_score >= t.high)
                      .order_by(Transaction.created_at.desc()).limit(limit)).all()
    return [txsvc.to_out(r).model_dump() for r in rows]


@router.get("/analytics", tags=["Risk API"])
def analytics(db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    live = select(Transaction).where(Transaction.is_historical.is_(False)).subquery()
    by_decision = dict(db.execute(select(live.c.decision, func.count()).group_by(live.c.decision)).all())
    lat = sorted(x for x in db.scalars(select(live.c.latency_ms)) if x is not None)
    p = (lambda q: round(lat[min(len(lat) - 1, int(q * len(lat)))], 2) if lat else None)
    top = db.execute(select(RiskSignal.type, func.count()).join(Transaction).where(Transaction.is_historical.is_(False))
                     .group_by(RiskSignal.type).order_by(func.count().desc()).limit(8)).all()
    return {"transactions_checked": sum(by_decision.values()), "by_decision": by_decision,
            "latency_ms": {"p50": p(0.5), "p95": p(0.95), "max": lat[-1] if lat else None},
            "top_signals": [{"type": t, "count": c} for t, c in top],
            "model": {"version": model.version, "feature_importance": model.importances()},
            "graph": {"nodes": graph.g.number_of_nodes(), "edges": graph.g.number_of_edges()}}


@router.get("/network/flagged", tags=["Risk API"])
def flagged_network(db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    seeds = [f"vpa:{b.vpa}" for b in db.scalars(select(Beneficiary).where(Beneficiary.flagged_fraud.is_(True)))]
    return graph.subgraph(seeds, radius=2)


@router.get("/audit", tags=["Risk API"])
def audit_log(db: Session = Depends(get_db), _: str = Depends(require_api_key), transaction_id: str | None = None,
              limit: int = 100):
    q = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(min(limit, 500))
    if transaction_id:
        q = q.where(AuditLog.transaction_id == transaction_id)
    return [{"at": a.created_at, "actor": a.actor, "action": a.action, "transaction_id": a.transaction_id,
             "result": a.result} for a in db.scalars(q)]


@router.get("/risk-users", tags=["Risk API"])
def users(db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    return [{"ref": u.ref, "name": u.name, "vpa": u.vpa} for u in db.scalars(select(User).order_by(User.ref))]


@router.get("/config/policy", tags=["Risk API"])
def policy(_: str = Depends(require_api_key)):
    s = get_settings()
    return {"thresholds": s.thresholds.model_dump(), "policy": s.policy.model_dump(), "weights": s.weights.model_dump()}


@router.get("/demo/risk-scenarios", tags=["Risk API"])
def scenarios(_: str = Depends(require_api_key)):
    return demo.scenarios()


@router.post("/demo/reset-risk-data", tags=["Risk API"], summary="Re-seed the synthetic risk dataset (dev/demo only)")
def reset(_: str = Depends(require_api_key)):
    if get_settings().env not in ("dev", "demo"):
        raise HTTPException(403, "Disabled outside dev/demo")
    from app.db import SessionLocal
    from app.seed import reseed_risk
    with SessionLocal() as db:
        reseed_risk(db)
        graph.rebuild(db)
    return {"status": "reset"}
