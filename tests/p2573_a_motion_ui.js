// 2.573.0 (#4763) UI: from 768 px showing and hiding moves briefly like on a phone.
// kalmido-suite: fresh
// app.css block "2.573.0 (#4763)", sheetmotion.js an_desk / an_panelOut / an_play: the side panel slides in and out, the sidebar glides in when it unfolds, menus (#pop) and the
// date picker (.dpop) pop up and fade, the toast slides in and fades, the rows of an opened task roll in. Closing keeps the node only
// for its exit: gone after at most 300 ms (measured in the page, waiting for the state, never a fixed time). With reduced motion
// nothing moves and closing removes at once. Own container (start.sh), Firefox at 1280 px with a mouse; alice (organisation) and
// frida (no organisation) run every check.
// freelancer-matrix: tasks (frida without an organisation opens, folds and closes the same panels)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const ffmod = require('./ff');
const moving = ffmod({tag: 'p2573_a_motion_ui', check, shots: 'P2573A_SHOTS', prefs: [['ui.prefersReducedMotion', 0]]});
const still = ffmod({tag: 'p2573_a_still_ui', check, shots: 'P2573A_SHOTS'});  // the ff.js default: reduced motion
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2573A_NOSTART !== '1' && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };

// in the page: ms until cond() holds (polled every 5 ms), -1 after 2 s
const GONE = cond => `new Promise(res => { const t0 = performance.now(); const f = () => { let c = false; try { c = (${cond})(); } catch { /* not yet */ }
  if (c) res(Math.round(performance.now() - t0)); else if (performance.now() - t0 > 2000) res(-1); else setTimeout(f, 5); }; f(); })`;
