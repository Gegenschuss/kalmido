// 2.979.0 UI test, part C (#5667): an undo / redo the server takes back by its group (undo.js histDo, #5255) no longer runs the
// kalmido-suite: fresh
// entry's own undo function; the areas with their own store register how they fetch again (core.js histReloader). Files,
// freelancer-matrix: undo (fiona without an organisation: a new sheet of her table goes with one undo, the first sheet shows)
// knowledge and tables:
//  - the file store (ablage.js 'ablage'): a folder renamed, another page, undo: the file store not shown is marked old and shows
//    the old name when it opens again; the next rename works (no stale node)
//  - a knowledge folder (wiki.js 'wiki' + its post): renamed while it is open, undo: the open folder shows its old name and its
//    page again, redo the new one, renaming once more works
//  - the document view of a file (docs.js 'docs'): v1 restored on its tab History, undo: the server points the file at v2
//    again (files/fsundo.py: no new version), the tab marks v2 as the current one; redo v3
//  - a table's sheets (sheetbook.js post): a new sheet, undo: the bar shows one sheet and the first sheet is open again, redo
//    opens the new one again; fiona (no organisation) the same
// jsdom, fresh container. Invented names only. The waits are on states (rows, titles, tabs), never on a fixed time.
const {boot, errs, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const until = (fn, ms) => until0(fn, {timeout: ms || 20000, step: 100});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const FEAT = 'collab,files,docs,wiki,sheets';

async function sheetCase(ck, user) {
  const sh = await call(ck, 'POST', '/api/sheets', {title: `Plan ${user}`, space: 'private'});
  check(sh.id > 0, `${user}: a table (${sh.http})`);
  const w = await boot({user, hash: 'sheets/' + sh.id}), d = w.document;
  const tabs = () => d.querySelectorAll('#view .shbtab');
  const on = () => d.querySelector('#view .shbtab.on')?.textContent.trim();
  check(await until(() => d.querySelector('#view .shvgrid') && tabs().length === 1), `${user}: the table with one sheet`);
  const n0 = w.eval('HIST.undo.length');
  d.querySelector('#view [data-shb="add"]')?.click();
  check(await until(() => tabs().length === 2 && w.location.hash !== '#sheets/' + sh.id && w.eval('HIST.undo.length') > n0), `${user}: a second sheet, open, one step ${w.location.hash}`);
  check(await until(() => w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length') > 0), `${user}: the step is a group of the server`);
  const t2 = w.location.hash.slice('#sheets/'.length);
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(() => w.location.hash === '#sheets/' + sh.id && tabs().length === 1 && on() === 'Sheet 1'), `${user}: undo (server group): one sheet, the first one open again ${w.location.hash} ${on()}`);
  await w.eval(`histStep('redo').then(() => 1)`);
  check(await until(() => w.location.hash === '#sheets/' + t2 && tabs().length === 2), `${user}: redo: the new sheet is back and open ${w.location.hash}`);
  w.close();
}

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: []});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', features: FEAT, tour: 'done'});

  // ---- the file store: renamed, another page, undo -> marked old, the old name when it opens again
  const fo = await call(CA, 'POST', '/api/files/folders', {name: 'Kiwi box', space: 'private'});
  check(fo.id > 0, `a folder (${fo.http})`);
  let w = await boot({user: 'alice', hash: 'ablage'}), d = w.document;
  const row = id => d.querySelector(`#view .abrow[data-abid="${id}"]`);
  check(await until(() => /Kiwi box/.test(row(fo.id)?.textContent || '')), 'the file store shows the folder');
  w.prompt = () => 'Mango box';
  await w.eval(`ab_rename(AB.data.items.find(x => x.id === ${fo.id})).then(() => 1)`);
  check(await until(() => /Mango box/.test(row(fo.id)?.textContent || '')), 'renamed: the row says Mango box');
  check(await until(() => w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length') > 0), 'file store: the rename is a group of the server');
  w.location.hash = 'home';
  check(await until(() => !d.querySelector('#view .abview')), 'another page');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(async () => (await call(CA, 'GET', `/api/files/nodes/${fo.id}`)).name === 'Kiwi box'), 'undo: the server has the old name');
  check(w.eval('AB.key') === '', 'the file store not shown is marked old');
  w.location.hash = 'ablage';
  check(await until(() => /Kiwi box/.test(row(fo.id)?.textContent || '')), 'back in the file store: the old name shows');
  w.prompt = () => 'Pear box';
  await w.eval(`ab_rename(AB.data.items.find(x => x.id === ${fo.id})).then(() => 1)`);
  check(await until(async () => (await call(CA, 'GET', `/api/files/nodes/${fo.id}`)).name === 'Pear box') && await until(() => /Pear box/.test(row(fo.id)?.textContent || '')), 'the next rename works');
  w.close();

  // ---- a knowledge folder (its node in the file store: a group of the server): renamed while open, undo / redo, once more
  const kfr = await call(CA, 'POST', '/api/wiki/folders', {space: 'private', name: 'Herd'}), kf = {http: kfr.http, ...(kfr.folder || {})};
  const pg = await call(CA, 'POST', '/api/wiki/pages', {space: 'private', path: 'Herd/Zebra notes', body: 'Text of the zebra'});
  check(kf.id > 0 && pg.id > 0, `a knowledge folder with a page (${kf.http} ${pg.http})`);
  w = await boot({user: 'alice', hash: 'wiki/d/Herd'}); d = w.document;
  const head = () => d.querySelector('#view .wktitle h2')?.textContent || '';
  const fold = () => w.eval(`wk_nodeInfo(${kf.id})?.folder`);
  check(await until(() => head() === 'Herd' && /Zebra notes/.test(d.querySelector('#view')?.textContent || '') && fold()), 'the folder is open with its page ' + head());
  w.prompt = () => 'Okapi';
  await w.eval(`wk_fRename('private', wk_nodeInfo(${kf.id}).folder).then(() => 1)`);
  check(await until(() => head() === 'Okapi' && /Okapi/.test(decodeURIComponent(w.location.hash))), `renamed: the open folder follows (${head()} ${w.location.hash})`);
  check(await until(() => w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length') > 0), 'knowledge: the rename is a group of the server');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(async () => (await call(CA, 'GET', `/api/files/nodes/${kf.id}`)).name === 'Herd'), 'undo: the server has the old name');
  check(await until(() => head() === 'Herd' && /Zebra notes/.test(d.querySelector('#view')?.textContent || '')), `undo: the open folder shows its old name with its page (${head()} ${w.location.hash})`);
  await w.eval(`histStep('redo').then(() => 1)`);
  check(await until(() => head() === 'Okapi'), 'redo: the new name again ' + head());
  w.prompt = () => 'Gnu';
  await w.eval(`wk_fRename('private', wk_nodeInfo(${kf.id}).folder).then(() => 1)`);
  check(await until(async () => (await call(CA, 'GET', `/api/files/nodes/${kf.id}`)).name === 'Gnu') && await until(() => head() === 'Gnu'), 'renaming once more works ' + head());
  w.close();

  // ---- the document view of a file: restore v1 on the tab History, undo / redo, the tab follows
  const up = async (name, text, parent) => {
    const fd = new FormData(); fd.append('file', new Blob([text], {type: 'text/plain'}), name); fd.append('parent_id', String(parent));
    const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CA}, body: fd});
    return ((await r.json()).items || [])[0];
  };
  await up('memo.txt', 'first', fo.id);
  const NID = (await up('memo.txt', 'second!', fo.id))?.id;
  const ver = async () => (await call(CA, 'GET', `/api/files/nodes/${NID}`)).version;
  check(NID && await ver() === 2, 'a text file with two versions');
  w = await boot({user: 'alice', hash: `ablage/${fo.id}`}); d = w.document;
  check(await until(() => row(NID) && w.eval('typeof ab_detailsOf === "function"')), 'the folder lists the file');
  w.eval(`ab_detailsOf(ab_item(${NID}))`);
  const hist = () => d.querySelector('.dv-view #dv-p-hist');
  const vrow = no => hist()?.querySelector(`.abvrow[data-abvno="${no}"]`);
  const cur = () => [...(hist()?.querySelectorAll('.abvrow') || [])].find(r => /current/.test(r.textContent))?.dataset.abvno;
  check(await until(() => hist() && !hist().hidden && vrow(1)?.querySelector('[data-abv="1"]')), 'the document view on its tab History, v1 restorable');
  vrow(1).querySelector('[data-abv="1"]').dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
  check(await until(async () => await ver() === 3) && await until(() => cur() === '3'), 'restore v1: v3, the tab marks it current');
  check(await until(() => w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length') > 0), 'document: the restore is a group of the server');
  await w.eval(`histStep('undo').then(() => 1)`);
  check(await until(async () => await ver() === 2), 'undo: the server points the file at v2 again');
  check(await until(() => cur() === '2'), `undo: the tab marks v2 as the current one (${cur()})`);
  await w.eval(`histStep('redo').then(() => 1)`);
  check(await until(async () => await ver() === 3) && await until(() => cur() === '3'), `redo: v3 again, the tab follows (${cur()})`);
  w.close();

  // ---- a table's sheets: alice, then fiona without an organisation
  await sheetCase(CA, 'alice');
  await call(CA, 'POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123', email: 'fiona@example.com', orgs: []});
  const CF = await login('fiona');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', features: FEAT, tour: 'done', workspace: 'private'});
  await sheetCase(CF, 'fiona');

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2979_c_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(err => { console.error(err); process.exit(1); });
