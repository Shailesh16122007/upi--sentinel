"""API contracts (request/response models)."""
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Channel = Literal["UPI", "AEPS"]
Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]


# ---------- System 1: risk check ----------

class TransactionCheckRequest(BaseModel):
    """What a PSP app / issuer bank sends before authorising a payment."""
    user_ref: str = Field(..., max_length=32, examples=["U-102"])
    beneficiary_vpa: str = Field(..., max_length=120, examples=["rahultraders@ybl"])
    beneficiary_name: str | None = Field(None, max_length=120)
    amount: float = Field(..., gt=0, le=10_000_000)
    channel: Channel = "UPI"
    device_ref: str = Field(..., max_length=64)
    ip: str | None = Field(None, max_length=64)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    note: str | None = Field(None, max_length=255)
    # Optional: lets the simulator replay a scenario at a fixed time. Defaults to now.
    timestamp: datetime | None = None

    @field_validator("beneficiary_vpa")
    @classmethod
    def _vpa(cls, v: str) -> str:
        v = v.strip().lower()
        if "@" not in v or len(v.split("@")[0]) == 0:
            raise ValueError("beneficiary_vpa must look like name@handle")
        return v


class SignalOut(BaseModel):
    type: str
    severity: Severity
    description: str
    weight: float
    evidence: dict = {}


class RiskCheckResponse(BaseModel):
    transaction_id: str
    transaction_ref: str
    risk_score: int
    risk_level: Severity
    decision: Literal["ALLOW", "VERIFY", "WARN", "BLOCK"]
    status: str
    can_override: bool
    signals: list[SignalOut]
    model_score: float
    rule_score: float
    network_score: float
    latency_ms: float


class DecisionRequest(BaseModel):
    action: Literal["CANCEL", "PROCEED"]


class TransactionOut(BaseModel):
    id: str
    ref: str
    created_at: datetime
    channel: str
    amount: float
    user_ref: str
    user_name: str
    beneficiary_vpa: str
    beneficiary_name: str
    device_ref: str | None
    status: str
    risk_score: int | None
    risk_level: str | None
    decision: str | None
    user_decision: str | None
    warning_shown_at: datetime | None
    user_decision_at: datetime | None
    model_score: float | None = None
    rule_score: float | None = None
    network_score: float | None = None
    latency_ms: float | None = None
    top_reason: str | None = None
    signals: list[SignalOut] = []


# ---------- Dispute investigation ----------

class CaseCreate(BaseModel):
    statement: str = Field(..., min_length=10, max_length=4000, description="What happened, in the customer's words")
    approx_date: date | None = None
    claimed_amount: float | None = Field(None, gt=0, le=100_000_000)


class CaseFromRiskTxn(BaseModel):
    statement: str = Field(..., min_length=10, max_length=4000)


class CaseUpdate(BaseModel):
    status: Literal["OPEN", "UNDER_REVIEW", "REPORT_READY", "CLOSED"] | None = None


class PastedMessage(BaseModel):
    text: str = Field(..., min_length=3, max_length=20_000)
    label: str | None = Field(None, max_length=80)
    occurred_at: datetime | None = Field(None, description="Optional: when the message was received")


class TranscriptIn(BaseModel):
    text: str = Field(..., min_length=3, max_length=50_000)


class NoteIn(BaseModel):
    body: str = Field(..., min_length=1, max_length=5000)
    author: str = Field("Investigator", max_length=80)


class EntityOut(BaseModel):
    id: str
    evidence_id: str
    type: str
    value: str
    normalized: str | None
    confidence: float
    method: str
    locator: str | None
    context: str | None
    occurred_at: datetime | None
    time_precision: str
    attrs: dict


class EvidenceOut(BaseModel):
    id: str
    code: str
    kind: str
    subtype: str | None
    original_name: str
    mime: str | None
    size_bytes: int | None
    sha256: str | None
    source: str
    is_synthetic: bool
    status: str
    method: str | None
    text: str | None
    pages: int | None
    duration_s: float | None
    segments: list | None
    quality: float | None
    steps: list
    error: str | None
    user_time_hint: datetime | None
    user_note: str | None
    uploaded_at: datetime
    processed_at: datetime | None
    entities: list[EntityOut] = []


class CaseSummaryOut(BaseModel):
    id: str
    ref: str
    status: str
    statement: str
    approx_date: date | None
    claimed_amount: float | None
    claim_type: str | None
    is_synthetic: bool
    created_at: datetime
    analyzed_at: datetime | None
    evidence_count: int
    processing: int
    disputed_amount: float | None = None
    counts: dict | None = None
    completeness: int | None = None


class CaseOut(CaseSummaryOut):
    analysis: dict | None
    disputed: dict | None
    transactions: list[dict]
    linked_risk_txn_id: str | None
