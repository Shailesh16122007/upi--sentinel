"""Statement extraction from transcripts and conversations (English, Hinglish, Hindi, Tamil).

These are *statements made by someone*, not facts. They are stored as CLAIM entities, worded as claims
("Caller claimed to represent a bank", never "Caller was a bank employee") and always labelled with their
origin ("Statement extracted from audio" / "Statement in message").
"""
from __future__ import annotations

import re

from app.services.extraction.entities import Ent

ORG = r"(bank|kyc|customer care|customer support|support|department|rbi|reserve bank|police|cyber|npci|paytm|phonepe|google pay|gpay|sbi|hdfc|icici|axis|kotak|income tax|courier|telecom|trai|electricity|customs)"
_I = re.I | re.U
RULES: list[tuple[str, re.Pattern]] = [
    ("IDENTITY_CLAIM", re.compile(
        rf"\b(i am|i'm|this is|we are|calling|speaking)\b[^.?!]{{0,50}}\b(from|of|with)\b[^.?!]{{0,30}}\b{ORG}\b"
        rf"|\b{ORG}\b\s*(?:se|ki taraf se|department se|office se)\s*(?:bol|baat|call)"
        rf"|(?:main|mai|hum)\b[^.?!]{{0,25}}?\b{ORG}\b[^.?!]{{0,25}}\bse\b"
        rf"|\b{ORG}[- ]?(?:la|il) irundhu|बैंक से (?:बोल|बात)", _I)),
    ("REQUESTED_ACTION", re.compile(
        r"\b(approve|accept|authori[sz]e|enter|share|tell me|read out|send|install|download|scan|click|open|pay|transfer|press)\b"
        r"[^.?!]{0,50}\b(request|otp|pin|mpin|code|app|link|qr|payment|money|amount|anydesk|teamviewer)\b"
        r"|\b(anydesk|teamviewer|app|otp|pin|upi pin|request|link|qr|payment)\b[^.?!]{0,30}?\b(download|install|batao|bata do|bataiye|"
        r"bhejo|daalo|dalo|daal do|approve|accept|click|scan|share|enter|sollunga|sollu|anuppunga|pannunga)\b"
        r"|(?:otp|ओटीपी|पिन)\s*(?:बताइए|बताओ|बता दो)", _I)),
    ("PRESSURE", re.compile(
        r"\b(will be|is going to be|would be|gets?|from being|being)\s+(blocked|suspended|frozen|closed|deactivated|cancelled|disconnected|cut)\b"
        r"|\blegal action\b|\barrest\b|\bimmediately\b|\bwithin \d+ (minutes|hours)\b"
        r"|\b(block|band|bandh|freeze|suspend|kat|cut)\s*(?:ho\s*)?(jayega|jaega|jaayega|jayegi|jaegi)\b|\bturant\b"
        r"|बंद हो जाएगा|block\s*(?:aayidum|aagidum)", _I)),
    ("INDUCEMENT", re.compile(
        r"\b(refund|cashback|reward|prize|lottery|bonus|returns?)\b|paise double|\bdouble\s*(?:ho|kar)\b|\binaam\b|इनाम|पैसे डबल", _I)),
    ("CONFIRMATION_BY_LISTENER", re.compile(
        r"\b(i (have )?(approved|paid|entered|shared|sent|done|installed|downloaded)|ok(ay)? i (did|will)|it is done|"
        r"maine (kar diya|daal diya|bata diya|approve kar diya)|ho gaya)\b", _I)),
]

ORG_PRIORITY = ["sbi", "hdfc", "icici", "axis", "kotak", "rbi", "reserve bank", "npci", "police", "cyber", "income tax", "paytm",
                "phonepe", "google pay", "gpay", "trai", "telecom", "courier", "customs", "electricity", "bank", "बैंक", "kyc",
                "customer care", "customer support", "support", "department"]

ACTIONS = [  # (pattern, plain description of what was asked)
    (r"anydesk|teamviewer|quick ?support|rustdesk|download|install|\bapp\b", "install or open an app"),
    (r"approve|accept|authori[sz]e|request", "approve a payment request"),
    (r"otp|code|ओटीपी", "share an OTP / code"),
    (r"pin|mpin|पिन", "enter or share the UPI PIN"),
    (r"\bqr\b|scan", "scan a QR code"),
    (r"link|click|open", "open a link"),
    (r"pay|transfer|money|amount|send", "make a payment"),
]


