// 2.622.0 A (#4946) UI test, own container (start.sh), Firefox: the agent chat on a phone runs edge to edge like the tab bar -
// kalmido-suite: fresh
// its header (.chath) and the composer (.chcomp) are as wide as the screen (320 and 412 px, touch), the messages keep a padding
// at both sides; the desktop layout (840 and 960 px, mouse; from 1000 px the chat is a side panel) since 2.1081.0 (#5903) fills the
// view's width as well (no side padding), the messages in a reading column with a padding.
// Invented names only. freelancer-matrix: agents (alice without an organisation chats with her agent)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2622_a_chatedge_ui', check, shots: 'P2622A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); if (!r.ok) console.log('call failed', method, url, r.status); return r.json().catch(() => ({})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {features: 'agents,comments,collab', lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'helper', display_name: 'Helper'});
  check(ag.id && ag.token, 'setup: an agent');
  const L = (await call('POST', '/api/lists', {name: 'Website'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const say = body => fetch(B + `api/v1/agent/chats/${ME}`, {method: 'POST', headers: {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'}, body: JSON.stringify({body})});
  for (let i = 0; i < 3; i++) await say(`An answer of the helper, number ${i + 1}, long enough to fill the row of a narrow phone screen`);

  const M = `JSON.stringify((() => { const r = s => { const e = document.querySelector(s); if (!e) return null; const b = e.getBoundingClientRect(); return {l: Math.round(b.left), r: Math.round(b.right), w: Math.round(b.width)}; };
    const m = [...document.querySelectorAll('#chat-msgs .cmsg.ag')].pop(), mb = m && m.getBoundingClientRect(), v = document.querySelector('#view');
    return {vw: document.documentElement.clientWidth, view: r('#view'), padL: v ? parseFloat(getComputedStyle(v).paddingLeft) : null, chview: r('#view .chview'), head: r('#view .chview .chath'), comp: r('#view .chview .chcomp'),
      msg: mb ? {l: Math.round(mb.left), r: Math.round(mb.right)} : null, sx: document.documentElement.scrollWidth,
      kids: [...(document.querySelector('#view .chview')?.children || [])].map(e => e.className).join(' / ').slice(0, 300), txt: (document.querySelector('#view .chview')?.textContent || '').slice(0, 160)}; })())`;
  for (const [wd, ht, touch] of [[320, 640, true], [412, 860, true], [840, 900, false], [960, 900, false]]) {
    await firefox(async o => {
      const {cmd, ev, ctx, until, idle, shot} = o, tag = `${wd}:`;
      await o.nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"dark"'); return 1; })()`);
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, tag + ' login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
      await o.nav(B + '#agents/' + ag.id); await idle();
      check(await until(`document.querySelectorAll('#view .chview #chat-msgs .cmsg.ag').length >= 3 && !!document.querySelector('#view .chview .chcomp #chat-in')`), tag + ' the chat with its messages is open in the page');
      await sleep(100);  // the chat's own height fit runs in the frame after the draw
      const g = JSON.parse(await ev(M));
      if (!g.head || !g.comp || !g.msg) { check(false, tag + ' measured ' + JSON.stringify(g)); return; }
      if (wd < 768) {
        check(g.head.l === 0 && g.head.w === g.vw, `${tag} the header reaches both edges (${JSON.stringify(g.head)}, screen ${g.vw})`);
        check(g.comp.l === 0 && g.comp.w === g.vw, `${tag} the composer reaches both edges (${JSON.stringify(g.comp)}, screen ${g.vw})`);
        check(g.msg.l >= 8 && g.msg.r <= g.vw - 8, `${tag} the messages keep a padding at both sides (${JSON.stringify(g.msg)})`);
        check(g.sx <= g.vw, `${tag} nothing sticks out sideways (${g.sx} > ${g.vw})`);
      } else {
        // 2.1081.0 (#5903): from 768 px the chat fills #view edge to edge too (no side padding any more, open Fold / tablet);
        // header and composer as wide as the chat, the messages stay in a reading column (46rem) in the middle with a padding
        check(g.padL === 0, `${tag} #view has no side padding in the chat (${g.padL})`);
        check(Math.abs(g.chview.l - g.view.l) <= 1 && g.chview.w >= g.view.w - 20, `${tag} the chat fills the view's width (${JSON.stringify(g.chview)} in ${JSON.stringify(g.view)})`);
        check(g.head.w === g.chview.w && g.comp.w === g.chview.w, `${tag} header and composer as wide as the chat (${g.head.w}, ${g.comp.w}, ${g.chview.w})`);
        check(g.msg.l >= g.chview.l + 8 && g.msg.r <= g.chview.r - 8, `${tag} the messages keep a padding at both sides (${JSON.stringify(g.msg)})`);
        check(g.msg.r - g.msg.l <= 736 + 1, `${tag} the messages stay within the reading width (${JSON.stringify(g.msg)})`);
        check(g.sx <= g.vw, `${tag} nothing sticks out sideways (${g.sx} > ${g.vw})`);
      await shot(`p2622a-chat-${wd}.png`);
    }, touch);
  }

  console.log(`p2622_a_chatedge_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
