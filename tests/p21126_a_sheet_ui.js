// 2.1126.0 A UI test (Firefox with touch, phone 390 x 844), fresh DB, invented data only:
// kalmido-suite: fresh
// - #6049 menu sheets (#pop.sheet) close with one flick like a map app's sheet: the "More" menu of the tab bar, pulled up to
//   its full height, closes with ONE short quick flick down at its head (before 2.1126.0 a flick on a tall sheet only shrank
//   it); while the finger moves the sheet follows by transform only - its height is set at most once per drag, not per move
//   (before: style.height per frame down to 40 %, which stuttered).
// - a long menu: a pull down in its CONTENT closes it while the content stands at its top; scrolled down, a swipe down in the
//   content is the browser's (it scrolls, no touchmove taken, the menu stays); a swipe up in the content is the browser's
//   too; a short slow pull springs back (open, no transform left).
// - dialogs keep the head-only rule of #5078 (p2652_c_sheet_ui.js).
const {errs, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21126_a_sheet_ui', check, shots: 'P21126A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', whatsnew_on: '0'});

  await firefox(async ({cmd, ev, nav, ctx, drag, until, shot}) => {
    // one finger: down at (x0, y0), `steps` moves of `ms` each over dy in total, optional rest before letting go
    const swipe = (x0, y0, dy, steps, ms, rest = 0) => {
      const acts = [{type: 'pointerMove', x: Math.round(x0), y: Math.round(y0)}, {type: 'pointerDown', button: 0}];
      for (let i = 1; i <= steps; i++) acts.push({type: 'pointerMove', x: Math.round(x0), y: Math.round(y0 + dy * i / steps), duration: ms});
      if (rest) acts.push({type: 'pause', duration: rest});
      acts.push({type: 'pointerUp', button: 0});
      return cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'p1', parameters: {pointerType: 'touch'}, actions: acts}]})
        .then(() => cmd('input.releaseActions', {context: ctx}));
    };
    const POP = `document.getElementById('pop')`;
    const st = () => ev(`(() => { const p = ${POP}; if (!p || p.classList.contains('hidden') || !p.classList.contains('sheet')) return 'gone'; const r = p.getBoundingClientRect(); return {top: Math.round(r.top), h: Math.round(r.height), st: Math.round(p.scrollTop), tf: p.style.transform, drag: p.classList.contains('sd-drag'), pd: window.__pd || 0, hs: window.__hs || []}; })()`);
    // touchmoves the page took from the browser, and the inline height of the sheet at every move
    const watch = () => ev(`(() => { window.__pd = 0; window.__hs = []; if (!window.__pdOn) { window.__pdOn = 1; addEventListener('touchmove', e => { if (e.defaultPrevented) window.__pd++; const p = document.getElementById('pop'); window.__hs.push(p ? p.style.height : ''); }); } return 1; })()`);
    // settled: no animation, no drag, two reads alike
    const settle = async () => { let last = ''; return until(async () => { const s = await st(); const k = JSON.stringify(s); const same = k === last && (s === 'gone' || !s.drag && await ev(`${POP}.getAnimations().length === 0`)); last = k; return same ? s : false; }, {step: 150}); };

    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#today');
    await until(`typeof sd_start === 'function' && typeof menu === 'function' && !!document.querySelector('#view')`);

    // ---- the "More" menu of the tab bar
    check(await until(`!!document.querySelector('[data-act="tabs-more"]')`), 'the tab bar has its "More" button');
    await ev(`(() => { document.querySelector('[data-act="tabs-more"]').click(); return 1; })()`);
    const m0 = await settle();
    check(m0 && m0 !== 'gone' && m0.h > 100, 'the More menu opens as a sheet ' + JSON.stringify(m0));
    check(await ev(`${POP}.querySelectorAll('button, [role="menuitem"]').length >= 3 && ${POP}.innerText.trim().length > 10`), 'the More menu shows its entries');
    await shot('p21126a-more.png');
    // pull it up at the head (slow, then rest): taller, the finger followed by transform; height set at most once
    await watch();
    await swipe(195, m0.top + 12, -Math.min(400, m0.top - 20), 8, 40, 300);
    const m1 = await settle();
    check(m1 && m1 !== 'gone' && m1.h >= m0.h, `pulled up at the head the More menu is as tall or taller (${m0.h} -> ${m1 && m1.h})`);
    const hs1 = m1 && m1 !== 'gone' ? [...new Set(m1.hs.filter(Boolean))] : [];
    check(hs1.length <= 1, '#6049: the height did not change from move to move while pulling up ' + JSON.stringify(m1 && m1.hs));
    // one short quick flick down at the head from the full height: closed (before: only shrank to half)
    await watch();
    await swipe(195, m1.top + 12, 140, 3, 25);
    const m2 = await settle();
    check(m2 === 'gone', '#6049: one short flick down closes the More menu from its full height ' + JSON.stringify(m2));

    // ---- a long menu: the content
    const openLong = () => ev(`(() => { closePop(); menu(document.querySelector('#view'), Array.from({length: 60}, (_, i) => ({label: 'Entry ' + (i + 1), fn: () => { window.__picked = i + 1; }})), null, null, 'Long menu'); return 1; })()`);
    await openLong();
    const l0 = await settle();
    check(l0 && l0 !== 'gone' && l0.h > 400, 'the long menu opens as a sheet ' + JSON.stringify(l0));
    check(await ev(`${POP}.innerText.includes('Entry 1') && ${POP}.scrollHeight > ${POP}.clientHeight + 100`), 'the long menu shows its entries and scrolls');
    // scrolled down: a swipe down in the content is the browser's (no touchmove taken), the menu stays as it was
    await ev(`(() => { ${POP}.scrollTop = 400; return 1; })()`);
    const la = await settle(); await watch();
    await swipe(195, la.top + 200, 250, 5, 30, 200);
    const lb = await settle();
    check(lb !== 'gone' && lb.pd === 0 && Math.abs(lb.h - la.h) <= 1 && !lb.tf, '#6049: scrolled down, a swipe down in the content scrolls and keeps the menu ' + JSON.stringify([la, lb]));
    // back at the top: a swipe up in the content is the browser's (scrolls) too
    await ev(`(() => { ${POP}.scrollTop = 0; return 1; })()`);
    const lc = await settle(); await watch();
    await swipe(195, lc.top + lc.h * 0.7, -250, 5, 30, 200);
    const ld = await settle();
    check(ld !== 'gone' && ld.pd === 0 && Math.abs(ld.h - lc.h) <= 1, '#6049: a swipe up in the content scrolls and keeps the menu ' + JSON.stringify([lc, ld]));
    // a short slow pull down in the content at the top: springs back, open, nothing left over
    await ev(`(() => { ${POP}.scrollTop = 0; return 1; })()`);
    const le = await settle(); await watch();
    await swipe(195, le.top + 200, 40, 4, 60, 300);
    const lf = await settle();
    check(lf !== 'gone' && Math.abs(lf.h - le.h) <= 1 && !lf.tf && Math.abs(lf.top - le.top) <= 1, '#6049: a short slow pull in the content springs back ' + JSON.stringify([le, lf]));
    check(!(await ev(`window.__picked || 0`)), '#6049: the pull did not pick an entry');
    // a quick pull down in the content at the top: closed (like a map app's sheet), the finger followed by transform only
    await watch();
    await swipe(195, lf.top + 200, 220, 4, 20);
    const lg = await settle();
    check(lg === 'gone', '#6049: a quick pull down in the content standing at its top closes the menu ' + JSON.stringify(lg));
    check(!(await ev(`window.__picked || 0`)), '#6049: closing by a pull picked no entry');
    // opened again: its own height, no transform left
    await openLong();
    const lh = await settle();
    check(lh && lh !== 'gone' && Math.abs(lh.h - l0.h) <= 2 && !lh.tf, 'opened again the menu has its own height back ' + JSON.stringify([l0, lh]));
    await ev(`(() => { closePop(); return 1; })()`);
  }, true);

  check(!errs.length, 'no script errors: ' + errs.join(' | '));
  console.log(`p21126_a_sheet_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p21126_a_sheet_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
