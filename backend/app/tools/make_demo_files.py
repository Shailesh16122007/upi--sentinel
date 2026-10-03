"""Generates the synthetic demo evidence and the sample upload files (committed to the repo).

    python -m app.tools.make_demo_files

All content is SYNTHETIC. Images carry a visible "SYNTHETIC DEMONSTRATION DATA" watermark and use a
generic app and a fictional bank ("Demo Bank") so nothing imitates a real organisation's UI.
Audio needs espeak-ng (pip install espeakng-loader); if unavailable, existing WAV files are kept.
"""
from __future__ import annotations

import csv
import ctypes
import json
import os
import random
import wave
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
DEMO = ROOT / "demo_evidence"
SAMPLE = ROOT / "sample_uploads"
FONTS = ROOT / "app" / "services" / "reporting" / "fonts"

CALL_LINES = [
    (0, "Hello, am I speaking with Ananya madam?"),
    (4, "Madam, I am calling from your bank KYC department."),
    (10, "Your account will be blocked today because your KYC is pending."),
    (17, "To keep the account active, a verification request will come on your UPI app."),
    (24, "Please approve the request and enter your PIN immediately."),
    (33, "Okay, I have entered the PIN. Is it done now?"),
    (38, "Yes madam, verification is complete. Do not share this call with anyone."),
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / ("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf")), size)


def watermark(img: Image.Image) -> None:
    d = ImageDraw.Draw(img)
    d.rectangle([0, img.height - 44, img.width, img.height], fill="#B42318")
    d.text((img.width // 2, img.height - 22), "SYNTHETIC DEMONSTRATION DATA", font=font(17, True), fill="white", anchor="mm")


def payment_screen(path: Path, lines: list[tuple[str, int, bool, str]], synthetic_mark: bool = True) -> None:
    img = Image.new("RGB", (560, 980), "#FFFFFF")
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, 560, 70], fill="#F2F4F7")
    d.text((28, 35), "UPI App", font=font(22, True), fill="#0F1B2D", anchor="lm")
    y = 120
    for text, size, bold, color in lines:
        d.text((40, y), text, font=font(size, bold), fill=color)
        y += int(size * 1.9)
    if synthetic_mark:
        watermark(img)
    img.save(path)


_ESPEAK: dict = {}


def _espeak():
    """Initialise libespeak-ng once (re-initialising crashes the library)."""
    if _ESPEAK:
        return _ESPEAK
    import espeakng_loader as e
    lib = ctypes.cdll.LoadLibrary(e.get_library_path())
    buf: list[int] = []
    CB = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(ctypes.c_short), ctypes.c_int, ctypes.c_void_p)

    @CB
    def cb(wav, n, _):
        if n > 0:
            buf.extend(wav[:n])
        return 0
    sr = lib.espeak_Initialize(1, 0, os.path.dirname(e.get_data_path()).encode(), 0)
    lib.espeak_SetSynthCallback(cb)
    lib.espeak_SetVoiceByName(b"en")
    lib.espeak_SetParameter(1, 150, 0)
    _ESPEAK.update(lib=lib, buf=buf, cb=cb, sr=sr)
    return _ESPEAK


def tts(lines: list[tuple[int, str]], out: Path) -> bool:
    try:
        es = _espeak()
    except (ImportError, OSError):
        return False
    lib, buf, sr = es["lib"], es["buf"], es["sr"]
    buf.clear()
    for start, text in lines:
        target = start * sr
        if len(buf) < target:
            buf.extend([0] * (target - len(buf)))
        t = text.encode()
        lib.espeak_Synth(t, len(t) + 1, 0, 0, 0, 0, None, None)
        lib.espeak_Synchronize()
        buf.extend([0] * int(0.4 * sr))
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((ctypes.c_short * len(buf))(*buf))
    return True


