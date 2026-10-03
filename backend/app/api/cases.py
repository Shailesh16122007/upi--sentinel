"""Case API: creation, evidence, analysis outputs, reports. Every endpoint checks the caller's role and
their right to see this specific case on the server (a changed URL never exposes someone else's case)."""
from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api import serial
from app.api.deps import current_account, require_api_key, roles
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import (Account, AuditLog, Case, CaseTransaction, EvidenceFile, EvidenceHash, EvidenceRequest,
                        Finding, InvestigatorNote, Report, ReportVersion, TimelineEvent, Transaction, VictimProfile)
from app.schemas import CaseFromRiskTxn, PastedMessage, TranscriptIn
from app.services import cases as cases_svc
from app.services import crosscase, ingest, integrity, lifecycle, notify
from app.services import reports as reports_svc
from app.services.accounts import DEFAULT_BANK
from app.services.analysis.run import analyze as run_analysis
from app.services.audit import audit
from app.services.graph import evidence_graph
from app.services.permissions import can_upload, require_staff, require_view, visible_cases

log = logging.getLogger("sentinel.api")
router = APIRouter(prefix="/api/v1", tags=["Cases"])
_case_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(case_id: str) -> threading.Lock:
    with _locks_guard:
        return _case_locks.setdefault(case_id, threading.Lock())


def get_case(db: Session, case_id: str, acc: Account | None = None) -> Case:
    c = db.get(Case, case_id) or db.scalar(select(Case).where(Case.ref == case_id))
    if c is None:
        raise HTTPException(404, "Case not found")
    if acc is not None:
        require_view(acc, c)
    return c


def _a(acc: Account) -> dict:
    return {"actor_id": acc.id, "actor_role": acc.role}


# ------------------------------------------------------------------ cases

class CaseCreate(BaseModel):
    statement: str = Field(..., min_length=10, max_length=4000, description="What happened, in the customer's own words")
    approx_date: date | None = None
    claimed_amount: float | None = Field(None, gt=0, le=100_000_000)
    synthetic: bool = Field(False, description="Demo accounts only: mark the case as synthetic demonstration data")


@router.post("/cases", status_code=201, summary="Customer creates a case (statement first, evidence later)")
def create_case(req: CaseCreate, db: Session = Depends(get_db), acc: Account = Depends(roles("VICTIM"))):
    if req.synthetic and not acc.is_demo:
        raise HTTPException(403, "Only demo accounts can create synthetic demonstration cases.")
    prof = db.get(VictimProfile, acc.id)
    c = cases_svc.create(db, req.statement, req.approx_date, req.claimed_amount, acc.name, synthetic=req.synthetic,
                         owner=acc, bank_org=(prof.bank_name if prof and prof.bank_name else DEFAULT_BANK))
    return serial.full(db, c, acc)


@router.post("/cases/from-risk-transaction/{txn_id}", status_code=201, tags=["Risk API"],
             summary="Partner integration: open a dispute for a payment checked by the real-time risk API")
def create_from_risk(txn_id: str, req: CaseFromRiskTxn, db: Session = Depends(get_db), actor: str = Depends(require_api_key)):
    t = db.get(Transaction, txn_id) or db.scalar(select(Transaction).where(Transaction.ref == txn_id))
    if t is None:
        raise HTTPException(404, "Transaction not found")
    if t.status != "COMPLETED":
        raise HTTPException(409, f"Only completed payments can be disputed (this one is {t.status}).")
    c = cases_svc.create_from_risk_transaction(db, t, req.statement, actor)
    run_analysis(db, c, actor)
    d = db.scalar(select(CaseTransaction).where(CaseTransaction.case_id == c.id, CaseTransaction.kind == "DISPUTED"))
    return {"id": c.id, "ref": c.ref, "status": c.status, "disputed": reports_svc._txn(d)}


