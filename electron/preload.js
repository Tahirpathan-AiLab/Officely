const { contextBridge } = require('electron');

contextBridge.exposeInMainWorld('robonest', {
  backendUrl: 'http://127.0.0.1:8765',
  wsUrl: 'ws://127.0.0.1:8765/ws',
  version: '1.0.0',
  platform: process.platform
});
