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
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models import Case, EvidenceFile, ExtractedEntity, uid
from app.services import integrity
from app.services.audio import stt
from app.services.audit import audit
from app.services.documents import extract as docx_
from app.services.extraction import claims as claims_
from app.services.extraction import entities as ents_
from app.services.extraction import language as lang_
from app.services.extraction import structured as struct_
from app.services.ocr import engine as ocr

log = logging.getLogger("sentinel.ingest")

KINDS = {
    "png": "IMAGE", "jpg": "IMAGE", "jpeg": "IMAGE", "jfif": "IMAGE", "webp": "IMAGE", "gif": "IMAGE", "bmp": "IMAGE",
    "tif": "IMAGE", "tiff": "IMAGE", "heic": "IMAGE", "heif": "IMAGE",
    "mp3": "AUDIO", "wav": "AUDIO", "m4a": "AUDIO", "aac": "AUDIO", "ogg": "AUDIO", "opus": "AUDIO", "amr": "AUDIO",
    "mp4": "VIDEO", "mov": "VIDEO", "webm": "VIDEO", "3gp": "VIDEO",
    "pdf": "DOCUMENT", "docx": "DOCUMENT", "txt": "DOCUMENT", "eml": "DOCUMENT",
    "csv": "STRUCTURED", "json": "STRUCTURED",
}
MIME = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "jfif": "image/jpeg", "heic": "image/heic", "heif": "image/heif", "webp": "image/webp", "gif": "image/gif",
        "bmp": "image/bmp", "tif": "image/tiff", "tiff": "image/tiff", "mp3": "audio/mpeg",
        "wav": "audio/wav", "m4a": "audio/mp4", "aac": "audio/aac", "ogg": "audio/ogg", "opus": "audio/ogg",
        "amr": "audio/amr", "mp4": "video/mp4", "mov": "video/quicktime", "webm": "video/webm", "3gp": "video/3gpp",
        "pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain", "eml": "message/rfc822", "csv": "text/csv", "json": "application/json"}

# Plain-language outcomes shown to everyone; technical detail stays in the processing steps and server log.
FRIENDLY = {
    "IMAGE": "We could not read this image. Please try uploading a clearer image.",
    "AUDIO": "We could not transcribe this recording. You can still keep the recording as evidence.",
    "VIDEO": "We could not read this recording automatically. The original file has been preserved.",
    "DOCUMENT": "This document could not be read automatically. The original document has been preserved.",
    "MESSAGE": "This message could not be read.",
    "STRUCTURED": "This file could not be read automatically. The original file has been preserved.",
}


# When a capability is missing on the server, the problem is the setup — not the person's file.
SETUP = {
    "IMAGE": "Text reading (OCR) is not set up on this computer yet. Your image is saved and will be read automatically "
             "once it is installed — use “Try reading again”.",
    "AUDIO": "Speech-to-text is not set up on this computer yet. Your recording is saved and can be read once it is "
             "installed — or type what was said.",
    "VIDEO": "Speech-to-text is not set up on this computer yet. Your recording is saved.",
}


class Rejected(Exception):
    pass


class Duplicate(Rejected):
    def __init__(self, existing: EvidenceFile):
        super().__init__(f"This file appears to have already been uploaded ({existing.code} · {existing.original_name}).")
        self.existing = existing


def _magic_ok(ext: str, d: bytes) -> bool:
    h = d[:16]
    return {
        "png": h.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": h.startswith(b"\xff\xd8\xff"), "jpeg": h.startswith(b"\xff\xd8\xff"), "jfif": h.startswith(b"\xff\xd8\xff"),
        "heic": d[4:8] == b"ftyp", "heif": d[4:8] == b"ftyp",
        "webp": h[:4] == b"RIFF" and d[8:12] == b"WEBP",
        "pdf": h.startswith(b"%PDF-"),
        "docx": h.startswith(b"PK\x03\x04"),
        "wav": h[:4] == b"RIFF" and d[8:12] == b"WAVE",
        "mp3": h.startswith(b"ID3") or (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xE0) == 0xE0),
        "m4a": d[4:8] == b"ftyp",
        "aac": (len(h) > 1 and h[0] == 0xFF and (h[1] & 0xF6) == 0xF0) or h.startswith(b"ADIF") or d[4:8] == b"ftyp",
        "ogg": h.startswith(b"OggS"), "opus": h.startswith(b"OggS"),
        "amr": h.startswith(b"#!AMR"),
        "gif": h.startswith(b"GIF8"), "bmp": h.startswith(b"BM"),
        "tif": h[:4] in (b"II*\x00", b"MM\x00*"), "tiff": h[:4] in (b"II*\x00", b"MM\x00*"),
        "mp4": d[4:8] == b"ftyp", "mov": d[4:8] in (b"ftyp", b"moov", b"wide", b"mdat", b"free"),
        "3gp": d[4:8] == b"ftyp", "webm": h.startswith(b"\x1a\x45\xdf\xa3"),
    }.get(ext, b"\x00" not in d[:4096])  # txt / csv / json / eml: must not be binary


