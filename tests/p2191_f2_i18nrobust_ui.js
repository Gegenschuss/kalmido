// 2.191.0 UI test, part F2 (#2518): the texts of the modules stay there offline and never hold a module up. Own container
// (start.sh), jsdom.
// freelancer-matrix: public
// - Collapse / Expand (picked as a value by a start file) show German at start, before the timeline is loaded
// - without a service worker the copy in localStorage keeps the parts fetched so far (a module opened once stays translated
//   offline): a new page offline opens the settings in German
// - a part that hangs: the module opens after about 3 seconds anyway (English), its texts follow and the app draws again
// - a part that answers 404 (the split turned off on the server): the whole file once, German, no retry every minute
// - warming with a service worker: starts on its own after the language load (not the idle chain), waits until the worker
//   controls the page (a first visit), pauses while the tab is hidden, runs with the data saver, fetches every part; after a
//   language switch the parts of the new language
// - a person without an organisation gets the same
// KMT_NOSTART=1 = the container is running.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const plain = part => Object.entries(part).filter(([k, v]) => typeof v === 'string' && v !== k && k.length > 14 && !/[{<|]/.test(k) && !/[{<]/.test(v));
const wrap = (seen, fn) => x => { const f0 = x.fetch; x.fetch = (u, o) => { seen.push(String(u)); return (fn && fn(String(u))) || f0(u, o); }; };

