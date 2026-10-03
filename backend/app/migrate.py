"""Additive schema migration.

`create_all` creates missing tables but never alters existing ones. A database created by an earlier
version of UPI Sentinel therefore lacks the V2 columns. This adds any missing column as NULLable
(SQLite and PostgreSQL both support `ALTER TABLE ... ADD COLUMN`). Nothing is dropped or rewritten,
so existing cases and evidence are preserved.
"""
from __future__ import annotations

import logging

from sqlalchemy import String, inspect, text
from sqlalchemy.engine import Engine

from app.db import Base

log = logging.getLogger("sentinel.migrate")

# V1 statuses → V2 lifecycle (V1 cases had no owner and were already being investigated)
LEGACY_STATUS = {"OPEN": "SUBMITTED", "UNDER_REVIEW": "BANK_REVIEW", "REPORT_READY": "BANK_REVIEW"}


def upgrade(engine: Engine) -> list[str]:
    Base.metadata.create_all(engine)
    insp = inspect(engine)
    added = []
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            cols = {c["name"]: c for c in insp.get_columns(table.name)}
            have = set(cols)
            for col in table.columns:
                if col.name in have:
                    old_len = getattr(cols[col.name]["type"], "length", None)
                    new_len = col.type.length if isinstance(col.type, String) else None
                    if engine.dialect.name == "postgresql" and old_len and new_len and new_len > old_len:
                        conn.execute(text(f'ALTER TABLE {table.name} ALTER COLUMN "{col.name}" TYPE VARCHAR({new_len})'))
                        added.append(f"{table.name}.{col.name} (widened to {new_len})")
                    continue
                ddl = col.type.compile(dialect=engine.dialect)
                conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}'))
                added.append(f"{table.name}.{col.name}")
        for old, new in LEGACY_STATUS.items():
            conn.execute(text("UPDATE cases SET status = :new WHERE status = :old"), {"new": new, "old": old})
    if added:
        log.info("Schema upgraded: %s", ", ".join(added))
    return added
