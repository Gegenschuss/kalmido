// 2.45.0 (#1529): reload safety, loaded first and without the stylesheet in mind.
// - rl_waitServer(): the page and the stylesheet answer with 200 (used before the automatic reload of core.js verReload)
// - after loading: no styling (app.css missing, e.g. the server was restarting) -> reload again after a few seconds, at most
//   3 times (counter in sessionStorage); then a plain notice with a "Reload" button (inline style, readable without app.css)
const RL_KEY = 'kalmido-rl-n', RL_MAX = 3;
const RL_TXT = {en: ['Kalmido could not be loaded completely.', 'Reload'], de: ['Kalmido konnte nicht vollständig geladen werden.', 'Neu laden']};
const rl_sleep = ms => new Promise(r => setTimeout(r, ms));
async function rl_ok(url, css) {
  try {
    const r = await fetch(url, {cache: 'no-store', credentials: 'same-origin'});
    return r.status === 200 && (!css || /css/.test(r.headers.get('content-type') || ''));
  } catch { return false; }
}
async function rl_waitServer(maxMs = 90000) {
  const end = Date.now() + maxMs;
  for (;;) {
    if (await rl_ok('/') && await rl_ok('/static/app.css', true)) return true;
    if (Date.now() >= end) return false;
    await rl_sleep(2000);
  }
}
function rl_styled() { try { return getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() !== ''; } catch { return true; } }
function rl_count(v) { try { if (v === undefined) return +sessionStorage.getItem(RL_KEY) || 0; if (v === null) sessionStorage.removeItem(RL_KEY); else sessionStorage.setItem(RL_KEY, String(v)); } catch { /* private mode */ } return 0; }
function rl_notice() {
  const t = RL_TXT[(navigator.language || 'en').slice(0, 2)] || RL_TXT.en;
  const el = document.createElement('div');
  el.id = 'rl-notice'; el.setAttribute('role', 'alert');
  el.style.cssText = 'position:fixed;left:0;right:0;top:0;z-index:99999;padding:14px;background:#16171a;color:#e8e8ea;font:15px system-ui,sans-serif;text-align:center';
  const b = document.createElement('button');
  b.type = 'button'; b.textContent = t[1];
  b.style.cssText = 'margin-left:12px;padding:8px 16px;font:inherit;border:0;border-radius:8px;background:#e8e8ea;color:#16171a;cursor:pointer';
  b.addEventListener('click', () => { rl_count(null); location.reload(); });
  el.append(document.createTextNode(t[0]), b);
  document.body.appendChild(el);
}
async function rl_check() {
  if (rl_styled()) { rl_count(null); return; }
  const n = rl_count();
  if (n >= RL_MAX) { rl_notice(); return; }
  rl_count(n + 1);
  await rl_sleep(2500 * (n + 1));
  await rl_waitServer(30000);
  location.reload();
}
if (document.readyState === 'complete') rl_check(); else window.addEventListener('load', () => { rl_check(); });