const anim = sel => `(() => { const e = document.querySelector('${sel}'); return e ? getComputedStyle(e).animationName : ''; })()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Nordwind', lang: 'en', modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});
  check(fr.http < 300, 'setup: frida (no organisation) ' + fr.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const data = {};
  for (const [who, ck] of [['alice', CA], ['frida', CF]]) {
    const L = (await call(ck, 'POST', '/api/lists', {name: 'Motion ' + who})).id;
    const P = (await call(ck, 'POST', '/api/tasks', {title: 'Parent task', list_id: L})).id;
    const K = (await call(ck, 'POST', '/api/tasks', {title: 'Child task', list_id: L, parent_id: P})).id;
    check(L && P && K, `${who}: list, task and subtask`);
    data[who] = {L, P, K};
  }

  const open = async (o, who) => {
    const {cmd, ev, ctx, nav, until, idle} = o, {L, P, K} = data[who];
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${who}', password: 'password123'})}).then(r => r.status)`);
    await nav(B);
    await until(`typeof an_desk === 'function' && S.booted && !!keyToHash`, {timeout: 30000});
    await ev(`(() => { location.hash = keyToHash('l:${L}'); return 1; })()`);
    const shown = await until(`!!document.querySelector('#view .trow[data-id="${P}"]') && !!document.querySelector('#view .trow[data-id="${K}"]')`, {timeout: 20000});
    check(!!shown, `${who}: the list shows the task and its subtask`);
    await idle();
    return {P, K};
  };

  // ---- motion allowed
  for (const who of ['alice', 'frida']) await moving(async o => {
    const {ev, until} = o, tag = `${who} 1280px moving`;
    const {P, K} = await open(o, who);
    check(await ev(`an_desk() && !isMobile()`), `${tag}: motion is on from 768 px`);

    // 1) the side panel
    await ev(`(() => { openDetail(${P}); return 1; })()`);
    check(await ev(anim('#detail')) === 'an_pin', `${tag}: the side panel slides in (${await ev(anim('#detail'))})`);
    await until(`!document.getAnimations().some(a => a.playState === 'running')`, {timeout: 3000});
    const out = await ev(`(() => { const d = document.querySelector('#detail'), w = d.getBoundingClientRect().width; closeDetail();
      const cs = getComputedStyle(d); return {out: d.classList.contains('an-out'), inert: d.hasAttribute('inert'), pos: cs.position, name: cs.animationName, w, w2: d.getBoundingClientRect().width,
        grid: document.querySelector('#app').classList.contains('detail-open')}; })()`);
    check(out.out && out.inert && out.pos === 'fixed' && out.name === 'an_pout', `${tag}: closing, the panel stays pinned for its exit ${JSON.stringify(out)}`);
    check(Math.abs(out.w - out.w2) < 2 && !out.grid, `${tag}: pinned at its width while the list takes the room ${JSON.stringify(out)}`);
    const tD = await ev(GONE(`() => { const d = document.querySelector('#detail'); return !d.classList.contains('an-out') && getComputedStyle(d).display === 'none' && !d.style.width; }`));
    check(tD >= 0 && tD <= 300, `${tag}: the panel is gone after at most 300 ms (${tD} ms)`);
    // opened again while it leaves: one panel, back in the grid
    const again = await ev(`(async () => { openDetail(${P}); await new Promise(r => setTimeout(r, 0)); closeDetail(); openDetail(${P}); await Promise.resolve();  // the #app observer runs before the next paint
      const d = document.querySelector('#detail'); return {out: d.classList.contains('an-out'), pos: getComputedStyle(d).position, hid: d.classList.contains('hidden')}; })()`);
    check(!again.out && !again.hid && again.pos !== 'fixed', `${tag}: opened again while leaving, the panel is back in its column ${JSON.stringify(again)}`);
    await ev(`(() => { closeDetail(); return 1; })()`);
    await ev(GONE(`() => !document.querySelector('#detail.an-out')`));

    // 2) the sidebar unfolds
    await ev(`(() => { document.querySelector('#app').classList.add('side-rail'); return 1; })()`);
    await ev(`(() => { document.querySelector('#app').classList.remove('side-rail'); return 1; })()`);
    check(await until(`document.querySelector('#side').classList.contains('an-sin')`, {timeout: 1000}) && await ev(anim('#side')) === 'an_sin', `${tag}: the sidebar glides in`);
    const tS = await ev(GONE(`() => !document.querySelector('#side').classList.contains('an-sin')`));
    check(tS >= 0 && tS <= 300, `${tag}: the sidebar's class goes after at most 300 ms (${tS} ms)`);
    await ev(`(() => { fitLayout(); return 1; })()`);

    // 3) a menu and the date picker
    await ev(`(() => { openPop(document.querySelector('#view .trow[data-id="${P}"]'), '<button type="button">x</button>'); return 1; })()`);
    check(await ev(anim('#pop')) === 'an_mpop', `${tag}: the menu pops up (${await ev(anim('#pop'))})`);
    const pop = await ev(`(async () => { closePop(); await Promise.resolve(); const p = document.querySelector('#pop'); return {hid: p.classList.contains('hidden'), out: p.classList.contains('an-out'), disp: getComputedStyle(p).display, name: getComputedStyle(p).animationName}; })()`);
    check(pop.hid && pop.out && pop.disp === 'block' && pop.name === 'an_mpopout', `${tag}: the closed menu fades out ${JSON.stringify(pop)}`);
    const tP = await ev(GONE(`() => getComputedStyle(document.querySelector('#pop')).display === 'none'`));
    check(tP >= 0 && tP <= 300, `${tag}: the menu is gone after at most 300 ms (${tP} ms)`);
    await ev(`(() => { dpOpen(document.querySelector('#view .trow[data-id="${P}"]'), {kind: 'date', value: ''}); return 1; })()`);
    check(await ev(anim('.dpop')) === 'an_mpop', `${tag}: the date picker pops up`);
    const dp = await ev(`(() => { dpClose(false); const e = document.querySelector('.dpop'); return {there: !!e, out: !!e && e.classList.contains('an-out')}; })()`);
    check(dp.there && dp.out, `${tag}: the closed date picker stays for its exit ${JSON.stringify(dp)}`);
    const tDp = await ev(GONE(`() => !document.querySelector('.dpop')`));
    check(tDp >= 0 && tDp <= 300, `${tag}: the date picker node is removed after at most 300 ms (${tDp} ms)`);

    // 4) the subtasks roll in when the task opens
    await ev(`(() => { document.querySelector('#view .trow[data-id="${P}"] .caret').click(); return 1; })()`);
    await until(`!document.querySelector('#view .trow[data-id="${K}"]')`, {timeout: 3000});
    await ev(`(() => { document.querySelector('#view .trow[data-id="${P}"] .caret').click(); return 1; })()`);
    const row = await until(`(() => { const r = document.querySelector('#view .trow[data-id="${K}"]'); return r && r.classList.contains('an-rowin') && getComputedStyle(r).animationName; })()`, {timeout: 3000});
    check(row === 'an_rowin', `${tag}: the opened subtask rolls in (${row})`);

    // 6) the toast
    await ev(`(() => { toast('Motion check'); return 1; })()`);
    check(await ev(anim('#toast')) === 'an_tin', `${tag}: the message slides in`);
    const t = await ev(`(async () => { const e = document.querySelector('#toast'); e.classList.add('hidden'); await Promise.resolve(); return {out: e.classList.contains('an-out'), disp: getComputedStyle(e).display}; })()`);
    check(t.out && t.disp === 'flex', `${tag}: the hidden message fades out ${JSON.stringify(t)}`);
    const tT = await ev(GONE(`() => getComputedStyle(document.querySelector('#toast')).display === 'none'`));
    check(tT >= 0 && tT <= 300, `${tag}: the message is gone after at most 300 ms (${tT} ms)`);
  }, false);

  // ---- reduced motion: nothing moves, closing removes at once
  for (const who of ['alice', 'frida']) await still(async o => {
    const {ev, until} = o, tag = `${who} 1280px reduced motion`;
    const {P} = await open(o, who);
    check(await ev(`!an_desk()`), `${tag}: motion is off`);
    await ev(`(() => { openDetail(${P}); return 1; })()`);
    await until(`!document.querySelector('#detail').classList.contains('hidden')`, {timeout: 2000});
    const d = await ev(`(() => { closeDetail(); const d = document.querySelector('#detail'); return {out: d.classList.contains('an-out'), pos: getComputedStyle(d).position}; })()`);
    check(!d.out && d.pos !== 'fixed', `${tag}: the panel does not wait for an exit ${JSON.stringify(d)}`);
    check(!!await until(`document.querySelector('#detail').classList.contains('hidden')`, {timeout: 1000}), `${tag}: the panel is hidden`);
    const p = await ev(`(async () => { openPop(document.querySelector('#view .trow[data-id="${P}"]'), '<button type="button">x</button>'); closePop(); await Promise.resolve(); const p = document.querySelector('#pop'); return {out: p.classList.contains('an-out'), disp: getComputedStyle(p).display}; })()`);
    check(!p.out && p.disp === 'none', `${tag}: the menu is gone at once ${JSON.stringify(p)}`);
    const dp = await ev(`(() => { dpOpen(document.querySelector('#view .trow[data-id="${P}"]'), {kind: 'date', value: ''}); dpClose(false); return !!document.querySelector('.dpop'); })()`);
    check(!dp, `${tag}: the date picker is removed at once`);
    const t = await ev(`(async () => { toast('Still'); const e = document.querySelector('#toast'); e.classList.add('hidden'); await Promise.resolve(); return {out: e.classList.contains('an-out'), disp: getComputedStyle(e).display}; })()`);
    check(!t.out && t.disp === 'none', `${tag}: the message is gone at once ${JSON.stringify(t)}`);
  }, false);

  console.log(`p2573_a_motion_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error('Error', e); process.exit(1); });
