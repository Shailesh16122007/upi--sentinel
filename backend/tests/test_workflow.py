"""Three-role lifecycle, permissions, requests, related cases, reports — one case through all roles."""
import io
import sqlite3
from pathlib import Path

from pypdf import PdfReader

from tests.conftest import API
from tests.test_disputes import DEMO, SAMPLES, new_case, upload


def sms(amount, ref, vpa="scammer@okaxis", when="02-10-26 21:15"):
    return (f"Dear Customer, your A/c XX1111 is debited by Rs.{amount} on {when} for UPI payment to {vpa}. "
            f"UPI Ref No {ref}. -Demo Bank")


def paste(client, hv, cid, text):
    r = client.post(f"{API}/cases/{cid}/evidence/text", json={"text": text}, headers=hv)
    assert r.status_code == 202, r.text
    return r.json()


def test_login_role_comes_from_account(client, auth):
    me = client.get(f"{API}/auth/me", headers=auth["bank"]).json()
    assert me["role"] == "BANK" and me["org"] == "Demo Bank" and "case:escalate" in me["permissions"]
    assert client.post(f"{API}/auth/login", json={"login": "bank@demo.upisentinel.in", "password": "wrong"}).status_code == 401
    assert client.post(f"{API}/auth/login", json={"login": "V901", "password": ""}).status_code == 422  # synthetic people cannot log in
    client.post(f"{API}/auth/logout", headers=auth["cyber"])
    assert client.get(f"{API}/auth/me", headers=auth["cyber"]).status_code == 401


def test_permissions_are_enforced_on_the_server(client, auth):
    V, V2, B, B2, C = (auth[k] for k in ("victim", "victim2", "bank", "bank2", "cyber"))
    cid = new_case(client, V)
    upload(client, V, cid, "bank_sms_847291.txt", channel="message")
    # another customer changing the URL gets nothing
    for path in ("", "/evidence", "/timeline", "/reports", "/requests"):
        assert client.get(f"{API}/cases/{cid}{path}", headers=V2).status_code == 404, path
    assert client.post(f"{API}/cases/{cid}/evidence/text", json={"text": "Rs 1 debited"}, headers=V2).status_code == 404
    # bank and cyber cannot see a draft; a different bank never sees it
    assert client.get(f"{API}/cases/{cid}", headers=B).status_code == 404
    client.post(f"{API}/cases/{cid}/submit", json={}, headers=V)
    assert client.get(f"{API}/cases/{cid}", headers=B).status_code == 200
    assert client.get(f"{API}/cases/{cid}", headers=B2).status_code == 404
    assert client.get(f"{API}/cases/{cid}", headers=C).status_code == 404  # not escalated
    # customer cannot use investigator endpoints
    for path in ("/findings", "/notes", "/graph", "/audit", "/history"):
        assert client.get(f"{API}/cases/{cid}{path}", headers=V).status_code == 403, path
    assert client.post(f"{API}/cases/{cid}/actions", json={"action": "escalate", "note": "x"}, headers=V).status_code == 403
    assert client.post(f"{API}/cases", json={"statement": "Bank cannot open cases for customers"}, headers=B).status_code == 403
    # customer view hides internal analysis
    v = client.get(f"{API}/cases/{cid}", headers=V).json()
    assert set(v["analysis"]) == {"field_status", "victim", "candidates", "counts"} and "victim" not in v.get("victim", {})


def test_state_machine_rejects_invalid_transitions(client, auth):
    V, B, C = auth["victim"], auth["bank"], auth["cyber"]
    cid = new_case(client, V)
    assert client.post(f"{API}/cases/{cid}/submit", json={}, headers=V).status_code == 409  # no evidence yet
    upload(client, V, cid, "bank_sms_847291.txt", channel="message")
    client.post(f"{API}/cases/{cid}/submit", json={}, headers=V)
    assert client.post(f"{API}/cases/{cid}/submit", json={}, headers=V).status_code == 409  # already submitted
    r = client.post(f"{API}/cases/{cid}/actions", json={"action": "cyber_accept"}, headers=B)
    assert r.status_code == 403
    r = client.post(f"{API}/cases/{cid}/actions", json={"action": "bank_resolve", "note": "x"}, headers=B)
    assert r.status_code == 409  # must start review first
    client.post(f"{API}/cases/{cid}/opened", headers=B)
    assert client.get(f"{API}/cases/{cid}", headers=B).json()["status"] == "BANK_REVIEW"
    assert client.post(f"{API}/cases/{cid}/actions", json={"action": "escalate"}, headers=B).status_code == 422  # note required


