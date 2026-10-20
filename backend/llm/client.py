import json
import re
import asyncio
import os
import random
import time
from typing import List, Dict, Any, Optional
import httpx

from backend.config import settings
from backend.security.secrets import SecretManager


PROVIDER_DEFAULT_URLS = {
    "openai": "https://api.openai.com/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}


def _clean_key(key: str) -> str:
    cleaned = str(key or "").strip().strip('"').strip("'").strip()
    if cleaned.lower().startswith("bearer "):
        cleaned = cleaned[7:].strip()
    return cleaned


def _mask_key(key: str) -> str:
    if not key:
        return "(empty)"
    return f"{key[:7]}...{key[-4:]} (len={len(key)})"


def _detect_provider_from_key(key: str, fallback: str):
    """Returns (provider, is_certain). Distinctive prefixes identify the issuer for sure."""
    if key.startswith("sk-or-"):
        return "openrouter", True
    if key.startswith("gsk_"):
        return "groq", True
    if key.startswith("AIza"):
        return "gemini", True
    if key.startswith(("sk-proj-", "sk-svcacct-", "sk-admin-")):
        return "openai", True
    return fallback, False


class LLMQuotaError(RuntimeError):
    """Billing/quota finished - retrying will never help."""


class LLMRateLimitError(RuntimeError):
    """Rate limit still hit after all internal retries."""


# Seconds to keep between two LLM calls (helps avoid 429). Override with env ROBONEST_LLM_MIN_INTERVAL
MIN_CALL_INTERVAL = float(os.getenv("ROBONEST_LLM_MIN_INTERVAL", "1.5"))
MAX_429_RETRIES = int(os.getenv("ROBONEST_LLM_429_RETRIES", "4"))


PROVIDER_KEY_SECRETS = {
    "openai": "ROBONEST_OPENAI_API_KEY",
    "openrouter": "ROBONEST_OPENROUTER_API_KEY",
    "groq": "ROBONEST_GROQ_API_KEY",
    "gemini": "ROBONEST_GEMINI_API_KEY",
    "custom": "ROBONEST_CUSTOM_API_KEY",
}


def get_provider_api_key(provider: str) -> str:
    """Return credentials only for the selected provider."""
    provider = (provider or "").lower()
    scoped_name = PROVIDER_KEY_SECRETS.get(provider)
    candidates = []
    if scoped_name:
        candidates.extend((os.getenv(scoped_name), SecretManager.get_persisted_secret(scoped_name)))
    named_env_key = os.getenv(f"{provider.upper()}_API_KEY") if provider else None
    candidates.append(named_env_key)
    if provider == "openai":
        candidates.extend((settings.llm.openai_api_key, SecretManager.get_persisted_secret("OPENAI_API_KEY")))
    for candidate in candidates:
        key = _clean_key(candidate)
        if key:
            return key
    return ""


class LLMClient:
    """
    Centralized LLM client supporting Ollama (local) and OpenAI-compatible APIs.
    Features:
    1. Strict Lock/Queue: Serializes LLM calls so local GPU/RAM never gets overwhelmed.
    2. JSON Schema extraction and auto-repair/retry.
    3. Mock fallback mode when no live model is running.
    """

    def __init__(self):
        self._lock = asyncio.Lock()
        self._last_call_ts = 0.0
        self._json_mode_supported = True

    async def _throttle(self):
        wait = MIN_CALL_INTERVAL - (time.monotonic() - self._last_call_ts)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_call_ts = time.monotonic()

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: Optional[str] = None,
        enforce_json: bool = True,
        max_retries: int = 2
    ) -> Dict[str, Any]:
        """
        Calls the LLM under an async lock. If enforce_json is True, validates and parses JSON.
        """
        async with self._lock:
            # Build conversation payload
            conversation = []
            if system_prompt:
                conversation.append({"role": "system", "content": system_prompt})
            conversation.extend(messages)

            retries_left = max_retries
            last_raw_response = ""

            while retries_left >= 0:
                try:
                    raw_text = await self._call_provider(conversation)
                    last_raw_response = raw_text

                    if not enforce_json:
                        return {"raw": raw_text}

                    # Attempt JSON extraction
                    parsed = self._extract_json(raw_text)
                    if parsed is not None:
                        return parsed

                    # If parsing failed, retry with feedback
                    retries_left -= 1
                    if retries_left >= 0:
                        conversation.append({"role": "assistant", "content": raw_text})
                        conversation.append({
                            "role": "user",
                            "content": "ERROR: Your output was not valid JSON. Please respond ONLY with a valid JSON object matching the requested schema."
                        })
                except (LLMQuotaError, LLMRateLimitError) as e:
                    # Already retried inside _call_openai (or retry is pointless) -> stop now
                    return {
                        "error": f"LLM error: {str(e)}",
                        "raw": last_raw_response,
                        "action": "finish",
                        "thought": f"Stopped: {e}",
                        "result": f"Execution halted due to LLM failure: {e}"
                    }
                except Exception as e:
                    retries_left -= 1
                    if retries_left < 0:
                        # Fallback response so agent doesn't crash
                        return {
                            "error": f"LLM error: {str(e)}",
                            "raw": last_raw_response,
                            "action": "finish",
                            "thought": f"Failed after retries due to {e}",
                            "result": f"Execution halted due to LLM failure: {e}"
                        }
                    await asyncio.sleep(1)

            # If all retries exhausted, return safe fallback
            return {
                "error": "Failed to parse valid JSON from LLM output",
                "raw": last_raw_response,
                "action": "finish",
                "thought": "Invalid JSON produced by model",
                "result": last_raw_response
            }

    async def _call_provider(self, conversation: List[Dict[str, str]]) -> str:
        provider = (settings.llm.provider or SecretManager.get_secret("ROBONEST_LLM_PROVIDER") or "mock").lower()

        if provider in ["openai", "openrouter", "groq", "gemini", "custom"]:
            if not get_provider_api_key(provider):
                raise RuntimeError(f"No API key is configured for {provider}. Add that provider's key in AI Model settings.")
            return await self._call_openai(conversation, provider)
        elif provider == "ollama":
            return await self._call_ollama(conversation)
        else:
            return self._mock_response(conversation)

    async def _call_ollama(self, conversation: List[Dict[str, str]]) -> str:
        ollama_url = SecretManager.get_secret("OLLAMA_BASE_URL") or settings.llm.ollama_url
        ollama_model = SecretManager.get_secret("OLLAMA_MODEL") or settings.llm.ollama_model
        url = f"{ollama_url.rstrip('/')}/api/chat"
        payload = {
            "model": ollama_model,
            "messages": conversation,
            "stream": False,
            "options": {
                "temperature": settings.llm.temperature,
                "num_predict": settings.llm.max_tokens
            }
        }
        async with httpx.AsyncClient(timeout=settings.llm.timeout_seconds) as client:
            resp = await client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data.get("message", {}).get("content", "")

    async def _call_openai(self, conversation: List[Dict[str, str]], provider: str = "openai") -> str:
        api_key = _clean_key(get_provider_api_key(provider))
        base_url = _clean_key(SecretManager.get_secret("OPENAI_BASE_URL") or settings.llm.openai_base_url)
        model = _clean_key(SecretManager.get_secret("OPENAI_MODEL") or settings.llm.openai_model)

        # Auto-fix key/URL mismatch: if the key prefix clearly belongs to a provider,
        # always use that provider's URL (ignores stale saved OPENAI_BASE_URL).
        detected, certain = _detect_provider_from_key(api_key, provider)
        if certain:
            base_url = PROVIDER_DEFAULT_URLS[detected]
            if detected == "openrouter" and "/" not in model:
                model = "openai/" + model
            elif detected == "openai" and model.startswith("openai/"):
                model = model.split("/", 1)[1]
        elif not base_url:
            base_url = PROVIDER_DEFAULT_URLS.get(provider, PROVIDER_DEFAULT_URLS["openai"])

        url = f"{base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": model,
            "messages": conversation,
            "temperature": settings.llm.temperature,
            "max_tokens": settings.llm.max_tokens
        }

        async with httpx.AsyncClient(timeout=settings.llm.timeout_seconds) as client:
            attempt = 0
            while True:
                await self._throttle()
                body = {**payload, "response_format": {"type": "json_object"}} if self._json_mode_supported else payload
                resp = await client.post(url, headers=headers, json=body)

                # 400 -> this model/provider may not support json mode; remember and retry once without it
                if resp.status_code == 400 and self._json_mode_supported:
                    self._json_mode_supported = False
                    continue

                if resp.status_code == 401:
                    server_msg = ""
                    try:
                        server_msg = str(resp.json().get("error", {}).get("message", ""))
                    except Exception:
                        server_msg = resp.text[:200]
                    raise RuntimeError(
                        f"{provider.title()} rejected the API key (401). "
                        f"[debug] url={url} | key used={_mask_key(api_key)} | model={model} | server says: {server_msg}"
                    )

                if resp.status_code == 429:
                    err_code, err_msg = "", ""
                    try:
                        err = resp.json().get("error", {})
                        err_code = str(err.get("code") or err.get("type") or "")
                        err_msg = str(err.get("message") or "")
                    except Exception:
                        pass

                    # Quota / billing finished: retry is useless
                    if "insufficient_quota" in err_code or "quota" in err_msg.lower() or "billing" in err_msg.lower():
                        raise LLMQuotaError(
                            f"{provider.title()} quota/credit khatam ho gaya (429 insufficient_quota). "
                            f"Billing/credits check karo ya naya API key daalo. Details: {err_msg}"
                        )

                    attempt += 1
                    if attempt > MAX_429_RETRIES:
                        raise LLMRateLimitError(
                            f"{provider.title()} rate limit (429) bar-bar aa raha hai. "
                            f"Thodi der baad try karo ya kam requests bhejo. Details: {err_msg}"
                        )

                    retry_after = resp.headers.get("retry-after")
                    try:
                        delay = float(retry_after) if retry_after else min(2 ** attempt, 30)
                    except ValueError:
                        delay = min(2 ** attempt, 30)
                    delay = min(delay, 60) + random.uniform(0, 1)
                    await asyncio.sleep(delay)
                    continue

                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]

    def _extract_json(self, text: str) -> Optional[Dict[str, Any]]:
        text = text.strip()
        # 1. Direct parse
        try:
            return json.loads(text)
        except Exception:
            pass

        # 2. Extract ```json ... ``` markdown block
        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if match:
            try:
                return json.loads(match.group(1).strip())
            except Exception:
                pass

        # 3. Find outermost { ... }
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except Exception:
                pass

        return None

    def _mock_response(self, conversation: List[Dict[str, str]]) -> str:
        """
        Intelligent English-language conversational mock generator.
        Provides natural chitchat when no live API key is set yet.
        """
        last_msg = conversation[-1]["content"] if conversation else ""
        sys_msg = conversation[0]["content"] if conversation and conversation[0]["role"] == "system" else ""
        l = last_msg.lower()

        # If it's Zed
        if "Zed" in sys_msg:
            # Check for file summarization or code tasks
            if "summarize" in l or "files" in l or "folder" in l or "directory" in l:
                return json.dumps({
                    "thought": "The user wants a summary of files in the workspace. Delegating file inspection to Lumi.",
                    "action": "delegate",
                    "agent": "lumi",
                    "instruction": "List and inspect the files in the workspace, then summarize the structure."
                })
            elif "design" in l or "colour" in l or "color" in l or "theme" in l:
                return json.dumps({
                    "thought": "This is a creative design task. Delegating to Evaan.",
                    "action": "delegate",
                    "agent": "evaan",
                    "instruction": last_msg
                })
            elif "layout" in l or "wireframe" in l or "responsive" in l or "grid" in l:
                return json.dumps({
                    "thought": "This is an architectural layout task. Delegating to Athena.",
                    "action": "delegate",
                    "agent": "athena",
                    "instruction": last_msg
                })
            # Casual conversation & Chit-chat handling
            elif re.search(r"\b(hi+|hello+|hey+|yo)\b", l):
                return json.dumps({
                    "thought": "The user is greeting. Respond warmly and politely in English.",
                    "action": "finish",
                    "response": "Hello! I’m Zed, RoboNest’s lead robot. How can I help today? You can chat with me or ask the team to build a new frontend project."
                })
            elif re.search(r"\b(how are you|how is it going)\b", l):
                return json.dumps({
                    "thought": "User asking how I am. Friendly casual reply.",
                    "action": "finish",
                    "response": "I’m doing great! 🤖 Evaan, Athena, and Lumi are all at their desks and ready to help. How is your day going?"
                })
            elif re.search(r"\b(who are you|who r u|introduce yourself)\b", l):
                return json.dumps({
                    "thought": "Explaining my role as team lead.",
                    "action": "finish",
                    "response": "I’m Zed, RoboNest’s receptionist and orchestrator (green avatar). I chat with you, answer questions, and coordinate our three frontend specialists: Evaan, Athena, and Lumi."
                })
            elif re.search(r"\b(help|what can you do|features)\b", l):
                return json.dumps({
                    "thought": "User asking about capabilities.",
                    "action": "finish",
                    "response": "I can help in several ways:\n1. 💬 Chat with you and answer questions\n2. 🎨 Ask Evaan to design a UI and color palette\n3. 📐 Ask Athena to plan a responsive layout\n4. ⚡ Ask Lumi to build JavaScript features and logic\n5. 📅 Schedule calendar tasks and manage files\n6. 🔑 Connect a live model by adding an OpenAI, OpenRouter, Groq, or Gemini key in Settings."
                })
            elif re.search(r"\b(api key|model|settings|connect|groq|openai|gemini)\b", l):
                return json.dumps({
                    "thought": "Helping user configure API key.",
                    "action": "finish",
                    "response": "Open the profile menu in the top-right corner or select the ‘AI Model / Key’ button above the chat. Add an OpenAI, OpenRouter, Groq, or Gemini API key to connect a live model."
                })
            elif re.search(r"\b(thanks|thank you|awesome|great)\b", l):
                return json.dumps({
                    "thought": "Polite acknowledgment.",
                    "action": "finish",
                    "response": "You’re welcome! 😄 I’m here whenever you need me. Let me know if you have another question or want to start a project."
                })
            else:
                return json.dumps({
                    "thought": "Natural conversational response to user's message.",
                    "action": "finish",
                    "response": f"I heard you: “{last_msg}”. I’m ready to help. To connect a live model, add an API key in Settings."
                })

        # If it's Lumi
        elif "Lumi" in sys_msg:
            if "result of list_directory" in l:
                return json.dumps({
                    "thought": "I have the file listing. Summarizing workspace structure.",
                    "action": "finish",
                    "result": "RoboNest workspace contains project code, backend services, agent configurations, and UI assets."
                })
            else:
                return json.dumps({
                    "thought": "Inspecting workspace files first using list_directory tool.",
                    "action": "call_tool",
                    "tool": "list_directory",
                    "args": {"path": "."}
                })

        # If it's Evaan
        elif "Evaan" in sys_msg:
            return json.dumps({
                "thought": "Designing palette and visual tokens.",
                "action": "finish",
                "result": "Color palette: Primary #4cc48a, Secondary #9fd3e6, Background #14110f. Fonts: Inter, JetBrains Mono."
            })

        # If it's Athena
        elif "Athena" in sys_msg:
            return json.dumps({
                "thought": "Creating semantic layout wireframe.",
                "action": "finish",
                "result": "Layout structure: Header, 3D Canvas Stage, Lateral Agent Feed, Bottom Command Console."
            })

        return json.dumps({
            "thought": "Standard response.",
            "action": "finish",
            "result": "Task completed successfully."
        })


llm_client = LLMClient()
