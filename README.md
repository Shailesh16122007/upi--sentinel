# UPI Sentinel

**Reconstruct the transaction. Understand the evidence.**

UPI Sentinel is an evidence-first investigation workstation for disputed UPI transactions. A customer
describes what happened in a sentence or two and uploads whatever they have — screenshots, bank SMS,
call recordings, PDFs, pasted messages. UPI Sentinel reads each item (OCR, speech-to-text, document
parsing), extracts transaction facts with provenance, matches the same transaction across sources,
rebuilds the timeline, flags anomalous activity and conflicts, lists what is missing, and produces a
PDF dispute report. It never decides "fraud / not fraud" — that belongs to the human investigator.

It also contains an optional **real-time risk-check API** (`POST /api/v1/transactions/check`) that a
PSP app or bank can call before authorising a payment; a disputed payment that went through that API
can be opened as a case with the platform's own record attached as evidence.

---

## Run it locally

Prerequisites: **Python 3.11+**, **Node 20+**, **Tesseract OCR**, **ffmpeg** (audio decoding).

| OS | Install Tesseract + ffmpeg |
|---|---|
| Ubuntu / Debian | `sudo apt install tesseract-ocr ffmpeg` |
| macOS | `brew install tesseract ffmpeg` |
| Windows | Tesseract installer from UB-Mannheim; `winget install ffmpeg`. Add both to PATH. |

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m app.tools.fetch_models                         # one-time speech-to-text model download (~150 MB)
uvicorn app.main:app --port 8000                         # API docs at http://127.0.0.1:8000/docs

# 2. Frontend (new terminal)
cd frontend
npm install
cp .env.example .env.local
npm run dev                                              # open http://127.0.0.1:5173
```

Or, on macOS/Linux after installing dependencies once: `./run.sh` starts both.

SQLite is used by default so it runs with no database setup. For PostgreSQL:

```bash
docker compose up -d postgres
# backend/.env
SENTINEL_DATABASE_URL=postgresql+psycopg://sentinel:sentinel@127.0.0.1:5432/sentinel
```

Tables are created on startup (`Base.metadata.create_all`).

## Try it

1. **Load synthetic demo case** on the home page — a fully synthetic dispute (watermarked screenshot,
   bank SMS, call recording + transcript, 60-row history, device/auth log) run through the real pipeline.
2. **Real-evidence test** — *Start a new dispute*, then upload the files in `backend/sample_uploads/`:
   - `upi_screenshot_847291.png` → OCR extracts ₹25,000 · UPI · 03 Oct 2026 · 10:32 PM · Ref 847291
   - paste the text of `bank_sms_847291.txt` → same amount and reference; the two are matched as one transaction
   - `scam_call.wav` → transcribed by Whisper (or shown as *Audio transcription unavailable* if the model is not installed)
   - `bank_sms_conflicting_amount.txt` → ₹20,000 with the same reference: reported as an **amount conflict**, both values kept
   - `transaction_history.csv` (advanced) → enables amount/time/beneficiary anomalies and the Isolation Forest check
3. Open the investigation, click any **E1 / E2…** tag to inspect the original and what was extracted from it,
   add a note, then *Generate report* → *Download report*.

See [DEMO.md](DEMO.md) for a judge-ready script.

## Tests

```bash
cd backend && pytest            # 27 tests: OCR, SMS formats, fusion, conflicts, audio fallback + stubbed Whisper,
                                # history/ML, demo pipeline, graph, PDF contents, audit, validation, risk API
cd frontend && npx tsc -b && npm run lint && npm run build
```

## Configuration (backend `.env`, prefix `SENTINEL_`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite file | Use PostgreSQL in deployment |
| `API_KEYS` | `demo-psp-key` | Comma-separated keys accepted in `X-API-Key` |
| `CORS_ORIGINS` | `http://localhost:5173,…` | Allowed browser origins |
| `STORAGE_DIR` | `backend/storage` | Evidence originals (write-once, 0440) and reports |
| `MAX_UPLOAD_MB` / `MAX_AUDIO_MB` | 15 / 40 | Size limits |
| `STT_ENGINE` | `faster-whisper` | `none` disables speech-to-text |
| `WHISPER_MODEL` | `base` | `small` is more accurate for Hindi/English mixed calls |
| `OCR_LANG` | `eng` | e.g. `eng+hin` if the Hindi traineddata is installed |
| `ML_MIN_HISTORY` | 20 | History rows required before Isolation Forest runs |
| `ANTHROPIC_API_KEY` | unset | Optional: LLM rewrites the summary from structured findings only |

Frontend `.env.local`: `VITE_API_TARGET` (proxy target) and `VITE_API_KEY`.

## What is real and what is not

Everything listed in the UI is computed from the uploaded files. Nothing is hard-coded per case.
When a capability is missing the app says so and keeps going:

| If… | The app shows |
|---|---|
| OCR can't read an image reliably | "Could not reliably extract text from this image." — no values invented |
| Speech-to-text model not installed | "Audio transcription unavailable" — recording kept; a person may attach a transcript, labelled *provided by user* |
| No LLM key | Deterministic summary (labelled) |
| < 20 history rows | "ML analysis unavailable — insufficient historical transaction data" |

## Known limitations

- **Authentication is an API key** shared by the frontend (fine for a local demo, not for production —
  add per-user login and roles before real use).
- **Speech-to-text** needs a one-time model download; in this repo's CI/sandbox it was verified with a
  stubbed model and the unavailable path, not with real Whisper inference.
- **OCR** is tuned for English phone screenshots. Handwriting, very low-resolution photos and Devanagari
  text need `OCR_LANG=eng+hin` and may still be weak. The ₹ sign is often read as `¥`/`%`; this is
  handled and flagged in the extracted value.
- **Extraction is rule-based** (regex + vocabularies) for Indian bank SMS/UPI formats. Unusual formats may be missed —
  the source panel always shows the full extracted text so an investigator can check.
- **Transaction matching** links sources by reference number, or by the same amount within 10 minutes.
  Two different payments of the same amount at nearly the same time without references could be merged.
- **Timeline** uses only times written in the evidence or entered by the user; audio statements are placed in time
  only if the user said when the call started.
- Processing runs in-process (FastAPI background tasks). For many concurrent users, move it to a worker queue.
- DOCX is supported; legacy `.doc`, HEIC images and video/screen recordings are not.

## Documentation

[ARCHITECTURE.md](ARCHITECTURE.md) · [API.md](API.md) · [DEMO.md](DEMO.md) · interactive API docs at `/docs`