def test_full_lifecycle_across_three_roles(client, auth):
    V, B, C = auth["victim"], auth["bank"], auth["cyber"]
    cid = new_case(client, V, statement="I received a call from someone claiming to be from my bank. Later ₹25,000 was transferred.")
    upload(client, V, cid, "upi_payment_screenshot.png", "bank_sms_screenshot.png", "chat_screenshot.png", "scam_call.wav", folder=DEMO)
    ref = client.post(f"{API}/cases/{cid}/submit", json={}, headers=V).json()["ref"]
    assert any(n["title"].startswith(f"New case received: {ref}") for n in client.get(f"{API}/notifications", headers=B).json()["items"])
    # bank sees the exact files the customer uploaded
    bank_ev = client.get(f"{API}/cases/{cid}/evidence", headers=B).json()
    f = client.get(f"{API}/cases/{cid}/evidence/{bank_ev[0]['id']}/file", headers=B)
    assert f.content == (DEMO / "upi_payment_screenshot.png").read_bytes()
    client.post(f"{API}/cases/{cid}/opened", headers=B)
    # request more evidence -> customer action required
    r = client.post(f"{API}/cases/{cid}/requests", json={"items": ["Bank statement"],
                                                          "message": "Please upload the bank statement showing the disputed transaction."}, headers=B)
    assert r.status_code == 201
    vv = client.get(f"{API}/cases/{cid}/victim-view", headers=V).json()
    assert vv["case"]["status_label"] == "Action required" and vv["requests"][0]["status"] == "OPEN"
    assert vv["case"]["next_action"] == "Upload the evidence your bank asked for"
    # customer uploads -> request fulfilled, back to bank review, bank notified, analysis re-runs
    before = client.get(f"{API}/cases/{cid}", headers=B).json()["analysis"]["counts"]["evidence"]
    upload(client, V, cid, "transaction_history.csv", folder=DEMO)
    after = client.get(f"{API}/cases/{cid}", headers=B).json()
    assert after["status"] == "BANK_REVIEW" and after["analysis"]["counts"]["evidence"] == before + 1
    assert after["analysis"]["counts"]["history_rows"] > 0
    assert client.get(f"{API}/cases/{cid}/requests", headers=B).json()[0]["status"] == "FULFILLED"
    assert any("Additional evidence uploaded" in n["title"] for n in client.get(f"{API}/notifications", headers=B).json()["items"])
    # human review of a system finding stays separate from it
    fcode = client.get(f"{API}/cases/{cid}/findings", headers=B).json()[0]["code"]
    client.post(f"{API}/cases/{cid}/notes", json={"body": "Beneficiary was known to the customer per internal record.",
                                                  "finding_code": fcode, "assessment": "DISAGREE"}, headers=B)
    fnd = next(x for x in client.get(f"{API}/cases/{cid}/findings", headers=B).json() if x["code"] == fcode)
    assert fnd["human_reviews"][0]["assessment"] == "DISAGREE" and "internal record" not in (fnd["detail"] or "")
    client.post(f"{API}/cases/{cid}/analyze", headers=B)  # re-analysis never removes human notes
    assert next(x for x in client.get(f"{API}/cases/{cid}/findings", headers=B).json() if x["code"] == fcode)["human_reviews"]
    # account action + escalation
    assert client.post(f"{API}/cases/{cid}/dispositions", json={"account_action": "ACCOUNT_RESTRICTED"}, headers=B).status_code == 200
    assert client.post(f"{API}/cases/{cid}/dispositions", json={"account_action": "MADE_UP"}, headers=B).status_code == 422
    client.post(f"{API}/cases/{cid}/actions", json={"action": "escalate", "note": "Beneficiary in related complaints."}, headers=B)
    # cyber crime receives the SAME case record
    cc = client.get(f"{API}/cases/{cid}", headers=C).json()
    assert cc["id"] == cid and cc["ref"] == ref and cc["evidence_count"] == 5
    client.post(f"{API}/cases/{cid}/notes", json={"body": "Beneficiary appears in multiple complaints. Further investigation required."}, headers=C)
    assert all(n["role"] != "CYBER" for n in client.get(f"{API}/cases/{cid}/notes", headers=B).json())  # cyber-only by default
    # information request to bank and response
    client.post(f"{API}/cases/{cid}/actions", json={"action": "cyber_accept"}, headers=C)
    rq = client.post(f"{API}/cases/{cid}/requests", json={"items": ["Additional transaction details"], "message": "Share device binding logs."},
                     headers=C).json()
    assert client.get(f"{API}/cases/{cid}", headers=B).json()["status"] == "INFO_REQUESTED"
    assert client.post(f"{API}/requests/{rq['id']}/respond", json={"note": "Logs attached to case as E6."}, headers=B).status_code == 200
    assert client.get(f"{API}/cases/{cid}", headers=C).json()["status"] == "CYBER_REVIEW"
    for a, n in (("cyber_investigate", None), ("cyber_pending", "Awaiting telecom records"), ("cyber_resolve", "Beneficiary account frozen; funds traced.")):
        assert client.post(f"{API}/cases/{cid}/actions", json={"action": a, "note": n}, headers=C).status_code == 200, a
    # customer sees the result
    v = client.get(f"{API}/cases/{cid}", headers=V).json()
    assert v["status_label"] == "Resolved" and [s["state"] for s in v["tracker"]] == ["done"] * 5
    msgs = [u["message"] for u in client.get(f"{API}/cases/{cid}/victim-view", headers=V).json()["updates"]]
    assert "Your case has been escalated to cyber crime." in msgs and "Your case has been resolved." in msgs
    # audit trail has every step, with roles
    acts = [(a["action"], a["role"]) for a in client.get(f"{API}/cases/{cid}/audit", headers=C).json()]
    for a in ("CASE_CREATED", "EVIDENCE_UPLOADED", "EVIDENCE_PROCESSED", "ANALYSIS_COMPLETED", "STATUS_CHANGED", "INVESTIGATOR_OPENED_CASE",
              "EVIDENCE_REQUESTED", "DISPOSITION_CHANGED", "NOTE_ADDED", "FINDING_REVIEWED", "EVIDENCE_VIEWED"):
        assert a in {x[0] for x in acts}, a
    assert ("STATUS_CHANGED", "CYBER") in acts and ("STATUS_CHANGED", "VICTIM") in acts


