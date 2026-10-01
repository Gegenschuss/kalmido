// 2.4.0 UI tests, own container (start.sh): subfolders (#361), project types (#243), project templates with relative dates
// (#328), ticket types (#340), quick capture (#187).
// Sidebar tree (a folder's lists, then its subfolders, one level deeper; folding is stored per user: folders_closed), the
// folder view with a header per subfolder, a folder path in the hash, the command palette's folder entries, the folder menu
// (New subfolder…, Move to the top level), dropping a list onto a subfolder and a subfolder onto the "Lists" header, the list
// dialog's "Folder / Subfolder" field. The "New list" dialog with the type Project: Blank / Agency / Software / Personal +
// own templates, creating a Software project (kanban, ticket types, next steps dialog). A template with relative dates asks
// for the start and an end. Ticket chips in the rows, the type select in the task panel (template notes), quick add !bug,
// the filter's ticket types. Quick capture: q and Ctrl+Space open the box, it goes to the inbox whatever view is open,
// /capture?title&url prefills it, /capture alone shows the bookmarklet. German texts, SW v66. Then Firefox headless (WebDriver
// BiDi, skipped without firefox) at 390 x 844 and 1280 x 800: tree, new project dialog, template dialog, ticket chips,
// capture box fit (no horizontal overflow, inside the viewport).
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const WS = globalThis.WebSocket || require('ws');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el && el.dispatchEvent(new w.Event('change', {bubbles: true}));
const input = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const menuTexts = d => [...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent.trim());
const menuClick = (w, d, re) => click(w, [...d.querySelectorAll('#pop .menu-list button')].find(b => re.test(b.textContent)));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments';
const st = () => call('GET', '/api/state');

