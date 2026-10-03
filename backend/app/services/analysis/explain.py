"""Explainable findings.

For every system finding: what was found (title/detail), why it matters, where it came from (sources) and
how certain it is — plus a plain-language view for the customer and a short "key findings" list for
investigators. Text here is derived only from the findings themselves; nothing new is asserted.
"""
from __future__ import annotations

from app.services.analysis.timeline import SOURCE_KIND

NOT_PROOF = "This does not by itself establish fraud."
WHY = {
    "AMOUNT_ANOMALY": "A payment far larger than the customer's usual payments is a common feature of unintended or induced transfers.",
    "TIME_ANOMALY": "Payments outside a customer's normal hours can indicate someone else acting, or pressure at an unusual time.",
    "BENEFICIARY_ANOMALY": "The beneficiary was not found in the available transaction history.",
    "DEVICE_ANOMALY": "A device change shortly before a payment can mean the account was used from another phone.",
    "SESSION_ANOMALY": "Sign-ins from new networks or repeated failures before a payment may indicate account takeover.",
    "SEQUENCE_ANOMALY": "The timing of account changes right before the payment may be relevant to the investigation.",
    "ML_OUTLIER": "A statistical comparison against this customer's own past payments only.",
    "STATEMENT_IDENTITY_CLAIM": "Impersonation of a bank or authority is a common opening in social-engineering cases.",
    "STATEMENT_REQUESTED_ACTION": "Shows what the other party asked the customer to do before the payment.",
    "STATEMENT_PRESSURE": "Threats and urgency are used to stop people from checking before acting.",
    "STATEMENT_INDUCEMENT": "Promises of refunds, rewards or returns are used to get people to approve payments.",
    "STATEMENT_LISTENER_CONFIRMS": "May show that the customer took the requested action themselves.",
    "COMMUNICATION_MATCHES_PAYMENT": "Links the communication to this specific payment.",
    "AUTH_EVENT_PRESENT": "Shows the payment was authorised from the account; it does not show who entered the credentials or why.",
    "CLAIMED_AMOUNT_MISMATCH": "The customer's own figure and the evidence disagree; the evidence values are preserved.",
    "CLAIMED_DATE_MISMATCH": "The date the customer gave and the evidence disagree.",
    "BENEFICIARY_PAID_BEFORE": "Prior payments to the same beneficiary suggest an existing relationship.",
    "TXN_STATUS": "If the payment failed or was reversed, the loss may not have occurred.",
    "CORROBORATED": "Independent sources agreeing on the same transaction increases reliability of the transaction details.",
    "BANK_CONFIRMS": "The bank's own message is independent confirmation that money moved.",
    "REPORTING_DELAY": "Early reporting improves the chance of freezing funds at the beneficiary bank.",
    "RELATED_TRANSACTIONS": "Other payments in the evidence may be part of the same incident or unrelated.",
    "MODUS_PATTERN": "Recognising the pattern helps decide what records to request next.",
}


def certainty(f: dict, ent_conf: dict[str, float], history_rows: int) -> tuple[str | None, str]:
    code = f["code"]
    if f["category"] == "MISSING" or code == "UNREADABLE_EVIDENCE":
        return None, ""
    low = [ent_conf[s["entity_id"]] for s in f["sources"] if s.get("entity_id") in ent_conf]
    hard = bool(low) and min(low) < 0.6
    if code.startswith("SOURCE_CONFLICT"):
        return ("Medium", "The sources disagree; one of the values comes from text that was hard to read.") if hard else \
            ("High", "Values read directly from the evidence.")
    if hard:
        return "Low", "Based on text that was hard to read (low extraction confidence)."
    if code in ("BANK_CONFIRMS", "CLAIMED_AMOUNT_MISMATCH"):
        return "High", "Values read directly from the evidence."
    if code in ("AMOUNT_ANOMALY", "TIME_ANOMALY", "BENEFICIARY_ANOMALY", "ML_OUTLIER"):
        return ("High" if history_rows >= 20 else "Medium"), f"Compared with {history_rows} historical transactions."
    if code in ("DEVICE_ANOMALY", "SESSION_ANOMALY", "SEQUENCE_ANOMALY", "AUTH_EVENT_PRESENT"):
        return "High", "Taken from timestamped account / device records."
    if code.startswith("STATEMENT_") or code.startswith("LANGUAGE_") or code == "MODUS_PATTERN":
        return "Medium", "Based on what someone said or wrote — an unverified statement."
    if code == "CORROBORATED":
        return ("High" if "reference" in (f["detail"] or "").lower() else "Medium"), "Depends on how the sources were matched."
    return "Medium", ""


