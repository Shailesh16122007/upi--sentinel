"""Backend authorisation. Every case endpoint goes through these checks — hiding a button is never enough."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import Select, or_

from app.models import Account, Case


def can_view(acc: Account, case: Case) -> bool:
    if acc.role == "VICTIM":
        return case.owner_id == acc.id
    if acc.role == "BANK":
        return case.status != "DRAFT" and case.bank_org is not None and case.bank_org == acc.org
    if acc.role == "CYBER":
        return case.escalated_at is not None
    return False


def require_view(acc: Account, case: Case) -> None:
    if not can_view(acc, case):
        # 404, not 403: do not reveal that another person's case exists
        raise HTTPException(404, "Case not found")


def require_staff(acc: Account) -> None:
    if acc.role not in ("BANK", "CYBER"):
        raise HTTPException(403, "This information is available to investigators only.")


def visible_cases(acc: Account, q: Select) -> Select:
    if acc.role == "VICTIM":
        return q.where(Case.owner_id == acc.id)
    if acc.role == "BANK":
        return q.where(Case.bank_org == acc.org, Case.status != "DRAFT")
    if acc.role == "CYBER":
        return q.where(Case.escalated_at.is_not(None))
    return q.where(or_(False))


def with_cyber(case: Case) -> bool:
    """True while the case is in cyber crime's hands (escalated and not returned to the bank)."""
    return case.escalated_at is not None and case.authority_status == "ACTIVE"


def can_upload(acc: Account, case: Case) -> bool:
    if acc.role == "VICTIM":
        return case.owner_id == acc.id and case.status not in ("CLOSED",)
    if acc.role == "BANK":
        return can_view(acc, case) and not with_cyber(case) and case.status not in ("CLOSED",) or \
            (can_view(acc, case) and case.status == "INFO_REQUESTED")
    return False
