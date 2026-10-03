"""Deterministic synthetic dataset for the real-time risk API. No real people, accounts or VPAs.

Run:  python -m app.seed        (drops and recreates the database)
"""
import random
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session  # noqa: I001

from app.db import Base, SessionLocal, engine
from app.models import AccountLink, Beneficiary, Device, Transaction, User

IST = ZoneInfo("Asia/Kolkata")

USERS = [
    # ref, name, phone, vpa, home(lat,lon), device, (min,max amount), active hours IST
    ("U-101", "Asha Nair", "9000000101", "asha.nair@oksbi", (12.97, 77.59), "D-ASHA-01", (500, 2000), range(9, 21)),
    ("U-102", "Ravi Kumar", "9000000102", "ravi.k@okhdfc", (12.93, 77.62), "D-RAVI-01", (300, 2000), range(8, 22)),
    ("U-103", "Meena Iyer", "9000000103", "meena.i@okicici", (13.08, 80.27), "D-MEENA-01", (400, 2500), range(9, 20)),
    ("U-104", "Lakshmi Devi", "9000000104", None, (12.71, 77.69), None, (1000, 3000), range(10, 17)),
]
EXTRA_SENDERS = [f"U-1{n}" for n in range(10, 18)]  # synthetic users feeding the mule beneficiary

REGULAR_BENES = [
    ("freshmart@okaxis", "FreshMart Grocers", "Axis Bank"),
    ("chaipoint.blr@ybl", "Chai Point", "Yes Bank"),
    ("priya.n@oksbi", "Priya N", "SBI"),
    ("metro.recharge@paytm", "Metro Card Recharge", "Paytm Payments Bank"),
    ("localpharma@okicici", "Local Pharma", "ICICI Bank"),
]
HOME_AEPS_TERMINAL = ("aeps-agent-0091@nsdl", "CSC Agent 0091, Anekal", "NSDL")

# Mule chain:  rahultraders -> cashout.hub -> mule.z (flagged)
#              fastkyc.refund -> mule.z
#              aeps-agent-7731 ~ mule.z
FLAGGED = ("mule.z@axl", "Z Enterprises", "Axis Bank", "Linked to 14 prior synthetic fraud complaints")
MULE_NODES = [
    ("rahultraders@ybl", "Rahul Traders", "Yes Bank", 2),
    ("cashout.hub@paytm", "Cashout Hub", "Paytm Payments Bank", 5),
    ("fastkyc.refund@ibl", "KYC Refund Desk", "IndusInd Bank", 3),
    ("aeps-agent-7731@nsdl", "AePS Agent 7731, Jaipur", "NSDL", 20),
]
LINKS = [
    ("rahultraders@ybl", "cashout.hub@paytm", "SENT_TO"),
    ("cashout.hub@paytm", "mule.z@axl", "SENT_TO"),
    ("fastkyc.refund@ibl", "mule.z@axl", "SENT_TO"),
    ("aeps-agent-7731@nsdl", "mule.z@axl", "ASSOCIATED_WITH"),
]

