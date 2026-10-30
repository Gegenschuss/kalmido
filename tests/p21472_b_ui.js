// 2.147.2 B (#2501) UI tests: role picker size, role help inline, storage "Region" key, trash dialog wrapping. P21472B_NOSTART=1 = server runs.
// P21472B_NOSTART=1 = the server already runs.
const {execFileSync} = require('child_process');
const path = require('path');
const fs = require('fs');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21472B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('org')`);
  const help = await until(() => d.querySelector('#s-ws .orgrolehelp'));
  const ul = help && help.querySelector('ul');
  check(ul && ul.classList.contains('keep'), 'role help list is marked keep');
  check(help && help.querySelectorAll('li').length === 5, 'role help shows 5 li');
  await sleep(300);
  check(help && !help.querySelector('.iisrc') && !help.querySelector('.iibtn,[data-ii="1"] + button'), 'role help: no iisrc, no (i) button');
  check(w.eval(`tr('Region|storage')`) === 'Region', 'storage region label falls back to "Region"');
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(/select\.orgrolesel[^{]*\{[^}]*min-height:\s*2\.75rem/.test(css), 'role select CSS: min-height 2.75rem');
  check(/select\.orgrolesel[^{]*\{[^}]*min-width:\s*8\.5rem/.test(css), 'role select CSS: min-width for the longest role name');
  const tr = (css.match(/\.wktrow \.n\{[^}]*\}/) || [''])[0];
  check(/white-space:\s*normal/.test(tr) && /overflow-wrap:\s*anywhere/.test(tr) && !/text-overflow:\s*ellipsis/.test(tr), 'trash row name wraps, no ellipsis');
  w.close();
  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
