// 2.1072.0 (#5860) UI test (Firefox, real layout): "Show me" under an agent's chat message (agentchat.js shw_btnHtml, showme.js)
// kalmido-suite: fresh
// freelancer-matrix: agents (frida has no organisation and a personal agent; alice an organisation's agent)
// Computer (1280 x 800, mouse): the agent's message with two steps (tasks.new, calendar.new) shows the button "Show me" on the
// screen, reachable (the point under its middle is the button); a press opens the first step's view (#today) and lays the
// spotlight on the control: the ring around it, the card with the agent's line and 1/2 on the screen, the control itself still
// takes a press (the layer lets it through); Next goes to #cal and rings "New event", Back comes back, Done on the last step ends
// it and stays there. Pressed again, Close (and Escape) goes back to where the button was pressed, the chat still there.
// Phone (390 x 844, touch): the chat is a page; a step whose control is not on the screen (settings.integrations: the settings
// are closed) says so in one line after its wait; Close goes back to the chat page. Nothing is clicked or saved: no dialog
// opened, the task box stays empty, no task / event more on the server. With P21072C_SHOTS: pictures of the spotlight.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21072_c_show_ui', check, shots: 'P21072C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEATS = 'cal,comments,collab,agents,office,clients,files,docs,events,time';

// (the waits below wait for the ring to lie on the control: it glides there in 0.25 s, app.css .tring transition)
// the spotlight as the person sees it: the step, its state, the ring, the card, the control of the step
const SPOT = `(() => { const el = document.querySelector('.spot'); if (!el) return null;
  const ring = el.querySelector('.tring'), card = el.querySelector('.tcard'), rr = ring.getBoundingClientRect(), cr = card.getBoundingClientRect();
  const on = r => r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.right > 0 && r.left < innerWidth;
  const st = SHW.steps[SHW.i], tg = shw_find(st.sel), tr0 = tg && tg.getBoundingClientRect();
  const inRing = !!tr0 && tr0.left >= rr.left - 1 && tr0.right <= rr.right + 1 && tr0.top >= rr.top - 1 && tr0.bottom <= rr.bottom + 1;
  const hit = tr0 ? document.elementFromPoint(tr0.left + tr0.width / 2, tr0.top + tr0.height / 2) : null;
  const miss = card.querySelector('.shw-miss'), mr = miss && miss.getBoundingClientRect();
  return JSON.stringify({i: SHW.i, state: el.dataset.state, target: el.dataset.target, hash: location.hash, ring: !ring.classList.contains('none') && on(rr), inRing,
    through: !!hit && (hit === tg || tg.contains(hit)), card: on(cr), h3: card.querySelector('h3')?.textContent || '', text: card.textContent.replace(/\\s+/g, ' '),
    miss: !!miss && on(mr), missLines: mr ? Math.round(mr.height / parseFloat(getComputedStyle(miss).lineHeight || '16')) : 0,
    btns: [...card.querySelectorAll('[data-shw]')].map(b => b.dataset.shw + ':' + b.textContent.trim()).join(',')}); })()`;
const BTN = id => `(() => { const b = document.querySelector('#chat-msgs .cmsg[data-mid="a:${id}"] [data-act="show-me"]'); if (!b) return null;
  b.scrollIntoView({block: 'nearest'}); const r = b.getBoundingClientRect(), hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  return JSON.stringify({text: b.textContent.trim(), on: r.width > 0 && r.height > 0 && r.top >= 0 && r.bottom <= innerHeight, hit: !!hit && (hit === b || b.contains(hit))}); })()`;

