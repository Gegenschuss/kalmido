// 2.48.0 UI tests of part D (#1152, #1356; own container, start.sh with a fake Paperless-ngx inside it). jsdom:
// - documents settings: the section Paperless-ngx, connect (a wrong token shows the reason in place), the preview with the
//   mapping (a tag left out), the import in the background, the result line, following switched on = one undo step
// - document sheet: an agent's receipt suggestion with Accept; Accept sets the project; Undo brings the suggestion back
// - phone width: the section and the suggestion are usable
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore',
  // 2.48.0 (#1152): the token is always sealed with a key derived from KALMIDO_SECRET_KEY (review S2) -> the container needs one
  env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8098 -e KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8='}});
let CK;
const call = async (method, url, body, ck = CK, extra = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...extra}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 200 : 15000, step: 200});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

function textPdf(line) {  // a one-page PDF with a text layer, written by hand
  const stream = `BT /F1 12 Tf 60 740 Td (${line}) Tj ET`;
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return out;
}
const pdoc = (id, title, tags) => ({id, title, content: title + ' text', created: '2025-03-0' + (id % 9 + 1), correspondent: null, document_type: null, tags,
  archive_serial_number: null, original_file_name: `d${id}.pdf`, custom_fields: [], notes: [], file: textPdf(title)});
