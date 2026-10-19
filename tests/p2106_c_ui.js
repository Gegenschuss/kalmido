// 2.106.0 UI tests of part C (#2029, #2030; own container, start.sh without a mail server). jsdom on the phone page:
// - the hooks of part C in LT_HOOKS: a draft gets "Insert text block" (tools); a sent letter none; the list without an open
//   letter gets "Text blocks" (sections, fn(null))
// - insert: the picker lists the office's blocks, the search filters, a tap inserts the block at the cursor of #lt-body
// - manage: a new block (dialog) with undo, delete with undo (the block comes back)
// - without a mail server "Send by e-mail" never shows (the slot of the actions hook empties itself)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2106C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'clients,office,docs', workspace: 'private'});
  const k1 = await call('POST', '/api/office/letter-blocks', {name: 'Grußformel', body: 'Mit freundlichen Grüßen'});
  const k2 = await call('POST', '/api/office/letter-blocks', {starter: 'extension', lang: 'de'});
  check(k1.http === 201 && k2.http === 201, 'setup: two blocks ' + k1.http + ' ' + k2.http);
  const L = await call('POST', '/api/office/letters', {rcpt_name: 'Amt', subject: 'Antrag'});
  check(L.http === 201, 'setup: a draft letter ' + L.http);
  const info = await call('GET', '/api/office/letters/mail-info');
  check(info.http === 200 && info.mail_on === false && info.reply_address === '', 'mail-info: no mail server here ' + JSON.stringify(info));

  const w = await boot({user: 'alice', hash: 'office', mobile: true}), d = w.document;
  check(await until(() => w.eval("typeof ltmBlocksModal === 'function' && typeof LT_HOOKS === 'object'")), 'part C is loaded with the office');
  const draft = JSON.stringify({id: L.id, status: 'draft'}), sent = JSON.stringify({id: L.id, status: 'sent'});
  const hook = (k, arg) => w.eval(`LT_HOOKS.${k}.map(f => f(${arg})).join('')`);
  check(/data-ltm="blocks"/.test(hook('tools', draft)) && /Insert text block/.test(hook('tools', draft)), 'a draft: "Insert text block"');
  check(!/data-ltm/.test(hook('tools', sent)), 'a sent letter: no text block button');
  check(/data-ltm="manage"/.test(hook('sections', 'null')) && !/data-ltm/.test(hook('sections', draft)), 'the list without a letter: "Text blocks"; an open letter: none');

  // a stand-in for the letter editor of part A: the text field + the tool and action buttons
  const box = d.createElement('div'); box.id = 'ltmtest';
  box.innerHTML = `<textarea id="lt-body">Sehr geehrte Damen und Herren,\n\nENDE</textarea><div class="tools">${hook('tools', draft)}</div><div class="acts">${hook('actions', draft)}</div>`;
  d.querySelector('#view').appendChild(box);
  check(await until(() => !d.querySelector('#ltmtest [data-ltm-slot]')), 'the e-mail slot resolves');
  check(!d.querySelector('#ltmtest [data-ltm="mail"]'), 'no mail server: no "Send by e-mail"');

  // ================= insert at the cursor
  const ta = d.querySelector('#lt-body');
  ta.focus(); const at = ta.value.indexOf('ENDE'); ta.setSelectionRange(at, at);
  ta.dispatchEvent(new w.FocusEvent('focusin', {bubbles: true}));
  click(w, d.querySelector('#ltmtest [data-ltm="blocks"]'));
  const rows = () => [...d.querySelectorAll('.modal .ltm-blocks .ltm-pick')];
  check(await until(() => rows().length === 2), 'the picker lists the two blocks ' + rows().length);
  const q = d.querySelector('.modal #ltm-q');
  q.value = 'freundlich'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(rows().length === 1 && /Grußformel/.test(rows()[0].textContent), 'the search filters (also in the text)');
  check(rows()[0].dataset.m === 'ins', 'a tap on the row inserts');
  click(w, rows()[0]);
  check(await until(() => !d.querySelector('.modal')), 'the picker closes');
  check(ta.value === 'Sehr geehrte Damen und Herren,\n\nMit freundlichen GrüßenENDE', 'inserted at the cursor ' + JSON.stringify(ta.value));

  // ================= manage: new with undo, delete with undo
  click(w, d.querySelector('#ltmtest [data-ltm="blocks"]'));
  await until(() => rows().length === 2);
  click(w, d.querySelector('.modal [data-m="new"]'));
  await until(() => d.querySelector('.modal #ltm-bname'));
  const dlg = [...d.querySelectorAll('.modal')].pop();
  dlg.querySelector('#ltm-bname').value = 'Anlage'; dlg.querySelector('#ltm-bbody').value = 'Anlagen: siehe unten';
  click(w, dlg.querySelector('[data-m="save"]'));
  check(await until(() => rows().length === 3), 'a new block shows in the open picker');
  const undo = () => d.querySelector('#toast button:not(.tx)');
  check(await until(() => undo() && /Added/.test(d.querySelector('#toast').textContent)), 'the toast offers undo');
  click(w, undo());
  check(await until(async () => (await call('GET', '/api/office/letter-blocks')).blocks.length === 2), 'undo removes the new block again');
  await until(() => rows().length === 2);
  click(w, rows().find(x => /Grußformel/.test(x.textContent)).closest('.ofcrow').querySelector('[data-m="edit"]'));
  await until(() => d.querySelector('.modal [data-m="del"]'));
  click(w, [...d.querySelectorAll('.modal')].pop().querySelector('[data-m="del"]'));
  check(await until(async () => (await call('GET', '/api/office/letter-blocks')).blocks.length === 1), 'deleted');
  check(await until(() => undo() && /Deleted/.test(d.querySelector('#toast').textContent)), 'delete: the toast offers undo');
  click(w, undo());
  check(await until(async () => (await call('GET', '/api/office/letter-blocks')).blocks.length === 2), 'undo brings the block back');

  // ================= the samples from the picker
  click(w, d.querySelector('.modal [data-m="starters"]'));
  check(await until(() => d.querySelectorAll('.modal .ltm-starters li').length === 4), 'four samples');
  check(/legal advice/.test([...d.querySelectorAll('.modal')].pop().textContent), 'the note: sample text, no legal advice');

  console.log(`p2106_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e && e.stack || e); process.exit(1); });
