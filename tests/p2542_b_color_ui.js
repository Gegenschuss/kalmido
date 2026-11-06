// kalmido-suite: fresh
// 2.542.0 UI test, part B (#4604): in an agent's chat the agent's own colour wins over the workspace's accent (#4026). Own container
// (start.sh), Firefox 1280 px, light and dark.
// - an organisation with its colour (the whole interface in it, #4026), a team agent with its own colour: the chat header has the
//   stripe in the agent colour, Send and the box's frame on focus are the agent colour (fitted, its text >= 4.5:1), the box's frame
//   is tinted, the agent's bubbles are tinted deeper (36 % dark / 24 % light) with the text >= 4.5:1 for all 12 account colours;
//   the workspace stands in the header only as its dot + name; outside the chat the workspace's accent stays
// - a colour picked while the chat is open repaints Send at once
// - without a colour of its own: the chat keeps the workspace's accent, as before
// - the appearance choice "Messages from agents" (data-chat-agent) still overrides the bubbles, only when set
// - a person without an organisation (frida, her own agent): Send in the agent colour too
// freelancer-matrix: agents (frida has no organisation and chats with her agent)
// Screenshots: P2542BC_SHOTS.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2542_b_color_ui', check, shots: 'P2542BC_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
// '#rrggbb', 'rgb(r, g, b)' or Firefox's 'color(srgb r g b)' (0..1, what a color-mix() computes to)
const rgbOf = c => /^#/.test(c) ? [0, 2, 4].map(i => parseInt(c.slice(1).slice(i, i + 2), 16)) : /^color\(srgb/.test(c) ? (c.match(/[\d.]+/g) || []).slice(0, 3).map(v => +v * 255) : (c.match(/\d+(\.\d+)?/g) || []).slice(0, 3).map(Number);
const lum = c => { const l = rgbOf(c).map(v => v / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2]; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => m - n); return (y + 0.05) / (x + 0.05); };
const near = (a, b, d = 6) => { const x = rgbOf(a), y = rgbOf(b); return x.length === 3 && y.length === 3 && x.every((v, i) => Math.abs(v - y[i]) <= d); };
const FEAT = 'comments,collab,agents';
const AGCOL = '#cf3539';  // red: far from the organisation's yellow and from Kalmido's petrol
const AC = ['#3e63dd', '#f76b15', '#30a46c', '#a43cb4', '#cf3539', '#12a594', '#e2a336', '#c2307f', '#2aa7dc', '#8d5f3e', '#6e56cf', '#99b13a'];  // core.js AC_COLORS

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Studio', lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', ws_colors: '{}', features: FEAT});
  const ME = (await call(CA, 'GET', '/api/state')).me, ORG = ME.workspaces[0].id;
  check((await call(CA, 'PATCH', '/api/orgs/' + ORG, {color: '#e0b05c'})).http === 200, 'the organisation colour');
  await call(CA, 'PATCH', '/api/settings', {workspace: 'org:' + ORG});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Website', org_id: ORG, kind: 'project'})).id;
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude', org_id: ORG});
  check(ag.id && ag.token, 'a team agent ' + ag.http);
  const AG = ag.id;
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  check((await call(CA, 'PATCH', `/api/agents/${AG}/color`, {color: AGCOL})).http < 300, 'the agent\'s own colour');
  await call(CA, 'POST', `/api/agents/${AG}/chat`, {body: 'Hello, which colour do you wear?'});
  check((await tcall('POST', `/agent/chats/${ME.id}`, ag.token, {body: 'My own one: red, and the bubbles show it.'})).status < 300, 'the agent answers');
  // frida without an organisation, her own agent
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true});
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida Solo', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CF, 'GET', '/api/state')).me.workspaces || []).length, 'P4: frida has no organisation');
  const fa = await call(CF, 'POST', '/api/my/agents', {username: 'helper', display_name: 'Helper', scopes: ['read', 'write']});
  check(fa.id && fa.token, 'frida\'s agent ' + fa.http);
  check((await call(CF, 'PATCH', `/api/agents/${fa.id}/color`, {color: '#30a46c'})).http < 300, 'frida\'s agent colour');
  await call(CF, 'POST', `/api/agents/${fa.id}/chat`, {body: 'Hello'});

  const signIn = async (ev, nav, u) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`) === 200, `${u} signs in`);
  };
  // what the chat shows: Send (background, ink), the header's stripe, the box's frame, an agent bubble, the page's accent outside
  const LOOK = `(() => { const cs = e => e ? getComputedStyle(e) : null, s = cs(document.querySelector('#achat [data-act="chat-send"]')), h = cs(document.querySelector('#achat .chath')),
    t = document.querySelector('#chat-in'), b = cs(document.querySelector('#chat-msgs .cmsg.agc .cbub')), r = getComputedStyle(document.documentElement);
    return {send: s?.backgroundColor, ink: s?.color, head: h?.boxShadow, box: cs(t)?.borderTopColor, bub: b?.backgroundColor, text: b?.color,
      acc: r.getPropertyValue('--accent').trim(), loc: !!document.querySelector('#achat .chcomp.wac-loc'), ws: document.querySelector('#achat .chath .chws')?.textContent || '',
      dot: !!document.querySelector('#achat .chath .chws .wsp-dot'), main: cs(document.querySelector('#main .btn.pri, #top .btn.pri, #fab'))?.backgroundColor}; })()`;
  // the accent an element would get: a probe with background var(--accent) in the page (outside the chat) or inside it
  const ACC = where => `(() => { const p = document.createElement('i'); p.style.background = 'var(--accent)'; (${where}).appendChild(p); const c = getComputedStyle(p).backgroundColor; p.remove(); return c; })()`;
  const redraw = `(() => { const p = document.querySelector('#achat'); p.dataset.aid = ''; chatDraw(); return 1; })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
    await signIn(ev, nav, 'alice');
    await nav(B + '#l/' + L); await until(`!!document.querySelector('#top h1') && document.documentElement.classList.contains('wac-on')`, {timeout: 20000});
    await ev(`(() => { chatOpen(${AG}); return 1; })()`);
    check(await until(`!!document.querySelector('#achat #chat-msgs .cmsg.agc .cbub') && !!document.querySelector('#achat [data-act="chat-send"]')`, {timeout: 20000}), 'the chat is open');
    for (const theme of ['light', 'dark']) {
      await ev(`(() => { document.documentElement.dataset.theme = '${theme}'; return 1; })()`); await sleep(100);
      const fit = await ev(`(() => { const v = wac_agentVars('${AGCOL}').split(';').map(x => x.split(':')); return Object.fromEntries(v); })()`);
      const tone = theme === 'light' ? fit['--wal'] : fit['--wad'];
      // job/2919: the switch of the theme runs colour transitions - under load 100 ms were not enough (dark measured the light
      // tones): wait for the end state itself (no running transition, Send in the fitted tone), not a fixed time
      await until(`!document.getAnimations().length`, {timeout: 5000});
      let g = await ev(LOOK);
      for (let i = 0; i < 50 && !(g.loc && near(g.send, tone, 2)); i++) { await sleep(100); g = await ev(LOOK); }
      const out = await ev(ACC(`document.querySelector('#main') || document.body`));
      check(g.loc && near(g.send, tone, 2), `#4604 ${theme}: Send wears the agent colour (fitted ${tone}) ` + JSON.stringify(g));
      check(ratio(g.send, g.ink) >= 4.5, `#4604 ${theme}: text on Send >= 4.5:1 (${ratio(g.send, g.ink).toFixed(2)})`);
      check(!near(out, tone, 12) && near(out, await ev(ACC('document.body')), 2), `#4604 ${theme}: outside the chat the workspace's accent stays ${out}`);
      check(/3px/.test(g.head || '') && near((g.head.match(/rgba?\([^)]*\)/) || [''])[0], AGCOL, 4), `#4604 ${theme}: the header has the stripe in the agent colour ${g.head}`);
      check(g.box && !near(g.box, 'rgb(227, 227, 230)', 3) && !near(g.box, 'rgb(46, 48, 54)', 3), `#4604 ${theme}: the box's frame is tinted ${g.box}`);
      check(/Studio/.test(g.ws) && g.dot, `#4604 ${theme}: the workspace in the header as dot + name "${g.ws}"`);
      const mine = await ev(`getComputedStyle(document.querySelector('#chat-msgs .cmsg.me .cbub')).backgroundColor`), mineWant = await ev(`(() => { const p = document.createElement('i'); p.style.background = 'color-mix(in srgb,var(--accent) 20%,var(--bg3))'; document.body.appendChild(p); const c = getComputedStyle(p).backgroundColor; p.remove(); return c; })()`);
      check(near(mine, mineWant, 3) && !near(mine, g.bub, 10), `#4604 ${theme}: my own bubbles keep the workspace's accent, apart from the agent's ${mine} / ${g.bub}`);
      // the focus frame of the box: the agent's accent
      // (a headless window may have no focus: then the rule itself, the accent there is the agent's)
      await ev(`(() => { document.querySelector('#chat-in').focus(); return 1; })()`); await sleep(50);
      const fb = await ev(`(() => { const t = document.querySelector('#chat-in'); return t.matches(':focus') ? getComputedStyle(t).borderTopColor : ''; })()`);
      const css = require('./boot').allCssSync();
      check(fb ? near(fb, tone, 2) : /\.chcomp\.agcol textarea:focus\{border-color:var\(--accent\)[;}]/.test(css) && near(await ev(ACC(`document.querySelector('#achat .chcomp')`)), tone, 2), `#4604 ${theme}: the box's frame on focus = the agent colour ${fb || '(rule)'}`);
      // deeper bubbles, readable for all 12 colours
      const worst = [];
      for (const c of AC) {
        await ev(`(() => { S.colors[${AG}] = '${c}'; return 1; })()`); await ev(redraw);
        const x = await ev(LOOK); const q = ratio(x.bub, x.text);
        if (!(q >= 4.5) || !x.loc || ratio(x.send, x.ink) < 4.5) worst.push(c + ' ' + q.toFixed(2) + ' ' + x.bub);
      }
      check(!worst.length, `#4604 ${theme}: agent bubbles and Send readable for all 12 account colours ` + worst.join(', '));
      const tint = await ev(`getComputedStyle(document.documentElement).getPropertyValue('--agent-tint-own').trim()`);
      check(tint === (theme === 'light' ? '24%' : '36%'), `#4604 ${theme}: the agent's bubbles tinted deeper ${tint}`);
      await ev(`(() => { S.colors[${AG}] = '${AGCOL}'; return 1; })()`); await ev(redraw);
      await shot(`p2542b-color-${theme}.png`);
    }
    await ev(`(() => { document.documentElement.dataset.theme = 'light'; return 1; })()`);
    // a colour picked while the chat is open (the palette of the agent's settings, account.js): Send follows at once
    const send0 = (await ev(LOOK)).send;
    await ev(`(() => { const b = document.createElement('button'); b.dataset.accol = '#3e63dd'; b.dataset.acwho = '${AG}'; document.body.appendChild(b); b.click(); return 1; })()`);
    const blue = await ev(`wac_agentVars('#3e63dd').split(';').find(x => x.startsWith('--wal:')).slice(6)`);
    // wait for the end state itself (the button's colour may pass through a transition under load), not the first change
    const sendBg = () => ev(`(() => { const s = document.querySelector('#achat [data-act="chat-send"]'); return s ? getComputedStyle(s).backgroundColor : ''; })()`);
    let sendNow = '';
    for (let i = 0; i < 100 && !(sendNow && near(sendNow, blue, 2)); i++) { sendNow = await sendBg(); if (!near(sendNow, blue, 2)) await sleep(100); }
    check(sendNow !== send0 && near(sendNow, blue, 2), '#4604: a colour picked while the chat is open repaints Send at once ' + sendNow + ' / ' + blue);
    await call(CA, 'PATCH', `/api/agents/${AG}/color`, {color: AGCOL});
    await ev(`(() => { S.colors[${AG}] = '${AGCOL}'; return 1; })()`); await ev(redraw);
    // the appearance choice "Messages from agents" overrides the bubbles (only when set)
    const before = (await ev(LOOK)).bub;
    await ev(`(() => { const r = document.documentElement; r.dataset.chatAgent = 'teal'; r.style.setProperty('--chat-a-l', '#0f766e'); r.style.setProperty('--chat-a-d', '#2dd4bf'); return 1; })()`); await sleep(50);
    const over = (await ev(LOOK)).bub;
    check(over !== before && near(over, await ev(`(() => { const p = document.createElement('i'); p.style.background = 'color-mix(in srgb,#0f766e 14%,var(--bg3))'; document.body.appendChild(p); const c = getComputedStyle(p).backgroundColor; p.remove(); return c; })()`), 3), `#4604: "Messages from agents" overrides the bubbles when set ${before} -> ${over}`);
    await ev(`(() => { const r = document.documentElement; delete r.dataset.chatAgent; r.style.removeProperty('--chat-a-l'); r.style.removeProperty('--chat-a-d'); return 1; })()`);
    // without a colour of its own: the workspace's accent as before (#4026)
    await ev(`(() => { S.colors[${AG}] = ''; return 1; })()`); await ev(redraw);
    const nc = await ev(LOOK), wsAcc = await ev(ACC('document.body'));
    check(!nc.loc && near(nc.send, wsAcc, 2), `#4604: without its own colour the chat keeps the workspace's accent ${nc.send} / ${wsAcc}`);
    await ev(`(() => { S.colors[${AG}] = '${AGCOL}'; return 1; })()`); await ev(redraw);

    // ================= frida without an organisation
    await signIn(ev, nav, 'frida');
    await nav(B + '#today'); await until(`!!document.querySelector('#top h1')`, {timeout: 20000});
    await ev(`(() => { chatOpen(${fa.id}); return 1; })()`);
    check(await until(`!!document.querySelector('#achat [data-act="chat-send"]')`, {timeout: 20000}), 'P4: frida\'s chat is open');
    const ff = await ev(LOOK), ftone = await ev(`wac_agentVars('#30a46c').split(';').find(x => x.startsWith('--wal:')).slice(6)`);
    check(ff.loc && near(ff.send, ftone, 2) && ratio(ff.send, ff.ink) >= 4.5 && !ff.ws, `#4604 P4: Send in her agent's colour, no workspace name without organisations ` + JSON.stringify(ff));
  }, false);

  console.log(`p2542_b_color_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
