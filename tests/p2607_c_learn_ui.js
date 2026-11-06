// 2.607.0 C UI test (#4872): "Apply what was learned" in the documents (jsdom, own container). Invented names only.
// kalmido-suite:
// - the selection's "Edit" offers it; two chosen documents are sorted by a rule, the message names "2 documents sorted, 0
//   suggestions" with Undo; Undo in the message takes both back (ONE step)
// - "To review" has the button for every document there; the step is ONE undo step as well
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
const sender = async id => (await call('GET', `/api/docs/${id}`)).sender?.name || null;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: 'files,docs,collab'});
  await call('PUT', '/api/docs/settings', {ws: 'private', levels: {sender: 'rules', type: 'rules', tags: 'rules', folder: 'rules'}});
  const D1 = await docNew('power-a.txt', 'Stadtwerke Nord Abschlag');
  const D2 = await docNew('power-b.txt', 'Stadtwerke Nord Rechnung');
  const D3 = await docNew('other.txt', 'Gartenverein Beitrag');
  const r = await call('POST', '/api/docs/rules', {ws: 'private', kind: 'any', match: 'Stadtwerke', sender: 'Stadtwerke Nord', tags: ['Energy']});
  check(r.status === 201, 'setup: the rule');
  check(await sender(D1) === null && await sender(D2) === null, 'setup: no sender before');

  const v = await boot({user: 'alice', hash: 'docs'}), vd = v.document;
  await until(() => vd.querySelectorAll('.dc-card').length === 3, 80);
  // the selection: Edit > Apply what was learned
  v.eval(`DC.selOn = true; DC.sel = new Map([[${D1}, null], [${D2}, null]]); dc_draw()`);
  click(v, vd.querySelector('[data-dcsel="edit"]'));
  const mi = await until(() => [...vd.querySelectorAll('#pop [role="menuitem"]')].find(b => /Apply what was learned/.test(b.textContent)));
  check(mi, 'the bar: "Edit" offers "Apply what was learned"');
  mi?.click();
  const t = await until(() => /2 documents sorted, 0 suggestions/.test(vd.querySelector('#toast')?.textContent || '') && vd.querySelector('#toast'));
  check(t && /Undo/.test(t.textContent), 'the message: "2 documents sorted, 0 suggestions" with Undo ' + (vd.querySelector('#toast')?.textContent || ''));
  check(await until(async () => await sender(D1) === 'Stadtwerke Nord' && await sender(D2) === 'Stadtwerke Nord', 60), 'both sorted on the server');
  check(await sender(D3) === null, 'the third one (not chosen) stays');
  check(v.eval(`HIST.undo[HIST.undo.length - 1]?.label`) === 'Apply what was learned', 'ONE undo step');
  if (t) click(v, t.querySelector('button'));
  check(await until(async () => await sender(D1) === null && await sender(D2) === null, 60), 'Undo in the message: both back');
  v.eval(`dc_selEnd()`);

  // "To review": the button for every document there
  v.eval(`go('docs/review')`);
  const lb = await until(() => vd.querySelector('.dc-learnbar [data-dc="learnall"]'), 80);
  check(lb, '"To review" shows the button');
  if (lb) click(v, lb);
  check(await until(async () => await sender(D1) === 'Stadtwerke Nord' && await sender(D2) === 'Stadtwerke Nord', 60), 'To review: sorted');
  check(await until(() => /2 documents sorted/.test(vd.querySelector('#toast')?.textContent || '')), 'To review: the message ' + (vd.querySelector('#toast')?.textContent || ''));
  await v.eval(`histStep('undo')`);
  check(await until(async () => await sender(D1) === null && await sender(D2) === null, 60), 'To review: undo');
  v.close();

  console.log(`p2607_c_learn_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e.stack || e); process.exit(1); });
