// 2.46.0 UI tests of part D, own container (start.sh). jsdom:
// - #1604 the Share dialog and the settings of a folder / of a list lead to each other with "Back", both ways, without stacking
//   dialogs (going back and forth leaves one visible dialog and at most one hidden parent)
// - #1563 the encryption block of Administration > Organisation has one heading and one "More" link; the boundary check lists
//   kind, object and person / agent, and "Clean up" removes the memberships of people
const {execFileSync} = require('child_process');
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
const FEAT = 'cal,comments,collab';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const LID = (await call('POST', '/api/lists', {name: 'Plans', folder: 'Team'})).id;
  const w = await boot({user: 'alice'}), d = w.document;
  await until(() => d.querySelector('#side .fhead[data-folder="Team"]'));
  const vis = () => [...d.querySelectorAll('.modal')].filter(m => m.style.display !== 'none');
  const hid = () => [...d.querySelectorAll('.modal')].filter(m => m.style.display === 'none');
  const footBtn = (m, sel) => m.querySelector('.foot ' + sel);
  const back = m => /Back/.test(m?.querySelector('.foot .btn.pri')?.textContent || '');

  // ================= #1604 folder: Share -> settings -> Share -> settings, Back each time
  w.eval(`LS.set('agSafeSeen', true); folderShareModal('Team')`);
  let md = await until(() => d.querySelector('.modal.fshmodal #fsh-members [data-m="add"]')?.closest('.modal'));
  check(md && !back(md), '#1604: the Share dialog opened on its own says "Done"');
  click(w, footBtn(md, '[data-m="fsh-props"]'));
  let pr = await until(() => d.querySelector('.modal.fsmodal #fs-am')?.closest('.modal'));
  check(pr && back(pr), '#1604: the folder settings opened from Share say "Back"');
  check(vis().length === 1 && hid().length === 1, '#1604: one visible dialog, the Share dialog hidden under it');
  click(w, footBtn(pr, '[data-m="people"]'));
  await sleep(300);
  check(vis().length === 1 && vis()[0] === md && hid().length === 0 && !pr.isConnected, '#1604: "Share…" in the settings goes back to the Share dialog, no stack');
  click(w, footBtn(md, '[data-m="fsh-props"]'));
  pr = await until(() => d.querySelector('.modal.fsmodal #fs-am')?.closest('.modal'));
  click(w, footBtn(pr, '.btn.pri'));
  await sleep(300);
  check(vis().length === 1 && vis()[0] === md && hid().length === 0, '#1604: "Back" of the settings shows the Share dialog again');
  click(w, md.querySelector('.lhdr [data-m="close"]'));
  await sleep(300);
  check(vis().length === 0, '#1604: closing the Share dialog leaves nothing open');

  // folder settings first -> Share (Back) -> settings (still no stack)
  w.eval(`folderPropsModal('Team')`);
  pr = await until(() => d.querySelector('.modal.fsmodal #fs-am')?.closest('.modal'));
  check(pr && !back(pr), '#1604: the folder settings on their own say "Done"');
  click(w, footBtn(pr, '[data-m="people"]'));
  md = await until(() => d.querySelector('.modal.fshmodal #fsh-members [data-m="add"]')?.closest('.modal'));
  check(md && back(md) && vis().length === 1 && hid().length === 1, '#1604: Share from the settings says "Back"');
  click(w, footBtn(md, '[data-m="fsh-props"]'));
  await sleep(300);
  check(vis().length === 1 && vis()[0] === pr && hid().length === 0, '#1604: "Folder settings…" in a Share dialog with Back returns, does not stack');
  click(w, footBtn(pr, '.btn.pri'));
  await sleep(200);
  check(vis().length === 0, '#1604: Done closes everything');

  // ================= #1604 list: Share <-> list settings
  w.eval(`shareModal(${LID})`);
  md = await until(() => d.querySelector('.modal [data-m="list-edit"]')?.closest('.modal'));
  check(md && !back(md), '#1604: the list Share dialog on its own says "Done"');
  click(w, footBtn(md, '[data-m="list-edit"]'));
  let le = await until(() => d.querySelector('.modal [data-m="share-open"]')?.closest('.modal'));
  check(le && back(le) && vis().length === 1 && hid().length === 1, '#1604: the list settings opened from Share say "Back"');
  click(w, le.querySelector('[data-m="share-open"]'));
  await sleep(400);
  check(vis().length === 1 && vis()[0] === md && hid().length === 0 && !le.isConnected, '#1604: "Share…" in the list settings goes back, no stack');
  click(w, footBtn(md, '[data-m="list-edit"]'));
  le = await until(() => d.querySelector('.modal [data-m="share-open"]')?.closest('.modal'));
  click(w, footBtn(le, '.btn.pri'));
  await sleep(400);
  check(vis().length === 1 && vis()[0] === md && hid().length === 0, '#1604: "Back" of the list settings shows the Share dialog');
  click(w, footBtn(md, '.btn.pri'));
  await sleep(200);
  check(vis().length === 0, '#1604: Done closes the list Share dialog');
  w.eval(`listModal(${LID})`);
  le = await until(() => d.querySelector('.modal [data-m="share-open"]')?.closest('.modal'));
  check(le && !back(le), '#1604: the list settings on their own have no Back');
  click(w, le.querySelector('[data-m="share-open"]'));
  md = await until(() => d.querySelector('.modal [data-m="list-edit"]')?.closest('.modal'));
  check(md && back(md) && vis().length === 1 && hid().length === 1, '#1604: Share from the list settings says "Back"');
  click(w, footBtn(md, '.btn.pri'));
  await sleep(400);
  check(vis().length === 1 && vis()[0] === le, '#1604: its "Back" shows the list settings again');

  // @@1563@@

  console.log(`p2460_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
