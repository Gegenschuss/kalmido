// 2.31.0 UI tests (agent B: the task panel), own container (start.sh). jsdom:
// #344 desktop: the properties on top, the comments (with the history and its switch) in their own area below, a separator
//      between them (role separator, aria-valuenow, ↑ ↓ Shift Home End, Enter / a double-click / the arrow in the head folds
//      the area); position + fold saved per user on the server and back after a reload; without comments the area stays
//      with "No comments yet."; without the comments module no split
// #1054 phone: no "Details | Comments" tabs, a small jump "To the comments" with the number next to the assignee; order and
//      history in a "…" of the comment head (no big switches); the assignee only once (the chip under the title, no select
//      under "More details"); the footer "Created by …" in the normal font
// Firefox (1440 mouse, 390 touch): dragging the line with the mouse (saved, back after a reload), folding, the panel's height
// split; #1050 an agent's file tile shows at least 8 characters of its name (1440 and 390); #1048 a Markdown table (file
// viewer and description) never breaks inside a word and scrolls sideways in its frame; tap targets of the jump and the "…".
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2310_b_ui', check, shots: 'P2310B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const key = (w, el, k, o = {}) => el && el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const V = B + 'api/v1';
const sett = async () => (await call('GET', '/api/state')).settings;
const FEAT = 'cal,comments,collab,agents';
const TABLE = ['| Kennzahl | Beschreibung des Werts im Bericht | C | Kommentar der Buchhaltung |', '|---|---|---|---|',
  '| Umsatz Q3 | Summe aller Rechnungen im Quartal ohne Steuern und Gebühren | wert 1 | geprüft und freigegeben durch die Abteilung |',
  '| Kosten | Personal, Miete, Lizenzen und Reisen zusammen | wert 22 | noch offen |'].join('\n');
const FNAME = 'bericht-wochenuebersicht.md';
// in the page: words of table cells that the browser broke over two lines (a Range over the word with two line boxes)
const BROKEN = sel => `(() => { const out = []; for (const c of document.querySelectorAll(${JSON.stringify(sel)})) {
  const tw = document.createTreeWalker(c, NodeFilter.SHOW_TEXT); let n;
  while ((n = tw.nextNode())) for (const m of n.data.matchAll(/\\S+/g)) { const r = document.createRange(); r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
    const ys = new Set([...r.getClientRects()].filter(x => x.width).map(x => Math.round(x.top))); if (ys.size > 1) out.push(m[0]); } }
  return {n: document.querySelectorAll(${JSON.stringify(sel)}).length, broken: out}; })()`;
