import json
import asyncio
import socket
import sys
from pathlib import Path
from typing import Set, Optional
import httpx
from aiohttp import web, WSMsgType

from backend.config import settings, PROJECT_ROOT
from backend.memory.db import db
from backend.agents.zed import zed_orchestrator
from backend.scheduler.jobs import scheduler
from backend.tools.registry import registry
from backend.security.secrets import SecretManager
from backend.llm.client import llm_client, get_provider_api_key, PROVIDER_KEY_SECRETS, _clean_key

routes = web.RouteTableDef()
connected_websockets: Set[web.WebSocketResponse] = set()


async def broadcast_event(event: dict):
    """Broadcast an event to all connected UI WebSocket clients."""
    if not connected_websockets:
        return
    payload = json.dumps(event)
    stale = []
    for ws in list(connected_websockets):
        try:
            if not ws.closed:
                await ws.send_str(payload)
            else:
                stale.append(ws)
        except Exception:
            stale.append(ws)
    for ws in stale:
        connected_websockets.discard(ws)


# --- CORS Middleware ---
@web.middleware
async def cors_middleware(request, handler):
    if request.method == "OPTIONS":
        response = web.Response(status=200)
    else:
        try:
            response = await handler(request)
        except web.HTTPException as ex:
            response = ex
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return response


# --- WebSocket Endpoint ---
@routes.get("/ws")
async def websocket_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    connected_websockets.add(ws)

    # Send initial welcome state
    await ws.send_str(json.dumps({
        "type": "connected",
        "message": "Connected to RoboNest Backend Brain",
        "agents": ["Zed", "Evaan", "Athena", "Lumi"]
    }))

    try:
        async for msg in ws:
            if msg.type == WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    msg_type = data.get("type")
                    if msg_type == "command":
                        cmd_text = data.get("command", "")
                        task = db.create_task(title=cmd_text, description="Submitted via WebSocket", source="ui")
                        asyncio.create_task(
                            zed_orchestrator.execute(
                                task_id=task["id"],
                                instruction=cmd_text,
                                event_callback=broadcast_event
                            )
                        )
                    elif msg_type == "ping":
                        await ws.send_str(json.dumps({"type": "pong"}))
                except Exception as e:
                    await ws.send_str(json.dumps({"type": "error", "error": str(e)}))
            elif msg.type == WSMsgType.ERROR:
                pass
    finally:
        connected_websockets.discard(ws)

    return ws


# --- REST API Endpoints ---
@routes.get("/api/health")
async def health(request):
    return web.json_response({
        "status": "ok",
        "app": settings.app_name,
        "version": settings.version,
        "active_clients": len(connected_websockets)
    })


@routes.get("/api/tasks")
async def list_tasks(request):
    tasks = db.list_tasks(limit=50)
    return web.json_response({"tasks": tasks})


@routes.post("/api/chat")
async def chat_with_zed(request):
    """Talk naturally first; only start an agent run after the model confirms intent."""
    body = await request.json()
    message = str(body.get("message", "")).strip()
    if not message:
        return web.json_response({"error": "Message is required"}, status=400)

    history = []
    for item in body.get("history", [])[-12:]:
        role = "assistant" if item.get("role") == "assistant" else "user"
        content = str(item.get("content", "")).strip()[:3000]
        if content:
            history.append({"role": role, "content": content})
    if not history or history[-1]["role"] != "user" or history[-1]["content"] != message:
        history.append({"role": "user", "content": message})

    system_prompt = """You are Zed, a warm and capable conversational office assistant. Reply in the same language and style as the user's latest message, including Hindi or Hinglish when appropriate. Talk naturally and do not treat every message as a task. Greetings, questions, opinions, brainstorming, and ordinary conversation are chat. If a user expresses an actionable goal, decide whether you have enough information to start useful work. Ask one focused follow-up question when a key choice or required detail is missing; do not invent a brief or turn vague statements into tasks. When the goal and essential details are clear, explain briefly what you understood and classify it as task. Mention the intended specialist if obvious: Evaan for visual design, Athena for structure/layout, Lumi for code and implementation. Never claim a plugin or external account is connected unless it is configured.

Return only a JSON object with these keys: kind (chat, clarify, task, or project), response (natural user-facing reply), instruction (complete actionable brief for task/project), title (short task title for task/project). Use project only when the user clearly asks to build or update a website. Ask for essential missing details before choosing task or project."""
    decision = await llm_client.chat(
        messages=history,
        system_prompt=system_prompt,
        enforce_json=True,
        max_retries=1,
    )
    if decision.get("error"):
        return web.json_response({
            "error": "Zed could not reach the configured AI model.",
            "detail": decision["error"],
        }, status=503)

    kind = decision.get("kind")
    response = str(decision.get("response", "")).strip()
    if kind not in {"chat", "clarify", "task", "project"} or not response:
        return web.json_response({"error": "The AI returned an incomplete reply. Please try again."}, status=502)

    payload = {"kind": kind, "response": response}
    if kind in {"task", "project"}:
        instruction = str(decision.get("instruction", "")).strip() or message
        title = str(decision.get("title", "")).strip() or instruction[:80]
        task = db.create_task(
            title=title[:120], description=instruction, source="chat", assigned_agent="zed"
        )
        if kind == "project":
            asyncio.create_task(zed_orchestrator.run_pipeline(
                task_id=task["id"], project_name=title[:40], project_description=instruction,
                event_callback=broadcast_event,
            ))
            payload["project_name"] = title[:40]
        else:
            asyncio.create_task(zed_orchestrator.execute(
                task_id=task["id"],
                instruction=instruction,
                context="Started from a confirmed user request in Zed's conversational chat.",
                event_callback=broadcast_event,
            ))
        payload["task_id"] = task["id"]
    return web.json_response(payload)


