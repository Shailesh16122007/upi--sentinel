"""Entity extraction from text (OCR output, SMS, chat, PDF text, transcripts).

Every entity records: value, normalized form, confidence, the line it came from (locator + context),
and — only when the evidence itself states it — a timestamp with an explicit precision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.services.extraction import lexicon

IST = ZoneInfo("Asia/Kolkata")
MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# Tesseract commonly misreads the rupee sign; these are accepted only when directly followed by digits.
RUPEE_LOOKALIKE = "¥%=€£zZ"
RE_AMOUNT = re.compile(
    r"(?P<cur>₹|rs\.?|inr|rupees|रु[.,]?|रुपये|[" + re.escape(RUPEE_LOOKALIKE) + r"])\s{0,12}(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)"
    r"(?:\s?/-)?(?P<tail>[OoIlSB|]?)", re.I)
RE_AMOUNT_WORD = re.compile(r"(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)\s?(?:rupees|rupaye|rupay|rs\.?|inr|रुपये)(?![a-z])", re.I)
RE_EMAIL = re.compile(r"\b[a-z0-9._%+-]{1,64}@[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63})*\.[a-z]{2,24}\b", re.I)
# Indian (1,23,45,678) or international (1,234,567) digit grouping; anything else is a likely OCR slip
RE_GROUPING_OK = re.compile(r"^(?:\d{1,2}(?:,\d{2})*,\d{3}|\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?$")
RE_BARE_AMOUNT = re.compile(r"^\s*(?P<sym>[^\w\s]{1,2}\s?|[A-Za-z]\s)?(?P<num>\d{1,3}(?:,\d{2,3})+(?:\.\d{1,2})?)\s*$")  # "25,000" alone on a line

RE_DATE_DMY_TEXT = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-/.,]*(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?[\s\-/.,']*(\d{4}|\d{2})\b", re.I)
RE_DATE_MDY_TEXT = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+(\d{1,2}),?\s+(\d{4})\b", re.I)
RE_DATE_NUM = re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4}|\d{2})\b")
RE_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})")
DEVANAGARI_DIGITS = str.maketrans("०१२३४५६७८९", "0123456789")
RE_TIME_ONLY_LINE = re.compile(r"^\s*\d{1,2}[:.]\d{2}\s*(?:[ap]\.?\s?m\.?)?\s*(?:[✓✔]{1,2})?\s*$", re.I)
RE_TIME = re.compile(r"(?<![\d:])(\d{1,2})[:.](\d{2})(?::(\d{2}))?\s*([ap]\.?\s?m\.?)?(?![\d])", re.I)

REF_LABEL = re.compile(
    r"(?P<label>utr(?:\s*(?:no|number))?|rrn|upi\s*(?:ref(?:erence)?|transaction\s*id|txn\s*id)(?:\s*(?:no|number|id))?|"
    r"ref(?:erence)?(?:\s*(?:no|number|id))?|upi(?=\s*[:#]\s*\d)|transaction\s*id|txn\s*(?:id|no)|order\s*id|google\s*pay\s*upi\s*transaction\s*id)"
    r"\.?\s*[:#\-]?\s*(?P<val>[A-Z0-9]{6,24})\b", re.I)
RE_UTR_BARE = re.compile(r"(?<![\d.,])\d{12}(?![\d,]|\.\d)")
RE_UPI = re.compile(r"\b[a-z0-9][a-z0-9._-]{1,63}@[a-z]{2,32}\b(?![-.]?[a-z0-9])", re.I)
# Common UPI handles. An unknown handle is still extracted but marked for review (OCR often clips the last letter).
UPI_HANDLES = set("""ybl ibl axl okaxis oksbi okhdfcbank okicici paytm pthdfc ptsbi ptyes ptaxis apl yapl rapl abfspay axisbank
    axisb upi icici hdfcbank sbi kotak kmbl idfcbank idfcfirst indus federal fbl yesbank yesg rbl aubank citi hsbc sc dbs
    pnb barodampay boi cnrb centralbank unionbank uboi ubi idbi iob indianbank allbank kbl kvb tjsb dlb jupiteraxis
    slice freecharge mobikwik ikwik airtel airtelpaymentsbank jio postbank waaxis wahdfcbank wasbi waicici naviaxis
    amazonpay apay timecosmos superyes tapicici fam okbizaxis oneyes""".split())
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


RE_BALANCE = re.compile(r"\b(?:opening|closing|available|avl\.?|avail\.?|current|ledger)\s*(?:bal(?:ance)?|bal\.)|\bbalance\b|\bbal\b\s*[:\-]|शेष", re.I)
RE_CREDIT = re.compile(r"\bcr\b|\bcredit(?:ed)?\b|\breceived\b|\brefund(?:ed)?\b|जमा", re.I)
RE_DEBIT = re.compile(r"\bdr\b|\bdebit(?:ed)?\b|\bwithdrawn\b|\bpaid\b|\bsent\b|\btransferred\b|डेबिट|कटौती", re.I)


def _direction(line: str) -> dict:
    """Balance figures are not payments; credits are not the money the customer lost."""
    if RE_BALANCE.search(line):
        return {"balance": True}
    cr, dr = RE_CREDIT.search(line), RE_DEBIT.search(line)
    if cr and not dr:
        return {"direction": "CREDIT"}
    if dr and not cr:
        return {"direction": "DEBIT"}
    return {}


def amount_review(num: str, tail: str, after: str, method: str) -> str | None:
    """Reasons an extracted amount should be checked by a person instead of trusted."""
    if "," in num and not RE_GROUPING_OK.match(num):
        return f"Unusual digit grouping '{num}' — possibly misread"
    if method in ("OCR", "PDF_OCR") and (tail or (after and after.isalpha() and after.upper() in "OILSB")):
        return f"Letter next to the digits ('{num}{tail or after}') — possibly misread"
    return None


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def extract(text: str, *, base_conf: float = 1.0, method: str = "TEXT", line_conf: list[float] | None = None,
            locator_prefix: str = "line") -> list[Ent]:
    ents: list[Ent] = []
    seen: set[tuple[str, str, str]] = set()
    text = text.translate(DEVANAGARI_DIGITS)
    if method in ("OCR", "PDF_OCR"):
        text = re.sub(r"(?<=[a-z])\|(?=[\s.,]|$)", "l", text, flags=re.M)  # 'axl' read as 'ax|'
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
    bubble: list[str] = []  # text lines since the last time-only line (a chat message before its timestamp)
    for i, raw in enumerate(lines):
        line = raw.strip()
        if not line:
            continue
        prev_line, prev = prev, line
        lc = base_conf * (line_conf[i] if line_conf and i < len(line_conf) else 1.0)
        loc = f"{locator_prefix} {i + 1}"
        low = line.lower()
        ctx = line[:300]
        if RE_TIME_ONLY_LINE.match(line):
            if bubble:
                ctx = " ".join(bubble)[:300]
            bubble = []
        elif parse_dates(line) and len(line) <= 30:  # a date header starts a new group of messages
            bubble = []
        else:
            bubble = (bubble + [line])[-3:]

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
            attrs.update(_direction(line))
            conf = 0.75 if lookalike else 0.95
            review = amount_review(m["num"], m["tail"], line[m.end():m.end() + 1], method)
            if review:
                attrs["needs_review"] = review
                conf = min(conf, 0.5)
            add(Ent("AMOUNT", m[0].strip(), f"{v:.2f}", round(conf * lc, 3), loc, ctx, attrs=attrs))
        for m in RE_AMOUNT_WORD.finditer(line):
            v = _num(m["num"])
            if v > 0:
                add(Ent("AMOUNT", m[0].strip(), f"{v:.2f}", round(0.9 * lc, 3), loc, ctx, attrs=_direction(line)))
        if method in ("OCR",) and RE_BARE_AMOUNT.match(line) and not any(e.type == "AMOUNT" and e.locator == loc for e in ents):
            bm = RE_BARE_AMOUNT.match(line)
            num = bm["num"]
            v = _num(num)
            why = (f"The currency symbol was not read clearly ('{bm['sym'].strip()}')" if bm["sym"] else
                   "No currency symbol was read — the first digit may be a misread ₹ sign" if num[0] in "4271"
                   else "No currency symbol was read next to this number")
            add(Ent("AMOUNT", line, f"{v:.2f}", round(0.45 * lc, 3), loc, ctx, attrs={"no_currency_marker": True, "needs_review": why}))

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
        emails = {m[0].lower() for m in RE_EMAIL.finditer(line)}
        for em in emails:
            add(Ent("EMAIL", em, em, round(0.9 * lc, 3), loc, ctx))
        for m in RE_UPI.finditer(line):
            if not any(m[0] in u for u in urls) and not any(m[0].lower() in em for em in emails):
                handle = m[0].split("@", 1)[1].lower()
                attrs = {} if handle in UPI_HANDLES else {"needs_review": f"Unrecognised UPI handle '@{handle}' — check against the image"}
                add(Ent("UPI_ID", m[0], m[0].lower(), round((0.93 if not attrs else 0.6) * lc, 3), loc, ctx, attrs=attrs))
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
            if any(u.lower().startswith(name.lower()) for u in RE_UPI.findall(line)):
                continue  # "Paid to ravi.store@okhdfcbank": the name is part of the UPI ID
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
        for code, matched in lexicon.find(line):
            add(Ent("LANGUAGE_SIGNAL", lexicon.LABEL[code], code, round(0.75 * lc, 3), loc, ctx, attrs={"matched": matched}))

    # Labels and values are often split over two lines by OCR ("UPI Ref No" / "427613847291"): match across pairs.
    for i in range(len(lines) - 1):
        a, b = lines[i].strip(), lines[i + 1].strip()
        if not a or not b:
            continue
        joined = f"{a} {b}"
        lc = base_conf * min((line_conf[i] if line_conf and i < len(line_conf) else 1.0),
                             (line_conf[i + 1] if line_conf and i + 1 < len(line_conf) else 1.0))
        loc = f"{locator_prefix}s {i + 1}-{i + 2}"
        for m in REF_LABEL.finditer(joined):
            if m.start("val") < len(a) + 1 or not any(c.isdigit() for c in m["val"]):
                continue  # only references whose label is on line a and value on line b
            label, val = m["label"].lower(), m["val"].upper()
            if any(e.type in ("UTR", "UPI_REF", "TXN_ID") and e.normalized == val and not e.attrs.get("unlabelled_12_digit") for e in ents):
                continue
            etype = "UTR" if ("utr" in label or "rrn" in label) else "TXN_ID" if ("transaction" in label or "txn" in label or "order" in label) else "UPI_REF"
            ents[:] = [e for e in ents if not (e.normalized == val and e.attrs.get("unlabelled_12_digit"))]
            add(Ent(etype, f"{m['label'].strip()}: {m['val']}", val, round(0.93 * lc, 3), loc, joined[:300], attrs={"label": m["label"].strip()}))
        have = {e.normalized for e in ents if e.type == "LANGUAGE_SIGNAL" and e.locator in (f"{locator_prefix} {i + 1}", f"{locator_prefix} {i + 2}")}
        for code, matched in lexicon.find(joined):
            if code not in have:
                add(Ent("LANGUAGE_SIGNAL", lexicon.LABEL[code], code, round(0.7 * lc, 3), loc, joined[:300], attrs={"matched": matched}))

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
