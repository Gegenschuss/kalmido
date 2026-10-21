// 2.148.0 UI tests, part B (#2470, office: the DATEV ZIP with the receipt images), own container (start.sh), Firefox at
// phone width. A person without organisation (personal office, its own admin). freelancer-matrix: office
// Invented figures only (the receipt is a PDF written here).
// - the DATEV export dialog has "With receipt images" (on) and "Only locked months" (off); the button says "Check"
// - the first press shows the check in the dialog (a receipt without amount = no booking) and the button turns into "Download"
// - switching the receipt images off makes it the plain batch download again
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2148_b_ui', check, shots: 'P2148B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2148B_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const TODAY = TC.today();
// a day of the month before (the dialog's default period)
const PREV_DAY = (() => { const y = +TODAY.slice(0, 4), m = +TODAY.slice(5, 7); return m === 1 ? `${y - 1}-12-10` : `${y}-${String(m - 1).padStart(2, '0')}-10`; })();
// a one-page PDF with a text layer, hand-written (as tests/p21141_b_ui.js)
const tinyPdf = text => {
  const stream = `BT /F1 12 Tf 40 700 Td (${text}) Tj ET`;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  return out + `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const fu = await call(CA, 'POST', '/api/users', {username: 'erin', display_name: 'Erin', password: 'password123', email: 'erin@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CE = await login('erin');
  await call(CE, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CE, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'erin is in no organisation');
  const st = await call(CE, 'PUT', '/api/office/settings', {company: {name: 'Erin Film'}, datev_extf: {advisor_no: '1234567', client_no: '12345'}});
  check(st.http === 200, 'DATEV numbers ' + st.http);
  // a receipt of the month before without an amount: the check names it
  const info = await call(CE, 'GET', '/api/office/books');
  const fd = new FormData(); fd.append('files', new Blob([tinyPdf('Beleg ohne Betrag')], {type: 'application/pdf'}), 'ohne-betrag.pdf'); fd.append('ws', info.upload_ws || 'private');
  const up = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CE}, body: fd})).json().catch(() => ({}));
  const nid = (up.ids || [])[0];
  check(!!nid, 'the receipt is uploaded ' + JSON.stringify(up).slice(0, 200));
  const p1 = await call(CE, 'PATCH', `/api/docs/${nid}`, {date: PREV_DAY});
  const p2 = await call(CE, 'PUT', `/api/docs/${nid}/receipt`, {category: 'Software', vat_pct: '19', keep: true});
  check(p1.http === 200 && p2.http === 200, `the receipt dated ${PREV_DAY} ${p1.http} ${p2.http}`);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const clk = sel => `(() => { const x = document.querySelector('${sel}'); if (!x) return 0; x.click(); return 1; })()`;
  const okText = `(document.querySelector('.modal [data-m="ok"]')?.textContent || '').trim()`;
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.modal, .modal *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});  // a phone
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'erin');
    await nav(B + '#office/offers');
    await ready(ev, `!!document.querySelector('[data-ofd="kind"][data-kind="invoice"]')`, 80);
    await ev(clk('[data-ofd="kind"][data-kind="invoice"]'));
    check(await ready(ev, `!!document.querySelector('[data-dx="extf"]')`, 80), 'the DATEV export button');
    await ev(clk('[data-dx="extf"]'));
    check(await ready(ev, `!!document.querySelector('.modal #dx-img')`, 40), 'the dialog opens');
    check(await ev(`document.querySelector('.modal #dx-img').checked && !document.querySelector('.modal #dx-locked').checked`),
      'with receipt images on, only locked months off');
    check(await ev(`${okText} === 'Check'`), 'the button says Check ' + await ev(okText));
    await ev(clk('.modal [data-m="ok"]'));
    check(await ready(ev, `/without a booking/.test(document.querySelector('.modal #dx-res')?.textContent || '')`, 40),
      'the first press shows the check: the receipt without amount ' + await ev(`document.querySelector('.modal #dx-res')?.textContent.replace(/\\s+/g, ' ') || ''`));
    check(await ev(`/0 bookings, 0 receipt files/.test(document.querySelector('.modal #dx-res').textContent)`), 'the check counts bookings and files');
    check(await ev(`!!document.querySelector('.modal #dx-img')`), 'the dialog stays open');
    check(await ready(ev, `${okText} === 'Download'`, 20), 'the button turns into Download ' + await ev(okText));
    await ev(`(() => { const d = document.querySelector('.modal details.dxchk'); if (d) d.open = true; return 1; })()`);
    check(await ev(`/ohne-betrag/.test(document.querySelector('.modal .dxchk')?.textContent || '')`), 'the list names the receipt');
    check(await ev(noSide), 'phone: nothing of the dialog sticks out at the side');
    await shot('p2148-b-check.png');
    // without receipt images: the plain batch (the button says Download at once)
    await ev(`(() => { const x = document.querySelector('.modal #dx-img'); x.checked = false; x.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `${okText} === 'Download'`, 20), 'without receipt images: Download');
    await ev(clk('.modal [data-m="close"]'));
  }, false);

  console.log(`p2148_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
