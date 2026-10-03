"""Cross-case intelligence: identifier index, possible related cases, mule clusters.

* Every analysed case publishes its identifiers (beneficiary UPI ID, contact numbers, links, e-mails, account
  numbers given in messages, the transaction reference) as EntityRelationship rows.
* Two submitted cases sharing an identifier become a "Possible related case" (CaseRelationship). A person can
  confirm (LINKED) or dismiss it; that decision survives re-analysis.
* Identifiers shared by 2+ submitted cases form a MuleCluster whose totals are recomputed from the case records.
* Synthetic (demo) and real cases are never mixed in any of these calculations.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from app.models import (Account, Case, CaseRelationship, CaseTransaction, EntityRelationship, EvidenceFile,
                        ExtractedEntity, MuleCluster, VictimProfile)
from app.services import notify

BANK_SUBTYPES = {"BANK_SMS", "BANK_SMS_SCREENSHOT", "BANK_STATEMENT", "TXN_HISTORY", "ACCOUNT_LOG", "SYSTEM_RECORD"}
CLUSTER_ROLES = ("BENEFICIARY", "CONTACT", "MENTIONED")
TYPE_LABEL = {"UPI_ID": "UPI ID", "PHONE": "Phone number", "URL": "Link", "EMAIL": "E-mail", "ACCOUNT": "Bank account",
              "UTR": "Transaction reference"}


def _identifiers(db: Session, case: Case) -> list[dict]:
    d = db.scalar(select(CaseTransaction).where(CaseTransaction.case_id == case.id, CaseTransaction.kind == "DISPUTED"))
    prof = db.get(VictimProfile, case.owner_id) if case.owner_id else None
    own = {x.lower() for x in ((prof and prof.phone and "+91" + prof.phone[-10:]), prof and prof.own_vpa) if x}
    out: dict[tuple, dict] = {}

    def add(t, v, role, ev_ids, amount=None, at=None):
        v = (v or "").strip().lower()
        if not v or v in own:
            return
        k = (t, v)
        if k in out:
            out[k]["evidence_ids"] = list(dict.fromkeys(out[k]["evidence_ids"] + ev_ids))
            if role == "BENEFICIARY":
                out[k]["role"] = role
            return
        out[k] = {"entity_type": t, "value": v, "role": role, "evidence_ids": list(ev_ids), "amount": amount, "occurred_at": at}

    amount = d.amount if d else None
    at = d.occurred_at if d else None
    if d and d.beneficiary_vpa:
        add("UPI_ID", d.beneficiary_vpa, "BENEFICIARY", [v["evidence_id"] for v in d.fields.get("beneficiary_vpa", [])], amount, at)
    if d and d.reference and len(d.reference) >= 10:
        add("UTR", d.reference, "TRANSACTION_REF", [v["evidence_id"] for v in d.fields.get("reference", [])], amount, at)
    evs = {e.id: e for e in db.scalars(select(EvidenceFile).where(EvidenceFile.case_id == case.id))}
    for x in db.scalars(select(ExtractedEntity).where(ExtractedEntity.case_id == case.id,
                                                      ExtractedEntity.type.in_(("PHONE", "URL", "EMAIL", "UPI_ID", "ACCOUNT")))):
        ev = evs.get(x.evidence_id)
        if not ev or (ev.subtype or "") in BANK_SUBTYPES or x.confidence < 0.6:
            continue  # bank messages carry the bank's own numbers and the customer's account
        if x.type == "ACCOUNT" and not (x.normalized or "").isdigit():
            continue  # masked account numbers (XX1234) are too weak to link people
        role = "CONTACT" if x.type in ("PHONE", "URL", "EMAIL") else "MENTIONED"
        add(x.type, x.normalized or x.value, role, [x.evidence_id], amount, at)
    return list(out.values())


def refresh(db: Session, case: Case, notify_changes: bool = True) -> dict:
    old_keys = {(r.entity_type, r.value) for r in db.scalars(select(EntityRelationship).where(EntityRelationship.case_id == case.id))}
    db.execute(delete(EntityRelationship).where(EntityRelationship.case_id == case.id))
    idents = _identifiers(db, case)
    for i in idents:
        db.add(EntityRelationship(case_id=case.id, is_synthetic=case.is_synthetic, **i))
    db.flush()

    # ---- possible related cases (both sides submitted, same synthetic class)
    desired: dict[tuple, dict] = {}
    if case.status != "DRAFT":
        for i in idents:
            others = db.execute(
                select(EntityRelationship, Case).join(Case, Case.id == EntityRelationship.case_id)
                .where(EntityRelationship.entity_type == i["entity_type"], EntityRelationship.value == i["value"],
                       EntityRelationship.case_id != case.id, EntityRelationship.is_synthetic.is_(case.is_synthetic),
                       Case.status != "DRAFT")).all()
            for er, oc in others:
                lbl = TYPE_LABEL.get(i["entity_type"], i["entity_type"])
                basis = (f"Same transaction reference {i['value']} — possibly the same payment reported twice"
                         if i["entity_type"] == "UTR" else f"Both cases contain {lbl.lower()} {i['value']}"
                         + (" as the payment recipient" if i["role"] == er.role == "BENEFICIARY" else ""))
                for a, b in ((case.id, oc.id), (oc.id, case.id)):
                    desired[(a, b, i["entity_type"], i["value"])] = {"basis": basis[:300]}
    existing = db.scalars(select(CaseRelationship).where(
        or_(CaseRelationship.case_id == case.id, CaseRelationship.related_case_id == case.id))).all()
    have = {(r.case_id, r.related_case_id, r.entity_type, r.value): r for r in existing}
    new_pairs = set()
    for k, v in desired.items():
        if k in have:
            have[k].basis = v["basis"]
        else:
            db.add(CaseRelationship(case_id=k[0], related_case_id=k[1], entity_type=k[2], value=k[3], basis=v["basis"]))
            new_pairs.add(k[1] if k[0] == case.id else k[0])
    for k, r in have.items():
        if k not in desired:
            db.delete(r)
    db.flush()

    # ---- clusters for every identifier this case had or has
    keys = old_keys | {(i["entity_type"], i["value"]) for i in idents}
    touched = []
    for t, v in keys:
        if t == "UTR":
            continue
        c = recompute_cluster(db, t, v, case.is_synthetic)
        if c is not None:
            touched.append(c)

    if notify_changes and new_pairs and case.status != "DRAFT":
        n = len({k[1] for k in desired if k[0] == case.id})
        notify.bank(db, case, "RELATED_CASES", f"{case.ref} linked to {n} possible related complaint(s)",
                    "Shared identifiers were found in other submitted cases.")
        if case.escalated_at:
            notify.cyber(db, case, "CLUSTER", f"Related beneficiary cluster detected for {case.ref}")
        for oid in new_pairs:
            oc = db.get(Case, oid)
            if oc and oc.escalated_at:
                notify.cyber(db, oc, "CLUSTER", f"New possible related case for {oc.ref}: {case.ref}")
    db.commit()
    return {"identifiers": len(idents), "related": len({k[1] for k in desired if k[0] == case.id}), "clusters": len(touched)}


def recompute_cluster(db: Session, entity_type: str, value: str, synthetic: bool) -> MuleCluster | None:
    rows = db.execute(select(EntityRelationship, Case).join(Case, Case.id == EntityRelationship.case_id).where(
        EntityRelationship.entity_type == entity_type, EntityRelationship.value == value,
        EntityRelationship.is_synthetic.is_(synthetic), EntityRelationship.role.in_(CLUSTER_ROLES),
        Case.status != "DRAFT")).all()
    by_case: dict[str, tuple] = {}
    for er, c in rows:
        by_case.setdefault(c.id, (er, c))
    cl = db.scalar(select(MuleCluster).where(MuleCluster.entity_type == entity_type, MuleCluster.value == value,
                                             MuleCluster.is_synthetic.is_(synthetic)))
    if len(by_case) < 2:
        if cl is not None:
            db.delete(cl)
        return None
    if cl is None:
        cl = MuleCluster(entity_type=entity_type, value=value, is_synthetic=synthetic)
        db.add(cl)
    amounts = [er.amount for er, _ in by_case.values() if er.amount]
    times = [er.occurred_at or c.submitted_at or c.created_at for er, c in by_case.values()]
    times = [t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in times if t]
    cl.case_ids = sorted(by_case)
    cl.case_count = len(by_case)
    cl.total_amount = float(sum(amounts))
    cl.amount_known_cases = len(amounts)
    cl.first_at, cl.last_at = (min(times), max(times)) if times else (None, None)
    cl.updated_at = datetime.now(timezone.utc)
    return cl


# ------------------------------------------------------------------ read models (role-aware)

def _case_brief(db: Session, c: Case, acc: Account, rel: str | None = None) -> dict:
    from app.services.lifecycle import label
    from app.services.permissions import can_view
    d = db.scalar(select(CaseTransaction).where(CaseTransaction.case_id == c.id, CaseTransaction.kind == "DISPUTED"))
    visible = can_view(acc, c)
    owner = db.get(Account, c.owner_id) if c.owner_id else None
    same_bank = acc.role == "CYBER" or c.bank_org == acc.org
    return {"id": c.id, "ref": c.ref, "amount": d.amount if d else c.claimed_amount, "amount_source": "evidence" if d and d.amount else "customer",
            "occurred_at": d.occurred_at if d else None, "submitted_at": c.submitted_at, "status": c.status,
            "status_label": label(c.status), "bank": c.bank_org, "is_synthetic": c.is_synthetic, "can_open": visible,
            "victim": (f"{owner.name} · {owner.user_code}" if owner else "—") if same_bank else "Customer of another bank",
            "relationship": rel}


def related_for(db: Session, case: Case, acc: Account) -> list[dict]:
    rows = db.scalars(select(CaseRelationship).where(CaseRelationship.case_id == case.id)
                      .order_by(CaseRelationship.created_at)).all()
    grouped: dict[str, dict] = {}
    for r in rows:
        oc = db.get(Case, r.related_case_id)
        if oc is None:
            continue
        g = grouped.setdefault(oc.id, {**_case_brief(db, oc, acc), "links": []})
        g["links"].append({"id": r.id, "entity_type": r.entity_type, "type_label": TYPE_LABEL.get(r.entity_type, r.entity_type),
                           "value": r.value, "basis": r.basis, "status": r.status, "reviewed_at": r.reviewed_at})
    return list(grouped.values())


def clusters_for(db: Session, acc: Account, synthetic: bool | None = None, case_id: str | None = None) -> list[dict]:
    q = select(MuleCluster).order_by(MuleCluster.case_count.desc(), MuleCluster.total_amount.desc())
    if synthetic is not None:
        q = q.where(MuleCluster.is_synthetic.is_(synthetic))
    out = []
    for cl in db.scalars(q):
        if case_id and case_id not in cl.case_ids:
            continue
        cases = [db.get(Case, i) for i in cl.case_ids]
        cases = [c for c in cases if c]
        if acc.role == "BANK" and not any(c.bank_org == acc.org for c in cases):
            continue  # banks see clusters that touch their own customers
        out.append(cluster_out(db, cl, cases, acc))
    return out


def cluster_out(db: Session, cl: MuleCluster, cases: list[Case], acc: Account) -> dict:
    window = None
    if cl.first_at and cl.last_at:
        window = round((cl.last_at - cl.first_at).total_seconds() / 3600, 1)
    rels = {er.case_id: er for er in db.scalars(select(EntityRelationship).where(
        EntityRelationship.entity_type == cl.entity_type, EntityRelationship.value == cl.value,
        EntityRelationship.case_id.in_(cl.case_ids)))}
    return {"id": cl.id, "entity_type": cl.entity_type, "type_label": TYPE_LABEL.get(cl.entity_type, cl.entity_type),
            "value": cl.value, "is_synthetic": cl.is_synthetic, "case_count": cl.case_count, "total_amount": cl.total_amount,
            "amount_known_cases": cl.amount_known_cases, "first_at": cl.first_at, "last_at": cl.last_at, "window_hours": window,
            "updated_at": cl.updated_at, "label": "Related transaction cluster detected",
            "cases": [_case_brief(db, c, acc, rels[c.id].role if c.id in rels else None) for c in cases]}


def network_graph(db: Session, acc: Account, synthetic: bool = False, cluster_id: str | None = None) -> dict:
    cls = clusters_for(db, acc, synthetic)
    if cluster_id:
        cls = [c for c in cls if c["id"] == cluster_id]
    nodes: dict[str, dict] = {}
    edges = []
    for cl in cls:
        nid = f"id:{cl['entity_type']}:{cl['value']}"
        nodes[nid] = {"id": nid, "kind": "IDENTIFIER", "label": cl["value"], "type_label": cl["type_label"],
                      "case_count": cl["case_count"], "total_amount": cl["total_amount"], "cluster_id": cl["id"]}
        for c in cl["cases"]:
            cid = f"case:{c['id']}"
            nodes.setdefault(cid, {"id": cid, "kind": "CASE", "label": c["ref"], "victim": c["victim"], "amount": c["amount"],
                                   "status_label": c["status_label"], "case_id": c["id"], "can_open": c["can_open"],
                                   "bank": c["bank"]})
            edges.append({"source": cid, "target": nid, "amount": c["amount"], "role": c["relationship"]})
    return {"nodes": list(nodes.values()), "edges": edges, "clusters": len(cls)}


def rebuild_all(db: Session) -> None:
    """Recompute every case's identifiers and relationships (used after demo seeding / maintenance)."""
    for c in db.scalars(select(Case)):
        refresh(db, c, notify_changes=False)


def summary_counts(db: Session, case_ids: list[str]) -> dict[str, int]:
    out = defaultdict(int)
    if not case_ids:
        return out
    for r in db.scalars(select(CaseRelationship).where(CaseRelationship.case_id.in_(case_ids),
                                                       CaseRelationship.status != "DISMISSED")):
        out[r.case_id] += 1
    return out
