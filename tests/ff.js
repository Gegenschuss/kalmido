// ff.js -- Firefox headless driven over WebDriver BiDi, shared by the UI suites that check the real layout (2.7.2: one copy
// instead of one per suite). 2.501.0 (#4296): no firefox on PATH = a failed check (it used to end green with only a log line);
// KALMIDO_SKIP_FIREFOX=1 leaves the browser part out on purpose, with a line that run_all.sh counts as partly skipped.
//   const firefox = require('./ff')({tag: 'p272', check, shots: 'P272_SHOTS'});
//   await firefox(async ({cmd, ev, nav, ctx, shot, drag, until, idle, officeWs}) => { ... }, touch);
// touch: true = a touch screen (coarse pointer, touch events); false or left out = a mouse (fine pointer, hover). 2.725.0 (#5169):
// left out used to be Firefox's own values - headless without an input device that is hover: none, the app's finger mode, so most
// suites checked the finger UI unnoticed and the mouse UI not at all; a suite that means a finger passes touch: true.
// A Firefox that does not answer in time (seen on CI runners) gets new tries on another port with a new profile (2.7.1, first in
// p221; #4346: connectS, the seconds each try waits). Every Firefox has really ended before the next one starts and before its
// folder goes; a Firefox that ended by itself with an error costs no wait.
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path'), net = require('net');
const WS = globalThis.WebSocket || require('ws');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const {clockOffset, shiftedDate, B} = require('./boot');  // 2.381.0 (#2713)
// 2.284.0 A (#3120): a port the system hands out free - a random one of 9300-9899 could be the port of another suite's Firefox
// on the same machine (parallel places / shards): the connection went to that one ("session.new: Maximum number of active sessions")
const freePort = () => new Promise(res => { const s = net.createServer(); s.on('error', () => res(9300 + Math.floor(Math.random() * 600)));
  s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });

// 2.358.0 C (#2782): the request counter, run in the page (script.addPreloadScript) - keep it free of outer names
const NET = () => {
  if (window.__net) return;
  const net = window.__net = {n: 0, at: performance.now(), open: new Map()}; let k = 0;
  const begin = u => { const id = ++k; net.n++; net.at = performance.now(); net.open.set(id, String(u).slice(0, 120)); return id; };
  const end = id => { if (!net.open.delete(id)) return; net.n--; net.at = performance.now(); };
  const f0 = window.fetch;
  if (f0) window.fetch = function (u, o) { const id = begin(u && u.url || u), p = f0.apply(this, arguments); p.then(() => end(id), () => end(id)); return p; };
  const X = window.XMLHttpRequest && window.XMLHttpRequest.prototype;
  if (X) { const open = X.open, send = X.send;
    X.open = function (m, u) { this.__u = u; return open.apply(this, arguments); };
    X.send = function () { const id = begin(this.__u); this.addEventListener('loadend', () => end(id), {once: true});
      try { return send.apply(this, arguments); } catch (e) { end(id); throw e; } }; }
};

// 2.501.0 (#4296): true = no browser part in this run, the caller returns; the suites with an own firefox() use it too
// 2.726.0 (#5160): fine pointer that can hover (6 = fine | hover); also for the suites with their own Firefox start (p230, p240 ...)
const MOUSE_PREFS = [['ui.primaryPointerCapabilities', 6], ['ui.allPointerCapabilities', 6]];
const noFirefox = (tag, check) => {
  if (process.env.KALMIDO_SKIP_FIREFOX === '1') { console.log(`${tag}: Firefox part skipped (KALMIDO_SKIP_FIREFOX=1)`); return true; }
  try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); return false; } catch { check(false, `${tag}: no firefox on PATH, the browser part cannot run (KALMIDO_SKIP_FIREFOX=1 leaves it out on purpose)`); return true; }
};

