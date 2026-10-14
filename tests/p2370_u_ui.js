// 2.37.0 UI tests, part U, own container (start.sh), Firefox (desktop, mouse):
// - #1158 folder settings: Alice's folder "Studio" (two lists of her own) with the subfolder "Studio/Shopping" that holds only a
//   list Bob shared with her. The subfolder's menu shows "Folder settings…" and the share entries greyed out with the reason;
//   its dialog says the settings hold for new lists. In "Studio" a value that one list cannot take: 2.41.0 (#1423) saved at
//   once, the lists that do not follow are named; opening again shows the values; "Share…" opens over the dialog,
//   "Back" brings it back; closing asks nothing (everything is saved)
// - #1159 chat message saved as a task: see the second half
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2370_u_ui', check, shots: 'P2370U_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
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
  const ALICE = (await call(CA, 'GET', '/api/state')).me.id;
  // #1158 set-up
  await call(CA, 'POST', '/api/lists', {name: 'Homepage', folder: 'Studio'});
  await call(CA, 'POST', '/api/lists', {name: 'Meeting', folder: 'Studio'});
  const dm = await call(CB, 'POST', '/api/lists', {name: 'Shop DM'});
  await call(CB, 'PUT', `/api/lists/${dm.id}/members`, {user_id: ALICE, role: 'edit'});
  const mv = await call(CA, 'POST', '/api/lists/reorder', {folder: {[dm.id]: 'Studio/Shopping'}});
  check(mv.http === 200, 'Bob\'s shared list in Alice\'s subfolder ' + mv.http);
  // #1159 set-up: an agent with a message that offers saving (and a file), a channel message of Bob
  const ag = await call(CA, 'POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'helper', display_name: 'Helper'});
  const AGH = {Authorization: 'Bearer ' + ag.token};
  const wl = await call(CA, 'POST', '/api/lists', {name: 'Work'});
  await call(CA, 'PUT', `/api/lists/${wl.id}/members`, {user_id: ag.id, role: 'edit'});
  const fd = new FormData(); fd.append('body', '# Release plan\n\nThe **whole** plan:\n\n- one\n- two'); fd.append('offer_save', 'true');
  fd.append('file', new Blob(['plan file'], {type: 'text/plain'}), 'plan-notes.txt');
  const am = await (await fetch(B + `api/v1/agent/chats/${ALICE}`, {method: 'POST', headers: AGH, body: fd})).json();
  check(am.id && am.offer_save === true, '#1159: the agent message with offer_save ' + JSON.stringify(am).slice(0, 120));
  const tl = await call(CA, 'POST', '/api/lists', {name: 'Team list'});
  await call(CA, 'PUT', `/api/lists/${tl.id}/members`, {user_id: bob.id, role: 'edit'});
  const RID = ((await call(CB, 'GET', '/api/team')).rooms || []).find(x => x.kind === 'list' && x.list_id === tl.id)?.id;
  const tm = await call(CB, 'POST', `/api/team/rooms/${RID}/messages`, {body: 'Minutes of today:\n\n- decided A\n- decided B'});
  check(RID && tm.id, '#1159: Bob writes in the channel');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  await firefox(async o => {
    const {cmd, ev, ctx, nav, shot} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B); await ready(ev, `!!document.querySelector('#side') && typeof folderMenu === 'function' && S.lists.length > 2`);
    await sleep(600);

    // ================= #1158: the menu of the subfolder with only a list of others
    const menuOf = f => ev(`(() => { folderMenu(document.querySelector('#side') , ${JSON.stringify(f)}); return [...document.querySelectorAll('#pop [role="menuitem"]')].map(b => ({t: b.querySelector('.ml')?.firstChild?.textContent || '', sub: b.querySelector('.msub')?.textContent || '', dis: b.disabled, aria: b.getAttribute('aria-disabled')})); })()`);
    let m = await menuOf('Studio/Shopping');
    const fs = m.find(x => x.t === 'Folder settings…'), sh = m.find(x => x.t === 'Share folder…');
    check(fs && !fs.dis, '#1158: the subfolder with only a list of others shows "Folder settings…" ' + JSON.stringify(m.map(x => x.t)));
    check(sh && sh.dis && sh.aria === 'true' && /Only your own lists/.test(sh.sub), '#1158: "Share folder…" greyed out with the reason ' + JSON.stringify(sh));
    await shot('p2370u-folder-menu.png');
    await ev(`(() => { closePop(); return 1; })()`);
    m = await menuOf('Studio');
    check(m.some(x => x.t === 'Share folder…' && !x.dis) && m.some(x => x.t === 'Folder settings…'), '#1158: the folder with own lists: share and settings usable');
    await ev(`(() => { closePop(); return 1; })()`);
    // the dialog of the subfolder: the hint, no "Apply to"
    await ev(`(() => { folderPropsModal('Studio/Shopping'); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal #fs-am')`);
    const sub = await ev(`(() => ({hint: document.querySelector('.modal .fsnone')?.textContent.trim() || '', apply: document.querySelector('.modal .fsapply')?.hidden, nw: document.querySelector('.modal [name="fs-ap"]:checked')?.value}))()`);
    check(/Applies to new lists in this folder\. Shared lists of others keep their settings\./.test(sub.hint) && sub.apply === true && sub.nw === 'new', '#1158: the dialog says it holds for new lists ' + JSON.stringify(sub));
    // 2.41.0 (#1423): the folder settings save every change at once (switches, "Saved · Undo"); no Save / Save anyway, no
    // question when closing. "Share…" (the folder's Share dialog, #1420) and Repository… still open over it with Back.
    await ev(`(() => { const s = document.querySelector('.modal #fs-am'); s.checked = true; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal .ssaved.on')`), '#1158: the subfolder saves at once (no list to ask about)');
    const sp = await call(CA, 'GET', '/api/folders/props?folder=' + encodeURIComponent('Studio/Shopping'));
    check(sp.props && sp.props.agent_members === true, '#1158: the subfolder\'s value is stored ' + JSON.stringify(sp.props));
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    await ready(ev, `!document.querySelector('.modal #fs-am')`);

    // ================= #1158: a value one list cannot take is named (after saving now)
    await ev(`(() => { folderPropsModal('Studio'); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal #fs-td')`);
    await ev(`(() => { const s = document.querySelector('.modal #fs-am'); s.checked = true; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal .ssaved.on')`);
    await ev(`(() => { const s = document.querySelector('.modal #fs-td'); s.disabled = false; s.value = 'suggest'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    await ready(ev, `!document.querySelector('.modal #fs-prev').hidden`);
    const pv = await ev(`(() => { const p = document.querySelector('.modal #fs-prev'); return {txt: p.textContent, role: p.getAttribute('role'), ok: !!document.querySelector('.modal [data-m="ok"]'), still: !!document.querySelector('.modal #fs-td')}; })()`);
    check(/do(es)? not follow/.test(pv.txt) && pv.role === 'status' && !pv.ok && pv.still, '#1158: the lists that do not follow are named, the dialog stays ' + JSON.stringify(pv));
    await shot('p2370u-not-following.png');
    await ev(`(() => { document.querySelector('.modal [data-m="close"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.modal #fs-td')`), '#1158: closing closes at once (everything is saved)');
    await ev(`(() => { folderPropsModal('Studio'); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal #fs-td')`);
    const vals = await ev(`(() => ({am: document.querySelector('.modal #fs-am').checked, ap: !!document.querySelector('.modal #fs-ap[data-fk]'), td: document.querySelector('.modal #fs-td').value}))()`);
    check(vals.am === true && !vals.ap && vals.td === 'suggest', '#1158: open again shows the saved values (2.40.0 #1373: no agent_peers select) ' + JSON.stringify(vals));

    // ================= #1158: "Share…" as a sub-dialog with Back
    await ev(`(() => { document.querySelector('.modal [data-m="people"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal.fshmodal')`);
    const pp = await ev(`(() => { const ms = [...document.querySelectorAll('.modal')]; const props = ms.find(x => x.querySelector('#fs-am')); return {n: ms.length, hidden: props && getComputedStyle(props).display === 'none', back: document.querySelector('.modal.fshmodal .foot .btn.pri')?.textContent.trim()}; })()`);
    check(pp.n === 2 && pp.hidden && pp.back === 'Back', '#1158: the Share dialog opens over the folder dialog with Back ' + JSON.stringify(pp));
    await ev(`(() => { document.querySelector('.modal.fshmodal .foot .btn.pri').click(); return 1; })()`);
    await ready(ev, `!document.querySelector('.modal.fshmodal')`);
    const bk = await ev(`(() => { const p = document.querySelector('.modal #fs-am')?.closest('.modal'); return {there: !!p, shown: p && getComputedStyle(p).display !== 'none', am: p && p.querySelector('#fs-am').checked}; })()`);
    check(bk.there && bk.shown && bk.am === true, '#1158: Back brings the folder dialog back ' + JSON.stringify(bk));
    // Repository… the same way
    await ev(`(() => { document.querySelector('.modal [data-m="repos"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.modal #l-repos')`);
    await ev(`(() => { document.querySelector('.modal #l-repos').closest('.modal').querySelector('[data-m="close"]').click(); return 1; })()`);
    await ready(ev, `!document.querySelector('.modal #l-repos')`);
    check(await ev(`document.querySelector('.modal #fs-am')?.checked === true && getComputedStyle(document.querySelector('.modal #fs-am').closest('.modal')).display !== 'none'`), '#1158: Repository… and back keeps the state too');
    await ev(`(() => { document.querySelector('.modal #fs-am').closest('.modal').querySelector('[data-m="close"]').click(); return 1; })()`);
    await sleep(300);
    check(await ev(`!document.querySelector('.modal #fs-am') && !document.querySelector('.cdlg')`), '#1158: closing asks nothing (saved at once)');
    const st = await call(CA, 'GET', '/api/folders/props?folder=Studio');
    check(st.props && st.props.agent_members === true && st.props.agent_tidy === 'suggest', '#1158: the values stay saved ' + JSON.stringify(st.props));

    // ================= #1159: save an agent message (the offer button), the mark, saving again, the link back
    await nav(B + '#agents/' + ag.id);
    check(await ready(ev, `!!document.querySelector('#chat-msgs [data-mid="a:${am.id}"]')`, 60), '#1159: the agent chat shows the message');
    const ofr = await ev(`(() => { const m = document.querySelector('#chat-msgs [data-mid="a:${am.id}"]'); return {offer: !!m.querySelector('.csoffer [data-act="chat-save"]'), menu: !!m.querySelector('[data-act="chat-msg-menu"]'), txt: m.querySelector('.csoffer')?.textContent.trim()}; })()`);
    check(ofr.offer && ofr.menu && ofr.txt === 'Save as task', '#1159: the offer button "Save as task" and the message menu ' + JSON.stringify(ofr));
    await shot('p2370u-offer.png');
    await ev(`(() => { document.querySelector('#chat-msgs [data-mid="a:${am.id}"] .csoffer button').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.csmodal #cs-title')`);
    const dl = await ev(`(() => { const md = document.querySelector('.csmodal'); return {title: md.querySelector('#cs-title').value, list: md.querySelector('#cs-list').selectedOptions[0]?.textContent, n: md.querySelector('#cs-list').options.length, due: !!md.querySelector('[data-dpfor="cs-due"]'), lists: [...md.querySelector('#cs-list').options].map(o => o.textContent)}; })()`);
    check(dl.title === 'Release plan' && dl.list === 'Basket' && dl.due && dl.lists.includes('Work') && dl.lists.includes('Shop DM'), '#1159: the dialog: title from the heading, the inbox, lists I may change, a date picker ' + JSON.stringify(dl));
    await shot('p2370u-save-dialog.png');
    await ev(`(() => { dpSet(document.querySelector('.csmodal #cs-due'), '2026-10-20'); document.querySelector('.csmodal [data-m="ok"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.csmodal') && !!document.querySelector('#chat-msgs [data-mid="a:${am.id}"] .csaved')`, 40), '#1159: saved: the dialog closes, the message shows "Saved"');
    check(await ev(`!document.querySelector('#chat-msgs [data-mid="a:${am.id}"] .csoffer')`), '#1159: the offer button goes once saved');
    const st1 = await call(CA, 'GET', `/api/agents/${ag.id}/chat`);
    const tid = (st1.messages || []).find(m => m.id === am.id)?.saved_task_id;
    const task = tid ? await call(CA, 'GET', '/api/tasks/' + tid) : {};
    check(task.title === 'Release plan' && task.due === '2026-10-20' && /The \*\*whole\*\* plan:/.test(task.content || '') && (task.content || '').includes(`#msg/a/${ag.id}/${am.id})`) && (task.attachments || []).some(a => a.name === 'plan-notes.txt'),
      '#1159: the task has the whole text, the file and the link back ' + JSON.stringify({t: task.title, due: task.due, att: (task.attachments || []).map(a => a.name), c: (task.content || '').slice(-120)}));
    // saving again says already saved
    await ev(`(() => { document.querySelector('#chat-msgs [data-mid="a:${am.id}"] [data-act="chat-msg-menu"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('#pop [role="menuitem"]')`);
    const mi = await ev(`[...document.querySelectorAll('#pop [role="menuitem"] .ml')].map(x => x.textContent)`);
    check(mi.includes('Saved as a task: open it'), '#1159: the menu of a saved message offers to open its task ' + JSON.stringify(mi));
    await ev(`(() => { closePop(); chatSaveModal('agent', S.chat.msgs.find(m => m.id === ${am.id})); return 1; })()`);
    await sleep(300);
    const tt = await ev(`document.querySelector('#toast')?.textContent || ''`);
    check(/Already saved as a task/.test(tt) && !(await ev(`!!document.querySelector('.csmodal')`)), '#1159: saving again says "Already saved as a task" ' + tt);
    // the mark opens the task; the description shows the link back
    await ev(`(() => { document.querySelector('#chat-msgs [data-mid="a:${am.id}"] .csaved').click(); return 1; })()`);
    check(await ready(ev, `S.sel === ${tid} && !!document.querySelector('#detail')`, 40), '#1159: the mark opens the task');
    await ready(ev, `!!document.querySelector('#detail #d-md a[href$="#msg/a/${ag.id}/${am.id}"]')`, 20);
    check(await ev(`!!document.querySelector('#detail #d-md a[href$="#msg/a/${ag.id}/${am.id}"]')`), '#1159: the description shows the link back to the message');
    await shot('p2370u-saved-task.png');
    // the link back opens the chat at the message
    await nav(B + `#msg/a/${ag.id}/${am.id}`);
    check(await ready(ev, `!!document.querySelector('#chat-msgs [data-mid="a:${am.id}"]')`, 60), '#1159: #msg/a/... opens the chat with the message');

    // ================= #1159: team chat -- Bob's message (not mine) has the menu with "Save as task"
    await nav(B + '#team/' + RID);
    check(await ready(ev, `!!document.querySelector('#tc-msgs [data-mid="t:${tm.id}"]')`, 60), '#1159: the channel shows Bob\'s message');
    await ev(`(() => { document.querySelector('#tc-msgs [data-mid="t:${tm.id}"] [data-act="tc-msg-menu"]').click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('#pop [role="menuitem"]')`);
    const ti = await ev(`[...document.querySelectorAll('#pop [role="menuitem"] .ml')].map(x => x.textContent)`);
    check(ti.includes('Save as task') && !ti.includes('Edit') && !ti.includes('Delete'), '#1159: a message of someone else: Save as task, no Edit / Delete ' + JSON.stringify(ti));
    await ev(`(() => { [...document.querySelectorAll('#pop [role="menuitem"]')].find(b => b.textContent.includes('Save as task')).click(); return 1; })()`);
    await ready(ev, `!!document.querySelector('.csmodal #cs-title')`);
    check(await ev(`document.querySelector('.csmodal #cs-title').value === 'Minutes of today:'`), '#1159: team: the title from the first line');
    await ev(`(() => { document.querySelector('.csmodal [data-m="ok"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#tc-msgs [data-mid="t:${tm.id}"] .csaved')`, 40), '#1159: team: the message shows "Saved"');
    await shot('p2370u-team-saved.png');
  }, false);

  console.log(`p2370_u_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
