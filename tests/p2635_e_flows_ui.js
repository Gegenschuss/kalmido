// 2.635.0 E UI test (#4856): document flows are edited in Settings > Documents (jsdom, own container). Invented names only.
// kalmido-suite: fresh
// - a flow is added through the form; the pencil opens the same form filled; a changed field + "Save flow" -> the list shows it
// - the share target (a group) is ticked and saved -> stored on the server, the list names the share
// - on / off sends the flow's version: after the flow changed elsewhere the switch gets the 409, the list shows the new state
//   and the flow is not switched off; with the current version it switches
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const flows = async () => (await call('GET', '/api/docs/settings?ws=private')).rules || [];

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'files,docs,collab'});
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const grp = await call('POST', '/api/admin/groups', {name: 'Crew Eins'});
  check(bob.id && grp.id, 'setup: bob and the group');

  const w = await boot({user: 'alice', hash: 'docs'}), d = w.document;
  w.eval(`settingsModal('docs')`);
  const form = () => d.querySelector('.dfl-add');
  check(await until(() => form()), 'the settings show the flow form ' + (d.querySelector('.dc-smd')?.textContent || 'no modal').slice(0, 300));
  const val = (id, v) => { const x = d.querySelector('#' + id); x.value = v; x.dispatchEvent(new w.Event('input', {bubbles: true})); x.dispatchEvent(new w.Event('change', {bubbles: true})); };
  const list = () => d.querySelector('.dc-smd .dc-rules')?.textContent || '';

  // add
  val('dfl-name', 'Strom'); val('dcr-match', 'Stadtwerke'); val('dcr-type', 'Abschlag');
  click(w, form().querySelector('[data-dcs="radd"]'));
  check(await until(async () => (await flows()).some(r => r.name === 'Strom')), 'add: the flow is stored');
  check(await until(() => /Strom/.test(list())), 'add: the list shows it ' + list());

  // pencil -> filled form -> change -> save
  const edit = () => d.querySelector('[data-dcs^="redit:"]:not([data-dcs="redit:0"])');
  check(await until(() => edit()), 'the pencil button is there');
  click(w, edit());
  check(await until(() => form()?.dataset.edit && d.querySelector('#dfl-name').value === 'Strom'), 'the pencil opens the form filled with the name');
  check(d.querySelector('#dcr-match').value === 'Stadtwerke' && d.querySelector('#dcr-type').value === 'Abschlag', 'the form is filled with the filter and the action');
  check(/Save flow/.test(form().querySelector('[data-dcs="radd"]').textContent), 'the button says "Save flow"');
  val('dfl-name', 'Strom neu'); val('dcr-type', 'Strom');
  click(w, form().querySelector('[data-dcs="radd"]'));
  check(await until(async () => (await flows()).some(r => r.name === 'Strom neu' && r.type === 'Strom')), 'save: stored on the server');
  check(await until(() => /Strom neu/.test(list()) && /Document type: Strom/.test(list())), 'save: the list shows the change ' + list());
  check((await flows()).length === 1, 'save: still one flow (not a second one)');

  // the share target
  click(w, edit());
  const box = await until(() => d.querySelector(`[data-dfl="share"][value="group_id:${grp.id}"]`));
  check(box, 'the form offers the group as a share target');
  if (box) { box.checked = true; box.dispatchEvent(new w.Event('change', {bubbles: true})); }
  click(w, form().querySelector('[data-dcs="radd"]'));
  check(await until(async () => (await flows()).some(r => (r.share || []).some(x => x.group_id === grp.id && x.role === 'view'))), 'share: the group is stored with the role view');
  check(await until(() => /Share: 1/.test(list())), 'share: the list names it ' + list());
  click(w, edit());
  check(await until(() => d.querySelector(`[data-dfl="share"][value="group_id:${grp.id}"]`)?.checked), 'share: the form shows it ticked again');
  click(w, d.querySelector('.dfl-cancel'));

  // on / off with the version
  const tog = () => d.querySelector('[data-dcs^="rtog:"]');
  const id = (await flows())[0].id;
  const v0 = (await flows())[0].updated_at;
  const other = await call('PATCH', `/api/docs/rules/${id}`, {...(await flows())[0], id: undefined, name: 'Strom woanders', expect_updated_at: v0});  // changed elsewhere; the page still has v0
  check(other.status === 200, 'setup: changed elsewhere ' + other.status);
  click(w, tog());
  check(await until(() => /Strom woanders/.test(list())), 'conflict: the list is reloaded with the other change ' + list());
  check(!(await flows())[0].off, 'conflict: the stale switch did not switch the flow off');
  click(w, tog());
  check(await until(async () => (await flows())[0].off === true), 'with the current version: switched off');
  check((await flows())[0].name === 'Strom woanders', 'switching does not overwrite the other change');
  click(w, tog());
  check(await until(async () => !(await flows())[0].off), 'switched on again');
  w.close();

  console.log(`p2635_e_flows_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
