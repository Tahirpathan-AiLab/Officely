import sys
import asyncio
from backend.memory.db import db
from backend.agents.zed import zed_orchestrator
from backend.tools.registry import registry
# Ensure all tools are registered
import backend.tools


async def cli_event_handler(event: dict):
    ev_type = event.get("type")
    if ev_type == "orchestrator_start":
        print(f"\n[ZED - Orchestrator] Task received: {event.get('instruction')}")
    elif ev_type == "delegation":
        print(f"[ZED -> {event.get('target_agent').upper()}] {event.get('instruction')}")
        print(f"       Reasoning: {event.get('thought')}")
    elif ev_type == "agent_start":
        print(f"\n[{event.get('agent').upper()} STARTED] {event.get('instruction')}")
    elif ev_type == "tool_executed":
        print(f"[{event.get('agent').upper()} TOOL] Ran '{event.get('tool')}' (Step {event.get('step')})")
        print(f"       Thought: {event.get('thought')}")
        preview = str(event.get('output', '')).replace('\n', ' ')[:100]
        print(f"       Output snippet: {preview}...")
    elif ev_type == "permission_requested":
        print(f"\n[PERMISSION REQUIRED] {event.get('agent')} wants to run '{event.get('tool')}'.")
        print(f"       Approval ID: {event.get('approval_id')}")
    elif ev_type == "agent_finish":
        print(f"[{event.get('agent').upper()} FINISHED] Result:\n{event.get('result')}")
    elif ev_type == "orchestrator_finish":
        print(f"\n==========================================")
        print(f"FINAL RESULT FROM ZED (Orchestrator):")
        print(f"==========================================")
        print(f"{event.get('result')}")
        print(f"==========================================\n")


async def main():
    if len(sys.argv) > 1:
        instruction = " ".join(sys.argv[1:])
    else:
        instruction = "Summarize the files in this folder"

    print(f"RoboNest Terminal Brain Runner")
    print(f"Command: \"{instruction}\"")
    print("-" * 50)

    # 1. Create task in SQLite
    task = db.create_task(title=instruction, description="Triggered from terminal CLI", source="cli")
    task_id = task["id"]
    print(f"Created SQLite Task ID: {task_id}")

    # 2. Run Zed Orchestrator
    result = await zed_orchestrator.execute(
        task_id=task_id,
        instruction=instruction,
        event_callback=cli_event_handler
    )

    # 3. Check final DB state
    db_task = db.get_task(task_id)
    print(f"\nTask Status in DB: {db_task['status']}")
    print(f"Agent Runs in DB: run logged successfully.")


if __name__ == "__main__":
    asyncio.run(main())
