const { app, BrowserWindow, ipcMain } = require('electron');
const path = require('path');
const http = require('http');
const { spawn } = require('child_process');

let mainWindow = null;
let backendProcess = null;
const BACKEND_PORT = 8765;

function checkBackendHealth(callback) {
  const req = http.get(`http://127.0.0.1:${BACKEND_PORT}/api/health`, (res) => {
    if (res.statusCode === 200) {
      callback(true);
    } else {
      callback(false);
    }
  });
  req.on('error', () => callback(false));
  req.setTimeout(1000, () => {
    req.destroy();
    callback(false);
  });
}

function startBackend() {
  checkBackendHealth((isAlive) => {
    if (isAlive) {
      console.log('[Electron] Backend is already running and active.');
      return;
    }

    const pythonBin = process.platform === 'win32' ? 'python' : 'python3';
    const backendCwd = path.join(__dirname, '..');

    console.log(`[Electron] Launching Python backend from ${backendCwd}...`);
    backendProcess = spawn(pythonBin, ['-m', 'backend.main'], {
      cwd: backendCwd,
      env: { ...process.env, PYTHONUNBUFFERED: '1' },
      stdio: 'pipe'
    });

    backendProcess.stdout.on('data', (data) => {
      console.log(`[Backend stdout] ${data.toString().trim()}`);
    });

    backendProcess.stderr.on('data', (data) => {
      console.error(`[Backend stderr] ${data.toString().trim()}`);
    });

    backendProcess.on('close', (code) => {
      console.log(`[Electron] Backend process exited with code ${code}`);
    });

  });
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 880,
    minWidth: 960,
    minHeight: 600,
    title: 'RoboNest AI Office',
    backgroundColor: '#14110f',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      nodeIntegration: false,
      contextIsolation: true
    }
  });

  mainWindow.webContents.on('console-message', (event, level, message, line, sourceId) => {
    console.log(`[Renderer Console] ${message} (${sourceId}:${line})`);
  });
  mainWindow.webContents.on('did-fail-load', (event, code, description, url) => {
    console.error(`[Electron] UI failed to load (${code}: ${description}): ${url}`);
  });
  const localFile = path.join(__dirname, 'renderer', 'index.html');

  // Show the bundled renderer immediately. The backend is only needed for
  // live data and commands, so its startup must not decide whether the UI loads.
  mainWindow.loadFile(localFile).catch((error) => {
    console.error('[Electron] Could not load the local RoboNest UI:', error);
  });
  startBackend();

  mainWindow.on('closed', () => {
    mainWindow = null;
  });
}

app.whenReady().then(() => {
  createWindow();

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) {
      createWindow();
    }
  });
});

app.on('before-quit', () => {
  if (backendProcess) {
    console.log('[Electron] Shutting down backend process...');
    backendProcess.kill('SIGTERM');
  }
});

app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});
