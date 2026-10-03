"""In-app notifications. Recipients are resolved from the case's routing (owner, bank, cyber unit)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Case, Notification


def _send(db: Session, accounts, case: Case | None, kind: str, title: str, body: str | None = None,
          exclude: str | None = None) -> None:
    for a in accounts:
        if a.id != exclude and a.is_active and not a.is_synthetic:
            db.add(Notification(account_id=a.id, case_id=case.id if case else None, kind=kind, title=title[:200],
                                body=(body or None) and body[:500]))


def victim(db: Session, case: Case, kind: str, title: str, body: str | None = None) -> None:
    if case.owner_id:
        acc = db.get(Account, case.owner_id)
        if acc:
            _send(db, [acc], case, kind, title, body)


def bank(db: Session, case: Case, kind: str, title: str, body: str | None = None, exclude: str | None = None) -> None:
    if case.bank_org:
        accs = db.scalars(select(Account).where(Account.role == "BANK", Account.org == case.bank_org)).all()
        _send(db, accs, case, kind, title, body, exclude)


def cyber(db: Session, case: Case, kind: str, title: str, body: str | None = None, exclude: str | None = None) -> None:
    _send(db, db.scalars(select(Account).where(Account.role == "CYBER")).all(), case, kind, title, body, exclude)
