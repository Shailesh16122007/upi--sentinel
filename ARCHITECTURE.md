# Architecture

```
 Browser (React + Vite)                FastAPI (Python)                                   PostgreSQL
 ─────────────────────                 ───────────────────────────────────────────────     ──────────
 /login            ── sign in ───────▶ api/auth      accounts, roles, sessions (token stored hashed)
 /my/*  (customer)                     api/cases     cases, evidence, timeline, findings, reports   ─┐
 /bank/* (bank)    ── Bearer token ──▶ api/workflow  submit, transitions, dispositions, requests,    │ every
 /cyber/* (cyber)                                    notifications, customer view                    │ endpoint:
                                       api/intel     dashboards, related cases, clusters, network,   │ permissions
                                                     export, audit                                    ─┘ .require_view
                                                          │
            upload ─▶ ingest.store: validate type + magic bytes + size → SHA-256 → duplicate check →
                      write-once original (0440) → EvidenceHash record → audit
                    ─▶ background: ingest.process on a WORKING COPY (original never opened for processing)
                         IMAGE   OCR (Tesseract; English + script-detected Indian model) + image indicators
                         AUDIO   faster-whisper (original language kept; English translation for extraction)
                         VIDEO   audio transcription + OCR of sampled frames
                         DOCUMENT PDF text / scanned-PDF OCR / DOCX / TXT / EML
                         STRUCTURED CSV / JSON bank exports
                       → extraction/entities (amount + validation, date/time, UTR/ref incl. split lines, UPI ID +
                         handle check, phone, e-mail, account, payee, bank, status, debit/credit/balance)
                       → extraction/claims (statements as claims: “Caller claimed to represent a bank”)
                       → extraction/lexicon + language (English/Hinglish/Hindi/Tamil signals; detected language)
                    ─▶ analysis/run (whenever no file is still processing):
                         normalization/fuse   mentions → transactions, cross-source matching, conflicts,
                                              persisted “which payment is disputed” selection
                         analysis/timeline    plain-language + investigator text, source kinds, no invented dates
                         analysis/context, ml, findings, modus (multi-signal scam patterns)
                         analysis/explain     why it matters, certainty, key findings, customer view, field states
                         analysis/summary     every sentence cites evidence codes
                    ─▶ crosscase.refresh: identifiers → possible related cases → mule clusters (recomputed)
```

## Case lifecycle (services/lifecycle.py)

```
DRAFT ─submit→ SUBMITTED ─start_review→ BANK_REVIEW ⇄ EVIDENCE_REQUESTED   (customer upload returns it automatically)
                                          │
                                          ├─escalate→ ESCALATED ─accept→ CYBER_REVIEW ⇄ INFO_REQUESTED (bank responds)
                                          │                └─return→ BANK_REVIEW
                                          │           CYBER_REVIEW → UNDER_INVESTIGATION ⇄ PENDING → RESOLVED → CLOSED
                                          └─resolve→ RESOLVED ─close→ CLOSED        (reopen / resume go back)
```

Each transition declares the roles allowed, the states it can start from, whether a note is required, and whether it
applies only while the bank or cyber crime holds the case. `lifecycle.apply` validates, writes a `CaseAction`, an audit line
and the notifications. Bank dispositions (outcome, account action, reversal status) are configurable
`case_status_options` rows per bank and are recorded the same way. The customer sees plain-language labels and
`victim_message` updates only.

## Permissions (services/permissions.py)

| | Can see | Cannot |
|---|---|---|
| Customer | own cases (`owner_id`) — simplified analysis, plain timeline, own reports | other customers' cases (404), findings/notes/graph/audit (403), investigator reports |
| Bank | submitted cases routed to its bank (`bank_org`) | drafts, other banks' cases, cyber-only notes, editing evidence or audit |
| Cyber crime | cases ever escalated | non-escalated cases (summary rows only in related-case lists) |

Checks happen on the server for every request; the UI hiding a button is never the control.

## Principles enforced in code

| Rule | Where |
|---|---|
| Every fact keeps its source | entities carry `evidence_id`, `locator`, `method`, `confidence`; findings/timeline carry sources |
| No invented values | `field_status` NOT_FOUND; time-of-day without a date stays undated; amounts in e-mails/chats are not payments unless the item shows one |
| Doubtful OCR is flagged | `needs_review` on amounts (letters next to digits, odd grouping, missing ₹), unknown UPI handles, unlabelled 12-digit numbers |
| Conflicts are never resolved silently | `fuse._collect`; CONFLICT field state and findings |
| Claims stay claims | CLAIM entities worded “Caller claimed / stated …” |
| One keyword is not a scam category | `modus.classify` needs an anchor + a supporting signal group, from evidence (not only the statement) |
| Originals never modified | write-once file, processing on a copy, SHA-256 re-verified on every read and before processing |
| Human notes are separate | `investigator_notes` (incl. finding reviews) are never touched by re-analysis |
| Synthetic data separated | `is_synthetic` on cases/evidence/identifiers/clusters; `DEMO-` IDs; banners; watermark |
| Reports are versioned | `reports` (case + audience) → `report_versions` with evidence count, status, changes |

## Data model

Existing (extended): `cases` (owner, bank routing, lifecycle timestamps, dispositions, disputed selection), `evidence_files`
(uploader, image indicators, language), `extracted_entities`, `case_transactions`, `timeline_events` (plain text, source kinds),
`findings` (why, certainty), `evidence_relationships`, `investigator_notes` (author, visibility, finding review), `reports`,
`audit_logs` (actor id/role).

New: `roles`, `accounts`, `victim_profiles`, `bank_profiles`, `authority_profiles`, `auth_sessions`, `case_status_options`,
`case_assignments`, `investigations`, `case_actions`, `evidence_requests`, `notifications`, `evidence_hashes`,
`entity_relationships`, `case_relationships`, `mule_clusters`, `report_versions`.
The risk-API module keeps `users`, `devices`, `beneficiaries`, `account_links`, `transactions`, `risk_signals`.

`app/migrate.py` adds missing tables/columns (and widens VARCHARs on PostgreSQL) at startup, so an older database is upgraded in place.

## Frontend

React 19 + TypeScript + Vite + Tailwind v4, TanStack Query, React Flow (evidence graph, mule network), Recharts (history).
`lib/auth.tsx` keeps only the sign-in token in the browser; all case data comes from the API. Navigation, dashboards and
case views are separate per role (`pages/victim/*`, `pages/staff/*`); the investigation components are shared by bank and cyber crime.

## Real-time risk module (secondary, unchanged)

`POST /api/v1/transactions/check` (partner `X-API-Key`) scores a payment before authorisation;
`POST /cases/from-risk-transaction/{id}` opens a dispute with the platform's own record as evidence.
