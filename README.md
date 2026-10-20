# RoboNest AI Office 🤖🏢

> Autonomous Multi-Agent AI Office with 3D Visualizer & Independent Python Backend Brain.

RoboNest separates the **Brain (Backend)** from the **Visualizer (UI)** cleanly:
- The **Python Backend** handles the orchestrator (Zed), specialized agents (Evaan, Athena, Lumi), tools, permissions, persistent calendar scheduler, and LLM calls.
- The **Electron / 3D Renderer** visualizes office activities in real-time over WebSockets and REST APIs, without executing any agent logic in the browser.

---

## 🏛️ Architecture

```
Electron App (3D Office, Calendar, Plugins UI)
        │
        │ WebSocket (ws://localhost:8765/ws) + REST HTTP (http://localhost:8765)
        ▼
Python Backend Brain (Async API + WebSockets)
   ├─ Orchestrator (Zed)             → Evaluates, plans, and delegates
   ├─ Agents (Evaan, Athena, Lumi)   → Specialized prompts, shared single LLM
   ├─ Tools & Plugins Registry       → Files, Web, Git, Calendar, Gmail, Drive
   ├─ Security & Approval Gate       → Dangerous actions halted for user consent
   ├─ Persistent Scheduler           → SQLite-backed automated calendar runner
   ├─ Memory Store                   → SQLite (tasks, runs, logs) + Vector memory
   └─ LLM Client                     → Ollama / OpenAI / Mock with Serialized Queue
```

---

## 👥 The Agent Team

| Agent | Role | Color / Avatar | Specialty |
|---|---|---|---|
| **Zed** | Orchestrator & Team Lead | `#4cc48a` (Green / Z) | Decomposes goals, plans pipelines, delegates tasks, and synthesizes final reports. |
| **Evaan** | Designer & Creative Lead | `#9fd3e6` (Sky Blue / E) | Color palettes, typography, UI visual tokens, brand copy, and styling guidelines. |
| **Athena** | Architect & Structural Lead | `#f08a9d` (Rose Pink / A) | Semantic layout wireframes, HTML skeletons, schema design, and component contracts. |
| **Lumi** | Software Engineer | `#b99be6` (Lavender / L) | Code writing, file operations, debugging, tool execution, and logic verification. |

---

## 🛡️ Safety & Core Engineering Rules

1. **Hardware-Friendly Concurrency**:
   Local LLMs (e.g., Ollama) run through an `asyncio.Lock` queue. Only one LLM inference executes at a time to prevent GPU/RAM memory saturation.
2. **Infinite Loop Protection**:
   Agents operate under a strict step limit (default: 10 steps max). Tasks exceeding the limit halt safely.
3. **Backend-Enforced Permission Gate**:
   Destructive or sensitive actions (`delete_file`, `git_push`, `git_commit`, `send_email`) are intercepted on the backend and placed in a `waiting_approval` state in SQLite. Approval cannot be bypassed in the UI.
4. **Prompt Injection Shield**:
   All external inputs (files, web pages, emails) are wrapped inside `<UNTRUSTED_EXTERNAL_DATA>` tags, instructing the model to treat content strictly as passive data.
5. **Robust JSON Output & Retry**:
   Extracts JSON from markdown code blocks or text delimiters, with automatic schema-correcting retries.

---

## 📁 Project Structure

```
robonest/
├─ electron/
│  ├─ main.js                 # Electron main process (spawns & supervises backend)
│  ├─ preload.js              # Secure contextBridge API
│  └─ renderer/               # 3D office visualization, calendar & live preview
│     ├─ index.html
│     ├─ js/
│     │  └─ ws.js             # WebSocket event bridge connecting UI to backend
│     └─ libs/                # Offline copies of three.min.js & jszip.min.js
├─ backend/
│  ├─ main.py                 # Async Web & WebSocket server (port 8765)
│  ├─ cli.py                  # Terminal runner (Zed -> Agent -> Tool -> Result)
│  ├─ config.py               # Paths, model settings, timeouts & limits
│  ├─ llm/
│  │  └─ client.py            # Unified LLM client (Ollama / OpenAI / Mock)
│  ├─ agents/
│  │  ├─ base.py              # BaseAgent (prompts, tools, step guard, logs)
│  │  ├─ zed.py               # Zed orchestrator
│  │  ├─ evaan.py             # Evaan designer
│  │  ├─ athena.py            # Athena architect
│  │  ├─ lumi.py              # Lumi engineer
│  │  └─ prompts/             # System prompts (.md files)
│  ├─ tools/
│  │  ├─ registry.py          # Tool registry & permission levels
│  │  ├─ files.py             # Safe file read, list, write, delete
│  │  ├─ web.py               # Web page fetching & search
│  │  ├─ github.py            # Git status, commit, push
│  │  └─ calendar_tool.py     # Calendar scheduling tools
│  ├─ scheduler/
│  │  └─ jobs.py              # SQLite-backed persistent background scheduler
│  ├─ memory/
│  │  ├─ db.py                # SQLite schema (tasks, runs, logs, approvals, calendar)
│  │  └─ vectors.py           # Resilient vector/TF-IDF memory store
│  └─ security/
│     └─ secrets.py           # OS keyring & secure secret manager
├─ legacy_ui/                 # Original reference HTML file safely backed up
├─ data/                      # SQLite database, logs & memory (ignored in git)
├─ tests/                     # Comprehensive unit & integration tests
├─ package.json               # Electron & project scripts
├─ pyproject.toml             # Python package definition
└─ README.md
```

---

## 🚀 Quickstart Guide

### 1. Test Backend Directly from Terminal (No UI required)
Run a test task to verify Zed -> Agent -> Tool -> Result:
```bash
python3 -m backend.cli "Summarize the files in this folder"
```

### 2. Run All Tests
```bash
python3 -m unittest discover tests
```

### 3. Launch Backend Brain Server
```bash
python3 -m backend.main
```
The server will boot on `http://127.0.0.1:8765` and listen for WebSocket connections at `ws://127.0.0.1:8765/ws`.

### 4. Launch Desktop App (Electron + Backend)
```bash
npm start
```
Electron will launch the backend process automatically and display the 3D office.

---

## ⚙️ Configuration & Environment

You can configure settings via environment variables or a `.env` file:

```env
# LLM Provider: "ollama", "openai", or "mock"
ROBONEST_LLM_PROVIDER=ollama

# Ollama Settings
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2:latest

# OpenAI Settings (optional)
OPENAI_API_KEY=your_key_here
OPENAI_MODEL=gpt-4o-mini
```

---

## 📦 Packaging for SaaS / Desktop Distribution
- **Backend Binary**: Bundle Python backend using PyInstaller:
  ```bash
  pyinstaller --onefile --name robonest-brain backend/main.py
  ```
- **Desktop Installer**: Bundle Electron + binary with electron-builder:
  ```bash
  npm run dist
  ```
