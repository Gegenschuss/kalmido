// 2.198.0 A (#2743) UI tests: knowledge under "All workspaces" - an entry "All pages <space>" per space instead of the space
// switch next to the search. Own container (start.sh), jsdom.
// - a computer (sidebar B): one root node per space in the panel (shared tree, keys 'wk:<space>:'), its arrow shows the
//   space's folders, several open at once; its name opens the space's list (#wiki/s/<space>, heading = the space, in the
//   accent), a folder link carries the space (#wiki/s/<space>/d/<path>), reload and Back show the right space, an older
//   #wiki/d/<path> link still opens; no space open = the overview of the entries; search over every space with the space's
//   name at each hit; "New page" goes into the open space without asking, with none open the dialog asks for the space
//   (the one used last first); a locked space: the lock, no folders, its page offers "Unlock", no hits from it
// - one workspace chosen above: only its "All pages" as before; a person WITHOUT an organisation: "All pages" as before
// - a phone: the entries as a list on top, a tap opens the space, the way back leads to the list
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2198A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const root = (d, sp) => d.querySelector(`#side .sbbt[data-wksp="${sp}"]`);
const rowOf = (d, txt) => [...d.querySelectorAll('#side .sbbt')].find(r => r.querySelector('.sbbtn .n')?.textContent === txt);
const icHtml = (w, x) => w.eval(`(() => { const t = document.createElement('span'); t.innerHTML = ${x}; return t.innerHTML; })()`);  // as the DOM writes it
const h2 = d => d.querySelector('#view .wkfolder h2')?.textContent || '';
const items = d => [...d.querySelectorAll('#view #wk-res .wkitem')].map(a => a.textContent);
async function newPage(w, d, name) {  // "New page" in the bar, the name typed, Create
  w.__dialogs = 'manual'; d.querySelector('#view [data-wk="new"]').click();
  const md = await until(() => d.querySelector('.cdlg #cdlg-in') && d.querySelector('.cdlg'));
  const sp = md?.querySelector('[data-wk-sp]')?.value || null;
  if (md) { md.querySelector('#cdlg-in').value = name; md.querySelector('form').dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true})); }
  return sp;
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const og = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: st0.me.id});
  check(og.http < 300, 'the organisation Alpha ' + og.http);
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'all'});
  const ORG = (await call('GET', '/api/state')).me.workspaces?.[0]?.id, OS = 'org:' + ORG;
  for (const p of ['Docs/Guide', 'Top page']) await call('POST', '/api/wiki/pages', {space: 'private', path: p, body: 'Text of ' + p});
  for (const p of ['Team/Process', 'Team/Deep/Inner', 'Org page']) await call('POST', '/api/wiki/pages', {space: OS, path: p, body: 'Text of ' + p});

  // ================= a computer, "All workspaces"
  let w = await boot({user: 'alice', hash: 'wiki'}), d = w.document;
  check(await until(() => root(d, 'private') && root(d, OS)), 'the panel: a root node per space');
  check(root(d, 'private')?.querySelector('.sbbtn').innerHTML.includes(icHtml(w, `wsIcon('private')`)), 'the entry has the space\'s symbol');
  // 2.200.0 (#2747): audit B 1 -- the entries are named like the file store's spaces (the same name in the panel and the path)
  check(root(d, 'private')?.querySelector('.sbbtn .n')?.textContent === 'Private' && root(d, OS)?.querySelector('.sbbtn .n')?.textContent === 'Alpha', 'the entries are named by the space');
  check(!d.querySelector('[data-wk="space"]') && !d.querySelector('#view select'), 'no space switch next to the search');
  check(!d.querySelector('#side .sbbi[data-go="wiki"]'), 'no single "All pages" row any more');
  check(await until(() => d.querySelectorAll('#view .wkspaces [data-wksp]').length === 2) && h2(d) === 'All workspaces', 'no space open: the overview of the entries');
  check(!d.querySelector('#view [data-wk="amenu"]'), 'no space open: no space menu');
  root(d, OS).querySelector('[data-act="sbb-tree"]').click();
  check(await until(() => rowOf(d, 'Team')), 'the arrow of Alpha shows its folder Team');
  root(d, 'private').querySelector('[data-act="sbb-tree"]').click();
  check(await until(() => rowOf(d, 'Docs') && rowOf(d, 'Team')), 'two spaces open at once');
  check(w.eval(`(LS.get('sbbOpen', []) || []).includes('wk:${OS}:') && (LS.get('sbbOpen', []) || []).includes('wk:private:') && sbb_treeAnyOpen()`), 'open per device in sbbOpen, counted by sbb_treeAnyOpen');
  root(d, OS).querySelector('.sbbtn').click();
  check(await until(() => w.location.hash === '#wiki/s/' + OS && h2(d) === 'Alpha'), 'the name opens the list of Alpha, heading = the space ' + w.location.hash);
  check(await until(() => root(d, OS)?.classList.contains('on') && root(d, OS).querySelector('[aria-current="page"]')), 'the open space in the accent');
  check(items(d).some(t => /Org page/.test(t)) && !items(d).some(t => /Top page/.test(t)), 'the list shows the pages of Alpha only');
  check(w.eval(`LS.get('wkSpace', '')`) === OS && d.querySelector('#view [data-wk="amenu"]'), 'the space is remembered, its menu is in the bar');
  rowOf(d, 'Team').querySelector('.sbbtn').click();
  check(await until(() => w.location.hash === `#wiki/s/${OS}/d/Team` && h2(d) === 'Team'), 'a folder link carries the space ' + w.location.hash);
  check(items(d).some(t => /Process/.test(t)) && d.querySelector('#view .wkcrumbs a')?.getAttribute('href') === '#wiki/s/' + OS, 'the folder of Alpha, the path starts at the space');
  rowOf(d, 'Docs').querySelector('.sbbtn').click();
  check(await until(() => w.location.hash === '#wiki/s/private/d/Docs' && items(d).some(t => /Guide/.test(t))), 'a folder of Private opens in Private');
  w.history.back();
  check(await until(() => h2(d) === 'Team' && items(d).some(t => /Process/.test(t))), 'Back: the folder of Alpha again ' + w.location.hash);
  // search over every space
  const q = d.querySelector('#wk-q'); q.value = 'page'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  const hit = t => [...d.querySelectorAll('#view #wk-res .wkitem')].find(a => a.querySelector('span')?.textContent === t);
  check(await until(() => hit('Top page') && hit('Org page')), 'search under "All": the hits of both spaces');
  check(hit('Top page')?.querySelector('.wkspn')?.textContent === 'Private' && hit('Org page')?.querySelector('.wkspn')?.textContent === 'Alpha', 'each hit names its space');
  q.value = ''; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  w.close();

  // reload: the address keeps the space; an older link #wiki/d/<path> opens the space used last
  w = await boot({user: 'alice', hash: `wiki/s/${OS}/d/Team`}); d = w.document;
  check(await until(() => h2(d) === 'Team' && items(d).some(t => /Process/.test(t))), 'reload: the folder of Alpha');
  check(await until(() => rowOf(d, 'Team')?.classList.contains('on')), 'reload: the panel opens Alpha down to the folder');
  w.close();
  w = await boot({user: 'alice', hash: 'wiki/d/Team', ls: {'tasks.wkSpace': JSON.stringify(OS)}}); d = w.document;
  check(await until(() => h2(d) === 'Team' && items(d).some(t => /Process/.test(t))), 'an older #wiki/d/<path> link still opens');
  w.close();

  // New page: into the open space without asking; none open = the dialog asks (the space used last first)
  w = await boot({user: 'alice', hash: 'wiki/s/private', ls: {'tasks.wkSpace': JSON.stringify(OS)}}); d = w.document;
  await until(() => h2(d) === 'Private');
  check(await newPage(w, d, 'Made in private') === null, 'a space open: no question about the space');
  check(await until(async () => ((await call('GET', '/api/wiki?space=private')).pages || []).some(p => p.path === 'Made in private')), 'the page is in the open space');
  w.close();
  w = await boot({user: 'alice', hash: 'wiki', ls: {'tasks.wkSpace': JSON.stringify(OS)}}); d = w.document;
  await until(() => h2(d) === 'All workspaces');
  check(await newPage(w, d, 'Made in alpha') === OS, 'no space open: the dialog asks, the space used last first');
  check(await until(async () => ((await call('GET', '/api/wiki?space=' + OS)).pages || []).some(p => p.path === 'Made in alpha')), 'the page is in the chosen space');
  w.close();

  // a locked space (encrypted in the browser, not unlocked here): its index comes in as the lock does it
  const lockOrg = `wkeIndex = async (sp, j) => { if (sp === '${OS}') { WKE.st[sp] = {mode: 'on', gen: 1, mine: true}; j.pages = []; } return j; };`;
  w = await boot({user: 'alice', hash: 'wiki'}); d = w.document;
  w.eval(lockOrg); w.eval(`for (const s of wk_spaces()) delete WK.idx[s]; renderView(); renderSide();`);
  check(await until(() => root(d, OS)?.querySelector('.sbbtn')?.innerHTML.includes(icHtml(w, `ic('lock')`)) && !root(d, OS).querySelector('[data-act="sbb-tree"]')), 'the locked space: the lock, no folders');  // 2.406.0 (#3492): tree rows draw the full-size symbol
  check(await until(() => d.querySelector(`#view .wkspaces [data-wksp="${OS}"] .wkemark`)), 'the overview: the entry with the lock');
  root(d, OS).querySelector('.sbbtn').click();
  check(await until(() => d.querySelector('#view .wkelock [data-wke="unlock"]')), 'a click on it: its page offers "Unlock"');
  w.location.hash = 'wiki'; await until(() => h2(d) === 'All workspaces');
  const q2 = d.querySelector('#wk-q'); q2.value = 'page'; q2.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(() => [...d.querySelectorAll('#view #wk-res .wkspn')].some(s => s.textContent === 'Private')) && ![...d.querySelectorAll('#view #wk-res .wkspn')].some(s => s.textContent === 'Alpha'), 'search: no hits from the locked space');
  w.close();

  // ================= a phone, "All workspaces"
  w = await boot({user: 'alice', hash: 'wiki', mobile: true}); d = w.document;
  check(await until(() => d.querySelectorAll('#view #wk-res .wkspaces [data-wksp]').length === 2), 'the phone: the entries as a list on top');
  check(!d.querySelector('[data-wk="space"]'), 'the phone: no space switch');
  d.querySelector(`#view #wk-res [data-wksp="${OS}"]`).click();
  w.location.hash = 'wiki/s/' + OS;  // jsdom follows no link by itself
  check(await until(() => items(d).some(t => /Org page/.test(t)) && /Alpha/.test(d.querySelector('#view .wkspbar')?.textContent || '')), 'a tap opens the space (its name on top)');
  check(d.querySelector('#view .wkspbar a')?.getAttribute('href') === '#wiki', 'the way back leads to the list');
  w.close();

  // ================= one workspace chosen above: as before
  await call('PATCH', '/api/settings', {workspace: OS});
  w = await boot({user: 'alice', hash: 'wiki'}); d = w.document;
  check(await until(() => d.querySelector('#side .sbbi[data-go="wiki"]')), 'one workspace: its "All pages" row');
  check(!d.querySelector('#side [data-wksp]') && !d.querySelector('[data-wk="space"]'), 'one workspace: no entry per space, no switch');
  check(await until(() => items(d).some(t => /Org page/.test(t))) && h2(d) === 'Knowledge', 'one workspace: its pages');  // 2.200.0 (#2747): audit B 1, the panel's name
  w.close();
  await call('PATCH', '/api/settings', {workspace: 'all'});

  // ================= a person without an organisation: "All pages" as before
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats}, FK);
  await call('POST', '/api/wiki/pages', {space: 'private', path: 'Mine/Note'}, FK);
  w = await boot({user: 'frida', hash: 'wiki'}); d = w.document;
  check(await until(() => d.querySelector('#side .sbbi[data-go="wiki"]') && /Knowledge/.test(d.querySelector('#side .sbbi[data-go="wiki"]').textContent)), 'without an organisation: one top entry');  // 2.200.0 (#2747): audit B 1, "Knowledge" as "Files" in the file store
  check(!d.querySelector('#side [data-wksp]') && !d.querySelector('#view .wkspaces'), 'without an organisation: no entry per space, no overview');
  check(await until(() => rowOf(d, 'Mine')), 'without an organisation: the folders as before');
  check(await newPage(w, d, 'Freelance page') === null, 'without an organisation: New page asks no space');
  check(await until(async () => ((await call('GET', '/api/wiki?space=private', null, FK)).pages || []).some(p => p.path === 'Freelance page')), 'without an organisation: the page is private');
  w.close();

  console.log(`p2198_a_wiki_spaces_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
