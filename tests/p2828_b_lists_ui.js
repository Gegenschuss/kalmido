// kalmido-suite: fresh
// 2.828.0 B (#5446, #5443) UI test, own container (start.sh), Firefox. Invented data only.
// #5446: the list rows, check marks and the detail have their rules in static/css/start-00-lists.css (no visible change): the
// row and the check mark still look as before (size / shape per place), the focus frame of the title edited in the row is
// visible (outline-style not none), a pop-up (.tdmove) lies below a dialog (z-index scale).
// #5443: the view switch has one form on every width (the active view with its name, the others as icons with their name in
// the tooltip / aria-label), 44 px high on a finger device; switching to another view and back shows the list again; the
// column strip on a phone does not cut a name in the middle (it scrolls with a hint at its edge); the project name wins over
// the icons (full name as title).
// P2828B_SHOTS=<dir>: screenshots + style-<place>.json (the computed styles of the rows / check marks / detail, to compare a
// stylesheet move before / after: tools nothing, a diff of two runs).
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2828_b_lists_ui', check, shots: 'P2828B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const SHOTS = process.env.P2828B_SHOTS || '';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

// the computed styles of the rows, check marks and the detail (with ::before / ::after), keyed by their place in the tree
const DUMP = `(() => { const out = {}, seen = new Set();
  const key = e => { const p = []; for (let x = e; x && x !== document.body; x = x.parentElement) p.unshift(x.id ? '#' + x.id : x.tagName.toLowerCase() + ':' + [...x.parentElement.children].indexOf(x)); return p.join('>'); };
  const css = (e, pe) => { const cs = getComputedStyle(e, pe), o = {}; for (let i = 0; i < cs.length; i++) { const n = cs[i]; if (/^transition|^animation/.test(n)) continue; o[n] = cs.getPropertyValue(n); } return o; };
  const add = e => { if (seen.has(e) || seen.size > 900) return; seen.add(e); const k = key(e); out[k] = {cls: String(e.className?.baseVal ?? e.className), s: css(e)};
    for (const pe of ['::before', '::after']) { const c = getComputedStyle(e, pe).content; if (c && c !== 'none') out[k + pe] = {s: css(e, pe)}; } };
  for (const e of document.querySelectorAll('#view .trow, #view .trow *, .chk, .chk *, #detail, #detail *, .vsegm, .vsegm *, .lcbar, .lcbar *, .lhead, .lhead *')) add(e);
  return JSON.stringify(out); })()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'kanban', 'timeline']});
  const st = await call(CA, 'GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean));
  ['cal', 'comments', 'kanban', 'timeline', 'matrix'].forEach(x => feats.add(x));
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(','), show_done_default: '1', show_done_new: '0'});
  const NAME = 'Abnahme-Workshop mit der Geschäftsführung und dem ganzen Team im Frühjahr';
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Imagefilm Stadtwerke'})).id, L2 = (await call(CA, 'POST', '/api/lists', {name: NAME})).id;
  const mk = async b => (await call(CA, 'POST', '/api/tasks', {list_id: L, ...b})).id;
  const T = [];
  T.push(await mk({title: 'Book the flights', due: day(3), due_time: '14:30', priority: 5}));
  T.push(await mk({title: 'Call the printer about the posters', due: day(0), priority: 3}));
  T.push(await mk({title: 'Write the quarterly report for the board with all the numbers of the last three months', priority: 1}));
  T.push(await mk({title: 'Plan the kick-off', priority: 7}));
  T.push(await mk({title: 'Milestone: first cut', due: day(10), ms: true}));
  T.push(await mk({title: 'Sub step', parent_id: T[0]}));
  const done = await mk({title: 'Old thing done'}), wont = await mk({title: 'Dropped idea'});
  const pd = await call(CA, 'POST', `/api/tasks/${done}/complete`, {status: 2}), pw = await call(CA, 'POST', `/api/tasks/${wont}/complete`, {status: -1});
  check(pd.http < 300 && pw.http < 300, 'a done and a dropped task ' + JSON.stringify([pd.http, pd.error, pw.http, pw.error]));
  T.push(done, wont);
  const T2 = (await call(CA, 'POST', '/api/tasks', {list_id: L2, title: 'Agenda for the workshop'})).id;

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const dump = async (ev, name) => {
    if (!SHOTS) return;
    // a real state: no row is still moving in (the entry animation's class is gone) and no request is open
    await ready(ev, `!document.querySelector('.an-rowin, .an-out') && (!window.__net || window.__net.n === 0)`, 40);
    fs.writeFileSync(path.join(SHOTS, `style-${name}.json`), await ev(DUMP));
  };
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(x => x.status)`);
  };
  const ROWS = `document.querySelectorAll('#view .trow[data-id]').length >= 6`;

  // #5443: the view switch - its buttons (header on a computer / tablet, the bar under the title on a phone), what each shows
  const SW = `(() => { const s = document.querySelector('#top .vseg.ttabs') || document.querySelector('#view .vsegm'); if (!s) return null;
    return [...s.querySelectorAll('button')].map(b => { const r = b.getBoundingClientRect(), t = b.querySelector('.vtl, span'), tr = t && t.getBoundingClientRect(), i = b.querySelector('svg'), ir = i && i.getBoundingClientRect();
      return {act: b.dataset.act, on: b.classList.contains('on'), shown: r.width > 0, h: r.height, name: tr && tr.width > 0 ? t.textContent.trim() : '', icon: !!ir && ir.width > 0, label: b.getAttribute('aria-label') || '', title: b.title}; }); })()`;
  const viewSwitch = async (o, tag) => {
    const {ev} = o;
    const b = await ev(SW);
    check(b && b.length >= 5, `${tag}: #5443 the view switch is there ` + JSON.stringify(b));
    if (!b) return;
    const on = b.filter(x => x.on), off = b.filter(x => !x.on && x.shown);
    check(on.length === 1 && on[0].shown && on[0].icon && on[0].name === 'List', `${tag}: #5443 the active view with its symbol and name ` + JSON.stringify(on));
    check(off.length >= 4 && off.every(x => x.icon && !x.name && x.label && x.title === x.label), `${tag}: #5443 the other views as symbols, their name as tooltip and aria-label ` + JSON.stringify(off));
    if (tag !== 'desk') check(b.filter(x => x.shown).every(x => x.h >= 43.5), `${tag}: #5443 44 px high on a finger device ` + JSON.stringify(b.map(x => x.h)));
    // to another view and back: the board shows, then the rows again (a real click on the button)
    await ev(`(() => { (document.querySelector('#top .vseg.ttabs') || document.querySelector('#view .vsegm')).querySelector('[data-act="view-kanban"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#view .kanban .trow, #view .kcards .trow') && /Kanban/.test((document.querySelector('#top .vseg.ttabs button.on, #view .vsegm button.on') || {}).textContent || '')`),
      `${tag}: #5443 a click on Kanban shows the board with the tasks, Kanban named as the active view`);
    const k = await ev(SW);
    check(k && k.filter(x => x.on && x.name === 'Kanban').length === 1 && k.find(x => x.act === 'view-list' && !x.name && x.icon), `${tag}: #5443 the switch keeps its form on the board ` + JSON.stringify(k));
    await ev(`(() => { (document.querySelector('#top .vseg.ttabs') || document.querySelector('#view .vsegm')).querySelector('[data-act="view-list"]').click(); return 1; })()`);
    check(await ready(ev, `${ROWS} && !document.querySelector('#view .kanban')`), `${tag}: #5443 back to the list: the rows are there again`);
  };
  // #5443: the column strip of a phone does not end in a cut name without a hint: either everything fits, or the edge with more
  // names fades out (class fr + a mask), and at the end of the strip the other edge does
  const strip = async (o, tag) => {
    const {ev} = o;
    const st = `(() => { const s = document.querySelector('#view .lcbar .lcbs'); if (!s || !s.offsetWidth) return null; const r = s.getBoundingClientRect(), cs = getComputedStyle(s);
      return {sw: s.scrollWidth, cw: s.clientWidth, sl: s.scrollLeft, fr: s.classList.contains('fr'), fl: s.classList.contains('fl'), mask: cs.maskImage || cs.webkitMaskImage || 'none',
        inside: [...s.children].every(b => { const x = b.getBoundingClientRect(); return x.left >= r.left - 1 && x.right <= r.right + 1; })}; })()`;
    check(await ready(ev, `(${st}) !== null`, 40), `${tag}: #5443 the column strip is there`);
    await ready(ev, `(s => !s || s.sw <= s.cw + 1 || s.fr)(${st})`, 20);
    let a = await ev(st);
    if (a && a.sw > a.cw + 1) {
      check(a.fr && !a.fl && a.mask !== 'none', `${tag}: #5443 more names to the right: that edge fades out ` + JSON.stringify(a));
      await ev(`(() => { const s = document.querySelector('#view .lcbar .lcbs'); s.scrollLeft = s.scrollWidth; s.dispatchEvent(new Event('scroll')); return 1; })()`);
      check(await ready(ev, `(s => s && s.fl && !s.fr)(${st})`, 20), `${tag}: #5443 at the end of the strip the left edge fades, the right one not ` + JSON.stringify(await ev(st)));
      await ev(`(() => { const s = document.querySelector('#view .lcbar .lcbs'); s.scrollLeft = 0; s.dispatchEvent(new Event('scroll')); return 1; })()`);
    } else check(a && a.inside && !a.fr && !a.fl, `${tag}: #5443 every name of the strip fits whole ` + JSON.stringify(a));
  };
  // #5446: the title edited in the row keeps a visible focus frame (it was outline:0!important)
  const editFrame = async (o, tag) => {
    const {ev} = o;
    await ev(`(() => { inlineEditStart(${T[1]}); return 1; })()`);
    check(await ready(ev, `document.activeElement && document.activeElement.matches('.trow .ttlin')`, 20), `${tag}: #5446 the title field in the row has the focus`);
    await o.cmd('browsingContext.activate', {context: o.ctx}).catch(() => 0);
    const f = await ev(`(() => { const i = document.querySelector('.trow .ttlin'), cs = getComputedStyle(i), row = i.closest('.trow');
      // a headless window that never got the system focus matches no :focus: then the frame is read from the field's own rule
      const rule = [...document.styleSheets].flatMap(sh => { try { return [...sh.cssRules]; } catch { return []; } }).filter(r => r.selectorText && r.selectorText.split(',').some(x => x.trim() === '.trow .ttlin:focus')).pop();
      return {focus: i.matches(':focus'), style: cs.outlineStyle, w: parseFloat(cs.outlineWidth), rule: rule ? rule.style.getPropertyValue('outline') : null, row: getComputedStyle(row).outlineStyle + ' ' + getComputedStyle(row).getPropertyPriority?.('outline')}; })()`);
    check(f && (f.focus ? f.style !== 'none' && f.w >= 2 : /^2px solid /.test(f.rule || '')), `${tag}: #5446 a visible focus frame while editing in the row ` + JSON.stringify(f));
    await o.shot(`p2828b-${tag}-edit.png`);
    await ev(`(() => { document.querySelector('.trow .ttlin').dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true})); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.ttlin')`, 20), `${tag}: #5446 Esc ends the editing`);
  };
  // #5446: the check marks look as before: a circle of .875rem in the row, the milestone a diamond (square turned), and the hint
  // "Move to project" of a drag lies below a dialog (z-index scale)
  const marks = async (o, tag) => {
    const m = await o.ev(`(() => { const c = sel => { const e = document.querySelector(sel); if (!e) return null; const cs = getComputedStyle(e); return {r: cs.borderTopLeftRadius, w: Math.round(e.getBoundingClientRect().width * 10) / 10, t: cs.transform}; };
      const z = cls => { const e = document.createElement('div'); e.className = cls; document.body.appendChild(e); const v = +getComputedStyle(e).zIndex; e.remove(); return v; };
      return {open: c('#view .trow[data-id="${T[1]}"] .chk'), ms: c('#view .trow[data-id="${T[4]}"] .chk'), rem: parseFloat(getComputedStyle(document.documentElement).fontSize), move: z('tdmove'), dialog: z('modal'), toast: (() => { const t = document.querySelector('#toast'); return t ? +getComputedStyle(t).zIndex : null; })()}; })()`);
    check(m && m.open && m.open.r === '50%' && Math.abs(m.open.w - .875 * m.rem) < 1.5, `${tag}: #5446 the check mark is the circle of .875rem ` + JSON.stringify(m));
    check(m && m.ms && m.ms.r === '2px' && m.ms.t !== 'none', `${tag}: #5446 the milestone keeps its diamond ` + JSON.stringify(m && m.ms));
    check(m && m.move > 0 && m.move < m.dialog && (m.toast == null || m.dialog < m.toast), `${tag}: #5446 the drag hint lies below dialogs, dialogs below toasts ` + JSON.stringify(m));
  };
  // #5443: the project name before the symbols: with the detail open the header is narrow; when the whole name does not fit
  // the switch shows only the active view (its name, a click opens the others) before the name is cut; the full name as title
  const titleFirst = async (o, tag) => {
    const {ev} = o;
    const h = await ev(`(() => { const t = document.querySelector('#top'), h1 = t.querySelector('h1'), ht = t.querySelector('h1 .ht'); return {tvc: t.classList.contains('tvc'), cut: ht.scrollWidth > ht.clientWidth + 1, title: h1.title, vis: [...t.querySelectorAll('.vseg.ttabs button')].filter(b => b.getBoundingClientRect().width > 0).map(b => b.dataset.act)}; })()`);
    check(h && h.title === NAME, `${tag}: #5443 the header keeps the full project name as its title ` + JSON.stringify(h));
    check(h && h.cut && h.tvc, `${tag}: #5443 the long name is only cut after the switch gave way ` + JSON.stringify(h));
    if (h && h.tvc) {
      check(h.vis.length === 1 && h.vis[0] === 'view-list', `${tag}: #5443 the narrow switch shows the active view only ` + JSON.stringify(h));
      await ev(`(() => { document.querySelector('#top .vseg.ttabs button.on').click(); return 1; })()`);
      check(await ready(ev, `[...document.querySelectorAll('#pop [role="menuitem"]')].some(b => /Kanban/.test(b.textContent))`, 20), `${tag}: #5443 a click on it lists the other views`);
      await ev(`(() => { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); return 1; })()`);
    }
    await o.shot(`p2828b-${tag}-detail-head.png`);
  };

  for (const [wd, ht, tag, touch] of [[1280, 800, 'desk', false], [360, 740, 'phone', true], [1366, 1024, 'tablet', true]]) {
    await firefox(async o => {
      const {cmd, ev, ctx, nav} = o;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
      check(await ffLogin(o) === 200, `${tag}: login`);
      await nav(B + '#l/' + L);
      check(await ready(ev, ROWS), `${tag}: the list shows its rows`);
      await dump(ev, `${tag}-list`);
      await o.shot(`p2828b-${tag}-list.png`);
      await marks(o, tag);
      await viewSwitch(o, tag);
      if (tag === 'phone') await strip(o, tag);
      if (tag === 'desk') await editFrame(o, tag);
      await ev(`(() => { openDetail(${T[0]}); return 1; })()`);
      check(await ready(ev, `!!document.querySelector('#detail .dtop')`), `${tag}: the detail opens`);
      if (tag === 'desk') {
        // the short name fits whole beside the whole switch even with the detail open (it was cut beside 7 symbols)
        // a real state: the header measured itself again after the detail slid in (whole name, or the switch gave way)
        await ready(ev, `(t => !!t.querySelector('h1 .ht') && (t.classList.contains('tvc') || t.querySelector('h1 .ht').scrollWidth <= t.querySelector('h1 .ht').clientWidth + 1))(document.querySelector('#top'))`, 20);
        const sh = await ev(`(() => { const t = document.querySelector('#top'), ht = t.querySelector('h1 .ht'); return {cut: ht.scrollWidth > ht.clientWidth + 1, text: ht.textContent, cls: t.className}; })()`);
        check(sh && !sh.cut && sh.text === 'Imagefilm Stadtwerke', `${tag}: #5443 the short project name stays whole with the detail open ` + JSON.stringify(sh));
        await ev(`(() => { closeDetail(); return 1; })()`);
        await nav(B + '#l/' + L2);
        check(await ready(ev, `!!document.querySelector('#view .trow[data-id="${T2}"]')`), `${tag}: the list with the long name`);
        await ev(`(() => { openDetail(${T2}); return 1; })()`);
        check(await ready(ev, `!!document.querySelector('#detail .dtop') && !!document.querySelector('#top h1 .ht')`), `${tag}: its detail opens`);
        await titleFirst(o, tag);
        await ev(`(() => { closeDetail(); return 1; })()`);
        await nav(B + '#l/' + L);
        check(await ready(ev, ROWS), `${tag}: back in the first list`);
        await ev(`(() => { openDetail(${T[0]}); return 1; })()`);
        await ready(ev, `!!document.querySelector('#detail .dtop')`);
      }
      await dump(ev, `${tag}-detail`);
      await o.shot(`p2828b-${tag}-detail.png`);
      await ev(`(() => { closeDetail(); return 1; })()`);
      await ready(ev, `!document.querySelector('#detail .dtop')`, 20);
      // the selection: rows marked, check marks in their selection colour
      await ev(`(() => { S.multiMode = true; S.multi.add(${T[1]}); S.multi.add(${T[2]}); render(); renderMultiBar(); return 1; })()`);
      await ready(ev, `!!document.querySelector('#view .trow.msel')`, 20);
      await dump(ev, `${tag}-multi`);
      await ev(`(() => { S.multiMode = false; S.multi.clear(); render(); renderMultiBar(); return 1; })()`);
      // the dark theme
      await ev(`(() => { localStorage.setItem('tasks.theme', '"dark"'); window.__old = 1; location.reload(); return 1; })()`).catch(() => 0);
      check(await ready(ev, `!window.__old && typeof S !== 'undefined' && !!S.me && ${ROWS}`), `${tag}: reloaded in the dark theme`);
      await dump(ev, `${tag}-dark`);
      await o.shot(`p2828b-${tag}-dark.png`);
    }, touch);
  }

  console.log(`p2828_b_lists_ui: ${ok} ok, ${F.length} failed`);
  if (F.length) { console.log(F.join('\n')); process.exit(1); }
  process.exit(0);
})().catch(e => { console.error(e); process.exit(1); });
