// kalmido-suite: fresh
// 2.365.0 A UI tests (#3319 chat window, #2824 phone thumb bar + message above the keyboard, #2802 first start on the phone,
// #3010 "Assigned to me"), own container (start.sh), Firefox (phone 360 / 412 px touch, desktop 1280 / 1400 px). Invented data
// only. P2365A_NOSTART=1 = the container runs.
// - #2802 setup step 2 at 360 px: the language is a small menu (six languages in it), the card does not scroll in the page
//   (one scroll bar) and starts at the top, the start tiles in one column; the first start opens on Today; the invitation page
//   names who invites and into which organisation (also without an organisation: the app's name)
// - #2824 phone: the task's bottom bar above the comment field holds the date, Today / Tomorrow, the project and Complete;
//   the header keeps Back, Priority and "…"; nothing sideways, 44 px targets; a message sits above the bar; the bar steps
//   aside while a comment is typed; a computer keeps the header as it was
// - #3319 desktop: the chat in its own window uses the window's whole width (header, history, composer), a bubble at most
//   75 % / about 900 px, own ones right; a narrow window keeps the usual bubbles
// - #3010 My tasks: the group of unassigned tasks from own projects is called "Unassigned in your projects", starts folded
//   and is not counted; the view switch says "Kanban"
// P4: frida (no organisation) gets the phone bar and the folded group in her private area (freelancer-matrix: tasks)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2365_a_ui', check, shots: 'P2365A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
// KALMIDO_ONBOARDING=1: a new account starts with the tour pending (the first start of #2802)
if (!process.env.P2365A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, KALMIDO_ONBOARDING: '1'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const day = n => { const d = new Date(Date.now() + n * 864e5); return d.toISOString().slice(0, 10); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = async (o, u) => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  };
  const SMALL = sel => `[...document.querySelectorAll(${JSON.stringify(sel)})].filter(e => e.offsetParent).map(e => { const q = e.getBoundingClientRect(); return {c: e.className || e.tagName, w: Math.round(q.width), h: Math.round(q.height)}; }).filter(x => x.w < 43.5 || x.h < 43.5)`;

  // ================= #2802 setup step 2 on a 360 px phone (the first admin, setup still open)
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    check(await signIn(o, 'alice') === 200, 'setup 360: login');
    await nav(B);
    check(await ready(ev, `!!document.querySelector('.authscreen .setupcard [data-su-preset]')`, 60), '#2802: step 2 is up');
    const g = await ev(`(() => { const md = document.querySelector('.modal.authscreen'), c = md.querySelector('.setupcard'), l = c.querySelector('#su-lang'), s = l?.querySelector('summary'), st = c.querySelector('.sustarts');
      const cr = c.getBoundingClientRect(), sr = s?.getBoundingClientRect();
      return {det: l?.tagName, langs: c.querySelectorAll('[data-su-lang]').length, sumH: sr ? Math.round(sr.height) : 0, sumRight: sr ? Math.round(cr.right - sr.right) : -1, sumTop: sr ? Math.round(sr.top - cr.top) : -1,
        cardOv: getComputedStyle(c).overflowY, cardScroll: c.scrollHeight - c.clientHeight, pageScroll: md.scrollHeight - md.clientHeight, top: Math.round(cr.top),
        cols: getComputedStyle(st).gridTemplateColumns.split(' ').length, cut: [...st.querySelectorAll('b')].filter(b => b.scrollWidth > b.clientWidth + 1).map(b => b.textContent),
        sideways: document.documentElement.scrollWidth - innerWidth}; })()`);
    check(g.det === 'DETAILS' && g.langs === 6 && g.sumH <= 48 && g.sumRight >= 0 && g.sumRight < 40 && g.sumTop < 40, '#2802: the language is a small menu in the top right corner with the six languages ' + JSON.stringify(g));
    check(g.cardOv === 'visible' && g.cardScroll <= 1 && g.pageScroll > 0, '#2802: one scroll bar - the page scrolls, not the card in it ' + JSON.stringify(g));
    check(g.top >= 0, '#2802: the card starts inside the screen (not cut off at the top) ' + JSON.stringify(g));
    check(g.cols === 1 && !g.cut.length && g.sideways <= 0, '#2802: the start tiles in one column, titles whole, nothing sideways ' + JSON.stringify(g));
    await shot('p2365a-setup-360.png');
    // the menu switches the language
    await ev(`(() => { document.querySelector('#su-lang summary').click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('#su-lang').open && document.querySelector('[data-su-lang="de"]').offsetParent !== null`), '#2802: the menu opens');
    await ev(`(() => { document.querySelector('[data-su-lang="de"]').click(); return 1; })()`);
    check(await ready(ev, `/Wofür nutzt du Kalmido/.test(document.querySelector('.setupcard').textContent) && /Deutsch/.test(document.querySelector('#su-lang summary').textContent)`), '#2802: German after the choice, the menu shows it');
  }, true);

  // the rest of the setup: an organisation, collaboration, comments and agents
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  const st = await call(CA, 'GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents'); feats.add('comments'); feats.add('collab');
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'all', features: [...feats].join(',')});
  const me = (await call(CA, 'GET', '/api/state')).me, ORG = me.workspaces[0].id;

  // ================= #2802 the very first start opens on Today (tour pending, no hash, nothing remembered)
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    // a new account: tour and onboarding still pending (the client can only finish the tour)
    const pu = await call(CA, 'POST', '/api/users', {username: 'paul', display_name: 'Paul', password: 'password123', email: 'paul@example.com', orgs: [ORG]});
    check(pu.id, 'first start: a new account ' + pu.http);
    check(await signIn(o, 'paul') === 200, 'first start: login');
    await nav(B);
    const hs = []; for (let i = 0; i < 20; i++) { hs.push(await ev(`(typeof S !== 'undefined' && S.booted ? S.route.key : '') + '|' + location.hash`).catch(() => '')); await sleep(100); }
    const bt = hs.filter(h => !/^\|/.test(h));
    check(bt.length && bt.every(h => /^today\|#today$/.test(h)), '#2802: the first start opens on Today, no Basket first ' + JSON.stringify([...new Set(hs)]));
  }, true);

  // ================= #2802 the invitation page names who invites and where
  const nina = await call(CA, 'POST', '/api/users', {username: 'nina', display_name: 'Nina', email: 'nina@example.com', invite: true, send: false, orgs: [ORG]});
  const olga = await call(CA, 'POST', '/api/users', {username: 'olga', display_name: 'Olga', email: 'olga@example.com', invite: true, send: false, orgs: []});
  const tokOf = u => ((u.invitation || {}).link || '').split('#invite/')[1] || '';
  check(tokOf(nina) && tokOf(olga), 'invitations with a link ' + JSON.stringify([nina.http, olga.http]));
  const chk = await call(null, 'POST', '/api/auth/invite/check', {token: tokOf(nina)});
  check(chk.invited_by === 'Alice' && chk.org_name === 'Alpha' && chk.username === 'nina', '#2802: the link names the inviting person and the organisation ' + JSON.stringify(chk));
  const chk2 = await call(null, 'POST', '/api/auth/invite/check', {token: tokOf(olga)});
  check(chk2.invited_by === 'Alice' && chk2.org_name === '', '#2802: without an organisation: only the inviting person ' + JSON.stringify(chk2));
  const bad = await call(null, 'POST', '/api/auth/invite/check', {token: 'x'.repeat(43)});
  check(bad.http === 404 && bad.invited_by === undefined && bad.org_name === undefined, '#2802: a wrong link says nothing about anyone ' + JSON.stringify(bad));
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await nav(B + '#invite/' + tokOf(nina));
    check(await ready(ev, `!!document.querySelector('.authscreen .invby')`, 60), '#2802: the invitation page is up');
    check(await ev(`document.querySelector('.authscreen .invby').textContent`) === 'Alice invites you to Alpha.', '#2802: "Alice invites you to Alpha."');
    await shot('p2365a-invite-360.png');
    await nav(B + 'static/icon.svg'); await nav(B + '#invite/' + tokOf(olga));
    check(await ready(ev, `/^Alice invites you to .+\\.$/.test(document.querySelector('.authscreen .invby')?.textContent || '')`, 60), '#2802: without an organisation: "Alice invites you to <app>."');
  }, true);

  // ================= data: a project with a dated task, a comment, frida without an organisation
  const W0 = (await call(CA, 'POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  const T1 = (await call(CA, 'POST', '/api/tasks', {title: 'Send the shooting plan', list_id: W0, due: day(3)})).id;
  await call(CA, 'POST', `/api/tasks/${T1}/comments`, {body: 'First note'});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'all', features: [...feats].join(',')});
  const FU = (await call(CF, 'GET', '/api/state')).me;
  check(!(FU.workspaces || []).length, 'frida: no organisation');
  const FL = (await call(CF, 'POST', '/api/lists', {name: 'Studio'})).id;
  const FT = (await call(CF, 'POST', '/api/tasks', {title: 'Invoice the client', list_id: FL, due: day(2)})).id;

  // ================= #2824 the phone's thumb bar
  const BAR = `(() => { const d = document.querySelector('#detail'), b = d?.querySelector('.dthumb'), top = d?.querySelector('.dtop'); if (!b) return null; const r = b.getBoundingClientRect(), cm = d.querySelector('.dcomp');
    const vis = e => !!e && e.offsetParent !== null && e.getBoundingClientRect().width > 0;
    return {date: vis(b.querySelector('[data-act="date"]')), quick: b.querySelectorAll('[data-act="due-q"]').length, proj: b.querySelector('.dtproj')?.getAttribute('aria-label'), chk: vis(b.querySelector('.dtdone[data-act="toggle"]')),
      last: b.lastElementChild?.matches('.dtdone'), topChk: !!top.querySelector('.chk'), topDate: !!top.querySelector('[data-act="date"], [data-act="due-q"]'), back: vis(top.querySelector('.back')), prio: vis(top.querySelector('[data-act="prio"]')), more: vis(top.querySelector('[data-act="task-menu"]')),
      above: cm ? Math.round(cm.getBoundingClientRect().top - r.bottom) : null, bottom: Math.round(innerHeight - r.bottom), sideways: d.scrollWidth - d.clientWidth, cut: b.scrollWidth - b.clientWidth,
      wide: [...d.querySelectorAll('*')].filter(e => e.getBoundingClientRect().right > d.getBoundingClientRect().left + d.clientWidth + .5).slice(0, 4).map(e => (typeof e.className === 'string' && e.className) || e.tagName)}; })()`;
  for (const [W, u, ck, tid, lname] of [[360, 'alice', CA, T1, 'Work'], [412, 'frida', CF, FT, 'Studio']]) await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o, L = `phone ${W} ${u}`;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 800}});
    check(await signIn(o, u) === 200, L + ': login');
    await nav(B + '#t/' + tid);
    check(await ready(ev, `!!document.querySelector('#detail .dthumb .dchip')`, 80), L + ': the task with its bottom bar');
    const g = await ev(BAR);
    check(g && g.date && g.quick >= 1 && g.chk && g.last && g.proj === 'Project: ' + lname, L + ': the bar holds date, Today / Tomorrow, the project and Complete (right) ' + JSON.stringify(g));
    check(g && !g.topChk && !g.topDate && g.back && g.prio && g.more, L + ': the header keeps Back, Priority and "…" ' + JSON.stringify(g));
    check(g && (g.above === null || (g.above >= 0 && g.above < 4)) && g.cut <= 0 && !g.wide.some(c => /dthumb|dtop|dchip|dq|dtproj|dtdone/.test(c)), L + ': right above the comment field, nothing of the bar or the header sideways ' + JSON.stringify(g));  // the comment's action buttons at 360 px: #3471
    const sm = await ev(SMALL('#detail .dthumb button'));
    check(!sm.length, L + ': 44 px targets in the bar ' + JSON.stringify(sm));
    await shot(`p2365a-thumb-${W}.png`);
    // a message sits above the bar
    await ev(`(() => { toast('Saved for the test'); return 1; })()`);
    await ready(ev, `(() => { const t = document.querySelector('#toast').getBoundingClientRect(), b = document.querySelector('#detail .dthumb').getBoundingClientRect(); return t.bottom <= b.top; })()`, 12);  // the message slides in
    const ts = await ev(`(() => { const e = document.querySelector('#toast'), t = e.getBoundingClientRect(), b = document.querySelector('#detail .dthumb').getBoundingClientRect(); return {t: Math.round(t.bottom), b: Math.round(b.top), sb: e.style.bottom, lay: document.documentElement.clientHeight, ih: innerHeight, kb: typeof kbReal === 'function' && kbReal(), vv: visualViewport.height}; })()`);
    check(ts.t <= ts.b, L + ': the message sits above the bar ' + JSON.stringify(ts));
    // the project button opens the move menu; Escape closes it
    await ev(`(() => { document.querySelector('#detail .dtproj').click(); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('#pop:not(.hidden) [role=menuitem], #pop:not(.hidden) button')].some(b => /Move to project/.test(b.textContent))`), L + ': the project opens "Move to project…"');
    await ev(`(() => { closePop(); return 1; })()`);
    // typing a comment: the bar steps aside
    if (await ev(`!!document.querySelector('#detail .dcomp textarea') && document.hasFocus()`)) {  // a headless window without focus never matches :focus
      await ev(`(() => { document.querySelector('#detail .dcomp textarea').focus(); return 1; })()`);
      check(await ready(ev, `getComputedStyle(document.querySelector('#detail .dthumb')).display === 'none'`), L + ': the bar steps aside while a comment is typed');
      await ev(`(() => { document.activeElement.blur(); return 1; })()`);
      check(await ready(ev, `getComputedStyle(document.querySelector('#detail .dthumb')).display !== 'none'`), L + ': and comes back');
    }
    // Complete in the bar completes the task
    await ev(`(() => { document.querySelector('#detail .dthumb .dtdone').click(); return 1; })()`);
    const done = async () => (await call(ck, 'GET', `/api/tasks/${tid}`)).status === 2;
    let dn = false; for (let i = 0; i < 30 && !dn; i++) { dn = await done(); if (!dn) await sleep(200); }
    check(dn, L + ': Complete in the bar completes the task');
    await call(ck, 'PATCH', `/api/tasks/${tid}`, {status: 0});
  }, true);
  // a computer keeps the header as it was
  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    check(await signIn(o, 'alice') === 200, 'desktop: login');
    await nav(B + '#t/' + T1);
    check(await ready(ev, `!!document.querySelector('#detail .dtop .dchip')`, 80), 'desktop: date in the header');
    check(await ev(`!document.querySelector('#detail .dthumb') && !!document.querySelector('#detail .dtop .chk')`), '#2824: no bottom bar on a computer, Complete stays in the header');
  }, false);

  // ================= #3319 the chat in its own window
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Dev Bot'});
  await call(CA, 'PATCH', `/api/admin/agents/${ag.id}`, {org_id: ORG});
  await call(CA, 'PUT', `/api/lists/${W0}/members`, {user_id: ag.id, role: 'edit'});
  check(ag.id && ag.token, 'the agent ' + ag.http);
  const LONG = 'A long line about the release notes that goes on and on so that it would fill the whole window if nothing limited it. '.repeat(4);
  await call(CA, 'POST', `/api/agents/${ag.id}/chat`, {body: 'Please write the notes ' + LONG});
  await v1(ag.token, 'POST', `/agent/chats/${me.id}`, {body: 'On it. ' + LONG});
  const CHAT = `(() => { const v = document.querySelector('#view .chview'), c = v?.querySelector('.chcomp'), h = v?.querySelector('.chath'); if (!v || !c) return null;
    const ms = [...v.querySelectorAll('.cmsg.me, .cmsg.ag')].map(m => ({me: m.classList.contains('me'), w: Math.round(m.getBoundingClientRect().width), l: Math.round(m.getBoundingClientRect().left), r: Math.round(m.getBoundingClientRect().right)}));
    const vr = v.getBoundingClientRect();
    return {vw: innerWidth, v: Math.round(vr.width), vl: Math.round(vr.left), vr: Math.round(vr.right), c: Math.round(c.getBoundingClientRect().width), h: h ? Math.round(h.getBoundingClientRect().width) : 0, ms, sideways: document.documentElement.scrollWidth - innerWidth}; })()`;
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1400, height: 860}});
    check(await signIn(o, 'alice') === 200, 'chat window: login');
    await nav(B + '?mini=1#agents/' + ag.id);
    check(await ready(ev, `document.querySelectorAll('#view .chview .cmsg.ag').length > 0 && document.querySelectorAll('#view .chview .cmsg.me').length > 0`, 80), '#3319: the chat window is up');
    const g = await ev(CHAT);
    check(g && g.v >= g.vw - 40 && g.c >= g.vw - 40 && (g.h === 0 || g.h >= g.vw - 40) && g.sideways <= 0, '#3319: header, history and composer use the whole window ' + JSON.stringify({...g, ms: undefined}));
    check(g && g.ms.length >= 2 && g.ms.every(m => m.w <= g.v * 0.75 + 2 && m.w <= 56 * 16 + 2), '#3319: a bubble at most 75 % / about 900 px ' + JSON.stringify(g?.ms));
    const mine = g?.ms.find(m => m.me), theirs = g?.ms.find(m => !m.me);
    check(mine && theirs && g.vr - mine.r < 30 && theirs.l - g.vl < 30, '#3319: own messages right, the agent left ' + JSON.stringify({mine, theirs, vl: g?.vl, vr: g?.vr}));
    await shot('p2365a-chatwin-1400.png');
    // the window grows / shrinks: the chat follows; a narrow window keeps the usual bubbles (88 %)
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1900, height: 860}}); await sleep(400);
    const g2 = await ev(CHAT);
    check(g2 && g2.v >= g2.vw - 40 && g2.c >= g2.vw - 40, '#3319: a wider window: still the whole width ' + JSON.stringify({...g2, ms: undefined}));
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 440, height: 720}}); await sleep(400);
    const g3 = await ev(CHAT);
    check(g3 && g3.v >= g3.vw - 40 && g3.sideways <= 0 && g3.ms.some(m => m.w > g3.v * 0.76), '#3319: a narrow window: whole width, the usual wider bubbles ' + JSON.stringify(g3));
  }, false);

  // ================= #3010 My tasks
  const G = (await call(CA, 'POST', '/api/lists', {name: 'Garden'})).id;
  await call(CA, 'POST', '/api/tasks', {title: 'Prune the roses', list_id: G});
  await call(CA, 'POST', '/api/tasks', {title: 'Mine in team', list_id: W0, assignee_id: me.id});
  await call(CF, 'POST', '/api/tasks', {title: 'Sort the receipts', list_id: FL});
  await call(CF, 'POST', '/api/tasks', {title: 'Mine at the studio', list_id: FL, assignee_id: FU.id});
  for (const [u, solo] of [['alice', 'Prune the roses'], ['frida', 'Sort the receipts']]) await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o, L = 'My tasks ' + u;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    check(await signIn(o, u) === 200, L + ': login');
    await nav(B + '#assigned');
    check(await ready(ev, `!!document.querySelector('#view .ghead[data-key="kb:mine"]')`, 80), L + ': the group is there');
    const g = await ev(`(() => { const h = document.querySelector('#view .ghead[data-key="kb:mine"]'); return {txt: h.textContent.trim(), closed: h.classList.contains('closed'), solo: ${JSON.stringify(solo)} && document.querySelector('#view').textContent.includes(${JSON.stringify(solo)}),
      kanban: document.querySelector('#view .mobar [data-act="mo-view"][data-k="board"]')?.textContent.trim() || ''}; })()`);
    check(/^Unassigned in your projects/.test(g.txt) && g.closed && !g.solo, '#3010: "Unassigned in your projects", folded until opened ' + JSON.stringify(g));
    check(g.kanban === '' || g.kanban === 'Kanban', '#3010: the view switch says Kanban ' + JSON.stringify(g));
    const n = await ev(`counts().assigned`);
    check(n === 1, '#3010: the counter counts only what is assigned ' + n);
    await ev(`(() => { document.querySelector('#view .ghead[data-key="kb:mine"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelector('#view').textContent.includes(${JSON.stringify(solo)})`), '#3010: a click opens it');
    await shot(`p2365a-mine-${u}.png`);
  }, false);

  console.log(`p2365_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
