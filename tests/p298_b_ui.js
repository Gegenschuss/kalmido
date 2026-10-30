// 2.98.0 part B UI test (#1954), own container (start.sh): questionnaires in the form dialog.
//  - jsdom: the dialog of a new form has the question editor; questions added (short text, choice with options, yes / no),
//    reordered by dragging the grip (pointer events) and with the up button, one deleted and brought back from the message;
//    the switches "one question per step" and "match the e-mail to a client" (new clients only while matching is on); saved:
//    the order, the options, required, the switches; opened again: shown as saved; the submissions dialog (empty)
//  - Firefox, phone (380 x 800, touch): the public page in steps -- only the first step is visible, Next / Back switch the
//    step (no script on the page), the progress shows, the targets are at least 44 px high; in the app the grip drags a
//    question with a finger (touch)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p298_b_ui', check, shots: 'P298B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P298B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const input = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const change = (w, el, v) => { if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const ptr = (w, el, type, y) => el.dispatchEvent(new w.MouseEvent(type, {bubbles: true, cancelable: true, clientY: y, button: 0}));
const FEAT = 'cal,comments,collab,agents,clients,workload,forms';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'collab']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  await call('PATCH', '/api/admin/settings', {public_links: true});
  const P = (await call('POST', '/api/lists', {name: 'Requests'})).id;

  // ================= jsdom: the question editor
  let w = await boot({user: 'alice', hash: `l/${P}`}), d = w.document;
  w.eval(`listModal(${P})`); await sleep(300);
  click(w, d.querySelector('.modal [data-act="forms-open"]')); await sleep(600);
  let md = [...d.querySelectorAll('.modal')].pop();
  click(w, md.querySelector('[data-fm="new"]')); await sleep(200);
  let ed = [...d.querySelectorAll('.modal')].pop();
  check(ed.querySelector('#fq-list') && ed.querySelector('#fq-kind') && ed.querySelector('#fq-step') && ed.querySelector('#fq-cm') && ed.querySelector('#fq-cn').disabled,
    'the dialog has the questions, the step switch and the client switches (new clients only while matching is on)');
  check([...ed.querySelector('#fq-kind').options].map(o => o.value).join(',') === 'short,long,choice,multi,date,number,file,yesno', 'eight kinds of question');
  input(w, ed.querySelector('#fm-title'), 'Intake');
  change(w, ed.querySelector('#fm-access'), 'public');
  const add = (kind, label) => { change(w, ed.querySelector('#fq-kind'), kind); click(w, ed.querySelector('[data-fq="add"]')); input(w, [...ed.querySelectorAll('.fqe-label')].pop(), label); };
  add('short', 'Company'); add('choice', 'Budget'); add('yesno', 'Agree?');
  const rows = () => [...ed.querySelectorAll('#fq-list .fqe')];
  const labels = () => rows().map(r => r.querySelector('.fqe-label').value).join('|');
  check(labels() === 'Company|Budget|Agree?' && rows()[1].querySelector('.fqe-opts') && !rows()[0].querySelector('.fqe-opts'), 'three questions, the choice has an options field');
  rows()[1].querySelector('.fqe-opts').value = 'Small\nLarge\n\n';
  rows()[0].querySelector('.fqe-req').checked = true;
  rows()[2].querySelector('.fqe-help').value = 'Our terms';
  // drag the last question by its grip to the top (jsdom has no layout: every row is at 0, a pointer above it = the top)
  const grip = rows()[2].querySelector('.fqe-grip');
  ptr(w, grip, 'pointerdown', 10); ptr(w, grip, 'pointermove', -5); ptr(w, grip, 'pointerup', -5);
  check(labels() === 'Agree?|Company|Budget' && !ed.querySelector('.fqe.dragging'), 'dragged by the grip: the last question at the top ' + labels());
  click(w, rows()[2].querySelector('[data-fq="up"]'));
  check(labels() === 'Agree?|Budget|Company', 'the up button moves a question one up (keyboard way) ' + labels());
  click(w, rows()[0].querySelector('[data-fq="del"]'));
  check(labels() === 'Budget|Company' && /removed/.test(d.querySelector('#toast')?.textContent || ''), 'deleted, with a message');
  click(w, d.querySelector('#toast button')); await sleep(100);
  check(labels() === 'Agree?|Budget|Company', 'Undo in the message brings it back at its place ' + labels());
  ed.querySelector('#fq-step').checked = true;
  ed.querySelector('#fq-cm').checked = true; change(w, ed.querySelector('#fq-cm'));
  check(!ed.querySelector('#fq-cn').disabled, 'matching on: the switch for new clients is free');
  click(w, ed.querySelector('[data-m="save"]'));
  let f = await until(async () => (await call('GET', `/api/lists/${P}/forms`)).forms?.[0]);
  const q = f?.questions || [];
  check(q.map(x => x.label).join('|') === 'Agree?|Budget|Company' && q[1].kind === 'choice' && q[1].options.join(',') === 'Small,Large'
    && q[2].required === true && q[0].help === 'Our terms' && f.one_per_step === true && f.client_match === true && f.client_new === false,
  'saved: order, options, required, help, steps, client matching ' + JSON.stringify(f).slice(0, 500));
  w.close();

  w = await boot({user: 'alice', hash: `l/${P}`}); d = w.document;
  w.eval(`listModal(${P})`); await sleep(300);
  click(w, d.querySelector('.modal [data-act="forms-open"]')); await sleep(600);
  md = [...d.querySelectorAll('.modal')].pop();
  click(w, md.querySelector(`[data-fid="${f.id}"] [data-fm="edit"]`)); await sleep(200);
  ed = [...d.querySelectorAll('.modal')].pop();
  check([...ed.querySelectorAll('.fqe-label')].map(x => x.value).join('|') === 'Agree?|Budget|Company' && ed.querySelector('#fq-step').checked
    && ed.querySelector('#fq-cm').checked && ed.querySelector('a[href$="' + f.url.split('/').pop() + '"]'), 'opened again: as saved, with a preview link');
  click(w, ed.querySelector('[data-fq="entries"]')); await sleep(500);
  const en = [...d.querySelectorAll('.modal')].pop();
  check(/Submissions/.test(en.textContent) && /Nothing sent yet/.test(en.textContent) && !en.querySelector('a[href$="entries.csv"]'), 'the submissions: none yet, no CSV');
  w.close();
  check(!errs.length, 'jsdom: no JS errors ' + errs.join(' | '));

  // ================= Firefox, a phone: the public page in steps, the grip with a finger
  const url = f.url.replace(/^https?:\/\/[^/]+\//, B);
  await firefox(async ({cmd, ev, nav, ctx, shot, drag}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 380, height: 800}});
    await nav(url); await sleep(500);
    const VIS = `JSON.stringify([...document.querySelectorAll('.fqs')].map(s => getComputedStyle(s).display !== 'none'))`;
    check(await ev(VIS) === '[true,false,false,false]', 'phone: only the first step is visible ' + await ev(VIS));
    check(await ev(`!document.querySelector('script') && !!document.querySelector('.fqs progress, .fqs .fqbar')`), 'no script, a progress bar');
    const hi = await ev(`Math.min(...[...document.querySelectorAll('.fqs.cur .fqo, .fqs.cur .fqnav .btn')].map(e => e.getBoundingClientRect().height))`);
    check(hi >= 44, 'phone: the answers and Next are at least 44 px high ' + hi);
    await shot('p298b-380-step1.png');
    await ev(`(() => { document.querySelector('.fqs.cur .fqnav a.btn:not(.sec)').click(); return 1; })()`); await sleep(300);
    check(await ev(VIS) === '[false,true,false,false]', 'Next: the second step ' + await ev(VIS));
    await ev(`(() => { document.querySelector('#fqs-2 .fqnav a.sec').click(); return 1; })()`); await sleep(300);
    check(await ev(VIS) === '[true,false,false,false]', 'Back: the first step again ' + await ev(VIS));
    await ev(`(() => { location.hash = '#fqs-4'; return 1; })()`); await sleep(300);
    check(await ev(`!!document.querySelector('#fqs-4 button[type=submit]') && getComputedStyle(document.querySelector('#fqs-4')).display !== 'none'`), 'the last step: the send button');
    await shot('p298b-380-last.png');
    // the app: drag the third question to the top with a finger
    await nav(B + 'static/icon.svg');
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + `#l/${P}`);
    for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300);
    await sleep(600);
    await ev(`(async () => { listModal(${P}); await new Promise(r => setTimeout(r, 300)); document.querySelector('.modal [data-act="forms-open"]').click(); await new Promise(r => setTimeout(r, 700));
      [...document.querySelectorAll('.modal')].pop().querySelector('[data-fm="edit"]').click(); await new Promise(r => setTimeout(r, 400)); return 1; })()`);
    const g = await ev(`(() => { const rs = [...document.querySelectorAll('#fq-list .fqe')]; rs[1].scrollIntoView({block: 'center'}); const a = rs[2].querySelector('.fqe-grip').getBoundingClientRect(), b = rs[0].getBoundingClientRect();
      return {x: a.x + a.width / 2, y: a.y + a.height / 2, top: b.y + 4, h: innerHeight}; })()`);
    await drag(g.x, g.y, 0, Math.max(4, g.top) - g.y, 'touch'); await sleep(300);
    const order = await ev(`[...document.querySelectorAll('#fq-list .fqe-label')].map(x => x.value).join('|')`);
    check(order === 'Company|Agree?|Budget', 'phone: a finger on the grip drags the question to the top ' + order + ' ' + JSON.stringify(g));
    await shot('p298b-380-drag.png');
  }, true);

  console.log(`p298_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
