// 2.121.0 UI tests, part C (#2096, #2094), own container (start.sh), Firefox (desktop + phone width). Invented figures only.
// - the receipt suggestion card of an agent shows amount, currency and VAT rate as fields; Accept with a changed amount
//   sets it; Undo brings the old values back (one step)
// - bookkeeping > receipts of the month: "Bill receipts on to a client" lists the receipts, nothing ticked = a message,
//   two ticked + markup = positions on the draft quotation, the rows say "billed on ..." and the button is gone; the
//   receipt sheet has its own button for one receipt
// - on a phone nothing sticks out to the side
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2121_c_ui', check, shots: 'P2121C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2121C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body, extra = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...extra}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const today = TC.today();

function textPdf(line) {
  const stream = `BT /F1 12 Tf 60 740 Td (${line}) Tj ET`;
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
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CA, 'PUT', '/api/office/settings', {lang: 'de', company_fields: {name: 'Studio Beispiel GmbH', street: 'Teststrasse 1', zip: '20000', city: 'Hamburg', country: 'DE'}});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Weg 1', zip: '10000', city: 'Berlin', country: 'DE'});
  const upload = async (name) => {
    const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([textPdf(name)], {type: 'application/pdf'}), name + '.pdf');
    const rr = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CA}, body: fd});
    const j = await rr.json(); const id = (j.ids || [])[0];
    for (let i = 0; i < 60; i++) { const d = await call(CA, 'GET', `/api/docs/${id}`); if (d.state !== 'wait' && d.state !== 'run') break; await sleep(500); }
    return id;
  };
  const receipt = async (name, amount, vat, cat) => {
    const id = await upload(name);
    await call(CA, 'PATCH', `/api/docs/${id}`, {amount, date: today, currency: 'EUR'});
    await call(CA, 'PUT', `/api/docs/${id}/receipt`, {project_id: null, category: cat, vat_pct: vat, keep: true});
    return id;
  };
  const R1 = await receipt('Baumarkt', '119.00', '19', 'Material');
  const R2 = await receipt('Taxi', '50.00', null, 'Travel');
  const R3 = await receipt('Buch', '107.00', '7', 'Books');
  const Q = await call(CA, 'POST', '/api/office/docs', {project_title: 'Film eins', client_id: cl.id});
  check(Q.http === 201 || Q.http === 200, 'setup: a draft quotation ' + Q.http);
  // an agent suggests amount + VAT rate for a separate document
  const DS = await upload('Hotel');
  const ag = await call(CA, 'POST', '/api/admin/agents', {username: 'rcbot', display_name: 'Rcbot'});
  await call(CA, 'POST', `/api/files/nodes/${DS}/shares`, {agent_id: ag.id, role: 'view'});
  const sg = await call(null, 'POST', `/api/v1/documents/${DS}/receipt-suggestion`, {amount: '119.00', currency: 'EUR', vat_pct: '19', category: 'Hotel'}, {Authorization: 'Bearer ' + ag.token});
  check(sg.http === 201, 'setup: the agent suggests amount + VAT rate ' + sg.http);
  await call(CA, 'PATCH', `/api/docs/${DS}`, {amount: '50.00', currency: 'USD'});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *, .rc-slot *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ---- #2096 the suggestion card
    await nav(B + `#docs/${DS}`);
    check(await ready(ev, `!!document.querySelector('.rc-slot .rc-sug [data-rcs="amount"]')`, 80), 'the suggestion card has an amount field');
    check(await ev(`(() => { const b = document.querySelector('.rc-slot .rc-sug'); return b.querySelector('[data-rcs="amount"]').value === '119.00' && b.querySelector('[data-rcs="currency"]').value === 'EUR' && b.querySelector('[data-rcs="vat_pct"]').value === '19'; })()`),
      'amount, currency and VAT rate come prefilled');
    await shot('p2121-c-suggest.png');
    await ev(`(() => { const b = document.querySelector('.rc-slot .rc-sug'); b.querySelector('[data-rcs="amount"]').value = '120.00'; b.querySelector('[data-rc^="accept"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.rc-slot .rc-sug')`, 60), 'Accept: the card is gone');
    const d1 = await call(CA, 'GET', `/api/docs/${DS}`);
    check(d1.amount === '120.00' && d1.currency === 'EUR', 'Accept with a changed amount sets it ' + d1.amount);
    check(await ev(`document.querySelector('#rc-vat')?.value === '19'`), 'the VAT rate of the receipt is set');
    await ev(`histStep('undo')`);
    check(await ready(ev, `!!document.querySelector('.rc-slot .rc-sug')`, 60), 'Undo: the suggestion is open again');
    const d2 = await call(CA, 'GET', `/api/docs/${DS}`);
    check(d2.amount === '50.00' && d2.currency === 'USD', 'Undo: the old amount and currency are back ' + d2.amount);
    // ---- #2094 bill receipts on to a client
    await nav(B + '#office/books');
    check(await ready(ev, `[...document.querySelectorAll('[data-bk="rc"]')].length >= 3 && !!document.querySelector('[data-bk="bill"]')`, 80), 'the receipts of the month and the button "Bill receipts on to a client"');
    await ev(`document.querySelector('[data-bk="bill"]').click()`);
    check(await ready(ev, `!!document.querySelector('#bkb-${R1}') && !!document.querySelector('#bkb-${R2}') && !!document.querySelector('#bkb-doc')`, 60), 'the dialog lists the receipts and the draft quotation');
    await ev(`document.querySelector('.ofcdlg [data-m="save"]').click()`);
    check(await ready(ev, `/Tick at least one receipt/.test(document.querySelector('.ofcdlg .aerr')?.textContent || '')`), 'nothing ticked: a message');
    await shot('p2121-c-bill.png');
    await ev(`(() => { const m = document.querySelector('.ofcdlg'); m.querySelector('#bkb-${R1}').checked = true; m.querySelector('#bkb-${R2}').checked = true; m.querySelector('#bkb-mk').value = '10'; m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.ofcdlg')`, 60), 'billed: the dialog closes');
    const q = await call(CA, 'GET', `/api/office/docs/${Q.id}`);
    check((q.items || []).length === 2 && q.items.map(i => i.cost).sort().join() === '100,50', 'two positions, net 100 + gross 50 ' + JSON.stringify((q.items || []).map(i => i.cost)));
    check(await ready(ev, `[...document.querySelectorAll('[data-bk="rc"]')].filter(b => /billed on/.test(b.textContent)).length === 2`, 60), 'the rows say "billed on ..."');
    // the toast undo: one step takes both back
    await ev(`document.querySelector('#toast button:not(.tx)')?.click()`);
    check(await ready(ev, `![...document.querySelectorAll('[data-bk="rc"]')].some(b => /billed on/.test(b.textContent))`, 60), 'Undo: the rows are free again');
    check(((await call(CA, 'GET', `/api/office/docs/${Q.id}`)).items || []).length === 0, 'Undo: the positions are gone');
    // one receipt out of its sheet
    await ev(`document.querySelector('[data-bk="rc"][data-id="${R3}"]').click()`);
    check(await ready(ev, `!!document.querySelector('.bk-sheet [data-m="bill"]')`, 60), 'the receipt sheet has "Bill on to a client"');
    await ev(`document.querySelector('.bk-sheet [data-m="bill"]').click()`);
    check(await ready(ev, `!!document.querySelector('.ofcdlg #bkb-doc') && !document.querySelector('.ofcdlg .bk-pick')`, 60), 'one receipt: no list to tick');
    await ev(`document.querySelector('.ofcdlg [data-m="save"]').click()`);
    check(await ready(ev, `!document.querySelector('.ofcdlg')`, 60), 'billed from the sheet');
    check(((await call(CA, 'GET', `/api/office/docs/${Q.id}`)).items || []).length === 1, 'one position');
    check(await ready(ev, `[...document.querySelectorAll('[data-bk="rc"]')].filter(b => /billed on/.test(b.textContent)).length === 1`, 60), 'the row says "billed on ..."');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide), 'on a phone nothing sticks out to the side');
    await ev(`document.querySelector('[data-bk="bill"]')?.click()`);
    check(await ready(ev, `!!document.querySelector('.ofcdlg')`, 40), 'phone: the dialog opens');
    check(await ev(`(() => { const m = document.querySelector('.ofcdlg'); const W = document.documentElement.clientWidth; return m.getBoundingClientRect().right <= W + 1 && [...m.querySelectorAll('button')].every(b => b.getBoundingClientRect().height >= 36); })()`), 'phone: dialog inside the screen, big buttons');
    await shot('p2121-c-bill-phone.png');
  }, false);

  console.log(`p2121_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
