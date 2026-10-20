// RoboNest Live Backend WebSocket & API Bridge
const BACKEND_URL = (window.robonest && window.robonest.backendUrl) || 'http://127.0.0.1:8765';
const WS_URL = (window.robonest && window.robonest.wsUrl) || 'ws://127.0.0.1:8765/ws';

class RoboNestBridge {
  constructor() {
    this.ws = null;
    this.reconnectTimer = null;
    this.connected = false;
  }

  init() {
    this.connect();
  }

  connect() {
    try {
      this.ws = new WebSocket(WS_URL);

      this.ws.onopen = () => {
        this.connected = true;
        console.log('[RoboNest WS] Connected to Python Backend Brain.');
        if (typeof notify === 'function') {
          notify('ok', 'Brain Connected', 'RoboNest Python backend is active.');
        }
      };

      this.ws.onmessage = (event) => {
        try {
          const data = jsonParseSafe(event.data);
          if (data) {
            this.handleEvent(data);
          }
        } catch (e) {
          console.error('[RoboNest WS] Message parse error:', e);
        }
      };

      this.ws.onclose = () => {
        this.connected = false;
        console.warn('[RoboNest WS] Disconnected. Retrying in 3s...');
        clearTimeout(this.reconnectTimer);
        this.reconnectTimer = setTimeout(() => this.connect(), 3000);
      };

      this.ws.onerror = (err) => {
        console.warn('[RoboNest WS] Connection error:', err);
      };
    } catch (e) {
      console.warn('[RoboNest WS] Init exception:', e);
    }
  }

  sendCommand(text) {
    if (!text || !text.trim()) return Promise.resolve({ ok: false, error: 'Message is empty.' });
    return this.chat(text.trim());
  }

