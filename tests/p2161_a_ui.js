// 2.161.0 UI test, part A, own container (start.sh). Invented data only.
// jsdom:
// - #2594: "Edit organisation" (Admin > Organisation) has the own picture of Settings > Workspaces (icon buttons in the
//   symbol row, so the narrow dialog keeps its height - layout in p21382_b_ui): an admin of the
//   organisation uploads a picture (file -> crop -> POST /api/orgs/{id}/icon) and removes it again; the preview shows the
//   picture, the symbol field is emptied so Save keeps the picture, the emoji stays the fallback without a picture;
//   a server admin who is not an admin of the organisation sees a hint under the dialog instead (same routes, no new rights)
// P4: an organisation is managed by the server admin; a person without an organisation has no such dialog (no new route)
const {execFileSync} = require('child_process');
const path = require('path');
const zlib = require('zlib');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2161A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const typeIn = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
// a real 16x16 PNG (one colour), invented
const png = (() => {
  const crcT = Array.from({length: 256}, (_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
  const crc = b => { let c = 0xffffffff; for (const x of b) c = crcT[(c ^ x) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
  const chunk = (t, d) => { const l = Buffer.alloc(4); l.writeUInt32BE(d.length); const td = Buffer.concat([Buffer.from(t), d]); const c = Buffer.alloc(4); c.writeUInt32BE(crc(td)); return Buffer.concat([l, td, c]); };
  const ih = Buffer.alloc(13); ih.writeUInt32BE(16, 0); ih.writeUInt32BE(16, 4); ih[8] = 8; ih[9] = 2;
  const raw = Buffer.concat(Array.from({length: 16}, () => Buffer.concat([Buffer.from([0]), Buffer.from(Array(16).fill([120, 80, 200]).flat())])));
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk('IHDR', ih), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
})();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab'});
  const me = (await call('GET', '/api/state')).me.id;
  const BOB = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'}).then(j => j.id);
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me})).id;
  const p0 = await call('PATCH', `/api/admin/orgs/${ORG}`, {members: [me, BOB], admins: [me], icon: '⭐'});
  check(p0.http === 200, 'org prepared ' + p0.http);
  const OTHER = (await call('POST', '/api/admin/orgs', {name: 'Beta', admin_id: BOB})).id;
  await call('PATCH', `/api/admin/orgs/${OTHER}`, {members: [BOB], admins: [BOB]});
  const orgOf = async (id = ORG) => ((await call('GET', '/api/admin/orgs')).orgs || []).find(o => o.id === id);

  const w = await boot({user: 'alice', hash: 'inbox'}), d = w.document;
  await until(() => w.eval(`typeof orgModal === 'function'`), 40);
  // the file picker and the crop dialog are the browser's / tested in #1913: a chosen file comes back as a cropped PNG;
  // jsdom's FormData does not reach the server through the test bridge, so the upload is sent from Node with the same body
  let posted = 0;
  w.eval(`avCropModal = async () => new Blob([new Uint8Array(4)], {type: 'image/png'})`);
  w.HTMLInputElement.prototype.click = function () { if (this.type === 'file') { Object.defineProperty(this, 'files', {configurable: true, value: [{size: 4, name: 'x.png'}]}); this.dispatchEvent(new w.Event('change')); } };
  const f0 = w.fetch;
  w.fetch = (u, o = {}) => {
    if (o.method === 'POST' && /\/api\/orgs\/\d+\/icon$/.test(String(u))) {
      posted++;
      const fd = new FormData(); fd.append('file', new Blob([png], {type: 'image/png'}), 'icon.png');
      return fetch(new URL(String(u), B), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
    }
    return f0(u, o);
  };
  const open = async id => { d.querySelectorAll('.modal.ogmodal').forEach(x => x.remove()); await w.eval(`S.orgs = []; orgModal({id: ${id}}, () => {})`); return until(() => d.querySelector('.modal.ogmodal'), 40); };

  // ================= an admin of the organisation: upload, preview, Save keeps it, remove, emoji fallback
  let md = await open(ORG);
  check(!!md, '#2594: the dialog opens');
  const up = () => md.querySelector('#og-pic [data-ogpic="up"]'), rm = () => md.querySelector('#og-pic [data-ogpic="rm"]');
  check(up() && !rm(), '#2594: "Upload a picture…" shown, no "Remove" without a picture');
  check(/Upload a picture/.test(up()?.title || '') && up()?.closest('.row')?.querySelector('#og-icon'), '#2594: the buttons sit in the symbol row (title = text)');
  check(md.querySelector('#og-icon')?.value === '⭐', '#2594: the emoji stays in the symbol field');
  up().click();
  check(await until(() => rm(), 40), '#2594: after the upload "Remove the picture" appears');
  check(posted === 1, '#2594: one upload to /api/orgs/{id}/icon ' + posted);
  let o = await orgOf();
  check(o?.icon_url && !o.icon, '#2594: the organisation has the picture, no emoji ' + JSON.stringify(o && {icon: o.icon, u: !!o.icon_url}));
  check(md.querySelector('#og-icprev img'), '#2594: the preview shows the picture');
  check(md.querySelector('#og-icon')?.value === '', '#2594: the symbol field is emptied (the picture replaced the emoji)');
  check(!!md.querySelector('#og-name'), '#2594: the dialog stays open after the upload');
  md.querySelector('[data-m="save"]').click();
  await until(() => !d.querySelector('.modal.ogmodal'), 40);
  o = await orgOf();
  check(o?.icon_url, '#2594: Save afterwards keeps the picture');
  // reopened: the picture row shows Remove; typing an emoji previews it
  md = await open(ORG);
  check(rm() && md.querySelector('#og-icprev img'), '#2594: reopened with the picture and "Remove the picture"');
  rm().click();
  check(await until(() => !rm(), 40), '#2594: Remove takes the button away');
  o = await orgOf();
  check(o && !o.icon_url && !o.icon, '#2594: the picture is removed');
  check(!md.querySelector('#og-icprev img[src*="/icon"]'), '#2594: the preview shows the default again');
  typeIn(w, md.querySelector('#og-icon'), '🌲');
  md.querySelector('[data-m="save"]').click();
  await until(() => !d.querySelector('.modal.ogmodal'), 40);
  o = await orgOf();
  check(o?.icon === '🌲' && !o.icon_url, '#2594: without a picture the emoji is the symbol again ' + o?.icon);

  // ================= a server admin who does not administer the organisation: a hint, no buttons (the routes stay as they are)
  md = await open(OTHER);
  check(md && !md.querySelector('[data-ogpic]') && /Only an admin of the organisation can upload a picture/.test(md.querySelector('#og-pich')?.textContent || '') && md.querySelector('#og-icon')?.getAttribute('aria-describedby') === 'og-pich', '#2594: not an admin of the organisation: hint instead of the buttons');
  const deny = await fetch(B + `api/orgs/${OTHER}/icon`, {method: 'DELETE', headers: {...H, Cookie: CK}});
  check(deny.status === 404 || deny.status === 403, '#2594: the route still refuses a non-member ' + deny.status);
  // "New organisation" has no picture row (there is nothing to attach it to yet)
  d.querySelectorAll('.modal.ogmodal').forEach(x => x.remove());
  await w.eval(`orgModal(null, () => {})`);
  md = await until(() => d.querySelector('.modal.ogmodal'), 40);
  check(md && !md.querySelector('#og-pic') && !md.querySelector('#og-pich'), '#2594: "New organisation" has no picture buttons');

  console.log(`p2161_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
