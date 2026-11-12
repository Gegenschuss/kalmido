// 2.1002.0 C (#5490) UI test, own container (start.sh), jsdom: deleting a video sign-off is a step of the server
// kalmido-suite: fresh
// (core/undoweb.py, videos/vdkern.py undo_trash_reg) and the app shows it again after Undo.
// - the task panel lists the review; its menu "Delete" closes the view, the row leaves the section, the toast offers Undo
// - Undo in the toast takes the server's step back: the row is back in the task's section (histReloader 'videos'), the
//   review is out of the trash; the person's list "Recent steps" (GET /api/undo) shows the step as undone
// - Redo (Ctrl+Shift+Z path: histStep('redo')) puts it into the trash again, the row leaves the section again
// The account has no organisation (a person on her own, like the freelancer fixture).
// freelancer-matrix: videos
// P21002C_NOSTART=1 = the container is running.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21002C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,videos'});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'setup: alice has no organisation');
  const L = (await call('POST', '/api/lists', {name: 'Example film', kind: 'project', org_id: null})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Example task', list_id: L})).id;
  const V = (await call('POST', '/api/videos', {task_id: T, url: 'https://vimeo.com/123456789', title: 'Example cut'})).id;
  check(L && T && V, 'setup: a review at a task');

  const w = await boot({user: 'alice', hash: 't/' + T});
  const d = w.document;
  const row = () => d.querySelector(`#d-vdr [data-vdr="open"][data-id="${V}"]`);
  check(await until(() => row() && /Example cut/.test(row().textContent)), 'the task panel lists the review');
  row().click();
  const dlg = await until(() => d.querySelector('.vdrdlg'));
  check(dlg, 'the review view opens');
  dlg.querySelector('[data-vdr="menu"]').click();
  const del = await until(() => [...d.querySelectorAll('[role="menuitem"]')].find(b => /^Delete$/.test(b.textContent.trim())));
  check(del, 'its menu offers "Delete"');
  del.click();
  check(await until(() => !d.querySelector('.vdrdlg') && !row()), 'deleted: the view closed, the row left the section');
  const undo = await until(() => !d.querySelector('#toast').classList.contains('hidden') && /deleted/.test(d.querySelector('#toast').textContent)
    && d.querySelector('#toast button:not(.tx)'));
  check(undo, 'the toast names the delete and offers Undo: ' + d.querySelector('#toast').textContent);
  check((await call('GET', `/api/videos/${V}`)).status === 404, 'the review is in the trash');
  check(await until(() => w.eval('HIST.undo.length') > 0 && w.eval('histGids(HIST.undo[HIST.undo.length - 1]).length') > 0),
    'the app holds the server\'s step group of the delete (X-Kalmido-Undo-Gid)');
  undo.click();
  check(await until(() => row() && /Example cut/.test(row().textContent)), 'Undo: the row is back in the task\'s section');
  check((await call('GET', `/api/videos/${V}`)).status === 200, 'Undo: the review is out of the trash');
  const st = ((await call('GET', '/api/undo')).items || []).find(x => x.kind === 'video_review' && x.ref_id === V);
  check(st && st.redo === true && /Example cut/.test(st.label), 'Recent steps: the delete step is listed as undone: ' + JSON.stringify(st));
  await w.eval(`histStep('redo')`);
  check(await until(() => !row()), 'Redo: the row left the section again');
  check((await call('GET', `/api/videos/${V}`)).status === 404, 'Redo: the review is in the trash again');
  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
