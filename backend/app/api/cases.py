"""Dispute investigation API."""
from __future__ import annotations

import hashlib
import threading
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import require_api_key
from app.config import get_settings
from app.db import SessionLocal, get_db
from app.models import (AuditLog, Case, CaseTransaction, EvidenceFile, ExtractedEntity, Finding, InvestigatorNote,
                        Report, TimelineEvent, Transaction)
from app.schemas import (CaseCreate, CaseFromRiskTxn, CaseOut, CaseSummaryOut, CaseUpdate, EntityOut, EvidenceOut,
                         NoteIn, PastedMessage, TranscriptIn)
from app.services import cases as cases_svc
from app.services import ingest
from app.services.analysis.run import analyze as run_analysis
from app.services.audit import audit
from app.services.graph import evidence_graph
from app.services.reporting import pdf

router = APIRouter(prefix="/api/v1", tags=["Dispute investigation"])
_case_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(case_id: str) -> threading.Lock:
    with _locks_guard:
        return _case_locks.setdefault(case_id, threading.Lock())


def get_case(db: Session, case_id: str) -> Case:
    c = db.get(Case, case_id) or db.scalar(select(Case).where(Case.ref == case_id))
    if c is None:
        raise HTTPException(404, "Case not found")
    return c


# ------------------------------------------------------------------ serialisers

def _ent(x: ExtractedEntity) -> EntityOut:
    return EntityOut(id=x.id, evidence_id=x.evidence_id, type=x.type, value=x.value, normalized=x.normalized,
                     confidence=x.confidence, method=x.method, locator=x.locator, context=x.context,
                     occurred_at=x.occurred_at, time_precision=x.time_precision, attrs=x.attrs or {})


def _ev(e: EvidenceFile, with_entities: bool = True) -> EvidenceOut:
    return EvidenceOut(id=e.id, code=e.code, kind=e.kind, subtype=e.subtype, original_name=e.original_name, mime=e.mime,
                       size_bytes=e.size_bytes, sha256=e.sha256, source=e.source, is_synthetic=e.is_synthetic, status=e.status,
                       method=e.method, text=e.text, pages=e.pages, duration_s=e.duration_s, segments=e.segments,
                       quality=e.quality, steps=e.steps or [], error=e.error, user_time_hint=e.user_time_hint,
                       user_note=e.user_note, uploaded_at=e.uploaded_at, processed_at=e.processed_at,
                       entities=[_ent(x) for x in sorted(e.entities, key=lambda x: (x.locator or "", x.type))] if with_entities else [])


def _txn(t: CaseTransaction) -> dict:
    return {"id": t.id, "kind": t.kind, "amount": t.amount, "occurred_at": t.occurred_at, "time_precision": t.time_precision,
            "reference": t.reference, "beneficiary": t.beneficiary, "beneficiary_vpa": t.beneficiary_vpa, "status": t.status,
            "channel": t.channel, "device": t.device, "fields": t.fields, "sources": t.sources, "match_basis": t.match_basis,
            "match_confidence": t.match_confidence}


def _summary(db: Session, c: Case) -> CaseSummaryOut:
    n = db.scalar(select(func.count()).select_from(EvidenceFile).where(EvidenceFile.case_id == c.id)) or 0
    busy = db.scalar(select(func.count()).select_from(EvidenceFile).where(
        EvidenceFile.case_id == c.id, EvidenceFile.status.in_(["RECEIVED", "PROCESSING"]))) or 0
    d = db.scalar(select(CaseTransaction).where(CaseTransaction.case_id == c.id, CaseTransaction.kind == "DISPUTED"))
    a = c.analysis or {}
    return CaseSummaryOut(id=c.id, ref=c.ref, status=c.status, statement=c.statement, approx_date=c.approx_date,
                          claimed_amount=c.claimed_amount, claim_type=c.claim_type, is_synthetic=c.is_synthetic,
                          created_at=c.created_at, analyzed_at=c.analyzed_at, evidence_count=n, processing=busy,
                          disputed_amount=d.amount if d else None, counts=a.get("counts"),
                          completeness=(a.get("completeness") or {}).get("score"))


def _full(db: Session, c: Case) -> CaseOut:
    s = _summary(db, c)
    txns = db.scalars(select(CaseTransaction).where(CaseTransaction.case_id == c.id, CaseTransaction.kind != "HISTORICAL")).all()
    d = next((t for t in txns if t.kind == "DISPUTED"), None)
    return CaseOut(**s.model_dump(), analysis=c.analysis, disputed=_txn(d) if d else None,
                   transactions=[_txn(t) for t in txns], linked_risk_txn_id=c.linked_risk_txn_id)


# ------------------------------------------------------------------ cases

