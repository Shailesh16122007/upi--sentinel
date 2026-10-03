"""Dashboards, related cases, mule clusters, network graph and the structured export.
Every number returned here is counted from case records at request time."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api import serial
from app.api.cases import get_case
from app.api.deps import current_account, roles
from app.db import get_db
from app.models import (Account, AuditLog, Case, CaseRelationship, CaseTransaction, EvidenceRequest, MuleCluster, Report,
                        ReportVersion)
from app.services import crosscase, lifecycle
from app.services import reports as reports_svc
from app.services.audit import audit
from app.services.permissions import require_view, visible_cases

router = APIRouter(prefix="/api/v1", tags=["Intelligence"])


@router.get("/dashboard", summary="Counts for the signed-in person's dashboard (from the database, never estimated)")
def dashboard(synthetic: bool | None = None, db: Session = Depends(get_db), acc: Account = Depends(current_account)):
    q = visible_cases(acc, select(Case))
    if synthetic is not None:
        q = q.where(Case.is_synthetic.is_(synthetic))
    cases = db.scalars(q).all()
    st = [c.status for c in cases]

    def n(*s):
        return sum(1 for x in st if x in s)
    if acc.role == "VICTIM":
        return {"open": n(*[s for s in lifecycle.STATES if s not in ("RESOLVED", "CLOSED")]), "draft": n("DRAFT"),
                "under_review": n("SUBMITTED", "BANK_REVIEW", "ESCALATED", "CYBER_REVIEW", "INFO_REQUESTED", "UNDER_INVESTIGATION", "PENDING"),
                "action_required": n("EVIDENCE_REQUESTED") + n("DRAFT"), "resolved": n("RESOLVED", "CLOSED"), "total": len(cases)}
    ids = [c.id for c in cases]
    rel = {r.case_id for r in db.scalars(select(CaseRelationship).where(CaseRelationship.case_id.in_(ids or [""]),
                                                                       CaseRelationship.status != "DISMISSED"))}
    open_req = db.scalars(select(EvidenceRequest).where(EvidenceRequest.case_id.in_(ids or [""]), EvidenceRequest.status == "OPEN")).all()
    amounts = {t.case_id: t.amount for t in db.scalars(select(CaseTransaction).where(CaseTransaction.case_id.in_(ids or [""]),
                                                                                  CaseTransaction.kind == "DISPUTED")) if t.amount}
    clusters = crosscase.clusters_for(db, acc, synthetic)
    base = {"total": len(cases), "with_related_cases": len(rel), "clusters": len(clusters),
            "open_amount": round(sum(amounts.get(c.id, 0) for c in cases if c.status not in ("RESOLVED", "CLOSED")), 2),
            "amount_known_cases": sum(1 for c in cases if c.id in amounts and c.status not in ("RESOLVED", "CLOSED"))}
    if acc.role == "BANK":
        return {**base, "new": n("SUBMITTED"), "under_review": n("BANK_REVIEW"),
                "awaiting_action": n("EVIDENCE_REQUESTED", "INFO_REQUESTED"),
                "awaiting_customer": n("EVIDENCE_REQUESTED"), "info_requested_by_cyber": n("INFO_REQUESTED"),
                "escalated": sum(1 for c in cases if c.escalated_at), "resolved": n("RESOLVED", "CLOSED"),
                "open_requests": sum(1 for r in open_req if r.target_role == "VICTIM")}
    high_value = sum(1 for c in cases if (amounts.get(c.id) or 0) >= 100000 and c.status not in ("RESOLVED", "CLOSED"))
    return {**base, "received": len(cases), "pending_review": n("ESCALATED"),
            "under_investigation": n("CYBER_REVIEW", "UNDER_INVESTIGATION", "INFO_REQUESTED"), "pending": n("PENDING"),
            "resolved": n("RESOLVED", "CLOSED"), "returned_to_bank": sum(1 for c in cases if c.authority_status == "RETURNED"),
            "high_value": high_value}


class RelReview(BaseModel):
    status: str = Field(..., pattern="^(POSSIBLE|LINKED|DISMISSED)$")
    note: str | None = Field(None, max_length=1000)


@router.post("/relationships/{rel_id}", summary="Confirm (link) or dismiss a possible related case")
def review_relationship(rel_id: str, req: RelReview, db: Session = Depends(get_db), acc: Account = Depends(roles("CYBER", "BANK"))):
    r = db.get(CaseRelationship, rel_id)
    if not r:
        raise HTTPException(404, "Not found")
    c = db.get(Case, r.case_id)
    require_view(acc, c)
    if acc.role == "BANK" and req.status == "LINKED":
        raise HTTPException(403, "Linking related cases is done by cyber crime.")
    now = datetime.now(timezone.utc)
    for x in db.scalars(select(CaseRelationship).where(  # both directions
            ((CaseRelationship.case_id == r.case_id) & (CaseRelationship.related_case_id == r.related_case_id)) |
            ((CaseRelationship.case_id == r.related_case_id) & (CaseRelationship.related_case_id == r.case_id)),
            CaseRelationship.entity_type == r.entity_type, CaseRelationship.value == r.value)):
        x.status, x.reviewed_by, x.reviewed_at = req.status, acc.id, now
    oc = db.get(Case, r.related_case_id)
    audit(db, "RELATIONSHIP_REVIEWED", acc.name, case_id=c.id,
          result=f"{req.status} with {oc.ref if oc else '?'} on {r.value}" + (f" — {req.note}" if req.note else ""),
          actor_id=acc.id, actor_role=acc.role)
    db.commit()
    return {"id": r.id, "status": req.status}


@router.get("/network/clusters", summary="Related transaction clusters (shared beneficiary / contact identifiers)")
def clusters(synthetic: bool = False, db: Session = Depends(get_db), acc: Account = Depends(roles("BANK", "CYBER"))):
    return crosscase.clusters_for(db, acc, synthetic)


@router.get("/network/clusters/{cluster_id}")
def cluster(cluster_id: str, db: Session = Depends(get_db), acc: Account = Depends(roles("BANK", "CYBER"))):
    cl = db.get(MuleCluster, cluster_id)
    if not cl:
        raise HTTPException(404, "Cluster not found")
    out = [x for x in crosscase.clusters_for(db, acc, cl.is_synthetic) if x["id"] == cluster_id]
    if not out:
        raise HTTPException(404, "Cluster not found")
    return out[0]


@router.get("/network/graph", summary="Mule network graph built from case records")
def network(synthetic: bool = False, cluster_id: str | None = None, db: Session = Depends(get_db),
            acc: Account = Depends(roles("BANK", "CYBER"))):
    return crosscase.network_graph(db, acc, synthetic, cluster_id)


@router.get("/related-cases", summary="All visible cases that have possible related cases")
def related_overview(synthetic: bool = False, db: Session = Depends(get_db), acc: Account = Depends(roles("BANK", "CYBER"))):
    out = []
    for c in db.scalars(visible_cases(acc, select(Case)).where(Case.is_synthetic.is_(synthetic)).order_by(Case.created_at.desc())):
        rel = crosscase.related_for(db, c, acc)
        if rel:
            out.append({**serial.summary(db, c, acc), "related": rel})
    return out


@router.get("/cases/{case_id}/export", summary="Structured cyber-crime export (JSON, current state, not saved)")
def export_preview(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(roles("CYBER"))):
    c = get_case(db, case_id, acc)
    return reports_svc.structured_export(reports_svc.assemble(db, c, "EXPORT"))


@router.get("/cases/{case_id}/export/download", summary="Download the structured export as a JSON file")
def export_download(case_id: str, db: Session = Depends(get_db), acc: Account = Depends(roles("CYBER"))):
    c = get_case(db, case_id, acc)
    data = reports_svc.structured_export(reports_svc.assemble(db, c, "EXPORT"))
    audit(db, "EXPORT_GENERATED", acc.name, case_id=c.id, result="structured JSON downloaded", actor_id=acc.id, actor_role=acc.role)
    db.commit()
    return JSONResponse(json.loads(json.dumps(data, default=str)), headers={
        "Content-Disposition": f'attachment; filename="{c.ref}_structured_export.json"', "Cache-Control": "no-store"})


@router.get("/reports", summary="Reports across all cases you can see")
def all_reports(db: Session = Depends(get_db), acc: Account = Depends(roles("BANK", "CYBER"))):
    from app.api.cases import ALLOWED_AUDIENCES, _version_out
    ids = {c.id: c for c in db.scalars(visible_cases(acc, select(Case)))}
    out = []
    for r in db.scalars(select(Report).where(Report.case_id.in_(list(ids) or [""]), Report.audience.in_(ALLOWED_AUDIENCES[acc.role]))):
        v = db.scalar(select(ReportVersion).where(ReportVersion.report_id == r.id).order_by(ReportVersion.version.desc()))
        if v:
            c = ids[r.case_id]
            out.append({**_version_out(v, r.audience), "case_id": c.id, "case_ref": c.ref, "case_status": lifecycle.label(c.status)})
    return sorted(out, key=lambda x: x["created_at"], reverse=True)


@router.get("/audit/cases", summary="Recent audit events across cases you can see")
def audit_all(limit: int = 200, db: Session = Depends(get_db), acc: Account = Depends(roles("BANK", "CYBER"))):
    from app.api.cases import AUDIT_LABEL
    ids = {c.id: c.ref for c in db.scalars(visible_cases(acc, select(Case)))}
    rows = db.scalars(select(AuditLog).where(AuditLog.case_id.in_(list(ids) or [""])).order_by(AuditLog.created_at.desc())
                      .limit(min(limit, 1000))).all()
    return [{"at": a.created_at, "case_id": a.case_id, "case_ref": ids.get(a.case_id), "action": a.action,
             "label": AUDIT_LABEL.get(a.action, a.action.replace("_", " ").capitalize()), "actor": a.actor, "role": a.actor_role,
             "result": a.result} for a in rows]
