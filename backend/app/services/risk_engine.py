"""System 1 — real-time risk engine. Deterministic rules + ML + network score. No LLM, no OCR."""
from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings
from app.ml.model import model
from app.services.features import Features


@dataclass
class Signal:
    type: str
    severity: str
    description: str
    weight: float
    evidence: dict


@dataclass
class RiskResult:
    risk_score: int
    risk_level: str
    decision: str
    signals: list[Signal]
    model_score: float
    rule_score: float
    network_score: float

    @property
    def can_override(self) -> bool:
        s = get_settings()
        return self.decision in ("VERIFY", "WARN") or (self.decision == "BLOCK" and s.policy.allow_block_override)


def _inr(x: float) -> str:
    return f"₹{x:,.0f}"


def rule_signals(f: Features) -> list[Signal]:
    s: list[Signal] = []

    if f.beneficiary_flagged:
        s.append(Signal("KNOWN_FRAUD_BENEFICIARY", "CRITICAL",
                        "Recipient is on the fraud watch-list", 0.5,
                        {"reason": f.beneficiary_flag_reason}))

    aeps = f.channel == "AEPS"  # for AePS the "beneficiary"/"device" is the agent terminal; handled below

    if f.is_new_beneficiary and not aeps:
        s.append(Signal("NEW_BENEFICIARY", "HIGH", "First payment to this recipient", 0.20, {}))
        if f.beneficiary_age_days is not None and f.beneficiary_age_days < 7:
            s.append(Signal("RECENTLY_CREATED_BENEFICIARY", "MEDIUM",
                            f"Recipient account first seen {f.beneficiary_age_days:.0f} day(s) ago", 0.10,
                            {"age_days": round(f.beneficiary_age_days, 1)}))

    if f.is_new_device and not aeps:
        s.append(Signal("NEW_DEVICE", "HIGH", "Transaction originated from a previously unseen device", 0.20,
                        {"device_shared_with_users": f.device_users}))

    if f.hist_count >= 3:
        if f.amount_ratio >= 3 and f.amount >= 5000:
            s.append(Signal("AMOUNT_ANOMALY", "HIGH",
                            f"{_inr(f.amount)} is {f.amount_ratio:.0f}x the user's largest payment in 90 days "
                            f"(typical {_inr(f.hist_mean)})", 0.25,
                            {"amount": f.amount, "hist_mean": round(f.hist_mean, 2), "hist_max": f.hist_max}))
        elif f.amount_ratio >= 1.5 and f.amount >= 2000:
            s.append(Signal("AMOUNT_ABOVE_NORMAL", "MEDIUM",
                            f"Amount is above the user's usual range (max {_inr(f.hist_max)})", 0.10,
                            {"amount": f.amount, "hist_max": f.hist_max}))
    elif f.amount >= 20000:
        s.append(Signal("NO_HISTORY_LARGE_AMOUNT", "MEDIUM", "Large amount with little payment history", 0.10, {}))

    if f.hour_unusual:
        s.append(Signal("UNUSUAL_TIME", "MEDIUM",
                        f"Payment at {f.hour_ist:02d}:00 IST, outside the user's normal hours", 0.10,
                        {"hour_ist": f.hour_ist, "usual_hours": sorted(f.usual_hours)}))

    if f.velocity_10m >= 3:
        s.append(Signal("VELOCITY", "HIGH", f"{f.velocity_10m} payment attempts in the last 10 minutes", 0.15,
                        {"count_10m": f.velocity_10m}))

    if f.fan_in >= 5:
        s.append(Signal("BENEFICIARY_FAN_IN", "MEDIUM",
                        f"Recipient receives money from {f.fan_in} different users — common mule pattern", 0.10,
                        {"distinct_senders": f.fan_in}))

    if f.network_score >= 0.45 and not f.beneficiary_flagged:
        hops = max(len(f.network_path) - 1, 0)
        sev = "HIGH" if f.network_score >= 0.65 else "MEDIUM"
        s.append(Signal("NETWORK_RISK", sev,
                        f"Recipient is {hops} hop(s) from a known fraud account", 0.15,
                        {"path": f.network_path, "network_score": f.network_score}))

    if f.channel == "AEPS":
        if f.distance_km is not None and f.distance_km > 100:
            s.append(Signal("AEPS_LOCATION_ANOMALY", "HIGH",
                            f"AePS withdrawal {f.distance_km:,.0f} km from the customer's home location", 0.25,
                            {"distance_km": round(f.distance_km, 1)}))
        if f.is_new_beneficiary:
            # for AePS the "beneficiary" is the agent terminal
            s.append(Signal("AEPS_NEW_TERMINAL", "MEDIUM", "Customer has never transacted at this AePS terminal", 0.10, {}))
        if f.amount >= 10000:
            s.append(Signal("AEPS_HIGH_WITHDRAWAL", "MEDIUM", f"High-value AePS cash withdrawal ({_inr(f.amount)})", 0.15,
                            {"amount": f.amount}))
    return s


def level_for(score: int, settings: Settings) -> str:
    t = settings.thresholds
    if score >= t.critical:
        return "CRITICAL"
    if score >= t.high:
        return "HIGH"
    if score >= t.medium:
        return "MEDIUM"
    return "LOW"


def evaluate(f: Features, settings: Settings | None = None) -> RiskResult:
    settings = settings or get_settings()
    signals = rule_signals(f)
    rule_score = min(1.0, sum(sg.weight for sg in signals))
    model_score = model.predict(f.vector())
    network_score = 1.0 if f.beneficiary_flagged else f.network_score
    w = settings.weights
    raw = w.rule * rule_score + w.model * model_score + w.network * network_score
    # A watch-listed recipient is never below CRITICAL, regardless of the blend.
    score = int(round(100 * raw))
    if f.beneficiary_flagged:
        score = max(score, settings.thresholds.critical)
    score = max(0, min(100, score))
    level = level_for(score, settings)
    decision = getattr(settings.policy, level)
    signals.sort(key=lambda s: -s.weight)
    return RiskResult(score, level, decision, signals, round(model_score, 4), round(rule_score, 4),
                      round(network_score, 4))