// in the page: the name of the agent's file tile: its width against the width of its first 8 characters
const CHIP = `(() => { const a = [...document.querySelectorAll('#detail .attsec .att.file')].find(x => x.textContent.includes(${JSON.stringify(FNAME)})); if (!a) return null;
  const an = a.querySelector('.an'), n = an.firstChild, r = document.createRange(); r.setStart(n, 0); r.setEnd(n, 8);
  return {name: Math.round(an.getBoundingClientRect().width), eight: Math.round(r.getBoundingClientRect().width), tag: !!a.querySelector('.attag'), w: Math.round(a.getBoundingClientRect().width)}; })()`;

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments', 'attachments:read', 'attachments:write'], username: 'claude', display_name: 'Claude'});
  const AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Software'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  await call('PATCH', `/api/lists/${L}`, {agent_members: true, agent_peers: true});
  const T = (await call('POST', '/api/tasks', {title: 'Weekly report', list_id: L, content: 'Numbers of the week:\n\n' + TABLE})).id;
  for (const [b, ck] of [['First note', CK], ['Second note from Bob', BCK], ['Third note', CK]]) { await call('POST', `/api/tasks/${T}/comments`, {body: b}, ck); await sleep(300); }
  const fr = await fetch(`${V}/tasks/${T}/attachments/text`, {method: 'POST', headers: AGH, body: JSON.stringify({name: FNAME, content: '# Report\n\n' + TABLE + '\n'})});
  check(fr.ok, 'the agent stored its file ' + fr.status);
  const P = (await call('POST', '/api/lists', {name: 'Private'})).id;
  const TP = (await call('POST', '/api/tasks', {title: 'Call the bank', list_id: P})).id;

  // ================= #344 desktop split (jsdom: a mouse, wider than 899 px)
  let w = await boot({user: 'alice', hash: 't/' + T}), d = w.document;
  await until(() => d.querySelectorAll('#d-tl-items .cm').length === 3);
  let g = d.querySelector('#d-sgrip');
  check(d.querySelector('#detail.dsplit') && g && g.getAttribute('role') === 'separator' && g.getAttribute('aria-orientation') === 'horizontal' && g.tabIndex === 0, '#344: the split with a separator');
  check(g && g.getAttribute('aria-valuenow') === '60' && g.getAttribute('aria-valuemin') === '20' && g.getAttribute('aria-valuemax') === '85' && /60 % properties, 40 % comments/.test(g.getAttribute('aria-valuetext')), '#344: the separator says its value (60 %) ' + g?.getAttribute('aria-valuetext'));
  check(d.querySelector('#detail > #d-cpane #d-tl') && !d.querySelector('#detail .dbody #d-tl') && d.querySelector('#detail .dbody + #d-sgrip + #d-cpane + .dbot'), '#344: properties | line | comments | the box, in this order');
  check(d.querySelector('#detail > .dbot .dcomp #c-input'), '#344: the comment box stays fixed at the bottom');
  check(d.querySelectorAll('#d-cpane .actl').length >= 1 && /Comments/.test(d.querySelector('#d-cpane .cmhead').textContent), '#344: the history comes along in the comments area');
  check(w.getComputedStyle(d.querySelector('#detail')).getPropertyValue('--dsT').trim() === '60', '#344: the share as a CSS value');
  const fb = d.querySelector('#d-tl .cmhead .dsfoldb');
  check(fb && fb.getAttribute('aria-expanded') === 'true' && fb.getAttribute('aria-label') === 'Fold the comments', '#344: the fold arrow in the head');
  check(!d.querySelector('#detail .djump') && !d.querySelector('#detail .dtabs'), '#344: no jump and no tabs on the desktop');
  // keyboard
  key(w, g, 'ArrowDown'); await sleep(50);
  check(g.getAttribute('aria-valuenow') === '65', '#344: ↓ moves the line down by 5 %');
  key(w, g, 'ArrowUp', {shiftKey: true}); await sleep(50);
  check(g.getAttribute('aria-valuenow') === '55', '#344: Shift+↑ by 10 %');
  key(w, g, 'Home'); await sleep(50);
  const vHome = g.getAttribute('aria-valuenow');
  key(w, g, 'End'); await sleep(50);
  const vEnd = g.getAttribute('aria-valuenow');
  check(vHome === '20' && vEnd === '85', '#344: Home / End = the smallest / largest share ' + vHome + ' ' + vEnd);
  for (let i = 0; i < 3; i++) key(w, g, 'ArrowUp');
  await sleep(900);
  let s = await sett();
  check(g.getAttribute('aria-valuenow') === '70' && s.detail_split === '70' && s.detail_cm_fold === '0', '#344: saved for the user on the server (70) ' + s.detail_split);
  key(w, g, 'Enter'); await sleep(900);
  s = await sett();
  check(d.querySelector('#detail.dsfold') && s.detail_cm_fold === '1' && d.querySelector('#d-tl .dsfoldb')?.getAttribute('aria-expanded') === 'false' && /folded/.test(d.querySelector('#d-sgrip').getAttribute('aria-valuetext')), '#344: Enter folds the comments area (saved) ' + JSON.stringify([d.querySelector('#detail').className, s.detail_cm_fold, d.querySelector('#d-tl .dsfoldb')?.getAttribute('aria-expanded'), d.querySelector('#d-sgrip')?.getAttribute('aria-valuetext')]));
  w.close();
  w = await boot({user: 'alice', hash: 't/' + T}); d = w.document;
  await until(() => d.querySelector('#d-sgrip'));
  g = d.querySelector('#d-sgrip');
  check(d.querySelector('#detail.dsplit.dsfold') && g.getAttribute('aria-valuenow') === '70', '#344: after a reload: still folded, the line at 70 %');
  click(w, d.querySelector('#d-tl .dsfoldb')); await sleep(900);
  check(!d.querySelector('#detail.dsfold') && (await sett()).detail_cm_fold === '0', '#344: the arrow unfolds it again');
  g.dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true})); await sleep(80);
  check(d.querySelector('#detail.dsfold'), '#344: a double-click on the line folds');
  key(w, g, 'ArrowDown'); await sleep(80);
  check(!d.querySelector('#detail.dsfold') && g.getAttribute('aria-valuenow') === '75', '#344: moving the line unfolds it');
  // the reply button of a push focuses the box and opens a folded area
  g.dispatchEvent(new w.MouseEvent('dblclick', {bubbles: true})); await sleep(80);
  w.eval(`replyFocus(${T})`); await sleep(200);
  check(!d.querySelector('#detail.dsfold') && d.activeElement?.id === 'c-input', '#344: "Reply" opens a folded area and focuses the box');
  // order + history in the "…"
  check(!d.querySelector('#d-tl .cmtoggle') && d.querySelector('#d-tl [data-act="tl-menu"]')?.getAttribute('aria-haspopup') === 'menu', '#1054: no big switches, a "…" in the head');
  click(w, d.querySelector('#d-tl [data-act="tl-menu"]')); await sleep(80);
  let mi = [...d.querySelectorAll('#pop [role="menuitem"]')];
  check(mi.length === 3 && mi[0].classList.contains('mtlold') && mi[0].classList.contains('on') && mi[1].classList.contains('mtlnew') && mi[2].classList.contains('mtlact') && mi[2].classList.contains('on'), '#1054: "…": Oldest first (checked), Newest first, With activity (checked) ' + mi.map(x => x.textContent).join('|'));
  click(w, mi[2]); await sleep(150);
  check(d.querySelectorAll('#d-cpane .actl').length === 0 && /Comments only/.test(d.querySelector('#d-tl .cmhead .cmmode')?.textContent || '') && d.querySelector('#detail.dsplit'), '#344: "Comments only" in the comments area, the head says so');
  click(w, d.querySelector('#d-tl [data-act="tl-menu"]')); await sleep(80);
  click(w, d.querySelector('#pop .mtlact')); await sleep(150);
  check(d.querySelectorAll('#d-cpane .actl').length >= 1 && !d.querySelector('#d-tl .cmmode'), '#344: with the history again');
  // the assignee once
  check(d.querySelector('#detail .dmeta .dwho') && !d.querySelector('#detail #d-assignee') && !d.querySelector('#detail select[data-sheet-av]'), '#1054: the assignee only as the chip under the title');
  click(w, d.querySelector('#detail .dmeta .dwho')); await sleep(100);
  const am = [...d.querySelectorAll('#pop [role="menuitem"]')].map(x => x.textContent);
  check(am.some(x => /Nobody/.test(x)) && am.some(x => /Bob Baker/.test(x)) && am.some(x => /Claude/.test(x)), '#1054: its menu: nobody, people and the agent ' + am.join('|'));
  w.eval('closePop()');
  w.close();
  // a private task without comments: the area stays with a hint; the comments module off: no split
  w = await boot({user: 'alice', hash: 't/' + TP}); d = w.document;
  await until(() => d.querySelector('#d-cpane .cmempty'));
  check(d.querySelector('#detail.dsplit #d-cpane .cmempty')?.textContent === 'No comments yet.' && d.querySelector('#detail .dbot #c-input'), '#344: without comments: the area says "No comments yet.", the box below');
  w.close();
  await call('PATCH', '/api/settings', {features: 'cal,collab,agents'});
  w = await boot({user: 'alice', hash: 't/' + T}); d = w.document;
  await until(() => d.querySelector('#d-title'));
  check(!d.querySelector('#detail.dsplit') && !d.querySelector('#d-sgrip') && !d.querySelector('#d-cpane'), '#344: comments module off: no split');
  w.close();
  await call('PATCH', '/api/settings', {features: FEAT, detail_split: 60, detail_cm_fold: '0'});

  // ================= #1054 phone
  w = await boot({user: 'alice', hash: 't/' + T, mobile: true}); d = w.document;
  await until(() => d.querySelectorAll('#d-tl-items .cm').length === 3);
  const jump = d.querySelector('#detail .dmeta .djump');
  check(!d.querySelector('#detail.dsplit') && !d.querySelector('#detail .dtabs') && !d.querySelector('#detail .dbody.dtab-c'), '#1054: phone: no split, no tabs');
  check(jump && jump.dataset.act === 'd-jump-cm' && /To the comments/.test(jump.textContent) && d.querySelector('#d-jump-count').textContent === '3', '#1054: the jump "To the comments 3" next to the assignee');
  check(d.querySelector('#detail .dbody #d-tl') && d.querySelector('#detail .dbot .dcomp #c-input'), '#1054: the comments stay below in the stream (#322), the box at the bottom');
  let jumped = null; d.querySelector('#d-tl').scrollIntoView = o => { jumped = o; };
  click(w, jump); await sleep(50);
  check(jumped && jumped.block === 'start', '#1054: the jump scrolls to the comments');
  await call('POST', `/api/tasks/${T}/comments`, {body: 'Fourth note'}, BCK);
  await w.eval(`loadTimeline(${T})`); await sleep(300);
  check(d.querySelector('#d-jump-count').textContent === '4', '#1054: the number follows new comments');
  check(!d.querySelector('#d-tl .cmtoggle') && d.querySelector('#d-tl [data-act="tl-menu"]'), '#1054: phone: the "…" instead of the switches');
  click(w, d.querySelector('#d-tl [data-act="tl-menu"]')); await sleep(80);
  click(w, d.querySelector('#pop .mtlnew')); await sleep(900);
  check((await sett()).comment_order === 'new' && d.querySelector('#d-tl .dctop #c-input'), '#1054: "Newest first" from the "…" (saved, the box on top)');
  click(w, d.querySelector('#d-tl [data-act="tl-menu"]')); await sleep(80);
  click(w, d.querySelector('#pop .mtlold')); await sleep(900);
  check((await sett()).comment_order === 'old', '#1054: back to "Oldest first"');
  check(!d.querySelector('#detail #d-assignee') && d.querySelectorAll('#detail .dwho').length === 1, '#1054: phone: the assignee once');
  check(d.querySelector('#detail .dfoot .dfc') && /Created by Alice/.test(d.querySelector('#detail .dfoot .dfc').textContent), 'the footer "Created by …"');
  w.close();
  // a private task without comments on the phone: only the box (no area, no jump)
  w = await boot({user: 'alice', hash: 't/' + TP, mobile: true}); d = w.document;
  await until(() => d.querySelector('#d-title')); await sleep(500);
  check(!d.querySelector('#detail #d-tl') && !d.querySelector('#detail .djump') && d.querySelector('#detail .dbot #c-input'), '#1054: phone, no comments: no jump, only the box');
  w.close();

  // ================= CSS
  const css = await (await fetch(B + 'static/app.css')).text();
  check(/\.dfoot \.dfc\{font-family:var\(--sans\)\}/.test(css), '#1054: the footer in the normal font');
  check(/\.mdtbl th,\.mdtbl td\{word-break:normal;overflow-wrap:normal/.test(css) && /\.mdtbl\{overflow-x:auto/.test(css), '#1048: table cells never break inside a word, the frame scrolls (everywhere)');
  check(/\.att \.atxt\{[^}]*flex:1 1 auto;min-width:8ch/.test(css), '#1050: the name has priority in the tile');

  // ================= Firefox
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const waitFor = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const open = async (o, id) => { await o.nav(B + '#t/' + id); await waitFor(o.ev, `!!document.querySelector('#detail #d-title') && !!document.querySelector('#d-tl-items .cm')`); await sleep(800); };
  const geo = `(() => { const r = s => document.querySelector(s)?.getBoundingClientRect(); const b = r('#detail .dbody'), p = r('#d-cpane'), g = r('#d-sgrip');
    return {body: b && Math.round(b.height), pane: p && Math.round(p.height), gy: g && Math.round(g.top + g.height / 2), gx: g && Math.round(g.left + g.width / 2), v: document.querySelector('#d-sgrip')?.getAttribute('aria-valuenow'),
      fold: !!document.querySelector('#detail.dsfold'), doc: document.documentElement.scrollWidth - innerWidth}; })()`;

  await firefox(async o => {
    const {cmd, ev, ctx, shot, drag} = o;
    check(await ffLogin(o) === 200, '1440: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await open(o, T);
    let m = await ev(geo);
    check(m.v === '60' && m.body > 0 && m.pane > 0 && Math.abs(m.body / (m.body + m.pane) * 100 - 60) < 4, '1440: #344 the panel split 60 / 40 ' + JSON.stringify(m));
    check(await ev(`(() => { const p = document.querySelector('#d-cpane'); return p.scrollHeight <= p.clientHeight + 2 || p.scrollTop > 0; })()`), '1440: #344 the comments area starts at the newest comment');
    // nothing in the properties overlaps the next block (the scroll area must not squeeze its children)
    const ovl = await ev(`(() => { const k = [...document.querySelectorAll('#detail .dbody > *')].filter(e => e.getBoundingClientRect().height); const bad = [];
      for (let i = 1; i < k.length; i++) { const a = k[i - 1], b = k[i]; if (a.scrollHeight > a.clientHeight + 2 && getComputedStyle(a).overflowY === 'visible' || a.getBoundingClientRect().bottom > b.getBoundingClientRect().top + 1) bad.push((a.id || a.className) + '>' + (b.id || b.className)); }
      return bad; })()`);
    check(!ovl.length, '1440: #344 the properties do not overlap each other ' + JSON.stringify(ovl));
    await shot('p2310b-1440-split.png');
    await drag(m.gx, m.gy, 0, -150);
    await sleep(900);
    const m2 = await ev(geo), s2 = await sett();
    check(+m2.v < 60 && +m2.v >= 20 && s2.detail_split === m2.v && !m2.fold, '1440: #344 dragging the line up with the mouse (saved) ' + JSON.stringify([m2.v, s2.detail_split]));
    check(Math.abs(m2.body / (m2.body + m2.pane) * 100 - +m2.v) < 4, '1440: #344 the heights follow ' + JSON.stringify(m2));
    await open(o, T);
    const m3 = await ev(geo);
    check(m3.v === m2.v && Math.abs(m3.body - m2.body) < 6, '1440: #344 after a reload the line is where it was ' + JSON.stringify([m2, m3]));
    await ev(`(() => { const g = document.querySelector('#d-sgrip'); g.focus(); g.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true, cancelable: true})); return 1; })()`); await sleep(900);
    const m4 = await ev(geo);
    check(m4.fold && m4.pane < 64 && m4.body > m3.body + 100 && (await sett()).detail_cm_fold === '1', '1440: #344 folded: only the head of the comments area ' + JSON.stringify(m4));
    await shot('p2310b-1440-folded.png');
    await open(o, T);
    check((await ev(geo)).fold, '1440: #344 still folded after a reload');
    await ev(`(() => { document.querySelector('#d-tl .dsfoldb').click(); return 1; })()`); await sleep(900);
    check(!(await ev(geo)).fold && (await sett()).detail_cm_fold === '0', '1440: #344 the arrow unfolds');
    check(await ev(`(() => { const f = getComputedStyle(document.querySelector('#detail .dfoot .dfc')).fontFamily, mono = getComputedStyle(document.documentElement).getPropertyValue('--mono'); return !!f && !f.includes(mono.split(',')[0].trim()) && !/mono/i.test(f); })()`), '1440: #1054 "Created by …" not in the monospace font');
    // #1050 the tile
    await ev(`(() => { const d = document.querySelector('#detail .dbody'); d.querySelector('.attsec')?.scrollIntoView({block: 'center'}); return 1; })()`); await sleep(300);
    const c1 = await ev(CHIP);
    check(c1 && c1.tag && c1.name >= c1.eight, '1440: #1050 the agent\'s tile shows at least 8 characters of its name ' + JSON.stringify(c1));
    await shot('p2310b-1440-chip.png');
    // #1048 the description's table
    const t1 = await ev(BROKEN('#d-md table th, #d-md table td'));
    check(t1.n === 12 && !t1.broken.length, '1440: #1048 the description\'s table: no word broken ' + JSON.stringify(t1));
    check(await ev(`!!document.querySelector('#d-cpane .cmhead [data-act="tl-menu"]') && !document.querySelector('#d-cpane .cmtoggle')`), '1440: #1054 the "…" in the head');
  }, false);

  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, '390: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await open(o, T);
    check(await ev(`!document.querySelector('#detail.dsplit') && !document.querySelector('#detail .dtabs') && !document.querySelector('#d-sgrip')`), '390: #1054 no tabs, no split');
    const jr = await ev(`(() => { const r = document.querySelector('#detail .dmeta .djump')?.getBoundingClientRect(); return r && {w: Math.round(r.width), h: Math.round(r.height), right: Math.round(r.right), vw: innerWidth}; })()`);
    check(jr && jr.h >= 24 && jr.w >= 24 && jr.right <= jr.vw, '390: #1054 the jump is a tap target of 24 px at least, on the screen ' + JSON.stringify(jr));
    await shot('p2310b-390-detail.png');
    const mr = await ev(`(() => { const r = document.querySelector('#d-tl [data-act="tl-menu"]').getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height)}; })()`);
    check(mr.w >= 24 && mr.h >= 24, '390: #1054 the "…" of the comment head ' + JSON.stringify(mr));
    await ev(`(() => { document.querySelector('#detail .djump').click(); return 1; })()`); await sleep(700);
    check(await ev(`(() => { const r = document.querySelector('#d-tl').getBoundingClientRect(); const h = document.querySelector('#detail .dtop').getBoundingClientRect(); return r.top >= Math.round(h.bottom) - 1 && r.top < innerHeight / 2; })()`), '390: #1054 the jump brings the comments up, below the panel header (2.31.1)');
    await ev(`(() => { document.querySelector('#d-tl [data-act="tl-menu"]').click(); return 1; })()`); await sleep(400);
    check(await ev(`(() => { const p = document.querySelector('#pop'); const r = p.getBoundingClientRect(); return !p.classList.contains('hidden') && r.left >= 0 && r.right <= innerWidth + 1 && !!p.querySelector('.mtlact'); })()`), '390: #1054 the "…" menu opens on the screen');
    await shot('p2310b-390-comments.png');
    await ev(`(() => { closePop(); return 1; })()`); await sleep(200);
    // #1050 the tile at 390
    await ev(`(() => { document.querySelector('#detail .attsec')?.scrollIntoView({block: 'center'}); return 1; })()`); await sleep(300);
    const c2 = await ev(CHIP);
    check(c2 && c2.tag && c2.name >= c2.eight, '390: #1050 the agent\'s tile shows at least 8 characters of its name ' + JSON.stringify(c2));
    // #1048 the description's table and the file viewer
    const t2 = await ev(BROKEN('#d-md table th, #d-md table td'));
    check(t2.n === 12 && !t2.broken.length, '390: #1048 the description\'s table: no word broken ' + JSON.stringify(t2));
    check(await ev(`(() => { const f = document.querySelector('#d-md .mdtbl'); return getComputedStyle(f).overflowX === 'auto' && f.scrollWidth > f.clientWidth && document.documentElement.scrollWidth <= innerWidth; })()`), '390: #1048 the table scrolls sideways in its frame, the page does not');
    await ev(`(() => { const a = [...document.querySelectorAll('#detail .attsec a[data-tview]')].find(x => x.title === ${JSON.stringify(FNAME)}); a.click(); return 1; })()`);
    check(await waitFor(ev, `!!document.querySelector('.tview .tvmd table td')`), '390: the viewer opens the file formatted');
    await sleep(400);
    const t3 = await ev(BROKEN('.tview .tvmd table th, .tview .tvmd table td'));
    check(t3.n === 12 && !t3.broken.length, '390: #1048 the viewer\'s table: no word broken ("wert 1" stays whole) ' + JSON.stringify(t3));
    const w1 = await ev(`(() => { const f = document.querySelector('.tview .mdtbl'); const c = [...f.querySelectorAll('td')].find(x => x.textContent === 'wert 1'); const r = document.createRange(); r.selectNodeContents(c);
      return {lines: new Set([...r.getClientRects()].filter(x => x.width).map(x => Math.round(x.top))).size, ox: getComputedStyle(f).overflowX, fw: f.getBoundingClientRect().right <= innerWidth + 1, page: document.documentElement.scrollWidth <= innerWidth}; })()`);
    check(w1.lines === 1 && w1.ox === 'auto' && w1.fw && w1.page, '390: #1048 the short cell "wert 1" stays on one line, a wide table scrolls in its frame, not the page ' + JSON.stringify(w1));
    await shot('p2310b-390-table.png');
  }, true);

  console.log(`p2310_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
