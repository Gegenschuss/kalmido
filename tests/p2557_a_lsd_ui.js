// 2.557.0 A (#4553) UI test, own container (start.sh, isolated test database), Firefox with a mouse. Invented data only.
// kalmido-suite:
// List and detail side by side on wide screens: once the content area (#view) is at least 100rem wide (#view.lsdw) the list
// stays on the left (about 40 %) and the open entry stands right of it, the pair at most 160rem; below that as before.
// - contacts and clients: at 1920 / 2560 / 3840 list about 40 % + card right of it; at 1440 the narrow list (22rem) as before;
//   Esc closes the card, the list stays and its row keeps the keyboard focus
// - a quotation: at 1920 the rows of its list beside the editor, the open one marked, a click on another row opens that one
//   and marks it, Esc closes the document (the list alone); at 1440 the editor in place of the list as before
// - a receipt: at 1920 its dialog stands right of the list (no backdrop), another row replaces it, Esc closes it; at 1440 the
//   dialog in the middle as before
// - the task panel grows with the room: 25.5rem at 1440, wider at 2560, at most 48rem at 3840
// - a phone (390) never gets the pair
// Screenshots (P2557A_SHOTS) at 1440, 1920, 2560 and 3840, light and dark.
// freelancer-matrix: Nebeneinander (alice has no organisation; the pair does not depend on the workspace)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2557_a_lsd_ui', check, shots: 'P2557A_SHOTS'});
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
  check(bk.http === 201, 'setup: an address book ' + bk.http);
  for (const [g, f] of [['Petra', 'Buyer'], ['Jonas', 'Light'], ['Mia', 'Sound'], ['Ole', 'Grip'], ['Lena', 'Cutter']]) await call('POST', '/api/contacts', {book_id: bk.id, given: g, family: f, org: 'Example Film GmbH', emails: [{value: `${g.toLowerCase()}@example.com`, type: ['work']}]});
  const CL = [];
  for (const n of ['Acme Example GmbH', 'Beta Example', 'Gamma Example AG']) CL.push((await call('POST', '/api/clients', {name: n})).id);
  check(CL.every(Boolean), 'setup: three clients');
  await call('GET', '/api/office/settings');
  const OF = [];
  for (const [i, t] of ['Image film', 'Trailer cut', 'Photo day'].entries()) OF.push((await call('POST', '/api/office/docs', {kind: 'offer', client_id: CL[i], project_title: t, date: '2026-10-0' + (i + 1)})).id);
  check(OF.every(Boolean), 'setup: three quotations ' + OF.join());
  const RC = [];
  for (const [n, a] of [['cloud.txt', '23.80'], ['books.txt', '107.00']]) {
    const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([`Receipt example ${n} ${a} EUR`], {type: 'text/plain'}), n);
    const j = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CA}, body: fd})).json().catch(() => ({}));
    const id = j.ids?.[0]; RC.push(id);
    await call('PATCH', `/api/docs/${id}`, {amount: a, date: '2026-10-15'});
    await call('PUT', `/api/docs/${id}/receipt`, {category: 'Software', vat_pct: '19', keep: true});
  }
  check(RC.every(Boolean), 'setup: two receipts ' + RC.join());
  const L = (await call('POST', '/api/lists', {name: 'Shoot plan', kind: 'project'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Book the studio', list_id: L})).id;

  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    const R = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e || !e.getClientRects().length) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), r: Math.round(b.right), t: Math.round(b.top), w: Math.round(b.width)}; })()`;
    const REM = `parseFloat(getComputedStyle(document.documentElement).fontSize)`;
    const ESC = `(() => { (document.activeElement || document.body).dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})); return 1; })()`;
    const shots = async name => { for (const theme of ['light', 'dark']) {
      await ev(`(() => { document.documentElement.dataset.theme = ${JSON.stringify(theme)}; return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1)))); })()`);  // painted before the shot
      await shot(`p2557a-${name}-${theme}.png`);
    } await ev(`(() => { delete document.documentElement.dataset.theme; return 1; })()`); };

    // a phone never gets the pair
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '?w=390#contacts');
    check(await until(`!!S.booted && !!document.querySelector('#view .ctrow')`), '390: the contacts show');
    check(await ev(`!document.querySelector('#view').classList.contains('lsdw')`), '390: no pair on a phone');

    for (const [vw, vh] of [[1440, 900], [1920, 1080], [2560, 1440], [3840, 1600]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      const wide = vw >= 1920;
      // ---- contacts
      await nav(B + '?w=' + vw + '#contacts');
      check(await until(`!!S.booted && !!document.querySelector('#view .ctrow[data-ctopen]')`), `${vw}: the contacts show`);
      check(await until(`document.querySelector('#view').classList.contains('lsdw') === ${wide}`), `${vw}: #view ${wide ? 'is' : 'is not'} wide enough for the pair ` + await ev(`document.querySelector('#view').clientWidth`));
      await ev(`(() => { const b = document.querySelector('#view .ctrow[data-ctopen]'); b.focus(); b.click(); return 1; })()`);
      const ct = await until(`(() => { const c = ${R('#view .ctcard:not(.ctnone)')}, l = ${R('#view .ctlistw')}, p = ${R('#view .ctcols')}; return c && l && p ? {c, l, p, rem: ${REM}} : null; })()`);
      if (!ct) check(false, `${vw}: a contact opens beside the list`);
      else if (wide) {
        check(ct.c.l >= ct.l.r && Math.abs(ct.c.t - ct.l.t) <= 4, `${vw}: contact card right of the list ` + JSON.stringify(ct));
        check(ct.l.w / ct.p.w > .33 && ct.l.w / ct.p.w < .45, `${vw}: the list takes about 40 % of the pair ` + JSON.stringify(ct));
        // 2.583.0 (#4840): no 160rem limit any more, the pair uses the full width
        check(ct.p.w > 96 * ct.rem, `${vw}: the pair is wider than 96rem ` + JSON.stringify(ct));
      } else check(ct.l.w <= 26 * ct.rem + 1 && ct.c.l >= ct.l.r, `${vw}: the list beside the card (at most 26rem) ` + JSON.stringify(ct));  // 2.1168.0 (#6117): the list grows to about a third (was 22rem)
      await shots(`contacts-${vw}`);
      if (wide) {
        await ev(ESC);
        check(await until(`!!document.querySelector('#view .ctcard.ctnone') && !!document.querySelector('#view .ctrow[data-ctopen]')`), `${vw}: Esc closes the contact, the list stays`);
        check(await until(`!!document.activeElement?.matches?.('#view .ctrow[data-ctopen]')`), `${vw}: the row keeps the keyboard focus ` + await ev(`document.activeElement?.outerHTML?.slice(0, 80)`));
      }

      // ---- clients (only the wide pair: below it the page is unchanged)
      if (wide) {
        await nav(B + '?w=' + vw + '#client/' + CL[1]);
        const cl = await until(`(() => { const c = ${R('#view .msclients .ctcard:not(.ctnone)')}, l = ${R('#view .msclients .ctlistw')}, p = ${R('#view .msclients .ctcols')}; return c && l && p && document.querySelector('#view .ctrow[data-clopen="${CL[1]}"][aria-current="true"]') ? {c, l, p} : null; })()`);
        check(cl && cl.c.l >= cl.l.r && cl.l.w / cl.p.w > .33 && cl.l.w / cl.p.w < .45, `${vw}: client card right of the list, list about 40 %, its row marked ` + JSON.stringify(cl));
        await shots(`clients-${vw}`);
        await ev(ESC);
        check(await until(`location.hash === '#clients' && !!document.querySelector('#view .msclients .ctcard.ctnone')`), `${vw}: Esc closes the client, the list stays ` + await ev('location.hash'));
      }

      // ---- a quotation
      await nav(B + '?w=' + vw + '#office/offers/' + OF[0]);
      check(await until(`!!document.querySelector('#view .ofdeditor')`), `${vw}: the quotation opens`);
      if (wide) {
        const q = await until(`(() => { const l = ${R('#view .lsd2 > .lsdl')}, e = ${R('#view .lsd2 > .lsdr')}; return l && e && document.querySelectorAll('#view .lsdl .ofdrow').length === 3 && document.querySelector('#view .lsdl .ofdrow[aria-current="true"]')?.dataset.id === '${OF[0]}' ? {l, e} : null; })()`);
        check(q && q.e.l > q.l.r && q.l.w / (q.e.r - q.l.l) > .33 && q.l.w / (q.e.r - q.l.l) < .45, `${vw}: the list of quotations beside the editor, the open one marked ` + JSON.stringify(q));
        check(await ev(`document.querySelectorAll('#ofd-status').length <= 1 && !document.querySelector('#view .lsdl #ofd-q')`), `${vw}: the list beside it has no search / filter fields (no doubled ids)`);
        await shots(`offer-${vw}`);
        await ev(`(() => { document.querySelector('#view .lsdl .ofdrow[data-id="${OF[2]}"]').click(); return 1; })()`);
        check(await until(`location.hash === '#office/offers/${OF[2]}' && document.querySelector('#view .lsdl .ofdrow[aria-current="true"]')?.dataset.id === '${OF[2]}' && !!document.querySelector('#view .lsdr .ofdeditor')`), `${vw}: another row opens its quotation beside the list ` + await ev('location.hash'));
        await ev(`(() => { document.activeElement?.blur?.(); return 1; })()`);
        await ev(ESC);
        check(await until(`/^#office\\/offers(\\/offer)?$/.test(location.hash) && !document.querySelector('#view .lsd2') && document.querySelectorAll('#view .ofdlist .ofdrow').length === 3`), `${vw}: Esc closes the quotation, the list alone ` + await ev('location.hash'));
      } else {
        check(await ev(`!document.querySelector('#view .lsd2') && !document.querySelector('#view .ofdlist')`), `${vw}: the editor in place of the list as before`);
        await shots(`offer-${vw}`);
      }

      // ---- a receipt
      await nav(B + '?w=' + vw + '#office/receipts');
      check(await until(`document.querySelectorAll('#view [data-rcl="rc"]').length === 2`), `${vw}: the two receipts show`);
      await ev(`(() => { const b = document.querySelector('#view [data-rcl="rc"][data-id="${RC[0]}"]'); b.focus(); b.click(); return 1; })()`);
      check(await until(`!!document.querySelector('.modal.bk-sheet #bk-cat')`), `${vw}: the receipt opens`);
      if (wide) {
        const r = await until(`(() => { const m = document.querySelector('.modal.bk-sheet.lsddock'), c = ${R('.modal.bk-sheet.lsddock > .card')}, row = ${R(`#view [data-rcl="rc"][data-id="${RC[0]}"]`)}, wr = ${R('#view > .ofwrap')}; return m && c && row && wr && getComputedStyle(m).backgroundColor === 'rgba(0, 0, 0, 0)' ? {c, row, wr} : null; })()`);
        check(r && r.c.l > r.row.r, `${vw}: the receipt stands right of the list, no backdrop ` + JSON.stringify(r));
        check(r && Math.abs(r.c.r - r.wr.r) <= 4 && (r.row.r - r.wr.l) / r.wr.w > .33 && (r.row.r - r.wr.l) / r.wr.w < .45, `${vw}: the receipt fills the right part of the pair up to its edge, the list about 40 % ` + JSON.stringify(r));
        check(await ev(`document.querySelector('#view [data-rcl="rc"][data-id="${RC[0]}"]').getAttribute('aria-current') === 'true'`), `${vw}: its row is marked`);
        await shots(`receipt-${vw}`);
        await ev(`(() => { document.querySelector('#view [data-rcl="rc"][data-id="${RC[1]}"]').click(); return 1; })()`);
        check(await until(`document.querySelectorAll('.modal.bk-sheet').length === 1 && document.querySelector('.modal.bk-sheet.lsddock')?.dataset.rxid === '${RC[1]}' && !!document.querySelector('.modal.bk-sheet #bk-cat')`), `${vw}: another row replaces the receipt ` + await ev(`[...document.querySelectorAll('.modal.bk-sheet')].map(m => m.dataset.rxid).join()`));
        await ev(`(() => { document.activeElement?.blur?.(); return 1; })()`);
        await ev(ESC);
        check(await until(`!document.querySelector('.modal.bk-sheet') && !document.body.classList.contains('rcldock') && document.querySelectorAll('#view [data-rcl="rc"]').length === 2`), `${vw}: Esc closes the receipt, the list stays`);
      } else {
        check(await ev(`!document.querySelector('.modal.bk-sheet.lsddock') && getComputedStyle(document.querySelector('.modal.bk-sheet')).backgroundColor !== 'rgba(0, 0, 0, 0)'`), `${vw}: the dialog in the middle as before`);
        await ev(`(() => { document.querySelector('.modal.bk-sheet [data-m="close"]').click(); return 1; })()`);
        await until(`!document.querySelector('.modal.bk-sheet')`);
      }

      // ---- the task panel grows with the room
      await nav(B + '?w=' + vw + '#l/' + L);
      check(await until(`!!S.booted && !!document.querySelector('#view .trow')`), `${vw}: the project shows`);
      await ev(`(() => { openDetail(${T}); return 1; })()`);
      const dt = await until(`(() => { const d = ${R('#detail')}; return d && document.querySelector('#app').classList.contains('detail-open') && d.w > 100 ? {...d, rem: ${REM}} : null; })()`);
      if (!dt) check(false, `${vw}: the task panel opens`);
      else if (vw === 1440) check(Math.abs(dt.w - 25.5 * dt.rem) <= 2, `1440: the task panel keeps 25.5rem ` + JSON.stringify(dt));
      else if (vw === 1920) check(dt.w >= 25.5 * dt.rem - 1 && dt.w <= 48 * dt.rem + 1, `1920: the task panel between 25.5 and 48rem ` + JSON.stringify(dt));
      else if (vw === 2560) check(dt.w > 25.5 * dt.rem + 16 && dt.w <= 48 * dt.rem + 1, `2560: the task panel is wider than 25.5rem ` + JSON.stringify(dt));
      else check(Math.abs(dt.w - 48 * dt.rem) <= 2, `3840: the task panel at most 48rem ` + JSON.stringify(dt));
      await shots(`task-${vw}`);
      await ev(`(() => { closeDetail(); return 1; })()`);
    }
  }, false);

  console.log(`p2557_a_lsd_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
