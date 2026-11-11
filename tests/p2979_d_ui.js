// 2.979.0 UI test, part C (#5667): an undo / redo the server takes back by its group (undo.js histDo, #5255) no longer runs the
// entry's own undo function, which used to fetch the area again; areas with their own store in the browser register how they
// fetch (core.js histReloader, undo.js histRedraw). Here: the household budget (BG) and "Read later" (RDL).
// kalmido-suite: fresh
// freelancer-matrix: undo (a person without an organisation: her ticked read-later link comes back with one undo)
// jsdom, fresh container. Invented names only.
//  - budget: an entry deleted in the open view; one undo shows it again, redo takes it away, undo once more; then changing its
//    amount in the dialog works (the page has the new version, no 409) and the server has it
//  - read later: ticking a link off takes it out of the open list; undo shows it again, redo, undo; ticking it off again works
//  - read later not shown: the list is marked old after the undo and the view fetches it when it opens again
//  - fiona (no organisation): tick + undo in her read-later list
// The waits are on states (rows, counters, server answers), never on a fixed time.
const {boot, errs, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const until = (fn, ms) => until0(fn, {timeout: ms || 20000, step: 100});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const pad = n => String(n).padStart(2, '0');
const now = new Date(), MONTH = `${now.getFullYear()}-${pad(now.getMonth() + 1)}`, DAY = `${MONTH}-${pad(now.getDate())}`;
const FEAT = 'budget,reading';

// a read-later list with two links; the view open
async function reading(ck, user, tag) {
  const a = await call(ck, 'POST', '/api/reading', {url: `https://example.com/${tag}-later-eins`, title: `Walross ${tag}`, space: 'private'});
  const b = await call(ck, 'POST', '/api/reading', {url: `https://example.com/${tag}-later-zwei`, title: `Kranich ${tag}`, space: 'private'});
  check(a.task_id > 0 && b.task_id > 0, `${user}: two links to read later (${a.http} ${b.http})`);
  const w = await boot({user, hash: 'reading'}); const d = w.document;
  const row = id => d.querySelector(`.rlrow[data-id="${id}"]`);
  check(await until(() => row(a.task_id) && row(b.task_id)), `${user}: the read-later view shows both links`);
  return {w, d, row, A: a.task_id, Bid: b.task_id};
}

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: []});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', features: FEAT, tour: 'done', workspace: 'private'});

  // ================= the budget: delete an entry in the open view, undo with the arrow
  const L = await call(CA, 'POST', '/api/budget/lists', {name: 'Haushalt Alice'});
  check(L.list_id > 0, `a budget (${L.http})`);
  const E = await call(CA, 'POST', `/api/budget/${L.list_id}/entries`, {day: DAY, amount: '12.50', kind: 'out', title: 'Zebra Bakery'});
  check(E.id > 0, `an entry (${E.http})`);
  let w = await boot({user: 'alice', hash: `budget/${L.list_id}`}); let d = w.document;
  const ent = () => d.querySelector(`.bgview [data-bg="entry"][data-id="${E.id}"]`);
  const steps = () => w.eval('HIST.undo.length');
  check(await until(() => ent()), 'budget: the view shows the entry');
  let n0 = steps();
  await w.eval(`bg_delEntry(BG.data.entries.find(x => x.id === ${E.id})).then(() => 1)`);
  check(await until(() => !ent() && steps() > n0), 'budget: deleted, the row goes, one step');
  check(await until(() => w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length') > 0), 'budget: the step is a group of the server');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => ent()), 'budget: undo (server group): the open view shows the entry again');
  check(/Zebra Bakery/.test(d.querySelector('.bgview')?.textContent || ''), 'budget: ... with its title');
  await w.eval(`histStep('redo').then(() => 1)`);
  check(await until(() => !ent()), 'budget: redo: deleted again, the row goes');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => ent()), 'budget: undo once more: back');
  // the next change on the entry brought back: the dialog has the current version (no 409), the server takes it
  const dlg = () => d.querySelector('.modal.bgdlg');
  click(w, ent()); check(await until(() => dlg()?.querySelector('#bg-amt')), 'budget: the entry opens in its dialog');
  dlg().querySelector('#bg-amt').value = '15';
  click(w, dlg().querySelector('[data-m="save"]'));
  check(await until(() => !dlg()), 'budget: saved, the dialog closes');
  const E2 = await until(async () => { const x = (await call(CA, 'GET', `/api/budget/${L.list_id}?month=${MONTH}`)).entries?.find(y => y.id === E.id); return x && +x.amount === 15 && x; });
  check(E2 && +E2.amount === 15, `budget: the change after the undo reached the server (${JSON.stringify(E2 || null)})`);
  check(!/conflict|changed meanwhile|409/i.test(d.querySelector('#toast')?.textContent || ''), `budget: no conflict message (${d.querySelector('#toast')?.textContent || ''})`);
  w.close();

  // ================= read later: tick a link off in the open list, undo with the arrow
  const r = await reading(CA, 'alice', 'alice');
  w = r.w; d = r.d;
  n0 = steps();
  click(w, r.row(r.A)?.querySelector('[data-rl="tick"]'));
  check(await until(() => !r.row(r.A) && steps() > n0), 'read later: ticked off, the link leaves the open list, one step');
  check(await until(() => w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length') > 0), 'read later: the step is a group of the server');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => r.row(r.A)), 'read later: undo (server group): the open list shows the link again');
  check(/Walross alice/.test(r.row(r.A)?.textContent || ''), 'read later: ... with its title');
  await w.eval(`histStep('redo').then(() => 1)`);
  check(await until(() => !r.row(r.A)), 'read later: redo: ticked off again');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => r.row(r.A)), 'read later: undo once more: back');
  // the next change works on the row brought back
  n0 = steps();
  click(w, r.row(r.A)?.querySelector('[data-rl="tick"]'));
  check(await until(() => !r.row(r.A) && steps() > n0), 'read later: the link brought back can be ticked off again');
  const srvA = await until(async () => { const t = await call(CA, 'GET', `/api/tasks/${r.A}`); return t.done || t.status === 1 || t.completed_at ? t : null; });
  check(srvA, 'read later: the server has it done');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => r.row(r.A)), 'read later: and back');

  // ---- a list not shown is old after the undo; the view fetches it when it opens again
  n0 = steps();
  click(w, r.row(r.Bid)?.querySelector('[data-rl="tick"]'));
  check(await until(() => !r.row(r.Bid) && steps() > n0), 'read later: ticked off before leaving the view, one step');
  w.location.hash = 'home';
  check(await until(() => !d.querySelector('.rlview')), 'another page');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(w.eval('RDL.at') === 0, 'read later: the list not shown is marked old');
  w.location.hash = 'reading';
  check(await until(() => r.row(r.Bid)), 'read later: back in the view, the link is there again');
  w.close();

  // ================= a person without an organisation (freelancer parity)
  await call(CA, 'POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com', orgs: []});
  const CF = await login('fiona');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', features: FEAT, tour: 'done', workspace: 'private'});
  const f = await reading(CF, 'fiona', 'fiona');
  const fn0 = f.w.eval('HIST.undo.length');
  click(f.w, f.row(f.A)?.querySelector('[data-rl="tick"]'));
  check(await until(() => !f.row(f.A) && f.w.eval('HIST.undo.length') > fn0), 'fiona: ticked off, one step (after the answer)');
  await f.w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => f.row(f.A)), 'fiona: one undo shows her link again');
  f.w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2979_d_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(err => { console.error(err); process.exit(1); });
