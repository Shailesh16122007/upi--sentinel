"""Evidence pipeline: extraction, matching, conflicts, degradation, analysis — through the authenticated API."""
import io
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.services.audio import stt
from tests.conftest import API, H

SAMPLES = Path(__file__).resolve().parents[1] / "sample_uploads"
DEMO = Path(__file__).resolve().parents[1] / "demo_evidence"


def new_case(client, hv, statement="₹25,000 was transferred from my account. I did not intend to make this payment.", **kw):
    r = client.post(f"{API}/cases", json={"statement": statement, **kw}, headers=hv)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def upload(client, hv, cid, *names, folder=SAMPLES, **form):
    files = [("files", (n, (folder / n).read_bytes())) for n in names]
    r = client.post(f"{API}/cases/{cid}/evidence", files=files, data=form, headers=hv)
    assert r.status_code == 202, r.text
    return r.json()


def evidence(client, hv, cid):
    return {e["original_name"]: e for e in client.get(f"{API}/cases/{cid}/evidence", headers=hv).json()}


def ents(ev, t):
    return [x for x in ev["entities"] if x["type"] == t]


# ------------------------------------------------------------------ extraction

def test_screenshot_ocr_extracts_transaction(client, auth):
    V = auth["victim"]
    cid = new_case(client, V)
    upload(client, V, cid, "upi_screenshot_847291.png")
    ev = evidence(client, V, cid)["upi_screenshot_847291.png"]
    assert ev["status"] == "PROCESSED" and ev["method"] == "OCR" and ev["subtype"] == "UPI_SCREENSHOT"
    assert "25,000" in ev["text"] and "847291" in ev["text"]
    assert {x["normalized"] for x in ents(ev, "AMOUNT")} == {"25000.00"}
    assert {x["normalized"] for x in ents(ev, "UPI_REF")} == {"847291"}
    dt = ents(ev, "DATETIME")
    assert dt and dt[0]["occurred_at"].startswith("2026-10-03T17:02") and dt[0]["time_precision"] == "EXACT"  # 10:32 PM IST
    assert ev["integrity"]["result"] == "MATCH" and ev["integrity"]["status"] == "Original file preserved"
    assert ev["image_check"]["label"] in ("No obvious technical indicators found", "Possible manipulation indicators")


def test_pasted_sms_matches_screenshot(client, auth):
    V = auth["victim"]
    cid = new_case(client, V)
    upload(client, V, cid, "upi_screenshot_847291.png")
    r = client.post(f"{API}/cases/{cid}/evidence/text", json={"text": (SAMPLES / "bank_sms_847291.txt").read_text()}, headers=V)
    assert r.status_code == 202
    case = client.get(f"{API}/cases/{cid}", headers=V).json()
    d = case["disputed"]
    assert d["amount"] == 25000 and d["reference"] == "847291" and len(d["sources"]) == 2
    assert case["analysis"]["field_status"]["amount"]["state"] == "CONFIRMED"
    assert case["analysis"]["field_status"]["beneficiary_vpa"]["label"] == "Not found in submitted evidence"
    assert case["status"] == "DRAFT"  # analysis never changes the lifecycle


def test_amount_conflict_preserves_both_values(client, auth):
    V, B = auth["victim"], auth["bank"]
    cid = new_case(client, V)
    upload(client, V, cid, "upi_screenshot_847291.png", "bank_sms_conflicting_amount.txt", channel="message")
    client.post(f"{API}/cases/{cid}/submit", json={}, headers=V)
    f = [x for x in client.get(f"{API}/cases/{cid}/findings", headers=B).json() if x["code"] == "SOURCE_CONFLICT_AMOUNT"]
    assert len(f) == 1 and f[0]["is_conflict"] and f[0]["certainty"] in ("High", "Medium") and f[0]["why"]
    assert "₹25,000" in f[0]["detail"] and "₹20,000" in f[0]["detail"]
    case = client.get(f"{API}/cases/{cid}", headers=V).json()
    assert case["analysis"]["field_status"]["amount"]["state"] == "CONFLICT"
    assert any("different amount" in x["text"] for x in case["analysis"]["victim"]["check"])


def test_audio_unavailable_degrades_gracefully(client, auth):
    V = auth["victim"]
    cid = new_case(client, V)
    upload(client, V, cid, "scam_call.wav", "upi_screenshot_847291.png")
    evs = evidence(client, V, cid)
    a = evs["scam_call.wav"]
    assert a["status"] == "UNAVAILABLE" and a["error"].startswith("We could not transcribe this recording")
    assert a["entities"] == [] and a["text"] is None  # nothing invented
    assert evs["upi_screenshot_847291.png"]["status"] == "PROCESSED"  # partial success
    miss = client.get(f"{API}/cases/{cid}", headers=V).json()["analysis"]["victim"]["missing"]
    assert any("could not transcribe scam_call.wav" in m["text"] for m in miss)


