"""Fraud probability model.

Trained on a deterministic SYNTHETIC dataset (no real customer data). The generator encodes
domain priors (fraud skews to new beneficiaries/devices, odd hours, large amount jumps, mule
proximity). In production you would retrain on labelled bank data; the interface stays the same.
"""
from __future__ import annotations

import threading

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier

FEATURE_NAMES = [
    "log_amount_ratio", "new_beneficiary", "new_device", "beneficiary_age_norm", "hour_unusual",
    "velocity_10m", "fan_in", "network_score", "log_distance_km", "is_aeps",
]


def synthetic_dataset(n: int = 6000, seed: int = 42) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    n_fraud = n // 4
    n_legit = n - n_fraud

    def block(m: int, fraud: bool) -> np.ndarray:
        aeps = rng.random(m) < (0.25 if fraud else 0.1)
        ratio = rng.lognormal(mean=1.6 if fraud else -0.6, sigma=0.9, size=m)
        new_b = rng.random(m) < (0.85 if fraud else 0.12)
        new_d = rng.random(m) < (0.6 if fraud else 0.04)
        age = np.where(new_b, rng.uniform(0, 0.05 if fraud else 1.0, m), rng.uniform(0.05, 1.0, m))
        hour = rng.random(m) < (0.45 if fraud else 0.06)
        vel = rng.poisson(2.0 if fraud else 0.2, m)
        fan = rng.poisson(6 if fraud else 1.0, m)
        net = np.where(rng.random(m) < (0.55 if fraud else 0.03), rng.choice([0.45, 0.65, 0.85, 1.0], m), 0.0)
        dist = np.where(aeps, rng.lognormal(5.0 if fraud else 1.5, 1.0, m), rng.lognormal(1.0, 1.0, m))
        return np.column_stack([np.log1p(ratio), new_b, new_d, age, hour, np.minimum(vel, 10),
                                np.minimum(fan, 50), net, np.log1p(dist), aeps]).astype(float)

    x = np.vstack([block(n_legit, False), block(n_fraud, True)])
    y = np.concatenate([np.zeros(n_legit), np.ones(n_fraud)])
    flip = rng.random(n) < 0.02  # label noise so the model doesn't become a lookup table
    y[flip] = 1 - y[flip]
    return x, y


class FraudModel:
    def __init__(self) -> None:
        self._clf: GradientBoostingClassifier | None = None
        self._lock = threading.Lock()
        self.version = "gbdt-synthetic-v1"

    def load(self) -> None:
        with self._lock:
            if self._clf is None:
                x, y = synthetic_dataset()
                clf = GradientBoostingClassifier(n_estimators=120, max_depth=3, learning_rate=0.1, random_state=7)
                clf.fit(x, y)
                self._clf = clf

    def predict(self, vector: list[float]) -> float:
        if self._clf is None:
            self.load()
        assert self._clf is not None
        return float(self._clf.predict_proba(np.asarray([vector]))[0, 1])

    def importances(self) -> dict[str, float]:
        if self._clf is None:
            self.load()
        assert self._clf is not None
        return dict(zip(FEATURE_NAMES, map(float, self._clf.feature_importances_)))


model = FraudModel()
