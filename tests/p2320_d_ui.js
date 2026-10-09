// 2.32.0 UI tests (agent D: dialogs and small things), own container (start.sh). jsdom:
// #1077 the personal switch "Suggest icons for new lists" (Settings > Appearance, on by default, stored on the server, only
//       0 / 1): on = "Holiday" suggests an icon in the new list dialog, off = the neutral list icon, picking one still works
// #1058 Share dialog: people open, the parts below (agents, public link, owner) fold with a short state in the folded line;
//       opened from "Agent…" the agents part is open; the agent switches explain behind the (i), the roles legend has no box
// #1059 quick add: the same placeholder in the phone sheet as on the desktop; the syntax help as chips that insert the
//       shortcut (# and ~ only the sign); the sheet's buttons in their own row with a visible label (title + aria-label stay)
// #1062 the view tabs in the header no longer fold into "…" (icons when the header is narrow)
// Firefox (1440 mouse, 390 touch): the view tabs stay visible as icons with the task panel open; no monospace in the
// quick add help and the task panel's footer; #362 files dropped on the open list (not on a task) = one task per file with
// the file attached, the drop hint while dragging; a drop on a task still attaches to it; the drop on a sidebar list.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2320_d_ui', check, shots: 'P2320D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const FEAT = 'cal,comments,collab,agents,kanban,timeline';