async function counts(ck) {
  const st = await call('GET', '/api/state', null, ck);
  const d0 = new Date(Date.now() - 60 * 864e5).toISOString().slice(0, 10), d1 = new Date(Date.now() + 120 * 864e5).toISOString().slice(0, 10);
  const ev = await call('GET', `/api/events?from=${d0}&to=${d1}`, null, ck);
  check(ev.http === 200 && Array.isArray(ev.items), 'the events of the calendar read ' + ev.http);
  return JSON.stringify({tasks: (st.tasks || []).length, events: (ev.items || []).length});
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  check((await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', tours_more: '0', features: FEATS})).http < 300, 'alice: modules on');
  const ME = (await call('GET', '/api/state')).me, ORG = ME.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'guide', display_name: 'Guide', org_id: ORG});
  const L = (await call('POST', '/api/lists', {name: 'Shown', org_id: ORG})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: ag.id, role: 'edit'});
  const u = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(u.http === 200 || u.http === 201, 'the freelancer ' + u.http);
  const fag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'fridabot', display_name: 'Fridabot', owner_id: u.id});
  const ACK = CK, FCK = await login('frida');
  check((await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', tours_more: '0', features: FEATS}, FCK)).http < 300, 'frida: modules on');
  const FL = (await call('POST', '/api/lists', {name: 'Mine'}, FCK)).id;
  const PEOPLE = [{who: 'frida', uid: u.id, ag: fag, ck: FCK, start: 'l/' + FL}, {who: 'alice', uid: ME.id, ag, ck: ACK, start: 'l/' + L}];
  const say = async (p, body, show) => (await fetch(B + `api/v1/agent/chats/${p.uid}`, {method: 'POST', headers: {Authorization: 'Bearer ' + p.ag.token, 'Content-Type': 'application/json'},
    body: JSON.stringify({body, show})})).json();

  for (const p of PEOPLE) {
    // ================= a computer: two steps, Next / Back / Done, then Close goes back
    const m1 = await say(p, 'A task goes into the box at the top, an event into the calendar.', [{target: 'tasks.new', text: 'Type your task into this box.'}, {target: 'calendar.new', text: 'This button starts a new event.'}]);
    check(m1.id && m1.show?.length === 2, `${p.who}: the message with two steps ` + JSON.stringify(m1).slice(0, 160));
    const before = await counts(p.ck);
    await firefox(async ({cmd, ev, ctx, nav, until, shot}) => {
      await nav(B + 'static/icon.svg');
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${p.who}', password: 'password123'})}).then(r => r.status)`) === 200, `${p.who}: login`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
      await nav(B + '#' + p.start);
      await until(`!!document.querySelector('#view')?.children.length`);
      await ev(`loadModule('agentchat').then(() => { chatOpen(${p.ag.id}); return 1; })`);
      const b = JSON.parse(await until(BTN(m1.id)) || 'null');
      check(b && b.text === 'Show me' && b.on && b.hit, `${p.who} desktop: the button "Show me" at the message, on the screen and reachable ` + JSON.stringify(b));
      const startHash = await ev('location.hash');
      await ev(`document.querySelector('#chat-msgs .cmsg[data-mid="a:${m1.id}"] [data-act="show-me"]').click()`);
      let s = JSON.parse(await until(`(() => { const x = ${SPOT}; return x && JSON.parse(x).state === 'on' && JSON.parse(x).inRing ? x : null; })()`) || 'null');
      check(s && s.hash === '#today' && s.target === 'tasks.new', `${p.who} desktop: the press opens the first step's view (#today) ` + JSON.stringify(s));
      check(s && s.ring && s.inRing && s.card, `${p.who} desktop: the ring lies on the task box, the card on the screen ` + JSON.stringify(s));
      check(s && /Type your task into this box\./.test(s.text) && /1\/2/.test(s.text) && s.h3 === 'Add a task', `${p.who} desktop: the card with the agent's line, the label and 1/2 ` + s?.text);
      check(s && s.through, `${p.who} desktop: the control still takes the person's press (the layer lets it through)`);
      await shot(`p21072c-${p.who}-desktop-1.png`);
      await ev(`document.querySelector('.spot [data-shw="next"]').click()`);
      s = JSON.parse(await until(`(() => { const x = ${SPOT}; return x && JSON.parse(x).i === 1 && JSON.parse(x).state === 'on' && JSON.parse(x).inRing ? x : null; })()`) || 'null');
      check(s && s.hash === '#cal' && s.target === 'calendar.new' && s.ring && s.inRing && /This button starts a new event\./.test(s.text) && /Done/.test(s.btns),
        `${p.who} desktop: Next goes to the calendar and rings "New event", the last step says Done ` + JSON.stringify(s));
      await shot(`p21072c-${p.who}-desktop-2.png`);
      await ev(`document.querySelector('.spot [data-shw="back"]').click()`);
      s = JSON.parse(await until(`(() => { const x = ${SPOT}; return x && JSON.parse(x).i === 0 && JSON.parse(x).state === 'on' && JSON.parse(x).inRing ? x : null; })()`) || 'null');
      check(s && s.hash === '#today' && s.inRing, `${p.who} desktop: Back comes back to the first step ` + JSON.stringify(s));
      await ev(`document.querySelector('.spot [data-shw="next"]').click()`);
      await until(`(() => { const x = ${SPOT}; return x && JSON.parse(x).i === 1; })()`);
      await ev(`document.querySelector('.spot [data-shw="next"]').click()`);
      check(await until(`!document.querySelector('.spot') && location.hash === '#cal'`), `${p.who} desktop: Done ends it and stays in the calendar`);
      check(await ev(`!document.querySelector('.modal') && !(document.querySelector('#qinput')?.value)`), `${p.who} desktop: nothing opened, nothing typed`);
      // again, then Close / Escape: back to where the button was pressed
      await nav(B + startHash);
      await until(`!!document.querySelector('#view')?.children.length`);
      await ev(`loadModule('agentchat').then(() => { chatOpen(${p.ag.id}); return 1; })`);
      await until(BTN(m1.id));
      await ev(`document.querySelector('#chat-msgs .cmsg[data-mid="a:${m1.id}"] [data-act="show-me"]').click()`);
      await until(`(() => { const x = ${SPOT}; return x && JSON.parse(x).state === 'on' && JSON.parse(x).inRing ? x : null; })()`);
      await ev(`document.querySelector('.spot [data-shw="close"]').click()`);
      check(await until(`!document.querySelector('.spot') && location.hash === ${JSON.stringify(startHash)}`), `${p.who} desktop: Close goes back to ${startHash}`);
      check(await until(`!document.querySelector('#achat')?.classList.contains('hidden') && !!document.querySelector('#chat-msgs .cmsg[data-mid="a:${m1.id}"]')`), `${p.who} desktop: the chat is there again`);
      await ev(`document.querySelector('#chat-msgs .cmsg[data-mid="a:${m1.id}"] [data-act="show-me"]').click()`);
      await until(`(() => { const x = ${SPOT}; return x && JSON.parse(x).state === 'on' && JSON.parse(x).inRing ? x : null; })()`);
      await ev(`window.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true, cancelable: true}))`);
      check(await until(`!document.querySelector('.spot') && location.hash === ${JSON.stringify(startHash)}`), `${p.who} desktop: Escape closes like Close`);
    }, false);
    check(await counts(p.ck) === before, `${p.who} desktop: no task, no event more on the server ${before} -> ${await counts(p.ck)}`);

    // ================= a phone: a step whose control is not on the screen says so in one line; Close back to the chat page
    const m2 = await say(p, 'The scan inbox is in the settings.', [{target: 'tasks.new', text: 'Here you add a task.'}, {target: 'settings.integrations', text: 'Then press Integrations.'}]);
    await firefox(async ({cmd, ev, ctx, nav, until, shot}) => {
      await nav(B + 'static/icon.svg');
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${p.who}', password: 'password123'})}).then(r => r.status)`) === 200, `${p.who} phone: login`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
      await nav(B + '#agents/' + p.ag.id);
      await ev(`loadModule('agentchat').then(() => { if (!document.querySelector('#chat-msgs')) chatOpen(${p.ag.id}); return 1; })`);
      const b = JSON.parse(await until(BTN(m2.id)) || 'null');
      check(b && b.on && b.hit, `${p.who} phone: the button on the screen and reachable ` + JSON.stringify(b));
      const chatHash = await ev('location.hash');
      await ev(`document.querySelector('#chat-msgs .cmsg[data-mid="a:${m2.id}"] [data-act="show-me"]').click()`);
      let s = JSON.parse(await until(`(() => { const x = ${SPOT}; return x && JSON.parse(x).state === 'on' && JSON.parse(x).inRing ? x : null; })()`) || 'null');
      check(s && s.hash === '#today' && s.ring && s.inRing && s.card && /Here you add a task\./.test(s.text), `${p.who} phone: the first step rings the way to a new task ` + JSON.stringify(s));
      await shot(`p21072c-${p.who}-phone-1.png`);
      await ev(`document.querySelector('.spot [data-shw="next"]').click()`);
      s = JSON.parse(await until(`(() => { const x = ${SPOT}; return x && JSON.parse(x).state === 'missing' ? x : null; })()`, {timeout: 8000}) || 'null');
      check(s && s.miss && s.missLines <= 2 && /Not on the screen here/.test(s.text) && !s.ring && s.card && /Then press Integrations\./.test(s.text),
        `${p.who} phone: the missing control says so in one line (no ring, the card stays) ` + JSON.stringify(s));
      await shot(`p21072c-${p.who}-phone-missing.png`);
      check(await ev(`!document.querySelector('.modal')`), `${p.who} phone: the settings were not opened for the person`);
      await ev(`document.querySelector('.spot [data-shw="close"]').click()`);
      check(await until(`!document.querySelector('.spot') && location.hash === ${JSON.stringify(chatHash)} && !!document.querySelector('#chat-msgs .cmsg[data-mid="a:${m2.id}"]')`),
        `${p.who} phone: Close goes back to the chat page (${chatHash})`);
    }, true);
  }
  const fails = F.length; console.log(`p21072_c_show_ui: ${ok} ok, ${fails} failed`); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
