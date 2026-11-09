// 2.783.0 B UI test (#4882): the title from the area's title pattern in the documents (jsdom, own container). Invented names only.
// kalmido-suite:
// - the document view: "Suggest title" beside the label Title; a press sets the pattern's title, Undo brings the typed one back
// - the selection's "Edit" offers "Set title from pattern": both chosen documents get the pattern's title, ONE undo step
// - Settings > Documents: "Title automatically" and the pattern field; a changed pattern is saved
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const docNew = async (name, text) => {
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob([text], {type: 'text/plain'}), name);
  const id = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 300);
  return id;
};
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const title = async id => (await call('GET', `/api/docs/${id}`)).title;
const PAT = 'Stadtwerke Nord Bill 12.03.2026';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'files,docs,collab'});
  await call('PUT', '/api/docs/settings', {ws: 'private', levels: {sender: 'rules', type: 'rules', tags: 'rules', folder: 'rules'}});
  const r = await call('POST', '/api/docs/rules', {ws: 'private', kind: 'any', match: 'Stadtwerke', sender: 'Stadtwerke Nord', type: 'Bill'});
  check(r.status === 201, 'setup: the rule');
  const D1 = await docNew('power-a.txt', 'Schreiben 12.03.2026\nStadtwerke Nord Abschlag');
  const D2 = await docNew('power-b.txt', 'Schreiben 12.03.2026\nStadtwerke Nord Jahresrechnung');
  check(await title(D1) === PAT, 'setup: the new document has the pattern\'s title ' + await title(D1));
  await call('PATCH', `/api/docs/${D1}`, {title: 'Strom Hand'});
  await call('PATCH', `/api/docs/${D2}`, {title: 'Strom Zwei'});

  // the document view: "Suggest title" + Undo
  const v = await boot({user: 'alice', hash: 'docs/' + D1}), vd = v.document;
  const ttl = await until(() => vd.querySelector('.dv-view #dc-name[data-dcp="title"]'), 80);
  check(ttl && ttl.value === 'Strom Hand', 'the view shows the typed title ' + ttl?.value);
  const sb = await until(() => vd.querySelector('.dv-view [data-dc="titlesug"]'));
  check(sb && sb.closest('.dc-f')?.contains(ttl), 'the button "Suggest title" in the title\'s row');
  if (sb) click(v, sb);
  check(await until(async () => await title(D1) === PAT, 60), 'the press sets the pattern\'s title on the server');
  check(await until(() => vd.querySelector('.dv-view #dc-name')?.value === PAT), 'the view shows it');
  check(/Title of .* suggested/.test(v.eval(`HIST.undo[HIST.undo.length - 1]?.label || ''`)), 'one undo step ' + v.eval(`HIST.undo[HIST.undo.length - 1]?.label`));
  await v.eval(`histStep('undo')`);
  check(await until(async () => await title(D1) === 'Strom Hand', 60), 'Undo: the typed title back');
  check((await call('GET', `/api/docs/${D1}`)).title_manual === true, 'Undo: set by hand again');
  v.close();

  // the selection: Edit > Set title from pattern, ONE undo step
  const w = await boot({user: 'alice', hash: 'docs'}), wd = w.document;
  await until(() => wd.querySelectorAll('.dc-card').length === 2, 80);
  w.eval(`ab_selEnd(); ab_selPick(${D1}); ab_selPick(${D2})`);
  click(w, wd.querySelector('#ab-sbar [data-absel="edit"]'));
  const mi = await until(() => [...wd.querySelectorAll('#pop [role="menuitem"]')].find(b => /Set title from pattern/.test(b.textContent)));
  check(mi, 'the bar: "Edit" offers "Set title from pattern"');
  mi?.click();
  check(await until(async () => await title(D1) === PAT && await title(D2) === PAT, 60), 'both get the pattern\'s title');
  const t = await until(() => /Title set from pattern/.test(wd.querySelector('#toast')?.textContent || '') && wd.querySelector('#toast'));
  check(t && /Undo/.test(t.textContent), 'the message with Undo ' + (wd.querySelector('#toast')?.textContent || ''));
  if (t) click(w, t.querySelector('button'));
  check(await until(async () => await title(D1) === 'Strom Hand' && await title(D2) === 'Strom Zwei', 60), 'Undo: both typed titles back');
  w.close();

  // Settings > Documents: the switch and the pattern
  const s = await boot({user: 'alice', hash: 'docs'}), sd = s.document;
  await until(() => s.eval('typeof dc_settings === "function"'), 60);
  (await until(() => sd.querySelector('#view [data-dc="settings"]')))?.click();  // the gear opens Settings > Documents
  const tp = await until(() => sd.querySelector('.smodal #s-dcs #dcs-tpat'), 80);
  check(tp && tp.value === '{Absender} {Typ} {Datum}' && sd.querySelector('#dcs-tauto')?.checked, 'the settings: the default pattern, on');
  if (tp) { tp.value = '{Typ} {Datum}'; tp.dispatchEvent(new s.Event('change', {bubbles: true})); }
  check(await until(async () => (await call('GET', '/api/docs/settings?ws=private')).title_pattern === '{Typ} {Datum}', 60), 'the changed pattern is saved');
  s.close();

  console.log(`p2783_b_doctitle_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
