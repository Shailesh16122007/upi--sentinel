"""OCR for screenshots and photos (Tesseract via pytesseract).

Real evidence is messy: dark mode, coloured app backgrounds, photos of a screen taken at an angle, rotated
images, tiny crops, huge camera photos, iPhone HEIC files. Each image is therefore read several ways
(different clean-ups and page layouts, rotation corrected) and the best reading is kept. Word-level
confidences are kept so extracted values carry an honest confidence; text that is only partly readable is
returned as low quality (the values are then marked "needs review") rather than thrown away.
"""
from __future__ import annotations

import io
import shutil
from dataclasses import dataclass, field

import logging
import os

from PIL import Image, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from app.config import get_settings

RELIABLE_QUALITY = 0.55   # below this the text is shown but entities are marked low-confidence
MIN_QUALITY = 0.30        # below this (or with too few confident words) the image is reported as unreadable
MIN_WORDS = 2
NOT_INSTALLED = "OCR engine (Tesseract) is not installed on this server."
log = logging.getLogger("sentinel.ocr")

try:  # iPhone photos (HEIC/HEIF) — optional dependency
    from pillow_heif import register_heif_opener
    register_heif_opener()
except Exception:  # noqa: BLE001
    pass


@dataclass
class OcrResult:
    ok: bool
    text: str = ""
    lines: list[dict] = field(default_factory=list)  # [{text, conf}]
    quality: float = 0.0
    error: str | None = None
    engine: str = "tesseract"


WINDOWS_DEFAULTS = [r"C:\Program Files\Tesseract-OCR\tesseract.exe", r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
                    os.path.expandvars(r"%LOCALAPPDATA%\Programs\Tesseract-OCR\tesseract.exe"),
                    os.path.expandvars(r"%LOCALAPPDATA%\Tesseract-OCR\tesseract.exe")]


def _tesseract_path() -> str | None:
    """PATH first, then the standard Windows install folders (the installer doesn't add itself to PATH)."""
    found = shutil.which("tesseract")
    if found:
        return found
    for p in [os.environ.get("SENTINEL_TESSERACT_CMD", ""), get_settings().tesseract_cmd or ""] + WINDOWS_DEFAULTS:
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


def _normalise(img: Image.Image) -> Image.Image:
    """Any mode/size → upright grayscale at a size Tesseract reads well."""
    img = ImageOps.exif_transpose(img)
    if img.mode in ("RGBA", "LA", "P", "PA"):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[-1])
        img = bg
    elif img.mode not in ("RGB", "L"):
        img = img.convert("RGB")  # CMYK, I;16, F ...
    g = img.convert("L")
    w = max(g.width, 1)
    if w < 1400:  # small screenshots and crops: enlarge so letters are ~30px high
        scale = min(4.0, 1400 / w)
        g = g.resize((int(g.width * scale), int(g.height * scale)), Image.LANCZOS)
    elif w > 2600:  # large camera photos: shrink (faster, and Tesseract dislikes huge glyphs)
        scale = 2200 / w
        g = g.resize((int(g.width * scale), int(g.height * scale)), Image.LANCZOS)
    return g


def _variants(g: Image.Image):
    """Different clean-ups; dark-mode images are inverted first. Yielded best-first for typical screenshots."""
    if ImageStat.Stat(g).mean[0] < 110:  # dark mode
        g = ImageOps.invert(g)
    base = ImageOps.autocontrast(g, cutoff=1)
    yield "contrast", base
    # binarise: removes coloured cards, gradients and low-contrast backgrounds
    mean = ImageStat.Stat(base).mean[0]
    yield "binary", base.point(lambda v: 255 if v > mean * 0.85 else 0)
    # photos of screens: soften noise / moiré, then sharpen
    yield "photo", ImageOps.autocontrast(base.filter(ImageFilter.MedianFilter(3)).filter(ImageFilter.SHARPEN), cutoff=2)
    # light grey text on white (some UPI apps): stretch harder
    yield "faint", ImageOps.equalize(g)


def _prepare(img: Image.Image) -> Image.Image:  # kept for callers that need one prepared image
    return next(_variants(_normalise(img)))[1]


