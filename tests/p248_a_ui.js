// 2.48.0 UI tests of part A (#1207, own container, start.sh; P248A_NOSTART=1: the container runs already). jsdom:
// - the area "File store" (sidebar row, route #ablage), the spaces My files / Shared with me / Trash
// - New folder (dialog), upload into the folder (FormData), the row with size and version, same name = version 2
// - the Share dialog: a person with a role, the agent; the share badge in the row
// - delete = trash with ONE undo step (Undo brings it back), the trash lists it, restore
// - phone width: the spaces as a row of buttons, the row actions in the menu sheet
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const firefox = require('./ff')({tag: 'p248_a_ui', check: (c, w) => check(c, w), shots: 'P248A_SHOTS'});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P248A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Example', password: 'password123'})).id;
  const AG = (await call('POST', '/api/admin/agents', {username: 'helperbot', display_name: 'Helper bot'})).id;
  const st = await call('GET', '/api/state');
  check((st.settings?.features || '').split(',').includes('files'), 'the module "files" is on by default ' + st.settings?.features);

  const w = await boot({user: 'alice', hash: 'ablage'}), d = w.document;
  await until(() => d.querySelector('#view .abview'));
  check(d.querySelector('#view .abview'), 'route #ablage shows the file store');
  check([...d.querySelectorAll('.abspace')].map(b => b.textContent.trim()).join('|').includes('My files'), 'the spaces: My files …');
  check(d.querySelector('.abspace[data-sp="shared"]') && d.querySelector('.abspace[data-sp="trash"]'), '… Shared with me and Trash');
  check(d.querySelector('[data-mgside="ablage"]'), 'the sidebar has the area row');
  check(await until(() => /Drop files here/.test(d.querySelector('.abempty')?.textContent || '')), 'empty: the hint to drop files');

  // ================= new folder
  w.prompt = () => 'Invoices';
  d.querySelector('[data-ab="new-folder"]').click();
  const row = await until(() => [...d.querySelectorAll('.abrow')].find(r => /Invoices/.test(r.textContent)));
  check(row, 'New folder: the row appears');
  check(w.eval(`HIST.undo.length && /Invoices/.test(HIST.undo[HIST.undo.length - 1].label)`), 'New folder = one undo step');
  const FID = +row.dataset.abid;
  row.querySelector('[data-ab="open"]').click();
  await until(() => w.location.hash === '#ablage/' + FID && d.querySelector('.abcrumbs'));
  check(/Invoices/.test(d.querySelector('.abcrumbs')?.textContent || ''), 'opening the folder: the path shows it');
  check(/Invoices/.test(d.querySelector('.abtree.on')?.textContent || ''), 'the tree on the left marks the open folder below its space');

  // ================= upload (twice the same name = a new version)
  await w.eval(`ab_upload([new File(['first'], 'note.txt', {type: 'text/plain'})], ${FID})`);
  const fr = await until(() => [...d.querySelectorAll('.abrow')].find(r => /note\.txt/.test(r.textContent)));
  check(fr && /5 B/.test(fr.textContent), 'upload: the file with its size ' + (fr?.textContent || ''));
  await w.eval(`ab_upload([new File(['second!'], 'note.txt', {type: 'text/plain'})], ${FID})`);
  await until(() => d.querySelector('.abrow .abver'));
  check(/v2/.test(d.querySelector('.abrow .abver')?.textContent || ''), 'same name again: version 2 in the row');
  check(d.querySelectorAll('.abrow').length === 1, 'still one row');
  const NID = +d.querySelector('.abrow').dataset.abid;
  const vers = await call('GET', `/api/files/nodes/${NID}`);
  check((vers.versions || []).length === 2, 'the server keeps both versions');

  // ================= details: versions and the history
  await w.eval(`ab_details(${NID})`);
  await until(() => d.querySelector('.abdlg'));
  check(d.querySelectorAll('.abdlg .abvrow').length === 2 && d.querySelector('.abdlg [data-abv="1"]'), 'details: two versions, the old one restorable');
  d.querySelector('.abdlg [data-m="close"]').click();

  // ================= Share dialog
  await w.eval(`ab_share(${FID})`);
  const md = await until(() => d.querySelector('.abshdlg'));
  const opts = [...md.querySelectorAll('#ab-sht option')].map(o => o.value);
  check(opts.includes('user_id:' + BOB) && opts.includes('agent_id:' + AG), 'share targets: bob and the agent ' + opts.join(','));
  md.querySelector('#ab-sht').value = 'agent_id:' + AG;
  md.querySelector('#ab-shr').value = 'edit';
  md.querySelector('[data-abs="add"]').click();
  await until(() => md.querySelector('#ab-shl .mrow[data-sid]'));
  check(/Helper bot/.test(md.querySelector('#ab-shl').textContent) && md.querySelector('#ab-shl [data-absr]').value === 'edit', 'the agent is in the list with "Can edit"');
  check(w.eval(`/Share/.test(HIST.undo[HIST.undo.length - 1].label)`), 'sharing = one undo step');
  md.querySelector('[data-m="close"]').click();
  w.eval(`go('ablage')`);
  await until(() => d.querySelector(`.abrow[data-abid="${FID}"] .abbadge`));
  check(d.querySelector(`.abrow[data-abid="${FID}"] .abbadge`), 'the folder row shows the share symbol');

  // ================= delete -> trash -> undo
  const fnode = (await call('GET', `/api/files/nodes/${FID}`));
  await w.eval(`ab_delete(${JSON.stringify({id: FID, name: 'Invoices', parent_id: null, role: 'owner'})})`);
  await until(() => !d.querySelector(`.abrow[data-abid="${FID}"]`));
  check(!d.querySelector(`.abrow[data-abid="${FID}"]`), 'delete: the folder leaves the list');
  check(/trash/.test(d.querySelector('#toast')?.textContent || ''), 'the toast says it is in the trash ' + (d.querySelector('#toast')?.textContent || ''));
  d.querySelector('.abspace[data-sp="trash"]').click();
  await until(() => d.querySelector(`.abrow[data-abid="${FID}"] [data-ab="restore"]`));
  check(d.querySelector(`.abrow[data-abid="${FID}"] [data-ab="restore"]`), 'the trash lists it with Restore');
  await w.eval(`histStep('undo')`);
  await sleep(400);
  const back = await call('GET', `/api/files/nodes/${FID}`);
  check(back.status === 200 && !back.in_trash && fnode.name === back.name, 'Undo brings the folder back');
  d.querySelector('.abspace[data-sp="private"]').click();
  await until(() => d.querySelector(`.abrow[data-abid="${FID}"]`));
  check(d.querySelector(`.abrow[data-abid="${FID}"]`), 'back in My files');
  // ================= "Show in the file store" on a task file: a link, no copy
  const inbox = (st.lists || []).find(l => l.is_inbox)?.id;
  const TID = (await call('POST', '/api/tasks', {title: 'With a file', list_id: inbox})).id;
  const fd = new FormData(); fd.append('file', new Blob(['task file']), 'brief.txt');
  await fetch(B + `api/tasks/${TID}/attachments`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  await w.eval(`refreshNow()`);
  await sleep(600);
  w.eval(`openDetail(${TID})`);
  const lb = await until(() => d.querySelector('#detail .att [data-ablink], .att [data-ablink]'));
  check(lb && /^att:\d+:$/.test(lb.dataset.ablink), 'a task file has "Show in the file store" ' + (lb?.dataset.ablink || ''));
  if (lb) {
    lb.click();
    await sleep(700);
    const top = await call('GET', '/api/files?space=private');
    const link = (top.items || []).find(x => x.kind === 'link' && x.name === 'brief.txt');
    check(link, 'the link is at the top of My files');
    check(w.eval(`/brief\.txt/.test(HIST.undo[HIST.undo.length - 1].label)`), 'one undo step');
  }
  w.close();

  // ================= phone width
  const m = await boot({user: 'alice', hash: 'ablage', mobile: true}), md2 = m.document;
  await until(() => md2.querySelector('#view .abview'));
  check(md2.querySelector('.abspaces'), 'phone: the spaces as a row on top');
  const mb = await until(() => md2.querySelector(`.abrow[data-abid="${FID}"] [data-ab="menu"]`));
  check(mb, 'phone: the row has the actions button');
  if (mb) {
    mb.click();
    await until(() => md2.querySelector('#pop [role="menuitem"]'));
    const labels = [...md2.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
    check(labels.some(t => /Share/.test(t)) && labels.some(t => /Rename/.test(t)) && labels.some(t => /trash/.test(t)), 'phone: the sheet offers Share, Rename, Move to the trash ' + labels.join('|'));
    check(md2.querySelector('#pop .tch-sh'), 'phone: the menu is a sheet with a head');
  }
  m.close();

  // ================= the real layout (Firefox): phone 390 px dark, desktop 1440 px light
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(700); };
  for (const [vw, vh, touch, th] of [[390, 844, true, 'dark'], [1440, 900, false, 'light']]) await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o, tag = String(vw);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.setItem('tasks.theme', '"${th}"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    await nav(B + '#ablage/' + FID); await ready(ev);
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('.abrow')`)); i++) await sleep(300);
    const L = await ev(`(() => { const rows = [...document.querySelectorAll('.abrow')].map(x => x.getBoundingClientRect()), sp = [...document.querySelectorAll('.abspace:not(.abtree)')].map(x => x.getBoundingClientRect());
      const btn = [...document.querySelectorAll('.abrow [data-ab="menu"]')].map(x => x.getBoundingClientRect());
      return {over: document.documentElement.scrollWidth - innerWidth, n: rows.length, minH: Math.round(Math.min(...rows.map(x => x.height))), out: rows.filter(x => x.right > innerWidth + 1).length,
        spH: Math.round(Math.min(...sp.map(x => x.height))), btnW: Math.round(Math.min(...btn.map(x => x.width))), tree: !!document.querySelector('.abtree.on') && getComputedStyle(document.querySelector('.abtree.on')).display !== 'none'}; })()`);
    check(L.n >= 1 && L.over <= 1 && L.out === 0, `${tag}: the list fits ` + JSON.stringify(L));
    if (touch) check(L.minH >= 44 && L.spH >= 44 && L.btnW >= 44, `${tag}: rows, spaces and the actions button at least 44 px ` + JSON.stringify(L));
    else check(L.tree, `${tag}: the tree on the left shows the open folder`);
    await shot(`p248a-${tag}-folder.png`);
    await ev(`(() => { ab_share(${FID}); return 1; })()`);
    for (let i = 0; i < 20 && !(await ev(`!!document.querySelector('.abshdlg')`)); i++) await sleep(300);
    await sleep(300);
    const M = await ev(`(() => { const m = document.querySelector('.abshdlg .card') || document.querySelector('.abshdlg'), r = m.getBoundingClientRect(); return {over: document.documentElement.scrollWidth - innerWidth, l: Math.round(r.left), r: Math.round(innerWidth - r.right)}; })()`);
    check(M.over <= 1 && M.l >= 0 && M.r >= 0, `${tag}: the Share dialog fits ` + JSON.stringify(M));
    await shot(`p248a-${tag}-share.png`);
  }, touch);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
