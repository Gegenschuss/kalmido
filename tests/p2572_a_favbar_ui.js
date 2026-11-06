// 2.572.0 (#4746) UI tests (Firefox, a computer), fresh DB: in the head bar the SEARCH gives way first when favourites need room
// - the order of the steps: full search (12rem) -> shrinks smoothly (down to 7rem) -> only the loupe -> only then "+N"
// - 1280 and 1024 px with 3 / 9 / 15 favourites; a sweep of widths: the steps only ever go on, never back and forth
// - few favourites: no loupe; the loupe still opens the search
// kalmido-suite: fresh
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2572_a_favbar_ui', check, shots: 'P2572_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const KEYS = ['v:inbox', 'v:assigned', 'v:today', 'v:tomorrow', 'v:week', 'v:doable', 'v:pinned', 'v:waiting', 'v:mine_wait', 'v:stale', 'v:all', 'v:done', 'v:trash', 'm:matrix', 'm:cal'];

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'cal,matrix'});
  const signIn = async o => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(async () => { localStorage.clear(); sessionStorage.clear(); return (await fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})})).status; })()`);
    await sleep(400);
    await o.nav(B + '#today');
  };
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // 0 full, 1 shrunk, 2 loupe, 3 loupe + "+N"
  const STATE = `(() => { const k = document.querySelector('#kbar'), s = k.querySelector('.kbsrch').getBoundingClientRect(), m = k.querySelector('.fv2-more'), px = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
    const mini = k.classList.contains('kb-mini'), more = !!m && !m.hidden, w = s.width / px;
    return JSON.stringify({mini, more, w, tiles: [...k.querySelectorAll('.fv2-tile')].filter(x => !x.hidden).length, phase: more ? 3 : mini ? 2 : w < 11.9 ? 1 : 0}); })()`;
  const st = async ev => JSON.parse(await ev(STATE));
  await firefox(async o => {
    const {ev, cmd, ctx, shot} = o;
    const set = async (n, width) => {
      await call('PATCH', '/api/settings', {fav_items: KEYS.slice(0, n)});
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height: 800}});
      await signIn(o);
      check(await ready(ev, `document.querySelectorAll('#kbar .fv2-tile').length === ${n}`), `${width}px, ${n} favourites drawn`);
      await sleep(400);
    };
    for (const width of [1280, 1024]) {
      let last = null;
      for (const n of [3, 9, 15]) {
        await set(n, width);
        const s = await st(ev);
        check(s.mini ? Math.abs(s.w - 30 / 16) < .3 : s.w <= 12.05 && s.w >= 6.95, `${width}px/${n}: the search is 12rem..7rem or the loupe ` + JSON.stringify(s));
        check(!s.more || s.mini, `${width}px/${n}: "+N" only after the loupe ` + JSON.stringify(s));
        if (s.phase === 1) check(s.tiles === n, `${width}px/${n}: the search is narrower and every favourite still stands ` + JSON.stringify(s));
        if (n === 3) check(s.phase === 0 && s.w > 11.9, `${width}px/3: few favourites: the full search, no loupe ` + JSON.stringify(s));
        if (last) check(s.phase >= last.phase, `${width}px/${n}: more favourites never bring the search back ` + JSON.stringify([last, s]));
        last = s;
        if (n === 15) await shot(`p2572-${width}.png`);
      }
    }
    // a sweep of widths with 15 favourites: the steps only ever go on and the shrink step exists
    await set(15, 1100);
    let prev = -1, seen = new Set(), mono = true;
    for (let w = 1100; w >= 840; w -= 10) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: 800}});
      await sleep(150);
      const s = await st(ev); seen.add(s.phase);

      if (s.phase < prev || (s.more && !s.mini)) { mono = false; console.log('sweep', w, JSON.stringify(s)); }
      prev = s.phase;
    }
    check(mono, 'sweep: 1100 -> 840 px: full -> shrunk -> loupe, never back and forth');
    check(seen.has(0) && seen.has(1) && seen.has(2), 'sweep: full, shrunk and loupe all occur ' + [...seen]);
    // the loupe still opens the search
    await ev(`document.querySelector('#kbar .kbsrch').click()`);
    check(await ready(ev, `!!document.querySelector('#pal, .palette, [role="dialog"] input, input[type="search"]')`, 20), 'the loupe opens the search');
  });
  console.log(`p2572_a_favbar_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('CRASH', e); process.exit(1); });
