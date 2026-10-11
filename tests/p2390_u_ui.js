// 2.39.0 UI tests, part U, own container (start.sh), Firefox (desktop, mouse): #1168 the Playbook of a list and a folder.
// Alice owns the folder "Finance" with the list "Receipts" (shared with the agent Helper and with Bob as an editor, not an
// admin). The folder has a playbook of its own.
// - the list dialog shows the Playbook area: the folder's part marked as inherited, "Edit" for Alice
// - the editor: the counter x / 8000, too long = Save off, the preview renders the Markdown, Save makes version 1
// - saved meanwhile elsewhere: "Changed in the meantime" with "Reload"
// - versions: the list, compare (lines added / removed), restore with a question first
// - an agent's proposal: the notice, the comparison, "Apply" makes it the playbook (source proposal)
// - the folder dialog: the same area with "Applies to all lists in this folder"
// - a regular check: new (agent, every working day, time), it shows in the list and in the area
// - the list menu has "Playbook", the help the three examples, News the text of a proposal
// - Bob (editor, no admin): reads the playbook, no Edit, no regular check
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2390_u_ui', check, shots: 'P2390U_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,agents';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const bob = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'helper', display_name: 'Helper'});
  const AGH = {Authorization: 'Bearer ' + ag.token};
  const ls = await call(CA, 'POST', '/api/lists', {name: 'Receipts', folder: 'Finance'});
  const LID = ls.id;
  await call(CA, 'PUT', `/api/lists/${LID}/members`, {user_id: ag.id, role: 'edit'});
  await call(CA, 'PUT', `/api/lists/${LID}/members`, {user_id: bob.id, role: 'edit'});
  await call(CA, 'POST', '/api/tasks', {title: 'Pharmacy receipt', list_id: LID});
  const fp = await call(CA, 'PUT', '/api/folders/playbook', {folder: 'Finance', text: '## Folder rule\n\nNever pay anything.'});
  check(fp.http === 200 && fp.version, 'the folder playbook is saved ' + JSON.stringify(fp));

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const asUser = async (ev, nav, u) => {
    await ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status)`).catch(() => 0);
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
    await nav(B); await ready(ev, `!!document.querySelector('#side') && typeof pbOpen === 'function' && S.lists.some(l => l.id === ${LID})`, 60);
    await sleep(400);
    return st;
  };
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    check(await asUser(ev, nav, 'alice') === 200, 'Firefox: login Alice');

    // ================= the area in the list dialog
    await ev(`(() => { listModal(${LID}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.lmodal #pb-area [data-pb="edit"]')`), 'the list dialog shows the Playbook area with Edit');
    const a0 = await ev(`(() => { const b = document.querySelector('.lmodal #pb-area'); return {inh: b.querySelector('.pbinh')?.textContent || '', ck: !!b.querySelector('[data-pb="checks"]'), empty: !!b.querySelector('.pbown')}; })()`);
    check(/From the folder Finance/.test(a0.inh) && /Folder rule/.test(a0.inh) && /read only here/.test(a0.inh), 'the folder part is shown and marked as inherited ' + JSON.stringify(a0));
    check(a0.ck && !a0.empty, 'Regular check offered, no own text yet ' + JSON.stringify(a0));
    await shot('p2390u-list-area.png');

    // ================= the editor
    await ev(`(() => { document.querySelector('.lmodal #pb-area [data-pb="edit"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.pbedmd #pb-text')`), 'Edit opens the editor');
    check(await ev(`document.querySelector('.lmodal').style.display === 'none'`), 'the list dialog steps aside');
    const setText = t => ev(`(() => { const ta = document.querySelector('.pbedmd #pb-text'); ta.value = ${JSON.stringify(t)}; ta.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    await setText('x'.repeat(8001));
    const over = await ev(`({c: document.querySelector('.pbedmd #pb-cnt').textContent, o: document.querySelector('.pbedmd #pb-cnt').classList.contains('over'), d: document.querySelector('.pbedmd [data-pe="save"]').disabled})`);
    check(over.c === '8001 / 8000 characters' && over.o && over.d, 'too long: the counter is marked, Save is off ' + JSON.stringify(over));
    const TXT = '## Receipts\n\n1. Read the **amount**\n2. Tag #submitted';
    await setText(TXT);
    check(await ev(`document.querySelector('.pbedmd #pb-cnt').textContent === '${[...TXT].length} / 8000 characters' && !document.querySelector('.pbedmd [data-pe="save"]').disabled`), 'within the limit: Save on');
    await ev(`(() => { document.querySelector('.pbedmd [data-pbm="prev"]').click(); return 1; })()`);
    const pv = await ev(`(() => { const p = document.querySelector('.pbedmd #pb-prev'); return {hid: p.hidden, ta: document.querySelector('.pbedmd #pb-text').hidden, strong: p.querySelector('.pbown strong, .pbown b')?.textContent || '', inh: !!p.querySelector('.pbinh')}; })()`);
    check(!pv.hid && pv.ta && pv.strong === 'amount' && pv.inh, 'Preview renders the Markdown with the folder part ' + JSON.stringify(pv));
    await shot('p2390u-editor-preview.png');
    await ev(`(() => { document.querySelector('.pbedmd [data-pbm="edit"]').click(); document.querySelector('.pbedmd [data-pe="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.pbedmd') && document.querySelector('.lmodal').style.display !== 'none'`), 'Save closes the editor, the list dialog comes back');
    check(await ready(ev, `/Read the/.test(document.querySelector('.lmodal #pb-area .pbown')?.textContent || '')`), 'the area shows the saved text');
    let g = await call(CA, 'GET', `/api/lists/${LID}/playbook`);
    check(g.text === TXT && g.version === 1 && /Folder rule/.test(g.effective || ''), 'the server has version 1 ' + JSON.stringify({v: g.version, t: g.text}));

    // ================= saved meanwhile elsewhere
    await ev(`(() => { document.querySelector('.lmodal #pb-area [data-pb="edit"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.pbedmd #pb-text')`);
    const p2 = await call(CA, 'PUT', `/api/lists/${LID}/playbook`, {text: TXT + '\n3. Second device', base_version: 1});
    check(p2.http === 200 && p2.version === 2, 'another device saves version 2 ' + JSON.stringify(p2));
    await setText(TXT + '\n3. Mine');
    await ev(`(() => { document.querySelector('.pbedmd [data-pe="save"]').click(); return 1; })()`);
    check(await ready(ev, `/Changed in the meantime/.test(document.querySelector('.pbedmd #pb-err')?.textContent || '') && !document.querySelector('.pbedmd #pb-err').hidden`), 'a stale save says "Changed in the meantime"');
    await shot('p2390u-conflict.png');
    await ev(`(() => { document.querySelector('.pbedmd [data-pe="reload"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.cdlg')`);
    await ev(`(() => { document.querySelector('.cdlg [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `/Second device/.test(document.querySelector('.pbedmd #pb-text').value) && document.querySelector('.pbedmd #pb-err').hidden`), 'Reload puts the newest version into the field');
    await ev(`(() => { document.querySelector('.pbedmd [data-pe="cancel"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.pbedmd')`), 'Cancel without changes closes at once');

    // ================= versions: compare and restore
    await ready(ev, `!!document.querySelector('.lmodal #pb-area [data-pb="versions"]')`);
    await ev(`(() => { document.querySelector('.lmodal #pb-area [data-pb="versions"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.pbvmd .pbvrow').length === 2`), 'Versions lists 2 versions');
    const vr = await ev(`[...document.querySelectorAll('.pbvmd .pbvrow')].map(x => x.textContent.replace(/\\s+/g, ' ').trim())`);
    check(/Version 2.*current/.test(vr[0]) && /Alice/.test(vr[0]) && /edited/.test(vr[0]) && /characters/.test(vr[0]), 'a row: version, current, who, source, characters ' + JSON.stringify(vr));
    await ev(`(() => { document.querySelector('.pbvmd .pbvrow[data-v="1"] [data-pv="cmp"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.pbvmd .pbdiff')`), 'Compare shows the line diff');
    const df = await ev(`({add: [...document.querySelectorAll('.pbvmd .pbd.add')].map(x => x.textContent), del: document.querySelectorAll('.pbvmd .pbd.del').length, sum: document.querySelector('.pbvmd .pbdsum')?.textContent})`);
    check(df.add.length === 1 && /Second device/.test(df.add[0]) && df.del === 0 && /1 lines added, 0 removed/.test(df.sum), 'the diff: one line added ' + JSON.stringify(df));
    await shot('p2390u-compare.png');
    await ev(`(() => { document.querySelector('.pbvmd [data-pv="restore"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.cdlg')`);
    check(/Restore version 1\?/.test(await ev(`document.querySelector('.cdlg h3')?.textContent || ''`)), 'Restore asks first');
    await ev(`(() => { document.querySelector('.cdlg [data-cd="yes"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.pbvmd')`), 'after restoring the versions dialog closes');
    g = await call(CA, 'GET', `/api/lists/${LID}/playbook`);
    const vs = await call(CA, 'GET', `/api/lists/${LID}/playbook/versions`);
    check(g.text === TXT && g.version === 3 && vs.versions?.[0]?.source === 'restore', 'version 3 = the text of version 1, source restore ' + JSON.stringify({v: g.version, s: vs.versions?.[0]?.source}));

    // ================= an agent's proposal
    const pr = await call(null, 'POST', `/api/v1/lists/${LID}/playbook/proposals`, {text: TXT + '\n3. Ask before deleting', note: 'Deleting needs a question'}, AGH);
    check(pr.http === 201 && pr.id, 'the agent proposes a change ' + JSON.stringify(pr));
    await ev(`(() => { document.querySelector('.lmodal').remove(); listModal(${LID}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.lmodal #pb-area .pbprop')`), 'the area shows the proposal');
    check(/Proposal from Helper/.test(await ev(`document.querySelector('.lmodal #pb-area .pbprop').textContent`)) && /Deleting needs a question/.test(await ev(`document.querySelector('.lmodal #pb-area .pbprop').textContent`)), 'the notice names the agent and its note');
    await ev(`(() => { document.querySelector('.lmodal #pb-area [data-pb="prop"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.pbpmd .pbdiff .pbd.add')`), 'the proposal opens with the comparison');
    check(/Ask before deleting/.test(await ev(`document.querySelector('.pbpmd .pbd.add').textContent`)), 'the added line of the proposal is marked');
    await shot('p2390u-proposal.png');
    await ev(`(() => { document.querySelector('.pbpmd [data-pp="apply"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.pbpmd')`), 'Apply closes the proposal');
    g = await call(CA, 'GET', `/api/lists/${LID}/playbook`);
    const vs2 = await call(CA, 'GET', `/api/lists/${LID}/playbook/versions`);
    check(/Ask before deleting/.test(g.text) && !(g.proposals || []).length && vs2.versions?.[0]?.source === 'proposal', 'the proposal is the playbook now (source proposal) ' + JSON.stringify({p: (g.proposals || []).length, s: vs2.versions?.[0]?.source}));
    check(await ready(ev, `!document.querySelector('.lmodal #pb-area .pbprop') && /Ask before deleting/.test(document.querySelector('.lmodal #pb-area').textContent)`), 'the area shows the new text, no notice');

    // ================= a regular check
    await ev(`(() => { document.querySelector('.lmodal #pb-area [data-pb="checks"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.pbckmd [data-ck="new"]')`), 'Regular check… opens its dialog with New check');
    await ev(`(() => { document.querySelector('.pbckmd [data-ck="new"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.pbckmd #pc-freq')`);
    const opts = await ev(`[...document.querySelectorAll('.pbckmd #pc-ag option')].map(o => o.textContent)`);
    check(JSON.stringify(opts) === '["Helper"]', 'the agents of the list to choose ' + JSON.stringify(opts));
    await ev(`(() => { const f = document.querySelector('.pbckmd #pc-freq'); f.value = 'weekdays'; f.dispatchEvent(new Event('change', {bubbles: true})); const t = document.querySelector('.pbckmd #pc-time'); t.value = '07:30'; document.querySelector('.pbckmd #pc-prompt').value = 'Compare with the bank'; return 1; })()`);
    await shot('p2390u-check-form.png');
    await ev(`(() => { document.querySelector('.pbckmd [data-pf="save"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.pbckmd .schedrow').length === 1`), 'the new check shows in the list');
    const ckr = await ev(`document.querySelector('.pbckmd .schedrow').textContent.replace(/\\s+/g, ' ')`);
    check(/Helper/.test(ckr) && /Every working day/.test(ckr) && /Compare with the bank/.test(ckr) && /next:/.test(ckr), 'the row: agent, rhythm, job, next run ' + ckr);
    const cks = await call(CA, 'GET', `/api/lists/${LID}/checks`);
    check(cks.checks?.length === 1 && cks.checks[0].freq === 'weekdays' && cks.checks[0].time === '07:30' && cks.checks[0].agent?.id === ag.id, 'the server has the check ' + JSON.stringify(cks.checks?.[0] || cks).slice(0, 200));
    await ev(`(() => { document.querySelector('.pbckmd [data-ck="run"]').click(); return 1; })()`);
    check(await ready(ev, `/Sent to Helper/.test(document.querySelector('#toast')?.textContent || '')`), 'Check now sends it to the agent');
    await ev(`(() => { document.querySelector('.pbckmd [data-ck="close"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.pbckmd') && /Helper: Every working day/.test(document.querySelector('.lmodal #pb-area .pbckline')?.textContent || '')`), 'the area names the check');
    await ev(`(() => { document.querySelector('.lmodal').remove(); return 1; })()`);

    // ================= the list menu, the help, News
    await ev(`load().then(render)`); await sleep(500);
    const mi = await ev(`listMenuItems(${LID}, document.querySelector('#side')).flatMap(x => x && x.more ? x.more : [x]).filter(x => x && x.label).map(x => x.label)`);
    check(mi.includes('Playbook'), 'the list menu has "Playbook" ' + JSON.stringify(mi));
    await ev(`(() => { pbOpen(${LID}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.pbmodal #pb-area .pbown')`), '"Playbook" opens its own dialog with the text');
    await ev(`(() => { document.querySelector('.pbmodal').remove(); return 1; })()`);
    check(await ev(`(pbHelpHtml().match(/class="pbex"/g) || []).length === 3 && /Receipts and insurance refunds/.test(pbHelpHtml()) && /Bug tickets/.test(pbHelpHtml())`), 'the help has the three examples');
    check(/Helper.*proposes a change to the playbook of.*Receipts/.test(await ev(`newsText({kind: 'playbook_proposal', list_id: ${LID}, actor_id: ${ag.id}, data: {agent: 'Helper', name: 'Receipts'}}, {${ag.id}: 'Helper'})`)), 'News says what the agent proposes');

    // ================= the folder dialog
    await ev(`(() => { folderPropsModal('Finance'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #pb-area [data-pb="edit"]')`), 'the folder dialog shows the Playbook area with Edit');
    const fa = await ev(`document.querySelector('.modal #pb-area').textContent.replace(/\\s+/g, ' ')`);
    check(/Applies to all lists in this folder/.test(fa) && /Folder rule/.test(fa) && /Currently 1 list in it/.test(fa), 'the folder area: applies to all lists, its text ' + fa.slice(0, 200));
    check(!(await ev(`!!document.querySelector('.modal #pb-area [data-pb="checks"], .modal #pb-area .pbprop')`)), 'no checks / proposals at a folder');
    await shot('p2390u-folder-area.png');
    await ev(`(() => { document.querySelector('.modal #pb-area [data-pb="edit"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.pbedmd #pb-text')`);
    await setText('## Folder rule\n\nNever pay anything.\nKeep receipts ten years.');
    await ev(`(() => { document.querySelector('.pbedmd [data-pe="save"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.pbedmd') && /ten years/.test(document.querySelector('.modal #pb-area')?.textContent || '')`), 'the folder playbook saves from its dialog');
    const fg = await call(CA, 'GET', '/api/folders/playbook?folder=Finance');
    check(/ten years/.test(fg.text || '') && fg.version === 2, 'the server has folder version 2 ' + JSON.stringify({v: fg.version}));
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    await sleep(300);

    // ================= Bob: editor of the list, no admin: reads only
    check(await asUser(ev, nav, 'bob') === 200, 'Firefox: login Bob');
    await ev(`(() => { listModal(${LID}); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.lmodal #pb-area .pbown')`), 'Bob sees the playbook');
    const bb = await ev(`(() => { const b = document.querySelector('.lmodal #pb-area'); return {edit: !!b.querySelector('[data-pb="edit"]'), ck: !!b.querySelector('[data-pb="checks"]'), ro: b.querySelector('.pbro')?.textContent || '', ver: !!b.querySelector('[data-pb="versions"]'), inh: /ten years/.test(b.textContent)}; })()`);
    check(!bb.edit && !bb.ck && /Only the owner and list admins can change it/.test(bb.ro) && bb.ver && bb.inh, 'Bob: read only, no Edit, no checks, versions to read ' + JSON.stringify(bb));
    await shot('p2390u-bob-readonly.png');
    const pb = await call(CB, 'PUT', `/api/lists/${LID}/playbook`, {text: 'mine'});
    check(pb.http === 403, 'Bob cannot write it through the API either ' + pb.http);
  }, false);

  console.log(`p2390_u_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
