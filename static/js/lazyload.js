/* Kalmido web client: modules loaded on demand (2.53.0, #1410). Rarely opened areas (the settings dialog, the contacts
   view, Office & finance) have no script tag in index.html: their first use loads them (loadModule), then they stay.
   The service worker precaches them (LAZY in sw.js), so they open offline too; tools/check_layout.py compares the lists.
   Classic script sharing the global scope with the others (load order: index.html, docs/ARCHITECTURE.md). */
'use strict';

// module -> its files in static/js/, in load order (the same files as LAZY in sw.js)
const LD_MODS = {
  settings: ['settings'],
  contacts: ['contacts'],
  office: ['office', 'office_docs', 'office_import', 'office_sheet', 'office_parts', 'office_travel', 'office_cashflow',
    'office_pipeline', 'office_kpi', 'office_datev', 'officeagents'],
};
// functions of a module that code loaded at start calls: a stand-in loads the module and then calls the real one (the
// module's own function declaration replaces the stand-in on window)
const LD_CALL = {settings: ['settingsModal', 'setApply', 'settingsSync', 'modCountsSync', 'setSaved'], contacts: ['ctRoute', 'ctEditor']};
// drawing functions: the stand-in draws "Loading…" (views) or nothing (parts of another view), loads, and redraws the view
const LD_VIEW = {viewContacts: ['contacts', 1], viewOffice: ['office', 1], kp_tile: ['office'], ux_info: ['office'], ofcII: ['office']};
// stays at start (core.js modOn, areas, dashboard, the client page ask it before anything of the office is loaded)
const officeOn = () => feat('office') && !S.me?.kid;

const LD_P = {};  // module -> the promise of its loading (each module once)
let ld_n = 0, ld_t = 0;
function ld_bar(d) {  // the thin bar at the top: only when loading takes longer than 300 ms (a slow connection)
  ld_n = Math.max(0, ld_n + d);
  clearTimeout(ld_t);
  let el = document.getElementById('ldbar');
  if (!ld_n) { el?.classList.remove('on'); return; }
  ld_t = setTimeout(() => {
    if (!el) { el = document.createElement('div'); el.id = 'ldbar'; el.className = 'ldbar'; el.setAttribute('aria-hidden', 'true'); document.body.appendChild(el); }
    el.getBoundingClientRect?.(); el.classList.add('on');
  }, 300);
}
const ld_url = f => `/static/js/${f}.js` + (APP_VER ? '?v=' + encodeURIComponent(APP_VER) : '');
const LD_RAN = new Set();  // files that have run (a retry after a failure loads only the rest: a second run would declare twice)
function ld_script(f) {
  if (LD_RAN.has(f)) return Promise.resolve();
  return new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = ld_url(f);
    s.dataset.ld = f;
    s.onload = () => { LD_RAN.add(f); res(); };
    s.onerror = () => { s.remove(); rej(new Error('could not load ' + f)); };
    document.head.appendChild(s);
  });
}
// loadModule('settings') -> a promise that resolves once the module's files have run. A failure (offline without the cached
// copy, a server restart) shows a toast with "Try again" (again: what to repeat) and may be retried.
function loadModule(name, again) {
  if (LD_P[name]) return LD_P[name];
  const files = LD_MODS[name];
  if (!files) return Promise.reject(new Error('unknown module ' + name));
  ld_bar(1);
  // the files of one module run one after the other (later ones use the first one's globals); the browser fetches them side
  // by side meanwhile (preload)
  for (const f of files.slice(1)) {
    const l = document.createElement('link'); l.rel = 'preload'; l.as = 'script'; l.href = ld_url(f); l.dataset.ld = f; document.head.appendChild(l);
  }
  const p = LD_P[name] = files.reduce((q, f) => q.then(() => ld_script(f)), Promise.resolve()).then(() => { ld_bar(-1); }, e => {
    ld_bar(-1); delete LD_P[name];
    for (const f of files) if (!LD_RAN.has(f)) document.querySelectorAll(`[data-ld="${f}"]`).forEach(x => x.remove());
    toast(tr('Could not be loaded'), again || (() => loadModule(name)), 8000, tr('Try again'));
    throw e;
  });
  return p;
}
const LD_DONE = new Set();  // modules that have run
function ld_all() { return Promise.all(Object.keys(LD_MODS).map(m => loadModule(m))); }  // the test suites (tests/boot.js: window.ld_all)
let ld_rv = 0;
function ld_later(name) {  // a view part asked for a module: load it, then draw the view again (once per load)
  if (LD_DONE.has(name)) return;  // loaded: a stand-in still asked (should not happen) - no redraw loop
  loadModule(name, () => ld_later(name)).then(() => {
    if (LD_DONE.has(name)) return;
    LD_DONE.add(name);
    if (!ld_rv) ld_rv = setTimeout(() => { ld_rv = 0; renderView(); }, 0);
  }, () => {});
}
for (const [m, ns] of Object.entries(LD_CALL)) for (const n of ns) {
  const stub = function (...a) {
    const again = () => stub.apply(this, a);
    return loadModule(m, again).then(() => {
      const f = window[n];
      if (typeof f !== 'function' || f === stub) throw new Error(n + ' is missing in ' + m);
      return f.apply(this, a);
    }).catch(e => { console.warn('loadModule', m, e); });
  };
  window[n] = stub;
}
// a part of another view (the client page's office hints, the start page's figures) loads the office only when it is on
for (const [n, [m, view]] of Object.entries(LD_VIEW)) window[n] = () => { if (!view && m === 'office' && !officeOn()) return ''; ld_later(m); return view ? `<p class="muted lempty">${tr('Loading…')}</p>` : ''; };
// the office switch of an agent (Settings > Agents, the agent chat's settings): its row is drawn at once, the office part
// only loads when the office is on
window.oa_switchRowHtml = aid => officeOn() ? `<div class="oa_sw" data-oa-aid="${+aid}" hidden></div>` : '';
window.oa_switchLoad = md => !officeOn() ? Promise.resolve() : loadModule('office').then(() => { if (window.oa_switchLoad.ld) return; return oa_switchLoad(md); }).catch(() => {});
window.oa_switchLoad.ld = 1;
// the settings dialog is opened most often: loaded in the background once the app has started and is idle
setTimeout(() => (window.requestIdleCallback || (f => setTimeout(f, 0)))(() => { if (S.me && !document.hidden) loadModule('settings').catch(() => {}); }), 5000);