def enrich(findings: list[dict], entities: list[dict], history_rows: int) -> None:
    conf = {e["id"]: e["confidence"] for e in entities}
    for f in findings:
        base = f["code"] if f["code"] in WHY else ("STATEMENT_" + f["code"].split("_", 1)[1] if f["code"].startswith("STATEMENT_") else f["code"])
        why = WHY.get(base) or WHY.get(f["code"].split("_SOURCE")[0])
        if f["code"].startswith("SOURCE_CONFLICT"):
            why = "Two sources disagree. Neither value has been chosen; a person needs to check which is right."
        if f["code"].startswith("LANGUAGE_"):
            why = "Wording often seen in social-engineering messages."
        if f["category"] == "MISSING":
            why = f.get("detail")
        if why and (f["is_anomaly"] or f["code"].startswith(("STATEMENT_", "LANGUAGE_", "MODUS"))):
            why = f"{why} {NOT_PROOF}"
        f["why"] = why
        f["certainty"], f["certainty_basis"] = certainty(f, conf, history_rows)


# ------------------------------------------------------------------ customer view

SIMPLE_ANOMALY = {
    "AMOUNT_ANOMALY": "This payment is much larger than your usual payments.",
    "TIME_ANOMALY": "This payment happened at an unusual time for you.",
    "BENEFICIARY_ANOMALY": "The money went to someone you have not paid before.",
    "DEVICE_ANOMALY": "A new phone or device was used shortly before the payment.",
    "SESSION_ANOMALY": "There was unusual sign-in activity before the payment.",
    "ML_OUTLIER": "Compared with your past payments, this one stands out.",
}
SIMPLE_MISSING = {
    "MISSING_AMOUNT": "We could not find the payment amount in your files.",
    "MISSING_TIMESTAMP": "We could not find the exact date and time of the payment.",
    "MISSING_REFERENCE": "We could not find a transaction reference number (UTR).",
    "MISSING_BENEFICIARY": "We could not find who received the money.",
    "MISSING_BANK_CONFIRMATION": "We do not have a bank SMS or statement showing the money left your account.",
    "MISSING_COMMUNICATION": "We do not have the call recording or messages from the other person.",
    "MISSING_HISTORY": "We do not have your past transactions. Your bank can usually add these.",
    "MISSING_DEVICE": "We do not have device or login information for this transaction.",
}


def lc(label: str) -> str:
    """'UPI screenshot' stays, 'Bank SMS' -> 'bank SMS'."""
    first = label.split(" ", 1)[0]
    return label if first.isupper() else label[:1].lower() + label[1:]


def victim_view(findings: list[dict], evidence: dict, modus: list[dict]) -> dict:
    unusual, related, check, missing = [], [], [], []

    def kinds(f):
        return [lc(SOURCE_KIND.get(evidence[s["evidence_id"]]["subtype"], "file")) for s in f["sources"]
                if s.get("evidence_id") in evidence]

    for f in findings:
        c = f["code"]
        if c in SIMPLE_ANOMALY:
            unusual.append({"text": SIMPLE_ANOMALY[c], "sources": f["sources"]})
        elif c == "SEQUENCE_ANOMALY":
            chain = " ".join((f.get("data") or {}).get("chain", [])).lower()
            unusual.append({"text": "A new payment recipient appeared shortly before the transaction."
                            if "beneficiary" in chain else "Several account changes happened just before the payment.",
                            "sources": f["sources"]})
        elif c == "CORROBORATED":
            k = list(dict.fromkeys(kinds(f)))
            related.append({"text": f"Your {' and '.join(k[:3]) if k else 'files'} appear to refer to the same transaction.",
                            "sources": f["sources"]})
        elif c == "BANK_CONFIRMS":
            related.append({"text": "Your bank message confirms the money left your account.", "sources": f["sources"]})
        elif c == "COMMUNICATION_MATCHES_PAYMENT":
            related.append({"text": "Your " + (kinds(f)[0] if kinds(f) else "file") + " mentions the same payment.",
                            "sources": f["sources"]})
        elif c.startswith("STATEMENT_") and c != "STATEMENT_LISTENER_CONFIRMS":
            where = "call recording" if f["title"].startswith("Audio") else "message"
            desc = f["title"].split(": ", 1)[-1].replace("Caller ", "the caller ", 1).replace("Sender ", "the sender ", 1)
            related.append({"text": f"In the {where}, {desc}.", "sources": f["sources"]})
        elif c.startswith("SOURCE_CONFLICT"):
            fld = c.replace("SOURCE_CONFLICT_", "").replace("_", " ").lower()
            check.append({"text": f"Your files show different {fld} values. The bank will check which one is right.",
                          "sources": f["sources"]})
        elif c == "CLAIMED_AMOUNT_MISMATCH":
            check.append({"text": "The amount you entered is different from the amount in your files. Both are kept.",
                          "sources": f["sources"]})
        elif c in SIMPLE_MISSING:
            missing.append({"text": SIMPLE_MISSING[c], "sources": []})
        elif c == "UNREADABLE_EVIDENCE":
            ev = next((evidence[s["evidence_id"]] for s in f["sources"] if s.get("evidence_id") in evidence), None)
            n = ev["original_name"] if ev else "a file"
            missing.append({"text": f"We could not transcribe {n}. The recording is kept as evidence." if ev and ev["kind"] in (
                "AUDIO", "VIDEO") else f"We could not read {n}. The original file is kept.", "sources": f["sources"]})
    for m in modus[:1]:
        related.append({"text": f"What you described looks similar to a known type of scam ({m['label'].lower()}). "
                                "Investigators will check this.", "sources": [
                            {"evidence_id": s["evidence_id"], "label": s["code"]} for s in m["signals"] if s.get("evidence_id")]})
    # merge device + auth + network gaps into one sentence
    return {"unusual": unusual, "related": related, "check": check, "missing": missing}


