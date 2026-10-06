// 2.2.0 UI tests (jsdom), own container (start.sh) with KALMIDO_SECRET_KEY and the fake GitHub / Gitea (fake_git.py) inside:
// #271 the task panel section "Code" (after the fields, before the comments): pull requests with state + CI icon, commits,
//      the branch-name button, "<agent> is working on it"; the row chip (#number + CI); the list dialog > Repository (owner:
//      rows with status + token set, the add form; connect a Gitea repository from the form; a member: no form); the history
//      line "Completed by the commit … in …" with Undo; German texts; phone
// #339 an agent's merge request: "Ready to merge" with the pull request, Approve / Reject for approvers only, Approve
//      approves; SW v63
const {execFileSync} = require('child_process');
const fs = require('fs'), path = require('path');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const KEY = require('crypto').randomBytes(32).toString('base64');
const GH = 'http://127.0.0.1:8090', GT = 'http://127.0.0.1:8091', TOKEN = 'ghp_ui_fake_token_19ab';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env,
  EXTRA: `-e KALMIDO_SECRET_KEY=${KEY} -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1 -e KALMIDO_GIT_POLL=2 -e KALMIDO_GIT_TICK=1`}});
const STATE = {'8090': {'acme/app': {token: TOKEN, default_branch: 'main', pulls: [], commits: {main: []}}},
  '8091': {'team/tool': {default_branch: 'develop', pulls: [], commits: {develop: []}}}};