(async () => {
  await sleep(600);
  const r0 = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r0.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const L = (await call('POST', '/api/lists', {name: 'Software'})).id;
  const L2 = (await call('POST', '/api/lists', {name: 'Briefings'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const T = (await call('POST', '/api/tasks', {title: 'Weekly report', list_id: L})).id;
  await call('POST', '/api/tasks', {title: 'Release notes', list_id: L});

  // ================= #1077 the switch on the server
  let st = await call('GET', '/api/state');
  check(st.settings.list_emoji === '1', '#1077: on by default');
  check((await call('PATCH', '/api/settings', {list_emoji: 'maybe'})).status === 400, '#1077: only 0 / 1');
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`settingsModal('look')`); let md = await until(() => d.querySelector('.modal #s-lemo'));
  check(md && md.checked && /Suggest icons for new lists/.test(md.closest('label').textContent), '#1077: the switch in Settings > Appearance, on');
  md.checked = false; md.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/state')).settings.list_emoji === '0'), '#1077: switched off, saved on the server');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.eval(`listModal(null)`); md = await until(() => d.querySelector('.modal #l-name'));
  input(w, md, 'Holiday'); await sleep(200);
  check(!d.querySelector('#l-emo').classList.contains('sugg') && d.querySelector('#l-emo svg'), '#1077: off: no suggestion, the neutral list icon');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.close();
  await call('PATCH', '/api/settings', {list_emoji: '1'});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  w.eval(`listModal(null)`); md = await until(() => d.querySelector('.modal #l-name'));
  input(w, md, 'Holiday'); await sleep(200);
  check(d.querySelector('#l-emo').classList.contains('sugg') && !d.querySelector('#l-emo svg'), '#1077: on: "Holiday" suggests an icon');
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());

  // ================= #1058 the Share dialog
  w.eval(`shareModal(${L})`); md = await until(() => d.querySelector('.modal.shmodal'));
  await until(() => md.querySelector('#sh-agsel'));
  const sec = k => md.querySelector('#sh-sec-' + k);
  check(md.querySelector('#l-members') && !md.querySelector('#l-members').closest('details.shsec'), '#1058: people are not folded');
  check(sec('ag') && !sec('ag').open && !sec('ag').hidden && sec('ag').querySelector('summary #sh-ag-h'), '#1058: agents folded, the heading in the folded line');
  check(/Claude/.test(md.querySelector('#sh-st-ag')?.textContent || ''), '#1058: the folded agents line names the agent: ' + md.querySelector('#sh-st-ag')?.textContent);
  check(sec('own') && !sec('own').open && /Alice/.test(md.querySelector('#sh-st-own').textContent), '#1058: owner folded with the name');
  check(!sec('pub') || (!sec('pub').open && await until(() => md.querySelector('#sh-st-pub')?.textContent === 'Off')), '#1058: public link folded, "Off"');
  check(md.querySelector('#l-agm') && !md.querySelector('#l-tidyrow .aghint.keep'), '#1058: the switch explanations are no longer inline (behind the (i))');
  check(await until(() => md.querySelector('#l-tidyrow label.chkl .ib')), '#1058: an (i) at the switch');
  const rh = md.querySelector('.rolehelp');
  check(rh && !rh.open && w.getComputedStyle(rh).borderTopStyle === 'none' || (rh && w.getComputedStyle(rh).borderTopWidth === '0px'), '#1058: the roles legend has no empty box when closed');
  click(w, sec('ag').querySelector('summary')); sec('ag').open = true; await sleep(100);
  check(sec('ag').open && md.querySelector('#sh-agsel'), '#1058: unfolds');
  md.remove();
  w.eval(`shareModal(${L}, {focus: 'agents'})`); md = await until(() => d.querySelector('.modal.shmodal'));
  check(await until(() => md.querySelector('#sh-sec-ag')?.open && d.activeElement?.id === 'sh-agsel'), '#1058: opened from "Agent…": the agents part is open, its choice focused');
  md.remove();
  // a list without an agent: no agent switches
  w.eval(`shareModal(${L2})`); md = await until(() => d.querySelector('.modal.shmodal')); await sleep(800);
  check(!md.querySelector('#l-agm') && !md.querySelector('#l-tidy'), '#1058: no agent chosen: no agent switches');
  md.remove();

  // ================= #1062 view tabs: no longer folding
  check(d.querySelector('#top .ttabs') && !d.querySelector('#top .ttabs').classList.contains('tf') && d.querySelector('#top .ttabs [data-act="view-kanban"] svg') && d.querySelector('#top .ttabs [data-act="view-kanban"] .vtl')?.textContent === 'Kanban'
    && d.querySelector('#top .ttabs [data-act="view-kanban"]').getAttribute('aria-label') === 'Kanban', '#1062: the view tabs carry an icon + their name and do not fold into "…"');
  w.close();

  // ================= #1059 quick add (phone sheet)
  w = await boot({user: 'alice', hash: 'l/' + L, mobile: true}); d = w.document;
  w.eval('openQuickSheet()'); const sh = await until(() => d.querySelector('.qadd.sheet'));
  const qi = d.querySelector('#qsheet');
  check(qi.placeholder === 'Add task…', '#1059: the same placeholder as the desktop: ' + qi.placeholder);
  const chips = [...sh.querySelectorAll('.qhint .qhc')];
  check(chips.map(c => c.textContent).join('|') === 'tomorrow 3pm|!high|#tag|~list|every monday', '#1059: the help as chips: ' + chips.map(c => c.textContent).join('|'));
  click(w, chips[1]); check(qi.value === '!high ', '#1059: a chip inserts its shortcut: ' + JSON.stringify(qi.value));
  click(w, chips[2]); check(qi.value === '!high #', '#1059: # only the sign: ' + JSON.stringify(qi.value));
  qi.value = 'Dentist'; qi.setSelectionRange(7, 7); click(w, chips[0]);
  check(qi.value === 'Dentist tomorrow 3pm ', '#1059: with a space before it: ' + JSON.stringify(qi.value));
  const acts = sh.querySelector('.qacts');
  check(acts && acts.querySelector('[data-act="q-clip"].qlab span')?.textContent === 'File' && acts.querySelector('[data-act="q-open"].qlab span')?.textContent === 'Details'
    && acts.querySelector('[data-act="q-open"]').getAttribute('aria-label') === 'Add and open details' && acts.querySelector('[data-act="q-clip"]').title, '#1059: the buttons with a visible label, title + aria-label kept');
  check(sh.querySelector('.box [data-act="qsheet-send"]') && !sh.querySelector('.box [data-act="q-clip"]'), '#1059: in the field only the send arrow');
  w.eval('closePop()'); await sleep(200);
  w.eval('quickCapture()'); await until(() => d.querySelector('.qadd.sheet.capture'));
  check(/Goes to the inbox/.test(d.querySelector('.qadd.sheet .qhlead')?.textContent || '') && d.querySelectorAll('.qadd.sheet .qhc').length === 4, '#1059: capture: the lead text + the chips');
  w.eval('closePop()');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, theme = 'light', user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  // a file drop (or dragover) on an element, with a real DataTransfer
  const DROP = (sel, type, name) => `(() => { const el = ${sel}; if (!el) return 'no target'; const dt = new DataTransfer(); dt.items.add(new File(['%PDF-1.4 test'], ${JSON.stringify(name)}, {type: 'application/pdf'}));
    const r = el.getBoundingClientRect(); return el.dispatchEvent(new DragEvent(${JSON.stringify(type)}, {dataTransfer: dt, bubbles: true, cancelable: true, clientX: r.left + 20, clientY: r.top + r.height - 10})) ? 'not taken' : 'taken'; })()`;
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + L); await ready(ev);
    const tabs = `(() => { const t = document.querySelector('#top .ttabs'); if (!t) return null; const bs = [...t.querySelectorAll('button')]; return {lvl: document.querySelector('#top').className, vis: bs.every(b => b.getBoundingClientRect().width > 0), icons: bs.every(b => b.querySelector('svg').getBoundingClientRect().width > 0), text: bs.some(b => b.querySelector('.vtl').getBoundingClientRect().width > 0)}; })()`;
    let tb = await ev(tabs);
    check(tb && tb.vis && tb.text, `${tag}: the view tabs with text (panel closed) ` + JSON.stringify(tb));
    await ev(`(() => { openDetail(${T}); return 1; })()`); await sleep(1200);
    tb = await ev(tabs);
    check(tb && tb.vis, `${tag}: #1062 the view tabs stay with the task panel open ` + JSON.stringify(tb));
    check(await ev(`!/Mono/.test(getComputedStyle(document.querySelector('#detail .dfoot .dfc')).fontFamily)`), `${tag}: #1062 the footer of the task panel in the normal font`);
    await shot('p2320d-1440-detail-tabs.png');
    // a narrower window with a long list name: the header folds (tl3 / tl4), the tabs become icons instead of going into "…"
    await call('PATCH', `/api/lists/${L}`, {name: 'Software for the new customer portal'});
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1180, height: 900}}); await ev(`(async () => { await load(); render(); openDetail(${T}); return 1; })()`); await sleep(1500);
    tb = await ev(tabs);
    check(tb && tb.vis && tb.icons && !tb.text && /\btl[34]\b/.test(tb.lvl), `1180: #1062 narrow header: the view tabs as icons ` + JSON.stringify(tb));
    check(!await ev(`topMoreItems().some(x => /^(List|Kanban|Timeline)$/.test(x.label || ''))`), '1180: #1062 the tabs are not in "…"');
    await shot('p2320d-1180-detail-icons.png');
    await call('PATCH', `/api/lists/${L}`, {name: 'Software'});
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}}); await ev(`(async () => { await load(); render(); return 1; })()`); await sleep(800);
    await ev(`(() => { closeDetail(); return 1; })()`); await sleep(600);
    // #362: drop on the open list (not on a task)
    check(await ev(DROP(`document.querySelector('#view')`, 'dragover', 'x.pdf')) === 'taken', `${tag}: #362 dragover on the list takes files`);
    check(await ev(`(() => { const h = document.querySelector('#fdhint'); return !!h && /one new task per file in Software/.test(h.textContent) && h.getBoundingClientRect().width > 0; })()`), `${tag}: #362 the drop hint names the list`);
    await shot('p2320d-1440-drop-hint.png');
    check(await ev(DROP(`document.querySelector('#view')`, 'drop', 'Briefing Kunde.pdf')) === 'taken', `${tag}: #362 the drop is taken`);
    check(!await ev(`!!document.querySelector('#fdhint')`), `${tag}: #362 the hint is gone after the drop`);
    const nt = await until(async () => { const s = await call('GET', '/api/state'); const t = [...(s.tasks || [])].find(x => x.title === 'Briefing Kunde' && x.list_id === L); return t && (t.attachments || []).length ? t : null; }, 60);
    check(nt && nt.attachments[0].name === 'Briefing Kunde.pdf', `${tag}: #362 a new task "Briefing Kunde" with the file attached`);
    // a drop on a task row still attaches to that task
    check(await ev(DROP(`document.querySelector('#view .trow[data-id="${T}"]')`, 'drop', 'notes.pdf')) === 'taken', `${tag}: #362 drop on a task`);
    const tt = await until(async () => { const s = await call('GET', '/api/state'); const t = s.tasks.find(x => x.id === T); return t && (t.attachments || []).some(a => a.name === 'notes.pdf') ? t : null; }, 60);
    check(tt && !(await call('GET', '/api/state')).tasks.some(x => x.title === 'notes'), `${tag}: #362 a drop on a task attaches to it (no new task)`);
    // on a list in the sidebar
    check(await ev(DROP(`document.querySelector('#side .srow[data-drop="l:${L2}"]')`, 'drop', 'Plan.pdf')) === 'taken', `${tag}: #362 drop on a sidebar list`);
    check(await until(async () => (await call('GET', '/api/state')).tasks.some(x => x.title === 'Plan' && x.list_id === L2), 60), `${tag}: #362 the sidebar list got the task`);
  }, false);
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { openQuickSheet(); return 1; })()`); await sleep(700);
    const q = await ev(`(() => { const c = [...document.querySelectorAll('.qadd.sheet .qhc')]; const s = document.querySelector('.qadd.sheet');
      return {n: c.length, mono: /Mono/.test(getComputedStyle(c[0]).fontFamily), h: Math.round(c[0].getBoundingClientRect().height), inside: c.every(x => x.getBoundingClientRect().top < s.getBoundingClientRect().bottom), lab: [...s.querySelectorAll('.qacts .qlab')].map(b => Math.round(b.getBoundingClientRect().height))}; })()`);
    check(q.n === 5 && !q.mono && q.h >= 24 && q.lab.every(h => h >= 44), `${tag}: #1059 chips in the normal font, >= 24 px, labelled buttons 44 px ` + JSON.stringify(q));
    await shot('p2320d-390-quick-add.png');
    await ev(`(() => { closePop(); shareModal(${L}); return 1; })()`); await sleep(1500);
    const sm = await ev(`(() => { const c = document.querySelector('.modal.shmodal .card') || document.querySelector('.modal.shmodal'); return {h: Math.round(c.scrollHeight), s: [...document.querySelectorAll('.shsec:not([hidden]) > summary')].map(x => Math.round(x.getBoundingClientRect().height))}; })()`);
    check(sm.s.length >= 2 && sm.s.every(h => h >= 44), `${tag}: #1058 the folded lines are 44 px targets ` + JSON.stringify(sm));
    await shot('p2320d-390-share.png');
  }, true);

  console.log(`p2320_d_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
