// 2.123.0 A UI tests (#2102 page history, #2106 text search; own container, start.sh). jsdom, invented texts only:
// - the page menu "History" lists the versions (the newest marked current), a version opens with the line comparison,
//   "Restore" makes its text the page's text (the dialog closes) and ONE Undo brings the text before back
// - "Find a page": the names are filtered here, the text hits of the server follow under "Found in the text", 30 at a time,
//   "Show more" loads the rest and goes when nothing is left
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2123A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const sql = (q, args = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(args)]).toString() || '[]');
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const st0 = await call('GET', '/api/state');
  const feats = (st0.settings.features || '').split(',').filter(Boolean);
  await call('PATCH', '/api/settings', {features: [...feats, 'wiki'].join(',')});
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Docs/Plan', body: 'Line one\nLine two'})).id;
  await call('PATCH', '/api/wiki/pages/' + PG, {body: 'Line one\nLine two\nLine three'});
  sql('UPDATE wiki_versions SET created_at=? WHERE page_id=?', ['2026-01-01T08:00:00.000+00:00', PG]);  // older than 10 minutes
  await call('PATCH', '/api/wiki/pages/' + PG, {body: 'Line one\nLine 2 changed\nLine three\nLine four'});
  const vs = (await call('GET', `/api/wiki/pages/${PG}/versions`)).versions || [];
  check(vs.length === 2 && vs[0].current, 'setup: two versions, the newest current ' + JSON.stringify(vs));
  for (let i = 0; i < 35; i++) await call('POST', '/api/wiki/pages', {space: 'private', path: `Fruit/Page ${String(i).padStart(2, '0')}`, body: `About the starfruit number ${i}`});

  // ================= the history
  const w = await boot({user: 'alice', hash: 'wiki/' + PG, ls: {'tasks.wkSpace': JSON.stringify('private')}}), d = w.document;
  await until(() => d.querySelector('.wkpage [data-wk="pmenu"]'));
  d.querySelector('.wkpage [data-wk="pmenu"]').click();
  const item = await until(() => [...d.querySelectorAll('#pop [role="menuitem"], #pop button')].find(x => x.textContent.includes('History')));
  check(item, 'the page menu has "History"');
  item?.click();
  const list = await until(() => d.querySelectorAll('.wkhdlg .wkhitem').length === 2 && d.querySelectorAll('.wkhdlg .wkhitem'));
  check(list && list[0].textContent.includes('current') && !list[1].textContent.includes('current'), 'the dialog lists 2 versions, the newest current');
  list?.[1].click();
  const diff = await until(() => d.querySelector('.wkhdlg .wkhdiff'));
  check(diff && [...diff.querySelectorAll('.wkhd.add')].some(x => x.textContent.includes('Line two')) && [...diff.querySelectorAll('.wkhd.del')].some(x => x.textContent.includes('Line four')),
    'the version opens with the comparison (+ comes back, - goes) ' + (diff?.textContent || '').slice(0, 200));
  d.querySelector('.wkhdlg [data-wkh="restore"]')?.click();
  check(await until(() => !d.querySelector('.wkhdlg')), 'Restore closes the dialog');
  const after = await until(async () => { const p = await call('GET', '/api/wiki/pages/' + PG); return p.body === 'Line one\nLine two\nLine three' && p; });
  check(after, 'the page has the restored text');
  check(await until(() => w.WK?.pg?.body === 'Line one\nLine two\nLine three'), 'the open page shows it');
  check(((await call('GET', `/api/wiki/pages/${PG}/versions`)).versions || []).length === 3, 'the restore is a new version');
  w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', '/api/wiki/pages/' + PG)).body === 'Line one\nLine 2 changed\nLine three\nLine four'), 'ONE Undo brings the text before back');

  // ================= the text search with "Show more"
  w.location.hash = '#wiki'; await sleep(400);
  const q = await until(() => d.querySelector('#wk-q'));
  q.value = 'starfruit'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  const n1 = await until(() => { const x = d.querySelectorAll('#wks .wkitem').length; return x === 30 && x; });
  check(n1 === 30 && d.querySelector('#wks').textContent.includes('Found in the text'), 'the text hits: 30 under "Found in the text" ' + d.querySelectorAll('#wks .wkitem').length);
  check(!d.querySelector('#wk-res > .empty'), '"No page matches." goes when the text has hits');
  const more = d.querySelector('#wks [data-wks="more"]');
  check(more && more.textContent.includes('Show more'), '"Show more" is there');
  more?.click();
  check(await until(() => d.querySelectorAll('#wks .wkitem').length === 35), 'Show more loads the other 5 ' + d.querySelectorAll('#wks .wkitem').length);
  check(!d.querySelector('#wks [data-wks="more"]'), 'no "Show more" when nothing is left');
  q.value = 'Page 0'; q.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(900);
  check(d.querySelectorAll('#wk-res > .wktree .wkitem').length === 10, 'the names are still filtered here ' + d.querySelectorAll('#wk-res > .wktree .wkitem').length);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
