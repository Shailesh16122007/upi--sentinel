"""Case workflow between the three roles: submit, transitions, bank dispositions, evidence requests,
notifications and the customer's case view. All state lives in the database."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api import serial
from app.api.cases import get_case
from app.api.deps import current_account, roles
from app.db import get_db
from app.models import (Account, Case, CaseAction, CaseStatusOption, EvidenceFile, EvidenceRequest, Notification)
from app.services import crosscase, lifecycle, notify
from app.services.accounts import onboarded_banks
from app.services.audit import audit
from app.services.permissions import require_view, with_cyber

router = APIRouter(prefix="/api/v1", tags=["Workflow"])


def _now():
    return datetime.now(timezone.utc)


# ------------------------------------------------------------------ submit

class SubmitIn(BaseModel):
    bank: str | None = Field(None, max_length=80, description="Bank to send the case to (defaults to the customer's bank)")


@router.post("/cases/{case_id}/submit", summary="Customer submits the case for review")
def submit(case_id: str, req: SubmitIn | None = None, db: Session = Depends(get_db), acc: Account = Depends(roles("VICTIM"))):
    c = get_case(db, case_id, acc)
    n = db.scalar(select(func.count()).select_from(EvidenceFile).where(EvidenceFile.case_id == c.id)) or 0
    busy = db.scalar(select(func.count()).select_from(EvidenceFile).where(
        EvidenceFile.case_id == c.id, EvidenceFile.status.in_(["RECEIVED", "PROCESSING"]))) or 0
    if not n:
        raise HTTPException(409, "Please upload at least one piece of proof before submitting.")
    if busy:
        raise HTTPException(409, "We are still reading your files. Please wait a moment and try again.")
    if req and req.bank:
        if req.bank not in onboarded_banks(db):
            raise HTTPException(422, "That bank is not available on this platform yet.")
        c.bank_org = req.bank
    lifecycle.apply(db, c, "submit", acc, detail={"bank": c.bank_org, "evidence": n})
    db.commit()
    crosscase.refresh(db, c)  # look for related cases now that the case is submitted
    return serial.full(db, c, acc)


# ------------------------------------------------------------------ transitions

class ActionIn(BaseModel):
    action: str = Field(..., max_length=40)
    note: str | None = Field(None, max_length=4000)


@router.post("/cases/{case_id}/actions", summary="Apply a lifecycle transition (validated by the state machine)")
def act(case_id: str, req: ActionIn, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    if req.action in lifecycle.INDIRECT:
        raise HTTPException(422, "Use the dedicated endpoint for this action.")
    lifecycle.apply(db, c, req.action, acc, req.note)
    db.commit()
    return serial.full(db, c, acc)


@router.get("/cases/{case_id}/actions", summary="Case action history (role-filtered)")
def action_history(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    rows = db.scalars(select(CaseAction).where(CaseAction.case_id == c.id).order_by(CaseAction.created_at)).all()
    out = []
    for x in rows:
        if acc.role == "VICTIM":
            if x.victim_message:
                out.append({"at": x.created_at, "message": x.victim_message, "status_label": lifecycle.label(x.to_status or "", "VICTIM")})
            continue
        if acc.role == "BANK" and x.actor_role == "CYBER" and x.action not in ("cyber_accept", "cyber_return", "cyber_request_info"):
            note = None  # cyber-crime internal reasoning stays with cyber crime
        else:
            note = x.note
        actor = db.get(Account, x.actor_id) if x.actor_id else None
        out.append({"at": x.created_at, "action": x.action,
                    "label": lifecycle.BY_ACTION[x.action].label if x.action in lifecycle.BY_ACTION else x.action.replace("_", " ").capitalize(),
                    "role": x.actor_role, "actor": actor.name if actor else "System", "from": x.from_status, "to": x.to_status,
                    "to_label": lifecycle.label(x.to_status or ""), "note": note, "detail": x.detail})
    return out


# ------------------------------------------------------------------ dispositions (configurable)

@router.get("/status-options", summary="Configurable bank dispositions")
def status_options(db: Session = Depends(get_db), acc: Account = Depends(roles("BANK", "CYBER"))):
    q = select(CaseStatusOption).where(CaseStatusOption.active.is_(True), (CaseStatusOption.org.is_(None)) |
                                       (CaseStatusOption.org == acc.org)).order_by(CaseStatusOption.category, CaseStatusOption.sort)
    out: dict[str, list] = {}
    for o in db.scalars(q):
        out.setdefault(o.category, []).append({"code": o.code, "label": o.label, "org": o.org})
    return out


class OptionIn(BaseModel):
    category: str = Field(..., pattern="^(BANK_OUTCOME|REVERSAL|ACCOUNT_ACTION)$")
    label: str = Field(..., min_length=2, max_length=80)


@router.post("/status-options", status_code=201, summary="Add a disposition for your bank")
def add_option(req: OptionIn, db: Session = Depends(get_db), acc: Account = Depends(roles("BANK"))):
    code = "".join(ch if ch.isalnum() else "_" for ch in req.label.upper()).strip("_")[:40]
    if db.scalar(select(CaseStatusOption).where(CaseStatusOption.org == acc.org, CaseStatusOption.category == req.category,
                                                CaseStatusOption.code == code)):
        raise HTTPException(409, "That option already exists.")
    db.add(CaseStatusOption(org=acc.org, category=req.category, code=code, label=req.label.strip(), sort=100))
    audit(db, "STATUS_OPTION_ADDED", acc.name, result=f"{req.category}: {req.label}"[:255], actor_id=acc.id, actor_role=acc.role)
    db.commit()
    return {"code": code, "label": req.label}


class DispositionIn(BaseModel):
    bank_outcome: str | None = Field(None, max_length=40)
    reversal_status: str | None = Field(None, max_length=40)
    account_action: str | None = Field(None, max_length=40)
    priority: str | None = Field(None, pattern="^(NORMAL|HIGH)$")
    note: str | None = Field(None, max_length=2000)


VICTIM_VISIBLE = {"reversal_status"}


@router.post("/cases/{case_id}/dispositions", summary="Record bank outcome, account action, reversal status or priority")
def dispositions(case_id: str, req: DispositionIn, db: Session = Depends(get_db), acc: Account = Depends(roles("BANK"))):
    c = get_case(db, case_id, acc)
    if c.status in ("DRAFT", "CLOSED"):
        raise HTTPException(409, "Dispositions cannot be changed in this state.")
    q = select(CaseStatusOption).where((CaseStatusOption.org.is_(None)) | (CaseStatusOption.org == acc.org))
    valid = {(o.category, o.code): o.label for o in db.scalars(q)}
    changes = {}
    for fld, cat in (("bank_outcome", "BANK_OUTCOME"), ("reversal_status", "REVERSAL"), ("account_action", "ACCOUNT_ACTION")):
        v = getattr(req, fld)
        if v is None or v == getattr(c, fld):
            continue
        if (cat, v) not in valid:
            raise HTTPException(422, f"'{v}' is not a configured option for {fld.replace('_', ' ')}.")
        changes[fld] = {"from": getattr(c, fld), "to": v, "label": valid[(cat, v)]}
        setattr(c, fld, v)
    if req.priority and req.priority != (c.priority or "NORMAL"):
        changes["priority"] = {"from": c.priority or "NORMAL", "to": req.priority, "label": req.priority.title()}
        c.priority = req.priority
    if not changes:
        raise HTTPException(422, "Nothing changed.")
    c.last_activity_at = _now()
    msg = None
    if "reversal_status" in changes:
        msg = f"Payment recovery update: {changes['reversal_status']['label']}."
        notify.victim(db, c, "REVERSAL", msg, f"Case {c.ref}")
    db.add(CaseAction(case_id=c.id, actor_id=acc.id, actor_role=acc.role, action="disposition",
                      from_status=c.status, to_status=c.status, detail=changes, note=req.note, victim_message=msg))
    audit(db, "DISPOSITION_CHANGED", acc.name, case_id=c.id,
          result="; ".join(f"{k}: {v['label']}" for k, v in changes.items())[:255], actor_id=acc.id, actor_role=acc.role)
    if with_cyber(c):
        notify.cyber(db, c, "BANK_ACTION", f"{c.ref}: bank recorded " + ", ".join(v["label"] for v in changes.values()))
    db.commit()
    return serial.full(db, c, acc)


# ------------------------------------------------------------------ evidence / information requests

REQUEST_ITEMS = ["Transaction screenshot", "Bank statement", "Identity document", "Call recording", "Message screenshot",
                 "Additional transaction details", "Other"]


class RequestIn(BaseModel):
    items: list[str] = Field(..., min_length=1, max_length=10)
    message: str = Field(..., min_length=5, max_length=2000)


def _req_out(db: Session, r: EvidenceRequest) -> dict:
    by = db.get(Account, r.requested_by) if r.requested_by else None
    evs = [db.get(EvidenceFile, i) for i in (r.evidence_ids or [])]
    return {"id": r.id, "case_id": r.case_id, "items": r.items, "message": r.message, "status": r.status,
            "requested_role": r.requested_role, "target_role": r.target_role, "requested_by": by.name if by else None,
            "created_at": r.created_at, "fulfilled_at": r.fulfilled_at, "response_note": r.response_note,
            "evidence": [{"id": e.id, "code": e.code, "name": e.original_name} for e in evs if e]}


@router.get("/request-items")
def request_items(_: Account = Depends(current_account)):
    return REQUEST_ITEMS


@router.post("/cases/{case_id}/requests", status_code=201,
             summary="Bank asks the customer for evidence, or cyber crime asks the bank for information")
def create_request(case_id: str, req: RequestIn, db: Session = Depends(get_db), acc: Account = Depends(roles("BANK", "CYBER"))):
    c = get_case(db, case_id, acc)
    if acc.role == "BANK":
        action, target = "request_evidence", "VICTIM"
    else:
        action, target = "cyber_request_info", "BANK"
    bad = [i for i in req.items if i not in REQUEST_ITEMS]
    if bad:
        raise HTTPException(422, f"Unknown item(s): {', '.join(bad)}")
    if c.status == "SUBMITTED" and acc.role == "BANK":
        lifecycle.apply(db, c, "start_review", acc)
    r = EvidenceRequest(case_id=c.id, requested_by=acc.id, requested_role=acc.role, target_role=target, items=req.items,
                        message=req.message.strip())
    db.add(r)
    db.flush()
    lifecycle.apply(db, c, action, acc, req.message, detail={"request_id": r.id, "items": req.items})
    audit(db, "EVIDENCE_REQUESTED", acc.name, case_id=c.id, result=f"to {target}: {', '.join(req.items)}"[:255],
          actor_id=acc.id, actor_role=acc.role)
    if target == "VICTIM":
        notify.victim(db, c, "EVIDENCE_REQUEST", "Your bank has requested additional evidence.",
                      f"{', '.join(req.items)} — {req.message[:200]}")
    else:
        notify.bank(db, c, "INFO_REQUEST", f"Cyber crime requested information for {c.ref}", req.message[:300])
    db.commit()
    return _req_out(db, r)


@router.get("/cases/{case_id}/requests")
def list_requests(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    q = select(EvidenceRequest).where(EvidenceRequest.case_id == c.id).order_by(EvidenceRequest.created_at.desc())
    rows = db.scalars(q).all()
    if acc.role == "VICTIM":
        rows = [r for r in rows if r.target_role == "VICTIM"]
    return [_req_out(db, r) for r in rows]


class RespondIn(BaseModel):
    note: str | None = Field(None, max_length=2000)


@router.post("/requests/{request_id}/respond", summary="Answer a request (customer → bank, bank → cyber crime)")
def respond(request_id: str, req: RespondIn, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    r = db.get(EvidenceRequest, request_id)
    if not r:
        raise HTTPException(404, "Request not found")
    c = db.get(Case, r.case_id)
    require_view(acc, c)
    if r.target_role != acc.role:
        raise HTTPException(403, "This request is not addressed to you.")
    if r.status != "OPEN":
        raise HTTPException(409, "This request has already been answered.")
    if acc.role == "BANK" and not (req.note or "").strip():
        raise HTTPException(422, "Please describe the information you are providing.")
    r.status, r.fulfilled_at, r.fulfilled_by, r.response_note = "FULFILLED", _now(), acc.id, (req.note or "").strip() or None
    audit(db, "REQUEST_RESPONDED", acc.name, case_id=c.id, result=(req.note or "responded")[:200], actor_id=acc.id, actor_role=acc.role)
    if acc.role == "VICTIM" and c.status == "EVIDENCE_REQUESTED":
        lifecycle.apply(db, c, "evidence_provided", acc, req.note)
        notify.bank(db, c, "REQUEST_ANSWERED", f"Customer answered the evidence request for {c.ref}", (req.note or "")[:300])
    elif acc.role == "BANK" and c.status == "INFO_REQUESTED":
        lifecycle.apply(db, c, "bank_provide_info", acc, req.note)
    db.commit()
    return _req_out(db, r)


@router.get("/requests", summary="Open requests across visible cases")
def all_requests(status: str = "OPEN", db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    from app.services.permissions import visible_cases
    ids = [c.id for c in db.scalars(visible_cases(acc, select(Case)))]
    if not ids:
        return []
    rows = db.scalars(select(EvidenceRequest).where(EvidenceRequest.case_id.in_(ids), EvidenceRequest.status == status)
                      .order_by(EvidenceRequest.created_at.desc())).all()
    if acc.role == "VICTIM":
        rows = [r for r in rows if r.target_role == "VICTIM"]
    out = []
    for r in rows:
        c = db.get(Case, r.case_id)
        out.append({**_req_out(db, r), "case_ref": c.ref, "case_status": lifecycle.label(c.status, acc.role)})
    return out


# ------------------------------------------------------------------ customer view

@router.get("/cases/{case_id}/victim-view", summary="Everything the customer's case page needs, in plain language")
def victim_view(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(roles("VICTIM"))):
    c = get_case(db, case_id, acc)
    full = serial.full(db, c, acc)
    reqs = [_req_out(db, r) for r in db.scalars(select(EvidenceRequest).where(
        EvidenceRequest.case_id == c.id, EvidenceRequest.target_role == "VICTIM").order_by(EvidenceRequest.created_at.desc()))]
    updates = [{"at": x.created_at, "message": x.victim_message} for x in db.scalars(
        select(CaseAction).where(CaseAction.case_id == c.id).order_by(CaseAction.created_at.desc())) if x.victim_message]
    return {"case": full, "requests": reqs, "updates": updates, "banks": onboarded_banks(db)}


# ------------------------------------------------------------------ notifications

@router.get("/notifications")
def notifications(db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    rows = db.scalars(select(Notification).where(Notification.account_id == acc.id)
                      .order_by(Notification.created_at.desc()).limit(100)).all()
    refs = {c.id: c.ref for c in db.scalars(select(Case).where(Case.id.in_([n.case_id for n in rows if n.case_id] or [""])))}
    return {"unread": sum(1 for n in rows if n.read_at is None),
            "items": [{"id": n.id, "kind": n.kind, "title": n.title, "body": n.body, "case_id": n.case_id,
                       "case_ref": refs.get(n.case_id), "created_at": n.created_at, "read": n.read_at is not None} for n in rows]}


class ReadIn(BaseModel):
    ids: list[str] | None = None


@router.post("/notifications/read", status_code=204)
def mark_read(req: ReadIn, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    q = select(Notification).where(Notification.account_id == acc.id, Notification.read_at.is_(None))
    if req.ids:
        q = q.where(Notification.id.in_(req.ids))
    for n in db.scalars(q):
        n.read_at = _now()
    db.commit()
