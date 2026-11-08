// kalmido-suite: fresh
// 2.576.0 (#4487) UI tests: Office > Receipts and the file store apart (decision 04.11.2026). Own container (start.sh),
// Firefox. Invented people and companies only. Carol has NO organisation (her personal office).
// - a computer: Office > Receipts is a tree node; unfolded it lists her office upload not recorded yet ("New in the office"),
//   never her private document; the file store's All documents (2.752.0 #4887: a row, no tree of its own) shows only the private one
// - the office document's sheet points to the other place instead of a copy: "Also in Office › Receipts" and "File store"
//   (its folder), the jump opens it; the private document's sheet has no such line
// - a phone, 390 px: the line fits, nothing sticks out, the jump closes the sheet and opens the file store's folder
// freelancer-matrix: files
// P2576C_NOSTART=1 = the server already runs; P2576C_SHOTS=<dir> keeps the screenshots.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2576_c_ui', check, shots: 'P2576C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2576C_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const up = async (ck, name, text, area) => {
  const fd = new FormData();
  fd.append('files', new Blob([text], {type: 'text/plain'}), name); fd.append('ws', 'private');
  if (area) fd.append('area', area);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return ((await r.json().catch(() => ({}))).ids || [])[0];
};
const FEAT = 'office,clients,files,docs';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CC = await login('carol');
  await call(CC, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  check(!((await call(CC, 'GET', '/api/state')).me.workspaces || []).length, 'carol has no organisation');
  check((await call(CC, 'PUT', '/api/office/settings', {company_fields: {name: 'Carol Grafik', vat_id: 'DE111222333'}})).http === 200, 'setup: her personal office');
  const OD = await up(CC, 'bueromarkt.txt', 'Beispiel Büromarkt KG\nRechnung Nr. BM-2026-21\nNetto 50,00 EUR\nUSt 19 % 9,50 EUR\nGesamt 59,50 EUR\n', 'office');
  const PD = await up(CC, 'urlaub.txt', 'Liebe Grüße aus dem Urlaub, bis bald.\n');
  check(OD && PD, 'setup: an office upload and a private document');
  let parent = null;
  for (let i = 0; i < 80 && !parent; i++) { const d = await call(CC, 'GET', `/api/docs/${OD}`); if (d.area?.area === 'office' && d.state === 'done') parent = d.parent_id; else await sleep(250); }
  check(parent, 'setup: the office document is recognised, in the office, in a folder');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'carol', password: 'password123'})}).then(r => r.status)`);
  const node = id => `document.querySelector('#side .sbbt[data-sbbid="${id}"]')`;
  const also = `document.querySelector('.dc-md .rc-also')`;

  // ================= a computer
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.sbbUnfold', '["office:money"]'); localStorage.setItem('tasks.ofmAll', 'true'); return 1; })()`);
    check(await signIn(ev) === 200, 'carol signs in');
    await nav(B + '#office/receipts');
    check(await ready(ev, `!!${node('a:receipts')}`, 80), 'computer: Office > Receipts is a tree node');
    await ev(`(() => { const a = ${node('a:receipts')}?.querySelector('[data-act="sbb-tree"]'); if (a && !a.dataset.open) a.click(); return 1; })()`);
    check(await ready(ev, `/New in the office/.test(${node('d:receipts:' + OD)}?.textContent || '')`, 60),
      'computer: unfolded, Receipts lists the office upload not recorded yet');
    check(await ev(`!${node('d:receipts:' + PD)}`), 'computer: never the private document');
    await shot('p2576c-desktop-receipts.png');
    // the file store's documents: lists only the private document. 2.752.0 (#4887): "All documents" is a row below the one
    // tree of the panel (no fold node with a second tree of the same folders any more)
    await nav(B + '#docs');
    check(await ready(ev, `!!document.querySelector('#side .abfilt [data-go="ablage/docs"][aria-current="page"]') && location.hash === '#ablage/docs'`, 80), 'computer: All documents, marked (the old link leads there)');
    check(await ev(`!document.querySelector('#side .dc-ptree') && !document.querySelector('#side [data-k="ab:docs"]')`), 'computer: no second folder tree below it');
    check(await ready(ev, `!!document.querySelector('.dc-view [data-dco="${PD}"]') && !document.querySelector('.dc-view [data-dco="${OD}"]')`, 60),
      'computer: the file store\'s documents: the private one, not the office\'s');
    // the office document's sheet points to Office > Receipts and to its folder
    await nav(B + '#docs/' + OD);
    check(await ready(ev, `!!${also}?.querySelector('[data-rcgo="office/receipts"]') && !!${also}?.querySelector('[data-rcgo="ablage/${parent}"]')`, 80),
      'computer: the office document: "Also in" Office › Receipts and File store ' + await ev(`${also}?.textContent || ''`));
    check(await ev(`/Also in/.test(${also}?.textContent || '') && /Receipts/.test(${also}.textContent)`), 'computer: the line is named');
    await shot('p2576c-desktop-also.png');
    await ev(`(() => { ${also}.querySelector('[data-rcgo="office/receipts"]').click(); return 1; })()`);
    check(await ready(ev, `location.hash === '#office/receipts'`, 40), 'computer: the jump opens Office > Receipts');
    await nav(B + '#docs/' + PD);
    check(await ready(ev, `!!document.querySelector('.dc-md .dc-body[data-id="${PD}"]')`, 80) && await ev(`!${also}`), 'computer: the private document: no "Also in"');
  }, false);

  // ================= a phone, 390 px
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await signIn(ev) === 200, 'phone: carol signs in');
    await nav(B + '#docs/' + OD);
    check(await ready(ev, `!!${also}?.querySelector('[data-rcgo="ablage/${parent}"]')`, 80), 'phone: the office document\'s sheet has "Also in"');
    check(await ev(`(() => { const r = ${also}.getBoundingClientRect(); return r.width > 0 && r.right <= innerWidth + 1 && document.documentElement.scrollWidth <= innerWidth + 1; })()`),
      'phone: the line fits into 390 px, nothing sticks out');
    await shot('p2576c-phone-also.png');
    await ev(`(() => { ${also}.querySelector('[data-rcgo="ablage/${parent}"]').click(); return 1; })()`);
    check(await ready(ev, `location.hash === '#ablage/${parent}' && !document.querySelector('.dc-md:not(.dc-pane)')`, 40), 'phone: the jump closes the sheet, opens its folder');
  }, true);

  console.log(`p2576_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
