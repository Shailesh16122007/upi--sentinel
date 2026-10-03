"""Investigation summary. Every sentence carries the evidence codes it relies on.

Deterministic by default. If an LLM key is configured, the model receives ONLY the structured findings
(no raw files) and must return sentences that cite existing evidence codes; anything else is rejected
and the deterministic summary is used.
"""
from __future__ import annotations

import json
import logging
import re

import httpx
from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.services.analysis.timeline import label as tlabel

log = logging.getLogger("sentinel.summary")


class Sentence(BaseModel):
    text: str
    sources: list[str]


class Summary(BaseModel):
    sentences: list[Sentence]


def _codes(ids, evidence):
    return [evidence[i]["code"] for i in dict.fromkeys(ids) if i in evidence]


def deterministic(case: dict, disputed, evidence: dict, findings: list[dict], comp: dict, ml: dict) -> list[dict]:
    s: list[dict] = []
    d = disputed
    if d:
        when = tlabel(d.occurred_at, d.precision) if d.occurred_at else "a time not stated in the evidence"
        approx = "" if d.precision == "EXACT" else "approximately "
        amt = f"₹{d.amount:,.0f}" if d.amount else "an amount not established"
        to = f" to {d.beneficiary_vpa or d.beneficiary}" if (d.beneficiary_vpa or d.beneficiary) else ""
        s.append({"text": f"The available evidence shows a disputed {amt} {d.channel or ''} transaction{to} at {approx}{when}.".replace("  ", " "),
                  "sources": _codes(d.sources, evidence)})
        s.append({"text": f"Transaction reference {d.reference} was found." if d.reference else
                  "Transaction reference: not available in submitted evidence.",
                  "sources": _codes([x["evidence_id"] for x in d.fields.get("reference", [])], evidence)})
    else:
        s.append({"text": "No transaction could be identified from the submitted evidence.", "sources": []})

    def pick(cat=None, code_prefix=None, anomaly=None, conflict=None):
        return [f for f in findings if (cat is None or f["category"] == cat)
                and (code_prefix is None or f["code"].startswith(code_prefix))
                and (anomaly is None or f["is_anomaly"] == anomaly) and (conflict is None or f["is_conflict"] == conflict)]

    bank = pick(code_prefix="BANK_CONFIRMS")
    if bank:
        s.append({"text": "A bank message confirms the debit.", "sources": [x["label"] for x in bank[0]["sources"]]})
    anomalies = pick(anomaly=True)
    if anomalies:
        s.append({"text": f"{len(anomalies)} anomalous pattern(s) were observed: " + "; ".join(a["title"].lower() for a in anomalies) + ".",
                  "sources": sorted({x["label"] for a in anomalies for x in a["sources"] if "label" in x}, key=_ord)})
    elif d:
        s.append({"text": "No anomalous patterns were identified from the available evidence.", "sources": []})
    stm = [f for f in pick(code_prefix="STATEMENT_") if f["code"] != "STATEMENT_LISTENER_CONFIRMS"]
    if stm:
        evs = sorted({x["label"] for f in stm for x in f["sources"] if "label" in x}, key=_ord)
        s.append({"text": f"{', '.join(evs)} contain statements in which the other party "
                          + "; ".join(sorted({f['title'].split(': ', 1)[-1].replace('Speaker ', '').replace('Caller ', '').replace('Sender ', '') for f in stm}))
                          + ". These are unverified statements, not established facts.", "sources": evs})
    auth = pick(code_prefix="AUTH_EVENT_PRESENT")
    if auth:
        s.append({"text": "An authentication event is recorded for the disputed payment.", "sources": [x["label"] for x in auth[0]["sources"] if "label" in x]})
    conf = pick(conflict=True)
    if conf:
        s.append({"text": f"{len(conf)} evidence conflict(s) require investigator review: " + "; ".join(c["title"].lower() for c in conf) + ".",
                  "sources": sorted({x["label"] for c in conf for x in c["sources"] if "label" in x}, key=_ord)})
    if ml.get("available"):
        s.append({"text": f"The statistical check (Isolation Forest, {ml['history_rows']} historical transactions) rates the payment "
                          f"more unusual than {ml['more_anomalous_than_pct']}% of the customer's past payments.", "sources": []})
    else:
        s.append({"text": f"ML analysis unavailable: {ml.get('reason', 'not run')}", "sources": []})
    missing = [i["label"].lower() for i in comp["items"] if i["status"] == "missing"]
    if missing:
        s.append({"text": "Not available in submitted evidence: " + ", ".join(missing) + ".", "sources": []})
    s.append({"text": f"Evidence completeness is {comp['score']}%. Investigation status: under review — the decision rests with the "
                      "authorised investigator.", "sources": []})
    return s


def _ord(code: str) -> int:
    m = re.match(r"E(\d+)", code)
    return int(m[1]) if m else 0


def llm_rewrite(base: list[dict], evidence: dict, findings: list[dict]) -> list[dict] | None:
    s = get_settings()
    if not s.anthropic_api_key:
        return None
    codes = {e["code"] for e in evidence.values()}
    payload = {"draft_summary": base, "findings": [{k: f[k] for k in ("category", "title", "detail")} | {
        "sources": [x.get("label") for x in f["sources"] if x.get("label")]} for f in findings],
               "evidence": [{"code": e["code"], "type": e["subtype"], "status": e["status"]} for e in evidence.values()]}
    prompt = ("Rewrite the draft into a clear, neutral investigation summary for a bank investigator. Rules: use only facts "
              "in the input; every sentence that states a fact must list the evidence codes it relies on; say 'Not available "
              "in submitted evidence' for gaps; never conclude whether fraud occurred; treat statements from calls/messages "
              "as unverified. Return JSON {\"sentences\":[{\"text\":...,\"sources\":[\"E1\",...]}]} only.\n\n"
              + json.dumps(payload, default=str))
    try:
        r = httpx.post("https://api.anthropic.com/v1/messages", timeout=45,
                       headers={"x-api-key": s.anthropic_api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
                       json={"model": s.anthropic_model, "max_tokens": 1500, "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
        txt = "".join(b.get("text", "") for b in r.json().get("content", []))
        out = Summary.model_validate_json(txt[txt.find("{"): txt.rfind("}") + 1])
    except (httpx.HTTPError, ValidationError, ValueError) as e:
        log.warning("LLM summary rejected: %s", type(e).__name__)
        return None
    sentences = []
    for x in out.sentences:
        if any(c not in codes for c in x.sources):
            return None  # cites evidence that does not exist -> reject whole output
        sentences.append(x.model_dump())
    return sentences or None


def build(case, disputed, evidence, findings, comp, ml) -> tuple[list[dict], str]:
    base = deterministic(case, disputed, evidence, findings, comp, ml)
    llm = llm_rewrite(base, evidence, findings)
    if llm:
        return llm, f"llm:{get_settings().anthropic_model} (validated against evidence codes)"
    return base, "deterministic"
