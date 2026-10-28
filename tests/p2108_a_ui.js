// 2.153.0 UI tests (#2179, own container, start.sh; P2108A_NOSTART=1: the container runs already). jsdom:
// - a person without an organisation: Documents > Settings > Custom fields, "New field" (a selection with options), the list
//   shows it; one undo step removes it again, redo brings it back
// - the document's sheet shows the fields of its workspace; a value typed in is saved, one undo step takes it back
// - no fields = nothing extra in the sheet
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2108A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const change = (w, el, v) => { if (el.type === 'checkbox') el.checked = v; else el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  CK = await login('frida');
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files', 'docs'])].filter(Boolean).join(',')});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  const fd = new FormData(); fd.append('ws', 'private'); fd.append('files', new Blob(['Vertrag Beispiel Nummer 12']), 'vertrag.txt');
  const DOC = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${DOC}`)).state), 300);

  const w = await boot({user: 'frida', hash: 'docs'}), d = w.document;
  await until(() => d.querySelector(`[data-dco="${DOC}"]`), 60);
  // ---- no fields yet: the sheet has none
  w.eval(`dc_open(${DOC})`);
  const md0 = await until(() => d.querySelector('.dc-md .dc-form'));
  check(md0 && !md0.querySelector('[data-dcf]'), 'no fields: nothing extra in the sheet');
  d.querySelector('.dc-md')?.remove();

  // ---- settings: the section, a new selection field
  w.eval('dc_settings()');
  const sm = await until(() => d.querySelector('.dc-smd .dc-fadd'));
  check(sm && /Custom fields/.test(d.querySelector('.dc-smd').textContent), 'settings: the section "Custom fields" for the own documents');
  d.querySelector('#dcf-name').value = 'Status';
  change(w, d.querySelector('#dcf-type'), 'select');
  check(!d.querySelector('.dcf-opts').hidden, 'a selection shows the options input');
  d.querySelector('#dcf-opts').value = 'Offen, Bezahlt';
  d.querySelector('[data-dcs="fadd"]').click();
  const li = await until(() => [...d.querySelectorAll('.dc-smd .dc-rule')].find(x => /Status/.test(x.textContent) && /Offen, Bezahlt/.test(x.textContent)));
  check(li, 'the new field in the list with its options');
  let defs = (await call('GET', '/api/docs/settings?ws=private')).fields || [];
  check(defs.length === 1 && defs[0].type === 'select', 'the server has the field');
  await w.eval(`histStep('undo')`);
  check(await until(async () => ((await call('GET', '/api/docs/settings?ws=private')).fields || []).length === 0), 'undo removes the new field');
  await w.eval(`histStep('redo')`);
  check(await until(async () => ((await call('GET', '/api/docs/settings?ws=private')).fields || []).length === 1), 'redo makes it again');
  await call('POST', '/api/docs/fields', {ws: 'private', name: 'Vertragsnummer', type: 'text'});
  d.querySelector('.dc-smd')?.remove();

  // ---- the sheet: both fields, a value saved, one undo step
  w.eval(`DC.set = null; dc_open(${DOC})`);
  const inp = await until(() => [...d.querySelectorAll('.dc-md [data-dcf]')].length === 2 && [...d.querySelectorAll('.dc-md .dc-cf')].find(x => /Vertragsnummer/.test(x.textContent))?.querySelector('input'));
  check(inp, 'the sheet shows the two fields');
  const sel = [...d.querySelectorAll('.dc-md .dc-cf')].find(x => /Status/.test(x.textContent))?.querySelector('select');
  check(sel && [...sel.options].map(o => o.textContent).join('|') === '|Offen|Bezahlt', 'the selection with its options ' + (sel ? [...sel.options].map(o => o.textContent).join('|') : ''));
  if (inp) change(w, inp, 'VN-2108');
  const val = async () => ((await call('GET', `/api/docs/${DOC}`)).custom_fields || []).find(x => x.name === 'Vertragsnummer')?.value;
  check(await until(async () => (await val()) === 'VN-2108'), 'the value is saved');
  await until(() => w.eval(`!!HIST.undo.length && /Edited/.test(HIST.undo[HIST.undo.length - 1].label)`));
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await val()) == null), 'one undo step takes the value back');
  w.close();

  console.log(`p2108_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