def _parse_amount(q: str) -> float | None:
    s = q.replace("₹", "").replace(",", "").replace("rs", "").replace("Rs", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


@router.get("/cases", summary="Cases visible to the signed-in person, with queue filters")
def list_cases(status: str | None = Query(None, description="Comma-separated statuses, or a group: new, review, action, "
                                                               "escalated, pending, resolved, closed, open"),
               synthetic: bool | None = None, amount_min: float | None = None, amount_max: float | None = None,
               date_from: date | None = None, date_to: date | None = None, completeness_min: int | None = None,
               beneficiary: str | None = None, q: str | None = None, priority: str | None = None,
               db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    groups = {
        "new": ["SUBMITTED"], "review": ["BANK_REVIEW", "CYBER_REVIEW", "UNDER_INVESTIGATION", "INFO_REQUESTED"],
        "action": ["EVIDENCE_REQUESTED", "INFO_REQUESTED"] if acc.role != "CYBER" else ["ESCALATED"],
        "escalated": ["ESCALATED", "CYBER_REVIEW", "INFO_REQUESTED", "UNDER_INVESTIGATION", "PENDING"],
        "pending": ["PENDING"], "resolved": ["RESOLVED"], "closed": ["CLOSED"],
        "open": [s for s in lifecycle.STATES if s not in ("RESOLVED", "CLOSED")],
        "done": ["RESOLVED", "CLOSED"],
    }
    query = visible_cases(acc, select(Case)).order_by(Case.created_at.desc())
    if status:
        sts = [x for part in status.split(",") for x in groups.get(part.strip().lower(), [part.strip().upper()])]
        query = query.where(Case.status.in_(sts))
    if synthetic is not None:
        query = query.where(Case.is_synthetic.is_(synthetic))
    if priority:
        query = query.where(Case.priority == priority.upper())
    rows = [serial.summary(db, c, acc) for c in db.scalars(query)]

    def amt(r):
        return r["disputed_amount"] if r["disputed_amount"] is not None else r["claimed_amount"]
    if amount_min is not None:
        rows = [r for r in rows if (amt(r) or 0) >= amount_min]
    if amount_max is not None:
        rows = [r for r in rows if amt(r) is not None and amt(r) <= amount_max]
    if date_from:
        rows = [r for r in rows if (r["submitted_at"] or r["created_at"]).date() >= date_from]
    if date_to:
        rows = [r for r in rows if (r["submitted_at"] or r["created_at"]).date() <= date_to]
    if completeness_min is not None:
        rows = [r for r in rows if (r["completeness"] or 0) >= completeness_min]
    if beneficiary:
        b = beneficiary.lower().strip()
        rows = [r for r in rows if b in (r.get("beneficiary") or "").lower()]
    if q:
        ids = {x["id"] for x in search_rows(db, acc, q)}
        rows = [r for r in rows if r["id"] in ids]
    return rows


def search_rows(db: Session, acc: Account, q: str) -> list[dict]:
    """Case ID, UTR / transaction ID, UPI ID, phone, beneficiary, amount or date — from the database."""
    q = q.strip()
    if not q:
        return []
    like = f"%{q.lower()}%"
    hits: dict[str, set] = {}

    def hit(cid, why):
        hits.setdefault(cid, set()).add(why)
    for c in db.scalars(select(Case).where(func.lower(Case.ref).like(like))):
        hit(c.id, "Case ID")
    from app.models import ExtractedEntity
    digits = "".join(ch for ch in q if ch.isdigit())
    for x in db.scalars(select(ExtractedEntity).where(
            ExtractedEntity.type.in_(("UTR", "UPI_REF", "TXN_ID", "UPI_ID", "PHONE", "PAYEE", "EMAIL", "ACCOUNT", "URL")),
            or_(func.lower(ExtractedEntity.normalized).like(like),
                *([func.lower(ExtractedEntity.normalized).like(f"%{digits}%")] if len(digits) >= 6 else [])))).all():
        hit(x.case_id, {"UTR": "UTR / reference", "UPI_REF": "UTR / reference", "TXN_ID": "Transaction ID", "UPI_ID": "UPI ID",
                        "PHONE": "Phone number", "PAYEE": "Beneficiary", "EMAIL": "E-mail", "ACCOUNT": "Account",
                        "URL": "Link"}[x.type])
    for t in db.scalars(select(CaseTransaction).where(CaseTransaction.kind != "HISTORICAL", or_(
            func.lower(CaseTransaction.beneficiary).like(like), func.lower(CaseTransaction.beneficiary_vpa).like(like),
            func.lower(CaseTransaction.reference).like(like)))):
        hit(t.case_id, "Beneficiary / reference")
    amount = _parse_amount(q)
    if amount is not None and amount >= 1:
        for t in db.scalars(select(CaseTransaction).where(CaseTransaction.kind == "DISPUTED",
                                                          CaseTransaction.amount.between(amount - 0.5, amount + 0.5))):
            hit(t.case_id, "Amount")
        for c in db.scalars(select(Case).where(Case.claimed_amount.between(amount - 0.5, amount + 0.5))):
            hit(c.id, "Amount (customer)")
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d %B %Y"):
        try:
            day = datetime.strptime(q, fmt).date()
        except ValueError:
            continue
        start = datetime.combine(day, datetime.min.time(), tzinfo=timezone(timedelta(hours=5, minutes=30)))
        for t in db.scalars(select(CaseTransaction).where(CaseTransaction.kind == "DISPUTED", CaseTransaction.occurred_at >= start,
                                                          CaseTransaction.occurred_at < start + timedelta(days=1))):
            hit(t.case_id, "Transaction date")
        break
    out = []
    for cid, why in hits.items():
        c = db.get(Case, cid)
        if not c:
            continue
        try:
            require_view(acc, c)
        except HTTPException:
            continue
        out.append({**serial.summary(db, c, acc), "matched_on": sorted(why)})
    return out


@router.get("/search", summary="Search cases (investigators)")
def search(q: str = Query(..., min_length=2, max_length=120), db: Session = Depends(get_db),
           acc: Account = Depends(roles("BANK", "CYBER"))):
    return search_rows(db, acc, q)


@router.get("/cases/{case_id}")
def read_case(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    return serial.full(db, c, acc)


@router.post("/cases/{case_id}/opened", status_code=204, summary="Record that an investigator opened the case")
def opened(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(roles("BANK", "CYBER"))):
    c = get_case(db, case_id, acc)
    last = db.scalar(select(AuditLog).where(AuditLog.case_id == c.id, AuditLog.action == "INVESTIGATOR_OPENED_CASE",
                                            AuditLog.actor_id == acc.id).order_by(AuditLog.created_at.desc()))
    now = datetime.now(timezone.utc)
    if last is None or (now - last.created_at) > timedelta(minutes=30):  # one line per working session, not per refresh
        audit(db, "INVESTIGATOR_OPENED_CASE", acc.name, case_id=c.id, result=f"{acc.role.title()} opened case", **_a(acc))
    if acc.role == "BANK" and c.status == "SUBMITTED":  # opening a new case starts the bank review
        lifecycle.apply(db, c, "start_review", acc)
    db.commit()


# ------------------------------------------------------------------ evidence

def _process_then_analyze(case_id: str, ev_ids: list[str], actor: str) -> None:
    with SessionLocal() as db:
        for eid in ev_ids:
            ev = db.get(EvidenceFile, eid)
            if ev and ev.status in ("RECEIVED", "PROCESSING", "FAILED", "UNAVAILABLE"):
                ingest.process(db, ev, actor)
        c = db.get(Case, case_id)
        busy = db.scalar(select(func.count()).select_from(EvidenceFile).where(
            EvidenceFile.case_id == case_id, EvidenceFile.status.in_(["RECEIVED", "PROCESSING"]))) or 0
        if c and not busy:
            with _lock(case_id):
                try:
                    run_analysis(db, c, "system")
                except Exception:  # noqa: BLE001
                    log.exception("Analysis failed for case %s", case_id)


def resume_pending() -> int:
    """After a restart, finish any evidence that was still queued or mid-processing."""
    with SessionLocal() as db:
        rows = db.execute(select(EvidenceFile.case_id, EvidenceFile.id).where(
            EvidenceFile.status.in_(["RECEIVED", "PROCESSING"]))).all()
    by_case: dict[str, list[str]] = {}
    for cid, eid in rows:
        by_case.setdefault(cid, []).append(eid)
    for cid, ids in by_case.items():
        threading.Thread(target=_process_then_analyze, args=(cid, ids, "system (resumed after restart)"), daemon=True).start()
    return len(rows)


def _after_upload(db: Session, c: Case, acc: Account, stored: list[EvidenceFile]) -> None:
    c.last_activity_at = datetime.now(timezone.utc)
    if acc.role == "VICTIM" and c.status == "EVIDENCE_REQUESTED":
        for r in db.scalars(select(EvidenceRequest).where(EvidenceRequest.case_id == c.id, EvidenceRequest.status == "OPEN",
                                                          EvidenceRequest.target_role == "VICTIM")):
            r.status, r.fulfilled_at, r.fulfilled_by = "FULFILLED", datetime.now(timezone.utc), acc.id
            r.evidence_ids = list(r.evidence_ids or []) + [e.id for e in stored]
        lifecycle.apply(db, c, "evidence_provided", acc, detail={"evidence": [e.code for e in stored]})
        notify.bank(db, c, "EVIDENCE_ADDED", f"Additional evidence uploaded for {c.ref}",
                    ", ".join(f"{e.code} {e.original_name}" for e in stored)[:300])
    elif c.status != "DRAFT":
        body = ", ".join(f"{e.code} {e.original_name}" for e in stored)[:300]
        if acc.role != "BANK":
            notify.bank(db, c, "EVIDENCE_ADDED", f"New evidence added to {c.ref}", body)
        if c.escalated_at and c.authority_status == "ACTIVE":
            notify.cyber(db, c, "EVIDENCE_ADDED", f"New evidence added to {c.ref}", body)


@router.post("/cases/{case_id}/evidence", status_code=202,
             summary="Upload files. Accepted files are processed in the background; duplicates and unreadable types are reported.")
async def upload(case_id: str, bg: BackgroundTasks, files: list[UploadFile] = File(...),
                 channel: str | None = Form(None), occurred_at: datetime | None = Form(None),
                 note: str | None = Form(None, max_length=500), db: Session = Depends(get_db),
                 acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    if not can_upload(acc, c):
        raise HTTPException(403 if acc.role == "CYBER" else 409, "Evidence cannot be added to this case right now.")
    s = get_settings()
    stored, rejected = [], []
    for f in files[:20]:
        data = await f.read(max(s.max_upload_mb, s.max_audio_mb) * 1024 * 1024 + 1)
        name = ingest.display_name(f.filename or "upload")
        try:
            stored.append(ingest.store(db, c, f.filename or "upload", data, channel=channel, time_hint=_tz(occurred_at),
                                       note=note, actor=acc.name, source="upload" if acc.role == "VICTIM" else acc.role.lower(),
                                       uploaded_by_id=acc.id, uploaded_by_role=acc.role))
        except ingest.Duplicate as e:
            rejected.append({"name": name, "reason": str(e), "duplicate_of": e.existing.code})
        except ingest.Rejected as e:
            rejected.append({"name": name, "reason": str(e)})
            audit(db, "EVIDENCE_REJECTED", acc.name, case_id=c.id, result=f"{name}: {e}"[:200], **_a(acc))
    if stored:
        _after_upload(db, c, acc, stored)
    db.commit()
    if stored:
        bg.add_task(_process_then_analyze, c.id, [e.id for e in stored], acc.name)
    elif not rejected:
        raise HTTPException(422, "No files received")
    return {"accepted": [serial.evidence(db, e, False) for e in stored], "rejected": rejected}


@router.post("/cases/{case_id}/evidence/text", status_code=202, summary="Paste a message (SMS, chat) directly")
def paste(case_id: str, req: PastedMessage, bg: BackgroundTasks, db: Session = Depends(get_db),
          acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    if not can_upload(acc, c):
        raise HTTPException(403 if acc.role == "CYBER" else 409, "Evidence cannot be added to this case right now.")
    name = (req.label or "pasted_message").strip().replace(" ", "_")[:60] + ".txt"
    try:
        ev = ingest.store(db, c, name, req.text.encode("utf-8"), channel="message", source="paste",
                          time_hint=_tz(req.occurred_at), actor=acc.name, uploaded_by_id=acc.id, uploaded_by_role=acc.role)
    except ingest.Duplicate as e:
        return {"accepted": [], "rejected": [{"name": name, "reason": "This message appears to have already been added.",
                                              "duplicate_of": e.existing.code}]}
    except ingest.Rejected as e:
        raise HTTPException(422, str(e))
    _after_upload(db, c, acc, [ev])
    db.commit()
    bg.add_task(_process_then_analyze, c.id, [ev.id], acc.name)
    return {"accepted": [serial.evidence(db, ev, False)], "rejected": []}


def _tz(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    from app.services.extraction.entities import IST
    return d if d.tzinfo else d.replace(tzinfo=IST)


@router.get("/cases/{case_id}/evidence")
def list_evidence(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    evs = db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == c.id).order_by(EvidenceFile.seq)).all()
    hs = {h.evidence_id: h for h in db.scalars(select(EvidenceHash).where(EvidenceHash.evidence_id.in_([e.id for e in evs] or [""])))}
    return [serial.evidence(db, e, True, hs.get(e.id)) for e in evs]


@router.get("/cases/{case_id}/evidence/{evidence_id}/file", summary="Original file (integrity-checked before serving)")
def evidence_file(case_id: str, evidence_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    e = db.get(EvidenceFile, evidence_id)
    if not e or e.case_id != c.id or not e.storage_path:
        raise HTTPException(404, "Evidence not found")
    result = integrity.verify(db, e)
    audit(db, "EVIDENCE_VIEWED", acc.name, case_id=c.id, evidence_id=e.id, result=f"{e.code} integrity {result}", **_a(acc))
    db.commit()
    if result != "MATCH":
        raise HTTPException(409, "Integrity check failed: the stored file does not match its recorded SHA-256.")
    return FileResponse(Path(e.storage_path), media_type=e.mime or "application/octet-stream", filename=e.original_name,
                        content_disposition_type="inline", headers={"Cache-Control": "no-store"})


@router.post("/cases/{case_id}/evidence/{evidence_id}/transcript",
             summary="Attach a human-provided transcript to an audio item (labelled as not machine-generated)")
def provide_transcript(case_id: str, evidence_id: str, req: TranscriptIn, db: Session = Depends(get_db),
                       acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    if not can_upload(acc, c):
        raise HTTPException(403, "You cannot change this case.")
    e = db.get(EvidenceFile, evidence_id)
    if not e or e.case_id != c.id or e.kind not in ("AUDIO", "VIDEO"):
        raise HTTPException(404, "Audio evidence not found")
    if e.status == "PROCESSED" and e.method and e.method.startswith("faster-whisper"):
        raise HTTPException(409, "This recording already has a machine transcript.")
    ingest.set_provided_transcript(db, e, req.text, acc.name)
    with _lock(c.id):
        run_analysis(db, c, acc.name)
    db.refresh(e)
    return serial.evidence(db, e)


@router.post("/cases/{case_id}/process", status_code=202, summary="(Re)process evidence that is pending, failed or unavailable")
def process(case_id: str, bg: BackgroundTasks, all: bool = Query(False), db: Session = Depends(get_db),
            acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    if acc.role == "CYBER":
        raise HTTPException(403, "Not available to your role.")
    q = select(EvidenceFile).where(EvidenceFile.case_id == c.id, EvidenceFile.kind != "SYSTEM")
    if not all:
        q = q.where(EvidenceFile.status.in_(["RECEIVED", "FAILED", "UNAVAILABLE"]))
    evs = db.scalars(q).all()
    for e in evs:
        e.status = "RECEIVED"
    db.commit()
    bg.add_task(_process_then_analyze, c.id, [e.id for e in evs], acc.name)
    return {"queued": [e.code for e in evs]}


# ------------------------------------------------------------------ analysis outputs

@router.post("/cases/{case_id}/analyze")
def analyze(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    busy = db.scalar(select(func.count()).select_from(EvidenceFile).where(
        EvidenceFile.case_id == c.id, EvidenceFile.status.in_(["RECEIVED", "PROCESSING"]))) or 0
    if busy:
        raise HTTPException(409, f"{busy} evidence item(s) are still being processed.")
    with _lock(c.id):
        run_analysis(db, c, acc.name)
    return serial.full(db, c, acc)


class SelectTxn(BaseModel):
    transaction_id: str


@router.post("/cases/{case_id}/disputed-transaction", summary="Choose which extracted transaction is the disputed one")
def select_disputed(case_id: str, req: SelectTxn, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    if acc.role == "CYBER" or (acc.role == "VICTIM" and c.status not in ("DRAFT", "EVIDENCE_REQUESTED")):
        raise HTTPException(403, "The disputed transaction can no longer be changed by you.")
    t = db.get(CaseTransaction, req.transaction_id)
    if not t or t.case_id != c.id or t.kind == "HISTORICAL":
        raise HTTPException(404, "Transaction not found in this case")
    tod = (t.fields or {}).get("time_of_day") or []
    c.disputed_selection = {"reference": t.reference, "amount": t.amount,
                            "occurred_at": t.occurred_at.isoformat() if t.occurred_at else None,
                            "time_of_day": tod[0]["value"] if tod else None, "sources": t.sources,
                            "by": acc.role, "at": datetime.now(timezone.utc).isoformat()}
    audit(db, "DISPUTED_TRANSACTION_SELECTED", acc.name, case_id=c.id,
          result=f"₹{t.amount or 0:,.0f} ref {t.reference or '—'}", **_a(acc))
    db.commit()
    with _lock(c.id):
        run_analysis(db, c, acc.name)
    return serial.full(db, c, acc)


@router.get("/cases/{case_id}/timeline")
def timeline(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    codes = {e.id: (e.code, e.original_name) for e in db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == c.id))}
    out = []
    for t in db.scalars(select(TimelineEvent).where(TimelineEvent.case_id == c.id).order_by(TimelineEvent.seq)):
        row = {"id": t.id, "occurred_at": t.occurred_at, "approximate": t.approximate, "time_label": t.time_label,
               "event_type": t.event_type, "simple": t.simple or t.description, "source_kinds": t.source_kinds or [],
               "reliability": t.reliability,
               "sources": [{"evidence_id": i, "label": codes.get(i, ("?",))[0], "name": codes.get(i, ("", ""))[1]} for i in t.evidence_ids]}
        if acc.role != "VICTIM":
            row.update({"description": t.description, "entity_ids": t.entity_ids})
        out.append(row)
    return out


@router.get("/cases/{case_id}/findings")
def findings(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    require_staff(acc)
    reviews: dict[str, list] = {}
    for n in reports_svc.notes_visible(db, c, acc.role):
        if n.finding_code:
            reviews.setdefault(n.finding_code, []).append(
                {"id": n.id, "author": n.author, "role": n.author_role, "assessment": n.assessment, "body": n.body,
                 "created_at": n.created_at, "finding_title": n.finding_title})
    return [{"id": f.id, "category": f.category, "code": f.code, "title": f.title, "detail": f.detail,
             "is_anomaly": f.is_anomaly, "is_conflict": f.is_conflict, "sources": f.sources, "data": f.data,
             "why": f.why, "certainty": f.certainty, "certainty_basis": f.certainty_basis,
             "human_reviews": reviews.get(f.code, [])}
            for f in db.scalars(select(Finding).where(Finding.case_id == c.id).order_by(Finding.seq))]


@router.get("/cases/{case_id}/graph")
def graph(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    require_staff(acc)
    return evidence_graph.build(db, c)


@router.get("/cases/{case_id}/history")
def history(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    require_staff(acc)
    rows = db.scalars(select(CaseTransaction).where(CaseTransaction.case_id == c.id, CaseTransaction.kind == "HISTORICAL")
                      .order_by(CaseTransaction.occurred_at)).all()
    return [{"occurred_at": t.occurred_at, "amount": t.amount, "beneficiary": t.beneficiary_vpa or t.beneficiary} for t in rows]


# ------------------------------------------------------------------ notes (investigators only)

class NoteIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)
    visibility: str | None = Field(None, pattern="^(BANK_AND_CYBER|CYBER_ONLY)$")
    finding_code: str | None = Field(None, max_length=40)
    assessment: str | None = Field(None, pattern="^(AGREE|DISAGREE|NEEDS_REVIEW)$")


def _note(n: InvestigatorNote) -> dict:
    return {"id": n.id, "author": n.author, "role": n.author_role, "body": n.body, "created_at": n.created_at,
            "visibility": n.visibility or "BANK_AND_CYBER", "finding_code": n.finding_code, "finding_title": n.finding_title,
            "assessment": n.assessment}


@router.get("/cases/{case_id}/notes")
def list_notes(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    require_staff(acc)
    return [_note(n) for n in reports_svc.notes_visible(db, c, acc.role)]


@router.post("/cases/{case_id}/notes", status_code=201, summary="Human note, or a human review of a system finding")
def add_note(case_id: str, req: NoteIn, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    require_staff(acc)
    vis = req.visibility or ("CYBER_ONLY" if acc.role == "CYBER" else "BANK_AND_CYBER")
    if acc.role == "BANK":
        vis = "BANK_AND_CYBER"
    title = None
    if req.finding_code:
        f = db.scalar(select(Finding).where(Finding.case_id == c.id, Finding.code == req.finding_code))
        if f is None:
            raise HTTPException(404, "Finding not found")
        title = f.title
    n = InvestigatorNote(case_id=c.id, author=acc.name, author_id=acc.id, author_role=acc.role, body=req.body.strip(),
                         visibility=vis, finding_code=req.finding_code, finding_title=title,
                         assessment=req.assessment if req.finding_code else None)
    db.add(n)
    c.last_activity_at = datetime.now(timezone.utc)
    audit(db, "FINDING_REVIEWED" if req.finding_code else "NOTE_ADDED", acc.name, case_id=c.id,
          result=(f"{req.assessment or 'note'} on {req.finding_code}" if req.finding_code else f"visibility {vis}"), **_a(acc))
    db.commit()
    return _note(n)


# ------------------------------------------------------------------ reports

class ReportIn(BaseModel):
    audience: str | None = Field(None, pattern="^(VICTIM|BANK|CYBER|EXPORT)$")


ALLOWED_AUDIENCES = {"VICTIM": {"VICTIM"}, "BANK": {"BANK"}, "CYBER": {"CYBER", "EXPORT"}}


def _version_out(v: ReportVersion, audience: str, stale: bool = False) -> dict:
    return {"id": v.id, "audience": audience, "version": v.version, "kind": v.kind, "created_at": v.created_at,
            "sha256": v.sha256, "evidence_count": v.evidence_count, "case_status": v.case_status,
            "status_label": lifecycle.label(v.case_status or ""), "changes": v.changes, "is_current": not stale,
            "download_url": f"/api/v1/report-versions/{v.id}/download"}


@router.post("/cases/{case_id}/reports", status_code=201, summary="Generate a new report version from the current case")
def make_report(case_id: str, req: ReportIn | None = None, db: Session = Depends(get_db),
                acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    audience = (req.audience if req and req.audience else acc.role)
    if audience not in ALLOWED_AUDIENCES[acc.role]:
        raise HTTPException(403, "You cannot generate this report.")
    if not c.analysis:
        raise HTTPException(409, "The evidence has not been analysed yet. Upload evidence first.")
    busy = db.scalar(select(func.count()).select_from(EvidenceFile).where(
        EvidenceFile.case_id == c.id, EvidenceFile.status.in_(["RECEIVED", "PROCESSING"]))) or 0
    if busy:
        raise HTTPException(409, "Some evidence is still being processed. Try again in a moment.")
    v = reports_svc.generate(db, c, audience, acc)
    return _version_out(v, audience)


@router.get("/cases/{case_id}/reports", summary="Report versions visible to you")
def list_reports(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    n = db.scalar(select(func.count()).select_from(EvidenceFile).where(EvidenceFile.case_id == c.id)) or 0
    out = []
    for r in db.scalars(select(Report).where(Report.case_id == c.id, Report.audience.in_(ALLOWED_AUDIENCES[acc.role]))):
        vs = db.scalars(select(ReportVersion).where(ReportVersion.report_id == r.id).order_by(ReportVersion.version.desc())).all()
        for i, v in enumerate(vs):
            out.append(_version_out(v, r.audience, stale=i > 0 or reports_svc.is_stale(c, v, n)))
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


@router.get("/report-versions/{version_id}/download")
def download_report(version_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    v = db.get(ReportVersion, version_id)
    r = v and db.get(Report, v.report_id)
    if not v or not r:
        raise HTTPException(404, "Report not found")
    c = get_case(db, v.case_id, acc)
    if r.audience not in ALLOWED_AUDIENCES[acc.role]:
        raise HTTPException(404, "Report not found")
    audit(db, "REPORT_DOWNLOADED", acc.name, case_id=c.id, result=f"{r.audience} v{v.version}", **_a(acc))
    db.commit()
    media = "application/json" if v.kind == "JSON" else "application/pdf"
    return FileResponse(v.storage_path, media_type=media, filename=Path(v.storage_path).name, headers={"Cache-Control": "no-store"})


# ------------------------------------------------------------------ audit

AUDIT_LABEL = {
    "CASE_CREATED": "Case created", "EVIDENCE_UPLOADED": "Evidence uploaded", "EVIDENCE_PROCESSED": "System extracted information",
    "EVIDENCE_PROCESSING_FAILED": "Evidence could not be processed", "EVIDENCE_LINKED": "System linked related evidence",
    "ANALYSIS_COMPLETED": "Investigation analysis completed", "STATUS_CHANGED": "Case status changed",
    "INVESTIGATOR_OPENED_CASE": "Investigator opened case", "NOTE_ADDED": "Note added", "FINDING_REVIEWED": "Finding reviewed by investigator",
    "REPORT_GENERATED": "Report generated", "REPORT_DOWNLOADED": "Report downloaded", "EVIDENCE_VIEWED": "Original evidence viewed",
    "EVIDENCE_REQUESTED": "Additional evidence requested", "REQUEST_RESPONDED": "Request answered",
    "DISPOSITION_CHANGED": "Bank action recorded", "DUPLICATE_EVIDENCE_REJECTED": "Duplicate file rejected",
    "EVIDENCE_REJECTED": "File rejected", "RELATIONSHIP_REVIEWED": "Related case reviewed", "TRANSCRIPT_PROVIDED": "Transcript added by user",
    "DISPUTED_TRANSACTION_SELECTED": "Disputed transaction selected", "SYSTEM_RECORD_ATTACHED": "Platform record attached",
    "DEMO_CASE_LOADED": "Synthetic demo case loaded", "SYNTHETIC_CASE_SEEDED": "Synthetic background case created",
    "INTEGRITY_CHECK_FAILED": "Integrity check failed", "EXPORT_GENERATED": "Structured export generated",
}


@router.get("/cases/{case_id}/audit")
def case_audit(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    c = get_case(db, case_id, acc)
    require_staff(acc)
    codes = {e.id: e.code for e in db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == c.id))}
    return [{"at": a.created_at, "action": a.action, "label": AUDIT_LABEL.get(a.action, a.action.replace("_", " ").capitalize()),
             "actor": a.actor, "role": a.actor_role, "result": a.result, "source": a.source, "evidence": codes.get(a.evidence_id)}
            for a in db.scalars(select(AuditLog).where(AuditLog.case_id == c.id).order_by(AuditLog.created_at))]


@router.get("/cases/{case_id}/related", summary="Possible related cases (shared identifiers)")
def related(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(roles("BANK", "CYBER"))):
    c = get_case(db, case_id, acc)
    return {"related": crosscase.related_for(db, c, acc),
            "clusters": crosscase.clusters_for(db, acc, c.is_synthetic, c.id)}
