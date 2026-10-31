// 2.235.0 D (#2899) UI tests (jsdom), fresh DB: phones close the keyboard after sending (agent chat), per setting chat_kbd_agent
// (default on); a desktop keeps the focus; setting off keeps the focus; a suggestion button closes it too. The user has no
// organisation (own admin), so this is also the freelancer case. freelancer-matrix: agents
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,team,files,docs';
const TOUCH = {'(hover: none)': true}, DESK = {'(hover:hover) and (pointer:fine)': true};

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'agents']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const a1 = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const A1 = a1.id, ME = (await call('GET', '/api/me')).id || 1;
  const L = (await call('POST', '/api/lists', {name: 'Studio'})).id; await call('PUT', `/api/lists/${L}/members`, {user_id: A1, role: 'edit'});
  await fetch(B + `api/v1/agent/chats/${ME}`, {method: 'POST', headers: {...H, Authorization: 'Bearer ' + a1.token}, body: JSON.stringify({body: 'Claude says hi'})});
  let s = (await call('GET', '/api/state')).settings || {};
  check(s.chat_kbd_agent === '1' && s.chat_kbd_team === '1', 'default: both switches on ' + JSON.stringify([s.chat_kbd_agent, s.chat_kbd_team]));
  await call('PATCH', '/api/settings', {chat_kbd_team: false}); await call('PATCH', '/api/settings', {chat_kbd_team: true});
  check((await call('GET', '/api/state')).settings.chat_kbd_team === '1', 'the switch is stored');

  // one send in a window; returns whether the box still has the focus afterwards
  const send = async (opts, text) => {
    const w = await boot({user: 'alice', hash: opts.mobile ? 'agents/' + A1 : 'today', ...opts}), d = w.document;
    await until(() => w.eval('S.booted && (S.agents || []).length >= 1'));
    if (!opts.mobile) w.eval(`chatOpen(${A1})`);
    await until(() => d.querySelector('#chat-in'));
    const ta = d.querySelector('#chat-in'); ta.focus(); ta.value = text;
    const n = w.eval('S.chat.msgs.length');
    d.querySelector('[data-act="chat-send"]').click();
    await until(() => w.eval('S.chat.msgs.length') > n && !w.eval('S.chat.sending'));
    await sleep(50);
    const r = d.activeElement === d.querySelector('#chat-in');
    w.close?.();
    return r;
  };
  check(!(await send({mobile: true, media: TOUCH}, 'phone one')), 'phone, switch on: the keyboard is closed after sending');
  check(await send({media: DESK}, 'desk one'), 'desktop: the box keeps the focus');
  await call('PATCH', '/api/settings', {chat_kbd_agent: false});
  check(await send({mobile: true, media: TOUCH}, 'phone two'), 'phone, switch off: the box keeps the focus');
  await call('PATCH', '/api/settings', {chat_kbd_agent: true});
  check(!(await send({mobile: true, media: TOUCH}, 'phone three')), 'phone, switch on again: closed');

  // the settings page lists the switches
  const w = await boot({user: 'alice', hash: 'today', mobile: true, media: TOUCH}), d = w.document;
  await until(() => w.eval('S.booted')); w.eval(`settingsModal('notify')`);
  await until(() => d.querySelector('#s-kbda'));
  check(d.querySelector('#s-kbda')?.checked === true, 'settings: the agent chat switch is on');
  console.log(F.length ? 'FAILED ' + F.length : 'OK ' + ok); process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
