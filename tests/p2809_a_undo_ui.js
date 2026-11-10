// 2.809.0 UI test, part A (#5476): undo across devices for the areas of group 1 - a project's settings and a section in
// "Recent steps" (static/js/undolist.js) as rows of the server, not "only this device".
// kalmido-suite: fresh
// freelancer-matrix: undo (a person without an organisation: her renamed project goes back from the list)
// jsdom, fresh container. Invented names only. alice renames a project in this browser (dialogs.js listPatch) and adds a
// section (dnd.js sectionCreate):
//  - the list "Recent steps" shows both as rows of the server ("This device"), with their labels, and no row "only this
//    device" for them
//  - the second device (another sign-in of alice) lists the same steps and takes the rename back on the server; this browser
//    shows the old name after the poll
//  - "Back up to here" on the section row in this browser takes the section back (gone in the sidebar's project), the row
//    says "Undone" and offers "Redo", which brings it back
// The waits are on states (rows, names, sections), never on a fixed time.
const {boot, errs, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const until = (fn, ms) => until0(fn, {timeout: ms || 20000, step: 100});
const call = async (ck, method, url, body, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...hd, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const FEAT = 'comments,collab';

async function person(ck, user, tag) {
  const L = (await call(ck, 'POST', '/api/lists', {name: `Projekt ${tag}`})).id;
  check(L, `${user}: a project`);
  const w = await boot({user, hash: `l/${L}`}); const d = w.document;
  const row = id => d.querySelector(`#pop:not(.hidden) .ulbody .ulrow[data-ul="s:${id}"]`);
  const open = () => d.querySelector('#top [data-act="hist-undo"]').dispatchEvent(new w.MouseEvent('contextmenu', {bubbles: true, cancelable: true}));
  return {L, w, d, row, open};
}

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', features: FEAT, tour: 'done'});
  const {L, w, d, row, open} = await person(CA, 'alice', 'Alpha');
  const name = () => w.eval(`listById(${L})?.name || ''`);

  // ---- this browser: a rename (project settings) and a new section
  await w.eval(`listPatch(${L}, {name: 'Projekt Beta'}).then(() => 1)`);
  await w.eval(`sectionCreate(${L}, 'Abschnitt Eins').then(() => 1)`);
  const srv = (await call(CA, 'GET', '/api/undo')).items || [];
  const GS = srv.find(g => g.kind === 'section_life'), GL = srv.find(g => g.kind === 'listset');
  check(GS && GL && /Projekt Alpha/.test(GL.label) && /Abschnitt Eins/.test(GS.label), `the server has both steps ${JSON.stringify(srv.slice(0, 3).map(g => [g.kind, g.label]))}`);
  open();
  check(await until(() => row(GL.id) && row(GS.id)), 'the window shows both as rows of the server');
  check(/Settings of Projekt Alpha/.test(row(GL.id).textContent) && /This device/.test(row(GL.id).textContent), `the rename's row: label, "This device" (${row(GL.id)?.textContent})`);
  check(![...d.querySelectorAll('#pop .ulbody .ulrow.ul-l')].some(r => /Projekt Alpha|Abschnitt Eins/.test(r.textContent)), 'no row "only this device" for them');

  // ---- the second device takes the rename back; this browser follows
  const CA2 = await login('alice');
  const other = (await call(CA2, 'GET', '/api/undo', null, {'X-Kalmido-Device-Name': 'Phone (Test)'})).items || [];
  check(other.some(g => g.id === GL.id), 'the second device lists the same step');
  // the newest first: the section goes too (Back up to here), so the second device takes back only the rename's group by
  // redoing the section afterwards
  const res = await call(CA2, 'POST', `/api/undo/to/${GL.id}`, {});
  await call(CA2, 'POST', `/api/undo/${GS.id}/redo`, {});
  check(res.http === 200 && (res.undone || []).includes(GL.id), `taken back on the second device (${res.http} ${JSON.stringify(res.undone)})`);
  check(await until(() => name() === 'Projekt Alpha'), `this browser shows the old name after the poll (${name()})`);
  check(await until(() => row(GL.id)?.classList.contains('ulundone')), 'the open window marks the rename undone');

  // ---- "Back up to here" on the section in this browser
  const secs = () => w.eval(`S.sections.filter(s => s.list_id === ${L}).map(s => s.name).join()`);
  check(await until(() => /Abschnitt Eins/.test(secs()) && row(GS.id) && !row(GS.id).querySelector('[data-ul-go]').disabled), `the section is there (${secs()})`);
  row(GS.id).querySelector('[data-ul-go]').click();
  check(await until(() => !/Abschnitt Eins/.test(secs()) && !w.eval('UL.busy')), `Back up to here: the section is gone (${secs()})`);
  check(await until(() => row(GS.id)?.classList.contains('ulundone') && row(GS.id).querySelector('[data-ul-redo]')), 'its row says undone and offers Redo');
  row(GS.id).querySelector('[data-ul-redo]').click();
  check(await until(() => /Abschnitt Eins/.test(secs())), `Redo: the section is back (${secs()})`);
  w.close();

  // ---- a person without an organisation (freelancer parity)
  await call(CA, 'POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com', orgs: []});
  const CF = await login('fiona');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', features: FEAT, tour: 'done', workspace: 'private'});
  const f = await person(CF, 'fiona', 'Frei');
  await f.w.eval(`listPatch(${f.L}, {name: 'Projekt Fiona'}).then(() => 1)`);
  const fg = ((await call(CF, 'GET', '/api/undo')).items || [])[0] || {};
  f.open();
  check(await until(() => f.row(fg.id)) && fg.kind === 'listset', `fiona: her rename is a row of the server (${fg.kind})`);
  f.row(fg.id).querySelector('[data-ul-go]').click();
  check(await until(() => f.w.eval(`listById(${f.L})?.name`) === 'Projekt Frei'), 'fiona: Back up to here gives the project its old name');
  f.w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2809_a_undo_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