@routes.post("/api/tasks")
async def create_task(request):
    body = await request.json()
    title = body.get("title", "").strip()
    if not title:
        return web.json_response({"error": "Title is required"}, status=400)
    
    description = body.get("description", "")
    source = body.get("source", "user")
    assigned = body.get("assigned_agent", "zed")

    task = db.create_task(title=title, description=description, source=source, assigned_agent=assigned)
    task_id = task["id"]

    # Start execution in background with event broadcasting
    asyncio.create_task(
        zed_orchestrator.execute(
            task_id=task_id,
            instruction=title,
            context=description,
            event_callback=broadcast_event
        )
    )

    return web.json_response({"task": task, "status": "started"})


@routes.get("/api/tasks/{task_id}")
async def get_task_details(request):
    task_id = request.match_info["task_id"]
    task = db.get_task(task_id)
    if not task:
        return web.json_response({"error": "Task not found"}, status=404)
    return web.json_response({"task": task})


@routes.get("/api/approvals")
async def get_pending_approvals(request):
    approvals = db.list_pending_approvals()
    return web.json_response({"approvals": approvals})


@routes.post("/api/approvals/{approval_id}/resolve")
async def resolve_approval(request):
    approval_id = request.match_info["approval_id"]
    body = await request.json()
    approved = bool(body.get("approved", False))
    
    resolved = db.resolve_approval(approval_id, approved)
    if not resolved:
        return web.json_response({"error": "Approval not found"}, status=404)

    await broadcast_event({
        "type": "permission_resolved",
        "approval_id": approval_id,
        "approved": approved,
        "agent": resolved.get("agent_name"),
        "tool": resolved.get("tool_name")
    })

    return web.json_response({"approval": resolved})


@routes.get("/api/calendar")
async def list_calendar(request):
    date = request.query.get("date")
    events = db.list_calendar_events(date=date)
    return web.json_response({"events": events})


@routes.post("/api/calendar")
async def add_calendar(request):
    body = await request.json()
    title = body.get("title", "").strip()
    date = body.get("date", "").strip()
    if not title or not date:
        return web.json_response({"error": "title and date are required"}, status=400)

    time = body.get("time", "")
    who = body.get("who", "auto")
    kind = body.get("kind", "task")
    note = body.get("note", "")
    plugins = body.get("plugins", [])

    event = db.create_calendar_event(
        title=title,
        date=date,
        time=time,
        who=who,
        kind=kind,
        note=note,
        plugins=plugins
    )

    await broadcast_event({
        "type": "calendar_created",
        "event": event
    })

    return web.json_response({"event": event})


@routes.post("/api/pipeline/run")
async def run_pipeline(request):
    body = await request.json()
    name = body.get("name", "New Project").strip()
    desc = body.get("description", "").strip()

    task = db.create_task(title=f"Project: {name}", description=desc, source="pipeline", assigned_agent="zed")
    task_id = task["id"]

    asyncio.create_task(
        zed_orchestrator.run_pipeline(
            task_id=task_id,
            project_name=name,
            project_description=desc,
            event_callback=broadcast_event
        )
    )

    return web.json_response({"task_id": task_id, "status": "pipeline_started"})


@routes.get("/api/tools")
async def list_tools(request):
    return web.json_response({"tools": registry.list_all()})


def mask_secret(secret: Optional[str]) -> str:
    if not secret:
        return ""
    if len(secret) <= 8:
        return "••••••••"
    return secret[:4] + "••••••••" + secret[-4:]


