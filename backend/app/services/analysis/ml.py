"""Isolation Forest over the customer's own transaction history.

Runs only when enough history was supplied (config: ml_min_history). Otherwise it returns an explicit
"unavailable" result with the reason — no score is ever fabricated.
"""
from __future__ import annotations

import math
from collections import Counter

import numpy as np
from sklearn.ensemble import IsolationForest

from app.config import get_settings
from app.services.extraction.entities import IST


def _ben(f) -> str | None:
    return (f.beneficiary_vpa or f.beneficiary or "").lower() or None


def _features(amount, hour, ben, freq: Counter, n: int, use_hour: bool) -> list[float]:
    v = [math.log1p(amount), (freq.get(ben, 0) / n) if ben else 0.0]
    if use_hour:
        v += [math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24)]
    return v


def assess(disputed, history: list) -> dict:
    need = get_settings().ml_min_history
    hist = [h for h in history if h.amount]
    if disputed is None or not disputed.amount:
        return {"available": False, "reason": "No disputed transaction amount could be established from the evidence."}
    if len(hist) < need:
        return {"available": False, "reason": f"Insufficient historical transaction data ({len(hist)} rows supplied; "
                                              f"at least {need} needed).", "history_rows": len(hist)}
    use_hour = sum(1 for h in hist if h.occurred_at and h.precision == "EXACT") >= need and \
        disputed.occurred_at is not None and disputed.precision in ("EXACT", "TIME_ONLY")
    freq = Counter(_ben(h) for h in hist if _ben(h))
    n = len(hist)
    x = np.array([_features(h.amount, h.occurred_at.astimezone(IST).hour if h.occurred_at else 12, _ben(h), freq, n, use_hour)
                  for h in hist])
    model = IsolationForest(n_estimators=200, contamination="auto", random_state=42).fit(x)
    d_hour = disputed.occurred_at.astimezone(IST).hour if disputed.occurred_at else 12
    xd = np.array([_features(disputed.amount, d_hour, _ben(disputed), freq, n, use_hour)])
    s_hist = model.score_samples(x)
    s_d = float(model.score_samples(xd)[0])
    more_anomalous_than = float((s_hist > s_d).mean())
    names = ["log(amount)", "beneficiary frequency"] + (["hour (sin)", "hour (cos)"] if use_hour else [])
    mu, sd = x.mean(axis=0), x.std(axis=0) + 1e-9
    devs = sorted(({"feature": nme, "z": round(float((xd[0][i] - mu[i]) / sd[i]), 2)} for i, nme in enumerate(names)),
                  key=lambda d: -abs(d["z"]))
    return {
        "available": True, "model": "IsolationForest(n_estimators=200, contamination='auto')",
        "history_rows": n, "features": names, "anomaly_score": round(-s_d, 4),
        "is_outlier": bool(model.predict(xd)[0] == -1),
        "more_anomalous_than_pct": round(100 * more_anomalous_than, 1),
        "top_deviations": devs[:3],
        "note": "Score is relative to this customer's supplied history only. Higher = more unusual.",
    }
