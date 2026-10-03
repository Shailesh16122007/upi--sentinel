# UPI Sentinel

**From complaint to resolution — one evidence trail.**

UPI Sentinel is a case management system for disputed UPI payments, used by three roles on the **same case record**:

| Role | What they do |
|---|---|
| **Customer (victim)** | Describes what happened in their own words, uploads whatever proof they have (screenshots, SMS, chats, call recordings, PDFs), sees a plain-language timeline and findings, submits the case, answers the bank's requests and tracks progress. |
| **Bank investigator** | Works a case queue, sees the reconstructed timeline with every fact linked to the original file, reviews explainable findings, requests more evidence, records outcomes / account actions / reversal status, escalates to cyber crime, generates a versioned investigation report. |
| **Cyber crime officer** | Receives escalated cases, sees the full investigation and the bank's work, related cases and mule clusters, requests information from the bank, moves the case through investigation, pending, resolved or closed, and downloads a structured export for manual entry into official systems. |

```
CUSTOMER ─submit→ BANK ─escalate→ CYBER CRIME ─→ RESOLVED / PENDING / CLOSED
   ↑   ←─ request evidence ─┘  ↑   ←─ request info / return ─┘          │
   └──────────────── every status change is visible to the customer ←───┘
```

UPI Sentinel never decides "fraud / not fraud". It reads the evidence, links it, shows where each fact came from,
what conflicts and what is missing. The decision belongs to the authorised investigator.

---

## Run it

Prerequisites: **Python 3.11+**, **Node 20+**, **PostgreSQL 14+** (or Docker), **Tesseract OCR**, **ffmpeg**.

| OS | Tesseract (+ Hindi/Tamil models) and ffmpeg |
|---|---|
| Ubuntu / Debian | `sudo apt install tesseract-ocr tesseract-ocr-hin tesseract-ocr-tam ffmpeg` |
| macOS | `brew install tesseract tesseract-lang ffmpeg` |
| Windows | Tesseract installer from UB-Mannheim (tick Hindi/Tamil); `winget install ffmpeg`. Add both to PATH. |

```bash
# 1. Database
docker compose up -d postgres            # or use any PostgreSQL; see SENTINEL_DATABASE_URL below

# 2. Backend
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                     # points at the PostgreSQL above
python -m app.tools.fetch_models                         # one-time speech-to-text model download (~150 MB)
uvicorn app.main:app --port 8000                         # API docs at http://127.0.0.1:8000/docs

# 3. Frontend (new terminal)
cd frontend
npm install
npm run dev                                              # open http://127.0.0.1:5173
```

Tables are created and upgraded automatically at startup (additive migration — a V1 database keeps its cases).
Without PostgreSQL, remove `SENTINEL_DATABASE_URL` from `.env` to fall back to a local SQLite file.

### Check your setup

```bash
cd backend && python -m app.tools.check_setup
```
Shows whether Tesseract OCR is found (and where), which languages it has, reads a sample screenshot, and whether
speech-to-text is ready. If Tesseract is installed somewhere unusual, add `SENTINEL_TESSERACT_CMD=C:\path\to\tesseract.exe`
to `backend/.env`.

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Every image says “Text reading (OCR) is not set up…” (older versions: “We could not read this image”) | Tesseract is not installed or not found. Install it (table above), run `check_setup`, restart the backend, then press **Try reading again** on the case. |
| Recordings say “Speech-to-text is not set up…” | Run `python -m app.tools.fetch_models` once with internet. The recording is kept either way. |
| `error while attempting to bind on address ('127.0.0.1', 8000)` | Port 8000 is taken. Start with `--port 8001` and create `frontend/.env.local` with `VITE_API_TARGET=http://127.0.0.1:8001`. |
| Hindi / Tamil text in images not read | Install those Tesseract languages (`tesseract-ocr-hin`, `-tam`, or tick them in the Windows installer). |

### Sign in

The login page lists the **demo accounts** (development / demo deployments only, `SENTINEL_SHOW_DEMO_ACCOUNTS`):

