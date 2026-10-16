// 2.53.0 UI tests, part D (#1449 references by dragging, #1440 preview card), Firefox (desktop + phone width). Invented data only.
// - dragging a list, a folder, a task, a contact, an event and an Ablage file onto the comment field / the description puts in
//   the reference ("#123" for a task, else a Markdown link to this app) at the drop point
// - the old drag keeps working: a task dropped on a list in the sidebar is moved there
// - links to the app render as cards with the name the reader sees; a target without access is "No access" without the
//   name the author wrote
// - the preview card: after 0.4 s on a task number / a card, inside the screen, gone after leaving
// - phone width: the "Insert reference" button opens the search, a pick goes into the comment field
const fs = require('fs');
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p253_d_ui', check, shots: 'P253D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
fs.rmSync(DATA, {recursive: true, force: true}); fs.mkdirSync(DATA, {recursive: true});
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const FEATS = 'cal,comments,collab,events,contacts';

// in the page: one synthetic HTML5 drag from a source element onto a target element (one DataTransfer for the whole drag)
const DRAG = `window.__fire = (type, el, x, y, dt) => { const e = new DragEvent(type, {bubbles: true, cancelable: true, clientX: x, clientY: y, dataTransfer: dt}); el.dispatchEvent(e); return e.defaultPrevented; };
window.__drag = (src, tgt) => { const dt = new DataTransfer(); __fire('dragstart', src, 0, 0, dt); const r = tgt.getBoundingClientRect(), x = r.left + 4, y = r.top + 4;
  const over = __fire('dragover', tgt, x, y, dt), drop = __fire('drop', tgt, x, y, dt); __fire('dragend', src, 0, 0, dt); return {over, drop, types: [...dt.types].join(',')}; };
window.__fake = html => { const d = document.createElement('div'); d.innerHTML = html; d.style.cssText = 'position:fixed;left:0;top:0;z-index:1'; document.body.appendChild(d); return d.firstElementChild; };
1`;

