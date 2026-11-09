// 2.778.0 UI test, part C (#5383): the walk-through of credit card positions and bank bookings with candidate cards.
// kalmido-suite: fresh
// freelancer-matrix: office (Frida, a person without an organisation: the bank walk-through in her own office, desktop and phone)
// Own container (start.sh, mode workspaces), Firefox. Invented statements and receipts only (receipts = small PNG pictures).
// - the list shows the candidate card (preview picture really loaded, amount) instead of the text suggestion
// - credit card (Alice, organisation): "Go through" -> "1 of 2" (the foreign fee needs no receipt from the start), the card's
//   preview + amount, "Take over" -> the next open position ("2 of 2"), "Undo" -> back to it, open again on the server; keys
//   1 + Enter take it again, the next one by its button -> the end view
// - bank (Frida, desktop): the suggestion card in the list, the walk-through: take -> "2 of 3", undo -> "1 of 3", open again
// - bank (Frida, phone 390 px): one card per screen width, no sideways scroll of the page, a swipe on the booking goes on / back
const path = require('path');
const zlib = require('zlib');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2778_c_walk_ui', check, shots: 'P2778C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const pdf = lines => {  // a PDF with a text layer, hand-written (as p2444_a_cards_ui.js)
  const stream = `BT /F1 10 Tf 12 TL 40 760 Td\n${lines.map(x => `(${x}) Tj T*`).join('\n')}\nET`;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n${offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('')}trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return out;
};
// a small PNG (a coloured sheet with stripes): the receipt picture whose preview the card shows
const CRC = Array.from({length: 256}, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
const crc = b => { let c = 0xffffffff; for (const x of b) c = CRC[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const chunk = (t, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([l, td, c]); };
const png = (rgb, w = 120, h = 160) => {
  const ih = Buffer.alloc(13); ih.writeUInt32BE(w, 0); ih.writeUInt32BE(h, 4); ih[8] = 8; ih[9] = 2;
  const raw = Buffer.alloc((w * 3 + 1) * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) { const o = y * (w * 3 + 1) + 1 + x * 3, s = (y >> 3) % 2 ? 40 : 0; raw[o] = rgb[0] - s; raw[o + 1] = rgb[1] - s; raw[o + 2] = rgb[2] - s; }
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ih), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
};
const upload = async (ck, url, field, name, data, type, extra = {}) => { const fd = new FormData(); fd.append(field, new Blob([data], {type}), name); for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
// a receipt picture in the documents of ws with amount / date (the person's own values: the recognition keeps them)
const receipt = async (ck, ws, name, rgb, amount, date, cat) => {
  const up = await upload(ck, '/api/docs', 'files', name, png(rgb), 'image/png', {ws});
  const id = (up.ids || [])[0];
  check(!!id, `the receipt ${name} is uploaded ` + JSON.stringify(up).slice(0, 200));
  await sleep(1200);
  const p = await call(ck, 'PATCH', `/api/docs/${id}`, {amount, date, name: name.replace(/\.png$/, '')});
  if (cat) await call(ck, 'PUT', `/api/docs/${id}/receipt`, {category: cat, vat_pct: '19'});
  check(p.http === 200, `the receipt ${name} has amount and date ${p.http}`);
  return id;
};
const de = iso => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;

(async () => {
  await sleep(600);
  const today = TC.today();
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'de'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'de', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  // ---- the credit card of the organisation: three positions, receipts for two of them
  const card = await call(CA, 'POST', '/api/office/cards', {holder_id: me.id, last4: '4711'});
  const st = await upload(CA, `/api/office/cards/${card.id}/statements`, 'file', 'abrechnung.pdf', pdf(['Abrechnung vom 15.01.2025', 'Karte 5232 12XX XXXX 4711', '03.01. 04.01. Cafe Beispiel Berlin 12,50-', '05.01. 05.01. Cloud Beispiel Inc USD 20,00 18,40-', 'Auslandseinsatzentgelt 0,32-', 'Neuer Saldo 31,22-']), 'application/pdf');
  check(st.http === 201 && st.read, 'the statement read ' + st.http);
  const sid = st.statement?.id;
  await receipt(CA, `org:${org.id}`, 'cafe-beispiel.png', [230, 200, 120], '12.50', '2025-01-03');
  await receipt(CA, `org:${org.id}`, 'cloud-beispiel.png', [120, 180, 230], '18.40', '2025-01-05');
  const lines = async () => (await call(CA, 'GET', `/api/office/cards/statements/${sid}`)).lines || [];
  // ---- Frida without an organisation: three money-out bookings, a receipt picture for each
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const fws = (await call(CF, 'GET', '/api/office/books')).upload_ws || 'private';
  await receipt(CF, fws, 'software-abo.png', [200, 120, 200], '119.00', today, 'Software');
  await receipt(CF, fws, 'druckerei.png', [120, 220, 140], '45.00', today, 'Werbung');
  await receipt(CF, fws, 'bahnticket.png', [220, 140, 120], '12.00', today, 'Reise');
  const csv = `Buchungstag;Auftraggeber/Empfänger;Verwendungszweck;Betrag\n${de(today)};Software Beispiel GmbH;Abo;-119,00\n${de(today)};Druckerei Muster;Flyer;-45,00\n${de(today)};Bahn Beispiel;Ticket;-12,00\n`;
  const pv = await call(CF, 'POST', '/api/office/bank/import/preview', {text: csv});
  const mapping = {}; for (const k of ['date', 'amount', 'amount_in', 'amount_out', 'title', 'counterpart', 'decimal', 'date_format']) mapping[k] = pv.guess?.[k] ?? null;
  const imp = await call(CF, 'POST', '/api/office/bank/import', {text: csv, filename: 'konto.csv', mapping});
  check(imp.http === 201 && imp.count === 3, 'three bookings imported ' + imp.http);
  const openTx = async () => ((await call(CF, 'GET', '/api/office/bank/tx?state=open')).items || []).length;
  // the server hands the preview's address along (only receipts; the thumb routes check the rights)
  const tx = (await call(CF, 'GET', '/api/office/bank/tx?state=open')).items || [];
  check(tx.length === 3 && tx.every(t => (t.suggestions || []).some(s => s.kind === 'receipt' && /^\/api\/(docs|files\/nodes)\/\d+\/thumb\?v=/.test(s.thumb || ''))),
    'every open booking suggests its receipt with a preview address ' + JSON.stringify(tx.map(t => t.suggestions)).slice(0, 400));

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.ok)`);
  const click = sel => `(() => { const e = ${sel}; if (!e) return 0; e.click(); return 1; })()`;
  const W = `document.querySelector('.wlkdlg')`;
  const progIs = t => `(${W}?.querySelector('[data-wlk-n]')?.textContent.trim() === ${JSON.stringify(t)})`;
  const headHas = re => `${re}.test(${W}?.querySelector('.wlk-tx')?.textContent || '')`;
  // a candidate card with its picture really loaded and the amount shown
  const cardOk = (scope, amt) => `(() => { const c = document.querySelector('${scope} .ocd'); const i = c?.querySelector('.ocd-img'); return !!i && i.complete && i.naturalWidth > 0 && ${amt}.test(c.querySelector('.ocd-amt')?.textContent || ''); })()`;
  const prog = () => `${W}?.querySelector('[data-wlk-n]')?.textContent`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ---- credit card
    await nav(B + '#office/cards');
    check(await ready(ev, `!!document.querySelector('[data-cc="card"]')`, 100), 'the card is listed');
    await ev(click(`document.querySelector('[data-cc="card"]')`));
    check(await ready(ev, `!!document.querySelector('[data-cc="stmt"]')`), 'the card lists its statement');
    await ev(click(`document.querySelector('[data-cc="stmt"]')`));
    check(await ready(ev, `!!document.querySelector('[data-cc="confirm"]')`), 'the statement waits for the confirmation');
    check(await ev(`!document.querySelector('[data-cc="walk"]')`), 'no walk-through before the positions are confirmed');
    await ev(click(`document.querySelector('[data-cc="confirm"]')`));
    check(await ready(ev, cardOk('.ccsug', '/12,50/')), 'the list: the suggestion is a candidate card with the picture and 12,50 ' + await ev(`document.querySelector('.ccsug')?.outerHTML.slice(0, 500) || 'none'`));
    check(await ev(`!document.querySelector('.ccsug .ofcrow')`), 'the list: no text row any more');
    check(await ev(`(() => { const c = document.querySelector('.ccsug .ocd'), r = c.getBoundingClientRect(); return r.height < 360 && document.querySelector('.ccsug').getBoundingClientRect().height < r.height + 40; })()`), 'the list: the card sits right under "Vorschlag", no empty space');
    await ev(click(`document.querySelector('.ccl [data-cc="pick"]')`));
    check(await ready(ev, `!!document.querySelector('.bnkother .ocd [data-cc="match"]') && !document.querySelector('.bnkother .ofcrow')`), '"Select receipt…" lists candidate cards');
    await shot('p2778c-cards-list.png');
    await ev(click(`document.querySelector('[data-cc="walk"]')`));
    // the foreign fee needs no receipt from the start (ccread: kind fee), so two positions are open
    check(await ready(ev, progIs('1 von 2') + ` && ${headHas('/Cafe Beispiel/')}`), 'the walk-through opens at the first open position "1 von 2": ' + await ev(prog()));
    check(await ready(ev, cardOk('.wlkdlg .wlk-cands', '/12,50/')), 'the walk-through: the card shows the picture and the amount');
    check(await ev(`/1/.test(${W}.querySelector('.ocd-key')?.textContent || '')`), 'mouse / keyboard: the card names its key');
    await shot('p2778c-cards-walk.png');
    await ev(click(`${W}.querySelector('.wlk-foot [data-wlk="take"]')`));
    check(await ready(ev, progIs('2 von 2') + ` && ${headHas('/Cloud Beispiel/')}`), '"Übernehmen" goes to the next open position "2 von 2": ' + await ev(prog()));
    check((await lines()).filter(x => x.state === 'matched').length === 1, 'the server: one position matched');
    check(await ready(ev, `!!${W}.querySelector('[data-wlk="undo"]')`), 'the undo button for the last step');
    await ev(click(`${W}.querySelector('[data-wlk="undo"]')`));
    check(await ready(ev, progIs('1 von 2') + ` && ${headHas('/Cafe Beispiel/')} && !!${W}.querySelector('.wlk-cands .ocd')`), 'undo: back at the first position with its card');
    let ls = await lines();
    check(!ls.some(x => x.state === 'matched'), 'the server: undo opened the position again ' + JSON.stringify(ls.map(x => x.state)));
    // keys: 1 chooses, Enter takes
    await ev(`(() => { for (const k of ['1', 'Enter']) document.dispatchEvent(new KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true})); return 1; })()`);
    check(await ready(ev, progIs('2 von 2') + ` && ${headHas('/Cloud Beispiel/')}`), 'keys 1 + Enter take the card, the next position comes');
    check(await ready(ev, cardOk('.wlkdlg .wlk-cands', '/18,40/')), 'the second position: its card (18,40) with the picture');
    check(await ev(`/USD/.test(${W}.querySelector('.wlk-tx')?.textContent || '')`), 'the foreign currency is shown');
    await ev(click(`${W}.querySelector('.wlk-foot [data-wlk="take"]')`));
    check(await ready(ev, `/Jede Buchung ist erledigt/.test(${W}?.textContent || '')`), 'the end view after the last one');
    ls = await lines();
    check(ls.filter(x => x.state === 'matched').length === 2 && ls.filter(x => x.state === 'noreceipt').length === 1, 'the server: two matched, one needs no receipt ' + JSON.stringify(ls.map(x => x.state)));
    await ev(click(`${W}.querySelector('[data-wlk="close"]')`));
    check(await ready(ev, `!document.querySelector('.wlkdlg') && document.querySelectorAll('.ccl .bnkrow.done').length === 3`), 'closed: the list shows the three done positions');

    // ---- bank, Frida (no organisation), desktop
    await signIn(ev, 'frida');
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/bank');
    check(await ready(ev, `document.querySelectorAll('.bnklist .bnkrow').length === 3`, 100), 'frida: three open bookings');
    check(await ready(ev, cardOk('.bnkrow .bnksug', '/(119|45|12),00/')), 'the bank list: the suggestion is a candidate card with the picture');
    await ev(click(`document.querySelector('.bnkrow [data-bnk="other"]')`));
    check(await ready(ev, `!!document.querySelector('.bnkother .ocd [data-bnk="match"][data-kind="receipt"]') && !document.querySelector('.bnkother .ofcrow')`), '"Other receipt…" lists candidate cards');
    await ev(click(`document.querySelector('[data-bnk="walk"]')`));
    check(await ready(ev, progIs('1 von 3') + ' && ' + cardOk('.wlkdlg .wlk-cands', '/(119|45|12),00/')), 'the bank walk-through: "1 von 3", the card with picture and amount: ' + await ev(prog()));
    const first = await ev(`${W}.querySelector('.wlk-tx b').textContent`);
    check(await ev(`!!${W}.querySelector('[data-wlk="mark"][data-v="ignored"]') && !!${W}.querySelector('[data-wlk="mark"][data-v="cash"]')`), 'bank: also "Ignorieren" and "Kasse"');
    await shot('p2778c-bank-walk.png');
    await ev(click(`${W}.querySelector('.wlk-foot [data-wlk="take"]')`));
    check(await ready(ev, progIs('2 von 3') + ` && ${W}.querySelector('.wlk-tx b').textContent !== ${JSON.stringify(first)}`), 'bank: "Übernehmen" goes to the next booking "2 von 3": ' + await ev(prog()));
    check(await openTx() === 2, 'the server: one booking matched');
    await ev(click(`${W}.querySelector('[data-wlk="undo"]')`));
    check(await ready(ev, progIs('1 von 3') + ` && ${W}.querySelector('.wlk-tx b').textContent === ${JSON.stringify(first)}`), 'bank: undo goes back to the booking "1 von 3"');
    check(await ready(ev, `!!${W}.querySelector('.wlk-cands .ocd')`), 'bank: its card is there again');
    check(await openTx() === 3, 'the server: the booking is open again');
    await ev(click(`${W}.querySelector('[data-wlk="mark"][data-v="noreceipt"]')`));
    check(await ready(ev, progIs('2 von 3')), 'bank: "Kein Beleg nötig" goes on too');
    check(await openTx() === 2, 'the server: marked as needing no receipt');
    await ev(click(`${W}.querySelector('[data-wlk="undo"]')`));
    check(await ready(ev, progIs('1 von 3') + ` && ${W}.querySelector('.wlk-tx b').textContent === ${JSON.stringify(first)}`), 'bank: undo of the mark goes back');
    check(await openTx() === 3, 'the server: open again after the undo of the mark');
    await ev(click(`${W}.querySelector('[data-wlk="close"]')`));

    // ---- bank, phone width: one card per screen, a swipe goes on and back
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await nav(B + '#office/bank');
    check(await ready(ev, `!!document.querySelector('[data-bnk="walk"]')`, 100), 'phone: the button "Durchgehen"');
    await ev(click(`document.querySelector('[data-bnk="walk"]')`));
    check(await ready(ev, progIs('1 von 3') + ' && ' + cardOk('.wlkdlg .wlk-cands', '/(119|45|12),00/')), 'phone: the walk-through with its card');
    check(await ev(`(() => { const r = ${W}.querySelector('.wlk-cands'), c = r.querySelector('.ocd'); return Math.abs(c.getBoundingClientRect().width - r.clientWidth) < 2; })()`), 'phone: one card fills the width');
    check(await ev(`document.documentElement.scrollWidth <= innerWidth + 1 && ${W}.querySelector('.card').scrollWidth <= ${W}.querySelector('.card').clientWidth + 1`), 'phone: no sideways scroll');
    const swipe = (x0, x1) => `(() => { const t = ${W}.querySelector('.wlk-tx'), o = (k, x) => new PointerEvent(k, {bubbles: true, cancelable: true, clientX: x, clientY: 200, pointerId: 9, pointerType: 'touch', isPrimary: true});
      t.dispatchEvent(o('pointerdown', ${x0})); t.dispatchEvent(o('pointermove', ${(x0 + x1) / 2})); t.dispatchEvent(o('pointerup', ${x1})); return 1; })()`;
    await ev(swipe(320, 60));
    check(await ready(ev, progIs('2 von 3')), 'phone: a swipe to the left shows the next booking: ' + await ev(prog()));
    await ev(swipe(60, 320));
    check(await ready(ev, progIs('1 von 3')), 'phone: a swipe to the right goes back: ' + await ev(prog()));
    await shot('p2778c-bank-phone.png');
    await ev(click(`${W}.querySelector('.wlk-foot [data-wlk="take"]')`));
    check(await ready(ev, progIs('2 von 3')), 'phone: "Übernehmen" goes on');
    check(await openTx() === 2, 'phone: the server has the match');
  });
  console.log(`p2778_c_walk_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
