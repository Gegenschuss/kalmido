// 2.59.0 UI tests (part B), own container (start.sh) with the embedding service's stub inside. jsdom:
// #1375 a task shows "Related tasks" folded; unfolded it loads the related tasks (the duplicate marked "probably a
//       duplicate", a tap opens it); the quick add shows "Similar: #…" after a pause in typing; the search has "also similar
//       meaning" (per device) and sends semantic=1; Administration > Server shows the switch with the service's state;
//       switched off, the section and the search switch are gone
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const EXTRA = (process.env.EXTRA || '') + ' -e KALMIDO_EMBED_URL=http://127.0.0.1:8090 -e KALMIDO_EMBED_IDLE=0.5 -e KALMIDO_EMBED_BUSY=0.2'
  + ' -e KALMIDO_RELATED_MIN=0.6 -e KALMIDO_RELATED_DUP=0.95 -e KALMIDO_RELATED_SEARCH=0.5';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA}});
// #2716: the root filesystem is read-only, docker cp refuses even /tmp (tmpfs) - pipe the file in
execFileSync('docker', ['exec', '-i', CT, 'sh', '-c', 'cat > /tmp/embed_stub.py'], {input: require('fs').readFileSync(path.join(__dirname, '..', 'embed', 'server.py'))});
execFileSync('docker', ['exec', '-d', '-e', 'EMBED_STUB=1', CT, 'python', '/tmp/embed_stub.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Office work'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Invoice template for clients', list_id: L})).id;
  const T2 = (await call('POST', '/api/tasks', {title: 'Invoice template for clients', list_id: L})).id;
  const T3 = (await call('POST', '/api/tasks', {title: 'Invoice template for customers', list_id: L})).id;
  await call('POST', '/api/tasks', {title: 'Buy milk and bread', list_id: L});
  const rel = await until(async () => { const j = await call('GET', `/api/tasks/${T1}/related`); return j.items?.length ? j : null; }, 150);
  check(rel && rel.items.some(x => x.id === T2 && x.dup), 'setup: the vectors are computed, T2 is a duplicate of T1 ' + JSON.stringify(rel));

  // ================= the section in a task: folded, loads when unfolded
  let w = await boot({user: 'alice', hash: 'l/' + L, ls: {'tasks.rt9Open': 'false'}}), d = w.document;
  w.eval(`openDetail(${T1})`); await until(() => d.querySelector('#d-rel'));
  const sec = () => d.querySelector('#d-rel');
  check(sec() && !sec().open, '#1375: the task has "Related tasks", folded');
  check(/Related tasks/.test(sec()?.querySelector('summary')?.textContent || ''), '#1375: its heading');
  check(!sec()?.querySelector('.rt9it'), '#1375: nothing loaded while folded');
  sec().open = true; sec().dispatchEvent(new w.Event('toggle'));
  await until(() => sec()?.querySelector('.rt9it'));
  const items = [...(sec()?.querySelectorAll('.rt9it') || [])];
  check(items.some(b => +b.dataset.id === T2 && b.querySelector('.rt9dup')), '#1375: the duplicate, marked "probably a duplicate"');
  check(items.some(b => +b.dataset.id === T3) && !items.some(b => +b.dataset.id === T1), '#1375: the close one, never the task itself');
  check(/#\d+/.test(items[0]?.querySelector('.rt9n')?.textContent || ''), '#1375: number and title');
  check(sec().querySelector('summary .rt9dupb'), '#1375: the heading says "probably a duplicate"');
  check(w.eval(`LS.get('rt9Open', false)`) === true, '#1375: unfolded is remembered (per device)');
  click(w, items.find(b => +b.dataset.id === T2)); await until(() => w.eval('S.sel') === T2);
  check(w.eval('S.sel') === T2, '#1375: a tap opens the related task');

  // ================= the hint while adding
  w.eval(`closeDetail && closeDetail()`); await sleep(200);
  const qi = d.querySelector('#qinput');
  check(qi, 'the quick add is there');
  if (qi) {
    qi.focus(); qi.value = 'Invoice template for clients'; qi.dispatchEvent(new w.Event('input', {bubbles: true}));
    await until(() => d.querySelector('.rt9qh'), 40);
    const h = d.querySelector('.rt9qh');
    check(h && /Similar:/.test(h.textContent) && h.querySelector(`[data-act="open-id"][data-id="${T1}"], [data-act="open-id"][data-id="${T2}"]`), '#1375: "Similar: #… title" under the quick add ' + (h?.textContent || ''));
    check(h && h.querySelectorAll('.rt9qi').length <= 2, '#1375: at most two');
    qi.value = ''; qi.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(100);
    check(!d.querySelector('.rt9qh'), '#1375: an empty field: no hint');
  }
  w.close();

  // ================= the search switch
  w = await boot({user: 'alice', hash: 'search', ls: {'tasks.rt9Sem': 'false'}}); d = w.document;
  await until(() => d.querySelector('#rt9-sem'));
  check(d.querySelector('#rt9-sem') && !d.querySelector('#rt9-sem').checked, '#1375: the search has "also similar meaning", off');
  check(/also similar meaning/.test(d.querySelector('.rt9sem')?.textContent || ''), '#1375: its label');
  const sem = d.querySelector('#rt9-sem'); sem.checked = true; sem.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(w.eval(`LS.get('rt9Sem', false)`) === true && w.eval('rt9_semQ()') === '&semantic=1', '#1375: on = semantic=1, remembered per device');
  w.eval(`doSearch('clients invoice')`); await until(() => d.querySelectorAll('#sresults .task, #sresults [data-id]').length);
  check(d.querySelectorAll('#sresults [data-id]').length >= 2, '#1375: the search shows hits');
  w.close();

  // ================= Administration > Server
  w = await boot({user: 'alice', lazy: true}); d = w.document;
  w.eval(`settingsModal('server')`); await until(() => d.querySelector('#s-rt9-on'), 60);
  check(d.querySelector('#s-rt9-on')?.checked, '#1375: Administration > Server: "Show related tasks" on');
  check(/Service reachable/.test(d.querySelector('#s-rt9')?.textContent || '') && /stub/.test(d.querySelector('#s-rt9')?.textContent || ''), '#1375: the state of the service ' + (d.querySelector('#s-rt9')?.textContent || ''));
  const on = d.querySelector('#s-rt9-on'); on.checked = false; on.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/related/config')).enabled === false);
  check((await call('GET', '/api/related/config')).enabled === false, '#1375: switched off on the server');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + L, ls: {'tasks.rt9Open': 'true'}}); d = w.document;
  w.eval(`openDetail(${T1})`); await sleep(1200);
  check(d.querySelector('#d-title') && !d.querySelector('#d-rel'), '#1375: switched off: no section in the task');
  w.close();
  w = await boot({user: 'alice', hash: 'search'}); d = w.document; await sleep(1000);
  check(d.querySelector('#searchq') && !d.querySelector('#rt9-sem'), '#1375: switched off: no search switch');
  w.close();
  await call('PUT', '/api/admin/related', {on: true});

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
