from sqlalchemy.orm import Session

from app.models import AuditLog


def audit(db: Session, action: str, actor: str, *, case_id: str | None = None, transaction_id: str | None = None,
          evidence_id: str | None = None, source: str = "api", result: str = "OK") -> None:
    """Append-only audit record. Never pass secrets, OTPs or raw evidence text here."""
    db.add(AuditLog(action=action, actor=actor, case_id=case_id, transaction_id=transaction_id,
                    evidence_id=evidence_id, source=source, result=result[:255]))
