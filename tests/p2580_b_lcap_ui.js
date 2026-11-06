// kalmido-suite: fresh
// 2.580.0 B (#4488): the project limit of an API token / an agent (integrations.js listCapHtml / listCapVal): one field
// "Add projects" with a search instead of a grid of ticks; the offers grouped by folder, a whole folder (with its subfolders)
// can be added, the projects added stand as rows with Remove; none added = every project (list_ids [] as before).
// - a search narrows the offers, Enter / a click adds, the folder's head adds its projects, Remove takes one out
// - New API token with a limit: saved list_ids are the projects added; the token's rights dialog shows them again as rows
// freelancer-matrix: integrations - frida has no organisation: her token limited the same way.
// Own container (start.sh), jsdom. Invented names only.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: waitFor} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2580B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => waitFor(fn, {timeout: 15000, step: 100});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true}));
const typeIn = (w, q, v) => { q.value = v; q.dispatchEvent(new w.Event('input', {bubbles: true})); };
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const FEAT = 'cal,comments,collab,agents';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call(CA, 'PUT', '/api/admin/agent-policy', {user_agents: true, max_per_user: 2});
  const mk = async (ck, name, folder) => (await call(ck, 'POST', '/api/lists', {name, ...(folder ? {folder} : {})})).id;
  const SOLO = await mk(CA, 'Solo errands'), C1 = await mk(CA, 'Client Anna', 'Clients'), C2 = await mk(CA, 'Client Ben', 'Clients');
  const BIG = await mk(CA, 'Big account', 'Clients/Big'), HOME = await mk(CA, 'Garden', 'Home');
  check(SOLO && C1 && C2 && BIG && HOME, 'setup: projects in folders, a subfolder and none');

  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  await w.eval(`loadModule('integrations')`);
  // ---- the field: search, folder, Remove, nothing added = all
  w.eval(`tokModal(() => {}, [])`);
  let md = await until(() => lastModal(d)?.querySelector('#tk-lcap') && lastModal(d));
  let root = md.querySelector('#tk-lcap'), q = root.querySelector('.lcapq');
  check(!root.querySelector('input[type="checkbox"]') && q && q.getAttribute('role') === 'combobox', 'no grid of ticks, one search field');
  check(/All its projects/.test(root.querySelector('.lcapst').textContent) && w.eval(`listCapVal(document, 'tk-lcap').length`) === 0, 'nothing added: every project (list_ids [])');
  q.dispatchEvent(new w.FocusEvent('focusin', {bubbles: true}));
  const res = root.querySelector('.lcapres');
  const offered = [...res.querySelectorAll('[data-lcapo]')].map(o => +o.dataset.lcapo);
  check(!res.hidden && q.getAttribute('aria-expanded') === 'true' && [SOLO, C1, C2, BIG, HOME].every(x => offered.includes(x)), 'the offers open with the field: all projects ' + offered.join(','));
  check(res.querySelector('[data-lcapf="Clients"]') && res.querySelector('[data-lcapf="Home"]') && /Whole folder Clients/.test(res.querySelector('[data-lcapf="Clients"]').textContent), 'the folders head their groups and can be chosen whole');
  const order = [...res.querySelectorAll('.lcapo')].map(o => o.dataset.lcapo || 'f:' + o.dataset.lcapf);
  const f1 = order.findIndex(x => x.startsWith('f:'));
  check(order.indexOf(String(SOLO)) < f1 && order.indexOf('f:Clients') < order.indexOf(String(C1)) && order.indexOf(String(C2)) < order.indexOf('f:Clients/Big') && order.indexOf('f:Clients/Big') < order.indexOf(String(BIG)), 'projects without a folder first, then each folder with its projects ' + order.join(','));
  typeIn(w, q, 'solo');
  check([...res.querySelectorAll('[data-lcapo]')].map(o => +o.dataset.lcapo).join() === String(SOLO), 'the search narrows the offers to "Solo errands"');
  key(w, q, 'Enter');
  check(w.eval(`listCapVal(document, 'tk-lcap').join()`) === String(SOLO) && /Limited to 1 project/.test(root.querySelector('.lcapst').textContent), 'Enter adds the only offer: limited to 1 project');
  check(q.value === '' && !res.querySelector(`[data-lcapo="${SOLO}"]`), 'the field is empty again, the project added is no longer offered');
  typeIn(w, q, 'zzz');
  check(/No matching project/.test(res.textContent), 'no match: said so');
  typeIn(w, q, '');
  click(w, res.querySelector('[data-lcapf="Clients"]'));
  const val = () => w.eval(`listCapVal(document, 'tk-lcap')`).slice().sort((a, b) => a - b).join();
  check(val() === [SOLO, C1, C2, BIG].sort((a, b) => a - b).join(), 'the whole folder Clients adds its projects and those of Clients/Big ' + val());
  check(root.querySelector(`.lcaprow[data-lcap="${BIG}"] .lcapf`)?.textContent === 'Clients / Big', 'a row names its folder');
  // keyboard: arrows walk the offers, Enter adds the one marked
  key(w, q, 'ArrowDown');
  const act = q.getAttribute('aria-activedescendant'), mark = act && root.querySelector('#' + act);
  check(mark && mark.getAttribute('aria-selected') === 'true', 'ArrowDown marks an offer (aria-activedescendant)');
  key(w, q, 'Escape');
  check(res.hidden && q.getAttribute('aria-expanded') === 'false' && d.contains(md), 'Escape closes the offers, not the dialog');
  click(w, root.querySelector(`[data-lcapx="${C2}"]`));
  check(!root.querySelector(`[data-lcap="${C2}"]`) && !w.eval(`listCapVal(document, 'tk-lcap')`).includes(C2), 'Remove takes "Client Ben" out');
  check(root.querySelector(`[data-lcapx="${C1}"]`)?.getAttribute('aria-label') === 'Remove Client Anna', 'Remove names its project for screen readers');
  // save the token with the limit, open its rights again
  md.querySelector('#tk-name').value = 'Report script';
  click(w, md.querySelector('[data-m="ok"]'));
  const tok = await until(async () => (await call(CA, 'GET', '/api/me/tokens')).tokens?.find(t => t.name === 'Report script'));
  const want = [SOLO, C1, BIG].sort((a, b) => a - b).join();
  check(tok && (tok.list_ids || []).slice().sort((a, b) => a - b).join() === want, 'the token is saved with the projects added ' + JSON.stringify(tok && tok.list_ids));
  d.querySelectorAll('.modal').forEach(m => m.remove());
  // the token's rights dialog (integrations.js tokWire "edit") draws the same field from the saved list_ids
  w.eval(`settingsModal('tokens')`);
  await until(() => d.querySelector('#s-toks')?._j);
  const dev = d.querySelector('.smodal details.sdev'); if (dev) dev.open = true;
  const edit = await until(() => d.querySelector(`[data-tokid="${tok?.id}"] [data-tok="edit"]`));
  if (edit) click(w, edit);
  root = await until(() => lastModal(d)?.querySelector('#pm-lcap'));
  const rows = root ? [...root.querySelectorAll('.lcaprow')].map(r => +r.dataset.lcap).sort((a, b) => a - b).join() : '';
  check(rows === want && /Limited to 3 projects/.test(root?.querySelector('.lcapst')?.textContent || ''), 'opened again: the three projects as rows ' + rows);
  // take all out = every project again
  for (const x of [...(root?.querySelectorAll('[data-lcapx]') || [])]) click(w, x);
  click(w, lastModal(d).querySelector('[data-m="ok"]'));
  check(await until(async () => ((await call(CA, 'GET', '/api/me/tokens')).tokens.find(t => t.id === tok?.id)?.list_ids || []).length === 0), 'all removed and saved: list_ids [] (every project)');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  w.close();

  // ---- frida: no organisation, her own token limited the same way
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(fu.http < 300 && ((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida has no organisation');
  const FT = await mk(CF, 'Taxes', 'Office'), FB = await mk(CF, 'Bookkeeping', 'Office'), FX = await mk(CF, 'Holiday');
  w = await boot({user: 'frida', hash: 'today'}); d = w.document;
  await w.eval(`loadModule('integrations')`);
  w.eval(`tokModal(() => {}, [])`);
  md = await until(() => lastModal(d)?.querySelector('#tk-lcap') && lastModal(d));
  root = md.querySelector('#tk-lcap'); q = root.querySelector('.lcapq');
  typeIn(w, q, 'office');  // the folder's name finds its projects
  check(root.querySelector('[data-lcapf="Office"]') && root.querySelectorAll('[data-lcapo]').length === 2, 'frida: the search finds the folder Office with its two projects');
  click(w, root.querySelector('[data-lcapf="Office"]'));
  md.querySelector('#tk-name').value = 'Tax export';
  click(w, md.querySelector('[data-m="ok"]'));
  const ft = await until(async () => (await call(CF, 'GET', '/api/me/tokens')).tokens?.find(t => t.name === 'Tax export'));
  check(ft && (ft.list_ids || []).slice().sort((a, b) => a - b).join() === [FT, FB].sort((a, b) => a - b).join() && !(ft.list_ids || []).includes(FX), 'frida: the token is limited to the folder Office ' + JSON.stringify(ft && ft.list_ids));
  w.close();

  console.log(`p2580_b_lcap_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
