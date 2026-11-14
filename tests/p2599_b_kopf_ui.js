// 2.599.0 B (#4814, #4808) UI test, own container (start.sh, isolated test database), Firefox with a mouse. Invented data only.
// kalmido-suite:
// #4814 heads flush with the page: every page reports its width to #main (data-w, render.js topw_sync); from 1700 px the
// inner edges of #top (title, search, buttons) are the edges of the content below (Start / a project list = --w-seite, a
// knowledge page / a note = their own block); a board (--w-voll) keeps #top as before; 1440 x 900 and 390 x 844 keep the
// padding of #top as before. Head bars in the content: the agenda's bar = the agenda list, the team chat room's head = the
// reading column of its history, the letter's bar = its form, the rights page's bar = .orr.
// #4808 a knowledge page and a note: from 1700 px a sheet (surface var(--bg2), border var(--line2), radius, inner space), its
// text column --w-lesen; 2.783.0 (#5376): the sheet takes the full width like the bar 'Find a page / New page' and #top stays as in
// the list (before: bar and sheet in the middle); 1440 no sheet (as before); the
// reading style Notepad without a second border; Read: a code block / a table reaches into the sheet's inner space; the width
// switch in the page's / note's "…": Wide (--w-seite), Full (no limit), the default per area kept with the account (look.wkW /
// ntW, a fixed choice only), a page's own choice on the device (LS pgW).
// Screenshots (P2599B_SHOTS) at 2560, light and dark.
// freelancer-matrix: Wissen/Notizen-Breite (alice has no organisation: the width switch is saved for a person on her own)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2599_b_kopf_ui', check, shots: 'P2599B_SHOTS'});
const FEAT = 'office,kanban,collab,wiki,cal,events';
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body, ck = CA) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['office', 'cal']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call('GET', '/api/state')).me.workspaces || []).length, 'alice: no organisation (person on her own)');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab'}, CB);

  // the default width per area: a fixed choice only (the account's appearance, like the own reading style)
  await call('PATCH', '/api/settings', {look: JSON.stringify({wkW: 'body{}', ntW: 'huge', theme: 'dark'})});
  let lk = (await call('GET', '/api/state')).settings?.look || '';
  check(!/wkW|ntW/.test(lk) && /"theme":"dark"/.test(lk), `#4808: an unknown default width is dropped (${lk})`);
  await call('PATCH', '/api/settings', {look: JSON.stringify({wkW: 'breit', ntW: 'voll'})});
  lk = (await call('GET', '/api/state')).settings?.look || '';
  check(/"wkW":"breit"/.test(lk) && /"ntW":"voll"/.test(lk), `#4808: Wide / Full are kept (${lk})`);
  await call('PATCH', '/api/settings', {look: JSON.stringify({})});

  const L = (await call('POST', '/api/lists', {name: 'Website relaunch', kind: 'project'})).id;
  const K = (await call('POST', '/api/lists', {name: 'Shoot plan', kind: 'project'})).id;
  for (const [i, t] of ['Write the brief', 'Book the studio', 'Cast two actors', 'Order the props'].entries()) {
    await call('POST', '/api/tasks', {title: t, list_id: L, due: `2026-11-${String(10 + i).padStart(2, '0')}`});
    await call('POST', '/api/tasks', {title: t + ' (board)', list_id: K});
  }
  await call('PATCH', `/api/lists/${K}`, {view: 'kanban'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const dm = await call('POST', '/api/team/dm', {user_id: BOB}), RID = dm.id || dm.room?.id;
  for (let i = 0; i < 3; i++) {
    await call('POST', `/api/team/rooms/${RID}/messages`, {body: `Bob here: question ${i + 1} about the shoot on Friday?`}, CB);
    await call('POST', `/api/team/rooms/${RID}/messages`, {body: `Alice: answer ${i + 1}, the studio has everything.`});
  }
  const longCode = '```\nconst shotList = [\'wide\', \'close\', \'detail\', \'over the shoulder\', \'reverse\', \'insert\'].map(s => s.toUpperCase()).join(\' / \') + \' -- \' + \'xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\';\n```';
  const table = '| Scene | Place | Time | Light | Sound | Props | Cast | Notes |\n|---|---|---|---|---|---|---|---|\n' + Array.from({length: 3}, (_, i) => `| ${i + 1} | Studio hall number ${i + 1} | 09:00 to 12:30 | three soft boxes | boom and two lavaliers | table, chairs, lamp | Anna, Ben | long take without cuts |`).join('\n');
  const WP = await call('POST', '/api/wiki/pages', {space: 'private', path: 'Shoot/Day plan', body: 'The plan for the shoot day.\n\n' + longCode + '\n\n' + table + '\n\nEnd.'});
  check(WP.id, 'setup: a knowledge page in the private space');
  const NT = await call('POST', `/api/lists/${L}/notes`, {title: 'Briefing', body: 'Meeting notes of the briefing.\n\n- the light\n- the sound'});
  check(NT.id, 'setup: a note in the project');

  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.setItem('tasks.wkRo', '1'); return 1; })()`);  // the knowledge page in its read view (.wkmd: code block and table)
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    // the inner edges of #top (without its padding) and the box of one element (px)
    const EDGES = sel => `(() => { const t = document.querySelector('#top'), e = document.querySelector(${JSON.stringify(sel)}); if (!t || !e || !e.offsetWidth || !t.offsetWidth) return null;
      const a = t.getBoundingClientRect(), s = getComputedStyle(t), b = e.getBoundingClientRect(), rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
      return {tl: Math.round(a.left + parseFloat(s.paddingLeft)), tr: Math.round(a.right - parseFloat(s.paddingRight)), el: Math.round(b.left), er: Math.round(b.right), pl: parseFloat(s.paddingLeft), pr: parseFloat(s.paddingRight), rem, w: document.querySelector('#main').dataset.w || ''}; })()`;
    const paint = theme => ev(`(() => { document.documentElement.dataset.theme = ${JSON.stringify(theme)}; return new Promise(r => requestAnimationFrame(() => requestAnimationFrame(() => r(1)))); })()`);
    const menuPick = async (trigger, sub, item) => {  // the "…" -> a sub menu -> an entry (by its test anchor data-act)
      await ev(`(() => { document.querySelector(${JSON.stringify(trigger)}).click(); return 1; })()`);
      if (!await until(`!!document.querySelector('#pop:not(.hidden) [data-act="${sub}"]')`)) return false;
      await ev(`(() => { document.querySelector('#pop [data-act="${sub}"]').click(); return 1; })()`);
      if (!await until(`!!document.querySelector('#pop:not(.hidden) [data-act="${item}"]')`)) return false;
      await ev(`(() => { document.querySelector('#pop [data-act="${item}"]').click(); return 1; })()`);
      return true;
    };
    const PAGES = [
      // 2.832.0 (#5514): start and list are 'seite' again - #5309 (2.757) tells them by their var(--w-seite) rules, so #top takes
      // the content's edges (the padding of #view, no --pw); the 'voll' expectation of cb857869c was written without 2.757 and
      // kept #top 4 px beside the content (the two fixes met in 2.819.0: red on the Mac too)
      ['start', '#home', '#view .dash', 'seite'],
      ['list', '#l/' + L, '#view .lwrap', 'seite'],
      ['board', '#l/' + K, '#view .kanban', 'voll'],
      ['wiki', '#wiki/' + WP.id, '#view article.wkpage', 'voll'],  // 2.783.0 (#5376): the page's card takes the full width, #top stays where the list has it (voll)
      ['note', '#note/' + NT.id, '#view .ntview.open', 'eigen'],
    ];
    for (const [vw, vh] of [[390, 844], [1440, 900], [1920, 1080], [2560, 1440]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      for (const [name, hash, sel, kind] of PAGES) {
        if (vw < 768 && (kind === 'eigen' || name === 'wiki')) continue;  // the phone shows the page alone (as before)
        await nav(B + '?w=' + vw + hash);
        const m = await until(`!!S.booted && (${EDGES(sel)})`);
        if (!m) { check(false, `${vw}px ${name}: ${sel} shows`); continue; }
        if (vw >= 1700 && kind !== 'voll') {
          const m2 = await until(`(() => { const x = ${EDGES(sel)}; return x && Math.abs(x.tl - x.el) <= 2 && Math.abs(x.tr - x.er) <= 2 ? x : null; })()`, {timeout: 5000}) || await ev(EDGES(sel));
          check(Math.abs(m2.tl - m2.el) <= 2 && Math.abs(m2.tr - m2.er) <= 2, `#4814 ${vw}px ${name}: #top has the edges of the content ` + JSON.stringify(m2));
          check(m2.w === (kind === 'eigen' ? 'eigen' : kind), `#4814 ${vw}px ${name}: #main data-w = ${kind} ` + JSON.stringify(m2));
        } else if (vw >= 1700) {  // voll: #top as before
          const m3 = await until(`(() => { const x = ${EDGES(sel)}; return x && Math.abs(x.pl - 2 * x.rem) < 1 ? x : null; })()`, {timeout: 5000}) || await ev(`[${EDGES(sel)}, document.querySelector('#top').className, document.querySelector('#main').getAttribute('style')]`);
          check(m3 && Math.abs(m3.pl - 2 * m3.rem) < 1 && m3.w === 'voll', `#4814 ${vw}px ${name}: voll keeps #top as before ` + JSON.stringify(m3));
        } else if (vw >= 768) {
          check(m.pl === 2 * m.rem && m.pr === 2 * m.rem && m.w === 'voll', `#4814 ${vw}px ${name}: #top keeps its padding 2rem (app.css) ` + JSON.stringify(m));
        } else check(m.pl <= 0.5 * m.rem + 1, `#4814 ${vw}px ${name}: the phone's #top as before ` + JSON.stringify(m));
      }
    }

    // ---- #4808 at 2560 and 1440: the knowledge page
    const SHEET = `(() => { const a = document.querySelector('#view article.wkpage'), v = document.querySelector('#view'), vs = getComputedStyle(v), vr = v.getBoundingClientRect(); if (!a || !a.offsetWidth || !document.querySelector('#wk-md')) return null;
      const s = getComputedStyle(a), b = a.getBoundingClientRect(), rem = parseFloat(getComputedStyle(document.documentElement).fontSize), bg2 = (() => { const p = document.createElement('i'); p.style.color = 'var(--bg2)'; document.body.append(p); const c = getComputedStyle(p).color; p.remove(); return c; })();
      // 2.783.0 (#5376): the card is the full width, the text column is the inside of #wk-md (its padding centres it)
      const md = document.querySelector('#wk-md'), ms = getComputedStyle(md), col = md.clientWidth - parseFloat(ms.paddingLeft) - parseFloat(ms.paddingRight), mr = {width: col};
      const pre = md.querySelector(':scope > pre.mdpre, :scope > .mdcode'), tb = md.querySelector(':scope > .mdtbl');
      return {bg: s.backgroundColor, bg2, bw: parseFloat(s.borderTopWidth), rad: parseFloat(s.borderTopLeftRadius), pad: parseFloat(s.paddingLeft), col, w: b.width, l: b.left, r: b.right, rem,
        area: Math.round(v.clientWidth - parseFloat(vs.paddingLeft) - parseFloat(vs.paddingRight)), l0: Math.round(vr.left + parseFloat(vs.paddingLeft)), noBar: !document.querySelector('#view .wkbar'), pre: pre ? [Math.round(pre.getBoundingClientRect().width), Math.round(mr.width)] : null, tbl: tb ? [Math.round(tb.getBoundingClientRect().width), tb.scrollWidth > tb.clientWidth] : null}; })()`;
    for (const vw of [1440, 2560]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vw === 1440 ? 900 : 1440}});
      await nav(B + '?w=' + vw + '#wiki/' + WP.id);
      const s = await until(`!!S.booted && (${SHEET})`);
      if (!s) { check(false, `#4808 ${vw}px: the page shows`); continue; }
      if (vw === 1440) {
        check(s.bw === 0 && s.pad === 0, `#4808 1440px: no sheet (as before) ` + JSON.stringify(s));
        // 2.783.0 (#5376): the card takes the full width, the text keeps the reading column (before: the page was 46rem wide)
        // 2.1163.0 (#6089): no area bar above an open page any more: the card's edges are the main area's
        check(Math.abs(s.col - 46 * s.rem) <= 2 && s.noBar && s.w >= 0.8 * s.area && Math.abs(s.l - s.l0) <= 8, `#4808/#5376 1440px: the card the main area's width, the text in the reading column ` + JSON.stringify(s));
        continue;
      }
      check(s.bg === s.bg2 && s.bw >= 1 && s.rad > 0 && s.pad >= s.rem, `#4808 2560px: the page lies as a sheet (surface, border, radius, inner space) ` + JSON.stringify(s));
      check(Math.abs(s.col - 46 * s.rem) <= 2, `#4808 2560px: Read = the text column --w-lesen ` + JSON.stringify(s));
      check(s.noBar && s.w >= 0.8 * s.area && Math.abs(s.l - s.l0) <= 8, `#4808/#5376 2560px: the sheet takes the main area's width (2.783.0; 2.1163.0 #6089: no bar above it) ` + JSON.stringify(s));
      check(s.pre && s.pre[0] > s.pre[1] + s.rem, `#4808 2560px: Read: the code block reaches beyond the text column into the sheet ` + JSON.stringify(s));
      check(s.tbl && s.tbl[0] > s.col + s.rem && s.tbl[0] <= s.w, `#4808 2560px: Read: the table reaches into the sheet, not beyond it ` + JSON.stringify(s));
      for (const theme of ['light', 'dark']) {
        await paint(theme);
        const c = await ev(SHEET);
        check(c && c.bg === c.bg2, `#4808 2560px ${theme}: the sheet is var(--bg2) ` + JSON.stringify(c && [c.bg, c.bg2]));
        await shot(`p2599b-wiki-2560-${theme}.png`);
      }
      // the reading style Notepad: its own paper and border, no second one
      await ev(`(() => { LS.set('wkSt', 'notepad'); renderView(); return 1; })()`);
      const NP = `(() => { const a = document.querySelector('#view article.wkpage.wkst-notepad'); if (!a) return null; const s = getComputedStyle(a), m = getComputedStyle(document.querySelector('#wk-md')); return {a: s.borderTopColor, bg: s.backgroundColor, md: parseFloat(m.borderTopWidth), cls: a.className, wrap: a.parentElement.className, n: document.querySelectorAll('#view article.wkpage').length}; })()`;
      const np = await until(`(() => { const x = ${NP}; return x && /rgba\\(0, 0, 0, 0\\)|transparent/.test(x.a) ? x : null; })()`, {timeout: 5000}) || await ev(NP);
      await shot('p2599b-wiki-2560-notepad.png');
      check(np && /rgba\(0, 0, 0, 0\)|transparent/.test(np.a) && /rgba\(0, 0, 0, 0\)|transparent/.test(np.bg) && np.md >= 1, `#4808 2560px: Notepad keeps its own border, the sheet none ` + JSON.stringify(np));
      await ev(`(() => { LS.del('wkSt'); renderView(); return 1; })()`);
      // the width switch: this page Wide -> Full -> like the default; the default for knowledge pages Wide (the account)
      check(await menuPick('[data-wk="pmenu"]', 'm-pgw', 'm-pgw-breit'), '#4808: "…" > Page width… > Wide (this page)');
      // 2.783.0 (#5376): Wide = the text takes the card's width (--w-seite is no limit since #4840); #top stays where the list has it
      const wide = await until(`(() => { const x = ${SHEET}; return x && document.querySelector('.ntwrap.pgw-breit') && Math.abs(x.col - (x.w - 2 * x.pad - 2 * x.bw)) <= 2 ? x : null; })()`, {timeout: 5000}) || await ev(SHEET);
      check(wide && Math.abs(wide.col - (wide.w - 2 * wide.pad - 2 * wide.bw)) <= 2, `#4808/#5376 2560px: Wide = the text column is the card's inside ` + JSON.stringify(wide));
      const t1 = await until(`(() => { const x = ${EDGES('#view article.wkpage')}; return x && x.w === 'voll' && Math.abs(x.pl - 2 * x.rem) < 1 ? x : null; })()`, {timeout: 5000}) || await ev(EDGES('#view article.wkpage'));
      check(t1 && t1.w === 'voll' && Math.abs(t1.pl - 2 * t1.rem) < 1, `#4814/#5376 2560px Wide: #top as in the list ` + JSON.stringify(t1));
      check(/"w\d+":"breit"/.test(await ev(`JSON.stringify(LS.get('pgW', null))`)), '#4808: the page\'s own width is kept on the device (LS pgW)');
      await shot('p2599b-wiki-2560-wide.png');
      check(await menuPick('[data-wk="pmenu"]', 'm-pgw', 'm-pgw-voll'), '#4808: "…" > Page width… > Full (this page)');
      const full = await until(`(() => { const x = ${SHEET}; return x && document.querySelector('.ntwrap.pgw-voll') && x.col > 100 * x.rem ? x : null; })()`, {timeout: 5000}) || await ev(SHEET);
      const area = await ev(`(() => { const v = document.querySelector('#view'), s = getComputedStyle(v); return v.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight); })()`);
      check(full && Math.abs(full.w - area) <= 2, `#4808 2560px: Full = the whole content area (${area}) ` + JSON.stringify(full));
      const t2 = await until(`(() => { const x = ${EDGES('#view article.wkpage')}; return x && x.w === 'voll' && Math.abs(x.pl - 2 * x.rem) < 1 ? x : null; })()`, {timeout: 5000}) || await ev(EDGES('#view article.wkpage'));
      check(t2 && t2.w === 'voll' && Math.abs(t2.pl - 2 * t2.rem) < 1, `#4814 2560px Full: #top as before ` + JSON.stringify(t2));
      check(await menuPick('[data-wk="pmenu"]', 'm-pgw', 'm-pgwd-breit'), '#4808: "…" > Page width… > default Wide');
      await ev(`(() => { const o = LS.get('pgW', {}); delete o['w${WP.id}']; LS.set('pgW', o); renderView(); return 1; })()`);  // back to the default
      check(await until(`!!document.querySelector('.ntwrap.pgw-breit')`), '#4808: the page without its own choice follows the default Wide');
      let lk2 = '';
      for (let i = 0; i < 40 && !/"wkW":"breit"/.test(lk2); i++) { await sleep(250); lk2 = (await call('GET', '/api/state')).settings?.look || ''; }
      check(/"wkW":"breit"/.test(lk2), `#4808: the default is kept with the account (person without an organisation) (${lk2})`);
      await ev(`(() => { LS.del('wkW'); renderView(); return 1; })()`);
      check(await until(`!!document.querySelector('.ntwrap.pgw-lesen')`), '#4808: without a default the page reads in Read');
    }

    // ---- #4808 the note at 2560: the same sheet, list + note one block in the middle, the switch in the note's "…"
    await nav(B + '?w=2560#note/' + NT.id);
    const NS = `(() => { const v = document.querySelector('#view .ntview.open'), a = document.querySelector('#view .ntview.open > article.ntedit'); if (!v || !a || !a.offsetWidth) return null;
      const s = getComputedStyle(a), vv = document.querySelector('#view'), vs = getComputedStyle(vv), vr = vv.getBoundingClientRect(), b = v.getBoundingClientRect(), rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
      const l0 = vr.left + parseFloat(vs.paddingLeft), r0 = vr.left + vv.clientWidth - parseFloat(vs.paddingRight);
      return {bw: parseFloat(s.borderTopWidth), pad: parseFloat(s.paddingLeft), col: a.clientWidth - parseFloat(s.paddingLeft) - parseFloat(s.paddingRight), l: b.left - l0, r: r0 - b.right, rem}; })()`;
    const n1 = await until(`!!S.booted && (${NS})`);
    check(n1 && n1.bw >= 1 && n1.pad >= n1.rem && Math.abs(n1.col - 46 * n1.rem) <= 2, '#4808 2560px note: a sheet with the column --w-lesen ' + JSON.stringify(n1));
    check(n1 && Math.abs(n1.l - n1.r) <= 2 && n1.l > 2, '#4808 2560px note: list + note one block in the middle ' + JSON.stringify(n1));
    for (const theme of ['light', 'dark']) { await paint(theme); await shot(`p2599b-note-2560-${theme}.png`); }
    check(await menuPick('[data-act="nt-menu"]', 'm-pgw', 'm-pgw-breit'), '#4808: the note\'s "…" > Page width… > Wide');
    // 2.832.0 (#5514): Wide = 96rem again (#5309, start-ntblatt-4808.css --ntpw: with --w-seite none, calc(none + ...) dropped the
    // grid of list + note), so Read / Wide / Full stay three widths; #top has the edges of the block (eigen)
    const n2 = await until(`(() => { const x = ${NS}; return x && document.querySelector('.ntwrap.pgw-breit') && Math.abs(x.col - 96 * x.rem) <= 2 ? x : null; })()`, {timeout: 5000}) || await ev(NS);
    check(n2 && Math.abs(n2.col - 96 * n2.rem) <= 2, '#4808/#5309 2560px note: Wide = 96rem ' + JSON.stringify(n2));
    const tn = await until(`(() => { const x = ${EDGES('#view .ntview.open')}; return x && Math.abs(x.tl - x.el) <= 2 ? x : null; })()`, {timeout: 5000}) || await ev(EDGES('#view .ntview.open'));
    check(tn && Math.abs(tn.tl - tn.el) <= 2 && Math.abs(tn.tr - tn.er) <= 2, '#4814 2560px note Wide: #top has the edges of the block ' + JSON.stringify(tn));
    check(await menuPick('[data-act="nt-menu"]', 'm-pgw', 'm-pgwd-voll'), '#4808: the note\'s "…" > default Full');
    let lk3 = '';
    for (let i = 0; i < 40 && !/"ntW":"voll"/.test(lk3); i++) { await sleep(250); lk3 = (await call('GET', '/api/state')).settings?.look || ''; }
    check(/"ntW":"voll"/.test(lk3), `#4808: the notes' default is kept with the account (${lk3})`);
    await ev(`(() => { LS.del('ntW'); LS.del('pgW'); renderView(); return 1; })()`);

    // ---- #4814 head bars in the content at 2560
    const BOX = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e || !e.offsetWidth) return null; const b = e.getBoundingClientRect(); return [Math.round(b.left), Math.round(b.right)]; })()`;
    // the team chat room: its head's inner edges = the history's reading column
    await nav(B + '?w=2560#team/' + RID);
    const tc = await until(`(() => { const h = document.querySelector('#view .tcrhead'), m = document.querySelector('#view .tcmsgs'); if (!h || !m || !h.offsetWidth) return null; const hs = getComputedStyle(h), ms = getComputedStyle(m), hb = h.getBoundingClientRect(), mb = m.getBoundingClientRect();
      return {h: [Math.round(hb.left + parseFloat(hs.paddingLeft)), Math.round(hb.right - parseFloat(hs.paddingRight))], m: [Math.round(mb.left + parseFloat(ms.paddingLeft)), Math.round(mb.left + m.clientWidth - parseFloat(ms.paddingRight))]}; })()`);
    check(tc && Math.abs(tc.h[0] - tc.m[0]) <= 2 && Math.abs(tc.h[1] - tc.m[1]) <= 2, '#4814 2560px team chat: the room\'s head reads in the column of the history ' + JSON.stringify(tc));
    // the calendar's agenda: its bar = the list
    await nav(B + '?w=2560#cal');
    await until(`!!S.booted && !!document.querySelector('#view .calbar [data-k="agenda"]')`);
    await ev(`(() => { document.querySelector('#view .calbar [data-k="agenda"]').click(); return 1; })()`);
    const ag = await until(`(() => { const a = ${BOX('#view > .calbar')}, b = ${BOX('#view .agendav')}; return a && b && document.querySelector('#view .agendav') ? {a, b} : null; })()`);
    check(ag && Math.abs(ag.a[0] - ag.b[0]) <= 2 && Math.abs(ag.a[1] - ag.b[1]) <= 2, '#4814 2560px agenda: the bar has the edges of the list ' + JSON.stringify(ag));
    // the office: a new letter (bar over the form) and the rights page (bar over .orr)
    await nav(B + '?w=2560#office/letters/new');  // a new draft (p2106_a)
    const lt = await until(`(() => { const a = ${BOX('#view .ofcbar:has(~ .lt-form)')}, b = ${BOX('#view .lt-form')}; return a && b ? {a, b} : null; })()`, {timeout: 20000});
    check(lt && Math.abs(lt.a[0] - lt.b[0]) <= 2 && Math.abs(lt.a[1] - lt.b[1]) <= 2, '#4814 2560px letter: the bar has the edges of the form ' + JSON.stringify(lt));
    await nav(B + '?w=2560#office/rights');
    const rr = await until(`(() => { const a = ${BOX('#view .ofcbar:has(+ .orr)')}, b = ${BOX('#view .orr')}; return a && b ? {a, b} : null; })()`, {timeout: 20000});
    check(rr && Math.abs(rr.a[0] - rr.b[0]) <= 2 && Math.abs(rr.a[1] - rr.b[1]) <= 2, '#4814 2560px rights: the bar has the edges of the page ' + JSON.stringify(rr));
    for (const theme of ['light', 'dark']) { await paint(theme); await shot(`p2599b-rights-2560-${theme}.png`); }
    await nav(B + '?w=2560#l/' + L);
    await until(`!!S.booted && !!document.querySelector('#view .lwrap')`);
    for (const theme of ['light', 'dark']) { await paint(theme); await shot(`p2599b-list-2560-${theme}.png`); }
  }, false);

  console.log(`p2599_b_kopf_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
