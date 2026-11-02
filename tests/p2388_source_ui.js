// kalmido-suite:
// 2.388.0 UI tests (#3341): the switch "Show dispatcher messages" in the filter menu of the agent chat, own container (start.sh).
// jsdom, invented data only. P2388_NOSTART=1 = the container runs.
// - no such line: no switch, no "Filter" entry (a chat without jobs stays as it was)
// - with lines: the switch sits in the filter submenu, on; off hides source dispatcher + an older "Dispatcher: …" line without
//   the field, the rest stays (a job's line, buttons, another source); the ⋯ button names it; kept after a new load
// - a search hit / quote on a hidden line brings it back (jcd_reveal); a hidden line is no "new message"
// - with jobs the four choices stay, the switch below them; a person without an organisation has the same switch
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2388_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 100});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const SW = 'Show dispatcher messages';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call(CA, 'GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call(CA, 'PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call(CA, 'GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const mk = async (username, display_name) => {
    const a = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username, display_name});
    await call(CA, 'PATCH', `/api/admin/agents/${a.id}`, {org_id: ORG});
    const L = (await call(CA, 'POST', '/api/lists', {name: 'Work ' + username, org_id: ORG})).id;
    await call(CA, 'PUT', `/api/lists/${L}/members`, {user_id: a.id, role: 'edit'});
    return a;
  };
  const a1 = await mk('devbot', 'Dev Bot'), a2 = await mk('jobbot', 'Job Bot'), a0 = await mk('quietbot', 'Quiet Bot');
  const say = (tok, body, kw = {}) => v1(tok, 'POST', `/agent/chats/${me.id}`, {body, ...kw}).then(m => m.id);
  await say(a0.token, 'Hello, nothing from a dispatcher');
  const plain = await say(a1.token, 'A plain answer');
  const disp = await say(a1.token, 'Three jobs started', {source: 'dispatcher'});
  const old = await say(a1.token, 'Dispatcher: an older line without the field');
  const other = await say(a1.token, 'From another helper', {source: 'helper'});
  const asks = await say(a1.token, 'Dispatcher: go on?', {source: 'dispatcher', choices: [{id: 'y', label: 'Yes'}]});
  check(plain && disp && old && other && asks, 'setup: the messages');

  const open = async (aid, o = {}) => {
    const w = await boot({user: 'alice', hash: `agents/${aid}`, ...o}), d = w.document;
    await until(() => d.querySelector('#jcd-fbtn') && d.querySelector('#chat-msgs [data-mid]'));
    return {w, d, row: id => d.querySelector(`#chat-msgs [data-mid="a:${id}"]`), fb: () => d.querySelector('#jcd-fbtn'), items: () => [...d.querySelectorAll('[role=menuitem]:not(.mback)')]};
  };
  const sub = async o => {  // the ⋯ menu -> "Filter: …"
    click(o.w, o.fb()); await until(() => o.items().length);
    const e = o.items().find(x => /^Filter/.test(x.textContent.trim()));
    if (!e) return null;
    click(o.w, e); await until(() => o.items().some(x => x.textContent.trim() === SW));
    return o.items();
  };

  {  // ---- no such line: nothing new
    const o = await open(a0.id);
    click(o.w, o.fb()); await until(() => o.items().length);
    check(!o.items().some(x => /^Filter/.test(x.textContent.trim())), 'no dispatcher line, no job: no filter entry');
    o.w.close();
  }
  {  // ---- the switch
    const o = await open(a1.id);
    const shown = () => [plain, disp, old, other, asks].map(id => !!o.row(id)).join();
    check(shown() === 'true,true,true,true,true', 'default: every line shows ' + shown());
    check(!o.fb().classList.contains('jcdfon'), 'default: the button is plain');
    let it = await sub(o);
    const s = it && it.find(x => x.textContent.trim() === SW);
    check(s && s.classList.contains('on'), 'the switch is on');
    check(it && it.length === 1, 'without a job: only the switch, no job filters ' + (it && it.length));
    click(o.w, s);
    await until(() => !o.row(disp));
    check(shown() === 'true,false,false,true,true', 'off: source dispatcher and the old line go, the rest stays ' + shown());
    check(o.fb().classList.contains('jcdfon') && /Dispatcher messages hidden/.test(o.fb().title), 'off: the button names it: ' + o.fb().title);
    check(o.w.eval(`LS.get('chatSrcHide')`) === '1', 'off: kept on this device');
    // a new line arrives hidden, no "new message"
    const nw = await say(a1.token, 'A fourth line', {source: 'dispatcher'}), nx = await say(a1.token, 'After it');
    await until(() => o.row(nx));
    check(!o.row(nw), 'a new dispatcher line stays hidden');
    check(o.w.eval(`chs_after(${nw - 1})?.id`) === nx, 'a hidden line is no new message');
    // a jump to a hidden line brings the lines back
    o.w.eval(`jcd_reveal(${disp})`);
    await until(() => o.row(disp));
    check(o.row(disp) && o.w.eval(`LS.get('chatSrcHide')`) === '' && !o.fb().classList.contains('jcdfon'), 'a jump to a hidden line shows the lines again');
    o.w.eval(`jcd_setSrc(false)`);
    await until(() => !o.row(disp));
    o.w.close();
  }
  {  // ---- with jobs: the choices stay, the switch below them; the job's line and its card stay
    const J = (await v1(a2.token, 'POST', '/agent/jobs', {title: 'Knox: a build', user_id: me.id, state: 'running'})).id;
    const js = await say(a2.token, 'Dispatcher: the job speaks', {job_id: J, job_msg: 'say'}), dl = await say(a2.token, 'Job #' + J + ' started', {source: 'dispatcher'});
    const o = await open(a2.id);
    const it = await sub(o);
    check(it && it.length === 5 && it[0].textContent.trim() === 'All' && it[4].textContent.trim() === SW, 'with a job: four choices, then the switch ' + (it && it.map(x => x.textContent.trim())));
    click(o.w, it[4]);
    await until(() => o.w.eval(`LS.get('chatSrcHide')`) === '1');
    await until(() => o.d.querySelector('#chat-msgs .jcd'));
    check(!o.w.eval(`S.jcd.map.has(${dl})`) && !o.row(dl), 'a hidden line stays out of the job card');
    check(o.w.eval(`S.jcd.map.has(${js})`), 'the job\'s own line stays');
    o.w.close();
  }
  {  // ---- kept after a new load on the same device
    const o = await open(a1.id, {ls: {'tasks.chatSrcHide': '"1"'}});
    check(!o.row(disp) && !!o.row(plain) && o.fb().classList.contains('jcdfon'), 'after a new load the lines stay hidden');
    o.w.close();
  }
  {  // ---- a person without an organisation (P4)
    await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
    const CF = await login('frida');
    await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: [...feats].join(',')});
    const FU = (await call(CF, 'GET', '/api/state')).me;
    await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true});
    const fa = await call(CF, 'POST', '/api/my/agents', {username: 'fridabot', display_name: 'Frida Bot', scopes: ['read', 'tasks:write', 'comments']});
    const ft = fa.token || (await call(CF, 'POST', `/api/my/agents/${fa.id}/token`, {})).token;
    const fp = (await v1(ft, 'POST', `/agent/chats/${FU.id}`, {body: 'Hello Frida'})).id, fd = (await v1(ft, 'POST', `/agent/chats/${FU.id}`, {body: 'A job started', source: 'dispatcher'})).id;
    const w = await boot({user: 'frida', hash: `agents/${fa.id}`}), d = w.document, o = {w, d, fb: () => d.querySelector('#jcd-fbtn'), items: () => [...d.querySelectorAll('[role=menuitem]:not(.mback)')]};
    const row = id => d.querySelector(`#chat-msgs [data-mid="a:${id}"]`);
    await until(() => row(fd));
    const it = await sub(o);
    click(w, it.find(x => x.textContent.trim() === SW));
    await until(() => !row(fd));
    check(!row(fd) && !!row(fp), 'without an organisation: the same switch');
    w.close();
  }
  console.log(`p2388_source_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error('CRASH', e); process.exit(1); });
