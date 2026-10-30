// 2.217.0 B (#2797) UI tests: the chat with an agent while the module Agents is off. The header menu still offers
// "Chat with … (1)"; a tap asks to turn the module on instead of a dead end (phone: the route fell back to Today), and the
// chat is neither loaded nor marked read meanwhile. "Not now" leaves everything as it was; "Turn on and open" switches the
// module on and opens the chat (desktop panel, phone view). jsdom, own container (start.sh). No organisation (freelancer).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'cal,comments,collab,time,progress,kanban,timeline,fields';  // no agents
const DESK = {'(hover:hover) and (pointer:fine)': true};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  const ME = (await call('GET', '/api/me')).id || 1;
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'helper', display_name: 'Office Helper'});
  const AG = ag.id;
  const L = (await call('POST', '/api/lists', {name: 'Office'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const say = body => fetch(B + `api/v1/agent/chats/${ME}`, {method: 'POST', headers: {...H, Authorization: 'Bearer ' + ag.token}, body: JSON.stringify({body})}).then(x => x.json());
  await say('A first note from the helper');
  const unread = async () => ((await call('GET', '/api/state')).agents || []).find(a => a.id === AG)?.chat_unread || 0;
  check(await unread() === 1, 'setup: one unread agent message with the module off');
  check(!(await call('GET', '/api/state')).settings.features.split(',').includes('agents'), 'setup: the module Agents is off');

  for (const mobile of [false, true]) {
    const tag = mobile ? 'phone' : 'desktop';
    const w = await boot({user: 'alice', mobile, ...(mobile ? {} : {media: DESK})}), d = w.document;
    w.__dialogs = 'manual';  // the suite answers the questions itself (the bridge would answer them with w.confirm)
    await until(() => w.eval('S.booted && (S.agents || []).length >= 1'));
    check(!w.eval('feat("agents")') && w.eval(`agentById(${AG}).chat_unread`) === 1, `${tag}: the client sees the unread message with the module off ` + w.eval('JSON.stringify([feat("agents"), (S.agents || []).map(x => x.chat_unread), location.hash, S.booted])'));
    // the header menu still offers the chat with its count (the counters stay)
    const chip = d.querySelector('[data-act="agent-chip"]');
    check(!!chip, `${tag}: the agent chip shows`);
    if (chip) { click(w, chip); await sleep(250); }
    const it = await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Chat with Office Helper \(1\)/.test(b.textContent)));
    check(!!it, `${tag}: the menu offers "Chat with Office Helper (1)"`);
    if (it) click(w, it); else w.eval(`chatOpen(${AG})`);
    const dlg = await until(() => d.querySelector('#cdlg-t'));
    check(dlg && /The Agents module is switched off/.test(dlg.textContent), `${tag}: a tap asks to turn the module on`);
    check(/Office Helper/.test(d.querySelector('#cdlg-b')?.textContent || ''), `${tag}: the dialog names the agent`);
    check(!d.querySelector('#achat:not(.hidden)') && !/^#agents\//.test(w.location.hash), `${tag}: no chat opened behind the dialog`);
    if (!mobile) {
      click(w, d.querySelector('[data-cd="no"]')); await sleep(600);
      check(!d.querySelector('#cdlg-t') && !d.querySelector('#achat:not(.hidden)'), 'desktop: "Not now" closes, no chat');
      check(await unread() === 1 && w.eval(`agentById(${AG}).chat_unread`) === 1, 'desktop: nothing marked read (server and client)');
      check(!(await call('GET', '/api/state')).settings.features.split(',').includes('agents'), 'desktop: the module stays off');
      // 2.217.0 (#2797): a link to the agent's chat (e.g. from a notification) asks too instead of falling back to Today silently
      w.eval(`go('agents/${AG}')`);
      const dl2 = await until(() => d.querySelector('#cdlg-t'));
      check(dl2 && /The Agents module is switched off/.test(dl2.textContent), 'desktop: a link #agents/<id> asks to turn the module on');
      if (dl2) { click(w, d.querySelector('[data-cd="no"]')); await sleep(400); }
      check(await unread() === 1, 'desktop: the link read nothing');
      check(!/^#agents/.test(w.location.hash), 'desktop: the hash went to the fallback (no second question on a re-route) ' + w.location.hash);
      await until(() => !d.querySelector('#cdlg-t'));
      // "Agents and jobs" in the header menu (the Agents view) asks the same, without an agent
      w.eval(`go('agents')`);
      const dl3 = await until(() => d.querySelector('#cdlg-t'));
      check(dl3 && /tab with their status/.test(d.querySelector('#cdlg-b')?.textContent || ''), 'desktop: the Agents view with the module off asks to turn it on ' + w.eval('JSON.stringify([location.hash, S.route.mod, feat("agents"), document.querySelector("#cdlg-t")?.textContent, document.querySelector("#cdlg-b")?.textContent, mg_alt("agents")])'));
      if (dl3) { click(w, d.querySelector('[data-cd="no"]')); await sleep(400); }
      check(!d.querySelector('#cdlg-t') && !(await call('GET', '/api/state')).settings.features.split(',').includes('agents'), 'desktop: "Not now" keeps the module off');
      w.close();
      continue;
    }
    click(w, d.querySelector('[data-cd="yes"]'));
    const msg = await until(() => [...d.querySelectorAll('.cmsg')].find(m => /A first note from the helper/.test(m.textContent)), 60);
    check(!!msg, 'phone: "Turn on and open" opens the chat with the message');
    check(/^#agents\//.test(w.location.hash), 'phone: the chat view is open ' + w.location.hash);
    check((await call('GET', '/api/state')).settings.features.split(',').includes('agents'), 'phone: the module Agents is on now');
    check(await until(async () => await unread() === 0), 'phone: read once the chat is shown');
    w.close();
  }

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
