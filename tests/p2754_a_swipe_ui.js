// kalmido-suite:
// 2.754.0 UI test (#5213: leafing between tasks like turning a page - the previous and the next task of the view are drawn
// ahead by the panel's own drawing (detail.js renderDetail0, dswDraw) with their comments fetched ahead, lie inside the panel
// beside the open one while the finger swipes (swipenav.js o.inside), snap, and after the snap their nodes ARE the panel: nothing
// glides in, no comment comes later), own container (start.sh), jsdom (phone) + Firefox (touch, 320 and 460 px). Invented data
// only. P2754A_NOSTART=1 = the container runs.
// - jsdom: the next task is drawn ahead (its title, its comments) outside the page, the one after it is not fetched; mid-swipe
//   it lies inside the panel (hidden from screen readers, not reachable), the open one's parts follow the finger; let go: its
//   nodes are the panel (the same title field, the same comment), "3 of 4", Back still closes (the entry is replaced), the
//   comments fetched ahead are there before the panel asks for them again; the rules that stay: not from the screen edge, not
//   in a field with the focus, a short swipe springs back, the last task springs back without a neighbour; reduced motion: no
//   snapping animation
// - Firefox 320 / 460: the next task's title and comments lie beside the open one, after the snap they stand where they lay
//   (top) and where the open one stood (left), and they stay there once the panel's own requests are done (no shift)
// P4: alice works without an organisation (private lists): the person without an organisation (freelancer-matrix: tasks)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2754_a_swipe_ui', check, shots: 'P2754A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2754A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n = 60) => require('./boot').until(fn, {timeout: Math.max(15000, n * 200), step: 100});