def test_related_cases_and_clusters_real_and_synthetic_kept_apart(client, auth):
    V, V2, B, C = auth["victim"], auth["victim2"], auth["bank"], auth["cyber"]
    ids = []
    for hv, amt, ref in ((V, "50,000.00", "427600000001"), (V2, "1,20,000.00", "427600000002"), (V, "80,000.00", "427600000003")):
        cid = new_case(client, hv)
        paste(client, hv, cid, sms(amt, ref))
        client.post(f"{API}/cases/{cid}/submit", json={}, headers=hv)
        ids.append(cid)
    # a synthetic case with the same beneficiary must not join the real cluster
    sid = new_case(client, V, synthetic=True)
    paste(client, V, sid, sms("9,999.00", "427600000009"))
    client.post(f"{API}/cases/{sid}/submit", json={}, headers=V)
    rel = client.get(f"{API}/cases/{ids[0]}/related", headers=B).json()
    assert {r["ref"] for r in rel["related"]} == {client.get(f"{API}/cases/{i}", headers=B).json()["ref"] for i in ids[1:]}
    cl = rel["clusters"][0]
    assert cl["value"] == "scammer@okaxis" and cl["case_count"] == 3 and cl["total_amount"] == 250000.0
    assert cl["label"] == "Related transaction cluster detected" and not cl["is_synthetic"]
    syn = client.get(f"{API}/network/clusters?synthetic=true", headers=B).json()
    assert syn == [] or all(c["is_synthetic"] for c in syn)
    g = client.get(f"{API}/network/graph", headers=B).json()
    assert {n["kind"] for n in g["nodes"]} == {"CASE", "IDENTIFIER"} and len(g["edges"]) == 3
    # dismissal by an officer survives re-analysis
    client.post(f"{API}/cases/{ids[0]}/actions", json={"action": "start_review"}, headers=B)
    client.post(f"{API}/cases/{ids[0]}/actions", json={"action": "escalate", "note": "cluster"}, headers=B)
    link = client.get(f"{API}/cases/{ids[0]}/related", headers=C).json()["related"][0]["links"][0]
    assert client.post(f"{API}/relationships/{link['id']}", json={"status": "LINKED"}, headers=C).status_code == 200
    client.post(f"{API}/cases/{ids[0]}/analyze", headers=B)
    assert client.get(f"{API}/cases/{ids[0]}/related", headers=C).json()["related"][0]["links"][0]["status"] == "LINKED"
    # search
    hits = client.get(f"{API}/search?q=427600000002", headers=B).json()
    assert [h["id"] for h in hits] == [ids[1]] and "UTR / reference" in hits[0]["matched_on"]
    assert {h["id"] for h in client.get(f"{API}/search?q=80000", headers=B).json()} == {ids[2]}
    assert client.get(f"{API}/search?q=scammer@okaxis", headers=V).status_code == 403
    # dashboard counts are real
    d = client.get(f"{API}/dashboard?synthetic=false", headers=B).json()
    assert d["total"] == 3 and d["clusters"] == 1


