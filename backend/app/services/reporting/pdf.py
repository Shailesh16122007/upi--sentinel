"""Role-specific case reports (ReportLab). Every factual row cites evidence codes (E1, E2 ...).

VICTIM: plain language. BANK: detailed investigation. CYBER: investigation + bank work + related cases + export."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.services.extraction.entities import IST

FONT_DIR = Path(__file__).parent / "fonts"
try:  # DejaVu has the ₹ glyph; Helvetica does not
    pdfmetrics.registerFont(TTFont("Sans", str(FONT_DIR / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("Sans-Bold", str(FONT_DIR / "DejaVuSans-Bold.ttf")))
    pdfmetrics.registerFontFamily("Sans", normal="Sans", bold="Sans-Bold")
    F, FB, RUPEE = "Sans", "Sans-Bold", "₹"
except Exception:  # pragma: no cover
    F, FB, RUPEE = "Helvetica", "Helvetica-Bold", "INR "

INK = colors.HexColor("#0F1B2D")
MUTED = colors.HexColor("#5B6576")
RULE = colors.HexColor("#D5DAE1")
HEAD = colors.HexColor("#EEF1F5")
CAT_COLOR = {"SUPPORTING": "#1F5FAD", "CONTRADICTORY": "#B42318", "CONTEXTUAL": "#5B6576", "MISSING": "#9A6700"}

H1 = ParagraphStyle("h1", fontName=FB, fontSize=16, leading=20, textColor=INK, spaceAfter=2)
H2 = ParagraphStyle("h2", fontName=FB, fontSize=10.5, leading=14, textColor=INK, spaceBefore=12, spaceAfter=5)
BODY = ParagraphStyle("b", fontName=F, fontSize=8.6, leading=11.8, textColor=INK)
SMALL = ParagraphStyle("s", fontName=F, fontSize=7.4, leading=9.6, textColor=MUTED)
CELL = ParagraphStyle("c", fontName=F, fontSize=7.6, leading=9.8, textColor=INK)
CELLB = ParagraphStyle("cb", parent=CELL, fontName=FB)


def r(s: str) -> str:
    return str(s).replace("₹", RUPEE)


def P(t, st=BODY):
    return Paragraph(escape(r(t if t not in (None, "") else "—")), st)


def T(rows, widths, header=True, bold_first_col=False):
    data = []
    for i, row in enumerate(rows):
        data.append([c if isinstance(c, Paragraph) else P(c, CELLB if (header and i == 0) or (bold_first_col and j == 0) else CELL)
                     for j, c in enumerate(row)])
    t = Table(data, colWidths=[w * mm for w in widths], repeatRows=1 if header else 0)
    st = [("GRID", (0, 0), (-1, -1), 0.4, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
          ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
          ("TOPPADDING", (0, 0), (-1, -1), 2.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5)]
    if header:
        st.append(("BACKGROUND", (0, 0), (-1, 0), HEAD))
    t.setStyle(TableStyle(st))
    return t


def KV(pairs):
    return T([[k, v] for k, v in pairs], [46, 128], header=False, bold_first_col=True)


def _t(d):
    if not d:
        return "—"
    if isinstance(d, str):
        d = datetime.fromisoformat(d)
    d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    return d.astimezone(IST).strftime("%d %b %Y, %I:%M %p IST")


def _src(sources):
    return ", ".join(s["label"] for s in sources if s.get("label")) or "—"



NA = "Not available in submitted evidence"


def _money(v):
    return f"₹{float(v):,.2f}" if v not in (None, "") else NA


class Doc:
    def __init__(self):
        self.s: list = []
        self.n = 0

    def h(self, title):
        self.n += 1
        self.s.append(P(f"{self.n}. {title}", H2))

    def p(self, text, st=BODY):
        self.s.append(P(text, st))

    def table(self, rows, widths, empty="None identified from the submitted evidence."):
        self.s.append(T(rows, widths) if len(rows) > 1 else P(empty))


def _field_rows(data, fields_spec):
    d = data["disputed"]
    fs = (data["analysis"] or {}).get("field_status") or {}
    rows = []
    for name, key, fmt in fields_spec:
        vals = (d or {}).get("fields", {}).get(key, []) if d else []
        if not vals:
            if key == "time" and d and d.get("time_of_day"):
                rows.append([name, f"{d['time_of_day']} — date unavailable", "—", fs.get(key, {}).get("label", "")])
            else:
                rows.append([name, NA, "—", fs.get(key, {}).get("label", "Not found in submitted evidence")])
            continue
        uniq = {}
        for v in vals:
            uniq.setdefault(str(v["value"]), []).append(data["codes"].get(v["evidence_id"], "?"))
        txt = "  |  ".join(f"{fmt(k)}" for k in uniq)
        src = ", ".join(dict.fromkeys(c for cs in uniq.values() for c in cs))
        rows.append([name, txt, src, fs.get(key, {}).get("label", "")])
    return rows


FIELDS = [("Amount", "amount", lambda v: f"₹{float(v):,.2f}"), ("Date & time", "time", _t), ("Reference / UTR", "reference", str),
          ("Beneficiary UPI ID", "beneficiary_vpa", str), ("Beneficiary name", "beneficiary_name", str), ("Status", "status", str),
          ("Channel", "channel", str), ("Account", "account", str), ("Bank", "bank", str)]


def _victim(doc: Doc, data):
    c, a = data["case"], data["analysis"] or {}
    vv = a.get("victim") or {}
    doc.h("Your case")
    doc.s.append(KV([("Case ID", c["ref"]), ("Case status", c["victim_status"]), ("Submitted", _t(c["submitted_at"]) if c["submitted_at"] else "Not submitted yet"),
                     ("Report version", data.get("version", 1))]))
    doc.h("What you told us")
    doc.p(f"“{c['statement']}”")
    doc.h("The payment you are reporting")
    doc.table([["Detail", "What we found", "From", "How sure"]] + _field_rows(data, FIELDS[:5]), [34, 70, 20, 50])
    doc.h("What happened")
    rows = [[t["time_label"].split(" (")[0], t["simple"], ", ".join(t["source_kinds"]) or "—"] for t in data["timeline"]]
    doc.table([["When", "What happened", "Source"]] + rows, [40, 100, 34], "We could not place any events in time yet.")
    doc.p("“≈” means the time is approximate. Times come only from your files or from a time you entered.", SMALL)
    doc.h("What we found")
    for key, title in (("unusual", "Unusual activity"), ("related", "Related evidence"), ("check", "Things the bank will check")):
        items = vv.get(key) or []
        if items:
            doc.p(title, CELLB)
            for x in items:
                doc.p(f"• {x['text']}")
    if not any(vv.get(k) for k in ("unusual", "related", "check")):
        doc.p("Nothing unusual could be identified from the files so far.")
    doc.h("Information still missing")
    miss = vv.get("missing") or []
    doc.table([["Missing information"]] + [[x["text"]] for x in miss], [174], "Nothing important is missing.")
    doc.h("Your files")
    doc.table([["Ref", "File", "Type", "Uploaded", "Fingerprint (SHA-256)", "Status"]] + [
        [e["code"], e["original_name"], e["type_label"], _t(e["uploaded_at"]), e["sha256"][:16] + "…",
         "Read" if e["status"] in ("PROCESSED", "PARTIAL") else "Kept, could not be read"] for e in data["evidence"]],
        [10, 46, 28, 34, 34, 22])
    doc.p("The fingerprint shows your file has not changed since you uploaded it.", SMALL)
    ups = [x for x in data["actions"] if x["victim_message"]]
    if ups:
        doc.h("Case updates")
        doc.table([["When", "Update"]] + [[_t(x["created_at"]), x["victim_message"]] for x in ups], [40, 134])


def _investigation(doc: Doc, data, cyber: bool):
    c, a = data["case"], data["analysis"] or {}
    counts = a.get("counts") or {}
    doc.h("Key findings")
    kf = a.get("key_findings") or []
    doc.table([["#", "Finding", "Source"]] + [[f"{k['n']:02d}", k["text"], _src(k["sources"])] for k in kf], [10, 140, 24])
    doc.h("Case summary")
    doc.s.append(KV([("Case", c["ref"]), ("Status", c["status_label"]), ("Bank", c["bank"] or "—"),
                     ("Customer", f"{data['victim']['name'] or '—'} · {data['victim']['code'] or ''}"),
                     ("Submitted", _t(c["submitted_at"]) if c["submitted_at"] else "Not submitted"),
                     ("Escalated to cyber crime", _t(c["escalated_at"]) if c["escalated_at"] else "No"),
                     ("Claim type (from statement wording)", (c["claim_type"] or "—").replace("_", " ").title()),
                     ("Bank outcome / account action / reversal", f"{c['bank_outcome'] or '—'} / {c['account_action'] or '—'} / {c['reversal_status'] or '—'}"),
                     ("Evidence items", counts.get("evidence", 0)),
                     ("Anomalies / conflicts / missing", f"{counts.get('anomalies', 0)} / {counts.get('conflicts', 0)} / {counts.get('missing', 0)}"),
                     ("Evidence completeness", f"{(a.get('completeness') or {}).get('score', 0)}%")]))
    doc.p(f"Summary ({a.get('summary_engine', 'deterministic')}):", SMALL)
    for x in a.get("summary") or []:
        doc.p(f"• {x['text']}" + (f"  [{', '.join(x['sources'])}]" if x["sources"] else ""))
    doc.h("Customer statement")
    doc.p(f"“{c['statement']}”")
    doc.p(f"Approximate date given: {c['approx_date'] or 'not given'} · Amount given: "
          f"{('₹' + format(c['claimed_amount'], ',.0f')) if c['claimed_amount'] else 'not given'}", SMALL)
    doc.h("Transaction details")
    if data["disputed"]:
        doc.table([["Field", "Value(s)", "Source", "Reliability"]] + _field_rows(data, FIELDS), [30, 74, 20, 50])
        if data["disputed"]["match_basis"]:
            doc.p(f"Sources matched because: {data['disputed']['match_basis']}", SMALL)
    else:
        doc.p("No transaction could be identified from the submitted evidence.")
    if data["other_transactions"]:
        doc.p("Other transactions found in the evidence (not the disputed one): " + "; ".join(
            f"{_money(t['amount'])} {t['reference'] or ''}".strip() for t in data["other_transactions"][:10]), SMALL)
    doc.h("Evidence received")
    doc.table([["Code", "File", "Type", "Received", "SHA-256", "Integrity"]] + [
        [e["code"], e["original_name"] + (" (synthetic)" if e["is_synthetic"] else ""), e["type_label"],
         _t(e["uploaded_at"]), e["sha256"], f"{e['hash_status']}; {e['integrity'] or 'n/a'}"] for e in data["evidence"]],
        [11, 36, 22, 28, 47, 30])
    doc.p("SHA-256 shows each stored file is unchanged since upload; it does not establish that the content was truthful "
          "before upload. Image indicators are technical signals, not proof of editing.", SMALL)
    doc.table([["Code", "Method", "Status", "Language", "Key items extracted"]] + [
        [e["code"], e["method"] or "—", e["status"] + (f" — {e['error']}" if e["error"] else ""), e["language"] or "—", e["key_items"] or "—"]
        for e in data["evidence"]], [11, 26, 40, 22, 75])
    doc.h("Reconstructed timeline")
    doc.table([["Time", "Event", "Basis", "Source"]] + [
        [t["time_label"], t["description"], t["reliability"].title(), ", ".join(x["label"] for x in t["sources"] if x.get("label")) or "—"]
        for t in data["timeline"]], [40, 100, 18, 16])
    doc.p("Documented = stated in a record. Statement = something a person said (unverified). ≈ = approximate time.", SMALL)

    F = data["findings"]
    imp = [f for f in F if f["is_anomaly"] or f["code"] == "MODUS_PATTERN"]
    doc.h("Important findings")
    doc.table([["Finding", "Why it matters", "Certainty", "Source"]] + [
        [f"{f['title']}. {f['detail'] or ''}", f["why"] or "—", f["certainty"] or "—", _src(f["sources"])] for f in imp],
        [62, 70, 18, 24], "No anomalous activity identified.")
    for cat, title in (("SUPPORTING", "Supporting evidence"), ("CONTRADICTORY", "Contradictory evidence")):
        rows = [f for f in F if f["category"] == cat and not f["is_anomaly"]]
        doc.h(title)
        doc.table([["Finding", "Detail", "Certainty", "Source"]] + [[f["title"], f["detail"], f["certainty"] or "—", _src(f["sources"])] for f in rows],
                  [46, 90, 18, 20])
    cf = [f for f in F if f["is_conflict"]]
    doc.h("Evidence conflicts")
    doc.table([["Conflict", "Detail", "Source"]] + [[f["title"], f["detail"], _src(f["sources"])] for f in cf], [48, 106, 20],
              "No conflicts between sources or with the customer's statement were detected.")
    ms = [f for f in F if f["category"] == "MISSING"]
    doc.h("Missing evidence")
    doc.table([["Item", "Why it matters"]] + [[f["title"], f["detail"]] for f in ms], [60, 114], "Nothing material identified as missing.")

    ml = a.get("ml") or {}
    ctx = a.get("context") or {}
    doc.h("Transaction history analysis")
    hist = [f for f in F if f["code"] in ("AMOUNT_ANOMALY", "TIME_ANOMALY", "ML_OUTLIER", "BENEFICIARY_PAID_BEFORE")]
    doc.p(f"History rows supplied: {counts.get('history_rows', 0)}.")
    doc.p(("Statistical check: Isolation Forest on " + str(ml.get("history_rows")) + f" past transactions — more unusual than "
           f"{ml.get('more_anomalous_than_pct')}% of them. This score only compares the payment with this customer's own history.")
          if ml.get("available") else f"Statistical check not run — {ml.get('reason', 'no data')}")
    doc.table([["Observation", "Detail"]] + [[f["title"], f["detail"]] for f in hist], [60, 114], "No history-based observations.")
    doc.h("Device / session analysis")
    dev = [f for f in F if f["code"] in ("DEVICE_ANOMALY", "SESSION_ANOMALY", "SEQUENCE_ANOMALY", "AUTH_EVENT_PRESENT")]
    doc.p(f"Device used for the payment: {ctx.get('txn_device') or NA}.")
    doc.table([["Observation", "Detail", "Source"]] + [[f["title"], f["detail"], _src(f["sources"])] for f in dev], [50, 104, 20],
              "No device, login or authentication records were submitted.")
    doc.h("Beneficiary analysis")
    d = data["disputed"] or {}
    ben = d.get("beneficiary_vpa") or d.get("beneficiary")
    doc.p(f"Beneficiary: {ben or NA}. " + ("Seen in customer history: " + ("yes" if ctx.get("beneficiary_in_history") else "no")
                                           if "beneficiary_in_history" in ctx else "No history available to compare."))
    doc.h("Related cases")
    doc.table([["Case", "Amount", "Status", "Shared identifier", "Relationship"]] + [
        [r["ref"], _money(r["amount"]), r["status_label"], "; ".join(f"{l['type_label']} {l['value']}" for l in r["links"]),
         "Possible related case" if all(l["status"] == "POSSIBLE" for l in r["links"]) else "Linked by investigator"]
        for r in data["related"]], [30, 26, 30, 58, 30], "No other submitted case shares an identifier with this case.")
    doc.h("Mule network findings")
    doc.table([["Identifier", "Cases", "Total disputed", "Window"]] + [
        [f"{c_['type_label']} {c_['value']}", c_["case_count"], _money(c_["total_amount"]) + (
            f" ({c_['amount_known_cases']} with known amount)" if c_["amount_known_cases"] < c_["case_count"] else ""),
         f"{c_['window_hours']} h" if c_["window_hours"] is not None else "—"] for c_ in data["clusters"]],
        [64, 18, 58, 34], "No related transaction cluster detected.")
    doc.p("Totals are computed from the linked case records. A cluster means cases share an identifier; it does not by "
          "itself establish an organised network.", SMALL)
    doc.h("Investigation notes (human-entered, kept separate from system findings)")
    doc.table([["Time", "Author", "Note"]] + [
        [_t(n["created_at"]), f"{n['author']} ({(n['role'] or '').title()})",
         (f"On finding “{n['finding_title']}” — {n['assessment'].replace('_', ' ').lower()}: " if n["finding_title"] else "") + n["body"]]
        for n in data["notes"]], [36, 36, 102], "No investigator notes.")
    doc.h("Case actions")
    doc.table([["Time", "By", "Action", "Note"]] + [[_t(x["created_at"]), x["role"].title(), x["label"], x["note"] or ""] for x in data["actions"]],
              [36, 20, 46, 72], "No actions recorded.")
    doc.h("Recommended next investigation steps")
    doc.table([["Step", "Because"]] + [[x["text"], x["basis"]] for x in data["next_steps"]], [120, 54], "No further steps suggested.")
    doc.p("Suggestions are generated from gaps and findings in the evidence. The decision rests with the investigator.", SMALL)
    if cyber and data.get("export"):
        ex = data["export"]
        doc.h("Structured export (for manual entry / integration)")
        doc.p(ex["label"], SMALL)
        t = ex["transaction"]
        doc.s.append(KV([("Victim", f"{ex['victim_details']['name']} · {ex['victim_details']['phone']}"),
                         ("Transaction date", t["date"]), ("Amount (INR)", t["amount_inr"]), ("UTR / reference", t["utr_or_reference"]),
                         ("Transaction ID", t["transaction_id"]), ("Beneficiary UPI ID", t["beneficiary_upi_id"]),
                         ("Beneficiary account", t["beneficiary_account"]), ("Suspect numbers", ", ".join(ex["suspect_contact_numbers"]) if isinstance(ex["suspect_contact_numbers"], list) else ex["suspect_contact_numbers"]),
                         ("Fraud pattern", ", ".join(ex["fraud_pattern"]) if isinstance(ex["fraud_pattern"], list) else ex["fraud_pattern"]),
                         ("Evidence references", ", ".join(e["code"] for e in ex["evidence_references"]))]))
    doc.h("Audit trail")
    doc.table([["Time", "Action", "Actor", "Result"]] + [[_t(x["created_at"]), x["action"], f"{x['actor']}" + (f" ({x['role'].title()})" if x["role"] else ""), x["result"]]
                                                         for x in data["audit"]], [36, 40, 44, 54])


def build(path: Path, data: dict) -> None:
    c = data["case"]
    aud = data["audience"]
    synthetic = c["is_synthetic"]
    title = {"VICTIM": "Your case report", "BANK": "Bank investigation report", "CYBER": "Cyber crime investigation report"}[aud]
    doc = Doc()
    doc.s.append(P(f"UPI Sentinel — {title}", H1))
    doc.s.append(P(f"{c['ref']} · version {data.get('version', 1)} · generated {_t(data['generated_at'])} · status "
                   f"{c['victim_status'] if aud == 'VICTIM' else c['status_label']}", SMALL))
    if synthetic:
        doc.s.append(Spacer(1, 4))
        doc.s.append(Paragraph("<font color='#B42318'><b>SYNTHETIC DEMONSTRATION DATA — not a real dispute.</b></font>", BODY))
    doc.s.append(Spacer(1, 4))
    if aud == "VICTIM":
        doc.p("This report was prepared from the information and files you gave us. It is not a decision on your case. "
              "Your bank and, if needed, the cyber crime authority will review it.", SMALL)
        _victim(doc, data)
    else:
        doc.p("This report organises the submitted evidence. Every statement cites its source (E-codes). It does not determine "
              "whether fraud occurred; that decision belongs to the authorised investigator. Statements from calls and messages "
              "are unverified.", SMALL)
        _investigation(doc, data, aud == "CYBER")
        doc.s += [Spacer(1, 10), KeepTogether([P("Investigator decision (to be completed by the authorised investigator)", H2),
                                               P("Decision: ______________________   Name: ______________________   Date: ____________")])]

    def frame(canvas, d):
        canvas.saveState()
        canvas.setFont(F, 6.8)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"UPI Sentinel · {c['ref']} · v{data.get('version', 1)} · Confidential — contains personal and financial information")
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {d.page}")
        if synthetic:
            canvas.setFillColor(colors.HexColor("#B42318"))
            canvas.drawString(18 * mm, 288 * mm, "SYNTHETIC DEMONSTRATION DATA")
        canvas.restoreState()

    sd = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm,
                           bottomMargin=16 * mm, title=f"{title} {c['ref']}", author="UPI Sentinel")
    sd.build(doc.s, onFirstPage=frame, onLaterPages=frame)