def display_name(name: str) -> str:
    base = os.path.basename((name or "upload").replace("\\", "/")).replace("\x00", "")
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip(" ._") or "upload"
    return base[:120]


def validate(filename: str, data: bytes) -> str:
    s = get_settings()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in KINDS:
        raise Rejected(f"We can't read '.{ext or '?'}' files yet. You can upload screenshots/photos (PNG, JPG, WEBP, GIF, HEIC), "
                       "audio (MP3, WAV, M4A, AAC, OGG, OPUS), screen recordings (MP4, MOV, WEBM), documents (PDF, DOCX, TXT, "
                       "EML email), or bank exports (CSV, JSON).")
    if not data:
        raise Rejected("The file is empty.")
    limit = (s.max_audio_mb if KINDS[ext] in ("AUDIO", "VIDEO") else s.max_upload_mb) * 1024 * 1024
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
          time_hint: datetime | None = None, note: str | None = None, actor: str = "user",
          uploaded_by_id: str | None = None, uploaded_by_role: str | None = None) -> EvidenceFile:
    s = get_settings()
    count = db.scalar(select(func.count()).select_from(EvidenceFile).where(EvidenceFile.case_id == case.id)) or 0
    if count >= s.max_files_per_case:
        raise Rejected(f"A case can hold at most {s.max_files_per_case} evidence items.")
    ext = validate(filename, data)
    kind = KINDS[ext]
    digest = hashlib.sha256(data).hexdigest()
    dup = db.scalar(select(EvidenceFile).where(EvidenceFile.case_id == case.id, EvidenceFile.sha256 == digest))
    if dup is not None:
        audit(db, "DUPLICATE_EVIDENCE_REJECTED", actor, case_id=case.id, evidence_id=dup.id, source=source,
              result=f"same SHA-256 as {dup.code}", actor_id=uploaded_by_id, actor_role=uploaded_by_role)
        raise Duplicate(dup)
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
                      storage_path=str(path), mime=MIME[ext], size_bytes=len(data), sha256=digest,
                      source=source, is_synthetic=case.is_synthetic, user_time_hint=time_hint, user_note=note,
                      status="RECEIVED", steps=[], subtype={"AUDIO": "CALL_RECORDING", "VIDEO": "SCREEN_RECORDING"}.get(kind),
                      uploaded_by_id=uploaded_by_id, uploaded_by_role=uploaded_by_role, uploaded_at=datetime.now(timezone.utc))
    _step(ev, "File received", "done", f"{len(data):,} bytes · SHA-256 {ev.sha256[:12]}…")
    _step(ev, "File type detected", "done", f"{kind.title()} (.{ext})")
    db.add(ev)
    db.flush()
    integrity.record_hash(db, ev)
    audit(db, "EVIDENCE_UPLOADED", actor, case_id=case.id, evidence_id=ev.id, source=source,
          result=f"{ev.code} {kind} {len(data)}B", actor_id=uploaded_by_id, actor_role=uploaded_by_role)
    return ev


