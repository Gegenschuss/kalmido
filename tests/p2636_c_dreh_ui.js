// 2.636.0 part C UI test (#4565), own container (start.sh): the project type Shoot in the app.
// kalmido-suite: fresh
// - without Film & Video the "New list" dialog offers no Shoot card; with it the card is there (after the built-in types)
// - the board of a shoot is the storyboard: the bar with "Shot list (PDF)" (a link to /api/lists/<id>/shotlist.pdf), every card
//   with its picture tile (the first image file) or an empty frame; shoot.js is loaded on demand (lazyload.js)
// - another board (an agency project) has neither the bar nor the tiles
// P2636C_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2636C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
// a 2 x 2 PNG (red), for the picture of a shot
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAEElEQVR4nGM4oaEBRAwQCgAhLgRhHuBtwgAAAABJRU5ErkJggg==', 'base64');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['comments', 'fields']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,kanban,fields,files'});
  const AG = await call('POST', '/api/lists', {name: 'Agency board', ptype: 'agency', sections: true});
  await call('PATCH', '/api/lists/' + AG.id, {view: 'kanban'});
  await call('POST', '/api/tasks', {title: 'Agency card', list_id: AG.id});

  // ================= without Film & Video: no Shoot card
  let w = await boot({user: 'alice', hash: 'inbox'}), d = w.document;
  w.eval(`listModal(null, '', {kind: 'project'})`);
  check(await until(() => d.querySelector('.modal.lnew .ptcard')), 'the New list dialog with its type cards');
  check(!d.querySelector('.modal.lnew [data-pt="shoot"]'), 'no industry: no Shoot card');
  w.close();

  // ================= Film & Video: the card, the storyboard
  const ind = await call('PUT', '/api/industry', {industry: 'film'});
  check(ind.status === 200, 'Film & Video chosen ' + ind.status);
  const L = await call('POST', '/api/lists', {name: 'Promo shoot', ptype: 'shoot', sections: true});
  check(L.id > 0, 'a shoot ' + JSON.stringify(L).slice(0, 80));
  const st = await call('GET', '/api/state');
  const secs = st.sections.filter(s => s.list_id === L.id);
  const T1 = await call('POST', '/api/tasks', {title: 'Opening on the roof', list_id: L.id, section_id: secs[0].id});
  const T2 = await call('POST', '/api/tasks', {title: 'Interview CEO', list_id: L.id, section_id: secs[1].id});
  const fd = new FormData(); fd.append('file', new Blob([PNG], {type: 'image/png'}), 'frame.png');
  const up = await fetch(B + `api/tasks/${T1.id}/attachments`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  check(up.ok, 'a picture for the first shot ' + up.status);

  w = await boot({user: 'alice', hash: 'inbox'}); d = w.document;
  w.eval(`listModal(null, '', {kind: 'project'})`);
  check(await until(() => d.querySelector('.modal.lnew [data-pt="shoot"]')), 'Film & Video: the Shoot card');
  const cards = [...d.querySelectorAll('.modal.lnew .ptcard')].map(b => b.dataset.pt);
  check(cards.join(',').startsWith(',agency,software,private,shoot'), 'after the built-in types ' + cards.join(','));
  d.querySelector('.modal.lnew').remove();
  w.location.hash = 'l/' + L.id;
  check(await until(() => d.querySelector('#view .kanban.shtboard .shtpic')), 'the storyboard: picture tiles on the board (shoot.js loaded)');
  const bar = d.querySelector('#view .shtbar a[data-sht="pdf"]');
  check(bar && bar.getAttribute('href') === `/api/lists/${L.id}/shotlist.pdf` && /Shot list \(PDF\)/.test(bar.textContent), 'the bar: Shot list (PDF) ' + bar?.getAttribute('href'));
  const tile = id => d.querySelector(`#view .kcards [data-id="${id}"] .shtpic`) || [...d.querySelectorAll('#view .kcards .trow')].find(r => r.textContent.includes(id === T1.id ? 'Opening' : 'Interview'))?.querySelector('.shtpic');
  check(await until(() => tile(T1.id)?.querySelector('img')?.getAttribute('src')?.startsWith('/api/attachments/')), 'shot 1: its picture');
  check(tile(T2.id)?.classList.contains('none') && !tile(T2.id).querySelector('img'), 'shot 2: the empty frame');
  check([...d.querySelectorAll('#view .kcol .khead')].map(h => h.textContent).join('|').includes('Shooting day 1'), 'the columns are the shooting days');

  // ================= another board: nothing of it
  w.location.hash = 'l/' + AG.id;
  check(await until(() => d.querySelector('#view .kanban') && [...d.querySelectorAll('#view .kcards .trow')].some(r => r.textContent.includes('Agency card'))), 'the agency board');
  check(!d.querySelector('#view .shtbar') && !d.querySelector('#view .shtpic') && !d.querySelector('#view .shtboard'), 'agency board: no bar, no tiles');
  w.close();

  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
