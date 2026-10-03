"""SQLAlchemy models. Portable across SQLite (local quick-start) and PostgreSQL (recommended).

Two domains:
  * Dispute investigation (primary product): cases, evidence_files, extracted_entities,
    case_transactions, timeline_events, findings, evidence_relationships, investigator_notes,
    reports, audit_logs.
  * Real-time risk API (secondary module): users, devices, beneficiaries, account_links,
    transactions, risk_signals.

UUIDs are 36-char strings so one schema works on both engines. Timestamps are timezone-aware UTC.
"""
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db import Base


class UTCDateTime(TypeDecorator):
    """Stores every timestamp as UTC and always returns timezone-aware values (SQLite drops offsets otherwise)."""
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        value = value.astimezone(timezone.utc)
        return value.replace(tzinfo=None) if dialect.name == "sqlite" else value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def uid() -> str:
    return str(uuid.uuid4())


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# =====================================================================================
# Dispute investigation
# =====================================================================================

class Case(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)  # UPI-2026-001
    statement: Mapped[str] = mapped_column(Text)
    approx_date: Mapped[date | None] = mapped_column(Date)
    claimed_amount: Mapped[float | None] = mapped_column(Float)
    # OPEN -> UNDER_REVIEW -> REPORT_READY -> CLOSED
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    claim_type: Mapped[str | None] = mapped_column(String(24))  # derived from statement wording
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    linked_risk_txn_id: Mapped[str | None] = mapped_column(String(36))
    analysis: Mapped[dict | None] = mapped_column(JSON)  # counts, completeness, ML, summary
    analyzed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, onupdate=utcnow)

    evidence: Mapped[list["EvidenceFile"]] = relationship(back_populates="case", cascade="all, delete-orphan",
                                                          order_by="EvidenceFile.seq")


class EvidenceFile(Base):
    __tablename__ = "evidence_files"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer)  # E1, E2 ... within a case
    kind: Mapped[str] = mapped_column(String(16))  # IMAGE | MESSAGE | AUDIO | DOCUMENT | STRUCTURED | SYSTEM
    subtype: Mapped[str | None] = mapped_column(String(32))  # UPI_SCREENSHOT, BANK_SMS, CALL_RECORDING ...
    original_name: Mapped[str] = mapped_column(String(255))
    storage_path: Mapped[str | None] = mapped_column(String(512))
    mime: Mapped[str | None] = mapped_column(String(80))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    source: Mapped[str] = mapped_column(String(16), default="upload")  # upload | paste | demo | system
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    user_time_hint: Mapped[datetime | None] = mapped_column(UTCDateTime())  # "when did this happen?"
    user_note: Mapped[str | None] = mapped_column(String(500))
    # RECEIVED | PROCESSING | PROCESSED | PARTIAL | UNAVAILABLE | FAILED
    status: Mapped[str] = mapped_column(String(16), default="RECEIVED", index=True)
    method: Mapped[str | None] = mapped_column(String(32))  # OCR, TEXT, PDF_TEXT, PDF_OCR, DOCX, STT ...
    text: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[float | None] = mapped_column(Float)
    segments: Mapped[list | None] = mapped_column(JSON)  # audio: [{start, end, text}]
    quality: Mapped[float | None] = mapped_column(Float)  # OCR mean word confidence / STT avg logprob mapped 0..1
    steps: Mapped[list] = mapped_column(JSON, default=list)  # [{name, status, at, detail}]
    error: Mapped[str | None] = mapped_column(String(500))
    uploaded_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    case: Mapped[Case] = relationship(back_populates="evidence")
    entities: Mapped[list["ExtractedEntity"]] = relationship(back_populates="evidence", cascade="all, delete-orphan")

    @property
    def code(self) -> str:
        return f"E{self.seq}"


class ExtractedEntity(Base):
    __tablename__ = "extracted_entities"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_files.id"), index=True)
    type: Mapped[str] = mapped_column(String(24), index=True)
    value: Mapped[str] = mapped_column(String(500))
    normalized: Mapped[str | None] = mapped_column(String(255), index=True)
    confidence: Mapped[float] = mapped_column(Float)
    method: Mapped[str] = mapped_column(String(32))  # how it was obtained (OCR, regex on SMS text, STT ...)
    locator: Mapped[str | None] = mapped_column(String(64))  # "line 3", "page 2", "02:14"
    context: Mapped[str | None] = mapped_column(String(500))
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    # EXACT (date+time in evidence) | DATE_ONLY | TIME_ONLY | USER_HINT | NONE
    time_precision: Mapped[str] = mapped_column(String(12), default="NONE")
    attrs: Mapped[dict] = mapped_column(JSON, default=dict)

    evidence: Mapped[EvidenceFile] = relationship(back_populates="entities")


class CaseTransaction(Base):
    """A normalized transaction assembled from one or more evidence sources (or a history row)."""
    __tablename__ = "case_transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    kind: Mapped[str] = mapped_column(String(12), index=True)  # DISPUTED | RELATED | HISTORICAL
    amount: Mapped[float | None] = mapped_column(Float)
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    time_precision: Mapped[str] = mapped_column(String(12), default="NONE")
    reference: Mapped[str | None] = mapped_column(String(64), index=True)
    beneficiary: Mapped[str | None] = mapped_column(String(160))
    beneficiary_vpa: Mapped[str | None] = mapped_column(String(160))
    status: Mapped[str | None] = mapped_column(String(24))
    channel: Mapped[str | None] = mapped_column(String(16))
    device: Mapped[str | None] = mapped_column(String(80))
    fields: Mapped[dict] = mapped_column(JSON, default=dict)  # field -> [{value, evidence_id, entity_id}]
    sources: Mapped[list] = mapped_column(JSON, default=list)  # evidence ids
    match_basis: Mapped[str | None] = mapped_column(String(300))
    match_confidence: Mapped[float | None] = mapped_column(Float)