  async chat(text, messages = []) {
    try {
      const history = messages.slice(-12).map((message) => ({
        role: message.w === 'z' ? 'assistant' : 'user',
        content: message.x
      }));
      const res = await fetch(`${BACKEND_URL}/api/chat`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: text, history })
      });
      const data = await res.json();
      if (!res.ok) return { ok: false, error: data.detail || data.error || `Backend error (${res.status})` };
      return { ok: true, ...data };
    } catch (e) {
      return { ok: false, error: 'Could not connect to the RoboNest backend. Please try again after it starts.' };
    }
  }

  async resolveApproval(approvalId, approved) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/approvals/${approvalId}/resolve`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ approved })
      });
      return await res.json();
    } catch (e) {
      console.error('[Resolve Approval Error]', e);
    }
  }

  async addCalendarTask(eventData) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/calendar`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(eventData)
      });
      return await res.json();
    } catch (e) {
      console.error('[Add Calendar Error]', e);
    }
  }

  async getLLMSettings(provider = '') {
    try {
      const suffix = provider ? `?provider=${encodeURIComponent(provider)}` : '';
      const res = await fetch(`${BACKEND_URL}/api/settings/llm${suffix}`);
      return await res.json();
    } catch (e) {
      console.error('[Get LLM Settings Error]', e);
      return null;
    }
  }

  async saveLLMSettings(data) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/settings/llm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      return await res.json();
    } catch (e) {
      console.error('[Save LLM Settings Error]', e);
      return { ok: false, error: e.message };
    }
  }

  async testLLMConnection(data) {
    try {
      const res = await fetch(`${BACKEND_URL}/api/settings/llm/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });
      return await res.json();
    } catch (e) {
      console.error('[Test LLM Connection Error]', e);
      return { ok: false, error: e.message };
    }
  }

  handleEvent(ev) {
    console.log('[RoboNest Event]', ev.type, ev);

    // 1. Orchestrator received task or chat
    if (ev.type === 'orchestrator_start') {
      if (typeof zedBusy !== 'undefined') zedBusy = 90;
      if (typeof say === 'function' && window.R && window.R.Z) {
        say(window.R.Z, "Thinking... ✨", 2.5);
      }
      if (typeof log === 'function') {
        log('Zed', 'Received: “' + (ev.instruction ? ev.instruction.slice(0, 35) : '') + '”');
      }
    }

    // 2. Delegation to subagents
    else if (ev.type === 'delegation') {
      const agentKey = (ev.target_agent[0] || 'Z').toUpperCase();
      const robot = window.R && window.R[agentKey];
      if (robot && typeof say === 'function') {
        const openers = ['I’ll take this part:', 'I can handle:', 'I’m starting with:'];
        const opener = openers[(Date.now() >>> 4) % openers.length];
        say(robot, opener + ' ' + (ev.instruction || 'the assigned work').replace(/[\n\r]+/g, ' ').slice(0, 75), 4);
      }
      if (typeof log === 'function') {
        log('Zed', 'Delegated to ' + ev.target_agent + ': ' + ev.instruction);
      }
    }

    else if (ev.type === 'pipeline_stage') {
      const agentKey = (ev.agent || 'Z')[0].toUpperCase();
      const robot = window.R && window.R[agentKey];
      if (robot && typeof say === 'function') say(robot, ev.description || 'I’m working on my part.', 4);
      if (typeof log === 'function') log(ev.agent || 'Team', ev.description || 'Project stage started.');
    }

    // 3. Tool execution
    else if (ev.type === 'tool_executed') {
      const agentKey = (ev.agent[0] || 'Z').toUpperCase();
      const robot = window.R && window.R[agentKey];
      if (robot && typeof say === 'function') {
        say(robot, 'Tool: ' + ev.tool, 2.5);
      }
      if (typeof log === 'function') {
        log(ev.agent, 'Executed tool ' + ev.tool + ' (' + ev.thought.slice(0, 35) + '...)');
      }
    }

    // 4. Permission / Approval required
    else if (ev.type === 'permission_requested') {
      if (typeof notify === 'function') {
        notify('perm', 'Approval Required', ev.agent + ' requests permission for: ' + ev.tool, ev.approval_id);
      }
      this.renderApprovalPrompt(ev);
    }

    // 5. Agent or Pipeline finish
    else if (ev.type === 'agent_finish' || ev.type === 'orchestrator_finish') {
      if (ev.type === 'orchestrator_finish' && typeof zedBusy !== 'undefined') zedBusy = 0;
      if (ev.type === 'agent_finish' && typeof burst === 'function' && window.R && window.R.Z) {
        burst(window.R.Z.g.position);
      }
      if (typeof log === 'function' && ev.result) {
        log(ev.agent || 'Zed', (ev.result.length > 50 ? ev.result.slice(0, 50) + '...' : ev.result));
      }
      if (ev.type === 'orchestrator_finish' && typeof zsay === 'function' && ev.result) {
        zsay(ev.result);
      }
      if (typeof say === 'function' && ev.result) {
        const key = (ev.agent || 'Z')[0].toUpperCase();
        const robot = window.R && window.R[key];
        if (robot) {
          const speech = ev.result.replace(/[\n\r]+/g, ' ').slice(0, 95);
          say(robot, speech + (ev.result.length > 95 ? '…' : ''), 4);
        }
      }
    }

    else if (ev.type === 'pipeline_complete') {
      if (typeof zedBusy !== 'undefined') zedBusy = 0;
      if (typeof zsay === 'function' && ev.summary) zsay(ev.summary);
      if (typeof log === 'function' && ev.summary) log('Zed', 'Project pipeline finished.');
    }

    // 6. Calendar Pickup
    else if (ev.type === 'calendar_pickup') {
      if (typeof notify === 'function') {
        notify('ok', 'Calendar Scheduled Task', 'Zed picked up: ' + ev.title);
      }
      if (typeof say === 'function' && window.R && window.R.Z) {
        say(window.R.Z, 'Calendar trigger: ' + ev.title.slice(0, 25), 4);
      }
    }

    // 7. LLM Settings Updated
    else if (ev.type === 'llm_settings_updated') {
      if (typeof notify === 'function') {
        notify('ok', 'Model Connected', 'Active Model: ' + ev.model + ' (' + ev.provider + ')');
      }
      if (typeof zsay === 'function') {
        zsay('AI model connected: ' + ev.model + ' (' + ev.provider + '). You can now chat with me.');
      }
    }
  }

  renderApprovalPrompt(ev) {
    const feed = document.getElementById('dock') || document.getElementById('chat');
    if (!feed) return;
    const card = document.createElement('div');
    card.className = 'row perm';
    card.id = `approval-${ev.approval_id}`;
    card.innerHTML = `
      <div class="t">⚠️ ${ev.agent} needs permission to run: <b>${ev.tool}</b></div>
      <div class="s">Arguments: <code>${JSON.stringify(ev.args)}</code></div>
      <div class="bt">
        <button class="ok" data-action="allow">Allow</button>
        <button class="danger" data-action="deny">Deny</button>
      </div>
    `;

    card.querySelector('[data-action="allow"]').addEventListener('click', async () => {
      await this.resolveApproval(ev.approval_id, true);
      card.remove();
    });

    card.querySelector('[data-action="deny"]').addEventListener('click', async () => {
      await this.resolveApproval(ev.approval_id, false);
      card.remove();
    });

    feed.prepend(card);
  }
}

function jsonParseSafe(str) {
  try {
    return JSON.parse(str);
  } catch (e) {
    return null;
  }
}

window.robonestBridge = new RoboNestBridge();
window.robonestBridge.init();
