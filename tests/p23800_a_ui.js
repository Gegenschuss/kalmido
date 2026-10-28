// kalmido-suite: fresh
// 2.380.0 part A UI test (#3423 #3424 #3408), own container (start.sh), jsdom + Firefox. Invented names only.
// - a table cell: the editor is no wider than the cell (css), Enter shows the typed value in the cell BEFORE the server
//   answered (the write is held back by a fetch hook), a formula keeps its old result dimmed (.pend) until the answer;
//   a refused write puts the old value back
// - a list with time tracking: the column head reads "Tracked" (not "Time"), the sum row adds up the tracked time
// - the workload: week heads in two short lines, numbers not in the mono face, "N without an estimate" instead of "+N";
//   Firefox 1270 px and 390 px: the week heads do not overlap, the cell editor is not wider than its cell
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P23800A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), _status: r.status}; };
const FEAT = 'collab,comments,sheets,time,workload';
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { try { if (await fn()) return true; } catch { /* not yet */ } await sleep(150); } return false; };
const key = (w, el, k, o = {}) => el && el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const firefox = require('./ff')({tag: 'p23800_a_ui', check, shots: 'P23800A_SHOTS'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;

  // ---- #3423 static: the editor is as wide as its cell
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'css', 'sheets.css'), 'utf8');
  const rule = (css.match(/\.shvin\{[^}]*\}/) || [''])[0];
  check(rule && /width:100%/.test(rule) && !/max\(|14rem/.test(rule), '#3423: .shvin is as wide as the cell ' + rule.slice(0, 80));

  // ---- #3423: the value stands at once
  const S = await call('POST', '/api/sheets', {title: 'Harvest', space: `org:${ORG}`});
  const SID = S.id, R = S.rows.map(r => r.id), C = S.columns.map(c => c.id);
  await call('PUT', `/api/sheets/${SID}/cells`, {cells: [{cell: 'A1', raw: 'Apples'}, {cell: 'B1', raw: '4'}, {cell: 'B2', raw: '5'}]});
  const cellOf = async addr => ((await call('GET', `/api/sheets/${SID}`)).cells || []).find(c => c.addr === addr);
  let w = await boot({user: 'alice', hash: 'sheets/' + SID}), d = w.document;
  check(await until(() => d.querySelector('#shv-scroll td.shvc')), '#3423: the table is open');
  const td = (r, c) => d.getElementById(`shv-c-${r}-${c}`), sc = () => d.getElementById('shv-scroll');
  // hold back the write of the cells (a promise the test releases) or refuse it
  w.eval(`window.__mode = 'hold'; window.__rel = null; const of = window.fetch; window.fetch = (u, o) => /\\/cells$/.test(String(u)) && o && o.method === 'PUT'
    ? (window.__mode === 'fail' ? Promise.resolve(new Response(JSON.stringify({error: 'refused'}), {status: 500, headers: {'Content-Type': 'application/json'}}))
      : new Promise(res => { window.__rel = () => res(of(u, o)); })) : of(u, o);`);
  w.eval(`shvSelect(${R[0]}, ${C[2]})`); sc().focus();
  key(w, sc(), 'N');
  let ed = d.getElementById('shv-ed');
  check(!!ed, '#3423: typing opens the editor');
  ed.value = 'Nectarines'; key(w, ed, 'Enter');
  check(await until(() => w.eval('window.__rel') && true), '#3423: the write is on its way (held back)');
  check(/Nectarines/.test(td(R[0], C[2])?.textContent || '') && !d.getElementById('shv-ed'), '#3423: the typed value stands in the cell before the answer ' + td(R[0], C[2])?.textContent);
  check(!(await cellOf('C1')), '#3423: the server has not answered yet');
  w.eval('window.__rel()');
  check(await until(async () => (await cellOf('C1'))?.raw === 'Nectarines'), '#3423: saved after the release');
  check(/Nectarines/.test(td(R[0], C[2])?.textContent || ''), '#3423: still there after the answer');
  // a formula: the old result stays, dimmed, until the answer
  w.eval(`shvSelect(${R[1]}, ${C[2]})`); sc().focus();
  key(w, sc(), '='); ed = d.getElementById('shv-ed'); ed.value = '=B1+B2'; key(w, ed, 'Enter');
  check(await until(() => w.eval('window.__rel') && true), '#3423: formula write held back');
  check(td(R[1], C[2])?.classList.contains('pend'), '#3423: a formula cell is dimmed (.pend) until the result');
  w.eval('window.__rel()');
  check(await until(() => /9/.test(td(R[1], C[2])?.textContent || '') && !td(R[1], C[2])?.classList.contains('pend')), '#3423: the result 9 replaces it ' + td(R[1], C[2])?.textContent);
  // a refused write: the old value is back
  w.eval(`window.__mode = 'fail'`);
  w.eval(`shvSelect(${R[1]}, ${C[0]})`); sc().focus();
  key(w, sc(), 'Z'); ed = d.getElementById('shv-ed'); ed.value = 'Zucchini'; key(w, ed, 'Enter');
  check(await until(() => !/Zucchini/.test(td(R[1], C[0])?.textContent || '')), '#3423: a refused write: the cell is empty again ' + td(R[1], C[0])?.textContent);
  check(!(await cellOf('A2')), '#3423: nothing was stored');
  w.close();

  // ---- #3424: the tracked-time column
  const L = (await call('POST', '/api/lists', {name: 'Shoot', kind: 'project', time_tracking: true, org_id: ORG})).id;
  await call('PATCH', `/api/lists/${L}`, {columns: ['due', 'time', 'tags']});
  const T1 = (await call('POST', '/api/tasks', {title: 'Light', list_id: L})).id, T2 = (await call('POST', '/api/tasks', {title: 'Sound', list_id: L})).id;
  await call('POST', '/api/time/entries', {task_id: T1, start: new Date(Date.now() - 6 * 36e5).toISOString(), minutes: 180});
  await call('POST', '/api/time/entries', {task_id: T2, start: new Date(Date.now() - 12 * 36e5).toISOString(), minutes: 60});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  check(await until(() => d.querySelector('#view .lc[data-k="time"]')), '#3424: the list shows the tracked-time column');
  const head = [...d.querySelectorAll('#view .lc[data-k="time"] .lcn')].map(x => x.textContent.trim());
  check(head.length && head.every(x => x === 'Tracked'), '#3424: the head reads "Tracked" ' + head.join('|'));
  check(await until(() => /4[:.]00|4 h/.test(d.querySelector('#view .fxsum .lc[data-k="time"]')?.textContent || '')), '#3424: the sum row adds up the tracked time ' + d.querySelector('#view .fxsum')?.textContent);
  w.close();

  // ---- #3408: the workload (jsdom)
  await call('POST', '/api/tasks', {title: 'Build', list_id: L, assignee_id: (await call('GET', '/api/state')).me.id, due: new Date().toISOString().slice(0, 10)});
  w = await boot({user: 'alice', hash: 'workload'}); d = w.document;
  check(await until(() => d.querySelector('#view .wltable thead th .wlw1')), '#3408: week heads in two lines');
  const ths = [...d.querySelectorAll('#view .wltable thead th')].filter(t => t.querySelector('.wlw1'));
  check(ths.length >= 4 && ths.every(t => /^\d{1,2}[./]\d{1,2}/.test(t.querySelector('.wlw1').textContent) && /^–/.test(t.querySelector('.wlw2').textContent)), '#3408: "26.10." above, "– 1.11." below ' + ths.map(t => t.textContent).join('|'));
  check(!/\+\d/.test(d.querySelector('#view .wltable tbody')?.textContent || ''), '#3408: no bare "+N" in the cells');
  const app = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  const wlt = (app.match(/\.wlt\{[^}]*\}/) || [''])[0];
  check(/tabular-nums/.test(wlt) && !/var\(--mono\)/.test(wlt), '#3408: .wlt in normal type with tabular numbers ' + wlt.slice(0, 90));
  w.close();

  // ---- Firefox: real widths
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(500); };
  for (const [vw, vh, touch] of [[1270, 900, false], [390, 844, true]]) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = `${vw}px`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
    check(await ffLogin(o) === 200, tag + ': login');
    await o.nav(B + '#workload'); await ready(ev, '#view .wltable thead th .wlw1');
    const g = await ev(`(() => { const rs = [...document.querySelectorAll('#view .wltable thead th')].map(t => { const r = t.getBoundingClientRect(); return [r.left, r.right]; });
      const ov = rs.some((a, i) => rs.some((b, j) => j > i && a[0] < b[1] - 0.5 && b[0] < a[1] - 0.5));
      const inner = [...document.querySelectorAll('#view .wltable thead th')].some(t => t.scrollWidth > t.clientWidth + 1);
      return {n: rs.length, ov, inner, mono: getComputedStyle(document.querySelector('#view .wlt')).fontFamily}; })()`);
    check(g.n >= 6 && !g.ov && !g.inner, `${tag}: #3408: the week heads do not overlap or overflow ` + JSON.stringify(g));
    check(!/mono|Courier/i.test(g.mono), `${tag}: #3408: the cell numbers are not in the mono face ` + g.mono);
    await shot(`p23800a-${vw}-workload.png`);
    await o.nav(B + `#sheets/${SID}`); await ready(ev, '#shv-scroll td.shvc');
    await ev(`(() => { shvSelect(${R[0]}, ${C[0]}); document.getElementById('shv-scroll').focus(); document.getElementById('shv-scroll').dispatchEvent(new KeyboardEvent('keydown', {key: 'F2', bubbles: true})); return 1; })()`);
    await ready(ev, '#shv-ed');
    const e = await ev(`(() => { const i = document.getElementById('shv-ed'), t = i.closest('td'); return {i: i.getBoundingClientRect().width, t: t.getBoundingClientRect().width}; })()`);
    check(e.i <= e.t + 1, `${tag}: #3423: the editor is as wide as its cell ` + JSON.stringify(e));
    await shot(`p23800a-${vw}-cell.png`);
  }, touch);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
