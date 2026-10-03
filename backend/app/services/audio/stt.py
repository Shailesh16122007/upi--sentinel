"""Local speech-to-text with faster-whisper.

* Runs on the server — raw audio never leaves the machine.
* The model is downloaded once (first use) into storage/models, then works offline.
* If the engine or model is unavailable, callers get a clear "unavailable" result and the rest of
  the pipeline continues. Nothing is guessed.
* Non-English calls (e.g. Hindi) are transcribed in the original language and additionally
  translated to English by Whisper, so entity extraction works; both are kept.
"""
from __future__ import annotations

import logging
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from app.config import get_settings

log = logging.getLogger("sentinel.stt")
_model = None
_model_err: str | None = None
_failed_at: float | None = None
RETRY_AFTER_S = 300
_lock = threading.Lock()


@dataclass
class SttResult:
    ok: bool
    segments: list[dict] = field(default_factory=list)  # [{start, end, text}]
    text: str = ""
    language: str | None = None
    translated_segments: list[dict] | None = None
    duration_s: float | None = None
    quality: float | None = None
    error: str | None = None
    engine: str = ""


def _load():
    global _model, _model_err, _failed_at
    s = get_settings()
    if s.stt_engine.lower() in ("none", "off", "disabled"):
        _model_err = "Speech-to-text is disabled on this server (SENTINEL_STT_ENGINE=none)."
        return None
    with _lock:
        if _model is not None:
            return _model
        if _failed_at and time.monotonic() - _failed_at < RETRY_AFTER_S:
            return None  # don't hammer the network on every upload after a failed download
        try:
            from faster_whisper import WhisperModel
        except ImportError:
            _model_err = "Speech-to-text engine (faster-whisper) is not installed."
            return None
        try:
            root = s.storage_dir / "models"
            root.mkdir(parents=True, exist_ok=True)
            _model = WhisperModel(s.whisper_model, device=s.whisper_device, compute_type=s.whisper_compute_type,
                                  download_root=str(root))
            _model_err, _failed_at = None, None
        except Exception as e:  # noqa: BLE001 — typically: model not downloaded and no network
            _model_err = (f"Speech-to-text model '{s.whisper_model}' could not be loaded "
                          f"({type(e).__name__}). Run `python -m app.tools.fetch_models` with internet access once.")
            _failed_at = time.monotonic()
            log.warning("STT model load failed: %s", type(e).__name__)
        return _model


def status() -> dict:
    m = _model if _model is not None else None
    return {"engine": f"faster-whisper:{get_settings().whisper_model}", "loaded": m is not None, "error": _model_err}


def duration_of(path: Path) -> float | None:
    try:
        import av
        with av.open(str(path)) as c:
            if c.duration:
                return round(c.duration / 1_000_000, 2)
    except Exception:  # noqa: BLE001
        return None
    return None


def transcribe(path: Path) -> SttResult:
    model = _load()
    dur = duration_of(path)
    if model is None:
        return SttResult(ok=False, error=_model_err or "Audio transcription unavailable.", duration_s=dur)
    try:
        segs, info = model.transcribe(str(path), vad_filter=True, beam_size=5)
        segs = list(segs)
    except Exception as e:  # noqa: BLE001
        return SttResult(ok=False, error=f"Audio could not be decoded or transcribed ({type(e).__name__}).",
                         duration_s=dur)
    out = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs if s.text.strip()]
    if not out:
        return SttResult(ok=False, error="No speech was detected in this recording.", duration_s=dur or info.duration,
                         language=info.language, engine=f"faster-whisper:{get_settings().whisper_model}")
    lp = [s.avg_logprob for s in segs if s.text.strip()]
    quality = round(math.exp(sum(lp) / len(lp)), 3) if lp else None
    translated = None
    if info.language and info.language != "en":
        try:
            tsegs, _ = model.transcribe(str(path), task="translate", vad_filter=True, beam_size=5)
            translated = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                          for s in tsegs if s.text.strip()]
        except Exception:  # noqa: BLE001
            translated = None
    return SttResult(ok=True, segments=out, text=" ".join(s["text"] for s in out), language=info.language,
                     translated_segments=translated, duration_s=round(info.duration, 2), quality=quality,
                     engine=f"faster-whisper:{get_settings().whisper_model}")
