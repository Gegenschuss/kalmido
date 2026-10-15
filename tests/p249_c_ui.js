// 2.49.0 UI tests of part C (#1199 knowledge pages, #1201 mind map; own container, start.sh). jsdom:
// - the module "Knowledge pages" (feature wiki): sidebar row, the view with the tree and "New page"
// - a new page opens in the editor; [[ suggests the pages of the space, the pick writes the link; saved automatically
// - read mode: [[link]] -> a link to the page, the other page lists the backlink; a ```mindmap block is drawn
// - Undo of "New page" moves it to the trash
// - the list view "Mind map": Tab = sub-branch, Enter = branch next to it, Shift+Tab = up a level, Space = fold, Del = delete
//   (+ Undo), each branch a task on the server; view-only lists show no editing buttons
// - phone width: the map has its stage and a wrapping tool bar, an open page hides the tree
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P249C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const st0 = await call('GET', '/api/state');
  const feats = (st0.settings.features || '').split(',').filter(Boolean);
  await call('PATCH', '/api/settings', {features: [...feats, 'wiki', 'kanban', 'timeline'].join(',')});
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: 1})).id;
  const SP = 'org:' + ORG;
  const OTHER = (await call('POST', '/api/wiki/pages', {space: SP, path: 'Docs/Other', body: 'The other page'})).id;
  check(OTHER > 0, 'setup: a page in the organisation');

  // ================= the view
  let w = await boot({user: 'alice', hash: 'wiki', ls: {'tasks.wkSpace': JSON.stringify(SP)}}), d = w.document;
  await until(() => d.querySelector('#view [data-wk="new"]'));
  check(d.querySelector('#view [data-wk="new"]'), 'the view: "New page"');
  check(d.querySelector('#side [data-go="wiki"]') || d.querySelector('[data-go="wiki"]'), 'the sidebar row of the module');
  check(await until(() => [...d.querySelectorAll('#view .wkitem')].some(a => a.textContent.includes('Other'))), 'the tree shows Docs/Other');
  check([...d.querySelectorAll('#view .wkdir')].some(x => x.textContent.includes('Docs')), 'a folder from the path');

  // ================= new page -> editor, [[ suggestions, autosave
  w.prompt = () => 'Docs/Start';
  d.querySelector('#view [data-wk="new"]').click();
  const ta = await until(() => d.querySelector('#wk-body'));
  check(ta && /^#wiki\/\d+$/.test(w.location.hash), 'the new page opens in the editor ' + w.location.hash);
  const START = +(w.location.hash.split('/')[1] || 0);
  if (ta) {
    ta.focus(); ta.value = 'See [[Oth'; ta.setSelectionRange(ta.value.length, ta.value.length);
    ta.dispatchEvent(new w.Event('input', {bubbles: true}));
    const ac = await until(() => { const b = d.querySelector('#wk-ac'); return b && !b.classList.contains('hidden') && b; });
    check(ac && ac.textContent.includes('Docs/Other'), '[[ suggests the pages of the space');
    key(w, ta, 'Enter');
    check(ta.value === 'See [[Docs/Other]]', 'the pick writes the link: ' + ta.value);
    ta.value += '\n\n```mindmap\n- Root\n  - A\n  - B\n```\n'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
    await w.eval('wk_flush()');
    const pg = await call('GET', '/api/wiki/pages/' + START);
    check(pg.body && pg.body.startsWith('See [[Docs/Other]]'), 'saved on the server: ' + JSON.stringify(pg.body));
  }
  // read mode: the link, the mind map block
  d.querySelector('#view [data-wk="mode"][data-m="read"]')?.click();
  await sleep(300);
  const lk = await until(() => d.querySelector('#wk-md a.wklink'));
  check(lk && lk.getAttribute('href') === '#wiki/' + OTHER, '[[link]] becomes a link to the page');
  check(d.querySelectorAll('#wk-md .mmblock svg [data-mmn]').length === 3, 'the ```mindmap block is drawn (3 branches)');
  const rh = w.eval(`wk_render({space: '${SP}', body: 'A \\x60[[Docs/Other]]\\x60 and [x](https://example.com/[[Docs/Other]]) and [[Docs/Other|<b>bold</b>]]'})`);
  const rd = d.createElement('div'); rd.innerHTML = rh;
  check(!rd.querySelector('code a') && rd.querySelector('code')?.textContent === '[[Docs/Other]]' && !rd.querySelector('b') && [...rd.querySelectorAll('a')].every(x => !x.querySelector('a') && !/wiki/.test(x.getAttribute('href')) === !x.classList.contains('wklink')), '[[links]] only in text (not in code, not inside a link), labels stay text: ' + rh);
  w.location.hash = 'wiki/' + OTHER;
  const bl = await until(() => d.querySelector('#view .wkback a'));
  check(bl && bl.getAttribute('href') === '#wiki/' + START, 'Docs/Other lists the backlink from Docs/Start');
  // Undo of "New page"
  const back0 = await call('GET', '/api/wiki/pages/' + START);
  check(back0.status === 200, 'page exists before undo');
  await w.eval(`(async () => { while (HIST.undo.length && !/Docs\\/Start|Start/.test(HIST.undo[HIST.undo.length - 1].label)) HIST.undo.pop(); await histStep('undo'); })()`);
  await sleep(300);
  check((await call('GET', '/api/wiki/pages/' + START)).status === 404, 'Undo of "New page": the page is in the trash');
  w.close();

  // ================= mind map view of a list
  const L = (await call('POST', '/api/lists', {name: 'Brainstorm'})).id;
  await call('PATCH', '/api/lists/' + L, {view: 'mindmap'});
  const T1 = (await call('POST', '/api/tasks', {title: 'First idea', list_id: L})).id;
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  const stage = await until(() => d.querySelector('#view .mmstage'));
  check(stage, 'the list opens as a mind map');
  check(d.querySelector('#view [data-mmn="r"]') && d.querySelector(`#view [data-mmn="t${T1}"]`), 'root = list, a branch per task');
  check([...d.querySelectorAll('[data-act="view-mindmap"]')].length > 0, 'the view switch offers "Mind map"');
  const tasks = async () => (await call('GET', '/api/state')).tasks.filter(t => t.list_id === L);
  // Tab on a task: sub-branch
  w.eval(`mm_select('t${T1}')`);
  key(w, d.querySelector('#view .mmstage'), 'Tab');
  let ed = await until(() => d.querySelector('#mm-edit'));
  check(ed, 'Tab opens the editor for a sub-branch');
  if (ed) { ed.value = 'Sub idea'; key(w, ed, 'Enter'); }
  let sub = await until(async () => (await tasks()).find(t => t.title === 'Sub idea'));
  check(sub && sub.parent_id === T1, 'Tab + Enter: a subtask of the selected task');
  // Enter: a branch next to it
  await until(() => d.querySelector(`#view [data-mmn="t${sub?.id}"]`));
  w.eval(`mm_select('t${T1}')`);
  key(w, d.querySelector('#view .mmstage'), 'Enter');
  ed = await until(() => d.querySelector('#mm-edit'));
  if (ed) { ed.value = 'Second idea'; key(w, ed, 'Enter'); }
  const sec = await until(async () => (await tasks()).find(t => t.title === 'Second idea'));
  check(sec && !sec.parent_id, 'Enter: a task next to it (same level)');
  // Shift+Tab: up a level
  await until(() => d.querySelector(`#view [data-mmn="t${sub?.id}"]`));
  w.eval(`mm_select('t${sub?.id}')`);
  key(w, d.querySelector('#view .mmstage'), 'Tab', {shiftKey: true});
  check(await until(async () => { const x = (await tasks()).find(t => t.id === sub?.id); return x && !x.parent_id; }), 'Shift+Tab: the subtask moves up a level');
  // fold with Space
  await call('PATCH', '/api/tasks/' + sub.id, {parent_id: T1}); await w.eval('load().then(render)'); await sleep(300);
  w.eval(`mm_select('t${T1}')`);
  key(w, d.querySelector('#view .mmstage'), ' ');
  await sleep(200);
  check(!d.querySelector(`#view [data-mmn="t${sub.id}"]`) && d.querySelector(`#view [data-mmn="t${T1}"] .mmfold`), 'Space folds a branch (count shown)');
  key(w, d.querySelector('#view .mmstage'), ' ');
  await sleep(200);
  check(d.querySelector(`#view [data-mmn="t${sub.id}"]`), 'Space unfolds it again');
  // Delete + Undo
  w.eval(`mm_select('t${sec.id}')`);
  key(w, d.querySelector('#view .mmstage'), 'Delete');
  check(await until(async () => !(await tasks()).some(t => t.id === sec.id)), 'Del deletes the branch (task)');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await tasks()).some(t => t.id === sec.id)), 'Undo brings it back');
  // the task names the pages that mention it; the command field finds pages
  await call('POST', '/api/wiki/pages', {space: SP, path: 'Docs/Mentions', body: `About #${T1}`});
  w.eval(`WK.men = {}; openDetail(${T1})`);
  const men = await until(() => d.querySelector('#detail .wkmen a.wklink'));
  check(men && men.textContent === 'Docs/Mentions', 'the task shows "Mentioned in" the page');
  w.eval(`closeDetail()`);
  await w.eval(`(async () => { for (const sp of wk_spaces()) await wk_load(sp, true); })()`);
  const pal = w.eval(`(() => { const out = []; wk_palAdd((id, k, label) => out.push(id + ':' + label)); return out.join('|'); })()`);
  check(/wk:\d+:Other/.test(pal) && /wk:\d+:Mentions/.test(pal), 'the command field lists the pages: ' + pal);
  // outline
  d.querySelector('#view [data-mm="as-outline"]').click();
  await sleep(200);
  check(d.querySelectorAll('#view .mmoutline .mmoi').length >= 4, 'the outline shows the same tree');
  d.querySelector('#view [data-mm="as-map"]').click();
  await sleep(200);
  check(w.eval('mm_md(MM.last.tree)').includes('- First idea\n  - Sub idea'), 'export: Markdown outline');
  check(/^<svg[\s\S]*<\/svg>$/.test(w.eval('mm_exportSvg()')), 'export: a standalone SVG');
  w.close();

  // ================= phone width
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true}); d = w.document;
  check(await until(() => d.querySelector('#view .mmstage')), 'phone: the map');
  check(d.querySelector('#view .mmbar') && !d.querySelector('#view .mmbar .btn span:not(.sr)')?.offsetWidth, 'phone: compact tool bar');
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(/\.mmstage\{[^}]*touch-action:none/.test(css) && /\.mmbar\{[^}]*flex-wrap:wrap/.test(css), 'CSS: the stage takes the fingers, the bar wraps');
  w.location.hash = 'wiki/' + OTHER;
  await until(() => d.querySelector('#view .wkpage h2'));
  check(d.querySelector('#view .wkpage') && !d.querySelector('#view .wkside') && d.querySelector('#view [data-wk="close"]'), 'phone: an open page hides the tree, Back is there');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
