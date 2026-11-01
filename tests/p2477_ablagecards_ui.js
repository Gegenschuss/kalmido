// kalmido-suite: fresh
// 2.477.0 (#3936) UI test: switching a folder of the file store between list and cards is at once -- the loaded entries are
// drawn again, the folder is not fetched from the server again (AB.seq counts the loads); a picture card shows the small
// preview (/thumb), never the original (/content). jsdom only. Invented names and pictures only.
// freelancer-matrix: files (alice has no organisation: her private workspace)
const {execFileSync} = require('child_process');
const path = require('path');
const zlib = require('zlib');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2477_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); let j = {}; try { j = await r.json(); } catch { /* no body */ } return {http: r.status, ...j}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
// a small grey PNG, hand-made
const crc = b => { let c, t = []; for (let n = 0; n < 256; n++) { c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1; t[n] = c >>> 0; } c = 0xFFFFFFFF; for (const x of b) c = t[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xFFFFFFFF) >>> 0; };
const chunk = (type, data) => { const len = Buffer.alloc(4); len.writeUInt32BE(data.length); const td = Buffer.concat([Buffer.from(type), data]); const cr = Buffer.alloc(4); cr.writeUInt32BE(crc(td)); return Buffer.concat([len, td, cr]); };
const png = (w, h) => { const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 2; const raw = Buffer.alloc((w * 3 + 1) * h, 128); for (let y = 0; y < h; y++) raw[y * (w * 3 + 1)] = 0; return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ihdr), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]); };
const up = async (parent, name, buf, type) => {
  const fd = new FormData(); fd.append('parent_id', String(parent)); fd.append('file', new Blob([buf], {type}), name);
  return ((await (await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json().catch(() => ({}))).items || [])[0]?.id;
};

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'files', 'docs'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats, workspace: 'private'});
  const FOLDER = (await call('POST', '/api/files/folders', {space: 'private', name: 'Holiday pictures'})).id;
  const PIC = await up(FOLDER, 'beach.png', png(40, 30), 'image/png');
  const TXT = await up(FOLDER, 'packing-list.txt', Buffer.from('Sun cream, hat'), 'text/plain');
  check(FOLDER && PIC && TXT, 'setup: a folder with a picture and a text file');

  const w = await boot({user: 'alice', hash: 'ablage/' + FOLDER}), d = w.document;
  check(await until(() => d.querySelector(`.abview .ablist [data-abid="${PIC}"]`) && !w.eval('AB.loading')), 'the folder: a list first');
  const seq0 = w.eval('AB.seq');
  d.querySelector('[data-abdv="cards"]')?.click();
  // at once: the cards stand right after the click (same task, no waiting for the server)
  check(d.querySelector('.abview .abcards'), 'Cards: drawn at once after the click');
  check(w.eval('AB.seq') === seq0, 'Cards: the folder was not loaded again');
  const img = d.querySelector('.abview .abcards .abcf img');
  check(img && /\/api\/files\/nodes\/\d+\/thumb\?v=\d+/.test(img.getAttribute('src') || ''), 'the picture card: the small preview (' + (img?.getAttribute('src') || '-') + ')');
  check(![...d.querySelectorAll('.abview .abcards img')].some(i => /\/content/.test(i.getAttribute('src') || '')), 'no card loads an original');
  check(await until(async () => JSON.parse((await call('GET', '/api/state')).settings.ab_cards || '[]').includes('n:' + FOLDER)), 'the choice is saved in the background');
  d.querySelector('[data-abdv="list"]')?.click();
  check(d.querySelector(`.abview .ablist [data-abid="${PIC}"]`) && !d.querySelector('.abview .abcards'), 'List: drawn at once after the click');
  check(w.eval('AB.seq') === seq0, 'List: the folder was not loaded again');
  // a preview that cannot be made: the card shows the picture icon, not a broken image
  d.querySelector('[data-abdv="cards"]')?.click();
  const im2 = d.querySelector('.abview .abcards .abcf img');
  im2?.dispatchEvent(new w.Event('error'));
  check(!d.querySelector('.abview .abcards .abcf img') && d.querySelector('.abview .abcards .abcf .dc-ph'), 'a failed preview: the icon instead');
  w.close();

  console.log(`p2477_ablagecards_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
