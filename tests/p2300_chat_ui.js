// 2.30.0 UI tests (agent chat + listening in), own container (start.sh). jsdom:
// #1037 only the newest question's buttons are live: an older question's open buttons disappear when the agent writes again
//       or when I write; pressed ones stay "Answered"; a press on buttons that expired meanwhile (an old tab) is refused
//       and the buttons go; the agent withdrawing them removes them
// #1041 a permission question: the buttons Allow (accent) / Deny (calm), no "👍 = approval" hint; afterwards one line
//       "Allowed HH:MM" / "Denied HH:MM", unanswered in time "Not answered, denied"; a 👍 answers it too
// #1039 "working" without a task shows under the chat's last message, never in a task; with a task only in that task
//       (with its text), not under the chat messages
// #1034 the list dialog's switch "Agent listens in" (on in a software project, off elsewhere), the list's "…" menu says
//       "Agent listens in" / "Agent only via @", the folder settings have "Agent listens in"
// Firefox (1440 light / dark, 390 touch): screenshots of the permission question and the buttons; the two buttons sit
// side by side, nothing overlaps them; Enter on the focused Allow button allows (Enter in the message box does not).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2300_chat_ui', check, shots: 'P2300_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,team';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me, ORG = ME.workspaces[0].id;
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const SW = (await call('POST', '/api/lists', {name: 'App dev', ptype: 'software', org_id: ORG})).id;
  const AGY = (await call('POST', '/api/lists', {name: 'Campaign', ptype: 'agency', org_id: ORG})).id;
  for (const l of [SW, AGY]) { await call('PUT', `/api/lists/${l}/agent`, {agent_id: AG}); await call('PUT', `/api/lists/${l}/members`, {user_id: BOB, role: 'edit'}); }
  const T1 = (await call('POST', '/api/tasks', {title: 'Login breaks on Safari', list_id: SW})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Settings page slow', list_id: SW})).id;
  const say = async (body, extra = {}) => (await fetch(V + `/agent/chats/${ME.id}`, {method: 'POST', headers: AGH, body: JSON.stringify({body, ...extra})})).json();
  const status = b => fetch(V + '/agent/status', {method: 'PUT', headers: AGH, body: JSON.stringify(b)});
  const cm = (d, id) => d.querySelector(`#chat-msgs .cmsg[data-mid="${id}"]`);

  // ================= #1037 only the newest buttons are live
  const q1 = await say('Shall I plan 2.30 now?', {choices: [{id: 'yes', label: 'Plan 2.30', style: 'primary'}, {id: 'no', label: 'Later'}]});
  let w = await boot({user: 'alice', hash: 'l/' + SW}), d = w.document;
  w.eval(`chatOpen(${AG})`); await until(() => cm(d, q1.id));
  check(cm(d, q1.id)?.querySelectorAll('.cchoices .cchb:not([disabled])').length === 2, '#1037: the newest question has live buttons');
  const q2 = await say('Or rather 2.31 first?', {choices: [{id: 'a', label: '2.31 first'}, {id: 'b', label: 'Stay with 2.30'}]});
  await w.eval('chatLoad()'); await until(() => cm(d, q2.id));
  check(!cm(d, q1.id).querySelector('.cchoices') && cm(d, q2.id).querySelectorAll('.cchoices .cchb').length === 2, '#1037: a newer agent message: the older open buttons are gone (not only greyed out)');
  click(w, cm(d, q2.id).querySelector('.cchb'));
  await until(() => cm(d, q2.id)?.querySelector('.cchoices.done'));
  check(/Answered/.test(cm(d, q2.id).querySelector('.cchans')?.textContent || ''), '#1037: pressed: "Answered"');
  const q3 = await say('Which colour?', {choices: ['red', 'blue']});
  await w.eval('chatLoad()'); await until(() => cm(d, q3.id)?.querySelector('.cchb'));
  d.querySelector('#chat-in').value = 'neither, green please';
  click(w, d.querySelector('[data-act="chat-send"]'));
  await until(() => !cm(d, q3.id)?.querySelector('.cchoices'), 60);
  check(!cm(d, q3.id).querySelector('.cchoices') && cm(d, q2.id).querySelector('.cchoices.done'), '#1037: my own message: the open buttons before it are gone, the answered one stays');
  // an old tab: the buttons still show here, meanwhile a newer message came -> refused, then gone
  const q4 = await say('Ship it?', {choices: ['Ship', 'Wait']});
  await w.eval('chatLoad()'); await until(() => cm(d, q4.id)?.querySelector('.cchb'));
  await say('Status: the build runs.');
  click(w, cm(d, q4.id).querySelector('.cchb'));
  await until(() => /no longer current/.test(d.querySelector('#toast')?.textContent || ''), 60);
  check(/no longer current/.test(d.querySelector('#toast')?.textContent || ''), '#1037: an expired press says "This suggestion is no longer current" ' + (d.querySelector('#toast')?.textContent || ''));
  await until(() => !cm(d, q4.id)?.querySelector('.cchoices'), 60);
  check(!cm(d, q4.id)?.querySelector('.cchoices'), '#1037: ... and the buttons go');
  const q5 = await say('Tidy the inbox?', {choices: ['Yes', 'No']});
  await w.eval('chatLoad()'); await until(() => cm(d, q5.id)?.querySelector('.cchb'));
  await fetch(V + `/agent/chats/${ME.id}/messages/${q5.id}/withdraw`, {method: 'POST', headers: AGH, body: '{}'});
  await w.eval('chatLoad()'); await until(() => !cm(d, q5.id)?.querySelector('.cchoices'));
  check(cm(d, q5.id) && !cm(d, q5.id).querySelector('.cchoices'), '#1037: buttons the agent withdrew are gone');

  // ================= #1041 permission questions
  const p1 = await say('May I run this?\n```\n./deploy.sh staging\n```', {permission: true, expires_in: 600});
  await w.eval('chatLoad()'); await until(() => cm(d, p1.id)?.querySelector('.cperm'));
  const pb = [...cm(d, p1.id).querySelectorAll('.cperm .cchb')];
  check(pb.length === 2 && /Allow/.test(pb[0].textContent) && pb[0].classList.contains('st-primary') && /Deny/.test(pb[1].textContent) && !pb[1].classList.contains('st-primary') && !pb[1].classList.contains('st-danger'), '#1041: two buttons, Allow (accent) and Deny (calm)');
  check(!d.querySelector('#chat-msgs .rxhint') && !/👍 = /.test(d.querySelector('#chat-msgs').textContent), '#1041: no "👍 = approval" hint anywhere');
  check(!cm(d, p1.id).querySelector('.rxrow [data-e="up"]:not(.rxq)'), '#1041: the 👍 / 👎 stay a shortcut behind the smiley, not next to the buttons');
  await say('Meanwhile: the tests are green.');
  await w.eval('chatLoad()'); await sleep(300);
  check(cm(d, p1.id).querySelectorAll('.cperm .cchb').length === 2, '#1041: the permission question stays live while newer messages come');
  click(w, cm(d, p1.id).querySelector('.cperm .cchb.st-primary'));
  await until(() => cm(d, p1.id)?.querySelector('.cpermst'));
  const line = cm(d, p1.id).querySelector('.cpermst');
  check(line && line.classList.contains('ok') && /^(\u{1F44D}\s*)?Allowed \d{1,2}:\d\d/u.test(line.textContent.trim()) /* 2.32.0 (#1082): 👍 in front */ && !cm(d, p1.id).querySelector('.cperm'), '#1041: afterwards one line "Allowed HH:MM", no buttons ' + (line?.textContent || ''));
  check(d.activeElement?.id === 'chat-in', '#1041: the focus goes back to the message box');
  const ev1 = (await (await fetch(V + '/agent/events?since=0&limit=200', {headers: AGH})).json()).data;
  check(ev1.some(e => e.event === 'chat_choice' && e.data.message_id === p1.id && e.data.approval === 'approved') && ev1.some(e => e.event === 'reaction' && e.data.chat_message?.id === p1.id && e.data.approval === 'approved'), '#1041: the agent got chat_choice and the reaction event');
  const p2 = await say('May I delete the cache?', {permission: true});
  await w.eval('chatLoad()'); await until(() => cm(d, p2.id)?.querySelector('.cperm'));
  await call('POST', `/api/agents/${AG}/chat/${p2.id}/reactions`, {emoji: 'down'});
  await w.eval('chatLoad()'); await until(() => cm(d, p2.id)?.querySelector('.cpermst'));
  check(cm(d, p2.id).querySelector('.cpermst.no') && /^(\u{1F44E}\s*)?Denied \d{1,2}:\d\d/u.test(cm(d, p2.id).querySelector('.cpermst').textContent.trim()), '#1041: a 👎 answers it: "Denied HH:MM"');
  const p3 = await say('May I restart the worker?', {permission: true, expires_in: 10});
  await w.eval('chatLoad()'); await until(() => cm(d, p3.id)?.querySelector('.cperm'));
  check(cm(d, p3.id)?.querySelector('.cperm'), '#1041: a question with a 10 s limit is open first');
  await until(() => cm(d, p3.id)?.querySelector('.cpermst.exp'), 120);  // the limit passes, the 5 s timer redraws it
  check(/Not answered, denied/.test(cm(d, p3.id)?.querySelector('.cpermst.exp')?.textContent || '') && !cm(d, p3.id).querySelector('.cperm'), '#1041: the time ran out: "Not answered, denied", no buttons (without a reload)');
  // a question of a 2.29 host (ids allow / deny with its own labels) looks the same
  const p4 = await say('Darf ich das ausführen?', {choices: [{id: 'allow', label: 'Erlauben', style: 'primary'}, {id: 'deny', label: 'Ablehnen', style: 'danger'}]});
  await w.eval('chatLoad()'); await until(() => cm(d, p4.id)?.querySelector('.cperm'));
  check(cm(d, p4.id).querySelectorAll('.cperm .cchb').length === 2, '#1041: allow / deny buttons of an older host show as a permission question');
  w.close();

  // ================= #1039 "working" only where the agent really writes
  await status({status: 'working', text: 'answering Alice in the chat'});
  w = await boot({user: 'alice', hash: 'l/' + SW}); d = w.document;
  await until(() => d.querySelector('#view .trow'));
  w.eval(`openDetail(${T1})`); await until(() => d.querySelector('#detail'));
  await sleep(400);
  check(!/answering Alice/.test(d.querySelector('#detail')?.textContent || '') && !d.querySelector('#d-typing:not(.hidden)'), '#1039: working without a task: nothing in the task, no status text there');
  w.eval(`chatOpen(${AG})`); await until(() => d.querySelector('#chat-typing'));
  await until(() => /answering Alice/.test(d.querySelector('#chat-st')?.textContent || ''));
  // 2.32.0 (#1062): the state only once, in the chat header; under the messages only the typing dots
  check(/answering Alice/.test(d.querySelector('#chat-st').textContent) && !/working on it|answering Alice/.test(d.querySelector('#chat-typing').textContent), '#1039 / #1062: ... but in the chat header, not again under the last message ' + d.querySelector('#chat-typing').textContent);
  w.close();
  await status({status: 'working', text: 'fixing the Safari login', task_id: T1});
  w = await boot({user: 'alice', hash: 'l/' + SW}); d = w.document;
  await until(() => d.querySelector('#view .trow'));
  w.eval(`openDetail(${T1})`); await until(() => d.querySelector('#d-typing:not(.hidden)'));
  check(/Claude is working on it/.test(d.querySelector('#d-typing')?.textContent || '') && /fixing the Safari login/.test(d.querySelector('#d-typing').textContent), '#1039: with its task: shows in exactly that task (with its text)');
  w.eval(`openDetail(${T2})`); await sleep(500);
  check(!d.querySelector('#d-typing:not(.hidden)') && !/fixing the Safari/.test(d.querySelector('#detail')?.textContent || ''), '#1039: ... not in another task of the list');
  w.eval(`chatOpen(${AG})`); await until(() => d.querySelector('#chat-typing'));
  check(!/working on it/.test(d.querySelector('#chat-typing')?.textContent || '') && /working on/.test(d.querySelector('#chat-st')?.textContent || '') && !/fixing the Safari/.test(d.querySelector('#chat-st')?.textContent || ''), '#1039: ... not under the chat messages (the header says "working on #…")');
  w.close();
  await status({status: 'idle'});

  // ================= #1034 "Agent listens in" / "Agent only via @"
  w = await boot({user: 'alice', hash: 'l/' + SW}); d = w.document;
  await until(() => d.querySelector('#view .trow'));
  const items = id => w.eval(`listMenuItems(${id}, document.body).map(x => x.label + '|' + (x.sub || '')).join('\\n')`);
  check(/Agent: Claude…\|Agent listens in/.test(items(SW)), '#1034: the software list\'s menu: "Agent listens in" ' + items(SW));
  check(/Agent: Claude…\|Agent only via @/.test(items(AGY)), '#1034: the agency list\'s menu: "Agent only via @"');
  w.eval(`shareModal(${SW}, {focus: 'agents'})`);
  await until(() => d.querySelector('.modal [data-lsn]'), 60);
  let sw = d.querySelector('.modal [data-lsn]');
  check(sw && sw.checked && /Agent listens in/.test(sw.closest('label').textContent) && /Default for software projects: on/.test(d.querySelector('.modal').textContent), '#1034: the switch in the share dialog, on in a software project');
  sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/state')).lists.find(l => l.id === SW).listen_agent_ids.length === 0);
  check((await call('GET', '/api/state')).lists.find(l => l.id === SW).listen_agent_ids.length === 0, '#1034: switched off');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  w.eval(`shareModal(${AGY}, {focus: 'agents'})`);
  await until(() => d.querySelector('.modal [data-lsn]'), 60);
  sw = d.querySelector('.modal [data-lsn]');
  check(sw && !sw.checked && /reacts only to an @mention/.test(d.querySelector('.modal').textContent), '#1034: off in an agency project, the hint says only @');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  await call('PATCH', `/api/lists/${SW}`, {listen_agent_ids: [AG]});
  await call('PATCH', `/api/lists/${SW}`, {folder: 'Dev'});
  await w.eval('load().then(render)'); await sleep(500);
  w.eval(`folderPropsModal('Dev')`); await until(() => d.querySelector('.modal #fs-al'), 60);
  check(d.querySelector('.modal #fs-al') && /Agent listens in/.test(d.querySelector('.modal label[for="fs-al"]')?.textContent || ''), '#1034: the folder settings have "Agent listens in"');
  w.close();

  // ================= Firefox: the permission question for real
  const fresh = await say('May I run the release build?\n```\n./build.sh --release 2.30.0\n```', {permission: true, expires_in: 540});
  const ffLogin = async ({ev, nav}, theme = 'light') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const geo = `(() => { const m = document.querySelector('#chat-msgs .cmsg[data-mid="${fresh.id}"]'); const b = m ? [...m.querySelectorAll('.cperm .cchb')] : []; if (b.length !== 2) return null;
    const r = b.map(x => x.getBoundingClientRect()); const hit = r.map(x => document.elementFromPoint(x.left + x.width / 2, x.top + x.height / 2));
    return {side: Math.abs(r[0].top - r[1].top) < 2 && r[0].right <= r[1].left, free: hit.every((h, i) => b[i].contains(h)), h: Math.min(r[0].height, r[1].height)}; })()`;
  for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440 ' + th;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + SW); await ready(ev);
    await ev(`(() => { chatOpen(${AG}, {float: false}); return 1; })()`); await sleep(1500);
    await ev(`(() => { const b = document.querySelector('#chat-msgs'); b.scrollTop = b.scrollHeight; return 1; })()`); await sleep(300);
    const g = await ev(geo);
    check(g && g.side && g.free, `${tag}: #1041 Allow / Deny side by side, nothing overlaps them ` + JSON.stringify(g));
    await shot(`p2300-${th}-1440-permission.png`);
    if (th === 'dark') {  // the last run: the question is answered afterwards
      // Enter in the message box sends nothing to the buttons; Enter on the focused Allow button allows
      const ci = await ev(`(() => { const r = document.querySelector('#chat-in').getBoundingClientRect(); return {x: Math.round(r.left + 20), y: Math.round(r.top + r.height / 2)}; })()`);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm', parameters: {pointerType: 'mouse'}, actions: [{type: 'pointerMove', x: ci.x, y: ci.y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx}); await sleep(300);

      await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k', actions: [{type: 'keyDown', value: ''}, {type: 'keyUp', value: ''}]}]}); await sleep(600);
      check(await ev(`!!document.querySelector('#chat-msgs .cmsg[data-mid="${fresh.id}"] .cperm')`), `${tag}: #1041 Enter in the message box does not allow`);
      await ev(`(() => { document.querySelector('#chat-msgs .cmsg[data-mid="${fresh.id}"] .cperm .cchb.st-primary').focus(); return 1; })()`);
      await cmd('input.performActions', {context: ctx, actions: [{type: 'key', id: 'k', actions: [{type: 'keyDown', value: ''}, {type: 'keyUp', value: ''}]}]}); await sleep(1200);
      check(await ev(`/^(\u{1F44D}\\s*)?Allowed/u.test(document.querySelector('#chat-msgs .cmsg[data-mid="${fresh.id}"] .cpermst.ok')?.textContent.trim() || '')`), `${tag}: #1041 Enter on the focused Allow button allows ` + await ev(`document.activeElement?.className + ' | ' + (document.querySelector('#chat-msgs .cmsg[data-mid="${fresh.id}"]')?.innerHTML || '').slice(-400) + ' | ' + document.querySelector('#toast')?.textContent`));
      await shot(`p2300-${th}-1440-permission-allowed.png`);
    }
    await ev(`(() => { chatClose(); shareModal(${SW}, {focus: 'agents'}); return 1; })()`); await sleep(1200);
    await shot(`p2300-${th}-1440-listens-in.png`);
  });
  const p5 = await say('May I clear the build cache?\n```\nrm -rf ./build/cache\n```', {permission: true, expires_in: 540});
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o, 'light') === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(1200);
    const g = await ev(geo.replace(String(fresh.id), String(p5.id)));
    check(g && g.side && g.free && g.h >= 40, `${tag}: #1041 the same two buttons on the phone, at least 40 px high ` + JSON.stringify(g));
    check(await ev(`document.documentElement.scrollWidth <= 390`), `${tag}: nothing sticks out sideways`);
    await shot('p2300-light-390-permission.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
