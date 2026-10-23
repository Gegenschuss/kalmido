// 2.42.0 UI tests, part D, own container (start.sh), Firefox (1440 x 900):
// - #1376: the delta state: an agent changes tasks of the open list -> the app fetches /api/state/delta (not the whole state),
//   no render() of the whole screen, the changed row shows the new title, the other rows and the sidebar keep their nodes;
//   PERF line: render() calls / state loads / bytes, the old way (S.lpOff) vs the delta; a change while a form holds unsaved
//   input: the data arrives, the input stays, the view waits (stale) and follows once the form is done
// - #1383: "Save as task" under an agent's comment (menu of the comment): the dialog offers subtask / new task in the list,
//   saving creates the task and the comment shows "Saved as task"; a person's comment has no such entry
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2420_d_ui', check, shots: 'P2420D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'comments,collab'});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Agent work'})).id;
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AGH = {Authorization: 'Bearer ' + ag.token};
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const T = [];
  for (const t of ['Alpha task', 'Beta task', 'Gamma task', 'Delta task', 'Epsilon task']) T.push((await call(CA, 'POST', '/api/tasks', {title: t, list_id: L})).id);
  const agPatch = (id, body) => call(null, 'PATCH', `/api/v1/tasks/${id}`, body, AGH);
  const agc = (id, body) => call(null, 'POST', `/api/v1/tasks/${id}/comments`, body, AGH);

  await firefox(async o => {
    const {ev, nav, shot, cmd, ctx} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    // 2.206.0 B (#2513): the page has taken the server's last change (its poll saw the version) instead of fixed 2.5 / 5 s;
    // each change still comes with a poll of its own (a write waits for the one before)
    const caught = () => ready(`fetch('/api/version', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.v === S.v && !td_polling)`, 120);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '#l/' + L);
    check(await ready(`typeof lpDelta === 'function' && !!document.querySelector('#view [data-id="${T[1]}"]') && !!S.lpA`, 60), '#1376: the list and the poll areas');
    // ================= #1376 measurement: the old way vs the delta
    await ev(`(() => { window.__lp = {r: 0, side: 0, st: 0, dl: 0, b: 0}; const R0 = render; render = function () { window.__lp.r++; return R0.apply(this, arguments); };
      const S0 = renderSide; renderSide = function () { window.__lp.side++; return S0.apply(this, arguments); };
      const F0 = window.fetch; window.fetch = async function (u, o) { const r = await F0.call(this, u, o); const s = String(u); if (s.includes('/api/state')) { if (s.includes('/api/state/delta')) window.__lp.dl++; else window.__lp.st++; try { window.__lp.b += (await r.clone().text()).length; } catch {} } return r; }; return 1; })()`);
    const measure = async (off, tag) => {
      await ev(`(() => { S.lpOff = ${off}; Object.assign(window.__lp, {r: 0, side: 0, st: 0, dl: 0, b: 0}); return 1; })()`);
      for (let i = 0; i < 3; i++) { await agPatch(T[3], {title: `Delta task ${tag} ${i}`}); await caught(); await agc(T[4], {body: `${tag} note ${i}`}); await caught(); }
      await sleep(600);  // the bundled redraw after a full load (TD_RS_MS)
      return ev(`({...window.__lp})`);
    };
    const before = await measure(true, 'old');
    check(await ready(`/Delta task old 2/.test(document.querySelector('#view [data-id="${T[3]}"]')?.textContent || '')`, 20), '#1376: the old way shows the change');
    const after = await measure(false, 'new');
    console.log(`PERF #1376 3 task changes + 3 comments of an agent in 20 s, list open: old way ${before.r} render() / ${before.st} state loads / ${Math.round(before.b / 1024)} kB; delta ${after.r} render() / ${after.st} state loads + ${after.dl} deltas / ${Math.round(after.b / 1024)} kB`);
    check(after.dl >= 2 && after.r < before.r && after.b < before.b, '#1376: the delta: fewer render() calls and bytes ' + JSON.stringify({before, after}));
    check(await ready(`/Delta task new 2/.test(document.querySelector('#view [data-id="${T[3]}"]')?.textContent || '')`, 20), '#1376: the changed row shows the new title');
    // only task changes (no comments: those move news / sidebar badges by design): marks on an unchanged row and the sidebar
    // a bundled follow-up of the comments above is done (2.206.0 B, #2513: run now instead of waiting 16 s for LP_DEFER_MS)
    await ev(`(async () => { if (lpT) { clearTimeout(lpT); await lpFollow(); } return 1; })()`);
    await caught();
    await ev(`(() => { document.querySelector('#view [data-id="${T[1]}"]').__keep = 1; const s = document.querySelector('#side .srow, #side button'); if (s) s.__keep = 1; Object.assign(window.__lp, {r: 0, side: 0, st: 0, dl: 0, b: 0}); return 1; })()`);
    for (let i = 0; i < 2; i++) { await agPatch(T[3], {title: `Delta task only ${i}`}); await caught(); }
    await sleep(600);  // a redraw that would follow (TD_RS_MS) is counted too
    const only = await ev(`({...window.__lp})`);
    check(await ready(`/Delta task only 1/.test(document.querySelector('#view [data-id="${T[3]}"]')?.textContent || '')`, 20), '#1376: the changed row shows the new title (only task changes)');
    check(only.dl >= 1 && only.r === 0 && only.st === 0, '#1376: task changes come as deltas, no render(), no state load ' + JSON.stringify(only));
    check(await ev(`document.querySelector('#view [data-id="${T[1]}"]')?.__keep === 1`), '#1376: an unchanged row keeps its node (only the changed row is redrawn)');
    check(await ev(`(document.querySelector('#side .srow, #side button')?.__keep === 1)`) && only.side === 0, '#1376: the sidebar is not redrawn for a title change ' + JSON.stringify(only));
    // a half-filled form: the data comes, the input stays, the view waits
    await ev(`(() => { const f = document.createElement('form'); f.dataset.fg = 'dl-test'; f.id = 'dlform'; f.innerHTML = '<input id="dlf" value="">'; document.querySelector('#view').appendChild(f); const i = f.querySelector('input'); i.value = 'half filled'; i.dispatchEvent(new Event('input', {bubbles: true})); window.__lp.r = 0; window.__lp.dl = 0; return 1; })()`);
    await agPatch(T[0], {title: 'Alpha changed while typing'});
    check(await ready(`S.tasks.get(${T[0]})?.title === 'Alpha changed while typing'`, 40), '#1376: the change arrives (delta) while the form has unsaved input');
    check(await ev(`document.querySelector('#dlf')?.value === 'half filled' && S.viewStale === true && window.__lp.r === 0`), '#1376: the input stays, nothing is redrawn');
    await ev(`(() => { fgDone('dl-test'); document.querySelector('#dlform')?.remove(); return 1; })()`);
    check(await ready(`!S.viewStale && /Alpha changed while typing/.test(document.querySelector('#view [data-id="${T[0]}"]')?.textContent || '')`, 30), '#1376: afterwards the view follows');
    // a deletion (another device of the person): the row goes
    await call(CA, 'DELETE', `/api/tasks/${T[2]}`);
    check(await ready(`!S.tasks.has(${T[2]}) && !document.querySelector('#view [data-id="${T[2]}"]')`, 120), '#1376: a deleted task leaves the list '
      + JSON.stringify(await ev(`({inState: S.tasks.has(${T[2]}), row: !!document.querySelector('#view [data-id="${T[2]}"]'), stale: S.viewStale, polling: td_polling, lpT: !!lpT})`).catch(e => String(e))));  // 2.206.0 B (#2513): 30 s + what is left
    await shot('p2420d-delta.png');
    S1383: {
      // ================= #1383 save an agent's comment as a task
      const C1 = (await agc(T[1], {body: '## Follow-up idea\nCheck the export with the new key.'})).id;
      const CP = (await call(CA, 'POST', `/api/tasks/${T[1]}/comments`, {body: 'my own note'})).id;
      if (!C1 || !CP) { check(false, '#1383: comments posted'); break S1383; }
      await ev(`(() => { openDetail(${T[1]}); return 1; })()`);
      check(await ready(`!!document.querySelector('#d-tl-items .cm[data-cid="${C1}"]')`), '#1383: the agent comment in the timeline');
      check(await ev(`!!document.querySelector('#d-tl-items .cm[data-cid="${C1}"] [data-act="cm-save"]')`), '#1383: "Save as task" under the agent comment');
      check(await ev(`!!document.querySelector('#d-tl-items .cm[data-cid="${CP}"] [data-act="cm-save"]')`), '#1383 -> 2.139.0 (#2130): also under a person\'s comment');
      await ev(`(() => { document.querySelector('#d-tl-items .cm[data-cid="${C1}"] [data-act="cm-save"]').click(); return 1; })()`);
      check(await ready(`!!document.querySelector('.modal [name="cs-as"][value="sub"]')`), '#1383: the dialog offers subtask / new task');
      const dlg = await ev(`(() => { const m = document.querySelector('.modal'); return {title: m.querySelector('#cs-title')?.value, sub: m.querySelector('[name="cs-as"][value="sub"]')?.checked, list: !!m.querySelector('[name="cs-as"][value="list"]')}; })()`);
      check(dlg.title === 'Follow-up idea' && dlg.sub === true && dlg.list, '#1383: title from the heading, subtask preselected ' + JSON.stringify(dlg));
      await shot('p2420d-save.png');
      await ev(`(() => { document.querySelector('.modal [data-m="ok"]').click(); return 1; })()`);
      check(await ready(`[...S.tasks.values()].some(t => t.title === 'Follow-up idea' && t.parent_id === ${T[1]})`, 40), '#1383: the subtask exists');
      check(await ready(`!!document.querySelector('#d-tl-items .cm[data-cid="${C1}"] [data-act="cm-saved"]')`, 40), '#1383: the comment shows "Saved as task"');
    }
  }, false);

  console.log(`p2420_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
