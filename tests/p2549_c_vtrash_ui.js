// 2.549.0 C (#4536) UI test, own container (start.sh), jsdom: the trash view shows the video sign-offs in their trash.
// kalmido-suite: fresh
// - a review whose project was deleted for good shows in the section "Video sign-offs" with "Without a place" and the hint of
//   the trash period (the test server: the deletion runs are off, so the hint says the trash keeps; with them on a row counts down)
// - "Restore" asks for a project of its workspace; the chosen one gets it (GET /api/videos?list_id=), the row leaves the section
// - a review that still has its project is restored without a question
// The account has no organisation (a person on her own, like the freelancer fixture).
// freelancer-matrix: videos
// P2549C_NOSTART=1 = the container is running.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2549C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments'});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'setup: alice has no organisation');
  const LG = (await call('POST', '/api/lists', {name: 'Old film', kind: 'project', org_id: null})).id;
  const V1 = (await call('POST', '/api/videos', {list_id: LG, url: 'https://vimeo.com/123456789', title: 'Lost cut'})).id;
  await call('PATCH', `/api/lists/${LG}`, {archived: true});
  await call('DELETE', `/api/lists/${LG}`);
  check((await call('DELETE', `/api/trash/lists/${LG}`)).status === 200, 'setup: the project deleted for good');
  const LT = (await call('POST', '/api/lists', {name: 'New home', kind: 'project', org_id: null})).id;
  const V2 = (await call('POST', '/api/videos', {list_id: LT, url: 'https://vimeo.com/987654321', title: 'Kept cut'})).id;
  check((await call('DELETE', `/api/videos/${V2}`)).status === 200, 'setup: a review deleted at its project');

  const w = await boot({user: 'alice'});
  const d = w.document;
  w.location.hash = '#trash';
  const row = id => d.querySelector(`#view .vtrlist [data-vtr="${id}"]`);
  await until(() => w.eval('S.route.key') === 'trash' && row(V1) && row(V2));
  const t1 = row(V1)?.textContent || '', t2 = row(V2)?.textContent || '';
  check(/Lost cut/.test(t1) && /Without a place/.test(t1) && /v1/.test(t1), '#4536: the review without a place shows in the section: ' + t1);
  check(/Kept cut/.test(t2) && /New home/.test(t2), '#4536: the review at its project names the project: ' + t2);
  check(/Video sign-offs/.test(d.querySelector('#view .vtrlist .ghead')?.textContent || ''), '#4536: the section is called "Video sign-offs"');
  const note = d.querySelector('#view .vtrlist .otrnote')?.textContent || '';
  check(/stay in the trash until the deletion runs of the server are switched on/.test(note), '#4536: the hint of the trash period (runs off on the test server): ' + note);
  w.eval('S.trashPurge = true; VTR.purge = true; renderView()');
  await until(() => /Deleted for good in 30 days/.test(row(V1)?.textContent || ''));
  check(/Deleted for good in 30 days/.test(row(V1)?.textContent || '') && /deleted for good after 30 days/.test(d.querySelector('#view .vtrlist .otrnote')?.textContent || ''),
    '#4536: with the runs on: the days left and the period ' + (row(V1)?.textContent || ''));
  // restore without a place: the dialog asks for the project
  row(V1).querySelector('[data-vtra="restore"]').click();
  const sel = await until(() => d.querySelector('.cdlg #vtr-pl'));
  check(sel && [...sel.options].some(o => +o.value === LT) && ![...sel.options].some(o => +o.value === LG), '#4536: the dialog offers her projects, not the deleted one');
  sel.value = String(LT); sel.dispatchEvent(new w.Event('change', {bubbles: true}));
  d.querySelector('.cdlg [data-cd="yes"]').click();
  const at = await until(async () => { const j = await call('GET', `/api/videos?list_id=${LT}`); return (j.reviews || []).some(r => r.id === V1) && j; });
  check(at, '#4536: the review is at the chosen project now');
  await until(() => !row(V1));
  check(!row(V1) && row(V2), '#4536: the restored review left the section');
  // a review with its project: no question, back at its project
  row(V2).querySelector('[data-vtra="restore"]').click();
  const back = await until(async () => { const j = await call('GET', `/api/videos?list_id=${LT}`); return (j.reviews || []).some(r => r.id === V2) && j; });
  check(back && !d.querySelector('.cdlg #vtr-pl'), '#4536: a review with its project comes back there without a question');
  await until(() => !d.querySelector('#view .vtrlist'));
  check(!d.querySelector('#view .vtrlist'), '#4536: an empty video trash shows no section');
  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
