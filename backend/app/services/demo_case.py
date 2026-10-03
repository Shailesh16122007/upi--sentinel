"""Synthetic demonstration data. Everything here is SYNTHETIC and labelled as such (DEMO- case IDs,
is_synthetic on cases and evidence, banners and report watermarks). Synthetic cases are never mixed into
real related-case or mule-cluster calculations.

* load_demo(): the full example case for the demo customer, run through the real pipeline.
* seed_background(): three synthetic complaints from synthetic customers that share the demo beneficiary,
  so the related-case / cluster features have something to find during a demonstration.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Case, CaseAction
from app.services import cases as cases_svc
from app.services import crosscase, ingest
from app.services.accounts import DEFAULT_BANK
from app.services.analysis.run import analyze
from app.services.audit import audit
from app.services.extraction.entities import IST

DEMO_DIR = Path(__file__).resolve().parents[2] / "demo_evidence"
STATEMENT = ("₹25,000 was transferred from my account on the night of 1 October to someone I don't know. "
             "I did not intend to make this payment. A caller who said he was from my bank's KYC department told me my "
             "account would be blocked and asked me to approve a request on my phone.")
FILES = [  # the four files a customer would have, plus two bank-side exports
    ("upi_payment_screenshot.png", None, None),
    ("bank_sms_screenshot.png", None, None),
    ("scam_call.wav", None, datetime(2026, 10, 1, 22, 24, tzinfo=IST)),
    ("chat_screenshot.png", None, None),
    ("transaction_history.csv", None, None),
    ("account_activity.json", None, None),
]

BACKGROUND = [
    # synthetic customer code, amount, SMS time, reference, statement, resulting status
    ("V901", "50,000.00", "30-09-26 21:10", "427610005511",
     "A man said my KYC was pending and my account would be blocked. He asked me to approve a request. ₹50,000 was taken.",
     "BANK_REVIEW"),
    ("V902", "1,20,000.00", "01-10-26 11:45", "427611120044",
     "I was told to install an app for verification. Later ₹1,20,000 left my account without my permission.", "ESCALATED"),
    ("V903", "80,000.00", "02-10-26 19:20", "427612080093",
     "Caller from 'bank KYC team' told me to share OTP. ₹80,000 was debited. I did not make this payment.", "SUBMITTED"),
]


def load_demo(db: Session, owner: Account) -> Case:
    case = cases_svc.create(db, STATEMENT, date(2026, 10, 1), 25000.0, owner.name, synthetic=True, owner=owner,
                            bank_org=DEFAULT_BANK)
    audio = None
    for name, channel, hint in FILES:
        p = DEMO_DIR / name
        ev = ingest.store(db, case, name, p.read_bytes(), channel=channel, source="demo", time_hint=hint, actor=owner.name,
                          note="Synthetic demonstration data", uploaded_by_id=owner.id, uploaded_by_role=owner.role)
        db.commit()
        ingest.process(db, ev, owner.name)
        if name.endswith(".wav"):
            audio = ev
    if audio is not None and audio.status != "PROCESSED":
        # Speech-to-text not available here: use the synthetic script the audio was generated from, clearly labelled.
        ingest.set_provided_transcript(db, audio, (DEMO_DIR / "scam_call_transcript.txt").read_text(), owner.name)
        audio.user_note = "Synthetic demonstration data · transcript is the script used to synthesise this audio"
        db.commit()
    analyze(db, case, owner.name)
    audit(db, "DEMO_CASE_LOADED", owner.name, case_id=case.id, source="demo", actor_id=owner.id, actor_role=owner.role)
    db.commit()
    return case


def seed_background(db: Session) -> int:
    """Idempotent: creates the synthetic background complaints if they do not exist yet."""
    made = 0
    for code, amount, when, ref, statement, status in BACKGROUND:
        acc = db.scalar(select(Account).where(Account.user_code == code))
        if acc is None or db.scalar(select(Case).where(Case.owner_id == acc.id)):
            continue
        c = cases_svc.create(db, statement, None, None, "system (synthetic seed)", synthetic=True, owner=acc, bank_org=DEFAULT_BANK)
        sms = (f"Dear Customer, your A/c XX{code[-3:]}0 is debited by Rs.{amount} on {when} for UPI payment to "
               f"rahultraders@ybl. UPI Ref No {ref}. If not done by you, report to Demo Bank. -Demo Bank")
        ev = ingest.store(db, c, "bank_sms.txt", sms.encode(), channel="message", source="demo", actor="system (synthetic seed)",
                          note="Synthetic demonstration data")
        db.commit()
        ingest.process(db, ev, "system")
        now = datetime.now(timezone.utc)
        c.status, c.submitted_at, c.last_activity_at = status, now, now
        if status == "ESCALATED":
            c.escalated_at, c.authority_status = now, "ACTIVE"
        db.add(CaseAction(case_id=c.id, actor_role="SYSTEM", action="synthetic_seed", from_status="DRAFT", to_status=status,
                          note="Synthetic background case created for demonstration (no person performed these steps).",
                          detail={"synthetic": True}))
        audit(db, "SYNTHETIC_CASE_SEEDED", "system (synthetic seed)", case_id=c.id, source="demo", result=f"{c.ref} -> {status}")
        db.commit()
        analyze(db, c, "system")
        made += 1
    if made:
        for c in db.scalars(select(Case).where(Case.is_synthetic.is_(True))):
            crosscase.refresh(db, c, notify_changes=False)
    return made