# ------------------------------------------------------------------ investigator "key findings"

ORDER = ["SEQUENCE_ANOMALY", "BENEFICIARY_ANOMALY", "DEVICE_ANOMALY", "AMOUNT_ANOMALY", "SESSION_ANOMALY", "TIME_ANOMALY",
         "ML_OUTLIER", "SOURCE_CONFLICT", "CLAIMED_AMOUNT_MISMATCH", "BANK_CONFIRMS", "AUTH_EVENT_PRESENT", "MODUS_PATTERN",
         "CORROBORATED", "STATEMENT_IDENTITY_CLAIM", "STATEMENT_REQUESTED_ACTION", "TXN_STATUS", "BENEFICIARY_PAID_BEFORE",
         "MISSING_DEVICE", "MISSING_REFERENCE", "MISSING_BANK_CONFIRMATION", "UNREADABLE_EVIDENCE"]
SHORT = {
    "SEQUENCE_ANOMALY": None, "BENEFICIARY_ANOMALY": "New beneficiary — not seen in the available transaction history",
    "BANK_CONFIRMS": "Bank SMS confirms the transaction", "AUTH_EVENT_PRESENT": "Authentication record is present",
    "MISSING_DEVICE": "Device information is unavailable", "MISSING_REFERENCE": "Transaction reference (UTR) not found in evidence",
    "MISSING_BANK_CONFIRMATION": "No bank confirmation (SMS / statement) submitted",
}


def key_findings(findings: list[dict], limit: int = 6) -> list[dict]:
    """A balanced short list: up to 3 anomalies, then conflicts, bank confirmation, authentication, pattern, one gap."""
    def rank(f):
        for i, k in enumerate(ORDER):
            if f["code"].startswith(k):
                return i
        return 99
    buckets = [  # (predicate, max items)
        (lambda f: f["is_anomaly"], 3),
        (lambda f: f["is_conflict"] and not f["is_anomaly"], 2),
        (lambda f: f["code"] in ("BANK_CONFIRMS", "CORROBORATED"), 1),
        (lambda f: f["code"] == "AUTH_EVENT_PRESENT", 1),
        (lambda f: f["code"] in ("MODUS_PATTERN", "TXN_STATUS"), 1),
        (lambda f: f["category"] == "MISSING" and f["code"] in ("MISSING_DEVICE", "MISSING_REFERENCE", "MISSING_BANK_CONFIRMATION"), 1),
    ]
    ranked = sorted([f for f in findings if rank(f) < 99], key=rank)
    picked, seen = [], set()
    for pred, cap in buckets:
        for f in [x for x in ranked if pred(x) and x["code"] not in seen][:cap]:
            seen.add(f["code"])
            picked.append(f)
    out = []
    for f in picked[:limit]:
        text = SHORT.get(f["code"]) or f["title"]
        if f["code"] == "SEQUENCE_ANOMALY":
            text = ("New beneficiary added shortly before the payment" if "beneficiary" in (f["detail"] or "").lower()
                    else "Account changes shortly before the payment")
        if f["code"] == "AMOUNT_ANOMALY":
            text = "Amount is significantly different from the available transaction history"
        out.append({"n": len(out) + 1, "text": text, "code": f["code"], "sources": f["sources"],
                    "is_conflict": f["is_conflict"], "is_anomaly": f["is_anomaly"], "category": f["category"]})
    return out
