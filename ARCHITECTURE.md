# Architecture

```
 Browser (React + Vite)                         FastAPI (Python)
 ───────────────────────                        ─────────────────────────────────────────────────────────
 /cases/new  ── statement ───────────────────▶  POST /cases
 /cases/:id/evidence ── files / pasted text ──▶  POST /cases/:id/evidence[/text]
                                                    │ validate (extension + magic bytes + size)
                                                    │ write-once storage, SHA-256, audit
                                                    ▼  background task, per file
                                                 services/ingest.process
                                                    ├─ IMAGE      → services/ocr (Tesseract, preprocessing, word confidences)
                                                    ├─ AUDIO      → services/audio/stt (faster-whisper, local; translate non-English)
                                                    ├─ DOCUMENT   → services/documents (TXT, PDF text layer, scanned PDF → OCR, DOCX)
                                                    ├─ MESSAGE    → plain text
                                                    └─ STRUCTURED → services/extraction/structured (CSV/JSON history & logs)
                                                    ▼
                                                 services/extraction/entities  (amount, date/time, UTR/ref, UPI ID, phone,
                                                    account, payee, bank, status, channel, URLs, language signals)
                                                 services/extraction/claims    (statements: identity claim, requested action,
                                                    pressure, inducement, listener confirmation)  → extracted_entities
                                                    ▼  when no file is still processing
                                                 services/analysis/run
                                                    ├─ normalization/fuse   mentions → linked transactions + conflicts
                                                    ├─ analysis/timeline    documented / statement / approximate events
                                                    ├─ analysis/context     amount, time, beneficiary, device, session, sequence
                                                    ├─ analysis/ml          Isolation Forest on the customer's own history
                                                    ├─ analysis/findings    supporting / contradictory / contextual / missing
                                                    │                        + completeness checklist
                                                    └─ analysis/summary     deterministic (optional validated LLM rewrite)
 /cases/:id/investigation ◀── GET findings / timeline / graph / evidence
 /cases/:id/report        ◀── POST /cases/:id/report  → services/reporting/pdf (ReportLab)
```

## Principles enforced in code

| Rule | Where |
|---|---|
| Every fact keeps its source | `extracted_entities.evidence_id`, `locator`, `method`, `confidence`; findings and timeline events carry `sources` |
| No invented timestamps | Entities get `occurred_at` only with `time_precision` EXACT / DATE_ONLY / TIME_ONLY / USER_HINT; timeline marks anything not EXACT as approximate and lists undated items separately |
| Conflicts are never silently resolved | `fuse._collect` keeps all values per field; disagreements from different sources become `is_conflict` findings |
| Statements ≠ facts | Audio/chat statements are `CLAIM` entities labelled "Statement extracted from audio"; findings say "not verified" |
| No fraud verdict | Case status is OPEN → UNDER_REVIEW → REPORT_READY → CLOSED; anomalies are "anomalous activity" |
| Honest degradation | OCR/STT/LLM/ML each report *unavailable* with a reason instead of producing output |
| Originals preserved | Stored as `{uuid}.{ext}` (never the user's filename), mode 0440, SHA-256 checked on every download |
| Synthetic data separated | `is_synthetic` on cases and evidence, `DEMO-` case refs, separate list, banners and PDF watermark |
| LLM sees structure, not files | `summary.llm_rewrite` gets findings + evidence codes only; output rejected if it cites a code that doesn't exist |

## Fusion (how sources become one transaction)

1. Each financial evidence item yields *mentions* (amount, references, time, payee …). Items with several
   amounts (statements) yield one mention per line.
2. Two mentions link when: same reference (exact or ≥6-digit suffix) → 0.95; same amount and times ≤10 min
   apart → 0.85; same amount, same date → 0.65; same amount only, and that amount is unique → 0.5.
   Mentions that both carry *different* references never link.
3. Linked mentions are unioned; history rows that match a cluster join it, the rest form the baseline.
4. The disputed transaction is the cluster matching the customer's stated amount, else the best-supported one.

## Completeness score

Weighted checklist (statement 10, amount 10, timestamp 10, reference 10, beneficiary 10, bank confirmation 10,
communication 10, history 10, device 8, auth logs 6, network 6). Present = full weight, partial = half.
The breakdown and formula are shown in the UI and report.

## Data model

`cases`, `evidence_files`, `extracted_entities`, `case_transactions` (DISPUTED / RELATED / HISTORICAL),
`timeline_events`, `findings`, `evidence_relationships`, `investigator_notes`, `reports`, `audit_logs`.
The risk-API module adds `users`, `devices`, `beneficiaries`, `account_links`, `transactions`, `risk_signals`.
All timestamps are stored as UTC through a `UTCDateTime` type (SQLite and PostgreSQL behave the same).

## Frontend

React 19 + TypeScript + Vite + Tailwind v4. UI primitives follow the shadcn/ui pattern (Radix + CVA, written
in `src/components/ui.tsx` because the shadcn registry was not reachable from the build environment).
TanStack Query polls processing status; React Flow draws the evidence graph; Recharts plots the customer's
history against the disputed payment. Files are fetched with the API key and shown via object URLs — there
are no public file URLs.

## Real-time risk module (secondary)

`POST /api/v1/transactions/check` scores a payment in a few milliseconds from rules + a gradient-boosted model
(trained on synthetic data) + NetworkX distance to watch-listed accounts, returns ALLOW / VERIFY / WARN / BLOCK,
and records the user's decision. `POST /cases/from-risk-transaction/{id}` opens a dispute with that record as E1.
