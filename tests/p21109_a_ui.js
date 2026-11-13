// 2.1109.0 A (#5959, #5963): UI checks of Part A. Own container
// kalmido-suite: fresh
// (start.sh), Firefox. Invented data only.
// - #5959: the booking archive / procedure documentation / all receipts show their page also under an address with the
//   workspace (#office/s/<ws>/books/<sub>): the CONTENT of the sub page is in sight, same as without the workspace.
// freelancer-matrix: office (frida has no organisation)
// usage: node p21109_a_ui.js <datadir>
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21109_a', check, shots: 'P21109A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Beispiel Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  check((await call('POST', '/api/users', {username: 'frida', display_name: 'frida', password: 'password123', email: 'frida@example.com', orgs: []})).http < 300, 'user frida');
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, FK);
  await call('PUT', '/api/office/settings', {pack: 'DE', company_fields: {name: 'Studio Beispiel', street: 'Hafenstrasse 12', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890'}}, FK);
  const signIn = (ev, user) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);

  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev, 'frida') === 200, 'frida signed in');
    // #5959: both address forms show the same sub page (heading in sight)
    const subs = [['archive', 'Booking archive', '.bka-h'], ['procdoc', 'Procedure documentation', '.pd-h'], ['receipts', 'All receipts', '#rcl-h']];
    for (const [sub, head, sel] of subs) {
      for (const ws of ['', 's/private/']) {
        await nav(B + `#office/${ws}books/${sub}`);
        const seen = await until(`(() => { const h = document.querySelector('#view ' + ${JSON.stringify(sel)}); return !!h && h.textContent.includes(${JSON.stringify(head)}) && h.getBoundingClientRect().height > 0; })()`, {timeout: 20000});
        check(seen, `#5959 ${sub} via #office/${ws}books/${sub}: "${head}" in sight ` + await ev(`(document.querySelector('#view')?.textContent || '').slice(0, 120)`));
      }
    }
    await shot('p21109a-archive-ws.png');
  });
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
