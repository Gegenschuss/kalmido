// ff.js -- Firefox headless driven over WebDriver BiDi, shared by the UI suites that check the real layout (2.7.2: one copy
// instead of one per suite). Skipped (with a note) when there is no firefox on PATH.
//   const firefox = require('./ff')({tag: 'p272', check, shots: 'P272_SHOTS'});
//   await firefox(async ({cmd, ev, nav, ctx, shot, drag}) => { ... }, touch);
// touch: true = a touch screen (coarse pointer, touch events), false = a mouse, undefined = Firefox's defaults.
// A Firefox that does not answer within 45 s (seen on CI runners) gets one more try on another port (2.7.1, first in p221).
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const WS = globalThis.WebSocket || require('ws');
const sleep = ms => new Promise(r => setTimeout(r, ms));

// prefs: extra Firefox preferences for one suite (2.13.0)
module.exports = ({tag, check, shots, prefs: extra = []}) => async function firefox(fn, touch) {
  try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); } catch { console.log(`${tag}: Firefox part skipped (no firefox on PATH)`); return; }
  const prof = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), `kalmido-${tag}-`));
  const prefs = [['browser.shell.checkDefaultBrowser', false], ['datareporting.policy.dataSubmissionEnabled', false], ['ui.prefersReducedMotion', 1],
    ...(touch === true ? [['ui.primaryPointerCapabilities', 1], ['ui.allPointerCapabilities', 1], ['dom.w3c_touch_events.enabled', 1]]
      : touch === false ? [['ui.primaryPointerCapabilities', 6], ['ui.allPointerCapabilities', 6]] : []), ...extra];
  fs.writeFileSync(path.join(prof, 'user.js'), prefs.map(([k, v]) => `user_pref("${k}", ${JSON.stringify(v)});`).join('\n') + '\n');
  const start = port => spawn('firefox', ['--headless', '--no-remote', '--profile', prof, `--remote-debugging-port=${port}`, 'about:blank'], {stdio: 'ignore'});
  let PORT = 9300 + Math.floor(Math.random() * 600), ff = start(PORT);
  let ws, seq = 0; const pend = new Map();
  try {
    for (let attempt = 0; attempt < 2 && !ws; attempt++) {
      if (attempt) { try { ff.kill(); } catch { /* gone */ } await sleep(1000); PORT = 9300 + Math.floor(Math.random() * 600); ff = start(PORT); }
      for (let i = 0; i < 90 && !ws; i++) {
        try { const w = new WS(`ws://127.0.0.1:${PORT}/session`); await new Promise((res, rej) => { w.onopen = res; w.onerror = rej; }); ws = w; } catch { await sleep(500); }
      }
    }
    if (!ws) { check(false, 'no WebDriver BiDi connection to Firefox'); return; }
    ws.onmessage = m => { const j = JSON.parse(m.data); if (j.id && pend.has(j.id)) { const p = pend.get(j.id); pend.delete(j.id); j.type === 'error' ? p.rej(new Error(p.method + ': ' + j.error + ' ' + j.message)) : p.res(j.result); } };
    // 2.27.0: a command that never answers (a hung page, a promise that never settles) fails after 120 s with its name and
    // what it ran, instead of stalling the whole CI shard until the job's time limit
    const cmd = (method, params = {}) => new Promise((res, rej) => {
      const id = ++seq, t = setTimeout(() => { if (pend.has(id)) { pend.delete(id); rej(new Error(`${method}: no answer within 120 s ` + String(params.expression || params.url || '').slice(0, 160))); } }, 120000);
      pend.set(id, {res: v => { clearTimeout(t); res(v); }, rej: e => { clearTimeout(t); rej(e); }, method}); ws.send(JSON.stringify({id, method, params}));
    });
    const unwrap = v => !v ? v : v.type === 'array' ? v.value.map(unwrap) : v.type === 'object' ? Object.fromEntries(v.value.map(([k, x]) => [typeof k === 'string' ? k : unwrap(k), unwrap(x)])) : v.value;
    await cmd('session.new', {capabilities: {}});
    const ctx = (await cmd('browsingContext.getTree', {})).contexts[0].context;
    const ev = async expr => { const r = await cmd('script.evaluate', {expression: expr, target: {context: ctx}, awaitPromise: true, resultOwnership: 'none', serializationOptions: {maxObjectDepth: 6}}); if (r.type === 'exception') throw new Error('JS: ' + r.exceptionDetails.text); return unwrap(r.result); };
    const nav = url => cmd('browsingContext.navigate', {context: ctx, url, wait: 'complete'});
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
