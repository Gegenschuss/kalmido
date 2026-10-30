// 2.145.0 UI test, part B (#2424): an own window (/?mini=1#…: a list, a task, a chat) starts fast. Own container (start.sh), Firefox:
// - a main window is open (#today); a second tab of the same browser opens the list / task / team chat window, several times each;
//   the time until the window is usable (its content drawn) is printed with the share of the scripts (DOMContentLoaded) and of the
//   state request; the limit is generous (3 s) so CI does not flicker
// - the window shows its content at once from the main window's state (no full state request before the first picture), works
//   (tick a task off in the list window, rename the task in the task window) and a change made in the main window arrives live
// - without a main window the own window still starts the normal way
// P2145B_NOSTART=1 = the container is running.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2145_b_ui', check, shots: 'P2145B_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2145B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'comments,collab,agents,team,time';
const N_LISTS = 24, N_TASKS = 40;  // about a thousand tasks: the state request costs something, like a real account
const RUNS = 3;
const median = a => { const s = [...a].sort((x, y) => x - y); return s[Math.floor(s.length / 2)]; };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const lists = [];
  for (let i = 0; i < N_LISTS; i++) lists.push((await call(CA, 'POST', '/api/lists', {name: `Project ${i + 1}`})).id);
  const L = lists[0];
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Buy paint', list_id: L})).id;
  const T2 = (await call(CA, 'POST', '/api/tasks', {title: 'Return the drill', list_id: L})).id;
  const filler = 'Some notes on the task, a few lines long so the state carries real text. '.repeat(4);
  for (const lid of lists) {
    for (let k = 0; k < N_TASKS; k += 10) await Promise.all(Array.from({length: 10}, (_, j) => call(CA, 'POST', '/api/tasks', {title: `Step ${k + j + 1} of list ${lid}`, list_id: lid, content: filler})));
  }
  const BOB = (await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});  // a shared list has a team room
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const team = await call(CA, 'GET', '/api/team');
  const RID = ((team.rooms || []).find(x => x.kind === 'list' && x.list_id === L) || {}).id;
  check(RID > 0, 'setup: the list room ' + JSON.stringify(team).slice(0, 160));
  await call(CA, 'POST', `/api/team/rooms/${RID}/messages`, {body: 'Hello studio'});
  const st = await call(CA, 'GET', '/api/state');
  console.log(`p2145_b_ui: state with ${(st.tasks || []).length} tasks, ${(st.lists || []).length} lists, ${Math.round(JSON.stringify(st).length / 1024)} KB`);

  const until = (ev, expr, n) => require('./boot').until(() => ev(expr).catch(() => false), {timeout: n ? n * 250 : 15000, step: 250});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
  const VIEWS = [
    ['list', `l/${L}`, `!!document.querySelector('#view .trow[data-id="${T}"]')`],
    ['task', `t/${T}`, `(document.querySelector('#detail #d-title')?.value || '') === 'Buy paint'`],
    ['chat', `team/${RID}`, `[...document.querySelectorAll('#tc-msgs .cbub')].some(x => /Hello studio/.test(x.textContent))`],
  ];
  // in the window: wait (in the page, every 2 ms) for its content, then the numbers of this start
  const probe = cond => `new Promise(res => { const t0 = Date.now(); const f = () => { let on = false; try { on = ${cond}; } catch { /* not yet */ }
    if (on || Date.now() - t0 > 15000) { const n = performance.getEntriesByType('navigation')[0] || {}, st = performance.getEntriesByType('resource').filter(x => /\\/api\\/state(\\?|$)/.test(x.name));
      const m = performance.getEntriesByName('kalmido:drawn')[0], s0 = performance.getEntriesByName('kalmido:snap')[0];
      res({ok: on, ready: Math.round(performance.now()), drawn: m ? Math.round(m.startTime) : null, scripts: Math.round(n.domInteractive || 0), state: st.length ? Math.round(st[0].responseEnd - st[0].startTime) : null,
        stateStart: st.length ? Math.round(st[0].startTime) : null, sw: !!navigator.serviceWorker?.controller,
        js: (() => { const j = performance.getEntriesByType('resource').filter(x => /\\/static\\/(js\\/|i18n)/.test(x.name) && x.startTime < (n.domInteractive || 1e9)); return {n: j.length, start: Math.round(Math.min(...j.map(x => x.startTime))), end: Math.round(Math.max(...j.map(x => x.responseEnd))), kb: Math.round(j.reduce((a, x) => a + (x.decodedBodySize || 0), 0) / 1024)}; })(), stateEnd: st.length ? Math.round(st[0].responseEnd) : null, snap: s0 ? Math.round(s0.startTime) : null}); }
    else setTimeout(f, 2); }; f(); })`;

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const evIn = async (c, expr) => { const x = await cmd('script.evaluate', {expression: expr, target: {context: c}, awaitPromise: true, resultOwnership: 'none', serializationOptions: {maxObjectDepth: 6}}); if (x.type === 'exception') throw new Error('JS: ' + x.exceptionDetails.text); const u = v => !v ? v : v.type === 'array' ? v.value.map(u) : v.type === 'object' ? Object.fromEntries(v.value.map(([k, y]) => [typeof k === 'string' ? k : u(k), u(y)])) : v.value; return u(x.result); };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    // the main window; a second load so the service worker serves the files (like every day)
    await nav(B + '#today'); await until(ev, `typeof S !== 'undefined' && S.booted`); await sleep(1500);
    await nav(B + '#today'); await until(ev, `typeof S !== 'undefined' && S.booted`); await sleep(1500);
    const main = await ev(probe(`S.booted && !!document.querySelector('#view')`));
    console.log(`p2145_b_ui: main window: scripts ${main.scripts} ms, state ${main.state} ms (ends at ${main.stateEnd} ms), drawn ${main.drawn} ms`);

    const nonce = await ev(`sessionStorage.getItem('kalmido-mwn') || ''`);
    check(/^[0-9a-f]{32}$/.test(nonce), '#2875: the main window holds a nonce for the channel ' + nonce);
    const open = async (hash, cond, inherit = true) => {
      const c = (await cmd('browsingContext.create', {type: 'tab'})).context;
      await cmd('browsingContext.setViewport', {context: c, viewport: {width: 440, height: 720}});
      if (inherit) {  // 2.306.0 D4 (#2875): a window opened by window.open copies the opener's sessionStorage (the nonce of the channel)
        await cmd('browsingContext.navigate', {context: c, url: B + 'static/icon.svg', wait: 'complete'});
        await evIn(c, `sessionStorage.setItem('kalmido-mwn', ${JSON.stringify(nonce)})`);
      }
      await cmd('browsingContext.navigate', {context: c, url: B + '?mini=1#' + hash, wait: 'interactive'});
      const m = await evIn(c, probe(cond));
      return [c, m];
    };
    const res = {};
    for (const [k, hash, cond] of VIEWS) {
      res[k] = [];
      for (let i = 0; i < RUNS; i++) {
        const [c, m] = await open(hash, cond);
        res[k].push(m);
        await sleep(300);
        await cmd('browsingContext.close', {context: c});
      }
      const rd = res[k].map(m => m.ready), all = res[k].every(m => m.ok);
      console.log(`p2145_b_ui: ${k} window: usable after ${rd.join(' / ')} ms (median ${median(rd)}); scripts ${res[k].map(m => m.scripts).join(' / ')} ms; state request ${res[k].map(m => m.state ?? '-').join(' / ')} ms (ends ${res[k].map(m => m.stateEnd ?? '-').join(' / ')}); snapshot at ${res[k].map(m => m.snap ?? '-').join(' / ')} ms, drawn at ${res[k].map(m => m.drawn ?? '-').join(' / ')} ms; sw ${res[k][0].sw}; script files ${JSON.stringify(res[k].map(m => m.js))}`);
      check(all, `#2424: the ${k} window shows its content ` + JSON.stringify(res[k]));
      check(median(rd) < 3000, `#2424: the ${k} window is usable within 3 s (median ${median(rd)} ms)`);
      // the first picture comes from the main window: no state request before it (the full load runs behind it)
      check(res[k].every(m => m.snap != null && m.drawn != null && (m.stateStart == null || m.stateStart >= m.snap)), `#2424: the ${k} window draws from the main window's state first ` + JSON.stringify(res[k].map(m => [m.snap, m.drawn, m.stateStart])));
    }
    // the windows work: a list window ticks a task off, a task window renames, a change in the main window arrives live
    {
      const [c] = await open(`l/${L}`, VIEWS[0][2]);
      await sleep(500);
      const tick = await evIn(c, `(() => { const b = document.querySelector('#view .trow[data-id="${T2}"] .chk, #view .trow[data-id="${T2}"] [data-act="toggle"]'); if (!b) return false; b.click(); return true; })()`);
      check(tick, '#2424: the list window has the tick box');
      let done = false;
      for (let i = 0; i < 30 && !done; i++) { await sleep(200); done = ((await call(CA, "GET", `/api/tasks/${T2}`)).status === 2); }
      check(done, '#2424: a task ticked off in the list window is done on the server');
      await call(CA, 'POST', '/api/tasks', {title: 'Added in the main window', list_id: L});
      check(await until(o => evIn(c, `[...document.querySelectorAll('#view .trow')].some(x => /Added in the main window/.test(x.textContent))`), 50), '#2424: a change from elsewhere arrives live in the list window');
      await shot('p2145b-list.png');
      await cmd('browsingContext.close', {context: c});
    }
    {
      const [c] = await open(`t/${T}`, VIEWS[1][2]);
      await sleep(500);
      await evIn(c, `(() => { const t = document.querySelector('#detail #d-title'); t.focus(); t.value = 'Buy blue paint'; t.dispatchEvent(new Event('input', {bubbles: true})); t.blur(); t.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
      let ttl = '';
      for (let i = 0; i < 30 && ttl !== 'Buy blue paint'; i++) { await sleep(200); ttl = (await call(CA, 'GET', `/api/tasks/${T}`)).title; }
      check(ttl === 'Buy blue paint', '#2424: the task window renames the task: ' + ttl);
      await call(CA, 'PATCH', `/api/tasks/${T}`, {title: 'Buy green paint'});
      check(await until(o => evIn(c, `(document.querySelector('#detail #d-title')?.value || '') === 'Buy green paint'`), 50), '#2424: a change from elsewhere arrives live in the task window');
      await shot('p2145b-task.png');
      await cmd('browsingContext.close', {context: c});
    }
    {
      const [c] = await open(`team/${RID}`, VIEWS[2][2]);
      await sleep(500);
      const pm = await call(CB, 'POST', `/api/team/rooms/${RID}/messages`, {body: 'Second message'});  // someone else writes
      const live = await until(o => evIn(c, `[...document.querySelectorAll('#tc-msgs .cbub')].some(x => /Second message/.test(x.textContent))`), 50);
      check(live, '#2424: a new message arrives live in the chat window ' + (live ? '' : JSON.stringify({post: pm.http, dbg: await evIn(c, `JSON.stringify({hidden: document.hidden, editing: editing(), mod: S.route.mod, rid: S.tc.rid, sig: S.teamSig, act: document.activeElement?.id, n: document.querySelectorAll('#tc-msgs .cbub').length, cw: !!S.cw?.lt})`)})));
      await shot('p2145b-chat.png');
      await cmd('browsingContext.close', {context: c});
    }
    // the main window answers only the same person, with ciphers-only text like the offline cache
    {
      const c = (await cmd('browsingContext.create', {type: 'tab'})).context;
      await cmd('browsingContext.navigate', {context: c, url: B + 'static/icon.svg', wait: 'complete'});
      const ask = (uid, nn = nonce) => evIn(c, `new Promise(res => { const ch = new BroadcastChannel('kalmido-mini-state'); let got = null; ch.onmessage = e => { if (e.data && e.data.re === 'q${uid}') got = e.data; };
        ch.postMessage({ask: 'q${uid}', uid: ${uid}, nonce: ${JSON.stringify(nn)}}); setTimeout(() => { ch.close(); res(got ? {uid: got.uid, len: got.state.length, tasks: JSON.parse(got.state).tasks.length} : null); }, 600); })`);
      const me = await ev(`S.me.id`);
      check(await ask(me + 1000) == null, '#2424: another person gets no answer');
      check(await ask(me, '') == null && await ask(me, 'f'.repeat(32)) == null, '#2875: without the nonce of the main window the same person gets no answer either');
      const a = await ask(me);
      check(a && a.uid === me && a.tasks > 900, '#2424: the same person gets the main window\'s state ' + JSON.stringify(a));
      await cmd('browsingContext.close', {context: c});
    }
    // no main window: the own window starts the normal way
    await nav(B + 'static/icon.svg');
    {
      const [c, m] = await open(`l/${L}`, VIEWS[0][2], false);
      console.log(`p2145_b_ui: list window without a main window: usable after ${m.ready} ms, state request ${m.state ?? '-'} ms`);
      check(m.ok && m.snap == null, '#2424: without a main window the list window still shows its content (the normal start) ' + JSON.stringify(m));
      await cmd('browsingContext.close', {context: c});
    }
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
