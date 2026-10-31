// kalmido-suite: fresh
// 2.456.0 part A UI tests (jsdom), fresh DB (#3837): the order of rows is changed the same way everywhere: hold the grip, then
// drag. Quotation positions and parts: a finger (long press), a mouse at once, a quick swipe does nothing, the arrows only on
// a computer, a sent quotation stays as it is. jsdom has no layout: the rows get their boxes here. Invented services only.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const svc = (title, rate) => ({kind: 'service', title, qty: 1, unit: 'day', rate, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1});
const HOLD = 450;
const tc = (w, el, type, y) => { const e = new w.Event(type, {bubbles: true, cancelable: true}); e.touches = type === 'touchend' || type === 'touchcancel' ? [] : [{clientX: 10, clientY: y}]; el.dispatchEvent(e); };
const ptr = (w, el, type, y) => el.dispatchEvent(new w.MouseEvent(type, {bubbles: true, cancelable: true, clientY: y, button: 0}));
// the rows one under the other, 100 px each
const lay = rows => rows.forEach((r, i) => { r.getBoundingClientRect = () => ({top: 100 * i, bottom: 100 * i + 100, left: 0, right: 300, width: 300, height: 100}); });
// a browser's click after a drag: swallowed by drg_noClick (otherwise that would be the next click of the test)
const after = w => w.document.body.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const held = async (w, g, y0, y) => { tc(w, g, 'touchstart', y0); await sleep(HOLD); tc(w, g, 'touchmove', y); await sleep(40); tc(w, g, 'touchend', y); after(w); };
const titles = async id => (await call('GET', `/api/office/docs/${id}`)).items.map(x => x.title).join();

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktstrasse 5', zip: '50667', city: 'Koeln', country: 'DE'})).id;
  const doc = await call('POST', '/api/office/docs', {kind: 'offer', client_id: CL, lang: 'en', items: [svc('One', 100), svc('Two', 200), svc('Three', 300)]});
  const pa = (await call('POST', `/api/office/docs/${doc.id}/parts`, {title: 'Part A'})).part.id;
  await call('PUT', `/api/office/docs/${doc.id}/parts/${pa}/items`, {items: [svc('Inner one', 10), svc('Inner two', 20)]});
  const pb = (await call('POST', `/api/office/docs/${doc.id}/parts`, {title: 'Part B', add_to_title: false})).part.id;
  const pc = (await call('POST', `/api/office/docs/${doc.id}/parts`, {title: 'Part C', add_to_title: false})).part.id;
  const parts = async () => (await call('GET', `/api/office/docs/${doc.id}`)).parts.map(p => p.id).join();
  const svcRows = d => [...d.querySelector('#ofd-items, .ofdeditor').querySelectorAll('.ofdits:not(.tplist):not(.ofdautos):not(.ofdrefs):not(.ofdpays)')][0];

  // ================= a touch screen
  let w = await boot({user: 'alice', hash: `office/offers/${doc.id}`, media: {'(hover: none)': true}}), d = w.document;
  check(await until(() => d.querySelector('[data-rowd="it"]')), 'the position symbol is the grip');
  check(!d.querySelector('[data-ofd="it-up"], [data-ofd="it-down"], [data-ofd="tp-up"], [data-ofd="tp-down"]'), 'no arrows on a touch screen');
  check(d.querySelector('[data-ofd="it-del"]'), 'remove stays');
  const items = () => [...svcRows(d).children].filter(x => x.matches('.ofdit:not(.tppl)'));
  const list = () => [...svcRows(d).children].filter(x => x.matches('.ofdit'));
  // the rows of the title page: the part lines of A sit among them
  check(items().length === 3 && list().length === 4, 'the title page has three services and one part line ' + list().length);

  lay(list());
  { const g = list()[2].querySelector('[data-rowd="it"]');
    tc(w, g, 'touchstart', 250); await sleep(HOLD);
    check(list()[2].classList.contains('rowd-on') && d.querySelector('.rowd-ghost'), 'the long press lifts the row, a copy follows the finger');
    tc(w, g, 'touchmove', 20); await sleep(60);
    check(list()[0].classList.contains('rowd-before'), 'the line shows where it lands');
    tc(w, g, 'touchend', 20); after(w); }
  check(await until(async () => (await titles(doc.id)).startsWith('Three,One,Two')), 'a held position dragged to the top: ' + await titles(doc.id));
  check(await until(() => !d.querySelector('.rowd-ghost, .rowd-on, .rowd-before, .rowd-after')), 'nothing of the drag stays behind');

  { await until(() => list()[0]?.querySelector('[data-k="title"]')?.value === 'Three');
    lay(list());
    const g = list()[0].querySelector('[data-rowd="it"]');
    tc(w, g, 'touchstart', 50); await sleep(60); tc(w, g, 'touchmove', 90); tc(w, g, 'touchend', 90); await sleep(300);
    check((await titles(doc.id)).startsWith('Three,One,Two') && !d.querySelector('.rowd-ghost'), 'a quick swipe is a scroll, not a drag'); }

  { lay(list()); const g = list()[0].querySelector('[data-rowd="it"]');
    tc(w, g, 'touchstart', 50); await sleep(HOLD); tc(w, g, 'touchend', 50); await sleep(300);
    check((await titles(doc.id)).startsWith('Three,One,Two'), 'held and let go without moving: nothing changes'); }

  // a text typed into a field just before the drag is not lost
  { const inp = list()[1].querySelector('[data-k="title"]'); inp.focus(); inp.value = 'One edited';
    inp.addEventListener('blur', () => inp.dispatchEvent(new w.Event('change', {bubbles: true})), {once: true});
    lay(list()); await held(w, list()[1].querySelector('[data-rowd="it"]'), 150, 20);
    check(await until(async () => (await titles(doc.id)).startsWith('One edited,Three,Two')), 'the field\'s change goes first, then the drag: ' + await titles(doc.id)); }

  // parts
  const tpRows = () => [...d.querySelectorAll('.tplist > .tprow')];
  if (!tpRows().length) d.querySelector('[data-ofd="sec"][data-sec="parts"], [data-sec="parts"]')?.click();
  check(await until(() => tpRows().length === 3), 'three parts');
  lay(tpRows());
  await held(w, tpRows()[2].querySelector('[data-rowd="tp"]'), 250, 20);
  check(await until(async () => await parts() === [pc, pa, pb].join()), 'a held part dragged to the top: ' + await parts());
  await until(() => tpRows()[0]?.textContent.includes('Part C')); lay(tpRows());
  await held(w, tpRows()[0].querySelector('[data-rowd="tp"]'), 50, 290);
  check(await until(async () => await parts() === [pa, pb, pc].join()), 'and to the end: ' + await parts());

  // positions of an open part go to that part
  await until(() => tpRows()[0]?.textContent.includes('Part A'));
  tpRows()[0].querySelector('.tpopen').click();
  check(await until(() => d.querySelectorAll(`.tpfbox[data-pid="${pa}"] [data-rowd="it"]`).length === 2), 'the open part has its positions with grips');
  { const inner = () => [...d.querySelector(`.tpfbox[data-pid="${pa}"] .ofdits`).children].filter(x => x.matches('.ofdit'));
    lay(inner()); await held(w, inner()[1].querySelector('[data-rowd="it"]'), 150, 20);
    const pi = async () => (await call('GET', `/api/office/docs/${doc.id}`)).parts.find(p => p.id === pa).items.map(x => x.title).join();
    check(await until(async () => await pi() === 'Inner two,Inner one'), 'a position of the open part moves in that part: ' + await pi());
    check((await titles(doc.id)).startsWith('One edited,Three,Two'), 'the title page stays'); }

  // ================= a computer
  w = await boot({user: 'alice', hash: `office/offers/${doc.id}`}); d = w.document;
  check(await until(() => d.querySelector('[data-ofd="it-up"]')), 'the arrows stay on a computer');
  await until(() => list().length === 4); lay(list());
  { const g = list()[2].querySelector('[data-rowd="it"]');
    ptr(w, g, 'pointerdown', 250); ptr(w, g, 'pointermove', 180); await sleep(40); ptr(w, g, 'pointermove', 20); await sleep(40); ptr(w, g, 'pointerup', 20); after(w); }
  check(await until(async () => (await titles(doc.id)).startsWith('Two,One edited,Three')), 'a mouse drags the grip without a long press: ' + await titles(doc.id));
  await until(() => list()[1]?.querySelector('[data-ofd="it-up"]'));
  list()[1].querySelector('[data-ofd="it-up"]').click();
  check(await until(async () => (await titles(doc.id)).startsWith('One edited,Two,Three')), 'the arrow works as before: ' + await titles(doc.id));

  // a sent quotation: the grip does nothing
  await call('POST', `/api/office/docs/${doc.id}/status`, {status: 'sent'});
  w = await boot({user: 'alice', hash: `office/offers/${doc.id}`, media: {'(hover: none)': true}}); d = w.document;
  await until(() => d.querySelector('[data-rowd="it"]'));
  const sent = await titles(doc.id);
  if (d.querySelector('fieldset[disabled] [data-rowd="it"]')) { lay(list()); await held(w, list()[2].querySelector('[data-rowd="it"]'), 250, 20); await sleep(300);
    check(await titles(doc.id) === sent && !d.querySelector('.rowd-ghost'), 'a sent quotation keeps its order'); }
  else check(false, 'the positions of a sent quotation sit in a disabled fieldset');

  check(!errs.length, 'no script errors: ' + errs.join(' | ').slice(0, 300));
  console.log(`p2456_a_rowdrag_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
