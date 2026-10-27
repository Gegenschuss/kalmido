// 2.169.0 A (#2671) UI tests (jsdom, own container via start.sh): the knowledge pages offline. jsdom has no IndexedDB: the
// copy's small store is handed in as a stand-in (window.__wkoStore, the same calls as the IndexedDB one in wiki.js), shared
// by the windows of one "browser".
// - opening the knowledge pages keeps a copy of the space with every text; the next sync asks only for the texts changed since
// - offline: the pages come from the copy with "Offline · as of …", the search finds words in the texts, a page opens with its text
// - an offline change waits in the outbox (the copy has it at once); the tab closed and opened again online = sent
// - changed elsewhere meanwhile: no version is lost, the own one waits at the page ("Compare" -> keep mine) until it is decided
// - a space this account no longer has leaves the copy at the next sync; logout empties it
// - 2.238.0 B (#2872): every record carries the sign-in mark (me.sgen); each boot here is a new sign-in (p2238_b_wikioffline_ui.js)
// - 2.169.1 (#949 / #2672): on a computer with sidebar B the offline mark sits in the bar above the folder and the search finds
//   words in the texts; on a phone the same in its list; waiting conflicts are read by key range (pre), the kept lock state
//   fills WKE.info offline, a refused page change has its own toast, the index says more=false and the mark names the 5000 cap
// freelancer-matrix: wiki (the pages are in the private space of a person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2169A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const clone = v => v === undefined ? v : JSON.parse(JSON.stringify(v));

