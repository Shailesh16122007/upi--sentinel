# API

Base path `/api/v1`. Every request needs `X-API-Key`. Full schemas: `http://127.0.0.1:8000/docs`.

## Disputes

| Method | Path | Purpose |
|---|---|---|
| POST | `/cases` | Create a dispute `{statement, approx_date?, claimed_amount?}` |
| GET | `/cases?synthetic=false` | List cases (synthetic demo cases listed separately) |
| GET | `/cases/{id}` | Case with analysis, disputed transaction (fields with per-source values), counts |
| PATCH | `/cases/{id}` | `{status}` — OPEN, UNDER_REVIEW, REPORT_READY, CLOSED |
| POST | `/cases/{id}/evidence` | Multipart `files[]` (+ `channel=message`, `occurred_at`, `note`). 202; processed in background |
| POST | `/cases/{id}/evidence/text` | Pasted message `{text, label?, occurred_at?}` |
| GET | `/cases/{id}/evidence` | Evidence with processing steps, extracted text/transcript and entities |
| GET | `/cases/{id}/evidence/{eid}/file` | Original file (SHA-256 verified before serving) |
| POST | `/cases/{id}/evidence/{eid}/transcript` | Human-provided transcript for an audio item (labelled) |
| POST | `/cases/{id}/process?all=false` | Re-process pending / failed / unavailable items |
| POST | `/cases/{id}/analyze` | Re-run fusion and analysis |
| GET | `/cases/{id}/timeline` | Ordered events with reliability and sources |
| GET | `/cases/{id}/findings` | Supporting / contradictory / contextual / missing, anomaly and conflict flags |
| GET | `/cases/{id}/graph` | Evidence graph nodes (details, sources, related events) and edges |
| GET | `/cases/{id}/history` | Historical transactions used as the baseline |
| GET/POST | `/cases/{id}/notes` | Investigator notes |
| POST | `/cases/{id}/report` | Generate PDF → `{download_url}` |
| GET | `/cases/{id}/reports`, `/reports/{rid}/download` | List / download reports |
| GET | `/cases/{id}/audit` | Audit trail |
| POST | `/cases/{id}/opened` | Record that an investigator opened the case |
| POST | `/demo/load` | Create the synthetic demo case |
| GET | `/system/capabilities` | OCR / speech-to-text / LLM / ML availability |

Example:

```bash
K='X-API-Key: demo-psp-key'
CID=$(curl -s -H "$K" -H 'Content-Type: application/json' -d '{"statement":"Rs 25,000 left my account. I did not make this payment."}' \
      localhost:8000/api/v1/cases | jq -r .id)
curl -s -H "$K" -F files=@backend/sample_uploads/upi_screenshot_847291.png localhost:8000/api/v1/cases/$CID/evidence
curl -s -H "$K" -H 'Content-Type: application/json' -d '{"text":"Your account has been debited Rs.25,000 through UPI. Reference number 847291."}' \
      localhost:8000/api/v1/cases/$CID/evidence/text
curl -s -H "$K" localhost:8000/api/v1/cases/$CID | jq '.disputed | {amount, reference, match_basis}'
```

## Real-time risk API

| Method | Path | Purpose |
|---|---|---|
| POST | `/transactions/check` | Score a payment before authorisation → risk score, level, decision, signals, latency |
| POST | `/transactions/{id}/decision` | `{action: CANCEL \| PROCEED}` after a warning |
| GET | `/transactions`, `/transactions/{id}` | Checked payments |
| POST | `/cases/from-risk-transaction/{id}` | Open a dispute with the platform's record as evidence |
| GET | `/alerts`, `/analytics`, `/network/flagged`, `/config/policy`, `/demo/risk-scenarios` | Monitoring and demo data |

Errors are JSON `{detail: "..."}`; 401 bad key, 404 not found, 409 wrong state, 422 validation / rejected file.
Stack traces are never returned.