@contextmanager
def working_copy(ev: EvidenceFile):
    """Processing never touches the original: OCR / transcription / parsing read a disposable copy."""
    work = get_settings().storage_dir / "work"
    work.mkdir(parents=True, exist_ok=True)
    ext = ev.storage_path.rsplit(".", 1)[-1]
    dst = work / f"{ev.id}-{uid()[:8]}.{ext}"
    shutil.copyfile(ev.storage_path, dst)
    try:
        yield dst
    finally:
        dst.unlink(missing_ok=True)


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
    if kind == "VIDEO":
        return "SCREEN_RECORDING"
    if re.search(r"\b(incoming|outgoing|missed)\b.*\bcall|call log|call history", t):
        return "CALL_LOG"
    is_bank_sms = bool(re.search(r"\b(a/?c|acct|account)\b|खात", t) and re.search(r"\b(debited|credited|withdrawn)\b|डेबिट|जमा|क्रेडिट", t))
    time_lines = len(re.findall(r"^\s*\d{1,2}[:.]\d{2}\s*(?:[ap]\.?\s?m\.?)?\s*[✓✔]{0,2}\s*$", t, re.M))
    is_chat = bool(re.search(r"whatsapp|telegram|\[\d{1,2}/\d{1,2}/\d{2,4},?\s*\d{1,2}:\d{2}|^\d{1,2}/\d{1,2}/\d{2,4},\s*\d{1,2}:\d{2}\s*-", t, re.M)) \
        or "chat" in n or time_lines >= 3
    is_statement = bool(re.search(r"opening balance|closing balance|statement of account|account statement", t))
    is_payment_ui = bool(re.search(r"payment successful|paid to|upi transaction id|transaction successful|money sent|sent to|paid successfully|upi ref", t))
    if is_statement:
        return "BANK_STATEMENT"
    if t.startswith("from:") and "\nsubject:" in t and not is_bank_sms:
        return "EMAIL"
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
    if ev.kind == "SYSTEM":
        return  # system records are created fully processed
    ev.status, ev.error = "PROCESSING", None
    db.commit()
    if integrity.verify(db, ev) != "MATCH":
        ev.status, ev.error = "FAILED", "The stored original failed its integrity check and was not processed."
        _step(ev, "Content extracted", "failed", ev.error)
        audit(db, "INTEGRITY_CHECK_FAILED", actor, case_id=ev.case_id, evidence_id=ev.id, result=ev.code)
        db.commit()
        return
    try:
        with working_copy(ev) as copy:
            _process(db, ev, copy, actor)
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.exception("Processing failed for evidence %s", ev.id)
        ev = db.get(EvidenceFile, ev.id)
        ev.status, ev.error = "FAILED", FRIENDLY.get(ev.kind, "Something went wrong while processing this file.")
        _step(ev, "Content extracted", "failed", f"Processing error ({type(e).__name__}). The original file is preserved.")
        audit(db, "EVIDENCE_PROCESSING_FAILED", actor, case_id=ev.case_id, evidence_id=ev.id, result=type(e).__name__)
        db.commit()


def _fail(ev: EvidenceFile, technical: str | None, status: str = "FAILED") -> None:
    msg = SETUP.get(ev.kind) if status == "UNAVAILABLE" else None
    ev.status, ev.error = status, msg or FRIENDLY.get(ev.kind, "This file could not be read automatically.")
    _step(ev, "Content extracted", "failed", technical or ev.error)


