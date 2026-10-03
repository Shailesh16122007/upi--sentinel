"""Dispute investigation: the spec's acceptance workflow, run against the real pipeline."""
import io
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.services.audio import stt
from tests.conftest import H

SAMPLES = Path(__file__).resolve().parents[1] / "sample_uploads"
API = "/api/v1"


def new_case(client, statement="₹25,000 was transferred from my account. I did not intend to make this payment.", **kw):
    r = client.post(f"{API}/cases", json={"statement": statement, **kw}, headers=H)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(client, cid, *names, **form):
    files = [("files", (n, (SAMPLES / n).read_bytes())) for n in names]
    r = client.post(f"{API}/cases/{cid}/evidence", files=files, data=form, headers=H)
    assert r.status_code == 202, r.text
    return r.json()


def evidence(client, cid):
    return {e["original_name"]: e for e in client.get(f"{API}/cases/{cid}/evidence", headers=H).json()}


def ents(ev, t):
    return [x for x in ev["entities"] if x["type"] == t]


# ------------------------------------------------------------------ extraction

def test_screenshot_ocr_extracts_transaction(client):
    cid = new_case(client)
    upload(client, cid, "upi_screenshot_847291.png")
    ev = evidence(client, cid)["upi_screenshot_847291.png"]
    assert ev["status"] == "PROCESSED" and ev["method"] == "OCR" and ev["subtype"] == "UPI_SCREENSHOT"
    assert "25,000" in ev["text"] and "847291" in ev["text"]
    assert {x["normalized"] for x in ents(ev, "AMOUNT")} == {"25000.00"}
    assert {x["normalized"] for x in ents(ev, "UPI_REF")} == {"847291"}
    dt = ents(ev, "DATETIME")
    assert dt and dt[0]["occurred_at"].startswith("2026-10-03T17:02") and dt[0]["time_precision"] == "EXACT"  # 10:32 PM IST
    assert [s["name"] for s in ev["steps"]][:5] == ["File received", "File type detected", "Content extracted",
                                                    "Entities identified", "Transaction information found"]


def test_pasted_sms_matches_screenshot(client):
    cid = new_case(client)
    upload(client, cid, "upi_screenshot_847291.png")
    r = client.post(f"{API}/cases/{cid}/evidence/text", json={"text": (SAMPLES / "bank_sms_847291.txt").read_text()}, headers=H)
    assert r.status_code == 202
    case = client.get(f"{API}/cases/{cid}", headers=H).json()
    d = case["disputed"]
    assert d["amount"] == 25000 and d["reference"] == "847291" and len(d["sources"]) == 2
    assert "Same reference number 847291" in d["match_basis"]
    assert case["status"] == "UNDER_REVIEW"


def test_amount_conflict_preserves_both_values(client):
    cid = new_case(client)
    upload(client, cid, "upi_screenshot_847291.png", "bank_sms_conflicting_amount.txt", channel="message")
    f = [x for x in client.get(f"{API}/cases/{cid}/findings", headers=H).json() if x["code"] == "SOURCE_CONFLICT_AMOUNT"]
    assert len(f) == 1 and f[0]["is_conflict"]
    assert "₹25,000" in f[0]["detail"] and "₹20,000" in f[0]["detail"]


def test_audio_unavailable_degrades_gracefully(client):
    cid = new_case(client)
    upload(client, cid, "scam_call.wav", "upi_screenshot_847291.png")
    evs = evidence(client, cid)
    a = evs["scam_call.wav"]
    assert a["status"] == "UNAVAILABLE" and "unavailable" in " ".join(s["detail"] or "" for s in a["steps"]).lower()
    assert a["entities"] == [] and a["text"] is None  # nothing invented
    assert evs["upi_screenshot_847291.png"]["status"] == "PROCESSED"
    miss = [x for x in client.get(f"{API}/cases/{cid}/findings", headers=H).json() if x["code"] == "UNREADABLE_EVIDENCE"]
    assert miss


