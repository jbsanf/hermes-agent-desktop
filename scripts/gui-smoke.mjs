#!/usr/bin/env node
// Run under xvfb-run/dbus-run-session, or an existing desktop session.
import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { mkdir, writeFile, open } from 'node:fs/promises';
import { homedir } from 'node:os';
import path from 'node:path';
import net from 'node:net';
import { startProvider } from '../tests/mock-provider.mjs';

const app = 'io.github.jbsanf.HermesDesktop';
const root = path.join(homedir(), '.var/app', app, 'data', `gui-smoke-${Date.now()}`);
await mkdir(root, { recursive: true });
const provider = await startProvider();
const hermesHome = path.join(root, 'data/hermes');
await mkdir(hermesHome, { recursive: true });
await writeFile(path.join(hermesHome, 'config.yaml'), `model:
  default: mock-model
  provider: mock
providers:
  mock:
    api: ${provider.url}/v1
    name: Mock
    api_mode: chat_completions
    key_env: MOCK_API_KEY
    models:
      mock-model: {}
    context_length: 64000
auxiliary:
  title_generation:
    enabled: false
security:
  tirith_enabled: false
approvals:
  mode: manual
`);
await writeFile(path.join(hermesHome, '.env'), 'MOCK_API_KEY=local-test-not-a-secret\n', { mode: 0o600 });
const server = net.createServer();
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const port = server.address().port;
await new Promise(resolve => server.close(resolve));
const log = await open(path.join(root, 'electron.log'), 'w');
// Xvfb needs X11 even if the outer environment also exposes a Wayland socket.
const args = ['run', '--user', '--die-with-parent', '--instance-id-fd=3', '--nosocket=wayland', '--socket=x11', '--command=sh',
  app, '-c', 'export XDG_DATA_HOME="$1/data" XDG_CONFIG_HOME="$1/config" XDG_CACHE_HOME="$1/cache"; shift; exec /app/bin/hermes-desktop "$@"', 'sh', root, '--skip-intro', '--ozone-platform=x11', '--disable-gpu', `--remote-debugging-port=${port}`, '--remote-debugging-address=127.0.0.1'];
const cleanEnv = Object.fromEntries(Object.entries(process.env).filter(([key]) =>
  !/(_KEY|_TOKEN|_SECRET|_PASSWORD|_PASSPHRASE|_CREDENTIALS|_BASE_URL)$/.test(key) && !/^_?HERMES_/.test(key)));
