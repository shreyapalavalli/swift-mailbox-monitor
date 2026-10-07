"""SQLite storage for processed-email audit rows and action-required SWIFTs."""
import os
import sqlite3
from contextlib import closing, contextmanager
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS processed_messages (
  graph_message_id TEXT PRIMARY KEY, folder TEXT, received_at TEXT, subject TEXT, sender TEXT,
  is_swift INTEGER NOT NULL, reference TEXT, message_type TEXT, category TEXT, action TEXT,
  status TEXT, outcome TEXT NOT NULL,
  completed_steps TEXT NOT NULL DEFAULT '',
  error TEXT, attempts INTEGER NOT NULL DEFAULT 1, processed_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS swift_actions (
  reference TEXT PRIMARY KEY, graph_message_id TEXT NOT NULL, received_at TEXT,
  format TEXT, message_type TEXT, related_reference TEXT, category TEXT NOT NULL,
  status TEXT NOT NULL, priority TEXT NOT NULL, sender_bic TEXT, receiver_bic TEXT,
  currency TEXT, amount TEXT, business_purpose TEXT, narrative TEXT,
  matched_terms TEXT, reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_actions_updated ON swift_actions(updated_at);
CREATE INDEX IF NOT EXISTS ix_processed_at ON processed_messages(processed_at);
"""

PROCESSED_COLS = [
    "graph_message_id", "folder", "received_at", "subject", "sender", "is_swift", "reference",
    "message_type", "category", "action", "status", "outcome", "completed_steps", "error",
    "attempts", "processed_at",
]
ACTION_COLS = [
    "reference", "graph_message_id", "received_at", "format", "message_type", "related_reference",
    "category", "status", "priority", "sender_bic", "receiver_bic", "currency", "amount",
    "business_purpose", "narrative", "matched_terms", "reason", "created_at", "updated_at",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SwiftRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        parent = os.path.dirname(os.path.abspath(db_path))
        os.makedirs(parent, exist_ok=True)
        self.init_schema()

    @contextmanager
    def _conn(self):
        with closing(sqlite3.connect(self.db_path, timeout=30)) as conn:
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            with conn:  # commit / rollback
                yield conn

    def init_schema(self) -> None:
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    def get_processed(self, graph_message_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM processed_messages WHERE graph_message_id = ?", (graph_message_id,)
            ).fetchone()
        return dict(row) if row else None

    def record_processed(self, row: dict) -> None:
        data = {c: row.get(c) for c in PROCESSED_COLS if c != "attempts"}
        data["completed_steps"] = data["completed_steps"] or ""
        data["processed_at"] = data["processed_at"] or _now()
        cols = list(data)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "graph_message_id")
        sql = (
            f"INSERT INTO processed_messages ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' * len(cols))}) "
            f"ON CONFLICT(graph_message_id) DO UPDATE SET {updates}, "
            "attempts = processed_messages.attempts + 1"
        )
        with self._conn() as conn:
            conn.execute(sql, [data[c] for c in cols])

    def upsert_action(self, row: dict) -> None:
        now = _now()
        data = {c: row.get(c) for c in ACTION_COLS}
        data["created_at"] = data["created_at"] or now
        data["updated_at"] = data["updated_at"] or now
        updates = ", ".join(
            f"{c}=excluded.{c}" for c in ACTION_COLS if c not in ("reference", "created_at")
        )
        sql = (
            f"INSERT INTO swift_actions ({', '.join(ACTION_COLS)}) "
            f"VALUES ({', '.join('?' * len(ACTION_COLS))}) "
            f"ON CONFLICT(reference) DO UPDATE SET {updates}"
        )
        with self._conn() as conn:
            conn.execute(sql, [data[c] for c in ACTION_COLS])

    def list_actions(self, status: str | None = None, category: str | None = None,
                     since: str | None = None, limit: int = 200) -> list[dict]:
        where, params = [], []
        if status:
            where.append("status = ?")
            params.append(status)
        if category:
            where.append("category = ?")
            params.append(category)
        if since:
            where.append("updated_at > ?")
            params.append(since)
        sql = "SELECT * FROM swift_actions"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(limit)
        with self._conn() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

    def get_action(self, reference: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM swift_actions WHERE reference = ?", (reference,)
            ).fetchone()
        return dict(row) if row else None

    def update_action_status(self, reference: str, status: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE swift_actions SET status = ?, updated_at = ? WHERE reference = ?",
                (status, _now(), reference),
            )
            return cur.rowcount > 0

    def list_processed(self, limit: int = 100) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM processed_messages ORDER BY processed_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def metrics(self, day: str) -> dict:
        prefix = day + "%"
        with self._conn() as conn:
            one = lambda sql, *p: conn.execute(sql, p).fetchone()[0]  # noqa: E731
            grouped = lambda col: {  # noqa: E731
                r[0]: r[1] for r in conn.execute(
                    f"SELECT {col}, COUNT(*) FROM processed_messages "
                    f"WHERE is_swift = 1 AND processed_at LIKE ? AND {col} IS NOT NULL "
                    f"GROUP BY {col}", (prefix,))
            }
            return {
                "processed_today": one(
                    "SELECT COUNT(*) FROM processed_messages WHERE processed_at LIKE ?", prefix),
                "swift_today": one(
                    "SELECT COUNT(*) FROM processed_messages "
                    "WHERE is_swift = 1 AND processed_at LIKE ?", prefix),
                "by_category_today": grouped("category"),
                "by_status_today": grouped("status"),
                "open_action_required": one(
                    "SELECT COUNT(*) FROM swift_actions WHERE status = 'ACTION_REQUIRED'"),
                "open_priority": one(
                    "SELECT COUNT(*) FROM swift_actions WHERE status = 'PRIORITY'"),
                "failed_open": one(
                    "SELECT COUNT(*) FROM processed_messages WHERE outcome = 'FAILED'"),
                "last_processed_at": one("SELECT MAX(processed_at) FROM processed_messages"),
            }
