// 2.39.0 UI tests, part B (#1151 "Tidy up the list"), own container (start.sh), Firefox as a phone (390 x 844, touch):
// - the list menu shows "Tidy up the list…" only in a list with a tidy agent where I may write (not in a list without an
//   agent); the dialog names the agent, the number of open tasks and takes a hint; "Ask for a proposal" sends it
// - two selected tasks of that list: "Tidy up…" in the selection's "More" menu opens the same dialog for the selection
// - the agent's proposal in the proposal sheet: one sentence per entry (merge, rename, move, close) with a checkbox, the
//   title of rename / merge editable, "Apply 4 entries"; a task completed meanwhile is listed as skipped with the reason
// - undo takes everything back in one step (histStep), redo applies it again
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2390_b_ui', check, shots: 'P2390B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'comments,collab,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['write'], username: 'tidy', display_name: 'Tidy'});
  const AGH = {Authorization: 'Bearer ' + ag.token};
  const W = (await call(CA, 'POST', '/api/lists', {name: 'Work'})).id;
  await call(CA, 'PUT', `/api/lists/${W}/members`, {user_id: ag.id, role: 'edit'});
  const NO = (await call(CA, 'POST', '/api/lists', {name: 'Plain'})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'plain task', list_id: NO});
  const SEC = (await call(CA, 'POST', '/api/sections', {list_id: W, name: 'Later'})).id;
  const T = {};
  for (const k of ['Flyer order', 'Order flyers', 'misc stuff', 'Archive boxes', 'Old fair booth', 'Done meanwhile']) T[k] = (await call(CA, 'POST', '/api/tasks', {title: k, list_id: W})).id;
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#l/' + W); await ready(ev, `typeof clnOk === 'function' && S.lists.length > 2 && !!document.querySelector('#view .trow')`);
    await sleep(500);

    // ================= the list menu
    const labels = id => ev(`listMenuSort(listMenuItems(${id}, document.querySelector('#top h1'))).flatMap(i => i === '-' ? [] : [i.label, ...((i.sub && Array.isArray(i.sub)) ? i.sub.map(x => x.label) : [])]).join('|')`);
    // 2.152.2 (#2624): project instead of list
    check(/Tidy up the project…/.test(await labels(W)), '#1151: the list menu offers "Tidy up the list…"');
    // 2.152.2 (#2624): project instead of list
    check(!/Tidy up the project…/.test(await labels(NO)), '#1151: not in a list without an agent');
    await ev(`(() => { listMenu(document.querySelector('#top h1'), ${W}); return 1; })()`); await sleep(300);
    // 2.152.2 (#2624): project instead of list
    const clicked = await ev(`(() => { const b = [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => /Tidy up the project…/.test(x.textContent)); if (b) b.click(); return !!b; })()`);
    check(clicked, '#1151: the entry is in the menu itself (not only in "More list options")');
    check(await ready(ev, `!!document.querySelector('.modal.clnreq')`), '#1151: the request dialog opens');
    const dlg = await ev(`(() => { const m = document.querySelector('.modal.clnreq'); return {h: m.querySelector('h3').textContent, n: m.querySelector('.pptask').textContent, priv: m.querySelector('#cln-priv').textContent, w: m.querySelector('.card').getBoundingClientRect().width}; })()`);
    // 2.152.2 (#2624): project instead of list
    check(/Tidy up the project with Tidy/.test(dlg.h) && /6 open tasks/.test(dlg.n) && /Tidy gets the titles/.test(dlg.priv), '#1151: the dialog names the agent, the number and what it gets ' + JSON.stringify(dlg));
    check(dlg.w <= 390, '#1151: the dialog fits the phone ' + dlg.w);
    await shot('p2390b-request.png');
    await ev(`(() => { const t = document.querySelector('#cln-hint'); t.value = 'merge duplicates'; document.querySelector('.modal.clnreq [data-m="ok"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal.clnreq')`), '#1151: sent, the dialog closes');
    const evs = (await call(null, 'GET', '/api/v1/agent/events?since=0&limit=500', null, AGH)).data || [];
    const jr = evs.filter(e => e.event === 'job_request').pop();
    check(jr && jr.data.kind === 'cleanup' && jr.data.list_id === W && jr.data.input.hint === 'merge duplicates' && jr.data.input.items.length === 6, '#1151: the agent got the job_request');
    const J = jr?.data.job.id;

    // ================= the selection: "Tidy up…" in the phone's "More" menu
    await ev(`(() => { S.multi.clear(); S.multi.add(${T['Flyer order']}); S.multi.add(${T['Order flyers']}); render(); return 1; })()`); await sleep(300);
    check(await ev(`clnSel()?.id === ${W}`), '#1151: two open tasks of the list are a valid selection');
    await ev(`(() => { document.querySelector('#mbar [data-act="mb-menu"]').click(); return 1; })()`); await sleep(300);
    const sel = await ev(`(() => { const b = [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => /Tidy up…/.test(x.textContent)); if (b) b.click(); return !!b; })()`);
    check(sel, '#1151: "Tidy up…" in the selection\'s More menu');
    check(await ready(ev, `/2 selected tasks/.test(document.querySelector('.modal.clnreq .pptask')?.textContent || '')`), '#1151: the dialog for the selection');
    await ev(`(() => { document.querySelector('.modal.clnreq [data-m="close"]').click(); S.multi.clear(); S.multiMode = false; render(); return 1; })()`); await sleep(300);

    // ================= the proposal in the sheet
    const prop = {kind: 'cleanup', summary: 'One duplicate, a vague title, a box for later, a stale booth.', items: [
      {op: 'merge', task_ids: [T['Flyer order'], T['Order flyers']], title: 'Order the flyers', reason: 'the same twice'},
      {op: 'rename', task_id: T['misc stuff'], title: 'Sort the misc stuff'},
      {op: 'move', task_id: T['Archive boxes'], section_id: SEC},
      {op: 'close', task_id: T['Old fair booth'], reason: 'the fair is over'},
      {op: 'close', task_id: T['Done meanwhile'], reason: 'looks done'}]};
    const sp = await call(null, 'POST', `/api/v1/agent/jobs/${J}/proposal`, prop, AGH);
    check(sp.http === 201, '#1151: the agent submits ' + sp.http);
    await call(CA, 'POST', `/api/tasks/${T['Done meanwhile']}/complete`, {});
    await ev(`(async () => { await load(); render(); propOpen(${J}); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.modal.ppm .clni').length === 5`), '#1151: five entries in the sheet');
    const rows = await ev(`[...document.querySelectorAll('.modal.ppm .clni')].map(x => ({s: x.querySelector('.clns').textContent.trim(), t: !!x.querySelector('input.ppt'), c: x.querySelector('.ppc').checked}))`);
    check(/^Merge: “Flyer order” \+ “Order flyers” → “Flyer order”/.test(rows[0]?.s) && rows[0].t, '#1151: merge sentence + title field ' + JSON.stringify(rows[0]));
    check(/^Rename: “misc stuff”/.test(rows[1]?.s) && rows[1].t, '#1151: rename sentence + title field');
    check(/^Move “Archive boxes” to section “Later”/.test(rows[2]?.s) && !rows[2].t, '#1151: move sentence (section), no title field');
    check(/^Close as won’t do: “Old fair booth”/.test(rows[3]?.s) && rows.every(x => x.c), '#1151: close sentence, all ticked');
    check(/Package/.test(await ev(`document.querySelector('.modal.ppm .pphead').textContent`)) === false, '#1151: no package line for a single package');
    check(await ev(`/Tasks someone is editing right now/.test(document.querySelector('.modal.ppm .shint.keep').textContent)`), '#1151: the hint about skipped tasks');
    const fit = await ev(`(() => { const c = document.querySelector('.modal.ppm .card').getBoundingClientRect(); const a = document.querySelector('.modal.ppm [data-pp="apply"]').getBoundingClientRect(); return {w: c.width, ah: a.height, ab: a.bottom}; })()`);
    check(fit.w <= 390 && fit.ah >= 32 && fit.ab <= 844, '#1151: the sheet fits the phone, Apply reachable ' + JSON.stringify(fit));
    await shot('p2390b-review.png');
    await ev(`(() => { const i = document.querySelectorAll('.modal.ppm .clni')[1].querySelector('input.ppt'); i.value = 'Sort the misc box'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(/Apply 5 entries/.test(await ev(`document.querySelector('.modal.ppm [data-pp="apply"]').textContent`)), '#1151: "Apply 5 entries"');
    await ev(`(() => { document.querySelector('.modal.ppm [data-pp="apply"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal.ppm') && !!document.querySelector('.modal.clnres')`, 60), '#1151: applied, the skipped one is listed');
    const res = await ev(`document.querySelector('.modal.clnres').textContent`);
    check(/4 changes applied/.test(res) && /Done meanwhile/.test(res) && /already completed or deleted/.test(res), '#1151: the result names the skipped task and why ' + res.slice(0, 200));
    await shot('p2390b-result.png');
    await ev(`(() => { document.querySelector('.modal.clnres [data-m="close"]').click(); return 1; })()`);
    const get = async id => call(CA, 'GET', `/api/tasks/${id}`);
    check((await get(T['Flyer order'])).title === 'Order the flyers' && (await get(T['Order flyers'])).status === -1, '#1151: merged');
    check((await get(T['misc stuff'])).title === 'Sort the misc box', '#1151: renamed with the edited title');
    check((await get(T['Archive boxes'])).section_id === SEC && (await get(T['Old fair booth'])).status === -1, '#1151: moved, closed');
    check(await ev(`HIST.undo[HIST.undo.length - 1].label`) === 'Applied the proposal of Tidy', '#1151: one history step');
    await ev(`(async () => { await histStep('undo'); return 1; })()`); await sleep(800);
    check((await get(T['Flyer order'])).title === 'Flyer order' && (await get(T['Order flyers'])).status === 0 && (await get(T['misc stuff'])).title === 'misc stuff'
      && (await get(T['Archive boxes'])).section_id === null && (await get(T['Old fair booth'])).status === 0, '#1151: undo takes everything back');
    await ev(`(async () => { await histStep('redo'); return 1; })()`); await sleep(800);
    check((await get(T['Order flyers'])).status === -1 && (await get(T['Archive boxes'])).section_id === SEC, '#1151: redo applies it again');
  }, true);

  console.log(`p2390_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
