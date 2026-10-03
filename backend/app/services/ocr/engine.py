"""OCR for screenshots/photos (Tesseract via pytesseract).

Phone screenshots are often dark-mode, small text, or have coloured backgrounds, so each image is
normalised (grayscale, upscale, dark-mode inversion, contrast) before OCR. Word-level confidences are
kept so downstream entities carry an honest confidence.
"""
from __future__ import annotations

import io
import shutil
from dataclasses import dataclass, field

from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings

RELIABLE_QUALITY = 0.55   # below this the text is shown but entities are marked low-confidence
MIN_QUALITY = 0.30        # below this we report the OCR as failed


@dataclass
class OcrResult:
    ok: bool
    text: str = ""
    lines: list[dict] = field(default_factory=list)  # [{text, conf}]
    quality: float = 0.0
    error: str | None = None
    engine: str = "tesseract"


WINDOWS_DEFAULTS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"]


def _tesseract_path() -> str | None:
    """PATH first, then the standard Windows install folders (the installer doesn't add itself to PATH)."""
    import os
    found = shutil.which("tesseract")
    if found:
        return found
    for p in [os.environ.get("SENTINEL_TESSERACT_CMD", "")] + WINDOWS_DEFAULTS:
        if p and os.path.isfile(p):
            return p
    return None


def available() -> bool:
    try:
        import pytesseract
    except ImportError:
        return False
    path = _tesseract_path()
    if path:
        pytesseract.pytesseract.tesseract_cmd = path
    return path is not None


# Tesseract script name (from orientation & script detection) -> language model
SCRIPT_LANG = {"Devanagari": "hin", "Tamil": "tam", "Bengali": "ben", "Telugu": "tel", "Kannada": "kan",
               "Malayalam": "mal", "Gujarati": "guj", "Gurmukhi": "pan"}
_installed: set[str] | None = None


def installed() -> set[str]:
    global _installed
    if _installed is None:
        try:
            import pytesseract
            _installed = set(pytesseract.get_languages(config=""))
        except Exception:  # noqa: BLE001
            _installed = set()
    return _installed


def languages() -> str:
    """Language models available to OCR. With 'auto', English is always used and an Indian-script model is added
    per image only when script detection finds that script (loading every model at once causes digit misreads,
    e.g. '₹25,000' read as '425,000')."""
    cfg = get_settings().ocr_lang
    if cfg != "auto":
        return cfg
    return "+".join(["eng"] + [l for l in SCRIPT_LANG.values() if l in installed()])


def _script_lang(img: Image.Image) -> str | None:
    if get_settings().ocr_lang != "auto":
        return None
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(img, config="--psm 0 -c min_characters_to_try=10")
    except Exception:  # noqa: BLE001 — OSD fails on sparse screenshots; English only then
        return None
    for line in osd.splitlines():
        if line.startswith("Script:"):
            lang = SCRIPT_LANG.get(line.split(":", 1)[1].strip())
            return lang if lang in installed() else None
    return None


def _prepare(img: Image.Image) -> Image.Image:
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", img.size, (255, 255, 255))
        img = img.convert("RGBA")
        bg.paste(img, mask=img.split()[-1])
        img = bg
    g = img.convert("L")
    if g.width < 1400:
        scale = min(3.0, 1400 / max(g.width, 1))
        g = g.resize((int(g.width * scale), int(g.height * scale)), Image.LANCZOS)
    hist = g.histogram()
    mean = sum(i * c for i, c in enumerate(hist)) / max(sum(hist), 1)
    if mean < 110:  # dark-mode screenshot
        g = ImageOps.invert(g)
    return ImageOps.autocontrast(g, cutoff=1)


def _run(img: Image.Image, psm: int, lang: str) -> tuple[list[dict], float, int]:
    import pytesseract
    d = pytesseract.image_to_data(img, lang=lang, config=f"--oem 1 --psm {psm}",
                                  output_type=pytesseract.Output.DICT)
    lines: dict[tuple, list[tuple[str, float]]] = {}
    for i, word in enumerate(d["text"]):
        w = (word or "").strip()
        conf = float(d["conf"][i])
        if not w or conf < 0:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        lines.setdefault(key, []).append((w, conf))
    out, confs = [], []
    for key in sorted(lines):
        words = lines[key]
        out.append({"text": " ".join(w for w, _ in words), "conf": round(sum(c for _, c in words) / len(words) / 100, 3)})
        confs += [c for _, c in words]
    quality = (sum(confs) / len(confs) / 100) if confs else 0.0
    return out, quality, len(confs)


def ocr_image(data: bytes) -> OcrResult:
    if not available():
        return OcrResult(ok=False, error="OCR engine (Tesseract) is not installed on this server.")
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError):
        return OcrResult(ok=False, error="The file could not be opened as an image.")
    prepared = _prepare(img)
    cfg = get_settings().ocr_lang
    extra = _script_lang(prepared)
    lang = cfg if cfg != "auto" else ("eng+" + extra if extra else "eng")
    best: tuple[list[dict], float, int] | None = None
    for psm in (6, 11):  # uniform block first, then sparse text (UPI app layouts are sparse)
        lines, q, n = _run(prepared, psm, lang)
        if best is None or (n >= 3 and q * min(n, 40) > best[1] * min(best[2], 40)):
            best = (lines, q, n)
        if n >= 8 and q >= 0.8:
            break
    lines, quality, n = best
    text = "\n".join(l["text"] for l in lines)
    if n == 0 or quality < MIN_QUALITY:
        return OcrResult(ok=False, text=text, lines=lines, quality=quality,
                         error="Could not reliably extract text from this image.")
    return OcrResult(ok=True, text=text, lines=lines, quality=round(quality, 3), engine=f"tesseract:{lang}")
