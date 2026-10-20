import asyncio
from datetime import datetime, timezone
from typing import Optional, Callable, Dict, Any
from backend.memory.db import db
from backend.agents.zed import zed_orchestrator
from backend.agents.evaan import evaan_agent
from backend.agents.athena import athena_agent
from backend.agents.lumi import lumi_agent


def get_current_date_time():
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%H:%M")
    return date_str, time_str


class BackgroundScheduler:
    """
    Independent Backend Scheduler.
    Runs persistently in the Python backend (separate from UI).
    Picks up scheduled tasks from SQLite whenever due and triggers Zed / agents.
    """

    def __init__(self, check_interval_seconds: int = 15):
        self.check_interval = check_interval_seconds
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self.event_broadcaster: Optional[Callable[[Dict[str, Any]], Any]] = None

    def start(self, broadcaster: Optional[Callable[[Dict[str, Any]], Any]] = None):
        if self._running:
            return
        self.event_broadcaster = broadcaster
        self._running = True
        self._task = asyncio.create_task(self._loop())

    def stop(self):
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _loop(self):
        while self._running:
            try:
                await self.check_and_run_due_jobs()
            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"[Scheduler Error] {e}")
            await asyncio.sleep(self.check_interval)

    async def check_and_run_due_jobs(self):
        cur_date, cur_time = get_current_date_time()
        due_events = db.get_due_calendar_events(cur_date, cur_time)

        for ev in due_events:
            ev_id = ev["id"]
            title = ev["title"]
            who = ev.get("who", "auto").lower()
            kind = ev.get("kind", "task")
            note = ev.get("note", "")

            # Mark as running in SQLite
            db.update_calendar_event_status(ev_id, "running")

            if self.event_broadcaster:
                await self.event_broadcaster({
                    "type": "calendar_pickup",
                    "event_id": ev_id,
                    "title": title,
                    "who": who,
                    "kind": kind
                })

            # Create corresponding task in DB
            task = db.create_task(
                title=title,
                description=note or f"Scheduled calendar {kind}",
                source="calendar",
                assigned_agent=who if who in ["evaan", "athena", "lumi"] else "zed"
            )
            task_id = task["id"]
            db.update_calendar_event_status(ev_id, "running", task_id=task_id)

            # Execute asynchronously in background
            asyncio.create_task(self._execute_job(ev_id, task_id, title, note, kind, who))

    async def _execute_job(self, ev_id: str, task_id: str, title: str, note: str, kind: str, who: str):
        try:
            if kind == "project":
                # Website Project Pipeline
                res = await zed_orchestrator.run_pipeline(
                    task_id=task_id,
                    project_name=title,
                    project_description=note,
                    event_callback=self.event_broadcaster
                )
            elif who == "e" or who == "evaan":
                res = await evaan_agent.execute(task_id, title, context=note, event_callback=self.event_broadcaster)
            elif who == "a" or who == "athena":
                res = await athena_agent.execute(task_id, title, context=note, event_callback=self.event_broadcaster)
            elif who == "l" or who == "lumi":
                res = await lumi_agent.execute(task_id, title, context=note, event_callback=self.event_broadcaster)
            else:
                # Zed decides
                res = await zed_orchestrator.execute(task_id, title, context=note, event_callback=self.event_broadcaster)

            status = "done" if res.get("status") == "completed" else "todo"
            db.update_calendar_event_status(ev_id, status, task_id=task_id)

            if self.event_broadcaster:
                await self.event_broadcaster({
                    "type": "calendar_completed",
                    "event_id": ev_id,
                    "task_id": task_id,
                    "status": status,
                    "result": res.get("result", "") or res.get("summary", "")
                })

        except Exception as e:
            print(f"[Scheduler Job Failed] {e}")
            db.update_calendar_event_status(ev_id, "todo", task_id=task_id)


scheduler = BackgroundScheduler()
