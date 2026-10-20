// 2.138.0 UI tests, part A (quotation editor), own container (start.sh), jsdom. Invented services and amounts.
// (taken over from the 2.112.0 A, 2.113.0 C and 2.114.0 sw suites, only the cases of #2236 #2239 #2249 #2257)
// - #2257 (no server): static/sw.js leaves requests of other origins (chrome-extension:// ...) to the browser and a
//   cache.put the browser refuses is no uncaught error (the worker runs in a small stub of its scope)
// - #2236: a percent position keeps its unit choice; back to "Day" counts 1 x rate again (quantity 1 when it was empty)
// - #2249: the unit select of a position follows the quantity (1 = singular, else plural), no redraw, focus stays
// - #2239: renaming an open part shows the new name on the title page line
// freelancer-matrix: office  (UI only, no new route; the person without an organisation uses the same editor code)
const fs = require('fs'), path = require('path'), vm = require('vm');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2138A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (!el) return; if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const svc = (title, qty, rate, unit = 'day') => ({kind: 'service', title, qty, unit, rate, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1});

// ================= #2257: the service worker and other origins (no server)
async function swCheck() {
  const SRC = fs.readFileSync(path.join(__dirname, '..', 'static', 'sw.js'), 'utf8');
  const ORIGIN = 'https://kalmido.example.com';
  const handlers = {}, puts = [], unhandled = [];
  const cache = {
    put: req => { puts.push(String(req.url || req)); return Promise.reject(new TypeError("Failed to execute 'put' on 'Cache': Request scheme is unsupported")); },
    match: async () => undefined, addAll: async () => {}, keys: async () => [], delete: async () => true,
  };
  const self = {location: {origin: ORIGIN}, addEventListener: (k, f) => { handlers[k] = f; }, skipWaiting: () => {}, clients: {claim: async () => {}}};
  const ctx = {self, caches: {open: async () => cache, match: async () => undefined, keys: async () => []}, URL, Headers, Response, console, setTimeout, Promise,
    fetch: async () => ({ok: true, redirected: false, type: 'basic', status: 200, headers: new Headers({'content-type': 'application/json'}), clone() { return this; }})};
  vm.createContext(ctx);
  vm.runInContext(SRC, ctx, {filename: 'sw.js'});
  const onUnh = e => unhandled.push(String(e));
  process.on('unhandledRejection', onUnh);
  const dispatch = (url, method = 'GET') => { let responded = null; handlers.fetch({request: {url, method}, respondWith: p => { responded = p; }}); return responded; };
  check(typeof handlers.fetch === 'function', '#2257: the fetch handler is registered');
  check(dispatch('chrome-extension://abcdefghijklmnop/content.js') === null, '#2257: a chrome-extension:// request is not answered by the worker');
  check(dispatch('https://cdn.other.example.org/x.js') === null, '#2257: a request of another origin is not answered by the worker');
  const own = dispatch(ORIGIN + '/static/app.css');
  check(own !== null, '#2257: a request of the own origin is still answered by the worker');
  await own;
  const i18n = dispatch(ORIGIN + '/static/i18n/de.json?v=1');
  check(i18n !== null, '#2257: a language file of the own origin is still answered by the worker');
  await i18n;
  await sleep(50);
  check(puts.length === 2, `#2257: both answers were offered to the cache (${puts.length})`);
  check(unhandled.length === 0, `#2257: a refused cache.put is no uncaught error (${unhandled.join('; ') || 'none'})`);
  process.off('unhandledRejection', onUnh);
}

// ================= #2249: the unit words of a position follow its quantity
async function unitWords(user) {
  for (const lang of ['de', 'en']) {
    const doc = await call('POST', '/api/office/docs', {kind: 'offer', lang, project_title: 'Units', items: [svc('Editing', 1, 500), svc('Flat', 1, 100, 'flat')]});
    check(doc.status === 201, `#2249 (${user}): a quotation ${doc.status}`);
    const w = await boot({user, hash: `office/offers/${doc.id}`}), d = w.document, tag = ` (${user}, ${lang})`;
    await until(() => d.querySelectorAll('.ofdeditor .ofdits .ofdit').length >= 2);
    const q = d.querySelector('.ofdits [data-k="qty"]'), sel = d.querySelector('.ofdits [data-k="unit"]');
    const txt = v => [...sel.options].find(o => o.value === v)?.textContent || '';
    const type = v => { q.focus(); q.value = v; q.dispatchEvent(new w.Event('input', {bubbles: true})); };
    // no pack labels in this fixture: the words of the UI language (en)
    check(/^(Tag|Day|day)$/.test(txt('day')), '#2249 qty 1: singular day: ' + txt('day') + tag);
    type('5'); check(/^(Tage|Days|days)$/i.test(txt('day')) && /^(Stunden|Hours|hours?)$/i.test(txt('hour')) && d.activeElement === q, '#2249 qty 5: plural, focus stays: ' + txt('day') + tag);
    type('1,5'); check(/^(Tage|Days|days)$/i.test(txt('day')) && d.activeElement === q, '#2249 qty 1,5: plural' + tag);
    type(''); check(/^(Tage|Days|days)$/i.test(txt('day')), '#2249 empty: plural' + tag);
    type('1'); check(/^(Tag|Day|day)$/i.test(txt('day')) && /^(Stunde|Hour|hour)$/i.test(txt('hour')), '#2249 qty 1 again: singular ' + txt('hour') + tag);
    const fl = txt('flat'); type('5'); check(fl === txt('flat') && fl !== '', '#2249 flat rate unchanged: ' + fl + tag);
    check(sel.value === 'day' && d.querySelector('.ofdits [data-k="qty"]') === q, '#2249 selection and field node unchanged' + tag);
    check(!errs.length, '#2249 no script errors ' + errs.join(' | ')); errs.splice(0);
    w.close();
  }
}