| Account | Email | Password |
|---|---|---|
| Victim demo | victim@demo.upisentinel.in | Victim@2026 |
| Victim demo (second, for permission checks) | victim2@demo.upisentinel.in | Victim@2026 |
| Bank investigator demo — *Demo Bank* | bank@demo.upisentinel.in | Bank@2026 |
| Bank investigator demo — *Sample Bank* (cannot see Demo Bank's cases) | bank2@demo.upisentinel.in | Bank@2026 |
| Cyber crime officer demo | cyber@demo.upisentinel.in | Cyber@2026 |

The role comes from the account. Nobody chooses a role at sign-in.

## Try it with your own evidence

1. Sign in as **Victim demo** → **Report a fraud** → write one or two sentences → continue.
   Leave “Mark as a synthetic demo case” **unticked** for real evidence.
2. Upload your screenshots, paste an SMS, add a call recording or a statement PDF. Nothing needs renaming or reformatting.
3. Watch *Your evidence*: each file shows only the steps that actually completed (“Screenshot read”, “Transaction details found”…).
   Unreadable files say so and are kept; the rest of the case continues.
4. Check *The payment you are reporting* — each value shows where it came from and whether it is confirmed by several files,
   needs review, or was not found. If a file holds several payments you are asked which one you are disputing.
5. **Submit case**, then sign in as **Bank investigator demo** and open the case from *Cases*.

See [DEMO.md](DEMO.md) for the full three-role script and the synthetic “related cases” demonstration.

## Tests

```bash
cd backend && pytest                    # 55 tests: extraction, unknown-file robustness, lifecycle, permissions,
                                        # related cases, reports, export, V1→V2 migration, risk API
SENTINEL_TEST_DATABASE_URL=postgresql+psycopg://sentinel:sentinel@127.0.0.1:5432/sentinel_test pytest   # same suite on PostgreSQL
cd frontend && npx tsc -b && npm run lint && npm run build

# Browser test of the full three-role flow (needs both servers running and Playwright installed):
python -m tests.unknown.make_fixtures /tmp/sentinel-fixtures     # from backend/
node e2e/three_roles.cjs all            # victim → bank → evidence request → victim → bank → cyber crime → victim
#   restart backend + frontend, then:
node e2e/three_roles.cjs after-restart  # the case, its evidence and audit trail survive the restart
node e2e/demo_moment.cjs                # synthetic demo: "This beneficiary appears in 3 other submitted cases"
```

## Configuration (backend `.env`, prefix `SENTINEL_`)

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | SQLite file | PostgreSQL recommended: `postgresql+psycopg://user:pass@host:5432/db` |
| `STORAGE_DIR` | `backend/storage` | Original evidence (write-once, 0440), processing copies, reports |
| `SESSION_HOURS` | 12 | Sign-in session length |
| `SHOW_DEMO_ACCOUNTS` | true | Show demo sign-in details on the login page — set `false` in production |
| `SEED_DEMO` | true | Create the three synthetic background complaints used by the related-case demo |
| `MAX_UPLOAD_MB` / `MAX_AUDIO_MB` | 15 / 40 | Size limits (audio/video use the larger one) |
| `STT_ENGINE` / `WHISPER_MODEL` | `faster-whisper` / `base` | `small` is more accurate for Hindi/English mixed calls; `none` disables |
| `OCR_LANG` | `auto` | English, plus the Indian-script model Tesseract detects on that image |
| `ML_MIN_HISTORY` | 20 | History rows required before the Isolation Forest check runs |
| `API_KEYS` | `demo-psp-key` | Partner keys for the real-time risk API only (`X-API-Key`) |
| `ANTHROPIC_API_KEY` | unset | Optional: LLM rewrites the investigator summary from structured findings only (validated) |

Reset synthetic demo data (development only; real cases are never touched): `python -m app.tools.reset_demo`.

## What is real and what is not

Every number, status, finding and timeline entry is computed from case records and uploaded files. Synthetic demo
cases are labelled **DEMO · synthetic** everywhere (IDs `DEMO-…`, banners, PDF watermark) and are never combined with
real cases in related-case or cluster calculations.

| If… | The app shows |
|---|---|
| A value is not in the evidence | “Not found in submitted evidence” — never a guess |
| OCR read something doubtful (e.g. `₹25000O`, a currency symbol read as `~`, an unknown UPI handle) | The value with **Needs review** and the reason |
| Two files disagree | **Evidence conflict** — both values kept, nothing chosen |
| Only a time is known | “10:32 PM — date unavailable” |
| A screenshot can't be read / a recording can't be transcribed / a PDF is corrupt | The plain-language reason; the original is preserved; other files still process |
| Speech-to-text model not installed | “We could not transcribe this recording” — the customer can type what was said (labelled as typed) |
| A file was uploaded twice | “This file appears to have already been uploaded” (SHA-256 match) |
| Image checks find nothing | “No obvious technical indicators found” + the checks that ran — never “authentic” |

## Known limitations

- **Speech-to-text needs a one-time model download** (`python -m app.tools.fetch_models`). In the build environment the model
  host was blocked, so transcription was verified with a stubbed model and the unavailable path, not with real Whisper output.
  Whisper does not separate speakers; the transcript says so instead of inventing “Speaker 1 / 2”.
- **Extraction is rule-based** (patterns + vocabularies for Indian bank SMS, UPI apps and statements, English / Hinglish /
  Hindi / Tamil signals). Unusual layouts may be missed — the source panel always shows the full extracted text.
  Language detection is a transparent script/marker-word heuristic, not a translation engine.
- **Image manipulation checks are lightweight** (metadata, compression consistency for JPEGs, size). They are indicators only.
- **External actions are prototype actions.** The “File a cyber crime complaint” option links to the official portal; the
  structured export is for manual entry. There is no integration with NCRP/CFCFRMS or any bank.
- **Short references** (e.g. 6-digit) are used for matching within a case but not for cross-case links (too ambiguous).
- Processing runs in-process (FastAPI background tasks, resumed after a restart). For many concurrent users, move it to a worker queue.
- Images are read several ways (contrast, binarised, photo clean-up, faint text; rotation corrected) and the best reading is kept.
  Thumbnail-sized images and partly readable text are kept but every value from them is marked *needs review*. Handwriting
  and pictures without text cannot be read. HEIC needs `pillow-heif` (in requirements). Legacy `.doc` is not supported;
  video frames are sampled for OCR (8 frames), not fully analysed.
- Accounts are seeded demo accounts; there is no self-registration or admin UI for creating staff accounts yet.

## Documentation

[ARCHITECTURE.md](ARCHITECTURE.md) · [API.md](API.md) · [DEMO.md](DEMO.md) · interactive API docs at `/docs`
