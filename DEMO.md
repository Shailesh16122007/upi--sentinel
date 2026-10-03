# Demo script (≈10 minutes, three roles, one case)

Everything below uses the real pipeline. Files in `backend/demo_evidence/` are **synthetic** (watermarked, fictional
“Demo Bank”). Three synthetic background complaints from other synthetic customers already exist; they share the
beneficiary `rahultraders@ybl`.

## 1. Customer — from four files to one case (Victim demo)
1. Sign in as **Victim demo** → **Report a fraud**.
   “I received a call from someone claiming to be from my bank KYC team. Later ₹25,000 was transferred from my account.”
   Tick **Mark as a synthetic demo case** (because we will upload synthetic files) → Continue.
2. Upload, from `backend/demo_evidence/`: `upi_payment_screenshot.png`, `bank_sms_screenshot.png`, `chat_screenshot.png`
   (Hinglish chat) under *Screenshots*, and `scam_call.wav` under *Audio*.
3. Point at *Your evidence*: steps appear only when they actually complete. Without the speech model the recording honestly says
   “We could not transcribe this recording” — use “Type what was said instead” and paste `scam_call_transcript.txt` (labelled as typed).
4. *The payment you are reporting*: ₹25,000, 01 Oct 2026 10:32 PM, UTR 427613847291, `rahultraders@ybl` — each **Confirmed by 2 sources**.
5. *What happened*: messages from the chat (10:15–10:22 PM), the payment, the bank message — each with “Source: …”.
6. *What we found*: related evidence, statements from the chat in plain words, what is still missing.
7. **Generate my report** → **Submit case** → “Your case has been submitted for review.” and *Where your case is now*.

## 2. Bank — reconstruction, not file-by-file reading (Bank investigator demo)
1. Dashboard: real counts; *Related case alerts* shows `rahultraders@ybl`. Open the new case from **Cases**.
2. **“Related case alert — Beneficiary rahultraders@ybl appears in 3 other submitted cases.”**
3. Overview: key findings, disputed transaction with E-codes and reliability, customer statement (a claim), possible fraud
   pattern (remote access / KYC, with the Hinglish quotes and sources). Click any **E1/E2** tag: the original file, OCR text,
   extracted values, SHA-256 integrity and image checks.
4. Timeline (click an event to open its evidence) · Findings (why it matters, certainty, add your own assessment) ·
   Connections (related cases with amounts and status, cluster total ₹2,75,000 within ~46 h, evidence graph).
5. Case actions → **Request more evidence** → *Bank statement*. (Sign in as the customer: “Action required”; upload a PDF
   statement — the case returns to bank review by itself and the bank is notified.)
6. Record **Account action: Account restricted** → **Escalate to cyber crime** (reason required) → Investigation report → Generate.

## 3. Cyber crime (Cyber crime officer demo)
1. **Escalated** → the same case ID. Connections: the cluster; **Link** a related case (officer decision, recorded).
2. Case actions → **Accept case** → add a note → **Mark under investigation** → **Mark pending** (reason) or **Mark resolved**.
3. Investigation report → cyber crime report + **Cyber crime reporting export** (JSON) — “for manual entry / integration”.
4. Mule network → *Synthetic demo data*: the graph built from the four cases.

## 4. Back to the customer
The case shows the new status, the tracker moves to *Cyber crime review*, and *Case updates* lists each step in plain words.

**Restart test:** stop backend and frontend, start them again, sign in — the case, files, timeline, reports and audit trail are all there.

**Reset synthetic data (dev only):** `cd backend && python -m app.tools.reset_demo`.

Closing line: *“UPI Sentinel doesn't call it fraud. It turns whatever the customer has into one traceable case — and shows
the bank and the police where else that beneficiary has appeared.”*
