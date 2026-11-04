// kalmido-suite: fresh
// 2.539.0 B (#4375) UI test, own container (start.sh), jsdom, invented data only:
// - the own password change shows the tick "End all app passwords and API tokens", set by default, and says before that
//   calendar / contacts apps and scripts must be connected again
// - tick removed: the API token stays; tick set: it ends (red without the fix: no tick, the request carries no revoke_tokens)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const works = async t => (await fetch(B + 'api/v1/me', {headers: {Authorization: 'Bearer ' + t}})).ok;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const T1 = (await call('POST', '/api/me/tokens', {name: 'Script', scopes: ['read']})).token;
  check(T1 && await works(T1), 'setup: a token that works');

  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;  // the window's own session stays over both changes
  w.eval(`settingsModal()`);
  const box = await until(() => d.querySelector('#a-pwrev'));
  const lab = box?.closest('label')?.textContent || '';
  check(box && box.checked, '#4375: the tick is there and set by default');
  check(/End all app passwords and API tokens/.test(lab) && /must be connected again/.test(lab), '#4375: the tick and the note before the change');
  const change = async (cur, nw, tick) => {
    d.querySelector('#a-cur').value = cur; d.querySelector('#a-new').value = nw;
    box.checked = tick;
    click(w, d.querySelector('[data-acc="pw"]'));
    await until(() => d.querySelector('#a-new')?.value === '');  // cleared once the server said yes
  };
  await change('password123', 'password234', false);
  check(d.querySelector('#a-new').value === '' && await works(T1), '#4375: tick removed: the password changes, the token stays');
  await change('password234', 'password345', true);
  check(await until(async () => !(await works(T1))), '#4375: tick set: the token ends');
  w.close();

  console.log(F.length ? 'FAILED ' + F.length : 'OK ' + ok); process.exit(F.length ? 1 : 0);
})();