def _process(db: Session, ev: EvidenceFile, copy: Path, actor: str) -> None:
    data = copy.read_bytes()
    ext = copy.suffix.lstrip(".").lower()
    ents: list[ents_.Ent] = []
    if ev.kind == "IMAGE":
        ev.integrity = integrity.check_image(data)
        r = ocr.ocr_image(data)
        ev.method, ev.quality = "OCR", r.quality
        ev.text = r.text or None
        if not r.ok:
            _fail(ev, r.error, "UNAVAILABLE" if "not installed" in (r.error or "") else "FAILED")
        else:
            _step(ev, "Content extracted", "done", f"OCR · {len(r.lines)} lines · mean word confidence {r.quality:.0%}")
            ents = ents_.extract(r.text, base_conf=min(1.0, r.quality + 0.1), method="OCR", line_conf=[l["conf"] for l in r.lines])
            ents += claims_.extract_claims([{"text": l["text"], "locator": f"line {i + 1}"} for i, l in enumerate(r.lines)], "MESSAGE", r.quality)
    elif ev.kind in ("MESSAGE", "DOCUMENT"):
        if ext == "pdf":
            r = docx_.extract_pdf(data)
        elif ext == "docx":
            r = docx_.extract_docx(data)
        elif ext == "eml":
            r = docx_.extract_email(data)
        else:
            t = docx_.decode_text(data)
            r = docx_.DocResult(ok=bool(t.strip()), text=t, method="TEXT", quality=1.0,
                                error=None if t.strip() else "The text is empty.")
        ev.method, ev.text, ev.pages, ev.quality = r.method or None, r.text or None, r.pages, r.quality
        if not r.ok:
            _fail(ev, r.error)
        else:
            pages = f" · {r.pages} page(s)" if r.pages else ""
            _step(ev, "Content extracted", "done", f"{r.method.replace('_', ' ').title()}{pages}")
            ents = ents_.extract(r.text, base_conf=r.quality or 1.0, method=r.method)
            ents += claims_.extract_claims([{"text": l, "locator": f"line {i + 1}"} for i, l in enumerate(r.text.splitlines())], "MESSAGE")
    elif ev.kind == "STRUCTURED":
        r = docx_.extract_structured(data, ext)
        ev.method, ev.text, ev.quality = r.method or None, r.text or None, r.quality
        if not r.ok:
            _fail(ev, r.error)
        else:
            ents, st = struct_.extract_rows(r.rows)
            _step(ev, "Content extracted", "done",
                  f"{len(r.rows)} records · {st['transactions']} transactions · {st['events']} account events · {st['skipped']} unrecognised")
    elif ev.kind in ("AUDIO", "VIDEO"):
        frame_text = ""
        if ev.kind == "VIDEO":
            frame_text = _video_frames_text(copy)
        r = stt.transcribe(copy)
        ev.duration_s = r.duration_s
        unavailable = any(k in (r.error or "").lower() for k in ("unavailable", "could not be loaded", "not installed", "disabled"))
        if not r.ok and ev.kind == "VIDEO" and frame_text:
            ev.method, ev.quality, ev.text = "VIDEO_OCR", None, frame_text
            _step(ev, "Content extracted", "done", "Text read from sampled video frames; speech not transcribed ("
                  + (r.error or "no speech") + ")")
            ents = ents_.extract(frame_text, base_conf=0.75, method="OCR")
            ents += claims_.extract_claims([{"text": l, "locator": f"line {i + 1}"} for i, l in enumerate(frame_text.splitlines())], "MESSAGE")
        elif not r.ok:
            ev.method = "STT"
            _fail(ev, ("Audio transcription unavailable. " if unavailable else "") + (r.error or ""),
                  "UNAVAILABLE" if unavailable else "FAILED")
        else:
            ev.method, ev.quality = r.engine, r.quality
            ev.segments = [{**s, "lang": r.language} for s in r.segments]
            if r.translated_segments:
                ev.segments += [{**s, "lang": "en", "translation": True} for s in r.translated_segments]
            eng = r.translated_segments or r.segments
            ev.text = "\n".join(f"[{_mmss(s['start'])}] {s['text']}" for s in r.segments)
            if r.translated_segments:
                ev.text += "\n\n[English translation — Whisper]\n" + "\n".join(
                    f"[{_mmss(s['start'])}] {s['text']}" for s in r.translated_segments)
            if frame_text:
                ev.text += "\n\n[Text read from video frames]\n" + frame_text
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
            if r.translated_segments:  # statements in the original language (Hinglish etc.) as well
                seen = {(e.locator, e.normalized) for e in ents if e.type == "CLAIM"}
                ents += [c for c in claims_.extract_claims(r.segments, "AUDIO", 0.9) if (c.locator, c.normalized) not in seen]
            if frame_text:
                ents += ents_.extract(frame_text, base_conf=0.7, method="OCR", locator_prefix="frame line")
    if ev.status == "PROCESSING":
        ev.language = _language(ev, r if ev.kind in ("AUDIO", "VIDEO") else None)
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
            ev.error = "Some text was hard to read. Please check the values against the image."
    else:
        _persist(db, ev, [])
    ev.processed_at = datetime.now(timezone.utc)
    audit(db, "EVIDENCE_PROCESSED", actor, case_id=ev.case_id, evidence_id=ev.id,
          result=f"{ev.code} {ev.status} {ev.method or ''}".strip())
    db.commit()


def _language(ev: EvidenceFile, r) -> dict | None:
    if r is not None and getattr(r, "language", None):
        primary = (r.segments and " ".join(s["text"] for s in r.segments)) or ""
        d = lang_.detect(primary)
        d["speech_language"] = r.language
        if d["label"] in ("English", "Unknown (Latin script)", "Not enough text") and r.language != "en":
            d["label"] = f"Speech detected as '{r.language}'"
        return d
    return lang_.detect(ev.text or "") if ev.text else None


def _video_frames_text(path: Path, max_frames: int = 8) -> str:
    """OCR a handful of evenly spaced frames from a screen recording. Best effort; empty on failure."""
    try:
        import io as _io

        import av
        out, seen = [], set()
        with av.open(str(path)) as c:
            vs = next((s for s in c.streams if s.type == "video"), None)
            if vs is None:
                return ""
            dur = float(c.duration or 0) / 1_000_000 or 10.0
            for i in range(max_frames):
                c.seek(int((i + 0.5) * dur / max_frames * 1_000_000), any_frame=False)
                frame = next(c.decode(video=0), None)
                if frame is None:
                    continue
                buf = _io.BytesIO()
                frame.to_image().save(buf, "PNG")
                r = ocr.ocr_image(buf.getvalue())
                for line in (r.text.splitlines() if r.ok else []):
                    if line.strip() and line not in seen:
                        seen.add(line)
                        out.append(line)
        return "\n".join(out)
    except Exception:  # noqa: BLE001
        log.info("Video frame OCR skipped for %s", path.name)
        return ""


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