def test_provided_transcript_is_labelled(client, auth):
    V = auth["victim"]
    cid = new_case(client, V)
    upload(client, V, cid, "scam_call.wav")
    aid = evidence(client, V, cid)["scam_call.wav"]["id"]
    r = client.post(f"{API}/cases/{cid}/evidence/{aid}/transcript", headers=V, json={
        "text": "[00:00] I am calling from your bank.\n[00:03] Please approve the UPI request to prevent your account from being blocked."})
    assert r.status_code == 200
    ev = r.json()
    assert ev["method"] == "PROVIDED_TRANSCRIPT"
    claims = {c["normalized"]: c for c in ents(ev, "CLAIM")}
    assert {"IDENTITY_CLAIM", "REQUESTED_ACTION", "PRESSURE"} <= set(claims)
    assert claims["IDENTITY_CLAIM"]["attrs"]["description"] == "Caller claimed to represent a bank"
    assert claims["PRESSURE"]["attrs"]["description"] == "Caller stated that the account would be blocked"
    assert claims["REQUESTED_ACTION"]["locator"] == "00:03"
    assert all("Statement extracted from audio" in c["attrs"]["label"] for c in claims.values())


def test_whisper_path_with_stub(client, auth, monkeypatch):
    """Exercises the real STT post-processing (incl. Hinglish) with a stubbed model (no model download in tests)."""
    class Seg:
        def __init__(self, s, e, t):
            self.start, self.end, self.text, self.avg_logprob = s, e, t, -0.2

    class Info:
        language, duration = "hi", 6.0

    class Model:
        def transcribe(self, path, task="transcribe", **kw):
            if task == "translate":
                return iter([Seg(0.0, 2.5, " I am speaking from SBI bank."), Seg(2.5, 6.0, " Download AnyDesk for verification.")]), Info()
            return iter([Seg(0.0, 2.5, " Main SBI bank se bol raha hoon."),
                         Seg(2.5, 6.0, " Verification ke liye AnyDesk download karo.")]), Info()
    monkeypatch.setattr(stt, "_load", lambda: Model())
    V = auth["victim"]
    cid = new_case(client, V)
    upload(client, V, cid, "scam_call.wav")
    ev = evidence(client, V, cid)["scam_call.wav"]
    assert ev["status"] == "PROCESSED" and ev["method"].startswith("faster-whisper")
    assert "Main SBI bank se bol raha hoon." in ev["text"]  # original kept, not translated away
    assert ev["language"]["label"] == "Hinglish" and ev["language"]["speech_language"] == "hi"
    descs = {c["attrs"]["description"] for c in ents(ev, "CLAIM")}
    assert "Caller claimed to represent SBI" in descs
    assert any("install or open an app" in d for d in descs)


# ------------------------------------------------------------------ validation & security

