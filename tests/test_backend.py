import asyncio
import unittest
from unittest.mock import patch
from pathlib import Path

from backend.config import PROJECT_ROOT
from backend.memory.db import db
from backend.agents.zed import zed_orchestrator
from backend.agents.lumi import lumi_agent
from backend.tools.registry import registry, PermissionLevel
from backend.llm.client import llm_client


class TestRoboNestBackend(unittest.TestCase):

    def test_database_initialization(self):
        task = db.create_task(title="Unit Test Task", description="Testing DB", source="test")
        self.assertIsNotNone(task["id"])
        self.assertEqual(task["status"], "pending")
        
        # Test updating status
        db.update_task_status(task["id"], "completed", result="All good")
        updated = db.get_task(task["id"])
        self.assertEqual(updated["status"], "completed")
        self.assertEqual(updated["result"], "All good")

    def test_permission_level_detection(self):
        delete_tool = registry.get("delete_file")
        self.assertIsNotNone(delete_tool)
        self.assertEqual(delete_tool.permission_level, PermissionLevel.ASK_USER)

        read_tool = registry.get("read_file")
        self.assertIsNotNone(read_tool)
        self.assertEqual(read_tool.permission_level, PermissionLevel.AUTO)

    def test_terminal_agent_tool_pipeline(self):
        async def run_pipeline():
            task = db.create_task(title="Summarize directory files", description="Automated test", source="test")
            events = []
            
            async def on_event(ev):
                events.append(ev)

            # This checks orchestration and tool wiring, not the configured
            # local/remote model connection. Keep it deterministic and offline.
            with patch.object(llm_client, "_call_provider", side_effect=llm_client._mock_response):
                res = await zed_orchestrator.execute(
                    task_id=task["id"],
                    instruction="Summarize the files in this folder",
                    event_callback=on_event
                )
            return res, events

        res, events = asyncio.run(run_pipeline())
        self.assertEqual(res["status"], "completed")
        self.assertTrue(any(e.get("type") == "delegation" for e in events))
        self.assertTrue(any(e.get("type") == "tool_executed" for e in events))

    def test_dangerous_tool_approval_pause(self):
        async def run_dangerous():
            # Test file creation
            test_file = PROJECT_ROOT / "data" / "temp_test_delete.txt"
            test_file.write_text("temporary content for testing delete permission")

            task = db.create_task(title="Delete sensitive file", description="Must trigger permission gate", source="test")
            
            # Direct execution of delete_file via Lumi should trigger waiting_approval
            # We mock Lumi's LLM response to ask for delete_file tool
            class MockLumiLLM:
                async def chat(self, *args, **kwargs):
                    return {
                        "thought": "I need to delete the temporary file per request.",
                        "action": "call_tool",
                        "tool": "delete_file",
                        "args": {"path": "data/temp_test_delete.txt"}
                    }
            
            original_llm = lumi_agent.llm
            lumi_agent.llm = MockLumiLLM()
            try:
                res = await lumi_agent.execute(
                    task_id=task["id"],
                    instruction="Delete the temp test file"
                )
                return res
            finally:
                lumi_agent.llm = original_llm

        res = asyncio.run(run_dangerous())
        self.assertEqual(res["status"], "waiting_approval")
        self.assertEqual(res["tool"], "delete_file")
        
        # Check SQLite approval record
        approval_id = res["approval_id"]
        approval = db.get_approval(approval_id)
        self.assertIsNotNone(approval)
        self.assertEqual(approval["status"], "pending")
        self.assertEqual(approval["tool_name"], "delete_file")

        # Resolve approval
        db.resolve_approval(approval_id, approved=True)
        resolved = db.get_approval(approval_id)
        self.assertEqual(resolved["status"], "approved")


if __name__ == "__main__":
    unittest.main()
