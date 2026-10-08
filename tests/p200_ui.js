// 2.0.0 UI tests (jsdom), fresh DB: agents (status dot on the avatar, header chip, agent badge on comments (2.4.1: no Wake button),
// Agents view with jobs Approve / Reject / Stop, chat side panel + phone view, Settings > Administration > Agents, turning a
// user into an agent), reactions ❤️ 👍 👎 on comments (names, approval), tidy suggestions (card, Apply, 👍), shared list tags
// (colored chips, personal tags with the person icon, tag editor, promote, list dialog: tags + "Agent may tidy up entries"),
// German texts.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,agents,comments';
const cks = {};
const call = async (u, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: cks[u]}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
let AT = '';
const v1 = async (method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + AT}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const events = async (since = 0) => (await v1('GET', `/agent/events?since=${since}`)).data || [];

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  cks.alice = await login('alice');
  const bob = (await call('alice', 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const carl = (await call('alice', 'POST', '/api/users', {username: 'carl', display_name: 'Carl', password: 'password123'})).id;
  cks.bob = await login('bob');
  for (const u of ['alice', 'bob']) await call(u, 'PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const ag = await call('alice', 'POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  AT = ag.token; const CL = ag.id;
  const L = (await call('alice', 'POST', '/api/lists', {name: 'Film', kind: 'project'})).id;
  await call('alice', 'PUT', `/api/lists/${L}/members`, {user_id: bob, role: 'edit'});
  await call('alice', 'PUT', `/api/lists/${L}/members`, {user_id: CL, role: 'edit'});
  await call('alice', 'POST', `/api/lists/${L}/tags`, {name: 'bug', color: '#f87171'});
  const T1 = (await call('alice', 'POST', '/api/tasks', {title: 'Cut trailer', list_id: L, assignee_id: CL, ltags: ['bug'], tags: ['mine']})).id;
  const T2 = (await call('alice', 'POST', '/api/tasks', {title: 'Private job', list_id: (await call('alice', 'POST', '/api/lists', {name: 'Private'})).id, tags: ['old']})).id;
  const k1 = (await v1('POST', `/tasks/${T1}/comments`, {body: 'Plan: rough cut, then music. OK?'})).id;
  await v1('PUT', '/agent/status', {status: 'working', text: 'Cutting'});
  const J = (await v1('POST', '/agent/jobs', {title: 'Rough cut', task_id: T1, state: 'waiting', log: 'plan ready'})).id;

  // ---- status dot, header chip, task rows with list tags
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  const chip = d.querySelector('#top .achip');
  check(chip && /Claude · 1 waiting/.test(chip.textContent) && chip.classList.contains('attn'), 'header chip: ' + chip?.textContent);
  const row = d.querySelector(`#view .trow[data-id="${T1}"]`);
  const lt = row?.querySelector('.tag.ltag');
  check(lt && lt.textContent === '#bug' && /--tc:\s*#f87171/.test(lt.getAttribute('style') || ''), 'list tag chip with its color');
  check(row?.querySelector('.tag.ptag svg') && /#mine/.test(row.querySelector('.tag.ptag').textContent), 'personal tag chip with person icon in a shared list');
  check(row?.querySelector('.who.agent .adot.st-working'), 'assignee avatar of the agent has the status dot');
  // ---- detail: agent badge, reactions, approval, wake
  w.eval(`openDetail(${T1})`); await sleep(1200);
  for (let i = 0; i < 30 && !d.querySelector(`.cm[data-cid="${k1}"]`); i++) await sleep(200);  // 2.28.0: the comments load after the panel
  const cm = d.querySelector(`.cm[data-cid="${k1}"]`);
  check(cm?.querySelector('.abadge') && /Agent/.test(cm.querySelector('.abadge').textContent), 'agent badge on its comment');
  check(cm && cm.querySelectorAll('.rx.add').length === 3, 'three reaction buttons (❤️ 👍 👎)');
  cm.querySelector('[data-act="c-react"][data-e="up"]').click(); await sleep(900);
  const cm2 = d.querySelector(`.cm[data-cid="${k1}"]`);
  const up = cm2?.querySelector('[data-e="up"]');
  check(up?.classList.contains('on') && up.querySelector('.rxn')?.textContent === '1' && /Alice/.test(up.title), 'my 👍 shown with count + name');
  check(/Approved/.test(d.querySelector('#toast')?.textContent || d.body.textContent), 'toast: Approved');
  let ev = await events();
  check(ev.some(e => e.event === 'reaction' && e.data.approval === 'approved'), 'agent got the approval');
  d.querySelector(`.cm[data-cid="${k1}"] [data-act="c-react-more"]`).click(); await sleep(300);
  const pk = d.querySelector('#pop .rxpick');
  check(pk && pk.querySelectorAll('[data-rx]').length >= 6 && pk.querySelector('[data-rx="heart"]') && pk.querySelector('#rx-in'), 'emoji picker: fixed set + custom field');
  pk.querySelector('#rx-in').value = '🚀'; pk.querySelector('[data-rx-ok]').click(); await sleep(900);
  check([...d.querySelectorAll(`.cm[data-cid="${k1}"] .rx`)].some(b => b.textContent.startsWith('🚀') && b.classList.contains('on')), 'custom emoji reaction shown');
  d.querySelector(`.cm[data-cid="${k1}"] [data-act="c-react-more"]`).click(); await sleep(300);
  d.querySelector('#pop [data-rx="🎉"]').click(); await sleep(900);
  check([...d.querySelectorAll(`.cm[data-cid="${k1}"] .rx`)].some(b => b.textContent.startsWith('🎉')), '🎉 from the picker');
  check([...d.querySelectorAll('.actl')].some(x => /approved the comment of/.test(x.textContent)) || !w.eval('showAct()'), 'approval in the history');
  // 2.4.1 (#376): no "Wake agent" button any more (the API route stays, see p200_api_test.py / p241_api_test.py)
  check(!d.querySelector('[data-act="agent-wake"]') && !/Wake/.test(d.querySelector('#detail').textContent), 'no Wake button in the task panel');
  // tag editor: list tag + personal tag + add by name
  const te = d.querySelector('#detail .tagedit');
  check(te?.querySelector('.tagpill.ltag') && te.querySelector('.tagpill.ptag [data-act="tag-promote"]'), 'tag editor: list tag + personal tag with promote');
  check([...d.querySelectorAll('#taglist option')].map(o => o.value)[0] === 'bug', 'autocomplete offers the list tags first');
  const inp = d.querySelector('#d-tag');
  inp.value = 'BUG'; inp.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); await sleep(700);
  inp.value = 'extra'; d.querySelector('#d-tag').dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); await sleep(800);
  let st = await call('alice', 'GET', '/api/state');
  let t1 = st.tasks.find(t => t.id === T1);
  check(t1.ltags.length === 1 && t1.tags.includes('extra') && t1.tags.includes('mine'), 'typed "BUG" = the existing list tag, "extra" = personal ' + JSON.stringify([t1.ltags, t1.tags]));
  d.querySelector('#detail [data-act="tag-promote"][data-tag="mine"]').click(); await sleep(1300);
  st = await call('alice', 'GET', '/api/state'); t1 = st.tasks.find(t => t.id === T1);
  check(t1.ltags.includes('mine') && !t1.tags.includes('mine'), 'promote: personal -> list tag');
  const bst = await call('bob', 'GET', '/api/state');
  check(bst.tasks.find(t => t.id === T1).ltags.includes('mine'), 'bob sees the promoted tag');
  // sidebar tag view includes list tags
  w.eval(`go('tag/bug')`); await sleep(500);
  check(d.querySelector(`#view .trow[data-id="${T1}"]`), 'tag view shows tasks with the list tag');

  // ---- tidy suggestion: card + Apply
  await call('alice', 'PATCH', `/api/lists/${L}`, {agent_tidy: 'suggest'});
  const T3 = (await call('bob', 'POST', '/api/tasks', {title: 'we should really fix the export thing it crashes with big files', list_id: L})).id;
  const ks = (await v1('POST', `/tasks/${T3}/comments`, {body: 'Tidy suggestion', suggestion: {title: 'Fix export crash', list_tags: ['bug'], priority: 'high'}})).id;
  w.eval(`closeDetail(); openDetail(${T3})`); await sleep(1300);
  const sug = d.querySelector(`.cm[data-cid="${ks}"] .sug`);
  check(sug && /Fix export crash/.test(sug.textContent) && sug.querySelector('.ltag') && sug.querySelector('[data-act="c-apply"]'), 'suggestion card with Apply');
  sug.querySelector('[data-act="c-apply"]').click(); await sleep(1500);
  st = await call('alice', 'GET', '/api/state');
  const t3 = st.tasks.find(t => t.id === T3);
  check(t3.title === 'Fix export crash' && t3.content.startsWith('**Original (Bob):** we should really') && t3.priority === 5, 'Apply: title, original kept, priority');
  check(/applied/.test(d.querySelector(`.cm[data-cid="${ks}"] .sug`)?.textContent || ''), 'card says applied');
  w.eval('closeDetail()');

  // ---- Agents view: cards, jobs, approve
  w.eval(`go('agents')`); await sleep(1200);
  check(d.querySelector('#top h1')?.textContent.startsWith('Agents'), 'Agents view title');
  const card = d.querySelector('.agcard');
  check(card && /Claude/.test(card.textContent) && /working · Cutting/.test(card.textContent) && card.querySelector('.adot.st-working'), 'agent card with status');
  const job = d.querySelector('.job.st-waiting');
  check(job && /Rough cut/.test(job.textContent) && /Cut trailer/.test(job.textContent) && job.querySelector('[data-a="approve"]'), 'waiting job with task + Approve');
  job.querySelector('[data-a="approve"]').click(); await sleep(1500);
  check((await v1('GET', '/agent/jobs')).data.find(j => j.id === J).state === 'running', 'approved: running');
  ev = await events();
  check(ev.some(e => e.event === 'job' && e.data.action === 'approve'), 'job event');
  check(d.querySelector('.job.st-running [data-a="stop"]') && !d.querySelector('.job [data-a="approve"]'), 'list refreshed: Stop left');
  check(d.querySelector('#side [data-go="agents"]'), 'Agents in the navigation (module on)');
  // ---- chat side panel (desktop)
  d.querySelector('.agcard [data-act="chat-open"]').click(); await sleep(900);
  const panel = d.querySelector('#achat');
  check(panel && !panel.classList.contains('hidden') && /Claude/.test(panel.querySelector('.chath').textContent), 'chat side panel open');
  const ci = d.querySelector('#chat-in');
  ci.value = 'How far is the trailer?'; ci.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Enter', bubbles: true})); await sleep(900);
  check(d.querySelector('#achat .cmsg.me')?.textContent.includes('How far is the trailer?'), 'my message shown');
  const cht = (await v1('GET', '/agent/chats')).data;
  check(cht.length === 1 && cht[0].body === 'How far is the trailer?', 'agent receives it');
  await v1('POST', '/agent/chats/1', {body: 'Half done. **Music** next.', task_id: T1});
  w.eval('chatLoad()'); await sleep(900);
  const am = d.querySelector('#achat .cmsg.ag');
  check(am && am.querySelector('strong, b')?.textContent === 'Music' && am.querySelector('[data-act="open-id"]'), 'agent answer (markdown + task link)');
  d.querySelector('#achat [data-act="chat-close"]').click(); await sleep(200);
  check(d.querySelector('#achat').classList.contains('hidden'), 'panel closes');
  w.close();

  // ---- quick add (#277): the list in plain words
  await call('alice', 'POST', '/api/lists', {name: 'Einkauf'});
  await call('alice', 'POST', '/api/lists', {name: '🏠 Home Office'});
  await call('alice', 'POST', '/api/lists', {name: 'Berlin trip'});
  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  const pq = t => w.eval(`(() => { const r = parseQuick(${JSON.stringify(t)}); return {title: r.title, list: r.list_id ? lname(listById(r.list_id)) : null, chip: (r.chips.find(c => c.type === 'list') || {}).label || null}; })()`);
  const cases = [
    ['Milch kaufen in Liste Einkauf', 'Milch kaufen', 'Einkauf'], ['Milch Liste Einkauf morgen', 'Milch', 'Einkauf'],
    ['Milch kaufen in die Liste Einkauf', 'Milch kaufen', 'Einkauf'], ['Brot in Einkauf', 'Brot', 'Einkauf'], ['Brot auf Einkauf', 'Brot', 'Einkauf'],
    ['Buy milk to list einkauf', 'Buy milk', 'Einkauf'], ['Print report in Home Office', 'Print report', '🏠 Home Office'],
    ['Print report into home office', 'Print report', '🏠 Home Office'], ['Call bank in list Home Office', 'Call bank', '🏠 Home Office'],
    ['Milch in Liste Eink', 'Milch', 'Einkauf'], ['Brief an Oma in Berlin', 'Brief an Oma in Berlin', null],
    ['Tickets in Berlin trip', 'Tickets', 'Berlin trip'], ['Make a list of groceries', 'Make a list of groceries', null],
    ['shopping list for mom', 'shopping list for mom', null], ['Liste Einkauf', 'Liste Einkauf', null],
    ['in Einkauf', 'in Einkauf', null], ['Wein in Einkaufen', 'Wein in Einkaufen', null], ['Brot ~eink', 'Brot', 'Einkauf'],
    ['Buy milk in inbox', 'Buy milk', 'Inbox']];
  for (const [t, title, list] of cases) { const r = pq(t); check(r.title === title && r.list === list && (!list || r.chip === list), `parseQuick ${JSON.stringify(t)} -> ${JSON.stringify(r)}`); }
  w.eval(`S.quick.ignore.add('list')`);
  const off = w.eval(`(() => { const r = parseQuick('Brot in Einkauf', S.quick.ignore); return [r.title, r.list_id || null, JSON.stringify(r.chips)]; })()`);
  check(off[0] === 'Brot in Einkauf' && off[1] === null && /"off":true/.test(off[2]), 'chip clicked off: the words stay in the title ' + off);
  w.close();

  // ---- phone: chat as its own view
  w = await boot({user: 'alice', mobile: true, hash: 'agents/' + CL}); d = w.document; await sleep(800);
  check(d.querySelector('#view .chview .chath') && d.querySelector('#view .cmsg.ag'), 'phone: chat view agents/<id>');
  w.close();

  // ---- list dialog: list tags + tidy; Settings > AI colleague (2.0.5, was Administration) > Agents; user -> agent
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  w.eval(`listModal(${L})`); await sleep(600);
  check(d.querySelector('#l-ltags')?.textContent.includes('#bug') && d.querySelector('#l-ltnew'), 'list dialog: list tags');
  w.eval(`shareModal(${L})`); await sleep(600);  // 2.6.0 (K12): the tidy setting lives in the Share dialog (Agents)
  const sel = d.querySelector('.shmodal #l-tidy');
  check(sel && sel.value === 'suggest' && !sel.disabled, 'Share dialog: tidy setting');
  sel.value = 'auto'; sel.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(900);
  check((await v1('GET', '/lists')).data.find(x => x.id === L).agent_tidy === 'auto', 'tidy saved (agent reads auto)');
  d.querySelector('.modal.shmodal')?.remove();
  d.querySelector('#l-ltnew').value = 'music'; d.querySelector('[data-lt="new"]').click(); await sleep(900);
  check((await v1('GET', `/lists/${L}/tags`)).data.some(x => x.name === 'music'), 'new list tag from the dialog');
  d.querySelector('.modal [data-m="close"]')?.click(); await sleep(200);
  w.eval(`settingsModal('agents')`);
  let agrow;  // (CI timing) wait for the agent list of the AI colleague tab
  for (let i = 0; i < 50 && !agrow; i++) { await sleep(200); agrow = d.querySelector('#s-ags [data-agid]'); }
  check(agrow && /Claude/.test(agrow.textContent) && /polling only/.test(agrow.querySelector('.n')?.title || ''), 'AI colleague > Agents lists the agent (2.5.1: details in the tooltip)');
  d.querySelector('[data-ag="new"]').click(); await sleep(300);
  d.querySelector('#pop [role="menuitem"]')?.click(); await sleep(300);  // 2.28.0 (#970): "Add agent…" asks team or personal first
  d.querySelector('#ag-user').value = 'robo'; d.querySelector('#ag-name').value = 'Robo';
  d.querySelector('.modal:last-of-type [data-m="ok"]').click(); await sleep(1200);
  check(/API token of Robo/.test(d.body.textContent) && [...d.querySelectorAll('input, code')].some(x => /abk_/.test(x.value || x.textContent)), 'new agent: token shown once');
  const us = (await call('alice', 'GET', '/api/users')).users;
  check(us.find(u => u.username === 'robo')?.kind === 'agent', 'robo created as agent');
  // pause (kill switch)
  w.__dialogs = undefined;
  [...d.querySelectorAll('.modal')].forEach(m => m.remove());
  w.eval(`settingsModal('agents')`);
  let cl;
  for (let i = 0; i < 50 && !cl; i++) { await sleep(200); cl = [...d.querySelectorAll('#s-ags [data-agid]')].find(r => /Claude/.test(r.textContent)); }
  check(cl, 'agent row after reopening the settings');
  cl?.querySelector('[data-ag="pause"]').click(); await sleep(1500);
  check((await v1('GET', '/me')).status === 403, 'pause from the settings = kill switch');
  await call('alice', 'PATCH', `/api/admin/agents/${CL}`, {enabled: true});
  w.close();
  // user -> agent in the user dialog
  w = await boot({user: 'alice'}); d = w.document;
  const users = (await call('alice', 'GET', '/api/users')).users;
  w.eval(`userModal(${JSON.stringify(users.find(u => u.username === 'carl'))}, null)`); await sleep(300);
  const ks2 = d.querySelector('#u-kind');
  check(ks2 && ks2.value === 'user', 'user dialog: Type');
  ks2.value = 'agent'; d.querySelector('.modal [data-m="save"]').click(); await sleep(1500);
  check((await call('alice', 'GET', '/api/users')).users.find(u => u.id === carl).kind === 'agent', 'carl is now an agent');
  w.close();

  // ---- German
  await call('alice', 'PATCH', '/api/settings', {lang: 'de'});
  await v1('PATCH', `/agent/jobs/${J}`, {state: 'waiting'});
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document; await sleep(1200);
  check(/Claude · 1 wartet/.test(d.querySelector('#top .achip')?.textContent || ''), 'German chip: ' + d.querySelector('#top .achip')?.textContent);
  check(d.querySelector('#top h1')?.textContent.startsWith('Agenten') && /Freigeben/.test(d.querySelector('.job')?.textContent || ''), 'German: Agenten, Freigeben');
  w.eval(`openDetail(${T1})`); await sleep(1200);
  check(d.querySelector('#detail') && !/anstoßen/.test(d.querySelector('#detail').textContent), 'German: no "anstoßen" (2.4.1)');
  w.close();

  const bad = errs.filter(e => !/Could not parse CSS/.test(e));
  check(!bad.length, 'no script errors: ' + bad.slice(0, 3).join(' | '));
  console.log(`\np200_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
