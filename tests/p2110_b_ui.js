// 2.110.0 UI tests, part B (#2055, all receipts + export for the tax adviser), own container (start.sh, mode workspaces),
// Firefox (desktop + phone width). Invented companies, people and figures only.
// - the bookkeeping has "All receipts" below the receipts of this month -> #office/books/receipts with the filter bar
// - the receipts of the year (all months) with their sums; a category filter makes the list shorter and the sum follows
// - the export links (CSV, ZIP for the tax adviser) carry the filters in their address
// - the filters stay when one comes back (sessionStorage); a tap on a row opens the receipt sheet
// - on a phone the filters are folded away and nothing sticks out to the side; "Bookkeeping" leads back
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2110_b_ui', check, shots: 'P2110B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2110B_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const today = TC.today();

function tinyPdf(text) {  // a one-page PDF with a text layer
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
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const year = today.slice(0, 4), ws = `org:${org.id}`;
  // three months of this year (January, February, today), one of last year (not in "this year")
  await receipt(CA, ws, 'software.pdf', '119.00', `${year}-01-15`, 'Software', '19');
  await receipt(CA, ws, 'buch.pdf', '107.00', `${year}-02-10`, 'Books', '7');
  await receipt(CA, ws, 'cloud.pdf', '23.80', today, 'Software', '19');
  await receipt(CA, ws, 'alt.pdf', '50.00', `${+year - 1}-06-01`, 'Material', '19');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  const rows = `document.querySelectorAll('.rcl-list [data-rcl="rc"]').length`;
  const sum = `(document.querySelector('.rcl-sum b')?.textContent || '')`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/books');
    check(await ready(ev, `!!document.querySelector('.bk-all a[href="#office/books/receipts"]')`, 80), '"All receipts" below the receipts of this month');
    await ev(`(() => { document.querySelector('.bk-all a').click(); return 1; })()`);
    check(await ready(ev, `${rows} === 3`, 80), 'all receipts of this year (three months, not last year) ' + await ev(`location.hash + ' ' + ${rows} + ' ' + (document.querySelector('.ofcbody')?.textContent || '').slice(0, 300)`).catch(e => String(e)));
    check(await ev(`/249\\.80/.test(${sum}) && /3 receipts/.test(document.querySelector('.rcl-sum').textContent)`), 'the sum of the year ' + await ev(sum));
    check(await ev(`!!document.querySelector('.rcl-filters[open] #rcl-per') && document.querySelector('#rcl-per').value === 'year'`), 'the filter bar (open on a desktop), period this year');
    await shot('p2110-b-list.png');
    // the category filter
    await ev(`(() => { const s = document.querySelector('#rcl-cat'); s.value = 'Software'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `${rows} === 2 && /142\\.80/.test(${sum})`), 'category Software: the list is shorter, the sum follows ' + await ev(sum));
    check(await ev(`(() => { const c = document.querySelector('#rcl-csv').getAttribute('href'), z = document.querySelector('#rcl-zip').getAttribute('href');
      return c.startsWith('/api/office/books/receipts.csv?') && z.startsWith('/api/office/books/receipts.zip?') && /category=Software/.test(c) && /category=Software/.test(z) && /from=${year}-01-01/.test(z); })()`),
      'the export links carry the filters');
    check(await ev(`fetch(document.querySelector('#rcl-csv').href).then(r => r.text()).then(t => t.split('\\r\\n').filter(Boolean).length === 3)`), 'the CSV has exactly the filtered rows');
    // the receipt sheet from a row
    await ev(`(() => { document.querySelector('.rcl-list [data-rcl="rc"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.bk-sheet #bk-cat')`, 60), 'a tap on a row opens the receipt sheet');
    await ev(`(() => { document.querySelector('.bk-sheet [data-m="close"]').click(); return 1; })()`);
    // the filters stay when one comes back
    await nav(B + '#office/books');
    await ready(ev, `!!document.querySelector('.bk-all a')`, 60);
    await nav(B + '#office/books/receipts');
    check(await ready(ev, `${rows} === 2 && document.querySelector('#rcl-cat').value === 'Software'`, 60), 'the filters stay when coming back');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await ev(`(() => { RCL.open = null; return 1; })()`);  // a fresh visit on a phone (a details the person opened stays open on a redraw)
    await nav(B + '#office/books');
    await ready(ev, `!!document.querySelector('.bk-all a')`, 60);
    await nav(B + '#office/books/receipts');
    await ready(ev, `${rows} === 2`, 60);
    await sleep(300);
    check(await ev(`!document.querySelector('.rcl-filters').open`), 'on a phone the filters are folded away');
    check(await ev(noSide), 'on a phone nothing sticks out to the side');
    check(await ev(`document.querySelector('#rcl-zip').getBoundingClientRect().height >= 44 && document.querySelector('.rcl-filters summary').getBoundingClientRect().height >= 44`), 'on a phone the targets are large');
    await ev(`(() => { document.querySelector('.rcl-filters summary').click(); return 1; })()`);
    await sleep(300);
    check(await ev(`document.querySelector('.rcl-filters').open`) && await ev(noSide), 'opened filters fit on a phone');
    await shot('p2110-b-phone.png');
    await ev(`(() => { document.querySelector('.rcl-top a[href="#office/books"]').click(); return 1; })()`);
    check(await ready(ev, `location.hash === '#office/books' && !!document.querySelector('.bk-all')`, 60), '"Bookkeeping" leads back');
  }, false);

  console.log(`p2110_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