class TimelineEvent(Base):
    __tablename__ = "timeline_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    occurred_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    approximate: Mapped[bool] = mapped_column(Boolean, default=False)
    time_label: Mapped[str] = mapped_column(String(120))
    event_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list] = mapped_column(JSON, default=list)
    entity_ids: Mapped[list] = mapped_column(JSON, default=list)
    # DOCUMENTED (record states it) | STATEMENT (a person's claim) | SYSTEM (platform action)
    reliability: Mapped[str] = mapped_column(String(16))


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    seq: Mapped[int] = mapped_column(Integer, default=0)
    category: Mapped[str] = mapped_column(String(16), index=True)  # SUPPORTING|CONTRADICTORY|CONTEXTUAL|MISSING
    code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(200))
    detail: Mapped[str | None] = mapped_column(Text)
    is_anomaly: Mapped[bool] = mapped_column(Boolean, default=False)
    is_conflict: Mapped[bool] = mapped_column(Boolean, default=False)
    sources: Mapped[list] = mapped_column(JSON, default=list)  # [{evidence_id, entity_id?, label}]
    data: Mapped[dict] = mapped_column(JSON, default=dict)


class EvidenceRelationship(Base):
    __tablename__ = "evidence_relationships"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    from_kind: Mapped[str] = mapped_column(String(16))  # evidence | transaction | entity
    from_id: Mapped[str] = mapped_column(String(36))
    to_kind: Mapped[str] = mapped_column(String(16))
    to_id: Mapped[str] = mapped_column(String(36))
    relation: Mapped[str] = mapped_column(String(32))  # EVIDENCES | SAME_TRANSACTION | MENTIONS | CONFLICTS_WITH
    confidence: Mapped[float] = mapped_column(Float)
    basis: Mapped[str] = mapped_column(String(300))


class InvestigatorNote(Base):
    __tablename__ = "investigator_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    author: Mapped[str] = mapped_column(String(80))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Report(Base):
    __tablename__ = "reports"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.id"), index=True)
    storage_path: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(40), index=True)
    case_id: Mapped[str | None] = mapped_column(String(36), index=True)
    transaction_id: Mapped[str | None] = mapped_column(String(36), index=True)
    evidence_id: Mapped[str | None] = mapped_column(String(36))
    source: Mapped[str] = mapped_column(String(40), default="api")
    result: Mapped[str] = mapped_column(String(255), default="OK")


# =====================================================================================
# Real-time risk API (secondary module)
# =====================================================================================

class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(20))
    vpa: Mapped[str | None] = mapped_column(String(120))
    home_lat: Mapped[float | None] = mapped_column(Float)
    home_lon: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ref: Mapped[str] = mapped_column(String(64), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    first_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_seen: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Beneficiary(Base):
    __tablename__ = "beneficiaries"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    vpa: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    bank: Mapped[str | None] = mapped_column(String(80))
    kind: Mapped[str] = mapped_column(String(16), default="UPI")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    flagged_fraud: Mapped[bool] = mapped_column(Boolean, default=False)
    flag_reason: Mapped[str | None] = mapped_column(String(255))


class AccountLink(Base):
    __tablename__ = "account_links"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    src_vpa: Mapped[str] = mapped_column(String(120), index=True)
    dst_vpa: Mapped[str] = mapped_column(String(120), index=True)
    relation: Mapped[str] = mapped_column(String(32), default="SENT_TO")
    observed_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    ref: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    beneficiary_id: Mapped[str] = mapped_column(ForeignKey("beneficiaries.id"), index=True)
    channel: Mapped[str] = mapped_column(String(8), default="UPI")
    amount: Mapped[float] = mapped_column(Float)
    device_ref: Mapped[str | None] = mapped_column(String(64))
    ip: Mapped[str | None] = mapped_column(String(64))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    note: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    risk_score: Mapped[int | None] = mapped_column(Integer, index=True)
    risk_level: Mapped[str | None] = mapped_column(String(12))
    decision: Mapped[str | None] = mapped_column(String(12))
    model_score: Mapped[float | None] = mapped_column(Float)
    rule_score: Mapped[float | None] = mapped_column(Float)
    network_score: Mapped[float | None] = mapped_column(Float)
    latency_ms: Mapped[float | None] = mapped_column(Float)
    is_historical: Mapped[bool] = mapped_column(Boolean, default=False)
    warning_shown_at: Mapped[datetime | None] = mapped_column(UTCDateTime())
    user_decision: Mapped[str | None] = mapped_column(String(32))
    user_decision_at: Mapped[datetime | None] = mapped_column(UTCDateTime())

    user: Mapped[User] = relationship()
    beneficiary: Mapped[Beneficiary] = relationship()
    signals: Mapped[list["RiskSignal"]] = relationship(back_populates="transaction", cascade="all, delete-orphan")


class RiskSignal(Base):
    __tablename__ = "risk_signals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    description: Mapped[str] = mapped_column(String(255))
    weight: Mapped[float] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    transaction: Mapped[Transaction] = relationship(back_populates="signals")
