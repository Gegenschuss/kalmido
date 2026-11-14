// 2.1168.0 B (#6091 #6092) UI test, jsdom, own container (start.sh), invented texts only. Used like a person would:
// kalmido-suite: fresh
// - the page's "…" says "Move to the trash" (no "Delete"), nothing asks; the toast names the page with Undo, the page is in the
//   trash, Undo brings it back and it opens again
// - the history: the current version is no button (it opened "No differences"), an older one opens with the plain hint
// - the conflict window marks the lines only each version has (the history's diff rows), Yours and Theirs side by side
// - an info window (the import's report) is the shared dialog with its OK alone
// - the device lock reads "Lock editing (this device)", "Copy as [[link]]" says "Reference copied"
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21168B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const sql = (q, args = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(args)]).toString() || '[]');
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const st0 = await call('GET', '/api/state');
  const feats = (st0.settings.features || '').split(',').filter(Boolean);
  await call('PATCH', '/api/settings', {features: [...feats, 'wiki'].join(',')});
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Garden/Watering plan', body: 'Water the roses'})).id;
  await call('PATCH', '/api/wiki/pages/' + PG, {body: 'Water the roses\nCut the hedge'});
  sql("UPDATE obj_versions SET created_at=? WHERE kind='wiki' AND ref_id=?", ['2026-01-01T08:00:00.000+00:00', PG]);  // older than ten minutes: its own version
  await call('PATCH', '/api/wiki/pages/' + PG, {body: 'Water the roses\nCut the hedge\nFeed the fish'});
  check(((await call('GET', `/api/wiki/pages/${PG}/versions`)).versions || []).length === 2, 'setup: two versions');
  const listed = async () => ((await call('GET', '/api/wiki?space=private')).pages || []).some(p => p.id === PG);

  const w = await boot({user: 'alice', hash: 'wiki/' + PG, ls: {'tasks.wkSpace': JSON.stringify('private')}}), d = w.document;
  const items = () => [...d.querySelectorAll('#pop [role="menuitem"], #pop button')];
  const pmenu = async () => {
    const b = await until(() => d.querySelector('.wkpage [data-wk="pmenu"]'));
    b?.click();
    return until(() => items().length && items());
  };
  const toastT = () => d.querySelector('#toast')?.textContent || '';

  // ================= the page into the trash: the menu's word, no question, the toast with Undo, the page back
  await until(() => w.eval(`!!(WK.pg && WK.pg.id === ${PG})`), 60);
  let it = await pmenu();
  const labels = (it || []).map(x => x.textContent.trim());
  check(labels.some(t => /Move to the trash/.test(t)) && !labels.some(t => /^Delete$/.test(t)), 'the page\'s "…" says "Move to the trash", no "Delete" ' + JSON.stringify(labels));
  check(/Move to the trash/.test(labels[labels.length - 1] || ''), 'it stays the last entry');
  check(labels.some(t => t === 'Lock editing (this device)'), '#6091: the device lock reads "Lock editing (this device)" ' + JSON.stringify(labels));
  w.__dialogs = 'manual';  // a question would stay open now (the bridge would answer it): there must be none
  (it || []).find(x => /Move to the trash/.test(x.textContent))?.click();
  check(await until(() => /“Watering plan” moved to the trash/.test(toastT()) && d.querySelector('#toast button')), 'the toast names the page with Undo: ' + toastT());
  check(!d.querySelector('.modal.cdlg'), 'nothing asked before');
  check(await until(async () => !(await listed())), 'the page left the list (it lies in the trash)');
  check((sql('SELECT deleted_at FROM wiki_pages WHERE id=?', [PG])[0] || {}).deleted_at, 'the page carries its trash mark');
  d.querySelector('#toast button')?.click();
  check(await until(async () => await listed()), 'Undo: the page is back in the list');
  w.location.hash = '#wiki/' + PG;
  check(await until(() => w.eval(`!!(WK.pg && WK.pg.id === ${PG} && /Feed the fish/.test(WK.pg.body || ''))`) && d.querySelector('#view .wkpage')), 'and it opens again with its text');

  // ================= the history: the current version opens nothing, an older one with the plain hint
  it = await pmenu();
  (it || []).find(x => /History/.test(x.textContent))?.click();
  const rows = await until(() => d.querySelectorAll('.wkhdlg .wkhitem').length === 2 && [...d.querySelectorAll('.wkhdlg .wkhitem')]);
  check(rows && rows[0].tagName === 'DIV' && /current/.test(rows[0].textContent) && !rows[0].matches('[data-wkh]'), 'the current version is no button ' + rows?.[0]?.outerHTML.slice(0, 160));
  check(rows && rows[1].tagName === 'BUTTON' && rows[1].dataset.wkh === 'open', 'the older one is a button');
  rows?.[0].click(); await sleep(300);
  check(!d.querySelector('.wkhdlg .wkhdiff') && !/No differences/.test(d.querySelector('.wkhdlg')?.textContent || ''), 'a click on the current one opens nothing');
  rows?.[1].click();
  const diff = await until(() => d.querySelector('.wkhdlg .wkhdiff'));
  check(diff && [...diff.querySelectorAll('.wkhd.del')].some(x => /Feed the fish/.test(x.textContent)), 'the older one opens with its comparison');
  check(/Green comes back with Restore, red goes\./.test(d.querySelector('.wkhdlg')?.textContent || ''), 'with the plain hint');
  d.querySelector('.wkhdlg [data-wkh="close"]')?.click();
  await until(() => !d.querySelector('.wkhdlg'));

  // ================= the conflict window: the lines only each version has are marked (the history's rows)
  const cf = w.eval(`(window.__cf = wk_conflict(WK.pg, {...WK.pg, body: 'Water the roses\\nCut the hedge\\nFeed the cat', updated_by_name: 'Bob'}, {body: 'Water the roses\\nCut the hedge\\nFeed the fish'}), 1)`);
  const md = await until(() => cf && d.querySelector('.modal.cdlg .wkcf'));
  const cols = md ? [...md.children] : [];
  const marked = c => [...(c?.querySelectorAll('.wkhd.add') || [])].map(x => x.textContent);
  check(cols.length === 2 && /Yours/.test(cols[0].querySelector('b')?.textContent || '') && /Theirs/.test(cols[1].querySelector('b')?.textContent || ''), 'both versions side by side, Yours first');
  check(marked(cols[0]).some(t => /Feed the fish/.test(t)) && !marked(cols[0]).some(t => /Feed the cat|Water the roses/.test(t)), 'Yours: only its own line marked ' + JSON.stringify(marked(cols[0])));
  check(marked(cols[1]).some(t => /Feed the cat/.test(t)) && !marked(cols[1]).some(t => /Feed the fish|Water the roses/.test(t)), 'Theirs: only its own line marked ' + JSON.stringify(marked(cols[1])));
  check(cols.every(c => /Cut the hedge/.test(c.textContent)), 'the shared lines around stay for orientation');
  check(!md?.closest('.modal')?.querySelector('pre'), 'no raw texts any more');
  check(/Take theirs/.test(d.querySelector('.modal.cdlg [data-cd="no"]')?.textContent || ''), 'the button to take the other version');
  // Keep mine saves (the page is unchanged on the server: the save goes through)
  d.querySelector('.modal.cdlg [data-cd="yes"]')?.click();
  check(await until(async () => /Feed the fish/.test((await call('GET', '/api/wiki/pages/' + PG)).body || '') && !d.querySelector('.modal.cdlg')), 'Keep mine closes the window, the page keeps the text');

  // ================= an info window: the shared dialog with OK alone
  w.eval(`wka_report({created: [1], files_n: 0, skipped: ['tool.exe'], skipped_detail: [{name: 'tool.exe', reason: 'not a page'}], skipped_n: 1})`);
  const info = await until(() => d.querySelector('.modal.cdlg'));
  check(info && /Import finished/.test(info.querySelector('#cdlg-t')?.textContent || '') && /1 skipped/.test(info.textContent), 'the import report is the shared dialog, titled Import finished');
  check(info && info.querySelector('[data-cd="no"]')?.hidden && !info.querySelector('[data-cd="yes"]')?.hidden, 'with OK alone (no Cancel)');
  info?.querySelector('[data-cd="yes"]')?.click();
  check(await until(() => !d.querySelector('.modal.cdlg')), 'OK closes it');

  // ================= Copy as [[link]]: the toast says what was copied
  w.eval(`navigator.clipboard ? Object.defineProperty(navigator.clipboard, 'writeText', {value: () => Promise.resolve(), configurable: true}) : Object.defineProperty(navigator, 'clipboard', {value: {writeText: () => Promise.resolve()}, configurable: true})`);
  it = await pmenu();
  (it || []).find(x => /Copy as \[\[link\]\]/.test(x.textContent))?.click();
  check(await until(() => /Reference copied/.test(toastT())), '#6091: "Copy as [[link]]" says "Reference copied": ' + toastT());

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