def seed(db: Session, now: datetime | None = None) -> None:
    rnd = random.Random(2026)
    now = now or datetime.now(timezone.utc)

    users: dict[str, User] = {}
    for ref, name, phone, vpa, (lat, lon), _dev, _amt, _hrs in USERS:
        users[ref] = User(ref=ref, name=name, phone=phone, vpa=vpa, home_lat=lat, home_lon=lon,
                          created_at=now - timedelta(days=400))
    for i, ref in enumerate(EXTRA_SENDERS):
        users[ref] = User(ref=ref, name=f"Synthetic User {ref[2:]}", phone=f"90000{ref[2:]:0>5}",
                          home_lat=12.9 + i * 0.01, home_lon=77.5, created_at=now - timedelta(days=200))
    db.add_all(users.values())

    benes: dict[str, Beneficiary] = {}
    for vpa, name, bank in REGULAR_BENES:
        benes[vpa] = Beneficiary(vpa=vpa, name=name, bank=bank, created_at=now - timedelta(days=500))
    v, n, b = HOME_AEPS_TERMINAL
    benes[v] = Beneficiary(vpa=v, name=n, bank=b, kind="AEPS_TERMINAL", created_at=now - timedelta(days=900))
    fv, fn, fb, reason = FLAGGED
    benes[fv] = Beneficiary(vpa=fv, name=fn, bank=fb, created_at=now - timedelta(days=30),
                            flagged_fraud=True, flag_reason=reason)
    for vpa, name, bank, age in MULE_NODES:
        benes[vpa] = Beneficiary(vpa=vpa, name=name, bank=bank, created_at=now - timedelta(days=age),
                                 kind="AEPS_TERMINAL" if vpa.startswith("aeps") else "UPI")
    db.add_all(benes.values())
    for s, d, rel in LINKS:
        db.add(AccountLink(src_vpa=s, dst_vpa=d, relation=rel, observed_at=now - timedelta(days=1)))
    db.flush()

    seq = 0

    def hist_txn(user: User, bene: Beneficiary, amount: float, at: datetime, device: str | None,
                 channel: str = "UPI", lat=None, lon=None) -> None:
        nonlocal seq
        seq += 1
        db.add(Transaction(ref=f"HTX-{seq:05d}", user_id=user.id, beneficiary_id=bene.id, channel=channel,
                           amount=amount, device_ref=device, created_at=at, status="COMPLETED",
                           is_historical=True, lat=lat, lon=lon))

    # 60 days of normal history for the named users
    for ref, _name, _ph, _vpa, (lat, lon), dev, (lo, hi), hours in USERS:
        u = users[ref]
        if dev:
            db.add(Device(ref=dev, user_id=u.id, first_seen=now - timedelta(days=300), last_seen=now))
        for day in range(60, 0, -1):
            for _ in range(rnd.choice([0, 1, 1, 2]) if ref != "U-104" else rnd.choice([0, 0, 0, 0, 1])):
                local = (now - timedelta(days=day)).astimezone(IST).replace(
                    hour=rnd.choice(list(hours)), minute=rnd.randint(0, 59), second=0, microsecond=0)
                amount = float(round(rnd.uniform(lo, hi), -1))
                if ref == "U-104":
                    hist_txn(u, benes[HOME_AEPS_TERMINAL[0]], amount, local.astimezone(timezone.utc), None, "AEPS", lat, lon)
                else:
                    bene = benes[rnd.choice(REGULAR_BENES)[0]]
                    hist_txn(u, bene, amount, local.astimezone(timezone.utc), dev)

    # Fan-in into the mule beneficiary from several synthetic users over the last 2 days
    for i, ref in enumerate(EXTRA_SENDERS[:6]):
        hist_txn(users[ref], benes["rahultraders@ybl"], float(rnd.choice([9999, 14500, 19999, 24000])),
                 now - timedelta(hours=40 - i * 5), f"D-X{i:02d}")
    for i, ref in enumerate(EXTRA_SENDERS[2:]):
        hist_txn(users[ref], benes["fastkyc.refund@ibl"], float(rnd.choice([4999, 9999])),
                 now - timedelta(hours=30 - i * 3), f"D-Y{i:02d}")

    db.commit()


def reseed_risk(db: Session) -> None:
    """Replace only the risk-module tables; dispute cases are untouched."""
    from sqlalchemy import delete
    from app.models import AuditLog, RiskSignal
    for m in (RiskSignal, Transaction, Device, AccountLink, Beneficiary, User):
        db.execute(delete(m))
    db.execute(delete(AuditLog).where(AuditLog.case_id.is_(None)))
    db.commit()
    seed(db)


def ensure_seeded(db: Session) -> None:
    from sqlalchemy import func, select
    if not db.scalar(select(func.count()).select_from(User)):
        seed(db)


def reset_database() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)


if __name__ == "__main__":
    reset_database()
    print("Seeded synthetic dataset.")
