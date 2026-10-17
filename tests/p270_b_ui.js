// 2.70.0 UI tests of part B (#1357 tidy up contacts with an agent; own container, start.sh). jsdom:
// - the contacts view's menu has "Find duplicates with an agent…"; the dialog names the agent and what it gets (name,
//   company, e-mails, phones of the N contacts), sending creates a proposal job of kind merge for that address book
// - the proposal sheet: one row per group with its own tick, the contacts side by side, the agent's reason, the main
//   contact switchable (marked); a group with a changed contact is greyed out and cannot be ticked; Apply says
//   "Merge 1 group" and merges as the person into the chosen main contact; Undo brings the merged contact back
// Firefox (real layout, skipped without firefox): 390 px - the sheet stays inside the screen, the contacts stack
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const firefox = require('./ff')({tag: 'p270_b_ui', check: (c, w) => check(c, w), shots: 'P270B_SHOTS'});
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P270B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');
const alive = id => sql('SELECT id FROM contacts WHERE id=?', [id]).length === 1;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,contacts,agents', workspace: 'all'});
  const ag = await call('POST', '/api/admin/agents', {username: 'claude', display_name: 'Claude', scopes: ['write']});
  sql('UPDATE agents SET org_id=NULL, owner_id=1 WHERE user_id=?', [ag.id]);  // alice's personal agent
  check((await call('PATCH', `/api/admin/agents/${ag.id}`, {proposals: 'all'})).http === 200, 'setup: the agent takes requests');
  const AGH = {Authorization: 'Bearer ' + ag.token};
  const bk = await call('POST', '/api/books', {name: 'Mine', org_id: null});
  const mk = async (given, family, kw = {}) => (await call('POST', '/api/contacts', {book_id: bk.id, given, family, ...kw})).id;
  const C1 = await mk('Erika', 'Muster', {emails: [{value: 'erika@example.com'}]});
  const C2 = await mk('Erika', 'Mustermann', {emails: [{value: 'erika@example.com'}], phones: [{value: '+49 170 1'}]});
  const C3 = await mk('Max', 'Beispiel');
  const C4 = await mk('Max', 'Beispiel2');

  // ================= the entry in the contacts view
  let w = await boot({user: 'alice', hash: 'contacts'}), d = w.document;
  await until(() => d.querySelector('.ctview [data-ct="menu"]') && w.eval('(S.proposers || []).length'));
  click(w, d.querySelector('[data-ct="menu"]'));
  const item = await until(() => [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Find duplicates with an agent/.test(b.textContent)));
  check(!!item, '#1357: the contacts menu offers "Find duplicates with an agent…"');
  click(w, item);
  const rq = await until(() => d.querySelector('.dupreq'));
  check(rq && /Claude/.test(rq.querySelector('#pp-priv')?.textContent || '') && /name, company, e-mail addresses and phone numbers of the 4 contacts/.test(rq.textContent),
    '#1357: the dialog says who gets what ' + (rq?.querySelector('#pp-priv')?.textContent || ''));
  click(w, rq?.querySelector('[data-m="ok"]'));
  const job = await until(() => sql("SELECT id, input FROM agent_jobs WHERE kind='merge' AND user_id=1")[0]);
  check(job && JSON.parse(job.input).book.id === bk.id && JSON.parse(job.input).contacts.length === 4, '#1357: a merge request for this address book');
  w.close();

  // ================= the proposal sheet
  const pr = await call('POST', `/api/v1/agent/jobs/${job?.id}/proposal`, {summary: 'Two pairs', groups: [
    {target_id: C1, ids: [C1, C2], reason: 'Same e-mail address'}, {target_id: C3, ids: [C3, C4], reason: 'Same name'}]}, null, AGH);
  check(pr.http === 201, 'setup: the agent proposes two groups ' + pr.http + JSON.stringify(pr.error || ''));
  await call('PATCH', `/api/contacts/${C4}`, {family: 'Changed'});  // the second group goes stale
  w = await boot({user: 'alice', hash: 'prop/' + job?.id}); d = w.document;
  const md = await until(() => d.querySelector('.ppm .dupg') && d.querySelector('.ppm'));
  const rows = md ? [...md.querySelectorAll('.dupg')] : [];
  check(rows.length === 2 && rows[0].querySelectorAll('.dupc').length === 2 && /Same e-mail address/.test(rows[0].textContent), '#1357: one row per group, contacts side by side, the reason');
  check(rows[0]?.querySelector('.ppc')?.checked && !rows[0].classList.contains('dupx') && rows[1]?.classList.contains('dupx') && rows[1].querySelector('.ppc')?.disabled,
    '#1357: a fine group ticked, the changed one greyed out and not tickable');
  check(/Changed since the request/.test(rows[1]?.textContent || ''), '#1357: the changed contact says so');
  check(/Merge 1 group/.test(md?.querySelector('[data-pp="apply"]')?.textContent || ''), '#1357: Apply says "Merge 1 group"');
  check(rows[0]?.querySelector('.dupc.tgt')?.dataset.cid === String(C1), '#1357: the agent\'s main contact is marked');
  const sel = rows[0]?.querySelector('[data-f="target_id"]');
  if (sel) { sel.value = String(C2); sel.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(rows[0]?.querySelector('.dupc.tgt')?.dataset.cid === String(C2), '#1357: the main contact switched to the other one');
  click(w, md?.querySelector('[data-pp="apply"]'));
  check(await until(() => !alive(C1) && alive(C2)), '#1357: Apply merges into the chosen main contact');
  check(alive(C3) && alive(C4), '#1357: the skipped group stays');
  check(await until(() => /1 group merged/.test(d.querySelector('#toast, .toast')?.textContent || '')), '#1357: the toast names the merge');
  await sleep(300);
  await w.eval("histStep('undo')");
  check(await until(() => alive(C1)), '#1357: Undo brings the merged contact back');
  w.close();

  // ================= Firefox: 390 px
  const j2 = await call('POST', '/api/proposals', {kind: 'merge', agent_id: ag.id, book_id: bk.id});
  await call('POST', `/api/v1/agent/jobs/${j2.id}/proposal`, {groups: [{target_id: C1, ids: [C1, C2], reason: 'Same e-mail address'}]}, null, AGH);
  await firefox(async ({cmd, ev: fev, nav, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await fev('(() => { localStorage.clear(); return 1; })()');
    check(await fev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#prop/' + j2.id);
    for (let i = 0; i < 30 && !(await fev('!!document.querySelector(".ppm .dupg")').catch(() => false)); i++) await sleep(300);
    const o = await fev(`(() => { const vw = document.documentElement.clientWidth, card = document.querySelector('.ppm .card').getBoundingClientRect();
      const c = [...document.querySelectorAll('.ppm .dupc')].map(e => e.getBoundingClientRect());
      const bad = [...document.querySelectorAll('.ppm .dupg *')].filter(e => { const r = e.getBoundingClientRect(); return r.width && r.right > vw + 1; }).length;
      const sel = document.querySelector('.ppm [data-f="target_id"]').getBoundingClientRect().height;
      return {vw, right: card.right, n: c.length, bad, sel}; })()`);
    check(o.right <= o.vw + 1 && o.n === 2 && !o.bad && o.sel >= 36, '390 px: the sheet inside the screen, the main contact choice large enough ' + JSON.stringify(o));
    await shot('p270b-sheet-390.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
