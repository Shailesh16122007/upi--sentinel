from app.config import Settings
from app.services.features import Features
from app.services.risk_engine import evaluate, level_for, rule_signals
from tests.conftest import H


def feat(**kw) -> Features:
    base = dict(amount=1000, channel="UPI", hour_ist=12, hist_count=40, hist_mean=1000, hist_std=400, hist_max=2000,
                amount_ratio=0.5, amount_z=0, is_new_beneficiary=False, beneficiary_age_days=400,
                beneficiary_flagged=False, beneficiary_flag_reason=None, fan_in=1, is_new_device=False, device_users=1,
                usual_hours={10, 12, 14}, hour_unusual=False, velocity_10m=0)
    base.update(kw)
    return Features(**base)


def types(f):
    return {s.type for s in rule_signals(f)}


def test_clean_transaction_is_low():
    r = evaluate(feat())
    assert r.risk_level == "LOW" and r.decision == "ALLOW" and r.signals == []


def test_new_beneficiary_signal():
    assert "NEW_BENEFICIARY" in types(feat(is_new_beneficiary=True))


def test_new_device_signal():
    assert "NEW_DEVICE" in types(feat(is_new_device=True))


def test_amount_anomaly():
    assert "AMOUNT_ANOMALY" in types(feat(amount=48000, amount_ratio=24))
    assert "AMOUNT_ANOMALY" not in types(feat(amount=1800, amount_ratio=0.9))


def test_velocity_anomaly():
    assert "VELOCITY" in types(feat(velocity_10m=4))


def test_network_risk_and_watchlist():
    assert "NETWORK_RISK" in types(feat(network_score=0.65, network_path=["vpa:a", "vpa:b", "vpa:z"]))
    r = evaluate(feat(beneficiary_flagged=True, beneficiary_flag_reason="x"))
    assert r.risk_level == "CRITICAL"


def test_thresholds_are_configurable():
    s = Settings()
    assert level_for(65, s) == "HIGH"
    s.thresholds.high = 70
    assert level_for(65, s) == "MEDIUM"


def test_policy_is_configurable():
    s = Settings()
    s.policy.HIGH = "BLOCK"
    r = evaluate(feat(is_new_beneficiary=True, is_new_device=True, amount=48000, amount_ratio=24, hour_unusual=True), s)
    assert r.risk_level in ("HIGH", "CRITICAL") and r.decision == "BLOCK"


def test_api_requires_key(client):
    assert client.get("/api/v1/transactions").status_code == 401


def test_demo_scenarios_end_to_end_levels(client, scenarios):
    out = {}
    for sid, s in scenarios.items():
        r = client.post("/api/v1/transactions/check", json=s["payload"], headers=H)
        assert r.status_code == 200, r.text
        out[sid] = r.json()
        assert out[sid]["latency_ms"] < 50
    assert out["001"]["risk_level"] == "LOW" and out["001"]["decision"] == "ALLOW"
    assert out["002"]["risk_level"] == "HIGH" and out["002"]["decision"] == "WARN"
    assert out["003"]["risk_level"] == "CRITICAL" and out["003"]["risk_score"] >= 85
    assert out["004"]["risk_level"] in ("HIGH", "CRITICAL")
    assert any(s["type"].startswith("AEPS_") for s in out["004"]["signals"])
    assert any(s["type"] == "NETWORK_RISK" for s in out["005"]["signals"])


def test_cancel_and_proceed_decisions(client, scenarios):
    r1 = client.post("/api/v1/transactions/check", json=scenarios["002"]["payload"], headers=H).json()
    c = client.post(f"/api/v1/transactions/{r1['transaction_id']}/decision", json={"action": "CANCEL"}, headers=H).json()
    assert c["status"] == "CANCELLED" and c["user_decision"] == "CANCELLED_AFTER_WARNING"
    again = client.post(f"/api/v1/transactions/{r1['transaction_id']}/decision", json={"action": "PROCEED"}, headers=H)
    assert again.status_code == 409

    r2 = client.post("/api/v1/transactions/check", json=scenarios["003"]["payload"], headers=H).json()
    p = client.post(f"/api/v1/transactions/{r2['transaction_id']}/decision", json={"action": "PROCEED"}, headers=H).json()
    assert p["status"] == "COMPLETED" and p["user_decision"] == "PROCEEDED_AFTER_WARNING"
    acts = {a["action"] for a in client.get(f"/api/v1/audit?transaction_id={r2['transaction_id']}", headers=H).json()}
    assert {"RISK_CHECK_CREATED", "WARNING_SHOWN", "USER_PROCEEDED"} <= acts


def test_input_validation(client):
    bad = {"user_ref": "U-101", "beneficiary_vpa": "not-a-vpa", "amount": -5, "device_ref": "x"}
    assert client.post("/api/v1/transactions/check", json=bad, headers=H).status_code == 422
