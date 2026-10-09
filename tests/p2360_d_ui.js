// 2.36.0 UI tests (agent D), own container (start.sh), Firefox (real layout):
// #1119 code blocks in task comments and in the description wrap like in the chat (no sideways scrolling, no scroll bar),
//       the code inside the block is no inline-code chip (no background / padding / rounding, the block's font size);
//       "Copy" takes the original text (no added line breaks); the quick reactions of a comment (hover, keyboard focus,
//       a tap on the smiley) never cover the comment's Reply / Edit / Delete buttons; light and dark, 390 px and wide
// #1120 a new comment / chat message (the poll draws the open task again) keeps the scroll position of the comments area
//       (desktop split), of the panel (one column, wide touch screen) and on the phone; who was at the very end stays at
//       the end when a comment arrives
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2360_d_ui', check, shots: 'P2360D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,agents';
const LONG = 'docker compose -f /srv/app/docker-compose.yml exec -T web python3 manage.py migrate --database=default --noinput --verbosity=2 && echo done-with-a-very-long-line-without-spaces-' + 'x'.repeat(80);
const CODE = LONG + '\nsecond line';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const SH = (await call('POST', '/api/lists', {name: 'Shared work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${SH}/members`, {user_id: bob.id, role: 'edit'});
  // a task with a code block in its description and a code block in bob's comment (#1119)
  const TC = (await call('POST', '/api/tasks', {title: 'Code task', list_id: SH, content: 'Run this:\n\n```bash\n' + CODE + '\n```\n\nThen `inline` here.'})).id;
  await call('POST', `/api/tasks/${TC}/comments`, {body: 'Mine first'});
  const cc = await call('POST', `/api/tasks/${TC}/comments`, {body: 'Please run:\n\n```bash\n' + CODE + '\n```\n\nKlasse 38: the next line stays readable.'}, CB);
  check(cc.id > 0, 'a comment with a code block ' + cc.status);
  // a task with many comments (#1120)
  const TS = (await call('POST', '/api/tasks', {title: 'Scroll task', list_id: SH})).id;
  for (let i = 1; i <= 16; i++) {
    const x = await call('POST', `/api/tasks/${TS}/comments`, {body: `Comment ${i}\n\nline two of ${i}\n\nline three of ${i}`}, i % 2 ? CB : CK);
    if (!(x.id > 0)) { await sleep(1500); await call('POST', `/api/tasks/${TS}/comments`, {body: `Comment ${i} again`}, i % 2 ? CB : CK); }
  }
  let nNew = 0;
  const bobSays = () => call('POST', `/api/tasks/${TS}/comments`, {body: `New from Bob ${++nNew}`}, CB);

  // static: the rules are in the style sheet
  const css = fs.readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8');
  check(/\.cbody pre\.mdpre,#d-md pre\.mdpre\{white-space:pre-wrap;overflow-wrap:anywhere/.test(css), '#1119: comment + description code blocks wrap (CSS)');
  check(/\.cm:hover \.cmrxq\{opacity:1/.test(css) && /\.cm:focus-within \.cmrxq/.test(css), '#1119: hover / keyboard focus still fade the quick reactions in (CSS)');

  const ffLogin = async ({ev, nav}, theme = 'light') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .agview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const openTask = async (ev, id) => { await ev(`(() => { openDetail(${id}); return 1; })()`); for (let i = 0; i < 30 && !(await ev(`document.querySelectorAll('#d-tl-items .cm').length > 1`)); i++) await sleep(300); await sleep(900); };
  // #1119: the code blocks of the open task (comment + description)
  const codeGeo = ev => ev(`(() => {
    const one = pre => { if (!pre) return null; const cs = getComputedStyle(pre), code = pre.querySelector('code'), cc = getComputedStyle(code), r = pre.getBoundingClientRect(), box = pre.closest('.mdcode').getBoundingClientRect();
      return {ws: cs.whiteSpace, ox: cs.overflowX, wide: pre.scrollWidth - pre.clientWidth, h: Math.round(r.height), inBox: r.right <= box.right + 1 && r.left >= box.left - 1,
        bg: cc.backgroundColor, pad: cc.paddingLeft + ' ' + cc.paddingTop, rad: cc.borderTopLeftRadius, fs: cc.fontSize === cs.fontSize, text: pre.textContent}; };
    const cm = document.querySelector('#d-tl-items .cm .cbody pre.mdpre'), md = document.querySelector('#d-md pre.mdpre');
    const nx = cm && cm.closest('.mdcode').nextElementSibling, nr = nx && nx.getBoundingClientRect(), pr = cm && cm.closest('.mdcode').getBoundingClientRect();
    return {cm: one(cm), md: one(md), next: nr ? Math.round(nr.top - pr.bottom) : null, page: document.documentElement.scrollWidth <= innerWidth}; })()`);
  const codeOk = (g, tag) => {
    for (const k of ['cm', 'md']) {
      const x = g && g[k];
      check(x && x.ws === 'pre-wrap' && x.ox === 'hidden' && x.wide <= 1 && x.inBox, `${tag}: #1119 the ${k === 'cm' ? 'comment' : 'description'} code block wraps (no sideways scrolling) ` + JSON.stringify(x && {ws: x.ws, ox: x.ox, wide: x.wide}));
      check(x && /rgba\(0, 0, 0, 0\)|transparent/.test(x.bg) && /^0px 0px$/.test(x.pad) && x.rad === '0px' && x.fs, `${tag}: #1119 the ${k} code inside the block is no inline-code chip ` + JSON.stringify(x && {bg: x.bg, pad: x.pad, rad: x.rad, fs: x.fs}));
      check(x && x.text === CODE, `${tag}: #1119 the ${k} block's text (what Copy takes) is the original, no added line breaks`);
    }
    check(g && g.next !== null && g.next >= 0, `${tag}: #1119 the text after the block starts below it (nothing over "Klasse 38") ` + (g && g.next));
    check(g && g.page, `${tag}: #1119 the page does not scroll sideways`);
  };
  // #1119: the quick reactions of bob's comment vs its action buttons
  const rxGeo = (ev, cid) => ev(`(() => {
    const cm = document.querySelector('#d-tl-items .cm[data-cid="${cid}"]'); if (!cm) return null;
    const q = cm.querySelector('.cmrxq'), qs = q && getComputedStyle(q), qr = q && q.getBoundingClientRect();
    const hit = [...cm.querySelectorAll('.cacts .iconbtn')].map(b => b.getBoundingClientRect()).filter(b => b.width)
      .some(b => qr && !(qr.right <= b.left || qr.left >= b.right || qr.bottom <= b.top || qr.top >= b.bottom));
    const body = cm.querySelector('.cbody').getBoundingClientRect();
    return {shown: !!q && qs.opacity === '1', acts: cm.querySelectorAll('.cacts .iconbtn').length, hit, overBody: !!qr && qr.top < body.bottom - 2 && qr.bottom > body.top + 2}; })()`);

  // ================= desktop, mouse, 1440: split view
  for (const theme of ['light', 'dark']) {
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o, tag = '1440-' + theme;
      check(await ffLogin(o, theme) === 200, tag + ': login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
      await o.nav(B + '#l/' + SH); await ready(ev);
      await openTask(ev, TC);
      check(await ev(`!!document.querySelector('#detail.dsplit')`), tag + ': the split view');
      codeOk(await codeGeo(ev), tag);
      // hover / keyboard focus only fade the quick reactions in (opacity; headless Firefox has neither a real hover nor window
      // focus): their place is laid out all the time: right end of the reaction row, not over the buttons or the text
      await ev(`(() => { document.querySelector('#d-tl-items .cm[data-cid="${cc.id}"]').scrollIntoView({block: 'center'}); return 1; })()`); await sleep(200);
      let g = await rxGeo(ev, cc.id);
      const pos = await ev(`(() => { const q = document.querySelector('#d-tl-items .cm[data-cid="${cc.id}"] .cmrxq'), cs = q && getComputedStyle(q); return q && {pos: cs.position, d: cs.display, w: Math.round(q.getBoundingClientRect().width)}; })()`);
      check(g && pos && pos.pos === 'absolute' && pos.d !== 'none' && pos.w > 40 && g.acts >= 1 && !g.hit && !g.overBody, `${tag}: #1119 hover / focus: the quick reactions cover neither the buttons nor the text ` + JSON.stringify({...g, ...pos}));
      if (theme === 'light') { await ev(`(() => { const c = document.querySelector('#d-tl-items .cm[data-cid="${cc.id}"]'); c.querySelector('.cmrxq').style.opacity = 1; c.querySelector('.cacts').style.opacity = 1; return 1; })()`); await shot('p2360d-1440-hover.png'); await ev(`(() => { const c = document.querySelector('#d-tl-items .cm[data-cid="${cc.id}"]'); c.querySelector('.cmrxq').style.opacity = ''; c.querySelector('.cacts').style.opacity = ''; return 1; })()`); }
      // a tap on the smiley: the bar opens in the flow under the comment
      await ev(`(() => { document.activeElement?.blur(); document.querySelector('#d-tl-items .cm[data-cid="${cc.id}"] .rxtog').click(); return 1; })()`); await sleep(400);
      g = await rxGeo(ev, cc.id);
      check(g && g.shown && !g.hit && !g.overBody, `${tag}: #1119 opened with the smiley: in the flow, nothing covered ` + JSON.stringify(g));
      // a rebuild while open (the poll): still the same place
      await ev(`(() => { renderDetail(); return 1; })()`); await sleep(300);
      g = await rxGeo(ev, cc.id);
      check(g && !g.hit && !g.overBody, `${tag}: #1119 after a rebuild nothing covered ` + JSON.stringify(g));
      await ev(`(() => { document.body.click(); return 1; })()`);
      if (theme === 'dark') return;

      // #1120: the comments area of the split, scrolled to the middle; bob comments; the poll draws again
      await openTask(ev, TS);
      const pane = `document.querySelector('#d-cpane')`;
      const mid = await ev(`(() => { const p = ${pane}; if (!p || p.scrollHeight <= p.clientHeight + 40) return null; p.scrollTop = Math.round((p.scrollHeight - p.clientHeight) / 2); return p.scrollTop; })()`);
      check(mid > 20, `${tag}: #1120 the comments area scrolls (${mid})`);
      let n0 = await ev(`document.querySelectorAll('#d-tl-items .cm').length`);
      await bobSays();
      for (let i = 0; i < 40 && await ev(`document.querySelectorAll('#d-tl-items .cm').length`) === n0; i++) await sleep(300);
      await sleep(600);
      let s = await ev(`(() => { const p = ${pane}; return {top: p.scrollTop, n: document.querySelectorAll('#d-tl-items .cm').length}; })()`);
      check(s.n === n0 + 1 && Math.abs(s.top - mid) <= 2, `${tag}: #1120 a new comment keeps the comments area where it was ` + JSON.stringify({mid, ...s}));
      // a rebuild of the panel (the poll after a new chat message) keeps it too
      await ev(`(() => { document.activeElement?.blur(); renderDetail(); return 1; })()`); await sleep(200);
      s = await ev(`${pane}.scrollTop`);
      check(Math.abs(s - mid) <= 2, `${tag}: #1120 a rebuild keeps the comments area where it was ${mid} -> ${s}`);
      // at the very end: stays at the end with the next comment
      await ev(`(() => { const p = ${pane}; p.scrollTop = p.scrollHeight; return 1; })()`); await sleep(200);
      n0 = await ev(`document.querySelectorAll('#d-tl-items .cm').length`);
      await bobSays();
      for (let i = 0; i < 40 && await ev(`document.querySelectorAll('#d-tl-items .cm').length`) === n0; i++) await sleep(300);
      await sleep(600);
      s = await ev(`(() => { const p = ${pane}; return {gap: Math.round(p.scrollHeight - p.clientHeight - p.scrollTop), n: document.querySelectorAll('#d-tl-items .cm').length}; })()`);
      check(s.n === n0 + 1 && s.gap <= 4, `${tag}: #1120 at the end: the new comment shows, still at the end ` + JSON.stringify(s));
      // another task starts at its top (2.18.0 R7)
      await openTask(ev, TC);
      check(await ev(`document.querySelector('#detail .dbody').scrollTop`) === 0, `${tag}: #1120 another task starts at its top`);
    }, false);
  }

  // ================= one column: a wide touch screen (1200) and the phone (390)
  for (const [W, Hh] of [[1200, 860], [390, 844]]) {
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o, tag = W + '-touch';
      check(await ffLogin(o, W === 390 ? 'dark' : 'light') === 200, tag + ': login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
      await o.nav(B + '#l/' + SH); await ready(ev);
      await openTask(ev, TC);
      check(await ev(`!document.querySelector('#detail.dsplit')`), tag + ': one column');
      codeOk(await codeGeo(ev), tag);
      await ev(`(() => { const c = document.querySelector('#d-tl-items .cm[data-cid="${cc.id}"]'); c.scrollIntoView({block: 'center'}); c.querySelector('.rxtog').click(); return 1; })()`); await sleep(400);
      const g = await rxGeo(ev, cc.id);
      check(g && g.shown && !g.hit && !g.overBody, `${tag}: #1119 the opened quick reactions cover nothing ` + JSON.stringify(g));
      if (W === 390) { await ev(`(() => { document.querySelector('#d-tl-items .cm[data-cid="${cc.id}"] .mdcode').scrollIntoView({block: 'start'}); document.querySelector('#detail').scrollTop -= 60; return 1; })()`); await sleep(300); await shot('p2360d-390-code.png'); }
      await ev(`(() => { document.body.click(); return 1; })()`);

      await openTask(ev, TS);
      const sc = `document.querySelector('#detail')`;
      const mid = await ev(`(() => { const p = ${sc}; if (p.scrollHeight <= p.clientHeight + 40) return null; p.scrollTop = Math.round((p.scrollHeight - p.clientHeight) / 2); return p.scrollTop; })()`);
      check(mid > 20, `${tag}: #1120 the panel scrolls (${mid})`);
      let n0 = await ev(`document.querySelectorAll('#d-tl-items .cm').length`);
      await bobSays();
      for (let i = 0; i < 40 && await ev(`document.querySelectorAll('#d-tl-items .cm').length`) === n0; i++) await sleep(300);
      await sleep(600);
      let s = await ev(`(() => ({top: ${sc}.scrollTop, n: document.querySelectorAll('#d-tl-items .cm').length}))()`);
      check(s.n === n0 + 1 && Math.abs(s.top - mid) <= 2, `${tag}: #1120 a new comment keeps the panel where it was ` + JSON.stringify({mid, ...s}));
      await ev(`(() => { document.activeElement?.blur(); renderDetail(); return 1; })()`); await sleep(200);
      s = await ev(`${sc}.scrollTop`);
      check(Math.abs(s - mid) <= 2, `${tag}: #1120 a rebuild keeps the panel where it was ${mid} -> ${s}`);
      await ev(`(() => { const p = ${sc}; p.scrollTop = p.scrollHeight; return 1; })()`); await sleep(200);
      n0 = await ev(`document.querySelectorAll('#d-tl-items .cm').length`);
      await bobSays();
      for (let i = 0; i < 40 && await ev(`document.querySelectorAll('#d-tl-items .cm').length`) === n0; i++) await sleep(300);
      await sleep(600);
      s = await ev(`(() => { const p = ${sc}; return {gap: Math.round(p.scrollHeight - p.clientHeight - p.scrollTop), n: document.querySelectorAll('#d-tl-items .cm').length}; })()`);
      check(s.n === n0 + 1 && s.gap <= 4, `${tag}: #1120 at the end: still at the end with the new comment ` + JSON.stringify(s));
    }, true);
  }

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