def test_provided_transcript_is_labelled(client):
    cid = new_case(client)
    upload(client, cid, "scam_call.wav")
    aid = evidence(client, cid)["scam_call.wav"]["id"]
    r = client.post(f"{API}/cases/{cid}/evidence/{aid}/transcript", headers=H, json={
        "text": "[00:00] I am calling from your bank.\n[00:03] Please approve the UPI request to prevent your account from being blocked."})
    assert r.status_code == 200
    ev = r.json()
    assert ev["method"] == "PROVIDED_TRANSCRIPT"
    claims = {c["normalized"]: c for c in ents(ev, "CLAIM")}
    assert {"IDENTITY_CLAIM", "REQUESTED_ACTION", "PRESSURE"} <= set(claims)
    assert claims["IDENTITY_CLAIM"]["attrs"]["description"] == "Speaker claimed to represent a bank"
    assert claims["REQUESTED_ACTION"]["locator"] == "00:03"
    assert all("Statement extracted from audio" in c["attrs"]["label"] for c in claims.values())


def test_whisper_path_with_stub(client, monkeypatch):
    """Exercises the real STT post-processing with a stubbed model (no model download in tests)."""
    class Seg:
        def __init__(self, s, e, t):
            self.start, self.end, self.text, self.avg_logprob = s, e, t, -0.2

    class Info:
        language, duration = "en", 6.0

    class Model:
        def transcribe(self, path, **kw):
            return iter([Seg(0.0, 2.5, " I am calling from your bank."),
                         Seg(2.5, 6.0, " Please approve the UPI request to prevent your account from being blocked.")]), Info()
    monkeypatch.setattr(stt, "_load", lambda: Model())
    cid = new_case(client)
    upload(client, cid, "scam_call.wav")
    ev = evidence(client, cid)["scam_call.wav"]
    assert ev["status"] == "PROCESSED" and ev["method"].startswith("faster-whisper")
    assert len(ev["segments"]) == 2 and ev["segments"][1]["start"] == 2.5
    claims = ents(ev, "CLAIM")
    assert any(c["normalized"] == "REQUESTED_ACTION" and c["locator"] == "00:02" for c in claims)


# ------------------------------------------------------------------ validation & security

def test_upload_validation(client):
    cid = new_case(client)
    bad = client.post(f"{API}/cases/{cid}/evidence", files=[("files", ("x.exe", b"MZ\x90\x00"))], headers=H)
    assert bad.status_code == 422
    fake = client.post(f"{API}/cases/{cid}/evidence", files=[("files", ("photo.png", b"not really a png"))], headers=H)
    assert fake.status_code == 422 and "does not look like" in fake.text
    ok = client.post(f"{API}/cases/{cid}/evidence", files=[("files", ("../../etc/passwd.txt", b"Rs.500 debited"))], headers=H)
    assert ok.status_code == 202 and ok.json()[0]["original_name"] == "passwd.txt"
    assert client.get(f"{API}/cases", headers={"X-API-Key": "wrong"}).status_code == 401


def test_original_file_served_with_integrity_check(client):
    cid = new_case(client)
    e = upload(client, cid, "bank_sms_847291.txt")[0]
    r = client.get(f"{API}/cases/{cid}/evidence/{e['id']}/file", headers=H)
    assert r.status_code == 200 and r.content == (SAMPLES / "bank_sms_847291.txt").read_bytes()


# ------------------------------------------------------------------ analysis

def test_ml_unavailable_without_history(client):
    cid = new_case(client)
    upload(client, cid, "upi_screenshot_847291.png")
    ml = client.get(f"{API}/cases/{cid}", headers=H).json()["analysis"]["ml"]
    assert ml["available"] is False and "Insufficient historical transaction data" in ml["reason"]


def test_history_enables_context_and_ml(client):
    cid = new_case(client)
    upload(client, cid, "upi_screenshot_847291.png", "transaction_history.csv")
    case = client.get(f"{API}/cases/{cid}", headers=H).json()
    assert case["analysis"]["ml"]["available"] is True
    codes = {f["code"] for f in client.get(f"{API}/cases/{cid}/findings", headers=H).json()}
    assert {"AMOUNT_ANOMALY", "TIME_ANOMALY"} <= codes


