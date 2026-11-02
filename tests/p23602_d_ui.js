// kalmido-suite: fresh
// 2.360.2 D (#2561) UI test (jsdom), fresh DB: settings > Move and export everything lists an approval record of a deleted
// video and deletes it; the row of a deleted person's month has no buttons to decide.
// freelancer-matrix: own (the account here has no organisation)
const {execFileSync} = require('child_process');
const {boot, errs, until, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || process.env.KALMIDO_TEST_DATA;
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [__dirname + '/dbx.py', DATA, q, JSON.stringify(a)]).toString());

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CK}, body: JSON.stringify({lang: 'en', tour: 'done', features: 'time,collab'})});
  const r0 = sql("SELECT id FROM users WHERE username='alice'")[0], me = r0.id ?? r0[0];
  sql(`INSERT INTO office_signoffs(org_id,kind,title,token_hash,token,state,created_by,created_at) VALUES(NULL,'video','Gone cut','h1','t1','open',?,'2026-10-01T10:00:00+00:00') RETURNING id`, [me]);
  const w = await boot({});
  await w.eval('ld_all()');
  const md = w.document.createElement('div');
  md.innerHTML = '<div id="s-umz-sig"></div>';
  w.document.body.append(md);
  w.__md = md;
  await w.eval('umzSigLoad(window.__md)');
  check(md.textContent.includes('Gone cut'), 'the record is listed');
  const b = md.querySelector('[data-umz="sigdel"]');
  check(b, 'it has a delete button');
  await w.eval(`api('DELETE', '/api/videos/signoffs/orphaned/${b.dataset.id}').then(() => umzSigLoad(window.__md))`);
  check(await until(() => md.querySelector('#s-umz-sig').innerHTML === ''), 'gone from the list, the section with it');
  check(!sql("SELECT id FROM office_signoffs WHERE kind='video'").length, 'gone from the server');
  // a deleted person's month: the review row without buttons (timesheet.js)
  const h = w.eval(`TSL.data = {month: 'other', review: [
    {user_id: null, name: 'Deleted person', month: '2026-05', state: 'closed', seconds: 3600}, {user_id: ${me}, name: 'Alice', month: '2026-05', state: 'closed', seconds: 60}]}; tsl_card()`);
  const box = w.document.createElement('div'); box.innerHTML = h;
  const rows = [...box.querySelectorAll('.tslrev .tslrow')];
  check(rows.length === 2 && !rows[0].querySelector('[data-tsl]') && rows[1].querySelector('[data-tsl="approve"]'), 'no decision on a deleted person\'s month, the other row keeps them');
  check(!errs.length, 'no client errors ' + errs.slice(0, 3));
  w.close();
  console.log(`p23602_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
