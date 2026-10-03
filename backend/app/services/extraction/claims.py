"""Statement extraction from transcripts and conversations.

These are *statements made by someone*, not facts. They are stored as CLAIM entities and always
labelled with their origin ("Statement extracted from audio" / "Statement in message").
"""
from __future__ import annotations

import re

from app.services.extraction.entities import Ent

ORG = r"(bank|kyc|customer care|customer support|support|department|rbi|reserve bank|police|cyber|npci|paytm|phonepe|google pay|gpay|sbi|hdfc|icici|axis|kotak|income tax|courier|telecom|trai)"
RULES: list[tuple[str, re.Pattern, str]] = [
    ("IDENTITY_CLAIM", re.compile(rf"\b(i am|i'm|this is|we are|calling|speaking)\b[^.?!]{{0,50}}\b(from|of|with)\b[^.?!]{{0,30}}\b{ORG}\b", re.I),
     "Speaker claimed to represent {org}"),
    ("REQUESTED_ACTION", re.compile(r"\b(approve|accept|authori[sz]e|enter|share|tell me|read out|send|install|download|scan|click|open|pay|transfer|press)\b[^.?!]{0,50}\b(request|otp|pin|mpin|code|app|link|qr|payment|money|amount|anydesk|teamviewer)\b", re.I),
     "Speaker asked the listener to {act}"),
    ("PRESSURE", re.compile(r"\b(will be|is going to be|would be|gets?|from being|being)\s+(blocked|suspended|frozen|closed|deactivated|cancelled)\b|\blegal action\b|\barrest\b|\bimmediately\b|\bwithin \d+ (minutes|hours)\b", re.I),
     "Speaker warned of consequences / urgency"),
    ("INDUCEMENT", re.compile(r"\b(refund|cashback|reward|prize|lottery|bonus|returns?)\b", re.I),
     "Speaker offered a refund, reward or return"),
    ("CONFIRMATION_BY_LISTENER", re.compile(r"\b(i (have )?(approved|paid|entered|shared|sent|done)|ok(ay)? i (did|will)|it is done)\b", re.I),
     "Listener appears to confirm taking an action"),
]


ORG_PRIORITY = ["sbi", "hdfc", "icici", "axis", "kotak", "rbi", "reserve bank", "npci", "police", "cyber", "income tax", "paytm",
                "phonepe", "google pay", "gpay", "trai", "telecom", "courier", "bank", "kyc", "customer care", "customer support",
                "support", "department"]


def _best_org(text: str) -> str | None:
    low = text.lower()
    return next((o for o in ORG_PRIORITY if re.search(rf"\b{o}\b", low)), None)


def _org_label(org: str | None) -> str:
    if not org:
        return "an organisation"
    o = org.lower()
    if o in ("bank", "department"):
        return "a bank" if o == "bank" else "a department"
    if o in ("sbi", "hdfc", "icici", "axis", "kotak", "rbi", "npci", "trai"):
        return o.upper()
    if o == "kyc":
        return "a KYC team"
    if o in ("customer care", "customer support", "support"):
        return "customer support"
    return o.title()


def _fmt(sec: float | None) -> str | None:
    if sec is None:
        return None
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"


def extract_claims(units: list[dict], origin: str, base_conf: float = 1.0) -> list[Ent]:
    """units: [{text, start?, end?, locator?}] — audio segments or message lines."""
    out: list[Ent] = []
    label = "Statement extracted from audio" if origin == "AUDIO" else "Statement in message"
    for u in units:
        text = (u.get("text") or "").strip()
        if not text:
            continue
        for cat, rx, tmpl in RULES:
            m = rx.search(text)
            if not m:
                continue
            org = _best_org(m.group(0)) if cat == "IDENTITY_CLAIM" else None
            act = m.group(0).lower() if cat == "REQUESTED_ACTION" else None
            desc = tmpl.format(org=_org_label(org), act=act or "")
            loc = u.get("locator") or (_fmt(u.get("start")) if u.get("start") is not None else None)
            out.append(Ent("CLAIM", text[:480], cat, round(0.8 * base_conf, 3), loc, text[:300],
                           attrs={"category": cat, "description": desc, "label": label, "origin": origin,
                                  "start": u.get("start"), "end": u.get("end"), "matched": m.group(0)}))
    return out
