// 2.96.0 UI tests of part A (#1941, own container, start.sh; P296A_NOSTART=1: the container runs already). jsdom:
// - the file store: a row's menu has "Move to another workspace…" (a person in an organisation), the dialog names the
//   source and the target, the dry run's notes show, "Move" moves; ONE undo step brings it back
// - choosing several rows (Select, checkboxes, the bar "n selected"): into the other workspace in one go, one undo step
// - documents: Select, cards toggle instead of opening, the bar moves the chosen documents into the organisation
// - a person without an organisation: no "Move to another workspace…" anywhere (there is no other workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P296A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const upload = async (ck, name, text, form) => {
  const fd = new FormData(); fd.append('file', new Blob([text]), name);
  for (const [k, v] of Object.entries(form || {space: 'private'})) fd.append(k, v);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).items[0].id;
};
const menuLabels = async (w, row) => {
  row.querySelector('[data-ab="menu"]').click();
  await until(() => w.document.querySelector('#pop [role="menuitem"]'));
  const out = [...w.document.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  w.document.querySelector('#pop')?.remove();
  return out;
};
// the shared dialog: wait for the dry run, then press "Move"
const confirmMove = async w => {
  const md = await until(() => w.document.querySelector('.smv-dlg'));
  const yes = md && await until(() => !md.querySelector('[data-smv="yes"]').disabled && md.querySelector('.smv-notes li') && md, 60);
  if (yes) yes.querySelector('form').dispatchEvent(new w.Event('submit', {cancelable: true, bubbles: true}));
  return md;
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const me = (await call('GET', '/api/state')).me;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id})).id;
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files', 'docs'])].filter(Boolean).join(',')});
  const KISTE = (await call('POST', '/api/files/folders', {name: 'Kiste', space: 'private'})).id;
  const A1 = await upload(CK, 'eins.txt', 'erste Datei'), A2 = await upload(CK, 'zwei.txt', 'zweite Datei');

  // ================= the row menu + the dialog + undo
  const w = await boot({user: 'alice', hash: 'ablage', ls: {abSpace: '"private"'}}), d = w.document;
  const row = await until(() => d.querySelector(`.abrow[data-abid="${KISTE}"]`));
  check(row, 'the folder "Kiste" in My files');
  const labels = row ? await menuLabels(w, row) : [];
  check(labels.some(t => /Move to another workspace/.test(t)), 'the menu offers "Move to another workspace…" ' + labels.join('|'));
  w.eval(`ab_smvSpace([AB.data.items.find(x => x.id === ${KISTE})])`);
  const md = await confirmMove(w);
  check(md && /Kiste/.test(md.querySelector('.smv-what')?.textContent || '') && /Alpha/.test(md.querySelector('#smv-to')?.textContent || ''),
    'the dialog names the folder and offers Alpha as the target ' + (md?.textContent || '').slice(0, 200));
  check(await until(async () => (await call('GET', `/api/files/nodes/${KISTE}`)).org_id === ORG, 60), 'the folder is in Alpha now');
  check(await until(() => w.eval(`!!HIST.undo.length && /workspace/.test(HIST.undo[HIST.undo.length - 1].label)`)), 'one undo step');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/files/nodes/${KISTE}`)).org_id === null, 60), 'Undo brings it back into the private space');

  // ================= several rows: Select, checkboxes, the bar
  w.eval('ab_reload()');
  await until(() => d.querySelector(`.abrow[data-abid="${A1}"]`));
  d.querySelector('[data-absel="mode"]').click();
  await until(() => d.querySelector('.absel input'));
  for (const id of [A1, A2]) { const b = d.querySelector(`[data-absel="one"][data-id="${id}"]`); b.checked = true; b.dispatchEvent(new w.Event('change', {bubbles: true})); }
  // 2.428.0 (#3581): the shared floating bar; "Move to another workspace…" sits under its "More"
  const bar = await until(() => /2 selected/.test(d.querySelector('#ab-sbar')?.textContent || '') && d.querySelector('#ab-sbar'));
  check(bar && bar.querySelector('[data-absel="more"]') && !bar.querySelector('[data-absel="more"]').disabled, 'the bar: 2 selected, "More" ' + (bar?.textContent || ''));
  bar?.querySelector('[data-absel="more"]').click();
  const sp1 = await until(() => d.querySelector('#pop .menu-list .msm-space'));
  check(sp1, 'More offers "Move to another workspace…"');
  sp1?.click();
  const md2 = await confirmMove(w);
  check(md2 && /2 items/.test(md2.querySelector('.smv-what')?.textContent || ''), 'the dialog says "2 items"');
  check(await until(async () => (await call('GET', `/api/files/nodes/${A1}`)).org_id === ORG && (await call('GET', `/api/files/nodes/${A2}`)).org_id === ORG, 60),
    'both files are in Alpha');
  const n0 = w.eval('HIST.undo.length');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/files/nodes/${A1}`)).org_id === null && (await call('GET', `/api/files/nodes/${A2}`)).org_id === null, 60) && w.eval('HIST.undo.length') === n0 - 1,
    'one undo step brings both back');
  w.close();

  // ================= documents: Select, the bar, into the organisation
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob(['Rechnung Beispiel 12,50 EUR']), 'beleg.txt');
  const DOC = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${DOC}`)).state), 300);  // a running recognition blocks the move
  const v = await boot({user: 'alice', hash: 'docs'}), vd = v.document;
  const card = await until(() => vd.querySelector(`[data-dco="${DOC}"]`), 60);
  check(card, 'the document card');
  vd.querySelector('[data-dcsel="mode"]')?.click();
  // 2.430.0 (#3582): a plain click on a card opens it even while choosing; the box on the card chooses
  await until(() => vd.querySelector(`.dc-grid.dc-selon [data-dcchk="${DOC}"]`));
  vd.querySelector(`[data-dcchk="${DOC}"]`).click();
  check(await until(() => vd.querySelector(`[data-dcchk="${DOC}"]`)?.getAttribute('aria-checked') === 'true' && !vd.querySelector('.dc-md')), 'Select: the box chooses the card, nothing opens');
  const dbar = await until(() => /1 selected/.test(vd.querySelector('#dc-sbar')?.textContent || '') && vd.querySelector('#dc-sbar'));  // 2.428.0 (#3581)
  dbar?.querySelector('[data-dcsel="more"]')?.click();
  const sp2 = await until(() => vd.querySelector('#pop .menu-list .msm-space'));
  check(dbar && sp2, 'the bar of the documents: 1 selected, "Move to another workspace…" under More');
  sp2?.click();
  await confirmMove(v);
  check(await until(async () => (await call('GET', `/api/docs/${DOC}`)).org_id === ORG, 60), 'the document is in Alpha');
  check(await until(() => v.eval(`!!HIST.undo.length && /workspace/.test(HIST.undo[HIST.undo.length - 1].label)`)), 'documents: one undo step');
  v.close();

  // ================= a person without an organisation: no other workspace, no action
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'}, FCK);
  const FN = await upload(FCK, 'eigen.txt', 'frei');
  const f = await boot({user: 'frida', hash: 'ablage'}), fdoc = f.document;
  const frow = await until(() => fdoc.querySelector(`.abrow[data-abid="${FN}"]`));
  const fl = frow ? await menuLabels(f, frow) : [];
  check(frow && fl.length && !fl.some(t => /another workspace/.test(t)), 'freelancer: no "Move to another workspace…" in the menu ' + fl.join('|'));
  check(f.eval('smv_can(null)') === false, 'freelancer: smv_can is false');
  fdoc.querySelector('[data-absel="mode"]')?.click();
  await until(() => fdoc.querySelector('#ab-sbar'));  // 2.428.0 (#3581): the shared bar, without "More" (nothing else in it)
  check(fdoc.querySelector('#ab-sbar') && !fdoc.querySelector('[data-absel="space"], [data-absel="more"]'), 'freelancer: the bar has no workspace button');
  f.close();

  console.log(`p296_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
