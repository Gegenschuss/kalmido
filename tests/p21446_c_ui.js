// 2.144.6 C (#2436): the personal office's Settings > Data has ONE section "Transfer into an organisation" (both ways)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21446C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  const w = await boot({hash: 'office/settings'}); const d = w.document;
  await until(() => d.querySelector('#os-small'), 60);
  // personal office as admin: exactly one "Transfer" heading, the new-organisation button inside it
  const hs = [...d.querySelectorAll('.office h3')].filter(h => /^Transfer into an organisation$/.test(h.textContent.trim()));
  check(hs.length === 1, 'exactly one transfer heading: ' + hs.length);
  check(![...d.querySelectorAll('.office h3')].some(h => /^Move into/.test(h.textContent.trim())), 'no "Move into" heading any more');
  check(d.querySelectorAll('[data-ofc="pb-move"]').length === 1, 'the new-organisation button is there once');
  const sec = d.querySelector('[data-ofc="pb-move"]')?.closest('fieldset');
  check(!!sec && sec === hs[0]?.closest('fieldset'), 'the button sits in the same section as the heading');
  // no organisation yet: the existing-organisation way is not offered
  check(!d.querySelector('[data-ofc="pb-transfer"]'), 'no existing organisation: no second button');
  w.close();
  console.log(F.length ? 'FAILED ' + F.length : 'ok ' + ok); process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
