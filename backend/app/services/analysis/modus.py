"""Fraud modus operandi — a *pattern* label derived from communication evidence.

A category is reported only when at least two independent signal groups support it (one keyword is never
enough), and at least one of them comes from submitted evidence rather than the customer's own statement.
Every signal keeps its quote and source. This describes how the communication reads; it is not a finding
that fraud occurred.
"""
from __future__ import annotations

import re

from app.services.extraction import lexicon

CATEGORIES = [
    # code, label, anchor signal(s) (one required), supporting signals (at least one required)
    ("REMOTE_ACCESS_SCAM", "Remote access scam", {"REMOTE_ACCESS"},
     {"IMPERSONATION", "CREDENTIAL_REQUEST", "PAYMENT_REQUEST", "REFUND", "KYC", "URGENCY", "AUTHORITY"}),
    ("KYC_SCAM", "KYC scam", {"KYC"}, {"THREAT", "CREDENTIAL_REQUEST", "PAYMENT_REQUEST", "REMOTE_ACCESS", "LINK", "URGENCY"}),
    ("BANK_IMPERSONATION", "Bank impersonation", {"IMPERSONATION"},
     {"CREDENTIAL_REQUEST", "PAYMENT_REQUEST", "THREAT", "KYC", "REMOTE_ACCESS", "SECRECY"}),
    ("REFUND_SCAM", "Refund scam", {"REFUND"}, {"PAYMENT_REQUEST", "CREDENTIAL_REQUEST", "REMOTE_ACCESS", "IMPERSONATION"}),
    ("PAYMENT_REQUEST_SCAM", "Payment request scam", {"PAYMENT_REQUEST"},
     {"REFUND", "PRIZE", "THREAT", "IMPERSONATION", "KYC", "URGENCY"}),
    ("INVESTMENT_SCAM", "Investment scam", {"INVESTMENT"}, {"PAYMENT_REQUEST", "URGENCY", "LINK", "PRIZE", "SECRECY"}),
    ("PRIZE_SCAM", "Prize / reward scam", {"PRIZE"}, {"PAYMENT_REQUEST", "CREDENTIAL_REQUEST", "URGENCY", "LINK"}),
    ("DELIVERY_CUSTOMS_SCAM", "Customs / delivery scam", {"DELIVERY_CUSTOMS"},
     {"PAYMENT_REQUEST", "THREAT", "AUTHORITY", "CREDENTIAL_REQUEST", "URGENCY"}),
    ("ELECTRICITY_BILL_SCAM", "Electricity / bill scam", {"ELECTRICITY"},
     {"THREAT", "URGENCY", "PAYMENT_REQUEST", "REMOTE_ACCESS", "LINK", "CONTACT_NUMBER"}),
]
CLAIM_SIGNALS = {"IDENTITY_CLAIM": "IMPERSONATION", "PRESSURE": "THREAT"}
SIGNAL_LABEL = {**lexicon.LABEL, "LINK": "Contains a link", "CONTACT_NUMBER": "Gives a phone number to call"}
EXCLUDED_SUBTYPES = {"BANK_SMS", "BANK_SMS_SCREENSHOT", "BANK_STATEMENT", "UPI_SCREENSHOT", "PAYMENT_RECEIPT", "TXN_HISTORY",
                     "ACCOUNT_LOG", "SYSTEM_RECORD"}


def _signals(case: dict, evidence: dict, entities: list[dict]) -> dict[str, list[dict]]:
    sig: dict[str, list[dict]] = {}

    def add(code, quote, ev_id=None, ent_id=None, locator=None, origin="evidence"):
        sig.setdefault(code, []).append({"signal": code, "label": SIGNAL_LABEL.get(code, code), "quote": (quote or "")[:200],
                                         "evidence_id": ev_id, "entity_id": ent_id, "locator": locator, "origin": origin,
                                         "code": evidence[ev_id]["code"] if ev_id in evidence else None})

    for x in entities:
        ev = evidence.get(x["evidence_id"])
        if not ev or ev["subtype"] in EXCLUDED_SUBTYPES:
            continue  # the bank's own messages mention OTP/PIN/blocking routinely
        if x["type"] == "LANGUAGE_SIGNAL":
            add(x["normalized"], x["context"], x["evidence_id"], x["id"], x["locator"])
        elif x["type"] == "CLAIM":
            cat = x["attrs"].get("category")
            m = (x["attrs"].get("matched") or "").lower()
            if cat in CLAIM_SIGNALS:
                add(CLAIM_SIGNALS[cat], x["value"], x["evidence_id"], x["id"], x["locator"])
            if cat == "REQUESTED_ACTION":
                for code, rx in (("REMOTE_ACCESS", r"anydesk|teamviewer|quick ?support|\bdownload|\binstall|\bapp\b"),
                                 ("CREDENTIAL_REQUEST", r"\botp\b|\bpin\b|\bcode\b|ओटीपी"),
                                 ("PAYMENT_REQUEST", r"\bapprove|\baccept|\brequest\b|\bpay\b|\bqr\b|\bscan")):
                    if re.search(rx, m):
                        add(code, x["value"], x["evidence_id"], x["id"], x["locator"])
            if cat == "INDUCEMENT":
                add("INVESTMENT" if any(k in m for k in ("double", "return", "डबल")) else
                    "PRIZE" if any(k in m for k in ("prize", "lottery", "inaam", "reward", "इनाम")) else "REFUND",
                    x["value"], x["evidence_id"], x["id"], x["locator"])
        elif x["type"] == "URL":
            add("LINK", x["value"], x["evidence_id"], x["id"], x["locator"])
        elif x["type"] == "PHONE":
            add("CONTACT_NUMBER", x["context"], x["evidence_id"], x["id"], x["locator"])
    for code, matched in lexicon.find(case.get("statement") or ""):
        add(code, matched, origin="statement")
    return sig


def classify(case: dict, evidence: dict, entities: list[dict]) -> list[dict]:
    sig = _signals(case, evidence, entities)
    out = []
    for code, lbl, anchors, support in CATEGORIES:
        a = [s for k in anchors for s in sig.get(k, [])]
        sup_groups = {k: sig[k] for k in support if k in sig}
        if not a or not sup_groups:
            continue
        used, seen = [], set()
        for s in a + [s for v in sup_groups.values() for s in v]:
            k = (s["signal"], s["quote"][:60].lower())
            if k not in seen:
                seen.add(k)
                used.append(s)
        if not any(s["origin"] == "evidence" for s in used):
            continue  # the customer's own words alone are not enough
        groups = 1 + len(sup_groups)
        out.append({
            "code": code, "label": lbl, "groups": groups,
            "strength": "Consistent pattern" if groups >= 3 else "Possible pattern",
            "signals": [s for s in used][:12],
            "signal_groups": sorted({s["signal"] for s in used}),
            "note": "Pattern based on what the communication says. It does not establish that fraud occurred.",
        })
    out.sort(key=lambda m: -m["groups"])
    return out
