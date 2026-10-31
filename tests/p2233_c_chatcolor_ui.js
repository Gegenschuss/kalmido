// 2.233.0 C (#3196): the chat bubble colours of people / agents (Settings > Appearance > Chat): the choice paints the bubbles of
// that kind only (own messages keep the accent), "Default" = no change, the choice is saved in the account (all devices).
// freelancer-matrix: settings  (the person has no organisation; the existing look route is used, no new route)
// Own container (start.sh), Firefox. P2233C_NOSTART=1 = the container is running.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2233_c_chatcolor_ui', check, shots: 'P2233C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2233C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const ck = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: ck}, body: JSON.stringify({lang: 'en', tour: 'done'})});
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // three bubbles with the real classes of agentchat.js / chat.js: a person, an agent, me; the colours as rgb triples
  const probe = `(() => { let h = document.getElementById('cc-probe'); if (!h) { h = document.createElement('div'); h.id = 'cc-probe'; h.className = 'chmsgs';
      h.innerHTML = '<div class="cmsg ag"><div class="cbub">p</div></div><div class="cmsg ag agc"><div class="cbub">a</div></div><div class="cmsg me"><div class="cbub">m</div></div>'; document.body.appendChild(h); }
    const c = s => { const v = getComputedStyle(h.querySelector(s + ' .cbub')).backgroundColor, n = v.match(/[\\d.]+/g).slice(0, 3).map(Number); return v.startsWith('color(') ? n.map(x => Math.round(x * 255)) : n; };  // Firefox answers color-mix() as color(srgb 0..1)
    return {h: c('.cmsg.ag:not(.agc)'), a: c('.cmsg.agc'), m: c('.cmsg.me'), attrs: [document.documentElement.dataset.chatHuman || '', document.documentElement.dataset.chatAgent || ''], vars: [document.documentElement.style.getPropertyValue('--chat-h-d'), getComputedStyle(document.documentElement).getPropertyValue('--chat-h')]}; })()`;
  const settle = async (ev, want) => { let d; for (let i = 0; i < 30; i++) { d = await ev(probe); if (want(d)) return d; await sleep(150); } return d; };  // waits for the state, not for a time
  const same = (x, y) => x.every((v, i) => Math.abs(v - y[i]) < 1);
  await firefox(async ({ev, ctx, nav, shot, cmd}) => {
    for (const theme of ['dark', 'light']) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
      await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.ok)`);
      await nav(B + '#news');
      check(await ready(ev, `typeof lookSet === 'function' && !!S.settings && !!document.querySelector('#kbar')`, 80), theme + ': the app is up');
      const d0 = await ev(probe);
      check(d0.attrs[0] === '' && d0.attrs[1] === '', theme + ': default = no attribute ' + JSON.stringify(d0.attrs));
      // people: orange, only the person's bubble changes
      await ev(`(() => { lookSet('chatHuman', 'orange'); return 1; })()`);
      const d1 = await settle(ev, d => !same(d.h, d0.h));
      check(d1.attrs[0] === 'orange' && !same(d1.h, d0.h) && d1.h[0] > d1.h[2], theme + ': the person bubble turns orange ' + JSON.stringify([d0.h, d1.h, d1.attrs, d1.vars]));
      check(same(d1.a, d0.a) && same(d1.m, d0.m), theme + ': the agent bubble and mine stay');
      // agents: sky, only the agent's bubble changes
      await ev(`(() => { lookSet('chatAgent', 'sky'); return 1; })()`);
      const d2 = await settle(ev, d => !same(d.a, d0.a));
      check(!same(d2.a, d0.a) && d2.a[2] > d2.a[0], theme + ': the agent bubble turns sky ' + JSON.stringify([d0.a, d2.a]));
      check(same(d2.h, d1.h) && same(d2.m, d0.m), theme + ': the person bubble keeps orange, mine stays');
      // the text stays the normal text colour (contrast)
      // the settings pane: two palettes + the preview with three bubbles
      const pane = await ev(`(() => { const d = document.createElement('div'); d.innerHTML = lkChatHtml(); return {g: d.querySelectorAll('.lkacc').length, pv: d.querySelectorAll('.lkcpv .cbub').length, on: [...d.querySelectorAll('.lkacc button.on')].map(b => b.dataset.v), n: d.querySelectorAll('#s-chatHuman button').length}; })()`);
      // 2.300.0 (#3198): default + 8 accents (petrol added)
      check(pane.g === 2 && pane.pv === 3 && pane.on.join() === 'orange,sky' && pane.n === 9, theme + ': settings block ' + JSON.stringify(pane));
      // back to default: the old look returns
      await ev(`(() => { lookSet('chatHuman', 'default'); lookSet('chatAgent', 'default'); return 1; })()`);
      const d3 = await settle(ev, d => same(d.h, d0.h) && same(d.a, d0.a));
      check(d3.attrs[0] === '' && d3.attrs[1] === '' && same(d3.h, d0.h) && same(d3.a, d0.a), theme + ': default = the old look again');
      if (theme === 'dark') await ev(`(() => { lookSet('chatHuman', 'violet'); lookSet('chatAgent', 'lime'); return 1; })()`);
    }
    // saved in the account: a second session (another device) reads it
    check(await ready(ev, `String((S.settings || {}).look || '').includes('"chatAgent"')`, 40), 'the look was sent to the account');
  }, false);
  const ck2 = await login('alice');
  let look = '';
  for (let i = 0; i < 20 && !look.includes('chatAgent'); i++) { const s = (await (await fetch(B + 'api/state', {headers: {...H, Cookie: ck2}})).json()).settings || {}; look = s.look || ''; if (!look.includes('chatAgent')) await sleep(500); }
  check(look.includes('"chatHuman"') && look.includes('"chatAgent"'), 'the second session sees both colours: ' + look);
  const bad = await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: ck2}, body: JSON.stringify({look: JSON.stringify({chatHuman: 'orange', evil: 'x'})})});
  const after = ((await (await fetch(B + 'api/state', {headers: {...H, Cookie: ck2}})).json()).settings || {}).look || '';
  check(bad.ok && after.includes('chatHuman') && !after.includes('evil'), 'the server keeps the new keys and drops unknown ones: ' + after);
  console.log(`p2233_c_chatcolor_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
