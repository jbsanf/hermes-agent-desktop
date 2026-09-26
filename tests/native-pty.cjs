// Exercise the module compiled for Electron's ABI inside the installed sandbox.
const pty = require('/app/lib/hermes-electron/resources/app/dist/node_modules/node-pty');
const terminal = pty.spawn('/bin/sh', ['-c', 'echo FLATPAK_PTY_OK'], {
  name: 'xterm', cols: 80, rows: 24, cwd: '/tmp', env: process.env,
});
let output = '';
const timer = setTimeout(() => { terminal.kill(); process.exit(1); }, 10000);
terminal.onData(data => { output += data; });
terminal.onExit(event => {
  clearTimeout(timer);
  console.log(output.trim());
  process.exit(event.exitCode === 0 && output.includes('FLATPAK_PTY_OK') ? 0 : 1);
});