def test_upload_validation_and_duplicates(client, auth):
    V = auth["victim"]
    cid = new_case(client, V)
    bad = client.post(f"{API}/cases/{cid}/evidence", files=[("files", ("x.exe", b"MZ\x90\x00"))], headers=V).json()
    assert bad["accepted"] == [] and "can't read '.exe'" in bad["rejected"][0]["reason"]
    fake = client.post(f"{API}/cases/{cid}/evidence", files=[("files", ("photo.png", b"not really a png"))], headers=V).json()
    assert "does not look like" in fake["rejected"][0]["reason"]
    ok = client.post(f"{API}/cases/{cid}/evidence", files=[("files", ("../../etc/passwd.txt", b"Rs.500 debited"))], headers=V)
    assert ok.status_code == 202 and ok.json()["accepted"][0]["original_name"] == "passwd.txt"
    dup = client.post(f"{API}/cases/{cid}/evidence", files=[("files", ("renamed.txt", b"Rs.500 debited"))], headers=V).json()
    assert dup["accepted"] == [] and dup["rejected"][0]["duplicate_of"] == "E1"
    assert "already been uploaded" in dup["rejected"][0]["reason"]
    assert client.get(f"{API}/cases", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get(f"{API}/cases").status_code == 401


def test_original_file_served_with_integrity_check(client, auth):
    V = auth["victim"]
    cid = new_case(client, V)
    e = upload(client, V, cid, "bank_sms_847291.txt")["accepted"][0]
    r = client.get(f"{API}/cases/{cid}/evidence/{e['id']}/file", headers=V)
    assert r.status_code == 200 and r.content == (SAMPLES / "bank_sms_847291.txt").read_bytes()


# ------------------------------------------------------------------ analysis

def test_ml_unavailable_without_history(client, auth):
    V, B = auth["victim"], auth["bank"]
    cid = new_case(client, V)
    upload(client, V, cid, "upi_screenshot_847291.png")
    client.post(f"{API}/cases/{cid}/submit", json={}, headers=V)
    ml = client.get(f"{API}/cases/{cid}", headers=B).json()["analysis"]["ml"]
    assert ml["available"] is False and "Insufficient historical transaction data" in ml["reason"]


def test_history_enables_context_and_ml(client, auth):
    V, B = auth["victim"], auth["bank"]
    cid = new_case(client, V)
    upload(client, V, cid, "upi_screenshot_847291.png", "transaction_history.csv")
    client.post(f"{API}/cases/{cid}/submit", json={}, headers=V)
    case = client.get(f"{API}/cases/{cid}", headers=B).json()
    assert case["analysis"]["ml"]["available"] is True
    codes = {f["code"] for f in client.get(f"{API}/cases/{cid}/findings", headers=B).json()}
    assert {"AMOUNT_ANOMALY", "TIME_ANOMALY"} <= codes


def test_demo_case_full_pipeline(client, auth):
    V, B = auth["victim"], auth["bank"]
    r = client.post(f"{API}/demo/load", headers=V)
    assert r.status_code == 201
    cid = r.json()["id"]
    case = client.get(f"{API}/cases/{cid}", headers=V).json()
    assert case["is_synthetic"] and case["ref"].startswith("DEMO-") and case["status"] == "DRAFT"
    assert all(e["is_synthetic"] for e in client.get(f"{API}/cases/{cid}/evidence", headers=V).json())
    assert client.post(f"{API}/cases/{cid}/submit", json={}, headers=V).status_code == 200

    f = client.get(f"{API}/cases/{cid}/findings", headers=B).json()
    codes = {x["code"] for x in f}
    assert {"AMOUNT_ANOMALY", "BENEFICIARY_ANOMALY", "DEVICE_ANOMALY", "SEQUENCE_ANOMALY", "ML_OUTLIER", "MODUS_PATTERN"} <= codes
    auth_f = next(x for x in f if x["code"] == "AUTH_EVENT_PRESENT")
    assert auth_f["category"] == "CONTRADICTORY" and auth_f["is_conflict"]  # statement says unintended; auth recorded
    seq = next(x for x in f if x["code"] == "SEQUENCE_ANOMALY")
    assert "New beneficiary added" in seq["detail"] and "₹25,000 payment" in seq["detail"]
    assert all(x["sources"] for x in f if x["category"] != "MISSING")  # every finding cites evidence
    assert all(x["why"] for x in f if x["is_anomaly"]) and all("does not by itself establish fraud" in x["why"] for x in f if x["is_anomaly"])
    full = client.get(f"{API}/cases/{cid}", headers=B).json()
    kf = [k["text"] for k in full["analysis"]["key_findings"]]
    assert kf[0] == "New beneficiary added shortly before the payment" and "Bank SMS confirms the transaction" in kf

    tl = client.get(f"{API}/cases/{cid}/timeline", headers=B).json()
    types = [t["event_type"] for t in tl]
    assert types.index("BENEFICIARY_ADDED") < types.index("TRANSACTION")
    vt = client.get(f"{API}/cases/{cid}/timeline", headers=V).json()
    assert "description" not in vt[0] and any(t["simple"] == "₹25,000 was sent to rahultraders@ybl" for t in vt)
    assert any("Call recording" in t["source_kinds"] for t in vt)

    g = client.get(f"{API}/cases/{cid}/graph", headers=B).json()
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"CUSTOMER", "TRANSACTION", "BENEFICIARY", "DEVICE", "SESSION", "AUTH_EVENT", "EVIDENCE"} <= kinds

    rep = client.post(f"{API}/cases/{cid}/reports", json={}, headers=B).json()
    pdf = client.get(rep["download_url"], headers=B)
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    for heading in ("Key findings", "Reconstructed timeline", "Evidence conflicts", "Missing evidence", "Beneficiary analysis",
                    "Related cases", "Mule network findings", "Recommended next investigation steps", "Audit trail",
                    "SYNTHETIC DEMONSTRATION DATA"):
        assert heading in text, heading


