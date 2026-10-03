"""Risk-API demo scenarios: ready-made payloads that go through the REAL /transactions/check pipeline.

Nothing here pre-computes a risk score — the engine decides.
"""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def _last_ist(hour: int, minute: int) -> datetime:
    now = datetime.now(IST)
    t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if t > now:
        t -= timedelta(days=1)
    return t.astimezone(timezone.utc)


def scenarios() -> list[dict]:
    return [
        {
            "id": "001", "title": "Normal payment", "expected": "LOW → ALLOW",
            "story": "Asha pays her usual grocer ₹1,200 from her own phone.",
            "payload": {"user_ref": "U-101", "beneficiary_vpa": "freshmart@okaxis", "beneficiary_name": "FreshMart Grocers",
                        "amount": 1200, "channel": "UPI", "device_ref": "D-ASHA-01"},
        },
        {
            "id": "002", "title": "Suspicious transfer", "expected": "HIGH → WARN",
            "story": "Meena sends ₹25,000 to a never-seen recipient from a new phone at 2:30 AM.",
            "payload": {"user_ref": "U-103", "beneficiary_vpa": "sharma.electronics@okicici",
                        "beneficiary_name": "Sharma Electronics", "amount": 25000, "channel": "UPI",
                        "device_ref": "D-NEW-5C21", "timestamp": _last_ist(2, 30).isoformat()},
        },
        {
            "id": "003", "title": "Fraud after warning", "expected": "CRITICAL → warning, user proceeds",
            "story": "Ravi got a 'KYC expiring' SMS, opened the link, and now pays ₹48,000 to Rahul Traders from an unknown device.",
            "payload": {"user_ref": "U-102", "beneficiary_vpa": "rahultraders@ybl", "beneficiary_name": "Rahul Traders",
                        "amount": 48000, "channel": "UPI", "device_ref": "D-UNKNOWN-7F3A", "ip": "103.21.44.10"},
        },
        {
            "id": "004", "title": "AePS withdrawal far from home", "expected": "HIGH / CRITICAL",
            "story": "₹10,000 AePS cash withdrawal on Lakshmi's Aadhaar at a Jaipur terminal, ~1,700 km from home.",
            "payload": {"user_ref": "U-104", "beneficiary_vpa": "aeps-agent-7731@nsdl",
                        "beneficiary_name": "AePS Agent 7731, Jaipur", "amount": 10000, "channel": "AEPS",
                        "device_ref": "AEPS-T-7731", "lat": 26.91, "lon": 75.79},
        },
        {
            "id": "005", "title": "Mule network", "expected": "Network risk detected",
            "story": "Asha pays a 'KYC refund desk' VPA that forwards money to a watch-listed account.",
            "payload": {"user_ref": "U-101", "beneficiary_vpa": "fastkyc.refund@ibl", "beneficiary_name": "KYC Refund Desk",
                        "amount": 4999, "channel": "UPI", "device_ref": "D-ASHA-01"},
        },
    ]
