"""Context analysis: compare the disputed transaction with the customer's history and surrounding account
activity. Results are labelled 'anomalous activity' — never 'fraud'."""
from __future__ import annotations

import statistics
from datetime import timedelta

from app.services.analysis.timeline import EVENT_LABEL
from app.services.extraction.entities import IST

PRECURSORS = {"BENEFICIARY_ADDED", "DEVICE_REGISTERED", "SIM_CHANGE", "PASSWORD_CHANGE", "LOGIN_FAILED", "OTP_VERIFIED"}


def _src(ev_ids, evidence, extra=None):
    out = [{"evidence_id": e, "label": evidence[e]["code"]} for e in dict.fromkeys(ev_ids) if e in evidence]
    return out + (extra or [])


def _ben(f):
    return (f.beneficiary_vpa or f.beneficiary or "").lower() or None


def _fmt_t(dt):
    return dt.astimezone(IST).strftime("%I:%M %p")


def auth_events_for(disputed, entities: list[dict]) -> list[dict]:
    """Authentication events tied to the disputed payment by reference, or within 3 minutes of it."""
    out = []
    for e in entities:
        if e["type"] != "ACCOUNT_EVENT" or e["attrs"]["event"] not in ("AUTH_SUCCESS", "AUTH_FAILED", "OTP_VERIFIED"):
            continue
        ref = (e["attrs"].get("reference") or "").upper()
        by_ref = bool(ref and disputed.reference and (ref == disputed.reference or ref.endswith(disputed.reference)
                                                      or disputed.reference.endswith(ref)))
        by_time = bool(e["occurred_at"] and disputed.occurred_at and disputed.precision == "EXACT"
                       and abs((e["occurred_at"] - disputed.occurred_at).total_seconds()) <= 180)
        if by_ref or by_time:
            out.append({**e, "_basis": "same reference" if by_ref else "within 3 minutes of the payment"})
    return out