def test_hinglish_chat_screenshot(client, auth):
    V = auth["victim"]
    cid = new_case(client, V, statement="Someone on chat said my KYC is pending and asked me to install an app. Then money was gone.")
    upload(client, V, cid, "chat_screenshot.png", folder=DEMO)
    ev = evidence(client, V, cid)["chat_screenshot.png"]
    assert ev["subtype"] == "CHAT_SCREENSHOT" and ev["language"]["label"] == "Hinglish"
    descs = {c["attrs"]["description"] for c in ents(ev, "CLAIM")}
    assert "Sender claimed to represent a bank" in descs
    assert "Sender stated that the account would be blocked" in descs
    assert client.post(f"{API}/cases/{cid}/submit", json={}, headers=V).status_code == 200
    modus = {m["code"] for m in client.get(f"{API}/cases/{cid}", headers=auth["bank"]).json()["analysis"]["modus"]}
    assert "REMOTE_ACCESS_SCAM" in modus or "KYC_SCAM" in modus
    tl = client.get(f"{API}/cases/{cid}/timeline", headers=V).json()
    assert any(t["simple"].startswith("Message: “Madam main Demo Bank KYC") for t in tl)


def test_dispute_from_risk_transaction(client, scenarios):
    r = client.post(f"{API}/transactions/check", json=scenarios["003"]["payload"], headers=H).json()
    client.post(f"{API}/transactions/{r['transaction_id']}/decision", json={"action": "PROCEED"}, headers=H)
    c = client.post(f"{API}/cases/from-risk-transaction/{r['transaction_id']}",
                    json={"statement": "I was told to pay this by a caller. I did not intend to pay."}, headers=H)
    assert c.status_code == 201, c.text
    assert c.json()["disputed"]["amount"] == 48000 and c.json()["status"] == "SUBMITTED"


@pytest.mark.parametrize("text,amount,ref", [
    ("Your A/C XXXX1234 is debited for Rs.25,000\non 03-10-2026 through UPI.\nRef No: 456789123.", "25000.00", "456789123"),
    ("INR 1,499.00 debited from a/c **4417 on 02Oct26. UPI:427613847291. -Bank", "1499.00", "427613847291"),
    ("Rs 25000 debited via UPI. UPI Ref No\n427613847291", "25000.00", "427613847291"),
])
def test_sms_formats(text, amount, ref):
    from app.services.extraction.entities import extract
    e = extract(text)
    assert amount in {x.normalized for x in e if x.type == "AMOUNT"}
    assert ref in {x.normalized for x in e if x.type in ("UPI_REF", "UTR", "TXN_ID") and not x.attrs.get("unlabelled_12_digit")}


def test_ocr_amount_validation():
    from app.services.extraction.entities import extract
    e = [x for x in extract("Paid ₹25000O to x", method="OCR") if x.type == "AMOUNT"]
    assert e and e[0].attrs.get("needs_review") and e[0].confidence <= 0.5
    bare = [x for x in extract("425,000", method="OCR") if x.type == "AMOUNT"]
    assert bare and "misread ₹" in bare[0].attrs["needs_review"]


@pytest.mark.parametrize("text,label,signal", [
    ("Sir bol raha tha ki AnyDesk download karo validation ke liye.", "Hinglish", "REMOTE_ACCESS"),
    ("Paise double ho jayega", "Hinglish", "INVESTMENT"),
    ("KYC update nahi kiya toh account block ho jayega.", "Hinglish", "THREAT"),
    ("Electricity bill kat jayega aaj raat", "Hinglish", "ELECTRICITY"),
    ("KYC update panna solli call pannanga, OTP sollunga", "Tanglish", "CREDENTIAL_REQUEST"),
    ("आपका खाता बंद हो जाएगा, ओटीपी बताइए", "Hindi", "THREAT"),
])
def test_multilingual_signals(text, label, signal):
    from app.services.extraction import language, lexicon
    assert language.detect(text)["label"] == label
    assert signal in {c for c, _ in lexicon.find(text)}


def test_single_keyword_is_not_a_scam_category():
    from app.services.analysis.modus import classify
    ev = {"e1": {"id": "e1", "code": "E1", "subtype": "MESSAGE"}}
    one = [{"id": "x", "evidence_id": "e1", "type": "LANGUAGE_SIGNAL", "normalized": "KYC", "context": "KYC", "locator": "line 1", "attrs": {}}]
    assert classify({"statement": ""}, ev, one) == []
    two = one + [{"id": "y", "evidence_id": "e1", "type": "LANGUAGE_SIGNAL", "normalized": "THREAT", "context": "blocked",
                  "locator": "line 2", "attrs": {}}]
    assert [m["code"] for m in classify({"statement": ""}, ev, two)] == ["KYC_SCAM"]
