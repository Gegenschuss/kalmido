// 2.743.0 B (#4930) UI test, own container (start.sh, isolated test database), Firefox with a mouse. Invented data only.
// kalmido-suite:
// One building block for list beside detail (.lsd2, static/css/start-lsd-4553.css) instead of three ways (.ctcols with its
// own columns, .lsd2 for documents, the receipts page padded by 60 %):
// - 1920 (#view.lsdw): contacts, clients, an invoice and a receipt all stand in a .lsd2 with the list .lsdl on the left
//   (about 40 %) and the detail on the right; the receipt's dialog sits over the right column of its pair and the page is
//   not padded any more
// - 1440: contacts keep the narrow list (--w-leiste, 15rem) beside the card through the same block; the receipts page is one
//   column, the dialog in the middle
// - a phone (390): contacts one column, the receipts page one column (as before)
// freelancer-matrix: Liste neben Detail (alice has no organisation; the block does not depend on the workspace)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2743_b_lsd_ui', check, shots: 'P2743B_SHOTS'});
const FEAT = 'office,contacts,clients,docs';
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['office', 'contacts', 'docs']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'alice: no organisation (person on her own)');

  const bk = await call('POST', '/api/books', {name: 'Customers'});
  for (const [g, f] of [['Petra', 'Buyer'], ['Jonas', 'Light'], ['Mia', 'Sound']]) await call('POST', '/api/contacts', {book_id: bk.id, given: g, family: f, org: 'Example Film GmbH'});
  const CL = [];
  for (const n of ['Acme Example GmbH', 'Beta Example']) CL.push((await call('POST', '/api/clients', {name: n})).id);
  check(CL.every(Boolean), 'setup: two clients');
  await call('GET', '/api/office/settings');
  const IV = [];
  for (const [i, t] of ['Image film', 'Trailer cut'].entries()) IV.push((await call('POST', '/api/office/docs', {kind: 'invoice', client_id: CL[i], project_title: t, date: '2026-10-0' + (i + 1), items: [{title: 'Cut', qty: 1, rate: 500}]})).id);
  check(IV.every(Boolean), 'setup: two invoices ' + IV.join());
  const RC = [];
  for (const [n, a] of [['cloud.txt', '23.80'], ['books.txt', '107.00']]) {
    const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([`Receipt example ${n} ${a} EUR`], {type: 'text/plain'}), n);
    const j = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CA}, body: fd})).json().catch(() => ({}));
    const id = j.ids?.[0]; RC.push(id);
    await call('PATCH', `/api/docs/${id}`, {amount: a, date: '2026-10-15'});
    await call('PUT', `/api/docs/${id}/receipt`, {category: 'Software', vat_pct: '19', keep: true});
  }
  check(RC.every(Boolean), 'setup: two receipts ' + RC.join());

  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    const R = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e || !e.getClientRects().length) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), r: Math.round(b.right), t: Math.round(b.top), w: Math.round(b.width)}; })()`;
    const REM = `parseFloat(getComputedStyle(document.documentElement).fontSize)`;
    // the pair of a page: the block, its list column and the share of the list
    const PAIR = sel => `(() => { const p = document.querySelector(${JSON.stringify(sel)}); if (!p || !p.getClientRects().length) return null; const l = p.querySelector(':scope > .lsdl'), cs = getComputedStyle(p); if (!l) return null;
      const pb = p.getBoundingClientRect(), lb = l.getBoundingClientRect(); return {disp: cs.display, cols: cs.gridTemplateColumns.split(' ').length, share: Math.round(lb.width / pb.width * 100) / 100, lw: Math.round(lb.width), lr: Math.round(lb.right), pr: Math.round(pb.right), rem: ${REM}}; })()`;

    // ================= 1920: all four areas in .lsd2
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1920, height: 1080}});
    await nav(B + '?w=1920#contacts');
    check(await until(`!!S.booted && !!document.querySelector('#view .ctrow[data-ctopen]') && document.querySelector('#view').classList.contains('lsdw')`), '1920: the contacts show, #view wide enough for the pair');
    await ev(`(() => { document.querySelector('#view .ctrow[data-ctopen]').click(); return 1; })()`);
    { const p = await until(`(() => { const p = ${PAIR('#view .ctview .lsd2')}, c = ${R('#view .lsd2 > .ctcard:not(.ctnone)')}; return p && c ? {...p, cl: c.l} : null; })()`);
      check(p && p.disp === 'grid' && p.cols === 2 && p.share > .33 && p.share < .45 && p.cl > p.lr, '1920: contacts in .lsd2, list about 40 %, the card right of it ' + JSON.stringify(p)); }
    await shot('p2743b-contacts-1920.png');

    await nav(B + '?w=1920#client/' + CL[1]);
    { const p = await until(`(() => { const p = ${PAIR('#view .msclients .lsd2')}, c = ${R('#view .msclients .lsd2 > .ctcard:not(.ctnone)')}; return p && c ? {...p, cl: c.l} : null; })()`);
      check(p && p.cols === 2 && p.share > .33 && p.share < .45 && p.cl > p.lr, '1920: clients in .lsd2, list about 40 %, the card right of it ' + JSON.stringify(p)); }

    await nav(B + '?w=1920#office/invoices/' + IV[0]);
    { const p = await until(`(() => { const p = ${PAIR('#view .lsd2')}; return p && document.querySelector('#view .lsd2 > .lsdr .ofdeditor') && document.querySelectorAll('#view .lsdl .ofdrow').length === 2 ? p : null; })()`);
      check(p && p.cols === 2 && p.share > .33 && p.share < .45, '1920: an invoice in .lsd2, its list about 40 % ' + JSON.stringify(p)); }
    await shot('p2743b-invoice-1920.png');

    await nav(B + '?w=1920#office/receipts');
    check(await until(`document.querySelectorAll('#view .lsd2.rcl-pair > .lsdl [data-rcl="rc"]').length === 2`), '1920: the receipts list stands in the block .lsd2');
    check(await ev(`getComputedStyle(document.querySelector('#view .lsd2.rcl-pair')).display === 'block'`), '1920: no receipt open: the receipts page is one column');
    await ev(`(() => { document.querySelector('#view [data-rcl="rc"][data-id="${RC[0]}"]').click(); return 1; })()`);
    { const r = await until(`(() => { const p = ${PAIR('#view .lsd2.rcl-pair')}, c = ${R('.modal.bk-sheet.lsddock > .card')}; return p && c && p.cols === 2 && document.querySelector('.modal.bk-sheet #bk-cat') ? {...p, c} : null; })()`);
      check(r && r.share > .33 && r.share < .45 && r.c.l >= r.lr && r.c.l - r.lr <= 1.1 * r.rem && Math.abs(r.c.r - r.pr) <= 2, '1920: the receipt dialog over the right column of the pair, the list about 40 % ' + JSON.stringify(r));
      check(await ev(`getComputedStyle(document.querySelector('#view .ofbody')).paddingRight === '0px'`), '1920: the page is not padded any more (the old dock) ' + await ev(`getComputedStyle(document.querySelector('#view .ofbody')).paddingRight`)); }
    await shot('p2743b-receipt-1920.png');
    await ev(`(() => { document.querySelector('.modal.bk-sheet [data-m="close"]').click(); return 1; })()`);
    check(await until(`!document.querySelector('.modal.bk-sheet') && getComputedStyle(document.querySelector('#view .lsd2.rcl-pair')).display === 'block'`), '1920: closed: one column again');

    // ================= 1440: the narrow list through the same block, receipts in the middle
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await nav(B + '?w=1440#contacts');
    check(await until(`!!S.booted && !!document.querySelector('#view .ctrow[data-ctopen]') && !document.querySelector('#view').classList.contains('lsdw')`), '1440: the contacts show, no wide pair');
    { const p = await until(PAIR('#view .ctview .lsd2'));
      check(p && p.cols === 2 && p.lw > 15 * p.rem + 2 && p.lw <= 26 * p.rem + 2, '1440: the contact list is the left column of .lsd2, wider than --w-leiste (at most 26rem) ' + JSON.stringify(p)); }  // 2.1168.0 (#6117): was the narrow 15rem
    await nav(B + '?w=1440#office/receipts');
    check(await until(`document.querySelectorAll('#view [data-rcl="rc"]').length === 2`), '1440: the receipts show');
    await ev(`(() => { document.querySelector('#view [data-rcl="rc"][data-id="${RC[1]}"]').click(); return 1; })()`);
    check(await until(`!!document.querySelector('.modal.bk-sheet #bk-cat')`), '1440: the receipt opens');
    check(await ev(`!document.querySelector('.modal.bk-sheet.lsddock') && getComputedStyle(document.querySelector('#view .lsd2.rcl-pair')).display === 'block'`), '1440: the dialog in the middle, the page one column as before');
    await ev(`(() => { document.querySelector('.modal.bk-sheet [data-m="close"]').click(); return 1; })()`);
    await until(`!document.querySelector('.modal.bk-sheet')`);

    // ================= a phone: one column as before
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '?w=390#contacts');
    check(await until(`!!S.booted && !!document.querySelector('#view .ctrow[data-ctopen]')`), '390: the contacts show');
    { const p = await ev(PAIR('#view .ctview .lsd2'));
      check(p && p.cols === 1 && !(await ev(`!!document.querySelector('#view .ctcard')`)), '390: contacts one column, no card beside the list ' + JSON.stringify(p)); }
    await nav(B + '?w=390#office/receipts');
    check(await until(`document.querySelectorAll('#view [data-rcl="rc"]').length === 2`), '390: the receipts show');
    check(await ev(`!document.querySelector('#view').classList.contains('lsdw') && getComputedStyle(document.querySelector('#view .lsd2.rcl-pair')).display === 'block'`), '390: the receipts page one column');
    await shot('p2743b-contacts-390.png');
  }, false);

  console.log(`p2743_b_lsd_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
