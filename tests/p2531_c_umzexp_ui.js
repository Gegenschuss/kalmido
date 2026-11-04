// 2.531.0 part C (#4317, audit #2425 F9 F10): Settings > Data > "Move and export everything" names what is not in the file,
// kalmido-suite: fresh
// readable, before and after the export: a closed list "What is not in the file (n)" with the trashes and the areas not yet in
// the export by name, never a table name. A person without an organisation (freelancer-matrix: own). Own container (start.sh),
// jsdom. Invented names only.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 200 : 15000, step: 200});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
async function dataPane(w) {
  w.eval('settingsModal()');
  const nav = await until(() => w.document.querySelector('.smodal .snav [data-sec="data"]'));
  click(w, nav);
  return until(() => w.document.querySelector('.smodal #s-umz-exp') && w.document.querySelector('.smodal'));
}
const lines = md => [...md.querySelectorAll('#s-umz-exp .umzleft .umzleftl li')].map(x => x.textContent);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Frei', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.id, 'a person without an organisation');
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments'});
  check(!((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length, 'frida is in no organisation');

  const w = await boot({user: 'frida'});
  const md = await dataPane(w);
  const box = await until(() => md.querySelector('#s-umz-exp [data-umz="exp"]') && md.querySelector('#s-umz-exp'));
  const det = box && box.querySelector('details.umzleft');
  check(det && !det.open, 'F9 before the export: a closed list of what is not in the file');
  const sum = det?.querySelector('summary')?.textContent || '';
  const L0 = lines(md);
  check(/^What is not in the file \(\d+\)$/.test(sum) && sum.includes(`(${L0.length})`), `F9 its summary counts the lines: ${sum} ${L0.length}`);
  check(L0.some(x => x.startsWith('the trash of your files, knowledge pages, tables, address books')), `F10 the trashes are named: ${L0.slice(-6).join(' | ')}`);
  check(L0.some(x => x.startsWith('not yet in the file: ') && x.includes('history of knowledge pages')), 'F9 the areas not yet in the export by name');
  check(!L0.some(x => /wiki_versions|kid_rewards|conn_requests/.test(x)), 'F9 no table name');

  click(w, md.querySelector('#s-umz-exp [data-umz="exp"]'));
  const dl = await until(() => md.querySelector('#s-umz-exp a[href="/api/account/export/file"]'), 150);
  check(dl, 'the export is ready');
  const L1 = lines(md);
  check(L1.length === L0.length && md.querySelector('#s-umz-exp details.umzleft'), `F9 after the export the list stays: ${L1.length}`);
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
