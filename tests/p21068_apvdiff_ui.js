// 2.1068.0 (#5831) the approval card shows what a text step changes. Own container, jsdom.
// kalmido-suite: fresh
// A person's agent asks to replace a knowledge page's text (one new line): the card in the agent chat reads, folded, one line in
// words ("Knowledge page Manual/Start: 1 line added, nothing removed"); unfolded the changed line stands as a + row (green, "+"
// in front, "added:" for screen readers) with the lines around it, and the technical line "Step: PATCH …" is inside the fold.
// A step without a text (delete a task) keeps its words as the folded line. After "Yes" the card still shows the change, marked
// as the state at the answer, also when the page changed afterwards. The knowledge history draws its comparison with the same
// rows (p2123_a_ui.js covers the dialog).
// 2.1088.0 (#5937): an upload card names the files it binds (count + first 3 names), visible, without a hash.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'wiki,files,collab,comments,agents'});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const ag = await call(CA, 'POST', '/api/admin/agents', {username: 'helper', display_name: 'Helper', owner_id: me.id, org_id: null,
    scopes: ['read', 'tasks:write', 'wiki:read', 'wiki:write']});
  check(ag.http === 201 && ag.token, 'setup: the personal agent ' + ag.http);
  const pg = await call(CA, 'POST', '/api/wiki/pages', {space: 'private', path: 'Manual/Start', body: 'Press the green button\nWait for the light\nOpen the lid\nDone'});
  check(pg.http === 201, 'setup: a private knowledge page ' + pg.http);
  const folder = ((await call(CA, 'GET', '/api/wiki?space=private')).folders || []).find(f => f.path === 'Manual');
  check((await call(CA, 'POST', `/api/files/nodes/${folder?.id}/shares`, {agent_id: ag.id, role: 'edit'})).http === 201, 'setup: the folder shared with the agent');
  const v1 = async (method, url, body) => { const x = await fetch(B + 'api/v1' + url, {method, headers: {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined}); return {...(await x.json().catch(() => ({}))), http: x.status}; };
  const cur = await v1('GET', `/wiki/pages/${pg.id}`);
  const c1 = await v1('POST', `/agent/chats/${me.id}`, {approval: {title: 'Add the last step to the manual', step: {method: 'PATCH', path: `/wiki/pages/${pg.id}`,
    body: {body: 'Press the green button\nWait for the light\nOpen the lid\nClose the lid again\nDone', expect_updated_at: cur.updated_at}}}});
  check(c1.http === 201, 'the text card ' + c1.http + ' ' + JSON.stringify(c1).slice(0, 200));
  const c2 = await v1('POST', `/agent/chats/${me.id}`, {approval: {title: 'Remove the old task', step: {method: 'DELETE', path: '/tasks/345'}}});
  check(c2.http === 201, 'the delete card ' + c2.http);
  // 2.1088.0 (#5937): an upload's card binds its files (body._files, #5936) and names them: count + the first 3, no hash
  const fl = ['plan.txt', 'shot list.pdf', 'cast.xlsx', 'map.png', 'notes.md'].map((name, i) => ({field: 'file', name, sha256: String(i).repeat(64)}));
  const c3 = await v1('POST', `/agent/chats/${me.id}`, {approval: {title: 'Upload the call sheets', step: {method: 'POST', path: '/tasks/345/attachments', body: {_files: fl}}}});
  check(c3.http === 201, 'the upload card ' + c3.http + ' ' + JSON.stringify(c3).slice(0, 200));
  const c4 = await v1('POST', `/agent/chats/${me.id}`, {approval: {title: 'Upload the plan', step: {method: 'POST', path: '/tasks/345/attachments', body: {_files: fl.slice(0, 1)}}}});
  check(c4.http === 201, 'the one-file card ' + c4.http);

  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`chatOpen(${ag.id})`);
  const card = () => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${c1.id}"]`);
  const sum = await until(() => { const s = card()?.querySelector('details.apvdet > summary'); return s && /1 line added/.test(s.textContent) && s; });
  check(sum && /^Knowledge page Manual\/Start: 1 line added, nothing removed$/.test(sum.textContent.trim()), 'folded: one line in words ' + (sum?.textContent || card()?.textContent || '').slice(0, 200));
  const det = card()?.querySelector('details.apvdet');
  check(det && !det.open, 'the change is folded at first');
  if (det) det.open = true;
  const add = [...(card()?.querySelectorAll('.wkhdiff .wkhd.add') || [])];
  check(add.length === 1 && /Close the lid again/.test(add[0].textContent) && add[0].querySelector('.wkhdm')?.textContent === '+' && /added:/.test(add[0].querySelector('.sr')?.textContent || ''),
    'unfolded: the new line as a + row ' + add.map(x => x.textContent).join('|'));
  check(!card()?.querySelector('.wkhd.del'), 'nothing removed, no - row');
  const ctx = [...(card()?.querySelectorAll('.wkhdiff .wkhd:not(.add):not(.gap)') || [])].map(x => x.textContent.trim());
  check(ctx.join('|') === 'Wait for the light|Open the lid|Done', 'two lines of context before, the one after: ' + ctx.join('|'));
  check(card()?.querySelector('.wkhd.gap'), 'the first line is folded into a gap');
  const st = det?.querySelector('[data-apv-step]');
  check(st && /^Step: PATCH \/wiki\/pages\/\d+ · Fields: body, expect_updated_at$/.test(st.textContent.trim()), 'the technical line is inside the fold ' + (st?.textContent || ''));
  const del = d.querySelector(`#chat-msgs .cmsg[data-mid="a:${c2.id}"] details.apvdet > summary`);
  check(del && /Step: Delete task 345/.test(del.textContent), 'a step without text keeps its words ' + (del?.textContent || ''));
  const upl = await until(() => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${c3.id}"] [data-apv-files]`));
  check(upl && upl.textContent.trim() === '5 files: plan.txt, shot list.pdf, cast.xlsx and 2 more' && !upl.closest('details'), '#5937: the upload card names its files, visible without unfolding ' + (upl?.textContent || ''));
  check(!/0{64}|1{64}/.test(d.querySelector(`#chat-msgs .cmsg[data-mid="a:${c3.id}"]`)?.textContent || ''), '#5937: no hash on the card');
  const one = d.querySelector(`#chat-msgs .cmsg[data-mid="a:${c4.id}"] [data-apv-files]`);
  check(one && one.textContent.trim() === '1 file: plan.txt', '#5937: one file ' + (one?.textContent || ''));
  check(!d.querySelector(`#chat-msgs .cmsg[data-mid="a:${c1.id}"] [data-apv-files]`), '#5937: a card without files has no file line');

  // Yes -> the card still shows the change, as it was at the answer, also after a later edit of the page
  click(w, card().querySelector('.apvbtns .cchb'));
  await until(() => card()?.classList.contains('apv') && !card()?.classList.contains('apvopen'));
  await call(CA, 'PATCH', `/api/wiki/pages/${pg.id}`, {body: 'Something else entirely'});
  w.eval(`S.apvd = {}; chatOpen(${ag.id})`);
  const dec = await until(() => card()?.querySelector('[data-apvd-decided]') && card());
  check(dec && /As it was when the card was answered/.test(dec.querySelector('[data-apvd-decided]').textContent), 'decided: marked as the state at the answer');
  check(dec && /1 line added, nothing removed/.test(dec.querySelector('details.apvdet > summary')?.textContent || '') && /Close the lid again/.test(dec.querySelector('.wkhd.add')?.textContent || ''),
    'decided: the approved line, not the later text ' + (dec?.querySelector('details.apvdet')?.textContent || '').slice(0, 200));
  w.close();
  console.log(`p21068_apvdiff_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
