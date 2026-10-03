# API

Base path `/api/v1`. People authenticate with `POST /auth/login` and send `Authorization: Bearer <token>`.
The real-time risk API (partner integrations) uses `X-API-Key`. Full schemas: `http://127.0.0.1:8000/docs`.
Errors are JSON `{detail}`: 401 not signed in, 403 role not allowed, 404 not found **or not yours**, 409 not possible in the
current state, 422 validation. Stack traces are never returned.

## Authentication
| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/auth/login` | anyone | `{login, password}` (email or user ID) → `{token, account}` |
| POST | `/auth/logout` · GET `/auth/me` · PATCH `/auth/me/profile` | signed in | Session / profile (profile: customers) |
| GET | `/auth/demo-accounts` | anyone | Demo sign-in details (empty unless `SHOW_DEMO_ACCOUNTS`) |
| GET | `/banks` | signed in | Banks a case can be routed to |

## Cases and evidence
| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/cases` | customer | `{statement, approx_date?, claimed_amount?, synthetic?}` → DRAFT case |
| GET | `/cases` | all | Visible cases. Filters: `status` (codes or groups `new, review, action, escalated, pending, resolved, closed, open, done`), `q`, `amount_min/max`, `date_from/to`, `completeness_min`, `beneficiary`, `synthetic`, `priority` |
| GET | `/search?q=` | bank, cyber | Case ID, UTR / transaction ID, UPI ID, phone, beneficiary, amount, date |
| GET | `/cases/{id}` | all | Role-filtered case (customers get plain-language analysis only) |
| POST | `/cases/{id}/opened` | bank, cyber | Audit "opened"; a bank opening a SUBMITTED case starts review |
| POST | `/cases/{id}/evidence` | owner, bank | Multipart `files[]` → `{accepted, rejected}` (duplicates and unreadable types listed, others accepted) |
| POST | `/cases/{id}/evidence/text` | owner, bank | Pasted message |
| GET | `/cases/{id}/evidence` · `/evidence/{eid}/file` | all with access | Evidence with steps, text, entities, language, image indicators, integrity; original file (SHA-256 verified first) |
| POST | `/cases/{id}/evidence/{eid}/transcript` | owner, bank | Typed transcript for an untranscribed recording (labelled) |
| POST | `/cases/{id}/disputed-transaction` | owner (draft), bank | `{transaction_id}` — which extracted payment is disputed |
| POST | `/cases/{id}/analyze` · `/process` | owner, bank | Re-run analysis / re-process failed items |
| GET | `/cases/{id}/timeline` | all | Customers get plain text + source kinds; investigators also the detailed description |
| GET | `/cases/{id}/findings` · `/graph` · `/history` · `/audit` | bank, cyber | Findings incl. why/certainty/human reviews; evidence graph; history; audit trail |
| GET/POST | `/cases/{id}/notes` | bank, cyber | Notes `{body, visibility?, finding_code?, assessment?}` (cyber notes are cyber-only unless shared) |
| GET | `/cases/{id}/related` | bank, cyber | Possible related cases + clusters for this case |

## Workflow
| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/cases/{id}/submit` | customer | `{bank?}` DRAFT → SUBMITTED, triggers related-case check |
| POST | `/cases/{id}/actions` | bank, cyber | `{action, note?}` — `start_review, escalate, bank_resolve, bank_close, bank_reopen, cyber_accept, cyber_return, cyber_investigate, cyber_pending, cyber_resolve, cyber_close, cyber_resume`; the case response lists `allowed_actions` |
| GET | `/cases/{id}/actions` | all | Action history (customers: plain updates only) |
| GET/POST | `/status-options` | bank | Configurable dispositions (POST adds one for your bank) |
| POST | `/cases/{id}/dispositions` | bank | `{bank_outcome?, account_action?, reversal_status?, priority?, note?}` |
| POST | `/cases/{id}/requests` | bank → customer, cyber → bank | `{items[], message}` |
| GET | `/cases/{id}/requests` · `/requests?status=` | all | Requests for a case / across visible cases |
| POST | `/requests/{rid}/respond` | addressed role | `{note}` — customers usually just upload; the request is fulfilled automatically |
| GET | `/cases/{id}/victim-view` | customer | Case, requests, updates and banks for the customer page |
| GET | `/notifications` · POST `/notifications/read` | all | In-app notifications |

## Reports, export, intelligence
| Method | Path | Who | Purpose |
|---|---|---|---|
| POST | `/cases/{id}/reports` | all | `{audience?}` new version from current state (customer → VICTIM, bank → BANK, cyber → CYBER) |
| GET | `/cases/{id}/reports` · `/reports` · `/report-versions/{vid}/download` | per audience | Versions with `is_current`, evidence count, changes |
| GET | `/cases/{id}/export` · `/export/download` | cyber | Structured export (JSON) for manual entry / integration — not an official submission |
| GET | `/dashboard` | all | Role-specific counts from the database |
| GET | `/network/clusters` · `/network/clusters/{id}` · `/network/graph` | bank, cyber | Mule clusters and graph (`synthetic=true` for demo data) |
| GET | `/related-cases` · POST `/relationships/{rid}` | bank, cyber | Overview; `{status: LINKED | DISMISSED | POSSIBLE}` (linking: cyber only) |
| GET | `/audit/cases` | bank, cyber | Recent audit across visible cases |
| POST | `/demo/load` | demo customers | Synthetic example case through the real pipeline |
| GET | `/system/capabilities` | signed in | OCR / speech-to-text / LLM availability |

## Real-time risk API (`X-API-Key`)
`POST /transactions/check`, `POST /transactions/{id}/decision`, `GET /transactions[/{id}]`, `POST /cases/from-risk-transaction/{id}`,
`GET /alerts`, `/analytics`, `/network/flagged`, `/config/policy`, `/demo/risk-scenarios`.
