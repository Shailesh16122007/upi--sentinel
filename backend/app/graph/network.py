"""Account / device / beneficiary relationship graph (NetworkX, in-memory).

Built once from the DB at startup and updated incrementally when transactions complete,
so the real-time path only does a bounded BFS — no DB scans.
"""
import threading

import networkx as nx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AccountLink, Beneficiary, Transaction, User

HOP_SCORE = {0: 1.0, 1: 0.85, 2: 0.65, 3: 0.45}
MAX_HOPS = 3


class FraudGraph:
    def __init__(self) -> None:
        self.g = nx.DiGraph()
        self._lock = threading.Lock()

    # ---- building ----
    def rebuild(self, db: Session) -> None:
        g = nx.DiGraph()
        for b in db.scalars(select(Beneficiary)):
            g.add_node(f"vpa:{b.vpa}", kind="AEPS_TERMINAL" if b.kind == "AEPS_TERMINAL" else "UPI_ID",
                       label=b.name, flagged=b.flagged_fraud, reason=b.flag_reason)
        for u in db.scalars(select(User)):
            g.add_node(f"user:{u.ref}", kind="USER", label=u.name, flagged=False)
            if u.phone:
                g.add_node(f"phone:{u.phone}", kind="PHONE", label=u.phone, flagged=False)
                g.add_edge(f"user:{u.ref}", f"phone:{u.phone}", rel="LINKED_TO")
        for link in db.scalars(select(AccountLink)):
            for n in (link.src_vpa, link.dst_vpa):
                g.add_node(f"vpa:{n}", kind=g.nodes.get(f"vpa:{n}", {}).get("kind", "UPI_ID"),
                           label=g.nodes.get(f"vpa:{n}", {}).get("label", n),
                           flagged=g.nodes.get(f"vpa:{n}", {}).get("flagged", False))
            g.add_edge(f"vpa:{link.src_vpa}", f"vpa:{link.dst_vpa}", rel=link.relation)
        rows = db.execute(
            select(User.ref, Beneficiary.vpa, Transaction.device_ref)
            .join(User, Transaction.user_id == User.id)
            .join(Beneficiary, Transaction.beneficiary_id == Beneficiary.id)
            .where(Transaction.status == "COMPLETED")
        ).all()
        for user_ref, vpa, device in rows:
            self._add_txn(g, user_ref, vpa, device)
        with self._lock:
            self.g = g

    @staticmethod
    def _add_txn(g: nx.DiGraph, user_ref: str, vpa: str, device: str | None) -> None:
        u, b = f"user:{user_ref}", f"vpa:{vpa}"
        g.add_node(u, kind="USER", label=g.nodes.get(u, {}).get("label", user_ref), flagged=False) if u not in g else None
        if b not in g:
            g.add_node(b, kind="UPI_ID", label=vpa, flagged=False)
        if g.has_edge(u, b):
            g[u][b]["count"] = g[u][b].get("count", 1) + 1
        else:
            g.add_edge(u, b, rel="SENT_TO", count=1)
        if device:
            d = f"device:{device}"
            if d not in g:
                g.add_node(d, kind="DEVICE", label=device, flagged=False)
            g.add_edge(u, d, rel="USED_DEVICE")

    def record_completed(self, user_ref: str, vpa: str, device: str | None) -> None:
        with self._lock:
            self._add_txn(self.g, user_ref, vpa, device)

    # ---- scoring (hot path) ----
    def beneficiary_risk(self, vpa: str) -> tuple[float, list[str]]:
        """Score by shortest downstream path from the beneficiary to a flagged node.

        Returns (score 0..1, path of node ids) — path is empty if nothing within MAX_HOPS.
        """
        node = f"vpa:{vpa}"
        g = self.g
        if node not in g:
            return 0.0, []
        if g.nodes[node].get("flagged"):
            return HOP_SCORE[0], [node]
        lengths, paths = nx.single_source_shortest_path_length(g, node, cutoff=MAX_HOPS), None
        best: tuple[int, str] | None = None
        for n, d in lengths.items():
            if d > 0 and g.nodes[n].get("flagged") and (best is None or d < best[0]):
                best = (d, n)
        if best is None:
            return 0.0, []
        paths = nx.shortest_path(g, node, best[1])
        return HOP_SCORE[best[0]], paths

    def fan_in(self, vpa: str) -> int:
        node = f"vpa:{vpa}"
        if node not in self.g:
            return 0
        return sum(1 for p in self.g.predecessors(node) if self.g.nodes[p].get("kind") == "USER")

    # ---- export for UI ----
    def subgraph(self, seeds: list[str], radius: int = 3) -> dict:
        g = self.g.to_undirected(as_view=True)
        keep: set[str] = set()
        for s in seeds:
            if s in g:
                keep |= set(nx.single_source_shortest_path_length(g, s, cutoff=radius))
        sub = self.g.subgraph(keep)
        flagged = {n for n, a in sub.nodes(data=True) if a.get("flagged")}
        suspicious: set[str] = set(flagged)
        for s in seeds:
            for f in flagged:
                try:
                    suspicious |= set(nx.shortest_path(sub, s, f))
                except (nx.NetworkXNoPath, nx.NodeNotFound):
                    pass
        nodes = [{"id": n, "kind": a.get("kind"), "label": a.get("label", n), "flagged": bool(a.get("flagged")),
                  "reason": a.get("reason"), "suspicious": n in suspicious, "seed": n in seeds}
                 for n, a in sub.nodes(data=True)]
        edges = [{"source": u, "target": v, "rel": a.get("rel"), "count": a.get("count", 1),
                  "suspicious": u in suspicious and v in suspicious}
                 for u, v, a in sub.edges(data=True)]
        return {"nodes": nodes, "edges": edges}


graph = FraudGraph()