const child = spawn('flatpak', args, { stdio: ['ignore', log.fd, log.fd, 'pipe'], env: cleanEnv });
let instance = '';
child.stdio[3].on('data', data => { instance += data.toString(); });
let socket;
let nextId = 0;
const pending = new Map();
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
function call(method, params = {}) {
  const id = ++nextId;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => { pending.delete(id); reject(new Error(`CDP timeout: ${method}`)); }, 60000);
    pending.set(id, { resolve, reject, timer });
    socket.send(JSON.stringify({ id, method, params }));
  });
}
async function evaluate(expression) {
  const result = await call('Runtime.evaluate', { expression, awaitPromise: true, returnByValue: true });
  if (result.exceptionDetails) throw new Error(JSON.stringify(result.exceptionDetails));
  return result.result.value;
}
try {
  let target;
  const deadline = Date.now() + 90000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) throw new Error(`Electron exited: ${child.exitCode}; see ${root}`);
    try {
      const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      target = targets.find(t => t.type === 'page' && t.url.startsWith('file:'));
      if (target) break;
    } catch {}
    await sleep(500);
  }
  assert(target, `No application window; see ${root}`);
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.addEventListener('open', resolve); socket.addEventListener('error', reject); });
  socket.addEventListener('message', event => {
    const message = JSON.parse(event.data);
    const task = pending.get(message.id);
    if (!task) return;
    clearTimeout(task.timer);
    pending.delete(message.id);
    if (message.error) task.reject(new Error(JSON.stringify(message.error)));
    else task.resolve(message.result);
  });
  let text = '';
  while (Date.now() < deadline) {
    text = await evaluate("document.body?.innerText ?? ''");
    if (text.trim().length > 80 && await evaluate('Boolean(window.hermesDesktop?.updates)')) break;
    await sleep(500);
  }
  assert(text.trim().length > 80, 'Renderer did not paint usable content');
  const connection = await evaluate('window.hermesDesktop.getConnection().then(c => ({mode:c.mode, baseUrl:c.baseUrl}))');
  assert.equal(connection.mode, 'local');
  assert.match(connection.baseUrl, /^http:\/\/127\.0\.0\.1:\d+$/);
  const status = await evaluate('window.hermesDesktop.updates.check({force: true})');
  assert.equal(status.supported, false);
  assert.equal(status.reason, 'flatpak-managed');
  const rejection = await evaluate('window.hermesDesktop.updates.apply()');
  assert.equal(rejection.ok, false);
  assert.match(rejection.message, /Flatpak/);
  const repair = await evaluate("window.hermesDesktop.repairBootstrap().then(() => 'allowed', error => String(error))");
  assert.match(repair, /Flatpak/);
  const terminal = await evaluate("window.hermesDesktop.openSessionInTerminal('test').then(r => r.ok)");
  assert.equal(terminal, false);
  const composer = '[data-slot="composer-root"] [contenteditable="true"]';
  const chatDeadline = Date.now() + 90000;
  while (!(await evaluate(`Boolean(document.querySelector(${JSON.stringify(composer)}))`))) {
    assert(Date.now() < chatDeadline, 'Chat composer did not become available');
    await sleep(500);
  }
  await evaluate(`document.querySelector(${JSON.stringify(composer)}).focus()`);
  await call('Input.insertText', { text: 'Please reply to this Flatpak integration test.' });
  await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  await call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
  while (true) {
    text = await evaluate("document.body?.innerText ?? ''");
    if (text.includes(provider.answer)) break;
    // The renderer retains the draft while its gateway reconnects.
    if (await evaluate(`document.querySelector(${JSON.stringify(composer)})?.textContent.includes('Please reply to this Flatpak integration test.')`)) {
      await call('Input.dispatchKeyEvent', { type: 'keyDown', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
      await call('Input.dispatchKeyEvent', { type: 'keyUp', key: 'Enter', code: 'Enter', windowsVirtualKeyCode: 13 });
    }
    assert(Date.now() < chatDeadline, `No streamed reply; provider requests=${provider.requests.length}; see ${root}`);
    await sleep(500);
  }
  assert(provider.requests.some(r => r.stream), 'No streaming model call was made');
  const screenshot = await call('Page.captureScreenshot', { format: 'png' });
  await writeFile(path.join(root, 'window.png'), Buffer.from(screenshot.data, 'base64'));
  await writeFile(path.join(root, 'renderer.txt'), text);
  await evaluate('window.hermesDesktop.windowControls.close()');
  const closeDeadline = Date.now() + 30000;
  while (child.exitCode === null && child.signalCode === null && Date.now() < closeDeadline) await sleep(250);
  assert(child.exitCode !== null || child.signalCode !== null, 'Application did not exit after closing the window');
  console.log(`PASS: normal window close; real renderer, local backend, streamed chat, preload IPC and Flatpak update policy. Evidence: ${root}`);
} finally {
  if (socket?.readyState === WebSocket.OPEN) {
    await evaluate("document.body?.innerText ?? ''").then(text => writeFile(path.join(root, 'renderer.txt'), text)).catch(() => {});
    const shot = await call('Page.captureScreenshot', { format: 'png' }).catch(() => null);
    if (shot) await writeFile(path.join(root, 'window.png'), Buffer.from(shot.data, 'base64'));
  }
  socket?.close();
  for (const task of pending.values()) clearTimeout(task.timer);
  if (instance.trim()) spawnSync('flatpak', ['kill', instance.trim()]);
  child.kill('SIGTERM');
  if (child.exitCode === null && child.signalCode === null) await Promise.race([new Promise(resolve => child.once('exit', resolve)), sleep(10000)]);
  if (child.exitCode === null) child.kill('SIGKILL');
  await log.close();
  await provider.close();
}
