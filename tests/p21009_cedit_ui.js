// kalmido-suite: fresh
// 2.1009.0 UI test in Firefox (real layout, phone 390 x 844, touch): own container (start.sh). Invented data only.
// - #5772 editing a comment of a task: the panel's bottom bar (comment box with Send, date / done) no longer sticks over the
//   edited comment. Device test v2.996.0 (iPhone): with the keyboard up the bar lay over "Save" and "Cancel". Here the panel
//   is scrolled so that "Save" sits at its bottom edge (where the keyboard pushes it); "Save" must be what lies there and a real
//   finger tap on it saves the new text; after saving the bar sticks to the bottom edge again.
// freelancer-matrix: n/a (no route; the task panel is drawn in the client only, tested as alice without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21009_cedit_ui', check, shots: 'P21009_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'comments,collab';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Garden shed'})).id;
  // a long description: the comments start below the fold, so the edited one can be scrolled to the panel's bottom edge
  const content = Array.from({length: 40}, (_, i) => `Step ${i + 1}: measure, cut and fit the boards`).join('\n\n');
  const T = (await call(CA, 'POST', '/api/tasks', {title: 'Build the shed roof', list_id: L, content})).id;
  check(!!T, 'task created');
  const C1 = (await call(CA, 'POST', `/api/tasks/${T}/comments`, {body: 'Boards are ordered'})).id;
  await call(CA, 'POST', `/api/tasks/${T}/comments`, {body: 'Delivery on Friday'});
  check(!!C1, 'comments written');

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const until = (expr, n) => require('./boot').until(() => ev(expr).catch(() => null), {timeout: n ? n * 250 : 15000, step: 250});
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await nav(B + '?p=1#t/' + T);  // a real load
    check(await until(`!!document.querySelector('#detail #d-tl-items .cm[data-cid="${C1}"]')`, 80), 'the task panel shows the comments');
    check(await until(`!!document.querySelector('#detail .dbot #c-input')`), 'the comment box sits in the bottom bar');
    check(await ev(`getComputedStyle(document.querySelector('#detail .dbot')).position`) === 'sticky', 'the bottom bar sticks to the bottom edge while nobody edits');
    const barH = await ev(`Math.round(document.querySelector('#detail .dbot').getBoundingClientRect().height)`);  // the strip it covers at the bottom edge
    // edit the first comment (as a person: its Edit button)
    await ev(`(() => { document.querySelector('#d-tl-items [data-act="c-edit"][data-cid="${C1}"]').click(); return 1; })()`);
    check(await until(`!!document.querySelector('.c-edit-input[data-cid="${C1}"]')`), 'the edit box is open');
    await ev(`(() => { const i = document.querySelector('.c-edit-input[data-cid="${C1}"]'); i.value = 'Boards are ordered and paid'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    // the panel scrolled so that "Save" lies at its bottom edge (as the keyboard pushes it there): what is under its middle?
    const g = await ev(`(async () => {
      const s = document.querySelector('[data-act="c-edit-save"][data-cid="${C1}"]');
      let sc = s.parentElement; while (sc && !(sc.scrollHeight > sc.clientHeight + 2 && /auto|scroll/.test(getComputedStyle(sc).overflowY))) sc = sc.parentElement;
      if (!sc) return {err: 'no scroller'};
      const lim = Math.min(sc.getBoundingClientRect().bottom, innerHeight);
      sc.scrollTop += s.getBoundingClientRect().bottom - (lim - 6);
      await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
      const r = s.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2, h = document.elementFromPoint(x, y);
      const c = document.querySelector('[data-act="c-edit-cancel"]').getBoundingClientRect(), hc = document.elementFromPoint(c.left + c.width / 2, c.top + c.height / 2);
      return {x: Math.round(x), y: Math.round(y), bottom: Math.round(r.bottom), lim: Math.round(lim), save: !!h && (h === s || s.contains(h)),
        cancel: !!hc && !!hc.closest('[data-act="c-edit-cancel"]'), on: h ? h.tagName + '.' + (h.className || '') + ' in ' + (h.closest('.dbot') ? '.dbot' : '-') : 'nothing',
        bar: getComputedStyle(document.querySelector('#detail .dbot')).position}; })()`);
    // as far down as the panel scrolls: its middle inside the strip the sticking bar covers (barH from the bottom edge)
    check(g && !g.err && g.bottom <= g.lim && g.y > g.lim - barH, '#5772: "Save" scrolled into the strip of the bottom bar ' + JSON.stringify({...g, barH}));
    check(g && g.save, '#5772: "Save" at the bottom edge is not covered by the comment box with Send ' + JSON.stringify(g));
    check(g && g.cancel, '#5772: "Cancel" at the bottom edge is not covered either ' + JSON.stringify(g));
    await shot('p21009-390-cedit-bottom.png');
    // a real finger tap on that spot saves the new text
    if (g && g.save) {
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: 'touch'},
        actions: [{type: 'pointerMove', x: g.x, y: g.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx});
    }
    check(await until(`!document.querySelector('.c-edit-input')`), '#5772: the tap on "Save" closes the edit box');
    const tl = await call(CA, 'GET', `/api/tasks/${T}/timeline`);
    check((tl.comments || []).some(c => c.id === C1 && c.body === 'Boards are ordered and paid'), '#5772: the new text is saved ' + JSON.stringify((tl.comments || []).map(c => c.body)));
    check(await until(`/ordered and paid/.test(document.querySelector('#d-tl-items .cm[data-cid="${C1}"]')?.textContent || '')`), '#5772: the panel shows the new text');
    check(await ev(`getComputedStyle(document.querySelector('#detail .dbot')).position`) === 'sticky', '#5772: after saving the bottom bar sticks to the bottom edge again');
  }, true);

  console.log(`p21009_cedit_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
