"""Unknown-evidence fixtures: layouts and formats NOT used by the demo generator.

Generated at test time into a temporary folder (nothing here is tuned into the extraction code)."""
import io, wave, math, random, struct
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

ROOT = Path(__file__).resolve().parents[2]
DJ = str(ROOT / "app/services/reporting/fonts/DejaVuSans.ttf")
DJB = str(ROOT / "app/services/reporting/fonts/DejaVuSans-Bold.ttf")
DEVA = "/usr/share/fonts/truetype/lohit-devanagari/Lohit-Devanagari.ttf"


def make(OUT: Path) -> Path:
    f = lambda s, b=False: ImageFont.truetype(DJB if b else DJ, s)

    # 1. dark-mode payment screen, different wording, no reference number, time only (no date)
    img = Image.new("RGB", (720, 1280), "#121212"); d = ImageDraw.Draw(img)
    d.text((40, 60), "Paid", font=f(40, True), fill="#FFFFFF")
    d.text((40, 160), "₹ 7,499", font=f(72, True), fill="#FFFFFF")
    d.text((40, 290), "To: Quick Loan Services", font=f(32), fill="#E0E0E0")
    d.text((40, 345), "quickloan.help@axl", font=f(28), fill="#BDBDBD")
    d.text((40, 420), "9:47 pm", font=f(28), fill="#BDBDBD")
    d.text((40, 480), "Completed", font=f(28), fill="#81C784")
    img.save(OUT / "dark_payment.png")

    # 2. bank SMS in Hindi (Devanagari) as a phone screenshot
    img = Image.new("RGB", (720, 900), "white"); d = ImageDraw.Draw(img)
    fd = ImageFont.truetype(DEVA, 30) if Path(DEVA).exists() else ImageFont.truetype(DJ, 30)
    lines = ["प्रिय ग्राहक, आपके खाते XX7781 से", "रु. 12,000 UPI द्वारा डेबिट किए गए", "दिनांक 28-09-2026 18:42", "UPI Ref No 427699001234",
             "यदि आपने नहीं किया है तो तुरंत बैंक को सूचित करें।"]
    for i, l in enumerate(lines):
        d.text((40, 80 + i * 60), l, font=fd, fill="#111111")
    img.save(OUT / "hindi_sms.png")

    # 3. photo of a screen: JPEG, slightly rotated + blurred, with a misread-prone amount
    img = Image.new("RGB", (900, 1200), "#F7F7F7"); d = ImageDraw.Draw(img)
    d.text((60, 80), "Transaction Successful", font=f(40, True), fill="#1B5E20")
    d.text((60, 180), "Rs. 3,250.00", font=f(64, True), fill="#111")
    d.text((60, 300), "Paid to ravi.store@okhdfcbank", font=f(32), fill="#333")
    d.text((60, 360), "UTR: 427655512345", font=f(32), fill="#333")
    d.text((60, 420), "27 Sep 2026, 11:05 AM", font=f(32), fill="#333")
    img = img.rotate(2.5, expand=True, fillcolor="#DDDDDD").filter(ImageFilter.GaussianBlur(1.1))
    img.save(OUT / "photo_of_screen.jpg", quality=72)

    # 4. two-page bank statement PDF with several transactions (incl. the disputed one)
    pdfmetrics.registerFont(TTFont("DJ", DJ))
    c = canvas.Canvas(str(OUT / "bank_statement.pdf"), pagesize=A4)
    c.setFont("DJ", 11); c.drawString(40, 800, "Demo Bank — Statement of Account"); c.drawString(40, 784, "A/c No XXXXXXXX4417   Period: 01-09-2026 to 03-10-2026")
    rows = [("28-09-2026", "UPI/freshmart@okaxis/Groceries", "1,240.00", "427600100001"), ("29-09-2026", "UPI/metrocard@ybl/Recharge", "300.00", "427600100002"),
            ("30-09-2026", "NEFT/SALARY CREDIT", "52,000.00 Cr", "N274932"), ("01-10-2026", "UPI/rahultraders@ybl/Payment", "25,000.00", "427613847291"),
            ("02-10-2026", "UPI/chaipoint@ybl/Food", "180.00", "427600100005")]
    y = 750
    c.drawString(40, y, "Date          Narration                                  Amount (Rs)   Ref No"); y -= 20
    for r in rows[:3]:
        c.drawString(40, y, f"{r[0]}  {r[1]:<40} Rs.{r[2]:>12}   {r[3]}"); y -= 18
    c.drawString(40, 60, "Page 1 of 2"); c.showPage(); c.setFont("DJ", 11); y = 780
    for r in rows[3:]:
        c.drawString(40, y, f"{r[0]}  {r[1]:<40} Rs.{r[2]:>12}   UPI Ref No {r[3]}"); y -= 18
    c.drawString(40, 60, "Page 2 of 2   Closing balance Rs.1,02,345.10"); c.save()

    # 5. corrupted PDF (valid header, garbage body)
    (OUT / "corrupted.pdf").write_bytes(b"%PDF-1.7\n" + bytes(random.Random(1).getrandbits(8) for _ in range(4000)))

    # 6. noisy "phone call" audio: tones + noise (no intelligible speech)
    sr = 8000
    with wave.open(str(OUT / "noisy_call.wav"), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        rnd = random.Random(3)
        w.writeframes(b"".join(struct.pack("<h", int(4000 * math.sin(2 * math.pi * 440 * t / sr) * (t // 4000 % 2) + rnd.gauss(0, 1500))) for t in range(sr * 6)))

    # 7. Hinglish chat export as text (WhatsApp format) with a phishing link
    (OUT / "whatsapp_chat.txt").write_text(
        "28/09/2026, 18:30 - +91 90000 55511: Sir aapka electricity bill update nahi hua hai\n"
        "28/09/2026, 18:31 - +91 90000 55511: Aaj raat 9 baje bijli kat jayegi\n"
        "28/09/2026, 18:31 - +91 90000 55511: Turant is number pe call karo ya link pe pay karo http://bijli-update-pay.xyz/p\n"
        "28/09/2026, 18:35 - Me: kitna pay karna hai?\n"
        "28/09/2026, 18:36 - +91 90000 55511: Sirf 12 rupaye verification, QuickSupport app download karo\n", encoding="utf-8")

    # 8. email export (.eml) with HTML body
    (OUT / "refund_email.eml").write_text(
        "From: \"Refund Desk\" <refunds@claims-desk.example>\nTo: customer@example.com\nSubject: Your refund of Rs 4,999 is pending\n"
        "Date: Fri, 26 Sep 2026 10:15:00 +0530\nMIME-Version: 1.0\nContent-Type: text/html; charset=utf-8\n\n"
        "<html><body><p>Dear customer,</p><p>Your refund of <b>Rs 4,999</b> is pending. To receive the refund, approve the collect request "
        "from <b>refund.desk@ybl</b> and enter your UPI PIN.</p><p>Call 9000033221 for help.</p></body></html>\n")
    return OUT


if __name__ == "__main__":  # python -m tests.unknown.make_fixtures /tmp/fixtures
    import sys
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/sentinel-fixtures")
    out.mkdir(parents=True, exist_ok=True)
    print("written to", make(out))
