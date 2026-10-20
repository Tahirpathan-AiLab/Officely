import asyncio
import unittest
from datetime import datetime
from backend.memory.db import db
from backend.scheduler.jobs import scheduler


class TestScheduler(unittest.TestCase):

    def test_calendar_event_creation_and_due_detection(self):
        today = datetime.now().strftime("%Y-%m-%d")
        now_time = datetime.now().strftime("%H:%M")

        ev = db.create_calendar_event(
            title="Auto Test Due Event",
            date=today,
            time=now_time,
            who="lumi",
            kind="task",
            note="Test note for scheduler"
        )
        self.assertEqual(ev["status"], "todo")

        due = db.get_due_calendar_events(today, now_time)
        due_ids = [e["id"] for e in due]
        self.assertIn(ev["id"], due_ids)

    def test_scheduler_pickup_job(self):
        async def run_sched_check():
            today = datetime.now().strftime("%Y-%m-%d")
            ev = db.create_calendar_event(
                title="Summarize directory files",
                date=today,
                time="",
                who="auto",
                kind="task"
            )

            picked = []
            async def on_ev(event):
                picked.append(event)

            scheduler.event_broadcaster = on_ev
            await scheduler.check_and_run_due_jobs()
            # wait a small moment for async task to progress
            await asyncio.sleep(0.3)
            return ev["id"], picked

        ev_id, picked = asyncio.run(run_sched_check())
        ev_after = db.get_calendar_event(ev_id)
        # Should be running or done, not todo
        self.assertIn(ev_after["status"], ["running", "done"])


if __name__ == "__main__":
    unittest.main()
