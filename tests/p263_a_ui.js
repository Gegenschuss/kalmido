// 2.63.0 part A UI test, own container (start.sh), jsdom.
// #1513: the form dialog of a list has the report settings: type of report, one file, a status link for the sender; the
//        status link switches "ask for an e-mail address" on (and locks it); all three are saved and shown again.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const change = (w, el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const FEAT = 'cal,comments,collab,agents,clients,workload,forms';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('PATCH', '/api/admin/settings', {public_links: true});
  const P = (await call('POST', '/api/lists', {name: 'Support'})).id;

  let w = await boot({user: 'alice', hash: `l/${P}`}), d = w.document;
  w.eval(`listModal(${P})`); await sleep(300);
  click(w, d.querySelector('.modal [data-act="forms-open"]')); await sleep(600);
  let md = [...d.querySelectorAll('.modal')].pop();
  click(w, md.querySelector('[data-fm="new"]')); await sleep(200);
  let ed = [...d.querySelectorAll('.modal')].pop();
  check(ed.querySelector('#fm-ttype') && ed.querySelector('#fm-files') && ed.querySelector('#fm-portal') && /never internal comments/.test(ed.textContent),
    '#1513: the dialog has type of report, file, status link and a hint what the customer sees');
  check([...ed.querySelector('#fm-ttype').options].map(o => o.value).join(',') === ',bug,feature,task', '#1513: the types: none, bug, feature, task');
  input(w, ed.querySelector('#fm-title'), 'Bug report');
  change(w, ed.querySelector('#fm-access'), 'public');
  ed.querySelector('#fm-email').checked = false;
  change(w, ed.querySelector('#fm-ttype'), 'bug');
  ed.querySelector('#fm-files').checked = true;
  ed.querySelector('#fm-portal').checked = true; change(w, ed.querySelector('#fm-portal'));
  check(ed.querySelector('#fm-email').checked && ed.querySelector('#fm-email').disabled, '#1513: the status link turns the e-mail field on and locks it');
  click(w, ed.querySelector('[data-m="save"]'));
  await until(() => [...d.querySelectorAll('.modal')].some(m => /Bug report/.test(m.textContent)));
  let fl = await call('GET', `/api/lists/${P}/forms`);
  const f = fl.forms?.[0] || {};
  check(f.title === 'Bug report' && f.access === 'public' && f.ttype === 'bug' && f.files === true && f.portal === true && f.ask_email === true,
    '#1513: saved: type bug, file, status link, e-mail on ' + JSON.stringify(f));
  w.close();

  // open it again: the settings are shown; switch the status link off and the type to feature
  w = await boot({user: 'alice', hash: `l/${P}`}); d = w.document;
  w.eval(`listModal(${P})`); await sleep(300);
  click(w, d.querySelector('.modal [data-act="forms-open"]')); await sleep(600);
  md = [...d.querySelectorAll('.modal')].pop();
  click(w, md.querySelector(`[data-fid="${f.id}"] [data-fm="edit"]`)); await sleep(200);
  ed = [...d.querySelectorAll('.modal')].pop();
  check(ed.querySelector('#fm-ttype').value === 'bug' && ed.querySelector('#fm-files').checked && ed.querySelector('#fm-portal').checked && ed.querySelector('#fm-email').disabled,
    '#1513: the dialog shows the saved settings');
  ed.querySelector('#fm-portal').checked = false; change(w, ed.querySelector('#fm-portal'));
  check(!ed.querySelector('#fm-email').disabled, '#1513: without the status link the e-mail field is free again');
  change(w, ed.querySelector('#fm-ttype'), 'feature');
  ed.querySelector('#fm-files').checked = false;
  click(w, ed.querySelector('[data-m="save"]'));
  await until(async () => (await call('GET', `/api/lists/${P}/forms`)).forms?.[0]?.ttype === 'feature');
  fl = await call('GET', `/api/lists/${P}/forms`);
  check(fl.forms[0].ttype === 'feature' && fl.forms[0].files === false && fl.forms[0].portal === false && fl.forms[0].ask_email === true,
    '#1513: changed: feature, no file, no status link, e-mail stays ' + JSON.stringify(fl.forms[0]));
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
