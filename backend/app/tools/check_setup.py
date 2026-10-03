"""Check that this computer can read evidence.

    python -m app.tools.check_setup

Reports whether Tesseract OCR is found (and where), which languages it has, reads a sample screenshot,
and whether speech-to-text is ready. Run it when uploads say they could not be read.
"""
from pathlib import Path

from app.config import get_settings
from app.services.audio import stt
from app.services.ocr import engine

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    ok = True
    print("UPI Sentinel — setup check\n")
    path = engine._tesseract_path()
    if not engine.available():
        ok = False
        print("✗ Tesseract OCR: NOT FOUND — images cannot be read.")
        print("  Install it: Windows https://github.com/UB-Mannheim/tesseract/wiki (tick Hindi and Tamil),")
        print("  macOS `brew install tesseract tesseract-lang`, Ubuntu `sudo apt install tesseract-ocr tesseract-ocr-hin`.")
        print("  If it is installed in an unusual folder, add to backend/.env:")
        print(r"  SENTINEL_TESSERACT_CMD=C:\path\to\tesseract.exe")
    else:
        import pytesseract
        print(f"✓ Tesseract OCR: {path}  (version {pytesseract.get_tesseract_version()})")
        langs = sorted(engine.installed())
        print(f"  Languages: {', '.join(langs) or 'none found'}")
        if "eng" not in langs:
            ok = False
            print("  ✗ English language data (eng) is missing — reinstall Tesseract with English.")
        for code, name in (("hin", "Hindi"), ("tam", "Tamil")):
            if code not in langs:
                print(f"  · {name} ({code}) not installed — {name} text in images will not be read (optional).")
        sample = ROOT / "sample_uploads" / "upi_screenshot_847291.png"
        if sample.exists():
            r = engine.ocr_image(sample.read_bytes())
            print(f"  Sample screenshot: {'read OK' if r.ok else 'FAILED'} — quality {r.quality:.0%}"
                  + (f" — {r.error}" if r.error else "") + f"\n    “{' | '.join(r.text.splitlines()[:4])}”")
            ok = ok and r.ok
    s = get_settings()
    st = stt.status()
    if s.stt_engine.lower() in ("none", "off", "disabled"):
        print("· Speech-to-text: disabled (SENTINEL_STT_ENGINE=none)")
    else:
        model = stt._load()
        if model is None:
            print(f"· Speech-to-text: not ready — {stt.status()['error']}")
            print("  Run once with internet: python -m app.tools.fetch_models   (call recordings are still saved without it)")
        else:
            print(f"✓ Speech-to-text: {st['engine']} ready")
    print("\nDatabase:", s.database_url.split("@")[-1] if "@" in s.database_url else s.database_url)
    print("\nResult:", "ready to read evidence" if ok else "fix the ✗ items above, then restart the backend")


if __name__ == "__main__":
    main()
