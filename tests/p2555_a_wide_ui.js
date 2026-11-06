// 2.555.0 UI test, part A (#4554: wide monitors: the settings dialog grows and shows its content in two columns, an invoice /
// kalmido-suite:
// quotation shows the head and the positions side by side), own container (start.sh), Firefox. Invented data only. Alice has
// no organisation (her own private workspace and personal office), so this is the freelancer case too.
// - 2560 px: the settings dialog is wider than at 1440 px, the area "Appearance" flows into two columns (two parts at the same
//   height side by side), the tab order is still the DOM order; an invoice and a quotation: head and positions side by side
// - 1920 px: the same two columns; 1440 px and 390 px: one column as before, nothing overlaps, no sideways scrolling
// Screenshots at 1440, 1920, 2560 and 3840 px, light and dark.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2555_a_wide_ui', check, shots: 'P2555AW_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2555AW_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const today = new Date().toISOString().slice(0, 10);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients,docs,time'});
  await call(CA, 'PUT', '/api/office/settings', {lang: 'en', company_fields: {name: 'Beispiel Studio GmbH', street: 'Musterweg 1', zip: '12345', city: 'Musterstadt', country: 'DE', tax_number: '12/345/67890', iban: 'DE02120300000000202051'}});
  const cl = await call(CA, 'POST', '/api/clients', {name: 'Kunde Eins GmbH', street: 'Kundenweg 5', zip: '20000', city: 'Beispielstadt', country: 'DE'});
  const items = [{title: 'Shoot', qty: 2, unit: 'day', rate: 4000, tax: 'standard'}, {title: 'Script', qty: 1, unit: 'flat', rate: 2000, tax: 'reduced'}, {title: 'Edit', qty: 3, unit: 'day', rate: 900, tax: 'standard'}];
  const inv = await call(CA, 'POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, project_title: 'Imagefilm', service_from: today, items});
  check(!!inv.id, 'setup: an invoice ' + inv.http);
  const off = await call(CA, 'POST', '/api/office/docs', {project_title: 'Imagefilm', client_id: cl.id, service_from: today});
  await call(CA, 'PUT', `/api/office/docs/${off.id}/items`, {items});
  check(!!off.id, 'setup: a quotation ' + off.http);

  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // the settings dialog: its width, the columns of the open area, the first block of each column, overlaps, sideways scrolling
  const SET = `(() => { const md = [...document.querySelectorAll('.smodal')].pop(), card = md.querySelector('.card'), sp = md.querySelector('.spane:not(.hidden)'), sps = md.querySelector('.spanes');
    const r = e => e.getBoundingClientRect(), pr = r(sp), mid = pr.left + pr.width / 2;
    const kids = [...sp.querySelectorAll(':scope > *')].filter(e => e.getClientRects().length && r(e).height > 0);
    const left = kids.filter(e => r(e).left < mid), right = kids.filter(e => r(e).left >= mid);
    // overlaps between the rows / hints of the area (both columns)
    const rows = [...sp.querySelectorAll('.row, .shint')].filter(e => e.getClientRects().length && r(e).height > 0 && !e.closest('[hidden]'));
    let over = 0; for (let i = 0; i < rows.length && over < 3; i++) for (let j = i + 1; j < rows.length; j++) { const a = r(rows[i]), b = r(rows[j]);
      if (rows[i].contains(rows[j]) || rows[j].contains(rows[i])) continue;
      if (a.left < b.right - 1 && b.left < a.right - 1 && a.top < b.bottom - 1 && b.top < a.bottom - 1) { over++; break; } }
    return JSON.stringify({cw: Math.round(r(card).width), cols: getComputedStyle(sp).columnCount, nl: left.length, nr: right.length,
      lt: left[0] ? Math.round(r(left[0]).top) : null, rt: right[0] ? Math.round(r(right[0]).top) : null, over,
      side: document.documentElement.scrollWidth > document.documentElement.clientWidth || card.scrollWidth > card.clientWidth + 1 || sps.scrollWidth > sps.clientWidth + 1}); })()`;
  // the office editor: the head section and the positions section
  const ED = `(() => { const ed = document.querySelector('.ofdeditor'); if (!ed) return 'null'; const r = e => e.getBoundingClientRect();
    const head = ed.querySelector('[data-sec="head"]'), pos = [...ed.querySelectorAll('section.ofdsec')][0];
    const h = r(head), p = r(pos);
    return JSON.stringify({h: [Math.round(h.left), Math.round(h.right), Math.round(h.top)], p: [Math.round(p.left), Math.round(p.right), Math.round(p.top)], hw: Math.round(h.width), cw: Math.round((ed.closest('.lsdr') || ed.parentElement).clientWidth),
      side: document.documentElement.scrollWidth > document.documentElement.clientWidth || ed.scrollWidth > ed.clientWidth + 1,
      tab: head.compareDocumentPosition(pos) & Node.DOCUMENT_POSITION_FOLLOWING ? 1 : 0}); })()`;
  // the dialog is there, its area drawn and its width settled (two looks in a row agree; the module's styles load with it)
  const openSet = async (ev, sec, sel = '.row') => { await ev(`(() => { document.querySelectorAll('.smodal').forEach(m => m.remove()); settingsModal('${sec}'); return 1; })()`);
    if (!await ready(ev, `!!document.querySelector('.smodal .spane:not(.hidden) ${sel}')`)) return false;
    const look = `(() => { const c = document.querySelector('.smodal .card'), sp = document.querySelector('.smodal .spane:not(.hidden)'); return Math.round(c.getBoundingClientRect().width) + ':' + getComputedStyle(sp).columnCount; })()`;
    let last = ''; for (let i = 0; i < 40; i++) { const v = await ev(look); if (v === last) return true; last = v; await sleep(150); }
    return false; };
  // the theme of this run: the appearance synced from the server wins over a value put into localStorage before the load
  const theme_ = t => `(() => { if (typeof LS === 'undefined' || typeof applyLook !== 'function') return false; if (LS.get('theme', 'auto') !== '${'${t}'}') { LS.set('theme', '${'${t}'}'); applyLook(); } return document.documentElement.dataset.theme === '${'${t}'}'; })()`;
  const wide = {};

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    for (const theme of ['light', 'dark']) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
      await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
      for (const [W, Hh] of [[1440, 900], [1920, 1080], [2560, 1440], [3840, 1600], [390, 844]]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
        await nav(B + '#home');
        await ready(ev, `typeof settingsModal === 'function' && !!document.querySelector('#view')`);
        check(await openSet(ev, 'look'), `${theme} ${W}: the settings open on Appearance`);
        const s = JSON.parse(await ev(SET));
        wide[W] = s.cw;
        check(!s.side && !s.over, `${theme} ${W}: settings: nothing overlaps, no sideways scrolling ` + JSON.stringify(s));
        if (W >= 1920 && W !== 390) {
          check(s.cols === '2' && s.nl > 0 && s.nr > 0 && Math.abs(s.lt - s.rt) <= 32, `${theme} ${W}: Appearance in two columns, two parts side by side at the same height ` + JSON.stringify(s));
        } else check(s.cols === 'auto' && s.nr === 0, `${theme} ${W}: one column as before ` + JSON.stringify(s));
        await ready(ev, theme_(theme)); await shot(`p2555-a-settings-${W}-${theme}.png`);
        await ev(`document.querySelector('.smodal')?.remove()`);

        if (W === 390) continue;
        for (const [doc, tab] of [[inv, 'invoices'], [off, 'offers']]) {
          await nav(B + 'static/icon.svg'); await nav(B + `#office/${tab}/${doc.id}`);
          check(await ready(ev, `!!document.querySelector('.ofdeditor [data-sec="head"]') && !!document.querySelector('.ofdeditor section.ofdsec .ofdit')`), `${theme} ${W}: the ${tab} editor opens`);
          const e = JSON.parse(await ev(ED));
          check(!e.side && e.tab === 1, `${theme} ${W} ${tab}: no sideways scrolling, the head before the positions in the DOM ` + JSON.stringify(e));
          // 2.555.0: since #4553 the document may stand beside its list; side by side counts by the document's own width (80rem)
          // 2.571.0 (#4740): the pair reaches 160rem again, so at 2560 / 3840 px the document is >= 1280 px wide and side by side is mandatory
          if (W >= 2560) check(e.cw >= 1280, `${theme} ${W} ${tab}: the document beside its list is at least 80rem wide ` + JSON.stringify(e));
          if (e.cw >= 1280) check(e.p[0] >= e.h[1] && Math.abs(e.p[2] - e.h[2]) <= 2, `${theme} ${W} ${tab}: head and positions side by side ` + JSON.stringify(e));
          else check(e.p[2] > e.h[2] && Math.abs(e.p[0] - e.h[0]) <= 1, `${theme} ${W} ${tab}: head above the positions as before ` + JSON.stringify(e));
          if (tab === 'invoices') { await ready(ev, theme_(theme)); await shot(`p2555-a-invoice-${W}-${theme}.png`); }
        }
      }
      check(wide[2560] > wide[1440] + 200 && wide[1440] <= 1030, `${theme}: the dialog grows on wide monitors, 1440 px as before ` + JSON.stringify(wide));
    }
    // the settings area with sub-tabs: the strip spans both columns at 2560 px
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 2560, height: 1440}});
    await nav(B + '#home'); await ready(ev, `typeof settingsModal === 'function'`);
    // the area Organisation of an admin has the sub-tabs People / Agents / Data
    check(await openSet(ev, 'users', '.aisub'), '2560: Organisation with its sub-tabs');
    const strip = await ev(`(() => { const s = document.querySelector('.smodal .spane:not(.hidden) .aisub'); if (!s) return false; const p = s.closest('.spane'); return s.getBoundingClientRect().width >= p.getBoundingClientRect().width - 2; })()`);
    check(strip, '2560: the sub-tabs span both columns');
    await shot('p2555-a-settings-org-2560.png');
  }, false);

  console.log(`p2555_a_wide_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
