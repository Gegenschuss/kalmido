// 2.993.0 A UI test (#5650): the three logos on top of the call sheet, used as a person would. Own container (start.sh), Firefox
// kalmido-suite: fresh
// (desktop and phone width). Invented names only.
// - the dialog shows the logo row: production left (the office logo, the picture really loaded), client right (the photo of the
//   contact chosen, loaded), the agency's place in the middle empty with "Add logo"; the three places are equally wide
// - "Add logo" without an agency chosen: first the choice of the contact; chosen + a picture -> the agency's logo shows (loaded),
//   the contact has it as its photo; "Save" keeps the agency chosen
// - the office logo removed: its place stays empty, the agency and the client keep their places
// - at phone width the row stays inside the dialog
// P2993AUI_NOSTART=1 = the server already runs.
const path = require('path');
const zlib = require('zlib');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2993_a_cslogos_ui', check, shots: 'P2993A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2993AUI_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const FEAT = 'collab,comments,contacts,office,clients,workload,dispo';
const dstr = x => `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`;
// a real PNG of w x h (no library)
const CRC = (() => { const t = []; for (let n = 0; n < 256; n++) { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; t.push(c >>> 0); } return t; })();
const crc32 = b => { let c = 0xffffffff; for (const x of b) c = CRC[(c ^ x) & 0xff] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
const chunk = (t, d) => { const len = Buffer.alloc(4), crc = Buffer.alloc(4), td = Buffer.concat([Buffer.from(t), d]); len.writeUInt32BE(d.length); crc.writeUInt32BE(crc32(td)); return Buffer.concat([len, td, crc]); };
const png = (w, h, rgb) => {
  const ih = Buffer.alloc(13); ih.writeUInt32BE(w, 0); ih.writeUInt32BE(h, 4); ih[8] = 8; ih[9] = 2;
  const raw = Buffer.concat(Array.from({length: h}, () => Buffer.concat([Buffer.from([0]), Buffer.from(Array.from({length: w}, () => rgb).flat())])));
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', ih), chunk('IDAT', zlib.deflateSync(raw)), chunk('IEND', Buffer.alloc(0))]);
};
/** the state of the logo row of the open dialog: per place its box, the picture (loaded, naturalWidth) and the upload button */
const ROW = `(() => { const m = document.querySelector('.modal.csmd'); if (!m) return 'null';
  const R = e => { const r = e.getBoundingClientRect(); return {l: Math.round(r.left), r: Math.round(r.right), w: Math.round(r.width), t: Math.round(r.top)}; };
  const out = {}; for (const c of m.querySelectorAll('.cslogos .cslogo')) { const i = c.querySelector('img');
    out[c.dataset.logo] = {box: R(c), img: i ? {nw: i.complete ? i.naturalWidth : 0, ...R(i)} : null, add: !!c.querySelector('[data-cs="logo"]')}; }
  const card = m.querySelector('.card').getBoundingClientRect(); out.card = {l: Math.round(card.left), r: Math.round(card.right)};
  return JSON.stringify(out); })()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ind = await call('PUT', '/api/industry', {industry: 'film'});
  await call('PUT', '/api/office/settings', {company_fields: {name: 'Beispiel Film GmbH', city: 'Musterstadt', country: 'DE'}});
  const fd = new FormData(); fd.append('file', new Blob([png(200, 60, [20, 120, 200])], {type: 'image/png'}), 'logo.png');
  const lr = await fetch(B + 'api/office/logo', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const bk = await call('POST', '/api/books', {name: 'Kunden', org_id: null});
  const agy = await call('POST', '/api/contacts', {book_id: bk.id, kind: 'org', fn: 'Werbe Beispiel GmbH'});
  const knd = await call('POST', '/api/contacts', {book_id: bk.id, kind: 'org', fn: 'Kundenfirma Beispiel KG'});
  const kp = await call('PATCH', `/api/contacts/${knd.id}`, {photo: 'data:image/png;base64,' + png(80, 80, [40, 160, 40]).toString('base64')});
  const t = new Date(), D = dstr(new Date(t.getFullYear(), t.getMonth(), t.getDate() + 3));
  const me = (await call('GET', '/api/state')).me;
  const b = await call('POST', '/api/team/dispo/bookings', {title: 'Imagefilm', start: D + 'T07:00', end: D + 'T19:00', status: 'firm', resources: [{kind: 'user', id: me?.id}]});
  const job = b.bookings?.[0]?.job, org = (await call('GET', `/api/team/dispo?start=${D}&days=1`)).org_id;
  const sv = await call('PUT', `/api/team/dispo/callsheet/${job}?org=${org}`, {data: {client_contact: knd.id}});
  check(ind.status === 200 && lr.ok && agy.id && kp.status === 200 && b.status === 201 && sv.status === 200,
    `setup: Film & Video, the office logo, two contacts (the client with a photo), a shoot day, the client chosen ${lr.status} ${kp.status} ${b.status} ${sv.status}`);

  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(200); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  const open = async ev => {
    await ev(`(() => { document.querySelectorAll('.modal.csmd').forEach(m => m.remove()); cs_open(${JSON.stringify(job)}, ${org}); return 1; })()`);
    return ready(ev, `!!document.querySelector('.modal.csmd #cs-loc_name')`);
  };
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev);
    await nav(B + '#workload');
    check(await ready(ev, `typeof cs_open === 'function' && !!document.querySelector('#view')`), 'the app is up');

    // ================= the logo row: production left, agency empty with "Add logo", client right
    check(await open(ev), 'the call sheet dialog opens');
    check(await ready(ev, `(() => { const j = JSON.parse(${ROW}); return j.production?.img?.nw > 0 && j.client?.img?.nw > 0; })()`), 'the production\'s and the client\'s logo are loaded');
    let row = JSON.parse(await ev(ROW));
    check(row.production?.img?.nw > 0 && row.client?.img?.nw > 0 && !row.agency?.img && row.agency?.add, 'production and client show their logos, the agency\'s place is empty with "Add logo" ' + JSON.stringify(row));
    check(row.production && row.agency && row.client && row.production.box.l < row.agency.box.l && row.agency.box.l < row.client.box.l
      && Math.abs(row.production.box.w - row.agency.box.w) <= 1 && Math.abs(row.agency.box.w - row.client.box.w) <= 1, 'three places of one width in a row ' + JSON.stringify(row));
    check(Math.abs(row.production.img.l - row.production.box.l) <= 1 && Math.abs(row.client.img.r - row.client.box.r) <= 1, 'the production\'s logo on the left, the client\'s on the right');
    check(row.production.box.t < (await ev(`Math.round(document.querySelector('.modal.csmd h3').getBoundingClientRect().top)`)), 'the logos are on top, above the heading');
    await shot('p2993a-logos.png');
    const before = row;

    // ================= "Add logo" without an agency: the contact first, then the picture
    await ev(`(() => { document.querySelector('.modal.csmd .cslogo[data-logo="agency"] [data-cs="logo"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal #cs-logoct')`), '"Add logo" without an agency: the choice of the contact first');
    check(await ev(`[...document.querySelectorAll('#cs-logoct option')].some(o => /Werbe Beispiel GmbH/.test(o.textContent))`), 'the choice lists the agency contact');
    await ev(`(() => { const s = document.querySelector('#cs-logoct'); s.value = '${agy.id}'; document.querySelector('.modal [data-csl="ok"]').click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('#cs-logoct') && document.querySelector('.modal.csmd #cs-agency_contact').value === '${agy.id}'`), 'the agency is chosen in the call sheet');
    await ev(`(async () => { const cv = document.createElement('canvas'); cv.width = 240; cv.height = 80; const g = cv.getContext('2d'); g.fillStyle = '#c03030'; g.fillRect(0, 0, 240, 80);
      const blob = await new Promise(r => cv.toBlob(r, 'image/png')); const dt = new DataTransfer(); dt.items.add(new File([blob], 'agentur.png', {type: 'image/png'}));
      const i = document.querySelector('.modal.csmd #cs-logofile'); i.files = dt.files; i.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `(() => { const j = JSON.parse(${ROW}); return j.agency?.img?.nw > 0; })()`), 'the agency\'s logo shows (loaded) after the upload');
    const ag = await call('GET', `/api/contacts/${agy.id}`);
    check(/^data:image\/(png|jpeg);base64,/.test(ag.photo || ''), 'the logo is the contact\'s photo now');
    row = JSON.parse(await ev(ROW));
    check(row.agency.box.l === before.agency.box.l && row.client.box.l === before.client.box.l, 'the places did not move');
    await ev(`(() => { document.querySelector('.modal.csmd [data-cs="save"]').click(); return 1; })()`);
    let ok2 = false;
    for (let i = 0; i < 40 && !ok2; i++) { ok2 = (await call('GET', `/api/team/dispo/callsheet/${job}?org=${org}`)).callsheet?.data?.agency_contact === agy.id; if (!ok2) await sleep(200); }
    check(ok2, '"Save" keeps the agency chosen');
    await shot('p2993a-logos-three.png');

    // ================= the office logo removed: its place stays empty, the others keep theirs
    await ev(`fetch('/api/office/logo', {method: 'DELETE', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status)`);
    check(await open(ev), 'the dialog opened again');
    check(await ready(ev, `(() => { const j = JSON.parse(${ROW}); return j.agency?.img?.nw > 0 && j.client?.img?.nw > 0; })()`), 'agency and client logos loaded');
    row = JSON.parse(await ev(ROW));
    check(row.production && !row.production.img && row.production.box.w === before.production.box.w, 'no office logo: its place is empty, but there ' + JSON.stringify(row.production));
    check(row.agency.box.l === before.agency.box.l && row.client.box.l === before.client.box.l, 'agency and client keep their places ' + JSON.stringify(row));

    // ================= phone width: the row stays inside the dialog
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await sleep(300);
    row = JSON.parse(await ev(ROW));
    check(row.client.box.r <= row.card.r && row.production.box.l >= row.card.l && row.client.img?.r <= row.card.r, 'phone: the logo row inside the dialog ' + JSON.stringify(row));
    await shot('p2993a-logos-phone.png');
  });

  console.log(`p2993_a_cslogos_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
