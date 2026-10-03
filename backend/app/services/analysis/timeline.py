"""Chronological timeline built only from times stated in evidence (or clearly-labelled approximations)."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.services.extraction.entities import IST

EVENT_LABEL = {
    "LOGIN": "Account login", "LOGIN_FAILED": "Failed login attempt", "DEVICE_REGISTERED": "Device registered / bound",
    "SIM_CHANGE": "SIM change", "BENEFICIARY_ADDED": "New beneficiary added", "OTP_SENT": "OTP sent",
    "OTP_VERIFIED": "OTP verified", "AUTH_SUCCESS": "Authentication succeeded", "AUTH_FAILED": "Authentication failed",
    "PASSWORD_CHANGE": "Password / PIN changed", "COLLECT_REQUEST": "Collect (payment) request",
}


def label(dt: datetime | None, precision: str) -> str:
    if dt is None:
        return "Time not stated in evidence"
    loc = dt.astimezone(IST)
    s = loc.strftime("%d %b %Y, %I:%M %p")
    return {
        "EXACT": s,
        "TIME_ONLY": f"≈ {s} (time from evidence; date assumed from dispute)",
        "DATE_ONLY": f"{loc.strftime('%d %b %Y')} (time not stated)",
        "USER_HINT": f"≈ {s} (time given by user)",
        "OFFSET": f"≈ {s} (recording start given by user + offset)",
    }.get(precision, s)


def build(case: dict, evidence: dict[str, dict], entities: list[dict], fused: list) -> list[dict]:
    ev_out: list[dict] = []

    def add(dt, precision, etype, desc, ev_ids, ent_ids, reliability):
        ev_out.append({"occurred_at": dt, "approximate": precision not in ("EXACT", "SYSTEM"), "precision": precision,
                       "time_label": label(dt, "EXACT" if precision == "SYSTEM" else precision), "event_type": etype,
                       "description": desc, "evidence_ids": list(dict.fromkeys(ev_ids)), "entity_ids": ent_ids,
                       "reliability": reliability})

    disputed = next((f for f in fused if f.kind == "DISPUTED"), None)

    # transactions (evidence-backed)
    for f in fused:
        if f.kind == "HISTORICAL":
            continue
        who = f.beneficiary_vpa or f.beneficiary or "an unidentified beneficiary"
        amt = f"₹{f.amount:,.0f}" if f.amount else "Unknown amount"
        srcs = ", ".join(evidence[e]["code"] for e in f.sources)
        tag = "Disputed transaction" if f.kind == "DISPUTED" else "Related transaction"
        add(f.occurred_at, f.precision, "TRANSACTION",
            f"{tag}: {amt} {f.channel or ''} payment to {who}".replace("  ", " ") + f" — corroborated by {srcs}",
            f.sources, [], "DOCUMENTED")

    # bank confirmations stated at their own time
    for e in entities:
        ev = evidence[e["evidence_id"]]
        if ev["subtype"] in ("BANK_SMS", "BANK_SMS_SCREENSHOT") and e["type"] == "DATETIME" and e["time_precision"] == "EXACT":
            amt = next((x for x in entities if x["evidence_id"] == ev["id"] and x["type"] == "AMOUNT"), None)
            stt = next((x["normalized"] for x in entities if x["evidence_id"] == ev["id"] and x["type"] == "STATUS"
                        and x["normalized"] in ("DEBITED", "CREDITED")), "transaction")
            add(e["occurred_at"], "EXACT", "BANK_CONFIRMATION",
                f"Bank message reports a {'credit' if stt == 'CREDITED' else 'debit'} of ₹{float(amt['normalized']):,.0f}" if amt else "Bank message",
                [ev["id"]], [e["id"]] + ([amt["id"]] if amt else []), "DOCUMENTED")
            break

    # account / device / authentication events (logs)
    window = None
    if disputed and disputed.occurred_at:
        window = (disputed.occurred_at - timedelta(hours=48), disputed.occurred_at + timedelta(hours=24))
    for e in entities:
        if e["type"] != "ACCOUNT_EVENT" or not e["occurred_at"]:
            continue
        if window and not (window[0] <= e["occurred_at"] <= window[1]):
            continue
        a = e["attrs"]
        bits = [EVENT_LABEL.get(a["event"], a["event"].replace("_", " ").title())]
        if a.get("device"):
            bits.append(f"device {a['device']}")
        if a.get("ip"):
            bits.append(f"IP {a['ip']}")
        if a.get("detail"):
            bits.append(str(a["detail"]))
        add(e["occurred_at"], e["time_precision"], a["event"], " · ".join(bits), [e["evidence_id"]], [e["id"]], "DOCUMENTED")

    # communications: chat/SMS lines with their own timestamps
    for ev in evidence.values():
        if ev["kind"] not in ("MESSAGE", "IMAGE", "DOCUMENT") or ev["subtype"] in (
                "BANK_SMS", "BANK_SMS_SCREENSHOT", "UPI_SCREENSHOT", "PAYMENT_RECEIPT", "BANK_STATEMENT"):
            continue
        for e in entities:
            if e["evidence_id"] == ev["id"] and e["type"] == "DATETIME" and e["time_precision"] == "EXACT":
                add(e["occurred_at"], "EXACT", "COMMUNICATION", f"Message: “{(e['context'] or '')[:180]}”", [ev["id"]],
                    [e["id"]], "STATEMENT")

    # audio: statements, placed in time only if the user said when the call happened
    for ev in evidence.values():
        if ev["kind"] != "AUDIO":
            continue
        claims = [e for e in entities if e["evidence_id"] == ev["id"] and e["type"] == "CLAIM"]
        start = ev.get("user_time_hint")
        if not claims:
            if ev["status"] in ("PROCESSED",) and start:
                add(start, "USER_HINT", "CALL", "Call recording (no statements of interest identified)", [ev["id"]], [], "STATEMENT")
            continue
        if start:
            add(start, "USER_HINT", "CALL", f"Call recording begins ({ev['code']})", [ev["id"]], [], "STATEMENT")
        seen = set()
        for c in claims:
            cat = c["attrs"]["category"]
            if cat in seen:
                continue
            seen.add(cat)
            off = c["attrs"].get("start")
            dt = start + timedelta(seconds=off) if start and off is not None else None
            add(dt, "OFFSET" if dt else "NONE", "AUDIO_STATEMENT",
                f"Statement extracted from audio ({c['locator'] or 'time in recording unknown'}): {c['attrs']['description']} — “{c['value'][:160]}”",
                [ev["id"]], [c["id"]], "STATEMENT")

    # the dispute itself
    add(case["created_at"], "SYSTEM", "DISPUTE_FILED", f"Dispute filed. Customer statement: “{case['statement'][:200]}”",
        [], [], "SYSTEM")

    dated = sorted([x for x in ev_out if x["occurred_at"]], key=lambda x: x["occurred_at"])
    undated = [x for x in ev_out if not x["occurred_at"]]
    return dated + undated
