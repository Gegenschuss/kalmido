// 2.138.3 part B UI test (#2371 #2189), jsdom, own container (start.sh). Invented names only.
// - #2371 checkbox cell: on the phone (390 px) a tap on the cell beside the box ticks it, the toast offers Undo and Undo takes
//   the tick back; with the mouse a click beside the box only chooses the cell; the box answers in a 44 px square and the
//   arrows of link / file cells are 44 px on touch (sheets.css, rem)
// - #2189 agent chat: while one's own message is edited, the 3-second refresh (chatLoad) keeps the editor: the same textarea,
//   the typed text and the focus stay, Save stores the new text; Cancel ends the editor
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21383B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j._status = r.status; return j; };
const FEAT = 'collab,comments,sheets,agents';
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { try { const x = await fn(); if (x) return x; } catch { /* not yet */ } await sleep(150); } return false; };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const key = (w, el, k, o = {}) => { const ev = new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}); el.dispatchEvent(ev); return ev; };
const rem = v => parseFloat(v) * 16;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments', 'agents']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;

  // ---- static: the 44 px targets (sheets.css, 2.138.3 B)
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'sheets.css'), 'utf8');
  const from = css.indexOf('2.138.3 B (#2371)'), mine = css.slice(from, css.indexOf('padding-right:3rem', from) + 30).replace(/\/\*[\s\S]*?\*\//g, '');
  const coarse = (mine.match(/@media \(pointer:coarse\)\{([^@]*)\}/) || [])[1] || '';
  const lnk = /\.shklnk\{width:([\d.]+)rem;height:([\d.]+)rem\}/.exec(coarse);
  check(lnk && rem(lnk[1]) >= 44 && rem(lnk[2]) >= 44, 'touch: the arrows of link / file cells are at least 44 px: ' + coarse.slice(0, 200));
  const ins = /\.shkbox::after\{[^}]*inset:-([\d.]+)rem/.exec(mine);
  check(ins && 20 + 2 * rem(ins[1]) >= 44, 'the box answers in a square of at least 44 px');
  check(!/(\d+(\.\d+)?)px/.test(mine.replace(/@media[^{]*\{/g, '')), 'sheets.css (2.138.3 B): rem sizes');

  // ---- a table with a checkbox column
  const S0 = await call('POST', '/api/sheets', {title: 'Packing', space: `org:${ORG}`});
  const SID = S0.id, R = S0.rows.map(r => r.id);
  const CB = (await call('POST', `/api/sheets/${SID}/columns`, {title: 'Packed', kind: 'checkbox'})).column.id;
  const cellOf = async (r, c) => ((await call('GET', `/api/sheets/${SID}`)).cells || []).find(x => x.row_id === r && x.col_id === c);

  // phone, 390 px
  let w = await boot({user: 'alice', hash: 'sheets/' + SID, mobile: true}), d = w.document;
  const td = (r, c) => d.getElementById(`shv-c-${r}-${c}`);
  check(await until(() => w.eval('!!SHV.sh') && td(R[0], CB)?.querySelector('[data-shkbox]')), 'phone: the checkbox cell is there');
  check(w.eval('isTouch()'), 'phone: a touch screen');
  click(w, td(R[0], CB));  // the cell itself, not the box
  check(await until(async () => (await cellOf(R[0], CB))?.raw === '1'), 'phone: a tap on the cell beside the box ticks it');
  check(await until(() => td(R[0], CB)?.querySelector('[data-shkbox].on')), 'phone: the box shows the tick');
  const ub = await until(() => d.querySelector('#toast:not(.hidden) button'));
  check(ub && /Undo/.test(ub.textContent) && /changed/.test(d.querySelector('#toast')?.textContent || ''), 'phone: the toast offers Undo: ' + (d.querySelector('#toast')?.textContent || ''));
  click(w, ub);
  check(await until(async () => !((await cellOf(R[0], CB))?.raw)), 'phone: Undo takes the tick back');
  check(await until(() => !td(R[0], CB)?.querySelector('[data-shkbox].on')), 'phone: the box is empty again');
  click(w, td(R[1], CB).querySelector('[data-shkbox]'));
  check(await until(async () => (await cellOf(R[1], CB))?.raw === '1'), 'phone: a tap on the box still ticks');
  check(w.eval(`SHV.cur && SHV.cur.r === ${R[1]} && SHV.cur.c === ${CB}`), 'phone: the ticked cell is the chosen one');
  w.close();

  // computer: a click beside the box chooses the cell, it does not tick
  w = await boot({user: 'alice', hash: 'sheets/' + SID}); d = w.document;
  check(await until(() => w.eval('!!SHV.sh') && d.getElementById(`shv-c-${R[2]}-${CB}`)), 'computer: the table opens');
  if (!w.eval('isTouch()')) {
    const c2 = d.getElementById(`shv-c-${R[2]}-${CB}`);
    c2.dispatchEvent(new w.MouseEvent('pointerdown', {bubbles: true, cancelable: true, button: 0}));
    click(w, c2); await sleep(600);
    check(!((await cellOf(R[2], CB))?.raw) && w.eval(`SHV.cur && SHV.cur.r === ${R[2]}`), 'computer: a click beside the box only chooses the cell');
    click(w, c2.querySelector('[data-shkbox]'));
    check(await until(async () => (await cellOf(R[2], CB))?.raw === '1'), 'computer: a click on the box ticks it');
    check(await until(() => /Undo/.test(d.querySelector('#toast:not(.hidden)')?.textContent || '')), 'computer: the toast offers Undo');
  }
  w.close();

  // ---- #2189 agent chat: the refresh keeps the editor
  const AG = (await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'helper', display_name: 'Helper'})).id;
  const LST = (await call('POST', '/api/lists', {name: 'Garden'})).id;
  await call('PUT', `/api/lists/${LST}/agent`, {agent_id: AG});
  w = await boot({user: 'alice', hash: 'l/' + LST}); d = w.document;
  w.eval(`chatOpen(${AG})`);
  const cin = await until(() => d.querySelector('#chat-in'));
  check(!!cin, 'agent chat opens');
  cin.value = 'water the roses'; cin.dispatchEvent(new w.Event('input', {bubbles: true}));
  key(w, cin, 'Enter', {ctrlKey: true});
  const mm = await until(() => d.querySelector('#chat-msgs .cmsg.me[data-mid]'));
  check(mm && /water the roses/.test(mm.textContent), 'agent chat: the message is sent');
  const MID = +String(mm?.dataset.mid || '').split(':').pop();
  w.eval(`chatEditStart(${MID})`);
  const ae = await until(() => d.querySelector('#chat-msgs textarea.ach-edit'));
  check(!!ae, 'agent chat: the editor opens');
  await sleep(100);
  ae.focus(); ae.value = 'water the tulips'; ae.dispatchEvent(new w.Event('input', {bubbles: true}));  // autosize sets a style
  ae._mark = 1;
  await w.eval('chatLoad()');
  await sleep(4000);  // and the 3-second refresh once more
  await w.eval('chatLoad()');
  const ae2 = d.querySelector('#chat-msgs textarea.ach-edit');
  check(ae2 && ae2._mark === 1, 'agent chat: the refresh keeps the same editor');
  check(ae2 && ae2.value === 'water the tulips', 'agent chat: the typed text stays: ' + (ae2 && ae2.value));
  check(ae2 && d.activeElement === ae2, 'agent chat: the editor keeps the focus');
  click(w, d.querySelector('#chat-msgs [data-act="chat-ed-save"]'));
  check(await until(() => !d.querySelector('#chat-msgs textarea.ach-edit') && /water the tulips/.test(d.querySelector('#chat-msgs .cmsg.me')?.textContent || '')), 'agent chat: Save stores the new text');
  const hist = await call('GET', `/api/agents/${AG}/chat`);
  check(JSON.stringify(hist).includes('water the tulips'), 'agent chat: the server has the new text');
  // editing ends: the row is redrawn (no editor left behind)
  w.eval(`chatEditStart(${MID})`);
  check(await until(() => d.querySelector('#chat-msgs textarea.ach-edit')), 'agent chat: edit again');
  click(w, d.querySelector('#chat-msgs [data-act="chat-ed-cancel"]'));
  check(await until(() => !d.querySelector('#chat-msgs textarea.ach-edit')), 'agent chat: Cancel ends the editor');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