def test_seeded_background_cluster(client, auth):
    from app.db import SessionLocal
    from app.services.demo_case import seed_background
    with SessionLocal() as db:
        assert seed_background(db) == 3
        assert seed_background(db) == 0  # idempotent
    V, B = auth["victim"], auth["bank"]
    cid = client.post(f"{API}/demo/load", headers=V).json()["id"]
    client.post(f"{API}/cases/{cid}/submit", json={}, headers=V)
    rel = client.get(f"{API}/cases/{cid}/related", headers=B).json()
    assert len(rel["related"]) == 3
    cl = rel["clusters"][0]
    assert cl["case_count"] == 4 and cl["total_amount"] == 275000.0 and cl["window_hours"] <= 48


def test_report_versions_track_changes(client, auth):
    V, B = auth["victim"], auth["bank"]
    cid = new_case(client, V)
    upload(client, V, cid, "upi_screenshot_847291.png")
    v1 = client.post(f"{API}/cases/{cid}/reports", json={}, headers=V).json()
    assert v1["audience"] == "VICTIM" and v1["version"] == 1 and v1["evidence_count"] == 1
    paste(client, V, cid, (SAMPLES / "bank_sms_847291.txt").read_text())
    reps = client.get(f"{API}/cases/{cid}/reports", headers=V).json()
    assert reps[0]["is_current"] is False  # stale once new evidence arrived
    v2 = client.post(f"{API}/cases/{cid}/reports", json={}, headers=V).json()
    assert v2["version"] == 2 and v2["evidence_count"] == 2 and "evidence 1 → 2" in v2["changes"]
    assert len(client.get(f"{API}/cases/{cid}/reports", headers=V).json()) == 2  # history kept
    pdf = client.get(v2["download_url"], headers=V)
    text = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert "Your case report" in text and "What happened" in text and "Isolation" not in text  # no ML jargon for customers
    assert client.post(f"{API}/cases/{cid}/reports", json={"audience": "BANK"}, headers=V).status_code == 403
    client.post(f"{API}/cases/{cid}/submit", json={}, headers=V)
    assert client.get(v2["download_url"], headers=B).status_code == 404  # bank cannot pull the customer copy


