// 2.513.0 A UI test (#4356): Administration > Server says when the page is open on another address than PUBLIC_URL (start.sh sets
// https://kalmido.example, the suite opens the proxy port). Own container, jsdom, invented data only. Instance admin, the hint is admin-only.
// kalmido-suite: fresh
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const DATA = process.argv[2] || path.join(__dirname, '.data');

(async () => {
  if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  let w = await boot({user: 'alice'}), d = w.document;
  await w.eval(`settingsModal('users')`);
  await require('./boot').until(() => d.querySelector('.smodal [data-admp="server"]'), {timeout: 15000, step: 50});
  const box = d.querySelector('.smodal [data-admp="server"] .shaddr');
  check(!!box, 'the hint shows on another address');
  const txt = box ? box.textContent : '';
  check(txt.includes('https://kalmido.example') && txt.includes(w.location.origin), `it names both addresses: ${txt}`);
  check(/PUBLIC_URL/.test(txt) && /\.env/.test(txt), 'it says what to change');

  const warn = a => w.eval(`shAddrWarn(${JSON.stringify(a)})`);
  const here = w.location.origin;
  check(warn({public_url: here}) === '', 'no hint on PUBLIC_URL itself');
  check(warn({public_url: here + '/'}) === '', 'a trailing slash changes nothing');
  check(warn({public_url: here.replace('127.0.0.1', 'localhost')}) === '', 'localhost and 127.0.0.1 are the same computer');
  check(warn({public_url: 'https://kalmido.example', public_url_also: [here]}) === '', 'a second allowed origin (KALMIDO_WEBAUTHN_ORIGINS) gets no hint');
  check(warn({public_url: here.replace(/:\d+$/, ':1')}) !== '', 'another port is another address');
  check(warn({}) === '', 'no address known (not an admin): no hint');
  w.__KALMIDO_SHELL__ = {kind: 'desktop'};
  check(warn({public_url: 'https://kalmido.example'}) === '', 'the app shells have an address of their own: no hint');
  delete w.__KALMIDO_SHELL__;

  w.close();
  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2513_a_addr_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
