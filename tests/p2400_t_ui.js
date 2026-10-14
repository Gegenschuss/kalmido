// 2.40.0 UI tests, part T, own container (start.sh), Firefox (mouse, 1440 x 900 unless said otherwise):
// - #1430: a width drag whose grip a render replaces ends (guide line and body.pgdrag go); stray guide lines go with the
//   next render; live renders are bundled (50 requests within 300 ms = one render)
// - #1203: a tap that stops the scrolling of the task does not open the description editor (500 ms after the last scroll),
//   a calm click later does; "Edit the description only with the pen": a click on the text never opens it, the pen does
// - #1415: an empty state with a button (Habits) in the column form: the button below the text
// - #1191: list columns from 600 px on: at 700 px the column titles and the first columns are there (title keeps its
//   minimum, what does not fit falls away), the columns button too; at 500 px the phone layout (no titles, no button)
// - #1416: "Priority as background" strong: rows with a priority are tinted in its colour, rows without one are not, the
//   selected row keeps its accent
// - #1409: Markdown in titles: bold / code / link in the row, HTML stays text, aria-label without the marks; a click on the
//   link does not open the task; checklist -> subtasks: the indented line becomes the subtask's description, the history
//   offers "Restore the description" and it brings the text back
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2400_t_ui', check, shots: 'P2400T_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, h = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...h, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'comments,collab,fields,habits';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Stock'})).id;
  const FT = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Package', type: 'text'})).id;
  const FN = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Amount', type: 'number'})).id;
  const FX = (await call(CA, 'POST', `/api/lists/${L}/fields`, {name: 'Note', type: 'text'})).id;
  await call(CA, 'PATCH', `/api/lists/${L}`, {columns: ['due', `f:${FT}`, `f:${FN}`, `f:${FX}`, 'tags']});
  const TH = (await call(CA, 'POST', '/api/tasks', {title: 'Order boxes', list_id: L, priority: 5, due: '2026-11-03', fields: {[FT]: 'pkg-1', [FN]: '4'}})).id;
  const TM = (await call(CA, 'POST', '/api/tasks', {title: 'Count shelves', list_id: L, priority: 3})).id;
  const T0 = (await call(CA, 'POST', '/api/tasks', {title: 'Sweep the floor', list_id: L})).id;
  const MD = (await call(CA, 'POST', '/api/tasks', {title: '**Master data:** read `.xlsx` [docs](https://example.com/docs)', list_id: L})).id;
  const XS = (await call(CA, 'POST', '/api/tasks', {title: '<img src=x onerror="window.__xss=1"> [x](javascript:window.__xss=2)', list_id: L})).id;
  const LONG = Array.from({length: 60}, (_, i) => `Line ${i + 1} of a long description.`).join('\n\n');
  const DS = (await call(CA, 'POST', '/api/tasks', {title: 'Long notes', list_id: L, content: LONG})).id;
  const CK = (await call(CA, 'POST', '/api/tasks', {title: 'Checklist', list_id: L, content: 'Intro\n- [ ] one\n  more about one\n- [x] done'})).id;
  check(TH && TM && T0 && MD && XS && DS && CK, 'tasks (setup)');
  const task = async id => (await call(CA, 'GET', '/api/state')).tasks.find(t => t.id === id);

  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    const ready = async (expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
    const act = actions => cmd('input.performActions', {context: ctx, actions});
    const release = () => cmd('input.releaseActions', {context: ctx});
    const clickAt = (x, y) => act([{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]).then(release);
    const mid = sel => ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const b = e.getBoundingClientRect(); return {x: b.left + b.width / 2, y: b.top + Math.min(b.height / 2, 12), w: b.width, h: b.height, t: b.top, b: b.bottom}; })()`);
    const vp = (width, height) => cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await vp(1440, 900);
    await nav(B + '#l/' + L);
    check(await ready(`typeof mdTitle === 'function' && !!document.querySelector('#view .lchead') && !!document.querySelector('#tc-${TH}')`), 'Firefox: the list with columns');
    await sleep(400);

    // ================= #1430 guide lines
    const g = await mid(`.lchead .lcg[data-lcg="f:${FT}"]`);
    check(!!g, '#1430: a width grip (setup)');
    await act([{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: Math.round(g.x), y: Math.round(g.y)}, {type: 'pointerDown', button: 0}, {type: 'pointerMove', x: Math.round(g.x - 20), y: Math.round(g.y), duration: 100}]}]);
    await sleep(150);
    check(await ev(`!!document.querySelector('body > .lcguide') && document.body.classList.contains('pgdrag')`), '#1430: the guide line while dragging');
    // a render that replaces the grip (as a live change did): the drag ends, line and pgdrag go
    await ev(`(() => { document.querySelector('#view .lchead').remove(); renderView(); return 1; })()`);
    await sleep(150);
    check(await ev(`!document.querySelector('body > .lcguide') && !document.body.classList.contains('pgdrag')`), '#1430: a render during the drag removes the guide line and pgdrag');
    await act([{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerUp', button: 0}]}]); await release();
    await ev(`(() => { localStorage.removeItem('tasks.lcw.${L}'); lcwApply(${L}); return 1; })()`);
    // a stray line (and pgdrag) without a drag: the next render takes it away
    await ev(`(() => { document.body.appendChild(Object.assign(document.createElement('div'), {className: 'lcguide'})); document.body.classList.add('pgdrag'); renderView(); return 1; })()`);
    check(await ev(`!document.querySelector('body > .lcguide') && !document.body.classList.contains('pgdrag')`), '#1430: a stray guide line goes with the next render');
    // bundled live renders
    const n50 = await ev(`new Promise(res => { let n = 0; const f = window.render; window.render = function (...a) { n++; return f.apply(this, a); };
      for (let i = 0; i < 50; i++) td_renderSoon(); setTimeout(() => { window.render = f; res(n); }, 600); })`);
    check(n50 === 1, `#1430: 50 live render requests within 300 ms = one render (${n50})`);
    const cache = await ev(`(() => { let a, b; td_rcRun(() => { a = fieldsOf(${L}); b = fieldsOf(${L}); }); return a === b && fieldsOf(${L}) !== a; })()`);
    check(cache, '#1430: field lookups are cached within one render only');

    // ================= #1416 priority as background
    await ev(`(async () => { await api('PATCH', '/api/settings', {prio_bg: 'strong'}); S.settings.prio_bg = 'strong'; render(); return 1; })()`); await sleep(300);
    const bg = await ev(`(() => { const c = id => getComputedStyle(document.querySelector('#view .trow[data-id="' + id + '"]')).backgroundColor; return {h: c(${TH}), m: c(${TM}), n: c(${T0}), body: document.body.classList.contains('prbg-strong')}; })()`);
    check(bg.body && bg.h !== bg.n && bg.m !== bg.n && bg.h !== bg.m, '#1416: high and medium rows are tinted, a row without priority is not ' + JSON.stringify(bg));
    await shot('p2400t-prio-bg.png');
    await ev(`(() => { openDetail(${TH}); return 1; })()`); await sleep(500);
    const sel = await ev(`(() => { const r = document.querySelector('#view .trow[data-id="${TH}"]'); return {sel: r.classList.contains('sel'), bg: getComputedStyle(r).backgroundColor}; })()`);
    check(sel.sel && sel.bg !== bg.h, '#1416: the selected row keeps its accent ' + JSON.stringify(sel));
    await ev(`(() => { closeDetail(); return 1; })()`);
    await ev(`(async () => { await api('PATCH', '/api/settings', {prio_bg: ''}); S.settings.prio_bg = ''; render(); return 1; })()`); await sleep(300);
    check(await ev(`!document.body.className.includes('prbg-')`), '#1416: off again');

    // ================= #1409 titles
    const tt = await ev(`(() => { const t = document.querySelector('#view .trow[data-id="${MD}"] .ttl'); return {b: t.querySelector('b')?.textContent, code: t.querySelector('code')?.textContent, a: t.querySelector('a[href]')?.getAttribute('href'), txt: t.textContent,
      aria: document.querySelector('#view .trow[data-id="${MD}"] .chk').getAttribute('aria-label')}; })()`);
    check(tt.b === 'Master data:' && tt.code === '.xlsx' && tt.a === 'https://example.com/docs' && !tt.txt.includes('**'), '#1409: bold, code and a link in the row ' + JSON.stringify(tt));
    check(tt.aria === 'Complete: Master data: read .xlsx docs', '#1409: the aria-label has the plain text ' + tt.aria);
    const xs = await ev(`(() => { const t = document.querySelector('#view .trow[data-id="${XS}"] .ttl'); return {img: !!t.querySelector('img'), a: !!t.querySelector('a'), txt: t.textContent, xss: window.__xss || 0}; })()`);
    check(!xs.img && !xs.a && xs.txt.includes('<img') && xs.txt.includes('javascript:') && !xs.xss, '#1409: HTML and a javascript: link stay text ' + JSON.stringify(xs));
    check(await ev(`mdPlain('**a** \`b\` [c](https://example.com) ~~d~~ \\\\*e\\\\*') === 'a b c d *e*'`), '#1409: mdPlain');
    await ev(`(() => { window.addEventListener('click', e => { if (e.target.closest('.ttl a[href]')) e.preventDefault(); }, {capture: true, once: true}); return 1; })()`);
    const la = await mid(`#view .trow[data-id="${MD}"] .ttl a[href]`);
    await clickAt(la.x, la.y); await sleep(500);
    check(await ev(`S.sel !== ${MD}`), '#1409: a click on the link in the title does not open the task');
    const tw = await mid(`#view .trow[data-id="${MD}"] .ttl b`);
    await clickAt(tw.x, tw.y); await sleep(600);
    check(await ev(`S.sel === ${MD} && document.querySelector('#d-title').value.startsWith('**Master data:**')`), '#1409: a click elsewhere opens it, the title field shows the source');
    await shot('p2400t-md-title.png');

    // ================= #1409 checklist -> subtasks
    await ev(`(() => { openDetail(${CK}); return 1; })()`); await sleep(600);
    await ev(`mdToSubtasks().then(() => 1)`); await sleep(1200);
    const kids = (await call(CA, 'GET', '/api/state')).tasks.filter(t => t.parent_id === CK);
    check(kids.length === 1 && kids[0].title === 'one' && kids[0].content === 'more about one', '#1409: the indented line is the subtask\'s description ' + JSON.stringify(kids.map(k => [k.title, k.content])));
    check((await task(CK)).content === 'Intro\n- [x] done', '#1409: the parent keeps the rest ' + JSON.stringify((await task(CK)).content));
    await ev(`(async () => { await loadTimeline(${CK}); renderDetail(); return 1; })()`);
    check(await ready(`!!document.querySelector('#detail [data-act="md-restore"]')`, 20), '#1409: the history offers "Restore the description"');
    await ev(`(() => { document.querySelector('#detail [data-act="md-restore"]').click(); return 1; })()`); await sleep(1200);
    check((await task(CK)).content === 'Intro\n- [ ] one\n  more about one\n- [x] done', '#1409: Restore brings the text back ' + JSON.stringify((await task(CK)).content));

    // ================= #1203 scroll stop, pen
    await vp(1440, 700);
    await ev(`(() => { openDetail(${DS}); return 1; })()`); await sleep(700);
    check(await ev(`!!document.querySelector('#d-md') && !document.querySelector('#detail .mdpen')`), '#1203: desktop: no pen by default');
    await ev(`(() => { document.querySelector('#detail .dbody').dispatchEvent(new Event('scroll')); return 1; })()`);
    let p = await mid('#d-md p:nth-of-type(2)');
    await clickAt(p.x, p.y); await sleep(500);
    check(await ev(`!S.editContent && document.querySelector('#d-content').classList.contains('hidden')`), '#1203: a click right after scrolling does not open the editor');
    await sleep(400);
    p = await mid('#d-md p:nth-of-type(2)');
    await clickAt(p.x, p.y); await sleep(600);
    check(await ev(`S.editContent === true`), '#1203: a calm click later opens it');
    await ev(`(() => { S.editContent = false; LS.set('mdPenOnly', true); renderDetail(); return 1; })()`); await sleep(400);
    check(await ev(`!!document.querySelector('#detail .mdpen')`), '#1203: "only with the pen": the pen is there');
    p = await mid('#d-md p:nth-of-type(2)');
    await clickAt(p.x, p.y); await sleep(600);
    check(await ev(`!S.editContent`), '#1203: "only with the pen": a click on the text does not open the editor');
    const pen = await mid('#detail .mdpen');
    await clickAt(pen.x, pen.y); await sleep(500);
    check(await ev(`S.editContent === true && !document.querySelector('#d-content').classList.contains('hidden')`), '#1203: the pen opens it');
    await ev(`(() => { S.editContent = false; LS.del('mdPenOnly'); closeDetail(); return 1; })()`);
    await ev(`(() => { settingsModal('general'); return 1; })()`); await sleep(600);
    check(await ev(`!!document.querySelector('#s-mdpen') && !document.querySelector('#s-mdpen').checked`), '#1203: the setting (off on a desktop)');
    await ev(`(() => { document.querySelector('.smodal')?.remove(); return 1; })()`);

    // ================= #1191 columns from 600 px
    await vp(700, 900); await nav(B + '#l/' + L); await sleep(300); await ev(`(() => { render(); return 1; })()`);
    await ready(`!!document.querySelector('#tc-${TH}')`); await sleep(400);
    const c7 = await ev(`(() => { const h = document.querySelector('#view .lchead'), vis = e => !!e && getComputedStyle(e).display !== 'none';
      const cells = [...document.querySelectorAll('#tc-${TH} .lc')].filter(vis).map(c => c.dataset.k);
      const t = document.querySelector('#view .trow[data-id="${TH}"] .tmain').getBoundingClientRect(), l = document.querySelector('#tc-${TH}').getBoundingClientRect();
      return {head: vis(h), cells, oneRow: Math.abs(t.top - l.top) < 20 && l.left >= t.right - 2, titleW: t.width, btn: !!document.querySelector('[data-act="cols"]'), mlc: [...document.querySelectorAll('#view .trow[data-id="${TH}"] .meta .mlc')].filter(vis).length}; })()`);
    check(c7.head && c7.cells.length >= 3 && c7.cells[0] === 'due' && c7.oneRow && c7.titleW >= 150 && c7.mlc === 0, '#1191: 700 px: titles and columns in one row, the rest falls away ' + JSON.stringify(c7));
    check(c7.btn, '#1191: 700 px: the columns button');
    await shot('p2400t-cols-700.png');
    await vp(500, 900); await sleep(300); await ev(`(() => { render(); return 1; })()`); await sleep(400);
    const c5 = await ev(`(() => { const vis = e => !!e && getComputedStyle(e).display !== 'none'; return {head: vis(document.querySelector('#view .lchead')), btn: !!document.querySelector('[data-act="cols"]')}; })()`);
    check(!c5.head && !c5.btn, '#1191: 500 px: the phone layout (no column titles, no button) ' + JSON.stringify(c5));

    // ================= #1415 empty state with a button
    await vp(1440, 900); await ev(`(() => { go('habits'); return 1; })()`);
    check(await ready(`!!document.querySelector('#view .empty.eact [data-act="habit-new"]')`), '#1415: Habits without habits (setup)');
    const em = await ev(`(() => { const e = document.querySelector('#view .empty.eact'), s = e.querySelector('span').getBoundingClientRect(), b = e.querySelector('.btn').getBoundingClientRect(); return {dir: getComputedStyle(e).flexDirection, below: b.top >= s.bottom - 1}; })()`);
    check(em.dir === 'column' && em.below, '#1415: the button sits below the text ' + JSON.stringify(em));
    await shot('p2400t-empty.png');
  }, false);

  console.log(`p2400_t_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
