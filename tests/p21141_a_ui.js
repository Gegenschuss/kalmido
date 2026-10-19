// 2.114.1 UI tests, part A (office UI fixes), own container (start.sh), Firefox. A person without an organisation (private office):
// freelancer-matrix: office
// - #2017: the bank suggestion button says "Assign" (German "Zuordnen"); the second buttons are >= 44 px high at 390 px
// - #2254: "Heading" / "Text block" add a line without an error toast; saved once a title is typed; empty ones are left out
// - #2255: the tick "Calculate producing" keeps its size (< 2rem at 1440 px), text fields stay wide
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21141_a_ui', check, shots: 'P21141A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21141A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const day = n => { const d = new Date(TC.today() + 'T12:00:00'); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10); };
const de = iso => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'de'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: FEAT});
  await call(CA, 'PUT', '/api/office/settings', {company_fields: {name: 'Beispiel Film', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE', iban: 'DE02120300000000202051', bic: 'BYLADEM1001'}, producing_on: 1});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Weg 2', zip: '10115', city: 'Berlin', country: 'DE'});
  const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, service_from: day(20), items: [{title: 'Schnitt', qty: 1, rate: 1000}]});
  const fin = await call(CA, 'POST', `/api/office/docs/${inv.id}/finalize`);
  const csv = `Buchungstag;Auftraggeber/Empfänger;Verwendungszweck;Betrag\n${de(day(3))};Kunde Eins GmbH;Rechnung ${fin.number};1.190,00\n${de(day(2))};Bäckerei Beispiel;Brötchen;-4,50\n`;
  const pv = await call(CA, 'POST', '/api/office/bank/import/preview', {text: csv});
  const mapping = {}; for (const k of ['date', 'amount', 'amount_in', 'amount_out', 'title', 'counterpart', 'decimal', 'date_format']) mapping[k] = pv.guess?.[k] ?? null;
  await call(CA, 'POST', '/api/office/bank/import', {text: csv, filename: 'konto.csv', mapping});
  const offer = await call(CA, 'POST', '/api/office/docs', {project_title: 'Imagefilm', client_id: cl.id, items: [{title: 'Dreh', qty: 1, rate: 500}]});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    // ---- #2017
    await nav(B + '#office/bank');
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 2`, 80), 'the bank tab lists two bookings');
    check(await ev(`document.querySelector('.bnksug [data-bnk="match"]')?.textContent.trim() === 'Zuordnen'`), '#2017: the suggestion button says "Zuordnen": ' + JSON.stringify(await ev(`[document.querySelector('.bnksug [data-bnk="match"]')?.textContent, document.documentElement.lang, [...document.querySelectorAll('.bnkrow')].length, document.querySelector('.bnkrow')?.innerHTML.slice(0, 400)]`)));
    check(await ev(`(() => { const b = [...document.querySelectorAll('.bnkacts .btn')]; return b.length > 0 && b.every(x => x.getBoundingClientRect().height >= 43.5); })()`), '#2017: second buttons >= 44 px at 390 px');
    await shot('p21141-a-bank.png');
    // ---- #2254
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + `#office/offers/${offer.id}`);
    check(await ready(ev, `!!document.querySelector('[data-ofd="it-head"]')`, 80), 'the offer editor');
    await ev(`(() => { window.__t = []; const o = toast; toast = (m, ...a) => { __t.push(String(m)); return o(m, ...a); }; return 1; })()`);
    const n0 = await ev(`document.querySelectorAll('.ofdits > li').length`);
    await ev(`document.querySelector('[data-ofd="it-head"]').click()`);
    check(await ready(ev, `document.querySelectorAll('.ofdits > li').length === ${n0 + 1}`), '#2254: the empty heading line shows');
    await sleep(500);
    check(await ev(`__t.length === 0`), '#2254: no error toast ' + JSON.stringify(await ev('__t')));
    await ev(`document.querySelector('[data-ofd="it-text"]').click()`); await sleep(400);
    check(await ev(`__t.length === 0`), '#2254: text block: no error toast ' + JSON.stringify(await ev('__t')));
    const rate = `document.querySelector('.ofdits [data-i="0"][data-k="rate"]')`;
    await ev(`(() => { const e = ${rate}; e.value = '600'; e.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`); await sleep(700);
    check(await ev(`__t.length === 0`), '#2254: changing another line with empty ones: no error ' + JSON.stringify(await ev('__t')));
    await ev(`document.querySelector('[data-ofd="it-head"]').click()`); await sleep(300);
    await ev(`(() => { const e = document.querySelector('.ofdits [data-k="title"][data-i="${n0}"]') || [...document.querySelectorAll('.ofdits [data-k="title"]')].pop(); e.value = 'Phase eins'; e.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await sleep(800);
    const d = await call(CA, 'GET', `/api/office/docs/${offer.id}`);
    check((d.items || []).some(i => i.kind === 'heading' && i.title === 'Phase eins') && !(d.items || []).some(i => i.kind === 'heading' && !i.title), '#2254: the typed heading is saved, empty ones are not');
    // ---- #2255
    check(await ev(`(() => { const e = document.getElementById('ofd-producing_on'); return !!e && e.getBoundingClientRect().width < 32; })()`), '#2255: the tick is small at 1440 px');
    check(await ev(`(() => { const e = document.querySelector('.ofdgrid .row input:not([type=checkbox]):not(.numin)'); return !e || e.getBoundingClientRect().width > 100; })()`), '#2255: text fields stay wide');
    await shot('p21141-a-offer.png');
  }, false);

  console.log(`p21141_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
