"""Evidence ingestion and per-file processing.

Upload  -> validate (extension + magic bytes + size) -> write-once storage + SHA-256 -> RECEIVED
Process -> detect type -> extract content (OCR / STT / document / structured) -> entities -> PROCESSED
Every step is persisted on the evidence row so the UI shows what actually happened.
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Case, EvidenceFile, ExtractedEntity, uid
from app.services.audio import stt
from app.services.audit import audit
from app.services.documents import extract as docx_
from app.services.extraction import claims as claims_
from app.services.extraction import entities as ents_
from app.services.extraction import structured as struct_
from app.services.ocr import engine as ocr

log = logging.getLogger("sentinel.ingest")

KINDS = {
    "png": "IMAGE", "jpg": "IMAGE", "jpeg": "IMAGE", "webp": "IMAGE",
    "mp3": "AUDIO", "wav": "AUDIO", "m4a": "AUDIO", "aac": "AUDIO", "ogg": "AUDIO",
    "pdf": "DOCUMENT", "docx": "DOCUMENT", "txt": "DOCUMENT",
    "csv": "STRUCTURED", "json": "STRUCTURED",
}
MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp", "mp3": "audio/mpeg",
        "wav": "audio/wav", "m4a": "audio/mp4", "aac": "audio/aac", "ogg": "audio/ogg", "pdf": "application/pdf",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "txt": "text/plain",
        "csv": "text/csv", "json": "application/json"}


class Rejected(Exception):
    pass


def _magic_ok(ext: str, d: bytes) -> bool:
    h = d[:16]
    return {
        "png": h.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": h.startswith(b"\xff\xd8\xff"), "jpeg": h.startswith(b"\xff\xd8\xff"),
        "webp": h[:4] == b"RIFF" and d[8:12] == b"WEBP",
        "pdf": h.startswith(b"%PDF-"),
        "docx": h.startswith(b"PK\x03\x04"),
        "wav": h[:4] == b"RIFF" and d[8:12] == b"WAVE",
        "mp3": h.startswith(b"ID3") or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0),
        "m4a": d[4:8] == b"ftyp",
        "aac": (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xF6) == 0xF0) or h.startswith(b"ADIF") or d[4:8] == b"ftyp",
        "ogg": h.startswith(b"OggS"),
    }.get(ext, b"\x00" not in d[:4096])  # txt / csv / json: must not be binary


def display_name(name: str) -> str:
    base = os.path.basename((name or "upload").replace("\\", "/")).replace("\x00", "")
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip(" ._") or "upload"
    return base[:120]


def validate(filename: str, data: bytes) -> str:
    s = get_settings()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in KINDS:
        raise Rejected(f"Unsupported file type '.{ext or '?'}'. Supported: images (PNG, JPG, WEBP), audio (MP3, WAV, M4A, AAC), "
                       "documents (PDF, DOCX, TXT), advanced (CSV, JSON).")
    if not data:
        raise Rejected("The file is empty.")
    limit = (s.max_audio_mb if KINDS[ext] == "AUDIO" else s.max_upload_mb) * 1024 * 1024
    if len(data) > limit:
        raise Rejected(f"File is larger than {limit // (1024 * 1024)} MB.")
    if not _magic_ok(ext, data):
        raise Rejected(f"The file content does not look like a .{ext} file.")
    return ext


def _next_seq(db: Session, case_id: str) -> int:
    return (db.scalar(select(func.max(EvidenceFile.seq)).where(EvidenceFile.case_id == case_id)) or 0) + 1


def _step(ev: EvidenceFile, name: str, status: str, detail: str | None = None) -> None:
    steps = [s for s in (ev.steps or []) if s["name"] != name]
    steps.append({"name": name, "status": status, "at": datetime.now(timezone.utc).isoformat(), "detail": detail})
    ev.steps = steps


def store(db: Session, case: Case, filename: str, data: bytes, *, channel: str | None = None, source: str = "upload",
          time_hint: datetime | None = None, note: str | None = None, actor: str = "user") -> EvidenceFile:
    s = get_settings()
    count = db.scalar(select(func.count()).select_from(EvidenceFile).where(EvidenceFile.case_id == case.id)) or 0
    if count >= s.max_files_per_case:
        raise Rejected(f"A case can hold at most {s.max_files_per_case} evidence items.")
    ext = validate(filename, data)
    kind = KINDS[ext]
    if ext == "txt" and channel == "message":
        kind = "MESSAGE"
    eid = uid()
    folder: Path = s.storage_dir / "cases" / case.id
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{eid}.{ext}"  # stored name never derives from user input
    with open(path, "xb") as fh:
        fh.write(data)
    os.chmod(path, 0o440)
    ev = EvidenceFile(id=eid, case_id=case.id, seq=_next_seq(db, case.id), kind=kind, original_name=display_name(filename),
                      storage_path=str(path), mime=MIME[ext], size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                      source=source, is_synthetic=case.is_synthetic, user_time_hint=time_hint, user_note=note,
                      status="RECEIVED", steps=[], subtype="CALL_RECORDING" if kind == "AUDIO" else None)
    _step(ev, "File received", "done", f"{len(data):,} bytes · SHA-256 {ev.sha256[:12]}…")
    _step(ev, "File type detected", "done", f"{kind.title()} (.{ext})")
    db.add(ev)
    db.flush()
    audit(db, "EVIDENCE_UPLOADED", actor, case_id=case.id, evidence_id=ev.id, source=source,
          result=f"{ev.code} {kind} {len(data)}B")
    return ev


# ---------------------------------------------------------------- processing

def _persist(db: Session, ev: EvidenceFile, ents: list[ents_.Ent]) -> None:
    db.execute(delete(ExtractedEntity).where(ExtractedEntity.evidence_id == ev.id))
    for e in ents:
        db.add(ExtractedEntity(case_id=ev.case_id, evidence_id=ev.id, type=e.type, value=e.value[:500],
                               normalized=(e.normalized or "")[:255] or None, confidence=e.confidence,
                               method=e.attrs.get("method", ev.method or "TEXT"), locator=e.locator,
                               context=(e.context or "")[:500] or None, occurred_at=e.occurred_at,
                               time_precision=e.time_precision, attrs={k: v for k, v in e.attrs.items() if k != "method"}))


def _subtype(kind: str, text: str, name: str) -> str:
    t, n = text.lower(), name.lower()
    if kind == "AUDIO":
        return "CALL_RECORDING"
    if re.search(r"\b(incoming|outgoing|missed)\b.*\bcall|call log|call history", t):
        return "CALL_LOG"
    is_bank_sms = bool(re.search(r"\b(a/?c|acct|account)\b", t) and re.search(r"\b(debited|credited|withdrawn)\b", t))
    is_chat = bool(re.search(r"whatsapp|telegram|\[\d{1,2}/\d{1,2}/\d{2,4},?\s*\d{1,2}:\d{2}|^\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}\s*-", t, re.M)) or "chat" in n
    is_statement = bool(re.search(r"opening balance|closing balance|statement of account|account statement", t))
    is_payment_ui = bool(re.search(r"payment successful|paid to|upi transaction id|transaction successful|money sent|sent to|paid successfully|upi ref", t))
    if is_statement:
        return "BANK_STATEMENT"
    if is_bank_sms:
        return "BANK_SMS" if kind in ("MESSAGE", "DOCUMENT") else "BANK_SMS_SCREENSHOT"
    if is_chat:
        return "CHAT" if kind != "IMAGE" else "CHAT_SCREENSHOT"
    if is_payment_ui:
        return "UPI_SCREENSHOT" if kind == "IMAGE" else "PAYMENT_RECEIPT"
    if re.search(r"\b(complaint|grievance|fir|cyber ?crime)\b", t):
        return "COMPLAINT"
    return {"IMAGE": "IMAGE_OTHER", "MESSAGE": "MESSAGE", "DOCUMENT": "DOCUMENT_OTHER"}.get(kind, "OTHER")


def _apply_time_hint(ev: EvidenceFile, ents: list[ents_.Ent]) -> None:
    """User-provided 'when did this happen' becomes a USER_HINT time, never EXACT."""
    if ev.user_time_hint and not any(e.time_precision == "EXACT" for e in ents):
        ents.append(ents_.Ent("DATETIME", "Time provided by the user at upload", ev.user_time_hint.isoformat(), 0.5,
                              "upload form", None, ev.user_time_hint, "USER_HINT", {"method": "USER_INPUT"}))


def process(db: Session, ev: EvidenceFile, actor: str = "system") -> None:
    ev.status, ev.error = "PROCESSING", None
    db.commit()
    data = Path(ev.storage_path).read_bytes() if ev.storage_path else b""
    ext = ev.storage_path.rsplit(".", 1)[-1].lower() if ev.storage_path else "json"
    ents: list[ents_.Ent] = []
    try:
        if ev.kind == "SYSTEM":
            return  # system records are created fully processed
        if ev.kind == "IMAGE":
            r = ocr.ocr_image(data)
            ev.method, ev.quality = "OCR", r.quality
            ev.text = r.text or None
            if not r.ok:
                ev.status, ev.error = ("UNAVAILABLE" if "not installed" in (r.error or "") else "FAILED"), r.error
                _step(ev, "Content extracted", "failed", r.error)
            else:
                _step(ev, "Content extracted", "done", f"OCR · {len(r.lines)} lines · mean word confidence {r.quality:.0%}")
                ents = ents_.extract(r.text, base_conf=min(1.0, r.quality + 0.1), method="OCR", line_conf=[l["conf"] for l in r.lines])
                ents += claims_.extract_claims([{"text": l["text"], "locator": f"line {i + 1}"} for i, l in enumerate(r.lines)], "MESSAGE", r.quality)
        elif ev.kind in ("MESSAGE", "DOCUMENT"):
            if ext == "pdf":
                r = docx_.extract_pdf(data)
            elif ext == "docx":
                r = docx_.extract_docx(data)
            else:
                t = docx_.decode_text(data)
                r = docx_.DocResult(ok=bool(t.strip()), text=t, method="TEXT", quality=1.0,
                                    error=None if t.strip() else "The text is empty.")
            ev.method, ev.text, ev.pages, ev.quality = r.method or None, r.text or None, r.pages, r.quality
            if not r.ok:
                ev.status, ev.error = "FAILED", r.error
                _step(ev, "Content extracted", "failed", r.error)
            else:
                pages = f" · {r.pages} page(s)" if r.pages else ""
                _step(ev, "Content extracted", "done", f"{r.method.replace('_', ' ').title()}{pages}")
                ents = ents_.extract(r.text, base_conf=r.quality or 1.0, method=r.method)
                ents += claims_.extract_claims([{"text": l, "locator": f"line {i + 1}"} for i, l in enumerate(r.text.splitlines())], "MESSAGE")
        elif ev.kind == "STRUCTURED":
            r = docx_.extract_structured(data, ext)
            ev.method, ev.text, ev.quality = r.method or None, r.text or None, r.quality
            if not r.ok:
                ev.status, ev.error = "FAILED", r.error
                _step(ev, "Content extracted", "failed", r.error)
            else:
                ents, st = struct_.extract_rows(r.rows)
                _step(ev, "Content extracted", "done",
                      f"{len(r.rows)} records · {st['transactions']} transactions · {st['events']} account events · {st['skipped']} unrecognised")
        elif ev.kind == "AUDIO":
            r = stt.transcribe(Path(ev.storage_path))
            ev.duration_s = r.duration_s
            if not r.ok:
                ev.method, ev.status, ev.error = "STT", "UNAVAILABLE" if "unavailable" in (r.error or "").lower() or "could not be loaded" in (r.error or "") or "not installed" in (r.error or "") or "disabled" in (r.error or "") else "FAILED", r.error
                _step(ev, "Content extracted", "failed", "Audio transcription unavailable. " + (r.error or ""))
            else:
                ev.method, ev.quality = r.engine, r.quality
                ev.segments = [{**s, "lang": r.language} for s in r.segments]
                if r.translated_segments:
                    ev.segments += [{**s, "lang": "en", "translation": True} for s in r.translated_segments]
                eng = r.translated_segments or r.segments
                ev.text = "\n".join(f"[{_mmss(s['start'])}] {s['text']}" for s in eng)
                _step(ev, "Content extracted", "done",
                      f"Transcript · {len(r.segments)} segments · language {r.language}" + (" · translated to English" if r.translated_segments else ""))
                ents = ents_.extract("\n".join(s["text"] for s in eng), base_conf=0.85, method="STT", locator_prefix="segment")
                for e in ents:  # locate entities by audio timestamp instead of line
                    if e.locator and e.locator.startswith("segment "):
                        idx = int(e.locator.split()[1]) - 1
                        if 0 <= idx < len(eng):
                            e.locator = _mmss(eng[idx]["start"])
                    e.attrs["label"] = "Statement extracted from audio"
                ents += claims_.extract_claims(eng, "AUDIO", 1.0)
        if ev.status == "PROCESSING":
            _apply_time_hint(ev, ents)
            ev.subtype = _subtype(ev.kind, ev.text or "", ev.original_name)
            if ev.kind == "STRUCTURED":
                n_t = sum(e.type == "HISTORY_TXN" for e in ents)
                n_e = sum(e.type == "ACCOUNT_EVENT" for e in ents)
                ev.subtype = "TXN_HISTORY" if n_t >= n_e else "ACCOUNT_LOG"
            _persist(db, ev, ents)
            core = [e for e in ents if e.type in ("AMOUNT", "UTR", "UPI_REF", "TXN_ID", "UPI_ID", "DATETIME", "HISTORY_TXN", "ACCOUNT_EVENT", "CLAIM", "PHONE")]
            _step(ev, "Entities identified", "done", f"{len(ents)} items ({', '.join(sorted({e.type for e in core})) or 'none of the core types'})")
            has_txn = any(e.type in ("AMOUNT", "UTR", "UPI_REF", "TXN_ID", "HISTORY_TXN") for e in ents)
            _step(ev, "Transaction information found", "done" if has_txn else "none",
                  None if has_txn else "No amount or reference found in this item")
            weak = ev.quality is not None and ev.quality < ocr.RELIABLE_QUALITY and ev.kind == "IMAGE"
            ev.status = "PARTIAL" if weak else "PROCESSED"
            if weak:
                ev.error = "Text was extracted with low confidence; verify values against the image."
        else:
            _persist(db, ev, [])
        ev.processed_at = datetime.now(timezone.utc)
        audit(db, "EVIDENCE_PROCESSED", actor, case_id=ev.case_id, evidence_id=ev.id,
              result=f"{ev.code} {ev.status} {ev.method or ''}".strip())
        db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.exception("Processing failed for evidence %s", ev.id)
        ev = db.get(EvidenceFile, ev.id)
        ev.status, ev.error = "FAILED", f"Processing error ({type(e).__name__})."
        _step(ev, "Content extracted", "failed", ev.error)
        audit(db, "EVIDENCE_PROCESSING_FAILED", actor, case_id=ev.case_id, evidence_id=ev.id, result=type(e).__name__)
        db.commit()


def set_provided_transcript(db: Session, ev: EvidenceFile, text: str, actor: str) -> None:
    """Attach a human-provided transcript to an audio item. Labelled; never presented as machine output."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    units = []
    for i, l in enumerate(lines):
        m = re.match(r"^\[?(\d{1,2}):(\d{2})\]?\s*(.*)$", l)
        start = int(m[1]) * 60 + int(m[2]) if m else None
        units.append({"text": m[3] if m else l, "start": start, "end": None})
    ev.segments = [{"start": u["start"], "end": None, "text": u["text"], "provided": True} for u in units]
    ev.text = "\n".join(lines)
    ev.method = "PROVIDED_TRANSCRIPT"
    ev.quality = None
    ents = ents_.extract("\n".join(u["text"] for u in units), base_conf=0.8, method="PROVIDED_TRANSCRIPT", locator_prefix="line")
    for e in ents:
        e.attrs["label"] = "Statement extracted from audio (transcript provided by user, not machine-generated)"
    ents += claims_.extract_claims(units, "AUDIO", 0.9)
    for e in ents:
        if e.type == "CLAIM":
            e.attrs["label"] = "Statement extracted from audio (transcript provided by user, not machine-generated)"
    _apply_time_hint(ev, ents)
    ev.subtype = "CALL_RECORDING"
    _persist(db, ev, ents)
    _step(ev, "Content extracted", "done", "Transcript provided by user (not machine-generated)")
    _step(ev, "Entities identified", "done", f"{len(ents)} items")
    ev.status, ev.error = "PROCESSED", None
    ev.processed_at = datetime.now(timezone.utc)
    audit(db, "TRANSCRIPT_PROVIDED", actor, case_id=ev.case_id, evidence_id=ev.id, result=ev.code)
    db.commit()


def _mmss(sec) -> str:
    if sec is None:
        return "--:--"
    return f"{int(sec // 60):02d}:{int(sec % 60):02d}"
