// kalmido-suite: fresh
// 2.1048.0 (#5821) UI test: "Scan inbox for this folder…" in the menu of a folder of the documents. Own container (start.sh), jsdom.
// Invented names only.
// - a folder below the documents folder: its "…" menu offers "Scan inbox for this folder…"; a plain folder outside the
//   documents does not
// - the item opens Settings > Integrations > Documents: inboxes with "New scan inbox" open, the folder chosen and its name set;
//   "Create inbox" shows the setup code and the inbox is listed with this folder (the server keeps it on that folder)
// - afterwards the folder's card carries the scanner mark and its menu says "Show scan inbox", which opens the settings at the
//   inbox's row (no new form)
// freelancer-matrix: files (alice has no organisation: her private workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21048_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const menuItems = d => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"] .ml')].map(x => x.textContent.trim());
const pick = (d, label) => [...d.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => b.querySelector('.ml')?.textContent.trim().startsWith(label));
const up = async (url, field, name, text, extra = {}) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  fd.append(field, new Blob([text], {type: 'text/plain'}), name);
  return (await fetch(B + url, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json().catch(() => ({}));
};
const closeMenu = d => d.dispatchEvent(new d.defaultView.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  check(!(st0.me?.workspaces || []).length, 'alice has no organisation');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'files', 'docs'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  const DOC = ((await up('api/docs', 'files', 'statement-alpha.txt', 'An invented bank statement', {ws: 'private'})).ids || [])[0];
  check(DOC, 'setup: a document (makes the documents folder)');
  const ROOT = (await call('GET', `/api/files/nodes/${DOC}`)).parent_id;
  const BANK = (await call('POST', '/api/files/folders', {parent_id: ROOT, name: 'Bank Alpha'})).id;
  const PLAIN = (await call('POST', '/api/files/folders', {space: 'private', name: 'Holiday'})).id;
  check(ROOT && BANK && PLAIN, 'setup: a folder in the documents and a plain folder');
  const sk0 = await call('GET', '/api/docs/scan-keys?ws=private');
  check(sk0.api === true && !(sk0.keys || []).length, 'setup: the API is on, no scan inbox yet');

  const w = await boot({user: 'alice', hash: 'ablage/' + ROOT}), d = w.document;
  const cardMenu = async id => {
    closeMenu(d);
    const b = await until(() => d.querySelector(`[data-ab="menu"][data-id="${id}"]`), 60);
    b?.click();
    return until(() => menuItems(d).length && menuItems(d));
  };
  check(await until(() => w.eval('typeof dsc_folderItems === "function"'), 60), 'the documents\' scripts are loaded');

  // ---- the folder in the documents: the item; the plain folder: none
  let m = await cardMenu(BANK);
  check(m && m.includes('Scan inbox for this folder…'), 'a folder of the documents: "Scan inbox for this folder…" in its menu ' + JSON.stringify(m));
  check(await until(() => w.eval('!!(DSCF.private && DSCF.private.s)')), 'what the workspace offers is known now');
  closeMenu(d);
  w.location.hash = '#ablage';
  m = await cardMenu(PLAIN);
  check(m && !m.some(x => /scan inbox/i.test(x)), 'a plain folder outside the documents: no scan inbox item ' + JSON.stringify(m));
  closeMenu(d);
  w.location.hash = '#ablage/' + ROOT;
  m = await cardMenu(BANK);
  check(m && m.includes('Scan inbox for this folder…'), 'back in the documents: the item again');

  // ---- the item opens the existing form, the folder and its name set
  pick(d, 'Scan inbox for this folder…')?.click();
  const form = await until(() => d.querySelector('#s-scan details.dsc-new[open] #dsc-name'), 60);
  check(!!form, 'Settings > Integrations: "New scan inbox" is open');
  check(d.querySelector('#dsc-name')?.value === 'Bank Alpha', 'the name is the folder\'s name: ' + d.querySelector('#dsc-name')?.value);
  check(d.querySelector('#dsc-folder')?.value === String(BANK), 'the folder is chosen: ' + d.querySelector('#dsc-folder')?.value);
  check(/Bank Alpha/.test(d.querySelector('#dsc-folder')?.selectedOptions?.[0]?.textContent || ''), 'the chosen folder shows its name');
  d.querySelector('#s-scan [data-dsc="new"]')?.click();
  const code = await until(() => d.querySelector('#dsc-code')?.value, 60);
  check(/^kalmido-scan:1:/.test(code || ''), 'Create inbox: the setup code is shown');
  check(await until(() => [...d.querySelectorAll('#s-scan .dsc-key')].some(x => /Bank Alpha/.test(x.textContent))), 'the inbox is listed in the settings');
  const sk1 = await call('GET', '/api/docs/scan-keys?ws=private');
  check((sk1.keys || []).length === 1 && sk1.keys[0].parent_id === BANK && sk1.keys[0].name === 'Bank Alpha', 'the server keeps the inbox on this folder ' + JSON.stringify(sk1.keys));
  d.querySelector('.modal [data-m="close"]')?.click();
  await until(() => !d.querySelector('#s-scan'));

  // ---- the scanner mark and "Show scan inbox"
  w.location.hash = '#ablage';
  await sleep(200);
  w.location.hash = '#ablage/' + ROOT;
  const mark = await until(() => [...d.querySelectorAll('#view .abscan')].find(x => x.closest('li, .abdlrow, .abrow')?.querySelector(`[data-id="${BANK}"]`)), 60);
  check(!!mark && /Scan inbox: Bank Alpha/.test(mark.getAttribute('title') || ''), 'the folder carries the scanner mark with the inbox\'s name');
  m = await cardMenu(BANK);
  check(m && m.includes('Show scan inbox') && !m.includes('Scan inbox for this folder…'), 'a folder with an inbox: "Show scan inbox" ' + JSON.stringify(m));
  pick(d, 'Show scan inbox')?.click();
  const row = await until(() => [...d.querySelectorAll('#s-scan .dsc-key')].find(x => /Bank Alpha/.test(x.textContent)), 60);
  check(!!row && row.classList.contains('sflash'), 'the settings open at the inbox\'s row (marked)');
  check(!d.querySelector('#s-scan details.dsc-new[open]'), 'no new form is opened for it');
  check((await call('GET', '/api/docs/scan-keys?ws=private')).keys.length === 1, 'still one inbox (nothing made twice)');
  w.close();

  console.log(`p21048_scan_folder_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
