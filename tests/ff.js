// ff.js -- Firefox headless driven over WebDriver BiDi, shared by the UI suites that check the real layout (2.7.2: one copy
// instead of one per suite). Skipped (with a note) when there is no firefox on PATH.
//   const firefox = require('./ff')({tag: 'p272', check, shots: 'P272_SHOTS'});
//   await firefox(async ({cmd, ev, nav, ctx, shot, drag}) => { ... }, touch);
// touch: true = a touch screen (coarse pointer, touch events), false = a mouse, undefined = Firefox's defaults.
// A Firefox that does not answer within 45 s (seen on CI runners) gets one more try on another port (2.7.1, first in p221).
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path'), net = require('net');
const WS = globalThis.WebSocket || require('ws');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const {clockOffset, shiftedDate} = require('./boot');  // 2.381.0 (#2713)
// 2.284.0 A (#3120): a port the system hands out free - a random one of 9300-9899 could be the port of another suite's Firefox
// on the same machine (parallel places / shards): the connection went to that one ("session.new: Maximum number of active sessions")
const freePort = () => new Promise(res => { const s = net.createServer(); s.on('error', () => res(9300 + Math.floor(Math.random() * 600)));
  s.listen(0, '127.0.0.1', () => { const p = s.address().port; s.close(() => res(p)); }); });

// prefs: extra Firefox preferences for one suite (2.13.0)
// 2.53.0 (#1410): nav() loads the modules the app loads on demand (settings, contacts, office) after each page load, so
// suites can call their functions directly; lazy: true leaves them to the app (tests/p253_a_ui.js)
module.exports = ({tag, check, shots, prefs: extra = [], lazy = false}) => async function firefox(fn, touch) {
  try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); } catch { console.log(`${tag}: Firefox part skipped (no firefox on PATH)`); return; }
  const prof = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), `kalmido-${tag}-`));
  const prefs = [['browser.shell.checkDefaultBrowser', false], ['datareporting.policy.dataSubmissionEnabled', false], ['ui.prefersReducedMotion', 1],
    ...(touch === true ? [['ui.primaryPointerCapabilities', 1], ['ui.allPointerCapabilities', 1], ['dom.w3c_touch_events.enabled', 1]]
      : touch === false ? [['ui.primaryPointerCapabilities', 6], ['ui.allPointerCapabilities', 6]] : []), ...extra];
  fs.writeFileSync(path.join(prof, 'user.js'), prefs.map(([k, v]) => `user_pref("${k}", ${JSON.stringify(v)});`).join('\n') + '\n');
  const start = port => spawn('firefox', ['--headless', '--no-remote', '--profile', prof, `--remote-debugging-port=${port}`, 'about:blank'], {stdio: 'ignore'});
  let PORT = await freePort(), ff = start(PORT);
  let ws, seq = 0; const pend = new Map();
  const connect = async () => {
    for (let i = 0; i < 90 && !ws; i++) {
      try { const w = new WS(`ws://127.0.0.1:${PORT}/session`); await new Promise((res, rej) => { w.onopen = res; w.onerror = rej; }); ws = w; } catch { await sleep(500); }
    }
  };
  try {
    for (let attempt = 0; attempt < 2 && !ws; attempt++) {
      if (attempt) { try { ff.kill(); } catch { /* gone */ } await sleep(1000); PORT = await freePort(); ff = start(PORT); }
      await connect();
    }
    if (!ws) { check(false, 'no WebDriver BiDi connection to Firefox'); return; }
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
      try { ff.kill(); } catch { /* gone */ }
      ws = null; PORT = await freePort(); ff = start(PORT);
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
    const ev = async expr => { const r = await cmd('script.evaluate', {expression: expr, target: {context: ctx}, awaitPromise: true, resultOwnership: 'none', serializationOptions: {maxObjectDepth: 6}}); if (r.type === 'exception') throw new Error('JS: ' + r.exceptionDetails.text); return unwrap(r.result); };
    // 2.161.2 CI fix: on a slow runner a navigate now and then never answers (an earlier page load that commits late swallows
    // it: p2100_ui, p21144_d_ui, p270_ui) - after 40 s the same navigate once more instead of 120 s and a failed suite
    const nav = async url => {
      let r;
      for (let k = 0; ; k++) {
        try { r = await cmd('browsingContext.navigate', {context: ctx, url, wait: 'complete'}, k < 2 ? 40000 : 120000); break; } catch (e) {
          if (k >= 2 || !/no answer within/.test(e.message)) throw e;
          console.log(`ff: navigate ${String(url).slice(0, 120)} gave no answer in 40 s, once more`);
        }
      }
      if (!lazy) await ev(`typeof ld_all === 'function' ? ld_all().then(() => 1, () => 0) : 0`).catch(() => 0);
      return r;
    };
    const shot = async name => { const dir = shots && process.env[shots]; if (!dir) return; const r = await cmd('browsingContext.captureScreenshot', {context: ctx}); fs.writeFileSync(path.join(dir, name), Buffer.from(r.data, 'base64')); };
    // a drag with the mouse (desktop) or one finger (touch) from (x0, y0) by (dx, dy)
    const drag = (x0, y0, dx, dy, kind = 'mouse') => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'p1', parameters: {pointerType: kind},
      actions: [{type: 'pointerMove', x: Math.round(x0), y: Math.round(y0)}, {type: 'pointerDown', button: 0}, {type: 'pointerMove', x: Math.round(x0 + dx / 2), y: Math.round(y0 + dy / 2), duration: 120},
        {type: 'pointerMove', x: Math.round(x0 + dx), y: Math.round(y0 + dy), duration: 120}, {type: 'pointerUp', button: 0}]}]}).then(() => cmd('input.releaseActions', {context: ctx}));
    await fn({cmd, ev, nav, ctx, shot, drag});
  } catch (e) { check(false, 'Firefox: ' + e.message); } finally {
    try { ws && ws.close(); } catch { /* gone */ }
    try { ff.kill(); } catch { /* gone */ }
    await sleep(500); fs.rmSync(prof, {recursive: true, force: true});
  }
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
