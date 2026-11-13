// 2.765.0 A (#5170) UI test (Firefox, a touch screen), fresh DB: the phone's main views at the phone widths, one sign-in.
// kalmido-suite: fresh
// Widths: 375 (iPhone), 460 (Fold 8 closed, over the 420 px phone rules), 840 (Fold 8 open: the desktop layout from 768 px on)
// and the iPhone Duo closed, upright (382 x 580, measured in Safari of the iOS 27.1 simulator at the device test of 01.11.2026).
// Views: Today, a project with an open task and its comments, the file store with an open document, the wiki, the calendar,
// contacts, Office > Invoices, the agent chat, the settings. Per view and width:
// - nothing runs over the side (scrollWidth <= innerWidth), also inside an open sheet / dialog
// - no button narrower than its content (scrollWidth > clientWidth + 1) and no two buttons of one bar with overlapping
//   rectangles (#5163)
// - the "…" of the header opens; every entry that leads to a further menu carries the arrow .mchev, inside the entry and the
//   screen (#5164); a further menu opens on a tap (phones: Back on top)
// - the sheet closes (its X on a phone, Escape on 840 where it is a popover), and the bottom bar stays reachable: on screen and
//   nothing lies over its buttons (the bottom bar exists below 768 px only)
// Gestures: a long press on a task starts the selection, its "More" holds the task's menu (phones; on 840 the selection is
// edited in the panel); leafing in the open document with a finger (#5150); a tap in a scrolled dialog hits the row under the
// finger (#5062, as p2649_c_sheettap_ui).
// Firefox cannot check Safari's own behaviour (safe area, 100vh with the address bar, the on-screen keyboard): that stays with
// the device test in the iOS simulator. The person works without an organisation (freelancer parity: her own office).
// P2765A_SHOTS=<dir> = a picture per view and width.
const {sleep, B, login} = require('./boot');
const {realClick} = require('./ff');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2765_a_touch_ui', check, shots: 'P2765A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };

// [name, width, height]; heights of the Fold are a usual window, only the widths matter here
const WIDTHS = [['iphone', 375, 812], ['fold-closed', 460, 860], ['fold-open', 840, 900], ['duo-closed', 382, 580]];
// Not measured yet (the simulator cannot fold or turn the iPhone Duo outside the live train's device test): the Duo open
// (upright), closed (landscape) and open (landscape) - left out on purpose until measured, never guessed (#5170).
const DUO_NOT_MEASURED = ['duo-open', 'duo-closed-landscape', 'duo-open-landscape'];
const FEATURES = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,comments,events,contacts,files,docs,' +
  'family,contracts,home,care,health,review,travel,reading,clients,office,dispo,workload,forms,wiki,budget,feeds,sheets,videos,agents';

function textPdf(lines) {  // a one-page PDF with a text layer, written by hand (as p2683_a_docnav_ui)
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c);
  const stream = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
