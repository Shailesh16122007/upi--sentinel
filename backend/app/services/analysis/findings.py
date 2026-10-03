"""Neutral evidence classification relative to the customer's own claim.

SUPPORTING     evidence consistent with the customer's account of events
CONTRADICTORY  evidence that conflicts with the customer's statement
CONTEXTUAL     relevant but does not favour either side (incl. source-vs-source conflicts)
MISSING        information that would materially help but was not provided

The system never decides which evidence is truthful or whether fraud occurred.
"""
from __future__ import annotations

import re
from datetime import timedelta

from app.config import get_settings
from app.services.analysis.context import auth_events_for
from app.services.extraction.entities import IST

UNAUTH = re.compile(r"\b(did ?n[o']?t|never)\s+(make|made|do|did|initiate|authori[sz]e|approve|send|sent|pay|paid|intend)|"
                    r"\bunauthori[sz]ed\b|without my (knowledge|consent|permission)|\bnot (done|made) by me\b|\bwasn'?t me\b", re.I)
DECEIVED = re.compile(r"\b(trick|tricked|scam|scammer|fraudster|cheat|cheated|fake|caller|called me|asked me|told me|"
                      r"pretend|impersonat|lured|misled|deceiv)", re.I)
UNKNOWN_PAYEE = re.compile(r"(do ?n[o']?t|did ?n[o']?t|never)\s+know|unknown (person|account|number|beneficiary)|stranger|someone i (don'?t|do not) know", re.I)


def claim_profile(statement: str) -> dict:
    return {"unauthorised": bool(UNAUTH.search(statement or "")), "deceived": bool(DECEIVED.search(statement or "")),
            "unknown_payee": bool(UNKNOWN_PAYEE.search(statement or ""))}


def claim_type(p: dict) -> str:
    if p["unauthorised"] and p["deceived"]:
        return "UNINTENDED_UNDER_DECEPTION"
    if p["unauthorised"]:
        return "UNAUTHORISED"
    if p["deceived"]:
        return "AUTHORISED_UNDER_DECEPTION"
    return "UNSPECIFIED"


def _s(ev_ids, evidence, ent_ids=None):
    out = [{"evidence_id": e, "label": evidence[e]["code"]} for e in dict.fromkeys(ev_ids) if e in evidence]
    for eid in ent_ids or []:
        out.append({"entity_id": eid})
    return out


