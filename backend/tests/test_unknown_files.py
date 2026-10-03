"""Evidence that was NOT made for the demo: other layouts, dark mode, Hindi, photos of screens, multi-page
statements, e-mails, chat exports, corrupted and noisy files. The pipeline must cope without inventing anything."""
from pathlib import Path

import pytest

from tests.conftest import API
from tests.test_disputes import new_case
from tests.unknown.make_fixtures import DEVA, make


@pytest.fixture(scope="module")
def fx(tmp_path_factory):
    return make(tmp_path_factory.mktemp("unknown"))


def run(client, hv, fx, name, **form):
    cid = new_case(client, hv, statement="Money was taken from my account after a call. I did not approve it.")
    r = client.post(f"{API}/cases/{cid}/evidence", files=[("files", (name, (fx / name).read_bytes()))], data=form, headers=hv)
    assert r.status_code == 202, r.text
    ev = client.get(f"{API}/cases/{cid}/evidence", headers=hv).json()[0]
    return cid, ev, client.get(f"{API}/cases/{cid}", headers=hv).json()


def test_dark_mode_screenshot_time_without_date(client, auth, fx):
    _, ev, c = run(client, auth["victim"], fx, "dark_payment.png")
    d = c["disputed"]
    assert d["amount"] == 7499 and d["beneficiary_vpa"] == "quickloan.help@axl"
    assert d["occurred_at"] is None and d["time_of_day"] == "21:47"  # the date is never invented
    assert c["analysis"]["field_status"]["amount"]["state"] == "NEEDS_REVIEW"  # symbol unclear -> a person checks
    assert c["analysis"]["field_status"]["reference"]["label"] == "Not found in submitted evidence"
    tl = client.get(f"{API}/cases/{c['id']}/timeline", headers=auth["victim"]).json()
    assert any(t["time_label"] == "9:47 PM — date unavailable" for t in tl)


@pytest.mark.skipif(not Path(DEVA).exists(), reason="Devanagari font not installed")
def test_hindi_bank_sms_screenshot(client, auth, fx):
    _, ev, c = run(client, auth["victim"], fx, "hindi_sms.png")
    assert ev["language"]["label"].startswith(("Hindi", "Mixed"))
    assert ev["subtype"] == "BANK_SMS_SCREENSHOT"
    assert c["disputed"]["amount"] == 12000 and c["disputed"]["reference"] == "427699001234"


def test_photo_of_a_screen(client, auth, fx):
    _, ev, c = run(client, auth["victim"], fx, "photo_of_screen.jpg")
    d = c["disputed"]
    assert (d["amount"], d["reference"], d["beneficiary_vpa"]) == (3250, "427655512345", "ravi.store@okhdfcbank")
    assert not any(x["type"] == "PAYEE" and x["normalized"] == "ravi" for x in ev["entities"])


def test_multi_page_statement_with_balance_and_credit(client, auth, fx):
    cid, ev, c = run(client, auth["victim"], fx, "bank_statement.pdf")
    assert ev["pages"] == 2 and ev["subtype"] == "BANK_STATEMENT"
    amounts = sorted(t["amount"] for t in c["transactions"])
    assert 102345.10 not in amounts  # closing balance is not a payment
    assert {1240, 300, 25000, 180} <= set(amounts)
    assert c["disputed"]["amount"] == 25000  # the customer's loss, not the salary credit
    credit = next(t for t in c["transactions"] if t["amount"] == 52000)
    assert credit["status"] == "CREDITED"


def test_email_mentioning_an_amount_is_not_a_payment(client, auth, fx):
    _, ev, c = run(client, auth["victim"], fx, "refund_email.eml")
    assert ev["subtype"] == "EMAIL" and ev["method"] == "EMAIL"
    assert c["disputed"] is None and c["transactions"] == []
    assert {x["normalized"] for x in ev["entities"] if x["type"] == "UPI_ID"} == {"refund.desk@ybl"}  # e-mail address is not a UPI ID
    descs = {x["attrs"]["description"] for x in ev["entities"] if x["type"] == "CLAIM"}
    assert "Sender asked the listener to approve a payment request" in descs


def test_hinglish_chat_export(client, auth, fx):
    cid, ev, c = run(client, auth["victim"], fx, "whatsapp_chat.txt", channel="message")
    assert ev["subtype"] == "CHAT" and ev["language"]["label"] == "Hinglish"
    client.post(f"{API}/cases/{cid}/submit", json={}, headers=auth["victim"])
    modus = {m["code"] for m in client.get(f"{API}/cases/{cid}", headers=auth["bank"]).json()["analysis"]["modus"]}
    assert "ELECTRICITY_BILL_SCAM" in modus
    tl = client.get(f"{API}/cases/{cid}/timeline", headers=auth["victim"]).json()
    assert any(t["simple"].startswith("Message: “+91 90000 55511: Aaj raat 9 baje bijli") for t in tl)


def test_corrupted_and_noisy_files_partial_success(client, auth, fx):
    V = auth["victim"]
    cid = new_case(client, V)
    files = [("files", (n, (fx / n).read_bytes())) for n in ("corrupted.pdf", "noisy_call.wav", "photo_of_screen.jpg")]
    r = client.post(f"{API}/cases/{cid}/evidence", files=files, headers=V).json()
    assert len(r["accepted"]) == 3
    evs = {e["original_name"]: e for e in client.get(f"{API}/cases/{cid}/evidence", headers=V).json()}
    assert evs["corrupted.pdf"]["status"] == "FAILED"
    assert evs["corrupted.pdf"]["error"] == "This document could not be read automatically. The original document has been preserved."
    assert evs["noisy_call.wav"]["status"] in ("UNAVAILABLE", "FAILED") and evs["noisy_call.wav"]["entities"] == []
    assert evs["photo_of_screen.jpg"]["status"] == "PROCESSED"
    assert client.get(f"{API}/cases/{cid}", headers=V).json()["disputed"]["amount"] == 3250
