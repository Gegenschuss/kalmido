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
function i18nLoad(code) {
  code = code || 'en';
  if (code === I18N.code) return Promise.resolve(true);
  if (code === 'en') { I18N = {code: 'en', dict: {}}; return Promise.resolve(true); }
  if (!/^[a-z]{2,3}(-[A-Za-z0-9]{2,8})?$/.test(code)) return Promise.resolve(false);
  return I18N_PENDING[code] || (I18N_PENDING[code] = (async () => {
    try {
      const r = await fetch(`/static/i18n/${code}.json`);
      if (!r.ok) throw new Error(r.status);
      I18N = {code, dict: await r.json()};
      try { localStorage.setItem(I18N_CACHE_KEY, JSON.stringify(I18N)); } catch { /* private mode */ }
      return true;
    } catch {
      try { const c = JSON.parse(localStorage.getItem(I18N_CACHE_KEY)); if (c && c.code === code && c.dict) { I18N = c; return true; } } catch { /* none */ }
      return false;
    } finally { delete I18N_PENDING[code]; }
  })());
}
const i18nGet = k => I18N.dict[k] ?? I18N_EN[k];
const LOCALE = () => i18nGet('_meta')?.locale || I18N.code;
const i18nFmt = (s, a) => a.length ? s.replace(/\{(\d+)\}/g, (m, i) => a[i] ?? m) : s;
const i18nKey = k => { const bar = k.indexOf('|'); return bar > 0 && !/[<>]/.test(k) ? k.slice(0, bar) : k; };
function tr(key, ...a) {
  const v = I18N.dict[key];
  return i18nFmt(typeof v === 'string' ? v : i18nKey(key), a);
}
function trn(one, other, n, ...a) {
  const v = I18N.dict[one], i = n === 1 ? 0 : 1;
  return i18nFmt(Array.isArray(v) ? v[i] : i18nKey(i ? other : one), [n, ...a]);
}
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
