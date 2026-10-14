// 2.40.0 UI tests, part L (list rights, custom fields, folders), own container (start.sh). jsdom:
// - #1431 the list dialog of a list admin: name, icon (emoji + picture) and colour are free, type / rate stay grey; a member
//   sees all of it grey; the owner info says what admins may
// - #1192 the list dialog of a list admin has "Custom fields" with "+ Field"; a member reads "only the owner and list admins"
// - #1193 the field dialog of a new select field: template "Status" (4 options with their colours), the palette per option
//   instead of cycling, Alt+Down moves an option; filled chips with a readable ink (rows, columns, detail select)
// - #1429 no "chip" in the field dialog; a list with own columns shows the hint with the link to "Shown fields"
// - #1373 no "Agents may address each other" switch in the list dialog nor in the folder settings
// - #1422 the folder dialog explains "Hide completed"; a shared list of someone else ignores my folder's hide_done
// - #1414 next steps of a new software project: the folder's agent is already in -> a line instead of "Share"
// - #1337 / #1431 the News texts for members (archived the list) and for the owner (renamed your list)
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
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,fields';
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const closeAll = d => d.querySelectorAll('.modal').forEach(m => m.remove());

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const uid = {};
  for (const u of ['bob', 'carol', 'dave']) uid[u] = (await call('POST', '/api/users', {username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: u + '@example.com'})).id;
  const CB = await login('bob'), CC = await login('carol'), CD = await login('dave');
  for (const c of [CB, CC, CD]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, c);
  const SH = (await call('POST', '/api/lists', {name: 'Fair stand', folder: 'Events'}, CB)).id;
  await call('PUT', `/api/lists/${SH}/members`, {user_id: uid.carol, role: 'admin'}, CB);
  await call('PUT', `/api/lists/${SH}/members`, {user_id: uid.dave, role: 'edit'}, CB);
  const FS = (await call('POST', `/api/lists/${SH}/fields`, {name: 'Stage', type: 'select', pinned: true, options: {options: [{name: 'Blue one', color: '#6d8cff'}, {name: 'Plain', color: ''}]}}, CB)).id;
  const T = (await call('POST', '/api/tasks', {title: 'Book the booth', list_id: SH}, CB)).id;
  const st0 = await call('GET', '/api/state', null, CB);
  const opt = st0.fields.find(f => f.id === FS).options.options;
  await call('PATCH', `/api/tasks/${T}`, {fields: {[FS]: opt[0].id}}, CB);

  // ================= #1431 / #1192 the list admin's list dialog
  let w = await boot({user: 'carol', hash: 'l/' + SH}), d = w.document;
  await until(() => w.eval(`!!listById(${SH})`));
  w.eval(`listModal(${SH})`); let md = await until(() => d.querySelector('.modal.lmodal'));
  check(md && !md.querySelector('#l-name').disabled && !md.querySelector('#l-emo').disabled, '#1431: admin: name and icon button free');
  check(md && [...md.querySelectorAll('#l-col button')].every(b => !b.disabled), '#1431: admin: colours free');
  check(md && !!md.querySelector('.lipickw .lipick'), '#1431: admin: "Or a picture" is offered');
  check(md && md.querySelector('#l-kindp')?.disabled === true, '#1431: admin: the type stays grey (owner)');
  check(md && !!md.querySelector('#l-fields [data-m="field-add"]'), '#1192: admin: Custom fields with "+ Field"');
  // a rename from the dialog saves (autosave on change)
  const nm = md.querySelector('#l-name'); nm.value = 'Fair booth'; nm.dispatchEvent(new w.Event('input', {bubbles: true})); nm.dispatchEvent(new w.Event('change', {bubbles: true}));
  nm.dispatchEvent(new w.FocusEvent('blur', {bubbles: true}));
  check(await until(async () => (await call('GET', '/api/state', null, CB)).lists.find(l => l.id === SH)?.name === 'Fair booth'), '#1431: the admin renames from the dialog');
  closeAll(d);
  // ================= #1193 the field dialog: template "Status", palette, Alt+Down
  w.eval(`fieldModal(${SH}, null, null)`); md = (await until(() => d.querySelector('#fd-type')))?.closest('.modal');
  md.querySelector('#fd-type').value = 'select'; md.querySelector('#fd-type').dispatchEvent(new w.Event('change', {bubbles: true}));
  check(!!md.querySelector('[data-m="opt-tpl"]') && !!md.querySelector('[data-m="opt-empty"]'), '#1193: a new select field offers the template "Status" or empty');
  click(w, md.querySelector('[data-m="opt-tpl"]'));
  const names = () => [...md.querySelectorAll('[data-oname]')].map(i => i.value);
  check(JSON.stringify(names()) === JSON.stringify(['Not started', 'In progress', 'Waiting', 'Done']), '#1193: the template\'s four options ' + JSON.stringify(names()));
  check(md.querySelectorAll('.optrow .swc').length === 4 && md.querySelectorAll('.optrow .colh').length === 4, '#1193: every option has a colour and a handle');
  click(w, md.querySelector('[data-ocol="1"]'));
  const pal = md.querySelector('.lrpal');
  check(pal && pal.querySelectorAll('[data-opal]').length === w.eval('LCOLORS.length'), '#1193: a tap on the colour opens the palette (list colours + none)');
  click(w, pal.querySelector('[data-opal="#f472b6"]'));
  check(!md.querySelector('.lrpal') && /244, 114, 182|#f472b6/i.test(md.querySelector('[data-ocol="1"]').style.background), '#1193: picking a colour sets it and closes the palette');
  md.querySelector('[data-oname="0"]').dispatchEvent(new w.KeyboardEvent('keydown', {key: 'ArrowDown', altKey: true, bubbles: true}));
  check(JSON.stringify(names()) === JSON.stringify(['In progress', 'Not started', 'Waiting', 'Done']), '#1193: Alt+Down moves the option ' + JSON.stringify(names()));
  check(!/chip/i.test(md.textContent), '#1429: no "chip" in the field dialog');
  closeAll(d);
  // filled chips with a readable ink
  check(w.eval(`lrInk('#ffffff')`) === '#111' && w.eval(`lrInk('#1e293b')`) === '#fff' && w.eval(`lrInk('#6d8cff')`) === '#111', '#1193: the ink follows the contrast');
  const chip = w.eval(`fieldChip(fieldById(${FS}), ${JSON.stringify(opt[0].id)}, ${SH})`);
  check(/class="fchip sel fill"/.test(chip) && /--fc:#6d8cff;--fct:#111/.test(chip), '#1193: the row chip is filled ' + chip);
  const plain = w.eval(`fieldCell(fieldById(${FS}), ${JSON.stringify(opt[1].id)}, ${SH})`);
  check(/class="fchip sel"/.test(plain) && !/fill/.test(plain), '#1193: an option without colour keeps the tinted chip');
  w.eval(`openDetail ? openDetail(${T}) : null`);
  const sel = await until(() => d.querySelector(`select[data-cf="${FS}"]`));
  check(sel && sel.classList.contains('fill') && /--fc/.test(sel.getAttribute('style') || ''), '#1193: the detail select shows the colour');
  w.close();

  // ================= a member: everything grey, read-only fields
  w = await boot({user: 'dave', hash: 'l/' + SH}); d = w.document;
  await until(() => w.eval(`!!listById(${SH})`));
  w.eval(`listModal(${SH})`); md = await until(() => d.querySelector('.modal.lmodal'));
  check(md && md.querySelector('#l-name').disabled && md.querySelector('#l-emo').disabled && [...md.querySelectorAll('#l-col button')].every(b => b.disabled), '#1431: a member: name, icon, colour grey');
  check(md && !md.querySelector('.lipickw') && !md.querySelector('#l-fields') && /only the owner and list admins can change them/.test(md.textContent), '#1192: a member reads who may change the fields');
  // News texts
  const nt = data => w.eval(`newsText({kind: 'orglist', actor_id: ${uid.carol}, data: ${JSON.stringify(data)}}, {})`).replace(/<[^>]+>/g, '');
  check(/archived the list Fair booth \(list admin\)/.test(nt({action: 'larchive', member: 1, name: 'Fair booth'})), '#1337: a member reads "archived the list"');
  check(/restored the list Fair booth from the archive/.test(nt({action: 'lrestore', member: 1, name: 'Fair booth'})), '#1337: ... "restored the list"');
  check(/renamed your list Fair stand to Fair booth/.test(nt({action: 'lrename', old: 'Fair stand', name: 'Fair booth'})), '#1431: the owner reads "renamed your list"');
  w.close();

  // ================= #1429 a list with own columns: the hint links "Shown fields"
  const COLS = (await call('POST', '/api/lists', {name: 'Columns list'})).id;
  await call('PATCH', `/api/lists/${COLS}`, {columns: ['title', 'due']});
  // ================= #1373 / #1414 agents
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'helper', display_name: 'Helper'});
  await call('PUT', '/api/folders/props', {folder: 'Dev', props: {agent_id: ag.id}});
  const APP = (await call('POST', '/api/lists', {name: 'App', folder: 'Dev', kind: 'project', ptype: 'software'})).id;
  // ================= #1422 hide_done of my folder only for my own lists
  await call('PUT', '/api/folders/props', {folder: 'Events', props: {hide_done: true}});
  await call('PUT', `/api/lists/${SH}/members`, {user_id: (await call('GET', '/api/state')).me.id, role: 'edit'}, CB);
  const MINE = (await call('POST', '/api/lists', {name: 'My events', folder: 'Events'})).id;
  w = await boot({user: 'alice', hash: 'l/' + COLS}); d = w.document;
  await until(() => w.eval(`!!listById(${COLS}) && !!listById(${APP})`));
  w.eval(`fieldModal(${COLS}, null, null)`); md = (await until(() => d.querySelector('#fd-type')))?.closest('.modal');
  const hint = md.querySelector('.lrcolhint');
  check(hint && /Whether the field shows in the task row is set in/.test(hint.textContent) && md.querySelector('#fd-pin').closest('.row').hidden, '#1429: own columns: the hint instead of the hidden option');
  click(w, hint.querySelector('[data-m="fd-cols"]'));
  check(await until(() => d.querySelector('#col-t')), '#1429: the link opens "Shown fields"');
  closeAll(d);
  w.eval(`listModal(${APP})`); md = await until(() => d.querySelector('.modal.lmodal'));
  check(md && !md.querySelector('#l-agp') && !/Agents may address each other/.test(md.textContent), '#1373: no switch "Agents may address each other" in the list dialog');
  closeAll(d);
  w.eval(`folderPropsModal('Events')`); md = (await until(() => d.querySelector('.modal #fs-hd')))?.closest('.modal');
  check(md && !md.querySelector('#fs-ap[data-fk]') && !/address each other/.test(md.textContent), '#1373: none in the folder settings');
  check(md && /for your own lists in this folder/.test(md.querySelector('.fshdhint')?.textContent || ''), '#1422: the folder dialog says how "Hide completed" works');
  closeAll(d);
  check(w.eval(`lmDoneDefault('l:${MINE}')`) === false, '#1422: my own list in the folder: completed hidden by the folder');
  check(w.eval(`lmDoneDefault('l:${SH}')`) === true, '#1422: a shared list of someone else in my folder "Events": my default (shown)');
  w.eval(`projectNextSteps(${APP})`); md = await until(() => d.querySelector('.nsmodal'));
  check(md && /Helper is already connected through the folder “Dev”/.test(md.textContent) && !md.querySelector('#ns-agent'), '#1414: the folder\'s agent is in: a line, no "Share" ' + (md?.textContent || '').replace(/\s+/g, ' ').slice(0, 300));
  w.close();

  console.log(`${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