def _best_org(text: str) -> str | None:
    low = text.lower()
    return next((o for o in ORG_PRIORITY if re.search(rf"(?<!\w){re.escape(o)}(?!\w)", low)), None)


def _org_label(org: str | None) -> str:
    if not org:
        return "an organisation"
    o = org.lower()
    if o in ("bank", "बैंक"):
        return "a bank"
    if o == "department":
        return "a department"
    if o in ("sbi", "hdfc", "icici", "axis", "kotak", "rbi", "npci", "trai"):
        return o.upper()
    if o == "kyc":
        return "a KYC team"
    if o in ("customer care", "customer support", "support"):
        return "customer support"
    if o == "electricity":
        return "an electricity board"
    return o.title()


def _describe(cat: str, matched: str, who: str) -> str:
    m = matched.lower()
    if cat == "IDENTITY_CLAIM":
        return f"{who} claimed to represent {_org_label(_best_org(matched))}"
    if cat == "REQUESTED_ACTION":
        whats = [d for rx, d in ACTIONS if re.search(rx, m)]
        return f"{who} asked the listener to {' and '.join(whats[:2]) or 'take an action'}"
    if cat == "PRESSURE":
        if re.search(r"block|band|freeze|frozen|suspend|closed|deactivat|बंद", m):
            return f"{who} stated that the account would be blocked"
        if re.search(r"cut|kat|disconnect", m):
            return f"{who} stated that a service would be cut off"
        if re.search(r"arrest|legal", m):
            return f"{who} mentioned legal action or arrest"
        return f"{who} created urgency"
    if cat == "INDUCEMENT":
        if re.search(r"double|returns?|डबल", m):
            return f"{who} promised that money would be doubled / returned"
        return f"{who} offered a refund, reward or prize"
    return "Listener appears to confirm taking an action"


def _fmt(sec: float | None) -> str | None:
    if sec is None:
        return None
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


def extract_claims(units: list[dict], origin: str, base_conf: float = 1.0) -> list[Ent]:
    """units: [{text, start?, end?, locator?}] — audio segments or message lines.

    A sentence is often split over two OCR lines or two audio segments, so adjacent pairs are also checked;
    a pair only adds a statement category that neither line produced on its own."""
    out = _claims(units, origin, base_conf)
    single = {(c.locator, c.normalized) for c in out}
    for i in range(len(units) - 1):
        a, b = (units[i].get("text") or "").strip(), (units[i + 1].get("text") or "").strip()
        if not a or not b:
            continue
        la = units[i].get("locator") or (_fmt(units[i].get("start")) if units[i].get("start") is not None else None)
        lb = units[i + 1].get("locator") or (_fmt(units[i + 1].get("start")) if units[i + 1].get("start") is not None else None)
        pair = {"text": f"{a} {b}", "start": units[i].get("start"), "end": units[i + 1].get("end"),
                "locator": la if (la or "").count(":") else (f"{la}–{lb.split()[-1]}" if la and lb else la)}
        for c in _claims([pair], origin, base_conf * 0.95):
            if (la, c.normalized) not in single and (lb, c.normalized) not in single:
                single.add((la, c.normalized))
                out.append(c)
            elif c.normalized == "IDENTITY_CLAIM":  # the pair may name the organisation the single line did not
                for o in out:
                    if o.normalized == "IDENTITY_CLAIM" and o.locator in (la, lb) and \
                            any(g in o.attrs["description"] for g in GENERIC_ORGS) and o.attrs["description"] != c.attrs["description"]:
                        o.value, o.context, o.locator = c.value, c.context, c.locator
                        o.attrs.update(description=c.attrs["description"], matched=c.attrs["matched"])
    return out


GENERIC_ORGS = ("a department", "an organisation", "customer support")


def _claims(units: list[dict], origin: str, base_conf: float) -> list[Ent]:
    out: list[Ent] = []
    label = "Statement extracted from audio" if origin == "AUDIO" else "Statement in message"
    who = "Caller" if origin == "AUDIO" else "Sender"
    for u in units:
        text = (u.get("text") or "").strip()
        if not text:
            continue
        for cat, rx in RULES:
            m = rx.search(text)
            if not m:
                continue
            loc = u.get("locator") or (_fmt(u.get("start")) if u.get("start") is not None else None)
            out.append(Ent("CLAIM", text[:480], cat, round(0.8 * base_conf, 3), loc, text[:300],
                           attrs={"category": cat, "description": _describe(cat, m.group(0), who), "label": label,
                                  "origin": origin, "start": u.get("start"), "end": u.get("end"), "matched": m.group(0)}))
    return out