(async () => {
  await swCheck();
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  { const me = (await call('GET', '/api/state')).me; const org = await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
    await call('PATCH', '/api/settings', {workspace: `org:${org.id}`}); }
  const doc = await call('POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Campaign', items: [svc('Concept', 1, 800), svc('Insurance', 0, 5, 'percent')]});
  check(doc.status === 201, 'a quotation ' + doc.status);

  // ================= #2236: the unit of a percent position
  let w = await boot({user: 'alice', hash: `office/offers/${doc.id}`}), d = w.document;
  await until(() => d.querySelectorAll('.ofdeditor .ofdits .ofdit').length >= 2);
  let row = () => d.querySelectorAll('.ofdeditor .ofdits .ofdit')[1];
  check(row()?.querySelector('select[data-k="unit"]')?.value === 'percent' && !row().querySelector('[data-k="qty"]') && row().querySelector('.ofdpctof'), '#2236: the percent row has the unit choice (percent), no quantity');
  change(w, row().querySelector('select[data-k="unit"]'), 'day');
  const back = await until(async () => { const x = await call('GET', `/api/office/docs/${doc.id}`); return x.items?.[1]?.unit === 'day' ? x : null; });
  check(back && +back.items[1].qty === 1 && back.totals.net === 805, '#2236: back to Day: quantity 1, 800 + 1 x 5 ' + JSON.stringify(back && [back.items[1].qty, back.totals.net]));
  await until(() => row()?.querySelector('[data-k="qty"]'));
  check(row()?.querySelector('[data-k="qty"]')?.value === '1' && row().querySelector('select[data-k="unit"]')?.value === 'day', '#2236: the row shows quantity and unit again');
  change(w, row().querySelector('select[data-k="unit"]'), 'percent');
  await until(async () => (await call('GET', `/api/office/docs/${doc.id}`)).items?.[1]?.unit === 'percent');
  await until(() => row()?.querySelector('.ofdpctof'));
  check(row()?.querySelector('select[data-k="unit"]')?.value === 'percent', '#2236: and to percent again, the choice stays');

  check(!errs.length, 'no script errors ' + errs.join(' | ')); errs.splice(0);
  w.close();
  await unitWords('alice');

  // ================= #2239: rename an open part -> the title page line shows it
  const d2 = await call('POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Parts', items: [svc('Concept', 1, 800)]});
  const pa = await call('POST', `/api/office/docs/${d2.id}/parts`, {});
  w = await boot({user: 'alice', hash: `office/offers/${d2.id}`}); d = w.document;
  await until(() => d.querySelector('.ofdeditor .tppl [data-ofd="tp-open"]'));
  check(!d.querySelector('details[data-sec="parts"] .tpunused'), '#2239: the new part is on the title page');
  click(w, d.querySelector('.ofdeditor .tppl [data-ofd="tp-open"]'));
  await until(() => d.querySelector('.tphead .tptitle'));
  change(w, d.querySelector('.tphead .tptitle'), 'Module web');
  await until(async () => ((await call('GET', `/api/office/docs/${d2.id}`)).parts || []).find(p => p.id === pa.part.id)?.title === 'Module web');
  click(w, d.querySelector('[data-ofd="tp-back"]'));
  await until(() => d.querySelector('.tppl [data-k="title"]'));
  check(d.querySelector('.tppl [data-k="title"]')?.value === 'Module web', '#2239: the title page line shows the new name ' + d.querySelector('.tppl [data-k="title"]')?.value);
  // a title page edit saved after the part list changed keeps the line (parts_known)
  change(w, d.querySelector('.ofdits .ofdit:not(.tppl) [data-k="qty"]'), '2');
  const kept = await until(async () => { const x = await call('GET', `/api/office/docs/${d2.id}`); return +x.items?.[0]?.qty === 2 ? x : null; });
  check(kept && kept.items.some(i => i.kind === 'part' && i.ref_part_id === pa.part.id), '#2239: saving the title page keeps the part line');
  check(!errs.length, 'no script errors ' + errs.join(' | '));
  w.close();

  // ================= freelancer-matrix: office - the same editor as a person without an organisation
  const fr = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.status === 200 || fr.status === 201, 'freelancer created ' + fr.status);
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,office,clients'});
  check(!((await call('GET', '/api/state')).me?.workspaces || []).length, 'the freelancer is in no organisation');
  await unitWords('frida');

  console.log(`p2138_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