(async () => {
  await sleep(900);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEATS});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.org'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEATS});
  const L1 = (await call(CA, 'POST', '/api/lists', {name: 'Agents'})).id;
  const L2 = (await call(CA, 'POST', '/api/lists', {name: 'Shoot', folder: 'Work'})).id;
  const T1 = (await call(CA, 'POST', '/api/tasks', {title: 'Write the brief', list_id: L1, priority: 5, due: day(2), tags: ['studio'], content: 'First line of the brief.\nSecond line.'})).id;
  const T2 = (await call(CA, 'POST', '/api/tasks', {title: 'Comment host', list_id: L1})).id;
  const T3 = (await call(CA, 'POST', '/api/tasks', {title: 'Move me', list_id: L1})).id;
  const CT = (await call(CA, 'POST', '/api/contacts', {fn: 'Erika Example', org: 'Example Ltd', phones: [{type: 'work', value: '+49 30 1234567'}]})).id;
  const CAL = (await call(CA, 'POST', '/api/evcals', {name: 'Work'})).id;
  const EV = (await call(CA, 'POST', '/api/events', {title: 'Location scout', cal_id: CAL, start: `${day(1)}T10:00`, end: `${day(1)}T11:00`, location: 'Harbour 3'})).id;
  // bob's own things alice may not see
  const BL = (await call(CB, 'POST', '/api/lists', {name: 'Bob private'})).id;
  const BT = (await call(CB, 'POST', '/api/tasks', {title: 'Bob secret title', list_id: BL})).id;
  const BC = (await call(CB, 'POST', '/api/contacts', {fn: 'Bob secret contact'})).id;
  check(L1 && L2 && T1 && CT && EV && BL && BT && BC, 'setup: lists, tasks, contact, event ' + [L1, L2, T1, CT, EV, BL, BT, BC].join(','));
  // a comment of alice with links the author wrote: one to her list under an old name, bob's list / task / contact under
  // made-up names (only "No access" may show)
  const body = `See [Old name](${B}#l/${L1}), [Leaked list](${B}#l/${BL}), [Leaked task](${B}#t/${BT}), [Leaked contact](${B}#contacts/${BC}) and [Scout](${B}#ev/${EV}).`;
  const cm = await call(CA, 'POST', `/api/tasks/${T1}/comments`, {body});
  check(cm.http === 200 || cm.http === 201, 'setup: a comment with links ' + cm.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#l/' + L1);
    await ready(ev, `typeof rf_card === 'function' && typeof S !== 'undefined' && !!S.booted && !!taskById(${T1})`, 80);
    await ev(DRAG);
    // ================= #1449 dragging onto the comment field
    await ev(`(() => { openDetail(${T2}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#c-input')`), 'the comment field is there');
    const cval = () => ev(`document.querySelector('#c-input').value`);
    const clear = () => ev(`(() => { const i = document.querySelector('#c-input'); i.value = ''; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    let d = await ev(`__drag(document.querySelector('#side .srow[data-list="${L1}"]'), document.querySelector('#c-input'))`);
    check(d.over && d.drop && /application\/x-kalmido-ref/.test(d.types), 'list: the drag carries the own format and the field takes it ' + JSON.stringify(d));
    check((await cval()).trim() === `[Agents](${B.replace(/\/$/, '')}/#l/${L1})`, 'list: a Markdown link at the drop point: ' + await cval());
    check(await ev(`S.drafts[${T2}] === document.querySelector('#c-input').value`), 'list: the draft is kept like typed text');
    await clear();
    await ev(`(() => { S.route.key === 'l:${L1}' || go('l/${L1}'); return 1; })()`);
    await ready(ev, `!!document.querySelector('#view .trow[data-id="${T1}"]')`);
    d = await ev(`__drag(document.querySelector('#view .trow[data-id="${T1}"]'), document.querySelector('#c-input'))`);
    check(d.drop && (await cval()).trim() === '#' + T1, 'task: "#id" ' + await cval());
    // at the cursor: text around it stays, a space on each side
    await ev(`(() => { const i = document.querySelector('#c-input'); i.value = 'before|after'; i.focus(); i.setSelectionRange(7, 7); return 1; })()`);
    await ev(`(() => { const i = document.querySelector('#c-input'); const dt = new DataTransfer(); __fire('dragstart', document.querySelector('#view .trow[data-id="${T1}"]'), 0, 0, dt);
      document.caretPositionFromPoint = () => null; __fire('dragover', i, 5, 5, dt); __fire('drop', i, 5, 5, dt); delete document.caretPositionFromPoint; return 1; })()`);
    check(await cval() === `before| #${T1} after`, 'task: put in at the cursor with spaces ' + JSON.stringify(await cval()));
    await clear();
    d = await ev(`__drag(document.querySelector('#side .fhead[data-folder="Work"]'), document.querySelector('#c-input'))`);
    check(d.drop && (await cval()).trim() === `[Work](${B.replace(/\/$/, '')}/#folder/Work)`, 'folder: link ' + await cval());
    await clear();
    d = await ev(`__drag(__fake('<button class="ctrow" data-ctopen="${CT}"><span class="ctn"><b>Erika Example</b></span></button>'), document.querySelector('#c-input'))`);
    check(d.drop && (await cval()).trim() === `[Erika Example](${B.replace(/\/$/, '')}/#contacts/${CT})`, 'contact: link ' + await cval());
    await clear();
    d = await ev(`__drag(__fake('<div class="cevrow" data-cev="${EV}"><span class="cevn">Location scout</span></div>'), document.querySelector('#c-input'))`);
    check(d.drop && (await cval()).trim() === `[Location scout](${B.replace(/\/$/, '')}/#ev/${EV})`, 'event: link ' + await cval());
    await clear();
    d = await ev(`__drag(__fake('<div class="abrow" data-abid="77" draggable="true"><span class="abname">Call sheet [v2].pdf</span></div>'), document.querySelector('#c-input'))`);
    check(d.drop && (await cval()).trim() === `[Call sheet (v2).pdf](${B.replace(/\/$/, '')}/#ablage/77)`, 'Ablage file: link, brackets of the name made safe ' + await cval());
    await clear();
    // a drop somewhere else is not taken (no reference into other fields)
    d = await ev(`__drag(document.querySelector('#side .srow[data-list="${L1}"]'), document.querySelector('#d-title'))`);
    check(!d.over && !/\\[Agents\\]/.test(await ev(`document.querySelector('#d-title').value`)), 'the title field is no drop target');
    // the description (rendered or the field)
    d = await ev(`__drag(document.querySelector('#side .srow[data-list="${L2}"]'), document.querySelector('#d-content:not(.hidden)') || document.querySelector('#d-md'))`);
    check(d.drop && (await ready(ev, `document.querySelector('#d-content').value.includes('[Shoot](')`)), 'description: link put in');
    check(await ready(ev, `fetch('/api/tasks/${T2}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.content.includes('#l/${L2}'))`, 40), 'description: saved on the server');
    // ================= the old drag: a task onto a list in the sidebar still moves it
    await ev(`(() => { closeDetail(); go('l/${L1}'); return 1; })()`);
    await ready(ev, `!!document.querySelector('#view .trow[data-id="${T3}"]')`);
    await ev(`__drag(document.querySelector('#view .trow[data-id="${T3}"]'), document.querySelector('#side .srow[data-list="${L2}"]'))`);
    check(await ready(ev, `taskById(${T3})?.list_id === ${L2}`), 'old drag: the task moved onto the other list');

    // ================= cards in rendered text
    await ev(`(() => { openDetail(${T1}); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('#d-tl .rfcard').length >= 5 && !document.querySelector('#d-tl .rfcard.rfwait')`, 60), 'cards: five cards, all resolved');
    const cards = await ev(`[...document.querySelectorAll('#d-tl .rfcard')].map(a => a.dataset.rf + '=' + a.textContent.trim() + (a.classList.contains('rfno') ? '!' : '')).join('|')`);
    check(cards.includes(`l:${L1}=Agents`) && !cards.includes('Old name'), 'cards: my list with its current name, not the author\'s label ' + cards);
    check(cards.includes(`l:${BL}=No access!`) && cards.includes(`t:${BT}=No access!`) && cards.includes(`c:${BC}=No access!`), 'cards: bob\'s list / task / contact are "No access" ' + cards);
    check(cards.includes(`e:${EV}=Location scout`), 'cards: the event with its name (asked from the server) ' + cards);
    check(!/Leaked|Bob secret/.test(await ev(`document.querySelector('#d-tl').innerHTML`)), 'cards: no name of a target without access anywhere in the comment');
    check(await ev(`!document.querySelector('#d-tl .rfcard.rfno[href]') && !!document.querySelector('#d-tl a.rfcard[href="#l/${L1}"]')`), 'cards: "No access" is no link, the others are');
    await shot('p253-d-cards.png');
    // ================= #1440 the preview card
    const hover = (sel, x, y) => ev(`(() => { const a = document.querySelector(${JSON.stringify(sel)}); a.dispatchEvent(new PointerEvent('pointerover', {bubbles: true, pointerType: 'mouse', clientX: ${x}, clientY: ${y}})); return 1; })()`);
    const leave = sel => ev(`(() => { const a = document.querySelector(${JSON.stringify(sel)}); a.dispatchEvent(new PointerEvent('pointerout', {bubbles: true, pointerType: 'mouse', relatedTarget: document.body})); return 1; })()`);
    // a task number in a comment of T2 that links T1
    await call(CA, 'POST', `/api/tasks/${T2}/comments`, {body: `Needs #${T1} first`});
    await ev(`(() => { openDetail(${T2}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#d-tl a.tref[data-tref="${T1}"]')`, 60), 'preview: the task number is a link');
    await hover(`#d-tl a.tref[data-tref="${T1}"]`, 1270, 890);
    await sleep(200);
    check(!(await ev(`!!document.querySelector('.rfpv')`)), 'preview: not yet after 0.2 s');
    check(await ready(ev, `!!document.querySelector('.rfpv.on')`, 8), 'preview: shown after 0.4 s');
    const pv = await ev(`(() => { const e = document.querySelector('.rfpv'), r = e.getBoundingClientRect(); return {t: e.textContent, in: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight}; })()`);
    check(pv.in, 'preview: inside the screen at the bottom right corner');
    check(/Write the brief/.test(pv.t) && /Agents/.test(pv.t) && /High/.test(pv.t) && /#studio/.test(pv.t) && /First line of the brief/.test(pv.t) && /1 comment/.test(pv.t),
      'preview: title, list, priority, tag, description, comments ' + pv.t);
    check(await ev(`!document.querySelector('#d-tl a.tref[data-tref="${T1}"]').title`), 'preview: no browser tooltip on top');
    await shot('p253-d-preview.png');
    await ev(`(() => { document.querySelector('.rfpv').dispatchEvent(new PointerEvent('pointerover', {bubbles: true, pointerType: 'mouse'})); return 1; })()`);
    await sleep(300);
    check(await ev(`!!document.querySelector('.rfpv.on')`), 'preview: stays while the mouse is on the card');
    await leave('.rfpv');
    check(await ready(ev, `!document.querySelector('.rfpv')`, 8), 'preview: gone after leaving');
    check(await ev(`document.querySelector('#d-tl a.tref[data-tref="${T1}"]').title === 'Write the brief'`), 'preview: the tooltip text is back');
    // a card of a contact: the contact's company and phone
    await ev(`(() => { const c = document.querySelector('#c-input'); c.value = ''; return 1; })()`);
    await ev(`(() => { __fake('<div class="md" id="rfx">' + renderMd('[x](${B}#contacts/${CT})') + '</div>'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#rfx a.rfcard') && !document.querySelector('#rfx .rfwait')`), 'contact card resolved');
    await hover('#rfx a.rfcard', 20, 20);
    check(await ready(ev, `/Example Ltd/.test(document.querySelector('.rfpv.on')?.textContent || '') && /1234567/.test(document.querySelector('.rfpv').textContent)`, 12), 'preview: contact with company and phone');
    await leave('#rfx a.rfcard');
    await ready(ev, `!document.querySelector('.rfpv')`, 8);
    // a card without access has no preview
    await ev(`(() => { __fake('<div class="md" id="rfy">' + renderMd('[x](${B}#l/${BL})') + '</div>'); return 1; })()`);
    await ev(`(() => { const a = document.querySelector('#rfy .rfcard'); a.dispatchEvent(new PointerEvent('pointerover', {bubbles: true, pointerType: 'mouse', clientX: 20, clientY: 20})); return 1; })()`);
    await sleep(600);
    check(!(await ev(`!!document.querySelector('.rfpv')`)), 'preview: none for "No access"');
    // a touch pointer never opens it
    await ev(`(() => { document.querySelector('#rfx a.rfcard').dispatchEvent(new PointerEvent('pointerover', {bubbles: true, pointerType: 'touch', clientX: 20, clientY: 20})); return 1; })()`);
    await sleep(600);
    check(!(await ev(`!!document.querySelector('.rfpv')`)), 'preview: not for touch');

    // ================= phone width: the button
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#l/' + L1);
    await ready(ev, `typeof rf_card === 'function' && !!S.booted && !!taskById(${T2})`, 80);
    await ev(`(() => { openDetail(${T2}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('[data-rfins="c"]') && !!document.querySelector('[data-rfins="d"]')`, 40), 'phone: "Insert reference" at the comment box and the description');
    await ev(`(() => { document.querySelector('[data-rfins="c"]').click(); return 1; })()`);
    check(await ready(ev, `PAL.mode === 'ref' && /Insert reference/.test(document.querySelector('.palette .pmode')?.textContent || '')`), 'phone: the search opens in reference mode');
    await ev(`(() => { const i = document.querySelector('.palette .pqin'); i.value = 'Shoot'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `PAL.items[0]?.id === 'rf:l:${L2}'`), 'phone: the list is the first hit');
    await shot('p253-d-phone-search.png');
    await ev(`(() => { document.querySelector('.palette [data-pi="0"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.palette') && document.querySelector('#c-input').value.includes('[Shoot](')`), 'phone: the pick is in the comment field');
    // contacts are asked from the server while typing
    await ev(`(() => { document.querySelector('[data-rfins="c"]').click(); return 1; })()`);
    await ready(ev, `PAL.mode === 'ref'`);
    await ev(`(() => { const i = document.querySelector('.palette .pqin'); i.value = 'Erika'; i.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `PAL.items.some(x => x.id === 'rf:c:${CT}')`), 'phone: a contact is found');
    check(await ev(`!PAL.items.some(x => x.id === 'rf:c:${BC}' || x.id === 'rf:l:${BL}')`), 'phone: nothing of bob in the search');
    await ev(`(() => { const e = new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}); document.querySelector('.palette .pqin').dispatchEvent(e); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.palette')`), 'phone: Escape closes the search (not the normal palette)');
  });
  console.log(`p253_d_ui: ${ok} passed, ${F.length} failed`);
  if (F.length) process.exit(1);
})().catch(e => { console.error(e); process.exit(1); });