def history_csv(path: Path, end: datetime, n: int = 60, seed: int = 11) -> None:
    rnd = random.Random(seed)
    payees = [("freshmart@okaxis", "FreshMart Grocers", (150, 1800)), ("metrocard@ybl", "Metro Card Recharge", (200, 500)),
              ("priya.n@oksbi", "Priya N", (500, 2400)), ("chaipoint@ybl", "Chai Point", (90, 300)),
              ("electricity.bescom@axl", "Electricity Board", (900, 2200)), ("pharmacy.local@okicici", "Local Pharmacy", (120, 950)),
              ("bookstore@ybl", "City Bookstore", (250, 1200)), ("mobile.recharge@paytm", "Mobile Recharge", (199, 599))]
    rows = []
    t = end - timedelta(days=60)
    for i in range(n):
        t += timedelta(days=60 / n)
        vpa, name, (lo, hi) = rnd.choice(payees)
        ts = t.replace(hour=rnd.randint(8, 20), minute=rnd.randint(0, 59), second=0)
        rows.append({"Date": ts.strftime("%d-%m-%Y"), "Time": ts.strftime("%H:%M"), "Description": vpa, "Payee": name,
                     "Amount": f"{round(rnd.uniform(lo, hi), -1):.2f}", "Type": "UPI", "UTR": f"4{rnd.randint(10**10, 10**11 - 1)}",
                     "Status": "SUCCESS", "Device": "Pixel 7 (customer)"})
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    DEMO.mkdir(exist_ok=True)
    SAMPLE.mkdir(exist_ok=True)
    dark, grey, green = "#0F1B2D", "#4A5568", "#067647"

    # ---------------- synthetic demo case
    payment_screen(DEMO / "upi_payment_screenshot.png", [
        ("Payment Successful", 30, True, green), ("₹25,000", 54, True, dark), ("Paid to", 20, False, grey),
        ("Rahul Traders", 26, True, dark), ("rahultraders@ybl", 22, False, grey), ("01 Oct 2026, 10:32 PM", 22, False, grey),
        ("UPI transaction ID: 427613847291", 20, False, grey), ("Debited from Demo Bank XX4417", 20, False, grey)])
    (DEMO / "bank_sms.txt").write_text(
        "Dear Customer, your A/c XX4417 is debited by Rs.25,000.00 on 01-10-26 22:32 for UPI payment to rahultraders@ybl. "
        "UPI Ref No 427613847291. If not done by you, report to Demo Bank. -Demo Bank\n")
    (DEMO / "scam_call_transcript.txt").write_text("\n".join(f"[{s // 60:02d}:{s % 60:02d}] {t}" for s, t in CALL_LINES) + "\n")
    tts(CALL_LINES, DEMO / "scam_call.wav")
    history_csv(DEMO / "transaction_history.csv", datetime(2026, 9, 30, 20, 0))
    events = [
        {"timestamp": "2026-09-29T09:12:00+05:30", "event": "LOGIN", "device_id": "Pixel 7 (customer)", "ip": "49.37.120.15"},
        {"timestamp": "2026-09-30T19:45:00+05:30", "event": "LOGIN", "device_id": "Pixel 7 (customer)", "ip": "49.37.120.15"},
        {"timestamp": "2026-10-01T22:26:40+05:30", "event": "LOGIN", "device_id": "Redmi Note 12", "ip": "103.88.12.7"},
        {"timestamp": "2026-10-01T22:27:10+05:30", "event": "DEVICE_REGISTERED", "device_id": "Redmi Note 12",
         "ip": "103.88.12.7", "detail": "UPI device binding completed"},
        {"timestamp": "2026-10-01T22:30:05+05:30", "event": "BENEFICIARY_ADDED", "device_id": "Redmi Note 12",
         "detail": "rahultraders@ybl"},
        {"timestamp": "2026-10-01T22:32:18+05:30", "event": "UPI PIN verified (AUTH_SUCCESS)", "device_id": "Redmi Note 12",
         "ip": "103.88.12.7", "reference": "427613847291"},
    ]
    (DEMO / "account_activity.json").write_text(json.dumps({"events": events}, indent=2))

    # ---------------- sample uploads for the "real evidence" test (no watermark — these exercise the normal pipeline)
    payment_screen(SAMPLE / "upi_screenshot_847291.png", [
        ("Payment Successful", 30, True, green), ("₹25,000", 54, True, dark), ("UPI", 22, False, grey),
        ("03 Oct 2026", 22, False, grey), ("10:32 PM", 22, False, grey), ("Ref: 847291", 22, False, grey)], synthetic_mark=False)
    (SAMPLE / "bank_sms_847291.txt").write_text("Your account has been debited Rs.25,000 through UPI.\nReference number 847291.\n")
    (SAMPLE / "bank_sms_conflicting_amount.txt").write_text("Your account has been debited Rs.20,000 through UPI.\nReference number 847291.\n")
    if not tts([(0, "Hello, I am calling from your bank."),
                (3, "Please approve the UPI request to prevent your account from being blocked.")], SAMPLE / "scam_call.wav"):
        print("espeak-ng not available — audio samples not regenerated")
    history_csv(SAMPLE / "transaction_history.csv", datetime(2026, 10, 2, 20, 0), seed=5)
    print("Demo and sample files written to", DEMO, "and", SAMPLE)


if __name__ == "__main__":
    main()