// prefs: extra Firefox preferences for one suite (2.13.0)
// 2.53.0 (#1410): nav() loads the modules the app loads on demand (settings, contacts, office) after each page load, so
// suites can call their functions directly; lazy: true leaves them to the app (tests/p253_a_ui.js)
// 2.543.0 (#4606): "All workspaces" with Private + exactly one organisation shows the overview of the areas in the office; the
// suites written before open the office the server chose there (that organisation's). nav() to an address #office... saves that
// workspace first, from the page that is open (it holds the login), like boot.js officeWs - only in exactly this case - and the
// next nav() to another address puts "All" back (if it is still that workspace), so the other views stay as the suite knew them
// (p21383_a: the bookmarks after the cash flow). allWs: true leaves it out (a suite of the overview); a suite that walks into the
// office by a click calls officeWs() itself (that one stays).
const WS_IN_PAGE = `async (to) => {
  const B = ${JSON.stringify(B)}; if (!location.href.startsWith(B)) return false;
  const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
  const j = await (await fetch(B + 'api/state', {headers: H})).json().catch(() => ({}));
  const ws = (j.me && j.me.workspaces) || [], cur = (j.settings && j.settings.workspace) || 'all';
  if (to) { if (cur !== to) return false; to = 'all'; }
  else if (!j.workspaces || ws.length !== 1 || /^(private|org:\\d+)$/.test(cur)) return false;
  else to = 'org:' + ws[0].id;
  return (await fetch(B + 'api/settings', {method: 'PATCH', headers: H, body: JSON.stringify({workspace: to})})).ok && to;
}`;
module.exports = ({tag, check, shots, prefs: extra = [], lazy = false, connectS = [45, 60, 90], allWs = false}) => async function firefox(fn, touch) {
  if (noFirefox(tag, check)) return;
  const base = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), `kalmido-${tag}-`));
  const prefs = [['browser.shell.checkDefaultBrowser', false], ['datareporting.policy.dataSubmissionEnabled', false], ['ui.prefersReducedMotion', 1],
    ...(touch === true ? [['ui.primaryPointerCapabilities', 1], ['ui.allPointerCapabilities', 1], ['dom.w3c_touch_events.enabled', 1]]
      : MOUSE_PREFS), ...extra];
  const userJs = prefs.map(([k, v]) => `user_pref("${k}", ${JSON.stringify(v)});`).join('\n') + '\n';
  // CI of 2.496.1: three starts of p2151_ui stayed without a connection and nothing said why: Firefox's messages go to a file, each
  // start notes how it ended, and the FAIL line carries it all (run_all.sh shows only FAIL lines)
  const errFile = path.join(base, 'firefox-stderr.txt'), tries = [];
  const start = port => {
    // #4346: an own profile per start: a Firefox that hangs still holds the lock of its profile, the next one on it gave up at once
    const prof = path.join(base, `profile-${tries.length}`);
    fs.mkdirSync(prof); fs.writeFileSync(path.join(prof, 'user.js'), userJs);
    const err = fs.openSync(errFile, 'a'), t = {at: performance.now(), end: 'still running', failed: false};
    const c = spawn('firefox', ['--headless', '--no-remote', '--profile', prof, `--remote-debugging-port=${port}`, 'about:blank'], {stdio: ['ignore', 'ignore', err]});
    fs.closeSync(err);
    c.ended = new Promise(res => {
      c.on('error', e => { t.end = `start failed: ${e.message}`; t.failed = true; res(); });
      c.on('exit', (code, sig) => { t.end = `ended after ${Math.round((performance.now() - t.at) / 1000)} s (${sig || 'exit ' + code})`; t.failed = code !== 0; res(); });
    });
    tries.push(t);
    return c;
  };
  const why = () => {
    let err = ''; try { err = fs.readFileSync(errFile, 'utf8').replace(/\s+/g, ' ').trim().slice(-400); } catch { /* none */ }
    return `tries: ${tries.map(t => t.end).join('; ')}; load ${os.loadavg()[0].toFixed(1)} on ${os.cpus().length} CPUs, ${Math.round(os.freemem() / 1048576)} MB free; stderr: ${err || '(empty)'}`;
  };
  // #4346: wait until this Firefox has really ended. One that hangs ignores SIGTERM, keeps its memory and CPU for the next start
  // (and the rest of the shard) and writes into a folder that is going away. hard: it never answered, nothing to shut down cleanly.
  const stop = async (c, hard = false) => {
    const gone = ms => new Promise(res => { const k = setTimeout(() => res(false), ms); c.ended.then(() => { clearTimeout(k); res(true); }); });
    if (!hard) { try { c.kill(); } catch { /* gone */ } if (await gone(5000)) return; }
    try { c.kill('SIGKILL'); } catch { /* gone */ }
    await gone(5000);
  };
  let PORT = await freePort(), ff = start(PORT);
  let ws, seq = 0; const pend = new Map();
  const connect = async (s = connectS[0]) => {
    const end = performance.now() + s * 1000, t = tries[tries.length - 1];
    while (!ws && !t.failed && performance.now() < end) {
      try { const w = new WS(`ws://127.0.0.1:${PORT}/session`); await new Promise((res, rej) => { w.onopen = res; w.onerror = rej; }); ws = w; } catch { await sleep(500); }
    }
  };
  const restart = async () => { await stop(ff, true); PORT = await freePort(); ff = start(PORT); };
  try {
    for (let attempt = 0; attempt < connectS.length && !ws; attempt++) {
      if (attempt) await restart();
      await connect(connectS[attempt]);
    }
    if (!ws) { check(false, `no WebDriver BiDi connection to Firefox (${why()})`); return; }
    const onmsg = m => { const j = JSON.parse(m.data); if (j.id && pend.has(j.id)) { const p = pend.get(j.id); pend.delete(j.id); j.type === 'error' ? p.rej(new Error(p.method + ': ' + j.error + ' ' + j.message)) : p.res(j.result); } };
    ws.onmessage = onmsg;
    // 2.27.0: a command that never answers (a hung page, a promise that never settles) fails after 120 s with its name and
    // what it ran, instead of stalling the whole CI shard until the job's time limit
    const cmd = (method, params = {}, ms = 120000) => new Promise((res, rej) => {
      const id = ++seq, t = setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error(`${method}: no answer within ${ms / 1000} s ` + String(params.expression || params.url || '').slice(0, 160))); } }, ms);
      pend.set(id, {res: v => { clearTimeout(t); res(v); }, rej: e => { clearTimeout(t); rej(e); }, method}); ws.send(JSON.stringify({id, method, params}));
    });
    const unwrap = v => !v ? v : v.type === 'array' ? v.value.map(unwrap) : v.type === 'object' ? Object.fromEntries(v.value.map(([k, x]) => [typeof k === 'string' ? k : unwrap(k), unwrap(x)])) : v.value;
    // 2.284.0 A (#3120): still someone else's Firefox (it took the port first) -> once more with an own Firefox on a new port
    await cmd('session.new', {capabilities: {}}).catch(async e => {
      if (!/Maximum number of active sessions/.test(e.message)) throw e;
      console.log(`ff: port ${PORT} answered with another Firefox's session, a new Firefox on another port`);
      try { ws.close(); } catch { /* gone */ }
      ws = null; await restart();
      await connect();
      if (!ws) throw e;
      ws.onmessage = onmsg;
      await cmd('session.new', {capabilities: {}});
    });
    // 2.381.0 (#2713): the test clock in Firefox too - with KALMIDO_TEST_NOW (run_all.sh `now …`) every page gets the shifted
    // Date of boot.js before its own scripts (only "now" moves; time zone, timers and dates with arguments stay; workers keep
    // the real clock)
    if (clockOffset) await cmd('script.addPreloadScript', {functionDeclaration: `() => { window.Date = (${shiftedDate})(window.Date, ${clockOffset}); }`});
    const ctx = (await cmd('browsingContext.getTree', {})).contexts[0].context;
    // 2.358.0 C (#2782): count the page's open requests (fetch + XMLHttpRequest) as window.__net = {n, at, open} like boot.js does
    // for jsdom - a preload script runs in every new document before the app's own scripts, so idle() works after each nav()
    await cmd('script.addPreloadScript', {functionDeclaration: NET.toString()}).catch(e => console.log('ff: no preload script, idle() waits by time only:', e.message));
    const ev = async expr => { const r = await cmd('script.evaluate', {expression: expr, target: {context: ctx}, awaitPromise: true, resultOwnership: 'none', serializationOptions: {maxObjectDepth: 6}}); if (r.type === 'exception') throw new Error('JS: ' + r.exceptionDetails.text); return unwrap(r.result); };
    // 2.161.2 CI fix: on a slow runner a navigate now and then never answers (an earlier page load that commits late swallows
    // it: p2100_ui, p21144_d_ui, p270_ui) - after 40 s the same navigate once more instead of 120 s and a failed suite
    let wsBack = false;  // 2.543.0 (#4606): the workspace nav() set for the office, put back to "All" on the next other address
    const wsSet = to => ev(`(${WS_IN_PAGE})(${JSON.stringify(to)})`).catch(() => false);
    const officeWs = () => wsSet(null);
    const nav = async url => {
      let r;
      // 2.543.0 (#4606): an app already open here keeps the old workspace in memory on a mere change of the hash: a new load after a change
      if (!allWs && !/static\/icon\.svg/.test(String(url))) {
        const office = /#office(\/|$)/.test(String(url)), to = office ? await officeWs() : wsBack && await wsSet(wsBack);
        if (office ? to : wsBack) wsBack = office && to;
        if (to && !/static\/icon\.svg/.test(await ev('location.href').catch(() => ''))) await cmd('browsingContext.navigate', {context: ctx, url: B + 'static/icon.svg', wait: 'complete'}, 40000);
      }
      for (let k = 0; ; k++) {
        try { r = await cmd('browsingContext.navigate', {context: ctx, url, wait: 'complete'}, k < 2 ? 40000 : 120000); break; } catch (e) {
          // CI red of 2.563.0 (p2120_a_ui): a navigate while the page still loads or goes somewhere itself (an app reacting to a new
          // sign-in, its own redirect) is answered NS_BINDING_ABORTED - the page's own load won; let it settle, then the same navigate again
          const aborted = /NS_BINDING_ABORTED/.test(e.message);
          if (k >= 2 || !(aborted || /no answer within/.test(e.message))) throw e;
          console.log(`ff: navigate ${String(url).slice(0, 120)} ${aborted ? 'was aborted by the page' : 'gave no answer in 40 s'}, once more`);
          if (aborted) for (let i = 0; i < 50 && !await ev(`document.readyState === 'complete'`).catch(() => false); i++) await sleep(100);
        }
      }
      // 2.501.0 (#4296): a module that does not load is red (the suite's later calls would only fail by chance); a page that
      // went away while it loaded (its own redirect or reload) is no load error. On purpose without the modules: lazy: true
      if (!lazy) {
        // under load a script fetch breaks off now and then (full run of 2.501: 19 suites, their own checks fine, alone green):
        // only a load that fails again, on a page that has settled, is a real one (a failed module may be retried, lazyload.js)
        for (let k = 0; ; k++) {
          const e = await ev(`typeof ld_all === 'function' ? ld_all().then(() => '', e => String(e && e.message || e)) : ''`).catch(x => {
            if (/^JS: |no answer within/.test(x.message)) return x.message;
            console.log(`ff: ${String(url).slice(0, 120)} went away during ld_all: ${x.message}`); return '';
          });
          if (!e) break;
          if (k >= 2) { check(false, `${tag}: ld_all failed on ${String(url).slice(0, 120)}: ${e}`); break; }
          console.log(`ff: ld_all on ${String(url).slice(0, 120)}: ${e}, once more`);
          for (let i = 0; i < 100 && !await ev(`document.readyState === 'complete'`).catch(() => false); i++) await sleep(100);
        }
      }
      return r;
    };
    const shot = async name => { const dir = shots && process.env[shots]; if (!dir) return; const r = await cmd('browsingContext.captureScreenshot', {context: ctx}); fs.writeFileSync(path.join(dir, name), Buffer.from(r.data, 'base64')); };
    // a drag with the mouse (desktop) or one finger (touch) from (x0, y0) by (dx, dy); hold = ms of a long press first
    const drag = (x0, y0, dx, dy, kind = 'mouse', hold = 0) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'p1', parameters: {pointerType: kind},
      actions: [{type: 'pointerMove', x: Math.round(x0), y: Math.round(y0)}, {type: 'pointerDown', button: 0}, ...(hold ? [{type: 'pause', duration: hold}] : []), {type: 'pointerMove', x: Math.round(x0 + dx / 2), y: Math.round(y0 + dy / 2), duration: 120},
        {type: 'pointerMove', x: Math.round(x0 + dx), y: Math.round(y0 + dy), duration: 120}, {type: 'pointerUp', button: 0}]}]}).then(() => cmd('input.releaseActions', {context: ctx}));
    // 2.358.0 C (#2782): wait for a state instead of a fixed sleep (like boot.js): until(expr | fn) polls a page expression (string,
    // a throw counts as false) or a function until it is truthy (-> that value) or timeout ms are over (-> the last value)
    const until = async (x, {timeout = 15000, step = 100} = {}) => {
      const end = performance.now() + timeout;
      for (;;) {
        const v = await Promise.resolve().then(() => typeof x === 'string' ? ev(x) : x()).catch(() => false);  // a plain (sync) fn too
        if (v || performance.now() >= end) return v;
        await sleep(step);
      }
    };
    // idle(): none of the page's requests in flight for `quiet` ms (at least `quiet` ms after the call, so a request the action
    // starts from a short timer is still seen), at most timeout ms (then it goes on and says what is still open). For an action
    // that loads; not for debounced saves or the app's own timers. Without the counter (no preload script) it waits `quiet` ms.
    const idle = async ({quiet = 250, timeout = 15000} = {}) => {
      const t0 = performance.now();
      const st = `(() => { const n = window.__net; return !n ? -1 : n.n ? -2 : performance.now() - n.at; })()`;
      const ok = await until(async () => { const q = await ev(st); return performance.now() - t0 >= quiet && (q === -1 || q >= quiet); }, {timeout, step: 50});
      if (!ok) console.log(`ff idle: still loading after ${timeout} ms:`, await ev(`[...(window.__net?.open?.values() || [])].slice(0, 5).join(' ')`).catch(() => '?'));
      return ok;
    };
    await fn({cmd, ev, nav, ctx, shot, drag, until, idle, officeWs});
  } catch (e) { check(false, 'Firefox: ' + e.message); } finally {
    try { ws && ws.close(); } catch { /* gone */ }
    await stop(ff);
    fs.rmSync(base, {recursive: true, force: true, maxRetries: 3});
  }
};

