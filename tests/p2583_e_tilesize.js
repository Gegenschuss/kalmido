// 2.583.0 UI test, part E (#4812 the card size, #4870 title and sender on a card): own container (start.sh), jsdom + Firefox
// kalmido-suite: fresh
// (2560 px and phone 390 px). Invented data only. P2583E_NOSTART=1 = the container runs.
// - #4870: a card shows the title (the name) bold and the sender below it, each one line with its full text as title
// - #4877: the date on a card always with its year (also in the running year), in numbers, no Today / weekday
// - the slider in the bar above the cards: 7 rem = small cards (picture only: html.dc-tsm), saved per person, a computer and a
//   phone each their own; Ctrl + wheel on the card area changes the size (not on the bar: the page keeps the browser's zoom);
//   Ctrl + Plus / Minus / 0 with the focus on a card; remembered after loading anew
// - from 13 rem the cards ask for the sharp preview (?size=l) of a document that has one; smaller back to the small one
// - the file store's cards of the same folder: the same slider, the same size (one part: tilesize.js)
// - Firefox 2560 px: small cards = more columns (auto-fill over the full width), big ones fewer; the small ones show no text
//   until hovered; the sharp preview really arrives 800 px wide; phone: own size, nothing sideways
// P4: alice works without an organisation (private documents): the person without an organisation (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2583_e_tilesize', check, shots: 'P2583E_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2583E_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const keyOn = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));