def anomalies(disputed, history: list, entities: list[dict], evidence: dict, claims: list[dict]) -> tuple[list[dict], dict]:
    res: list[dict] = []
    meta = {"history_rows": len(history)}
    if disputed is None:
        return res, meta
    hist_ev = list(dict.fromkeys(e for h in history for e in h.sources))
    d_src = disputed.sources

    # ---- amount
    amts = [h.amount for h in history if h.amount]
    if disputed.amount and len(amts) >= 5:
        mx, mean = max(amts), statistics.mean(amts)
        sd = statistics.pstdev(amts)
        z = (disputed.amount - mean) / sd if sd else 0
        meta["amount"] = {"max": mx, "mean": round(mean, 2), "z": round(z, 2), "n": len(amts)}
        if disputed.amount > 2 * mx or z > 3:
            res.append({"code": "AMOUNT_ANOMALY", "title": "Amount far above the customer's usual payments",
                        "detail": f"₹{disputed.amount:,.0f} is {disputed.amount / mx:.1f}× the largest payment (₹{mx:,.0f}) and "
                                  f"{disputed.amount / mean:.1f}× the average (₹{mean:,.0f}) across {len(amts)} historical transactions.",
                        "sources": _src(d_src + hist_ev, evidence)})

    # ---- time of day
    timed = [h for h in history if h.occurred_at and h.precision == "EXACT"]
    if disputed.occurred_at and disputed.precision in ("EXACT", "TIME_ONLY") and len(timed) >= 10:
        hd = disputed.occurred_at.astimezone(IST).hour
        hours = [h.occurred_at.astimezone(IST).hour for h in timed]
        near = sum(1 for h in hours if min(abs(h - hd), 24 - abs(h - hd)) <= 1)
        meta["hour"] = {"hour": hd, "historical_within_1h": near, "n": len(hours)}
        if near == 0:
            res.append({"code": "TIME_ANOMALY", "title": "Payment outside the customer's usual hours",
                        "detail": f"Payment at {_fmt_t(disputed.occurred_at)}; none of {len(hours)} timed historical "
                                  f"payments occurred within an hour of that time (usual range "
                                  f"{min(hours):02d}:00–{max(hours):02d}:59).",
                        "sources": _src(d_src + hist_ev, evidence)})

    # ---- beneficiary
    ben = _ben(disputed)
    if ben and len(history) >= 5:
        seen = {_ben(h) for h in history if _ben(h)}
        meta["beneficiary_in_history"] = ben in seen
        if ben not in seen:
            res.append({"code": "BENEFICIARY_ANOMALY", "title": "Beneficiary not seen before",
                        "detail": f"{disputed.beneficiary_vpa or disputed.beneficiary} does not appear in {len(history)} "
                                  f"historical transactions.",
                        "sources": _src(d_src + hist_ev, evidence)})

    # ---- device / session / sequence (needs account logs)
    events = sorted([e for e in entities if e["type"] == "ACCOUNT_EVENT" and e["occurred_at"]], key=lambda e: e["occurred_at"])
    t0 = disputed.occurred_at if disputed.precision == "EXACT" else None
    auths = auth_events_for(disputed, entities)
    txn_device = next((a["attrs"].get("device") for a in auths if a["attrs"].get("device")), None) or disputed.device
    meta["txn_device"] = txn_device
    if t0 and events:
        before = [e for e in events if t0 - timedelta(hours=24) <= e["occurred_at"] <= t0]
        hist_devices = {(h.device or "").lower() for h in history if h.device}
        earlier_devices = {(e["attrs"].get("device") or "").lower() for e in events if e["occurred_at"] < t0 - timedelta(hours=24) and e["attrs"].get("device")}
        known = (hist_devices | earlier_devices) - {""}
        reg = [e for e in before if e["attrs"]["event"] == "DEVICE_REGISTERED"]
        if reg:
            r = reg[-1]
            mins = (t0 - r["occurred_at"]).total_seconds() / 60
            res.append({"code": "DEVICE_ANOMALY", "title": "New device registered shortly before the payment",
                        "detail": f"Device {r['attrs'].get('device') or '(unnamed)'} was registered {mins:.0f} min before the payment.",
                        "sources": _src([r["evidence_id"]] + d_src, evidence, [{"entity_id": r["id"], "locator": r["locator"]}])})
        elif txn_device and known and txn_device.lower() not in known:
            res.append({"code": "DEVICE_ANOMALY", "title": "Payment authorised from a device not seen before",
                        "detail": f"Device {txn_device} does not appear in earlier history or logs (known: {', '.join(sorted(known))}).",
                        "sources": _src(d_src + [a["evidence_id"] for a in auths], evidence)})
        logins = [e for e in before if e["attrs"]["event"] in ("LOGIN", "LOGIN_FAILED") and t0 - e["occurred_at"] <= timedelta(hours=2)]
        known_ips = {e["attrs"].get("ip") for e in events if e["occurred_at"] < t0 - timedelta(hours=24) and e["attrs"].get("ip")}
        new_ip = [e for e in logins if e["attrs"].get("ip") and known_ips and e["attrs"]["ip"] not in known_ips]
        failed = [e for e in logins if e["attrs"]["event"] == "LOGIN_FAILED"]
        if new_ip or len(failed) >= 2:
            bits = []
            if new_ip:
                bits.append(f"login from previously unseen IP {new_ip[-1]['attrs']['ip']} at {_fmt_t(new_ip[-1]['occurred_at'])}")
            if len(failed) >= 2:
                bits.append(f"{len(failed)} failed login attempts in the 2 hours before")
            ids = [e["evidence_id"] for e in new_ip + failed]
            res.append({"code": "SESSION_ANOMALY", "title": "Unusual account session before the payment",
                        "detail": "; ".join(bits).capitalize() + ".", "sources": _src(ids, evidence)})

        # sequence: precursor events in the 30 minutes before payment
        pre = [e for e in before if e["attrs"]["event"] in PRECURSORS and t0 - e["occurred_at"] <= timedelta(minutes=30)]
        chain = [(e["occurred_at"], EVENT_LABEL.get(e["attrs"]["event"], e["attrs"]["event"]), e) for e in pre]
        call = [c for c in claims if c.get("_abs_time") and timedelta(0) <= t0 - c["_abs_time"] <= timedelta(minutes=30)]
        if call:
            first = min(call, key=lambda c: c["_abs_time"])
            cats = {c["attrs"]["category"] for c in call}
            what = []
            if "IDENTITY_CLAIM" in cats:
                what.append("caller claims to be from " + next(c for c in call if c["attrs"]["category"] == "IDENTITY_CLAIM")["attrs"]["description"].split("represent ")[-1])
            if "REQUESTED_ACTION" in cats:
                what.append("asks for an approval/action")
            chain.append((first["_abs_time"], "Call (" + ", ".join(what or ["statements recorded"]) + ")", first))
        chain.sort(key=lambda x: x[0])
        if chain:
            steps, last = [], None
            for when, lbl, _ in chain:
                if last is not None:
                    steps.append(f"{(when - last).total_seconds() / 60:.0f} min")
                steps.append(f"{lbl} ({_fmt_t(when)})")
                last = when
            steps.append(f"{(t0 - last).total_seconds() / 60:.0f} min")
            steps.append(f"₹{disputed.amount:,.0f} payment ({_fmt_t(t0)})" if disputed.amount else "Payment")
            res.append({"code": "SEQUENCE_ANOMALY", "title": "Account changes immediately before the payment",
                        "detail": " → ".join(steps), "data": {"chain": steps},
                        "sources": _src([x[2]["evidence_id"] for x in chain] + d_src, evidence)})
    return res, meta