(async () => {
  if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'de'})});
  check(r.ok, 'setup');
  const CK = await login('alice');
  await call(CK, 'POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'de', collab_all: true, modules: ['cal', 'comments']});
  await call(CK, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: 'cal,comments,office'});
  const html = await (await fetch(B, {headers: {Cookie: CK}})).text();
  const V = (html.match(/name="kalmido-i18n" content="([0-9a-f]{12})"/) || [])[1] || '';
  check(V, 'the page names the version ' + V);
  const part = async (code, m) => (await fetch(B + `static/i18n/${code}.mod-${m}.json?v=${V}`)).json();
  const core = await (await fetch(B + `static/i18n/de.core.json?v=${V}`)).json();
  const [sk, sv] = plain(await part('de', 'settings'))[0] || [];
  const [ok0, ov] = plain(await part('de', 'office'))[0] || [];
  check(sk && ok0 && Array.isArray(core._mods), `texts of the parts found (${sk} / ${ok0})`);

  // ================= Collapse / Expand at start; the copy in localStorage keeps the parts (no service worker)
  let seen = [];
  let w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}, setup: wrap(seen)});
  check(w.eval('tr("Collapse")') === core.Collapse && w.eval('tr("Expand")') === core.Expand && core.Collapse !== 'Collapse', `Collapse / Expand in German at start (${core.Collapse} / ${core.Expand})`);
  check(!w.eval('LD_P.timeline'), 'the timeline is not loaded');
  await w.eval(`loadModule('settings')`);
  let ls = JSON.parse(w.__store['tasks.i18n'] || '{}');
  check(ls.code === 'de' && ls.ver === V && ls.dict?.[sk] === sv && (ls.parts || []).includes('settings') && ls.dict.Collapse, 'without a service worker the copy in localStorage holds the core and the settings part');
  const store = {...w.__store};
  w.close();
  // a new page offline: the settings from the copy, German
  w = await boot({user: 'alice', lazy: true, ls: {...store, 'tasks.lang': '"de"'}, setup: x => { const f0 = x.fetch; x.fetch = (u, o) => (/\/static\/i18n\//.test(String(u)) ? Promise.reject(new TypeError('Failed to fetch')) : f0(u, o)); }});
  check(w.eval('I18N.code') === 'de' && w.eval('I18N.parts.has("settings")'), 'offline: the copy with its parts is the language');
  await w.eval(`loadModule('settings')`);
  check(w.eval(`tr(${JSON.stringify(sk)})`) === sv && !w.eval('I18N_MISS.has("settings")'), `offline: the settings open in German (${sv})`);
  w.close();

  // ================= a part that hangs: the module opens after about 3 seconds, the texts follow
  let release = null;
  seen = [];
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}, setup: wrap(seen, u => (/de\.mod-office\.json/.test(u) && !release ? new Promise(res => { release = res; }) : null))});
  const t0 = Date.now();
  await w.eval(`loadModule('office')`);
  const dt = Date.now() - t0;
  check(dt >= 2500 && dt < 6000 && typeof w.eval('viewOffice') === 'function', `a hanging part: the office opens after ${dt} ms`);
  check(w.eval(`tr(${JSON.stringify(ok0)})`) === ok0, 'meanwhile English');
  let renders = 0;
  const r0 = w.eval('render'); w.render = (...a) => { renders++; return r0(...a); };
  const fr = await fetch(B + `static/i18n/de.mod-office.json?v=${V}`);
  release(new w.Response(await fr.text(), {status: 200, headers: {'Content-Type': 'application/json'}}));
  await until(() => w.eval(`tr(${JSON.stringify(ok0)})`) === ov, 40);
  check(w.eval(`tr(${JSON.stringify(ok0)})`) === ov && renders > 0, `the texts follow and the app draws again (${renders})`);
  w.close();

  // ================= a part that answers 404: the whole file once
  seen = [];
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}, setup: wrap(seen, u => (/de\.mod-office\.json/.test(u) ? Promise.resolve(new Response('{}', {status: 404, headers: {'Content-Type': 'application/json'}})) : null))});
  await w.eval(`loadModule('office')`);
  check(w.eval(`tr(${JSON.stringify(ok0)})`) === ov && w.eval('I18N.whole') && !w.eval('I18N_MISS.size'), 'a part 404: the whole file, German, nothing missing');
  await w.eval(`loadModule('calendar')`);
  await sleep(3500);
  check(seen.filter(u => /de\.mod-office\.json/.test(u)).length === 1 && seen.filter(u => /\/static\/i18n\/de\.json/.test(u)).length === 1, 'asked once each, no retry');
  check(!seen.some(u => /de\.mod-calendar\.json/.test(u)), 'with the whole file no further part');
  w.close();

  // ================= warming with a service worker (a first visit: no controller yet), hidden tab, data saver
  const swSetup = sn => x => {
    wrap(sn)(x);
    const sw = {register: () => Promise.resolve(), controller: null, ready: Promise.resolve({}), cl: [], addEventListener(t, f) { if (t === 'controllerchange') this.cl.push(f); }};
    Object.defineProperty(x.navigator, 'serviceWorker', {configurable: true, value: sw});
    Object.defineProperty(x.navigator, 'connection', {configurable: true, value: {saveData: true, effectiveType: '2g'}});
    x.caches = {match: async () => undefined};
    x.__hidden = false;
    Object.defineProperty(x.document, 'hidden', {configurable: true, get: () => x.__hidden});
  };
  seen = [];
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}, setup: swSetup(seen)});
  w.ld_idle = () => {};  // no module loads in the background meanwhile (their parts would count here)
  w.__hidden = true;
  const warm = () => seen.filter(u => /\/static\/i18n\/de\.mod-/.test(u)).map(u => u.match(/mod-([\w-]+)\.json/)[1]);
  await sleep(9000);  // the warming starts 8 s after the language load
  check(!warm().length, 'no part before the worker controls the page ' + warm().slice(0, 3));
  w.navigator.serviceWorker.controller = {};
  for (const f of w.navigator.serviceWorker.cl) f();
  await sleep(800);
  check(!warm().length, 'hidden tab: paused ' + warm().slice(0, 3));
  w.__hidden = false; w.document.dispatchEvent(new w.Event('visibilitychange'));
  await until(() => warm().length >= core._mods.length, 100);
  check(new Set(warm()).size === core._mods.length && core._mods.every(m => warm().includes(m)), `visible again: every part fetched with the data saver too (${new Set(warm()).size} of ${core._mods.length})`);
  check(seen.filter(u => /de\.mod-/.test(u)).every(u => u.includes('?v=' + V)), 'with the version');
  check(w.eval(`I18N_WARMED.has('de@${V}')`), 'done for this language and version');
  // a language switch: the parts of the new language
  await call(CK, 'PATCH', '/api/settings', {lang: 'fr'});
  check(await w.eval(`i18nLoad('fr')`), 'French loaded');
  w.eval('i18nWarmSoon(10)');
  const frMods = w.eval('I18N.dict._mods') || [];
  await until(() => new Set(seen.filter(u => /\/static\/i18n\/fr\.mod-/.test(u))).size >= frMods.length, 100);
  check(frMods.length > 10 && new Set(seen.filter(u => /\/static\/i18n\/fr\.mod-/.test(u))).size === frMods.length, `after the switch: every part of French (${frMods.length})`);
  await call(CK, 'PATCH', '/api/settings', {lang: 'de'});
  w.close();

  // ================= a person without an organisation
  await call(CK, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida').catch(() => null);
  if (CF) {
    await call(CF, 'PATCH', '/api/settings', {lang: 'de', tour: 'done'});
    w = await boot({user: 'frida', lazy: true, ls: {'tasks.lang': '"de"'}});
    await w.eval(`loadModule('settings')`);
    ls = JSON.parse(w.__store['tasks.i18n'] || '{}');
    check(w.eval('tr("Collapse")') === core.Collapse && (ls.parts || []).includes('settings'), 'without an organisation: Collapse in German, the copy keeps the settings part');
    w.close();
  } else check(false, 'a person without an organisation signs in');

  console.log(`\np2191_f2_i18nrobust_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