@routes.get("/api/settings/llm")
async def get_llm_settings(request):
    # settings.llm.provider is initialized from env on startup, then updated by
    # the settings UI. Prefer it so a saved UI choice is not shadowed by .env.
    provider = request.query.get("provider") or settings.llm.provider or SecretManager.get_secret("ROBONEST_LLM_PROVIDER")
    api_key = get_provider_api_key(provider)
    base_url = SecretManager.get_secret("OPENAI_BASE_URL") or settings.llm.openai_base_url
    model = SecretManager.get_secret("OPENAI_MODEL") or settings.llm.openai_model
    ollama_url = SecretManager.get_secret("OLLAMA_BASE_URL") or settings.llm.ollama_url
    ollama_model = SecretManager.get_secret("OLLAMA_MODEL") or settings.llm.ollama_model

    return web.json_response({
        "provider": provider,
        "has_api_key": bool(api_key),
        "masked_api_key": mask_secret(api_key),
        "openai_base_url": base_url,
        "openai_model": model,
        "ollama_url": ollama_url,
        "ollama_model": ollama_model,
        "supported_providers": [
            {"id": "openai", "name": "OpenAI", "default_model": "gpt-4o-mini", "default_url": "https://api.openai.com/v1"},
            {"id": "openrouter", "name": "OpenRouter", "default_model": "google/gemini-2.0-flash-exp:free", "default_url": "https://openrouter.ai/api/v1"},
            {"id": "groq", "name": "Groq", "default_model": "llama-3.3-70b-versatile", "default_url": "https://api.groq.com/openai/v1"},
            {"id": "gemini", "name": "Google Gemini", "default_model": "gemini-3.8-flash", "default_url": "https://generativelanguage.googleapis.com/v1beta/openai/"},
            {"id": "ollama", "name": "Ollama (Local)", "default_model": "llama3.2:latest", "default_url": "http://localhost:11434"},
            {"id": "custom", "name": "Custom OpenAI Compatible", "default_model": "gpt-4o-mini", "default_url": "http://localhost:8000/v1"}
        ]
    })


@routes.post("/api/settings/llm")
async def save_llm_settings(request):
    body = await request.json()
    provider = body.get("provider", "openai").strip().lower()
    api_key = _clean_key(body.get("api_key", ""))
    base_url = body.get("base_url", "").strip()
    model = body.get("model", "").strip()
    ollama_url = body.get("ollama_url", "").strip()
    ollama_model = body.get("ollama_model", "").strip()

    supported = {"openai", "openrouter", "groq", "gemini", "ollama", "custom"}
    if provider not in supported:
        return web.json_response({"ok": False, "error": f"Unsupported AI provider: {provider}"}, status=400)
    if provider in PROVIDER_KEY_SECRETS and not (api_key or get_provider_api_key(provider)):
        return web.json_response({"ok": False, "error": f"Add an API key for {provider.title()} before saving this provider."}, status=400)

    SecretManager.set_secret("ROBONEST_LLM_PROVIDER", provider)
    settings.llm.provider = provider

    if api_key:
        provider_key_name = PROVIDER_KEY_SECRETS.get(provider)
        if provider_key_name:
            SecretManager.set_secret(provider_key_name, api_key)
        if provider == "openai":
            # Keep supporting existing OpenAI environment/config consumers.
            SecretManager.set_secret("OPENAI_API_KEY", api_key)
            settings.llm.openai_api_key = api_key

    if base_url:
        SecretManager.set_secret("OPENAI_BASE_URL", base_url)
        settings.llm.openai_base_url = base_url

    if model:
        SecretManager.set_secret("OPENAI_MODEL", model)
        settings.llm.openai_model = model

    if ollama_url:
        SecretManager.set_secret("OLLAMA_BASE_URL", ollama_url)
        settings.llm.ollama_url = ollama_url

    if ollama_model:
        SecretManager.set_secret("OLLAMA_MODEL", ollama_model)
        settings.llm.ollama_model = ollama_model

    active_model = model or (ollama_model if provider == "ollama" else settings.llm.openai_model)

    await broadcast_event({
        "type": "llm_settings_updated",
        "provider": provider,
        "model": active_model,
        "has_api_key": bool(get_provider_api_key(provider))
    })

    return web.json_response({
        "ok": True,
        "message": f"AI Model '{active_model}' ({provider}) successfully saved & connected!",
        "provider": provider,
        "model": active_model
    })


