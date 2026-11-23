import json
import sqlite3
import time
from contextlib import closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

MAX_ATTEMPTS = 2


@dataclass(frozen=True)
class Claim:
    task_id: str
    token: str
    parameters: dict
    attempt: int


class TaskStore:
    def __init__(self, path: Path, *, readonly: bool = False):
        self.path = path
        self.readonly = readonly
        if readonly:
            return
        with closing(self.connect()) as db:
            db.executescript("""
                PRAGMA journal_mode = WAL;
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL UNIQUE,
                    parameters TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    lease_token TEXT,
                    lease_until REAL,
                    result TEXT,
                    error TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS task_poll_order ON tasks(status, created_at);
                CREATE TABLE IF NOT EXISTS task_events (
                    id INTEGER PRIMARY KEY,
                    task_id TEXT NOT NULL REFERENCES tasks(id),
                    event TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    at REAL NOT NULL,
                    details TEXT NOT NULL
                );
            """)

    def connect(self):
        target = self.path.resolve().as_uri() + "?mode=ro" if self.readonly else self.path
        db = sqlite3.connect(target, timeout=5, uri=self.readonly)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        return db

    @contextmanager
    def write(self):
        with closing(self.connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            yield db

    @staticmethod
    def event(db, task_id, event, attempt, at, **details):
        db.execute(
            "INSERT INTO task_events(task_id, event, attempt, at, details) VALUES(?,?,?,?,?)",
            (task_id, event, attempt, at, json.dumps(details)),
        )

    def submit(self, run_id: str, material: str, calculation: str, scenario: str) -> str:
        parameters = json.dumps({
            "material": material, "calculation": calculation, "scenario": scenario,
        })
        with self.write() as db:
            existing = db.execute("SELECT id FROM tasks WHERE run_id = ?", (run_id,)).fetchone()
            if existing:
                return existing["id"]
            now = time.time()
            task_id = uuid4().hex
            db.execute(
                """INSERT INTO tasks(id, run_id, parameters, status, created_at, updated_at)
                   VALUES(?, ?, ?, 'queued', ?, ?)""",
                (task_id, run_id, parameters, now, now),
            )
            self.event(db, task_id, "queued", 0, now)
            return task_id

    def claim(self, *, lease_seconds: float = 3, now: float | None = None) -> Claim | None:
        with self.write() as db:
            now = time.time() if now is None else now
            expired = db.execute(
                """SELECT id, attempts FROM tasks
                   WHERE status = 'running' AND lease_until <= ?""", (now,),
            ).fetchall()
            for row in expired:
                self.record_failure(db, row["id"], row["attempts"], now, "Worker lease expired")
            row = db.execute(
                """SELECT id, parameters, attempts FROM tasks
                   WHERE status = 'queued' ORDER BY created_at LIMIT 1"""
            ).fetchone()
            if row is None:
                return None
            attempt = row["attempts"] + 1
            token = uuid4().hex
            db.execute(
                """UPDATE tasks SET status = 'running', attempts = ?, lease_token = ?,
                   lease_until = ?, updated_at = ? WHERE id = ?""",
                (attempt, token, now + lease_seconds, now, row["id"]),
            )
            self.event(db, row["id"], "started", attempt, now)
            return Claim(row["id"], token, json.loads(row["parameters"]), attempt)

    def finish(self, claim: Claim, *, result: dict | None = None, error: str | None = None,
               retryable: bool = True, elapsed_ms: float | None = None) -> bool:
        with self.write() as db:
            valid = db.execute(
                "SELECT 1 FROM tasks WHERE id = ? AND status = 'running' AND lease_token = ?",
                (claim.task_id, claim.token),
            ).fetchone()
            if valid is None:
                return False
            now = time.time()
            if error is not None:
                self.record_failure(
                    db, claim.task_id, claim.attempt, now, error, retryable, elapsed_ms,
                )
            else:
                db.execute(
                    """UPDATE tasks SET status = 'succeeded', result = ?, error = NULL,
                       lease_token = NULL, lease_until = NULL, updated_at = ? WHERE id = ?""",
                    (json.dumps(result), now, claim.task_id),
                )
                self.event(db, claim.task_id, "succeeded", claim.attempt, now,
                           elapsed_ms=elapsed_ms)
            return True

    def record_failure(self, db, task_id, attempt, now, error, retryable=True, elapsed_ms=None):
        retry = retryable and attempt < MAX_ATTEMPTS
        db.execute(
            """UPDATE tasks SET status = ?, error = ?, lease_token = NULL,
               lease_until = NULL, updated_at = ? WHERE id = ?""",
            ("queued" if retry else "failed", error, now, task_id),
        )
        self.event(db, task_id, "retry_scheduled" if retry else "failed", attempt, now,
                   error=error, elapsed_ms=elapsed_ms)

    def get(self, task_id: str) -> dict | None:
        with closing(self.connect()) as db, db:
            db.execute("BEGIN")
            row = db.execute(
                """SELECT id, status, attempts, parameters, result, error, created_at, updated_at
                   FROM tasks WHERE id = ?""",
                (task_id,),
            ).fetchone()
            if row is None:
                return None
            events = db.execute(
                """SELECT id, event, attempt, at, details FROM task_events
                   WHERE task_id = ? ORDER BY id""", (task_id,),
            ).fetchall()
            task = dict(row)
            task["parameters"] = json.loads(task["parameters"])
            task["result"] = json.loads(task["result"]) if task["result"] is not None else None
            task["events"] = [
                {**dict(event), "details": json.loads(event["details"])} for event in events
            ]
            return task
