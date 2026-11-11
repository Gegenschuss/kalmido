// 2.979.0 UI test, part B (#5667, the office): an undo / redo the server takes back by its group no longer runs the entry's
// kalmido-suite: fresh
// own undo function, which used to fetch the office area again; the areas register how they fetch (core.js histReloader).
// freelancer-matrix: undo (a person without an organisation: her archived contract in her personal office comes back with one undo)
// jsdom, fresh container. Invented names, companies and figures only.
//  - contracts (office_agreements.js AGR): archive one in the open tab, one undo shows it again, redo hides it, the next change
//    on the row brought back works (the server has it archived), a list not shown is read again when the tab opens
//  - the office settings (OFC.info): no group of the server (their own undo runs); the tax reserve changed, one undo -> the old
//    value again, shown in the settings field, the next change works
//  - bank rules (office_bankrules.js BRL, a settings section): a rule switched off, undo -> the section shows it on again
//  - fiona (no organisation, her personal office): archive a contract + undo in her tab
// The waits are on states (rows, values, counters), never on a fixed time.
const {boot, errs, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const until = (fn, ms) => until0(fn, {timeout: ms || 20000, step: 100});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const AGR_BODY = name => ({kind: 'insurance', name, provider: 'Beispiel Versicherung AG', cost: 120, per: 'year', ends: '2031-06-30', notice: 0, renew_months: 12, lead_days: 30});

// a contract archived in the open tab, undo / redo by the server's group; -> the window
async function contracts(ck, user, name) {
  const a = await call(ck, 'POST', '/api/office/agreements', AGR_BODY(name));
  check(a.http === 201 && a.id > 0, `${user}: a contract (${a.http})`);
  const w = await boot({user, hash: 'office/agreements'}), d = w.document;
  const row = () => [...d.querySelectorAll('.agr-li .ofcrow')].find(b => b.textContent.includes(name)) || null;
  check(await until(() => row()), `${user}: the tab lists the contract`);
  const steps = () => w.eval('HIST.undo.length');
  const n0 = steps();
  await w.eval(`agrArchive(AGR.data.items.find(x => x.id === ${a.id}), true).then(() => 1)`);
  check(await until(() => !row() && steps() > n0), `${user}: archived, the row leaves the list, one step`);
  check(await until(() => w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length') > 0), `${user}: the step is a group of the server`);
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => row()), `${user}: undo (server group): the open tab shows the contract again`);
  return {w, d, row, id: a.id};
}

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha Studio', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});

  // ================= contracts (AGR)
  const {w, d, row, id} = await contracts(CA, 'alice', 'Inventarversicherung');
  await w.eval(`histStep('redo').then(() => 1)`);
  check(await until(() => !row()), 'redo: archived again, the row goes');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => row()), 'undo once more: back');
  // the next change on the row brought back: the page has the new state
  await w.eval(`agrArchive(AGR.data.items.find(x => x.id === ${id}), true).then(() => 1)`);
  check(await until(() => !row()), 'the contract brought back can be changed again (archive)');
  const srv = ((await call(CA, 'GET', '/api/office/agreements?archived=1')).items || []).find(x => x.id === id) || {};
  check(!!srv.archived, `the server has it archived (${JSON.stringify(srv.archived)})`);
  // a list not shown: undo on another page, the tab reads it again when it opens
  w.location.hash = 'home';
  check(await until(() => !d.querySelector('.dash.office')), 'another page');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(w.eval('AGR.data') === null, 'the contracts not shown are marked old');
  w.location.hash = 'office/agreements';
  check(await until(() => row()), 'back in the tab: the contract is there again');

  // ================= the office settings (OFC.info): the tax reserve
  const pct = () => +w.eval('OFC.info?.settings?.tax_reserve_pct || 0');
  const p0 = pct(), p1 = p0 === 33 ? 34 : 33;
  await w.eval(`bkSetUndo('tax_reserve_pct', ${p1}).then(() => 1)`);
  check(await until(() => pct() === p1), `tax reserve set to ${p1} (${pct()})`);
  const gs = w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length');
  // the office settings write no undo group (PUT /api/office/settings): the entry's own undo (ost_back / bkSet) takes it back.
  // Should they get a group one day, this turns red: then OFC.info needs a histReloader in office.js (ofcInfo(true))
  check(gs === 0, `the settings step has no group of the server, its own undo runs (${gs})`);
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => pct() === p0), `undo: the office has the old tax reserve again (${pct()} = ${p0})`);
  w.eval(`settingsModal('biz')`);
  // the field sits in Settings > Company & office (Bank & taxes); drawn from OFC.info, so it shows the value the undo left
  if (await until(() => d.querySelector('#bk-reserve'), 10000)) check(+d.querySelector('#bk-reserve').value === p0, `the settings field shows the old value (${d.querySelector('#bk-reserve').value})`);
  else console.log('note: #bk-reserve not drawn in the settings dialog here, value checked on OFC.info only');
  await w.eval(`bkSetUndo('tax_reserve_pct', ${p1}).then(() => 1)`);
  check(await until(() => pct() === p1), 'the next change works');
  check(+(await call(CA, 'GET', '/api/office/settings')).settings?.tax_reserve_pct === p1, 'the server has it');

  // ================= bank rules (BRL, a section of the office settings)
  const rule = await call(CA, 'POST', '/api/office/bank/rules', {name: 'Kontogebühr', counterpart: 'Beispielbank', action: 'private', active: true});
  const rid = rule.rule?.id || rule.id;
  check(rule.http < 300 && rid > 0, `a bank rule (${rule.http})`);
  w.eval(`BRL.oid = -1; brl_settingsHtml()`);  // as the settings page does when it draws the section
  const ruleOn = () => !!w.eval(`(BRL.items || []).find(r => r.id === ${rid})?.active`);
  check(await until(() => ruleOn()), 'the section has the rule, switched on');
  const n1 = w.eval('HIST.undo.length');
  await w.eval(`brl_on(${rid}, false).then(() => 1)`);
  check(await until(() => !ruleOn() && w.eval('HIST.undo.length') > n1), 'switched off, one step');
  await w.eval(`histStep('undo').then(() => 1)`);
  // shown: read at once (the switch is on again); not shown: marked old, the next drawing reads it
  if (!d.querySelector('.brlset')) w.eval('brl_settingsHtml()');
  check(await until(() => ruleOn()), 'undo (server group): the rules section has the rule on again');
  const sw = d.querySelector(`.brlset input[data-brl-on="${rid}"]`);
  if (sw) check(sw.checked, 'the switch in the shown section is on');
  check(!!(await call(CA, 'GET', '/api/office/bank/rules')).items?.find(r => r.id === rid)?.active, 'the server has it on');
  w.eval(`document.querySelector('.smodal')?.remove()`);
  w.close();

  // ================= a person without an organisation (her personal office)
  await call(CA, 'POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com', orgs: []});
  const CF = await login('fiona');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  const f = await contracts(CF, 'fiona', 'Kameraversicherung');
  await f.w.eval(`agrArchive(AGR.data.items.find(x => x.id === ${f.id}), true).then(() => 1)`);
  check(await until(() => !f.row()), 'fiona: the contract brought back can be archived again');
  f.w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2979_b_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(err => { console.error(err); process.exit(1); });
