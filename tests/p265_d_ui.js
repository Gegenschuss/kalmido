// 2.65.0 part D (#1825): long lists draw only the rows near the visible part. A list with 5000 generated tasks (some with a
// subtask) in three sections, written straight into the test database (like perf_ui.js), and a list with 200 tasks; Firefox
// at 1440 (mouse) and 390 (touch):
// - the long list draws far fewer rows than it has, has spacers, no "Show more"; the short list is drawn as before (all rows)
// - render time and scroll frames (PERF lines); scrolling never shows an empty screen; the end shows the last task
// - Shift-click selects across rows that are not drawn; Ctrl+A selects all rows of the view
// - j over the window's edge moves on and keeps the focused row visible; a jump far down draws the row
// - a drop after the last drawn row takes its neighbour from the data (the order is right)
// - a re-render (live update) and coming back to the list keep the scroll position
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p265_d', check, shots: 'P265D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const N = +(process.env.P265D_N || 5000);
const perf = (k, v) => console.log(`PERF p265_d ${k} = ${typeof v === 'number' ? Math.round(v * 10) / 10 : JSON.stringify(v)}`);

(async () => {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['kanban', 'cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const BIG = (await call('POST', '/api/lists', {name: 'Big'})).id, SMALL = (await call('POST', '/api/lists', {name: 'Small'})).id;
  check(BIG && SMALL, 'setup: two lists');
  execFileSync('docker', ['exec', '-w', '/app', process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test', 'python', '-c', `
import datetime
from kalmido.core.db import connect
from kalmido.core.pg import insert_id
c = connect()
now = datetime.datetime.now(datetime.timezone.utc).isoformat()
secs = [insert_id(c, "INSERT INTO sections(list_id, name, sort) VALUES(?,?,?)", (${BIG}, f"Part {k}", k)) for k in range(3)]
for i in range(${N}):
    t = insert_id(c, "INSERT INTO tasks(list_id, section_id, title, priority, sort, created_at, updated_at, created_by) VALUES(?,?,?,0,?,?,?,1)",
                  (${BIG}, secs[i * 3 // ${N}], f"Row {i:05d}", i, now, now))
    if i % 25 == 7:
        c.execute("INSERT INTO tasks(list_id, parent_id, title, sort, created_at, updated_at, created_by) VALUES(?,?,?,?,?,?,1)", (${BIG}, t, f"Sub of {i:05d}", 0, now, now))
for i in range(200):
    c.execute("INSERT INTO tasks(list_id, title, priority, sort, created_at, updated_at, created_by) VALUES(?,?,0,?,?,?,1)", (${SMALL}, f"Small {i:03d}", i, now, now))
c.execute("UPDATE settings SET value=CAST(CAST(value AS BIGINT)+1 AS TEXT) WHERE key='version'")
c.commit()
c.close()
`], {stdio: 'ignore'});

  for (const [vw, vh, touch] of [[1440, 900, false], [390, 844, true]]) await firefox(async ({cmd, ev, ctx, nav}) => {
    const tag = String(vw);
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    const s0 = Date.now();
    await nav(B + '#l/' + BIG);
    for (let i = 0; i < 300 && !(await ev(`!!document.querySelector('#view .trow')`).catch(() => false)); i++) await sleep(50);
    perf(`${tag} start ms`, Date.now() - s0);
    await sleep(400);
    const frame = `await new Promise(r => requestAnimationFrame(() => setTimeout(r, 0)))`;
    const rt = await ev(`(async () => { const t = performance.now(); render(); ${frame}; return performance.now() - t; })()`);
    perf(`${tag} render ms`, rt); check(rt < 1500, `${tag}: a render of the long list in ${Math.round(rt)} ms`);
    const i0 = await ev(`(() => ({rows: document.querySelectorAll('#view .trow').length, pads: document.querySelectorAll('#view .vlpad').length, ids: vl_ids().length, more: !!document.querySelector('#view [data-act="rows-more"]'), h: document.getElementById('view').scrollHeight}))()`);
    perf(`${tag} drawn rows`, i0.rows);
    check(i0.ids >= N && i0.rows > 10 && i0.rows < 600 && i0.pads >= 2 && !i0.more, `${tag}: the long list draws a window ` + JSON.stringify(i0));
    check(i0.h > N * 20, `${tag}: the scroll height stands for all rows (${i0.h})`);
    // scrolling: the work per frame, never an empty screen
    const sc = await ev(`(async () => {
      const v = document.getElementById('view'), fr = []; let blank = 0, maxRows = 0, diag = null;
      for (let i = 0; i < 80; i++) {
        const t = performance.now(); v.scrollTop += v.clientHeight * .9; vl_sync(); fr.push(performance.now() - t);
        ${frame};
        const r = v.getBoundingClientRect(), mid = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
        if (!mid?.closest('.trow, .ghead, .secadd, .sdrop') && !blank++) diag = {i, st: v.scrollTop, vh: v.clientHeight, sh: v.scrollHeight, mid: mid?.className, on: VL.on, segs: VL.segs.map(g => [g.a, g.b, g.arr.length, Math.round(g.tp)]), pads: [...document.querySelectorAll('#view .vlpad')].map(p => [p.dataset.k, p.style.height, p.offsetHeight, Math.round(p.getBoundingClientRect().top - r.top)]), rows: [...document.querySelectorAll('#view .trow[data-id]')].filter((x, j, all) => !j || j === all.length - 1).map(x => [x.dataset.id, Math.round(x.getBoundingClientRect().top - r.top)])};
        maxRows = Math.max(maxRows, document.querySelectorAll('#view .trow').length);
      }
      fr.sort((a, b) => a - b);
      return {avg: fr.reduce((a, b) => a + b, 0) / fr.length, p95: fr[Math.floor(fr.length * .95)], max: fr[fr.length - 1], blank, maxRows, top: v.scrollTop, diag};
    })()`);
    perf(`${tag} scroll frame ms avg`, sc.avg); perf(`${tag} scroll frame ms p95`, sc.p95); perf(`${tag} scroll frame ms max`, sc.max); perf(`${tag} scroll max drawn rows`, sc.maxRows);
    check(sc.p95 < 60, `${tag}: a scroll step takes ${Math.round(sc.p95)} ms (p95)`);
    check(!sc.blank, `${tag}: scrolling never shows an empty screen (${sc.blank} empty) ` + JSON.stringify(sc.diag));
    check(sc.maxRows < 600, `${tag}: the window stays small while scrolling (${sc.maxRows})`);
    // the end of the list
    const end = await ev(`(async () => {
      const v = document.getElementById('view');
      for (let i = 0; i < 4; i++) { v.scrollTop = v.scrollHeight; vl_sync(); ${frame}; }
      const ids = vl_ids(), last = ids[ids.length - 1], el = document.querySelector('#view .trow[data-id="' + last + '"]'), r = el?.getBoundingClientRect(), vr = v.getBoundingClientRect();
      return {last: S.tasks.get(last)?.title, vis: !!r && r.bottom > vr.top && r.top < vr.bottom};
    })()`);
    check(end.vis && new RegExp(`Row 0*${N - 1}$`).test(end.last || ''), `${tag}: the end shows the last task ` + JSON.stringify(end));
    // Shift-click across rows that are not drawn
    const ms = await ev(`(async () => {
      const v = document.getElementById('view'); v.scrollTop = 0; vl_sync(); ${frame};
      S.multi.clear(); S.multiLast = null; S.sel = null; S.kf = null;
      const ids = vl_ids(), clk = (id, o) => document.querySelector('#view .trow[data-id="' + id + '"] .ttl').dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
      clk(ids[0], {ctrlKey: true});
      vl_reveal(ids[700]); ${frame};
      const gone = !document.querySelector('#view .trow[data-id="' + ids[0] + '"]');
      clk(ids[700], {shiftKey: true});
      const r = {gone, n: S.multi.size, mid: S.multi.has(ids[350]), end: S.multi.has(ids[700]), out: S.multi.has(ids[701])};
      S.multi.clear(); S.multiLast = null; render();
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'a', ctrlKey: true, bubbles: true, cancelable: true})); ${frame};
      r.all = S.multi.size; r.ids = ids.length;
      S.multi.clear(); S.multiMode = false; S.multiLast = null; render(); renderMultiBar();
      return r;
    })()`);
    check(ms.gone && ms.n === 701 && ms.mid && ms.end && !ms.out, `${tag}: Shift-click selects across rows that are not drawn ` + JSON.stringify(ms));
    check(ms.all === ms.ids, `${tag}: Ctrl+A selects all rows of the view (${ms.all} of ${ms.ids})`);
    // keyboard
    const kb = await ev(`(async () => {
      const v = document.getElementById('view'); v.scrollTop = 0; vl_sync(); ${frame};
      const ids = vl_ids(); kfocus(ids[0]);
      for (let i = 0; i < 150; i++) { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'j', bubbles: true, cancelable: true})); if (i % 10 === 9) ${frame}; }
      ${frame};
      const vr = v.getBoundingClientRect(), vis = id => { const r = document.querySelector('#view .trow[data-id="' + id + '"]')?.getBoundingClientRect(); return !!r && r.top >= vr.top - 1 && r.bottom <= vr.bottom + 1; };
      const r = {kf: S.kf === ids[150], vis: vis(ids[150]), first: !document.querySelector('#view .trow[data-id="' + ids[0] + '"]')};
      document.dispatchEvent(new KeyboardEvent('keydown', {key: 'k', bubbles: true, cancelable: true})); ${frame};
      r.back = S.kf === ids[149] && vis(ids[149]);
      kfocus(ids[4000]); ${frame};
      r.far = vis(ids[4000]); if (!r.far) { const e = document.querySelector('#view .trow[data-id="' + ids[4000] + '"]'); r.fd = {e: !!e, top: e && Math.round(e.getBoundingClientRect().top - vr.top), st: v.scrollTop, vh: v.clientHeight, segs: VL.segs.map(g => [g.a, g.b, g.arr.length, Math.round(g.tp)])}; }
      kfocus(null);
      return r;
    })()`);
    check(kb.kf && kb.vis && kb.first, `${tag}: j moves over the window's edge, the row stays visible ` + JSON.stringify(kb));
    check(kb.back && kb.far, `${tag}: k back, a jump far down draws the row ` + JSON.stringify(kb));
    // a drop after the last drawn row: the neighbour below comes from the data
    const dr = await ev(`(async () => {
      const v = document.getElementById('view'); v.scrollTop = 6000; vl_sync(); ${frame};
      const drawn = new Set([...document.querySelectorAll('#view .trow[data-id]')].map(r => +r.dataset.id));
      const top = vl_ids().map(i => S.tasks.get(i)).filter(t => t && !t.parent_id);
      let k = top.findIndex((t, i) => i > 6 && drawn.has(t.id) && top[i + 1] && !drawn.has(top[i + 1].id) && top[i + 1].section_id === t.section_id && top[i - 5].section_id === t.section_id);
      if (k < 0) return {k};
      const target = top[k], next = top[k + 1], mover = top[k - 5], row = document.querySelector('#view .trow[data-id="' + target.id + '"]'), rr = row.getBoundingClientRect();
      await dropTask(mover.id, row.querySelector('.ttl'), rr.bottom - 2);
      ${frame};
      const t2 = vl_ids().map(i => S.tasks.get(i)).filter(t => t && !t.parent_id).map(t => t.id), m = S.tasks.get(mover.id);
      return {k, order: t2.indexOf(mover.id) === t2.indexOf(target.id) + 1 && t2.indexOf(next.id) === t2.indexOf(mover.id) + 1, sort: [S.tasks.get(target.id).sort, m.sort, S.tasks.get(next.id).sort], sec: m.section_id === target.section_id};
    })()`);
    check(dr.k >= 0 && dr.order && dr.sec, `${tag}: a drop after the last drawn row lands between it and its neighbour from the data ` + JSON.stringify(dr));
    // a live update keeps the place
    const lu = await ev(`(async () => {
      const v = document.getElementById('view'); v.scrollTop = 40000; vl_sync(); ${frame};
      const vr = v.getBoundingClientRect(), fv = () => { for (const r of document.querySelectorAll('#view .trow[data-id]')) { const b = r.getBoundingClientRect(); if (b.bottom > vr.top + 1) return [r.dataset.id, Math.round(b.top)]; } return null; };
      const a = v.scrollTop, f0 = fv(), d0 = {st: a, segs: VL.segs.map(g => [g.a, g.b, g.arr.length, Math.round(g.tp)]), pads: [...document.querySelectorAll('#view .vlpad')].map(p => [p.style.height, Math.round(p.getBoundingClientRect().top - vr.top)])};
      await load(); render(); ${frame}; ${frame};
      const t = performance.now(); render(); const rms = performance.now() - t;
      ${frame};
      const f1 = fv();
      return {d: Math.abs(v.scrollTop - a), same: !!f0 && !!f1 && f0[0] === f1[0] && Math.abs(f0[1] - f1[1]) <= 2, f0, f1, rms, d0: f0 ? null : d0};
    })()`);
    perf(`${tag} re-render while scrolled ms`, lu.rms);
    check(lu.d <= 2 && lu.same, `${tag}: a live update keeps the scroll position ` + JSON.stringify(lu));
    // back to the list
    const bk = await ev(`(async () => {
      const v = document.getElementById('view'), a = v.scrollTop;
      go('today'); await new Promise(r => setTimeout(r, 400));
      go('l/${BIG}'); await new Promise(r => setTimeout(r, 600)); ${frame};
      return {a, b: v.scrollTop, rows: document.querySelectorAll('#view .trow').length};
    })()`);
    check(Math.abs(bk.a - bk.b) <= 4 && bk.rows > 10, `${tag}: back in the list it is where it was ` + JSON.stringify(bk));
    // a short list is drawn as before
    const sm = await ev(`(async () => { go('l/${SMALL}'); await new Promise(r => setTimeout(r, 600)); return {rows: document.querySelectorAll('#view .trow').length, pads: document.querySelectorAll('#view .vlpad').length}; })()`);
    check(sm.rows === 200 && !sm.pads, `${tag}: a list with 200 tasks draws all rows, no spacers ` + JSON.stringify(sm));
  }, touch);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
