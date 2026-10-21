// 2.152.0 UI tests, part A (#2164 deleting an account, #2167 deleting an organisation), own container (start.sh;
// P2103A_NOSTART=1: a running server). jsdom:
// - the organisations list: deleting one with a knowledge page asks with the numbers ("1 knowledge page") and offers the
//   export; confirming deletes it
// - the delete dialog of an account with a personal office: it says the office goes with its files and names the document
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2103A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,office,wiki,files';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BETA = (await call('POST', '/api/admin/orgs', {name: 'Beta Films'})).id;
  await call('PATCH', '/api/settings', {workspace: `org:${BETA}`});
  const pg = await call('POST', '/api/wiki/pages', {space: `org:${BETA}`, path: 'Shoot day checklist'});
  check(pg.status < 300, 'setup: a knowledge page in Beta ' + pg.status);
  const FIO = (await call('POST', '/api/users', {orgs: [], username: 'fiona', display_name: 'Fiona Example', password: 'password123', email: 'fiona@example.com'})).id;
  const CF = await login('fiona');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CF);
  await call('GET', '/api/office/settings', null, CF);
  const doc = await call('POST', '/api/office/docs', {project_title: 'Imagefilm draft'}, CF);
  check(doc.status === 201, 'setup: fiona has a draft in her personal office ' + doc.status);

  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.__dialogs = 'manual';
  await until(() => d.querySelector('#side .srow'));
  w.eval(`settingsModal('users')`);
  await until(() => d.querySelector('.modal #a-users .mrow[data-urow]'));
  check(await until(() => w.eval(`typeof odlDelete === 'function' && typeof ua8_delete === 'function'`)), 'the admin code is loaded');

  // ---- #2167 the organisation's delete dialog: the numbers, the export, then deleted
  w.eval(`window.__od = odlDelete({id: ${BETA}, name: 'Beta Films'})`);
  const dlg = await until(() => [...d.querySelectorAll('.modal.cdlg')].find(m => /Beta Films/.test(m.textContent)));
  const txt = (dlg?.textContent || '').replace(/\s+/g, ' ');
  check(/Delete the organisation “Beta Films”\?/.test(txt) && /These go with it: 1 knowledge page\. Export the organisation first\./.test(txt), 'the dialog names 1 knowledge page ' + txt.slice(0, 300));
  check(dlg && dlg.querySelector('.oxbox') && dlg.querySelector('[data-cd="yes"]').classList.contains('danger'), 'the dialog offers the export and a red Delete');
  click(w, dlg.querySelector('[data-cd="yes"]'));
  check(await w.eval('window.__od') === true, 'confirmed: deleted');
  const orgs = (await call('GET', '/api/admin/orgs')).orgs || [];
  check(!orgs.some(o => o.id === BETA), 'Beta is gone from the organisations list');

  // ---- #2164 the account's delete dialog: the personal office goes with its files
  w.eval(`window.__ud = ua8_delete({id: ${FIO}, display_name: 'Fiona Example'})`);
  const ud = await until(() => [...d.querySelectorAll('.modal.cdlg')].find(m => /Fiona Example/.test(m.textContent)));
  const ut = (ud?.textContent || '').replace(/\s+/g, ' ');
  check(/The personal office goes with its files: 1 document\./.test(ut) && /basket, habits/.test(ut), 'the account dialog names the personal office ' + ut.slice(0, 300));
  click(w, ud.querySelector('[data-cd="no"]'));
  check(await w.eval('window.__ud') === false && (await call('GET', '/api/users')).status !== 500, 'cancelled: nothing deleted');
  check(((await call('GET', `/api/users/${FIO}/delete-info`)).purge || {}).office === 'delete', 'fiona is still there');

  console.log(`p2103_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
