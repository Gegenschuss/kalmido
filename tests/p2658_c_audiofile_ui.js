// 2.658.0 part C UI test (#5015), own container (start.sh): an audio file of the file store in the approval, on a phone.
// kalmido-suite: fresh
// - an MP3 uploaded at a task: the review view plays it in the app's own <audio> from its bytes route, no question first (no
//   third party), no image stage, the time line / timecode composer of a timed medium
// - the section's file picker lists audio files of the file store (VDR_FILE_RE), the menu offers "Download the file" (not
//   "Open the original link"), the client link section is there (audio may go to the customer)
// - a stored audio whose file left the file store says so instead of an empty player
// P2658CUI_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2658CUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const upload = async (url, fields, name, bytes, mime) => {
  const fd = new FormData();
  for (const [k, v] of Object.entries(fields)) fd.append(k, String(v));
  fd.append('file', new Blob([bytes], {type: mime}), name);
  const r = await fetch(B + url.replace(/^\//, ''), {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return {status: r.status, ...(await r.json().catch(() => ({})))};
};
const until = fn => require('./boot').until(fn, {timeout: 15000, step: 100});
const MP3 = Buffer.concat([Buffer.from('ID3\x04\x00\x00\x00\x00\x00\x00', 'latin1'), Buffer.from([0xff, 0xfb, 0x90, 0x64]), Buffer.alloc(2048, 7)]);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,clients,videos,files'});
  const L = await call('POST', '/api/lists', {name: 'Podcast Folge 7', ptype: 'agency'});
  const T = await call('POST', '/api/tasks', {title: 'Mischung', list_id: L.id});
  const R = await upload('/api/videos', {task_id: T.id, title: 'Mix'}, 'mix.mp3', MP3, 'audio/mpeg');
  const v1 = (R.versions || [])[0] || {};
  check(R.status === 200 && v1.provider === 'audio' && v1.file_id, 'an audio review by upload ' + R.status + ' ' + (R.error || ''));
  await call('POST', `/api/videos/${R.id}/comments`, {body: 'Hier knackt es', at_sec: 42});

  const w = await boot({user: 'alice', mobile: true, hash: 't/' + T.id}), d = w.document;
  const key = JSON.stringify('task_id:' + T.id);
  await until(() => w.eval('S.sel') === T.id && w.eval("typeof VDR === 'object'") && w.eval(`Array.isArray(VDR.by[${key}])`));
  check(w.eval("VDR_FILE_RE.test('audio/mpeg') && VDR_FILE_RE.test('audio/x-m4a') && !VDR_FILE_RE.test('text/html') && !VDR_FILE_RE.test('image/svg+xml')"),
    'the file picker lists audio files, not HTML / SVG');

  w.eval(`vdr_open(${R.id})`);
  await until(() => d.querySelector('.vdrdlg .vdrplay audio'));
  const au = d.querySelector('.vdrdlg .vdrplay audio');
  check(au.getAttribute('src') === `/api/videos/${R.id}/versions/${v1.id}/file`, 'the <audio> plays the bytes route ' + au.getAttribute('src'));
  check(!d.querySelector('.vdrdlg .vdrgate') && !d.querySelector('.vdrdlg .vdrstage'), 'no question first, no image stage');
  check(w.eval(`vdr_stored(VDR.cur.r.versions[0]) && !vdr_media(VDR.cur.r.versions[0])`), 'a stored audio: from the file store, not an image / PDF');
  await until(() => d.querySelector('.vdrdlg .vdrsig h4'));
  check(!!d.querySelector('.vdrdlg .vdrsig h4'), 'the client link section is there');
  const mb = d.querySelector('.vdrdlg [data-vdr="menu"]');
  if (mb) {
    mb.click();
    await until(() => /Download the file/.test(d.body.textContent));
    check(/Download the file/.test(d.body.textContent) && !/Open the original link/.test(d.body.textContent), 'the menu: "Download the file", no original link');
    d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  } else check(false, 'the review menu button');
  // the file left the file store: say so, no empty player
  check(/no longer in the file store/.test(w.eval(`vdr_playerHtml(Object.assign({}, VDR.cur.r.versions[0], {embed: null, file_id: null}), 'x')`)),
    'a stored audio without its file says so');

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
