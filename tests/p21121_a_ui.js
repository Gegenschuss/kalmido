// 2.112.1 UI tests of part A (#2058, own container, start.sh; P21121A_NOSTART=1: the container runs already). jsdom:
// - the file store: Select, two rows checked, the bar offers Download and "Move to the trash"; the trash takes both in ONE
//   request, ONE undo step brings both back
// - a folder's menu offers "Download as ZIP"
// - Scan: the button next to Upload opens the dialog; two pictures become two pages (turn, order), "Save as PDF" stores
//   one PDF in the open space; ONE undo step
// - the documents offer Scan as well
const {execFileSync} = require('child_process');
const path = require('path');
const zlib = require('zlib');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21121A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const upload = async (ck, name, text, form) => {
  const fd = new FormData(); fd.append('file', new Blob([text]), name);
  for (const [k, v] of Object.entries(form || {space: 'private'})) fd.append(k, v);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).items[0].id;
};
const isDeleted = async id => (await fetch(B + `api/files/nodes/${id}/content`, {headers: {...H, Cookie: CK}})).status === 404;  // the details stay readable for who may restore
// a plain PNG of one colour (no library)
const CRC = Array.from({length: 256}, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
const crc32 = b => { let c = 0xFFFFFFFF; for (const x of b) c = CRC[(c ^ x) & 0xFF] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
const chunk = (t, d) => { const len = Buffer.alloc(4), crc = Buffer.alloc(4), td = Buffer.concat([Buffer.from(t), d]); len.writeUInt32BE(d.length); crc.writeUInt32BE(crc32(td)); return Buffer.concat([len, td, crc]); };
const png = (w, h, rgb) => {
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2;
  const row = Buffer.concat([Buffer.from([0]), Buffer.from(Array(w).fill(rgb).flat())]);
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(Buffer.concat(Array(h).fill(row)))), chunk('IEND', Buffer.alloc(0))]);
};

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = await call('GET', '/api/state');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...new Set([...(st.settings?.features || '').split(','), 'files', 'docs'])].filter(Boolean).join(',')});
  const KISTE = (await call('POST', '/api/files/folders', {name: 'Kiste', space: 'private'})).id;
  const A1 = await upload(CK, 'eins.txt', 'erste Datei'), A2 = await upload(CK, 'zwei.txt', 'zweite Datei');

  // ================= Select: Download + Move to the trash, ONE undo step
  const w = await boot({user: 'alice', hash: 'ablage', ls: {abSpace: '"private"'}}), d = w.document;
  await until(() => d.querySelector(`.abrow[data-abid="${A1}"]`));
  d.querySelector('[data-absel="mode"]').click();
  await until(() => d.querySelector('.absel input'));
  for (const id of [A1, A2]) { const b = d.querySelector(`[data-absel="one"][data-id="${id}"]`); b.checked = true; b.dispatchEvent(new w.Event('change', {bubbles: true})); }
  const bar = await until(() => /2 selected/.test(d.querySelector('#ab-sbar')?.textContent || '') && d.querySelector('#ab-sbar'));  // 2.428.0 (#3581): the shared bar
  check(bar && bar.querySelector('[data-absel="dl"]') && !bar.querySelector('[data-absel="dl"]').disabled, 'the bar offers Download ' + (bar?.textContent || '').replace(/\s+/g, ' '));
  check(bar && bar.querySelector('[data-absel="trash"]') && !bar.querySelector('[data-absel="trash"]').disabled, 'the bar offers "Move to the trash"');
  check(bar && bar.querySelector('[data-absel="move"]'), 'the bar offers Move');  // 2.428.0 (#3581): Move is on the bar, "More" only for another workspace
  const h0 = w.eval('HIST.undo.length');
  bar?.querySelector('[data-absel="trash"]').click();
  check(await until(async () => await isDeleted(A1) && await isDeleted(A2), 60), 'both files are in the trash');
  check(await until(() => w.eval(`HIST.undo.length === ${h0 + 1} && /trash/.test(HIST.undo[HIST.undo.length - 1].label)`)), 'ONE undo step for both');
  check(await until(() => !d.querySelector(`.abrow[data-abid="${A1}"]`) && !d.querySelector('#ab-sbar')), 'the rows are gone, the selection ends');
  await w.eval(`histStep('undo')`);
  check(await until(async () => !(await isDeleted(A1)) && !(await isDeleted(A2)), 60), 'Undo brings both back');

  // ================= a folder's menu: Download as ZIP
  w.eval('ab_reload()');
  const row = await until(() => d.querySelector(`.abrow[data-abid="${KISTE}"]`));
  row?.querySelector('[data-ab="menu"]').click();
  await until(() => d.querySelector('#pop [role="menuitem"]'));
  const labels = [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim());
  check(labels.some(t => /Download as ZIP/.test(t)), 'the folder menu offers "Download as ZIP" ' + labels.join('|'));
  d.querySelector('#pop')?.remove();

  // ================= Scan: two pictures -> one PDF
  const scanBtn = d.querySelector('[data-ab="scan"]');
  check(scanBtn && scanBtn.previousElementSibling?.dataset.ab === 'upload', 'Scan sits next to Upload');
  scanBtn?.click();
  const md = await until(() => d.querySelector('.abscandlg'));
  check(md && md.querySelector('[data-abs="save"]').disabled, 'the dialog opens, "Save as PDF" waits for a page');
  const inp = md?.querySelector('#abs-file');
  check(inp && inp.getAttribute('capture') === 'environment' && /image/.test(inp.getAttribute('accept')), 'the camera input (capture=environment)');
  if (inp) {
    Object.defineProperty(inp, 'files', {configurable: true, value: [new w.File([png(30, 20, [200, 40, 40])], 'a.png', {type: 'image/png'}), new w.File([png(20, 30, [40, 40, 200])], 'b.png', {type: 'image/png'})]});
    inp.dispatchEvent(new w.Event('change', {bubbles: true}));
  }
  check(await until(() => md.querySelectorAll('.abscpg').length === 2), 'two pages in the dialog');
  md?.querySelector('[data-pg="0"] [data-abp="rot"]')?.click();
  md?.querySelector('[data-pg="0"] [data-abp="down"]')?.click();
  check(/Page 2/.test(md?.querySelector('[data-pg="1"]')?.textContent || '') && !md.querySelector('[data-abs="save"]').disabled, 'turned, moved down, ready to save');
  md.querySelector('#abs-name').value = 'UI Scan';
  const h1 = w.eval('HIST.undo.length');
  md?.querySelector('[data-abs="save"]').click();
  const pdf = await until(async () => ((await call('GET', '/api/files?space=private')).items || []).find(x => x.name === 'UI Scan.pdf'), 60);
  check(pdf && pdf.mime === 'application/pdf', 'the PDF is in My files ' + JSON.stringify(pdf || {}).slice(0, 200));
  check(await until(() => !d.querySelector('.abscandlg')), 'the dialog closes');
  check(await until(() => w.eval(`HIST.undo.length === ${h1 + 1} && HIST.undo[HIST.undo.length - 1].label === 'Scan'`)), 'ONE undo step "Scan"');
  if (pdf) {
    await w.eval(`histStep('undo')`);
    check(await until(async () => await isDeleted(pdf.id), 60), 'Undo moves the scan into the trash');
  }
  w.close();

  // ================= the documents offer Scan as well
  const w2 = await boot({user: 'alice', hash: 'docs'}), d2 = w2.document;
  check(await until(() => d2.querySelector('[data-dc="scan"]')), 'the documents have a Scan button');
  d2.querySelector('[data-dc="scan"]')?.click();
  check(await until(() => d2.querySelector('.abscandlg')), 'it opens the scan dialog');
  w2.close();

  console.log(`p21121_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
