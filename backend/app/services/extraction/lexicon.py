"""Fraud-communication signals across English, Hinglish, Hindi (Devanagari) and Tamil (script + romanized).

Each signal is a small group of patterns. A single match is only a *signal* attached to the line it came
from — scam categories (analysis/modus.py) need several independent signals. Add languages by appending
patterns to a group; nothing else needs to change.
"""
from __future__ import annotations

import re

_F = re.I | re.U

SIGNALS: dict[str, tuple[str, list[str]]] = {
    "IMPERSONATION": ("Claims to be from a bank / support", [
        r"calling from (?:your |the )?\w*\s?(?:bank|kyc|customer care|support)", r"\bbank (?:officer|executive|manager|official)\b",
        r"\bcustomer (?:care|support)\b", r"\bbank se\b", r"(?:main|mai|hum)\s.{0,25}\b(?:bank|kyc)\b.{0,15}\bse\b",
        r"बैंक से", r"bank[- ]?(?:la|il) irundhu", r"வங்கியில் இருந்து", r"\bkyc (?:department|team|cell)\b"]),
    "AUTHORITY": ("Claims to be from police / government", [
        r"\brbi\b", r"reserve bank", r"\bcyber (?:cell|police|crime)\b", r"\bcbi\b", r"\bcustoms (?:officer|department)\b",
        r"income tax", r"\btrai\b", r"\bpolice\b", r"\bnarcotics\b", r"digital arrest", r"पुलिस"]),
    "KYC": ("KYC / identity update", [r"\b(?:re-?)?kyc\b", r"\bpan card\b", r"\baadhaa?r\b", r"केवाईसी", r"\bkyc update\b"]),
    "THREAT": ("Account block / penalty threat", [
        r"\bblock(?:ed)?\b", r"\bsuspend(?:ed)?\b", r"\bfrozen\b", r"\bfreeze\b", r"\bdeactivat", r"legal action", r"\barrest",
        r"\b(?:band|block|freeze|suspend|bandh)\s*(?:ho\s*)?(?:jayega|jaega|jaayega|jayegi|jaegi|ho jayega|kar diya jayega)",
        r"बंद हो जाएगा", r"ब्लॉक", r"block\s*(?:aayidum|aagidum|pannuvom)", r"முடக்க"]),
    "CREDENTIAL_REQUEST": ("Asks for OTP / PIN / password", [
        r"\botp\b", r"\bupi pin\b", r"\bm-?pin\b", r"\bcvv\b", r"\bpassword\b", r"\bpin\b", r"ओटीपी", r"पिन",
        r"(?:otp|pin)\s*(?:batao|bata do|bataiye|bhejo|daalo|dalo|share karo|sollunga|sollu|anuppunga)"]),
    "REMOTE_ACCESS": ("Remote-access / screen-sharing app", [
        r"any\s?desk", r"team\s?viewer", r"quick\s?support", r"rust\s?desk", r"screen ?shar", r"\.apk\b",
        r"(?:app|application)\s*(?:download|install)\s*(?:karo|kariye|kar lo|pannunga)?",
        r"download\s*(?:karo|kariye|kar lo|pannunga)"]),
    "PAYMENT_REQUEST": ("Asks to approve / pay / scan", [
        r"approve (?:the |this )?(?:request|payment|collect)", r"collect request", r"payment request", r"scan (?:the |this )?qr",
        r"\b(?:request|payment)\s*(?:approve|accept)\s*(?:karo|kariye|kar do|kar dijiye|pannunga)",
        r"\bpay\s*(?:karo|kariye|kar do)\b", r"\b(?:pin|upi pin)\s*(?:enter|daalo|dalo|daal do)\b", r"enter (?:your |the )?(?:upi )?pin"]),
    "REFUND": ("Refund / cashback offer", [
        r"\brefund\b", r"\bcashback\b", r"credited back", r"paise wapas", r"refund (?:milega|mil jayega)", r"रिफंड", r"वापस"]),
    "PRIZE": ("Prize / lottery / reward", [
        r"\blottery\b", r"\bprize\b", r"you have won", r"\binaam\b", r"इनाम", r"lucky draw", r"\bkbc\b", r"\breward\b", r"lottery lagi"]),
    "INVESTMENT": ("Investment / doubling returns", [
        r"paise double", r"\bdouble\s*(?:ho|kar|your money|the money|returns)", r"\binvest(?:ment)?\b", r"guaranteed (?:returns|profit)",
        r"\btrading\b", r"\bcrypto\b", r"part[- ]time job", r"daily (?:income|profit)", r"\btask(?:s)?\b.*\b(?:earn|commission)",
        r"पैसे डबल"]),
    "DELIVERY_CUSTOMS": ("Parcel / courier / customs", [
        r"\bcustoms\b", r"\bparcel\b", r"\bcourier\b", r"\bfedex\b", r"delivery (?:failed|pending|on hold)", r"\bpackage\b.*\b(?:held|seized)"]),
    "ELECTRICITY": ("Electricity / utility bill", [
        r"\belectricity\b", r"\bbijli\b", r"बिजली", r"power (?:cut|disconnect)", r"connection (?:will be )?(?:cut|disconnected)",
        r"bill\s*(?:kat|cut)\s*(?:jayega|jaega|ho jayega)", r"\b(?:light|bijli)\s*(?:kat|cut)", r"\beb bill\b", r"मीटर"]),
    "URGENCY": ("Urgency / time pressure", [
        r"\bimmediately\b", r"\burgent(?:ly)?\b", r"within \d+ (?:minutes|mins|hours)", r"\blast chance\b", r"\bturant\b",
        r"\babhi\b", r"\bjaldi\b", r"aaj hi", r"\budane\b", r"तुरंत", r"अभी", r"\btoday\b"]),
    "SECRECY": ("Asks to keep it secret", [
        r"do ?n[o']?t (?:share|tell)", r"kisi ko (?:mat|na) (?:batana|bolna|bataiye)", r"किसी को मत", r"yaarukkum sollatheenga"]),
}
_COMPILED = {k: [re.compile(p, _F) for p in pats] for k, (_, pats) in SIGNALS.items()}
LABEL = {k: v[0] for k, v in SIGNALS.items()}


def find(line: str) -> list[tuple[str, str]]:
    """[(signal code, matched text)] for one line."""
    out = []
    for code, rxs in _COMPILED.items():
        for rx in rxs:
            m = rx.search(line)
            if m:
                out.append((code, m.group(0)))
                break
    return out
