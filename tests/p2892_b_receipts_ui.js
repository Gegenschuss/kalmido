// 2.892.0 UI test, part B (#5453): Office > Receipts on a phone (360 px, a finger). Own container (start.sh, mode workspaces),
// kalmido-suite: fresh
// Firefox with touch. Invented companies and figures only.
// - the first receipt row stands in the first screen without scrolling (one tool row: "Upload receipt" + "More"; Select,
//   the kinds, CSV and ZIP behind "More")
// - "Upload receipt" is ONE button: its sheet offers the camera and the files
// - a complete receipt (amount, date, category, VAT rate) carries no "With hints" tag and its sheet shows no hint block;
//   a receipt without VAT rate keeps the tag (a real gap)
// - the filters are folded with the number of the active filters
// - the receipt sheet: the currency in the row of the amount, the foot in one row ("More" holds Open document / Bill on)
// - frida without an organisation (her private office): the same tool row, a complete receipt without "With hints"
// freelancer-matrix: office (frida has no organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2892_b_receipts_ui', check, shots: 'P2892B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2892B_NOSTART !== '1' && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const today = TC.today();

function tinyPdf(text) {  // a one-page PDF with a text layer (no figures: as a scan the recognition could not read)
  const s = `BT /F1 12 Tf 40 700 Td (${text}) Tj ET`;
  const o = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${s.length} >>\nstream\n${s}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  o.forEach((x, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${x}\nendobj\n`; });
  const xr = out.length; out += `xref\n0 ${o.length + 1}\n0000000000 65535 f \n` + offs.map(n => String(n).padStart(10, '0') + ' 00000 n \n').join('');
  return out + `trailer\n<< /Size ${o.length + 1} /Root 1 0 R >>\nstartxref\n${xr}\n%%EOF\n`;
}
async function receipt(ck, ws, name, amount, day, category, vat) {
  const fd = new FormData(); fd.append('ws', ws); fd.append('files', new Blob([tinyPdf('Beleg ' + name)], {type: 'application/pdf'}), name);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  const j = await r.json(); check(r.status === 201, 'upload ' + name + ' ' + r.status);
  const id = j.ids[0];
  for (let i = 0; i < 120; i++) { const d = await call(ck, 'GET', `/api/docs/${id}`); if (d.state === 'done' || d.state === 'error') break; await sleep(250); }  // the recognition ran (it stores the hints)
  check((await call(ck, 'PATCH', `/api/docs/${id}`, {amount, date: day})).http === 200, 'amount + date ' + name);
  check((await call(ck, 'PUT', `/api/docs/${id}/receipt`, {category, vat_pct: vat, keep: true})).http === 200, 'receipt ' + name);
  return id;
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Gegenlicht Muster GbR', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const ws = `org:${org.id}`;
  check((await call(CA, 'PUT', '/api/office/settings', {pack: 'DE'})).http === 200, 'the office country (no country card on top)');
  // complete: amount, date, category, VAT rate (the 2.786 walk showed "6 hints" at such a receipt)
  const R1 = await receipt(CA, ws, 'objektivmiete-verleih-nord.pdf', '357.00', today, 'Equipment rental', '19');
  const R2 = await receipt(CA, ws, 'tankstelle-oktober.pdf', '84.20', today, 'Travel', '19');
  // a real gap: no VAT rate
  const R3 = await receipt(CA, ws, 'kopierladen.pdf', '12.50', today, 'Material', null);

  // P4: frida without an organisation, her private office
  check((await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []})).http < 300, 'user frida (no organisation)');
  const FK = await login('frida');
  await call(FK, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  check((await call(FK, 'PUT', '/api/office/settings', {pack: 'DE'})).http === 200, 'frida: the office country');
  const RF = await receipt(FK, 'private', 'druckerei-beispiel.pdf', '48.00', today, 'Material', '19');

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const rows = `document.querySelectorAll('.rcl-list [data-rcl="rc"]').length`;
  const row = id => `document.querySelector('.rcl-list [data-rcl="rc"][data-id="${id}"]')`;
  const popItems = `[...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].map(b => b.textContent.trim())`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/receipts');
    check(await ready(ev, `${rows} === 3`, 120), 'Office > Receipts: three receipts ' + await ev(`location.hash + ' ' + ${rows}`).catch(e => String(e)));
    // the hints: only the receipt without VAT rate is tagged (the list fills the stale checks; wait until it settled)
    check(await ready(ev, `!!${row(R3)}?.querySelector('.rcl-hint')`, 80), 'the receipt without VAT rate: "With hints" ' + await ev(`${row(R3)}?.textContent || ''`));
    check(await ev(`!${row(R1)}.querySelector('.rcl-hint') && !${row(R2)}.querySelector('.rcl-hint')`), 'complete receipts: no "With hints" ' + await ev(`${row(R1)}.textContent.replace(/\\s+/g, ' ')`));
    // the first screen
    await ev(`(() => { scrollTo(0, 0); return 1; })()`);
    const first = JSON.parse(await ev(`JSON.stringify((() => { const b = document.querySelector('.rcl-list > li').getBoundingClientRect(); return {top: b.top, bottom: b.bottom, h: innerHeight, y: scrollY}; })())`));
    check(first.y === 0 && first.top > 0 && first.bottom <= first.h, 'the first receipt row in the first screen, without scrolling ' + JSON.stringify(first));
    check(await ev(`(() => { const t = document.querySelector('.rcl-tools'), bs = [...t.querySelectorAll('.btn')].filter(b => b.getClientRects().length); return bs.length === 2 && bs.every(b => Math.abs(b.getBoundingClientRect().top - bs[0].getBoundingClientRect().top) < 2) && !!t.querySelector('.bk-shot') && !!t.querySelector('.rcl-mbtn'); })()`),
      'one tool row: "Upload receipt" + "More" ' + await ev(`[...document.querySelectorAll('.rcl-tools .btn')].filter(b => b.getClientRects().length).map(b => b.textContent.trim()).join(' | ')`));
    check(await ev(`!document.querySelector('.rcl-filters').open && !document.querySelector('.rcl-filters summary .rotag')`), 'filters folded, no number while none is set');
    check(await ev(`!document.querySelector('.bk-photohint')`), 'the office holds receipts: no line of explanation');
    await shot('p2892-b-belege-phone.png');
    // the one upload button: camera or files
    await ev(`(() => { document.querySelector('.rcl-tools .bk-shot').click(); return 1; })()`);
    check(await ready(ev, `${popItems}.length === 2`, 20), 'Upload receipt: a sheet with two ways ' + await ev(`JSON.stringify(${popItems})`));
    check(await ev(`/Photograph receipt/.test(${popItems}[0]) && /Select files/.test(${popItems}[1])`), 'camera, then files');
    check(await ev(`document.querySelector('#bk-file').getAttribute('capture') === 'environment' && document.querySelector('#bk-files').multiple`), 'the inputs stay (camera with capture, files several)');
    await ev(`(() => { closePop(); return 1; })()`);
    // More: Select, CSV, ZIP
    await ev(`(() => { document.querySelector('.rcl-tools .rcl-mbtn').click(); return 1; })()`);
    check(await ready(ev, `${popItems}.some(t => /ZIP for the tax adviser/.test(t))`, 20), 'More: ' + await ev(`JSON.stringify(${popItems})`));
    check(await ev(`${popItems}.some(t => /^Select/.test(t)) && ${popItems}.some(t => /CSV/.test(t))`), 'More holds Select and CSV');
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => /^Select/.test(b.textContent.trim())).click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.rcl-pickin').length === 3`, 20), 'Select from More: a box per row');
    await ev(`(() => { document.querySelector('.rcl-selbar [data-rcl="selx"]').click(); return 1; })()`);
    await ready(ev, `!document.querySelector('.rcl-pickin')`, 20);
    // a filter: folded with its number
    await ev(`(() => { rclSet({category: 'Travel'}); return 1; })()`);
    check(await ready(ev, `${rows} === 1`, 60), 'the category filter: one receipt');
    check(await ev(`!document.querySelector('.rcl-filters').open && document.querySelector('.rcl-filters summary .rotag')?.textContent.trim() === '1'`), 'filters stay folded and say 1');
    await ev(`(() => { rclSet({category: ''}); return 1; })()`);
    await ready(ev, `${rows} === 3`, 60);
    // the receipt without VAT rate: its sheet names the gap
    await ev(`(() => { rcl_open(${R3}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.bk-sheet details.rck')`, 60), 'receipt without VAT rate: the hint block is there');
    check(await ev(`/1 hint on this receipt/.test(document.querySelector('.bk-sheet details.rck summary').textContent)`), 'it counts the one real gap ' + await ev(`document.querySelector('.bk-sheet details.rck summary')?.textContent || ''`));
    await ev(`(() => { document.querySelector('.bk-sheet [data-m="close"]').click(); return 1; })()`);
    await ready(ev, `!document.querySelector('.bk-sheet')`, 20);
    // the receipt sheet of a complete receipt
    await ev(`(() => { rcl_open(${R1}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.bk-sheet #bk-amount')`, 60), 'the receipt sheet opens');
    // (the documents' part that draws the hint block is loaded since the sheet before)
    check(await ev(`!document.querySelector('.bk-sheet .rck')`), 'complete receipt: no hint block in the sheet ' + await ev(`(document.querySelector('.bk-sheet .bk-rx')?.textContent || '').slice(0, 200)`));
    check(await ev(`(() => { const i = document.querySelector('#bk-amount').getBoundingClientRect(), c = document.querySelector('.bk-sheet .bk-cur').getBoundingClientRect(); return c.height > 0 && c.left >= i.right && c.top < i.bottom && c.bottom > i.top; })()`), 'the currency beside the amount, in its row');
    check(await ev(`(() => { const bs = [...document.querySelectorAll('.bk-sheet .foot .btn')].filter(b => b.getClientRects().length); return bs.length === 3 && bs.every(b => Math.abs(b.getBoundingClientRect().top - bs[0].getBoundingClientRect().top) < 2); })()`),
      'the foot in one row: More, Cancel, Save ' + await ev(`[...document.querySelectorAll('.bk-sheet .foot .btn')].filter(b => b.getClientRects().length).map(b => b.textContent.trim()).join(' | ')`));
    await ev(`(() => { document.querySelector('.bk-sheet [data-m="more"]').click(); return 1; })()`);
    check(await ready(ev, `${popItems}.some(t => /Open document/.test(t))`, 20), 'More in the sheet: Open document ' + await ev(`JSON.stringify(${popItems})`));
    await ev(`(() => { closePop(); return 1; })()`);
    await shot('p2892-b-beleg-blatt-phone.png');

    // P4: frida (no organisation): her receipts page has the same tool row, the complete receipt has no hint tag
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev, 'frida') === 200, 'frida signed in');
    await nav(B + '#office/receipts');
    check(await ready(ev, `${rows} === 1 && !!${row(RF)}`, 120), 'frida: her receipt in the list ' + await ev(`location.hash + ' ' + ${rows}`).catch(e => String(e)));
    check(await ev(`(() => { const t = document.querySelector('.rcl-tools'); return !!t && !!t.querySelector('.bk-shot') && !!t.querySelector('.rcl-mbtn') && t.querySelector('.rcl-mbtn').getClientRects().length > 0; })()`), 'frida: the tool row with "Upload receipt" and "More"');
    check(await ready(ev, `!${row(RF)}.querySelector('.rcl-hint')`, 40), 'frida: a complete receipt without "With hints" ' + await ev(`${row(RF)}.textContent.replace(/\\s+/g, ' ')`));
  }, true);

  console.log(`p2892_b_receipts_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
