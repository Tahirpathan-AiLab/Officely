import sqlite3
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Optional
from backend.config import DB_PATH


from contextlib import contextmanager


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_schema(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Tasks table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                source TEXT DEFAULT 'user',
                assigned_agent TEXT DEFAULT 'zed',
                status TEXT DEFAULT 'pending',
                result TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """)

            # Agent Runs table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                status TEXT DEFAULT 'running',
                step_count INTEGER DEFAULT 0,
                summary TEXT DEFAULT '',
                started_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );
            """)

            # Step Logs table (every single thought, tool call, output saved)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS step_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                step_number INTEGER NOT NULL,
                thought TEXT,
                action_type TEXT NOT NULL,
                tool_name TEXT,
                tool_input TEXT,
                tool_output TEXT,
                timestamp TEXT NOT NULL
            );
            """)

            # Approvals / Permissions table (for dangerous actions: ask user)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                agent_name TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                tool_args TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            );
            """)

            # Calendar tasks table (stored in SQLite, not UI timer)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS calendar_events (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                date TEXT NOT NULL,
                time TEXT DEFAULT '',
                who TEXT DEFAULT 'auto',
                kind TEXT DEFAULT 'task',
                note TEXT DEFAULT '',
                plugins TEXT DEFAULT '[]',
                status TEXT DEFAULT 'todo',
                created_at TEXT NOT NULL,
                task_id TEXT
            );
            """)

            # Plugins registry table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS plugins (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                enabled INTEGER DEFAULT 0,
                config TEXT DEFAULT '{}',
                auth_status TEXT DEFAULT 'none'
            );
            """)

            conn.commit()

    # --- Task Methods ---
    def create_task(self, title: str, description: str = "", source: str = "user", assigned_agent: str = "zed") -> Dict[str, Any]:
        task_id = str(uuid.uuid4())
        created_at = now_iso()
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO tasks (id, title, description, source, assigned_agent, status, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                (task_id, title, description, source, assigned_agent, created_at, created_at)
            )
            conn.commit()
        return self.get_task(task_id)

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            return dict(row) if row else None

    def list_tasks(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]

    def update_task_status(self, task_id: str, status: str, result: str = "") -> None:
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE tasks SET status = ?, result = CASE WHEN ? != '' THEN ? ELSE result END, updated_at = ? WHERE id = ?",
                (status, result, result, now_iso(), task_id)
            )
            conn.commit()

    # --- Run Methods ---
    def start_agent_run(self, task_id: str, agent_name: str) -> str:
        run_id = str(uuid.uuid4())
        started_at = now_iso()
        with self.get_connection() as conn:
            conn.execute(
                "INSERT INTO agent_runs (id, task_id, agent_name, status, step_count, started_at) VALUES (?, ?, ?, 'running', 0, ?)",
                (run_id, task_id, agent_name, started_at)
            )
            conn.commit()
        return run_id

    def finish_agent_run(self, run_id: str, status: str = "completed", summary: str = "", step_count: int = 0) -> None:
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE agent_runs SET status = ?, summary = ?, step_count = ?, completed_at = ? WHERE id = ?",
                (status, summary, step_count, now_iso(), run_id)
            )
            conn.commit()

    # --- Step Logging Methods ---
    def log_step(self, run_id: str, task_id: str, agent_name: str, step_number: int,
                 thought: str, action_type: str, tool_name: Optional[str] = None,
                 tool_input: Any = None, tool_output: Any = None) -> None:
        input_str = json.dumps(tool_input) if tool_input is not None else ""
        output_str = json.dumps(tool_output) if tool_output is not None else ""
        timestamp = now_iso()
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO step_logs (run_id, task_id, agent_name, step_number, thought, action_type, tool_name, tool_input, tool_output, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (run_id, task_id, agent_name, step_number, thought, action_type, tool_name, input_str, output_str, timestamp)
            )
            conn.commit()

    def get_run_logs(self, run_id: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM step_logs WHERE run_id = ? ORDER BY step_number ASC", (run_id,)).fetchall()
            return [dict(r) for r in rows]

    # --- Approvals / Security Methods ---
    def request_approval(self, task_id: str, run_id: str, agent_name: str, tool_name: str, tool_args: Dict[str, Any], reason: str) -> str:
        approval_id = str(uuid.uuid4())
        created_at = now_iso()
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO approvals (id, task_id, run_id, agent_name, tool_name, tool_args, reason, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (approval_id, task_id, run_id, agent_name, tool_name, json.dumps(tool_args), reason, created_at)
            )
            conn.commit()
        return approval_id

    def resolve_approval(self, approval_id: str, approved: bool) -> Optional[Dict[str, Any]]:
        status = "approved" if approved else "rejected"
        resolved_at = now_iso()
        with self.get_connection() as conn:
            conn.execute(
                "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ?",
                (status, resolved_at, approval_id)
            )
            conn.commit()
        return self.get_approval(approval_id)

    def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
            if row:
                res = dict(row)
                res["tool_args"] = json.loads(res["tool_args"]) if res["tool_args"] else {}
                return res
            return None

    def list_pending_approvals(self) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute("SELECT * FROM approvals WHERE status = 'pending' ORDER BY created_at DESC").fetchall()
            res = []
            for r in rows:
                item = dict(r)
                item["tool_args"] = json.loads(item["tool_args"]) if item["tool_args"] else {}
                res.append(item)
            return res

    # --- Calendar Methods ---
    def create_calendar_event(self, title: str, date: str, time: str = "", who: str = "auto",
                              kind: str = "task", note: str = "", plugins: List[str] = None) -> Dict[str, Any]:
        event_id = str(uuid.uuid4())
        plugins_json = json.dumps(plugins or [])
        created_at = now_iso()
        with self.get_connection() as conn:
            conn.execute(
                """INSERT INTO calendar_events (id, title, date, time, who, kind, note, plugins, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'todo', ?)""",
                (event_id, title, date, time, who, kind, note, plugins_json, created_at)
            )
            conn.commit()
        return self.get_calendar_event(event_id)

    def get_calendar_event(self, event_id: str) -> Optional[Dict[str, Any]]:
        with self.get_connection() as conn:
            row = conn.execute("SELECT * FROM calendar_events WHERE id = ?", (event_id,)).fetchone()
            if row:
                res = dict(row)
                res["plugins"] = json.loads(res["plugins"]) if res["plugins"] else []
                return res
            return None

    def list_calendar_events(self, date: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            if date:
                rows = conn.execute("SELECT * FROM calendar_events WHERE date = ? ORDER BY time ASC", (date,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM calendar_events ORDER BY date ASC, time ASC").fetchall()
            res = []
            for r in rows:
                item = dict(r)
                item["plugins"] = json.loads(item["plugins"]) if item["plugins"] else []
                res.append(item)
            return res

    def update_calendar_event_status(self, event_id: str, status: str, task_id: Optional[str] = None) -> None:
        with self.get_connection() as conn:
            if task_id:
                conn.execute("UPDATE calendar_events SET status = ?, task_id = ? WHERE id = ?", (status, task_id, event_id))
            else:
                conn.execute("UPDATE calendar_events SET status = ? WHERE id = ?", (status, event_id))
            conn.commit()

    def get_due_calendar_events(self, current_date: str, current_time: str) -> List[Dict[str, Any]]:
        with self.get_connection() as conn:
            rows = conn.execute(
                """SELECT * FROM calendar_events 
                   WHERE status = 'todo' 
                     AND (date < ? OR (date = ? AND (time = '' OR time <= ?)))
                   ORDER BY date ASC, time ASC""",
                (current_date, current_date, current_time)
            ).fetchall()
            res = []
            for r in rows:
                item = dict(r)
                item["plugins"] = json.loads(item["plugins"]) if item["plugins"] else []
                res.append(item)
            return res


db = Database()
