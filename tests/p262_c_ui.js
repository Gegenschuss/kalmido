// 2.62.0 part C UI tests, own container (start.sh). jsdom:
// - #1853 the list menu (sidebar) and the group menu of the basket: ONE entry "Change position…", the four moves in its second level
//   (opens in the same place, "Back" on top, keyboard)
// - #1485 the head of the list and folder settings (name, "Saved · Undo", close) is sticky
// - #1844 Documents: the tab loads again on every open (a list that was empty before shows what arrived since)
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,files,docs';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L1 = (await call('POST', '/api/lists', {name: 'Alpha'})).id, L2 = (await call('POST', '/api/lists', {name: 'Beta'})).id;
  await call('POST', '/api/tasks', {title: 'One', list_id: L1});

  // ================= #1853 the sidebar list menu
  let w = await boot({user: 'alice', hash: 'l/' + L2}), d = w.document;
  await until(() => d.querySelector('#side .srow[data-list]'));
  const labels = () => [...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim());
  w.eval(`menu(document.querySelector('#side .srow[data-list="${L2}"]'), listMenuItems(${L2}, document.querySelector('#side .srow[data-list="${L2}"]')))`);
  await sleep(200);
  check(labels().some(x => /^Change position/.test(x)) && !labels().some(x => /^Move (up|down)$|Move to the (top|bottom)/.test(x)), '#1853: the sidebar menu has one entry "Change position…" ' + labels().join('|'));
  const pos = [...d.querySelectorAll('#pop .menu-list button')].find(b => /Change position/.test(b.textContent));
  check(pos?.getAttribute('aria-haspopup') === 'menu', '#1853: the entry opens a second level');
  click(w, pos); await sleep(200);
  check(['Back', 'Move up', 'Move down', 'Move to the top', 'Move to the bottom'].every(x => labels().includes(x)), '#1853: the second level has Back and the four moves ' + labels().join('|'));
  key(w, d.activeElement, 'ArrowLeft'); await sleep(200);
  check(labels().some(x => /^Change position/.test(x)), '#1853: ← goes back (keyboard)');
  click(w, [...d.querySelectorAll('#pop .menu-list button')].find(b => /Change position/.test(b.textContent))); await sleep(200);
  click(w, [...d.querySelectorAll('#pop .menu-list button')].find(b => b.textContent.trim() === 'Move up')); await sleep(800);
  const ls = (await call('GET', '/api/state')).lists;
  check(ls.find(l => l.id === L2).sort < ls.find(l => l.id === L1).sort, '#1853: "Move up" in the second level moves the list');

  // ================= #1485 the sticky head of the list settings and the folder settings
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(/\.lmodal \.card>\.lhdr,\.fsmodal \.card>\.lhdr\{[^}]*position:sticky;top:0/.test(css), '#1485: CSS: the settings head is sticky');
  w.eval(`listModal(${L1})`); await sleep(500);
  const hd = d.querySelector('.lmodal .lhdr');
  check(hd && hd.parentElement.classList.contains('card') && hd.querySelector('.ssaved'), '#1485: the list settings head (Saved · Undo) is a direct child of the scrolling card');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  await call('PATCH', `/api/lists/${L1}`, {folder: 'Work'});
  await w.eval(`load().then(render)`); await sleep(500);
  w.eval(`folderPropsModal('Work')`); await sleep(500);
  const fh = d.querySelector('.fsmodal .lhdr');
  check(fh && fh.parentElement.classList.contains('card') && fh.querySelector('.ssaved'), '#1485: the folder settings head is a direct child of the card');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  w.close();

  // ================= #1853 the group menu of the basket
  w = await boot({user: 'alice', hash: 'assigned'}); d = w.document;
  await call('PATCH', '/api/settings', {}).catch(() => {});
  await until(() => d.querySelector('#view'));
  w.eval(`menu(document.querySelector('#top h1') || document.body, [mpo_posItem([{label: 'Move up', fn() {}}, {label: 'Move down', fn() {}}])])`);
  await sleep(200);
  check(labels().length === 1 && /Change position/.test(labels()[0]), '#1853: mpo_posItem builds the one entry');
  d.querySelectorAll('#pop').forEach(p => p.classList.add('hidden'));
  w.close();

  // ================= #1844 Documents: opened empty first, a file arrives, opened again
  w = await boot({user: 'alice', hash: 'docs'}); d = w.document;
  await until(() => d.querySelector('.dc-view'));
  await until(() => d.querySelector('.dc-empty'));
  check(!!d.querySelector('.dc-empty'), '#1844: the first open shows the empty page');
  const fd = new FormData(); fd.append('files', new Blob(['Invoice 42 from Example Ltd'], {type: 'text/plain'}), 'letter.txt'); fd.append('ws', 'private');
  const up = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  check(up.status < 300, '#1844: a document is added behind the page\'s back (' + up.status + ')');
  await sleep(3300);
  w.eval(`go('ablage')`); await sleep(500);
  w.eval(`go('docs')`);
  check(await until(() => d.querySelector('.dc-card'), 60), '#1844: opening the tab again shows the document');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
