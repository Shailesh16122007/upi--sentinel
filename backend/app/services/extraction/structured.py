"""Advanced evidence: CSV/JSON transaction histories and account/device/authentication logs.

Column names vary between banks and apps, so fields are matched by synonyms. Unrecognised rows are
kept in the raw text but produce no entities (no guessing).
"""
from __future__ import annotations

import re
from datetime import datetime

from dateutil import parser as dparser

from app.services.extraction.entities import IST, Ent

SYN = {
    "ts": ["timestamp", "datetime", "date_time", "event_time", "created_at", "txn_time", "transaction_time", "time_stamp"],
    "date": ["date", "txn_date", "transaction_date", "value_date", "posting_date"],
    "time": ["time", "txn_time_only"],
    "amount": ["amount", "amt", "txn_amount", "transaction_amount", "debit", "withdrawal", "withdrawal_amt", "value", "inr"],
    "beneficiary": ["beneficiary", "payee", "to", "to_vpa", "vpa", "receiver", "merchant", "counterparty", "beneficiary_vpa",
                    "payee_vpa", "name", "description", "narration", "remarks", "particulars"],
    "reference": ["utr", "rrn", "ref", "reference", "ref_no", "txn_id", "transaction_id", "upi_ref", "upi_ref_no", "cheque_ref"],
    "status": ["status", "txn_status", "result", "outcome"],
    "channel": ["channel", "mode", "txn_type", "transaction_type", "type", "method"],
    "device": ["device", "device_id", "device_name", "device_model", "handset"],
    "ip": ["ip", "ip_address", "ipaddr", "source_ip"],
    "event": ["event", "event_type", "action", "activity", "log_type", "type"],
    "detail": ["detail", "details", "message", "info", "note", "location"],
}
EVENT_MAP = [
    ("LOGIN_FAILED", r"login.*fail|fail.*login|invalid (password|mpin)"),
    ("LOGIN", r"\blogin\b|\bsign[ -]?in\b|session (start|created)"),
    ("DEVICE_REGISTERED", r"device.*(regist|bind|added|new|link)|(bind|binding|registration)\b|new device"),
    ("SIM_CHANGE", r"\bsim\b.*(change|swap)|sim swap"),
    ("BENEFICIARY_ADDED", r"(beneficiary|payee).*(add|creat|regist)|add.*(beneficiary|payee)"),
    ("OTP_SENT", r"otp.*(sent|generat|request)"),
    ("OTP_VERIFIED", r"otp.*(verif|validat|success)"),
    ("AUTH_FAILED", r"(pin|mpin|auth|biometric).*(fail|incorrect|wrong|invalid)"),
    ("AUTH_SUCCESS", r"(upi pin|mpin|pin|auth|biometric|fingerprint|face).*(success|verified|validated|ok|entered|approved)|authori[sz]ed"),
    ("PASSWORD_CHANGE", r"password.*(change|reset)|(change|reset).*password|mpin.*(change|reset)"),
    ("COLLECT_REQUEST", r"collect request|payment request"),
]


def _get(row: dict, key: str):
    low = {re.sub(r"[\s\-]+", "_", k.lower()): v for k, v in row.items()}
    for k in SYN[key]:
        if k in low and low[k] not in (None, ""):
            return low[k]
    return None


def _ts(row: dict) -> datetime | None:
    raw = _get(row, "ts")
    if raw is None:
        d, t = _get(row, "date"), _get(row, "time")
        raw = f"{d} {t}" if d and t else d
    if raw is None:
        return None
    try:
        if isinstance(raw, (int, float)) and raw > 1e9:
            return datetime.fromtimestamp(raw / (1000 if raw > 1e12 else 1), tz=IST)
        dt = dparser.parse(str(raw), dayfirst=not re.match(r"^\d{4}-", str(raw)))
        return dt if dt.tzinfo else dt.replace(tzinfo=IST)
    except (ValueError, OverflowError):
        return None


def _amount(v) -> float | None:
    if v is None:
        return None
    try:
        return float(re.sub(r"[^\d.\-]", "", str(v)) or "nan")
    except ValueError:
        return None


def _event_type(row: dict) -> str | None:
    raw = _get(row, "event")
    if raw is None:
        return None
    s = str(raw).lower()
    for name, rx in EVENT_MAP:
        if re.search(rx, s):
            return name
    return None


def extract_rows(rows: list[dict]) -> tuple[list[Ent], dict]:
    ents: list[Ent] = []
    stats = {"transactions": 0, "events": 0, "skipped": 0}
    for i, row in enumerate(rows):
        loc = f"row {i + 1}"
        ts = _ts(row)
        ev = _event_type(row)
        amt = _amount(_get(row, "amount"))
        device, ip, ref = _get(row, "device"), _get(row, "ip"), _get(row, "reference")
        prec = "EXACT" if ts and (ts.hour or ts.minute) else ("DATE_ONLY" if ts else "NONE")
        ctx = ", ".join(f"{k}={v}" for k, v in list(row.items())[:8] if not k.startswith("_"))[:300]
        is_event = ev is not None and (amt is None or row.get("_collection") in ("events", "logs"))
        if is_event:
            stats["events"] += 1
            ents.append(Ent("ACCOUNT_EVENT", str(_get(row, "event")), ev, 0.97, loc, ctx, ts, prec,
                            attrs={"event": ev, "device": device, "ip": ip, "reference": str(ref) if ref else None,
                                   "detail": _get(row, "detail"), "status": _get(row, "status"), "amount": amt}))
        elif amt is not None and amt > 0:
            stats["transactions"] += 1
            ben = _get(row, "beneficiary")
            ents.append(Ent("HISTORY_TXN", f"₹{amt:,.2f} → {ben or 'unknown'}", f"{amt:.2f}", 0.97, loc, ctx, ts, prec,
                            attrs={"amount": amt, "beneficiary": str(ben) if ben else None, "reference": str(ref) if ref else None,
                                   "status": _get(row, "status"), "channel": _get(row, "channel"), "device": device}))
        else:
            stats["skipped"] += 1
            continue
        if device:
            ents.append(Ent("DEVICE", str(device), str(device).lower(), 0.97, loc, ctx, ts, prec))
        if ip:
            ents.append(Ent("IP", str(ip), str(ip), 0.97, loc, ctx, ts, prec))
    return ents, stats
