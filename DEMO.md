# Demo script (≈5 minutes)

**Story:** "A customer lost ₹25,000. She has a screenshot, an SMS and a recording of the call. Watch what
UPI Sentinel does with exactly that."

1. **Home** → *Start a new dispute*. Type: "₹25,000 was transferred from my account. I did not intend to make
   this payment." Continue.
2. **Upload** `backend/sample_uploads/upi_screenshot_847291.png` under *Screenshots & images*.
   Point at the steps ticking: file received → type detected → content extracted (OCR) → entities → transaction found.
3. *Messages → Paste text*, paste `Your account has been debited Rs.25,000 through UPI. Reference number 847291.`
   → the panel shows "Disputed transaction identified from 2 sources".
4. Upload `scam_call.wav` under *Audio*. With the Whisper model installed the transcript appears with statements
   ("Speaker claimed to represent a bank", "asked the listener to approve the UPI request") labelled as
   *statements extracted from audio*. Without it: "Audio transcription unavailable" — nothing invented.
5. *Open investigation*. Overview: amount / time / reference with **E1 E2** tags and "Agrees". Click **E1**:
   the original screenshot, OCR text, every extracted value with confidence — note OCR read ₹ as ¥ and it is flagged.
6. Upload `bank_sms_conflicting_amount.txt` (₹20,000, same reference) → **Evidence conflict: amount**,
   both values preserved, "investigator review required".
7. Back to home → **Load synthetic demo case** (clearly labelled synthetic). Show:
   - 7 anomalies, including the sequence *call → new device registered → 3 min → new beneficiary → 2 min → ₹25,000*;
   - Isolation Forest against 60 past payments;
   - **Contradictory**: customer says she did not intend the payment, yet a UPI PIN authentication is recorded —
     the system shows the conflict and does not pick a side;
   - Timeline (solid = documented, hollow = statement, dashed = approximate), Evidence graph (click nodes).
8. Add an investigator note → *Report* → *Generate report* → *Download report* (16 sections, every row cites E-codes,
   audit trail at the end).

Closing line: *"UPI Sentinel doesn't call it fraud. It hands the investigator every fact, where it came from,
what conflicts and what is missing."*
