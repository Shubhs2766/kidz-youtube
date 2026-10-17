import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  date TEXT NOT NULL, status TEXT NOT NULL,
  started_at TEXT, finished_at TEXT, script_file TEXT, title TEXT,
  video_id TEXT, video_url TEXT, privacy TEXT, est_cost REAL DEFAULT 0, error TEXT, dry_run INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS scenes(
  run_id INTEGER, idx INTEGER, prompt TEXT, seconds REAL, status TEXT, path TEXT, attempts INTEGER DEFAULT 0, error TEXT,
  PRIMARY KEY(run_id, idx)
);
"""

# Run statuses: running | awaiting_approval | scheduled | published | qa_failed | failed | dry_run_ok
SUCCESS = ("awaiting_approval", "scheduled", "published", "dry_run_ok")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class DB:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self.conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    def start_run(self, date, script_file, dry_run=False) -> int:
        with self.conn() as c:
            cur = c.execute("INSERT INTO runs(date,status,started_at,script_file,dry_run) VALUES(?,?,?,?,?)",
                            (date, "running", now(), script_file, int(dry_run)))
            return cur.lastrowid

    def update_run(self, run_id, **kw):
        if not kw:
            return
        cols = ", ".join(f"{k}=?" for k in kw)
        with self.conn() as c:
            c.execute(f"UPDATE runs SET {cols} WHERE id=?", (*kw.values(), run_id))

    def finish(self, run_id, status, **kw):
        self.update_run(run_id, status=status, finished_at=now(), **kw)

    def latest_run(self, date, include_dry=False):
        q = "SELECT * FROM runs WHERE date=?" + ("" if include_dry else " AND dry_run=0") + " ORDER BY id DESC LIMIT 1"
        with self.conn() as c:
            return c.execute(q, (date,)).fetchone()

    def recent_runs(self, n=14):
        with self.conn() as c:
            return c.execute("SELECT * FROM runs ORDER BY id DESC LIMIT ?", (n,)).fetchall()

    def estimated_cost_for_date(self, date):
        with self.conn() as c:
            row = c.execute("SELECT COALESCE(SUM(est_cost), 0) FROM runs WHERE date=? AND dry_run=0", (date,)).fetchone()
            return float(row[0] or 0)

    def upsert_scene(self, run_id, idx, **kw):
        with self.conn() as c:
            c.execute("INSERT OR IGNORE INTO scenes(run_id, idx) VALUES(?,?)", (run_id, idx))
            cols = ", ".join(f"{k}=?" for k in kw)
            c.execute(f"UPDATE scenes SET {cols} WHERE run_id=? AND idx=?", (*kw.values(), run_id, idx))
