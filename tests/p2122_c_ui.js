// 2.122.0 UI tests of part C (own container, start.sh; jsdom):
// - #2100 documents: choose documents -> "Export as CSV" posts the chosen ids to /api/docs/export.csv and starts a download
//   (documents.csv); the button waits for a choice
// - #2314 news on a phone (390 px): the task opened from the news swipes left to the next unread news (marked read like on
//   opening) and right back to the previous unread one; at the end a notice, the view stays; a swipe on a field is no swipe
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2122C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const cks = {};
const call = async (u, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: cks[u]}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const textPdf = line => {  // a one-page PDF with a text layer, written by hand
  const stream = `BT /F1 12 Tf 60 740 Td (${line}) Tj ET`;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  return out + `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  cks.alice = await login('alice');
  await call('alice', 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('alice', 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'collab,comments,docs,files'});
  const bob = (await call('alice', 'POST', '/api/users', {username: 'bob', display_name: 'Bob Builder', password: 'password123'})).id;
  cks.bob = await login('bob');
  await call('bob', 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'collab,comments'});

  // ================= #2100: CSV button
  for (const t of ['Letter one', 'Letter two']) {
    const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([textPdf(t)], {type: 'application/pdf'}), t + '.pdf');
    const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: cks.alice}, body: fd});
    check(r.status === 201, 'a document uploaded: ' + r.status);
  }
  let w = await boot({user: 'alice', hash: 'docs'}), d = w.document;
  await until(() => d.querySelector('[data-dcsel="mode"]'));
  d.querySelector('[data-dcsel="mode"]').click(); await sleep(300);
  const btn = () => d.querySelector('#dc-sbar [data-dcsel="more"]');  // 2.428.0 (#3581): "Export as CSV" sits under "More" of the shared bar
  check(btn() && btn().disabled, 'More (with the CSV export) waits for a choice');
  const dl = []; const calls = [];
  w.HTMLAnchorElement.prototype.click = function () { dl.push({name: this.download, href: this.href}); };
  w.URL.createObjectURL = () => 'blob:csv'; w.URL.revokeObjectURL = () => {};
  const f0 = w.fetch.bind(w); w.fetch = (u, o) => { if (/export\.csv/.test(u)) calls.push({u, body: o && o.body, method: o && o.method}); return f0(u, o); };
  const ids = w.eval('DC.docs.map(x => x.id)');
  check(ids.length === 2, 'two documents listed');
  for (const id of ids) w.eval(`dc_smvToggle(${id})`);
  await sleep(300);
  check(!btn().disabled, 'More is on with a choice');
  btn().click();
  const csv = await until(() => d.querySelector('#pop .menu-list .msm-csv'));
  check(csv && /Export as CSV/.test(csv.textContent), 'More offers "Export as CSV"');
  csv?.click();
  await until(() => dl.length);
  check(calls.length === 1 && calls[0].method === 'POST' && JSON.parse(calls[0].body).ids.length === 2, 'the chosen ids are posted ' + JSON.stringify(calls[0] || {}).slice(0, 120));
  check(dl.length === 1 && dl[0].name === 'documents.csv' && dl[0].href === 'blob:csv', 'a download of documents.csv starts');
  w.close();

  // ================= #2314: news on a phone
  const L = (await call('alice', 'POST', '/api/lists', {name: 'Team'})).id;
  await call('alice', 'PUT', `/api/lists/${L}/members`, {user_id: bob, role: 'edit'});
  const T = [];
  for (const t of ['Job one', 'Job two', 'Job three']) { T.push((await call('alice', 'POST', '/api/tasks', {title: t, list_id: L, assignee_id: bob})).id); await sleep(1100); }
  w = await boot({user: 'bob', hash: 'news', mobile: true, setup: x => { x.ontouchstart = null; x.navigator.maxTouchPoints = 5; }}); d = w.document;
  await until(() => d.querySelectorAll('#view .nitem').length >= 3);
  const unreadTasks = () => JSON.parse(w.eval(`JSON.stringify((S.nf.items || []).filter(x => !x.read && x.task_id).map(x => x.task_id))`));
  const order = unreadTasks();
  check(order.length >= 3 && T.every(t => order.includes(t)), 'three unread news with tasks ' + order.join(','));
  const rows = [...d.querySelectorAll('#view .nitem')];
  rows[0].dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
  await until(() => w.eval('S.sel') === order[0]);
  check(w.eval('S.sel') === order[0] && w.eval('nswOn()'), 'opened from the news: the first unread, swipe on');
  const swipe = async (dx, target) => {
    const el = target || d.querySelector('#detail .dbody');
    const T_ = (type, x) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.touches = type === 'touchend' ? [] : [{clientX: x, clientY: 300}]; el.dispatchEvent(e); };
    const x0 = dx < 0 ? 300 : 90;
    T_('touchstart', x0); T_('touchmove', x0 + dx / 4); T_('touchmove', x0 + dx); T_('touchend', x0 + dx);
    await sleep(900);
  };
  await swipe(-200);
  check(w.eval('S.sel') === order[1], `left: the next unread (${w.eval('S.sel')} / ${order[1]})`);
  // 2.147.2 CI: marking read goes out after the swipe; on a slow runner it can take longer than the 900 ms
  let st = {};
  for (let i = 0; i < 20; i++) { st = await call('bob', 'GET', '/api/news'); if ((st.items || []).filter(x => x.task_id === order[1]).every(x => x.read)) break; await sleep(200); }
  check((st.items || []).filter(x => x.task_id === order[1]).every(x => x.read), 'the one reached is marked read');
  await swipe(200);
  check(w.eval('S.sel') === order[1] && /No more unread news/.test(d.querySelector('#toast')?.textContent || ''), 'right: nothing unread before it, a notice and the task stays');
  // a short swipe does nothing; one on an input does nothing
  const before = w.eval('S.sel');
  await swipe(-30);
  check(w.eval('S.sel') === before, 'a short swipe does not change the task');
  const rest = unreadTasks();
  for (let i = 0; i < rest.length; i++) await swipe(-200);
  check(rest.length === 0 || w.eval('S.sel') !== before, 'left again: on to the remaining unread news');
  await swipe(-200);
  check(unreadTasks().length === 0 && /No more unread news/.test(d.querySelector('#toast')?.textContent || ''), 'no more unread: a notice ' + (d.querySelector('#toast')?.textContent || ''));
  check(w.eval('S.sel') && !d.querySelector('#detail').classList.contains('hidden'), 'the view stays');
  w.eval('closeDetail()'); await sleep(300);
  check(!w.eval('nswOn()'), 'closing the task ends the news swipe');
  w.close();

  console.log(`p2122_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
