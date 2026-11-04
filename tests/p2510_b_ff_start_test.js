// kalmido-suite: nodata
// #4346: the start of Firefox in tests/ff.js with a stand-in for firefox, no browser and no server. CI of 2.496.1: p2151_ui, three
// starts "no WebDriver BiDi connection to Firefox". The second try ran on the profile of a first Firefox that had only got a SIGTERM
// and a second: one that hangs still holds the lock, so the second gave up at once. And nothing waited for the end of a Firefox.
// - a hanging Firefox is really gone before the next start, which has its own profile and connects
// - a Firefox that dies at once costs no wait for its connection
// - at the end nothing keeps running, also not one that ignores SIGTERM, and the folder is gone
// - all tries fail: one FAIL line that says how each try ended
const fs = require('fs'), os = require('os'), path = require('path');
const F = []; let ok = 0;
const check = (c, m) => { if (c) ok++; else { F.push(m); console.log('FAIL:', m); } };

const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'p2510b-')), bin = path.join(tmp, 'bin'), state = path.join(tmp, 'starts.log'), base = path.join(tmp, 'ff');
fs.mkdirSync(bin); fs.mkdirSync(base);
// The stand-in. FAKE_FF_PLAN: what each start does, in turn. hang: holds the lock of its profile, never listens, ignores SIGTERM.
// die: ends at once with an error. ok: ends with an error when the lock of its profile is held (as Firefox does), else answers BiDi.
// stubborn: as ok, but ignores SIGTERM.
fs.writeFileSync(path.join(bin, 'firefox'), `#!/usr/bin/env node
const fs = require('fs'), path = require('path'), a = process.argv.slice(2);
if (a[0] === '--version') process.exit(0);
const prof = a[a.indexOf('--profile') + 1], port = +a.find(x => x.startsWith('--remote-debugging-port=')).split('=')[1];
const log = process.env.FAKE_FF_LOG, n = fs.existsSync(log) ? fs.readFileSync(log, 'utf8').split('\\n').length - 1 : 0;
const what = process.env.FAKE_FF_PLAN.split(',')[n] || 'die', lock = path.join(prof, '.parentlock');
const alive = pid => { try { process.kill(pid, 0); return true; } catch { return false; } };
const held = fs.existsSync(lock) && alive(+fs.readFileSync(lock, 'utf8'));
fs.appendFileSync(log, JSON.stringify({pid: process.pid, prof, what, held, prev: n}) + '\\n');
if (what === 'die') process.exit(3);
if (what !== 'hang' && held) { console.error('Firefox is already running, but is not responding'); process.exit(1); }
fs.writeFileSync(lock, String(process.pid));
if (what === 'hang' || what === 'stubborn') process.on('SIGTERM', () => {});
if (what === 'hang') setInterval(() => {}, 1000);
else {
  const {WebSocketServer} = require(process.env.FAKE_FF_WS);
  new WebSocketServer({port, host: '127.0.0.1', path: '/session'}).on('connection', w => w.on('message', m => {
    const {id, method} = JSON.parse(m);
    w.send(JSON.stringify({id, type: 'success', result: method === 'browsingContext.getTree' ? {contexts: [{context: 'c1'}]} : {}}));
  }));
}
`, {mode: 0o755});
process.env.PATH = bin + path.delimiter + process.env.PATH;
process.env.TMPDIR = base;
process.env.FAKE_FF_LOG = state;
process.env.FAKE_FF_WS = require.resolve('ws');

const alive = pid => { try { process.kill(pid, 0); return true; } catch { return false; } };
const run = async (plan, connectS) => {
  fs.rmSync(state, {force: true});
  process.env.FAKE_FF_PLAN = plan;
  const fails = []; let ran = false, pidsAtFn = null;
  const firefox = require('./ff')({tag: 'p2510b', check: (c, m) => { if (!c) fails.push(m); }, connectS});
  const t0 = performance.now();
  await firefox(async o => { ran = !!o.ctx; pidsAtFn = starts().filter(s => alive(s.pid)).length; });
  return {fails, ran, pidsAtFn, secs: (performance.now() - t0) / 1000, starts: starts()};
};
const starts = () => fs.readFileSync(state, 'utf8').trim().split('\n').map(l => JSON.parse(l));
const left = () => fs.readdirSync(base);

(async () => {
  // 1. a Firefox that hangs: gone before the next one, which has its own profile and connects
  let r = await run('hang,ok', [1, 20]);
  check(r.ran && !r.fails.length, 'hang, then a new start: connected: ' + r.fails.join(' | '));
  check(r.starts.length === 2 && r.starts[0].prof !== r.starts[1].prof && !r.starts[1].held, 'the second start has its own profile, no lock of the first: ' + JSON.stringify(r.starts));
  check(r.pidsAtFn === 1, `only the new Firefox is alive when the test begins (was ${r.pidsAtFn})`);
  check(r.starts.every(s => !alive(s.pid)), 'both have ended afterwards');
  check(!left().length, 'the folder is gone: ' + left());

  // 2. a Firefox that dies at once: no wait for its connection (the limit is far away)
  r = await run('die,ok', [60, 20]);
  check(r.ran && !r.fails.length, 'die, then a new start: connected: ' + r.fails.join(' | '));
  check(r.secs < 30, `a dead Firefox costs no wait: ${Math.round(r.secs)} s`);

  // 3. at the end: one that ignores SIGTERM does not stay behind
  r = await run('stubborn', [20]);
  check(r.ran && !r.fails.length, 'stubborn: connected: ' + r.fails.join(' | '));
  check(!alive(r.starts[0].pid), 'a Firefox that ignores SIGTERM has ended after the test');
  check(!left().length, 'its folder is gone: ' + left());

  // 4. all tries fail: one FAIL line that says how each try ended
  r = await run('die,hang,die', [10, 1, 10]);
  check(!r.ran && r.starts.length === 3, `every try is made: ${r.starts.length}`);
  check(r.fails.length === 1 && /no WebDriver BiDi connection/.test(r.fails[0]) && /exit 3.*SIGKILL.*exit 3/.test(r.fails[0]), 'the FAIL line says how each try ended: ' + r.fails.join(' | '));
  check(r.starts.every(s => !alive(s.pid)) && !left().length, 'nothing stays behind after a failed start');

  fs.rmSync(tmp, {recursive: true, force: true});
  console.log(`p2510_b_ff_start: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
