// 2.106.0 UI tests, part B (#2028: letters <-> documents), own container (start.sh, mode workspaces), Firefox (desktop + phone
// width). Invented companies, people and figures only.
// - the document detail of an incoming letter shows "Correspondence": "Write an answer", the deadline found in the text
//   with "Create task" (the task is made, one undo step removes it again), the answer letter linked to the document
// - "Write an answer" opens #office/letters/new?answers=<document>
// - the letter side (office_letterlinks.js): the reference with its document, the history; unlink + undo
// - on a phone nothing sticks out to the side; a member of the organisation gets no "Correspondence" block
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2106_b_ui', check, shots: 'P2106B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2106B_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces -e KALMIDO_DOCS_SCAN_S=1'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const TXT = 'Versicherung Beispiel AG\nDatum: 05.10.2026\nUnser Zeichen: VB-2026/4711\n\nBitte senden Sie uns die Unterlagen bis zum 31.10.2026 zurück.\n';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob Member', password: 'password123', email: 'bob@example.com'});
  const CB = await login('bob');
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'bob@example.com', role: 'member'});
  for (const ck of [CA, CB]) await call(ck, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const fd = new FormData();
  fd.append('ws', `org:${org.id}`);
  fd.append('files', new Blob([TXT], {type: 'text/plain'}), 'Schreiben Versicherung.txt');
  const up = await (await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CA}, body: fd})).json();
  const NID = up.ids && up.ids[0];
  check(!!NID, 'a document uploaded');
  for (let i = 0; i < 120; i++) { const d = await call(CA, 'GET', `/api/docs/${NID}`); if (d.state === 'done' || d.state === 'failed') break; await sleep(500); }
  const L = await call(CA, 'POST', '/api/office/letters', {answers: NID});
  check(L.http === 201, 'an answer letter ' + L.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const noSide = sel => `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('${sel} *')].filter(e => e.getClientRects().length).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ================= the document side
    await nav(B + `#docs/${NID}`);
    check(await ready(ev, `!!document.querySelector('.dc-md .ltd [data-ltd="answer"]')`, 80), 'document: "Write an answer"');
    check(await ev(`/Correspondence/.test(document.querySelector('.ltd').textContent)`), 'document: the block "Correspondence"');
    check(await ev(`document.querySelectorAll('.ltd-list a[href="#office/letters/${L.id}"]').length === 1`), 'document: the answer letter is linked');
    check(await ready(ev, `!!document.querySelector('.ltd-dl [data-ltd="dltask"]')`), 'document: the deadline with "Create task"');
    check(await ev(`/31/.test(document.querySelector('.ltd-dl').textContent)`), 'document: the deadline date ' + await ev(`document.querySelector('.ltd-dl')?.textContent.trim()`));
    if (process.env.P2106B_SHOTS) await shot('p2106b-doc');
    await ev(`(() => { document.querySelector('.ltd-dl [data-ltd="dltask"]').click(); return 1; })()`);
    const tid = async () => (await call(CA, 'GET', `/api/docs/${NID}`)).task_id;
    let t = null; for (let i = 0; i < 40 && !t; i++) { t = await tid(); if (!t) await sleep(250); }
    check(!!t, 'create task: the task is linked at the document');
    const task = t ? await call(CA, 'GET', `/api/tasks/${t}`) : {};
    check((task.due || '').slice(0, 10) === '2026-10-31' && /^Deadline: /.test(task.title || ''), 'create task: due on the deadline ' + task.due + ' ' + task.title);
    check(await ready(ev, `!document.querySelector('.ltd-dl')`), 'create task: the deadline row is gone');
    await ev(`(() => { histStep('undo'); return 1; })()`);
    let gone = false; for (let i = 0; i < 40 && !gone; i++) { gone = !(await tid()); if (!gone) await sleep(250); }
    check(gone, 'undo: the task link is gone');
    check((await call(CA, 'GET', `/api/tasks/${t}`)).http === 404 || (await call(CA, 'GET', `/api/tasks/${t}`)).deleted_at, 'undo: the task is deleted');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(400);
    check(await ev(noSide('.ltd')), 'phone: nothing of the block sticks out to the side');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`(() => { document.querySelector('.ltd [data-ltd="answer"]').click(); return 1; })()`);
    check(await ready(ev, `/^#office\\/letters\\/(new\\?answers=${NID}|\\d+)$/.test(location.hash)`), 'answer: the new letter is opened ' + await ev('location.hash'));
    // 2.106.0 (#2028): with part A merged the address really opens a new answering draft in the office; leave the editor
    // again so the probe below is the only letter section on the page (one letter is open at a time)
    await sleep(800); await ev(`(() => { location.hash = '#docs'; return 1; })()`); await sleep(800);
    // ================= the letter side: the section of office_letterlinks.js (drawn into the page by hand)
    check(await ready(ev, `typeof ltkSection === 'function' && typeof LT_HOOKS === 'object' && LT_HOOKS.sections.includes(ltkSection)`, 80), 'letter: the section is in LT_HOOKS');
    await ev(`(async () => { const d = await api('GET', '/api/office/letters/${L.id}'); const box = document.createElement('div'); box.id = 'ltk-probe'; box.style.cssText = 'position:fixed;inset:auto 0 0 0;z-index:9999;background:var(--bg);max-height:60vh;overflow:auto;padding:1rem'; document.body.append(box); box.innerHTML = ltkSection(d); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#ltk-probe .ltk-list a[href="#docs/${NID}"]')`), 'letter: the reference document is listed');
    await ev(`(() => { const d = document.querySelector('#ltk-probe .ltk-th'); d.open = true; return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('#ltk-probe .ltk-tl li').length >= 2`), 'letter: the history (document + letter)');
    await ev(`(() => { document.querySelector('#ltk-probe [data-ltk^="unlink:"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#ltk-probe .ltk-none')`), 'letter: unlinked');
    await ev(`(() => { histStep('undo'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('#ltk-probe .ltk-list a[href="#docs/${NID}"]')`), 'letter: undo links it again');
    // ================= a member: no block
    await signIn(ev, 'bob');
    await nav(B + 'static/icon.svg');
    await nav(B + `#docs/${NID}`);
    await ready(ev, `!!document.querySelector('.dc-md')`, 40);  // a member may see the document or not: either way no block
    await sleep(800);
    check(await ev(`!document.querySelector('.ltd [data-ltd]')`), 'member: no "Correspondence" block');
  });
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
