// kalmido-suite: fresh
// 2.854.0 A UI tests (Firefox): #5508 the agent chat's live interim status ("steps") on a narrow screen (360 px): a long status
// wraps (more than one line, at most 3, then it is cut), a tap opens the whole text and closes it again, the block keeps its height
// while a new status arrives (the message list does not jump); on a wide screen (1280 px) the status stays one line.
// Screenshots into $P2854A_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2854_a_ui', check, shots: 'P2854A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,agents';
const LONG = 'LONGSTART I read the failing test, found that the helper builds the query twice, and now I am rewriting the loader so that '
  + 'the second pass reuses the first result; after that I will run the narrow suite again and compare the timings before and after '
  + 'the change, then write down what I found in the task so that nothing gets lost LONGEND';  // the server keeps about 200 characters of a status: the text ends with a dots character, never LONGEND

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Team list'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const v1 = async (method, url, body) => { const x = await fetch(B + 'api/v1' + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined}); return {...(await x.json().catch(() => ({}))), status: x.status}; };
  for (let i = 0; i < 12; i++) await v1('POST', `/agent/chats/${ME.id}`, {body: `Line ${i + 1}: ` + 'some words of a longer answer '.repeat(2)});
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const progress = async text => { await v1('POST', '/agent/typing', {chat_user_id: ME.id}); await v1('POST', '/agent/progress', {chat_user_id: ME.id, text}); };
  // geometry of the live block: the first (newest) status, the block, the last message of the list
  const geo = `(() => { const q = s => document.querySelector(s), c = q('#chat-steps .chstep'), l = q('#chat-steps .chstepl'), ms = [...document.querySelectorAll('#chat-msgs .cmsg')], m = ms[ms.length - 1];
    if (!c || !l || !m) return null; const cs = getComputedStyle(c), lh = parseFloat(cs.lineHeight) || 16;
    return {h: Math.round(c.getBoundingClientRect().height), lh: Math.round(lh), sh: c.scrollHeight, ch: c.clientHeight, block: Math.round(l.getBoundingClientRect().height),
      mt: Math.round(m.getBoundingClientRect().top), n: document.querySelectorAll('#chat-steps .chstep').length, older: q('#chat-steps .chstep + .chstep') ? getComputedStyle(q('#chat-steps .chstep + .chstep')).display : '-',
      clamp: cs.webkitLineClamp || cs.getPropertyValue('-webkit-line-clamp'), ws: cs.whiteSpace, open: !!q('#chat-steps.open'), txt: c.textContent}; })()`;
  const calm = `!document.getAnimations?.().some(a => a.playState === 'running')`;  // the status's entry animation is over
  const first = text => `(() => { const c = document.querySelector('#chat-steps .chstep'); return !!c && c.textContent.includes(${JSON.stringify(text)}); })()`;

  for (const [wd, tag] of [[360, '360'], [1280, '1280']]) {
    await firefox(async o => {
      const {cmd, ev, ctx} = o;
      check(await ffLogin(o) === 200, `${tag}: login`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: 800}});
      await o.nav(B + '#agents/' + AG);
      check(await o.until(`!!document.querySelector('#chat-msgs .cmsg') && !!document.querySelector('#chat-steps')`, {timeout: 20000}), `${tag}: the agent chat is up`);
      await progress('Reading the tests first');
      await ev(`chatLoad().then(() => 1)`);
      check(await o.until(first('Reading the tests first'), {timeout: 8000}), `${tag}: the first status shows`);
      await o.until(calm, {timeout: 5000});
      const g0 = await ev(geo);
      await progress(LONG);
      await ev(`chatLoad().then(() => 1)`);
      check(await o.until(first('LONGSTART'), {timeout: 8000}), `${tag}: the long status is the newest line`);
      await o.until(calm, {timeout: 5000});
      const g1 = await ev(geo);
      if (wd < 640) {
        check(g1 && g1.h > g1.lh * 1.5, `${tag} #5508: the long status wraps, more than one line ` + JSON.stringify(g1));
        check(g1 && g1.h <= g1.lh * 3.2 && g1.sh > g1.ch + 1 && g1.clamp === '3', `${tag} #5508: at most 3 lines, the rest is cut ` + JSON.stringify(g1));
        check(g0 && g1 && g1.block === g0.block && g1.mt === g0.mt, `${tag} #5508: the block keeps its height, the message list does not jump ` + JSON.stringify([g0, g1]));
        check(g1 && g1.older === 'none', `${tag} #5508: older lines wait until opened ` + JSON.stringify(g1.older));
        await o.shot('p2854a-5508-360-closed.png');
        await ev(`document.querySelector('#chat-steps .chstepl').click()`);
        await o.until(`!!document.querySelector('#chat-steps.open')`, {timeout: 5000});
        const g2 = await ev(geo);
        check(g2 && g2.open && g2.h >= g2.sh - 1 && g2.h > g2.lh * 3.2 && g2.older !== 'none', `${tag} #5508: a tap shows the whole text ` + JSON.stringify(g2));
        check(await ev(`!!document.querySelector('#chat-steps .chstepl')`), `${tag} #5508: the steps are still there (a tap did not hide them)`);
        await o.shot('p2854a-5508-360-open.png');
        await progress('A third status while opened');
        await ev(`chatLoad().then(() => 1)`);
        check(await o.until(first('A third status'), {timeout: 8000}), `${tag}: a new status while opened`);
        check(await ev(`!!document.querySelector('#chat-steps.open')`), `${tag} #5508: it stays opened with a new status`);
        await ev(`document.querySelector('#chat-steps .chstepl').click()`);
        await o.until(`!document.querySelector('#chat-steps.open')`, {timeout: 5000});
        const g3 = await ev(geo);
        check(g3 && !g3.open && g3.h <= g3.lh * 3.2, `${tag} #5508: a second tap closes it again ` + JSON.stringify(g3));
      } else {
        check(g1 && g1.h <= g1.lh * 1.5 && g1.ws === 'nowrap' && g1.older !== 'none', `${tag} #5508: wide screens stay one line, older lines shown ` + JSON.stringify(g1));
        await o.shot('p2854a-5508-1280.png');
      }
    }, undefined);
  }
  console.log(`p2854_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
