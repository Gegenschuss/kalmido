// 2.138.2 B (#2395) UI test: the company name field in the office settings grows with its text (up to 3 rows, no inner scrollbar).
// freelancer-matrix: office - nur Oberfläche, das Feld ist für Organisation und Person ohne Organisation dasselbe
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,clients,office'});
  const w = await boot({hash: 'inbox'}), d = w.document;
  await until(() => d.querySelector('#side'), 60);
  w.eval(`go('office/settings')`);
  const ta = await until(() => d.querySelector('#os-name'), 60);
  check(!!ta && ta.tagName === 'TEXTAREA', 'the company name field exists');
  if (ta) {
    check(ta.rows === 1, 'empty name: one row ' + ta.rows);
    const type = v => { ta.value = v; ta.dispatchEvent(new w.Event('input', {bubbles: true})); };
    type('FIRMA\n'); check(ta.rows === 2, 'Enter + text: two rows ' + ta.rows);
    type('FIRMA\nName & Name GbR\nDritte'); check(ta.rows === 3, 'three lines: three rows ' + ta.rows);
    type('A\nB\nC\nD'); check(ta.rows === 3, 'never more than three rows ' + ta.rows);
    type('A'); check(ta.rows === 1, 'back to one row ' + ta.rows);
    check(/hidden/.test(ta.style.overflow), 'no inner scrollbar (overflow hidden)');
  }
  w.close();
  console.log(`p21381_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
