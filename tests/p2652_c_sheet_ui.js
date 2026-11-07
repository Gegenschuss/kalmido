// 2.652.0 C UI test (Firefox with touch), fresh DB, invented data only:
// kalmido-suite: fresh
// - #5078 bottom sheets: only the grip / head (top 44 px) drags; a swipe in the content always scrolls. Phone (390 x 844):
//   a dialog with long content - swipe up / down in the scrolled content, hold, let go: no touchmove is taken from the browser
//   (so the browser scrolls; WebDriver touches do not pan, so the scroll itself is set by script), scrollTop and height stay
//   on release; a pull down in the content
//   scrolled to the top neither shrinks nor closes it (before: it closed); the head still swipes it closed. Tablet width with
//   touch (840 x 1100): a dialog is a centred card, a pull down in its content leaves it alone; the quick-add sheet still
//   closes with a swipe down at its head.
// - #5086 touch tablet (840, touch): the finger rules that stood at max-width:767px only - filter chips of the files (.tsp,
//   .tsfx), the spaces (.abspace), the roadmap chips and list rows (.rm-chips button, .rm-lrow) are 44 px high, the buttons of
//   a time entry (.terow .teacts) are fully visible without hover; the long-press rows of the office have
//   -webkit-touch-callout:none at the pointer (Firefox drops that property, so the stylesheet text is checked)
const {errs, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2652_c_sheet_ui', check, shots: 'P2652C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', whatsnew_on: '0'});

  await firefox(async ({cmd, ev, nav, ctx, drag, until}) => {
    // one finger: down, move by (dx, dy), hold still (no fling), let go
    const swipeHold = (x0, y0, dx, dy) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'p1', parameters: {pointerType: 'touch'},
      actions: [{type: 'pointerMove', x: Math.round(x0), y: Math.round(y0)}, {type: 'pointerDown', button: 0},
        {type: 'pointerMove', x: Math.round(x0 + dx / 2), y: Math.round(y0 + dy / 2), duration: 150},
        {type: 'pointerMove', x: Math.round(x0 + dx), y: Math.round(y0 + dy), duration: 150}, {type: 'pause', duration: 400}, {type: 'pointerUp', button: 0}]}]})
      .then(() => cmd('input.releaseActions', {context: ctx}));
    const CARD = `document.querySelector('.p2652c > .card')`;
    const st = () => ev(`(() => { const c = ${CARD}; if (!c) return null; const r = c.getBoundingClientRect(); return {top: Math.round(r.top), h: Math.round(r.height), st: Math.round(c.scrollTop), tf: c.style.transform, drag: c.classList.contains('sd-drag'), pd: window.__pd || 0}; })()`);
    // touchmoves the page took from the browser (drag.js prevents them while a drag runs; then the content does not scroll)
    const watch = () => ev(`(() => { window.__pd = 0; if (!window.__pdOn) { window.__pdOn = 1; addEventListener('touchmove', e => { if (e.defaultPrevented) window.__pd++; }); } return 1; })()`);
    const scrollTo = y => ev(`(() => { ${CARD}.scrollTop = ${y}; return 1; })()`);
    // the card has settled: no animation, no drag, two reads in a row alike (the scroll has come to rest)
    const settle = async () => { let last = ''; return until(async () => { const s = await st(); const k = JSON.stringify(s); const same = k === last && !s?.drag && await ev(`!${CARD} || ${CARD}.getAnimations().length === 0`); last = k; return same ? s || 'gone' : false; }, {step: 150}); };
    const open = () => ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); const m = modal('<h3>Long dialog</h3>' + Array.from({length: 60}, (_, i) => '<p>Line ' + (i + 1) + '</p>').join('')); m.classList.add('p2652c'); return 1; })()`);

    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');

    // ---- phone
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#today');
    await until(`typeof modal === 'function' && typeof sd_start === 'function' && !!document.querySelector('#view')`);
    await open();
    const s0 = await settle();
    check(s0 && s0.top > 0 && s0.h > 300, '390: the dialog is open as a sheet ' + JSON.stringify(s0));
    // scrolled down, swipe up and down in the content, hold, let go: the browser keeps the moves, height and scroll stay
    for (const dy of [-260, 260]) {
      await scrollTo(300); const a = await settle(); await watch();
      await swipeHold(195, s0.top + s0.h * (dy < 0 ? 0.7 : 0.3), 0, dy);
      const b = await settle();
      check(b && b !== 'gone' && b.pd === 0, `390 #5078: a swipe ${dy < 0 ? 'up' : 'down'} in the content is left to the browser (scrolls) ` + JSON.stringify(b));
      check(b && b.st === a.st && Math.abs(b.h - s0.h) <= 1 && !b.tf, `390 #5078: on release neither height nor scroll change (${dy}) ` + JSON.stringify([a, b]));
    }
    // back to the top, then a pull down in the content: no shrink, no close (before 2.652.0 it dragged and closed the sheet)
    await scrollTo(0);
    const s2 = await settle(); await watch();
    await swipeHold(195, s2.top + 120, 0, Math.min(500, 830 - s2.top - 120));
    const s3 = await settle();
    check(s3 && s3 !== 'gone' && s3.pd === 0, '390 #5078: a pull down in the content scrolled to the top leaves the dialog open ' + JSON.stringify(s3));
    check(s3 && Math.abs(s3.h - s2.h) <= 1 && !s3.tf, `390 #5078: ... and its height as it was (${s2.h} -> ${s3 && s3.h})`);
    // the head still drags: up = taller is allowed, down = closed
    await drag(195, s3.top + 12, 0, Math.min(600, 830 - s3.top - 12), 'touch');
    check(await until(`!document.querySelector('.p2652c')`) === true, '390: a swipe down at the head closes the dialog');

    // ---- tablet width with touch (Galaxy Fold open, ~840 px)
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 840, height: 1100}});
    await until(`!matchMedia('(max-width:767px)').matches`);
    check(await ev(`isTouch() && !isMobile()`), '840: touch without the phone width');
    await open();
    const t0 = await settle();
    check(t0 && t0 !== 'gone', '840: the dialog is open ' + JSON.stringify(t0));
    if (t0 && t0 !== 'gone') {
      await watch();
      await swipeHold(420, t0.top + 120, 0, 400);
      const t1 = await settle();
      check(t1 && t1 !== 'gone' && t1.pd === 0 && Math.abs(t1.h - t0.h) <= 1 && !t1.tf, '840 #5078: a pull down in the content leaves the dialog as it was ' + JSON.stringify([t0, t1]));
      await scrollTo(300); const ta = await settle(); await watch();
      await swipeHold(420, t0.top + t0.h * 0.7, 0, -300);
      const t2 = await settle();
      check(t2 && t2.pd === 0 && t2.st === ta.st && Math.abs(t2.h - t0.h) <= 1, '840 #5078: a swipe up in the scrolled content is the browser\'s, height and scroll stay ' + JSON.stringify([ta, t2]));
      await ev(`(() => { document.querySelector('.p2652c')?.remove(); return 1; })()`);
    }
    // the quick-add sheet of a touch tablet: its head drags it away
    await ev(`(() => { openQuickSheet(); return 1; })()`);
    check(await until(`!!document.querySelector('.qadd.sheet') && document.querySelector('.qadd.sheet').getAnimations().length === 0`), '840: the quick-add sheet is open');
    const q = await ev(`(() => { const r = document.querySelector('.qadd.sheet').getBoundingClientRect(); return {top: r.top, h: r.height}; })()`);
    await drag(420, q.top + 6, 0, Math.min(600, 1090 - q.top - 6), 'touch');
    check(await until(`!document.querySelector('.qadd.sheet')`) === true, '840: a swipe down at the head closes the quick-add sheet');

    // ---- #5086 touch CSS at 840 with touch
    await ev(`Promise.all(['tagsel', 'timeline', 'office'].map(f => loadCss(f))).then(() => 1)`);
    const css = await ev(`(() => {
      const box = document.createElement('div'); box.className = 'p2652c-css'; box.style.cssText = 'position:fixed;left:0;top:0;width:800px';
      box.innerHTML = '<button class="tsp">Tag</button><span class="tsfx">Filter</span><div class="abspaces"><button class="abspace">Space</button></div>'
        + '<div class="tl rm"><div class="rm-chips"><button type="button">Chip</button></div><div class="rm-lpop"><label class="rm-lrow rm-lf">List</label><label class="rm-lrow">Item</label></div></div>'
        + '<div class="terow"><span class="ted">1 h</span><div class="teacts"><button class="iconbtn">x</button></div></div>';
      document.body.appendChild(box);
      const h = sel => Math.round(box.querySelector(sel).getBoundingClientRect().height * 10) / 10;
      const r = {tsp: h('.tsp'), tsfx: h('.tsfx'), abspace: h('.abspace'), chip: h('.rm-chips button'), lrow: h('.rm-lrow:not(.rm-lf)'), teacts: getComputedStyle(box.querySelector('.teacts')).opacity};
      box.remove(); return r; })()`);
    for (const k of ['tsp', 'tsfx', 'abspace', 'chip', 'lrow']) check(css[k] >= 43.5, `840 touch #5086: ${k} is at least 44 px (${css[k]})`);
    check(css.teacts === '1', `840 touch #5086: the buttons of a time entry are fully visible without hover (${css.teacts})`);
    const oc = await ev(`fetch('/static/css/office.css').then(r => r.text())`);
    const blocks = [...oc.matchAll(/@media([^{]*)\{((?:[^{}]*\{[^{}]*\})*[^{}]*)\}/g)].filter(m => /touch-callout/.test(m[2]));
    const sels = ['.oimarch a.ofdrow', '.agr-li .ofcrow', '.rin-it', '.brlrow', '.bkarow', '.dma-open', '.dsbsec .ctlinks li'];
    check(sels.every(x => blocks.some(m => /pointer:\s*coarse|hover:\s*none/.test(m[1]) && m[2].split('}').some(rule => rule.includes(x) && /-webkit-touch-callout:\s*none/.test(rule)))),
      '840 touch #5086: the long-press rows of the office have -webkit-touch-callout:none at the pointer ' + JSON.stringify(blocks.map(m => m[1])));
  }, true);

  check(!errs.length, 'no script errors: ' + errs.join(' | '));
  console.log(`p2652_c_sheet_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p2652_c_sheet_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
