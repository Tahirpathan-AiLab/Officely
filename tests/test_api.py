import unittest
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop
from aiohttp import web
from backend.main import create_app
from backend.memory.db import db


class TestApiEndpoints(AioHTTPTestCase):

    async def get_application(self):
        return create_app()

    @unittest_run_loop
    async def test_health_check(self):
        resp = await self.client.request("GET", "/api/health")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["app"], "RoboNest Backend")

    @unittest_run_loop
    async def test_create_and_list_tasks(self):
        # Create a task
        payload = {"title": "API Test Task", "description": "Testing API", "source": "api_test"}
        post_resp = await self.client.request("POST", "/api/tasks", json=payload)
        self.assertEqual(post_resp.status, 200)
        post_data = await post_resp.json()
        self.assertEqual(post_data["status"], "started")
        task_id = post_data["task"]["id"]

        # Get task details
        get_resp = await self.client.request("GET", f"/api/tasks/{task_id}")
        self.assertEqual(get_resp.status, 200)
        get_data = await get_resp.json()
        self.assertEqual(get_data["task"]["title"], "API Test Task")

    @unittest_run_loop
    async def test_calendar_endpoints(self):
        payload = {
            "title": "API Scheduled Event",
            "date": "2026-10-25",
            "time": "14:00",
            "who": "lumi",
            "kind": "task",
            "note": "Scheduled from API"
        }
        resp = await self.client.request("POST", "/api/calendar", json=payload)
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["event"]["title"], "API Scheduled Event")

        # List calendar
        list_resp = await self.client.request("GET", "/api/calendar?date=2026-10-25")
        self.assertEqual(list_resp.status, 200)
        list_data = await list_resp.json()
        self.assertTrue(any(e["title"] == "API Scheduled Event" for e in list_data["events"]))

    @unittest_run_loop
    async def test_tools_list_endpoint(self):
        resp = await self.client.request("GET", "/api/tools")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        tools = data["tools"]
        tool_names = [t["name"] for t in tools]
        self.assertIn("read_file", tool_names)
        self.assertIn("write_file", tool_names)
        self.assertIn("delete_file", tool_names)
        self.assertIn("git_status", tool_names)


    @unittest_run_loop
    async def test_llm_settings_endpoints(self):
        # 1. Get current LLM settings
        get_resp = await self.client.request("GET", "/api/settings/llm")
        self.assertEqual(get_resp.status, 200)
        data = await get_resp.json()
        self.assertIn("provider", data)
        self.assertIn("supported_providers", data)
        self.assertTrue(len(data["supported_providers"]) >= 5)

        # 2. Save new LLM settings with API key
        payload = {
            "provider": "openrouter",
            "api_key": "sk-or-v1-testkey1234567890abcdef",
            "model": "google/gemini-2.0-flash-exp:free",
            "base_url": "https://openrouter.ai/api/v1"
        }
        post_resp = await self.client.request("POST", "/api/settings/llm", json=payload)
        self.assertEqual(post_resp.status, 200)
        post_data = await post_resp.json()
        self.assertTrue(post_data["ok"])
        self.assertEqual(post_data["provider"], "openrouter")

        # 3. Verify settings were updated
        get_resp2 = await self.client.request("GET", "/api/settings/llm")
        data2 = await get_resp2.json()
        self.assertEqual(data2["provider"], "openrouter")
        self.assertTrue(data2["has_api_key"])
        self.assertTrue("••••" in data2["masked_api_key"])


if __name__ == "__main__":
    unittest.main()