@routes.post("/api/settings/llm/test")
async def test_llm_connection(request):
    body = await request.json()
    provider = body.get("provider", settings.llm.provider).lower()
    api_key = _clean_key(body.get("api_key")) or get_provider_api_key(provider)
    base_url = body.get("base_url") or SecretManager.get_secret("OPENAI_BASE_URL") or settings.llm.openai_base_url
    model = body.get("model") or SecretManager.get_secret("OPENAI_MODEL") or settings.llm.openai_model
    ollama_url = body.get("ollama_url") or SecretManager.get_secret("OLLAMA_BASE_URL") or settings.llm.ollama_url

    start_t = asyncio.get_event_loop().time()
    try:
        if provider == "ollama":
            url = f"{ollama_url.rstrip('/')}/api/tags"
            async with httpx.AsyncClient(timeout=8) as client:
                res = await client.get(url)
                res.raise_for_status()
                models = [m.get("name") for m in res.json().get("models", [])]
                latency = round((asyncio.get_event_loop().time() - start_t) * 1000)
                return web.json_response({
                    "ok": True,
                    "message": f"Ollama is reachable! Available models: {', '.join(models[:4]) or 'none'}",
                    "latency_ms": latency
                })
        else:
            api_key = _clean_key(api_key)
            if not api_key:
                return web.json_response({"ok": False, "error": "API Key is required to connect to this provider."}, status=400)

            test_url = f"{base_url.rstrip('/')}/chat/completions"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Reply with 'OK'"}],
                "max_tokens": 10
            }
            async with httpx.AsyncClient(timeout=12) as client:
                res = await client.post(test_url, headers=headers, json=payload)
                if res.status_code >= 400:
                    err_msg = res.text
                    try:
                        err_json = res.json()
                        err_msg = err_json.get("error", {}).get("message", res.text)
                    except Exception:
                        pass
                    if res.status_code == 401:
                        provider_message = err_msg
                        err_msg = (f"{provider.title()} returned 401 Unauthorized: {provider_message}. "
                                   "Check that the API key is correct and active, then save it again.")
                    return web.json_response({"ok": False, "error": f"Provider error ({res.status_code}): {err_msg}"}, status=400)

                latency = round((asyncio.get_event_loop().time() - start_t) * 1000)
                data = res.json()
                reply = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                return web.json_response({
                    "ok": True,
                    "message": f"Connected to {model}! Response: '{reply}'",
                    "latency_ms": latency
                })
    except Exception as e:
        return web.json_response({"ok": False, "error": f"Connection failed: {str(e)}"}, status=500)


def create_app() -> web.Application:
    app = web.Application(middlewares=[cors_middleware])
    app.add_routes(routes)

    # Static files for the renderer UI if present
    renderer_path = PROJECT_ROOT / "electron" / "renderer"
    if renderer_path.exists():
        app.router.add_static("/ui", path=str(renderer_path), name="ui")

    async def on_startup(app):
        # Sync saved secrets into in-memory settings
        saved_provider = SecretManager.get_secret("ROBONEST_LLM_PROVIDER")
        if saved_provider:
            settings.llm.provider = saved_provider
        saved_key = SecretManager.get_secret("OPENAI_API_KEY")
        if saved_key:
            settings.llm.openai_api_key = saved_key
        saved_url = SecretManager.get_secret("OPENAI_BASE_URL")
        if saved_url:
            settings.llm.openai_base_url = saved_url
        saved_model = SecretManager.get_secret("OPENAI_MODEL")
        if saved_model:
            settings.llm.openai_model = saved_model
        saved_ollama_url = SecretManager.get_secret("OLLAMA_BASE_URL")
        if saved_ollama_url:
            settings.llm.ollama_url = saved_ollama_url
        saved_ollama_model = SecretManager.get_secret("OLLAMA_MODEL")
        if saved_ollama_model:
            settings.llm.ollama_model = saved_ollama_model

        # Start persistent scheduler
        scheduler.start(broadcaster=broadcast_event)

    async def on_cleanup(app):
        # Stop scheduler & disconnect websockets
        scheduler.stop()
        for ws in list(connected_websockets):
            await ws.close(code=1001, message=b"Server shutting down")

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    return app


if __name__ == "__main__":
    app = create_app()
    # Electron may already have started the local backend. Avoid an aiohttp
    # traceback when a user manually starts a second copy from the terminal.
    try:
        with socket.create_connection((settings.host, settings.port), timeout=0.5):
            print(
                f"RoboNest Backend is already running at "
                f"http://{settings.host}:{settings.port}; using the existing instance."
            )
            sys.exit(0)
    except OSError:
        pass
    print(f"Starting RoboNest Backend on http://{settings.host}:{settings.port}")
    web.run_app(app, host=settings.host, port=settings.port)
