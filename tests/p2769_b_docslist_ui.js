// Release 2.769.0 part B (#5340) UI tests: a folder with recognition (the documents folder) has the switch List | Cards again.
// kalmido-suite: fresh
// Own container (start.sh), jsdom + Firefox for the widths (1280, 460, 320). Invented names and files only.
// - the switch stands above the folder, Cards is the default there; List shows the documents as rows with their fields
//   Name, Type, Sender, Date, Amount, To review; a column header sorts (the server sorts: ?sort=type|review new)
// - the choice is kept per folder (the setting ab_cards: "!n:<id>" = list chosen in a recognising folder), also after a new
//   start; back to Cards removes it; a folder without recognition keeps its own switch (list by default)
// - the setting accepts "!n:<id>" and still refuses other values
// - widths: 1280 the columns with their header; 460 / 320 the type (and the other fields) as a second line below the name,
//   nothing runs over the side
// freelancer-matrix: files (alice has no organisation: her private workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2769_b_docslist_ui', check, shots: 'P2769B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2769B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const dbx = (sql, args = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args)]).toString());
const up = async (name, text) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  return ((await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json().catch(() => ({}))).ids || [])[0];
};
const cards = async () => JSON.parse((await call('GET', '/api/state')).settings.ab_cards || '[]');
const order = async q => ((await call('GET', '/api/docs?ws=private&facets=0&' + q)).docs || []).map(x => x.id);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'files', 'docs'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  check(!(st0.me.workspaces || []).length, 'setup: alice has no organisation (a person on her own)');
  const D1 = await up('bill-north.txt', 'An invented bill'), D2 = await up('contract-south.txt', 'An invented contract'), D3 = await up('note-plain-with-a-rather-long-name-for-narrow-screens.txt', 'An invented note');
  check(D1 && D2 && D3, 'setup: three documents');
  for (const id of [D1, D2, D3]) await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 200);
  const p1 = await call('PATCH', `/api/docs/${D1}`, {type: 'Invoice', sender: 'Beta Example GmbH', date: '2025-03-01', amount: '120.00'});
  const p2 = await call('PATCH', `/api/docs/${D2}`, {type: 'Contract', sender: 'alpha Sample AG', date: '2025-01-15', amount: '9.50'});
  check(p1.http < 300 && p2.http < 300, 'setup: the fields set by hand ' + p1.http + ' ' + p2.http);
  dbx('UPDATE doc_meta SET review=(CASE WHEN node_id=? THEN 1 ELSE 0 END) WHERE node_id IN (?, ?, ?)', [D2, D1, D2, D3]);
  const ROOT = (await call('GET', `/api/files/nodes/${D1}`)).parent_id;
  const PLAIN = (await call('POST', '/api/files/folders', {space: 'private', name: 'Holiday'})).id;
  const pfd = new FormData(); pfd.append('parent_id', String(PLAIN)); pfd.append('file', new Blob(['Sun cream, hat'], {type: 'text/plain'}), 'packing-list.txt');
  const PFILE = ((await (await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: pfd})).json().catch(() => ({}))).items || [])[0]?.id;  // the switch shows in a folder with entries
  check(ROOT && PLAIN && (await call('GET', `/api/files?parent=${ROOT}`)).node?.recog_on, 'setup: the documents folder recognises, a plain folder beside it');
  check(PFILE, 'setup: a file in the plain folder');

  // ================= the server: sort by type / to review, the setting's new value
  const tyA = await order('sort=type'), tyD = await order('sort=type&dir=desc');
  check(tyA.join() === [D2, D1, D3].join(), `sort=type: A-Z (Contract, Invoice), without a type last ${tyA}`);
  check(tyD.join() === [D1, D2, D3].join(), `sort=type&dir=desc: Z-A, without a type still last ${tyD}`);
  check((await order('sort=review'))[0] === D2, 'sort=review: the one to review first');
  check((await call('PATCH', '/api/settings', {set_delta: {ab_cards: {add: ['!n:' + ROOT]}}})).http === 200 && (await cards()).includes('!n:' + ROOT), 'ab_cards accepts "!n:<id>" (list chosen in a recognising folder)');
  check((await call('PATCH', '/api/settings', {set_delta: {ab_cards: {remove: ['!n:' + ROOT]}}})).http === 200 && !(await cards()).length, '... and removes it');
  check((await call('PATCH', '/api/settings', {ab_cards: '["!s:private"]'})).http === 400 && (await call('PATCH', '/api/settings', {ab_cards: '["!!n:3"]'})).http === 400, 'other values stay refused');

  // ================= a computer (jsdom): the switch, the list, the sort, kept after a new start
  let w = await boot({user: 'alice', hash: 'ablage/' + ROOT}), d = w.document;
  check(await until(() => d.querySelector(`.abview .dc-infold .dc-card [data-dco="${D1}"]`)), 'the documents folder: cards by default');
  check(d.querySelector('.abview .abtools [data-abdv="cards"][aria-pressed="true"]') && d.querySelector('.abview .abtools [data-abdv="list"][aria-pressed="false"]'), 'the switch List | Cards above it, Cards chosen');
  d.querySelector('.abview [data-abdv="list"]').click();
  check(await until(() => d.querySelector(`.abview .dc-infold .abdl [data-dco="${D1}"]`) && !d.querySelector('.dc-infold .dc-grid')), 'List: the documents as rows, no cards');
  check(d.querySelector('.abview [data-abdv="list"][aria-pressed="true"]'), '... the switch shows List');
  const head = [...d.querySelectorAll('.abdl .abdlhead [role="columnheader"] .abdlsort')].map(b => b.firstChild?.textContent.trim());
  check(head.join('|') === 'Name|Type|Sender|Date|Amount|To review', 'the columns: ' + head.join('|'));
  const row = id => d.querySelector(`.abdl .abdlrow[data-abid="${id}"]`), cell = (id, k) => row(id)?.querySelector('.abdl-' + k)?.textContent.trim();
  check(cell(D1, 'type') === 'Invoice' && cell(D1, 'sender') === 'Beta Example GmbH' && /2025/.test(cell(D1, 'date') || '') && /120/.test(cell(D1, 'amount') || ''), `a row: type, sender, date, amount (${row(D1)?.textContent.replace(/\s+/g, ' ')})`);
  check(/To review/.test(cell(D2, 'review') || '') && !/To review/.test(cell(D1, 'review') || ''), 'the column To review marks the one to check');
  check(/Invoice/.test(row(D1)?.querySelector('.abdlsub')?.textContent || ''), 'the second line below the name carries the type (shown on narrow screens)');
  check(row(D1)?.querySelector('[data-ab="menu"]'), 'a row keeps the file store\'s menu');
  check(await until(async () => (await cards()).includes('!n:' + ROOT)), 'the choice is saved (ab_cards "!n:<id>")');
  check(!d.querySelector('.dc-infold .ts-bar'), 'no card size above the list');
  const ids = () => [...d.querySelectorAll('.abdl .abdlrow[data-abid] [data-dco]')].map(b => +b.dataset.dco);
  d.querySelector('.abdl [data-abdls="type"]').click();
  check(await until(() => !w.eval('DC.loading') && ids().join() === [D2, D1, D3].join()), 'the header Type sorts A-Z ' + ids());
  check(d.querySelector('.abdl .abdl-type[aria-sort="ascending"]'), '... marked ascending');
  d.querySelector('.abdl [data-abdls="type"]').click();
  check(await until(() => !w.eval('DC.loading') && ids().join() === [D1, D2, D3].join()), 'Type again: Z-A ' + ids());
  d.querySelector('.abdl [data-abdls="review"]').click();
  check(await until(() => !w.eval('DC.loading') && ids()[0] === D2), 'the header To review: the one to check first ' + ids());
  d.querySelector('.abdl [data-abdls="title"]').click();
  check(await until(() => !w.eval('DC.loading') && ids().join() === [D1, D2, D3].join()), 'the header Name: A-Z ' + ids());
  d.querySelector(`.abdl [data-dco="${D2}"]`).click();
  check(await until(() => d.querySelector('.dv-view')), 'a row opens the document view');
  d.querySelector('.dv-view [data-dc="close"]')?.click();
  check(await until(() => w.location.hash === `#ablage/${ROOT}` && d.querySelector(`.abdl [data-dco="${D2}"]`)), 'Back: the list again');
  w.close();
  w = await boot({user: 'alice', hash: 'ablage/' + ROOT}); d = w.document;
  check(await until(() => d.querySelector(`.abview .dc-infold .abdl [data-dco="${D1}"]`)), 'a new start: the folder shows its list again (kept)');
  d.querySelector('.abview [data-abdv="cards"]').click();
  check(await until(() => d.querySelector(`.abview .dc-infold .dc-card [data-dco="${D1}"]`) && !d.querySelector('.abdl')), 'Cards again: the cards');
  check(await until(async () => !(await cards()).includes('!n:' + ROOT)), '... the choice removed from the setting');
  w.location.hash = '#ablage/' + PLAIN;
  check(await until(() => d.querySelector('.abview [data-abdv="list"][aria-pressed="true"]') && d.querySelector(`.abview .ablist [data-abid="${PFILE}"]`) && !d.querySelector('.dc-infold')), 'a folder without recognition: its own switch, a list by default');
  w.close();

  // ================= the widths (Firefox): 1280 the columns, 460 / 320 the second line, nothing over the side
  await call('PATCH', '/api/settings', {set_delta: {ab_cards: {add: ['!n:' + ROOT]}}});
  await firefox(async o => {
    const {cmd, ev, ctx, shot, nav, idle} = o;
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    for (const [W, Ht] of [[1280, 860], [460, 860], [320, 700]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Ht}});
      await nav(B + '#ablage/' + ROOT);
      check(await o.until(`!!document.querySelector('.abdl [data-dco="${D1}"]')`, {timeout: 20000}), `${W}: the list of the documents folder`);
      await idle();
      const m = await ev(`(() => { const vis = e => !!e && getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().width > 0;
        const r = document.querySelector('.abdl .abdlrow[data-abid="${D1}"]'), sub = r?.querySelector('.abdlsub');
        return {head: vis(document.querySelector('.abdl .abdlhead')), type: vis(r?.querySelector('.abdl-type')), sub: vis(sub), subTxt: sub?.textContent || '',
          seg: vis(document.querySelector('.abview [data-abdv="list"]')), menu: vis(r?.querySelector('[data-ab="menu"]')),
          sw: document.documentElement.scrollWidth, vw: innerWidth, right: Math.round(document.querySelector('.abdl').getBoundingClientRect().right) }; })()`);
      if (W >= 768) check(m.head && m.type && !m.sub, `${W}: the header and the column Type, no second line ${JSON.stringify(m)}`);
      else check(!m.head && !m.type && m.sub && /Invoice/.test(m.subTxt), `${W}: the type as a second line below the name, no header ${JSON.stringify(m)}`);
      check(m.seg && m.menu, `${W}: the switch and the row's menu are there`);
      check(m.sw <= m.vw && m.right <= m.vw, `${W}: nothing runs over the side ${JSON.stringify(m)}`);
      await shot(`p2769-b-${W}-list.png`);
    }
  });

  console.log(`p2769_b_docslist_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
