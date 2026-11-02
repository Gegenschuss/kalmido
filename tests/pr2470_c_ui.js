// 2.470.0 UI tests of part C (#3596, point 4): the sharing defaults of a workspace (own container, start.sh). jsdom:
// - Settings > Data: the section opens on the current workspace; a change is saved, one undo step back
// - an organisation: its admin changes the values, a member sees them disabled
// - the dialogs start with them: "Link for external people" (validity) and "New file request" (date, MB, files, kinds)
// - the settings search finds the section by "Freigabe"
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces -e TASKS_MAX_FILE_MB=50'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json(); };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 150});
const change = (w, el, v) => { if (el.type === 'checkbox') el.checked = v; else el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const me = (await call('GET', '/api/state')).me;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id})).id;
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files'])].filter(Boolean).join(',')});
  await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'org:' + ORG}, CB);
  const OF = (await call('POST', '/api/files/folders', {name: 'Kunde Nord', space: 'org:' + ORG})).id;

  // ================= private: the section, saved, one undo step
  await call('PATCH', '/api/settings', {workspace: 'private'});
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('data')`);
  const exp = await until(() => d.querySelector('#s-xlstd-exp'));
  check(exp?.value === '7d' && d.querySelector('#s-xlstd-days')?.value === '14' && d.querySelector('#s-xlstd-mb')?.value === '25' && d.querySelector('#s-xlstd-n')?.value === '20', 'private: the built-in values');
  check(d.querySelector('#s-xlstd-ws')?.value === '', 'it opens on the current workspace');
  check(!d.querySelector('[data-xlstd="reset"]'), 'nothing stored: no way back to show');
  if (exp) change(w, exp, 'none');
  check(await until(async () => JSON.parse((await call('GET', '/api/state')).settings.share_defaults || '{}').link_expires === 'none'), 'private: saved');
  await until(() => d.querySelector('[data-xlstd="reset"]'));
  await w.eval(`histStep('undo')`);
  check(await until(async () => !Object.keys((await call('GET', '/api/share-defaults?space=private')).stored).length), 'one undo step back');

  // ================= the organisation: its admin
  const sel = await until(() => d.querySelector('#s-xlstd-ws'));
  if (sel) change(w, sel, String(ORG));
  const pick = await until(() => d.querySelector('#s-xlstd')._j?.space === 'org:' + ORG && !d.querySelector('#s-xlstd-exp').disabled && d.querySelector('#s-xlstd-exp'));
  check(pick, 'the workspace select reaches the organisation, its admin may change it');
  if (pick) change(w, pick, '30d');
  check(await until(async () => (await call('GET', `/api/share-defaults?space=org:${ORG}`)).stored.link_expires === '30d'), 'org: the validity saved');
  await until(() => d.querySelector('#s-xlstd-exp')?.value === '30d');
  change(w, d.querySelector('#s-xlstd-days'), '30');
  check(await until(async () => (await call('GET', `/api/share-defaults?space=org:${ORG}`)).stored.req_days === 30), 'org: the days saved');
  await until(() => d.querySelector('#s-xlstd-days')?.value === '30');
  change(w, d.querySelector('#s-xlstd-mb'), '10');
  check(await until(async () => (await call('GET', `/api/share-defaults?space=org:${ORG}`)).stored.req_mb === 10), 'org: the size saved');
  await until(() => d.querySelector('#s-xlstd-mb')?.value === '10');
  change(w, d.querySelector('#s-xlstd-n'), '5');
  check(await until(async () => (await call('GET', `/api/share-defaults?space=org:${ORG}`)).stored.req_files === 5), 'org: the number saved');
  await until(() => d.querySelector('#s-xlstd-n')?.value === '5');
  change(w, d.querySelector('.frq-kinds input[value="media"]'), true);
  check(await until(async () => (await call('GET', `/api/share-defaults?space=org:${ORG}`)).stored.req_types?.includes('media')), 'org: the kinds saved');
  change(w, d.querySelector('#s-xlstd-days'), '500');  // above the limit: the server refuses, the shown value goes back
  check(await until(() => d.querySelector('#s-xlstd-days')?.value === '30'), 'a value above the limit goes back');

  // ================= the search
  const q = d.querySelector('#s-search');
  q.value = 'Freigabe'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => /Sharing defaults/.test(d.querySelector('#s-sres')?.textContent || '')), 'the settings search finds the section: ' + d.querySelector('#s-sres')?.textContent);
  w.close();

  // ================= the dialogs of the organisation start with them
  w = await boot({user: 'alice', hash: 'ablage', ls: {abSpace: `"org:${ORG}"`}}); d = w.document;
  await until(() => w.eval(`typeof xl_newDlg === 'function' && !!S.me`));
  await w.eval(`xl_newDlg(${OF})`);
  const md = await until(() => d.querySelector('.xldlg'));
  check(md?.querySelector('#xl-exp')?.value === '30d', 'the link dialog starts with 30 days: ' + md?.querySelector('#xl-exp')?.value);
  w.eval(`$('.xldlg')?.remove()`);
  await w.eval(`frq_open({id: ${OF}, name: 'Kunde Nord'})`);
  (await until(() => d.querySelector('[data-frq="new"]')))?.click();
  const nf = await until(() => d.querySelector('.frqnew'));
  const days = Math.round((new Date(nf?.querySelector('#frq-exp')?.value) - new Date(w.eval('today()'))) / 864e5);
  check(days === 30, 'the request dialog: 30 days ' + days);
  check(nf?.querySelector('#frq-mb')?.value === '10' && nf?.querySelector('#frq-n')?.value === '5', 'the request dialog: 10 MB, 5 files');
  check(nf?.querySelector('input[value="media"]')?.checked && nf?.querySelector('input[value="docs"]')?.checked && !nf?.querySelector('input[value="design"]')?.checked, 'the request dialog: the kinds');
  w.close();

  // ================= a member reads them
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal('data')`);
  const be = await until(() => d.querySelector('#s-xlstd-exp'));
  check(be?.value === '30d' && be?.disabled && d.querySelector('#s-xlstd-mb')?.disabled && d.querySelector('.frq-kinds input')?.disabled, 'a member sees them disabled');
  check(/Only an admin/.test(d.querySelector('#s-xlstd')?.textContent || '') && !d.querySelector('[data-xlstd="reset"]'), 'a member: the hint, no way back');
  w.close();

  console.log(`pr2470_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
