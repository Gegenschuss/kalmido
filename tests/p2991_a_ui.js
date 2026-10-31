// 2.99.1 part A UI test (#1959), own container (start.sh): video sign-off at a task. The task panel has the section "Video
// sign-off" with "Add video link"; the dialog takes a direct file link (no video is loaded in the test browser), the review
// view opens with the player (<video>), typing pauses and keeps the player's time ("at 00:42"), Send stores the comment at
// that second, the mark sits on the time line at second / duration, a tap on the timecode seeks, done is one undo step, the
// section lists the review with its open comments; a project's overview and a client's card show their section.
// P2991A_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2991A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,clients'});
  const L = await call('POST', '/api/lists', {name: 'Imagefilm', kind: 'project'});
  const T = await call('POST', '/api/tasks', {title: 'Rohschnitt', list_id: L.id});
  check(L.id && T.id, 'a project list and a task');

  // ================= the task panel: section, "Add video link", the dialog
  let w = await boot({user: 'alice', hash: 't/' + T.id}), d = w.document;
  const add = await until(() => d.querySelector('#detail [data-vdr="new"]'));
  check(add && /Video sign-off/.test(d.querySelector('#d-vdr h5')?.textContent || ''), 'the section with "Add video link"');
  d.querySelector('#d-more')?.setAttribute('open', '');
  add?.click();
  const form = await until(() => d.querySelector('.vdrform'));
  check(form && /stores no videos/.test(form.textContent), 'the dialog says that Kalmido stores no videos');
  form.querySelector('#vdr-url').value = 'http://example.com/clip.mp4';
  form.querySelector('[type="submit"]').click();
  check(await until(() => !form.querySelector('.calerr').hidden && /https/.test(form.querySelector('.calerr').textContent)), 'http is refused with a hint');
  form.querySelector('#vdr-url').value = 'https://example.com/clip.mp4';
  form.querySelector('#vdr-ttl').value = 'Rohschnitt v1';
  form.querySelector('[type="submit"]').click();
  const dlg = await until(() => d.querySelector('.vdrdlg'));
  // 2.240.0 (#2886): a file from another host is asked for first (placeholder), the player comes after "Load video"
  check(dlg && dlg.querySelector('.vdrgate') && !dlg.querySelector('video'), 'the file player waits behind the placeholder');
  dlg.querySelector('[data-vdr="gate"]').click();
  check(dlg && dlg.querySelector('.vdrplay video')?.getAttribute('src') === 'https://example.com/clip.mp4' && /Rohschnitt v1/.test(dlg.querySelector('#vdr-h')?.textContent || ''),
    'the review view with the player of the file');
  const rv = (await call('GET', '/api/videos?task_id=' + T.id)).reviews || [];
  check(rv.length === 1 && rv[0].versions[0].provider === 'file', 'the review exists at the task');
  const RID = rv[0] && rv[0].id;

  // ================= a comment at the player's time
  w.eval('VDR.cur.ctl.dur = 120; VDR.cur.ctl.cur = 42.3; VDR.cur.ctl.pause = () => { window.__paused = 1; }');
  const ta = dlg.querySelector('#vdr-in');
  ta.focus(); ta.dispatchEvent(new w.FocusEvent('focusin', {bubbles: true}));
  check(w.__paused === 1 && /at 00:42/.test(dlg.querySelector('[data-vdr="at"]')?.textContent || ''), 'typing pauses the player and keeps its time');
  w.eval('VDR.cur.ctl.cur = 50');
  ta.value = 'Schnitt zu hart';
  dlg.querySelector('[data-vdr="send"]').click();
  const c1 = await until(async () => { const r = await call('GET', '/api/videos/' + RID); return (r.comments || [])[0]; });
  check(c1 && c1.at_sec === 42.3 && c1.body === 'Schnitt zu hart', 'the comment stored at the kept second ' + JSON.stringify(c1));
  const mk = await until(() => dlg.querySelector('.vdrtl .vdrmk'));
  check(mk && /left:\s*35\.25%/.test(mk.getAttribute('style') || '') && !dlg.querySelector('.vdrtl').hidden, 'the mark on the time line at 42.3 / 120 ' + (mk && mk.getAttribute('style')));
  const tc = dlg.querySelector('.vdrc [data-vdr="seek"]');
  check(tc && tc.textContent.trim() === '00:42', 'the comment shows its timecode');
  w.eval('window.__seek = null; VDR.cur.ctl.seek = s => { window.__seek = s; }');
  tc?.click();
  check(w.__seek === 42.3, 'a tap on the timecode seeks the player');
  // without time: the chip turns off
  dlg.querySelector('[data-vdr="at"]').click();
  dlg.querySelector('#vdr-in').value = 'Allgemein';
  dlg.querySelector('[data-vdr="send"]').click();
  const c2 = await until(async () => { const r = await call('GET', '/api/videos/' + RID); return (r.comments || []).find(x => x.body === 'Allgemein'); });
  check(c2 && c2.at_sec === null, 'a comment without time');
  // done = one undo step
  const done = await until(() => dlg.querySelector(`[data-cid="${c1 && c1.id}"] [data-vdr="done"]`));
  done?.click();
  check(await until(async () => (await call('GET', '/api/videos/' + RID)).comments.find(x => x.id === c1.id).done), 'done');
  // 2.99.1: the undo step is recorded after the answer (its toast) - wait for it, the server saw "done" earlier
  await until(() => /Marked as done/.test(d.querySelector('#toast')?.textContent || ''));
  await w.eval(`histStep('undo')`);
  check(await until(async () => !(await call('GET', '/api/videos/' + RID)).comments.find(x => x.id === c1.id).done), 'Undo: open again');
  // the section lists the review
  dlg.querySelector('[data-m="close"]').click();
  w.eval('renderDetail()');
  const row = await until(() => d.querySelector('#d-vdr [data-vdr="open"]'));
  check(row && /Rohschnitt v1/.test(row.textContent) && /v1/.test(row.textContent) && /open comment/.test(row.textContent), 'the section lists the review ' + (row && row.textContent.replace(/\s+/g, ' ')));
  w.close();

  // ================= a project's overview and a client's card
  const CL = await call('POST', '/api/clients', {name: 'Kunde Eins GmbH'});
  await call('POST', '/api/videos', {client_id: CL.id, url: 'https://vimeo.com/123456789', title: 'Kundenfilm'});
  w = await boot({user: 'alice', hash: 'client/' + CL.id}); d = w.document;
  check(await until(() => /Kundenfilm/.test(d.querySelector('.vdrcl')?.textContent || '')), 'the client card shows its video sign-offs '
    + (d.querySelector('#view')?.textContent || '').replace(/\s+/g, ' ').slice(0, 300) + ' ' + w.eval('JSON.stringify(Object.keys(VDR.by))'));
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
