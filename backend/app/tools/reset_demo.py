"""Development-only: remove ALL synthetic demonstration cases and re-create the synthetic background cases.

    python -m app.tools.reset_demo            (asks for confirmation)
    python -m app.tools.reset_demo --yes

Real (non-synthetic) cases are never touched. There is deliberately no web endpoint for this.
"""
import shutil
import sys

from sqlalchemy import delete, select

from app.config import get_settings
from app.db import SessionLocal, engine
from app.migrate import upgrade
from app.models import (AuditLog, Case, CaseAction, CaseAssignment, CaseRelationship, CaseTransaction, EntityRelationship,
                        EvidenceFile, EvidenceHash, EvidenceRelationship, EvidenceRequest, ExtractedEntity, Finding,
                        Investigation, InvestigatorNote, MuleCluster, Notification, Report, ReportVersion, TimelineEvent)
from app.services.accounts import ensure_accounts
from app.services.demo_case import seed_background


def reset() -> int:
    s = get_settings()
    if s.env not in ("dev", "demo"):
        raise SystemExit("Refusing to reset: SENTINEL_ENV is not dev/demo.")
    upgrade(engine)
    with SessionLocal() as db:
        ensure_accounts(db)
        ids = list(db.scalars(select(Case.id).where(Case.is_synthetic.is_(True))))
        if ids:
            ev_ids = list(db.scalars(select(EvidenceFile.id).where(EvidenceFile.case_id.in_(ids))))
            db.execute(delete(EvidenceHash).where(EvidenceHash.evidence_id.in_(ev_ids or [""])))
            db.execute(delete(ReportVersion).where(ReportVersion.case_id.in_(ids)))
            for m in (ExtractedEntity, CaseTransaction, TimelineEvent, Finding, EvidenceRelationship, InvestigatorNote, Report,
                      CaseAction, EvidenceRequest, Notification, CaseAssignment, Investigation, EntityRelationship, AuditLog):
                db.execute(delete(m).where(m.case_id.in_(ids)))
            db.execute(delete(CaseRelationship).where(CaseRelationship.case_id.in_(ids) | CaseRelationship.related_case_id.in_(ids)))
            db.execute(delete(EvidenceFile).where(EvidenceFile.case_id.in_(ids)))
            db.execute(delete(Case).where(Case.id.in_(ids)))
        db.execute(delete(MuleCluster).where(MuleCluster.is_synthetic.is_(True)))
        db.commit()
        for cid in ids:
            for sub in ("cases", "reports"):
                shutil.rmtree(s.storage_dir / sub / cid, ignore_errors=True)
        seed_background(db)
    return len(ids)


if __name__ == "__main__":
    if "--yes" not in sys.argv and input("Delete all synthetic demo cases? Type 'yes': ").strip() != "yes":
        raise SystemExit("Cancelled.")
    print(f"Removed {reset()} synthetic case(s); synthetic background cases re-created.")
