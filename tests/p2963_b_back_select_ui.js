// 2.963.0 UI test (#5234: Back ends a selection mode and the search's move mode first), own container
// kalmido-suite: fresh
// Firefox as a touch screen (Android Back = history.back()) in phone width. A selection mode is one step of the page
// (multisel.js MS_STEPS / ms_stepSync on #view, backclose.js f8d_step): Back ends the selection, the page and its entries
// stay, the next Back leaves the page as usual. A selection ended another way (the bar's X) takes its history entry with it:
// no dead Back. Places: task list, contacts, clients, documents, file store, knowledge, trip receipts. The search palette's
// "Move to another project" is one step of the palette: Back (and Esc) = back to the plain search, the next Back closes it.
// The drawer and the tour (also #5234) were built with #5230 and stay in p_back_steps_ui. Invented data only.
// P4: alice works without an organisation: the person without an organisation
// freelancer-matrix: n/a - no route of its own, the Back key in the browser
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2963_b_back_select_ui', check, shots: 'P2963B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2963B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const upload = async (url, field, name, text, extra) => {
  const fd = new FormData(); for (const [k, v] of Object.entries(extra)) fd.append(k, v); fd.append(field, new Blob([text]), name);
  const r = await fetch(B + url, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return r.status;
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st0.settings?.features || '').split(','), 'files', 'docs', 'wiki', 'office', 'clients', 'contacts'])].filter(Boolean).join(',')});
  const lst = await call('POST', '/api/lists', {name: 'Garden plans'});
  const lst2 = await call('POST', '/api/lists', {name: 'Kitchen plans'});
  check(lst.id > 0 && lst2.id > 0, 'two lists ' + JSON.stringify(lst));
  const task = await call('POST', '/api/tasks', {title: 'Water the tomatoes', list_id: lst.id});
  await call('POST', '/api/tasks', {title: 'Cut the hedge', list_id: lst.id});
  check(task.id > 0, 'a task ' + JSON.stringify(task));
  check((await call('POST', '/api/contacts', {fn: 'Erika Example'})).http < 300, 'a contact');
  check((await call('POST', '/api/clients', {name: 'Example Studio Ltd'})).http < 300, 'a client');
  check(await upload('api/docs', 'files', 'Letter one.txt', 'Invoice example letter one', {ws: 'private'}) === 201, 'a document');
  check(await upload('api/files/upload', 'file', 'garden-notes.txt', 'some notes', {space: 'private'}) < 300, 'a file in the file store');
  for (const p of ['Loose', 'Other']) await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: 'Text of ' + p});
  const me = await call('GET', '/api/state');
  const y = new Date().getFullYear();
  const trip = await call('POST', '/api/office/trips', {date_from: `${y}-03-10`, dest: 'Example Town', people: [{id: me.me?.id}], items: [{date: `${y}-03-10`, category: 'train', amount: 40}, {date: `${y}-03-10`, category: 'taxi', amount: 12}]});
  check(trip.id > 0, 'a trip with two receipts ' + JSON.stringify(trip).slice(0, 200));

  await firefox(async ({cmd, ev, nav: go, ctx, shot, until: wait}) => {
    await go(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('abSpace', '"private"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 760}});
    const STATE = `JSON.stringify({open: f8d_open(), depth: f8d_depth(), f8d: history.state?.f8d, pback: history.state?.pback, p: f8d_bk.pushed, skip: f8d_bk.skip, hash: location.hash, stk: (document.querySelector('#view')._stk || []).map(f => f._ms || '?')})`;
    // settled: n levels / steps open, our entries match them, the history stands on the top one
    const at = (n, more = 'true', timeout = 8000) => wait(`!f8d_bk.skip && f8d_depth() === ${n} && f8d_bk.pushed === ${n} && (history.state?.f8d || 0) === ${n} && (${more})`, {timeout});
    const back = () => ev(`(history.back(), 1)`);
    const click = sel => ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return 0; b.click(); return 1; })()`);
    // the page: #inbox below it (the next Back after the selection lands there), the page's own entry marked
    const open = async (hash, ready, prep = '') => {
      await go(B + '#inbox');
      check(await wait(`!!document.querySelector('#view') && typeof ms_stepSync === 'function' && S.route?.key === 'inbox'`, {timeout: 20000}), hash + ': the app is there');
      await ev(`(location.hash = ${JSON.stringify(hash)}, 1)`);
      if (prep) { await wait(prep, {timeout: 20000}); }
      const there = await wait(ready, {timeout: 20000});
      await ev(`(history.replaceState({pback: 1}, '', location.href), window.__h = location.hash, 1)`);
      check(there && await ev(`isTouch() && isMobile()`), hash + ': the page shows its entries (touch, phone width) ' + await ev(STATE));
      return there;
    };
    const onPage = `history.state?.pback === 1 && location.hash === window.__h`;

    // one place: start the selection -> one entry; Back ends it, the page and its entries stay; again and the bar's X
    // ends it -> its entry goes too (no dead Back); the next Back leaves the page for #inbox
    // 2.997.0 (#5681): inner = a view of the page that is a Back step of its own (#5233, 2.979.0: an open trip) and holds the
    // selection: opened first (one entry), the selection one more; Back ends the selection, the next Back closes the view
    // (the page stays), the one after leaves the page
    const place = async (name, {hash, ready, prep, inner, start, on, bar, close, content}) => {
      if (!await open(hash, ready, prep)) return;
      const b = inner ? 1 : 0, here = inner ? `(${inner.on})` : onPage;
      if (inner) {
        await ev(inner.start);
        check(await at(1, inner.on), `${name}: ${inner.what} opens, one entry ` + await ev(STATE));
      }
      await ev(start);
      check(await at(b + 1, `(${on}) && !!document.querySelector(${JSON.stringify(bar)})`), `${name}: the selection starts, one entry ` + await ev(STATE));
      await shot(`p2963b-${name}-sel.png`);
      await back();
      check(await at(b, `!(${on}) && !document.querySelector(${JSON.stringify(bar)}) && ${here}`), `${name}: Back ends the selection, the page stays ` + await ev(STATE));
      check(await wait(content, {timeout: 6000}), `${name}: the page still shows its entries after Back`);
      await ev(start);
      await at(b + 1, on);
      check(await click(close), `${name}: the bar has its X`);
      check(await at(b, `!(${on}) && ${here}`), `${name}: the X ends the selection and takes its entry with it ` + await ev(STATE));
      if (inner) {
        await back();
        check(await at(0, `!(${inner.on}) && ${onPage}`), `${name}: the next Back closes ${inner.what}, the page stays ` + await ev(STATE));
      }
      await back();
      check(await wait(`location.hash === '#inbox' && S.route?.key === 'inbox' && !f8d_bk.skip`, {timeout: 8000}), `${name}: the next Back leaves the page as usual (no dead Back) ` + await ev(STATE));
    };
    const rowWith = (sel, txt) => `[...document.querySelectorAll(${JSON.stringify(sel)})].some(r => r.textContent.includes(${JSON.stringify(txt)}))`;

    // 1. the task list (S.multiMode, the menu's "Select" - popovers.js taskMenu)
    await place('tasks', {hash: `#l/${lst.id}`, ready: rowWith('#view .trow', 'Water the tomatoes'),
      start: `(S.multiMode = true, S.multi.add(${task.id}), S.multiLast = ${task.id}, render(), 1)`, on: `S.multiMode || S.multi.size > 0`,
      bar: '#mbar:not(.hidden)', close: '#mbar [data-act="mb-close"]', content: rowWith('#view .trow', 'Water the tomatoes') + ' && ' + rowWith('#view .trow', 'Cut the hedge')});
    // 2. contacts (bk_start / bk_end): the head's "Select"
    await place('contacts', {hash: '#contacts', ready: `typeof CT === 'object' && ${rowWith('#view', 'Erika Example')} && !!document.querySelector('#view [data-ct="pick"]')`,
      start: `(document.querySelector('#view [data-ct="pick"]').click(), 1)`, on: `!!CT.pick`, bar: '#ct-sbar', close: '#ct-sbar [data-ctb="close"]', content: rowWith('#view', 'Erika Example')});
    // 3. clients (MSC.pick)
    await place('clients', {hash: '#clients', ready: `typeof MSC === 'object' && ${rowWith('#view', 'Example Studio Ltd')} && !!document.querySelector('#view [data-mscl="pick"]')`,
      start: `(document.querySelector('#view [data-mscl="pick"]').click(), 1)`, on: `!!MSC.pick`, bar: '#ct-sbar', close: '#ct-sbar [data-clb="close"]', content: rowWith('#view', 'Example Studio Ltd')});
    // 4. documents (AB.selOn, the area's one selection since #4888)
    await place('docs', {hash: '#docs', ready: `typeof AB === 'object' && ${rowWith('#view', 'Letter one')} && !!document.querySelector('#view [data-absel="mode"]')`,
      start: `(document.querySelector('#view [data-absel="mode"]').click(), 1)`, on: `AB.selOn`, bar: '#ab-sbar', close: '#ab-sbar [data-absel="close"]', content: rowWith('#view', 'Letter one')});
    // 5. the file store (same selection, its own page)
    await place('ablage', {hash: '#ablage', ready: `typeof AB === 'object' && ${rowWith('#view .abrow', 'garden-notes')} && !!document.querySelector('#view [data-absel="mode"]')`,
      start: `(document.querySelector('#view [data-absel="mode"]').click(), 1)`, on: `AB.selOn`, bar: '#ab-sbar', close: '#ab-sbar [data-absel="close"]', content: rowWith('#view .abrow', 'garden-notes')});
    // 6. knowledge (WK.selOn)
    await place('wiki', {hash: '#wiki', ready: `typeof WK === 'object' && ${rowWith('#view .wkrow', 'Loose')} && !!document.querySelector('#view [data-wksel="mode"]')`,
      start: `(document.querySelector('#view [data-wksel="mode"]').click(), 1)`, on: `WK.selOn`, bar: '#wk-sbar', close: '#wk-sbar [data-wksel="close"]', content: rowWith('#view .wkrow', 'Loose') + ' && ' + rowWith('#view .wkrow', 'Other')});
    // 7. the receipts of a trip (RK.sel): a tick starts it
    // 2.997.0 (#5681): the trip is opened by its row (a Back step of its own since #5233), the receipts' selection lies above it
    await place('travel', {hash: '#office/travel', prep: `typeof RK === 'object' && !!RK.data && (RK.year === '' || (RK.year = '', rk_reload(), true))`,
      ready: `!!document.querySelector('#view .rklist [data-rk="open"][data-id="${trip.id}"]')`,
      inner: {what: 'the trip', start: `(document.querySelector('#view .rklist [data-rk="open"][data-id="${trip.id}"]').click(), 1)`,
        on: `RK.open === ${trip.id} && document.querySelectorAll('#view [data-rk="sel"]').length === 2`},
      start: `(document.querySelector('#view [data-rk="sel"]').click(), 1)`, on: `RK.sel.size > 0`, bar: '#rk-sbar', close: '#rk-sbar [data-rk="close"]', content: `document.querySelectorAll('#view [data-rk="sel"]').length === 2 && ${rowWith('#view', 'Example Town')}`});

    // 8. the search palette: "Move to another project" is one step; Back = the plain search, the next Back closes it
    if (await open(`#l/${lst.id}`, rowWith('#view .trow', 'Water the tomatoes'))) {
      const pmove = `!!document.querySelector('.palette:not(.an-out) .pmode') && /Move/.test(document.querySelector('.palette:not(.an-out) .pmode').textContent)`;
      const plain = `!!document.querySelector('.palette:not(.an-out) .pqin') && !document.querySelector('.palette:not(.an-out) .pmode') && !PAL.mode`;
      const toMove = async () => {
        await ev(`(S.kf = ${task.id}, openPalette(), 1)`);
        check(await at(1, plain), 'palette: the plain search, one entry ' + await ev(STATE));
        await ev(`(() => { const i = PAL.items.findIndex(x => x.id === 'a:move'); if (i < 0) return 0; document.querySelector('.palette [data-pi="' + i + '"]').click(); return 1; })()`);
        check(await at(2, pmove + ` && ${rowWith('.palette .plist', 'Kitchen plans')}`), 'palette: "Move to another project" shows the projects, one step more ' + await ev(STATE));
      };
      await toMove();
      await shot('p2963b-palette-move.png');
      await back();
      check(await at(1, plain), 'palette: Back = back to the plain search, the palette stays ' + await ev(STATE));
      await back();
      check(await at(0, `!document.querySelector('.palette:not(.an-out)') && ${onPage}`), 'palette: the next Back closes the search, the page stays ' + await ev(STATE));
      // Esc in the move mode = the plain search too, the step's entry goes with it (the next Back closes the search)
      await toMove();
      await ev(`(document.querySelector('.palette:not(.an-out) .pqin').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})), 1)`);
      check(await at(1, plain), 'palette: Esc in the move mode = the plain search, its entry goes ' + await ev(STATE));
      await back();
      check(await at(0, `!document.querySelector('.palette:not(.an-out)') && ${onPage}`), 'palette: then Back closes the search, the page stays ' + await ev(STATE));
      check(await wait(rowWith('#view .trow', 'Water the tomatoes'), {timeout: 6000}), 'palette: the list still shows its tasks');
    }
  }, true);

  console.log(`p2963_b_back_select_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