def _quote(s: str, n: int = 120) -> str:
    s = re.sub(r"\s+", " ", s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def completeness(case: dict, disputed, history: list, evidence: dict, entities: list[dict]) -> dict:
    items = []

    def item(key, label, weight, earned_frac, basis, why):
        items.append({"key": key, "label": label, "weight": weight, "earned": round(weight * earned_frac, 1),
                      "status": "present" if earned_frac >= 1 else "partial" if earned_frac > 0 else "missing",
                      "basis": basis, "why": why})

    d = disputed
    item("statement", "Customer statement", 10, 1 if len((case["statement"] or "").strip()) >= 15 else 0,
         "Provided when the dispute was filed" if case["statement"] else None, "Establishes what the customer says happened.")
    item("amount", "Transaction amount", 10, 1 if d and d.amount else 0,
         f"₹{d.amount:,.0f} from {', '.join(evidence[e]['code'] for e in d.sources)}" if d and d.amount else None,
         "Needed to identify and quantify the disputed payment.")
    ts_frac = 0 if not d or not d.occurred_at else 1 if d.precision == "EXACT" else 0.5
    item("timestamp", "Transaction date & time", 10, ts_frac,
         None if not ts_frac else ("Exact date and time stated in evidence" if ts_frac == 1 else f"Approximate only ({d.precision.replace('_', ' ').lower()})"),
         "Anchors the timeline and the bank's lookup.")
    item("reference", "Transaction reference / UTR", 10, 1 if d and d.reference else 0,
         f"Reference {d.reference}" if d and d.reference else None, "Lets the bank trace the exact transaction.")
    item("beneficiary", "Beneficiary details", 10, 1 if d and (d.beneficiary_vpa or d.beneficiary) else 0,
         (d.beneficiary_vpa or d.beneficiary) if d else None, "Needed to request a hold on the receiving account.")
    bank_src = [e for e in evidence.values() if e["subtype"] in ("BANK_SMS", "BANK_SMS_SCREENSHOT", "BANK_STATEMENT")]
    item("bank_confirmation", "Bank confirmation (SMS / statement)", 10, 1 if bank_src else 0,
         ", ".join(e["code"] for e in bank_src) or None, "Independent confirmation from the bank that money moved.")
    comm = [e for e in evidence.values() if e["subtype"] in ("CHAT", "CHAT_SCREENSHOT", "CALL_RECORDING", "CALL_LOG")
            or any(x["evidence_id"] == e["id"] and x["type"] == "CLAIM" for x in entities)]
    comm_ok = [e for e in comm if e["status"] in ("PROCESSED", "PARTIAL")]
    item("communication", "Communication with the other party (call / chat / SMS)", 10,
         1 if comm_ok else 0.5 if comm else 0, ", ".join(e["code"] for e in comm) or None,
         "Shows how the customer was approached, if at all.")
    need = get_settings().ml_min_history
    item("history", "Customer transaction history", 10, 1 if len(history) >= need else 0.5 if len(history) >= 5 else 0,
         f"{len(history)} historical transactions" if history else None,
         f"Needed to judge whether the payment is unusual (≥{need} rows for the ML check).")
    dev = [x for x in entities if x["type"] == "DEVICE" or (x["type"] == "ACCOUNT_EVENT" and x["attrs"].get("device"))]
    item("device", "Device information", 8, 1 if dev else 0, f"{len({(x['attrs'].get('device') or x['value']) for x in dev})} device reference(s)" if dev else None,
         "Shows whether the customer's own device was used.")
    auth = [x for x in entities if x["type"] == "ACCOUNT_EVENT" and x["attrs"]["event"] in ("AUTH_SUCCESS", "AUTH_FAILED", "OTP_VERIFIED", "LOGIN")]
    item("auth_logs", "Authentication logs", 6, 1 if auth else 0, f"{len(auth)} authentication/login event(s)" if auth else None,
         "Shows how the payment was authorised (PIN, biometric, OTP).")
    ips = [x for x in entities if x["type"] == "IP"]
    item("network", "Network information (IP)", 6, 1 if ips else 0, f"{len({x['value'] for x in ips})} IP address(es)" if ips else None,
         "Helps link sessions to a location or network.")
    total = sum(i["weight"] for i in items)
    earned = sum(i["earned"] for i in items)
    return {"score": round(100 * earned / total), "earned": earned, "total": total, "items": items,
            "method": "Weighted checklist: each category's weight is earned in full when present, half when only partially "
                      "available, zero when absent. Score = earned ÷ total weight."}


def classify(case: dict, fused: list, evidence: dict, entities: list[dict], anomalies: list[dict], ml: dict,
             comp: dict) -> list[dict]:
    out: list[dict] = []
    prof = claim_profile(case["statement"])
    d = next((f for f in fused if f.kind == "DISPUTED"), None)
    history = [f for f in fused if f.kind == "HISTORICAL"]

    def add(category, code, title, detail, sources, anomaly=False, conflict=False, data=None):
        out.append({"category": category, "code": code, "title": title, "detail": detail, "sources": sources,
                    "is_anomaly": anomaly, "is_conflict": conflict, "data": data or {}})

    # ---------------- anomalies (consistent with an unintended / unusual payment)
    for a in anomalies:
        add("SUPPORTING", a["code"], a["title"], a["detail"] + " This is anomalous activity, not proof of fraud.",
            a["sources"], anomaly=True, data=a.get("data"))
    if ml.get("available") and ml.get("is_outlier"):
        add("SUPPORTING", "ML_OUTLIER", "Statistical model rates the payment as unusual for this customer",
            f"Isolation Forest (trained on {ml['history_rows']} historical transactions) rates this payment more unusual than "
            f"{ml['more_anomalous_than_pct']}% of them. Main deviations: "
            + ", ".join(f"{x['feature']} (z={x['z']})" for x in ml["top_deviations"]) + ".",
            _s(list(dict.fromkeys((d.sources if d else []) + [e for h in history for e in h.sources])), evidence), anomaly=True,
            data=ml)

    # ---------------- statements in calls / messages
    by_key = {}
    for c in [e for e in entities if e["type"] == "CLAIM"]:
        key = (c["evidence_id"], c["attrs"]["category"])
        by_key.setdefault(key, c)
    for (ev_id, cat), c in by_key.items():
        full_lbl = c["attrs"]["label"]
        lbl = "Audio statement" if c["attrs"].get("origin") == "AUDIO" else "Message statement"
        prov = " Transcript provided by the user, not machine-generated." if "provided by user" in full_lbl else ""
        q = f"“{_quote(c['value']).rstrip('.')}”"
        loc = f" at {c['locator']}" if c["locator"] else ""
        if cat in ("IDENTITY_CLAIM", "REQUESTED_ACTION", "PRESSURE", "INDUCEMENT"):
            add("SUPPORTING", f"STATEMENT_{cat}", f"{lbl}: {c['attrs']['description']}",
                f"{evidence[ev_id]['code']}{loc}: {q}. {full_lbl.split(' (')[0]} — a statement made by the other party; not verified.{prov}",
                _s([ev_id], evidence, [c["id"]]))
        elif cat == "CONFIRMATION_BY_LISTENER":
            cat_ = "CONTRADICTORY" if prof["unauthorised"] and not prof["deceived"] else "CONTEXTUAL"
            add(cat_, "STATEMENT_LISTENER_CONFIRMS", f"{lbl}: listener appears to confirm taking an action",
                f"{evidence[ev_id]['code']}{loc}: {q}.{prov}", _s([ev_id], evidence, [c["id"]]),
                conflict=cat_ == "CONTRADICTORY")
    lang_seen = set()
    for x in entities:
        if x["type"] != "LANGUAGE_SIGNAL":
            continue
        ev = evidence[x["evidence_id"]]
        if ev["subtype"] in ("BANK_SMS", "BANK_SMS_SCREENSHOT", "BANK_STATEMENT", "UPI_SCREENSHOT", "PAYMENT_RECEIPT", "TXN_HISTORY", "ACCOUNT_LOG"):
            continue
        if any(k[0] == x["evidence_id"] for k in by_key):
            continue  # statements from this item are already reported above
        if x["normalized"] in ("REMOTE_ACCESS", "CREDENTIAL_REQUEST", "KYC", "IMPERSONATION") and (x["evidence_id"], x["normalized"]) not in lang_seen:
            lang_seen.add((x["evidence_id"], x["normalized"]))
            add("SUPPORTING", f"LANGUAGE_{x['normalized']}",
                f"{ev['code']} contains {x['normalized'].replace('_', ' ').lower()} language",
                f"“{_quote(x['context'] or '', 160)}” ({x['locator']}). Common in social-engineering messages; not proof on its own.",
                _s([x["evidence_id"]], evidence, [x["id"]]))

    if d:
        # communication evidence that names the same amount / beneficiary as the disputed payment
        for ev in evidence.values():
            if ev["id"] in d.sources or ev["kind"] == "STRUCTURED":
                continue
            ents = [x for x in entities if x["evidence_id"] == ev["id"]]
            hits = []
            if d.amount and any(x["type"] == "AMOUNT" and abs(float(x["normalized"]) - d.amount) < 1 for x in ents):
                hits.append(f"the same amount (₹{d.amount:,.0f})")
            if d.beneficiary_vpa and any(x["type"] == "UPI_ID" and x["normalized"] == d.beneficiary_vpa for x in ents):
                hits.append(f"the same beneficiary ({d.beneficiary_vpa})")
            if hits:
                add("SUPPORTING", "COMMUNICATION_MATCHES_PAYMENT",
                    f"{ev['code']} refers to {' and '.join(hits)} as the disputed payment",
                    f"{ev['original_name']} mentions {' and '.join(hits)}, linking this communication to the payment.",
                    _s([ev["id"]] + d.sources, evidence))

        # ---------------- authentication vs the customer's statement
        auths = [a for a in auth_events_for(d, entities) if a["attrs"]["event"] in ("AUTH_SUCCESS", "OTP_VERIFIED")]
        if auths:
            a = auths[0]
            how = a["value"]
            dev = f" on device {a['attrs']['device']}" if a["attrs"].get("device") else ""
            when = a["occurred_at"].astimezone(IST).strftime("%I:%M %p") if a["occurred_at"] else "time not stated"
            if prof["unauthorised"]:
                add("CONTRADICTORY", "AUTH_EVENT_PRESENT", "Authentication event recorded for the disputed payment",
                    f"Customer statement: “{_quote(case['statement'], 140)}”. Available evidence: {how}{dev} at {when} "
                    f"({a['_basis']}). Potential conflict requiring investigator review.",
                    _s([a["evidence_id"]] + d.sources, evidence, [a["id"]]), conflict=True)
            else:
                add("CONTEXTUAL", "AUTH_EVENT_PRESENT", "Authentication event recorded for the disputed payment",
                    f"{how}{dev} at {when} ({a['_basis']}). Consistent with a payment authorised from the account; "
                    "does not by itself show who entered the credentials or why.",
                    _s([a["evidence_id"]] + d.sources, evidence, [a["id"]]))

        # ---------------- statement vs evidence
        if case.get("claimed_amount") and d.amount and abs(case["claimed_amount"] - d.amount) >= 1:
            add("CONTRADICTORY", "CLAIMED_AMOUNT_MISMATCH", "Amount in the customer's statement differs from the evidence",
                f"Customer reported ₹{case['claimed_amount']:,.0f}; evidence shows ₹{d.amount:,.0f}. Both values preserved.",
                _s(d.sources, evidence), conflict=True)
        if case.get("approx_date") and d.occurred_at and d.precision in ("EXACT", "DATE_ONLY"):
            gap = abs((d.occurred_at.astimezone(IST).date() - case["approx_date"]).days)
            if gap > 1:
                add("CONTEXTUAL", "CLAIMED_DATE_MISMATCH", "Date in the dispute form differs from the evidence",
                    f"Customer gave approximately {case['approx_date']:%d %b %Y}; evidence shows {d.occurred_at.astimezone(IST):%d %b %Y}.",
                    _s(d.sources, evidence), conflict=True)
        ben = (d.beneficiary_vpa or d.beneficiary or "").lower()
        prior = [h for h in history if ben and (h.beneficiary_vpa or h.beneficiary or "").lower() == ben]
        if prior:
            cat_ = "CONTRADICTORY" if prof["unknown_payee"] else "CONTEXTUAL"
            add(cat_, "BENEFICIARY_PAID_BEFORE", "Beneficiary was paid before",
                f"{d.beneficiary_vpa or d.beneficiary} appears {len(prior)} time(s) in the customer's history"
                + (" although the statement describes the recipient as unknown." if cat_ == "CONTRADICTORY" else "."),
                _s(list(dict.fromkeys(e for h in prior for e in h.sources)), evidence), conflict=cat_ == "CONTRADICTORY")
        if d.status in ("FAILED", "REVERSED", "PENDING"):
            add("CONTRADICTORY" if d.status in ("FAILED", "REVERSED") else "CONTEXTUAL", "TXN_STATUS",
                f"Evidence shows the payment as {d.status.lower()}",
                "If the payment did not complete or was reversed, the loss described may not have occurred.",
                _s(d.sources, evidence))

        # ---------------- contextual corroboration
        if len(d.sources) > 1:
            basis = "; ".join(sorted({l[3] for l in d.links}))
            add("CONTEXTUAL", "CORROBORATED", f"Disputed transaction appears in {len(d.sources)} independent sources",
                f"{', '.join(evidence[e]['code'] for e in d.sources)} were matched as the same transaction ({basis}).",
                _s(d.sources, evidence))
        bank = [e for e in d.sources if evidence[e]["subtype"] in ("BANK_SMS", "BANK_SMS_SCREENSHOT", "BANK_STATEMENT")]
        if bank:
            add("CONTEXTUAL", "BANK_CONFIRMS", "Bank message confirms the money left the account",
                f"{', '.join(evidence[e]['code'] for e in bank)} {'reports' if len(bank) == 1 else 'report'} the debit.", _s(bank, evidence))
        for c in d.conflicts:
            grouped: dict = {}
            for v in c["values"]:
                grouped.setdefault(_fmt_val(c["field"], v["value"]), []).append(evidence[v["evidence_id"]]["code"])
            vals = " vs ".join(f"{k} ({', '.join(dict.fromkeys(cs))})" for k, cs in grouped.items())
            add("CONTEXTUAL", f"SOURCE_CONFLICT_{c['field'].upper()}", f"Evidence conflict: {c['field'].replace('_', ' ')}",
                f"{vals}. Both values are preserved. Investigator review required.",
                _s([v["evidence_id"] for v in c["values"]], evidence, [v["entity_id"] for v in c["values"]]), conflict=True,
                data={"field": c["field"], "values": c["values"]})
        if d.occurred_at and d.precision == "EXACT":
            delay = case["created_at"] - d.occurred_at
            if delay >= timedelta(0):
                hrs = delay.total_seconds() / 3600
                add("CONTEXTUAL", "REPORTING_DELAY", "Time between payment and dispute",
                    f"The dispute was filed {hrs:.1f} hours after the payment ({'within' if hrs <= 24 else 'more than'} 24 hours)."
                    + (" Note: synthetic demonstration case — filing time is when the demo was loaded." if case["is_synthetic"] else ""),
                    _s(d.sources, evidence))
    related = [f for f in fused if f.kind == "RELATED"]
    if related:
        add("CONTEXTUAL", "RELATED_TRANSACTIONS", f"{len(related)} other transaction(s) found in the evidence",
            "; ".join(f"₹{f.amount:,.0f}" if f.amount else "amount unknown" for f in related[:6]) + ". Not matched to the disputed payment.",
            _s([e for f in related for e in f.sources], evidence))

    # ---------------- missing
    for it in comp["items"]:
        if it["status"] != "present":
            add("MISSING", f"MISSING_{it['key'].upper()}",
                f"{'Partial' if it['status'] == 'partial' else 'No'}: {it['label'].lower()}",
                it["why"] + (f" Currently: {it['basis']}." if it["basis"] else " Not available in submitted evidence."), [])
    for ev in evidence.values():
        if ev["status"] in ("FAILED", "UNAVAILABLE"):
            add("MISSING", "UNREADABLE_EVIDENCE", f"{ev['code']} could not be read",
                f"{ev['original_name']}: {ev['error'] or 'processing failed'}", _s([ev["id"]], evidence))
    return out


def _fmt_val(field_, v):
    if field_ == "amount":
        return f"₹{float(v):,.0f}"
    if field_ == "time":
        from datetime import datetime
        return datetime.fromisoformat(v).astimezone(IST).strftime("%d %b %Y %I:%M %p")
    return str(v)
