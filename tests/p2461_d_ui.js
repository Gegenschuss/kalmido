// 2.46.1 UI tests, part D (#1361 favourites 4-7), own container (start.sh). jsdom:
// - Ctrl+K: the empty palette starts with the group "Favourites" (the starred lists in star order); a search ranks a
//   starred list above an unstarred one with the same match
// - Settings > Appearance: the switches "Quieter pushes from lists without a star" (off) and "Suggest favourites" (on) save
// - the suggestion: a busy list without a star is offered once in a message; its button sets the star, nothing is set alone
// - #1422: showing completed in my list of a folder with "Hide completed" marks it at once ("This list differs", Back to
//   the folder); the server marks it the same way
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2461_D_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const sql = (q, args = []) => execFileSync('python3', [path.join(__dirname, 'dbx.py'), path.join(DATA, 'tasks.db'), q, JSON.stringify(args)], {encoding: 'utf-8'});

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', show_done_default: '1', show_done_new: '0'});  // 2.49.0 (#1535): the old defaults (completed stay visible)
  const L = {};
  for (const n of ['Report North', 'Report South', 'Garden', 'Kitchen', 'Busy project']) L[n] = (await call('POST', '/api/lists', {name: n})).id;
  await call('PUT', `/api/lists/${L.Kitchen}/favorite`, {});
  await call('PUT', `/api/lists/${L['Report South']}/favorite`, {});

  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval('openPalette()'); await sleep(150);
  const groups = [...d.querySelectorAll('.plist .pgroup')].map(x => x.textContent.trim());
  const items = w.eval('palItems().slice(0, 3).map(x => x.group + ":" + x.label)');
  check(groups[0] === 'Favourites', '#1361: the empty palette starts with Favourites: ' + groups.slice(0, 3));
  check(items[0] === 'fav:Kitchen' && items[1] === 'fav:Report South' && items[2] !== 'fav:Garden', '#1361: the starred lists in star order: ' + items);
  w.eval(`PAL.q = 'Report'`);
  const hits = w.eval(`palItems().filter(x => x.kind === 'list').map(x => x.label)`);
  check(hits.indexOf('Report South') === 0 && hits.indexOf('Report North') > 0, '#1361: a search ranks the starred list first: ' + hits);
  w.eval('closePalette()');

  // Settings > Appearance: both switches
  w.eval(`settingsModal('look')`); await sleep(400);
  const q = d.querySelector('#s-favq'), sg = d.querySelector('#s-favs');
  check(q && !q.checked && sg && sg.checked, '#1361: Settings: quieter pushes off, suggestions on');
  if (q) { q.checked = true; q.dispatchEvent(new w.Event('change', {bubbles: true})); }
  const st = await until(async () => { const s = (await call('GET', '/api/state')).settings; return s.fav_quiet === '1' && s; });
  check(st && st.fav_quiet === '1', '#1361: the switch saves fav_quiet');
  w.close();

  // #1422: an own choice against the folder's "Hide completed" is visible
  await call('PUT', '/api/folders/props', {folder: 'Jobs', props: {hide_done: true}});
  const J = (await call('POST', '/api/lists', {name: 'Shoot', folder: 'Jobs'})).id;
  w = await boot({user: 'alice', hash: 'l/' + J}); d = w.document;
  check(w.eval(`showDone('l:${J}')`) === false, '#1422: the folder hides completed in my list');
  await w.eval(`setShowDone(true, 'l:${J}')`); await sleep(300);
  check(w.eval(`JSON.parse(listById(${J}).folder_own || '[]').includes('hide_done')`), '#1422: the own choice marks the list at once');
  check(/This list differs: Hide completed/.test(w.eval(`folderHintHtml(listById(${J}), ${J})`)), '#1422: the list dialog says it differs');
  const fo = await until(async () => { const l = (await call('GET', '/api/state')).lists.find(x => x.id === J); return (l.folder_own || '').includes('hide_done') && l; });
  check(!!fo, '#1422: the server marks it the same way');
  await w.eval(`setShowDone(false, 'l:${J}')`); await sleep(300);
  check(!w.eval(`JSON.parse(listById(${J}).folder_own || '[]').includes('hide_done')`), '#1422: the same value as the folder: no longer differs');
  w.close();

  // the suggestion: alice's own changes in "Busy project" on 6 days of the last two weeks
  const T = (await call('POST', '/api/tasks', {title: 'Busy task', list_id: L['Busy project']})).id;
  const me = (await call('GET', '/api/state')).me.id;
  for (let i = 0; i < 24; i++) {
    const at = new Date(Date.now() - (i % 6 + 1) * 864e5).toISOString().slice(0, 19) + '+00:00';
    sql('INSERT INTO activity(task_id, user_id, kind, data, created_at) VALUES(?,?,?,?,?)', [T, me, 'edit', '{}', at]);
  }
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  w.eval('toast("x")');
  await w.eval('lc_favSuggest()');
  const tt = d.querySelector('#toast');
  check(tt && /Busy project/.test(tt.textContent) && /Add to favourites/.test(tt.textContent), '#1361: the suggestion names the list: ' + (tt && tt.textContent));
  check(!w.eval(`favIs(${L['Busy project']})`), '#1361: no star by itself');
  tt?.querySelector('button')?.click(); await sleep(400);
  check(w.eval(`favIs(${L['Busy project']})`), '#1361: the button sets the star');
  const s2 = await until(async () => { const s = (await call('GET', '/api/state')).settings; return (s.fav_lists || '').split(',').includes(String(L['Busy project'])) && s; });
  check(!!s2, '#1361: the star is saved');
  w.close();

  console.log(`p2461_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