async function firefox(fn) {
  try { execFileSync('firefox', ['--version'], {stdio: 'ignore'}); } catch { console.log('p240_ui: Firefox part skipped (no firefox on PATH)'); return; }
  const PORT = 9300 + Math.floor(Math.random() * 600);
  const prof = fs.mkdtempSync(path.join(process.env.TMPDIR || os.tmpdir(), 'kalmido-p240-'));
  fs.writeFileSync(path.join(prof, 'user.js'), [['browser.shell.checkDefaultBrowser', false], ['datareporting.policy.dataSubmissionEnabled', false], ['ui.prefersReducedMotion', 1]]
    .map(([k, v]) => `user_pref("${k}", ${JSON.stringify(v)});`).join('\n') + '\n');
  const ff = spawn('firefox', ['--headless', '--no-remote', '--profile', prof, `--remote-debugging-port=${PORT}`, 'about:blank'], {stdio: 'ignore'});
  let ws, seq = 0; const pend = new Map();
  try {
    for (let i = 0; i < 90 && !ws; i++) {
      try { const w = new WS(`ws://127.0.0.1:${PORT}/session`); await new Promise((res, rej) => { w.onopen = res; w.onerror = rej; }); ws = w; } catch { await sleep(500); }
    }
    if (!ws) { check(false, 'no WebDriver BiDi connection to Firefox'); return; }
    ws.onmessage = m => { const j = JSON.parse(m.data); if (j.id && pend.has(j.id)) { const p = pend.get(j.id); pend.delete(j.id); j.type === 'error' ? p.rej(new Error(p.method + ': ' + j.error + ' ' + j.message)) : p.res(j.result); } };
    const cmd = (method, params = {}) => new Promise((res, rej) => { const id = ++seq; pend.set(id, {res, rej, method}); ws.send(JSON.stringify({id, method, params})); });
    const unwrap = v => !v ? v : v.type === 'array' ? v.value.map(unwrap) : v.type === 'object' ? Object.fromEntries(v.value.map(([k, x]) => [typeof k === 'string' ? k : unwrap(k), unwrap(x)])) : v.value;
    await cmd('session.new', {capabilities: {}});
    const ctx = (await cmd('browsingContext.getTree', {})).contexts[0].context;
    const ev = async expr => { const r = await cmd('script.evaluate', {expression: expr, target: {context: ctx}, awaitPromise: true, resultOwnership: 'none', serializationOptions: {maxObjectDepth: 5}}); if (r.type === 'exception') throw new Error('JS: ' + r.exceptionDetails.text); return unwrap(r.result); };
    const nav = url => cmd('browsingContext.navigate', {context: ctx, url, wait: 'complete'});
    const shot = async name => { const dir = process.env.P240_SHOTS; if (!dir) return; const r = await cmd('browsingContext.captureScreenshot', {context: ctx}); fs.writeFileSync(path.join(dir, name), Buffer.from(r.data, 'base64')); };
    await fn({cmd, ev, nav, ctx, shot});
  } catch (e) { check(false, 'Firefox: ' + e.message); } finally {
    try { ws && ws.close(); } catch { /* gone */ }
    try { ff.kill(); } catch { /* gone */ }
    await sleep(500); fs.rmSync(prof, {recursive: true, force: true});
  }
}

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(6[6-9]|7[0-3])'/.test(SW), 'service worker cache v66 (2.4.1: v67, 2.4.2: v68, 2.5.0: v69, 2.5.1: v70, 2.5.2: v71, 2.6.0: v72, 2.6.1: v73)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const L = async (name, folder = '', extra = {}) => (await call('POST', '/api/lists', {name, ...(folder ? {folder} : {}), ...extra})).id;
  const RET = await L('Retainer', 'Clients'), WEB = await L('Website', 'Clients/Company X'), SHOP = await L('Shop', 'Clients/Company Y'), HOME = await L('Garden');
  await call('PATCH', '/api/settings', {folders: JSON.stringify(['Clients', 'Clients/Company X', 'Clients/Company Y'])});
  await call('POST', '/api/tasks', {title: 'Monthly report', list_id: RET});
  await call('POST', '/api/tasks', {title: 'New landing page', list_id: WEB});
  const APP = await L('App', '', {kind: 'project', tickets: true});
  const BUG = (await call('POST', '/api/tasks', {title: 'Crash on start', list_id: APP, ttype: 'bug'})).id;
  const PLAIN = (await call('POST', '/api/tasks', {title: 'Write docs', list_id: APP})).id;

  // ================= sidebar tree
  let w = await boot({user: 'alice', hash: 'l/' + HOME}), d = w.document;
  const fh = f => d.querySelector(`#side .fhead[data-folder="${f}"]`);
  check(fh('Clients') && !fh('Clients').classList.contains('fsub'), 'top folder header');
  check(fh('Clients/Company X')?.classList.contains('fsub') && fh('Clients/Company X').closest('.fsubw')?.closest('.fbody[data-folder="Clients"]'), 'subfolder inside its folder');
  check(fh('Clients/Company X').querySelector('.n').textContent === 'Company X', 'subfolder shows its own name');
  const kids = [...d.querySelector('#side .fbody[data-folder="Clients"]').children];
  check(kids[0].matches('.srow[data-list="' + RET + '"]') && kids[1].matches('.fsubw'), "the folder's lists first, then its subfolders");
  check(d.querySelector(`#side .fbody[data-folder="Clients/Company X"] .srow[data-list="${WEB}"]`), 'list inside the subfolder');
  // fold a subfolder: stored per user
  click(w, fh('Clients/Company X'));
  check(fh('Clients/Company X').classList.contains('closed') && !d.querySelector(`#side .srow[data-list="${WEB}"]`), 'subfolder folded');
  check(await until(async () => JSON.parse((await st()).settings.folders_closed || '[]').includes('Clients/Company X')), 'folded state saved on the server');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + HOME, ls: {'tasks.collapsed': '[]'}}); d = w.document;
  check(fh('Clients/Company X')?.classList.contains('closed'), 'folded on another device too');
  click(w, fh('Clients/Company X'));
  check(await until(async () => !JSON.parse((await st()).settings.folders_closed || '[]').length), 'unfolded: saved');
  // folder view: lists incl. subfolders, a header per subfolder
  w.location.hash = 'folder/' + encodeURIComponent('Clients'); await sleep(500);
  check(/Monthly report/.test(d.querySelector('#view').textContent) && /New landing page/.test(d.querySelector('#view').textContent), 'folder view: lists of the subfolders too');
  check([...d.querySelectorAll('#view .fsubhd')].map(x => x.textContent.trim()).join('|') === 'Company X', 'folder view: a header per subfolder');
  w.location.hash = 'folder/' + encodeURIComponent('Clients/Company X'); await sleep(500);
  check(w.eval('S.route.key') === 'folder:Clients/Company X' && d.querySelector('#top h1').textContent.includes('Clients / Company X') && /New landing page/.test(d.querySelector('#view').textContent) && !/Monthly report/.test(d.querySelector('#view').textContent), 'subfolder path in the hash');
  // palette
  check(w.eval(`palAll().some(x => x.id === 'folder:Clients/Company X' && x.label === 'Clients / Company X')`), 'palette: folder entries with paths');
  check(w.eval(`palAll().find(x => x.id === 'l:${WEB}').sub === 'Clients / Company X'`), 'palette: the list shows its folder');
  // folder menu
  w.eval(`folderMenu(document.querySelector('#top h1'), 'Clients')`);
  check(menuTexts(d).includes('New subfolder…') && !menuTexts(d).includes('Move to the top level'), 'top folder menu: New subfolder…');
  w.eval('closePop()');
  w.eval(`folderMenu(document.querySelector('#top h1'), 'Clients/Company Y')`);
  check(menuTexts(d).includes('Move to the top level') && !menuTexts(d).includes('New subfolder…'), 'subfolder menu: Move to the top level');
  w.prompt = () => 'Company Z';
  menuClick(w, d, /^Rename$/);
  check(await until(async () => (await st()).lists.find(l => l.id === SHOP).folder === 'Clients/Company Z'), 'rename a subfolder keeps it in its folder');
  await w.eval('load().then(() => render())'); await sleep(200);
  // drops: a list onto a subfolder, a subfolder onto the "Lists" header
  await w.eval(`sideDrop({list: ${HOME}, folder: null}, document.querySelector('#side .fhead[data-folder="Clients/Company Z"]'))`);
  check(await until(async () => (await st()).lists.find(l => l.id === HOME).folder === 'Clients/Company Z'), 'list dropped into a subfolder');
  check(w.eval(`folderDropKind('Clients/Company Z', document.querySelector('#side .shead.lroot'))`) === 'top', 'subfolder onto Lists = top level');
  check(w.eval(`folderDropKind('Clients', document.querySelector('#side .fhead[data-folder="Clients/Company X"]'))`) === null, 'a folder with subfolders cannot become a subfolder');
  await w.eval(`sideDrop({list: null, folder: 'Clients/Company Z'}, document.querySelector('#side .shead.lroot'))`);
  check(await until(async () => (await st()).lists.find(l => l.id === SHOP).folder === 'Company Z'), 'subfolder dropped on Lists: top level');
  await w.eval('load().then(() => render())'); await sleep(200);
  check(w.eval(`folderDropKind('Company Z', document.querySelector('#side .fhead[data-folder="Clients"]'))`) === 'before', 'a top folder onto a top folder: reorder');
  w.eval(`folderMenu(document.querySelector('#top h1'), 'Company Z')`);
  check(menuTexts(d).includes('Move into a folder…'), 'a folder without subfolders: "Move into a folder…"');
  w.eval('closePop()');
  // list dialog: the folder field
  w.eval(`listModal(${WEB})`); await sleep(150);
  const fo = d.querySelector('.lmodal #l-folder');
  check(fo.value === 'Clients / Company X' && [...d.querySelectorAll('#l-folders option')].some(o => o.value === 'Clients / Company X'), 'folder field: path with " / "');
  input(w, fo, 'Clients / Company Q'); fo.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true}));
  check(await until(async () => (await st()).lists.find(l => l.id === WEB).folder === 'Clients/Company Q'), 'typed path saved');
  d.querySelector('.lmodal').remove();
  w.close();

  // ================= project types in the "New list" dialog
  await call('POST', '/api/templates', {list_id: APP, relative: true, name: 'App plan'});
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  w.eval(`listModal(null, '', {kind: 'project'})`); await sleep(300);
  let md = d.querySelector('.modal.lnew');
  check(md && !md.querySelector('.lptype').hidden && md.querySelector('#l-kind').value === 'project', 'New project: type Project, picker shown');
  const cards = [...md.querySelectorAll('.ptcard')].map(b => b.dataset.pt);
  check(cards.join(',').startsWith(',agency,software,private,tpl:'), 'Blank, Agency, Software, Personal, own template: ' + cards.join(','));
  check(await until(() => /Dates from the project start/.test(md.querySelector('[data-ptd]')?.textContent || '')), 'own template: says it is relative');
  md.querySelector('#l-kind').value = 'list'; change(w, md.querySelector('#l-kind'));
  check(md.querySelector('.lptype').hidden, 'type List: no picker');
  md.querySelector('#l-kind').value = 'project'; change(w, md.querySelector('#l-kind'));
  click(w, md.querySelector('.ptcard[data-pt="software"]'));
  check(md.querySelector('.ptcard.on')?.dataset.pt === 'software' && md.querySelector('#l-name').value === 'Software / AI dev' && md.querySelector('#l-view').value === 'kanban', 'software picked: name + kanban');
  md.querySelector('#l-name').value = 'Kalmido'; md.querySelector('#l-folder').value = 'Dev / Tools';
  click(w, md.querySelector('[data-m="save"]'));
  const SWL = await until(async () => (await st()).lists.find(l => l.name === 'Kalmido'));
  check(SWL && SWL.kind === 'project' && SWL.tickets === 1 && SWL.view === 'kanban' && SWL.folder === 'Dev/Tools', 'software project created');
  check(await until(() => d.querySelector('.modal.nsmodal')), 'next steps dialog');
  check(/Connect a repository/.test(d.querySelector('.nsmodal').textContent), 'next steps: repository');
  click(w, d.querySelector('.nsmodal [data-m="close"]'));
  // own template: start + end
  w.eval(`listModal(null, '', {kind: 'project'})`); await sleep(200);
  md = [...d.querySelectorAll('.modal.lnew')].pop();
  click(w, md.querySelector('.ptcard[data-pt^="tpl:"]'));
  check(!md.querySelector('.ptdates').hidden && md.querySelector('#l-name').value === 'App plan', 'own template: start / end fields');
  md.remove();
  const tpl = (await call('GET', '/api/templates')).templates.find(t => t.name === 'App plan');
  w.eval(`useTemplate({id: ${tpl.id}, kind: 'list', name: 'App plan'})`);
  md = await until(() => d.querySelector('.modal.tumodal'));
  check(md && md.querySelector('#tu-start')?.dataset.dp === 'date' && md.querySelector('#tu-name').value === 'App', 'template dialog asks for the start');
  md.querySelector('#tu-name').value = 'App 2'; md.querySelector('#tu-start').value = '2027-05-03';
  click(w, md.querySelector('[data-m="ok"]'));
  check(await until(async () => (await st()).lists.some(l => l.name === 'App 2' && l.tickets === 1)), 'created from the template');
  w.close();

  // ================= ticket types
  w = await boot({user: 'alice', hash: 'l/' + APP}); d = w.document;
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  check(row(BUG)?.querySelector('.ttchip.tt-bug')?.textContent === 'Bug', 'bug chip in the row');
  check(!row(PLAIN).querySelector('.ttchip'), 'no chip without a type');
  w.eval(`openDetail(${PLAIN})`); await sleep(300);
  const sel = d.querySelector('#d-ttype');
  check(sel && [...sel.options].map(o => o.value).join(',') === ',bug,feature,task', 'type select in the task panel');
  sel.value = 'feature'; change(w, sel);
  check(await until(async () => { const t = (await st()).tasks.find(x => x.id === PLAIN); return t.ttype === 'feature' && /Acceptance criteria/.test(t.content); }), 'type set, template notes');
  const pq = w.eval(`JSON.stringify(parseQuick('Login broken !bug tomorrow'))`);
  check(JSON.parse(pq).ttype === 'bug' && JSON.parse(pq).title === 'Login broken', 'quick add: !bug');
  check(JSON.parse(w.eval(`JSON.stringify(parseQuick('Neues Menü !funktion'))`)).ttype === 'feature', 'quick add: !funktion');
  w.eval(`filterModal()`); await sleep(150);
  check([...d.querySelectorAll('.fchips[data-key="types"] button')].length === 4, 'filter: ticket types');
  check(w.eval(`filterMatch(taskById(${BUG}), {types: ['bug']}) && !filterMatch(taskById(${BUG}), {types: ['feature']})`), 'filter matches the type');
  [...d.querySelectorAll('.modal')].forEach(x => x.remove());
  w.close();
  // a list without ticket types: no chips, !bug stays text there when no list has them
  await call('PATCH', `/api/lists/${APP}`, {tickets: false});
  w = await boot({user: 'alice', hash: 'l/' + APP}); d = w.document;
  check(!d.querySelector('#view .ttchip'), 'ticket types off: no chips');
  w.close();
  await call('PATCH', `/api/lists/${APP}`, {tickets: true});

  // ================= quick capture
  w = await boot({user: 'alice', hash: 'l/' + HOME}); d = w.document;
  key(w, d.body, 'q');
  let sh = await until(() => d.querySelector('.qadd.sheet.capture'));
  check(sh && d.querySelector('#qsheet').placeholder === 'Capture to the inbox…', 'q opens the capture box');
  const qs = d.querySelector('#qsheet');
  input(w, qs, 'Call mum tomorrow');
  click(w, sh.querySelector('[data-act="qsheet-send"]'));
  check(await until(async () => { const t = (await st()).tasks.find(x => x.title === 'Call mum'); return t && t.list_id === w.eval('inbox().id') && !!t.due; }), 'captured into the inbox (not the open list), date parsed');
  check(!d.querySelector('.qadd.sheet'), 'the box closes after saving');
  d.querySelector('#view').insertAdjacentHTML('beforeend', '<input id="xin">');
  key(w, d.querySelector('#xin'), ' ', {ctrlKey: true, code: 'Space'});
  check(await until(() => d.querySelector('.qadd.sheet.capture')), 'Ctrl+Space opens it while typing');
  w.eval('closePop()');
  check(w.eval(`palAll().some(x => x.id === 'a:capture')`), 'palette: Quick capture');
  w.close();
  w = await boot({user: 'alice', path: 'capture?title=' + encodeURIComponent('A good read') + '&url=' + encodeURIComponent('https://example.org/post')}); d = w.document;
  sh = await until(() => d.querySelector('.qadd.sheet.capture'));
  check(sh && d.querySelector('#qsheet').value === 'A good read' && /example\.org/.test(sh.querySelector('.qhint').textContent), '/capture: prefilled title + link');
  click(w, sh.querySelector('[data-act="qsheet-send"]'));
  check(await until(async () => (await st()).tasks.some(t => t.title === 'A good read' && t.url === 'https://example.org/post')), '/capture: saved with the link');
  check(await until(() => d.querySelector('.capdone')), '/capture: done message');
  w.close();
  w = await boot({user: 'alice', path: 'capture'}); d = w.document;
  md = await until(() => d.querySelector('.modal.capmodal'));
  check(md && md.querySelector('.capbm').getAttribute('href').startsWith('javascript:') && /\/capture"\+'\?title='/.test(md.querySelector('.capbm').getAttribute('href')), '/capture: bookmarklet');
  check(!d.querySelector('.tour'), 'no tour on the capture page');
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + APP}); d = w.document;
  check(d.querySelector(`#view .trow[data-id="${BUG}"] .ttchip`)?.textContent === 'Fehler', 'German: Fehler');
  w.eval(`listModal(null, '', {kind: 'project'})`); await sleep(200);
  check([...d.querySelectorAll('.lnew .ptcard b')].map(b => b.textContent).slice(0, 4).join('|') === 'Leer|Agentur|Software / KI-Dev|Privat', 'German: project types');
  d.querySelector('.lnew').remove();
  w.eval('quickCapture()'); await sleep(100);
  check(d.querySelector('#qsheet').placeholder === 'In den Eingang notieren …', 'German: capture box');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= Firefox: the new screens fit at phone and desktop width
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(lgi === 200, 'Firefox: login');
    const fit = sel => ev(`(() => { const c = document.querySelector('${sel}'); if (!c) return null; const r = c.getBoundingClientRect();
      const over = [...c.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > r.right + 1 && getComputedStyle(e).position !== 'fixed' && !e.closest('select') && e.getBoundingClientRect().width).length;
      return {doc: document.documentElement.scrollWidth - innerWidth, left: r.left, right: r.right, vw: innerWidth, bottom: r.bottom, vh: innerHeight, over}; })()`);
    const good = (m, bottom = true) => m && m.doc <= 0 && m.left >= 0 && m.right <= m.vw + 1 && (!bottom || m.bottom <= m.vh + 1) && m.over === 0;
    for (const [W, Hh] of [[390, 844], [1280, 800]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
      await nav(B + '#l/' + APP); await sleep(2500);
      if (W < 900) { await ev(`document.querySelector('[data-act="side"]').click()`); await sleep(400); }
      const m1 = await fit('#side');
      check(good(m1, false), `${W}px: sidebar tree fits ${JSON.stringify(m1)}`);
      const ind = await ev(`(() => { const a = document.querySelector('#side .fhead[data-folder="Clients"] .n'), b = document.querySelector('#side .fhead.fsub .n'); return a && b ? b.getBoundingClientRect().left - a.getBoundingClientRect().left : null; })()`);
      check(ind > 8, `${W}px: the subfolder is indented (${ind})`);
      await shot(`p240-tree-${W}.png`);
      if (W < 900) { await ev(`closeSide()`); await sleep(300); }
      const m2 = await fit('#view');
      check(good(m2, false), `${W}px: ticket rows fit ${JSON.stringify(m2)}`);
      await shot(`p240-tickets-${W}.png`);
      await ev(`listModal(null, '', {kind: 'project'})`); await sleep(400);
      const m3 = await fit('.lnew .card');
      check(good(m3), `${W}px: new project dialog fits ${JSON.stringify(m3)}`);
      await shot(`p240-newproject-${W}.png`);
      await ev(`document.querySelector('.lnew').remove()`);
      await ev(`useTemplate({id: ${tpl.id}, kind: 'list', name: 'App plan'})`); await sleep(700);
      const m4 = await fit('.tumodal .card');
      check(good(m4), `${W}px: template dialog fits ${JSON.stringify(m4)}`);
      await shot(`p240-template-${W}.png`);
      await ev(`document.querySelector('.tumodal').remove()`);
      await ev(`quickCapture('Idea for the offsite')`); await sleep(300);
      const m5 = await fit('.qadd.sheet');
      check(good(m5), `${W}px: capture box fits ${JSON.stringify(m5)}`);
      await shot(`p240-capture-${W}.png`);
      await ev(`closePop()`);
    }
  });

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
