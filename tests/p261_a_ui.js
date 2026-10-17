// 2.61.0 part A UI test, own container (start.sh with KALMIDO_CLAMD pointing at nothing: every upload is "unchecked"),
// Firefox (the real layout). #1818: the scan marks of stored files -- "Unchecked" on a task file, an image (overlay) and an
// Ablage file, "Locked: malware found" as a tile without a link (no download, no preview) that keeps its remove button;
// a tap on a mark shows its explanation (no hover needed); the server answers 403 for the locked file.
// Screenshots with P261A_SHOTS=<dir>.
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p261_a_ui', check, shots: 'P261A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: '-e KALMIDO_CLAMD=127.0.0.1:3399 -e KALMIDO_CLAMD_DOWN_S=0'}});
const [DBC, DBN] = fs.readFileSync(path.join(DATA, '.kalmido-db'), 'utf8').trim().split(/\s+/);
const sql = q => execFileSync('docker', ['exec', DBC, 'psql', '-U', 'kalmido', '-d', DBN, '-Atqc', q]).toString().trim();
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const upload = async (url, name, data, type, form = {}) => {
  const fd = new FormData(); for (const [k, v] of Object.entries(form)) fd.append(k, v);
  fd.append('file', new Blob([data], {type}), name);
  const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return r.status;
};
// a 24x24 purple PNG (no image library)
const CRC = Array.from({length: 256}, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
const crc = b => { let c = 0xffffffff; for (const x of b) c = CRC[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const chunk = (t, d) => { const len = Buffer.alloc(4), cr = Buffer.alloc(4), td = Buffer.concat([Buffer.from(t), d]); len.writeUInt32BE(d.length); cr.writeUInt32BE(crc(td)); return Buffer.concat([len, td, cr]); };
const PNG = (() => { const w = 24, ih = Buffer.alloc(13); ih.writeUInt32BE(w, 0); ih.writeUInt32BE(w, 4); ih[8] = 8; ih[9] = 2;
  const raw = Buffer.concat(Array.from({length: w}, () => Buffer.concat([Buffer.from([0]), Buffer.from(Array(w).fill([124, 58, 237]).flat())])));
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ih), chunk('IDAT', require('zlib').deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]); })();

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});  // the default modules (the file store is one)
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const L = (await call('POST', '/api/lists', {name: 'Scan'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Files to check', list_id: L})).id;
  check(await upload(`/api/tasks/${T}/attachments`, 'notes.txt', 'some notes\n', 'text/plain') === 200, 'upload notes.txt');
  check(await upload(`/api/tasks/${T}/attachments`, 'photo.png', PNG, 'image/png') === 200, 'upload photo.png');
  check(await upload(`/api/tasks/${T}/attachments`, 'invoice.pdf', '%PDF-1.4 bad\n', 'application/pdf') === 200, 'upload invoice.pdf');
  const AB = await upload('/api/files/upload', 'contract.txt', 'contract\n', 'text/plain', {space: 'private'});
  const BAD = +sql("SELECT id FROM attachments WHERE name='invoice.pdf'");
  sql(`UPDATE upload_scan SET state='infected', sig='Eicar-Test-Signature' WHERE kind='att' AND ref_id=${BAD}`);
  const NID = +sql("SELECT id FROM fs_nodes WHERE name='contract.txt'");
  sql(`UPDATE upload_scan SET state='infected', sig='Eicar-Test-Signature' WHERE kind='fs' AND ref_id=${NID}`);
  check(+sql('SELECT COUNT(*) FROM upload_scan') === 4 && AB >= 200 && AB < 300, `four uploads remembered (two unchecked, two locked): ${sql('SELECT kind, ref_id, state FROM upload_scan')} / Ablage upload ${AB}`);
  const dl = await fetch(B + `api/attachments/${BAD}`, {headers: {Cookie: CK}});
  check(dl.status === 403, 'the locked file: 403 ' + dl.status);

  const ffLogin = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(700); };
  const run = async (o, w, theme) => {
    const {cmd, ev, shot} = o, tag = `${w} ${theme}`;
    await cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: w, height: 900}});
    check(await ffLogin(o, theme) === 200, tag + ': login');
    await o.nav(B + '#l/' + L); await ready(ev, '.task');
    await ev(`(() => { openDetail(${T}); return 1; })()`); await ready(ev, '.atts .att');
    const d = await ev(`(() => { const q = s => [...document.querySelectorAll(s)];
      const tile = n => q('.atts .att').find(a => a.textContent.includes(n) || a.querySelector('img')?.alt === n);
      const notes = tile('notes.txt'), photo = tile('photo.png'), bad = tile('invoice.pdf');
      return {notes: notes?.querySelector('.scnmark')?.textContent || '', photo: photo?.querySelector('.scnover .scnmark')?.textContent || '',
        bad: bad?.querySelector('.scnmark.scnbad')?.textContent || '', badLink: !!bad?.querySelector('a[href]'), badLock: !!bad?.classList.contains('scnlock'),
        badDel: !!bad?.querySelector('[data-act="att-del"]'), h: photo ? Math.round(photo.querySelector('.scnmark').getBoundingClientRect().height) : 0}; })()`);
    const j = JSON.stringify(d);
    check(d.notes === 'Unchecked', `${tag}: #1818: "Unchecked" on the text file ` + j);
    check(d.photo === 'Unchecked', `${tag}: #1818: "Unchecked" over the image ` + j);
    check(d.bad.includes('Locked') && d.badLock && !d.badLink, `${tag}: #1818: the infected file is a locked tile without a link ` + j);
    check(d.badDel, `${tag}: #1818: the locked file keeps its remove button ` + j);
    await shot(`p261a-task-${w}-${theme}.png`);
    const t = await ev(`(() => { document.querySelector('.atts .att.scnlock .scnmark').click(); return new Promise(r => setTimeout(() => r(document.querySelector('#toast:not(.hidden)')?.textContent || ''), 300)); })()`);
    check(/virus scanner found Eicar-Test-Signature/.test(t), `${tag}: #1818: a tap on the mark explains it ` + t);
    const t2 = await ev(`(() => { const a = [...document.querySelectorAll('.atts .att')].find(x => x.textContent.includes('notes.txt')); const before = location.href; a.querySelector('.scnmark').click(); return new Promise(r => setTimeout(() => r({toast: document.querySelector('#toast:not(.hidden)')?.textContent || '', lb: !!document.querySelector('.lightbox'), same: location.href === before}), 300)); })()`);
    check(/not reachable/.test(t2.toast) && !t2.lb && t2.same, `${tag}: #1818: a tap on "Unchecked" explains it and opens nothing ` + JSON.stringify(t2));
    await shot(`p261a-toast-${w}-${theme}.png`);
    await o.nav(B + 'static/icon.svg'); await o.nav(B + '#ablage'); await ready(ev, '.abrow');
    const a = await ev(`(() => { const r = document.querySelector('.abrow[data-abid="${NID}"]'); return {mark: r?.querySelector('.scnmark.scnbad')?.textContent || ''}; })()`);
    check(a.mark.includes('Locked'), `${tag}: #1818: the Ablage row shows the lock ` + JSON.stringify(a));
    await shot(`p261a-ablage-${w}-${theme}.png`);
  };
  await firefox(async o => { await run(o, 1440, 'light'); await run(o, 1440, 'dark'); }, false);
  await firefox(async o => { await run(o, 390, 'light'); }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
