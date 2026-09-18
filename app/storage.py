import json
import sqlite3
from pathlib import Path

from app.schemas import Run, now


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created TEXT, status TEXT, body TEXT)")
        self.db.commit()

    def save(self, run: Run):
        self.db.execute("INSERT OR REPLACE INTO runs VALUES (?,?,?,?)",
                        (run.run_id, run.created_at, run.status, run.model_dump_json()))
        self.db.commit()

    def get(self, run_id: str) -> Run | None:
        row = self.db.execute("SELECT body FROM runs WHERE id=?", (run_id,)).fetchone()
        return Run.model_validate_json(row[0]) if row else None

    def recent(self, limit=30) -> list[dict]:
        rows = self.db.execute("SELECT body FROM runs ORDER BY created DESC LIMIT ?", (limit,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def interrupt_pending(self):
        rows = self.db.execute("SELECT body FROM runs WHERE status IN ('queued','running')").fetchall()
        for (body,) in rows:
            run = Run.model_validate_json(body)
            run.status = "interrupted"
            run.failure_code = "interrupted"
            run.failure_reason = "Application restarted before this run completed. Submit again to retry."
            run.finished_at = now()
            run.event("interrupted", run.failure_reason)
            self.save(run)

    def close(self):
        self.db.close()