function touch(w, el, type, pts) {  // jsdom has no Touch constructor: touches as plain objects
  const ev = new w.Event(type, {bubbles: true, cancelable: true});
  Object.defineProperty(ev, 'touches', {value: type === 'touchend' || type === 'touchcancel' ? [] : pts.map(([x, y]) => ({clientX: x, clientY: y, target: el}))});
  el.dispatchEvent(ev);
}
function hold(w, el, dx, x0 = 200) {  // one finger from (x0, 300) by dx in a few steps, held (not let go)
  touch(w, el, 'touchstart', [[x0, 300]]);
  for (const f of [.25, .5, .75, 1]) touch(w, el, 'touchmove', [[x0 + dx * f, 300]]);
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'comments,collab'});
  const L = (await call('POST', '/api/lists', {name: 'Leafing'})).id;
  const T = [];
  for (const n of ['Alpha task', 'Bravo task', 'Charlie task', 'Delta task']) T.push((await call('POST', '/api/tasks', {title: n, list_id: L})).id);
  for (const id of T) for (let c = 1; c <= 2; c++) await call('POST', `/api/tasks/${id}/comments`, {body: `Note ${c} on task ${id}`});

  // ================= the phone (jsdom)
  const m = await boot({user: 'alice', hash: 'l/' + L, mobile: true}), d = m.document;
  await until(() => d.querySelectorAll('#view .trow').length >= 4);
  const order = m.eval(`JSON.stringify([...document.querySelectorAll('#view .trow')].map(r => +r.dataset.id))`), O = JSON.parse(order);
  const title = id => m.eval(`taskById(${id}).title`);
  m.eval(`window.__f = []; { const f0 = window.fetch; window.fetch = function (u) { __f.push(String(u && u.url || u)); return f0.apply(this, arguments); }; } 1`);
  const gets = (id, what) => m.eval(`__f.filter(u => u.includes('/api/tasks/${id}/${what}')).length`);
  m.eval(`openDetail(${O[1]}); 1`);
  check(await until(() => m.eval(`typeof swn_attach === 'function' && !!DSW_PRE.get(${O[2]})?.el?.querySelector('#d-title')`)), 'phone: the next task is drawn ahead');
  const nb2 = `DSW_PRE.get(${O[2]}).el`;
  check(m.eval(`${nb2}.querySelector('#d-title').value`) === title(O[2]) && m.eval(`!!${nb2}.querySelector('.dtop') && !!${nb2}.querySelector('.dbody') && !!${nb2}.querySelector('.dbot')`), '... by the panel\'s own drawing: its title, header, body and bottom bar');
  check(await until(() => m.eval(`!!DSW_PRE.get(${O[2]})?.el?.textContent.includes('Note 2 on task ${O[2]}')`)), '... with its comments fetched ahead (no Loading…)');
  check(!m.eval(`${nb2}.isConnected`) && d.querySelectorAll('[id="d-title"]').length === 1, '... outside the page: the open one\'s fields stay the only ones');
  check(await until(() => m.eval(`!!DSW_PRE.get(${O[0]})?.el`)) && !m.eval(`DSW_PRE.has(${O[3]})`), '... the one before too, the third one is not fetched (only the direct neighbours)');

  // mid-swipe
  const area = () => d.querySelector('#detail .dbody');
  const H0 = m.eval('history.length');
  hold(m, area(), -120);
  const lay = () => d.querySelector(`#detail > .swn-nb > .dnbp[data-id="${O[2]}"]`);
  check(!!lay() && lay().querySelector('#d-title').value === title(O[2]), 'mid-swipe: the next task drawn ahead lies inside the panel');
  const kids = [...d.querySelectorAll('#detail > *')].map(x => x.classList.contains('swn-nb') ? 'nb' : 'own').join(',');
  check(lay()?.parentElement.getAttribute('aria-hidden') === 'true' && lay()?.inert === true && /^(own,)+nb(,nb)?$/.test(kids), '... hidden from screen readers, not reachable, after the open one\'s own parts ' + kids);
  check(/translateX\(-120px\)/.test(d.querySelector('#detail > .dtop').style.transform) && /translateX\(-120px\)/.test(d.querySelector('#detail > .dbody').style.transform), '... the open one\'s header and body follow the finger');
  m.eval(`window.__t = document.querySelector('#detail > .swn-nb .dnbp #d-title'); window.__cm = document.querySelector('#detail > .swn-nb .dnbp #d-tl'); 1`);
  const tl0 = gets(O[2], 'timeline');
  touch(m, area(), 'touchend', []);
  check(await until(() => m.eval('S.sel') === O[2] && !d.querySelector('#detail .swn-nb')), 'let go: the next task is open, nothing beside it any more');
  check(m.eval(`document.querySelector('#d-title') === __t && __t.closest('#detail') === document.querySelector('#detail')`), '... its nodes drawn ahead ARE the panel (the same title field, nothing drawn anew)');
  check(m.eval(`!!__cm && document.querySelector('#d-tl') === __cm && __cm.textContent.includes('Note 2 on task ${O[2]}')`), '... the same comments section, its comments there at once');
  check(!d.querySelector('#detail > .dtop').style.transform && d.querySelectorAll('[id="d-title"]').length === 1, '... in place, its ids the only ones');
  check(await until(() => (d.querySelector('#dswpos')?.textContent || '') === '3 of 4'), '"3 of 4" shows: ' + d.querySelector('#dswpos')?.textContent);
  check(m.eval('history.length') === H0 && m.eval('history.state?.detail') === O[2], 'the history entry is replaced: Back closes the task');
  check(gets(O[2], 'timeline') <= tl0 + 1 && m.eval(`S.tl.id === ${O[2]}`), `the comments fetched ahead were taken (at most the one quiet refresh: ${gets(O[2], 'timeline') - tl0})`);
  check(await until(() => m.eval(`!!DSW_PRE.get(${O[3]})?.el && !!DSW_PRE.get(${O[1]})?.el && !DSW_PRE.has(${O[0]})`)), '... its own neighbours drawn ahead, the one that is no neighbour any more dropped');

  // the rules that stay
  hold(m, area(), -30); touch(m, area(), 'touchend', []);
  check(await until(() => !d.querySelector('#detail .swn-nb')) && m.eval('S.sel') === O[2], 'a short swipe springs back');
  hold(m, area(), -150, 10); touch(m, area(), 'touchend', []);
  check(!d.querySelector('#detail .swn-nb') && m.eval('S.sel') === O[2], 'not from the screen edge (the phone\'s Back)');
  m.eval(`document.querySelector('#d-title').focus(); 1`);
  hold(m, d.querySelector('#d-title'), -150); touch(m, d.querySelector('#d-title'), 'touchend', []);
  check(!d.querySelector('#detail .swn-nb') && m.eval('S.sel') === O[2], 'not in a field with the focus');
  m.eval(`document.activeElement.blur(); openDetail(${O[3]}); 1`);
  await until(() => m.eval(`!!DSW_PRE.get(${O[2]})?.el`));
  hold(m, area(), -150);
  check(!d.querySelector('#detail .swn-nb[data-dir="1"]'), 'the last task: nothing lies after it');
  touch(m, area(), 'touchend', []);
  check(await until(() => !d.querySelector('#detail > .dbody').style.transform) && m.eval('S.sel') === O[3], '... it springs back');
  m.eval(`closeDetail(); 1`);
  m.close();

  // reduced motion: no snapping animation
  const r = await boot({user: 'alice', hash: 'l/' + L, mobile: true, media: {'(prefers-reduced-motion: reduce)': true}}), rd = r.document;
  await until(() => rd.querySelectorAll('#view .trow').length >= 4);
  r.eval(`openDetail(${O[0]}); 1`);
  check(await until(() => r.eval(`typeof swn_attach === 'function' && !!DSW_PRE.get(${O[1]})?.el`)), 'reduced motion: the next task drawn ahead');
  hold(r, rd.querySelector('#detail .dbody'), -150);
  touch(r, rd.querySelector('#detail .dbody'), 'touchend', []);
  check(rd.querySelector('#detail > .swn-nb')?.style.transition === 'none' || r.eval('S.sel') === O[1], '... it changes at once (no transition)');
  check(await until(() => r.eval('S.sel') === O[1]), '... the next task is open');
  r.close();

  // ================= Firefox, a touch screen: 320 and 460 px
  await firefox(async ({cmd, ev, nav: go, ctx, shot}) => {
    await go(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(150); } return false; };
    const TOUCH = `const tc = (el, type, pts) => { const e = new Event(type, {bubbles: true, cancelable: true}); Object.defineProperty(e, 'touches', {value: type === 'touchend' ? [] : pts.map(([x, y]) => ({clientX: x, clientY: y, target: el}))}); el.dispatchEvent(e); };
      const hold = (el, dx) => { const r = el.getBoundingClientRect(), x = innerWidth / 2, y = r.top + Math.min(20, r.height / 2); tc(el, 'touchstart', [[x, y]]); for (const f of [.25, .5, .75, 1]) tc(el, 'touchmove', [[x + dx * f, y]]); };`;
    const R = `r => ({l: Math.round(r.left), t: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)})`;
    const near = (a, b) => typeof a === 'number' && typeof b === 'number' && Math.abs(a - b) <= 1;
    for (const W of [320, 460]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 760}});
      check(await wait(`innerWidth === ${W}`, 40), `Firefox ${W}: the window has its size`);
      await go(B + 'static/icon.svg'); await go(B + '#l/' + L);  // a fresh page per width (the Back step of the last close is done)
      check(await wait(`document.querySelectorAll('#view .trow').length >= 4 && isTouch()`), `Firefox ${W}: four tasks, a touch screen`);
      await ev(`(openDetail(${O[1]}), 1)`);
      const NB = `DSW_PRE.get(${O[2]})?.el`;
      check(await wait(`typeof swn_attach === 'function' && !!${NB}?.querySelector('#d-title') && S.tl.id === ${O[1]}`, 120), `Firefox ${W}: open, the next task drawn ahead`);
      const pre0 = await ev(`JSON.stringify([...DSW_PRE].map(([k, e]) => [k, e.at ? Date.now() - e.at : 'none', e.tl?.comments?.length ?? 'none', !!e.el, e.busy ? 1 : 0]).concat([['sel', S.sel, S.v, String(dswOrder().ids)]]))`);
      const r0 = await ev(`(${R})(document.querySelector('#detail > .dbody #d-title').getBoundingClientRect())`);
      const mid = await ev(`(() => { ${TOUCH} hold(document.querySelector('#detail > .dbody #d-title'), -${Math.round(W * .35)});
        const n = document.querySelector('#detail > .swn-nb .dnbp'); if (!n) return null; const t = n.querySelector('#d-title'), c = n.querySelector('#d-tl'); t.__ahead = 1;
        const m = /translateX\\((-?[\\d.]+)px\\)/.exec(n.parentElement.style.transform), off = m ? +m[1] : 0, b = r => ({...(${R})(r), l: Math.round(r.left - off)});
        return {t: b(t.getBoundingClientRect()), c: c ? b(c.getBoundingClientRect()) : null, title: t.value, cm: c ? c.textContent.includes('Note') : null, ctext: c ? c.textContent.replace(/\\s+/g, ' ').slice(0, 120) : null,
          pre: (e => e && {tl: e.tl?.comments?.length ?? null, busy: !!e.busy, at: Date.now() - e.at})(DSW_PRE.get(${O[2]}))}; })()`);
      check(mid?.title === await ev(`taskById(${O[2]}).title`), `Firefox ${W}: mid-swipe the next task lies beside the open one with its title ` + JSON.stringify(mid));
      check(mid?.cm === true, `Firefox ${W}: ... its comments already there ` + JSON.stringify({c: mid?.ctext, pre: mid?.pre, pre0}));
      await ev(`(() => { ${TOUCH} tc(document.querySelector('#detail > .dbody'), 'touchend', []); return 1; })()`);
      check(await wait(`S.sel === ${O[2]} && !document.querySelector('#detail .swn-nb')`), `Firefox ${W}: let go, the next task is open`);
      const at = `({t: (${R})(document.querySelector('#d-title').getBoundingClientRect()), c: document.querySelector('#d-tl') ? (${R})(document.querySelector('#d-tl').getBoundingClientRect()) : null, same: document.querySelector('#d-title').__ahead === 1})`;
      const at1 = await ev(at);
      check(at1.same, `Firefox ${W}: the title field drawn ahead is the panel's (not drawn again)`);
      check(near(at1.t.t, mid.t.t) && near(at1.t.l, r0.l) && near(at1.t.w, mid.t.w), `Firefox ${W}: the title stands where it lay (top) and where the open one stood (left): no jump ` + JSON.stringify({r0, mid: mid?.t, at1: at1.t}));
      check(await wait(`(!window.__net || window.__net.n === 0) && S.tl.id === ${O[2]} && !S.tl.pre`, 80), `Firefox ${W}: settled (the panel's own requests done)`);
      const at2 = await ev(at);
      check(at1.c && near(at1.c.t, mid.c?.t) && near(at2.t.t, at1.t.t) && at2.c && near(at2.c.t, at1.c.t) && near(at2.c.h, at1.c.h), `Firefox ${W}: ... and everything stays there (no comment comes later and moves it) ` + JSON.stringify({at1, at2}));
      await shot(`p2754a-${W}.png`);
      await ev(`(closeDetail(), 1)`);
      await wait(`!S.sel && !history.state?.detail`);
    }
  }, true);

  console.log(`p2754_a_swipe_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