def test_structured_export(client, auth):
    V, B, C = auth["victim"], auth["bank"], auth["cyber"]
    cid = new_case(client, V)
    paste(client, V, cid, sms("25,000.00", "427613847291", "rahultraders@ybl"))
    client.post(f"{API}/cases/{cid}/submit", json={}, headers=V)
    assert client.get(f"{API}/cases/{cid}/export", headers=B).status_code == 403
    client.post(f"{API}/cases/{cid}/actions", json={"action": "start_review"}, headers=B)
    client.post(f"{API}/cases/{cid}/actions", json={"action": "escalate", "note": "please investigate"}, headers=B)
    ex = client.get(f"{API}/cases/{cid}/export", headers=C).json()
    assert "not an official NCRP" in ex["label"]
    assert ex["transaction"]["amount_inr"] == 25000.0 and ex["transaction"]["utr_or_reference"] == "427613847291"
    assert ex["transaction"]["beneficiary_upi_id"] == "rahultraders@ybl"
    assert ex["transaction"]["beneficiary_account"] == "Not available in submitted evidence"
    assert ex["evidence_references"][0]["sha256"]
    dl = client.get(f"{API}/cases/{cid}/export/download", headers=C)
    assert dl.status_code == 200 and "attachment" in dl.headers["content-disposition"]


def test_multiple_transactions_and_selection(client, auth):
    V = auth["victim"]
    cid = new_case(client, V)
    stmt = ("Statement of account\n01-10-2026 UPI/freshmart@okaxis Rs.500.00 Dr UPI Ref 427600000101\n"
            "01-10-2026 UPI/chaipoint@ybl Rs.1,200.00 Dr UPI Ref 427600000102\n"
            "01-10-2026 UPI/unknown.pay@okicici Rs.25,000.00 Dr UPI Ref 427600000103\n")
    paste(client, V, cid, stmt)
    case = client.get(f"{API}/cases/{cid}", headers=V).json()
    assert len(case["transactions"]) == 3 and case["analysis"]["candidates"] == 3
    target = next(t for t in case["transactions"] if t["amount"] == 1200)
    r = client.post(f"{API}/cases/{cid}/disputed-transaction", json={"transaction_id": target["id"]}, headers=V)
    assert r.status_code == 200 and r.json()["disputed"]["amount"] == 1200
    paste(client, V, cid, "Note: I also lost money")  # re-analysis keeps the person's choice
    assert client.get(f"{API}/cases/{cid}", headers=V).json()["disputed"]["reference"] == "427600000102"


def test_v1_database_is_upgraded_in_place(tmp_path):
    """A database created by the previous version keeps its cases; new columns/tables are added."""
    from sqlalchemy import create_engine, inspect, text
    from app.migrate import upgrade
    p = tmp_path / "v1.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE cases (id VARCHAR(36) PRIMARY KEY, ref VARCHAR(32), statement TEXT, approx_date DATE, "
                "claimed_amount FLOAT, status VARCHAR(20), claim_type VARCHAR(24), is_synthetic BOOLEAN, linked_risk_txn_id VARCHAR(36), "
                "analysis JSON, analyzed_at DATETIME, created_at DATETIME, updated_at DATETIME)")
    con.execute("INSERT INTO cases (id, ref, statement, status, is_synthetic) VALUES ('c1', 'UPI-2026-001', 'old case', 'UNDER_REVIEW', 0)")
    con.commit()
    con.close()
    eng = create_engine(f"sqlite:///{p}")
    added = upgrade(eng)
    assert "cases.owner_id" in added and "cases.bank_org" in added
    with eng.connect() as c:
        assert c.execute(text("SELECT status FROM cases WHERE id='c1'")).scalar() == "BANK_REVIEW"
    assert inspect(eng).has_table("accounts") and inspect(eng).has_table("mule_clusters")
