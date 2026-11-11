// 2.936.0 B (#5448) Polish office: the head of an open document on a phone, own container (start.sh). Invented data only.
// kalmido-suite: fresh
// - #5448 (Firefox, phone 360 x 740): an open quotation has ONE navigation line above its content: no office menu row, no
//   path, no area chip; back (arrow with its name as label), number and status share the line and stand in the upper quarter
//   of the screen (was ~390 of 740 px); "Send" keeps its word; the next steps without a word ("Create invoice" before
//   acceptance, "Change number" of a draft) wait in "…" and do there what their button did; Back leads to the list, which
//   keeps its menu row. A computer's big heading names the document (not "Quotations"), the list keeps "Quotations".
//   A tab row cut by the screen edge fades out (.ofx-r / .ofx-l), no cut word. Template: job/3917 (p2889_b_office_ui.js).
// Screenshots into $P2936B_SHOTS.
// freelancer-matrix: office (frida has no organisation)
// usage: node p2936_b_office_head_ui.js <datadir>
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2936_b_head', check, shots: 'P2936B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Beispiel Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  // a person without an organisation (freelancer-matrix: office)
  check((await call('POST', '/api/users', {username: 'frida', display_name: 'frida', password: 'password123', email: 'frida@example.com', orgs: []})).http < 300, 'user frida');
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, FK);

  await call('PUT', '/api/office/settings', {pack: 'DE', company_fields: {name: 'Studio Beispiel', street: 'Hafenstrasse 12', zip: '20457', city: 'Hamburg', country: 'DE', tax_number: '12/345/67890', iban: 'DE02120300000000202051', bic: 'BYLADEM1001', bank_name: 'Beispielbank'}}, FK);
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktstrasse 5', zip: '50667', city: 'Koeln', country: 'DE'}, FK)).id;
  const quote = async title => { const q = await call('POST', '/api/office/docs', {client_id: CL, project_title: title}, FK); await call('PUT', `/api/office/docs/${q.id}/items`, {items: [{kind: 'service', title: 'Kamera', qty: 2, unit: 'day', rate: 800}]}, FK); return q.id; };
  const Q = await quote('Imagefilm'), Q2 = await quote('Werbespot');
  check((await call('POST', `/api/office/docs/${Q2}/finalize`, {}, FK)).http === 200, 'the second quotation finalised (it has a number)');
  check((await call('POST', `/api/office/docs/${Q2}/status`, {status: 'sent'}, FK)).http === 200, 'the second quotation is sent');
  const NUM = (await call('GET', `/api/office/docs/${Q2}`, null, FK)).number;
  check(!!NUM, 'the finalised quotation has a number ' + NUM);
  const QNUM = (await call('GET', `/api/office/docs/${Q}`, null, FK)).number || 'Draft';
  // a finalised invoice: its kind word and its number on a phone
  const INV = (await call('POST', '/api/office/docs', {kind: 'invoice', client_id: CL, service_from: '2026-10-01', items: [{title: 'Schnitt', qty: 1, rate: 100}]}, FK)).id;
  check(!!INV && (await call('POST', `/api/office/docs/${INV}/finalize`, {}, FK)).http === 200, 'an invoice finalised');
  const INUM = (await call('GET', `/api/office/docs/${INV}`, null, FK)).number;

  const signIn = (ev, user) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  const R = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const b = e.getBoundingClientRect(); return b.width || b.height ? {top: b.top, bottom: b.bottom, left: b.left, right: b.right, h: b.height} : null; })()`;
  const shown = sel => `[...document.querySelectorAll(${JSON.stringify(sel)})].some(e => { const b = e.getBoundingClientRect(); return b.width > 0 && b.height > 0 && getComputedStyle(e).visibility !== 'hidden'; })`;
  const menuItems = `(() => { const x = [...document.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim()); return x.length ? x : null; })()`;
  const tapItem = re => `(() => { const b = [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => ${re}.test(b.textContent)); if (!b) return 0; b.click(); return 1; })()`;

  // ================= #5448: a phone, 360 x 740
  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev, 'frida') === 200, 'phone: frida signed in');
    await nav(B + '#office/offers/' + Q2);
    check(await until(`/${NUM}/.test(document.querySelector('.ofdhead .ofdnum')?.textContent || '') && !!document.querySelector('.ofdsec')`, {timeout: 20000}), 'phone: the sent quotation opens');
    await until(`!document.querySelector('#view .ofmcrumb')`, {timeout: 3000});
    check(await ev(`!${shown('#view .ofpb')} && !${shown('#view .ofmcrumb')} && !${shown('#view .ofchead .ofcws')} && !${shown('#view .ofchead .ofcorg')}`), '#5448 phone: no office menu row, no path, no area line above the document');
    const back = await ev(R('.ofdhead .ofdback')), num = await ev(R('.ofdhead .ofdnum b')), st = await ev(R('.ofdhead .ofdstat'));
    check(back && num && st, '#5448 phone: back, number and status shown ' + JSON.stringify({back, num, st}));
    const mid = b => (b.top + b.bottom) / 2;
    check(back && num && st && Math.abs(mid(back) - mid(num)) < 12 && Math.abs(mid(back) - mid(st)) < 12, '#5448 phone: back, number and status in ONE line ' + JSON.stringify({back, num, st}));
    check(await ev(`(() => { const b = document.querySelector('.ofdhead .ofdback'); return /Back to Quotations/.test(b.getAttribute('aria-label') || '') && !b.querySelector('span')?.getBoundingClientRect().width; })()`), '#5448 phone: the back button is the arrow with its name as label');
    check(await ev(`(() => { const b = document.querySelector('.ofdhead .ofdnum b'); return b.scrollWidth <= b.clientWidth + 1; })()`), '#5448 phone: the number is shown in full: ' + await ev(`document.querySelector('.ofdhead .ofdnum b')?.textContent`));
    check(await ev(`/Sent/.test(document.querySelector('.ofdhead .ofdstat')?.selectedOptions[0]?.textContent || '')`), '#5448 phone: the status reads "Sent"');
    check(num && st && num.bottom < 740 / 4 && st.bottom < 740 / 4, '#5448 phone: number and status are seen in the upper quarter of the screen ' + JSON.stringify({num, st}));
    check(await ev(`(() => { const b = document.querySelector('.ofdhead [data-ofd="send"]'); if (!b) return 0; const r = b.getBoundingClientRect(); return r.width > 0 && r.right <= innerWidth && /Send/.test(b.innerText); })()`), '#5448 phone: "Send" keeps its button with its word');
    check(await ev(`!${shown('.ofdhead [data-ofd="to-invoice"]')} && !${shown('.ofdhead [data-st="declined"]')} && ${shown('.ofdhead [data-st="accepted"]')}`), '#5448 phone: "Accepted" is the main step, "Rejected" and "Create invoice" are not in the head');
    check(await ev('document.documentElement.scrollWidth <= innerWidth'), '#5448 phone: nothing wider than the screen');
    // the head (one navigation line + the actions with their words) ends high; below it the content (the "Finalised" note)
    const hd = await ev(R('.ofdhead'));
    check(hd && hd.top < 90 && hd.bottom < 260, '#5448 phone: the head starts right below the top bar and ends high (the content started at ~390 of 740 px): ' + JSON.stringify(hd));
    await shot('p2936b-handy-angebot.png');
    await ev(`(() => { document.querySelector('.ofdhead [data-ofd="more"]').click(); return 1; })()`);
    const items = await until(menuItems);
    check(items && items.some(t => /Create invoice/.test(t)) && items.some(t => /Rejected/.test(t)), '#5448 phone: "…" offers "Rejected" and "Create invoice": ' + JSON.stringify(items));
    // a tap on it does what the button did: the question about an invoice of a quotation not yet accepted
    await ev(tapItem('/Create invoice/'));
    check(await until(`/not been accepted/.test(document.querySelector('.cdlg')?.textContent || '')`), '#5448 phone: "Create invoice" from "…" asks like the button: ' + await ev(`document.querySelector('.cdlg')?.textContent || document.querySelector('.modal')?.textContent || ''`));
    await ev(`(() => { document.querySelector('.cdlg [data-cd="no"]')?.click(); return 1; })()`);
    await until(`!document.querySelector('.cdlg')`, {timeout: 3000});
    // Back leads to the list of quotations, which keeps its menu row
    await ev(`(() => { document.querySelector('.ofdhead .ofdback').click(); return 1; })()`);
    check(await until(`/^#office\\/offers/.test(location.hash) && !document.querySelector('.ofdhead') && !!document.querySelector('#view .ofdrow[data-id="${Q2}"]')`), '#5448 phone: Back leads to the list ' + await ev('location.hash'));
    check(await ev(shown('#view .ofpb')), '#5448 phone: the list keeps the office menu row');
    // a draft: its number whole, "Change number" in "…" opens the number field
    await nav(B + '#office/offers/' + Q);
    check(await until(`!!document.querySelector('.ofdsec') && (document.querySelector('.ofdhead .ofdnum')?.textContent || '').includes(${JSON.stringify(QNUM)})`, {timeout: 20000}), 'phone: the draft opens ' + QNUM);
    const top2 = await ev(`document.querySelector('.ofdsec').getBoundingClientRect().top`);
    check(top2 < 330, '#5448 phone: a draft\'s content starts high (was ~390 of 740 px): ' + top2);
    check(await ev(`(() => { const b = document.querySelector('.ofdhead .ofdnum b'); return b.scrollWidth <= b.clientWidth + 1; })()`), '#5448 phone: the draft\'s number is shown in full: ' + await ev(`document.querySelector('.ofdhead .ofdnum b')?.textContent`));
    check(await ev(`!!document.querySelector('.ofdhead .onumpen') && !${shown('.ofdhead .onumpen')}`), '#5448 phone: the pen "Change number" is not in the head');
    await shot('p2936b-handy-entwurf.png');
    await ev(`(() => { document.querySelector('.ofdhead [data-ofd="more"]').click(); return 1; })()`);
    const items2 = await until(menuItems);
    check(items2 && items2.some(t => /Change number/.test(t)), '#5448 phone: "…" offers "Change number": ' + JSON.stringify(items2));
    await ev(tapItem('/Change number/'));
    check(await until(`(() => { const i = document.querySelector('#onum-doc'); if (!i) return false; const b = i.getBoundingClientRect(); return b.width > 0 && b.right <= innerWidth; })()`), '#5448 phone: "Change number" from "…" opens the number field inside the screen');
    await ev(`(() => { document.querySelector('[data-onum="doc-x"]')?.click(); return 1; })()`);
    // the invoice: the kind small above, the number in full, the status beside it, "Record payment" with its word
    await nav(B + '#office/offers/' + INV);
    check(await until(`!!document.querySelector('.ofdsec') && (document.querySelector('.ofdhead .ofdnum b')?.textContent || '').includes(${JSON.stringify(INUM || '?')})`, {timeout: 20000}), 'phone: the invoice opens ' + INUM);
    const iv = await ev(`(() => { const b = document.querySelector('.ofdhead .ofdnum b'), k = b.querySelector('.ofdkn'), s = document.querySelector('.ofdhead .ofdstat'); if (!k || !s) return null; const bb = b.getBoundingClientRect(), sb = s.getBoundingClientRect();
      return {full: b.scrollWidth <= b.clientWidth + 1, kind: k.textContent.trim(), line: sb.top < bb.bottom && sb.bottom > bb.top, txt: b.textContent}; })()`);
    check(iv && iv.full && /Invoice/.test(iv.kind) && iv.line, '#5448 phone: the invoice head: kind word, full number, status on the line ' + JSON.stringify(iv));
    check(await ev(`/Record payment/.test(document.querySelector('.ofdhead [data-ofd="pay"]')?.innerText || '')`), '#5448 phone: "Record payment" keeps its word');
    await shot('p2936b-handy-rechnung.png');
    // the kind tabs of the invoices: wider than the phone, they fade at the cut edge, after scrolling at the other one
    await nav(B + '#office/invoices');
    check(await until(`!!document.querySelector('.office .ofdkinds button')`, {timeout: 20000}), 'phone: the invoices with their kind tabs');
    const k = await until(`(() => { const r = document.querySelector('.office .ofdkinds'); return r && r.scrollWidth > r.clientWidth + 1 ? {r: r.classList.contains('ofx-r'), l: r.classList.contains('ofx-l'), m: getComputedStyle(r).maskImage} : null; })()`, {timeout: 5000});
    if (!k) console.log('p2936_b_head: the kind tabs fit the phone here, no fade to check');
    else {
      check(k.r && !k.l && k.m && k.m !== 'none', '#5448 phone: the cut kind tabs fade out on the right ' + JSON.stringify(k));
      await ev(`(() => { const r = document.querySelector('.office .ofdkinds'); r.scrollLeft = r.scrollWidth; return 1; })()`);
      check(await until(`(() => { const r = document.querySelector('.office .ofdkinds'); return r.classList.contains('ofx-l') && !r.classList.contains('ofx-r'); })()`), '#5448 phone: scrolled to the end: the fade moves to the left');
    }
    await shot('p2936b-handy-rechnungen-reiter.png');
  }, true);

  // ================= #5448: a computer: the big heading names the open document, back keeps its word
  await firefox(async ({cmd, ev, ctx, nav, until}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await signIn(ev, 'frida') === 200, 'desktop: frida signed in');
    await nav(B + '#office/offers/' + Q2);
    check(await until(`(document.querySelector('#top h1 .ht')?.textContent || '').includes(${JSON.stringify(NUM)})`, {timeout: 20000}), '#5448 desktop: the heading names the document: ' + await ev(`document.querySelector('#top h1')?.textContent`));
    check(await ev(`!!document.querySelector('.ofdhead .ofdback') && /Quotations/.test(document.querySelector('.ofdhead .ofdback').innerText)`), '#5448 desktop: the back button keeps its word');
    check(await ev(`${shown('.ofdhead [data-ofd="to-invoice"]')} && ${shown('.ofdhead [data-st="declined"]')}`), '#5448 desktop: the next steps stay buttons in the head');
    await ev(`(() => { document.querySelector('.ofdhead .ofdback').click(); return 1; })()`);
    check(await until(`/^#office\\/offers/.test(location.hash) && !document.querySelector('.ofdhead') && (document.querySelector('#top h1 .ht')?.textContent || '').trim() === 'Quotations'`, {timeout: 20000}), '#5448 desktop: back in the list, the heading reads "Quotations" again: ' + await ev(`document.querySelector('#top h1')?.textContent`));
  });

  console.log(`p2936_b_office_head_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
