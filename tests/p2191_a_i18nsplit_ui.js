// 2.191.0 UI test, part A (#1410 #2518): the texts of a module come with the module. Own container (start.sh), jsdom.
// freelancer-matrix: public
// - German start: the core texts with ?v=<meta kalmido-i18n>, never the whole file; the start shows German texts; the copy
//   in localStorage holds the core only (no text of a module); before a module is loaded its texts are not there
// - the settings dialog / the office load their part with the module: the dialog shows German texts and no English one
// - a language switch to French with the settings open: the core and the parts of the loaded modules in French, the dialog
//   drawn again in French
// - a part that fails once: the module still opens (English texts), the part is fetched again a moment later (German)
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
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
// a plain text of a part: no placeholder, no markup, translated differently, long enough not to occur by chance
const plain = part => Object.entries(part).filter(([k, v]) => typeof v === 'string' && v !== k && k.length > 14 && !/[{<|]/.test(k) && !/[{<]/.test(v));
const rec = seen => x => { const f0 = x.fetch; x.fetch = (u, o) => { seen.push(String(u)); return f0(u, o); }; };

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
  check(V, 'the page names the version of the split texts ' + V);
  const part = async (code, m) => (await fetch(B + `static/i18n/${code}.mod-${m}.json?v=${V}`)).json();
  const setDe = await part('de', 'settings'), setFr = await part('fr', 'settings'), offDe = await part('de', 'office');
  const [sk, sv] = plain(setDe)[0] || [];
  const [ok0, ov] = plain(offDe)[0] || [];
  check(sk && ok0, `texts of the parts found (${sk} / ${ok0})`);

  // ================= German start
  let seen = [];
  let w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}, setup: rec(seen)}), d = w.document;
  const i18n = seen.filter(u => /\/static\/i18n\//.test(u));
  check(i18n.some(u => u.includes(`/static/i18n/de.core.json?v=${V}`)), 'the start fetches the core texts with the version ' + i18n.slice(0, 3).join(' '));
  check(!i18n.some(u => /\/static\/i18n\/de\.json/.test(u)), 'the start never fetches the whole language file');
  check(w.eval('I18N.code') === 'de' && w.eval('tr("Basket")') === 'Eingang' && /Eingang/.test(d.querySelector('#side')?.textContent || ''), 'the start shows German texts');
  const ls = JSON.parse(w.__store['tasks.i18n'] || '{}');
  check(ls.code === 'de' && ls.ver === V && ls.dict && !(sk in ls.dict) && Array.isArray(ls.dict._mods), 'the copy in localStorage holds the core only, with the version');
  check(w.eval(`tr(${JSON.stringify(sk)})`) === sk, 'a text of the settings is not loaded before the settings');
  // the settings dialog loads its part with the module
  w.eval('settingsModal()');
  await until(() => d.querySelector('.modal') && w.eval(`tr(${JSON.stringify(sk)})`) === sv, 60);
  check(w.eval(`tr(${JSON.stringify(sk)})`) === sv, `the settings' texts in German (${sv})`);
  check(seen.some(u => u.includes(`/static/i18n/de.mod-settings.json?v=${V}`)), 'the settings part is fetched with the version');
  await sleep(400);
  const txt = () => d.querySelector('.modal')?.textContent || '';
  const de = plain(setDe), shownDe = de.filter(([, v]) => txt().includes(v)), leftEn = de.filter(([k, v]) => txt().includes(k) && !txt().includes(v));
  check(shownDe.length >= 3, `the dialog shows German texts of the settings part (${shownDe.length}: ${shownDe.slice(0, 2).map(x => x[1]).join(' / ')})`);
  check(!leftEn.length, 'no English text of the settings part in the dialog ' + leftEn.slice(0, 3).map(x => x[0]).join(' / '));
  await w.eval(`loadModule('office')`);
  check(w.eval(`tr(${JSON.stringify(ok0)})`) === ov, `the office's texts in German with the office (${ov})`);

  // ================= switch to French with the settings open
  await call(CK, 'PATCH', '/api/settings', {lang: 'fr'});  // like the settings: the account's language (a state reload keeps it)
  const n0 = seen.length;
  check(await w.eval(`i18nLoad('fr')`), 'French loaded');
  const frSeen = seen.slice(n0);
  check(['fr.core.json', 'fr.mod-settings.json', 'fr.mod-office.json'].every(f => frSeen.some(u => u.includes('/static/i18n/' + f + '?v=' + V))), 'the switch fetches the core and the parts of the loaded modules ' + frSeen.filter(u => /i18n/.test(u)).length);
  check(w.eval(`tr(${JSON.stringify(sk)})`) === setFr[sk] && w.eval('tr("Basket")') !== 'Eingang', `the settings' texts in French (${setFr[sk]})`);
  d.querySelector('.modal')?.remove(); w.eval('settingsModal()'); await sleep(800);
  const shownFr = plain(setFr).filter(([, v]) => txt().includes(v)), leftDe = shownDe.filter(([k, v]) => setFr[k] !== v && v.length > 10 && txt().includes(v));
  check(shownFr.length >= 3 && !leftDe.length, `the dialog drawn again in French (${shownFr.length}), no German text of the part left ${leftDe.slice(0, 2).map(x => x[1]).join(' / ')}`);
  w.close();
  await call(CK, 'PATCH', '/api/settings', {lang: 'de'});

  // ================= a part that fails once: the module opens, the texts follow
  let fails = 1;
  seen = [];
  w = await boot({user: 'alice', lazy: true, ls: {'tasks.lang': '"de"'}, setup: x => { const f0 = x.fetch; x.fetch = (u, o) => { seen.push(String(u)); if (/de\.mod-office\.json/.test(String(u)) && fails-- > 0) return Promise.reject(new TypeError('Failed to fetch')); return f0(u, o); }; }});
  await w.eval(`loadModule('office')`);
  check(typeof w.eval('viewOffice') === 'function' && w.eval('LD_P.office') && w.eval(`tr(${JSON.stringify(ok0)})`) === ok0, 'the office opens without its texts (English, no failure)');
  check(w.eval('I18N_MISS.has("office")'), 'the missing part is noted');
  await until(() => w.eval(`tr(${JSON.stringify(ok0)})`) === ov, 60);
  check(w.eval(`tr(${JSON.stringify(ok0)})`) === ov && !w.eval('I18N_MISS.size'), 'fetched again a moment later: German');
  w.close();

  // ================= a person without an organisation
  await call(CK, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida').catch(() => null);
  if (CF) {
    await call(CF, 'PATCH', '/api/settings', {lang: 'de', tour: 'done'});
    seen = [];
    w = await boot({user: 'frida', lazy: true, ls: {'tasks.lang': '"de"'}, setup: rec(seen)});
    await w.eval(`loadModule('settings')`);
    check(w.eval('tr("Basket")') === 'Eingang' && w.eval(`tr(${JSON.stringify(sk)})`) === sv, 'without an organisation: the core and the settings part in German');
    w.close();
  } else check(false, 'a person without an organisation signs in');

  console.log(`\np2191_a_i18nsplit_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
