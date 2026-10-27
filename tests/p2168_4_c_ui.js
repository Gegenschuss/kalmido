// 2.210 C (#2761) UI test (own container, start.sh; P21684C_NOSTART=1: the container runs already). jsdom, a person WITHOUT an
// organisation (freelancer-matrix: docs): the sheet of an own document has "Share…" and "Link for external people…" (the file store's
// dialogs), a recipient (view role) sees neither, the card shows the "shared" mark once a share exists.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21684C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const prep = async u => { CK = await login(u); const st = await call('GET', '/api/state'); await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files', 'docs'])].filter(Boolean).join(',')}); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const bob = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: []})).id;
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  await prep('bob'); const bobCK = CK;
  await prep('frida');
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob(['Vertrag Beispiel Nummer 12']), 'vertrag.txt');
  const DOC = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${DOC}`)).state), 300);
  check((await call('GET', `/api/docs/${DOC}`)).shared === false, 'not shared yet: shared=false');

  let w = await boot({user: 'frida', hash: 'docs'}), d = w.document;
  await until(() => d.querySelector(`[data-dco="${DOC}"]`), 60);
  check(!d.querySelector('.dc-shared'), 'no mark on the card before sharing');
  w.eval(`dc_open(${DOC})`);
  await until(() => d.querySelector('.dc-md [data-dc="view"]'));
  check(d.querySelector('.dc-md [data-dc="share"]'), 'owner: "Share…" in the sheet');
  check(d.querySelector('.dc-md [data-dc="xlink"]'), 'owner: "Link for external people…" in the sheet');
  d.querySelector('.dc-md [data-dc="share"]').click();
  check(await until(() => d.querySelector('.abshdlg')), 'click opens the file store share dialog');
  const r = await call('POST', `/api/files/nodes/${DOC}/shares`, {user_id: bob, role: 'view'});
  check(r.status < 300, 'share with bob: ' + r.status);
  d.querySelector('.abshdlg [data-m="close"]').click();
  check(await until(() => d.querySelector('.dc-card .dc-shared')), 'card shows the shared mark after the dialog closed');

  // the recipient: no buttons
  CK = bobCK;
  w = await boot({user: 'bob', hash: 'docs'}); d = w.document;
  await until(() => d.querySelector(`[data-dco="${DOC}"]`), 60);
  w.eval(`dc_open(${DOC})`);
  await until(() => d.querySelector('.dc-md [data-dc="view"]'));
  check(!d.querySelector('.dc-md [data-dc="share"]') && !d.querySelector('.dc-md [data-dc="xlink"]'), 'recipient: neither Share nor external link');
  console.log(F.length ? 'FAILED ' + F.length : 'OK ' + ok); process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
