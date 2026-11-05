// 2.534.0 A (#4551) UI test, own container (start.sh, isolated test database), Firefox with a mouse. Invented data only.
// kalmido-suite:
// One width system for wide screens: four widths in :root (--w-lesen 46rem, --w-form 40rem, --w-seite 96rem, --w-voll none).
// Measured at 1920 x 1080 and 3840 x 1600 in the content area (#view without its padding and scroll bar):
// - Start (.dash), the office (.ofwrap) and a project list (.lwrap) are at most --w-seite wide and stand in the middle;
//   at 3840 the limit holds (narrower than the content area: before, the list was as wide as the area, Start / office 72rem)
// - the board of a project (.kanban) uses the full width (--w-voll)
// - the team chat: the messages (own ones right, the other's left) stay inside a reading column of --w-lesen in the middle
// - 2.552.0 (#4552): from 1920 more than one column of tiles on Start / Projects start, board columns 18 to 28rem, 390 px one column
// - 1440 x 900 and 390 x 844: the pages fill the content area as before (the widths are only upper limits), no sideways overflow
// Screenshots (P2534A_SHOTS) at 1440, 1920, 2560 and 3840, light and dark.
// freelancer-matrix: Breiten (alice has no organisation; the widths do not depend on the workspace)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2534_a_breite_ui', check, shots: 'P2534A_SHOTS'});
const FEAT = 'office,contacts,kanban,collab';  // collab: the team chat
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body, ck = CA) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['office', 'contacts']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'alice: no organisation (person on her own)');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab'}, CB);

  const L = (await call('POST', '/api/lists', {name: 'Website relaunch', kind: 'project'})).id;
  const K = (await call('POST', '/api/lists', {name: 'Shoot plan', kind: 'project'})).id;
  const titles = ['Write the brief', 'Book the studio', 'Cast two actors', 'Order the props', 'Plan the light', 'Cut the trailer'];
  for (const [i, t] of titles.entries()) {
    await call('POST', '/api/tasks', {title: t, list_id: L, due: `2026-11-${String(10 + i).padStart(2, '0')}`, priority: [0, 1, 3, 5][i % 4]});
    await call('POST', '/api/tasks', {title: t + ' (board)', list_id: K});
  }
  await call('PATCH', `/api/lists/${K}`, {view: 'kanban'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});  // a direct chat needs someone I work with
  const dm = await call('POST', '/api/team/dm', {user_id: BOB}), RID = dm.id || dm.room?.id;
  check(!!RID, 'a direct chat with Bob');
  for (let i = 0; i < 4; i++) {
    await call('POST', `/api/team/rooms/${RID}/messages`, {body: `Bob here: question number ${i + 1} about the shoot on Friday, do we have the light?`}, CB);
    await call('POST', `/api/team/rooms/${RID}/messages`, {body: `Alice: answer ${i + 1}, yes, the studio has everything we need.`});
  }

  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    // the four widths, once
    await nav(B + '#home');
    await until(`!!S.booted && !!document.querySelector('#view .dash')`);
    const vars = await ev(`(() => { const s = getComputedStyle(document.documentElement); return ['--w-lesen', '--w-form', '--w-seite', '--w-voll'].map(k => s.getPropertyValue(k).trim()).join(' '); })()`);
    check(vars === '46rem 40rem 96rem none', 'the four widths in :root ' + vars);

    // the box of the content area and of one element (px); rem = the root font size
    const MEASURE = sel => `(() => { const v = document.querySelector('#view'), e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null;
      const cs = getComputedStyle(v), vr = v.getBoundingClientRect(), l = vr.left + parseFloat(cs.paddingLeft), r = vr.left + v.clientWidth - parseFloat(cs.paddingRight), b = e.getBoundingClientRect();
      return {l: b.left - l, r: r - b.right, w: b.width, area: r - l, rem: parseFloat(getComputedStyle(document.documentElement).fontSize), over: v.scrollWidth - v.clientWidth}; })()`;
    const PAGES = [
      ['start', '#home', '#view .dash', 'seite'],
      ['office', '#office', '#view .ofwrap', 'seite'],
      ['list', '#l/' + L, '#view .lwrap', 'seite'],
      ['board', '#l/' + K, '#view .kanban', 'voll'],
    ];
    for (const [vw, vh] of [[390, 844], [1440, 900], [1920, 1080], [2560, 1440], [3840, 1600]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      for (const [name, hash, sel, kind] of PAGES) {
        if (name === 'office' && vw < 768) continue;  // the phone shows the office without its frame (.ofwrap is the computer's)
        await nav(B + '?w=' + vw + hash);
        const m = await until(`!!S.booted && !!document.querySelector(${JSON.stringify(sel)}) && (${MEASURE(sel)})`);
        if (!m) { check(false, `${vw}px ${name}: ${sel} shows`); continue; }
        const lim = kind === 'seite' ? Math.min(m.area, 96 * m.rem) : m.area;  // the phone's board runs out to the screen edges (as before)
        check(kind === 'voll' ? m.w >= lim - 2 : Math.abs(m.w - lim) <= 2, `${vw}px ${name}: width ${kind} = ${Math.round(lim)} px ` + JSON.stringify(m));
        check(Math.abs(m.l - m.r) <= 2, `${vw}px ${name}: in the middle (left = right) ` + JSON.stringify(m));
        check(m.over <= 1, `${vw}px ${name}: no sideways overflow ` + JSON.stringify(m));
        if (vw === 3840 && kind === 'seite') check(m.w > 96 * m.rem - 2 && m.area - m.w > 2, `${vw}px ${name}: limited (narrower than the content area) ` + JSON.stringify(m));
        if (vw >= 1440) for (const theme of ['light', 'dark']) {
          await ev(`(() => { document.documentElement.dataset.theme = ${JSON.stringify(theme)}; return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1)))); })()`);  // painted before the shot
          await shot(`p2534a-${name}-${vw}-${theme}.png`);
        }
      }
      // 2.552.0 (#4552): tiles in a grid by the space (auto-fill, 22rem), board columns grow up to 28rem
      const COLS = sel => `(() => { const e = [...document.querySelectorAll(${JSON.stringify(sel)})].filter(x => x.offsetWidth); if (e.length < 2) return null; return new Set(e.map(x => Math.round(x.getBoundingClientRect().left))).size; })()`;
      for (const [name, hash, sel] of [['start', '#home', '#view .dash .dcard'], ['projects start', '#projects', '#view .pstart .psg']]) {
        await nav(B + '?w=' + vw + hash);
        const n = await until(`!!S.booted && (${COLS(sel)})`).catch(() => null);
        if (!n) { if (name === 'start') check(false, `${vw}px ${name}: tiles show`); continue; }  // the projects start may hold a single group
        if (vw >= 1920) check(n > 1, `${vw}px ${name}: more than one column (${n})`);
        if (vw < 768) check(n === 1, `${vw}px ${name}: one column (${n})`);
      }
      await nav(B + '?w=' + vw + '#l/' + K);
      const kc = await until(`!!S.booted && (() => { const c = [...document.querySelectorAll('#view .kcol')].filter(x => x.offsetWidth); return c.length ? c.map(x => x.getBoundingClientRect().width).concat([parseFloat(getComputedStyle(document.documentElement).fontSize)]) : null; })()`);
      if (kc) { const rem = kc.pop(); check(Math.max(...kc) <= 28 * rem + 1 && Math.min(...kc) >= 18 * rem - 1, `${vw}px board: columns between 18rem and 28rem ` + JSON.stringify(kc)); }
      else check(false, `${vw}px board: columns show`);
      // the team chat: the messages of both sides inside the reading column in the middle of the room
      await nav(B + '?w=' + vw + '#team/' + RID);
      const c = await until(`(() => { const box = document.querySelector('#view .tcmsgs'), ms = [...document.querySelectorAll('#view .tcmsgs .cmsg')].filter(x => x.offsetWidth); if (!box || ms.length < 8) return null;
        const b = box.getBoundingClientRect(), cs = getComputedStyle(box), l = b.left + parseFloat(cs.borderLeftWidth), r = l + box.clientWidth, rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
        const L = Math.min(...ms.map(x => x.getBoundingClientRect().left)), R = Math.max(...ms.map(x => x.getBoundingClientRect().right));
        return {l: L - l, r: r - R, spread: R - L, room: r - l, rem}; })()`);
      if (!c) check(false, `${vw}px team chat: the messages show`);
      else if (c.room > 46 * c.rem + 24) {
        check(c.spread <= 46 * c.rem + 1, `${vw}px team chat: own and other messages within --w-lesen ` + JSON.stringify(c));
        check(Math.abs(c.l - c.r) <= 2, `${vw}px team chat: the reading column in the middle ` + JSON.stringify(c));
      } else check(c.l >= 0 && c.r >= 0 && c.room - c.spread < 3 * c.rem, `${vw}px team chat: a narrow room keeps the messages at its edges as before ` + JSON.stringify(c));
      if (vw >= 1440) for (const theme of ['light', 'dark']) {
        await ev(`(() => { document.documentElement.dataset.theme = ${JSON.stringify(theme)}; return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1)))); })()`);  // painted before the shot
        await shot(`p2534a-chat-${vw}-${theme}.png`);
      }
    }
  }, false);

  console.log(`p2534_a_breite_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
