// 2.1168.0 C (#6117, #6118) UI test, own container (start.sh, isolated test database), Firefox. Invented data only.
// kalmido-suite: fresh
// Contacts by the room of the content area and a calm phone head:
// - 1280 (mouse): list beside the card, the list wider than the old 15rem and a long company name not cut; a click opens
//   the card beside it and its name takes the focus; the arrow keys walk the list (down from the search field); Esc closes
//   the card and its row keeps the focus; the page is called Contacts; the office hint stands in the list column, once
// - 820 (mouse) with the side panel: the content area is too narrow for both (#view.lsdnar) - the list alone, a row opens the
//   whole card (wide, no sideways scroll, its way back), Back / Esc return to the list; the hint does not come again
// - 360 (finger): the bar is one row (search, Filter, New, More), group and address book behind Filter with the number of
//   active filters, the first contact high up; the card's head: back, picture, Edit and More in one row, the name below it
//   over the full width, no path line; Arrange blocks... in the card's More; the selection bar shows whole words, what does
//   not fit is in its "..."
// freelancer-matrix: Kontakte (alice has no organisation; contacts do not depend on the workspace)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21168_c_contacts_ui', check, shots: 'P21168C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['contacts']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'contacts'});
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'alice: no organisation (person on her own)');

  const b1 = await call('POST', '/api/books', {name: 'Customers'}), b2 = await call('POST', '/api/books', {name: 'Crew'});
  check(b1.id && b2.id, 'setup: two address books');
  const LONG = 'Stadtwerke Lüneburg Netzbetrieb GmbH';
  const C = {};
  C.sw = (await call('POST', '/api/contacts', {book_id: b1.id, org: LONG, emails: [{value: 'presse-und-oeffentlichkeitsarbeit@stadtwerke-lueneburg-netzbetrieb.example', type: ['work']}], groups: ['Press']})).id;
  C.jana = (await call('POST', '/api/contacts', {book_id: b1.id, given: 'Jana', family: 'Krüger', title: 'Head of corporate communications', org: 'Example Utilities', dept: 'Press and public relations', groups: ['Press']})).id;
  for (const [g, f] of [['Petra', 'Buyer'], ['Jonas', 'Light'], ['Mia', 'Sound'], ['Ole', 'Grip']]) C[g] = (await call('POST', '/api/contacts', {book_id: b2.id, given: g, family: f, org: 'Example Film GmbH'})).id;
  check(Object.values(C).every(Boolean), 'setup: six contacts ' + JSON.stringify(C));

  const R = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e || !e.getClientRects().length) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), r: Math.round(b.right), t: Math.round(b.top), b: Math.round(b.bottom), w: Math.round(b.width)}; })()`;
  const REM = `parseFloat(getComputedStyle(document.documentElement).fontSize)`;
  const key = (k, sel) => `(() => { const t = ${sel ? `document.querySelector(${JSON.stringify(sel)})` : 'document.activeElement'} || document.body; t.dispatchEvent(new KeyboardEvent('keydown', {key: ${JSON.stringify(k)}, bubbles: true, cancelable: true})); return 1; })()`;
  const signIn = `fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`;

  // ================= mouse: 1280 and 820
  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(signIn) === 200, 'ff: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await nav(B + '?w=1280#contacts');
    check(await until(`!!S.booted && document.querySelectorAll('#view .ctrow[data-ctopen]').length === 6`), '1280: the six contacts show');
    check(await until(`!document.querySelector('#view').classList.contains('lsdnar')`), '1280: the content area holds list and card (no lsdnar) ' + await ev(`document.querySelector('#view').clientWidth`));
    { const l = await ev(`(() => { const l = ${R('#view .ctlistw')}; return l ? {...l, rem: ${REM}} : null; })()`);
      check(l && l.w > 15 * l.rem + 2, '1280: the list is wider than the old 15rem ' + JSON.stringify(l)); }
    const nm = `(() => { const b = document.querySelector('#view .ctrow[data-ctopen="${C.sw}"] .ctn b'); return b ? {t: b.textContent, sw: b.scrollWidth, cw: b.clientWidth, sh: b.scrollHeight, ch: b.clientHeight} : null; })()`;
    { const n = await ev(nm); check(n && n.t === LONG && n.sw <= n.cw + 1 && n.sh <= n.ch + 1, '1280: the long company name is not cut (it may take a second line) ' + JSON.stringify(n)); }
    check(await ev(`!!document.querySelector('#view .ctlistw > .ct18') && !document.querySelector('#view .ctview > .ct18')`), '1280: the office hint stands in the list column (first visit)');
    check(/Contacts/.test(await ev(`document.querySelector('#top h1')?.textContent || ''`)) && !/Address book/.test(await ev(`document.querySelector('#top')?.textContent || ''`)), '1280: the page is called Contacts ' + await ev(`document.querySelector('#top h1')?.textContent`));
    await shot('p21168c-1280-list.png');

    // open: beside the list, the name takes the focus
    await ev(`(() => { document.querySelector('#view .ctrow[data-ctopen="${C.jana}"]').click(); return 1; })()`);
    const pr = await until(`(() => { const c = ${R('#view .ctcard:not(.ctnone) #ct-h')}, l = ${R('#view .ctlistw')}; return c && l && document.activeElement?.id === 'ct-h' ? {c, l} : null; })()`);
    check(pr && pr.c.l >= pr.l.r, '1280: the card opens beside the list, its name has the focus ' + JSON.stringify(pr) + ' ' + await ev(`document.activeElement?.id || document.activeElement?.className`));
    check(/Jana Krüger/.test(await ev(`document.querySelector('#view #ct-h')?.textContent || ''`)), '1280: the card shows Jana Krüger');
    await shot('p21168c-1280-card.png');
    // the arrow keys: from the search field into the list, then down and up
    await ev(`(() => { document.querySelector('#ct-q').focus(); return 1; })()`);
    await ev(key('ArrowDown'));
    const rows = await ev(`[...document.querySelectorAll('#view .ctlist .ctrow[data-ctopen]')].map(r => r.dataset.ctopen)`);
    check(await until(`document.activeElement?.dataset?.ctopen === '${rows[0]}'`), '1280: ArrowDown in the search field goes to the first contact');
    await ev(key('ArrowDown'));
    check(await until(`document.activeElement?.dataset?.ctopen === '${rows[1]}'`), '1280: ArrowDown walks to the next contact');
    await ev(key('End'));
    check(await until(`document.activeElement?.dataset?.ctopen === '${rows[rows.length - 1]}'`), '1280: End goes to the last contact');
    await ev(key('ArrowUp'));
    check(await until(`document.activeElement?.dataset?.ctopen === '${rows[rows.length - 2]}'`), '1280: ArrowUp walks back');
    // Esc closes the card, its row keeps the keyboard
    await ev(`(() => { document.querySelector('#view .ctrow[data-ctopen="${C.jana}"]').focus(); return 1; })()`);
    await ev(key('Escape'));
    check(await until(`!!document.querySelector('#view .ctcard.ctnone') && !document.querySelector('#view #ct-h') && !!document.querySelector('#view .ctrow[data-ctopen]')`), '1280: Esc closes the card, the list stays');
    check(await until(`document.activeElement?.dataset?.ctopen === '${C.jana}'`), '1280: the closed contact\'s row has the focus');
    // the selection bar on a computer: every button with its word, no "..."
    await ev(`(() => { bk_start(${C.Petra}); bk_toggle(${C.Mia}); return CT.pick.size; })()`);
    check(await until(`!!document.querySelector('#ct-sbar') && document.querySelector('#ct-sbar .mbdots')?.hidden === true && [...document.querySelectorAll('#ct-sbar .mbb:not(.mbdots)')].every(b => !b.hidden)`), '1280: the selection bar shows all its buttons, no "..."');
    await ev(`(bk_end(), 1)`);

    // ================= 820 with the side panel: one column
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 820, height: 1100}});
    await nav(B + 'static/icon.svg');
    await nav(B + '?w=820#contacts');
    check(await until(`!!S.booted && document.querySelectorAll('#view .ctrow[data-ctopen]').length === 6`), '820: the contacts show');
    const vw = await ev(`(() => ({w: document.querySelector('#view').clientWidth, rem: ${REM}, side: !!document.querySelector('#side')?.getClientRects().length}))()`);
    check(vw.w < 43 * vw.rem, '820: with the side panel the content area is narrower than 43rem ' + JSON.stringify(vw));
    check(await until(`document.querySelector('#view').classList.contains('lsdnar') && !document.querySelector('#view .ctcard')`), '820: lsdnar - the list alone, no squeezed card beside it');
    check(await ev(`!document.querySelector('#view .ct18')`), '820: the office hint came once, not again');
    await ev(`(() => { document.querySelector('#view .ctrow[data-ctopen="${C.sw}"]').click(); return 1; })()`);
    check(await until(`location.hash === '#contacts/${C.sw}' && !!document.querySelector('#view .ctcard #ct-h') && !document.querySelector('#view .ctlistw')`), '820: a row opens the whole card (no list beside it) ' + await ev('location.hash'));
    { const m = await until(`(() => { const c = document.querySelector('#view .ctcard[data-ck]'), v = document.querySelector('#view .ctview'), h = document.querySelector('#view #ct-h'); return c && v && h ? {cw: c.getBoundingClientRect().width, vw: v.getBoundingClientRect().width, sw: c.scrollWidth, cl: c.clientWidth, hw: h.getBoundingClientRect().width, focus: document.activeElement === h, back: !!c.querySelector('[data-ct="back"]')} : null; })()`);
      check(m && m.cw >= .9 * m.vw && m.cw > 400, '820: the card takes the content width ' + JSON.stringify(m));
      check(m && m.sw <= m.cl + 1, '820: the card does not scroll sideways ' + JSON.stringify(m));
      check(m && m.hw >= .6 * m.cw, '820: the name has the width of the card, not a narrow column ' + JSON.stringify(m));
      check(m && m.back && m.focus, '820: the card has its way back and its name has the focus ' + JSON.stringify(m)); }
    await shot('p21168c-820-card.png');
    await ev(`(() => { document.querySelector('#view .ctcard [data-ct="back"]').click(); return 1; })()`);
    check(await until(`location.hash === '#contacts' && !!document.querySelector('#view .ctrow[data-ctopen]') && !document.querySelector('#view .ctcard')`), '820: Back returns to the list ' + await ev('location.hash'));
    await ev(`(() => { document.querySelector('#view .ctrow[data-ctopen="${C.jana}"]').click(); return 1; })()`);
    check(await until(`location.hash === '#contacts/${C.jana}' && !!document.querySelector('#view .ctcard #ct-h')`), '820: another contact opens');
    await ev(`(() => { document.activeElement?.blur?.(); return 1; })()`);
    await ev(key('Escape'));
    check(await until(`location.hash === '#contacts' && !!document.querySelector('#view .ctrow[data-ctopen]') && !document.querySelector('#view .ctcard')`), '820: Esc closes the card back to the list ' + await ev('location.hash'));
    await shot('p21168c-820-list.png');
  }, false);

  // ================= finger: 360
  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(signIn) === 200, 'ff 360: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await nav(B + '?w=360#contacts');
    check(await until(`!!S.booted && document.querySelectorAll('#view .ctrow[data-ctopen]').length === 6`), '360: the contacts show');
    const bar = await ev(`(() => { const t = s => { const e = document.querySelector(s); return e && e.getClientRects().length ? Math.round(e.getBoundingClientRect().top) : null; };
      return {q: t('#ct-q'), filt: t('#view .ctfbtn'), nw: t('#view [data-ct="new"]'), more: t('#view [data-ct="menu"]'), group: t('#ct-group'), book: t('#ct-book'), pick: t('#view [data-ct="pick"]'), first: t('#view .ctrow[data-ctopen]')}; })()`);
    check(bar.q !== null && [bar.filt, bar.nw, bar.more].every(x => x !== null && Math.abs(x - bar.q) <= 8), '360: search, Filter, New and More in one row ' + JSON.stringify(bar));
    check(bar.group == null && bar.book == null && bar.pick == null, '360: group, address book and Select are not in the bar ' + JSON.stringify(bar));
    check(bar.first !== null && bar.first < 260, '360: the first contact is high up (was at 400) ' + JSON.stringify(bar));
    check(await ev(`!!document.querySelector('#view .ctlistw > .ct18') && !document.querySelector('#view .ctview > .ct18')`), '360: the office hint in the list column');
    await shot('p21168c-360-list.png');
    // Filter: the selects come, a chosen group counts
    await ev(`(() => { document.querySelector('#view .ctfbtn').click(); return 1; })()`);
    check(await until(`!!document.querySelector('#ct-group')?.getClientRects().length && !!document.querySelector('#ct-book')?.getClientRects().length && document.querySelector('#view .ctfbtn')?.getAttribute('aria-expanded') === 'true'`), '360: Filter shows group and address book');
    await ev(`(() => { const s = document.querySelector('#ct-group'); s.value = 'Press'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await until(`document.querySelectorAll('#view .ctrow[data-ctopen]').length === 2 && document.querySelector('#view .ctfbtn .ctfn')?.textContent === '1' && /1/.test(document.querySelector('#view .ctfbtn').getAttribute('aria-label'))`), '360: one active filter, the button says 1, two contacts left');
    await shot('p21168c-360-filter.png');
    await ev(`(() => { const s = document.querySelector('#ct-group'); s.value = ''; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await until(`document.querySelectorAll('#view .ctrow[data-ctopen]').length === 6 && !document.querySelector('#view .ctfbtn .ctfn')`), '360: no filter, no number');
    // More has Select on the phone
    await ev(`(() => { document.querySelector('#view [data-ct="menu"]').click(); return 1; })()`);
    check(await until(`[...document.querySelectorAll('#pop [role="menuitem"]')].some(b => /^\\s*Select\\s*$/.test(b.textContent))`), '360: Select is in More');
    await ev(`(closePop(), 1)`);

    // the card's head
    await ev(`(() => { document.querySelector('#view .ctrow[data-ctopen="${C.jana}"]').click(); return 1; })()`);
    check(await until(`location.hash === '#contacts/${C.jana}' && !!document.querySelector('#view .ctcard #ct-h')`), '360: the card opens');
    const hd = await until(`(() => { const r = s => { const e = document.querySelector(s); if (!e || !e.getClientRects().length) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), r: Math.round(b.right), t: Math.round(b.top), b: Math.round(b.bottom), w: Math.round(b.width)}; };
      const c = document.querySelector('#view .ctcard[data-ck]'); return c ? {card: r('#view .ctcard[data-ck]'), av: r('#view .cthead .ctav'), name: r('#view .cthn'), edit: r('#view .cthead [data-ct="edit"]'), more: r('#view .cthead [data-ct="cmenu"]'), back: r('#view .cthead [data-ct="back"]'),
        sw: c.scrollWidth, cw: c.clientWidth, crumb: !!document.querySelector('#view .ofmcrumb'), hint: !!document.querySelector('#view .ct18'), lycust: !!document.querySelector('#view .ctcard [data-act="ly-custom"]')} : null; })()`);
    check(hd && hd.av && hd.edit && hd.more && hd.back && Math.abs(hd.edit.t - hd.av.t) < hd.av.b - hd.av.t && Math.abs(hd.more.t - hd.edit.t) <= 8, '360: back, picture, Edit and More in one row ' + JSON.stringify(hd));
    check(hd && hd.name && hd.name.t >= hd.av.b - 1 && hd.name.w >= .85 * hd.card.w, '360: the name below the picture over the full width ' + JSON.stringify(hd));
    check(hd && hd.sw <= hd.cw + 1, '360: the card does not scroll sideways ' + JSON.stringify(hd));
    check(hd && !hd.crumb && !hd.hint && !hd.lycust, '360: no path line beside the back arrow, no office hint and no Arrange row above the card ' + JSON.stringify(hd));
    await shot('p21168c-360-card.png');
    await ev(`(() => { document.querySelector('#view .ctcard [data-ct="cmenu"]').click(); return 1; })()`);
    check(await until(`[...document.querySelectorAll('#pop [role="menuitem"]')].some(b => /Arrange blocks/.test(b.textContent))`), '360: Arrange blocks… is in the card\'s More');
    await ev(`(closePop(), 1)`);
    await ev(`(() => { document.querySelector('#view .ctcard [data-ct="back"]').click(); return 1; })()`);
    check(await until(`location.hash === '#contacts' && !!document.querySelector('#view .ctrow[data-ctopen]')`), '360: back to the list');

    // the selection bar: whole words, the rest in "..."
    await ev(`(() => { bk_start(${C.Petra}); bk_toggle(${C.Mia}); bk_toggle(${C.Ole}); return CT.pick.size; })()`);
    const sb = await until(`(() => { const b = document.querySelector('#ct-sbar'), x = b && b.querySelector('.mbx'); if (!b || !x) return null; const vis = [...b.querySelectorAll('.mbb')].filter(e => !e.hidden && e.getClientRects().length);
      return {n: vis.length, row: vis.every(e => e.offsetTop < x.offsetTop + x.offsetHeight && e.offsetTop + e.offsetHeight > x.offsetTop), whole: vis.every(e => { const l = e.querySelector('.mbl'); return !l || l.scrollWidth <= l.clientWidth + 1; }), words: vis.map(e => e.querySelector('.mbl')?.textContent), dots: !b.querySelector('.mbdots').hidden, hid: [...b.querySelectorAll('.mbb[hidden]:not(.mbdots)')].map(e => e.getAttribute('aria-label')), sw: b.scrollWidth, cw: b.clientWidth}; })()`);
    check(sb && sb.row && sb.whole && sb.sw <= sb.cw + 1, '360: the selection bar is one row of whole words ' + JSON.stringify(sb));
    check(sb && (sb.dots ? sb.hid.length > 0 : sb.hid.length === 0), '360: "..." shows exactly when buttons went into it ' + JSON.stringify(sb));
    await shot('p21168c-360-select.png');
    if (sb?.dots) {
      await ev(`(() => { document.querySelector('#ct-sbar .mbdots').click(); return 1; })()`);
      check(await until(`(() => { const t = [...document.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim()); return ${JSON.stringify(sb.hid)}.every(h => t.some(x => x.includes(h))); })()`), '360: the "..." menu has the buttons that did not fit ' + JSON.stringify(sb.hid));
      await ev(`(closePop(), 1)`);
    }
    await ev(`(bk_end(), 1)`);
  }, true);

  console.log(`p21168_c_contacts_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
