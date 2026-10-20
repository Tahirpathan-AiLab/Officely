from typing import Optional, List
from backend.memory.db import db
from backend.tools.registry import registry, PermissionLevel, wrap_untrusted_data


@registry.register(
    name="list_calendar_events",
    description="List scheduled calendar events and tasks.",
    parameters={"date": "optional YYYY-MM-DD date string"},
    permission_level=PermissionLevel.AUTO
)
def list_calendar_events(date: Optional[str] = None) -> str:
    events = db.list_calendar_events(date=date)
    if not events:
        return wrap_untrusted_data("No scheduled events found.")
    
    lines = []
    for ev in events:
        lines.append(f"[{ev['status'].upper()}] {ev['date']} {ev.get('time', '')} - {ev['title']} (Assigned: {ev['who']})")
        if ev.get("note"):
            lines.append(f"   Note: {ev['note']}")
    return wrap_untrusted_data("\n".join(lines))


@registry.register(
    name="add_calendar_event",
    description="Add a new automated task or reminder to the RoboNest calendar.",
    parameters={
        "title": "string title of the task",
        "date": "string date in YYYY-MM-DD format",
        "time": "optional string time in HH:MM format",
        "who": "optional assigned agent (auto, zed, evaan, athena, lumi)",
        "note": "optional detailed instruction or note"
    },
    permission_level=PermissionLevel.AUTO
)
def add_calendar_event(title: str, date: str, time: str = "", who: str = "auto", note: str = "") -> str:
    ev = db.create_calendar_event(
        title=title,
        date=date,
        time=time,
        who=who,
        note=note
    )
    return f"Created calendar event ID: {ev['id']} scheduled for {date} {time}"
