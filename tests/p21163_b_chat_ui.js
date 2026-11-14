// 2.1163.0 B (#6094) the team chat between 768 and 899 px is no third mixed form, the agent button never covers Send.
// kalmido-suite: fresh
// Own container (start.sh), Firefox with real layout, invented people and texts only. Usability, not presence:
// - 820 px (finger): the conversation's messages are readable, the box is wide (tools behind the plus, round Send), Send is
//   reachable (elementFromPoint); "3 replies" opens the thread FULL SIZE in the conversation's place (no 90 px column beside an
//   empty one), its answers readable, its box and Send usable, Back returns to the conversation with its messages
// - 1280 px (mouse): the agent button (#chatfab) lies neither on Send nor on the box - of the conversation and of the thread pane
//   beside it; the page head above the open conversation is one low row
// - 360 px: the thread full size as before (picture)
// Pictures 360 / 820 / 1280, light and dark, with P21163B_SHOTS=<dir> (kalmido-mactest.sh shot p21163_b_chat_ui).
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21163_b_chat_ui', check, shots: 'P21163B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

// the measures of the open conversation / thread (all in one JSON): box and Send of the visible composer, what lies on Send's
// centre and its corners, the agent button's box (its badge and ring included), a readable message bubble
const M = `JSON.stringify((() => {
  const vis = e => !!e && e.getClientRects().length > 0 && getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none';
  const R = e => { if (!vis(e)) return null; const r = e.getBoundingClientRect(); return {l: Math.round(r.left), t: Math.round(r.top), r: Math.round(r.right), b: Math.round(r.bottom), w: Math.round(r.width), h: Math.round(r.height)}; };
  const th = document.querySelector('#tth-in'), ta = th && vis(th) ? th : document.querySelector('#tc-in');
  const comp = ta && ta.closest('.chcomp'), send = comp && comp.querySelector(':scope > .btn.pri');
  const sr = send && send.getBoundingClientRect();
  const on = (x, y) => { const e = document.elementFromPoint(x, y); return !!e && !!send && send.contains(e); };
  const hitSend = sr ? [on(sr.left + sr.width / 2, sr.top + sr.height / 2), on(sr.left + 3, sr.top + 3), on(sr.right - 3, sr.top + 3), on(sr.left + 3, sr.bottom - 3), on(sr.right - 3, sr.bottom - 3)] : [];
  const f = document.querySelector('#chatfab'); let fab = null;
  if (vis(f)) { const bs = [f, ...f.querySelectorAll('*')].map(e => e.getBoundingClientRect()).filter(r => r.width && r.height);
    fab = {l: Math.min(...bs.map(r => r.left)), t: Math.min(...bs.map(r => r.top)), r: Math.max(...bs.map(r => r.right)), b: Math.max(...bs.map(r => r.bottom))}; }
  const bub = t => { const e = [...document.querySelectorAll('.cbub')].filter(vis).find(x => x.textContent.includes(t)); return e ? {...R(e), lines: Math.round(e.getBoundingClientRect().height / parseFloat(getComputedStyle(e).lineHeight || 20))} : null; };
  const plus = comp && comp.querySelector('.chplus'), tools = comp && comp.querySelector('.chtools');
  return {vw: innerWidth, ta: R(ta), taId: ta && ta.id, ph: ta && ta.placeholder, comp: R(comp), send: R(send), sendWord: !!send && vis(send.querySelector('span')), hitSend, fab,
    plus: vis(plus), tools: !!tools && vis(tools), pane: vis(document.querySelector('.tthpane')), inthread: !!document.querySelector('.tcview.inthread'),
    full: vis(document.querySelector('.tcroom .tthview')), room: vis(document.querySelector('#tc-msgs')), thMsgs: R(document.querySelector('#tth-msgs')), tcMsgs: R(document.querySelector('#tc-msgs')),
    bRoot: bub('Musikauswahl'), bAns: bub('drei Stücke aus der Bibliothek'), bRoom: bub('Drehgenehmigung liegt vor'), top: R(document.querySelector('#top')), head: R(document.querySelector('.tcroom .tcrhead'))};
})())`;
const meet = (a, b, gap = 0) => !!a && !!b && a.r + gap > b.l && a.l < b.r + gap && a.b + gap > b.t && a.t < b.b + gap;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'anna', display_name: 'Anna Berger', password: 'password123'})});
  check(r.ok, 'setup');
  const CA = await login('anna');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Gegenlicht Film', lang: 'de', collab_all: true, modules: ['cal', 'comments', 'collab', 'agents', 'team']});
  const st0 = await call(CA, 'GET', '/api/state'); const ORG = (st0.me?.workspaces || [])[0]?.id;
  check(ORG, 'the organisation');
  const feats = new Set(((st0.settings || {}).features || '').split(',').filter(Boolean)); for (const m of ['cal', 'comments', 'collab', 'agents', 'team']) feats.add(m);
  const FEAT = [...feats].join(','), WS = `org:${ORG}`;
  await call(CA, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: FEAT, workspace: WS});
  const U = {}, CK = {anna: CA};
  for (const [u, n] of [['bert', 'Bert Kaminski'], ['carla', 'Carla Hohenstein-Wiedemann'], ['emil', 'Emil Yildiz']]) {
    U[u] = (await call(CA, 'POST', '/api/users', {username: u, password: 'password123', display_name: n, email: `${u}@example.com`, orgs: [{id: ORG, role: 'member'}]})).id;
    CK[u] = await login(u); await call(CK[u], 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: FEAT, workspace: WS});
  }
  // an agent in a project of the organisation: the round agent button shows on the computer
  const AG = (await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'assistent', display_name: 'Kalmido Assistent'})).id;
  await call(CA, 'PATCH', `/api/admin/agents/${AG}`, {org_id: ORG});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Imagefilm Stadtwerke', org_id: ORG, kind: 'project'})).id;
  await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const CH = (await call(CA, 'POST', '/api/team/channels', {name: 'Drehteam', org_id: ORG, open: false, members: [U.bert, U.carla, U.emil]})).id;
  check(CH, 'the channel');
  const post = (u, body, extra = {}) => call(CK[u], 'POST', `/api/team/rooms/${CH}/messages`, {body, ...extra});
  const lines = ['Morgen um 7 Uhr am Hafen?', 'Ich bringe die Akkus mit.', 'Wer holt die Objektive ab?', 'Halle 3 ist reserviert.'];
  for (let i = 0; i < 12; i++) await post(['bert', 'carla', 'anna', 'emil'][i % 4], lines[i % lines.length]);
  const ROOT = (await post('bert', 'Thread zur Musikauswahl - bitte Vorschläge hier rein.')).id;
  check(ROOT, 'the thread\'s first message');
  for (const [u, t] of [['carla', 'Etwas Ruhiges, Klavier.'], ['emil', 'Ich habe drei Stücke aus der Bibliothek, Links folgen.'], ['anna', 'Klavier finde ich gut.']]) await post(u, t, {thread_of: ROOT});
  await post('carla', 'Drehgenehmigung liegt vor.');

  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'anna', password: 'password123'})}).then(r => r.status)`);
  for (const [wd, ht, touch] of [[820, 1180, true], [1280, 800, false], [360, 740, true]]) {
    await firefox(async ({cmd, ev, nav, ctx, shot, until, idle}) => {
      const get = async () => JSON.parse(await ev(M));
      for (const theme of ['light', 'dark']) {
        const tag = `${wd} ${theme}:`;
        await nav(B + 'static/icon.svg');
        await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); localStorage.setItem('tasks.lookLocal', 'true'); return 1; })()`);
        check(await signIn(ev) === 200, tag + ' login');
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: ht}});
        await nav(B + '#team/' + CH); await idle();
        check(await until(`!!document.querySelector('#tc-in') && [...document.querySelectorAll('#tc-msgs .cbub')].some(b => b.textContent.includes('Drehgenehmigung liegt vor'))`), tag + ' the conversation opens with its messages');
        if (wd >= 1000) await until(`!!document.querySelector('#chatfab')`, {timeout: 8000});
        await ev(`(() => { const b = document.querySelector('#tc-msgs'); if (b) b.scrollTop = b.scrollHeight; return 1; })()`); await idle();
        let g = await get();
        // the conversation: messages readable, the box wide, Send free
        check(g.bRoom && g.bRoom.w >= 120 && g.bRoom.lines <= 2, `${tag} a message reads on one or two lines ${JSON.stringify(g.bRoom)}`);
        check(g.ta && g.comp && g.ta.w >= g.comp.w * (wd >= 900 ? 0.4 : 0.55), `${tag} the box takes most of the composer (${g.ta && g.ta.w} of ${g.comp && g.comp.w}, "${g.ph}")`);
        check(g.send && g.hitSend.length === 5 && g.hitSend.every(Boolean), `${tag} Send is reachable at its centre and corners ${JSON.stringify(g.hitSend)} ${JSON.stringify(g.send)} fab ${JSON.stringify(g.fab)}`);
        if (wd < 900) {
          check(g.plus && !g.tools && !g.sendWord && g.send && g.send.w <= 48, `${tag} the phone's composer: tools behind the plus, round Send without its word ${JSON.stringify({plus: g.plus, tools: g.tools, word: g.sendWord, send: g.send})}`);
        } else {
          check(g.fab, `${tag} the agent button shows`);
          check(g.fab && !meet(g.fab, g.send, 8) && !meet(g.fab, g.ta, 8), `${tag} the agent button keeps 8 px off Send and the box ${JSON.stringify({fab: g.fab, send: g.send, ta: g.ta})}`);
          check(g.top && g.top.h <= 52 && g.head, `${tag} the page head above the open conversation is one low row (${g.top && g.top.h} px)`);
        }
        await shot(`p21163b-${wd}-${theme}-1-unterhaltung.png`);
        // the thread
        await until(`!!document.querySelector('.tthline[data-root="${ROOT}"]')`);
        await ev(`(() => { const b = document.querySelector('.tthline[data-root="${ROOT}"]'); b.scrollIntoView({block: 'center'}); b.click(); return 1; })()`);
        check(await until(`[...document.querySelectorAll('#tth-msgs .cbub')].some(b => b.textContent.includes('drei Stücke aus der Bibliothek')) && !!document.querySelector('#tth-in')`), tag + ' the thread opens with its answers');
        await idle(); await ev(`(() => { const b = document.querySelector('#tth-msgs'); if (b) b.scrollTop = b.scrollHeight; return 1; })()`);
        g = await get();
        check(g.bAns && g.bAns.w >= 150 && g.bAns.lines <= 3, `${tag} an answer in the thread reads in lines, not letter by letter ${JSON.stringify(g.bAns)}`);
        check(g.taId === 'tth-in' && g.ta.w >= g.comp.w * 0.5, `${tag} the thread's box is wide (${g.ta && g.ta.w} of ${g.comp && g.comp.w})`);
        check(g.hitSend.length === 5 && g.hitSend.every(Boolean), `${tag} the thread's Send is reachable ${JSON.stringify(g.hitSend)} ${JSON.stringify(g.send)} fab ${JSON.stringify(g.fab)}`);
        if (wd < 900) {
          check(g.full && !g.pane && !g.inthread && !g.room, `${tag} the thread full size in the conversation's place, no column beside it ${JSON.stringify({full: g.full, pane: g.pane, inthread: g.inthread, room: g.room})}`);
          check(g.thMsgs && g.thMsgs.w >= wd * 0.6, `${tag} the thread uses the width (${g.thMsgs && g.thMsgs.w} of ${wd})`);
        } else {
          check(g.pane && g.inthread && g.room, `${tag} the thread pane beside the conversation ${JSON.stringify({pane: g.pane, inthread: g.inthread, room: g.room})}`);
          check(g.fab && !meet(g.fab, g.send, 8) && !meet(g.fab, g.ta, 8), `${tag} the agent button keeps off the thread's Send and box ${JSON.stringify({fab: g.fab, send: g.send, ta: g.ta})}`);
        }
        await shot(`p21163b-${wd}-${theme}-2-strang.png`);
        // back / close: the conversation with its messages again
        await ev(`(() => { document.querySelector('[data-act="tth-close"]').click(); return 1; })()`);
        check(await until(`!document.querySelector('#tth-in') && !!document.querySelector('#tc-in') && [...document.querySelectorAll('#tc-msgs .cbub')].some(b => b.textContent.includes('Drehgenehmigung liegt vor'))`), tag + ' Back / close returns to the conversation with its messages');
      }
    }, touch);
  }
  console.log(`p21163_b_chat_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