const waitFor = async (fn, ms = 30000) => { const end = Date.now() + ms; for (;;) { const v = await fn().catch(() => false); if (v || Date.now() > end) return v; await sleep(200); } };
async function upload(name, lines) {
  const fd = new FormData();
  fd.append('files', new Blob([textPdf(lines)], {type: 'application/pdf'}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = (await r.json()).ids[0];
  await waitFor(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state));
  return id;
}

// ---- checks run in the page
// the visible elements; fixed ones have no offsetParent
const VIS = `const vis = e => { if (!e || !e.getClientRects().length) return false; const s = getComputedStyle(e); if (s.visibility === 'hidden' || s.display === 'none') return false; const r = e.getBoundingClientRect(); return r.width > 1 && r.height > 1; };
  const nm = e => (e.id ? '#' + e.id : '') + (e.dataset.act ? '[' + e.dataset.act + ']' : '') + ' ' + (e.getAttribute('aria-label') || e.textContent || e.className || '').trim().replace(/\\s+/g, ' ').slice(0, 30);`;
// side overflow of the page and of the open sheet / dialog; cut buttons and overlapping buttons of one bar
const AUDIT = `(() => { ${VIS}
  const out = {vw: innerWidth, sw: document.documentElement.scrollWidth, bw: document.body.scrollWidth, cards: [], cut: [], lap: []};
  for (const c of document.querySelectorAll('.modal > .card, #pop:not(.hidden), #detail')) if (vis(c) && c.scrollWidth > c.clientWidth + 1 && getComputedStyle(c).overflowX !== 'visible') out.cards.push(nm(c) + ' ' + c.scrollWidth + '/' + c.clientWidth);
  const roots = [...document.querySelectorAll('#top, #tabs, #mbar, #view, #detail, .modal > .card')].filter(vis);
  const btns = new Set(); for (const r of roots) for (const b of r.querySelectorAll('button, .btn, .iconbtn, [role="button"]')) if (vis(b)) btns.add(b);
  // a hit area (an empty ::before / ::after that paints nothing, e.g. .chk::after with inset -.625rem) is no content: measured
  // without it; everything that paints counts
  document.getElementById('p2765-np') || Object.assign(document.head.appendChild(document.createElement('style')), {id: 'p2765-np', textContent: '.p2765-npb::before,.p2765-npa::after{display:none!important}.p2765-nps{display:none!important}'});
  const clear = c => !c || c === 'transparent' || (c.startsWith('rgba(') && parseFloat(c.split(',')[3]) === 0);
  // an icon drawn in a transparent colour (an unticked .chk: color transparent) paints nothing either
  const ghost = e => { if (!(e instanceof SVGSVGElement)) return false; const s = getComputedStyle(e); if (+s.opacity === 0 || s.visibility === 'hidden') return true;
    const cc = clear(s.color); return cc && (s.fill === 'none' || clear(s.fill) || /currentcolor/i.test(s.fill) || s.fill === s.color) && (s.stroke === 'none' || clear(s.stroke) || /currentcolor/i.test(s.stroke) || s.stroke === s.color); };
  const blank = (e, w) => { const s = getComputedStyle(e, w); if (s.display === 'none' || !/^(none|normal|""|'')$/.test(s.content)) return false;
    return clear(s.backgroundColor) && s.backgroundImage === 'none' && s.boxShadow === 'none' && !parseFloat(s.borderTopWidth) && !parseFloat(s.borderLeftWidth) && !parseFloat(s.borderRightWidth) && !parseFloat(s.borderBottomWidth) && (s.outlineStyle === 'none' || !parseFloat(s.outlineWidth)); };
  for (const b of btns) { if (b.scrollWidth <= b.clientWidth + 1) continue;
    if (b.matches('.cal .cev, .week .cev') && getComputedStyle(b).textOverflow === 'ellipsis') continue;  // 2.884.0 (#5469): a month / week chip is role=button now (keyboard); its title ends in "…" on purpose (full title in its tooltip)
    const ps = [b, ...b.querySelectorAll('*')], marks = [];
    // the status dot and the agent mark of an avatar sit on its edge on purpose (a badge, not cut content)
    for (const e of ps) { if (e !== b && (ghost(e) || e.matches('.avb .adot, .avb .abot-b'))) { e.classList.add('p2765-nps'); marks.push([e, 'p2765-nps']); continue; } if (blank(e, '::before')) { e.classList.add('p2765-npb'); marks.push([e, 'p2765-npb']); } if (blank(e, '::after')) { e.classList.add('p2765-npa'); marks.push([e, 'p2765-npa']); } }
    const sw = b.scrollWidth; marks.forEach(([e, c]) => e.classList.remove(c));
    if (sw > b.clientWidth + 1) out.cut.push(nm(b) + ' ' + sw + '/' + b.clientWidth + ' (beyond its edge: ' + (br => [...b.querySelectorAll('*')].filter(e => { const r = e.getBoundingClientRect(); return r.right > br.right + 1 || r.left < br.left - 1; })
      .map(e => { const r = e.getBoundingClientRect(); return e.tagName.toLowerCase() + '.' + String(e.className.baseVal ?? e.className).trim().split(/ +/).join('.').slice(0, 30) + ' ' + Math.round(r.left - br.left) + '..' + Math.round(r.right - br.left); }).slice(0, 4).join('; ') || 'text / a pseudo element')(b.getBoundingClientRect()) + ')'); }
  const bars = new Map(); for (const b of btns) { const p = b.parentElement; if (!bars.has(p)) bars.set(p, []); bars.get(p).push(b); }
  for (const [p, bs] of bars) { if (bs.length < 2) continue; const rs = bs.map(b => b.getBoundingClientRect());
    for (let i = 0; i < rs.length; i++) for (let j = i + 1; j < rs.length; j++) { const a = rs[i], c = rs[j];
      if (a.left < c.right - 1 && c.left < a.right - 1 && a.top < c.bottom - 1 && c.top < a.bottom - 1) out.lap.push(nm(bs[i]) + ' / ' + nm(bs[j])); } }
  return out; })()`;
// the open menu: on screen, every entry leading on carries its arrow inside the entry and the screen
const MENU = `(() => { ${VIS}
  const p = document.querySelector('#pop'); if (!vis(p) || p.classList.contains('hidden')) return null;
  const r = p.getBoundingClientRect(), items = [...p.querySelectorAll('[role="menuitem"]')].filter(vis), bad = [];
  for (const it of items) { if (!(it.classList.contains('msubm') || it.classList.contains('mnext') || it.getAttribute('aria-haspopup') === 'menu')) continue;
    const c = it.querySelector('.mchev'), ir = it.getBoundingClientRect(), cr = c && c.getBoundingClientRect();
    if (!vis(c) || cr.right > ir.right + 1 || cr.left < ir.left - 1 || cr.right > innerWidth) bad.push(nm(it)); }
  return {n: items.length, sheet: p.classList.contains('sheet'), left: Math.round(r.left), right: Math.round(r.right), over: p.scrollWidth > p.clientWidth + 1,
    arrows: items.filter(i => i.querySelector('.mchev')).length, sub: !!p.querySelector('.msubm'), bad, labels: items.map(i => i.textContent.trim().slice(0, 20))}; })()`;
// the bottom bar (phones): shown, on screen, nothing over its buttons, no sheet / dialog left over it
const TABS = `(() => { ${VIS}
  const t = document.querySelector('#tabs'); if (innerWidth >= 768) return {none: true, pop: !document.querySelector('#pop:not(.hidden)'), modal: !document.querySelector('.modal')};
  if (!vis(t)) return {shown: false};
  const r = t.getBoundingClientRect(), hid = [];
  for (const b of t.querySelectorAll('button')) { if (!vis(b)) continue; const q = b.getBoundingClientRect(), h = document.elementFromPoint(q.left + q.width / 2, q.top + q.height / 2); if (!h || !(h === b || b.contains(h))) hid.push(nm(b) + ' under ' + (h ? h.tagName + (h.id ? '#' + h.id : '') + '.' + String(h.className).slice(0, 30) : 'nothing')); }
  return {shown: true, onscreen: r.top >= 0 && r.bottom <= innerHeight + 1 && r.left >= -1 && r.right <= innerWidth + 1, n: t.querySelectorAll('button').length, hid,
    pop: !document.querySelector('#pop:not(.hidden)'), modal: !document.querySelector('.modal')}; })()`;

(async () => {
  const t0 = Date.now();
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', whatsnew_on: '0', features: FEATURES});
  const st = await call('GET', '/api/state');
  check(((st.me || {}).workspaces || []).length === 0, 'alice works without an organisation (freelancer parity)');
  const today = new Date(Date.now() - new Date().getTimezoneOffset() * 60000).toISOString().slice(0, 10);

  // ---- invented data for every view
  const L = (await call('POST', '/api/lists', {name: 'Garden project'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Order the new fence posts', list_id: L, due: today})).id;
  await call('POST', '/api/tasks', {title: 'Ask the neighbour about the hedge', list_id: L});
  for (const b of ['The shop has them in stock until Friday.', 'Twelve posts, two metres each, please.']) await call('POST', `/api/tasks/${T}/comments`, {body: b});
  check(L && T, `setup: a project with an open task (${L}/${T})`);
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Garden/Plan', body: '# Plan\n\nPosts first, then the gate.\n\n- [ ] posts\n- [ ] gate'})).id;
  check(PG, 'setup: a wiki page');
  const evt = await call('POST', '/api/events', {title: 'Fence delivery', start: `${today}T10:00`, end: `${today}T11:00`});
  check(evt.http < 300, 'setup: an event ' + evt.http);
  const bk = await call('POST', '/api/books', {name: 'Suppliers'});
  const ct = await call('POST', '/api/contacts', {book_id: bk.id, given: 'Erika', family: 'Example', org: 'Example Timber Ltd'});
  check(ct.http < 300, 'setup: a contact ' + ct.http);
  const cl = await call('POST', '/api/clients', {name: 'Example Garden Ltd', street: 'Sample Street 1', zip: '12345', city: 'Sampletown', country: 'DE'});
  const inv = await call('POST', '/api/office/docs', {kind: 'invoice', client_id: cl.id, service_from: '2026-10-01', items: [{title: 'Fence work', qty: 1, rate: 100}]});
  check(inv.http === 201, 'setup: an invoice in her own office ' + inv.http);
  // personal agents are off on a fresh server: the instance admin (alice) adds one
  const ag = await call('POST', '/api/admin/agents', {username: 'gardenbot', display_name: 'Gardenbot', scopes: ['write'], owner_id: st.me.id});
  check(ag.id, 'setup: an agent of her own ' + JSON.stringify(ag).slice(0, 120));
  const DOCS = [];
  for (const [n, l] of [['one.pdf', 'Timber Example Ltd'], ['two.pdf', 'Garden Sample GmbH'], ['three.pdf', 'Fence Example AG']]) DOCS.push(await upload(n, [l, 'Invoice']));
  for (const id of DOCS) await call('POST', `/api/docs/${id}/review`, {done: true});
  const PID = (await call('GET', `/api/docs/${DOCS[0]}`)).parent_id;
  check(PID && (await call('GET', `/api/docs/${DOCS[2]}`)).parent_id === PID, 'setup: three documents in one folder');
  await call('PATCH', '/api/settings', {set_delta: {ab_cards: {add: ['n:' + PID]}}});
  const tSetup = Date.now();

  await firefox(async o => {
    const {cmd, ev, nav, ctx, shot, drag, until, idle} = o;
    const tap = sel => realClick(o, sel, {kind: 'touch'});
    const key = async k => { await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k', actions: [{type: 'keyDown', value: k}, {type: 'keyUp', value: k}]}]}); await cmd('input.releaseActions', {context: ctx}); };
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');

    // the "…" of the header: opens, arrows, a further menu, closes; the bottom bar reachable after
    const moreMenu = async (t, W) => {
      // render.js hides the "…" when it would hold nothing (desktop layout: no undo / redo in it) - then there is no menu
      const hid = await ev(`(() => { if (document.body.classList.contains('in-chat')) return false; const b = document.querySelector('#top [data-act="top-more"]'); return !!b && b.hidden && !topMoreItems().length; })()`);
      if (hid) { check(W >= 768, `${t}: an empty "…" is hidden only in the desktop layout`); console.log(`${t}: no "…" (nothing in it)`); return; }
      // 2.1121.0 (#6031): a phone's open knowledge page has no "…" in the head bar since 2.1108.0 (#5965): the page's own "…"
      // carries the head bar's entries (render.js renderTop0 / wiki.js wk_pmenuItems)
      const wkp = await ev(`!document.querySelector('#top [data-act="top-more"]') && typeof wk_phonePage === 'function' && wk_phonePage() && !!document.querySelector('#view [data-wk="pmenu"]')`);
      const r = await tap(await ev(`document.body.classList.contains('in-chat')`) ? '#view [data-act="chat-head-menu"]' : wkp ? '#view [data-wk="pmenu"]' : '#top [data-act="top-more"]');
      check(r.ok, `${t}: the "…" of the header can be tapped (${r.on}) ` + (r.ok ? '' : await ev(`[document.body.className, [...document.querySelectorAll('#view [data-act], #achat [data-act]')].map(e => e.dataset.act).slice(0, 30).join(',')].join(' ')`)));
      if (!r.ok) return;
      const m = await until(`(${MENU})`, {timeout: 8000});
      check(m && m.n > 0, `${t}: "…" opens a menu ${JSON.stringify(m)}`);
      if (!m) return;
      check(m.left >= -1 && m.right <= W + 1 && !m.over, `${t}: the menu stays on the screen ${JSON.stringify(m)}`);
      check(!m.bad.length, `${t}: every entry leading to a further menu carries its arrow .mchev (#5164) ${JSON.stringify(m.bad)}`);
      check(m.sheet === (W < 768), `${t}: a sheet below 768 px, a popover above ${m.sheet}`);
      if (m.sub && W < 768) {  // a further menu opens in the same sheet, Back on top
        const s = await tap('#pop .msubm');
        check(s.ok && await until(`!!document.querySelector('#pop:not(.hidden) .mback')`, {timeout: 5000}), `${t}: an entry with an arrow opens its further menu (${s.on})`);
      }
      if (W < 768) { const x = await tap('#pop .tch-shx'); check(x.ok, `${t}: the X of the sheet can be tapped (${x.on})`); } else await key('');
      check(await until(`!document.querySelector('#pop:not(.hidden)') && (!document.querySelector('#scrim') || document.querySelector('#scrim').classList.contains('hidden'))`, {timeout: 5000}), `${t}: the sheet closes`);
      const b = await ev(`(${TABS})`);
      check(b.none ? b.pop && b.modal : b.shown && b.onscreen && b.n > 0 && !b.hid.length && b.pop && b.modal, `${t}: the bottom bar stays reachable after the sheet ${JSON.stringify(b)}`);
    };
    const audit = async t => {
      const a = await ev(AUDIT);
      check(a.sw <= a.vw && a.bw <= a.vw, `${t}: nothing runs over the side (scrollWidth ${a.sw}/${a.bw} <= ${a.vw})`);
      check(!a.cards.length, `${t}: no sheet / dialog / panel runs over the side ${JSON.stringify(a.cards)}`);
      check(!a.cut.length, `${t}: no button narrower than its content ${JSON.stringify(a.cut)}`);
      check(!a.lap.length, `${t}: no two buttons of a bar overlap (#5163) ${JSON.stringify(a.lap)}`);
    };
    const view = async (t, hash, ready) => {
      await nav(B + hash);
      const up = await until(ready, {timeout: 20000});
      check(up, `${t}: the view is up (${ready})`);
      await idle();
      return up;
    };

    for (const [name, W, Ht] of WIDTHS) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Ht}});
      check(await until(`innerWidth === ${W}`, {timeout: 5000}), `${name}: the window is ${W} px wide`);
      const tag = v => `${v} @${name} ${W}`;
      const pass = async (v, hash, ready, extra) => {
        if (!await view(tag(v), hash, ready)) return;
        if (extra) await extra();
        await audit(tag(v));
        await shot(`p2765a-${v}-${name}.png`);
        await moreMenu(tag(v), W);
      };

      // Today, then the tap in a scrolled dialog (#5062)
      await pass('today', '#today', `!!document.querySelector('#view .trow[data-id="${T}"]')`);
      await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); const m = modal('<h3>Rows</h3>' + Array.from({length: 40}, (_, i) => '<label class="chkl"><input type="checkbox" data-row="' + i + '"><span>Row ' + i + '</span></label>').join('')); m.classList.add('p2765a'); return 1; })()`);
      check(await until(`(() => { const c = document.querySelector('.p2765a > .card'); return !!c && c.getAnimations().length === 0 && c.scrollHeight > c.clientHeight + 300; })()`), tag('dialog') + ': setup: the dialog scrolls');
      const st0 = await ev(`(() => { const c = document.querySelector('.p2765a > .card'); c.scrollTop = 300; return c.scrollTop; })()`);
      const PT = `(() => { const c = document.querySelector('.p2765a > .card'), h = innerHeight / 2; const l = [...c.querySelectorAll('label.chkl')].find(x => { const r = x.getBoundingClientRect(); return r.top <= h && r.bottom >= h; }); if (!l) return null; const r = l.getBoundingClientRect(), p = {x: Math.round(r.left + r.width * .7), y: Math.round(r.top + r.height / 2), row: l.querySelector('input').dataset.row}; const same = window.__p2765 === JSON.stringify(p); window.__p2765 = JSON.stringify(p); return same ? p : null; })()`;
      const p = await until(() => ev(PT).catch(() => null));
      check(!!p, tag('dialog') + ': a row under the middle of the screen');
      if (p) {
        await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: p.x, y: p.y}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]});
        await cmd('input.releaseActions', {context: ctx});
        const ticked = `[...document.querySelectorAll('.p2765a input:checked')].map(x => x.dataset.row).join(',')`;
        await until(`${ticked} !== ''`, {timeout: 5000});
        check(await ev(ticked) === p.row, tag('dialog') + `: a tap in the scrolled dialog toggles the row under the finger (#5062; row ${p.row}, ticked: ${await ev(ticked)})`);
        check(await ev(`document.querySelector('.p2765a > .card').scrollTop`) === st0, tag('dialog') + ': the tap keeps the scroll');
      }
      await ev(`(() => { const m = document.querySelector('.p2765a'); if (m) modalClose(m); return 1; })()`);
      await until(`!document.querySelector('.p2765a')`, {timeout: 5000});

      // the project: a long press on the task, then the task with its comments
      await pass('project', `#l/${L}`, `!!document.querySelector('#view .trow[data-id="${T}"]')`);
      const row = await ev(`(() => { const e = document.querySelector('#view .trow[data-id="${T}"] .ttl') || document.querySelector('#view .trow[data-id="${T}"]'); e.scrollIntoView({block: 'center'}); const r = e.getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()`);
      await drag(row.x, row.y, 0, 0, 'touch', 650);
      check(await until(`S.multiMode && S.multi.has(${T}) && !!document.querySelector('#mbar:not(.hidden)')`, {timeout: 5000}), tag('long press') + ': a long press on the task starts the selection with it');
      if (W < 768) {
        const r = await tap('#mbar [data-act="mb-menu"]');
        const m = r.ok && await until(`(${MENU})`, {timeout: 5000});
        check(m && !m.bad.length && m.arrows > 0, tag('long press') + `: "More" of the selection opens, its entries leading on carry the arrow (#5164; ${r.on}) ${JSON.stringify(m)}`);
        // the task's own menu: "More actions" (a further menu, with its arrow) holds it
        const has = await ev(`(() => { const e = [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => /^More actions/.test(x.textContent.trim())); if (e) e.dataset.p2765 = 'ma'; return !!e; })()`);
        check(has, tag('long press') + `: "More" of the selection offers the task's "More actions" ${JSON.stringify(m && m.labels)}`);
        if (has) {
          const r2 = await tap('#pop [data-p2765="ma"]');
          const m2 = r2.ok && await until(`(() => { const m = (${MENU}); return m && m.labels.some(l => /^New date/.test(l)) && m; })()`, {timeout: 5000});
          check(m2 && !m2.bad.length, tag('long press') + `: "More actions" opens the task's menu, "New date…" with its arrow (${r2.on}) ${JSON.stringify(m2)}`);
        }
        if (m) { await tap('#pop .tch-shx'); await until(`!document.querySelector('#pop:not(.hidden)')`, {timeout: 5000}); }
        await audit(tag('selection'));
      }
      await key('');
      if (!await until(`!S.multiMode && !S.multi.size`, {timeout: 3000})) await ev(`(() => { S.multi.clear(); S.multiMode = false; renderMultiBar(); return 1; })()`);
      await ev(`(location.hash = '#t/${T}', 1)`);
      check(await until(`document.querySelectorAll('#detail .cm').length >= 2`, {timeout: 15000}), tag('task') + ': the open task shows its comments');
      await idle();
      await audit(tag('task'));
      await shot(`p2765a-task-${name}.png`);
      await key('\uE00C');
      check(await until(`!S.sel`, {timeout: 5000}), tag('task') + ': the open task closes (Escape)');
      if (await ev('!!S.sel')) await ev('(closeDetail(), 1)');
      const bt = await until(`(() => { const b = (${TABS}); return (b.none || b.shown && b.onscreen && !b.hid.length) && b; })()`, {timeout: 5000}) || await ev(`(${TABS})`);
      check(bt.none || bt.shown && bt.onscreen && !bt.hid.length, tag('task') + `: the bottom bar is reachable after the task closed ${JSON.stringify(bt)}`);

      // the file store with an open document, leafing with a finger (#5150)
      if (await view(tag('ablage'), `#ablage/${PID}`, `document.querySelectorAll('.abview [data-dco]').length === 3`)) {
        const first = await ev(`+document.querySelector('.abview [data-dco]').dataset.dco`);
        const c = await tap(`.abview [data-dco="${first}"]`);
        check(c.ok && await until(`+(document.querySelector('.dv-view .dc-body')?.dataset.id || 0) === ${first} && !!document.querySelector('.dv-view .dv-pages')`, {timeout: 20000}), tag('document') + `: a tap on the card opens the document (${c.on})`);
        await idle();
        // 2.765.0 (#5331): the preview has room at every width (840 px beside the side bar and the file tree: was 16 px)
        const pw = await ev(`(() => { const v = document.querySelector('.dv-view').getBoundingClientRect(), p = document.querySelector('.dv-view .dv-pv').getBoundingClientRect(); return {v: Math.round(v.width), p: Math.round(p.width), h: Math.round(p.height)}; })()`);
        check(pw.p >= Math.min(280, pw.v * .8) && pw.h >= 200, tag('document') + `: the preview has room (#5331) ${JSON.stringify(pw)}`);
        await audit(tag('document'));
        await shot(`p2765a-document-${name}.png`);
        const pv = await ev(`(() => { const r = document.querySelector('.dv-view .dv-pages').getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + Math.min(120, r.height / 2)), w: Math.round(r.width)}; })()`);
        await ev(`(() => { window.__p2765t = []; for (const k of ['touchstart', 'touchmove', 'touchend', 'touchcancel', 'pointercancel']) document.addEventListener(k, e => { if (__p2765t.length < 40) __p2765t.push(k + (e.cancelable ? '' : '!') + (k === 'touchmove' ? ':' + (DCW.sw ? DCW.sw.lock + '/' + Math.round(DCW.sw.dx) : 'nosw') : '')); }, {capture: true, passive: true}); return 1; })()`);
        await drag(pv.x + pv.w / 4, pv.y, -Math.round(pv.w / 2), 0, 'touch');
        check(await until(`+(document.querySelector('.dv-view .dc-body')?.dataset.id || 0) !== ${first} && !document.querySelector('.dv-view .dc-nb')`, {timeout: 10000}), tag('document') + ': a swipe to the left leafs to the next document (#5150) ' + await ev(`document.querySelector('.dv-view .dc-navn')?.textContent + ' touch-action ' + getComputedStyle(document.querySelector('.dv-view .dv-pages')).touchAction + ' at ' + (h => h ? h.tagName + '.' + String(h.className).slice(0, 40) + ' in pages ' + !!h.closest('.dv-view .dv-pages') : '-')(document.elementFromPoint(${pv.x + pv.w / 4}, ${pv.y})) + ' snap ' + !!DCW.snap + ' nav ' + dc_navIdx(DC.doc) + ' ' + __p2765t.slice(0, 8).join(' ')`).catch(() => '?'));
        await audit(tag('document 2'));
        await moreMenu(tag('document'), W);
      }

      await pass('wiki', `#wiki/${PG}`, `!!document.querySelector('#view .wkpage')`);
      await pass('calendar', '#cal', `!!document.querySelector('#view .calbar')`);
      await pass('contacts', '#contacts', `!!document.querySelector('#view .ctlist .ctrow')`);
      await pass('invoices', '#office/invoices', `!!document.querySelector('#view .ofdlist')`);
      await pass('agent chat', `#agents/${ag.id}`, `!!document.querySelector('#view .chview .chhb')`);

      // the settings: a sheet of their own; it closes, the bottom bar is reachable after
      await ev(`(settingsModal(), 1)`);
      check(await until(`(() => { const c = document.querySelector('.smodal > .card'); return !!c && c.getAnimations().length === 0; })()`, {timeout: 10000}), tag('settings') + ': the settings open');
      await idle();
      await audit(tag('settings'));
      await shot(`p2765a-settings-${name}.png`);
      const x = await tap('.smodal [data-m="close"]');
      check(x.ok && await until(`!document.querySelector('.smodal')`, {timeout: 5000}), tag('settings') + `: the settings close with their X (${x.on})`);
      const b = await ev(`(${TABS})`);
      check(b.none ? b.modal : b.shown && b.onscreen && !b.hid.length && b.modal, tag('settings') + `: the bottom bar stays reachable after the settings ${JSON.stringify(b)}`);
    }
  }, true);

  const s = Math.round((Date.now() - t0) / 1000), sf = Math.round((Date.now() - tSetup) / 1000);
  console.log(`p2765_a_touch_ui: ${ok} ok, ${F.length} failed (${s} s, Firefox ${sf} s; widths ${WIDTHS.map(w => w[0] + ' ' + w[1] + 'x' + w[2]).join(', ')}; not measured yet: ${DUO_NOT_MEASURED.join(', ')})`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack || e); console.log(`p2765_a_touch_ui: ${ok} ok, ${F.length + 1} failed`); process.exit(1); });
