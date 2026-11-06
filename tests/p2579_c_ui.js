// kalmido-suite: fresh
// 2.579.0 UI tests, part C (#4802): saved views of the documents search (static/js/docviews.js). Own container (start.sh).
// Invented names and generated texts only. jsdom:
// - "Save view" in the documents' bar keeps the search under a name, #docs/v/<id> opens it; leaving it empties the search
// - the sidebar lists the view under To review with its number of hits; a changed search offers "Update view"
// - the view's menu: rename, take over, favourite, show on Today, delete (with Undo); "share with everyone" only for an admin of
//   the organisation the view searches (a member's own view has none)
// - favourite: a tile for the view; Today: a block with the first hits and the number
// Firefox at 390 px: the bar with the open view stays inside the screen (no sideways scrolling), screenshot.
// freelancer-matrix: n/a - nur Oberfläche (die Person ohne Organisation prüft p2579_c_api_test.py)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2579_c_ui', check, shots: 'P2579C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const docNew = async (name, text, ws = 'private', ck = CK) => {
  const fd = new FormData(); fd.append('ws', ws); fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  const id = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd})).json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`, null, ck)).state), 300);
  return id;
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'files,docs,collab,comments', workspace: 'private'});
  const ORG = (await call('GET', '/api/state')).me.workspaces?.[0]?.id;
  check(ORG, 'setup: the organisation');
  const bob = await call('POST', '/api/users', {orgs: [{id: ORG, role: 'member'}], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const D1 = await docNew('koala-1.txt', 'Rechnung Koala Eukalyptus');
  await docNew('emu-1.txt', 'Brief Emu Steppe');

  // ================= jsdom: save, open, sidebar, menu, favourite, Today, delete + undo
  let w = await boot({user: 'alice', hash: 'docs'}), d = w.document;
  await until(() => w.eval(`typeof DC !== 'undefined' && DC.total === 2 && typeof dcv_barHtml === 'function'`), 100);
  const type = q => { const qi = d.querySelector('#dc-q'); qi.value = q; qi.dispatchEvent(new w.Event('input', {bubbles: true})); };  // as a person types (docs.js: 300 ms later the list loads)
  type('Koala');
  await until(() => w.eval(`DC.total === 1 && !DC.loading`));
  const save = await until(() => d.querySelector('[data-dcv="save"]'));
  check(save, 'the documents\' bar offers "Save view"');
  w.prompt = () => 'Koala docs';
  click(w, save);
  const VID = await until(() => w.eval(`(DCV.items || []).find(v => v.title === 'Koala docs')?.id`), 100);
  check(VID, 'saved: the view is there');
  check(await until(() => w.location.hash === '#docs/v/' + VID), 'the saved view opens (#docs/v/<id>)');
  const st = () => w.eval(`JSON.stringify({q: DC.q, total: DC.total, loading: DC.loading, dv: DC.dv, route: S.route, applied: DCV.applied, now: typeof dc_params === 'function' ? dcv_queryNow() : '', hash: location.hash})`);
  const v0 = w.eval(`dcv_get(${VID})`);
  check(v0 && v0.query === 'q=Koala&area=private' && v0.ws === 'private' && v0.count === 1, 'it keeps the search and counts its hits ' + JSON.stringify(v0));
  const side = await until(() => d.querySelector(`#side [data-sbbpart="docs-view"][data-dcvid="${VID}"]`), 60);
  check(side && side.textContent.includes('Koala docs') && side.querySelector('.c')?.textContent === '1', 'the sidebar: the view with its number ' + side?.outerHTML?.slice(0, 200));
  check(side && side.getAttribute('aria-current') === 'page' && !d.querySelector('#side [data-sbbpart="docs"]')?.classList.contains('on'), 'the open view is marked, not "Documents"');
  check(d.querySelector('.dcv-name')?.textContent.includes('Koala docs') && !d.querySelector('[data-dcv="update"]'), 'the bar names the open view, nothing changed yet');
  // leaving the view empties the search, the row brings it back
  w.location.hash = 'docs';
  // (Documents itself brings back its own last search text when one comes back: viewmem.js, #3439)
  check(await until(() => w.eval(`DC.dv === null && DCV.applied === null && !DC.vsort && !DC.f.review && !DC.loading`)), 'back to Documents: the view is left (its sort and filters go) ' + st());
  click(w, d.querySelector(`#side [data-dcvid="${VID}"]`));
  check(await until(() => w.eval(`DC.q === 'Koala' && DC.total === 1 && !DC.loading`)), 'the sidebar row applies the view again');
  // a changed search: "Update view" takes it over
  type('Emu');
  const upd = await until(() => !w.eval('DC.loading') && d.querySelector('[data-dcv="update"]'));
  check(upd && d.querySelector('.dcv-dirty'), 'a changed search: marked, "Update view" offered ' + st());
  click(w, upd);
  check(await until(() => w.eval(`dcv_get(${VID})?.query === 'q=Emu&area=private'`)), 'updated: the view keeps the new search');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', `/api/obj/docview/${VID}`)).query === 'q=Koala&area=private'), 'undo: the old search again');
  // the menu
  const labels = w.eval(`dcv_menuItems(dcv_get(${VID})).filter(x => x !== '-').map(x => x.label)`);
  check(['Rename…', 'Take over the current filters', 'Add to favourites', 'Show on Today', 'Delete view'].every(x => labels.includes(x)) && !labels.includes('Share with everyone of the organisation'),
    'the menu of a private view (no sharing with an organisation) ' + JSON.stringify(labels));
  w.prompt = () => 'Koala invoices';
  w.eval(`dcv_rename(dcv_get(${VID}))`);
  check(await until(() => d.querySelector(`#side [data-dcvid="${VID}"]`)?.textContent.includes('Koala invoices')), 'renamed: the sidebar follows');
  // favourite + Today
  w.eval(`fv2_set('r:docview:${VID}', true)`);
  check(await until(async () => ((await call('GET', '/api/favorites/targets')).items || {})['r:docview:' + VID]?.to === 'docs/v/' + VID), 'a favourite of the view, resolved by the server');
  w.eval(`dcv_todaySet(${VID}, true)`);
  check(await until(async () => (await call('GET', '/api/state')).settings.dv_today === String(VID)), 'Show on Today: stored');
  w.location.hash = 'today';
  const card = await until(() => d.querySelector(`#view .dcv-today[aria-labelledby="dcvh-${VID}"] .dwl a[href="#docs/${D1}"]`) && d.querySelector(`#view .dcv-today`), 100);
  check(card && card.querySelector('.dcn')?.textContent === '1' && card.textContent.includes('Koala invoices') && card.querySelector(`a[href="#docs/v/${VID}"]`), 'Today: the block with its hit, the number and "Show all"');
  // delete + undo
  w.location.hash = 'docs/v/' + VID;
  await until(() => w.eval(`DC.dv === ${VID}`));
  await w.eval(`dcv_delete(dcv_get(${VID}))`);
  check(await until(() => !d.querySelector(`#side [data-dcvid="${VID}"]`) && w.location.hash === '#docs'), 'deleted: gone from the sidebar, back to Documents');
  check((await call('GET', '/api/state')).settings.dv_today === '', 'deleted: off Today too');
  await w.eval(`histStep('undo')`);
  check(await until(() => d.querySelector(`#side [data-dcvid="${VID}"]`)), 'undo: the view is back');
  // an organisation's view: the admin may share it, a member's own view has no such entry
  const OV = (await call('POST', '/api/obj/docview', {title: 'Studio receipts', query: 'q=Koala', ws: 'org:' + ORG})).id;
  await w.eval('dcv_load(true)');
  check(w.eval(`dcv_menuItems((DCV.items || []).find(v => v.id === ${OV}) || {id: ${OV}, ws: 'org:${ORG}', role: 'manage', title: 'x'}).some(x => x.label === 'Share with everyone of the organisation')`),
    'the admin\'s view of the organisation: "Share with everyone" offered');
  w.close();
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'files,docs,collab,comments'}, BK);
  const BV = (await call('POST', '/api/obj/docview', {title: 'Bob view', query: 'q=Koala', ws: 'org:' + ORG}, BK)).id;
  w = await boot({user: 'bob', hash: 'docs'}); d = w.document;
  await until(() => w.eval(`typeof dcv_menuItems === 'function'`), 100);
  await w.eval('dcv_load(true)');
  const bl = w.eval(`dcv_menuItems((DCV.items || []).find(v => v.id === ${BV}) || {id: ${BV}, ws: 'org:${ORG}', role: 'manage', title: 'x'}).map(x => x.label)`);
  check(bl.includes('Delete view') && !bl.includes('Share with everyone of the organisation'), 'a member\'s own view: no "Share with everyone" ' + JSON.stringify(bl));
  check(bob.http === 200 || bob.http === 201, 'setup: bob');
  w.close();

  // ================= Firefox 390 px: the bar with the open view stays on the screen
  await firefox(async o => {
    const {cmd, ev, ctx, shot, until: u, nav} = o;
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, '390: login');
    await nav(B + '#docs/v/' + VID);
    const name = await u(`(() => { const b = document.querySelector('.dcv-name'); return b && b.getBoundingClientRect().width > 0 ? 1 : 0; })()`, {timeout: 20000});
    check(name, '390: the open view in the bar');
    const fit = await ev(`(() => { const b = document.querySelector('.dcv-name').getBoundingClientRect(); return {r: Math.round(b.right), sw: document.documentElement.scrollWidth, vw: window.innerWidth}; })()`);
    check(fit && fit.r <= fit.vw && fit.sw <= fit.vw, '390: the view\'s button inside the screen, no sideways scrolling ' + JSON.stringify(fit));
    await shot('p2579c-390-view.png');
  }, true);

  console.log(`p2579_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
