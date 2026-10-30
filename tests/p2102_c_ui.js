// 2.102.0 part C UI test (#2201, #2208), own container (start.sh), jsdom with the app's own on-demand loading (boot lazy: true).
//  - #2208: the start loads neither polls.js nor formq.js (no script tag, no script error); "Find a date" in the calendar bar
//    loads polls.js and opens the list of polls, "Find a date" in a task opens ONE new poll about the task (the start point's
//    click lives in lazyload.js, polls.js has none of its own); the forms dialog of a list loads formq.js with it and shows
//    the question editor
//  - #2201: the form dialog of a saved form has "Link for a client" (the clients of the list's workspace): Copy link = the
//    form's link with ?k=<client>; a client's "…" menu has "Copy questionnaire link for this client" (formq.js loads on the
//    click, one open form = the link at once)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2102C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'collab,comments,events,cal,clients,office,forms';
const loaded = (d, f) => [...d.querySelectorAll('script[src*="/static/js/"]')].some(s => new RegExp(`/static/js/${f}\\.js`).test(s.getAttribute('src')));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('PATCH', '/api/admin/settings', {public_links: true});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const P = (await call('POST', '/api/lists', {name: 'Requests', org_id: ORG})).id;
  const T = (await call('POST', '/api/tasks', {list_id: P, title: 'Kick-off with Beta'})).id;
  const BETA = (await call('POST', '/api/clients', {name: 'Beta Example', org_id: ORG})).id;
  check(P > 0 && T > 0 && BETA > 0, 'setup: a list of the organisation, a task, a client');

  // ================= #2208: the start without polls.js / formq.js
  const e0 = errs.length;
  let w = await boot({user: 'alice', hash: 'cal', lazy: true}), d = w.document;
  const html = await (await fetch(B)).text(), sw = await (await fetch(B + 'sw.js')).text();
  check(!/static\/js\/(polls|formq)\.js/.test(html) && /const LAZY = \[[^\]]*'\/static\/js\/polls\.js',\s*'\/static\/js\/formq\.js'[^\]]*\]/s.test(sw),  // 2.139.0 (#2128): later modules follow (voice.js); 2.149.0: the list wraps between the two
    'no script tag for polls.js / formq.js, both in the service worker\'s LAZY list');
  check(!loaded(d, 'polls') && !loaded(d, 'formq'), 'the start loads neither polls.js nor formq.js');
  check(w.eval(`typeof tpo_on === 'function' && typeof tpo_list === 'function' && typeof tpo_forClient === 'function' && typeof fq_clientLink === 'function' && typeof fq_dialogHtml === 'undefined'`),
    'at start: the switch and the stand-ins, not the module');
  const fb = await until(() => d.querySelector('#view [data-act="tpo-list"]'));
  check(fb && /Find a date/.test(fb.textContent), 'the calendar bar has "Find a date"');
  click(w, fb);
  const ld = await until(() => d.querySelector('.tpo-dlg'));
  check(ld && /No polls yet/.test(ld.textContent) && loaded(d, 'polls') && d.querySelectorAll('.tpo-dlg').length === 1, 'the click loads polls.js and opens the list of polls');
  click(w, d.querySelector('.tpo-dlg [data-tpo="new"]'));
  check(await until(() => d.querySelector('.tpo-dlg #tpo-title')), 'the list works: a new poll');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  // a task's "Find a date": ONE dialog about the task (the click of the start point is in lazyload.js only)
  w.eval(`S.sel = ${T}`);
  await until(() => w.eval(`!!taskById(${T})`));
  const tb = d.createElement('button'); tb.dataset.act = 'tpo-task'; d.body.appendChild(tb);
  click(w, tb);
  const ti = await until(() => d.querySelector('.tpo-dlg #tpo-title'));
  await sleep(300);
  check(ti && ti.value === 'Kick-off with Beta' && d.querySelectorAll('.tpo-dlg').length === 1, 'a task: one new poll with the task\'s title');
  check(errs.length === e0, 'no script error ' + errs.slice(e0).join(' | '));
  w.close();

  // ================= #2208 + #2201: the forms dialog loads formq.js; the link for a client
  const FQ = await call('POST', `/api/lists/${P}/forms`, {title: 'Intake', access: 'public', questions: [{kind: 'short', label: 'Project'}]});
  check(FQ.id > 0, 'a questionnaire');
  w = await boot({user: 'alice', hash: `l/${P}`, lazy: true}); d = w.document;
  check(!loaded(d, 'formq'), 'the list view: formq.js not loaded');
  w.eval(`listModal(${P})`); await sleep(300);
  click(w, d.querySelector('.modal [data-act="forms-open"]'));
  const fm = await until(() => d.querySelector('.modal [data-fm="edit"]'));
  check(fm && loaded(d, 'formq'), 'the forms dialog loads formq.js');
  click(w, fm);
  const ed = await until(() => [...d.querySelectorAll('.modal')].find(m => m.querySelector('#fq-list')));
  check(ed && ed.querySelectorAll('#fq-list .fqe').length === 1, 'the form dialog shows the question editor');
  const sel = ed?.querySelector('#fq-ckc');
  check(sel && [...sel.options].some(o => +o.value === BETA && /Beta Example/.test(o.textContent)) && /Link for a client/.test(ed.textContent), 'the form dialog: "Link for a client" with the workspace\'s clients');
  if (sel) sel.value = String(BETA);
  click(w, ed?.querySelector('[data-fq="cklink"]'));
  const t1 = await until(() => { const x = d.querySelector('#toast')?.textContent || ''; return /\?k=/.test(x) && x; });
  check(t1 && t1.includes(FQ.url + '?k=' + BETA + '.'), 'Copy link: the form\'s link with ?k=<client> (without a clipboard: shown in the message) ' + t1);
  check(errs.length === e0, 'no script error ' + errs.slice(e0).join(' | '));
  w.close();

  // ================= #2201: the client's "…" menu
  w = await boot({user: 'alice', hash: `client/${BETA}`, lazy: true}); d = w.document;
  const cm = await until(() => d.querySelector('#view [data-mscl="cmenu"]'));
  check(cm && !loaded(d, 'formq'), 'the client page: formq.js not loaded');
  click(w, cm);
  const it = await until(() => [...d.querySelectorAll('[role="menuitem"]')].find(b => /Copy questionnaire link for this client/.test(b.textContent)));
  check(it, 'the client menu has "Copy questionnaire link for this client"');
  click(w, it);
  const t2 = await until(() => { const x = d.querySelector('#toast')?.textContent || ''; return /\?k=/.test(x) && x; });
  check(t2 && t2.includes(FQ.url + '?k=' + BETA + '.') && loaded(d, 'formq'), 'one open form: its link for the client at once (formq.js loaded on the click) ' + t2);
  check(errs.length === e0, 'no script error ' + errs.slice(e0).join(' | '));
  w.close();

  console.log(`p2102_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
