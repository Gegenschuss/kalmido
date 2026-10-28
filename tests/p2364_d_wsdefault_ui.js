// kalmido-suite: fresh
// 2.364.0 D (#3033) "New project": under "All workspaces" the workspace starts on the one picked last for a new project, else
// Private (no longer the first organisation); the choice is the question "For whom?" right under the title, then the name;
// everything else sits under "More options" (closed) and is sent as before. Under "All" a private project carries a small
// house in the sidebar. Own container (start.sh), jsdom.
// freelancer-matrix: lists - frida has no organisation: name only (no "For whom?"), the rest folded, no house marks.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (f, ms = 6000) => { for (let t = 0; t < ms; t += 100) { const v = await f(); if (v) return v; await sleep(100); } return f(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,kanban,timeline';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'all'});
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(fu.http < 300 && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'P4: frida is in no organisation');
  const OL = (await call(CA, 'POST', '/api/lists', {name: 'Shoot', org_id: org.id})).id;
  const PL = (await call(CA, 'POST', '/api/lists', {name: 'Move house', org_id: null})).id;
  const lists = async ck => (await call(ck, 'GET', '/api/state')).lists || [];
  check((await lists(CA)).find(l => l.id === OL)?.org_id === org.id && !(await lists(CA)).find(l => l.id === PL)?.org_id, 'an organisation project and a private one');

  const open = async w => { w.eval('listModal(null)'); return until(() => w.document.querySelector('.modal.lnew #l-name')?.closest('.modal')); };
  // (1) alice under "All workspaces": the dialog starts on Private, "For whom?" on top, the rest folded
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  check(w.eval('wsCur()') === 'all', 'alice shows all workspaces');
  let md = await open(w);
  const ws = md?.querySelector('#l-ws');
  check(ws && ws.value === '', 'All workspaces: a new project starts on Private ' + (ws && ws.value));
  const card = md.querySelector('.card'), kids = [...card.children];
  check(kids[0].tagName === 'H3' && kids[1].classList.contains('lwsrow') && /For whom\?/.test(kids[1].querySelector('label')?.textContent || ''), '"For whom?" right under the title ' + kids.slice(0, 3).map(k => k.className || k.tagName).join('|'));
  const more = md.querySelector('details.lnmore');
  check(more && !more.open && /More options/.test(more.querySelector('summary').textContent), '"More options" is there and closed');
  check(!md.querySelector('#l-name').closest('details') && !ws.closest('details'), 'name and "For whom?" outside');
  check(['#l-folder', '#l-view', '#l-col', '#lm-sec-proj', '#l-nag'].every(s => md.querySelector(s)?.closest('details.lnmore')), 'folder, view, colour, project features, reminders under "More options" (2.352.0 B #2752: no progress switch any more)');
  check(md.querySelector('.foot [data-m="save"]') && !md.querySelector('.foot').closest('details'), 'Create stays at the foot');
  // pick the organisation, create
  ws.value = String(org.id); ws.dispatchEvent(new w.Event('change', {bubbles: true}));
  md.querySelector('#l-name').value = 'Casting';
  click(w, md.querySelector('[data-m="save"]'));
  const made = await until(async () => (await lists(CA)).find(l => l.name === 'Casting'));
  check(made && made.org_id === org.id, 'created in the organisation ' + JSON.stringify(made && made.org_id));
  // the next one starts on the workspace picked last
  md = await open(w);
  check(md?.querySelector('#l-ws')?.value === String(org.id), 'the next new project starts on the workspace picked last');
  md.remove();
  // the sidebar under "All": a house at the private project only
  await w.eval('load().then(render)');
  const prow = await until(() => d.querySelector(`#side .srow[data-list="${PL}"]`));
  check(prow && prow.querySelector('.wsprv'), 'the private project carries the house');
  check(!d.querySelector(`#side .srow[data-list="${OL}"] .wsprv`), 'the organisation project does not');
  w.close();

  // (2) P4: frida (no organisation): name only, the rest folded, she can create
  w = await boot({user: 'frida', hash: 'today'}); d = w.document;
  md = await open(w);
  check(md && !md.querySelector('#l-ws') && md.querySelector('details.lnmore:not([open])'), 'frida: no "For whom?", the rest folded');
  md.querySelector('#l-name').value = 'Taxes';
  click(w, md.querySelector('[data-m="save"]'));
  check(await until(async () => (await lists(CF)).some(l => l.name === 'Taxes')), 'frida: created');
  await w.eval('load().then(render)');
  check(!d.querySelector('#side .wsprv'), 'frida: no house marks (no workspaces)');
  w.close();

  console.log(`p2364_d_wsdefault_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
