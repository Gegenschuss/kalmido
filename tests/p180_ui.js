// 1.8.0 UI tests (jsdom): the sample project. Setup step 2: 2.7.0 (K21) "Start with" offers the sample project as one of
// the cards (Empty preselected, one start at a time) and Start creates it. The sample in the
// app: Flow order + "Next", "Now doable" skips the waiting task. Settings > Data: remove (own dialog naming the lists and
// the number of tasks; Cancel keeps it), create again (opens the list), the command palette entry. Welcome tour (own
// container with KALMIDO_ONBOARDING=1): the first card offers it (preticked with the project modules, unticked without,
// German), Next / Esc create it, unticked or Skip do not, it is asked only once.
// Restarts the test container (start.sh) for the setup and the tour parts.
const {execFileSync} = require('child_process');
const path = require('path');
const {JSDOM, VirtualConsole} = require('jsdom');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
// a restarted container: wait until the proxy port answers too (start.sh only waits for the app port)
const fresh = async (env = {}) => {
  execFileSync('bash', [path.join(__dirname, 'start.sh')], {stdio: 'ignore', env: {...process.env, ...env}});
  for (let i = 0; i < 60; i++) { try { if ((await fetch(B + 'api/health')).ok) break; } catch { /* not up yet */ } await sleep(500); }
  await sleep(500);
};
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { el.checked = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const until = async (fn, ms = 5000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(80); } return false; };

async function openSetup(jar) {  // the app with a cookie jar of its own (the setup response logs the admin in), as in setup_ui.js
  const vc = new VirtualConsole(); vc.on('jsdomError', e => { if (!/navigation|Not implemented/.test(e.message)) errs.push(e.message); });
  const dom = await JSDOM.fromURL(B, {runScripts: 'dangerously', resources: new (require('./boot').PooledLoader)(),  /* 2.20.0: browser-like connections (boot.js) */ pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      const store = {};
      w.matchMedia = () => ({matches: false, addEventListener() {}, addListener() {}});
      Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; }, key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
      w.fetch = async (u, o = {}) => {
        const r = await fetch(new URL(String(u), B), {...o, headers: {...(o.headers || {}), ...(jar.c ? {Cookie: jar.c} : {})}});
        const sc = r.headers.get('set-cookie'); if (sc) jar.c = sc.split(';')[0];
        return r;
      };
      w.Request = Request; w.Response = Response; w.Headers = Headers; w.FormData = FormData;
      Object.defineProperty(w.navigator, 'serviceWorker', {value: {register: () => Promise.resolve(), addEventListener() {}, controller: null}});
      w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
      w.confirm = () => true; w.prompt = () => null;
      require('./boot').dialogBridge(w);
    }});
  await sleep(1500);
  return dom.window;
}