function pdf(lines) {  // a one-page PDF written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c);
  const st = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [4 0 R] /Count 1 >>', '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 5 0 R /Resources << /Font << /F1 3 0 R >> >> >>', `<< /Length ${st.length} >>\nstream\n${st}\nendstream`];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
async function upload(name, lines) {
  const fd = new FormData();
  fd.append('files', new Blob([pdf(lines)], {type: 'application/pdf'}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = (await r.json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 150);
  return id;
}
const saved = async k => (await call('GET', '/api/state')).settings?.[k];

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const D1 = await upload('water-bill-2026.pdf', ['Wasserwerk Beispielstadt', 'Abrechnung', 'Datum 02.10.2026']);
  const D2 = await upload('gym-contract.pdf', ['Sportverein Muster', 'Vertrag', 'Datum 04.10.2026']);
  const D3 = await upload('notes.pdf', ['Some notes']);
  check([D1, D2, D3].every(Boolean), 'three documents uploaded');
  await call('PATCH', `/api/docs/${D1}`, {sender: 'Wasserwerk Beispielstadt'});
  await call('PATCH', `/api/docs/${D3}`, {sender: ''});
  const YEAR = new Date().getFullYear();
  await call('PATCH', `/api/docs/${D2}`, {date: `${YEAR}-01-15`});  // #4877: a date in the running year
  check((await call('GET', `/api/docs/${D1}`)).sender?.name === 'Wasserwerk Beispielstadt', 'the first one has a sender');
  const thumbL = (await call('GET', `/api/docs/${D1}`)).thumb_l;
  check(thumbL === true, 'the document has a sharp preview (thumb_l)');

  // ================= computer (jsdom)
  const w = await boot({user: 'alice', hash: 'docs'}), d = w.document, root = d.documentElement;
  await until(() => d.querySelectorAll('.dc-card').length === 3);
  // #4870: the title always, the sender below it
  const c1 = d.querySelector(`.dc-view [data-dco="${D1}"]`), c3 = d.querySelector(`.dc-view [data-dco="${D3}"]`);
  check(c1?.querySelector('.dc-nm')?.textContent === 'water-bill-2026.pdf' && c1.querySelector('.dc-nm').title === 'water-bill-2026.pdf', '#4870: bold the title, not the sender ' + c1?.querySelector('.dc-nm')?.textContent);
  check(c1?.querySelector('.dc-snd')?.textContent === 'Wasserwerk Beispielstadt' && c1.querySelector('.dc-snd').title === 'Wasserwerk Beispielstadt', '#4870: the sender on its own line below it, full text as title');
  check(c3 && !c3.querySelector('.dc-snd') && c3.querySelector('.dc-nm')?.textContent === 'notes.pdf', '#4870: no sender = no sender line');
  const mt2 = d.querySelector(`.dc-view [data-dco="${D2}"] .dc-mt`)?.textContent || '';
  check(mt2.includes(String(YEAR)) && /15/.test(mt2) && !/Today|Yesterday|Mon|Tue|Wed|Thu|Fri|Sat|Sun/.test(mt2), '#4877: a date of the running year with its year, in numbers ' + mt2);
  // the slider
  const range = () => d.querySelector('.dc-bar input.ts-range');
  check(range() && range().min === '7' && range().max === '28' && range().value === '11' && range().getAttribute('aria-label') === 'Card size', 'the slider in the bar: 7 to 28 rem, the standard 11, named');
  check(root.style.getPropertyValue('--dc-tw') === '11rem' && !root.classList.contains('dc-tsm'), 'the standard size on the root, no small cards');
  const img1 = () => d.querySelector(`.dc-view [data-dco="${D1}"] .dc-th img`);
  check(img1() && !/size=l/.test(img1().getAttribute('src')) && /size=l/.test(img1().dataset.dctl || ''), 'standard size: the small preview, the sharp one noted');
  range().value = '7'; range().dispatchEvent(new w.Event('input', {bubbles: true}));
  check(root.style.getPropertyValue('--dc-tw') === '7rem' && root.classList.contains('dc-tsm'), 'the slider at 7: small cards (picture only)');
  check(await until(async () => (await saved('dc_tile_d')) === '7'), 'the size is saved for the person (computer)');
  check(!(await saved('dc_tile_m')), '... the phone keeps its own (none)');
  // Ctrl + wheel: on the card area it changes the size, on the bar it is the browser's
  const card = d.querySelector('.dc-grid .dc-card > button[data-dco]');
  const wh = el => { const e = new w.WheelEvent('wheel', {deltaY: -100, ctrlKey: true, bubbles: true, cancelable: true}); el.dispatchEvent(e); return e.defaultPrevented; };
  check(!wh(d.querySelector('.dc-bar')) && root.style.getPropertyValue('--dc-tw') === '7rem', 'Ctrl + wheel on the bar: not taken (the page zoom stays the browser\'s)');
  check(wh(card), 'Ctrl + wheel on the card area: taken');
  wh(card);  // two steps of 100 px up: 7 rem x 1.28 x 1.28 = about 11.5
  check(await until(() => parseFloat(root.style.getPropertyValue('--dc-tw')) > 10), 'Ctrl + wheel up on the cards: bigger ' + root.style.getPropertyValue('--dc-tw'));
  check(parseFloat(root.style.getPropertyValue('--dc-tw')) < 20, '... step by step, not at once to the end');
  // Ctrl + Plus / Minus / 0 with the focus on a card
  await until(() => !w.eval('TS.v'));  // the wheel has come to rest (saved), a redraw after the save may have drawn new cards
  const cardNow = () => d.querySelector('.dc-grid .dc-card > button[data-dco]');
  cardNow().focus();
  const before = parseFloat(root.style.getPropertyValue('--dc-tw'));
  keyOn(w, d.activeElement, '+', {ctrlKey: true});
  check(parseFloat(root.style.getPropertyValue('--dc-tw')) > before, 'Ctrl + Plus on a card: bigger ' + JSON.stringify([before, root.style.getPropertyValue('--dc-tw'), !!d.activeElement?.closest?.('.dc-grid')]));
  for (let i = 0; i < 12; i++) keyOn(w, d.activeElement, '+', {ctrlKey: true});
  check(root.style.getPropertyValue('--dc-tw') === '28rem' && range().value === '28', 'at most 28 rem, the slider follows');
  check(/size=l/.test(img1().getAttribute('src')), 'big cards: the sharp preview (?size=l)');
  keyOn(w, d.activeElement, '0', {ctrlKey: true});
  check(root.style.getPropertyValue('--dc-tw') === '11rem' && !/size=l/.test(img1().getAttribute('src')), 'Ctrl + 0: the standard size, the small preview again');
  for (let i = 0; i < 3; i++) keyOn(w, d.activeElement, '-', {ctrlKey: true});
  check(root.classList.contains('dc-tsm'), 'Ctrl + Minus: smaller, small cards');
  range().value = '20'; range().dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(async () => (await saved('dc_tile_d')) === '20'), 'the last size (20) is saved');
  w.close();
  // remembered after loading anew
  const w2 = await boot({user: 'alice', hash: 'docs'}), d2 = w2.document;
  await until(() => d2.querySelectorAll('.dc-card').length === 3 && d2.querySelector('.dc-bar input.ts-range'));
  check(await until(() => d2.documentElement.style.getPropertyValue('--dc-tw') === '20rem') && d2.querySelector('.dc-bar input.ts-range').value === '20', 'loaded anew: the size is kept');
  check(/size=l/.test(d2.querySelector(`.dc-view [data-dco="${D1}"] .dc-th img`)?.getAttribute('src') || ''), '... with the sharp preview at once');
  // the file store: the documents' folder as cards, the same slider and size
  const folder = (await call('GET', `/api/docs/${D1}`)).parent_id;
  w2.location.hash = '#ablage/' + folder;
  check(await until(() => d2.querySelector(`.abview .dc-grid [data-dco="${D1}"]`), 80), 'the file store shows the documents\' folder as cards');
  const ar = d2.querySelector('.abview input.ts-range');
  check(ar && ar.value === '20' && d2.documentElement.style.getPropertyValue('--dc-tw') === '20rem', 'the file store: the same slider, the same size');
  ar.value = '8'; ar.dispatchEvent(new w2.Event('input', {bubbles: true}));
  check(d2.documentElement.classList.contains('dc-tsm') && await until(async () => (await saved('dc_tile_d')) === '8'), 'the slider of the file store sets the same size');
  w2.close();
  // phone: its own size
  const m = await boot({user: 'alice', hash: 'docs', mobile: true}), dm = m.document;
  await until(() => dm.querySelectorAll('.dc-card').length === 3 && dm.querySelector('.dc-bar input.ts-range'));
  check(dm.querySelector('.dc-bar input.ts-range').value === '9.5' && dm.documentElement.style.getPropertyValue('--dc-tw') === '9.5rem', 'phone: its own standard size (9.5), not the computer\'s 8');
  const mr = dm.querySelector('.dc-bar input.ts-range'); mr.value = '12'; mr.dispatchEvent(new m.Event('input', {bubbles: true}));
  check(await until(async () => (await saved('dc_tile_m')) === '12') && (await saved('dc_tile_d')) === '8', 'phone: saved apart, the computer keeps 8');
  m.close();
  await call('PATCH', '/api/settings', {dc_tile_d: '11'});

  // ================= Firefox: the real columns at 2560 px
  await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 2560, height: 1300}});
    await nav(B + '#docs');
    const wait = async (js, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(250); } return false; };
    check(await wait(`document.querySelectorAll('.dc-card').length === 3 && !!document.querySelector('.dc-bar .ts-range')`), 'Firefox: three cards, the slider');
    const set = v => ev(`(() => { const r = document.querySelector('.dc-bar .ts-range'); r.value = '${v}'; r.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    const cols = () => ev(`getComputedStyle(document.querySelector('.dc-grid')).gridTemplateColumns.split(' ').length`);
    const c11 = await cols();
    await set(7);
    check(await wait(`document.documentElement.classList.contains('dc-tsm')`), 'Firefox: 7 rem, small cards');
    const c7 = await cols();
    await set(28);
    check(await wait(`getComputedStyle(document.documentElement).getPropertyValue('--dc-tw').trim() === '28rem'`), 'Firefox: 28 rem');
    const c28 = await cols();
    check(c7 > c11 && c11 > c28 && c7 >= 14, `Firefox 2560 px: small cards = more columns over the full width (7: ${c7}, 11: ${c11}, 28: ${c28})`);
    const gw = await ev(`Math.round(document.querySelector('.dc-grid').getBoundingClientRect().width)`);
    check(gw > 2000, 'Firefox: the cards use the full width (no 68.75rem page, #4840) ' + gw);
    check(await wait(`(() => { const i = document.querySelector('.dc-view [data-dco="${D1}"] .dc-th img'); return !!i && /size=l/.test(i.src) && i.complete && i.naturalWidth === 800; })()`, 60), 'Firefox: the big card shows the sharp preview, 800 px wide');
    await shot('p2583-tiles-28.png');
    await set(7);
    await wait(`document.documentElement.classList.contains('dc-tsm')`);
    // (the one card the mouse may rest on shows its name: at most one with text)
    const hid = await ev(`(() => { const cs = [...document.querySelectorAll('.dc-card')]; return {n: cs.length, shown: cs.filter(c => getComputedStyle(c.querySelector('.dc-ct')).opacity !== '0').length, mt: cs.filter(c => c.querySelector('.dc-mt') && getComputedStyle(c.querySelector('.dc-mt')).display !== 'none').length}; })()`);
    check(hid && hid.n === 3 && hid.shown <= 1 && hid.mt === 0, 'Firefox: small cards show no text (picture only; the name only on hover / focus) ' + JSON.stringify(hid));
    await shot('p2583-tiles-7.png');
    // phone: no sideways scrolling even with a big size
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#docs');
    check(await wait(`document.querySelectorAll('.dc-card').length === 3`), 'Firefox phone: the cards');
    await ev(`(() => { const r = document.querySelector('.dc-bar .ts-range'); r.value = '28'; r.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    const p = await ev(`(() => { const v = document.querySelector('.dc-view'), g = document.querySelector('.dc-grid'); return {sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth, cols: getComputedStyle(g).gridTemplateColumns.split(' ').length}; })()`);
    check(p && p.sw <= p.cw + 1 && p.cols === 1, 'Firefox phone: the biggest size = one column, nothing sideways ' + JSON.stringify(p));
    await shot('p2583-tiles-phone.png');
  });

  console.log(`p2583_e_tilesize: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
