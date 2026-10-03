"""Entity extraction from text (OCR output, SMS, chat, PDF text, transcripts).

Every entity records: value, normalized form, confidence, the line it came from (locator + context),
and — only when the evidence itself states it — a timestamp with an explicit precision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# Tesseract commonly misreads the rupee sign; these are accepted only when directly followed by digits.
RUPEE_LOOKALIKE = "¥%=€£zZ"
RE_AMOUNT = re.compile(
    r"(?P<cur>₹|rs\.?|inr|rupees|[" + re.escape(RUPEE_LOOKALIKE) + r"])\s?(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    r"(?:\s?/-)?", re.I)
RE_AMOUNT_WORD = re.compile(r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s?(?:rupees|rs\.?|inr)\b", re.I)
RE_BARE_AMOUNT = re.compile(r"^\s*(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?)\s*$")  # "25,000" alone on a line

RE_DATE_DMY_TEXT = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/.,]*(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?[\s\-/.,']*(\d{4}|\d{2})\b", re.I)
RE_DATE_MDY_TEXT = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
RE_DATE_NUM = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})\b")
RE_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})")
RE_TIME = re.compile(r"(?<![\d:])(\d{1,2})[:.](\d{2})(?::(\d{2}))?\s*([ap]\.?\s?m\.?)?(?![\d])", re.I)

REF_LABEL = re.compile(
    r"(?P<label>utr(?:\s*(?:no|number))?|rrn|upi\s*(?:ref(?:erence)?|transaction\s*id|txn\s*id)(?:\s*(?:no|number|id))?|"
    r"ref(?:erence)?(?:\s*(?:no|number|id))?|upi(?=\s*[:#]\s*\d)|transaction\s*id|txn\s*(?:id|no)|order\s*id|google\s*pay\s*upi\s*transaction\s*id)"
    r"\.?\s*[:#\-]?\s*(?P<val>[A-Z0-9]{6,24})\b", re.I)
RE_UTR_BARE = re.compile(r"(?<![\d.,])\d{12}(?![\d,]|\.\d)")
RE_UPI = re.compile(r"\b[a-z0-9][a-z0-9._-]{1,63}@[a-z]{2,32}\b(?!\.[a-z])", re.I)
RE_PHONE = re.compile(r"(?<![\d])(?:\+?91[\s-]?)?([6-9]\d{4})[\s-]?(\d{5})(?![\d])")
RE_ACCOUNT = re.compile(r"(?:a/?c|acct|account)(?:\s*(?:no\.?|number|ending(?:\s*with)?))?\s*[:#]?\s*((?:[xX*]{2,}|\.{2,})\s?\d{3,6}|\d{9,18})", re.I)
RE_URL = re.compile(r"\b(?:https?://|www\.)[^\s<>\"')]+|\b[a-z0-9-]+\.(?:in|com|co\.in|net|org|xyz|top|online|site|info|link)/[^\s]*", re.I)
RE_PAYEE_LABEL_ONLY = re.compile(r"^(?:paid\s+to|sent\s+to|to|payee|beneficiary|transferred\s+to|paying)\s*:?$", re.I)
RE_MASKED_ACCT = re.compile(r"\b(?:[xX*]{2,4})(\d{4})\b")
RE_PAYEE = re.compile(r"(?:paid\s+to|sent\s+to|to\s*:|transferred\s+to|credited\s+to|payee\s*:?|beneficiary\s*:?|merchant\s*:?)\s*(?P<name>[A-Z][A-Za-z.&' ]{2,40}?)(?=\s*(?:\n|$|,|\.|\bon\b|\bvia\b|\bupi\b|\(|\d))", re.I)

BANKS = [
    ("State Bank of India", r"state bank of india|\bsbi\b"), ("HDFC Bank", r"\bhdfc\b"), ("ICICI Bank", r"\bicici\b"),
    ("Axis Bank", r"\baxis\s*bank\b"), ("Kotak Mahindra Bank", r"\bkotak\b"), ("Punjab National Bank", r"punjab national|\bpnb\b"),
    ("Bank of Baroda", r"bank of baroda|\bbob\b"), ("Canara Bank", r"\bcanara\b"), ("Union Bank of India", r"union bank"),
    ("IDFC FIRST Bank", r"\bidfc\b"), ("Yes Bank", r"\byes\s*bank\b"), ("IndusInd Bank", r"\bindusind\b"),
    ("Federal Bank", r"federal bank"), ("Bank of India", r"\bbank of india\b"), ("Indian Bank", r"\bindian bank\b"),
    ("Paytm Payments Bank", r"paytm payments bank"), ("Airtel Payments Bank", r"airtel payments bank"),
    ("India Post Payments Bank", r"india post payments|\bippb\b"),
]
APPS = [("Google Pay", r"google\s*pay|\bgpay\b"), ("PhonePe", r"phone\s*pe"), ("Paytm", r"\bpaytm\b(?!\s*payments bank)"),
        ("BHIM", r"\bbhim\b"), ("Amazon Pay", r"amazon\s*pay"), ("CRED", r"\bcred\b")]
STATUS = [("DEBITED", r"\bdebited\b|\bdebit\b|\bwithdrawn\b|\bsent\b|\bpaid\b"), ("CREDITED", r"\bcredited\b|\breceived\b"),
          ("SUCCESS", r"\bsuccessful(?:ly)?\b|\bsuccess\b|\bcompleted\b"), ("FAILED", r"\bfailed\b|\bdeclined\b|\bunsuccessful\b"),
          ("PENDING", r"\bpending\b|\bprocessing\b"), ("REVERSED", r"\breversed\b|\brefunded\b|\breversal\b")]
CHANNELS = [("UPI", r"\bupi\b"), ("IMPS", r"\bimps\b"), ("NEFT", r"\bneft\b"), ("RTGS", r"\brtgs\b"), ("AEPS", r"\baeps\b"),
            ("COLLECT_REQUEST", r"collect request|payment request|approve (?:the )?request")]
LANGUAGE = {
    "URGENCY": r"\bimmediately\b|\burgent(?:ly)?\b|\btoday\b|\bwithin \d+ (?:minutes|hours)\b|\blast chance\b",
    "THREAT": r"\bblock(?:ed)?\b|\bsuspend(?:ed)?\b|\bfrozen\b|\bfreeze\b|\blegal action\b|\barrest\b|\bdeactivat",
    "CREDENTIAL_REQUEST": r"\botp\b|\bupi pin\b|\bmpin\b|\bpin\b|\bcvv\b|\bpassword\b",
    "KYC": r"\bkyc\b|\bpan card\b|\baadhaar\b",
    "REMOTE_ACCESS": r"anydesk|teamviewer|quick ?support|screen ?shar|rustdesk",
    "REFUND_REWARD": r"\brefund\b|\bcashback\b|\breward\b|\bprize\b|\blottery\b|\bcredited back\b",
    "IMPERSONATION": r"calling from (?:your |the )?\w*\s?(?:bank|kyc|customer care|support)|\bbank (?:officer|executive|manager)\b|\brbi\b|\bcyber cell\b",
}


@dataclass
class Ent:
    type: str
    value: str
    normalized: str | None
    confidence: float
    locator: str | None = None
    context: str | None = None
    occurred_at: datetime | None = None
    time_precision: str = "NONE"
    attrs: dict = field(default_factory=dict)


def _year(y: str) -> int:
    v = int(y)
    return v + 2000 if v < 100 else v


def parse_dates(line: str) -> list[tuple[date, str, tuple[int, int]]]:
    out = []
    for m in RE_DATE_ISO.finditer(line):
        try:
            out.append((date(int(m[1]), int(m[2]), int(m[3])), m[0], m.span()))
        except ValueError:
            pass
    for m in RE_DATE_DMY_TEXT.finditer(line):
        try:
            out.append((date(_year(m[3]), MONTHS[m[2][:3].lower()], int(m[1])), m[0], m.span()))
        except ValueError:
            pass
    for m in RE_DATE_MDY_TEXT.finditer(line):
        try:
            out.append((date(int(m[3]), MONTHS[m[1][:3].lower()], int(m[2])), m[0], m.span()))
        except ValueError:
            pass
    for m in RE_DATE_NUM.finditer(line):
        if any(s[0] <= m.start() < s[1] for _, _, s in out):
            continue
        try:  # Indian convention: day first
            out.append((date(_year(m[3]), int(m[2]), int(m[1])), m[0], m.span()))
        except ValueError:
            pass
    return out


def parse_times(line: str, date_spans: list[tuple[int, int]]) -> list[tuple[time, str]]:
    out = []
    for m in RE_TIME.finditer(line):
        if any(a <= m.start() < b for a, b in date_spans):
            continue
        h, mi, se, ap = int(m[1]), int(m[2]), int(m[3] or 0), (m[4] or "").lower().replace(".", "").replace(" ", "")
        if ap:
            if not 1 <= h <= 12:
                continue
            h = (h % 12) + (12 if ap.startswith("p") else 0)
        elif "." in m[0][:3] and not m[3]:
            continue  # "10.32" without am/pm is too ambiguous (could be an amount)
        if h > 23 or mi > 59 or se > 59:
            continue
        out.append((time(h, mi, se), m[0].strip()))
    return out


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def extract(text: str, *, base_conf: float = 1.0, method: str = "TEXT", line_conf: list[float] | None = None,
            locator_prefix: str = "line") -> list[Ent]:
    ents: list[Ent] = []
    seen: set[tuple[str, str, str]] = set()
    lines = text.splitlines()
    all_dates: list[tuple[date, int]] = []
    time_only: list[Ent] = []

    def add(e: Ent):
        key = (e.type, (e.normalized or e.value).lower(), e.locator or "")
        if key in seen:
            return
        seen.add(key)
        e.attrs.setdefault("method", method)
        ents.append(e)

    prev = ""
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        prev_line, prev = prev, line
        lc = base_conf * (line_conf[i] if line_conf and i < len(line_conf) else 1.0)
        loc = f"{locator_prefix} {i + 1}"
        low = line.lower()
        ctx = line[:300]

        # --- dates & times ---
        dates = parse_dates(line)
        times = parse_times(line, [s for _, _, s in dates])
        for d, raw_d, _ in dates:
            all_dates.append((d, i))
        if dates and times:
            d = dates[0][0]
            for t, raw_t in times:
                dt = datetime.combine(d, t, tzinfo=IST)
                add(Ent("DATETIME", f"{dates[0][1]} {raw_t}", dt.isoformat(), round(0.95 * lc, 3), loc, ctx, dt, "EXACT"))
        else:
            for d, raw_d, _ in dates:
                add(Ent("DATE", raw_d, d.isoformat(), round(0.9 * lc, 3), loc, ctx, None, "DATE_ONLY", {"date": d.isoformat()}))
            for t, raw_t in times:
                e = Ent("TIME", raw_t, t.strftime("%H:%M:%S"), round(0.9 * lc, 3), loc, ctx, None, "TIME_ONLY",
                        {"time": t.strftime("%H:%M:%S")})
                add(e)
                time_only.append(e)

        # --- amounts ---
        for m in RE_AMOUNT.finditer(line):
            cur = m["cur"]
            lookalike = cur in RUPEE_LOOKALIKE
            if lookalike and method not in ("OCR", "PDF_OCR"):
                continue  # only tolerate symbol misreads in OCR output
            v = _num(m["num"])
            if v <= 0:
                continue
            attrs = {"ocr_symbol_misread": cur} if lookalike else {}
            add(Ent("AMOUNT", m[0].strip(), f"{v:.2f}", round((0.75 if lookalike else 0.95) * lc, 3), loc, ctx, attrs=attrs))
        for m in RE_AMOUNT_WORD.finditer(line):
            v = _num(m["num"])
            if v > 0:
                add(Ent("AMOUNT", m[0].strip(), f"{v:.2f}", round(0.9 * lc, 3), loc, ctx))
        if method in ("OCR",) and RE_BARE_AMOUNT.match(line) and not any(e.type == "AMOUNT" and e.locator == loc for e in ents):
            v = _num(RE_BARE_AMOUNT.match(line)["num"])
            add(Ent("AMOUNT", line, f"{v:.2f}", round(0.55 * lc, 3), loc, ctx, attrs={"no_currency_marker": True}))

        # --- references ---
        ref_vals = set()
        for m in REF_LABEL.finditer(line):
            label, val = m["label"].lower(), m["val"].upper()
            if not any(c.isdigit() for c in val):
                continue
            etype = "UTR" if ("utr" in label or "rrn" in label) else "TXN_ID" if ("transaction" in label or "txn" in label or "order" in label) else "UPI_REF"
            ref_vals.add(val)
            add(Ent(etype, f"{m['label'].strip()}: {m['val']}", val, round(0.95 * lc, 3), loc, ctx, attrs={"label": m["label"].strip()}))
        for m in RE_UTR_BARE.finditer(line):
            if m[0] not in ref_vals and not RE_PHONE.fullmatch(m[0]):
                add(Ent("UTR", m[0], m[0], round(0.55 * lc, 3), loc, ctx, attrs={"unlabelled_12_digit": True}))

        # --- identifiers ---
        urls = [u.rstrip(".,;)") for u in RE_URL.findall(line)]
        for u in urls:
            add(Ent("URL", u, u.lower(), round(0.95 * lc, 3), loc, ctx))
        for m in RE_UPI.finditer(line):
            if not any(m[0] in u for u in urls):
                add(Ent("UPI_ID", m[0], m[0].lower(), round(0.93 * lc, 3), loc, ctx))
        for m in RE_PHONE.finditer(line):
            n = m[1] + m[2]
            if n in "".join(ref_vals):
                continue
            add(Ent("PHONE", m[0].strip(), f"+91{n}", round(0.9 * lc, 3), loc, ctx))
        for m in RE_ACCOUNT.finditer(line):
            v = re.sub(r"\s", "", m[1])
            add(Ent("ACCOUNT", m[0].strip(), v.upper().replace("*", "X").replace(".", "X"), round(0.9 * lc, 3), loc, ctx,
                    attrs={"last_digits": re.sub(r"\D", "", v)[-4:]}))
        if RE_PAYEE_LABEL_ONLY.match(prev_line) and re.fullmatch(r"[A-Z][A-Za-z.&' ]{2,40}", line):
            add(Ent("PAYEE", line, line.lower(), round(0.8 * lc, 3), loc, f"{prev_line} / {line}"))
        if not any(e.type == "ACCOUNT" and e.locator == loc for e in ents) and re.search(r"debit|credit|a/?c|account|bank", low):
            for m in RE_MASKED_ACCT.finditer(line):
                add(Ent("ACCOUNT", m[0], f"XX{m[1]}", round(0.8 * lc, 3), loc, ctx, attrs={"last_digits": m[1]}))
        for m in RE_PAYEE.finditer(line):
            name = m["name"].strip(" .")
            if len(name) >= 3 and not re.search(r"\b(your|you|the|this|my)\b", name, re.I):
                add(Ent("PAYEE", name, name.lower(), round(0.8 * lc, 3), loc, ctx))

        # --- vocab ---
        for name, rx in BANKS:
            if re.search(rx, line, re.I):
                add(Ent("BANK", name, name.lower(), round(0.85 * lc, 3), loc, ctx))
        for name, rx in APPS:
            if re.search(rx, line, re.I):
                add(Ent("APP", name, name.lower(), round(0.85 * lc, 3), loc, ctx))
        for name, rx in STATUS:
            if method in ("STT", "PROVIDED_TRANSCRIPT"):
                break  # words like "pending" in conversation are not payment statuses
            if re.search(rx, low):
                add(Ent("STATUS", name, name, round(0.8 * lc, 3), loc, ctx))
        for name, rx in CHANNELS:
            if re.search(rx, low):
                add(Ent("CHANNEL", name, name, round(0.85 * lc, 3), loc, ctx))
        for name, rx in LANGUAGE.items():
            m = re.search(rx, low)
            if m:
                add(Ent("LANGUAGE_SIGNAL", name, name, round(0.75 * lc, 3), loc, ctx, attrs={"matched": m[0]}))

    # A time with no date on its line takes the document's date only if the document states exactly one date.
    distinct = {d for d, _ in all_dates}
    if len(distinct) == 1:
        d = next(iter(distinct))
        for e in time_only:
            t = time.fromisoformat(e.attrs["time"])
            dt = datetime.combine(d, t, tzinfo=IST)
            add(Ent("DATETIME", f"{d.strftime('%d %b %Y')} {e.value}", dt.isoformat(), round(e.confidence * 0.95, 3),
                    e.locator, e.context, dt, "EXACT", {"date_from_other_line": True}))
    return ents