// one browser: the copy's store and localStorage, shared by its windows
function browser() {
  const db = new Map(), urls = [];
  const store = {get: async k => clone(db.get(k)), put: async v => { db.set(v.k, clone(v)); }, del: async k => { db.delete(k); },
    all: async () => { store.nAll++; return [...db.values()].map(clone); }, pre: async x => [...db.values()].filter(r => r.k.startsWith(x)).map(clone), nAll: 0, clear: async () => { db.clear(); }, close: async () => {}};
  const setup = w => {
    w.__wkoStore = store;
    const of = w.fetch; w.fetch = (u, o = {}) => { if (!w.__offline && /\/api\/wiki\?/.test(String(u))) urls.push(String(u)); return of(u, o); };
  };
  return {db, urls, setup, store, shared: {store: {}, wins: []}};
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  check(!(st0.me.workspaces || []).length, 'setup: frida has no organisation');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'wiki'])].join(',');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: feats});
  const P1 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Docs/Start', body: 'Alpha start text'})).id;
  const P2 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Docs/Other', body: 'Beta zebra text'})).id;
  check(P1 && P2, 'setup: two pages');

  // ================= the copy: kept on opening, the next sync only for changed texts
  const br = browser();
  const opt = {user: 'frida', hash: 'wiki', shared: br.shared, setup: br.setup, ls: {'tasks.wkSpace': JSON.stringify('private')}};
  let w = await boot(opt), d = w.document;
  await until(() => typeof w.wk_loadPage === 'function' && w.eval(`(WK.idx.private?.pages || []).length`) === 2, 60);
  const c0 = await until(() => { const r = br.db.get('s:private'); return r && r.pages?.length === 2 ? r : null; }, 40);
  check(c0 && c0.uid === st0.me.id && c0.pages.find(p => p.id === P2)?.body === 'Beta zebra text' && c0.pages.find(p => p.id === P1)?.body === 'Alpha start text', 'the copy holds the space with every text');
  check(br.urls.some(u => /offline=1/.test(u) && /bodies=1/.test(u)), 'the index is asked with offline=1 ' + JSON.stringify(br.urls.slice(0, 2)));
  check((await call('GET', '/api/wiki?space=private&offline=1&bodies=1')).more === false, '2.169.1 (#2672): the index says more=false below the cap');
  await sleep(1100);
  await call('PATCH', `/api/wiki/pages/${P2}`, {body: 'Beta zebra changed'});
  br.urls.length = 0;
  await w.eval(`wk_load('private', true)`);
  check(br.urls.length === 1 && /[?&]since=/.test(br.urls[0]), 'the next sync asks only for what changed since the newest text ' + JSON.stringify(br.urls));
  const c1 = br.db.get('s:private');
  check(c1?.pages.find(p => p.id === P2)?.body === 'Beta zebra changed' && c1?.pages.find(p => p.id === P1)?.body === 'Alpha start text', 'the copy: the changed text new, the unchanged one kept');

  // ================= offline: reading, searching, a page
  w.__offline = true;
  w.eval(`WK.idx = {}; WK.pg = null; 1`);
  await w.eval(`wk_load('private', true)`);
  check(w.eval(`!!WK.idx.private.off && WK.idx.private.pages.length === 2`), 'offline: the pages come from the copy');
  w.location.hash = '#wiki';
  const hint = await until(() => d.querySelector('#view .wkoff'), 40);
  check(hint && /Offline · as of/.test(hint.textContent), 'offline: the view says "Offline · as of …" ' + (hint?.textContent || ''));
  const q = d.querySelector('#wk-q');
  q.value = 'zebra'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  check([...d.querySelectorAll('#wk-res a')].some(a => a.getAttribute('href') === '#wiki/' + P2), 'offline: the search finds a word of the text');
  // 2.169.1 (#949): a computer = sidebar B: the mark in the bar above the folder, the hits in the folder's list
  check(w.eval(`sbb_on()`) && !!d.querySelector('#view .wkdesk .wkoff') && !!d.querySelector('#view .wkdesk #wk-res.wkdlist'), 'sidebar B: offline mark and text search in the computer view');
  w.eval(`WK.idx.private.more = true; renderView(); 1`);
  check(/only the first 5000 pages/.test(d.querySelector('#view .wkoff')?.textContent || ''), '2.169.1 (#2672): a space over the cap: the mark names it');
  w.eval(`WK.idx.private.more = false; 1`);
  q.value = ''; q.dispatchEvent(new w.Event('input', {bubbles: true})); w.eval(`WK.q = ''; 1`);
  w.location.hash = '#wiki/' + P2;
  const md = await until(() => { const x = d.querySelector('#view #wk-md'); return x && /Beta zebra changed/.test(x.textContent) ? x : null; }, 40);
  check(md, 'offline: the page opens with its text');
  check(/Offline · as of/.test(d.querySelector('#view .wkpage .ntfoot')?.textContent || ''), 'offline: the page foot says it is the copy');

  // ================= offline: a change waits, the tab goes, online again = sent
  d.querySelector('#view [data-wk="mode"][data-m="edit"]')?.click();
  const ta = await until(() => d.querySelector('#wk-body'), 20);
  check(ta, 'offline: the page can be edited');
  ta.value = 'Offline edit one'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  await w.eval(`wk_flush()`);
  const qd = w.eval(`JSON.stringify(OUT.q.filter(x => x.url === '/api/wiki/pages/${P2}').map(x => x.body))`);
  check(/Offline edit one/.test(qd) && /expect_updated_at/.test(qd), 'offline: the change waits in the outbox with its base ' + qd);
  check(br.db.get('s:private')?.pages.find(p => p.id === P2)?.body === 'Offline edit one', 'offline: the copy has the change at once');
  check(/Saved on this device/.test(d.querySelector('#wk-saved')?.textContent || ''), 'offline: "Saved on this device, sent when online"');
  ta.value = 'Offline edit two'; ta.dispatchEvent(new w.Event('input', {bubbles: true}));
  await w.eval(`wk_flush()`);
  check(w.eval(`OUT.q.filter(x => x.url === '/api/wiki/pages/${P2}').length`) === 1, 'offline: a newer text replaces the waiting one');
  check((await call('GET', `/api/wiki/pages/${P2}`)).body === 'Beta zebra changed', 'offline: nothing sent yet');
  w.close();
  w = await boot(opt); d = w.document;
  const sent = await until(async () => (await call('GET', `/api/wiki/pages/${P2}`)).body === 'Offline edit two', 60);
  check(sent, 'the tab closed and opened again online: the waiting text is sent');
  await until(() => !w.eval(`OUT.q.length`), 40);

  // ================= changed elsewhere meanwhile: mine waits at the page
  await until(() => typeof w.wk_loadPage === 'function', 60);
  w.location.hash = '#wiki/' + P1;
  await until(() => d.querySelector('#view #wk-md'), 40);
  w.__offline = true;
  await w.eval(`wk_loadPage(${P1}, true)`);
  check(w.eval(`!!WK.pg?._off`), 'conflict: the page offline from the copy');
  w.eval(`WK.edit = true; renderView(); 1`);
  const ta2 = await until(() => d.querySelector('#wk-body'), 20);
  ta2.value = 'Mine offline'; ta2.dispatchEvent(new w.Event('input', {bubbles: true}));
  await w.eval(`wk_flush()`);
  await sleep(1100);
  await call('PATCH', `/api/wiki/pages/${P1}`, {body: 'Theirs online'});
  w.__offline = false;
  await w.eval(`flush()`);
  await until(() => !w.eval(`OUT.q.length`), 40);
  check((await call('GET', `/api/wiki/pages/${P1}`)).body === 'Theirs online', 'conflict: the other version stays on the server');
  const cf = br.db.get('x:' + P1);
  check(cf && cf.mine === 'Mine offline' && cf.sp === 'private', 'conflict: my version waits in the copy ' + JSON.stringify(cf));
  check(!w.eval(`S.conflicts.some(c => c.mine === 'Mine offline')`), 'conflict: not as a rejected change in the conflicts dialog');
  w.eval(`WK.edit = false; 1`);
  await w.eval(`wk_loadPage(${P1}, true)`);
  w.eval(`renderView(); 1`);
  const bar = await until(() => d.querySelector('#view .wkocf'), 40);
  br.store.nAll = 0; w.eval(`WKO.cf = {}; 1`); await w.eval(`wko_cfLoad('private')`);
  check(w.eval(`!!WKO.cf[${P1}]`) && br.store.nAll === 0, '2.169.1 (#2672): waiting conflicts read by key range, not the whole copy');
  check(bar && /changed elsewhere/.test(bar.textContent), 'conflict: the bar at the page');
  let asked = '';
  w.confirm = t => { asked = String(t); return true; };  // the harness answers the app's dialogs through confirm (boot.js): "Keep mine"
  bar?.querySelector('[data-wk="cfshow"]')?.click();
  await until(() => asked, 40);
  check(/Keep your version or take theirs/.test(asked) && /Mine offline/.test(asked) && /Theirs online/.test(asked), 'conflict: "Compare" shows both versions ' + asked.slice(0, 300));
  const kept = await until(async () => (await call('GET', `/api/wiki/pages/${P1}`)).body === 'Mine offline', 40);
  check(kept, 'conflict: "Keep mine" saves my version');
  check(await until(() => !br.db.has('x:' + P1) && !d.querySelector('#view .wkocf'), 40), 'conflict: decided = the bar and the waiting version are gone');

  // ================= 2.169.1 (#949): a phone: the same offline mark and text search in its list
  const wp = await boot({...opt, mobile: true}), dp = wp.document;
  await until(() => typeof wp.wk_loadPage === 'function' && wp.eval(`(WK.idx.private?.pages || []).length`) >= 2, 60);
  // 2.238.0 B (#2872): the phone window has its own sign-in (boot logs in again): the copy carries its mark once it synced
  await wp.eval(`wk_load('private', true)`);
  check(await until(() => br.db.get('s:private')?.g === wp.eval('S.me.sgen'), 40), '2.238.0 B: the copy carries the phone window\'s sign-in mark');
  wp.__offline = true;
  wp.eval(`WK.idx = {}; 1`); await wp.eval(`wk_load('private', true)`); wp.eval(`renderView(); 1`);
  const hp = await until(() => dp.querySelector('#view .wkoff'), 40);
  check(hp && !wp.eval(`sbb_on()`) && !dp.querySelector('#view .wkdesk'), 'phone: offline mark without the computer view');
  const qp = dp.querySelector('#wk-q');
  if (qp) { qp.value = 'edit two'; qp.dispatchEvent(new wp.Event('input', {bubbles: true})); }
  check([...dp.querySelectorAll('#wk-res a')].some(a => a.getAttribute('href') === '#wiki/' + P2), 'phone: offline the search finds a word of the text');
  // 2.169.1 (#2672): the kept lock state fills WKE.info offline (names, not ?)
  br.db.set('e:org:4242', {k: 'e:org:4242', sp: 'org:4242', uid: st0.me.id, g: wp.eval('S.me.sgen'), j: {mode: 'e2e', gen: 1, space_id: 4242, members: [{user_id: 777, name: 'Zora'}]}});
  await wp.eval(`delete WKE.info['org:4242']; wkeInfo('org:4242').catch(() => null)`);
  check(wp.eval(`wkeName('org:4242', 777)`) === 'Zora' && wp.eval(`!!WKE.st['org:4242']`), 'offline: the kept lock state fills WKE.info');
  br.db.delete('e:org:4242');
  wp.close();
  // 2.169.1 (#2672): an offline change of a page deleted meanwhile: its own toast, not "task deleted"
  const P3 = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Docs/Gone', body: 'Gone soon'})).id;
  await w.eval(`wk_load('private', true)`);
  w.location.hash = '#wiki/' + P3;
  await until(() => /Gone soon/.test(d.querySelector('#view #wk-md')?.textContent || ''), 40);
  w.__offline = true;
  await w.eval(`wk_loadPage(${P3}, true)`);
  w.eval(`WK.edit = true; renderView(); 1`);
  const ta3 = await until(() => d.querySelector('#wk-body'), 20);
  check(ta3, 'offline: the page to be deleted can be edited');
  if (ta3) { ta3.value = 'Typed offline'; ta3.dispatchEvent(new w.Event('input', {bubbles: true})); }
  await w.eval(`wk_flush()`); w.eval(`WK.edit = false; 1`);
  await call('DELETE', `/api/wiki/pages/${P3}`);
  w.eval(`window.__toasts = []; const t0 = toast; toast = (m, ...a) => { window.__toasts.push(String(m)); return t0(m, ...a); }; 1`);
  w.__offline = false;
  await w.eval(`flush()`);
  const tt = await until(() => { const x = w.eval(`window.__toasts.join(' | ')`); return /knowledge page/.test(x) ? x : null; }, 40);
  check(tt && !/task deleted/.test(tt), 'a refused page change: "knowledge page not applied", not "task deleted" ' + w.eval(`window.__toasts.join(' | ')`));

  // ================= a space this account no longer has goes; logout empties the copy
  br.db.set('s:org:9999', {k: 's:org:9999', sp: 'org:9999', uid: st0.me.id, pages: [{id: 1, path: 'Old', body: 'old'}]});
  br.db.set('s:private-other', {k: 's:private-other', sp: 'private', uid: 999999, pages: []});
  // 2.280.0 C (#3114): the tidying runs at the first space opened in a session (no start sync any more)
  await w.eval(`WKO.swept = null; wk_load('private', true)`);
  await w.eval(`WKO.swept`);
  check(!br.db.has('s:org:9999') && !br.db.has('s:private-other') && br.db.has('s:private'), 'sync: a space no longer mine and another account\'s record leave the copy');
  // review: my own text sent twice (the first answer got lost) is no conflict
  const twice = await w.eval(`wkoReject({url: '/api/wiki/pages/${P1}', method: 'PATCH', body: {body: 'Same text'}}, {status: 409, data: {page: {id: ${P1}, space: 'private', body: 'Same text', updated_at: '2030-01-01T00:00:00Z'}}})`);
  check(twice === true && !br.db.has('x:' + P1), 'a text sent twice: saved already, no waiting conflict');
  await w.eval(`clearLocal()`);
  check(br.db.size === 0, 'logout: the copy is empty');
  await w.eval(`wko_put({k: 's:private', sp: 'private', pages: [{id: 1, path: 'Late', body: 'late'}]})`);
  check(br.db.size === 0, 'logout: a sync still on its way writes nothing afterwards');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
