// kalmido-suite: fresh
// 2.414.0 UI tests, part A (#3502, office: the booking archive of past DATEV years), own container, Firefox. Invented
// companies, accounts and figures only (EXTF files and a tiny PDF written here). freelancer-matrix: office
// - a person without organisation (personal office): Bookkeeping -> "Booking archive" (empty: the explanation and the button)
// - the dialog reads a ZIP (booking batch of one year with a receipt link, account labels, document.xml + a PDF) and the
//   batch of another year at once: the preview per year (debit = credit), the files, the receipt image linked; then one run
// - the newest year first; the other year: 250 bookings in pages of 200 ("Load more"), the filters account / text / amount,
//   the sums per account (labels, count, debit), an account -> its bookings, one booking with every column of its line and
//   its receipt image (opens as a PDF)
// - the same batch again: "Already in the archive", nothing to take over; undo of the run empties the archive
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2414_a_ui', check, shots: 'P2414A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const Y = +TC.today().slice(0, 4), Y1 = Y - 3, Y2 = Y - 2;
const GUID = '3f2a9c10-5b7d-4e21-9a0c-7d1e2f3a4b5c';

// ---- the DATEV files (EXTF), all invented
const head = (cat, name, ver, y) => { const f = ['"EXTF"', '700', String(cat), `"${name}"`, String(ver), '20260101120000000', '', '"RE"', '""', '""', '1234567', '12345', `${y}0101`, '4']; while (f.length < 31) f.push(''); return f.join(';'); };
const COLS = '"Umsatz (ohne Soll/Haben-Kz)";"Soll/Haben-Kennzeichen";"Konto";"Gegenkonto (ohne BU-Schlüssel)";"Belegdatum";"Belegfeld 1";"Buchungstext";"Beleglink"';
const csv = lines => lines.join('\r\n') + '\r\n';
const rows1 = [];
for (let i = 0; i < 248; i++) rows1.push(`10,00;"S";4930;1200;${String(1 + (i % 28)).padStart(2, '0')}${String(1 + (i % 12)).padStart(2, '0')};"R${i}";"Buero ${i}";""`);
rows1.push(`119,00;"S";6815;1200;1503;"RE-777";"Druckerpapier Beispiel";"BEDI ""${GUID}"""`);
rows1.push('500,00;"H";8400;1200;2006;"AR-1";"Honorar Beispiel";""');
const B1 = csv([head(21, 'Buchungsstapel', 13, Y1), COLS, ...rows1]);
const B2 = csv([head(21, 'Buchungsstapel', 13, Y2), COLS, '20,00;"S";4930;1200;0201;"R1";"Porto";""', '30,00;"S";4930;1200;0302;"R2";"Porto";""', '900,00;"H";8400;1200;0403;"AR-2";"Honorar";""']);
const L1 = csv([head(20, 'Kontenbeschriftungen', 2, Y1), '"Konto";"Kontenbeschriftung"', '1200;"Bank Beispiel"', '4930;"Buerobedarf"', '6815;"Zeitschriften Beispiel"']);
const XML = `<?xml version="1.0" encoding="utf-8"?><archive xmlns="http://xml.datev.de/bedi/tps/document/v06.0" version="6.0"><content><document guid="${GUID}"><extension datafile="beleg-777.pdf" name="beleg-777.pdf"/></document></content></archive>`;
const PDF = '%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj 2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF\n';
// a ZIP without compression (stored entries)
const CRC = Array.from({length: 256}, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
const crc32 = b => { let c = 0xFFFFFFFF; for (const x of b) c = CRC[(c ^ x) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
function zip(entries) {
  const loc = [], cen = []; let off = 0;
  for (const [name, text] of entries) {
    const d = Buffer.from(text, 'utf8'), n = Buffer.from(name), crc = crc32(d);
    const lh = Buffer.alloc(30); lh.writeUInt32LE(0x04034b50, 0); lh.writeUInt16LE(20, 4); lh.writeUInt32LE(crc, 14); lh.writeUInt32LE(d.length, 18); lh.writeUInt32LE(d.length, 22); lh.writeUInt16LE(n.length, 26);
    const ch = Buffer.alloc(46); ch.writeUInt32LE(0x02014b50, 0); ch.writeUInt16LE(20, 4); ch.writeUInt16LE(20, 6); ch.writeUInt32LE(crc, 16); ch.writeUInt32LE(d.length, 20); ch.writeUInt32LE(d.length, 24); ch.writeUInt16LE(n.length, 28); ch.writeUInt32LE(off, 42);
    loc.push(lh, n, d); cen.push(ch, n); off += 30 + n.length + d.length;
  }
  const c = Buffer.concat(cen), end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50, 0); end.writeUInt16LE(entries.length, 8); end.writeUInt16LE(entries.length, 10); end.writeUInt32LE(c.length, 12); end.writeUInt32LE(off, 16);
  return Buffer.concat([...loc, c, end]);
}
const ZIP = zip([['EXTF_Buchungsstapel.csv', B1], ['EXTF_Kontenbeschriftungen.csv', L1], ['belege/document.xml', XML], ['belege/beleg-777.pdf', PDF]]);
const b64 = s => Buffer.from(s).toString('base64');

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  // the person without organisation (tests/freelancer_fixture.py does the same in Python)
  const fu = await call(CA, 'POST', '/api/users', {username: 'erin', display_name: 'Erin', password: 'password123', email: 'erin@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CE = await login('erin');
  await call(CE, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(((await call(CE, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'erin is in no organisation');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const give = files => `(() => { const i = document.querySelector('.modal #bka-file'); const dt = new DataTransfer();
    for (const [n, b] of ${JSON.stringify(files)}) dt.items.add(new File([Uint8Array.from(atob(b), c => c.charCodeAt(0))], n));
    i.files = dt.files; i.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`;
  const txt = sel => `(document.querySelector('${sel}')?.textContent || '').replace(/\\s+/g, ' ')`;
  const sum = `${txt('.bka-sum')}`;
  const filter = f => `(() => { const fm = document.querySelector('[data-bka-form]'); for (const i of fm.querySelectorAll('[data-bkaf]')) i.value = ${JSON.stringify(f)}[i.dataset.bkaf] || ''; fm.requestSubmit(); return 1; })()`;
  const arch = cond => `fetch('/api/office/books/archive', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => ${cond})`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});  // a phone first
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'erin');
    // the bookkeeping: the button; the archive empty
    await nav(B + '#office/books');
    check(await ready(ev, `!!document.querySelector('.bk-bar [data-bk-archive]')`, 80), 'the bookkeeping shows "Booking archive"');
    await ev(`(() => { document.querySelector('[data-bk-archive]').click(); return 1; })()`);
    check(await ready(ev, `location.hash === '#office/books/archive' && !!document.querySelector('.bka-empty [data-bka="read"]')`, 80), 'empty: the explanation and "Read DATEV data"');
    check(await ev(`/No tax advice/.test(${txt('.bka-note')})`), 'the note of the server at the end');

    // the dialog: preview of two years
    await ev(`(() => { document.querySelector('[data-bka="read"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #bka-file')`, 40), 'the dialog opens');
    check(await ev(`document.querySelector('.modal [data-m="ok"]').disabled`), 'no file: "Take over" is off');
    check(await ev(`/past years do not flow/.test(${txt('.modal .bka-ro')})`), 'the dialog says: read only, not in the income statement');
    await ev(give([['datev-' + Y1 + '.zip', ZIP.toString('base64')], ['EXTF_Buchungsstapel_' + Y2 + '.csv', b64(B2)]]));
    check(await ready(ev, `document.querySelectorAll('.modal .bka-pyear').length === 2`, 80), 'the preview: two years ' + await ev(txt('.modal #bka-pv')));
    check(await ev(`[...document.querySelectorAll('.modal .bka-pyear')].every(x => x.querySelector('.bka-bal') && /Debit = Credit/.test(x.textContent))`), 'both years: debit = credit');
    check(await ev(`/250 bookings/.test(document.querySelector('.modal .bka-pyear[data-year="${Y1}"]').textContent)`), 'the preview counts the bookings of the year');
    check(await ev(`!!document.querySelector('.modal .bka-pfile[data-kind="labels"]') && !!document.querySelector('.modal .bka-pfile[data-kind="docs"]')`), 'the preview lists the labels and the document.xml');
    check(await ev(`/1 linked/.test(${txt('.modal .bka-pdocs')})`), 'the receipt image is linked ' + await ev(txt('.modal .bka-pdocs')));
    check(await ev(`!document.querySelector('.modal [data-m="ok"]').disabled`), '"Take over" is on');
    check(await arch('j.years.length === 0'), 'the preview wrote nothing');
    await shot('p2414-a-preview.png');
    await ev(`(() => { document.querySelector('.modal [data-m="ok"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.itc-dlg [data-cd="yes"]')`, 40), 'the import names its target first');
    await ev(`(() => { document.querySelector('.itc-dlg [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, arch(`j.years.length === 2 && j.runs.length === 1`), 80), 'taken over: two years, one run');
    check(await ready(ev, `!document.querySelector('.modal #bka-file') && /253 bookings taken over/.test(document.querySelector('#toast')?.textContent || '')`, 60), 'the dialog closed, the toast names the result');

    // the newest year first, then the other one: pages of 200
    check(await ready(ev, `document.querySelector('#bka-year')?.value === '${Y2}' && /3 bookings/.test(${sum})`, 80), 'the newest year first: 3 bookings ' + await ev(sum));
    check(await ev(`[...document.querySelectorAll('#bka-year option')].map(o => o.value).join() === '${Y2},${Y1}'`), 'only years with data, newest first');
    await ev(`(() => { const s = document.querySelector('#bka-year'); s.value = '${Y1}'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `/250 bookings/.test(${sum}) && document.querySelectorAll('.bka-list li').length === 200`, 80), 'the other year: 250 bookings, the first 200 in the page ' + await ev(sum));
    check(await ev(`/Debit 2,599.00 · Credit 500.00/.test(${sum}.replace(/[€\\u00a0]/g, ''))`), 'the head: debit and credit of the matches ' + await ev(sum));
    check(await ev(`/Bank Beispiel/.test(${txt('.bka-list')}) && /Buerobedarf/.test(${txt('.bka-list')})`), 'the rows show the account labels');
    await shot('p2414-a-bookings.png');
    await ev(`(() => { document.querySelector('[data-bka="more"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.bka-list li').length === 250 && !document.querySelector('[data-bka="more"]')`, 80), '"Load more": all 250, the button gone');

    // filters
    await ev(filter({account: '6815'}));
    check(await ready(ev, `/^ ?1 booking /.test(${sum}) && /Druckerpapier Beispiel/.test(${txt('.bka-list')})`, 60), 'filter account: 1 booking ' + await ev(sum));
    check(await ev(`!!document.querySelector('.bka-list .bka-doc')`), 'the row with a receipt image shows the clip');
    await ev(filter({q: 'honorar'}));
    check(await ready(ev, `/^ ?1 booking /.test(${sum}) && /8400/.test(${txt('.bka-list')})`, 60), 'filter text: 1 booking ' + await ev(sum));
    await ev(filter({min: '100', max: '200'}));
    check(await ready(ev, `/^ ?1 booking /.test(${sum}) && /RE-777/.test(${txt('.bka-list')})`, 60), 'filter amount: 1 booking ' + await ev(sum));

    // one booking: every column and the receipt image
    await ev(`(() => { document.querySelector('.bka-list [data-bka="row"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.bka-dlg .bka-rawt')`, 40), 'the booking opens');
    check(await ev(`(() => { const t = [...document.querySelectorAll('.bka-dlg .bka-rawt th')].map(x => x.textContent); return t.includes('Buchungstext') && t.includes('Belegfeld 1') && t.includes('Beleglink'); })()`),
      'the dialog shows the raw columns ' + await ev(txt('.bka-dlg .bka-rawt')));
    check(await ev(`!document.querySelector('.bka-dlg input, .bka-dlg textarea')`), 'nothing to edit');
    const doc = await ev(`(() => { const a = document.querySelector('.bka-dlg a[data-bka-doc]'); return a ? fetch(a.href).then(r => r.status + ' ' + r.headers.get('content-type') + ' ' + a.target) : 'none'; })()`);
    check(/^200 application\/pdf.* _blank$/.test(doc), '"Open receipt": the PDF in a new tab ' + doc);
    await ev(`(() => { document.querySelector('.bka-dlg [data-m="close"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.bka-dlg')`, 20), 'the booking closes');

    // the sums per account
    await ev(`(() => { document.querySelector('[data-bka="clear"]').click(); return 1; })()`);
    check(await ready(ev, `/250 bookings/.test(${sum})`, 60), 'filters reset');
    await ev(`(() => { document.querySelector('[data-bka="view"][data-v="sum"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.bka-sums tr[data-acct="4930"]')`, 60), 'the sums per account');
    const s4930 = await ev(`${txt('.bka-sums tr[data-acct="4930"]')}.replace(/[€\\u00a0]/g, '')`);
    check(/Buerobedarf/.test(s4930) && /248/.test(s4930) && /2,480\.00/.test(s4930), 'account 4930: label, 248 bookings, debit 2,480.00 ' + s4930);
    const s1200 = await ev(`${txt('.bka-sums tr[data-acct="1200"]')}.replace(/[€\\u00a0]/g, '')`);
    check(/250/.test(s1200) && /500\.00/.test(s1200) && /2,099\.00 H/.test(s1200), 'the counter account 1200 counts too: 250, balance 2,099.00 H ' + s1200);
    await ev(`(() => { document.querySelector('.bka-sums tr[data-acct="6815"]').click(); return 1; })()`);
    check(await ready(ev, `/^ ?1 booking /.test(${sum}) && /Account 6815, either side/.test(${txt('.bka-anyl')})`, 60), 'an account -> its bookings ' + await ev(sum));

    // the same batch again: recognised, nothing to take over
    await ev(`(() => { document.querySelector('[data-bka="read"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #bka-file')`, 40), 'the dialog opens again');
    await ev(give([['EXTF_Buchungsstapel_' + Y2 + '.csv', b64(B2)]]));
    check(await ready(ev, `!!document.querySelector('.modal .bka-pfile[data-kind="duplicate"] .bka-dup')`, 60), 'the same batch: "Already in the archive" ' + await ev(txt('.modal #bka-pv')));
    check(await ev(`document.querySelector('.modal [data-m="ok"]').disabled`), 'nothing to take over: "Take over" stays off');
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);

    // undo of the run
    check(await ready(ev, `!document.querySelector('.modal #bka-file') && !!document.querySelector('.bka-runs [data-bka="undo"]')`, 40), 'the run with its undo');
    check(await ev(`document.querySelectorAll('.bka-runs .bka-files a').length >= 3 && /EXTF_Buchungsstapel.csv/.test(${txt('.bka-runs .bka-files')})`), 'the run lists the original files as downloads ' + await ev(txt('.bka-runs .bka-files')));
    await ev(`(() => { document.querySelector('.bka-runs [data-bka="undo"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('[data-cd="yes"]')`, 40), 'undo asks first');
    await ev(`(() => { document.querySelector('[data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, arch('j.years.length === 0 && !!j.runs[0].undone_at'), 60), 'undo removes the years');
    check(await ready(ev, `!!document.querySelector('.bka-empty') && /undone/.test(${txt('.bka-runs')})`, 60), 'the page: empty again, the run marked undone');
  }, false);

  console.log(`p2414_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
