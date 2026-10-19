// 2.119.0 UI tests, part B (#2301 #2302 #2210): switched-on icon buttons are filled shapes (pin, priority flag, lock, bells), the
// key hint of the chats is a line under the field (also in the narrow side panel), the dialog "All people …" has an Agents
// section with pins (side_agents) for iPhones. jsdom for the dialog, then Firefox (ff.js) at 390 and 1280 px, dark + light.
// Own container (start.sh). P2119B_NOSTART=1: an app already running.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2119_b_ui', check, shots: 'P2119B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2119B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Object.assign(j, {status: r.status}); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,collab,stats,time,progress,agents,comments';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: ALL});
  const L = (await call('POST', '/api/lists', {name: 'Work'})).id;
  const mkAgent = async (u, n) => { const a = await call('POST', '/api/admin/agents', {scopes: ['write'], username: u, display_name: n}); const l = (await call('POST', '/api/lists', {name: 'Work of ' + n})).id; await call('PUT', `/api/lists/${l}/members`, {user_id: a.id, role: 'edit'}); return {id: a.id, tok: a.token}; };
  const AG = await mkAgent('pinbot', 'PinBot');
  const T = (await call('POST', '/api/tasks', {title: 'Pinned task', list_id: L, priority: 5})).id;
  await call('PATCH', `/api/tasks/${T}`, {pinned: 1});

  // ================= #2210: the Agents section in the dialog "All people …"
  let w = await boot({user: 'alice', hash: 'inbox'}), d = w.document;
  check(await until(() => d.querySelector('#side .sbpall[data-act="sb-people"]')), '"All people …" is there with only an agent to show');
  w.eval('sbp_dialog()');
  const md = await until(() => d.querySelector('.modal.sbpmd'));
  const pin = () => d.querySelector(`.modal.sbpmd .mrow[data-aid="${AG.id}"] [data-sbp="apin"]`);
  check(md && /Agents/.test(md.querySelector('.sbph')?.textContent || '') && pin(), 'the dialog has the section Agents with PinBot');
  check(pin()?.getAttribute('aria-pressed') === 'false', 'not pinned: aria-pressed false');
  click(w, pin());
  check(await until(async () => (await call('GET', '/api/state')).settings.side_agents === String(AG.id)), 'pin: stored as side_agents');
  check(await until(() => pin()?.getAttribute('aria-pressed') === 'true' && pin().classList.contains('on')), 'the pin shows pressed');
  check(await until(() => d.querySelector(`#side .sg-team [data-aid="${AG.id}"]`)), 'the agent stands in the sidebar');
  click(w, pin());
  check(await until(async () => (await call('GET', '/api/state')).settings.side_agents === ''), 'unpin: side_agents empty');
  check(await until(() => !d.querySelector(`#side .sg-team [data-aid="${AG.id}"]`)), 'the agent is gone from the sidebar again');
  w.close();

  // ================= Firefox: real layout
  for (const touch of [true, false]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.ok)`), 'login in Firefox');
      let nr = 0;
      for (const [vw, vh] of touch ? [[390, 844]] : [[1280, 800]]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
        for (const theme of ['dark', 'light']) {
          await nav(B + 'static/icon.svg');
          await ev(`(() => { localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
          await nav(B + '?v=' + (++nr) + '#inbox');
          for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300);
          await ev(`(() => { openDetail(${T}); return 1; })()`); await sleep(1200);
          const f = await ev(`(() => { const q = s => document.querySelector('#detail ' + s), fl = e => e ? getComputedStyle(e.querySelector('svg path')).fill : '';
            return {pin: fl(q('[data-act="pin"]')), pinOn: !!q('[data-act="pin"].on'), prio: fl(q('[data-act="prio"]')), doc: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1}; })()`);
          check(f.pinOn && f.pin !== 'none' && f.prio !== 'none' && f.doc, `${vw}px ${theme}: the pin and the priority flag are filled ${JSON.stringify(f)}`);
          await call('PATCH', `/api/tasks/${T}`, {pinned: 0, priority: 0});
          await ev(`(() => { openDetail(${T}); return 1; })()`); await sleep(800);
          const g = await ev(`(() => { const e = document.querySelector('#detail [data-act="pin"] svg path'); return e ? getComputedStyle(e).fill : 'x'; })()`);
          check(g === 'none' || g === 'x', `${vw}px ${theme}: unpinned = outline ${g}`);
          await call('PATCH', `/api/tasks/${T}`, {pinned: 1, priority: 5});
          // #2302: the chat panel: the hint is a line under the field (not on touch devices)
          await ev(`(() => { chatOpen(${AG.id}); return 1; })()`); await sleep(1500);
          const h = await ev(`(() => { const e = document.querySelector('.chcomp .chkh'), t = document.querySelector('.chcomp textarea');
            return {txt: e ? e.textContent.trim() : null, vis: !!(e && e.offsetWidth), below: !!(e && t && e.getBoundingClientRect().top >= t.getBoundingClientRect().bottom - 1)}; })()`);
          if (touch) check(!h.vis, `${vw}px ${theme}: no key hint on a touch device ${JSON.stringify(h)}`);
          else check(/(Ctrl|Cmd)\+Enter sends/.test(h.txt || '') && h.vis && h.below, `${vw}px ${theme}: the key hint stands under the chat field ${JSON.stringify(h)}`);
          await shot(`p2119b-chat-${vw}-${theme}.png`);
        }
      }
    }, touch);
  }
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