def test_demo_case_full_pipeline(client):
    r = client.post(f"{API}/demo/load", headers=H)
    assert r.status_code == 201
    cid = r.json()["id"]
    case = client.get(f"{API}/cases/{cid}", headers=H).json()
    assert case["is_synthetic"] and case["ref"].startswith("DEMO-")
    assert all(e["is_synthetic"] for e in client.get(f"{API}/cases/{cid}/evidence", headers=H).json())
    real = client.get(f"{API}/cases?synthetic=false", headers=H).json()
    assert all(not c["is_synthetic"] for c in real)

    f = client.get(f"{API}/cases/{cid}/findings", headers=H).json()
    codes = {x["code"] for x in f}
    assert {"AMOUNT_ANOMALY", "BENEFICIARY_ANOMALY", "DEVICE_ANOMALY", "SEQUENCE_ANOMALY", "ML_OUTLIER"} <= codes
    auth = next(x for x in f if x["code"] == "AUTH_EVENT_PRESENT")
    assert auth["category"] == "CONTRADICTORY" and auth["is_conflict"]  # statement says unintended; auth recorded
    seq = next(x for x in f if x["code"] == "SEQUENCE_ANOMALY")
    assert "New beneficiary added" in seq["detail"] and "₹25,000 payment" in seq["detail"]
    assert all(x["sources"] for x in f if x["category"] != "MISSING")  # every finding cites evidence

    tl = client.get(f"{API}/cases/{cid}/timeline", headers=H).json()
    types = [t["event_type"] for t in tl]
    assert types.index("BENEFICIARY_ADDED") < types.index("TRANSACTION")
    assert all(t["occurred_at"] is None for t in tl if t["time_label"].startswith("Time not stated"))

    g = client.get(f"{API}/cases/{cid}/graph", headers=H).json()
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"CUSTOMER", "TRANSACTION", "BENEFICIARY", "DEVICE", "SESSION", "AUTH_EVENT", "EVIDENCE"} <= kinds
    txn = next(n for n in g["nodes"] if n["kind"] == "TRANSACTION")
    assert txn["sources"] and txn["events"]

    rep = client.post(f"{API}/cases/{cid}/report", headers=H).json()
    pdf = client.get(rep["download_url"], headers=H)
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    for heading in ("1. Case information", "6. Timeline", "11. Evidence conflicts", "12. Missing evidence",
                    "13. Evidence completeness", "16. Audit trail", "SYNTHETIC DEMONSTRATION DATA"):
        assert heading in text


def test_notes_and_audit(client):
    cid = new_case(client)
    upload(client, cid, "bank_sms_847291.txt", channel="message")
    client.post(f"{API}/cases/{cid}/opened", headers=H)
    n = client.post(f"{API}/cases/{cid}/notes", json={"body": "Customer called support at 10:48 PM."}, headers=H)
    assert n.status_code == 201
    client.post(f"{API}/cases/{cid}/report", headers=H)
    acts = [a["action"] for a in client.get(f"{API}/cases/{cid}/audit", headers=H).json()]
    for a in ("CASE_CREATED", "EVIDENCE_UPLOADED", "EVIDENCE_PROCESSED", "EVIDENCE_LINKED", "ANALYSIS_COMPLETED",
              "INVESTIGATOR_OPENED_CASE", "NOTE_ADDED", "REPORT_GENERATED"):
        assert a in acts, a


def test_dispute_from_risk_transaction(client, scenarios):
    r = client.post(f"{API}/transactions/check", json=scenarios["003"]["payload"], headers=H).json()
    client.post(f"{API}/transactions/{r['transaction_id']}/decision", json={"action": "PROCEED"}, headers=H)
    c = client.post(f"{API}/cases/from-risk-transaction/{r['transaction_id']}",
                    json={"statement": "I was told to pay this by a caller. I did not intend to pay."}, headers=H)
    assert c.status_code == 201, c.text
    case = c.json()
    assert case["disputed"]["amount"] == 48000
    ev = client.get(f"{API}/cases/{case['id']}/evidence", headers=H).json()
    assert ev[0]["kind"] == "SYSTEM" and ev[0]["subtype"] == "SYSTEM_RECORD"


@pytest.mark.parametrize("text,amount,ref", [
    ("Your A/C XXXX1234 is debited for Rs.25,000\non 03-10-2026 through UPI.\nRef No: 456789123.", "25000.00", "456789123"),
    ("INR 1,499.00 debited from a/c **4417 on 02Oct26. UPI:427613847291. -Bank", "1499.00", "427613847291"),
])
def test_sms_formats(text, amount, ref):
    from app.services.extraction.entities import extract
    e = extract(text)
    assert amount in {x.normalized for x in e if x.type == "AMOUNT"}
    assert ref in {x.normalized for x in e if x.type in ("UPI_REF", "UTR", "TXN_ID")}
