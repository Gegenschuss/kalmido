// 2.61.0 UI tests (part B, #1819), own container (start.sh). jsdom:
// - Settings > Data > Photos: "Remove location data from photos" on by default; switched off = saved, one undo step back on
// - Settings > Workspaces: the organisation's switch -- its admin changes it (one undo step), a member sees it disabled
// - a photo document: "Taken on …" in the document's sheet, the date from the photo marked "automatic"
// Firefox 390 touch: the document sheet with the capture date fits the phone, screenshot.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p261_b_ui', check, shots: 'P261B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const change = (w, el, on) => { el.checked = on; el.dispatchEvent(new w.Event('change', {bubbles: true})); };

// a small photo with EXIF (camera, GPS, capture time), made with Pillow (tests/requirements.txt)
const PHOTO = Buffer.from(execFileSync('python3', ['-c', `
import base64, io, sys
from PIL import Image
e = Image.Exif(); e[0x010F] = "TestCam"; e.get_ifd(0x8769)[0x9003] = "2026:05:04 13:14:15"; e.get_ifd(0x8825)[1] = "N"
o = io.BytesIO(); Image.new("RGB", (64, 32), (200, 40, 40)).save(o, "JPEG", exif=e.tobytes()); sys.stdout.write(base64.b64encode(o.getvalue()).decode())
`]).toString(), 'base64');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const feats = ((await call('GET', '/api/state')).settings.features || '').split(',').filter(Boolean);
  if (!feats.includes('docs')) await call('PATCH', '/api/settings', {features: [...feats, 'docs'].join(',')});  // the area Documents
  await call('POST', '/api/users', {orgs: [1], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CB);
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  check(PHOTO.includes(Buffer.from('TestCam')), 'setup: the photo carries EXIF');

  // ================= Settings > Data > Photos
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('data')`); await until(() => d.querySelector('#s-pmeta'));
  const cb = d.querySelector('#s-pmeta');
  check(cb && cb.checked, '#1819: "Remove location data from photos" is on by default');
  check(/camera details and capture time/.test(d.querySelector('#s-pmeta')?.closest('.row')?.nextElementSibling?.textContent || ''), '#1819: the hint names camera details and capture time');
  change(w, cb, false);
  check(await until(async () => (await call('GET', '/api/state')).settings.photo_meta_strip === '0'), '#1819: switched off = saved');
  check(w.eval(`HIST.undo.length >= 1`), '#1819: one undo step');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', '/api/state')).settings.photo_meta_strip === '1'), '#1819: undo switches it on again');
  w.close();

  // ================= Settings > Workspaces: the organisation's switch
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal(lmOrgPaneOn() ? 'org' : 'account')`); await until(() => d.querySelector('.pmeta-row input'));
  const oc = d.querySelector('.pmeta-row input');
  check(oc && oc.checked && !oc.disabled, '#1819: the organisation admin sees the switch, on, changeable');
  change(w, oc, false);
  check(await until(async () => (await call('GET', '/api/orgs')).orgs.find(o => o.id === ORG)?.photo_meta_strip === false), '#1819: the admin switches it off');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', '/api/orgs')).orgs.find(o => o.id === ORG)?.photo_meta_strip === true), '#1819: one undo step: on again');
  w.close();
  w = await boot({user: 'bob'}); d = w.document;
  w.eval(`settingsModal(lmOrgPaneOn() ? 'org' : 'account')`); await until(() => d.querySelector('.pmeta-row input'));
  check(d.querySelector('.pmeta-row input')?.disabled && /Only an admin/.test(d.querySelector('.pmeta-row + .shint')?.textContent || ''), '#1819: a member sees it disabled, with the reason');
  w.close();

  // ================= a photo document: the capture date
  const fd = new FormData();
  fd.append('files', new Blob([PHOTO], {type: 'image/jpeg'}), 'receipt-photo.jpg');
  fd.append('ws', 'private');
  const D = (await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd})).json()).ids[0];
  const doc = await until(async () => { const x = await call('GET', `/api/docs/${D}`); return ['done', 'failed'].includes(x.state) ? x : null; }, 200);
  check(doc && doc.taken_at === '2026-05-04T13:14:15' && doc.date === '2026-05-04', '#1819: the document has the capture date ' + JSON.stringify(doc && [doc.taken_at, doc.date]));
  w = await boot({user: 'alice', hash: 'docs'}); d = w.document;
  await until(() => d.querySelector(`[data-dco="${D}"]`));
  d.querySelector(`[data-dco="${D}"]`)?.click();
  await until(() => d.querySelector('.dc-md #dc-date'));
  check(/Taken on .*13:14|Taken on .*1:14/.test(d.querySelector('.pmeta-taken')?.textContent || ''), '#1819: "Taken on …" in the sheet ' + (d.querySelector('.pmeta-taken')?.textContent || ''));
  check(d.querySelector('#dc-date')?.value === '2026-05-04' && d.querySelector('#dc-date')?.closest('.dc-f')?.querySelector('.dc-auto'), '#1819: the date from the photo, marked automatic');
  w.close();

  // ================= Firefox: the phone (390, touch)
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#docs'); await sleep(2500);
    await ev(`(() => { document.querySelector('[data-dco="${D}"]')?.click(); return 1; })()`); await sleep(1500);
    const g = await ev(`(() => { const t = document.querySelector('.pmeta-taken'); if (!t) return null; const r = t.getBoundingClientRect();
      return {left: r.left, right: r.right, wide: document.documentElement.scrollWidth <= 390}; })()`);
    check(g && g.left >= 0 && g.right <= 390 && g.wide, `${tag}: #1819 the capture date fits the phone ` + JSON.stringify(g));
    await ev(`(() => { document.querySelector('.pmeta-taken')?.scrollIntoView({block: 'center'}); return 1; })()`); await sleep(300);
    await shot('p261b-390-doc-taken.png');
    await o.nav(B + '#today'); await sleep(1500);
    await ev(`(() => { settingsModal('data'); return 1; })()`); await sleep(1200);
    await ev(`(() => { document.querySelector('#s-pmeta-h')?.scrollIntoView({block: 'start'}); return 1; })()`); await sleep(300);
    await shot('p261b-390-settings-photos.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
