from __future__ import annotations

import json
from pathlib import Path

from app.db import FIXTURES_DIR, connect


SCHEMA = """
CREATE TABLE IF NOT EXISTS shifts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  keeper TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT '空闲',
  inflight_limit INTEGER NOT NULL DEFAULT 10 CHECK (inflight_limit > 0)
);
CREATE TABLE IF NOT EXISTS batches (
  id INTEGER PRIMARY KEY,
  biz_key TEXT NOT NULL UNIQUE,
  title TEXT NOT NULL,
  owner_shift_id INTEGER REFERENCES shifts(id),
  status TEXT NOT NULL DEFAULT '在途',
  note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS handovers (
  id INTEGER PRIMARY KEY,
  from_shift_id INTEGER NOT NULL REFERENCES shifts(id),
  to_shift_id INTEGER NOT NULL REFERENCES shifts(id),
  status TEXT NOT NULL,
  batch_count INTEGER NOT NULL DEFAULT 0,
  reason TEXT NOT NULL DEFAULT '',
  started_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS handover_items (
  handover_id INTEGER NOT NULL REFERENCES handovers(id),
  batch_id INTEGER NOT NULL REFERENCES batches(id),
  PRIMARY KEY (handover_id, batch_id)
);
CREATE TABLE IF NOT EXISTS reconcile_reports (
  id INTEGER PRIMARY KEY,
  handover_id INTEGER REFERENCES handovers(id),
  before_count INTEGER NOT NULL,
  after_from_count INTEGER NOT NULL,
  after_to_count INTEGER NOT NULL,
  consistent INTEGER NOT NULL,
  detail_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS capacity_prechecks (
  id INTEGER PRIMARY KEY,
  handover_id INTEGER NOT NULL UNIQUE REFERENCES handovers(id),
  to_shift_id INTEGER NOT NULL REFERENCES shifts(id),
  current_inflight INTEGER NOT NULL,
  item_count INTEGER NOT NULL,
  capacity_limit INTEGER NOT NULL,
  headroom INTEGER NOT NULL,
  decision TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);
"""


def _migrate(conn) -> None:
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(shifts)").fetchall()}
    if "inflight_limit" not in cols:
        conn.execute(
            "ALTER TABLE shifts ADD COLUMN inflight_limit INTEGER NOT NULL DEFAULT 10"
            " CHECK (inflight_limit > 0)"
        )


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)
        n = conn.execute("SELECT COUNT(*) AS c FROM shifts").fetchone()["c"]
        if n:
            return
        seed_path = FIXTURES_DIR / "seed.json"
        data = json.loads(Path(seed_path).read_text(encoding="utf-8"))
        for s in data["shifts"]:
            conn.execute(
                "INSERT INTO shifts(id, name, keeper, status, inflight_limit) VALUES (?, ?, ?, ?, ?)",
                (s["id"], s["name"], s["keeper"], s["status"], s.get("inflight_limit", 10)),
            )
        for b in data["batches"]:
            conn.execute(
                "INSERT INTO batches(id, biz_key, title, owner_shift_id, status, note) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    b["id"],
                    b["biz_key"],
                    b["title"],
                    b["owner_shift_id"],
                    b["status"],
                    b.get("note", ""),
                ),
            )
        conn.commit()
