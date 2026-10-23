/* Kalmido i18n helpers. English is the source language: every UI string in the code is English and
   is its own lookup key. Other languages live in static/i18n/<code>.json (see TRANSLATING.md) and are
   loaded at boot / on switching (i18nLoad). No translations in this file.
     tr('Delete list “{0}”?', name)      -> translated text, {0}, {1} = args
     trn('{0} task', '{0} tasks', n, ...) -> one/other form picked by n (n === 1 -> one); {0} = n, {1}.. = rest
     N_('High')                          -> marks a key for the checker without translating (tables; tr() later)
   'Text|ctx' keys disambiguate one English word that needs different translations; English shows the
   part before '|'. User content (task titles, list names, tags, notes) never goes through tr(). */
'use strict';
const I18N_LS_KEY = 'tasks.lang', I18N_CACHE_KEY = 'tasks.i18n';
// built-in English: names (Sunday first, like Date.getDay()) and date patterns
const I18N_EN = {
  _meta: {name: 'English', locale: 'en-GB'},
  _weekdays: ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'],
  _weekdays_short: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
  _months: ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'],
  _months_short: ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
  // near: 2-6 days ahead, short: this year, year: other year, long: calendar day view title
  _date_formats: {near: '{wd}, {mon} {d}', short: '{wd}, {mon} {d}', year: '{wd}, {mon} {d}, {y}', long: '{wdl}, {month} {d}'},
};
let I18N = {code: 'en', dict: {}};
const I18N_PENDING = {};
function uiLang() {
  if (typeof S !== 'undefined' && S.settings && S.settings.lang) return S.settings.lang;
  try { return JSON.parse(localStorage.getItem(I18N_LS_KEY)) || 'en'; } catch { return 'en'; }
}
// load (or switch to) a language; resolves true when it is active. Offline: service worker cache,
// then the copy of the last loaded language in localStorage.
// 2.25.0 (UX-29): texts of the page shell outside the app's renders (the skip link on the setup / invitation pages)
function i18nStatic() { const sk = document.getElementById('skip'); if (sk) sk.textContent = tr('Skip to content'); }
// 2.35.0 (#1094): the language file is fetched with the version of the code (?v=, index.html meta kalmido-version), so no
// browser or service-worker cache can hand out the file of an older version. The copy in localStorage carries the version
// it was loaded with; a copy of another version (or a file the service worker only had from an older version, header
// X-Kalmido-I18n-Stale) is only a stopgap: the texts show, I18N.stale is set and the file is fetched again a little later
// (i18nRetry), then the app draws again - without reloading the page.
// 2.191.0 A (#1410 #2518): the start loads only the core texts (<code>.core.json); the texts of a module loaded on demand come
// with the module (i18nPart: loadModule waits for them before the module's files run). A language switch loads the core and
// the parts of every module loaded so far before the new language shows. ?v= is the version of the split texts (meta
// kalmido-i18n, a content hash), else the version of the code. A part that fails (offline without a copy) leaves that
// module's texts English until the next try (i18nRetry). The copy in localStorage holds the core only.
const I18N_VER = () => (typeof document !== 'undefined' && (document.querySelector?.('meta[name="kalmido-i18n"]')?.content || document.querySelector?.('meta[name="kalmido-version"]')?.content)) || '';
const I18N_MODS = new Set();  // the modules loaded so far (their part belongs to every language loaded later)
const I18N_MISS = new Set();  // parts of the active language that failed
let I18N_RT = null, I18N_RTN = 0;
function i18nRetry() {
  if (I18N_RT || !(I18N.stale || I18N_MISS.size)) return;
  const wait = [3000, 10000, 30000, 60000][Math.min(I18N_RTN++, 3)];
  I18N_RT = setTimeout(async () => {
    I18N_RT = null; const was = I18N.code;
    if (!(I18N.stale || I18N_MISS.size) || was !== uiLang()) return;
    const ok = I18N.stale ? await i18nLoad(was, true) : await i18nParts([...I18N_MISS]);
    if (ok && !I18N.stale && !I18N_MISS.size) { I18N_RTN = 0; if (typeof render === 'function' && typeof S !== 'undefined' && S.booted) { try { render(); } catch { /* next render */ } } }
    else i18nRetry();
  }, wait);
}
const i18nUrl = (code, part, ver) => `/static/i18n/${code}${part ? '.' + part : ''}.json${ver ? '?v=' + encodeURIComponent(ver) : ''}`;
// one file of a language -> {dict, old} (old: the service worker had only a copy of another version, offline); throws without one
async function i18nFetch(code, part, ver) {
  const r = await fetch(i18nUrl(code, part, ver));
  // a sign-in page after a redirect (proxy login) or an error page is no language file
  if (!r.ok || r.redirected || !/json/.test(r.headers.get('content-type') || '')) throw Object.assign(new Error(String(r.status)), {status: r.status});
  const dict = await r.json();
  if (!dict || typeof dict !== 'object' || Array.isArray(dict)) throw new Error('no language file');
  return {dict, old: r.headers.get('X-Kalmido-I18n-Stale') === '1'};
}
// the parts of modules into a language (t = {code, dict, ...}); -> the modules whose part failed
async function i18nPartsInto(t, names) {
  const want = new Set(Array.isArray(t.dict._mods) ? t.dict._mods : []), miss = [], ver = I18N_VER();
  t.parts = t.parts || new Set();
  await Promise.all(names.filter(m => want.has(m) && !t.parts.has(m)).map(async m => {
    try {
      const {dict, old} = await i18nFetch(t.code, 'mod-' + m, ver);
      Object.assign(t.dict, dict); t.parts.add(m);
      if (old && ver) t.stale = true;
    } catch { miss.push(m); }
  }));
  return miss;
}
async function i18nParts(names) {
  const t = I18N, miss = await i18nPartsInto(t, names);
  if (I18N !== t) return false;
  for (const m of names) if (!miss.includes(m)) I18N_MISS.delete(m);
  return !miss.length;
}
// the texts of a module loaded on demand (lazyload.js loadModule); never fails: without them the module shows English texts
async function i18nPart(name) {
  I18N_MODS.add(name);
  const pend = Object.values(I18N_PENDING);
  if (pend.length) await Promise.all(pend);  // a language being loaded: its part of this language
  const t = I18N;
  if (t.code === 'en' || t.parts?.has(name)) return;
  const miss = await i18nPartsInto(t, [name]);
  if (I18N !== t) return;
  if (miss.length) I18N_MISS.add(name);
  if (I18N_MISS.size || I18N.stale) i18nRetry();
}
// 2.191.0 A: the parts of every module of the active language, fetched one per idle moment when a service worker keeps them
// (each module opens translated offline too); a part already kept is not fetched again
async function i18nWarm() {
  const t = I18N, ver = I18N_VER();
  if (t.code === 'en' || !Array.isArray(t.dict._mods) || !navigator.serviceWorker?.controller || typeof caches === 'undefined') return;
  if (navigator.connection?.saveData || /2g/.test(navigator.connection?.effectiveType || '')) return;
  for (const m of t.dict._mods) {
    if (I18N !== t || document.hidden) return;
    const u = i18nUrl(t.code, 'mod-' + m, ver);
    try { if (await caches.match(u)) continue; await fetch(u); } catch { return; }
    await new Promise(res => (window.requestIdleCallback || setTimeout)(() => res()));
  }
}
function i18nLoad(code, again) {
  code = code || 'en';
  if (code === I18N.code && !(again && I18N.stale)) { i18nStatic(); if (I18N.stale || I18N_MISS.size) i18nRetry(); return Promise.resolve(true); }
  if (code === 'en') { I18N = {code: 'en', dict: {}}; I18N_MISS.clear(); i18nStatic(); return Promise.resolve(true); }
  if (!/^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$/.test(code)) return Promise.resolve(false);
  return I18N_PENDING[code] || (I18N_PENDING[code] = (async () => {
    const ver = I18N_VER();
    let next;
    try {
      let f;
      try { f = await i18nFetch(code, 'core', ver); } catch (e) {
        if (e.status !== 404) throw e;
        f = await i18nFetch(code, '', ver);  // a server without the split (a proxy serving /static/ itself): the whole file
      }
      const {dict, old} = f;
      if (!dict._meta) throw new Error('no language file');
      const c0 = old ? i18nCached(code) : null;
      if (c0 && c0.ver === ver) next = c0;
      else {
        next = {code, dict, ver: old ? '' : ver, ...(old && ver ? {stale: true} : {})};
        if (!old) try { localStorage.setItem(I18N_CACHE_KEY, JSON.stringify(next)); } catch { /* private mode */ }
      }
    } catch {
      const c = i18nCached(code);
      if (!c) { delete I18N_PENDING[code]; return false; }
      next = {...c, ...(ver && c.ver !== ver ? {stale: true} : {})};
    }
    try {
      const miss = await i18nPartsInto(next, [...I18N_MODS]);
      I18N = next; I18N_MISS.clear(); for (const m of miss) I18N_MISS.add(m);
      i18nStatic(); if (I18N.stale || I18N_MISS.size) i18nRetry();
      return true;
    } finally { delete I18N_PENDING[code]; }
  })());
}
function i18nCached(code) {
  try { const c = JSON.parse(localStorage.getItem(I18N_CACHE_KEY)); if (c && c.code === code && c.dict) { delete c.stale; return c; } } catch { /* none */ }
  return null;
}
const i18nGet = k => I18N.dict[k] ?? I18N_EN[k];
const LOCALE = () => i18nGet('_meta')?.locale || I18N.code;
const i18nFmt = (s, a) => a.length ? s.replace(/\{(\d+)\}/g, (m, i) => a[i] ?? m) : s;
const i18nKey = k => { const bar = k.indexOf('|'); return bar > 0 && !/[<>]/.test(k) ? k.slice(0, bar) : k; };
/** @param {string} key @param {...any} a @returns {string} */  // 2.102.0 (#1995)
function tr(key, ...a) {
  const v = I18N.dict[key];
  return i18nFmt(typeof v === 'string' ? v : i18nKey(key), a);
}
// 2.11.0: the "one" form follows the language's plural rule where it differs (French: 0 and 1), else n === 1
let I18N_PL = null;
function plOne(n) {
  if (n === 1) return true;
  if (n !== 0 || !I18N.code || I18N.code === 'en') return false;
  try { if (!I18N_PL || I18N_PL.c !== I18N.code) I18N_PL = {c: I18N.code, r: new Intl.PluralRules(LOCALE())}; return I18N_PL.r.select(0) === 'one'; } catch { return false; }
}
/** @param {string} one @param {string} other @param {number} n @param {...any} a @returns {string} */
function trn(one, other, n, ...a) {
  const v = I18N.dict[one], i = Array.isArray(v) && plOne(n) ? 0 : n === 1 ? 0 : 1;
  return i18nFmt(Array.isArray(v) ? v[i] : i18nKey(i ? other : one), [n, ...a]);
}
/** @type {(s: string) => string} */
const N_ = s => s;
// weekday / month names of the active language (index like Date.getDay() / getMonth())
const i18nArr = k => new Proxy(I18N_EN[k], {get: (_, p) => Reflect.get(i18nGet(k), p)});
const WD = i18nArr('_weekdays_short'), WDL = i18nArr('_weekdays'), MON = i18nArr('_months'), MONS = i18nArr('_months_short');
// date pattern of the active language: {wd} {wdl} weekday short/long, {d} {dd} day, {mm} month number,
// {mon} {month} month name short/long, {y} year
function fmtDay(kind, d) {
  const p = (I18N.dict._date_formats || {})[kind] || I18N_EN._date_formats[kind];
  const pad2 = n => String(n).padStart(2, '0');
  const v = {wd: WD[d.getDay()], wdl: WDL[d.getDay()], d: d.getDate(), dd: pad2(d.getDate()), mm: pad2(d.getMonth() + 1),
    mon: MONS[d.getMonth()], month: MON[d.getMonth()], y: d.getFullYear()};
  return p.replace(/\{(\w+)\}/g, (m, k) => v[k] ?? m);
}
