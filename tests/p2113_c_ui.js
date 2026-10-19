// 2.113.0 UI test, part C (#2249): the unit select of a position follows the quantity (1 = singular, else plural), no redraw
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status, status: typeof j.status === 'string' ? j.status : r.status}; };  // a document's own status wins
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,office,clients';

// freelancer-matrix: office  (UI only, no new route; the person without an organisation uses the same editor code)
(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH', lines: ['Studio Nordlicht GmbH', 'Hafenstrasse 12', '20457 Hamburg']}, lang: 'de'});
  const S1 = (await call('POST', '/api/office/services', {name_de: 'Schnitt', name_en: 'Editing', category: 'Video', daily_rate: 500, unit: 'day', tax: 'standard'})).id;
  check(!!S1, 'service');
  for (const lang of ['de', 'en']) {
    const w = await boot({hash: 'office/offers'}); const d = w.document;
    await until(() => d.querySelector('.office [data-ofd="new"]'));
    d.querySelector('.office [data-ofd="new"]').click();
    await until(() => d.querySelector('.ofdeditor'), 60);
    if (lang === 'en') { const l = d.querySelector('#ofd-lang'); l.value = 'en'; l.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(600); }
    d.querySelector('[data-ofd="it-svc"]').click();
    await until(() => d.querySelector('.modal.ofdpick [data-sid]'));
    d.querySelector('.modal.ofdpick [data-sid]').click();
    await until(() => d.querySelectorAll('.ofdits .ofdit').length === 1, 60);
    const q = d.querySelector('.ofdits [data-k="qty"]'), sel = d.querySelector('.ofdits [data-k="unit"]');
    const txt = v => [...sel.options].find(o => o.value === v).textContent;
    const type = v => { q.focus(); q.value = v; q.dispatchEvent(new w.Event('input', {bubbles: true})); };
    const [one, many, hone, hmany] = lang === 'de' ? ['Tag', 'Tage', 'Stunde', 'Stunden'] : ['day', 'days', 'hour', 'hours'];
    const tag = ' (' + lang + ')';
    check(/^(Tag|Day|day)$/.test(txt('day')), 'qty 1: singular day: ' + txt('day') + tag);  // no pack labels in this fixture: the UI language (en) words
    type('5'); check(/^(Tage|Days|days)$/i.test(txt('day')) && /^(Stunden|Hours|hours?)$/i.test(txt('hour')) && d.activeElement === q, 'qty 5: plural, focus stays: ' + txt('day') + tag);
    type('1,5'); check(/^(Tage|Days|days)$/i.test(txt('day')) && d.activeElement === q, 'qty 1,5: plural' + tag);
    type(''); check(/^(Tage|Days|days)$/i.test(txt('day')), 'empty: plural' + tag);
    type('1'); check(/^(Tag|Day|day)$/i.test(txt('day')) && /^(Stunde|Hour|hour)$/i.test(txt('hour')), 'qty 1 again: singular ' + txt('hour') + tag);
    const fl = txt('flat'); type('5'); check(fl === txt('flat') && fl !== '', 'flat rate unchanged: ' + fl + tag);
    check(sel.value === 'day' && d.querySelector('.ofdits [data-k="qty"]') === q, 'selection and field node unchanged' + tag);
  }
  console.log(`p2113_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
