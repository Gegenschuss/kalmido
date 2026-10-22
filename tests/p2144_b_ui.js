// 2.144.0 B (#2417 fold long messages, #2365 job card with only the end result, #2411 agent colour on the chat header)
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2144B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK, TOK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + TOK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  const st = await call('GET', '/api/state'), feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const me = (await call('GET', '/api/state')).me, ORG = me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Dev Bot'});
  const CL = ag.id; TOK = ag.token;
  await call('PATCH', `/api/admin/agents/${CL}`, {org_id: ORG});
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: CL, role: 'edit'});
  const say = (body, kw = {}) => v1('POST', `/agent/chats/${me.id}`, {body, ...kw});
  const lines = (t, n) => t + '\n' + Array.from({length: n}, (_, i) => `- line ${i + 1}`).join('\n');
  await call('POST', `/api/agents/${CL}/chat`, {body: 'Please build the release'});
  // #2365: a job card whose only message is the long end result
  const J = (await v1('POST', '/agent/jobs', {title: 'Knox: Release 2.144 solo', user_id: me.id, state: 'running'})).id;
  const mr = (await say(lines('✅ Knox: release ready', 9), {job_id: J})).id;
  await v1('PATCH', `/agent/jobs/${J}`, {state: 'done'});
  const w = await boot({user: 'alice', hash: `agents/${CL}`, mobile: true}), d = w.document;
  const card = () => d.querySelector(`#chat-msgs .jcd[data-jcd="${J}"]`);
  await until(() => card()?.querySelector('.jcdres'));
  // 2.153.0 (#1962): a job created for a person starts with its start line, folded in the card -- no message besides it
  check(card() && !card().querySelector('.jcdhist .cmsg'), '#2365: the card has no folded messages (only the start line)');
  check(card().querySelector(`.jcdres [data-mid="a:${mr}"]`), '#2365: the end result stands under the card');
  check(card().querySelector('.jcdres.jcdclamp .jcdmore')?.textContent === 'Show more', '#2365: cut, with "Show more"');
  click(w, card().querySelector('.jcdmore'));
  await until(() => !card()?.querySelector('.jcdres.jcdclamp'));
  check(!card().querySelector('.jcdres.jcdclamp') && card().querySelector('.jcdmore').textContent === 'Show less', '#2365: opens by a tap');
  click(w, card().querySelector('.jcdmore'));
  await until(() => card()?.querySelector('.jcdres.jcdclamp'));

  // #2417: long messages -- 2.152.4 (#2659): only a job's messages fold (here the ones in the card's history); the main
  // agent's long answer stays whole without a button
  const pl = (await say(lines('Long answer of the agent itself', 8))).id;
  const a1 = (await say(lines('First long step', 8), {job_id: J})).id;
  const a2 = (await say(lines('Second long step', 8), {job_id: J})).id;
  const sh = (await say('Short one', {job_id: J})).id;
  w.eval(`jcd_setOpen(${J}, true)`);
  await w.eval('chatLoad()');
  const msg = id => d.querySelector(`#chat-msgs [data-mid="a:${id}"]`);
  await until(() => msg(a2) && msg(pl));
  const menuItem = async re => {  // 2.152.2 (#2627): the header's menu entry (open the menu, return the item)
    click(w, d.querySelector('.chath [data-act="chat-head-menu"]')); await until(() => [...d.querySelectorAll('[role=menuitem]')].find(x => re.test(x.textContent)));
    return [...d.querySelectorAll('[role=menuitem]')].find(x => re.test(x.textContent));
  };
  const togOn = async () => { const on = (await menuItem(/Fold long messages/)).classList.contains('on'); w.eval('closePop()'); await sleep(150); return on; };
  const togFlip = async () => click(w, await menuItem(/Fold long messages/));
  check(!d.querySelector('.chath .jcfbtn') && !(await togOn()), 'the menu entry is there, off (no header icon any more)');  // 2.152.2 (#2627)
  check(!msg(pl).querySelector('.jcdmore') && !msg(pl).classList.contains('jcfcut'), '#2659: the agent\'s own long answer has no button');
  check(!msg(a1).classList.contains('jcfcut') && msg(a1).querySelector('.jcdmore')?.dataset.jca === 'fold', 'off: a long message is whole and offers "Show less"');
  check(!msg(sh).querySelector('.jcdmore'), 'a short message has no button');
  click(w, msg(a1).querySelector('.jcdmore'));
  await until(() => msg(a1).classList.contains('jcfcut'));
  check(msg(a1).classList.contains('jcfcut') && msg(a2).classList.contains('jcfcut'), 'folding one message folds all');
  check(w.eval(`LS.get('jcfOn')`) === '1' && (await togOn()), 'mode on, kept per device, menu entry checked');
  const bub = msg(a1).querySelector('.cbub'), btn = msg(a1).querySelector('.jcdmore');
  check(btn.textContent === 'Show more' && btn.previousElementSibling === bub, '"Show more" sits right under the text');
  // a message that comes later is cut as well
  const a3 = (await say(lines('Third long step', 8), {job_id: J})).id;
  await w.eval('chatLoad()');
  await until(() => msg(a3));
  check(msg(a3).classList.contains('jcfcut'), 'a new long message arrives cut');
  // opening one stays open (kept per message)
  click(w, msg(a2).querySelector('.jcdmore'));
  await until(() => !msg(a2).classList.contains('jcfcut'));
  check(!msg(a2).classList.contains('jcfcut') && msg(a1).classList.contains('jcfcut'), 'one opened message stays open, the others stay cut');
  check(JSON.stringify(w.eval(`LS.get('jcfOpen')`)).includes(String(a2)), 'the open message is remembered');
  await w.eval('chatPatch({keep: true})');
  check(!msg(a2).classList.contains('jcfcut'), 'still open after a redraw');
  // search / reply jump unfolds the target
  await w.eval(`jcd_reveal(${a1})`);
  await until(() => !msg(a1).classList.contains('jcfcut'));
  check(!msg(a1).classList.contains('jcfcut'), 'jump to a cut message unfolds it');
  // the header toggle switches the mode off again
  await togFlip();
  await until(() => !msg(a3).classList.contains('jcfcut'));
  check(!msg(a3).classList.contains('jcfcut') && !(await togOn()), 'toggle off: all whole again');
  await togFlip();
  await until(() => msg(a3).classList.contains('jcfcut'));
  check(msg(a3).classList.contains('jcfcut') && !msg(a2).classList.contains('jcfcut'), 'toggle on: cut again, opened ones stay open');
  check(!msg(pl).querySelector('.jcdmore') && !msg(pl).classList.contains('jcfcut'), '#2659: mode on: the agent\'s own long answer stays whole');
  // the list of open ids is limited
  check(w.eval(`(() => { for (let i = 1; i <= 260; i++) S.jcd.more.add(100000 + i); jcf_save(); return LS.get('jcfOpen').length; })()`) <= 200, 'at most 200 open ids kept');

  // #2411: the agent's colour on the header and the input box
  const col = w.eval(`ac_color(${CL})`);
  const hd = d.querySelector('.chath'), cp = d.querySelector('.chcomp');
  check(col && hd.classList.contains('agcol') && hd.style.getPropertyValue('--agcol') === col, 'header carries the agent colour');
  check(cp.classList.contains('agcol') && cp.style.getPropertyValue('--agcol') === col, 'input box carries the agent colour');

  console.log(`p2144_b_ui: ${ok} ok, ${F.length} failed`);
  w.close();
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
