"""Evidence integrity.

1. Chain of custody: SHA-256 recorded at upload and re-verified whenever the original is read.
   A matching hash proves the *stored file* has not changed since upload. It says nothing about whether the
   screenshot or document was truthful or unedited before it was uploaded.
2. Image technical indicators: metadata and compression checks that may warrant review. These never prove
   manipulation or authenticity; the result is either "possible manipulation indicators" or
   "no obvious technical indicators found" plus the list of checks actually performed.
"""
from __future__ import annotations

import hashlib
import io
from datetime import datetime, timezone
from pathlib import Path

from PIL import ExifTags, Image, ImageChops
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import EvidenceFile, EvidenceHash

EDITORS = ("photoshop", "gimp", "snapseed", "picsart", "canva", "lightroom", "pixlr", "paint.net", "affinity", "fotor",
           "photo editor", "inshot", "meitu", "facetune", "remini")
NOTE = ("Technical indicators only. They may warrant further review but do not show that the image was edited, "
        "and their absence does not show that it is authentic.")


def record_hash(db: Session, ev: EvidenceFile) -> EvidenceHash:
    h = EvidenceHash(evidence_id=ev.id, digest=ev.sha256, size_bytes=ev.size_bytes or 0,
                     last_verified_at=ev.uploaded_at, last_result="MATCH", verify_count=1)
    db.add(h)
    return h


def verify(db: Session, ev: EvidenceFile) -> str:
    """Re-hash the stored original. Returns MATCH | MISMATCH | MISSING and records the result."""
    p = Path(ev.storage_path or "")
    if not ev.storage_path or not p.exists():
        result = "MISSING"
    else:
        result = "MATCH" if hashlib.sha256(p.read_bytes()).hexdigest() == ev.sha256 else "MISMATCH"
    h = db.scalar(select(EvidenceHash).where(EvidenceHash.evidence_id == ev.id))
    if h is None:
        h = EvidenceHash(evidence_id=ev.id, digest=ev.sha256 or "", size_bytes=ev.size_bytes or 0, verify_count=0)
        db.add(h)
    h.last_verified_at, h.last_result, h.verify_count = datetime.now(timezone.utc), result, (h.verify_count or 0) + 1
    return result


def describe(h: EvidenceHash | None, ev: EvidenceFile) -> dict:
    res = h.last_result if h else None
    return {
        "algorithm": "SHA-256", "digest": ev.sha256, "uploaded_at": ev.uploaded_at, "size_bytes": ev.size_bytes,
        "original_name": ev.original_name, "mime": ev.mime,
        "last_verified_at": h.last_verified_at if h else None, "verify_count": h.verify_count if h else 0,
        "result": res or "NOT_VERIFIED",
        "status": {"MATCH": "Original file preserved", "MISMATCH": "Stored file does not match its recorded hash",
                   "MISSING": "Stored file is missing"}.get(res or "", "Not yet verified"),
        "meaning": "The hash shows the stored file has not changed since it was uploaded. It does not show whether "
                   "the content was accurate or unedited before upload.",
    }


def check_image(data: bytes) -> dict:
    checks, indicators = [], []
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:  # noqa: BLE001
        return {"status": "not_checked", "checks": [], "indicators": [], "note": "The image could not be opened for checks."}
    fmt = (img.format or "").upper()

    # 1. metadata
    checks.append("Embedded metadata (software, capture vs modification time)")
    sw = None
    exif = {}
    try:
        raw = img.getexif()
        exif = {ExifTags.TAGS.get(k, k): v for k, v in raw.items()}
        sub = raw.get_ifd(0x8769) if hasattr(raw, "get_ifd") else {}
        exif.update({ExifTags.TAGS.get(k, k): v for k, v in (sub or {}).items()})
    except Exception:  # noqa: BLE001
        pass
    sw = str(exif.get("Software") or img.info.get("Software") or img.info.get("software") or "")
    if sw and any(e in sw.lower() for e in EDITORS):
        indicators.append({"code": "EDITING_SOFTWARE", "label": "Image editing software recorded in metadata",
                           "detail": f"Metadata names '{sw[:60]}'. Images are often opened in editors for harmless reasons (cropping)."})
    orig, mod = exif.get("DateTimeOriginal"), exif.get("DateTime")
    if orig and mod and str(orig) != str(mod):
        indicators.append({"code": "MODIFIED_AFTER_CAPTURE", "label": "Metadata shows a modification time after capture",
                           "detail": f"Captured {orig}, modified {mod}."})

    # 2. compression consistency (JPEG only; PNG screenshots are lossless)
    if fmt == "JPEG":
        checks.append("Compression consistency across image regions (error level analysis)")
        try:
            rgb = img.convert("RGB")
            buf = io.BytesIO()
            rgb.save(buf, "JPEG", quality=90)
            diff = ImageChops.difference(rgb, Image.open(io.BytesIO(buf.getvalue()))).convert("L")
            w, h = diff.size
            bs = 32
            means = []
            px = diff.load()
            for by in range(0, h - bs + 1, bs):
                for bx in range(0, w - bs + 1, bs):
                    tot = 0
                    for y in range(by, by + bs, 4):
                        for x in range(bx, bx + bs, 4):
                            tot += px[x, y]
                    means.append(tot / ((bs // 4) ** 2))
            if len(means) >= 20:
                srt = sorted(means)
                med = srt[len(srt) // 2] or 0.5
                p99 = srt[int(len(srt) * 0.99) - 1]
                hot = sum(1 for m in means if m > max(6 * med, 10))
                if p99 > max(8 * med, 12) and 0 < hot <= len(means) * 0.15:
                    indicators.append({"code": "UNEVEN_COMPRESSION", "label": "Uneven compression levels between regions",
                                       "detail": f"{hot} of {len(means)} regions recompress very differently from the rest. "
                                                 "Can come from pasted content, but also from sharp text or graphics."})
        except Exception:  # noqa: BLE001
            pass
    else:
        checks.append(f"Compression analysis not applicable ({fmt or 'unknown'} is not a JPEG)")

    # 3. dimensions
    checks.append("Image dimensions")
    if img.width < 200 or img.height < 200:
        indicators.append({"code": "VERY_SMALL", "label": "Very small image", "detail": f"{img.width}×{img.height} pixels; "
                           "details may be unreadable and the image may be a re-saved crop."})
    return {"status": "indicators_found" if indicators else "no_obvious_indicators",
            "label": "Possible manipulation indicators" if indicators else "No obvious technical indicators found",
            "checks": checks, "indicators": indicators, "format": fmt, "size": [img.width, img.height],
            "software": sw or None, "note": NOTE}
