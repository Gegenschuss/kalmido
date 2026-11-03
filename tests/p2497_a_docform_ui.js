// kalmido-suite:
// 2.497.0 UI test, part A (#4046: the document view has one fixed grid of label + field, the receipt part only at a receipt,
// the actions in order with Delete apart at the end), own container (start.sh), Firefox (1280 px and phone 320 px). Invented
// data only. Alice has no organisation (private documents), so this is the freelancer case too.
// - all fields (receipt and document) start at the same left edge, labels too; the archive number is as wide as the title
// - a letter: no receipt fields, the button "Record as receipt" shows them; a receipt and an invoice with recognised values
//   show them at once; a saved value keeps them after a new load
// - Delete is the last action, set apart; "Add" is one chip per field, the recognised text a section with a heading
// - 320 px: no sideways scrolling, still one left edge
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2497_a_docform_ui', check, shots: 'P2497A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2497A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

function textPdf(lines) {  // a one-page PDF with a text layer, written by hand
  const stream = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${l}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return out;
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,docs'});
  const upload = async (name, lines) => {
    const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([textPdf(lines)], {type: 'application/pdf'}), name + '.pdf');
    const rr = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CA}, body: fd});
    const id = ((await rr.json()).ids || [])[0];
    for (let i = 0; i < 120; i++) { const d = await call(CA, 'GET', `/api/docs/${id}`); if (d.state === 'done' || d.state === 'failed') return d; await sleep(250); }
    return call(CA, 'GET', `/api/docs/${id}`);
  };
  const L = await upload('letter', ['Stadt Musterstadt', 'Bescheid ueber Ihren Antrag', 'Datum 01.10.2026', 'Mit freundlichen Gruessen']);
  check(L.state === 'done', 'setup: the letter was read ' + L.state);
  check(!L.extracted, 'setup: a letter has no invoice values ' + JSON.stringify(L.extracted));
  check(L.date === '2026-10-01', 'finding 5: the recognition fills the date of the letter ' + L.date);
  console.log('p2497_a: after the recognition: name=%s sender=%s type=%s date=%s', L.name, L.sender?.name, L.type?.name, L.date);
  const R = await upload('receipt', ['Quittung', 'Datum 02.10.2026']);
  const pr = await call(CA, 'PUT', `/api/docs/${R.id}/receipt`, {project_id: null, category: 'Material', vat_pct: '19', keep: true});
  check(pr.receipt?.is_receipt === true, 'setup: a receipt ' + pr.http);
  const I = await upload('invoice', ['Muster Bau GmbH', 'Rechnung Nr. 4711', 'Datum 03.10.2026', 'Netto 100,00 EUR', 'USt 19 % 19,00 EUR', 'Brutto 119,00 EUR']);
  check(!!I.extracted, 'setup: an invoice has recognised values ' + JSON.stringify(I.extracted));
  const Fee = await upload('fee', ['Stadt Musterstadt', 'Muster GmbH', 'Bescheid', 'Datum 04.10.2026', 'Gesamtbetrag 25,00 EUR']);

  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // the rows of the grid: left edge of the label and of the field, right edge of the field
  const GRID = `(() => { const vis = e => e.getClientRects().length > 0; const rows = [...document.querySelectorAll('.rc-slot .dc-f, .dc-form .dc-f')].filter(vis).filter(r => r.children[0].tagName === 'LABEL');
    return JSON.stringify(rows.map(r => { const a = r.children[0].getBoundingClientRect(), b = r.children[1].getBoundingClientRect(); return {f: r.children[0].htmlFor, l: Math.round(a.left), x: Math.round(b.left), r: Math.round(b.right)}; })); })()`;
  const same = (rows, k) => rows.length > 0 && rows.every(r => Math.abs(r[k] - rows[0][k]) <= 1);
  // a real page load (a hash alone leaves an open sheet as it is) and this very document
  const open = async (nav, ev, doc) => { await nav(B + 'static/icon.svg'); await nav(B + `#docs/${doc.id}`); return ready(ev, `document.querySelector('.dc-form #dc-name')?.value === ${JSON.stringify(doc.name)}`); };
  const noSide = `(() => { const W = document.documentElement.clientWidth, b = document.querySelector('.dc-body'), card = b.closest('.card') || b.parentElement, br = b.getBoundingClientRect().right;
    const out = [...b.querySelectorAll('*')].filter(e => e.getClientRects().length && e.getBoundingClientRect().right > br + .5).map(e => e.tagName + '.' + String(e.className).slice(0, 30) + ':' + Math.round(e.getBoundingClientRect().right - br));
    return JSON.stringify({W, sw: document.documentElement.scrollWidth, cs: card.scrollWidth, cc: card.clientWidth, bs: b.scrollWidth, bc: b.clientWidth, br: Math.round(br), out: out.slice(0, 8)}); })()`;
  const flat = s => { const o = JSON.parse(s); return o.sw <= o.W && o.cs <= o.cc && o.br <= o.W; };

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);

    // ---- a letter: no receipt fields, the button shows them
    check(await open(nav, ev, L), 'the letter opens');
    check(await ready(ev, `!!document.querySelector('.rc-slot [data-rc="open:0"]')`), 'a letter: the button "Record as receipt"');
    check(await ev(`!document.querySelector('#rc-proj') && !document.querySelector('.rc-h')`), 'a letter: no receipt part');
    await shot('p2497-a-letter-desktop.png');
    let rows = JSON.parse(await ev(GRID));
    check(rows.length >= 6, 'the fields of the document ' + rows.length);
    check(same(rows, 'l') && same(rows, 'x'), 'a letter: labels and fields each start at one left edge ' + JSON.stringify(rows));
    check(rows[0].x - rows[0].l >= 60, 'computer: the label stands left of its field');
    const widths = await ev(`(() => { const w = s => Math.round(document.querySelector(s).getBoundingClientRect().width); return JSON.stringify([w('#dc-name'), w('#dc-asn').valueOf() && w('.dc-f .dc-amt')]); })()`);
    const [wn, wa] = JSON.parse(widths);
    check(Math.abs(wn - wa) <= 2, 'the archive number row is as wide as the title ' + widths);
    // the actions
    const acts = `(() => { const r = e => e.getBoundingClientRect(), a = [...document.querySelectorAll('.dc-acts .btn')].filter(e => e.getClientRects().length); const del = a[a.length - 1], prev = a[a.length - 2];
      return JSON.stringify({n: a.length, last: del.dataset.dc, cl: del.classList.contains('dc-adel'), lines: new Set(a.map(e => Math.round(r(e).top))).size, apart: (r(del).top > r(prev).bottom || r(del).left - r(prev).right >= 16) && Math.abs(r(del).right - r(del.parentElement).right) <= 1}); })()`;
    let g = JSON.parse(await ev(acts));
    check(g.last === 'del' && g.cl, 'Delete is the last action ' + JSON.stringify(g));
    check(g.lines <= 2 && g.apart, 'closed: at most two lines of actions (it was three), Delete apart at the right edge ' + JSON.stringify(g));
    check(await ev(`document.querySelector('[data-dc="share"]')?.getClientRects().length === 0`), 'the rarer actions are folded behind More');
    await ev(`document.querySelector('[data-dc="actsmore"]')?.click()`);
    check(await ready(ev, `document.querySelector('[data-dc="actsmore"]')?.getAttribute('aria-expanded') === 'true' && document.querySelector('[data-dc="share"]')?.getClientRects().length > 0 && document.querySelector('[data-dc="xlink"]')?.getClientRects().length > 0`), 'More shows them');
    g = JSON.parse(await ev(acts));
    check(g.last === 'del', 'More open: Delete stays the last action ' + JSON.stringify(g));
    await shot('p2497-a-letter-more-desktop.png');
    await ev(`document.querySelector('[data-dc="actsmore"]')?.click()`);
    // the chips and the section
    check(await ev(`!document.querySelector('.dc-form .linkbtn[data-dc^="showopt"]') && !!document.querySelector('[data-dc="showopt:due"]') && !!document.querySelector('[data-dc="showopt:amount"]')`), 'one chip per optional field');
    check(await ev(`!!document.querySelector('.dc-text > summary h4')`), 'the recognised text is a section with a heading');
    await ev(`document.querySelector('[data-dc="showopt:due"]')?.click()`);
    check(await ready(ev, `!!document.querySelector('#dc-due') && document.querySelector('#dc-due').closest('.dc-f').getClientRects().length > 0 && !document.querySelector('[data-dc="showopt:due"]') && !!document.querySelector('[data-dc="showopt:amount"]')`), 'the chip opens its field only');
    rows = JSON.parse(await ev(GRID));
    check(same(rows, 'x'), 'the opened field stands in the grid ' + JSON.stringify(rows));
    // the button shows the fields, in the same grid
    await ev(`document.querySelector('.rc-slot [data-rc="open:0"]')?.click()`);
    check(await ready(ev, `!!document.querySelector('#rc-proj') && !document.querySelector('[data-rc="open:0"]')`), 'the button shows the receipt fields');
    rows = JSON.parse(await ev(GRID));
    check(rows.some(r => r.f === 'rc-proj') && same(rows, 'l') && same(rows, 'x'), 'receipt and document fields share one grid ' + JSON.stringify(rows));
    await shot('p2497-a-letter-open-desktop.png');
    const noRow = await call(CA, 'GET', `/api/docs/${L.id}/receipt`);
    check(noRow.receipt?.is_receipt === false, 'showing the fields alone makes nothing a receipt');
    await ev(`(() => { const c = document.querySelector('#rc-cat'); if (c) { c.value = 'Fees'; c.dispatchEvent(new Event('change', {bubbles: true})); } return 1; })()`);
    for (let i = 0; i < 20 && !(await call(CA, 'GET', `/api/docs/${L.id}/receipt`)).receipt?.is_receipt; i++) await sleep(250);
    check((await call(CA, 'GET', `/api/docs/${L.id}/receipt`)).receipt?.category === 'Fees', 'a value in the fields makes it a receipt');
    check(await open(nav, ev, L) && await ready(ev, `document.querySelector('#rc-cat')?.value === 'Fees'`), 'after a new load it shows the receipt part at once');
    await call(CA, 'PUT', `/api/docs/${L.id}/receipt`, {project_id: null, category: '', vat_pct: null});

    // ---- a receipt, an invoice with recognised values: the part at once
    check(await open(nav, ev, R) && await ready(ev, `document.querySelector('#rc-cat')?.value === 'Material'`), 'a receipt: the part at once');
    check(await ev(`!document.querySelector('[data-rc="open:0"]')`), 'a receipt: no button');
    rows = JSON.parse(await ev(GRID));
    check(same(rows, 'l') && same(rows, 'x'), 'a receipt: one grid ' + JSON.stringify(rows));
    await shot('p2497-a-receipt-desktop.png');
    check(await open(nav, ev, I) && await ready(ev, `!!document.querySelector('#rc-proj')`), 'an invoice with recognised values: the part at once');

    if (!Fee.extracted?.net && !Fee.extracted?.vat_pct && !Fee.extracted?.invoice_no) check(await open(nav, ev, Fee) && await ready(ev, `!!document.querySelector('[data-rc="open:0"]') && !document.querySelector('#rc-proj')`), 'a letter with a fee (a gross amount alone): the button, no receipt part ' + JSON.stringify(Fee.extracted));
    else check(false, 'setup: the letter with a fee has no net, rate or invoice number ' + JSON.stringify(Fee.extracted));

    // ---- phone 320 px
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 700}});
    check(await open(nav, ev, R) && await ready(ev, `!!document.querySelector('#rc-cat')`), 'phone: the receipt opens');
    const sr = await ev(noSide); check(flat(sr), 'phone 320 px, a receipt: no sideways scrolling ' + sr);
    rows = JSON.parse(await ev(GRID));
    check(same(rows, 'x') && rows.every(r => Math.abs(r.x - r.l) <= 1), 'phone: labels above the fields, one left edge ' + JSON.stringify(rows));
    await shot('p2497-a-receipt-phone.png');
    await ev(`document.querySelector('.dc-form').scrollIntoView()`);
    await shot('p2497-a-receipt-phone-form.png');
    check(await open(nav, ev, L) && await ready(ev, `!!document.querySelector('[data-rc="open:0"]')`), 'phone: the letter with its button');
    const sl = await ev(noSide); check(flat(sl), 'phone 320 px, a letter: no sideways scrolling ' + sl);
    await ev(`document.querySelector('[data-dc="actsmore"]')?.click()`);
    const sm = await ev(noSide); check(flat(sm), 'phone 320 px, More open: no sideways scrolling ' + sm);
    await ev(`document.querySelector('[data-dc="actsmore"]')?.click()`);
    check(await ev(`[...document.querySelectorAll('.dc-acts .btn')].pop().dataset.dc === 'del'`), 'phone: Delete is the last action');
    await ev(`document.querySelector('.dc-acts').scrollIntoView()`);
    await shot('p2497-a-letter-phone.png');
  }, false);

  console.log(`p2497_a_docform_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
