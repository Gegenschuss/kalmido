// 2.112.1 UI tests of part B (#2058, own container, start.sh; P21121B_NOSTART=1: the container runs already). jsdom:
// - the file store: a row's menu has "Link for external people…" (its owner); the details show the section "Link for
//   external people" with "Create link"; the dialog (expiry, password, label) makes the link and shows it with "Copy"
// - the row gets the link badge; the section lists the link with copy / new link / revoke; revoking is ONE undo step
// - the organisation's switch in Settings > Workspaces (its admin): off and back on with undo
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const firefox = require('./ff')({tag: 'p21121_b_ui', check, shots: 'P21121B_SHOTS'});
const PNG = Buffer.from('89504e470d0a1a0a0000000d4948445200000001000000010806000000' +
  '1f15c4890000000d49444154789c6360000002000154a24f5d0000000049454e44ae426082', 'hex');
if (!process.env.P21121B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const upload = async (ck, name, text, form) => {
  const fd = new FormData(); fd.append('file', new Blob([text]), name);
  for (const [k, v] of Object.entries(form || {space: 'private'})) fd.append(k, v);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).items[0].id;
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const me = (await call('GET', '/api/state')).me;
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id})).id;
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files'])].filter(Boolean).join(',')});
  const KUNDE = (await call('POST', '/api/files/folders', {name: 'Kunde Nord', space: 'private'})).id;
  await upload(CK, 'angebot.txt', 'Angebot', {parent_id: KUNDE});

  const w = await boot({user: 'alice', hash: 'ablage', ls: {abSpace: '"private"'}}), d = w.document;
  const row = await until(() => d.querySelector(`.abrow[data-abid="${KUNDE}"]`));
  check(row, 'the folder "Kunde Nord" in My files');
  row?.querySelector('[data-ab="menu"]').click();
  await until(() => d.querySelector('#pop [role="menuitem"]'));
  const labels = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  check(labels.some(t => /Link for external people/.test(t)), 'the menu offers "Link for external people…" ' + labels.join('|'));
  d.querySelector('#pop')?.remove();

  // ================= the details: the section, the dialog
  w.eval(`ab_details(${KUNDE})`);
  const sec = await until(() => d.querySelector('.abdlg .xl-sec [data-xl="new"]') && d.querySelector('.abdlg .xl-sec'), 60);
  check(sec && /Link for external people/.test(sec.textContent), 'details: the section with "Create link" ' + (sec?.textContent || '').slice(0, 120));
  sec?.querySelector('[data-xl="new"]').click();
  const md = await until(() => d.querySelector('.xldlg'));
  check(md && md.querySelector('#xl-exp')?.value === '7d' && md.querySelector('#xl-pw')?.type === 'password', 'dialog: 7 days preset, a password field');
  if (md) {
    md.querySelector('#xl-exp').value = '30d';
    md.querySelector('#xl-lbl').value = 'Kunde Nord GmbH';
    md.querySelector('[data-xn="make"]').click();
  }
  const out = await until(() => md && !md.querySelector('.xl-out').hidden && md.querySelector('#xl-url').value, 60);
  check(out && /\/s\/f\/[A-Za-z0-9_-]{20,}$/.test(md.querySelector('#xl-url').value) && md.querySelector('[data-xn="copy"]'), 'the link is shown with "Copy"');
  const j = await call('GET', `/api/files/nodes/${KUNDE}/ext-links`);
  const L = (j.links || [])[0];
  check(L && L.label === 'Kunde Nord GmbH' && L.expires_at && new Date(L.expires_at) - Date.now() > 29 * 86400e3, 'stored: label, 30 days');
  check(w.eval(`/external/i.test(HIST.undo[HIST.undo.length - 1]?.label || '')`), 'making it = one undo step');
  md?.querySelector('.foot [data-m="close"]').click();

  // ================= the badge, the list in the section, revoke + undo
  const rx = await until(() => d.querySelector(`.abrow[data-abid="${KUNDE}"] .abbadges [title="Shared through an external link"]`), 60);
  check(rx, 'the row shows the link badge');
  const lrow = await until(() => d.querySelector(`.abdlg .xl-row[data-xlid="${L?.id}"]`), 60);
  check(lrow && /Kunde Nord GmbH/.test(lrow.textContent) && lrow.querySelector('[data-xl="copy"]') && lrow.querySelector('[data-xl="regen"]'),
    'the section lists the link with copy / new link ' + (lrow?.textContent || '').slice(0, 120));
  const n0 = w.eval('HIST.undo.length');
  lrow?.querySelector('[data-xl="revoke"]').click();
  check(await until(async () => !((await call('GET', `/api/files/nodes/${KUNDE}/ext-links`)).links || []).length, 60), 'revoked');
  check(await until(() => w.eval('HIST.undo.length') === n0 + 1), 'revoking = one undo step');
  check(await until(() => !d.querySelector(`.abdlg .xl-row[data-xlid="${L?.id}"]`)), 'the section no longer lists it');
  await w.eval(`histStep('undo')`);
  check(await until(async () => ((await call('GET', `/api/files/nodes/${KUNDE}/ext-links`)).links || []).length === 1, 60), 'Undo brings the link back');

  // ================= the organisation's switch (Settings > Workspaces)
  const on = await w.eval(`(async () => {
    const box = document.createElement('div'); document.body.appendChild(box);
    box._j = await api('GET', '/api/orgs');
    box.innerHTML = box._j.orgs.map(o => '<details class="wsorg" data-oid="' + o.id + '" open><summary>' + esc(o.name) + '</summary></details>').join('');
    xl_paneDraw(box); window._xlbox = box;
    return !!box.querySelector('#xl-o${ORG}')?.checked;
  })()`);
  check(on === true, 'the organisation switch is on by default');
  const cb = d.querySelector(`#xl-o${ORG}`);
  if (cb) { cb.checked = false; cb.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(async () => (await call('GET', '/api/orgs')).orgs.find(o => o.id === ORG)?.ext_links === false, 60), 'switched off');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', '/api/orgs')).orgs.find(o => o.id === ORG)?.ext_links === true, 60), 'Undo switches it on again');
  w.close();

  // ================= the real layout on a phone (Firefox): the public folder / file / password page, the details
  const PICF = await upload(CK, 'motiv.png', PNG, {parent_id: KUNDE});
  const pth = u => u.replace(/^https?:\/\/[^/]+\//, '');
  const FOLDER = pth((await call('GET', `/api/files/nodes/${KUNDE}/ext-links`)).links[0].url);
  const pr = await call('POST', `/api/files/nodes/${PICF}/ext-links`, {expires: '7d'});
  const FILE = pth(pr.links.find(x => x.id === pr.id).url);
  const pw = await call('POST', `/api/files/nodes/${PICF}/ext-links`, {password: 'sesame123'});
  const PW = pth(pw.links.find(x => x.id === pw.id).url);
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const fits = '(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1)()';
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + FOLDER);
    check(await ready(ev, `/angebot\\.txt/.test(document.body.textContent) && /motiv\\.png/.test(document.body.textContent)`), 'phone: the folder page lists the files');
    check(await ev(fits), 'phone: the folder page fits the screen');
    check(await ev(`[...document.querySelectorAll('ul.xl-list a')].every(a => a.getBoundingClientRect().height >= 40)`), 'phone: big targets');
    await shot('p21121-b-folder-phone.png');
    await nav(B + FILE);
    check(await ready(ev, `!!document.querySelector('.xl-prev img') && document.querySelector('.xl-prev img').naturalWidth > 0`), 'phone: the file page shows the picture');
    check(await ev(fits) && await ev(`!!document.querySelector('a.xl-btn[download]')`), 'phone: download button, fits');
    await shot('p21121-b-file-phone.png');
    await nav(B + PW);
    check(await ready(ev, `!!document.querySelector('form.pw input[type=password]') && !document.querySelector('.xl-prev')`), 'phone: the password page');
    await shot('p21121-b-password-phone.png');
    await nav(B + 'static/icon.svg');  // the public page's CSP allows no fetch
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#ablage');
    check(await ready(ev, `typeof ab_details === 'function' && !!document.querySelector('.abrow[data-abid="${KUNDE}"]')`, 80), 'phone: the file store');
    await ev(`(() => { ab_details(${KUNDE}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.abdlg .xl-row')`, 60), 'phone: the details list the link');
    await ev(`(() => { document.querySelector('.abdlg .xl-sec').scrollIntoView(); return 1; })()`);
    check(await ev(`[...document.querySelectorAll('.abdlg .xl-row .iconbtn')].every(b => b.getBoundingClientRect().width >= 40)`), 'phone: the link buttons are big enough');
    await shot('p21121-b-details-phone.png');
    await ev(`(() => { xl_newDlg(${KUNDE}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.xldlg #xl-exp')`), 'phone: the new link dialog');
    await shot('p21121-b-dialog-phone.png');
  }, true);

  console.log(`p21121_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
