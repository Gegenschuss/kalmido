// 2.30.0 small UI fixes, own container (start.sh), Firefox on a phone (390 x 844, touch):
// #1043 a dialog opened from the folder menu in the drawer (Folder settings…, Share folder…): after Cancel / Done the
//       drawer has its scrim again (or is closed), a tap next to it closes only the drawer and never opens the task behind
// #1044 (a) "Share folder": the person's name and "new lists too" are not cut; (b) a person who has the folder already is not
//       offered again under "Person" (nobody left = no add row); (d) the agent chat keeps its side margin when iOS pushes
//       the page up for the keyboard (.chview.vvfix); (e) a one-time hint's dismiss X does not stretch the text's lines
// #1042 the copy button of a code block (chat bubble, task description) never covers the code's text, a touch target
// #1033 the quick-add sheet has no clip / square explanation any more (the example line stays), both buttons are labelled
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2300_ui_fixes', check, shots: 'P2300_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,family,team';
const V = B + 'api/v1';
const LONG = 'cd ~/bin && ./devlist.py show 362 --with-comments --format markdown --output /tmp/a-very-long-path/that/keeps/going/and/going.md';
// no text rect of the code block's first lines under its copy button (the button's own box, 1 px tolerance)
const NOOVER = sel => `(() => { const box = document.querySelector('${sel}'); if (!box) return 'no code block'; const pre = box.querySelector('pre'), b = box.querySelector('.mdcopy');
  const br = b.getBoundingClientRect(), pr = pre.getBoundingClientRect(), rg = document.createRange(); rg.selectNodeContents(pre);
  // only what is visible: text scrolled out of the pre's box is clipped by it
  const vis = [...rg.getClientRects()].map(r => ({left: Math.max(r.left, pr.left), right: Math.min(r.right, pr.right), top: Math.max(r.top, pr.top), bottom: Math.min(r.bottom, pr.bottom)})).filter(r => r.right > r.left && r.bottom > r.top);
  const hit = vis.filter(r => r.right > br.left + 1 && r.left < br.right - 1 && r.bottom > br.top + 1 && r.top < br.bottom - 1);
  return {hit: hit.length, w: Math.round(br.width), h: Math.round(br.height), wrap: pre.scrollWidth <= pre.clientWidth + 1}; })()`;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker-Bartholomew', password: 'password123'})).id;
  const CAR = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  await call('PATCH', '/api/settings', {folders: '["Clients"]'});
  const C1 = (await call('POST', '/api/lists', {name: 'Client A', folder: 'Clients', org_id: null})).id;
  await call('POST', '/api/lists', {name: 'Client B', folder: 'Clients', org_id: null});
  const share = await call('PUT', '/api/folders/people', {folder: 'Clients', user_id: BOB, role: 'edit'});
  check(share.status === 200, '#1044 setup: the folder is shared with Bob ' + share.status);
  // tasks in today's view: the area next to the drawer is full of task rows
  for (let i = 0; i < 12; i++) await call('POST', '/api/tasks', {title: 'Row behind the drawer ' + (i + 1), list_id: C1, due: new Date().toISOString().slice(0, 10)});
  const TD = (await call('POST', '/api/tasks', {title: 'Task with code', list_id: C1, content: 'Run this:\n\n```\n' + LONG + '\n```\n\nThen go on.'})).id;
  const AGL = (await call('POST', '/api/lists', {name: 'With the agent'})).id;  // the agent is reachable for Alice through a shared list
  await call('PUT', `/api/lists/${AGL}/members`, {user_id: AG, role: 'edit'});
  const cm = await fetch(V + '/agent/chats/1', {method: 'POST', headers: AGH, body: JSON.stringify({body: 'Please run:\n```\n' + LONG + '\n```\nAnd tell me.'})});
  check(cm.ok, '#1042 setup: the agent wrote into the chat ' + cm.status);

  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const wait = async (ev, js, n = 30) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(200); } return false; };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    const tap = async (x, y) => {
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 't', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x, y}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx}); await sleep(600);
    };
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#today'); await ready(ev);

    // ================= #1043 dialogs from the folder menu in the drawer
    for (const [item, close, name] of [[/Folder settings/, '[data-m="close"]', 'folder-settings'], [/Share folder/, '[data-m="close"]', 'share-folder']]) {
      await ev(`(() => { closeSide(); closePop(); document.querySelector('#top [data-act="side"]').click(); return 1; })()`);
      check(await wait(ev, `!!document.querySelector('#side.open') && !document.querySelector('#scrim').classList.contains('hidden')`), `${tag}: #1043 the drawer opens with its scrim (${name})`);
      await sleep(400);
      await ev(`(() => { document.querySelector('#side .fhead[data-folder="Clients"] [data-act="folder-menu"]').click(); return 1; })()`);
      await wait(ev, `!!document.querySelector('#pop:not(.hidden) [role="menuitem"]')`);
      await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(x => ${item}.test(x.textContent)).click(); return 1; })()`);
      check(await wait(ev, `!!document.querySelector('.modal ${close}')`), `${tag}: #1043 the dialog opens (${name})`);
      await sleep(500);
      if (name === 'share-folder') {
        // #1044 (a) + (b) while the dialog is open
        const fp = await ev(`(() => { const md = document.querySelector('.modal'); const n = md.querySelector('.fpl .mrow .n'); if (!n) return null; const kids = [...n.children];
          return {cut: kids.filter(k => k.scrollWidth > k.clientWidth + 1).length, kids: kids.length, txt: n.textContent, wide: document.documentElement.scrollWidth,
            opts: [...md.querySelectorAll('#fp-user option')].map(o => +o.value)}; })()`);
        check(fp && fp.kids === 2 && fp.cut === 0 && /new lists too/.test(fp.txt) && fp.wide <= 390, `${tag}: #1044 (a) name and "new lists too" not cut ` + JSON.stringify(fp));
        check(fp && !fp.opts.includes(BOB) && fp.opts.includes(CAR), `${tag}: #1044 (b) Bob (has the folder) is not offered again, Carol is ` + JSON.stringify(fp && fp.opts));
        await shot('p2300-390-share-folder.png');
        await ev(`(() => { const md = document.querySelector('.modal'); md.querySelector('#fp-user').value = '${CAR}'; md.querySelector('[data-m="add"]').click(); return 1; })()`);
        check(await wait(ev, `document.querySelectorAll('.modal .fpl .mrow').length === 2 && document.querySelector('.modal #fp-user').closest('.row').hidden && !document.querySelector('.modal #fp-user option')`),
          `${tag}: #1044 (b) nobody left to add: the "Person" row goes`);
      } else await shot('p2300-390-folder-settings.png');
      await ev(`(() => { document.querySelector('.modal ${close}').click(); return 1; })()`);
      await wait(ev, `!document.querySelector('.modal')`); await sleep(500);
      const st = await ev(`({open: !!document.querySelector('#side.open'), scrim: !document.querySelector('#scrim').classList.contains('hidden')})`);
      check(!st.open || st.scrim, `${tag}: #1043 after the dialog (${name}) the drawer is closed or dimmed again ` + JSON.stringify(st));
      if (st.open) await shot(`p2300-390-after-${name}.png`);
      // a tap next to the drawer: closes the drawer only, no task opens
      const el = await ev(`(() => { const e = document.elementFromPoint(370, 520); return e ? (e.id || e.className || e.tagName) : null; })()`);
      if (st.open) check(/scrim|sidesearch/.test(String(el)), `${tag}: #1043 next to the drawer is the scrim (${name}) ` + el);
      await tap(370, 520);
      const after = await ev(`({open: !!document.querySelector('#side.open'), sel: S.sel || null, detail: !!document.querySelector('#app.detail-open')})`);
      check(!after.open && !after.sel && !after.detail, `${tag}: #1043 the tap next to the drawer closed it and opened no task (${name}) ` + JSON.stringify(after));
    }

    // ================= #1033 quick-add sheet
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { openQuickSheet(); return 1; })()`);
    await wait(ev, `!!document.querySelector('.qadd.sheet #qsheet')`); await sleep(500);
    const q = await ev(`(() => { const s = document.querySelector('.qadd.sheet'); const lab = b => !!b && !!b.getAttribute('title') && !!b.getAttribute('aria-label');
      return {hint: !!s.querySelector('[data-hint="qbtns"]') || /clip adds the task/.test(s.textContent), ex: !!s.querySelector('.qhint'), clip: lab(s.querySelector('[data-act="q-clip"]')), open: lab(s.querySelector('[data-act="q-open"]'))}; })()`);
    check(q && !q.hint && q.ex && q.clip && q.open, `${tag}: #1033 no clip / square explanation, example line stays, both buttons labelled ` + JSON.stringify(q));
    await shot('p2300-390-quick-add.png');
    await ev(`(() => { closePop(); return 1; })()`); await sleep(300);

    // ================= #1044 (e) a one-time hint: the dismiss X sits next to the text, the lines stay close
    const hl = await ev(`(() => { const d = document.createElement('div'); d.style.width = '300px'; d.innerHTML = hintOnce('p2300test', 'A one-time hint with a text long enough to wrap onto a second and maybe a third line on a phone screen.');
      document.querySelector('#view').prepend(d); const sp = d.querySelector('.mhint.once > span'); if (!sp) return null; const rg = document.createRange(); rg.selectNodeContents(sp);
      const tops = [...new Set([...rg.getClientRects()].filter(r => r.width > 0).map(r => Math.round(r.top)))].sort((a, b) => a - b);
      const fs = parseFloat(getComputedStyle(sp).fontSize), gaps = tops.slice(1).map((t, i) => t - tops[i]); d.remove();
      return {lines: tops.length, maxGap: Math.max(0, ...gaps), fs}; })()`);
    check(hl && hl.lines >= 2 && hl.maxGap <= hl.fs * 1.7, `${tag}: #1044 (e) the hint's lines stay close together ` + JSON.stringify(hl));

    // ================= #1042 code block in the task description
    await o.nav(B + '#today/t/' + TD); await sleep(1500);
    await ev(`(() => { if (!S.sel) openDetail(${TD}); return 1; })()`);
    if (await wait(ev, `!!document.querySelector('#detail .md .mdcode .mdcopy')`, 20)) {
      const d = await ev(NOOVER('#detail .md .mdcode'));
      check(d && d.hit === 0 && d.w >= 32 && d.h >= 32, `${tag}: #1042 the copy button does not cover the description's code ` + JSON.stringify(d));
      await shot('p2300-390-task-code.png');
    } else check(false, `${tag}: #1042 the description shows the code block with its copy button`);

    // ================= #1042 + #1044 (d) agent chat
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(900);
    if (!await wait(ev, `!!document.querySelector('.cbub .mdcode .mdcopy')`)) console.log('chat:', await ev(`location.hash + ' | ' + document.querySelectorAll('.cbub').length + ' | ' + (document.querySelector('#view')?.textContent || '').slice(0, 300)`));
    const c = await ev(NOOVER('.cbub .mdcode'));
    check(c && c.hit === 0 && c.w >= 32 && c.h >= 32 && c.wrap, `${tag}: #1042 the copy button does not cover the chat code, wraps, touch size ` + JSON.stringify(c));
    check(await ev(`(() => { const b = document.querySelector('.cbub .mdcopy'); return !!b && getComputedStyle(b).backgroundColor !== 'rgba(0, 0, 0, 0)'; })()`), `${tag}: #1042 the copy button has its own background`);
    await shot('p2300-390-chat-code.png');
    const dx = await ev(`(async () => { const v = document.querySelector('#view .chview'), cp = v.querySelector('.chcomp') || v; const a = cp.getBoundingClientRect().left;
      v.classList.add('vvfix'); await new Promise(r => setTimeout(r, 400)); const cs = getComputedStyle(v), b = cp.getBoundingClientRect().left, r = {a: Math.round(a), b: Math.round(b), pl: cs.paddingLeft, cls: v.className, pos: cs.position, disp: cs.display, bs: cs.boxSizing, w: v.clientWidth}; v.classList.remove('vvfix'); return r; })()`);
    check(dx && Math.abs(dx.a - dx.b) <= 1 && dx.a > 4, `${tag}: #1044 (d) the chat keeps its side margin with the keyboard up (vvfix) ` + JSON.stringify(dx));
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