fs.copyFileSync(path.join(__dirname, 'fake_paperless.py'), path.join(DATA, 'fake_paperless.py'));
fs.writeFileSync(path.join(DATA, 'pl.json'), JSON.stringify({tags: [{id: 1, name: 'Keep', document_count: 1}, {id: 2, name: 'Drop', document_count: 1}],
  correspondents: [], document_types: [], custom_fields: [], documents: [pdoc(21, 'Letter one', [1]), pdoc(22, 'Letter two', [2])]}));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_paperless.py']);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});

  // ================= Paperless-ngx (2.87.9 #1936: in Settings > Integrations; the documents settings keep a jump there)
  const w = await boot({user: 'alice', hash: 'docs'}), d = w.document;
  await until(() => d.querySelector('[data-dc="settings"]'));
  d.querySelector('[data-dc="settings"]').click();
  await until(() => d.querySelector('.dc-smd .pl-slot [data-pl="goset"]'));
  check(!d.querySelector('.dc-smd #pl-url') && /Connect in the settings/.test(d.querySelector('.dc-smd [data-pl="goset"]')?.textContent || ''), '2.87.9 (#1936): the documents settings jump to the settings');
  d.querySelector('.dc-smd [data-pl="goset"]')?.click();
  await until(() => d.querySelector('.smodal .pl-slot #pl-url'));
  check(!d.querySelector('.dc-smd') && d.querySelector('.smodal [data-pane="integr"] .pl-slot'), '2.87.9 (#1936): Settings > Integrations has the section');
  const slot = () => d.querySelector('.smodal .pl-slot');
  check(/Paperless-ngx/.test(slot()?.textContent || '') && d.querySelector('#pl-url') && d.querySelector('#pl-tok'), 'settings: the section with address + token');
  d.querySelector('#pl-url').value = 'http://127.0.0.1:8098';
  d.querySelector('#pl-tok').value = 'wrong';
  d.querySelector('[data-pl="connect"]').click();
  await until(() => /refused/.test(slot()?.querySelector('.pl-err')?.textContent || ''));
  check(/refused the API token/.test(slot()?.querySelector('.pl-err')?.textContent || ''), 'a wrong token: the reason in place');
  d.querySelector('#pl-tok').value = 'pl-secret';
  d.querySelector('[data-pl="connect"]').click();
  await until(() => slot()?.querySelector('[data-pl="preview"]'));
  check(/127\.0\.0\.1:8098/.test(slot()?.querySelector('.pl-url')?.textContent || '') && !/pl-secret/.test(slot()?.innerHTML || ''), 'connected: the address, never the token');
  slot().querySelector('[data-pl="preview"]').click();
  const pm = await until(() => d.querySelector('.pl-pmd [data-plp="start"]') && d.querySelector('.pl-pmd'));
  check(pm && /2 documents in Paperless-ngx/.test(pm.textContent), 'the preview counts the documents');
  const rows = [...(pm?.querySelectorAll('.pl-map') || [])];
  check(rows.length === 2, 'one row per tag');
  const drop = rows.find(r => /Drop/.test(r.textContent));
  if (drop) { const s = drop.querySelector('select'); s.value = 'skip'; s.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(drop?.querySelector('input').disabled, 'leave out: the name field is off');
  pm?.querySelector('[data-plp="start"]').click();
  // 2.87.9 (#1940): the import first names its target (no organisation: the private space)
  await until(() => d.querySelector('.itc-dlg [data-cd="yes"]'));
  check(/2 documents into your private space/.test(d.querySelector('.itc-dlg')?.textContent || ''), '2.87.9 (#1940): the target named before the start');
  d.querySelector('.itc-dlg [data-cd="yes"]')?.click();
  await until(async () => (await call('GET', '/api/paperless?ws=private')).conn?.run?.state === 'idle' && (await call('GET', '/api/docs?ws=private')).docs?.length === 2, 150);
  const docs = (await call('GET', '/api/docs?ws=private')).docs || [];
  check(docs.length === 2, 'the import brought two documents');
  const two = docs.find(x => /Letter two/.test(x.name));
  check(two && !(two.tags || []).length, 'the left out tag did not come');
  await until(() => /Last import: 2 new/.test(slot()?.textContent || ''), 40);
  check(/Last import: 2 new/.test(slot()?.textContent || ''), 'the result line ' + (slot()?.textContent || '').slice(0, 300));
  const fol = slot().querySelector('[data-pl="follow"]');
  fol.checked = true; fol.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', '/api/paperless?ws=private')).conn?.follow === true);
  // 2.284.0 A (#3120): the step comes after the client has the server's answer - the server (polled above) can be first on a busy place
  await until(() => w.eval(`HIST.undo.length && /automatically/.test(HIST.undo[HIST.undo.length - 1].label)`), 40);
  check(w.eval(`HIST.undo.length && /automatically/.test(HIST.undo[HIST.undo.length - 1].label)`), 'following on = one undo step ' + w.eval(`HIST.undo[HIST.undo.length - 1]?.label`));
  await w.eval(`histStep('undo')`);
  await until(async () => (await call('GET', '/api/paperless?ws=private')).conn?.follow === false);
  check((await call('GET', '/api/paperless?ws=private')).conn?.follow === false, 'Undo switches following off again');
  w.close();

  // ================= a receipt suggestion in the document sheet
  const D = docs[0].id;
  const ag = await call('POST', '/api/admin/agents', {username: 'rcbot', display_name: 'Rcbot'});
  const P = (await call('POST', '/api/lists', {name: 'Fair 2026', kind: 'project', org_id: null})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: ag.id, role: 'edit'});
  await call('POST', `/api/files/nodes/${D}/shares`, {agent_id: ag.id, role: 'view'});
  const sg = await call('POST', `/api/v1/documents/${D}/receipt-suggestion`, {project_id: P, category: 'Travel', note: 'Fair hotel'}, null, {Authorization: 'Bearer ' + ag.token});
  check(sg.status === 201, 'setup: the agent suggests ' + JSON.stringify(sg).slice(0, 200));
  const v = await boot({user: 'alice', hash: `docs/${D}`}), e = v.document;
  const box = await until(() => e.querySelector('.rc-slot .rc-sug'), 80);
  check(box && /Rcbot/.test(box.textContent) && /Fair 2026/.test(box.textContent) && /Travel/.test(box.textContent), 'the sheet shows the suggestion with agent, project and category');
  box?.querySelector('[data-rc^="accept"]').click();
  await until(() => !e.querySelector('.rc-slot .rc-sug') && e.querySelector('#rc-proj')?.value === String(P));
  check(e.querySelector('#rc-proj')?.value === String(P) && e.querySelector('#rc-cat')?.value === 'Travel', 'Accept: project + category set');
  check(v.eval(`HIST.undo.length && /accepted/.test(HIST.undo[HIST.undo.length - 1].label)`), 'Accept = one undo step');
  await v.eval(`histStep('undo')`);
  await until(() => e.querySelector('.rc-slot .rc-sug'));
  check(e.querySelector('.rc-slot .rc-sug') && !e.querySelector('#rc-proj')?.value, 'Undo: the suggestion is open again, no project');
  v.close();

  // ================= phone width
  const m = await boot({user: 'alice', hash: `docs/${D}`, mobile: true}), f = m.document;
  const mb = await until(() => f.querySelector('.rc-slot .rc-sug [data-rc^="accept"]'), 80);
  check(mb, 'phone: the suggestion with its buttons');
  m.close();

  console.log(`p248_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