def _rotation(img: Image.Image) -> int:
    """Degrees to rotate (from Tesseract orientation detection). 0 when unsure."""
    try:
        import pytesseract
        osd = pytesseract.image_to_osd(img, config="--psm 0 -c min_characters_to_try=10")
    except Exception:  # noqa: BLE001 — sparse screenshots often have too little text for OSD
        return 0
    rot, conf = 0, 0.0
    for line in osd.splitlines():
        if line.startswith("Rotate:"):
            rot = int(line.split(":")[1])
        elif line.startswith("Orientation confidence:"):
            conf = float(line.split(":")[1])
    return rot if rot and conf >= 1.5 else 0


def _run(img: Image.Image, psm: int, lang: str) -> tuple[list[dict], float, int, int]:
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
    good = sum(1 for ws in lines.values() for w, c in ws if c >= 60 and sum(ch.isalnum() for ch in w) >= 2)
    for key in sorted(lines):
        words = lines[key]
        out.append({"text": " ".join(w for w, _ in words), "conf": round(sum(c for _, c in words) / len(words) / 100, 3)})
        confs += [c for _, c in words]
    quality = (sum(confs) / len(confs) / 100) if confs else 0.0
    return out, quality, len(confs), good


def _score(q: float, n: int) -> float:
    return q * min(n, 60)


def ocr_image(data: bytes) -> OcrResult:
    if not available():
        return OcrResult(ok=False, error=NOT_INSTALLED)
    try:
        img = Image.open(io.BytesIO(data))
        if getattr(img, "n_frames", 1) > 1:
            img.seek(0)  # animated GIF / multi-page TIFF: first frame
        img.load()
    except (UnidentifiedImageError, OSError, ValueError):
        return OcrResult(ok=False, error="The file could not be opened as an image.")
    try:
        g = _normalise(img)
    except Exception as e:  # noqa: BLE001
        log.warning("Image normalisation failed: %s", type(e).__name__)
        return OcrResult(ok=False, error="The image could not be prepared for reading.")
    rot = _rotation(g)
    if rot:
        g = g.rotate(-rot, expand=True, fillcolor=255)
    cfg = get_settings().ocr_lang
    extra = _script_lang(next(_variants(g))[1])
    lang = cfg if cfg != "auto" else ("eng+" + extra if extra else "eng")

    best: tuple[list[dict], float, int, int, str] | None = None
    tried = 0
    for vi, (name, variant) in enumerate(_variants(g)):
        for psm in (6, 11, 4):  # block of text · sparse text (app layouts) · columns
            try:
                lines, q, n, good = _run(variant, psm, lang)
            except Exception as e:  # noqa: BLE001
                log.warning("Tesseract run failed (%s, psm %s): %s", name, psm, type(e).__name__)
                continue
            tried += 1
            if best is None or (good, _score(q, n)) > (best[3], _score(best[1], best[2])):
                best = (lines, q, n, good, f"{name}/psm{psm}")
            if n >= 8 and q >= 0.85:
                break
        if best and best[2] >= 8 and best[1] >= 0.80:
            break  # good enough — don't spend time on further clean-ups
        if vi >= 1 and best and (best[3] == 0 or best[1] < 0.35):
            break  # two clean-ups found nothing that reads like text (noise, a photo without words)
    if best is None:
        return OcrResult(ok=False, error="Tesseract could not process this image." if tried == 0 else
                         "No text could be found in this image.")
    lines, quality, n, good, how = best
    text = "\n".join(l["text"] for l in lines)
    if good < MIN_WORDS or quality < MIN_QUALITY:
        return OcrResult(ok=False, text=text, lines=lines, quality=quality,
                         error="No readable text was found in this image." if good < MIN_WORDS
                         else "Text in this image was too unclear to read reliably.")
    if img.width < 400 and img.height < 400:
        # a thumbnail-sized image: letters are a few pixels high, so digits are easily confused — every value
        # read from it is marked for review instead of being trusted
        quality = min(quality, 0.5)
        how += ":small-image"
    return OcrResult(ok=True, text=text, lines=lines, quality=round(quality, 3),
                     engine=f"tesseract:{lang}:{how}" + (f":rot{rot}" if rot else ""))
