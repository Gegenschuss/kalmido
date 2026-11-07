// 2.622.0 A (#4948) UI test, own container (start.sh), Firefox on a phone (390 x 780, touch): the system Back (Android's key /
// kalmido-suite: fresh
// gesture = a step back in the browser history, here browsingContext.traverseHistory, NOT the Back button in the task's head)
// after a comment. "Waiting for me" -> a task (a row far down, the list scrolled) -> a comment typed, a person picked from the
// @ suggestions, sent -> ONE Back closes the task and shows "Waiting for me" at the same place, a second Back the view before.
// The same walk without a comment and with a plain comment (no suggestions). Invented names only.
// freelancer-matrix: tasks (alice's own lists; the mention needs a second person on the list)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2622_a_backcomment_ui', check, shots: 'P2622A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); if (!r.ok) console.log('call failed', method, url, r.status); return r.json().catch(() => ({})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {features: 'agents,comments,collab', lang: 'en', tour: 'done'});
  const me = (await call('GET', '/api/state')).me.id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bobby Baker', password: 'password123'})).id;
  const L = (await call('POST', '/api/lists', {name: 'Release'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: BOB, role: 'edit'});
  const T = [];
  for (let i = 0; i < 30; i++) {
    const id = (await call('POST', '/api/tasks', {title: `Review step ${String(i).padStart(2, '0')}`, list_id: L})).id;
    await call('POST', `/api/tasks/${id}/review`, {action: 'request', reviewer_id: me});
    T.push(id);
  }
  check((await call('GET', '/api/inbox')).counts?.review === 30, 'setup: 30 reviews wait for alice');

  await firefox(async o => {
    const {cmd, ev, ctx, until, idle, shot} = o;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 780}});
    const HS = `JSON.stringify({len: history.length, st: history.state, hash: location.hash, sel: S.sel || null, ov: typeof f8d_open === 'function' ? f8d_open() : '?', fo: document.activeElement?.id || document.activeElement?.tagName})`;
    const TR = [];  // the history at each step, printed as one line at the end (the runner shows the last lines only)
    const log = async what => TR.push(`${what} ${await ev(HS)}`);
    // a tap at the element's middle where it stands now (no scrolling first: the list's place is what the test is about)
    const tap = async sel => {
      const p = await ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e) return null; const r = e.getBoundingClientRect(); return {x: Math.round(r.left + r.width / 2), y: Math.round(r.top + r.height / 2)}; })()`);
      if (!p) return false;
      TR.push(`tap ${sel} on ${await ev(`(() => { const h = document.elementFromPoint(${p.x}, ${p.y}); return h ? h.tagName + '#' + h.id + '.' + h.className : '-'; })()`)}`);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'tp', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: p.x, y: p.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx});
      return true;
    };
    const type = async text => { await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'kb', actions: [...text].flatMap(c => [{type: 'keyDown', value: c}, {type: 'keyUp', value: c}])}]}); await cmd('input.releaseActions', {context: ctx}); };
    const back = () => cmd('browsingContext.traverseHistory', {context: ctx, delta: -1});

    // the rows stand newest first: T[0] is the last one. walk: 'none' = only open and Back, 'plain' = a comment, 'mention' = a comment with a person picked from the suggestions
    const walk = async (mode, idx) => {
      const tag = `${mode}:`, tid = T[idx], title = `Review step ${String(idx).padStart(2, '0')}`;
      // a fresh page per walk (the app keeps the open task over a reload: the stored state goes, the login stays)
      await o.nav(B + 'static/icon.svg'); await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await o.nav(B + '#today'); await idle();
      check(await until(`!S.sel && location.hash === '#today'`), tag + ' Today without an open task');
      await ev(`(location.hash = 'mine_wait', 1)`);
      check(await until(`[...document.querySelectorAll('#view .mwg a.mwa')].length >= 30`), tag + ' "Waiting for me" lists the 30 reviews');
      // the row far down, the list scrolled so it stands in the middle
      const y0 = await ev(`(() => { const a = [...document.querySelectorAll('#view .mwg a.mwa')].find(x => x.textContent.includes(${JSON.stringify(title)})); a.scrollIntoView({block: 'center'}); return document.querySelector('#view').scrollTop; })()`);
      check(y0 > 150, `${tag} the list is scrolled (${y0})`);
      await sleep(50);  // a touch tap right after the scroll: the scroll has settled in the frame before
      await log(tag + ' list');
      check(await tap(`#view .mwg a.mwa[href="#t/${tid}"]`), tag + ' the row is tapped');
      check(await until(`S.sel === ${tid} && !!document.querySelector('#detail.open #c-input')`), tag + ' the task is open with its comment box');
      await idle();
      await log(tag + ' open');
      if (mode !== 'none') {
        await ev(`(() => { const i = document.querySelector('#c-input'); i.scrollIntoView({block: 'center'}); return 1; })()`);
        check(await tap('#c-input'), tag + ' the comment box is tapped');
        // a tap of Firefox's touch emulation does not always move the focus (a finger on a phone does): then the box gets it here
        if (!await until(`document.activeElement?.id === 'c-input'`, {timeout: 1500})) await ev(`(document.querySelector('#c-input').focus(), 1)`);
        check(await until(`document.activeElement?.id === 'c-input'`), tag + ' the comment box has the focus');
        await type(mode === 'mention' ? 'Looks fine @Bob' : 'Looks fine to me');
        if (mode === 'mention') {
          check(await until(`!!document.querySelector('#detail .mpick:not(.hidden) [data-act="mention-pick"]')`), tag + ' the @ suggestions are open');
          await log(tag + ' suggestions');
          check(await tap('#detail .mpick:not(.hidden) [data-act="mention-pick"]'), tag + ' a person is picked');
          check(await until(`/@Bobby Baker /.test(document.querySelector('#c-input').value)`), tag + ' the name is in the box');
          await type('thanks');
        }
        await log(tag + ' typed');
        check(await tap('#detail [data-act="c-send"]'), tag + ' Send is tapped');
        check(await until(`!!(S.tl.comments || []).some(c => /Looks fine/.test(c.body)) && !document.querySelector('#detail .cmpend')`), tag + ' the comment is saved');
        await idle();
        await log(tag + ' sent');
        await shot(`p2622a-${mode}-sent.png`);
      }
      // the first system Back: the task closes, "Waiting for me" at the same place
      await back();
      const closed = await until(`!S.sel && location.hash === '#mine_wait' && !!document.querySelector('#view .mwg')`);
      await log(tag + ' back 1');
      check(closed, `${tag} ONE Back closes the task and shows "Waiting for me" (${await ev(HS)})`);
      await until(`Math.abs(document.querySelector('#view').scrollTop - ${y0}) < 40`, {timeout: 3000});
      const y1 = await ev(`document.querySelector('#view').scrollTop`);
      check(Math.abs(y1 - y0) < 40, `${tag} the list stands where it was (${y0} -> ${y1})`);
      await sleep(300);  // no late step: the panel stays closed
      check(await ev(`!S.sel && location.hash === '#mine_wait'`), `${tag} the task stays closed (${await ev(HS)})`);
      // the second Back: the view before
      await back();
      const prev = await until(`location.hash === '#today' && !S.sel`);
      await log(tag + ' back 2');
      check(prev, `${tag} the second Back shows the view before (${await ev(HS)})`);
    };
    await walk('none', 2);
    await walk('plain', 4);
    await walk('mention', 6);
    console.log('p2622a trace: ' + TR.join(' | '));
  }, true);

  console.log(`p2622_a_backcomment_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