@router.post("/cases", response_model=CaseOut, status_code=201, summary="Create a dispute (statement first, evidence later)")
def create_case(req: CaseCreate, db: Session = Depends(get_db), actor: str = Depends(require_api_key)):
    return _full(db, cases_svc.create(db, req.statement, req.approx_date, req.claimed_amount, actor))


@router.post("/cases/from-risk-transaction/{txn_id}", response_model=CaseOut, status_code=201,
             summary="Open a dispute for a payment previously checked by the real-time risk API")
def create_from_risk(txn_id: str, req: CaseFromRiskTxn, bg: BackgroundTasks, db: Session = Depends(get_db),
                     actor: str = Depends(require_api_key)):
    t = db.get(Transaction, txn_id) or db.scalar(select(Transaction).where(Transaction.ref == txn_id))
    if t is None:
        raise HTTPException(404, "Transaction not found")
    if t.status != "COMPLETED":
        raise HTTPException(409, f"Only completed payments can be disputed (this one is {t.status}).")
    c = cases_svc.create_from_risk_transaction(db, t, req.statement, actor)
    run_analysis(db, c, actor)
    return _full(db, c)


@router.get("/cases", response_model=list[CaseSummaryOut])
def list_cases(synthetic: bool | None = None, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    q = select(Case).order_by(Case.created_at.desc())
    if synthetic is not None:
        q = q.where(Case.is_synthetic.is_(synthetic))
    return [_summary(db, c) for c in db.scalars(q)]


@router.get("/cases/{case_id}", response_model=CaseOut)
def read_case(case_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    return _full(db, get_case(db, case_id))


@router.patch("/cases/{case_id}", response_model=CaseOut)
def update_case(case_id: str, req: CaseUpdate, db: Session = Depends(get_db), actor: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    if req.status:
        old, c.status = c.status, req.status
        audit(db, "STATUS_CHANGED", actor, case_id=c.id, result=f"{old} -> {req.status}")
    db.commit()
    return _full(db, c)


@router.post("/cases/{case_id}/opened", status_code=204, summary="Record that an investigator opened the case")
def opened(case_id: str, db: Session = Depends(get_db), actor: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    audit(db, "INVESTIGATOR_OPENED_CASE", actor, case_id=c.id)
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
                run_analysis(db, c, "system")


@router.post("/cases/{case_id}/evidence", response_model=list[EvidenceOut], status_code=202,
             summary="Upload one or more evidence files. Processing runs in the background; poll GET /evidence.")
async def upload(case_id: str, bg: BackgroundTasks, files: list[UploadFile] = File(...),
                 channel: str | None = Form(None), occurred_at: datetime | None = Form(None),
                 note: str | None = Form(None, max_length=500), db: Session = Depends(get_db),
                 actor: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    s = get_settings()
    stored, errors = [], []
    for f in files[:20]:
        data = await f.read(max(s.max_upload_mb, s.max_audio_mb) * 1024 * 1024 + 1)
        try:
            stored.append(ingest.store(db, c, f.filename or "upload", data, channel=channel, time_hint=_tz(occurred_at),
                                       note=note, actor=actor))
        except ingest.Rejected as e:
            errors.append(f"{ingest.display_name(f.filename or 'upload')}: {e}")
            audit(db, "EVIDENCE_REJECTED", actor, case_id=c.id, result=str(e)[:200])
    db.commit()
    if not stored:
        raise HTTPException(422, "; ".join(errors) or "No files received")
    bg.add_task(_process_then_analyze, c.id, [e.id for e in stored], actor)
    out = [_ev(e, False) for e in stored]
    if errors:  # partial success: surface rejections without failing the accepted files
        for o in out:
            o.user_note = (o.user_note or "") + (" | Rejected in same upload: " + "; ".join(errors))[:300]
    return out


@router.post("/cases/{case_id}/evidence/text", response_model=EvidenceOut, status_code=202,
             summary="Paste a message (SMS, chat) directly")
def paste(case_id: str, req: PastedMessage, bg: BackgroundTasks, db: Session = Depends(get_db),
          actor: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    name = (req.label or "pasted_message").strip().replace(" ", "_")[:60] + ".txt"
    try:
        ev = ingest.store(db, c, name, req.text.encode("utf-8"), channel="message", source="paste",
                          time_hint=_tz(req.occurred_at), actor=actor)
    except ingest.Rejected as e:
        raise HTTPException(422, str(e))
    db.commit()
    bg.add_task(_process_then_analyze, c.id, [ev.id], actor)
    return _ev(ev, False)


def _tz(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    from app.services.extraction.entities import IST
    return d if d.tzinfo else d.replace(tzinfo=IST)


@router.get("/cases/{case_id}/evidence", response_model=list[EvidenceOut])
def list_evidence(case_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    return [_ev(e) for e in db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == c.id).order_by(EvidenceFile.seq))]


@router.get("/cases/{case_id}/evidence/{evidence_id}/file", summary="Original file (integrity-checked)")
def evidence_file(case_id: str, evidence_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    e = db.get(EvidenceFile, evidence_id)
    if not e or e.case_id != c.id or not e.storage_path:
        raise HTTPException(404, "Evidence not found")
    p = Path(e.storage_path)
    if hashlib.sha256(p.read_bytes()).hexdigest() != e.sha256:
        raise HTTPException(409, "Integrity check failed: stored file does not match its recorded SHA-256")
    return FileResponse(p, media_type=e.mime or "application/octet-stream", filename=e.original_name,
                        content_disposition_type="inline", headers={"Cache-Control": "no-store"})


@router.post("/cases/{case_id}/evidence/{evidence_id}/transcript", response_model=EvidenceOut,
             summary="Attach a human-provided transcript to an audio item (labelled as not machine-generated)")
def provide_transcript(case_id: str, evidence_id: str, req: TranscriptIn, db: Session = Depends(get_db),
                       actor: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    e = db.get(EvidenceFile, evidence_id)
    if not e or e.case_id != c.id or e.kind != "AUDIO":
        raise HTTPException(404, "Audio evidence not found")
    if e.status == "PROCESSED" and e.method and e.method.startswith("faster-whisper"):
        raise HTTPException(409, "This recording already has a machine transcript.")
    ingest.set_provided_transcript(db, e, req.text, actor)
    with _lock(c.id):
        run_analysis(db, c, actor)
    db.refresh(e)
    return _ev(e)


@router.post("/cases/{case_id}/process", status_code=202, summary="(Re)process evidence that is pending, failed or unavailable")
def process(case_id: str, bg: BackgroundTasks, all: bool = Query(False), db: Session = Depends(get_db),
            actor: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    q = select(EvidenceFile).where(EvidenceFile.case_id == c.id, EvidenceFile.kind != "SYSTEM")
    if not all:
        q = q.where(EvidenceFile.status.in_(["RECEIVED", "FAILED", "UNAVAILABLE"]))
    evs = db.scalars(q).all()
    for e in evs:
        e.status = "RECEIVED"
    db.commit()
    bg.add_task(_process_then_analyze, c.id, [e.id for e in evs], actor)
    return {"queued": [e.code for e in evs]}


# ------------------------------------------------------------------ analysis outputs

@router.post("/cases/{case_id}/analyze", response_model=CaseOut)
def analyze(case_id: str, db: Session = Depends(get_db), actor: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    busy = db.scalar(select(func.count()).select_from(EvidenceFile).where(
        EvidenceFile.case_id == c.id, EvidenceFile.status.in_(["RECEIVED", "PROCESSING"]))) or 0
    if busy:
        raise HTTPException(409, f"{busy} evidence item(s) are still being processed.")
    with _lock(c.id):
        run_analysis(db, c, actor)
    return _full(db, c)


@router.get("/cases/{case_id}/timeline")
def timeline(case_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    codes = {e.id: e.code for e in db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == c.id))}
    return [{"id": t.id, "occurred_at": t.occurred_at, "approximate": t.approximate, "time_label": t.time_label,
             "event_type": t.event_type, "description": t.description, "reliability": t.reliability,
             "entity_ids": t.entity_ids, "sources": [{"evidence_id": i, "label": codes.get(i)} for i in t.evidence_ids]}
            for t in db.scalars(select(TimelineEvent).where(TimelineEvent.case_id == c.id).order_by(TimelineEvent.seq))]


@router.get("/cases/{case_id}/findings")
def findings(case_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    return [{"id": f.id, "category": f.category, "code": f.code, "title": f.title, "detail": f.detail,
             "is_anomaly": f.is_anomaly, "is_conflict": f.is_conflict, "sources": f.sources, "data": f.data}
            for f in db.scalars(select(Finding).where(Finding.case_id == c.id).order_by(Finding.seq))]


@router.get("/cases/{case_id}/graph")
def graph(case_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    return evidence_graph.build(db, get_case(db, case_id))


@router.get("/cases/{case_id}/history")
def history(case_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    rows = db.scalars(select(CaseTransaction).where(CaseTransaction.case_id == c.id, CaseTransaction.kind == "HISTORICAL")
                      .order_by(CaseTransaction.occurred_at)).all()
    return [{"occurred_at": t.occurred_at, "amount": t.amount, "beneficiary": t.beneficiary_vpa or t.beneficiary} for t in rows]


# ------------------------------------------------------------------ notes, report, audit

@router.get("/cases/{case_id}/notes")
def list_notes(case_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    return [{"id": n.id, "author": n.author, "body": n.body, "created_at": n.created_at}
            for n in db.scalars(select(InvestigatorNote).where(InvestigatorNote.case_id == c.id).order_by(InvestigatorNote.created_at))]


@router.post("/cases/{case_id}/notes", status_code=201)
def add_note(case_id: str, req: NoteIn, db: Session = Depends(get_db), actor: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    n = InvestigatorNote(case_id=c.id, author=req.author.strip() or "Investigator", body=req.body.strip())
    db.add(n)
    audit(db, "NOTE_ADDED", actor, case_id=c.id, result=f"by {n.author}")
    db.commit()
    return {"id": n.id, "author": n.author, "body": n.body, "created_at": n.created_at}


@router.post("/cases/{case_id}/report", status_code=201)
def make_report(case_id: str, db: Session = Depends(get_db), actor: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    if not c.analysis:
        raise HTTPException(409, "Run the analysis before generating a report.")
    evs = db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == c.id).order_by(EvidenceFile.seq)).all()
    codes = {e.id: e.code for e in evs}
    key_types = ("AMOUNT", "DATETIME", "UTR", "UPI_REF", "TXN_ID", "UPI_ID", "PAYEE", "PHONE", "URL")
    ev_rows = []
    for e in evs:
        items = []
        for x in e.entities:
            if x.type in key_types and len(items) < 6:
                items.append(f"{x.type.replace('_', ' ').title()}: {x.value}")
        claims = [x for x in e.entities if x.type == "CLAIM"]
        if claims:
            items.append(f"{len(claims)} statement(s) extracted" + (" from audio" if e.kind == "AUDIO" else ""))
        hist = sum(1 for x in e.entities if x.type == "HISTORY_TXN")
        evts = sum(1 for x in e.entities if x.type == "ACCOUNT_EVENT")
        if hist or evts:
            items.append(f"{hist} history rows, {evts} account events")
        ev_rows.append({"code": e.code, "original_name": e.original_name, "kind": e.kind, "subtype": e.subtype,
                        "uploaded_at": e.uploaded_at, "sha256": e.sha256, "method": e.method, "status": e.status,
                        "error": e.error, "is_synthetic": e.is_synthetic, "key_items": "; ".join(items)})
    d = db.scalar(select(CaseTransaction).where(CaseTransaction.case_id == c.id, CaseTransaction.kind == "DISPUTED"))
    data = {
        "case": {"ref": c.ref, "status": c.status, "created_at": c.created_at, "claim_type": c.claim_type, "statement": c.statement,
                 "approx_date": c.approx_date, "claimed_amount": c.claimed_amount, "is_synthetic": c.is_synthetic},
        "analysis": c.analysis, "disputed": _txn(d) if d else None, "codes": codes, "evidence": ev_rows,
        "timeline": timeline(c.id, db, "internal"), "findings": findings(c.id, db, "internal"),
        "notes": list_notes(c.id, db, "internal"),
        "audit": [{"created_at": a.created_at, "action": a.action, "actor": a.actor, "result": a.result}
                  for a in db.scalars(select(AuditLog).where(AuditLog.case_id == c.id).order_by(AuditLog.created_at))],
    }
    folder = get_settings().storage_dir / "reports" / c.id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{c.ref}_report_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}.pdf"
    pdf.build(path, data)
    r = Report(case_id=c.id, storage_path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
    db.add(r)
    if c.status in ("OPEN", "UNDER_REVIEW"):
        c.status = "REPORT_READY"
    audit(db, "REPORT_GENERATED", actor, case_id=c.id, result=f"sha256={r.sha256[:12]}")
    db.commit()
    return {"id": r.id, "created_at": r.created_at, "sha256": r.sha256, "download_url": f"/api/v1/reports/{r.id}/download"}


@router.get("/cases/{case_id}/reports")
def list_reports(case_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    return [{"id": r.id, "created_at": r.created_at, "sha256": r.sha256, "download_url": f"/api/v1/reports/{r.id}/download"}
            for r in db.scalars(select(Report).where(Report.case_id == c.id).order_by(Report.created_at.desc()))]


@router.get("/reports/{report_id}/download")
def download_report(report_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    r = db.get(Report, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    return FileResponse(r.storage_path, media_type="application/pdf", filename=Path(r.storage_path).name,
                        headers={"Cache-Control": "no-store"})


@router.get("/cases/{case_id}/audit")
def case_audit(case_id: str, db: Session = Depends(get_db), _: str = Depends(require_api_key)):
    c = get_case(db, case_id)
    codes = {e.id: e.code for e in db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == c.id))}
    return [{"at": a.created_at, "action": a.action, "actor": a.actor, "result": a.result, "source": a.source,
             "evidence": codes.get(a.evidence_id)}
            for a in db.scalars(select(AuditLog).where(AuditLog.case_id == c.id).order_by(AuditLog.created_at))]
