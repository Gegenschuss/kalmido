// 2.76.0 UI tests of part B (#1023): Office & finance > Settings > Packs (static/js/office_packs.js). Own container (start.sh),
// jsdom, a fake catalogue served inside the test container (python -m http.server on 127.0.0.1:8097, allowed as an
// internal host). The packs in it are made from the built-in ones (invented names, no real data):
// - without a catalogue: the section, the note "No catalogue set up", the built-in packs
// - with the fake catalogue: the source line; the search filters; the kind filter; a community pack asks with the warning
//   first, then shows "Installed v1"; the country pack choice offers it; a verified industry pack installs without a
//   question and gets its box in the calculation rules; Undo removes it again (one step)
// - the country pack in use cannot be uninstalled: the reason in plain words in the card
// - a member sees the list without buttons; phone width: the section and its buttons
const {execFileSync} = require('child_process');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const CAT = 'http://127.0.0.1:8097';
const start = (extra, keep) => execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore',
  env: {...process.env, ...(keep ? {KEEP: '1'} : {}), EXTRA: (process.env.EXTRA || '') + extra}});
start('', false);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const card = (d, k) => d.querySelector(`#pkc [data-pkc-item="${k}"]`);
const cards = d => [...d.querySelectorAll('#pkc [data-pkc-item]')].map(x => x.dataset.pkcItem);
const dlg = async d => until(() => [...d.querySelectorAll('.modal.cdlg')].pop());

