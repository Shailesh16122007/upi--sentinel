"""Case lifecycle — an explicit state machine. Every transition is validated, persisted as a CaseAction,
audited, and produces the notifications for the people involved.

    DRAFT ─submit→ SUBMITTED ─start_review→ BANK_REVIEW ⇄ EVIDENCE_REQUESTED (customer uploads → back)
                                             │
                                             ├─escalate→ ESCALATED ─accept→ CYBER_REVIEW ⇄ INFO_REQUESTED (bank responds)
                                             │                        └─return→ BANK_REVIEW
                                             │           CYBER_REVIEW → UNDER_INVESTIGATION ⇄ PENDING → RESOLVED → CLOSED
                                             └─resolve→ RESOLVED ─close→ CLOSED   (reopen / resume go back)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Account, Case, CaseAction, CaseAssignment, EvidenceFile, Investigation
from app.services import notify
from app.services.audit import audit
from app.services.permissions import with_cyber

STATES: dict[str, tuple[str, str]] = {
    # code: (investigator label, customer label)
    "DRAFT": ("Draft (not submitted)", "Not submitted yet"),
    "SUBMITTED": ("New", "Submitted — waiting for the bank"),
    "BANK_REVIEW": ("Under bank review", "Under bank review"),
    "EVIDENCE_REQUESTED": ("Additional evidence requested", "Action required"),
    "ESCALATED": ("Escalated to cyber crime", "Sent to cyber crime"),
    "CYBER_REVIEW": ("Cyber crime review", "Under cyber crime review"),
    "INFO_REQUESTED": ("Information requested from bank", "Under cyber crime review"),
    "UNDER_INVESTIGATION": ("Under investigation", "Under investigation by cyber crime"),
    "PENDING": ("Pending", "Pending"),
    "RESOLVED": ("Resolved", "Resolved"),
    "CLOSED": ("Closed", "Closed"),
}
BANK_STAGES = {"SUBMITTED", "BANK_REVIEW", "EVIDENCE_REQUESTED"}
CYBER_STAGES = {"ESCALATED", "CYBER_REVIEW", "INFO_REQUESTED", "UNDER_INVESTIGATION", "PENDING"}


@dataclass(frozen=True)
class T:
    action: str
    frm: frozenset
    to: str
    roles: frozenset
    label: str
    victim_msg: str | None = None
    note_required: bool = False
    holder: str | None = None  # "BANK" / "CYBER": only while the case is in that party's hands


def _t(action, frm, to, roles, label, victim_msg=None, note_required=False, holder=None):
    return T(action, frozenset(frm), to, frozenset(roles), label, victim_msg, note_required, holder)


TRANSITIONS: list[T] = [
    _t("submit", {"DRAFT"}, "SUBMITTED", {"VICTIM"}, "Submit case", "Your case has been submitted for review."),
    _t("start_review", {"SUBMITTED"}, "BANK_REVIEW", {"BANK"}, "Start review", "Your case has been received by the bank."),
    _t("request_evidence", {"SUBMITTED", "BANK_REVIEW"}, "EVIDENCE_REQUESTED", {"BANK"}, "Request more evidence",
       "Your bank has requested additional evidence.", holder="BANK"),
    _t("evidence_provided", {"EVIDENCE_REQUESTED"}, "BANK_REVIEW", {"VICTIM", "BANK", "SYSTEM"}, "Evidence provided",
       "Your additional evidence was sent to the bank."),
    _t("escalate", {"BANK_REVIEW"}, "ESCALATED", {"BANK"}, "Escalate to cyber crime",
       "Your case has been escalated to cyber crime.", note_required=True),
    _t("bank_resolve", {"BANK_REVIEW"}, "RESOLVED", {"BANK"}, "Mark resolved", "Your case has been resolved by the bank.",
       note_required=True),
    _t("bank_close", {"BANK_REVIEW", "RESOLVED"}, "CLOSED", {"BANK"}, "Close case", "Your case has been closed.",
       note_required=True, holder="BANK"),
    _t("bank_reopen", {"RESOLVED", "CLOSED"}, "BANK_REVIEW", {"BANK"}, "Reopen case", "Your case has been reopened for review.",
       note_required=True, holder="BANK"),
    _t("cyber_accept", {"ESCALATED"}, "CYBER_REVIEW", {"CYBER"}, "Accept case", "Cyber crime has accepted your case for review."),
    _t("cyber_request_info", {"ESCALATED", "CYBER_REVIEW", "UNDER_INVESTIGATION", "PENDING"}, "INFO_REQUESTED", {"CYBER"},
       "Request information from bank", None),
    _t("bank_provide_info", {"INFO_REQUESTED"}, "CYBER_REVIEW", {"BANK"}, "Provide requested information", None),
    _t("cyber_return", {"ESCALATED", "CYBER_REVIEW"}, "BANK_REVIEW", {"CYBER"}, "Return to bank",
       "Your case is back with the bank for review.", note_required=True),
    _t("cyber_investigate", {"CYBER_REVIEW", "PENDING"}, "UNDER_INVESTIGATION", {"CYBER"}, "Mark under investigation",
       "Cyber crime is investigating your case."),
    _t("cyber_pending", {"CYBER_REVIEW", "UNDER_INVESTIGATION"}, "PENDING", {"CYBER"}, "Mark pending",
       "Your case is pending with cyber crime.", note_required=True),
    _t("cyber_resolve", {"CYBER_REVIEW", "UNDER_INVESTIGATION", "PENDING"}, "RESOLVED", {"CYBER"}, "Mark resolved",
       "Your case has been resolved.", note_required=True),
    _t("cyber_close", {"CYBER_REVIEW", "UNDER_INVESTIGATION", "PENDING", "RESOLVED"}, "CLOSED", {"CYBER"}, "Close case",
       "Your case has been closed.", note_required=True, holder="CYBER"),
    _t("cyber_resume", {"RESOLVED", "CLOSED"}, "UNDER_INVESTIGATION", {"CYBER"}, "Resume investigation",
       "Cyber crime has resumed work on your case.", note_required=True, holder="CYBER"),
]
BY_ACTION = {t.action: t for t in TRANSITIONS}
# actions driven by their own endpoints (they need extra data)
INDIRECT = {"submit", "request_evidence", "evidence_provided", "cyber_request_info", "bank_provide_info"}


def label(status: str, role: str = "BANK") -> str:
    s = STATES.get(status, (status, status))
    return s[1] if role == "VICTIM" else s[0]


def _holder_ok(t: T, case: Case) -> bool:
    if t.holder == "BANK":
        return not with_cyber(case)
    if t.holder == "CYBER":
        return with_cyber(case)
    return True


def allowed(case: Case, role: str) -> list[T]:
    return [t for t in TRANSITIONS if case.status in t.frm and role in t.roles and _holder_ok(t, case)]


def _now():
    return datetime.now(timezone.utc)


def apply(db: Session, case: Case, action: str, actor: Account | None, note: str | None = None,
          detail: dict | None = None) -> CaseAction:
    t = BY_ACTION.get(action)
    role = actor.role if actor else "SYSTEM"
    if t is None:
        raise HTTPException(422, f"Unknown action '{action}'.")
    if role not in t.roles:
        raise HTTPException(403, f"'{t.label}' is not available to your role.")
    if case.status not in t.frm or not _holder_ok(t, case):
        raise HTTPException(409, f"'{t.label}' is not possible while the case is '{label(case.status)}'.")
    if t.note_required and not (note or "").strip():
        raise HTTPException(422, f"Please add a note explaining '{t.label}'.")
    old = case.status
    case.status = t.to
    now = _now()
    case.last_activity_at = now
    if action == "submit":
        case.submitted_at = now
    elif action == "escalate":
        case.escalated_at, case.authority_status = now, "ACTIVE"
    elif action == "cyber_return":
        case.authority_status = "RETURNED"
    if t.to == "RESOLVED":
        case.resolved_at = now
    elif t.to == "CLOSED":
        case.closed_at = now
    elif old in ("RESOLVED", "CLOSED"):
        case.resolved_at = case.closed_at = None
    ca = CaseAction(case_id=case.id, actor_id=actor.id if actor else None, actor_role=role, action=action,
                    from_status=old, to_status=t.to, detail=detail or {}, note=(note or "").strip() or None,
                    victim_message=t.victim_msg)
    db.add(ca)
    who = actor.name if actor else "system"
    audit(db, "STATUS_CHANGED", who, case_id=case.id, result=f"{old} -> {t.to} ({action})"[:255],
          actor_id=actor.id if actor else None, actor_role=role)
    _side_effects(db, case, t, actor, note)
    return ca


def _investigation(db: Session, case: Case, role: str, actor: Account | None) -> Investigation:
    inv = db.scalar(select(Investigation).where(Investigation.case_id == case.id, Investigation.role == role))
    if inv is None:
        inv = Investigation(case_id=case.id, role=role, opened_by=actor.id if actor else None)
        db.add(inv)
    elif inv.status == "COMPLETED":
        inv.status, inv.completed_at = "OPEN", None
    return inv


def assign(db: Session, case: Case, actor: Account) -> None:
    active = db.scalar(select(CaseAssignment).where(CaseAssignment.case_id == case.id, CaseAssignment.role == actor.role,
                                                    CaseAssignment.active.is_(True)))
    if active and active.account_id == actor.id:
        return
    if active:
        active.active = False
    db.add(CaseAssignment(case_id=case.id, account_id=actor.id, role=actor.role))


def _side_effects(db: Session, case: Case, t: T, actor: Account | None, note: str | None) -> None:
    ex = actor.id if actor else None
    a = t.action
    if t.victim_msg and a != "request_evidence":  # the request endpoint sends its own, more specific notice
        notify.victim(db, case, f"STATUS_{t.to}", t.victim_msg, f"Case {case.ref}")
    if a == "submit":
        n = db.query(EvidenceFile).filter(EvidenceFile.case_id == case.id).count()
        notify.bank(db, case, "NEW_CASE", f"New case received: {case.ref}", f"{n} evidence item(s) submitted by the customer.")
    elif a == "start_review" and actor:
        _investigation(db, case, "BANK", actor)
        assign(db, case, actor)
    elif a == "escalate":
        _investigation(db, case, "BANK", actor).status = "COMPLETED"
        notify.cyber(db, case, "ESCALATED", f"New case escalated by bank: {case.ref}", (note or "")[:300])
    elif a == "cyber_accept" and actor:
        _investigation(db, case, "CYBER", actor)
        assign(db, case, actor)
        notify.bank(db, case, "CYBER_ACCEPTED", f"Cyber crime accepted {case.ref}")
    elif a == "cyber_return":
        notify.bank(db, case, "RETURNED", f"{case.ref} returned to the bank by cyber crime", (note or "")[:300])
    elif a == "bank_provide_info":
        notify.cyber(db, case, "INFO_PROVIDED", f"Bank provided the requested information for {case.ref}", (note or "")[:300], ex)
    elif a in ("cyber_investigate", "cyber_pending", "cyber_resolve", "cyber_close", "cyber_resume"):
        notify.bank(db, case, f"CYBER_{t.to}", f"{case.ref}: cyber crime status is now '{label(t.to)}'")
        if t.to in ("RESOLVED", "CLOSED"):
            inv = db.scalar(select(Investigation).where(Investigation.case_id == case.id, Investigation.role == "CYBER"))
            if inv:
                inv.status, inv.completed_at, inv.conclusion = "COMPLETED", _now(), note
    elif a in ("bank_resolve", "bank_close"):
        inv = db.scalar(select(Investigation).where(Investigation.case_id == case.id, Investigation.role == "BANK"))
        if inv:
            inv.status, inv.completed_at, inv.conclusion = "COMPLETED", _now(), note


def tracker(case: Case, evidence_count: int) -> list[dict]:
    """The customer's 'Where your case is now' steps, derived from the persisted lifecycle."""
    s = case.status
    submitted = s != "DRAFT"
    escalated = case.escalated_at is not None
    finished = s in ("RESOLVED", "CLOSED")
    cyber_now = with_cyber(case) and not finished
    steps = [
        {"key": "submitted", "label": "Complaint submitted", "state": "done" if submitted else "current",
         "at": case.submitted_at},
        {"key": "evidence", "label": "Evidence received",
         "state": "done" if submitted and evidence_count else ("current" if not submitted else "todo")},
        {"key": "bank", "label": "Bank review",
         "state": "done" if submitted and (escalated or finished) and not (s in BANK_STAGES)
         else "current" if s in BANK_STAGES else "todo"},
        {"key": "cyber", "label": "Cyber crime review",
         "state": "current" if cyber_now else "done" if escalated and finished else
         "skipped" if finished and not escalated else "todo"},
        {"key": "resolution", "label": "Case resolution", "state": "done" if finished else "todo",
         "at": case.resolved_at or case.closed_at},
    ]
    if s == "EVIDENCE_REQUESTED":
        steps[2]["note"] = "Action required: the bank asked for more evidence"
    return steps
