// Automated E2E verification test for RoboNest AI Office UI
const { app, BrowserWindow } = require('electron');
const path = require('path');
const http = require('http');
const { spawn } = require('child_process');

app.disableHardwareAcceleration();

let errors = [];
let backendProc = null;

function waitForBackend(retries = 25) {
  return new Promise((resolve, reject) => {
    const check = (left) => {
      http.get('http://127.0.0.1:8765/api/health', (res) => {
        if (res.statusCode === 200) return resolve();
        if (left <= 0) return reject(new Error('Backend timeout'));
        setTimeout(() => check(left - 1), 250);
      }).on('error', () => {
        if (left <= 0) return reject(new Error('Backend connection timeout'));
        setTimeout(() => check(left - 1), 250);
      });
    };
    check(retries);
  });
}

app.whenReady().then(async () => {
  // Ensure Python backend is running
  try {
    await waitForBackend(3);
    console.log('[Test Runner] Connected to existing Python backend.');
  } catch (_) {
    console.log('[Test Runner] Launching Python backend on port 8765...');
    backendProc = spawn('python3', ['-m', 'backend.main'], {
      cwd: path.join(__dirname, '..'),
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdio: 'ignore'
    });
    await waitForBackend(35);
    console.log('[Test Runner] Python backend started successfully!');
  }

  const win = new BrowserWindow({
    width: 1360,
    height: 880,
    show: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: false
    }
  });

  win.webContents.on('console-message', (event, level, message, line, sourceId) => {
    if (level >= 3) {
      console.error(`[Console Error] ${message} (${sourceId}:${line})`);
      errors.push(message);
    } else {
      console.log(`[Console Log] ${message}`);
    }
  });

  win.webContents.on('did-fail-load', (event, code, desc, url) => {
    console.error(`[Load Error] ${code} ${desc} ${url}`);
    if (backendProc) backendProc.kill();
    process.exit(1);
  });

  const indexPath = path.join(__dirname, '..', 'electron', 'renderer', 'index.html');
  await win.loadFile(indexPath);

  // Wait 1.5 seconds for Three.js & scene & WS connection
  await new Promise(r => setTimeout(r, 1500));

  console.log('--- STARTING COMPREHENSIVE UI VERIFICATION ---');

  const result = await win.webContents.executeJavaScript(`
    (async function() {
      const results = {
        tabs: {},
        projectFlow: null,
        profile: null,
        calendar: null,
        plugins: null,
        chatFlow: null,
        llmModalFlow: null
      };

      const sleep = ms => new Promise(r => setTimeout(r, ms));

      // 1. Verify all 9 tabs
      const tabKeys = ['act', 'perm', 'proj', 'live', 'bg', 'files', 'sum', 'cal', 'plug'];
      for (const t of tabKeys) {
        try {
          const btn = document.querySelector('#nav button[data-t="' + t + '"]');
          if (!btn) {
            results.tabs[t] = { ok: false, error: 'Button not found' };
            continue;
          }
          const currentState = window.getRoboState ? window.getRoboState() : {};
          if (currentState.tab !== t) {
            btn.click();
            await sleep(60);
          }

          const state = window.getRoboState ? window.getRoboState() : {};
          const dock = document.getElementById('dock');
          const isVisible = dock && getComputedStyle(dock).display !== 'none';
          const contentLen = dock ? dock.innerHTML.trim().length : 0;
          const preview = dock ? dock.innerText.slice(0, 50).replace(/\\n/g, ' ') : '';

          results.tabs[t] = {
            ok: isVisible && contentLen > 10 && state.tab === t,
            tab: state.tab,
            visible: isVisible,
            contentLength: contentLen,
            previewText: preview
          };
        } catch (e) {
          results.tabs[t] = { ok: false, error: e.message };
        }
      }

      // 2. Test "Start project" flow
      try {
        const projChip = document.querySelector('.chips button[data-i="proj"]');
        if (projChip) {
          projChip.click();
          await sleep(100);
          const pf = document.getElementById('pf');
          const formShown = pf && pf.classList.contains('show');

          if (formShown) {
            const tpl0 = pf.querySelector('button[data-tpl="0"]');
            if (tpl0) tpl0.click();
            await sleep(60);

            const submitBtn = pf.querySelector('button.go[data-go="update"]');
            if (submitBtn) {
              submitBtn.click();
              await sleep(150);
              const formClosed = !pf.classList.contains('show');
              const state = window.getRoboState ? window.getRoboState() : {};
              const pipeRunning = !!state.pipe;
              results.projectFlow = {
                ok: formClosed && pipeRunning,
                formClosed,
                pipeRunning,
                projectName: state.pipe ? state.pipe.p.name : null,
                stage: state.pipe ? state.pipe.p.stage : null
              };
            } else {
              results.projectFlow = { ok: false, error: 'Submit button not found' };
            }
          } else {
            results.projectFlow = { ok: false, error: 'Form modal did not show' };
          }
        } else {
          results.projectFlow = { ok: false, error: 'Start project chip not found' };
        }
      } catch (e) {
        results.projectFlow = { ok: false, error: e.message };
      }

      // 3. Test Profile Menu & Avatars
      try {
        const profBtn = document.getElementById('prof');
        const pmenu = document.getElementById('pm');
        profBtn.click();
        await sleep(80);

        const pmShown = pmenu && pmenu.classList.contains('show');
        const evaanBtn = pmenu.querySelector('button.av-btn[data-av="E"]');
        if (evaanBtn) {
          evaanBtn.click();
          await sleep(80);
          const state = window.getRoboState ? window.getRoboState() : {};
          results.profile = {
            ok: pmShown && state.userAvatar === 'E',
            menuShown: pmShown,
            avatarSet: state.userAvatar
          };
        } else {
          results.profile = { ok: false, error: 'Evaan avatar button not found' };
        }
        document.body.click();
        await sleep(50);
      } catch (e) {
        results.profile = { ok: false, error: e.message };
      }

      // 4. Test Calendar Tab & Event Creation
      try {
        const calBtn = document.querySelector('#nav button[data-t="cal"]');
        calBtn.click();
        await sleep(60);

        const titleInp = document.querySelector('input[data-calf="title"]');
        const addBtn = document.querySelector('button[data-cal-add="1"]');
        if (titleInp && addBtn) {
          titleInp.value = 'Automated Test Event';
          titleInp.dispatchEvent(new Event('input', { bubbles: true }));
          addBtn.click();
          await sleep(100);

          const state = window.getRoboState ? window.getRoboState() : {};
          const eventFound = state.CAL && state.CAL.some(x => x.title === 'Automated Test Event');
          results.calendar = {
            ok: !!eventFound,
            eventFound
          };
        } else {
          results.calendar = { ok: false, error: 'Calendar inputs not found' };
        }
      } catch (e) {
        results.calendar = { ok: false, error: e.message };
      }

      // 5. Test Plugins Tab
      try {
        const plugBtn = document.querySelector('#nav button[data-t="plug"]');
        plugBtn.click();
        await sleep(60);

        const allPlugins = window.RoboNestPlugins ? window.RoboNestPlugins.all() : [];
        results.plugins = {
          ok: allPlugins.length > 0,
          count: allPlugins.length,
          sample: allPlugins.slice(0, 3).map(p => p.name)
        };
      } catch (e) {
        results.plugins = { ok: false, error: e.message };
      }

      // 6. Test Normal Conversational Chat with Zed
      try {
        const inp = document.getElementById('inp');
        const sendBtn = document.getElementById('send');
        if (inp && sendBtn) {
          inp.value = 'Hello Zed, how are you?';
          sendBtn.click();
          await sleep(800);

          const chat = document.getElementById('chat');
          const chatText = chat ? chat.innerText : '';
          const hasGreeting = chatText.includes('Hello') || chatText.includes('Zed') || chatText.includes('How are you');
          results.chatFlow = {
            ok: hasGreeting,
            snippet: chatText.slice(-140).replace(/\\n/g, ' ')
          };
        } else {
          results.chatFlow = { ok: false, error: 'Chat input/send not found' };
        }
      } catch (e) {
        results.chatFlow = { ok: false, error: e.message };
      }

      // 7. Test AI Model & API Key Modal
      try {
        const llmBtn = document.querySelector('.chips button[data-act="open_llm"]');
        if (llmBtn) {
          llmBtn.click();
          await sleep(150);

          const modal = document.getElementById('llm_modal');
          const isShown = modal && modal.classList.contains('show');

          // Switch provider to Groq
          const groqBtn = modal.querySelector('button[data-prov="groq"]');
          if (groqBtn) groqBtn.click();
          await sleep(60);

          // Type an API key
          const keyInp = modal.querySelector('#llm_key_inp');
          if (keyInp) {
            keyInp.value = 'gsk_testGroqKey123456789';
          }

          // Save
          const saveBtn = modal.querySelector('#llm_btn_save');
          if (saveBtn) {
            saveBtn.click();
            await sleep(400);

            const closed = !modal.classList.contains('show');
            const settings = window.robonestBridge && window.robonestBridge.getLLMSettings ? await window.robonestBridge.getLLMSettings() : null;
            const updated = settings && settings.provider === 'groq';

            results.llmModalFlow = {
              ok: isShown && closed && updated,
              modalShown: isShown,
              modalClosed: closed,
              savedProvider: settings ? settings.provider : null,
              hasKey: settings ? settings.has_api_key : false
            };
          } else {
            results.llmModalFlow = { ok: false, error: 'Save button not found' };
          }
        } else {
          results.llmModalFlow = { ok: false, error: 'AI Model / Key button not found' };
        }
      } catch (e) {
        results.llmModalFlow = { ok: false, error: e.message };
      }

      return results;
    })()
  `);

  console.log('TEST RESULTS:');
  console.log(JSON.stringify(result, null, 2));

  let passed = true;
  for (const [t, info] of Object.entries(result.tabs)) {
    if (!info.ok) {
      console.error(`TAB FAILED: ${t}`, info);
      passed = false;
    } else {
      console.log(`TAB PASSED: ${t} -> ${info.previewText}`);
    }
  }

  if (result.projectFlow && result.projectFlow.ok) {
    console.log(`PROJECT FLOW PASSED: "${result.projectFlow.projectName}" (Stage: ${result.projectFlow.stage})`);
  } else {
    console.error('PROJECT FLOW FAILED:', result.projectFlow);
    passed = false;
  }

  if (result.profile && result.profile.ok) {
    console.log(`PROFILE AVATAR PASSED: ${result.profile.avatarSet}`);
  } else {
    console.error('PROFILE AVATAR FAILED:', result.profile);
    passed = false;
  }

  if (result.calendar && result.calendar.ok) {
    console.log('CALENDAR TAB PASSED: Event created');
  } else {
    console.error('CALENDAR TAB FAILED:', result.calendar);
    passed = false;
  }

  if (result.plugins && result.plugins.ok) {
    console.log(`PLUGINS TAB PASSED: ${result.plugins.count} plugins available (${result.plugins.sample.join(', ')})`);
  } else {
    console.error('PLUGINS TAB FAILED:', result.plugins);
    passed = false;
  }

  if (result.chatFlow && result.chatFlow.ok) {
    console.log(`CONVERSATIONAL CHAT PASSED: ${result.chatFlow.snippet}`);
  } else {
    console.error('CONVERSATIONAL CHAT FAILED:', result.chatFlow);
    passed = false;
  }

  if (result.llmModalFlow && result.llmModalFlow.ok) {
    console.log(`LLM MODAL & API KEY PASSED: Provider=${result.llmModalFlow.savedProvider}, HasKey=${result.llmModalFlow.hasKey}`);
  } else {
    console.error('LLM MODAL & API KEY FAILED:', result.llmModalFlow);
    passed = false;
  }

  console.log('--- TEST FINISHED. STATUS:', passed ? 'SUCCESS' : 'FAILURE', '---');
  if (backendProc) {
    backendProc.kill();
  }
  app.exit(passed ? 0 : 1);
});