const putState = () => { fs.writeFileSync(path.join(DATA, 'git.json.tmp'), JSON.stringify(STATE)); fs.renameSync(path.join(DATA, 'git.json.tmp'), path.join(DATA, 'git.json')); };
putState();
fs.copyFileSync(path.join(__dirname, 'fake_git.py'), path.join(DATA, 'fake_git.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_git.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const v1 = async (tok, method, url, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(250); } return fn(); };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments,agents';
const iso = d => d.toISOString().replace(/\.\d+Z$/, 'Z');
const pr = (n, title, o = {}) => ({number: n, title, body: o.body || '', state: o.merged ? 'closed' : 'open', merged_at: o.merged || null,
  html_url: `${GH}/acme/app/pull/${n}`, user: {login: 'dev'}, head: {ref: o.ref || 'feature', sha: o.sha || `sha${n}`}, updated_at: iso(new Date())});
const cm = (sha, message, at = new Date(Date.now() + 5000)) => ({sha, html_url: `${GH}/acme/app/commit/${sha}`, author: {login: 'dev'},
  commit: {message, author: {name: 'Dev', date: iso(at)}, committer: {date: iso(at)}}});
const taskOf = async (id, ck = CK) => (await call('GET', '/api/state', null, ck)).tasks.find(t => t.id === id);

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:(6[3-9]|7[0-9])|8[0-9]|9[0-9]|[1-9][0-9]{2})'/.test(SW), 'service worker cache v63 (2.2.1: v64, 2.3.0: v65, 2.4.0: v66, 2.4.1: v67, 2.4.2: v68, 2.5.0: v69, 2.5.1: v70, 2.5.2: v71, 2.6.0: v72, 2.6.1: v73, 2.7.0: v74, 2.7.1: v75, 2.7.2: v76, 2.8.0: v77, 2.9.0: v78, 2.10.0: v79, 2.11.0: v80)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en'}, CKB);
  const ag = await call('POST', '/api/admin/agents', {scopes: ['write'], username: 'claude', display_name: 'Claude'});
  const P = (await call('POST', '/api/lists', {name: 'App', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  await call('PUT', `/api/lists/${P}/members`, {user_id: ag.id, role: 'edit'});
  await call('PATCH', `/api/lists/${P}`, {agent_members: true});  // 2.26.0: members may use the agent (default off)
  const T1 = (await call('POST', '/api/tasks', {title: 'Login broken', list_id: P})).id;
  const T4 = (await call('POST', '/api/tasks', {title: 'Closed by a commit', list_id: P})).id;
  const T9 = (await call('POST', '/api/tasks', {title: 'CSV export', list_id: P, assignee_id: ag.id})).id;
  const r = await call('POST', `/api/lists/${P}/repos`, {provider: 'github', base_url: GH, repo: 'acme/app', token: TOKEN});
  check(r.id && r.full_name === 'acme/app', 'connected via the API');
  const g = STATE['8090']['acme/app'];
  g.pulls = [pr(5, `Fix login #${T1}`, {sha: 'aaa1'}), pr(11, 'CSV export', {ref: `kalmido-${T9}-csv-export`, sha: 'eee5'})];
  g.commits.main = [cm('c0ffee1', `Refactor login (#${T1})`), cm('c0ffee2', `fixes #${T4}`)];
  g.status = {aaa1: {state: 'failure', total_count: 1, statuses: [{state: 'failure'}]}, eee5: {state: 'success', total_count: 1, statuses: [{state: 'success'}]}};
  putState();
  await until(async () => (await taskOf(T1))?.code?.prs?.[0]?.ci && (await taskOf(T4))?.status === 2 && (await taskOf(T9))?.code?.prs?.[0]?.ci, 80);

  // ================= the task panel: Code
  for (const [mobile, lab] of [[false, 'desktop'], [true, 'phone']]) {
    const w = await boot({user: 'alice', mobile, hash: 't/' + T1}), d = w.document; await sleep(500);
    const sec = d.querySelector('#d-code');
    check(sec && /Code/.test(sec.querySelector('h5')?.textContent || '') && /acme\/app/.test(sec.querySelector('h5').textContent), `${lab}: section Code with the repository`);
    const rows = [...(sec?.querySelectorAll('.gitrow') || [])];
    check(rows.length === 2 && /Fix login/.test(rows[0].textContent) && /open/.test(rows[0].querySelector('.gst')?.textContent || '') && rows[0].querySelector('.ci-failure')
      && rows[0].getAttribute('href') === `${GH}/acme/app/pull/5` && rows[0].target === '_blank', `${lab}: the pull request row with state + CI`);
    check(rows[1] && /c0ffee1/.test(rows[1].textContent) && /Refactor login/.test(rows[1].textContent), `${lab}: the commit row`);
    check(sec && /^kalmido-\d+$/.test((sec.querySelector('.gbranch')?.textContent || '').trim()), `${lab}: branch name button`);
    const order = [...d.querySelectorAll('#detail .dsec')].map(x => x.id || x.className);
    const ic = order.indexOf('d-code'), it = order.findIndex(x => x === 'd-tl'), iti = order.findIndex(x => /fields/.test(x));
    // 2.24.0 (UX-41): the comments come first; Code follows the fields under "More details"
    check(ic > iti && (it < 0 || ic > it) && !!d.querySelector('#detail #d-more #d-code'), `${lab}: Code after the fields, under "More details": ${order.join(',')}`);
    if (!mobile) {
      const w2 = await boot({user: 'alice', hash: 'l/' + P}); await sleep(500);
      const chip = [...w2.document.querySelectorAll('.gitc')].find(x => /#5/.test(x.textContent));
      check(chip && chip.querySelector('.ci-failure') && /Pull request #5: open · CI failed/.test(chip.title), 'row chip: #5 + CI: ' + (chip?.title || w2.document.querySelectorAll('.gitc').length));
      w2.close();
    }
    w.close();
  }

  // ================= the history line "Completed by the commit" + Undo
  let w = await boot({user: 'alice', hash: 't/' + T4}), d = w.document; await sleep(700);
  const line = await until(() => [...d.querySelectorAll('.actl')].find(x => /Completed by the commit/.test(x.textContent)), 20);
  check(line && /fixes #\d+/.test(line.textContent) && /acme\/app/.test(line.textContent), 'history: completed by the commit in acme/app: ' + (line?.textContent || [...d.querySelectorAll('.actl')].map(x => x.textContent).join(' | ')));
  const ub = line && line.querySelector('[data-act="git-undo"]');
  check(ub, 'the Undo button');
  click(w, ub); await sleep(1200);
  check((await taskOf(T4)).status === 0, 'undo reopened the task');
  w.close();

  // ================= #339: merge request + agent working on it
  const url = `${GH}/acme/app/pull/11`;
  const mr = await v1(ag.token, 'POST', `/tasks/${T9}/comments`, {body: 'Ready to merge', suggestion: {kind: 'merge_request', pr_url: url, summary: 'Adds the CSV export'}});
  check(mr.status === 201 || mr.status === 200, 'merge request posted: ' + mr.status);
  await v1(ag.token, 'PUT', '/agent/status', {status: 'working', text: 'Writing tests', task_id: T9});
  w = await boot({user: 'bob', hash: 't/' + T9}); d = w.document; await sleep(700);
  let box = await until(() => d.querySelector('.sug.mr'), 20);
  check(box && /Ready to merge/.test(box.textContent) && /CSV export/.test(box.textContent) && /Adds the CSV export/.test(box.textContent) && box.querySelector('.ci-success'),
    'bob sees the merge request with the PR and CI');
  check(box && !box.querySelector('[data-act="mr-ok"]'), 'bob (member) gets no Approve button');
  check(/Claude is working on it/.test(d.querySelector('#d-code')?.textContent || ''), '"Claude is working on it" in the Code section');
  w.close();
  w = await boot({user: 'alice', hash: 't/' + T9}); d = w.document; await sleep(700);
  box = await until(() => d.querySelector('.sug.mr [data-act="mr-ok"]') && d.querySelector('.sug.mr'), 20);
  check(box && box.querySelector('[data-act="mr-no"]'), 'alice (owner) gets Approve / Reject');
  click(w, box.querySelector('[data-act="mr-ok"]')); await sleep(1200);
  const tl = await call('GET', `/api/tasks/${T9}/timeline`);
  check(tl.comments.find(c => c.id === mr.id)?.suggestion?.state === 'approved', 'Approve approved it');
  check(/approved/.test(d.querySelector('.sug.mr')?.textContent || '') && !d.querySelector('.sug.mr [data-act="mr-ok"]'), 'the box shows approved, no buttons');
  w.close();
  await v1(ag.token, 'PUT', '/agent/status', {status: 'idle'});

  // ================= list dialog > Repository
  for (const [mobile, lab] of [[false, 'desktop'], [true, 'phone']]) {
    w = await boot({user: 'alice', mobile, hash: 'l/' + P}); d = w.document;
    w.eval(`listModal(${P})`);
    const row = await until(() => d.querySelector('.lmodal #l-repos .reporow'));
    check(row && /acme\/app/.test(row.textContent) && /GitHub/.test(row.textContent) && /Token set/.test(row.textContent) && /Checked/.test(row.textContent), `${lab}: repo row: ` + (row?.textContent.replace(/\s+/g, ' ') || ''));
    check(d.querySelector('.lmodal #l-repos .repoadd #rp-name') && !d.querySelector('.lmodal #rp-tok').disabled, `${lab}: the add form for the owner`);
    check(!d.querySelector('.lmodal').innerHTML.includes(TOKEN), `${lab}: no token in the page`);
    if (!mobile) {
      d.querySelector('#rp-prov').value = 'gitea';
      d.querySelector('#rp-prov').dispatchEvent(new w.Event('change', {bubbles: true}));
      check(d.querySelector('#rp-base').placeholder === 'https://git.example.com', 'Gitea: the server placeholder');
      d.querySelector('#rp-base').value = GT; d.querySelector('#rp-name').value = 'team/tool';
      click(w, d.querySelector('[data-rp="add"]'));
      const r2 = await until(() => [...d.querySelectorAll('.lmodal .reporow')].find(x => /team\/tool/.test(x.textContent)));
      check(r2 && /Gitea \/ Forgejo/.test(r2.textContent) && /No token/.test(r2.textContent), 'connected a Gitea repository from the form');
      check(w.eval(`listRepos(${P}).length`) === 2, 'the list knows both repositories');
    }
    w.close();
  }
  w = await boot({user: 'bob', hash: 'l/' + P}); d = w.document;
  w.eval(`listModal(${P})`);
  await until(() => d.querySelector('.lmodal #l-repos .reporow'));
  check(!d.querySelector('.lmodal #rp-name') && !d.querySelector('.lmodal [data-rp="menu"]') && d.querySelector('.lmodal [data-rp="refresh"]'), 'bob: rows + refresh, no form, no menu');
  w.close();

  // ================= 2.18.0 (#408 "Software 2" A + F): provider select (GitLab / Bitbucket, auto-detect) + error reports
  {
    w = await boot({user: 'alice', hash: 'l/' + P}); d = w.document;
    w.eval(`listModal(${P})`);
    await until(() => d.querySelector('.lmodal #l-repos .reporow'));
    const sel = d.querySelector('#rp-prov');
    check(sel && ['github', 'gitlab', 'gitea', 'bitbucket'].every(v => [...sel.options].some(o => o.value === v)), '2.18.0: the provider select has GitHub, GitLab, Gitea, Bitbucket');
    const nm = d.querySelector('#rp-name');
    nm.value = 'https://gitlab.com/grp/sub/app'; nm.dispatchEvent(new w.Event('input', {bubbles: true}));
    const hint = d.querySelector('#rp-phint');
    check(sel.value === 'gitlab' && hint && !hint.hidden && /subgroups/.test(hint.textContent) && d.querySelector('#rp-base').placeholder === 'empty = gitlab.com',
      `2.18.0: a gitlab.com address picks GitLab: ${sel.value} ${hint?.hidden} ${d.querySelector('#rp-base').placeholder}`);
    nm.value = 'https://bitbucket.org/ws/web'; nm.dispatchEvent(new w.Event('input', {bubbles: true}));
    check(sel.value === 'bitbucket' && /Bitbucket Cloud only/.test(hint.textContent) && /app password/.test(d.querySelector('#rp-tok').placeholder), '2.18.0: bitbucket.org -> Bitbucket Cloud + hint');
    nm.value = 'https://git.example.com/a/b'; nm.dispatchEvent(new w.Event('input', {bubbles: true}));
    check(sel.value === 'bitbucket', '2.18.0: another host keeps the chosen provider');
    sel.value = 'github'; sel.dispatchEvent(new w.Event('change', {bubbles: true}));
    check(hint.hidden, '2.18.0: GitHub: no extra hint');
    const eh = d.querySelector('#rp-err');
    check(eh && /Error reports/.test(eh.textContent) && /Off/.test(eh.textContent) && eh.querySelector('[data-rp="err-on"]'), '2.18.0: error reports row, off, Turn on');
    click(w, eh.querySelector('[data-rp="err-on"]'));
    const code = await until(() => d.querySelector('#rp-err .rpsec code'));
    const url = code?.textContent || '';
    check(new RegExp(`/api/hooks/issues/${P}/[\\w-]{20,}$`).test(url) && d.querySelector('#rp-err [data-rp="err-copy"]') && d.querySelector('#rp-err [data-rp="err-menu"]')
      && /On/.test(d.querySelector('#rp-err .rpm').textContent), '2.18.0: on: the URL once, Copy, the menu: ' + url);
    check(d.activeElement === d.querySelector('#rp-err [data-rp="err-copy"]'), '2.18.0: focus moves to Copy');
    w.close();
    const ep = B + 'api/hooks/issues/' + url.split('/api/hooks/issues/')[1];
    const rr = await (await fetch(ep, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title: 'UI crash', fingerprint: 'ui-1'})})).json();
    check(rr.task_id, '2.18.0: a report made a ticket');
    await fetch(ep, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({title: 'UI crash', fingerprint: 'ui-1'})});
    w = await boot({user: 'bob', hash: 'l/' + P}); d = w.document;
    w.eval(`listModal(${P})`);
    const ebob = await until(() => d.querySelector('.lmodal #rp-err'));
    check(ebob && /On/.test(ebob.textContent) && /2 received/.test(ebob.textContent) && !ebob.querySelector('[data-rp]') && !/hooks\/issues/.test(ebob.innerHTML),
      '2.18.0: bob sees the state, no buttons, no URL: ' + (ebob?.textContent.replace(/\s+/g, ' ') || ''));
    w.close();
    w = await boot({user: 'alice', hash: 't/' + rr.task_id}); d = w.document; await sleep(700);
    const lines = await until(() => { const x = [...d.querySelectorAll('.actl')].map(e => e.textContent).join(' | '); return /happened again/.test(x) && x; }, 20);
    check(/Created from an error report \(webhook\)/.test(lines || '') && /The error happened again \(2×\)/.test(lines || ''), '2.18.0: history lines: ' + lines);
    w.close();
  }

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 't/' + T9}); d = w.document; await sleep(900);
  check(/Code/.test(d.querySelector('#d-code h5')?.textContent || '') && /Bereit zum Mergen/.test(d.querySelector('.sug.mr')?.textContent || '')
    && /freigegeben/.test(d.querySelector('.sug.mr')?.textContent || ''), 'German: Code, Bereit zum Mergen, freigegeben');
  w.eval(`listModal(${P})`);
  await until(() => d.querySelector('.lmodal #l-repos .reporow'));
  check(/Repository/.test(d.querySelector('#l-repos-h')?.textContent || '') && /Token gesetzt/.test(d.querySelector('#l-repos').textContent) && /Verbinden/.test(d.querySelector('#l-repos').textContent), 'German: the dialog');
  w.close();

  check(!errs.length, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})();