// the fake catalogue: a community country pack (from the built-in DE) and a verified industry pack (from film)
function writeCatalogue() {
  const dir = path.join(DATA, 'pkcat'), src = path.join(__dirname, '..', 'kalmido', 'office', 'packs');
  fs.mkdirSync(path.join(dir, 'country'), {recursive: true}); fs.mkdirSync(path.join(dir, 'industry'), {recursive: true});
  const at = {...JSON.parse(fs.readFileSync(path.join(src, 'de.json'), 'utf8')), code: 'AT', name: 'Österreich', name_en: 'Austria', version: 1, community: true};
  const ev = {...JSON.parse(fs.readFileSync(path.join(src, 'industry', 'film.json'), 'utf8')), code: 'event', name: {de: 'Veranstaltungen', en: 'Events'}, version: 1};
  const put = (rel, obj) => { const raw = Buffer.from(JSON.stringify(obj)); fs.writeFileSync(path.join(dir, rel), raw); return {sha256: crypto.createHash('sha256').update(raw).digest('hex'), size: raw.length}; };
  const a = put('country/at-1.json', at), e = put('industry/event-1.json', ev);
  // min_app below the running version: the test server still reports the base version until the release bump
  const ver = (rel, h) => [{version: 1, url: `${CAT}/${rel}`, ...h, released: '2026-10-17', min_app: '2.0.0', changes: {de: 'Erste Fassung', en: 'First version'}}];
  fs.writeFileSync(path.join(dir, 'index.json'), JSON.stringify({format: 1, name: 'Test packs', updated: '2026-10-17', packs: [
    {kind: 'country', code: 'AT', name: {de: 'Österreich', en: 'Austria'}, description: {de: 'Steuersätze und Texte, *Beispiel*', en: 'Tax rates and texts, *example* <b>bold</b>'},
      author: 'Example group', license: 'CC0-1.0', verified: false, homepage: 'https://example.com/at', versions: ver('country/at-1.json', a)},
    {kind: 'industry', code: 'event', name: {de: 'Veranstaltungen', en: 'Events'}, description: {de: 'Kalkulation für Veranstaltungen', en: 'Calculation for events'},
      author: 'Example group', license: 'CC0-1.0', verified: true, versions: ver('industry/event-1.json', e)}]}));
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal', 'comments']});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,office,clients'});
  const me = (await call('GET', '/api/state')).me.id;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  await call('PUT', `/api/orgs/${ORG}/members`, {email: 'bob@example.com', role: 'member'});
  await call('PATCH', '/api/settings', {workspace: `org:${ORG}`});
  let BK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,office,clients', workspace: `org:${ORG}`}, BK);

  // ================= no catalogue set up
  let w = await boot({hash: 'office/settings'}), d = w.document;
  const sec = await until(() => d.querySelector('#pkc'), 80);
  check(sec && /Packs/.test(sec.querySelector('h3')?.textContent || ''), 'settings: the section Packs');
  const ctyH = [...d.querySelectorAll('#ofc-set h3')].findIndex(h => /Country pack/.test(h.textContent)), pkH = [...d.querySelectorAll('#ofc-set h3')].findIndex(h => h.id === 'pkc-h');
  check(ctyH >= 0 && pkH > ctyH, 'the section comes after Country pack');
  await until(() => card(d, 'country/DE'));
  check(/No catalogue set up/.test(d.querySelector('#pkc .pkc-src')?.textContent || ''), 'no catalogue: the note');
  check(/Built in/.test(card(d, 'country/DE')?.textContent || '') && /Verified/.test(card(d, 'country/DE')?.querySelector('.pkc-badge')?.textContent || ''), 'no catalogue: DE built in, verified');
  check(!card(d, 'country/DE')?.querySelector('[data-pkc="install"],[data-pkc="remove"]'), 'a built-in pack has no install / uninstall button');
  check(d.querySelector('#os-ind-film'), 'the film box keeps its id');
  w.close();

  // ================= with the fake catalogue
  writeCatalogue();
  start(` -e KALMIDO_PACKS_CATALOG=${CAT}/index.json -e KALMIDO_PACKS_ALLOW_HOSTS=127.0.0.1:8097`, true);
  execFileSync('docker', ['exec', '-d', CT, 'python', '-m', 'http.server', '8097', '--bind', '127.0.0.1', '--directory', '/data/pkcat']);
  await sleep(800);
  CK = await login('alice'); BK = await login('bob');
  w = await boot({hash: 'office/settings'}); d = w.document;
  await until(() => card(d, 'country/AT'), 80);
  check(/Catalogue: 127\.0\.0\.1/.test(d.querySelector('#pkc .pkc-src')?.textContent || ''), 'catalogue: the source line');
  const at = card(d, 'country/AT');
  check(/Austria/.test(at?.querySelector('.pkc-name')?.textContent || '') && /Community/.test(at?.querySelector('.pkc-badge')?.textContent || ''), 'AT: English name, badge Community');
  check(!at?.querySelector('.pkc-desc b') && at?.querySelector('.pkc-desc i'), 'description: simple Markdown, no markup from the catalogue');
  check(/Verified/.test(card(d, 'industry/event')?.querySelector('.pkc-badge')?.textContent || ''), 'event: badge Verified');
  // search
  const q = d.querySelector('#pkc-q'); q.value = 'austr'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => cards(d).length === 1 && cards(d)[0] === 'country/AT'), 'search "austr": only AT ' + cards(d));
  q.value = 'zzzz-none'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => !cards(d).length && /No pack matches/.test(d.querySelector('#pkc-body')?.textContent || '')), 'search without hits: the note');
  q.value = ''; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(() => cards(d).length > 2);
  // kind filter
  click(w, d.querySelector('#pkc [data-pkc="kind"][data-kind="industry"]'));
  check(await until(() => cards(d).length && cards(d).every(k => k.startsWith('industry/'))), 'kind Industries: only industry packs ' + cards(d));
  click(w, d.querySelector('#pkc [data-pkc="kind"][data-kind=""]'));
  await until(() => cards(d).some(k => k.startsWith('country/')));
  // install the community pack: the warning first
  click(w, card(d, 'country/AT').querySelector('[data-pkc="install"]'));
  let md = await dlg(d);
  check(/not checked by the Kalmido team/.test(md?.textContent || ''), 'community: the warning before installing');
  click(w, md.querySelector('[data-cd="yes"]'));
  check(await until(() => /Installed v1/.test(card(d, 'country/AT')?.textContent || ''), 80), 'AT: Installed v1');
  check(await until(() => [...(d.querySelector('#os-pack')?.options || [])].some(o => o.value === 'AT')), 'the country pack choice offers AT');
  // a verified industry pack: no question; its box appears; Undo removes it again
  const nUndo = w.eval('HIST.undo.length');
  click(w, card(d, 'industry/event').querySelector('[data-pkc="install"]'));
  check(await until(() => /Installed v1/.test(card(d, 'industry/event')?.textContent || ''), 80) && !d.querySelector('.modal.cdlg'), 'event: installed without a question');
  check(await until(() => d.querySelector('#os-ind-event')), 'the calculation rules show the box of the event pack');
  check(w.eval('HIST.undo.length') === nUndo + 1, 'one undo step');
  w.eval("histStep('undo')");
  check(await until(() => card(d, 'industry/event')?.querySelector('[data-pkc="install"]'), 80), 'Undo: event is not installed any more');
  check(await until(() => !d.querySelector('#os-ind-event')), 'Undo: its box is gone');
  w.close();

  // ================= the country pack in use cannot be uninstalled
  const st = await call('PUT', '/api/office/settings', {pack: 'AT'});
  check(st.http === 200 && st.settings?.pack === 'AT', 'AT chosen as the country pack');
  w = await boot({hash: 'office/settings'}); d = w.document;
  await until(() => card(d, 'country/AT')?.querySelector('[data-pkc="remove"]'), 80);
  click(w, card(d, 'country/AT').querySelector('[data-pkc="remove"]'));
  md = await dlg(d);
  check(/Uninstall/.test(md?.textContent || ''), 'uninstall: asks first');
  click(w, md.querySelector('[data-cd="yes"]'));
  check(await until(() => /country pack of this office/.test(card(d, 'country/AT')?.querySelector('.pkc-err')?.textContent || ''), 80), 'in use: the reason in the card');
  check(/Installed v1/.test(card(d, 'country/AT')?.textContent || ''), 'in use: still installed');
  w.close();

  // ================= a member: the list, no buttons
  w = await boot({user: 'bob', hash: 'office/settings'}); d = w.document;
  await until(() => card(d, 'country/AT'), 80);
  check(card(d, 'country/AT') && !d.querySelector('#pkc [data-pkc="install"],#pkc [data-pkc="remove"],#pkc [data-pkc="update"],#pkc [data-pkc="refresh"]'), 'member: the list without buttons');
  w.close();

  // ================= phone width
  w = await boot({hash: 'office/settings', mobile: true}); d = w.document;
  await until(() => card(d, 'industry/event'), 80);
  check(d.querySelector('#pkc #pkc-q') && card(d, 'industry/event')?.querySelector('[data-pkc="install"]'), 'phone: the search and the buttons');
  w.close();

  console.log(`p276_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