// 2.501.0 (#4282): a click as a person does it: the element comes into view, then the real pointer moves to its middle and presses
// (input.performActions, so the browser decides what is hit: a dialog in front of it takes the click, a script click would not
// notice). Pass what firefox() hands the suite. -> {ok, on}: ok = the element itself (or a child) lay under the pointer and was pressed;
// on = what lay there (something else: nothing is pressed, the suite reports it).
//   const {realClick} = require('./ff');  const r = await realClick(o, '#side [data-ofm="bank"]');  check(r.ok, r.on);
module.exports.realClick = async ({cmd, ev, ctx}, sel, {kind = 'mouse'} = {}) => {
  // the element may still slide in (a drawer): measure until it stands still over two frames, at most 3 s
  const p = await ev(`(async () => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null;
    e.scrollIntoView({block: 'center', inline: 'nearest'});
    const frame = () => new Promise(r => requestAnimationFrame(r)), at = () => { const r = e.getBoundingClientRect(); return [r.left + r.width / 2, r.top + r.height / 2]; };
    let a = at(); const end = performance.now() + 3000;
    for (;;) { await frame(); await frame(); const b = at(), still = Math.abs(a[0] - b[0]) < 0.5 && Math.abs(a[1] - b[1]) < 0.5; a = b; if (still || performance.now() > end) break; }
    const [x, y] = a, h = document.elementFromPoint(x, y);
    return {x: Math.round(x), y: Math.round(y), ok: !!h && (h === e || e.contains(h)), on: h ? h.tagName.toLowerCase() + (h.id ? '#' + h.id : '') + (typeof h.className === 'string' && h.className ? '.' + h.className.trim().split(/\\s+/).join('.') : '') : 'nothing at that place'}; })()`);
  if (!p) return {ok: false, on: `no element ${sel}`};
  if (!p.ok) return p;  // nothing is pressed: the pointer would hit something else
  await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'pc', parameters: {pointerType: kind},
    actions: [{type: 'pointerMove', x: p.x, y: p.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
  await cmd('input.releaseActions', {context: ctx});
  return {ok: true, on: p.on};
};

// 2.312.0 A (#3283): click the Undo button of the toast with the EXPECTED text. A hidden toast keeps its old button in the DOM
// (events.js toast(): only .hidden) and the server saves before the app has the answer, so an older toast's Undo can still be there:
// wait until #toast is shown, carries `text` (string or RegExp) and has its Undo button, only then click. opts.after: an expression to
// wait for after the click (e.g. the redraw); opts.n: tries of 250 ms. Returns true when the click and the `after` wait worked.
module.exports.undoToast = async (ev, text, {after = null, n = 60} = {}) => {
  const re = text instanceof RegExp ? text : new RegExp(String(text).replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const ready = async expr => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const t = `(() => { const t = document.querySelector('#toast'); return !!t && !t.classList.contains('hidden') && ${re}.test(t.textContent) && !!t.querySelector('button:not(.tx)'); })()`;
  if (!await ready(t)) return false;
  await ev(`(() => { document.querySelector('#toast button:not(.tx)').click(); return 1; })()`);
  return after ? ready(after) : true;
};
// 2.551.0 (#4599): the same anchor as boot.js untilAct for Firefox suites: wait for [data-act="<name>"] (name = boot.js actName of the
// i18n key, a ready-made anchor name is kept as it is), then click it (opts.click false: only wait). opts.n: tries of 250 ms. Returns true when found.
module.exports.act = async (ev, name, {click = true, n = 60} = {}) => {
  const sel = JSON.stringify(`[data-act="${require('./boot').actName(name)}"]`);
  for (let i = 0; i < n; i++) {
    if (await ev(`!!document.querySelector(${sel})`).catch(() => false)) {
      if (click) await ev(`(() => { document.querySelector(${sel}).click(); return 1; })()`);
      return true;
    }
    await sleep(250);
  }
  return false;
};
module.exports.noFirefox = noFirefox;
module.exports.MOUSE_PREFS = MOUSE_PREFS;
