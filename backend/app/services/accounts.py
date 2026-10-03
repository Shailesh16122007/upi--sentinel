"""Roles, permissions and the clearly-labelled demo accounts.

Roles are fixed by the platform (an account cannot choose its role at sign-in). Demo accounts exist so the
prototype can be exercised; they are marked is_demo and their names say "(demo)".
"""
from __future__ import annotations

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.models import (Account, AuthorityProfile, BankProfile, Case, CaseStatusOption, Role, VictimProfile)
from app.security import hash_password

ROLES = {
    "VICTIM": ("Customer", "Person reporting a disputed payment", [
        "case:create", "case:read:own", "evidence:upload:own", "case:submit", "timeline:simple", "findings:simple",
        "report:victim", "request:respond"]),
    "BANK": ("Bank investigator", "Fraud / dispute investigation team of the customer's bank", [
        "case:read:bank", "evidence:read", "evidence:upload:bank", "investigation:run", "timeline:full", "findings:full",
        "request:victim", "status:bank", "note:write", "case:escalate", "report:bank", "network:read", "search"]),
    "CYBER": ("Cyber crime officer", "Cyber crime authority receiving escalated cases", [
        "case:read:escalated", "evidence:read", "timeline:full", "findings:full", "request:bank", "status:cyber",
        "note:write", "network:read", "relationship:review", "report:cyber", "export:structured", "search"]),
}

DEFAULT_BANK = "Demo Bank"
CYBER_UNIT = "Cyber Crime Cell (Demo)"

DEMO_ACCOUNTS = [
    # email, password, name, code, role, org, profile
    ("victim@demo.upisentinel.in", "Victim@2026", "Ananya Rao (demo)", "V102", "VICTIM", None,
     {"phone": "9000000102", "bank_name": DEFAULT_BANK, "city": "Bengaluru"}),
    ("victim2@demo.upisentinel.in", "Victim@2026", "Karan Mehta (demo)", "V103", "VICTIM", None,
     {"phone": "9000000103", "bank_name": DEFAULT_BANK, "city": "Pune"}),
    ("bank@demo.upisentinel.in", "Bank@2026", "R. Iyer — Fraud Investigation (demo)", "B201", "BANK", DEFAULT_BANK,
     {"bank_name": DEFAULT_BANK, "branch": "Dispute Resolution Cell", "employee_id": "DB-FI-201", "designation": "Investigator"}),
    ("bank2@demo.upisentinel.in", "Bank@2026", "P. Shah — Disputes (demo)", "B202", "BANK", "Sample Bank",
     {"bank_name": "Sample Bank", "branch": "Disputes Desk", "employee_id": "SB-D-202", "designation": "Investigator"}),
    ("cyber@demo.upisentinel.in", "Cyber@2026", "Insp. S. Khan (demo)", "C301", "CYBER", CYBER_UNIT,
     {"unit": CYBER_UNIT, "jurisdiction": "Demo District", "badge_no": "CC-301", "designation": "Inspector"}),
]

# Synthetic background victims for the demo mule cluster. They cannot sign in.
SYNTHETIC_PEOPLE = [("Synthetic victim A", "V901"), ("Synthetic victim B", "V902"), ("Synthetic victim C", "V903")]

DEFAULT_OPTIONS = {
    "BANK_OUTCOME": [("UNDER_ASSESSMENT", "Under assessment"), ("FRAUD_CONFIRMED", "Fraud confirmed"),
                     ("FRAUD_NOT_ESTABLISHED", "Fraud not established"), ("CUSTOMER_AUTHORISED", "Customer-authorised payment")],
    "REVERSAL": [("NOT_STARTED", "Not started"), ("REVERSAL_REQUESTED", "Payment reversal requested"),
                 ("LIEN_MARKED", "Lien marked on beneficiary funds"), ("AMOUNT_REPAID", "Amount repaid to customer"),
                 ("PARTIALLY_REPAID", "Amount partially repaid"), ("NOT_RECOVERABLE", "Not recoverable")],
    "ACCOUNT_ACTION": [("NONE", "No action"), ("ACCOUNT_RESTRICTED", "Account restricted"),
                       ("ACCOUNT_FROZEN", "Account frozen"), ("BENEFICIARY_BLOCKED", "Beneficiary blocked"),
                       ("CARD_UPI_BLOCKED", "UPI / card access blocked")],
}


def ensure_roles(db: Session) -> None:
    for code, (label, desc, perms) in ROLES.items():
        r = db.get(Role, code)
        if r is None:
            db.add(Role(code=code, label=label, description=desc, permissions=perms))
        else:
            r.label, r.description, r.permissions = label, desc, perms
    db.flush()


def ensure_options(db: Session) -> None:
    have = {(o.category, o.code) for o in db.scalars(select(CaseStatusOption).where(CaseStatusOption.org.is_(None)))}
    for cat, opts in DEFAULT_OPTIONS.items():
        for i, (code, label) in enumerate(opts):
            if (cat, code) not in have:
                db.add(CaseStatusOption(org=None, category=cat, code=code, label=label, sort=i))
    db.flush()


def create_account(db: Session, email: str, password: str | None, name: str, code: str, role: str, org: str | None,
                   profile: dict | None = None, *, demo: bool = False, synthetic: bool = False) -> Account:
    acc = Account(email=email.lower(), user_code=code, name=name, role=role, org=org, is_demo=demo,
                  is_synthetic=synthetic, password_hash=hash_password(password) if password else "!", is_active=True)
    db.add(acc)
    db.flush()
    p = profile or {}
    if role == "VICTIM":
        db.add(VictimProfile(account_id=acc.id, **p))
    elif role == "BANK":
        db.add(BankProfile(account_id=acc.id, **p))
    elif role == "CYBER":
        db.add(AuthorityProfile(account_id=acc.id, **p))
    return acc


def ensure_accounts(db: Session) -> None:
    ensure_roles(db)
    ensure_options(db)
    for email, pw, name, code, role, org, prof in DEMO_ACCOUNTS:
        if not db.scalar(select(Account).where(Account.email == email)):
            create_account(db, email, pw, name, code, role, org, prof, demo=True)
    for name, code in SYNTHETIC_PEOPLE:
        if not db.scalar(select(Account).where(Account.user_code == code)):
            create_account(db, f"{code.lower()}@synthetic.invalid", None, name, code, "VICTIM", None,
                           {"bank_name": DEFAULT_BANK}, synthetic=True)
    # V1 cases had no routing: send them to the default bank so they stay visible.
    db.execute(update(Case).where(Case.bank_org.is_(None), Case.status != "DRAFT").values(bank_org=DEFAULT_BANK))
    db.commit()


def next_victim_code(db: Session) -> str:
    codes = [c for c in db.scalars(select(Account.user_code).where(Account.role == "VICTIM")) if c[1:].isdigit()]
    n = max([int(c[1:]) for c in codes if int(c[1:]) < 900] or [100]) + 1
    return f"V{n}"


def onboarded_banks(db: Session) -> list[str]:
    return sorted({b for b in db.scalars(select(Account.org).where(Account.role == "BANK", Account.is_active.is_(True))) if b})
