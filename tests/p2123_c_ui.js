// 2.123.0 UI tests of part C (own container, start.sh). jsdom:
// - #2103 read mode: a picture of the file store shows (its address in the file store), a file the reader may not open is
//   "File not available" without its name; the editor's "Insert picture or file" offers upload and "From the file store…",
//   the dialog lists the folders / files of the page's space and inserts the reference at the cursor
// - #2107 [[datei:…]] / [[tabelle:…]]: a link for who may open it, plain text otherwise; typing [[datei: / [[tabelle:
//   suggests files / tables of the space, the pick writes [[datei:<id>|name]]
// - #2108 open checkbox lines: a + per line and "Open items as tasks"; the dialog creates the task with the quick add fields
//   (date, priority, tag) in the chosen list, the line ends with #<id>; ONE undo step removes the task and the #<id> again;
//   a done task is struck through at its link
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2123C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const upload = async (name, bytes, mime, form, ck = CK) => {
  const fd = new FormData(); for (const [k, v] of Object.entries(form)) fd.append(k, String(v));
  fd.append('file', new Blob([bytes], {type: mime}), name);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).items?.[0]?.id;
};
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==', 'base64');
const PDF = Buffer.from('%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj 3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 200 200]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki', 'files', 'sheets'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats}, CB);
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: st0.me.id})).id, SP = 'org:' + ORG;
  await call('PUT', `/api/orgs/${ORG}/members`, {email: 'bob@example.com', role: 'member'});
  const TEAM = (await call('POST', '/api/files/folders', {name: 'Team', space: SP})).id;
  await call('PATCH', '/api/files/nodes/' + TEAM, {org_access: 'view'});
  const PIC = await upload('plan.png', PNG, 'image/png', {parent_id: TEAM});
  const SEC = await upload('geheim-lohnliste.pdf', PDF, 'application/pdf', {space: SP});
  const SH = (await call('POST', '/api/sheets', {title: 'Budget', space: SP})).id;
  check(TEAM && PIC && SEC && SH, 'setup: folder, files, table');
  const OLD = (await call('POST', '/api/tasks', {title: 'Already a task'})).id;
  const BODY = `# Project\n\n![Plan](/api/files/nodes/${PIC}/content)\n\n![Pay](/api/files/nodes/${SEC}/content)\n\nSee [[datei:${SEC}|the list]] and [[tabelle:Budget]].\n\n- [ ] Offer to the client tomorrow !high #sales\n- [ ] Call the printer\n- [ ] Already done #${OLD}\n- [x] Closed\n`;
  const PG = (await call('POST', '/api/wiki/pages', {space: SP, path: 'Project', body: BODY})).id;
  const PG2 = (await call('POST', '/api/wiki/pages', {space: SP, path: 'Scratch', body: ''})).id;
  check(PG > 0 && PG2 > 0, 'setup: the pages');

  // ================= read mode as the admin
  let w = await boot({user: 'alice', hash: 'wiki/' + PG, ls: {'tasks.wkSpace': JSON.stringify(SP)}}), d = w.document;
  const img = await until(() => d.querySelector('#wk-md img.wkimg'));
  check(img && img.getAttribute('src') === `/api/files/nodes/${PIC}/content`, '#2103: the picture of the file store shows (its address there, no copy)');
  const tl = await until(() => [...d.querySelectorAll('#wk-md a.wemlink')].find(a => a.getAttribute('href') === '#sheets/' + SH));
  check(tl && tl.textContent.includes('Budget'), '#2107: [[tabelle:Budget]] links the table');
  check([...d.querySelectorAll('#wk-md a.wemlink')].some(a => a.textContent.includes('the list')), '#2107: the admin may open the closed file: a link');
  // checkbox lines
  const cbs = d.querySelectorAll('#wk-md li.cb .wemcb');
  check(cbs.length === 2, `#2108: a + on the two open lines without a task (${cbs.length})`);
  check(d.querySelector('#wk-md .wemcbbar [data-wem="cbs"]')?.textContent.includes('2'), '#2108: "Open items as tasks" with the number');
  cbs[0]?.click();
  const md = await until(() => d.querySelector('.modal.wemdlg #wem-list'));
  check(md && md.value === String(w.eval('inbox().id')), '#2108: the dialog offers the lists, the basket first');
  d.querySelector('.modal.wemdlg [data-m="ok"]')?.click();
  const pg1 = await until(async () => { const p = await call('GET', '/api/wiki/pages/' + PG); return /tomorrow !high #sales #\d+/.test(p.body) && p; });
  const tid = +(/#sales #(\d+)/.exec(pg1?.body || '') || [])[1];
  const t = tid ? await call('GET', '/api/tasks/' + tid) : {};
  const tom = w.eval('addDays(today(), 1)');
  check(tid && t.title === 'Offer to the client' && t.due === tom && t.priority === 5 && (t.tags || []).includes('sales'),
    '#2108: the task with the quick add fields: ' + JSON.stringify({title: t.title, due: t.due, prio: t.priority, tags: t.tags}));
  check(t.list_id === w.eval('inbox().id'), '#2108: in the chosen list (basket)');
  check(await until(() => d.querySelector(`#wk-md a.tref[data-tref="${tid}"]`)), '#2108: the line links the task now');
  check(d.querySelectorAll('#wk-md li.cb .wemcb').length === 1, '#2108: one + less');
  // ONE undo step: the task and the #<id> go again
  await w.eval(`histStep('undo')`); await sleep(400);
  const pg2 = await until(async () => { const p = await call('GET', '/api/wiki/pages/' + PG); return !/#sales #\d+/.test(p.body) && p; });
  check(pg2 && pg2.body === BODY, '#2108: undo restores the line');
  const t2 = await call('GET', '/api/tasks/' + tid);
  check(t2.status === 404 || !!t2.deleted_at, '#2108: undo removes the task (' + t2.status + ')');
  // a done task is struck through at its link
  await call('POST', `/api/tasks/${OLD}/complete`, {});
  w.close();
  w = await boot({user: 'alice', hash: 'wiki/' + PG, ls: {'tasks.wkSpace': JSON.stringify(SP)}}); d = w.document;
  const done = await until(() => d.querySelector(`#wk-md a.tref[data-tref="${OLD}"]`));
  check(done && done.classList.contains('wemdone'), '#2108: a done task shows struck through at its link ' + (done?.outerHTML || 'no link') + ' ' + JSON.stringify(w.eval(`(() => { const t = taskById(${OLD}); return t ? {s: t.status} : null; })()`)));

  // ================= the editor (another page): insert from the file store, suggestions
  w.location.hash = 'wiki/' + PG2;
  await until(() => d.querySelector('#view [data-wk="mode"][data-m="edit"]') && w.eval('WK.pg?.id') === PG2);
  d.querySelector('#view [data-wk="mode"][data-m="edit"]')?.click();
  const ta = await until(() => d.querySelector('#wk-body'));
  check(d.querySelector('.wkedwrap .wembar [data-wem="ins"]'), '#2103: the editor has "Insert picture or file"');
  ta.value = 'Start\n'; ta.setSelectionRange(6, 6); ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  d.querySelector('.wembar [data-wem="ins"]').click();
  const items = await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent.trim()).filter(Boolean).length && [...d.querySelectorAll('#pop [role="menuitem"]')]);
  check(items && ['Upload from this device', 'From the file store'].every(s => items.some(x => x.textContent.includes(s))), '#2103: the menu offers upload and the file store ' + (items || []).map(x => x.textContent.trim()));
  items && items.find(x => x.textContent.includes('From the file store'))?.click();
  const team = await until(() => [...d.querySelectorAll('.modal.wemdlg .wemit')].find(b => b.textContent.includes('Team')));
  check(team && team.dataset.k === 'folder', '#2103: the dialog shows the folders of the space');
  team?.click();
  const pic = await until(() => [...d.querySelectorAll('.modal.wemdlg .wemit')].find(b => b.textContent.includes('plan.png')));
  check(pic, '#2103: inside the folder: the picture');
  pic?.click();
  await sleep(200);
  check(ta.isConnected && ta.value === `Start\n![plan.png](/api/files/nodes/${PIC}/content)\n`, '#2103: the reference is inserted at the cursor: ' + JSON.stringify(ta.value));
  check(!d.querySelector('.modal.wemdlg'), '#2103: the dialog closes');
  // [[datei: and [[tabelle: suggestions
  ta.value += 'File [[datei:plan'; ta.setSelectionRange(ta.value.length, ta.value.length); ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  const ac = await until(() => { const b = d.querySelector('#wk-ac'); return b && !b.classList.contains('hidden') && b.textContent.includes('plan.png') && b; });
  check(ac, '#2107: [[datei: suggests files of the space');
  key(w, ta, 'Enter');
  check(ta.value.endsWith(`File [[datei:${PIC}|plan.png]]`), '#2107: the pick writes [[datei:<id>|name]] ' + JSON.stringify(ta.value.slice(-40)));
  ta.value += ' [[tabelle:bud'; ta.setSelectionRange(ta.value.length, ta.value.length); ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  const ac2 = await until(() => { const b = d.querySelector('#wk-ac'); return b && !b.classList.contains('hidden') && b.textContent.includes('Budget') && b; });
  check(ac2, '#2107: [[tabelle: suggests the tables of the space');
  key(w, ta, 'Enter');
  check(ta.value.endsWith(`[[tabelle:${SH}|Budget]]`), '#2107: the pick writes [[tabelle:<id>|title]]');
  await w.eval('wk_flush()');
  w.close();

  // ================= a member without access to the closed file
  w = await boot({user: 'bob', hash: 'wiki/' + PG, ls: {'tasks.wkSpace': JSON.stringify(SP)}}); d = w.document;
  await until(() => d.querySelector('#wk-md img.wkimg'));
  const na = await until(() => [...d.querySelectorAll('#wk-md .wemna')].find(x => /not available/.test(x.textContent)));
  check(na, '#2103: a file the member may not open: "File not available"');
  const mdText = d.querySelector('#wk-md')?.innerHTML || '';
  check(!/geheim|lohnliste/i.test(mdText), '#2103: no name of the closed file');
  check([...d.querySelectorAll('#wk-md .wemref')].some(x => x.textContent === 'the list') && ![...d.querySelectorAll('#wk-md a')].some(a => a.textContent === 'the list'),
    '#2107: a link to a file one may not open stays plain text');
  check(d.querySelector('#wk-md img.wkimg')?.getAttribute('src') === `/api/files/nodes/${PIC}/content`, '#2103: the open picture shows for the member');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
