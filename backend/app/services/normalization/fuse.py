"""Evidence normalization and fusion.

Each evidence item yields "transaction mentions" (amount, reference, time, payee ...). Mentions from
different sources are linked when they share a reference number, or the same amount at a matching
time. Linked mentions become one normalized transaction whose every field keeps all observed values
with their sources. Disagreements are reported as conflicts — no value is silently chosen.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from app.services.extraction.entities import IST

REF_TYPES = ("UTR", "UPI_REF", "TXN_ID")
# Items that are proof of a payment by their nature. Anything else (an e-mail, an image of something, a letter)
# yields a transaction only if it also shows a payment happened (a reference, or a debited / successful status).
PAYMENT_PROOF = {"UPI_SCREENSHOT", "BANK_SMS", "BANK_SMS_SCREENSHOT", "PAYMENT_RECEIPT", "BANK_STATEMENT", "SYSTEM_RECORD"}
FIN_SUBTYPES = {"UPI_SCREENSHOT", "BANK_SMS", "BANK_SMS_SCREENSHOT", "PAYMENT_RECEIPT", "BANK_STATEMENT", "SYSTEM_RECORD",
                "MESSAGE", "IMAGE_OTHER", "DOCUMENT_OTHER", "COMPLAINT"}
COMM_SUBTYPES = {"CHAT", "CHAT_SCREENSHOT", "CALL_RECORDING", "CALL_LOG", "EMAIL"}


@dataclass
class Mention:
    key: str
    evidence_id: str
    subtype: str
    amount: tuple[float, str] | None = None  # (value, entity_id)
    direction: str | None = None  # DEBIT | CREDIT
    refs: dict[str, str] = field(default_factory=dict)  # normalized ref -> entity id
    dt: tuple[datetime, str, str] | None = None  # (datetime, precision, entity_id)
    date_only: tuple[date, str] | None = None
    time_only: tuple[time, str] | None = None
    vpas: dict[str, str] = field(default_factory=dict)
    payees: dict[str, str] = field(default_factory=dict)
    status: dict[str, str] = field(default_factory=dict)
    channel: dict[str, str] = field(default_factory=dict)
    account: dict[str, str] = field(default_factory=dict)
    bank: dict[str, str] = field(default_factory=dict)
    device: dict[str, str] = field(default_factory=dict)
    from_history: bool = False


def _amount_entities(ents):
    return [e for e in ents if e["type"] == "AMOUNT" and not e["attrs"].get("balance")]


def mentions_for_evidence(ev: dict, ents: list[dict]) -> list[Mention]:
    if ev["subtype"] in COMM_SUBTYPES or ev["kind"] == "STRUCTURED":
        return []
    amts = _amount_entities(ents)
    distinct = {e["normalized"] for e in amts}
    groups: list[list[dict]]
    if len(distinct) <= 1:
        groups = [ents]
    else:  # several amounts (e.g. statement): one mention per line that carries an amount
        by_line = defaultdict(list)
        for e in ents:
            by_line[e["locator"]].append(e)
        groups = [g for g in by_line.values() if _amount_entities(g)]
    proof = ev["subtype"] in PAYMENT_PROOF or any(
        e["type"] in REF_TYPES and not e["attrs"].get("unlabelled_12_digit") for e in ents) or any(
        e["type"] == "STATUS" and e["normalized"] in ("DEBITED", "SUCCESS") for e in ents)
    if not proof:
        return []  # mentions an amount, but nothing shows a payment was made
    out = []
    for gi, g in enumerate(groups):
        m = Mention(key=f"{ev['id']}:{gi}", evidence_id=ev["id"], subtype=ev["subtype"])
        _fill(m, g)
        if m.amount or m.refs:
            out.append(m)
    return out


def _fill(m: Mention, ents: list[dict]) -> None:
    best_amt = max(_amount_entities(ents), key=lambda e: e["confidence"], default=None)
    if best_amt:
        m.amount = (float(best_amt["normalized"]), best_amt["id"])
        m.direction = best_amt["attrs"].get("direction")
    for e in ents:
        t, n = e["type"], e["normalized"]
        if t in REF_TYPES and n:
            if not e["attrs"].get("unlabelled_12_digit") or not m.refs:
                m.refs.setdefault(n, e["id"])
        elif t == "DATETIME" and e["occurred_at"]:
            rank = {"EXACT": 3, "USER_HINT": 1}.get(e["time_precision"], 0)
            if m.dt is None or rank > {"EXACT": 3, "USER_HINT": 1}.get(m.dt[1], 0):
                m.dt = (e["occurred_at"], e["time_precision"], e["id"])
        elif t == "DATE" and not m.date_only:
            m.date_only = (date.fromisoformat(e["attrs"]["date"]), e["id"])
        elif t == "TIME" and not m.time_only:
            m.time_only = (time.fromisoformat(e["attrs"]["time"]), e["id"])
        elif t == "UPI_ID":
            m.vpas.setdefault(n, e["id"])
        elif t == "PAYEE":
            m.payees.setdefault(e["value"], e["id"])
        elif t == "STATUS":
            m.status.setdefault(n, e["id"])
        elif t == "CHANNEL":
            m.channel.setdefault(n, e["id"])
        elif t == "ACCOUNT":
            m.account.setdefault(n, e["id"])
        elif t == "BANK":
            m.bank.setdefault(e["value"], e["id"])
        elif t == "DEVICE":
            m.device.setdefault(e["value"], e["id"])


def history_mentions(ev: dict, ents: list[dict]) -> list[Mention]:
    out = []
    for e in ents:
        if e["type"] != "HISTORY_TXN":
            continue
        a = e["attrs"]
        m = Mention(key=f"{ev['id']}:{e['id']}", evidence_id=ev["id"], subtype="TXN_HISTORY", from_history=True)
        m.amount = (float(a["amount"]), e["id"])
        if a.get("reference"):
            m.refs[str(a["reference"]).upper()] = e["id"]
        if e["occurred_at"]:
            m.dt = (e["occurred_at"], e["time_precision"], e["id"])
        if a.get("beneficiary"):
            ben = a["beneficiary"]
            (m.vpas if "@" in ben else m.payees)[ben.lower() if "@" in ben else ben] = e["id"]
        if a.get("status"):
            m.status[str(a["status"]).upper()] = e["id"]
        if a.get("device"):
            m.device[str(a["device"])] = e["id"]
        out.append(m)
    return out


def _refs_match(a: dict, b: dict) -> str | None:
    for ra in a:
        for rb in b:
            if ra == rb:
                return ra
            short, long_ = sorted((ra, rb), key=len)
            if len(short) >= 6 and long_.endswith(short):
                return short
    return None


def _when(m: Mention, approx: date | None) -> tuple[datetime | None, str]:
    if m.dt and m.dt[1] == "EXACT":
        return m.dt[0], "EXACT"
    if m.time_only and approx:
        return datetime.combine(approx, m.time_only[0], tzinfo=IST), "TIME_ONLY"
    if m.dt:
        return m.dt[0], m.dt[1]
    if m.date_only:
        return datetime.combine(m.date_only[0], time(12, 0), tzinfo=IST), "DATE_ONLY"
    return None, "NONE"


def link(a: Mention, b: Mention, approx: date | None) -> tuple[float, str] | None:
    if a.evidence_id == b.evidence_id and not (a.from_history or b.from_history):
        return None
    r = _refs_match(a.refs, b.refs)
    if r:
        return 0.95, f"Same reference number {r}"
    if a.refs and b.refs:
        return None  # both carry references and they differ: different transactions
    if not (a.amount and b.amount) or abs(a.amount[0] - b.amount[0]) > 0.5:
        return None
    ta, pa = _when(a, approx)
    tb, pb = _when(b, approx)
    amt = f"₹{a.amount[0]:,.0f}"
    if ta and tb:
        gap = abs((ta - tb).total_seconds()) / 60
        if "DATE_ONLY" in (pa, pb):
            return (0.65, f"Same amount {amt} on the same date") if ta.date() == tb.date() else None
        if gap <= 10:
            return (0.85 if pa == pb == "EXACT" else 0.75), f"Same amount {amt}, times {gap:.0f} min apart"
        return None
    if a.time_only and b.time_only:
        gap = abs(datetime.combine(date.min, a.time_only[0]) - datetime.combine(date.min, b.time_only[0])).total_seconds() / 60
        return ((0.7, f"Same amount {amt}, same time of day") if gap <= 10 else None)
    return 0.5, f"Same amount {amt} (no time or reference to confirm)"


@dataclass
class Fused:
    mentions: list[Mention]
    links: list[tuple[str, str, float, str]]  # (mention a, mention b, conf, basis)
    kind: str = "RELATED"
    fields: dict = field(default_factory=dict)
    conflicts: list[dict] = field(default_factory=list)
    amount: float | None = None
    occurred_at: datetime | None = None
    precision: str = "NONE"
    reference: str | None = None
    beneficiary: str | None = None
    beneficiary_vpa: str | None = None
    status: str | None = None
    channel: str | None = None
    device: str | None = None
    confidence: float = 1.0
    time_of_day: str | None = None  # "22:32" when the evidence states a time but no date
    direction: str | None = None    # CREDIT when every source shows money coming in
    selected: bool = False          # chosen as disputed by a person

    @property
    def sources(self) -> list[str]:
        return list(dict.fromkeys(m.evidence_id for m in self.mentions))


def _collect(cluster: list[Mention], approx: date | None) -> tuple[dict, list[dict]]:
    f: dict[str, list[dict]] = defaultdict(list)
    for m in cluster:
        if m.amount:
            f["amount"].append({"value": m.amount[0], "evidence_id": m.evidence_id, "entity_id": m.amount[1]})
        for r, eid in m.refs.items():
            f["reference"].append({"value": r, "evidence_id": m.evidence_id, "entity_id": eid})
        when, prec = _when(m, approx)
        if when:
            eid = (m.dt[2] if m.dt else (m.time_only or m.date_only)[1])
            f["time"].append({"value": when.isoformat(), "precision": prec, "evidence_id": m.evidence_id, "entity_id": eid})
        elif m.time_only:  # time stated, date unknown: keep the time, never invent a date
            f["time_of_day"].append({"value": m.time_only[0].strftime("%H:%M"), "evidence_id": m.evidence_id,
                                     "entity_id": m.time_only[1]})
        for name, attr in (("beneficiary_vpa", "vpas"), ("beneficiary_name", "payees"), ("status", "status"),
                           ("channel", "channel"), ("account", "account"), ("bank", "bank"), ("device", "device")):
            for v, eid in getattr(m, attr).items():
                f[name].append({"value": v, "evidence_id": m.evidence_id, "entity_id": eid})
    conflicts = []

    def distinct_sources(field_, values):
        by_val = defaultdict(set)
        for x in f[field_]:
            if x["value"] in values:
                by_val[x["value"]].add(x["evidence_id"])
        return by_val

    amts = {x["value"] for x in f["amount"]}
    if len(amts) > 1:
        conflicts.append({"field": "amount", "values": [x for x in f["amount"]]})
    refs = {x["value"] for x in f["reference"]}
    if len(refs) > 1 and not all(any(o.endswith(r) or r.endswith(o) for o in refs if o != r) for r in refs):
        conflicts.append({"field": "reference", "values": [x for x in f["reference"]]})
    exact = [x for x in f["time"] if x["precision"] == "EXACT"]
    if exact:
        ts = sorted(datetime.fromisoformat(x["value"]) for x in exact)
        if (ts[-1] - ts[0]) > timedelta(minutes=5):
            conflicts.append({"field": "time", "values": exact})
    vpas = {x["value"] for x in f["beneficiary_vpa"]}
    if len(vpas) > 1:
        conflicts.append({"field": "beneficiary_vpa", "values": f["beneficiary_vpa"]})
    st = {x["value"] for x in f["status"]} & {"SUCCESS", "FAILED", "PENDING", "REVERSED"}
    if len(st) > 1:
        conflicts.append({"field": "status", "values": [x for x in f["status"] if x["value"] in st]})
    # Only keep conflicts where the disagreeing values come from different evidence items.
    conflicts = [c for c in conflicts if len({x["evidence_id"] for x in c["values"]}) > 1]
    return dict(f), conflicts


def _pick(values: list[dict]):
    """Most-supported value (distinct sources), used for display/sorting only; conflicts are reported separately."""
    if not values:
        return None
    by = defaultdict(set)
    for x in values:
        by[x["value"]].add(x["evidence_id"])
    return max(by.items(), key=lambda kv: (len(kv[1]), str(kv[0])))[0]


def matches_selection(fz: "Fused", sel: dict | None) -> bool:
    """Does this transaction match the one a person marked as disputed? Several attributes, never amount alone
    when a time or reference is available."""
    if not sel:
        return False
    refs = {x["value"] for x in fz.fields.get("reference", [])}
    if sel.get("reference"):
        return any(r == sel["reference"] or r.endswith(sel["reference"]) or sel["reference"].endswith(r) for r in refs)
    if sel.get("amount") is None or fz.amount is None or abs(fz.amount - sel["amount"]) > 0.5:
        return False
    if sel.get("occurred_at") and fz.occurred_at:
        return abs((fz.occurred_at - datetime.fromisoformat(sel["occurred_at"])).total_seconds()) <= 600
    if sel.get("time_of_day") or fz.time_of_day:
        return sel.get("time_of_day") == fz.time_of_day
    return set(sel.get("sources") or []) & set(fz.sources) != set()


def fuse(evidence: list[dict], entities: list[dict], approx: date | None, claimed: float | None,
         selection: dict | None = None) -> list[Fused]:
    by_ev = defaultdict(list)
    for e in entities:
        by_ev[e["evidence_id"]].append(e)
    ms: list[Mention] = []
    hist: list[Mention] = []
    for ev in evidence:
        ms += mentions_for_evidence(ev, by_ev[ev["id"]])
        hist += history_mentions(ev, by_ev[ev["id"]])

    # union-find over evidence mentions
    parent = {m.key: m.key for m in ms}

    def find(k):
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    links = []
    for i, a in enumerate(ms):
        for b in ms[i + 1:]:
            r = link(a, b, approx)
            if r and r[0] >= 0.5:
                # 'amount only' links are only made when that amount is unique among mentions
                if r[0] == 0.5 and sum(1 for m in ms if m.amount and a.amount and abs(m.amount[0] - a.amount[0]) < 0.5) > 2:
                    continue
                links.append((a.key, b.key, r[0], r[1]))
                parent[find(a.key)] = find(b.key)
    clusters = defaultdict(list)
    for m in ms:
        clusters[find(m.key)].append(m)

    fused: list[Fused] = []
    for members in clusters.values():
        keys = {m.key for m in members}
        fl = [l for l in links if l[0] in keys]
        fused.append(Fused(mentions=members, links=fl))

    # history rows that are the same payment as an evidence cluster join that cluster; the rest are baseline history
    leftover_hist = []
    for h in hist:
        target = None
        for fz in fused:
            for m in fz.mentions:
                r = link(h, m, approx)
                if r and r[0] >= 0.75:
                    target = (fz, m, r)
                    break
            if target:
                break
        if target:
            fz, m, r = target
            fz.mentions.append(h)
            fz.links.append((h.key, m.key, r[0], r[1] + " (also present in transaction history)"))
        else:
            leftover_hist.append(h)

    for fz in fused:
        fz.fields, fz.conflicts = _collect(fz.mentions, approx)
        fz.amount = _pick(fz.fields.get("amount", []))
        ref = _pick(fz.fields.get("reference", []))
        fz.reference = str(ref) if ref else None
        times = fz.fields.get("time", [])
        exact = [t for t in times if t["precision"] == "EXACT"]
        chosen = exact or [t for t in times if t["precision"] == "TIME_ONLY"] or [t for t in times if t["precision"] == "USER_HINT"] or times
        if chosen:
            vals = sorted(datetime.fromisoformat(t["value"]) for t in chosen)
            fz.occurred_at, fz.precision = vals[0], chosen[0]["precision"]
        fz.beneficiary_vpa = _pick(fz.fields.get("beneficiary_vpa", []))
        fz.beneficiary = _pick(fz.fields.get("beneficiary_name", []))
        sts = [x for x in fz.fields.get("status", []) if x["value"] in ("SUCCESS", "FAILED", "PENDING", "REVERSED", "DEBITED")]
        fz.status = _pick(sts)
        fz.channel = _pick(fz.fields.get("channel", []))
        fz.device = _pick(fz.fields.get("device", []))
        fz.confidence = min([l[2] for l in fz.links], default=1.0)
        if not fz.occurred_at:
            fz.time_of_day = _pick(fz.fields.get("time_of_day", []))
        dirs = {m.direction for m in fz.mentions if m.direction}
        if dirs == {"CREDIT"}:
            fz.direction = "CREDIT"
            fz.status = fz.status or "CREDITED"

    # choose the disputed transaction: a person's selection first, then the customer's stated amount,
    # then the best-supported transaction
    for fz in fused:
        fz.selected = matches_selection(fz, selection)

    def score(fz: Fused):
        claimed_hit = 1 if (claimed and fz.amount and abs(fz.amount - claimed) < 1) else 0
        not_credit = all(m.direction != "CREDIT" for m in fz.mentions)  # money the customer received is not the loss
        return (fz.selected, claimed_hit, not_credit, len(fz.sources), fz.amount or 0)
    if fused:
        max(fused, key=score).kind = "DISPUTED"

    for h in leftover_hist:
        fz = Fused(mentions=[h], links=[], kind="HISTORICAL")
        fz.fields, _ = _collect([h], approx)
        fz.amount = h.amount[0] if h.amount else None
        fz.occurred_at = h.dt[0] if h.dt else None
        fz.precision = h.dt[1] if h.dt else "NONE"
        fz.reference = next(iter(h.refs), None)
        fz.beneficiary_vpa = next(iter(h.vpas), None)
        fz.beneficiary = next(iter(h.payees), None)
        fz.status = next(iter(h.status), None)
        fz.device = next(iter(h.device), None)
        fused.append(fz)
    return fused