(async () => {
  // ================= (1) setup step 2
  await fresh();
  const jar = {};
  let w = await openSetup(jar), d = w.document;
  const f = d.querySelector('.authscreen #auth-form');
  d.querySelector('#au-user').value = 'admin'; d.querySelector('#au-name').value = 'Admin'; d.querySelector('#au-pw').value = 'password123';
  f.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  await until(() => d.querySelector('.setupcard'));
  // 2.7.0 (K21): one question "Start with" (cards): Empty (preselected) or the sample project or a project type
  const card = k => d.querySelector(`[data-su-start="${k}"]`);
  check(card('sample') && /Sample project/.test(card('sample').textContent), 'setup: "Sample project" offered as a start');
  check(card('').classList.contains('on') && !card('sample').classList.contains('on'), 'setup: "Empty" preselected');
  click(w, d.querySelector('[data-su-preset="team"]')); await sleep(50);
  check(card('').classList.contains('on'), 'setup: the preset does not change the start');
  click(w, card('agency')); await sleep(50);
  check(card('agency').classList.contains('on') && card('agency').getAttribute('aria-checked') === 'true', 'setup: a project type can be picked');
  click(w, card('sample')); await sleep(50);
  check(card('sample').classList.contains('on') && !card('agency').classList.contains('on'), 'setup: one start at a time');
  click(w, d.querySelector('[data-su="go"]')); await sleep(1200);
  let st = await call('GET', '/api/state', null, jar.c);
  check(st.sample && st.sample.tasks === 27 && st.sample.lists.length === 2, 'setup: Start created the sample: ' + JSON.stringify(st.sample)?.slice(0, 120));
  check(st.settings.sample_ask === '0', 'setup: decided, the tour will not ask');
  w.close();
  const PRJ = st.sample.lists[0].id;

  // ================= (2) the sample in the app: Flow, Now doable
  w = await boot({user: 'admin', hash: 'l/' + PRJ}); d = w.document;
  check(w.eval('S.lists').find(l => l.id === PRJ)?.name === 'Example: Image film for client Muster', 'sample list loaded');
  check(w.eval('sortMode()') === 'flow', 'project sample: Flow order');
  check(d.querySelectorAll('#view .trow').length >= 14, 'rows shown: ' + d.querySelectorAll('#view .trow').length);
  check(d.querySelectorAll('#view .ghead').length >= 5, 'sections shown');
  check(d.querySelector('#view .trow.flownext'), '"Next" marker');
  check(d.querySelectorAll('#view .trow .blk').length >= 3, 'waiting tasks carry the lock');
  w.eval(`go('doable')`); await sleep(300);
  const doable = [...d.querySelectorAll('#view .trow .ttl, #view .trow .title')].map(x => x.textContent).join('|') || d.querySelector('#view').textContent;
  check(/Write the concept and treatment/.test(doable) && !/Get the quote and budget approved/.test(doable), 'Now doable: the overdue concept, not the budget that waits on it');
  // ================= (3) Settings > Data: remove (dialog), create again, palette
  w.__dialogs = 'manual';
  w.eval(`settingsModal('sample')`); await sleep(300);
  const row = () => d.querySelector('.smodal #s-sample');
  check(d.querySelector('.smodal [data-sec="data"].on') && d.querySelector('.smodal #s-sample-h'), 'Settings opens on Data > Sample project');
  check(row()?.querySelector('[data-m="sample-rm"]') && /Image film/.test(row().textContent), 'row: Remove + the list names');
  click(w, row().querySelector('[data-m="sample-rm"]')); await sleep(200);
  let dlg = d.querySelector('.modal.cdlg');
  const txt = dlg?.textContent || '';
  check(/Remove the sample project\?/.test(txt) && /Image film for client Muster/.test(txt) && /Shoot day packing list/.test(txt) && /27 sample tasks/.test(txt), 'dialog names the lists and the tasks: ' + txt.slice(0, 200));
  click(w, dlg.querySelector('[data-cd="no"]')); await sleep(300);
  check((await call('GET', '/api/state', null, await login('admin'))).sample, 'Cancel keeps the sample');
  click(w, row().querySelector('[data-m="sample-rm"]')); await sleep(200);
  click(w, d.querySelector('.modal.cdlg [data-cd="yes"]')); await sleep(900);
  check(w.eval('S.sample') === null && !w.eval('S.lists').some(l => l.name.startsWith('Example:')), 'removed: lists gone');
  check(row()?.querySelector('[data-m="sample-add"]'), 'row switches to "Create sample project"');
  check(/Sample project removed \(27 tasks\)/.test(d.querySelector('#toast, .toast')?.textContent || d.body.textContent), 'toast after removal');
  click(w, row().querySelector('[data-m="sample-add"]')); await sleep(1200);
  check(!d.querySelector('.smodal'), 'create closes the settings');
  const s2 = w.eval('S.sample');
  check(s2 && w.eval('S.route.key') === 'l:' + s2.lists[0].id, 'created again and opened: ' + w.eval('S.route.key'));
  w.eval('openPalette()'); await sleep(100);
  const inp = d.querySelector('.palette input'); inp.value = 'sample'; inp.dispatchEvent(new w.Event('input', {bubbles: true})); await sleep(150);
  check(/Remove sample project/.test(d.querySelector('.palette').textContent), 'palette: "Remove sample project"');
  w.eval('closePalette()');
  w.close();

  // ================= (4) welcome tour (new accounts, KALMIDO_ONBOARDING=1)
  await fresh({KALMIDO_ONBOARDING: '1'});
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  for (const u of ['bob', 'carol', 'dave']) await call('POST', '/api/users', {username: u, display_name: u, password: 'password123'}, CK);
  const tourOpen = async w => until(() => w.document.querySelector('.tour .tcard h3'), 4000);
  // alice: all modules (projects) -> preticked, Next creates it
  w = await boot({user: 'alice'}); d = w.document;
  check(await tourOpen(w), 'tour opens on the first start');
  const tb = () => d.querySelector('.tour #t-sample');
  // 2.25.0 (UX-24): the tour only explains; the sample project is offered on its LAST card
  const toLast = async () => { for (let i = 0; i < 8 && /Next|Weiter/.test(d.querySelector('[data-tour="next"]')?.textContent || ''); i++) { click(w, d.querySelector('[data-tour="next"]')); await sleep(80); } };
  check(!tb(), 'tour: no question on the first card');
  await toLast();
  check(tb() && tb().checked && /Create a sample project/.test(tb().closest('label').textContent), 'tour: the last card offers the sample, preticked with the project modules');
  click(w, d.querySelector('[data-tour="next"]'));
  check(await until(() => w.eval('S.sample')), 'tour: Done created it');
  check(w.eval('S.lists').some(l => l.name === 'Getting started') && w.eval('S.sample.lists').length === 2, 'Getting started list + the sample');
  w.close();
  // bob: German, no project modules -> unticked, Done creates nothing
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {features: 'cal,timeline,matrix', lang: 'de'}, BK);
  w = await boot({user: 'bob'}); d = w.document;
  check(await tourOpen(w), 'bob: tour');
  await toLast();
  check(tb() && !tb().checked && /Beispielprojekt anlegen/.test(tb().closest('label').textContent), 'bob: German, unticked without project modules');
  click(w, d.querySelector('[data-tour="next"]')); await sleep(800);
  check((await call('GET', '/api/state', null, BK)).sample === null, 'bob: unticked -> nothing created');
  w.close();
  // carol: preticked, untick, Done -> nothing
  w = await boot({user: 'carol'}); d = w.document;
  await tourOpen(w); await toLast();
  change(w, tb(), false);
  click(w, d.querySelector('[data-tour="next"]')); await sleep(800);
  check((await call('GET', '/api/state', null, await login('carol'))).sample === null, 'carol: unticked + Done -> nothing');
  w.close();
  // dave: Skip on the first card -> nothing (the offer was never shown)
  w = await boot({user: 'dave'}); d = w.document;
  await tourOpen(w);
  click(w, d.querySelector('[data-tour="skip"]')); await sleep(800);
  check((await call('GET', '/api/state', null, await login('dave'))).sample === null, 'dave: Skip on the first card creates nothing');
  w.close();
  // restarting the tour later never offers it
  w = await boot({user: 'dave'}); d = w.document;
  w.eval('tourStart()'); await tourOpen(w);
  check(!tb(), 'restarted tour: no sample offer');
  w.close();

  const bad = errs.filter(e => !/Could not load|ECONNREFUSED/.test(e));
  check(!bad.length, 'no script errors: ' + bad.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
