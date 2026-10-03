"""Dispute investigation report (ReportLab). Every factual row cites evidence codes (E1, E2 ...)."""
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


def build(path: Path, data: dict) -> None:
    c, a = data["case"], data["analysis"]
    s: list = []
    synthetic = c["is_synthetic"]
    s.append(P("UPI Sentinel — Dispute Investigation Report", H1))
    s.append(P(f"{c['ref']} · generated {_t(datetime.now(timezone.utc))} · status {c['status'].replace('_', ' ')}", SMALL))
    if synthetic:
        s.append(Spacer(1, 4))
        s.append(Paragraph("<font color='#B42318'><b>SYNTHETIC DEMONSTRATION DATA — not a real dispute.</b></font>", BODY))
    s.append(Spacer(1, 4))
    s.append(P("This report organises the submitted evidence. It does not determine whether fraud occurred; that decision "
               "belongs to the authorised investigator. Statements from calls and messages are unverified.", SMALL))

    d = data["disputed"]
    counts = a["counts"]
    s += [P("1. Case information", H2), KV([
        ("Case", c["ref"]), ("Status", c["status"].replace("_", " ")), ("Filed", _t(c["created_at"])),
        ("Claim type (from statement wording)", (c["claim_type"] or "—").replace("_", " ").title()),
        ("Evidence items", counts["evidence"]), ("Anomalies / conflicts / missing", f"{counts['anomalies']} / {counts['conflicts']} / {counts['missing']}"),
        ("Evidence completeness", f"{a['completeness']['score']}%")])]
    s += [P("2. Customer statement", H2), P(f"“{c['statement']}”"),
          P(f"Approximate date given: {c['approx_date'] or 'not given'} · Amount given: "
            f"{('₹' + format(c['claimed_amount'], ',.0f')) if c['claimed_amount'] else 'not given'}", SMALL)]

    s.append(P("3. Disputed transaction", H2))
    if d:
        conflicts = {f["data"].get("field") for f in data["findings"] if f["code"].startswith("SOURCE_CONFLICT")}
        def fld(name, key, fmt=lambda v: v):
            vals = d["fields"].get(key, [])
            if not vals:
                return [name, "Not available in submitted evidence", "—"]
            uniq = {}
            for v in vals:
                uniq.setdefault(str(v["value"]), []).append(data["codes"][v["evidence_id"]])
            txt = "  |  ".join(f"{fmt(k)} [{', '.join(dict.fromkeys(cs))}]" for k, cs in uniq.items())
            flag = "CONFLICT — review" if key in conflicts or (key == "time" and "time" in conflicts) else "Consistent" if len(uniq) == 1 else "Multiple values"
            return [name, txt, flag]
        s.append(T([["Field", "Value(s) [source]", "Agreement"],
                    fld("Amount", "amount", lambda v: f"₹{float(v):,.2f}"),
                    fld("Date & time", "time", _t),
                    fld("Reference / UTR", "reference"),
                    fld("Beneficiary VPA", "beneficiary_vpa"),
                    fld("Beneficiary name", "beneficiary_name"),
                    fld("Status", "status"),
                    fld("Channel", "channel"),
                    fld("Account", "account"),
                    fld("Bank", "bank")], [34, 110, 30]))
        if d["match_basis"]:
            s.append(P(f"Sources matched because: {d['match_basis']}", SMALL))
    else:
        s.append(P("No transaction could be identified from the submitted evidence."))

    s += [P("4. Submitted evidence", H2), T([["Code", "File", "Type", "Received", "SHA-256"]] + [
        [e["code"], e["original_name"] + (" (synthetic)" if e["is_synthetic"] else ""), (e["subtype"] or e["kind"]).replace("_", " ").title(),
         _t(e["uploaded_at"]), e["sha256"]] for e in data["evidence"]], [12, 44, 28, 34, 56])]

    s += [P("5. Evidence extraction summary", H2), T([["Code", "Method", "Status", "Key items extracted"]] + [
        [e["code"], e["method"] or "—", e["status"] + (f" — {e['error']}" if e["error"] else ""), e["key_items"] or "—"]
        for e in data["evidence"]], [12, 30, 44, 88]),
          P("Audio-derived items are statements extracted from audio, not established facts.", SMALL)]

    s += [P("6. Timeline", H2), T([["Time", "Event", "Basis", "Source"]] + [
        [t["time_label"], t["description"], t["reliability"].title(), ", ".join(x["label"] for x in t["sources"] if x.get("label")) or "—"]
        for t in data["timeline"]], [40, 100, 18, 16]),
          P("Documented = stated in a record. Statement = something a person said. ≈ = approximate time.", SMALL)]

    n = 7
    for cat, title in (("SUPPORTING", "Supporting evidence"), ("CONTRADICTORY", "Contradictory evidence"), ("CONTEXTUAL", "Contextual evidence")):
        rows = [f for f in data["findings"] if f["category"] == cat]
        s.append(P(f"{n}. {title}", H2))
        s.append(T([["Finding", "Detail", "Source"]] + [[f["title"], f["detail"], _src(f["sources"])] for f in rows], [48, 106, 20])
                 if rows else P("None identified from the submitted evidence."))
        n += 1

    an = [f for f in data["findings"] if f["is_anomaly"]]
    s.append(P("10. Anomalies (anomalous activity — not a fraud determination)", H2))
    s.append(T([["Anomaly", "Detail", "Source"]] + [[f["title"], f["detail"], _src(f["sources"])] for f in an], [48, 106, 20]) if an
             else P("No anomalous activity identified." + ("" if a["counts"]["history_rows"] else " No transaction history was provided, so amount/time/beneficiary comparisons were not possible.")))
    ml = a["ml"]
    s.append(P(("ML check: " + (f"Isolation Forest on {ml['history_rows']} historical transactions — more unusual than {ml['more_anomalous_than_pct']}% "
                                f"of them (score {ml['anomaly_score']}, outlier: {'yes' if ml['is_outlier'] else 'no'}).")
                if ml.get("available") else f"ML analysis unavailable — {ml.get('reason')}"), SMALL))

    cf = [f for f in data["findings"] if f["is_conflict"]]
    s.append(P("11. Evidence conflicts", H2))
    s.append(T([["Conflict", "Detail", "Source"]] + [[f["title"], f["detail"], _src(f["sources"])] for f in cf], [48, 106, 20]) if cf
             else P("No conflicts between sources or with the customer's statement were detected."))

    ms = [f for f in data["findings"] if f["category"] == "MISSING"]
    s.append(P("12. Missing evidence", H2))
    s.append(T([["Item", "Why it matters"]] + [[f["title"], f["detail"]] for f in ms], [60, 114]) if ms else P("Nothing material identified as missing."))

    comp = a["completeness"]
    s += [P("13. Evidence completeness", H2), P(f"Score: {comp['score']}% ({comp['earned']} of {comp['total']} weighted points)"),
          T([["Category", "Weight", "Earned", "Status", "Basis"]] + [[i["label"], i["weight"], i["earned"], i["status"], i["basis"] or "—"]
                                                                    for i in comp["items"]], [52, 14, 14, 18, 76]),
          P(comp["method"], SMALL)]

    s += [P("14. Investigation summary", H2), P(f"Generated by: {a['summary_engine']}", SMALL)]
    for x in a["summary"]:
        s.append(P(f"• {x['text']}" + (f"  [{', '.join(x['sources'])}]" if x["sources"] else "")))

    s.append(P("15. Investigator notes (human-entered, not system-generated)", H2))
    s.append(T([["Time", "Author", "Note"]] + [[_t(x["created_at"]), x["author"], x["body"]] for x in data["notes"]], [40, 26, 108])
             if data["notes"] else P("No investigator notes."))

    s.append(P("16. Audit trail", H2))
    s.append(T([["Time", "Action", "Actor", "Result"]] + [[_t(x["created_at"]), x["action"], x["actor"], x["result"]] for x in data["audit"]],
               [40, 44, 28, 62]))
    s += [Spacer(1, 10), KeepTogether([P("Investigator decision (to be completed by the authorised investigator)", H2),
                                        P("Decision: ______________________   Name: ______________________   Date: ____________")])]

    def frame(canvas, doc):
        canvas.saveState()
        canvas.setFont(F, 6.8)
        canvas.setFillColor(MUTED)
        canvas.drawString(18 * mm, 10 * mm, f"UPI Sentinel · {c['ref']} · Confidential — contains personal and financial information")
        canvas.drawRightString(192 * mm, 10 * mm, f"Page {doc.page}")
        if synthetic:
            canvas.setFillColor(colors.HexColor("#B42318"))
            canvas.drawString(18 * mm, 288 * mm, "SYNTHETIC DEMONSTRATION DATA")
        canvas.restoreState()

    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=15 * mm,
                            bottomMargin=16 * mm, title=f"Dispute investigation {c['ref']}", author="UPI Sentinel")
    doc.build(s, onFirstPage=frame, onLaterPages=frame)
