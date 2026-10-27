// 2.240.0 D (#2886) UI test, own container (start.sh): the video sign-off asks before it loads a YouTube / Vimeo player. First the
// placeholder with the provider's name and "Load video" (no iframe in the DOM), after the click the iframe; with "Do not ask again"
// the setting video_ext_ok = 1 is saved and the next review view loads the player straight away. A person without an organisation
// (freelancer) sees the same question in a private video sign-off.
// freelancer-matrix: videos
// P2240D_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2240D_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

async function openReview(user, hash, title) {
  const w = await boot({user, hash}), d = w.document;
  const row = await until(() => [...d.querySelectorAll('#detail [data-vdr="open"]')].find(b => b.textContent.includes(title)));
  row?.click();
  return {w, d, dlg: await until(() => d.querySelector('.vdrdlg'))};
}

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,clients'});
  const L = await call('POST', '/api/lists', {name: 'Imagefilm', kind: 'project'});
  const T = await call('POST', '/api/tasks', {title: 'Rohschnitt', list_id: L.id});
  const R = await call('POST', '/api/videos', {task_id: T.id, url: 'https://www.youtube.com/watch?v=AbCdEfGhI-9', title: 'Film Gate'});
  check(L.id && T.id && R.id, 'a task with a YouTube review');
  check((await call('GET', '/api/state')).settings.video_ext_ok !== '1', 'video_ext_ok is off by default');

  // ================= first view: placeholder, no player; the click loads it
  let {w, d, dlg} = await openReview('alice', 't/' + T.id, 'Film Gate');
  check(dlg && dlg.querySelector('.vdrgate') && !dlg.querySelector('iframe'), 'placeholder first, no iframe in the DOM');
  check(/YouTube/.test(dlg.querySelector('.vdrgate')?.textContent || '') && dlg.querySelector('[data-vdr="gate"]'), 'the note names YouTube, button "Load video"');
  check(!/ytimg|img/.test(dlg.querySelector('.vdrgate')?.innerHTML.replace(/<svg[\s\S]*?<\/svg>/, '') || ''), 'no thumbnail from the provider');
  dlg.querySelector('[data-vdr="gate"]').click();
  const fr = await until(() => dlg.querySelector('.vdrplay iframe'));
  check(fr && /^https:\/\/www\.youtube-nocookie\.com\/embed\/AbCdEfGhI-9/.test(fr.getAttribute('src')), 'after the click the iframe of the player');
  check((await call('GET', '/api/state')).settings.video_ext_ok !== '1', 'without the box nothing is remembered');
  w.close();

  // ================= "Do not ask again" -> video_ext_ok = 1, the next view loads directly
  ({w, d, dlg} = await openReview('alice', 't/' + T.id, 'Film Gate'));
  check(dlg && dlg.querySelector('.vdrgate'), 'still asked on the next visit');
  dlg.querySelector('.vdrgate-ok').checked = true;
  dlg.querySelector('[data-vdr="gate"]').click();
  check(await until(async () => (await call('GET', '/api/state')).settings.video_ext_ok === '1'), 'the box saves video_ext_ok = 1');
  w.close();
  ({w, d, dlg} = await openReview('alice', 't/' + T.id, 'Film Gate'));
  check(dlg && dlg.querySelector('.vdrplay iframe') && !dlg.querySelector('.vdrgate'), 'with video_ext_ok = 1 the player loads straight away');
  w.close();

  // ================= switching it off again in the settings
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('data')`);
  const sw = await until(() => d.querySelector('#s-vext'));
  check(sw && sw.checked, 'the settings switch shows it on');
  sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true}));  // as p261_b_ui.js change()
  check(await until(async () => (await call('GET', '/api/state')).settings.video_ext_ok === '0'), 'the settings switch takes it back');
  w.close();

  // ================= 2.240.0 D2 (#2886): video_ext_ok does not cover a direct file from another host: always asked, no "Do not ask again"
  await call('PATCH', '/api/settings', {video_ext_ok: '1'});
  const R2 = await call('POST', '/api/videos', {task_id: T.id, url: 'https://cdn.example.com/film.mp4', title: 'Film Datei'});
  check(R2.id, 'a review with a direct file');
  ({w, d, dlg} = await openReview('alice', 't/' + T.id, 'Film Datei'));
  check(dlg && dlg.querySelector('.vdrgate') && !dlg.querySelector('video') && /cdn\.example\.com/.test(dlg.querySelector('.vdrgate').textContent),
    'a direct file asks even with video_ext_ok = 1');
  check(dlg && !dlg.querySelector('.vdrgate-ok'), 'no "Do not ask again" box for a direct file');
  w.close();

  // ================= a person without an organisation: same question at a private review
  const U = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,clients'}, FK);
  const FL = await call('POST', '/api/lists', {name: 'Privat', kind: 'project'}, FK);
  const FT = await call('POST', '/api/tasks', {title: 'Privater Schnitt', list_id: FL.id}, FK);
  const FR = await call('POST', '/api/videos', {task_id: FT.id, url: 'https://vimeo.com/123456789', title: 'Privat Gate'}, FK);
  check(U.id && FR.id, 'a private review of a person without an organisation ' + JSON.stringify(FR).slice(0, 120));
  ({w, d, dlg} = await openReview('frida', 't/' + FT.id, 'Privat Gate'));
  check(dlg && dlg.querySelector('.vdrgate') && !dlg.querySelector('iframe') && /Vimeo/.test(dlg.querySelector('.vdrgate').textContent), 'the freelancer is asked, too');
  w.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
