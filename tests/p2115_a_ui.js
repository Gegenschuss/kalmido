// 2.115.0 UI tests (part A, #2061), own container (start.sh). jsdom:
// list settings > Inbound webhook (owner): "Add inbound webhook" asks for a name, the URL shows once with a copy button and a
// curl example, the row shows name and "Not used yet", a request through the URL counts; delete asks first and is one undo
// step (undo brings it back); an edit member does not see the section; the basket has none.
// Settings > Organisation: an admin sees the section Webhooks of the organisation, the dialog groups the events (Tasks,
// Calendar, Files, Invoices, Time tracking); a member does not see it. The history line of a task made by the webhook
// reads "via webhook".
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2115A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,events,files,time';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const bob = await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  const W = (await call('POST', '/api/lists', {name: 'Home', org_id: null})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: bob.id, role: 'edit'});

  // ================= the section in the list settings
  let w = await boot({user: 'alice'}), d = w.document;
  w.__dialogs = 'manual';
  w.eval(`listModal(${W})`);
  await until(() => d.querySelector('#l-whi [data-whi-add]'));
  const box = () => d.querySelector('#l-whi');
  check(box() && /Inbound webhook/.test(box().previousElementSibling?.textContent || ''), '#2061: the list settings have the section Inbound webhook');
  click(w, box().querySelector('[data-whi-add]'));
  await until(() => d.querySelector('.cdlg #cdlg-in'));
  const inp = d.querySelector('.cdlg #cdlg-in');
  check(!!inp, '#2061: "Add" asks for a name');
  inp.value = 'Home Assistant';
  d.querySelector('.cdlg form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await until(() => box()?.querySelector('.whi-url code'));
  const url = box()?.querySelector('.whi-url code')?.textContent || '';
  check(/\/api\/hooks\/in\/khi_/.test(url), '#2061: the URL shows once: ' + url.slice(0, 60));
  check(!!box()?.querySelector('[data-whi-copy="url"]') && !!box()?.querySelector('[data-whi-copy="curl"]'), '#2061: copy buttons for the URL and the curl example');
  check(/curl -X POST/.test(box()?.querySelector('.whi-ex')?.textContent || ''), '#2061: the curl example');
  check(/Home Assistant/.test(box()?.querySelector('.whi-row')?.textContent || '') && /Not used yet/.test(box()?.querySelector('.whi-row')?.textContent || ''), '#2061: the row: name, not used yet');
  const hooks = (await call('GET', `/api/lists/${W}/hooks-in`)).hooks || [];
  check(hooks.length === 1 && hooks[0].name === 'Home Assistant', '#2061: saved on the server');
  // a request through the URL (no cookie)
  const tok = url.split('/api/hooks/in/')[1];
  const p = await fetch(B + 'api/hooks/in/' + tok, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title: 'From the hook'})});
  check(p.status === 201, '#2061: the URL creates a task ' + p.status);
  const tid = (await p.json()).id;
  const tl = await call('GET', `/api/tasks/${tid}/timeline`);
  const a = (tl.activity || []).find(x => x.kind === 'created');
  const txt = a ? w.eval(`actText(${JSON.stringify(a)}, ${JSON.stringify(tl.users || {})})`) : '';
  check(/via webhook/.test(txt), '#2061: the history line reads "via webhook": ' + txt.replace(/<[^>]+>/g, '').slice(0, 120));
  // delete asks first, one undo step
  await w.eval(`(async () => { await whiLoad(${W}); document.querySelector('#l-whi').innerHTML = whiRowsHtml(${W}); })()`);
  check(/1 task created/.test(box()?.querySelector('.whi-row')?.textContent || ''), '#2061: the row counts the tasks: ' + (box()?.querySelector('.whi-row')?.textContent || '').trim().slice(0, 80));
  click(w, box().querySelector('[data-whi-menu]'));
  await until(() => [...d.querySelectorAll('.menu-list [role="menuitem"]')].find(b => /Delete/.test(b.textContent)));
  click(w, [...d.querySelectorAll('.menu-list [role="menuitem"]')].find(b => /Delete/.test(b.textContent)));
  await until(() => d.querySelector('.cdlg [data-cd="yes"]'));
  check(/Delete the inbound webhook/.test(d.querySelector('.cdlg')?.textContent || ''), '#2061: delete asks first');
  click(w, d.querySelector('.cdlg [data-cd="yes"]'));
  await until(async () => !((await call('GET', `/api/lists/${W}/hooks-in`)).hooks || []).length);
  check(!((await call('GET', `/api/lists/${W}/hooks-in`)).hooks || []).length, '#2061: deleted');
  const p2 = await fetch(B + 'api/hooks/in/' + tok, {method: 'POST', headers: {'Content-Type': 'text/plain'}, body: 'after delete'});
  check(p2.status === 404, '#2061: a deleted URL answers 404');
  await w.eval(`histStep('undo')`); await sleep(600);
  check(((await call('GET', `/api/lists/${W}/hooks-in`)).hooks || []).length === 1, '#2061: undo brings it back');
  d.querySelector('.modal')?.remove();
  // the basket has no section
  const inbox = w.eval(`S.lists.find(l => l.is_inbox).id`);
  w.eval(`listModal(${inbox})`); await sleep(700);
  check(!d.querySelector('#l-whi'), '#2061: the basket has no inbound webhook');
  d.querySelectorAll('.modal').forEach(m => m.remove());

  // ================= Settings > Organisation > Webhooks
  w.eval(`settingsModal('org')`);
  await until(() => d.querySelector(`.whobox[data-whoorg="${ORG}"] [data-who="new"]`), 60);
  const ob = d.querySelector(`.whobox[data-whoorg="${ORG}"]`);
  check(!!ob && /Webhooks/.test(ob.querySelector('h5')?.textContent || ''), '#2061: the organisation has a section Webhooks');
  await until(() => /No webhooks yet/.test(ob.querySelector('.whorows')?.textContent || ''));
  check(/No webhooks yet/.test(ob.querySelector('.whorows')?.textContent || ''), '#2061: none yet');
  click(w, ob.querySelector('[data-who="new"]'));
  await until(() => d.querySelector('#wh-evs .whevg'));
  const groups = [...d.querySelectorAll('#wh-evs .whevg > b')].map(x => x.textContent);
  check(['Tasks', 'Calendar', 'Files', 'Invoices', 'Time tracking'].every(g => groups.includes(g)), '#2061: the events in groups ' + JSON.stringify(groups));
  check(/never the members’ private areas/.test(d.querySelector('.modal')?.textContent || ''), '#2061: the dialog says: never the private areas');
  w.close();
  const wb = await boot({user: 'bob'});
  wb.eval(`settingsModal('org')`); await sleep(1500);
  check(!wb.document.querySelector('.whobox'), '#2061: a member does not see the organisation\'s webhooks');
  wb.eval(`listModal(${W})`); await sleep(800);
  check(!wb.document.querySelector('#l-whi'), '#2061: an edit member does not see the inbound webhooks');
  wb.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
