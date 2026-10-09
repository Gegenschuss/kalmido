// 2.18.0 lane 1b UI + API tests (#408 "Software"), own container (start.sh, isolated test database).
// API: lists.ptype (web PATCH {ptype}, v1 project_type on GET / PATCH + validation, owner / list admins only, never the
// inbox; switching turns on what the type needs and never deletes; ptype_prev / ptype_missing; new projects of a type keep it).
// jsdom: the list dialog shows "Project type" (change it, the type's sections offered + Undo, "No thanks", a member / viewer
// cannot change it), the Repository area only for software projects and lists that have a repository; ticket templates
// (bug: "Version / found in", feature: acceptance criteria as a checklist); the Code section: branch name + commit
// reference one tap each; Markdown code blocks: highlighting (tokens, escaping, XSS attempts, plain blocks, diff), Copy;
// file:line links for GitHub, Gitea, Forgejo, GitLab, Bitbucket (and no false positives); the duplicate hint of a new bug.
// Firefox at 390 touch and 1440 mouse, light + dark: the list dialog and the task panel (nothing sideways, 44 px targets,
// AA contrast of the code colours on the code background in both themes and with another accent).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2180_soft_ui', check, shots: 'P2180_SHOTS', prefs: [['widget.gtk.overlay-scrollbars.enabled', true], ['ui.useOverlayScrollbars', 1]]});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
// the HTTP status as "http" (a v1 list has its own "status" field)
const tcall = async (method, url, tok, body) => { const r = await fetch(B + 'api/v1' + url, {method, headers: {'Content-Type': 'application/json', Authorization: 'Bearer ' + tok}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const lst = async (id, ck = CK) => (await call('GET', '/api/state', null, ck)).lists.find(x => x.id === id);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const U = {};
  for (const n of ['bob', 'carol', 'dave']) U[n] = (await call('POST', '/api/users', {username: n, display_name: n[0].toUpperCase() + n.slice(1), password: 'password123'})).id;
  const CB = await login('bob'), CC = await login('carol'), CD = await login('dave');
  for (const c of [CB, CC, CD]) await call('PATCH', '/api/settings', {features: ALL, tour: 'done', lang: 'en'}, c);
  const L = (await call('POST', '/api/lists', {name: 'App', kind: 'project'})).id;  // a project with tasks, no type yet
  await call('PUT', `/api/lists/${L}/members`, {user_id: U.bob, role: 'admin'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: U.carol, role: 'edit'});
  await call('PUT', `/api/lists/${L}/members`, {user_id: U.dave, role: 'view'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Write the login page', list_id: L})).id;
  const PL = (await call('POST', '/api/lists', {name: 'Plain'})).id;  // a plain, empty list
  const EM = (await call('POST', '/api/lists', {name: 'Empty project', kind: 'project'})).id;  // empty project for the dialog

  // ================= API
  const sw = await call('POST', '/api/lists', {name: 'Shop', ptype: 'software'});
  check(sw.ptype === 'software' && (await lst(sw.id)).ptype === 'software', 'a new project of a type keeps its type (lists.ptype, /api/state)');
  check((await lst(L)).ptype === '', 'an existing project without a type: ptype ""');
  check((await call('PATCH', `/api/lists/${L}`, {ptype: 'bogus'})).status === 400, 'web PATCH: an unknown type is refused (400)');
  check((await call('PATCH', `/api/lists/${L}`, {ptype: 7})).status === 400, 'web PATCH: a non-string type is refused');
  check((await call('PATCH', `/api/lists/${L}`, {ptype: 'agency'}, CC)).status === 403, 'a member (edit) cannot change the project type');
  check((await call('PATCH', `/api/lists/${L}`, {ptype: 'agency'}, CD)).status === 403, 'a viewer cannot change the project type');
  check((await lst(L)).ptype === '', '... and nothing changed');
  let r = await call('PATCH', `/api/lists/${L}`, {ptype: 'software'}, CB);
  let x = await lst(L);
  check(r.status === 200 && x.ptype === 'software' && x.tickets && x.view === 'list', 'a list admin sets Software: ticket types on, the view stays (the list has tasks) ' + JSON.stringify([r.status, x.ptype, x.tickets, x.view]));
  check(r.ptype_prev && r.ptype_prev.tickets === 0 && !('view' in r.ptype_prev) && !('kind' in r.ptype_prev), 'ptype_prev names what was switched on ' + JSON.stringify(r.ptype_prev));
  check(JSON.stringify(r.ptype_missing?.sections) === JSON.stringify(['Backlog', 'Next', 'In progress', 'Review', 'Done']), 'ptype_missing: the type\'s sections the list lacks ' + JSON.stringify(r.ptype_missing));
  check((await call('GET', `/api/tasks/${T1}`)).title === 'Write the login page', 'switching keeps the tasks');
  r = await call('PATCH', `/api/lists/${PL}`, {ptype: 'software'});
  x = await lst(PL);
  check(x.kind === 'project' && x.tickets && x.view === 'list' && x.ptype === 'software', 'a plain empty list -> Software: type Project, ticket types, (2.22.0 #749) the list view ' + JSON.stringify([x.kind, x.tickets, x.view]));
  check(r.ptype_prev.kind === 'list' && (r.ptype_prev.view ?? 'list') === 'list' && r.ptype_prev.tickets === 0, 'ptype_prev for the undo ' + JSON.stringify(r.ptype_prev));
  r = await call('PATCH', `/api/lists/${PL}`, {ptype: '', kind: 'list', tickets: 0, view: 'list', _prev: {ptype: 'software', kind: 'project', tickets: 1, view: 'list'}});
  x = await lst(PL);
  check(r.status === 200 && x.ptype === '' && x.kind === 'list' && !x.tickets && x.view === 'list', 'the undo request restores type, kind, ticket types and view');
  await call('POST', '/api/sections', {list_id: EM, name: 'backlog'});
  r = await call('PATCH', `/api/lists/${EM}`, {ptype: 'software'});
  check(!r.ptype_missing.sections.includes('Backlog') && r.ptype_missing.sections.length === 4, 'ptype_missing ignores sections the list has (case-insensitive) ' + JSON.stringify(r.ptype_missing.sections));
  await call('PATCH', `/api/lists/${EM}`, {ptype: '', view: 'list', tickets: false});
  for (const s of (await call('GET', '/api/state')).sections.filter(s => s.list_id === EM)) await call('DELETE', `/api/sections/${s.id}`);
  const st = await call('GET', '/api/state'), ib = st.lists.find(l => l.is_inbox).id;
  check((await call('PATCH', `/api/lists/${ib}`, {ptype: 'private'})).status === 400, 'the inbox cannot get a project type');
  const ag = await call('PATCH', `/api/lists/${L}`, {ptype: 'agency'});
  check(ag.ptype_missing.fields.map(f => f.name).join() === 'Client,Budget h' && ag.modules_on !== undefined, 'agency: missing fields named, modules reported');
  await call('PATCH', `/api/lists/${L}`, {ptype: 'software'});
  // v1
  const tk = await call('POST', '/api/me/tokens', {name: 'p2180', scopes: ['read', 'write']});
  check(tk.status === 201 && tk.token, 'a personal token');
  const vg = await tcall('GET', `/lists/${L}`, tk.token);
  check(vg.http === 200 && vg.project_type === 'software', 'v1 GET list: project_type ' + vg.project_type);
  check((await tcall('GET', `/lists/${EM}`, tk.token)).project_type === null, 'v1: no type = null');
  const vp = await tcall('PATCH', `/lists/${EM}`, tk.token, {project_type: 'private'});
  check(vp.http === 200 && vp.project_type === 'private', 'v1 PATCH project_type ' + vp.http);
  check((await tcall('PATCH', `/lists/${EM}`, tk.token, {project_type: 'nope'})).http === 400, 'v1 PATCH: an unknown project_type is refused');
  const vn = await tcall('PATCH', `/lists/${EM}`, tk.token, {project_type: null});
  check(vn.http === 200 && vn.project_type === null, 'v1 PATCH project_type null = none');
  const vl = await tcall('GET', '/lists', tk.token);
  check((vl.data || []).find(l => l.id === L)?.project_type === 'software', 'v1 GET /lists carries project_type');
  const oa = await (await fetch(B + 'api/v1/openapi.json')).json().catch(() => ({}));
  check(oa?.components?.schemas?.List?.properties?.project_type && oa?.components?.schemas?.ListPatch?.properties?.project_type, 'OpenAPI: List and ListPatch name project_type');
  await call('PATCH', `/api/lists/${EM}`, {view: 'list', tickets: false});

  // ticket templates (C, E)
  const bug = await call('POST', '/api/tasks', {title: 'Crash on save', list_id: L, ttype: 'bug'});
  check(/\*\*Steps to reproduce\*\*/.test(bug.content) && /\*\*Version \/ found in\*\*/.test(bug.content), 'bug template: Version / found in ' + JSON.stringify(bug.content));
  const feat = await call('POST', '/api/tasks', {title: 'Dark mode', list_id: L, ttype: 'feature'});
  check(/\*\*Acceptance criteria\*\*\n- \[ \] /.test(feat.content), 'feature template: acceptance criteria as a checklist ' + JSON.stringify(feat.content));

  // ================= jsdom: the list dialog
  let w = await boot({user: 'alice', hash: 'l/' + EM}), d = w.document;
  w.eval(`listModal(${EM})`); await sleep(300);
  let md = d.querySelector('.modal.lmodal') || d.querySelector('.lmodal');
  let sel = md?.querySelector('#l-ptype');
  check(sel && !sel.disabled && sel.options.length === 4 && sel.value === '' && md.querySelector('label[for="l-ptype"]')?.textContent === 'Project type', 'dialog: Project type with None / Agency / Software / Personal');
  check(sel && [...sel.options].map(o => o.textContent).join('|') === 'None|Agency|Software / AI dev|Personal', 'the type names ' + [...(sel?.options || [])].map(o => o.textContent).join('|'));
  check(md.querySelector('.lrepo')?.hidden === true, 'a project without a type and without a repository: no Repository area');
  change(w, sel, 'software');
  check(await until(() => w.eval(`listById(${EM}).ptype === 'software'`)), 'changing the select saves the type');
  await until(() => md.querySelector('.ptoffer'));
  check(w.eval(`!!listById(${EM}).tickets`) && md.querySelector('#l-tickets')?.checked, 'the dialog shows ticket types switched on');
  check(md.querySelector('.lrepo') && !md.querySelector('.lrepo').hidden && !md.querySelector('.lrepohint').hidden && /Connect a repository \(optional\)/.test(md.querySelector('.lrepohint').textContent), 'Software: the Repository area shows with "Connect a repository (optional)"');
  check(/Backlog, Next, In progress, Review, Done/.test(md.querySelector('.ptoffer')?.textContent || ''), 'the type\'s sections are offered, not added ' + (md.querySelector('.ptoffer')?.textContent || ''));
  check(w.eval(`S.sections.filter(s => s.list_id === ${EM}).length`) === 0, '... nothing added yet');
  check(/Software/.test(md.querySelector('#l-pthint').textContent) || /Backlog to Done/.test(md.querySelector('#l-pthint').textContent), 'the hint describes the type');
  click(w, md.querySelector('[data-pto="add"]'));
  check(await until(() => w.eval(`S.sections.filter(s => s.list_id === ${EM}).length === 5`)), 'Add sections: the five sections exist');
  check(!md.querySelector('.ptoffer'), 'the offer closes');
  w.eval(`histStep('undo')`);
  check(await until(() => w.eval(`S.sections.filter(s => s.list_id === ${EM}).length === 0`)), 'Undo removes the added sections');
  await until(() => w.eval('!HIST.busy'));
  w.eval(`histStep('undo')`);
  check(await until(() => w.eval(`(listById(${EM}).ptype || '') === '' && !listById(${EM}).tickets`)), 'the next Undo takes the type and the ticket types back');
  await until(() => w.eval('!HIST.busy'));
  check(await until(() => md.querySelector('#l-ptype')?.value === ''), 'the open dialog follows the undo');
  change(w, md.querySelector('#l-ptype'), 'private');
  await until(() => md.querySelector('.ptoffer'));
  click(w, md.querySelector('[data-pto="no"]'));
  check(!md.querySelector('.ptoffer') && w.eval(`S.sections.filter(s => s.list_id === ${EM}).length`) === 0 && w.eval(`listById(${EM}).ptype`) === 'private', '"No thanks": the type stays, no sections');
  check(md.querySelector('.lrepo').hidden, 'Personal: no Repository area');
  w.eval(`listById(${EM}).repos = [{id: 9, full_name: 'acme/site', provider: 'github', web_url: 'https://github.com/acme/site'}]; [...document.querySelectorAll('.modal')].forEach(m => m.remove()); listModal(${EM})`); await sleep(200);
  check(!d.querySelector('.lmodal .lrepo').hidden, 'a list that already has a repository keeps showing it');
  // 2.18.0 review (R1): arrow keys through the select save ONCE (on Enter / leaving it), one history step, the offer fits
  md = d.querySelector('.lmodal'); sel = md.querySelector('#l-ptype');
  check(/Simple list/.test(md.querySelector('.lkrow')?.textContent || '') && md.querySelector('.lkrow #l-kindp'), 'the kind: Simple list | Project (2.27.0, #977; was the switch "Project features")');
  const kd = (el, key) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key, bubbles: true, cancelable: true}));
  const h0 = w.eval('HIST.undo.length');
  sel.focus(); kd(sel, 'ArrowDown'); change(w, sel, 'agency'); kd(sel, 'ArrowDown'); change(w, sel, 'software'); await sleep(700);
  check(w.eval(`listById(${EM}).ptype`) === 'private' && w.eval('HIST.undo.length') === h0, 'R1: walking the options with the keyboard saves nothing yet');
  check(/Backlog to Done|Software/.test(md.querySelector('#l-pthint').textContent), 'R1: the hint follows the option under the keyboard ' + md.querySelector('#l-pthint').textContent);
  kd(sel, 'Enter');
  check(await until(() => w.eval(`listById(${EM}).ptype === 'software'`)), 'R1: Enter saves the chosen type');
  await until(() => w.eval('!HIST.busy')); await sleep(400);
  check(w.eval('HIST.undo.length') === h0 + 1, 'R1: one history step ' + (w.eval('HIST.undo.length') - h0));
  check(!md.querySelector('.ptoffer') || /Software/.test(md.querySelector('.ptoffer').textContent), 'R1: an offer names the chosen type ' + (md.querySelector('.ptoffer')?.textContent || ''));
  sel.focus(); kd(sel, 'ArrowUp'); change(w, sel, 'agency'); sel.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true}));
  check(await until(() => w.eval(`listById(${EM}).ptype === 'agency'`)), 'R1: leaving the select saves too');
  await until(() => w.eval('!HIST.busy'));
  // 2.18.0 review (R11): a self-hosted address with Provider still on GitHub -> a hint; a failed connect shows next to the field
  await until(() => md.querySelector('#rp-name'));
  const rn = md.querySelector('#rp-name'), inp = (el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
  check(md.querySelector('#rp-self')?.hidden === true, 'R11: no hint at first');
  inp(rn, 'https://git.example.com/acme/app');
  check(md.querySelector('#rp-self').hidden === false && /self-hosted/.test(md.querySelector('#rp-self').textContent), 'R11: a self-hosted address on GitHub: "pick its provider"');
  change(w, md.querySelector('#rp-prov'), 'gitea');
  check(md.querySelector('#rp-self').hidden === true, 'R11: the hint goes once a provider is picked');
  change(w, md.querySelector('#rp-prov'), 'github'); inp(rn, 'https://github.com/acme/app');
  check(md.querySelector('#rp-self').hidden === true, 'R11: no hint for github.com');
  inp(rn, 'not a repo !!'); click(w, md.querySelector('[data-rp="add"]'));
  check(await until(() => md.querySelector('#rp-cerr')?.textContent.trim()), 'R11: the connect error shows next to the fields ' + (md.querySelector('#rp-cerr')?.textContent || ''));
  check(rn.getAttribute('aria-invalid') === 'true' && rn.getAttribute('aria-describedby') === 'rp-cerr' && md.querySelector('#rp-cerr').getAttribute('role') === 'alert', 'R11: the field is marked invalid and points at the message');
  inp(rn, 'acme/app');
  check(!md.querySelector('#rp-cerr').textContent && !rn.hasAttribute('aria-invalid'), 'R11: typing clears the message');
  // "…" menu: "As a list / As a project"
  w.eval(`[...document.querySelectorAll('.modal')].forEach(m => m.remove())`);
  const lmi = w.eval(`listMenuItems(${EM}).filter(x => x && x.label).map(x => x.label)`);
  check(!lmi.includes('As a list') && !lmi.includes('As a project') && !lmi.some(x => /^Type:/.test(x)) && lmi.includes('Edit list…'), 'list menu: no type entries (2.25.0, UX-52) ' + lmi.join(' | '));
  w.close();
  for (const [u, may] of [['bob', true], ['carol', false], ['dave', false]]) {
    w = await boot({user: u, hash: 'l/' + L}); d = w.document;
    w.eval(`listModal(${L})`); await sleep(300);
    const s2 = d.querySelector('.lmodal #l-ptype');
    check(s2 && s2.value === 'software' && s2.disabled === !may, `${u}: the type is shown (Software), ${may ? 'changeable (list admin)' : 'not changeable'}`);
    if (!may) check(/Only the owner and list admins/.test(s2?.title || ''), `${u}: the disabled select says why`);
    w.close();
  }

  // ================= jsdom: Code section, Markdown, file links, duplicate hint
  const OLD = (await call('POST', '/api/tasks', {title: 'Login button crashes on Safari', list_id: L, ttype: 'bug'})).id;
  const NEW = (await call('POST', '/api/tasks', {title: 'Login button crashes on Safari iOS', list_id: L, ttype: 'bug'})).id;
  const OTHER = (await call('POST', '/api/tasks', {title: 'Export to CSV is slow', list_id: L, ttype: 'bug'})).id;
  w = await boot({user: 'alice', hash: 't/' + NEW}); d = w.document;
  let copied = null; Object.defineProperty(w.navigator, 'clipboard', {configurable: true, value: {writeText: async v => { copied = v; }}});
  w.eval(`listById(${L}).repos = [{id: 1, full_name: 'acme/app', provider: 'github', web_url: 'https://github.com/acme/app', default_branch: 'main'}]; renderDetail()`); await sleep(200);
  const gb = [...d.querySelectorAll('#d-code .gcopy .gbranch')];
  check(gb.length === 2 && gb[0].textContent.includes(`kalmido-${NEW}`) && gb[1].textContent.includes(`fixes #${NEW}`), 'Code section: branch name and commit reference, one tap each');
  check(gb.every(b => b.getAttribute('aria-label')), 'both copy buttons have names');
  click(w, gb[1]); await sleep(100);
  check(copied === `fixes #${NEW}`, 'a tap copies the commit reference ' + copied);
  // duplicate hint
  const dup = d.querySelector('#detail .ddup');
  check(dup && dup.textContent.includes(`#${OLD}`) && dup.textContent.includes('Login button crashes on Safari'), 'a new bug like an open ticket: "Similar open ticket: #id title"');
  check(dup?.querySelector('[data-act="open-id"]') && dup.querySelector('[data-act="dup-x"]')?.getAttribute('aria-label') === 'Dismiss', 'the hint: open the other ticket, dismiss (named)');
  click(w, dup.querySelector('[data-act="dup-x"]')); await sleep(100);
  w.eval('renderDetail()'); await sleep(100);
  check(!d.querySelector('#detail .ddup'), 'dismissed: stays away');
  w.eval(`openDetail(${OTHER})`); await sleep(200);
  check(!d.querySelector('#detail .ddup'), 'no hint for a bug without a similar ticket');
  w.eval(`openDetail(${OLD})`); await sleep(200);
  check(!d.querySelector('#detail .ddup') || d.querySelector('#detail .ddup').textContent.includes(`#${NEW}`), 'the older ticket may point at the newer one (both new)');
  // Markdown: highlighting
  const R = (src, lid) => w.eval(`renderMd(${JSON.stringify(src)}, true${lid ? `, {lid: ${lid}}` : ''})`);
  const frag = html => { const el = d.createElement('div'); el.innerHTML = html; return el; };
  let h = frag(R('```js\nconst a = "x"; // note\nreturn 42;\n```'));
  check(h.querySelector('pre.mdpre[data-lang="js"] .hl-k')?.textContent === 'const' && h.querySelector('.hl-s')?.textContent === '"x"' && h.querySelector('.hl-c')?.textContent === '// note' && h.querySelector('.hl-n')?.textContent === '42', 'js: keyword, string, comment, number');
  check(h.querySelector('pre').textContent === 'const a = "x"; // note\nreturn 42;', 'the code text is unchanged');
  h = frag(R('```py\ndef f(x):\n    """doc"""\n    return None  # done\n```'));
  check(h.querySelectorAll('.hl-k').length >= 3 && h.querySelector('.hl-s')?.textContent === '"""doc"""' && h.querySelector('.hl-c')?.textContent === '# done', 'python: def / return / None, docstring, # comment');
  h = frag(R('```sql\nSELECT id FROM t WHERE a = \'x\' -- c\n```'));
  check(h.querySelector('.hl-k')?.textContent === 'SELECT' && h.querySelector('.hl-c')?.textContent === '-- c', 'sql: keywords in capitals, -- comment');
  h = frag(R('```diff\n--- a/x\n+++ b/x\n@@ -1 +1 @@\n-old\n+new\n same\n```'));
  check(h.querySelector('.hl-del')?.textContent === '-old' && h.querySelector('.hl-add')?.textContent === '+new' && h.querySelectorAll('.hl-m').length === 3, 'diff: + / - lines and the header lines');
  for (const lg of ['sh', 'json', 'yaml', 'go', 'rust', 'java', 'c', 'cpp', 'ts', 'css', 'html', 'xml']) {
    const hh = frag(R('```' + lg + '\nx = "s" // 1\n```'));
    check(hh.querySelector('pre.mdpre') && hh.querySelector('pre').textContent === 'x = "s" // 1', `${lg}: highlighted without changing the text`);
  }
  h = frag(R('```\nconst plain = 1;\n```'));
  check(h.querySelector('pre.mdpre') && !h.querySelector('pre [class^="hl-"]') && !h.querySelector('pre').dataset.lang, 'a block without a language stays plain');
  const XSS = ['<img src=x onerror="window.__x=1">', '"</span><script>window.__x=2</script>', "'<svg onload=window.__x=3>'", '<!-- --><iframe src=javascript:1>'];
  for (const lg of ['js', 'html', 'py', '', 'diff', 'x"><img src=x onerror=window.__x=4>']) {
    const hh = frag(R('```' + lg + '\n' + XSS.join('\n') + '\n```'));
    check(!hh.querySelector('pre img, pre script, pre svg, pre iframe, img, script, iframe') && hh.querySelector('pre')?.textContent === XSS.join('\n') && !w.__x, `escaping (${lg.slice(0, 12) || 'plain'}): no element from the code, the text unchanged`);
  }
  check(!/<img/i.test(R('```' + 'x"><img src=x>' + '\nA\n```')), 'a hostile language name is cleaned');
  // 2.18.0 review (R6): backslash escapes render as the plain character (error-report tickets), never as markup or a link
  h = frag(R(String.raw`**Error:** TypeError \(reading \*x\*\) in \_\_init\_\_ \<b\> \[a\] https\://y.example \\ ok`));
  check(h.textContent === 'Error: TypeError (reading *x*) in __init__ <b> [a] https://y.example \\ ok' && !h.querySelector('a, i, code') && h.querySelectorAll('b').length === 1,
    'escapes: plain characters, no emphasis / link / HTML ' + h.textContent);
  h = frag(R(String.raw`code ${'`'}a\_b${'`'} and C:\Users\x`));
  check(h.querySelector('code')?.textContent === String.raw`a\_b` && /C:\\Users\\x/.test(h.textContent), 'escapes: inside code spans and before letters the backslash stays ' + h.textContent);
  const big = 'let a = 1;\n'.repeat(3000);
  const t0 = Date.now(); h = frag(R('```js\n' + big + '```'));
  check(Date.now() - t0 < 1500 && !h.querySelector('.hl-k'), 'long blocks stay plain and fast (' + (Date.now() - t0) + ' ms)');
  check(h.querySelector('.mdcopy')?.getAttribute('aria-label') === 'Copy code' && h.querySelector('.mdcopy').tagName === 'BUTTON', 'a code block has a named Copy button');
  // Copy in the task notes: copies the code, never opens the editor
  await call('PATCH', `/api/tasks/${T1}`, {content: 'Run:\n```sh\nnpm test\n```'});
  w.eval(`load().then(() => openDetail(${T1}))`); await sleep(600);
  copied = null;
  click(w, d.querySelector('#d-md .mdcopy')); await sleep(100);
  check(copied === 'npm test' && d.querySelector('#d-content').classList.contains('hidden'), 'Copy in the notes copies the code, the editor stays closed ' + copied);
  // file:line links
  const REPO = {github: ['https://github.com/acme/app', 'https://github.com/acme/app/blob/main/src/app.py#L42', 'https://github.com/acme/app/blob/main/static/app.js#L10-L20'],
    gitea: ['https://git.example.com/acme/app', 'https://git.example.com/acme/app/src/branch/main/src/app.py#L42', 'https://git.example.com/acme/app/src/branch/main/static/app.js#L10-L20'],
    forgejo: ['https://code.example.org/acme/app', 'https://code.example.org/acme/app/src/branch/main/src/app.py#L42', 'https://code.example.org/acme/app/src/branch/main/static/app.js#L10-L20'],
    gitlab: ['https://gitlab.com/acme/app', 'https://gitlab.com/acme/app/-/blob/main/src/app.py#L42', 'https://gitlab.com/acme/app/-/blob/main/static/app.js#L10-20'],
    bitbucket: ['https://bitbucket.org/acme/app', 'https://bitbucket.org/acme/app/src/main/src/app.py#lines-42', 'https://bitbucket.org/acme/app/src/main/static/app.js#lines-10:20']};
  const TXT = 'See src/app.py:42 and `static/app.js:10-20`, also path/to/file.go and app.js:7. Not 12:30, e.g. Node.js, nor https://x.io/a/b.py or example.com/index.html.';
  for (const [pv, [web, a, b]] of Object.entries(REPO)) {
    w.eval(`listById(${L}).repos = [{id: 1, full_name: 'acme/app', provider: '${pv}', web_url: '${web}', default_branch: 'main'}]`);
    const hh = frag(R(TXT, L)), hrefs = [...hh.querySelectorAll('a')].map(e => e.getAttribute('href'));
    check(hrefs.includes(a) && hrefs.includes(b), `${pv}: src/app.py:42 and \`static/app.js:10-20\` link to the file + line ` + hrefs.join(' '));
    check(hrefs.some(u => u.endsWith('/path/to/file.go')) && hrefs.some(u => /\/app\.js#(L|lines-)7$/.test(u)), `${pv}: path/to/file.go and app.js:7`);
    check(hrefs.length === 5 && hrefs.includes('https://x.io/a/b.py') && !hrefs.some(u => /Node\.js|12|index\.html/.test(u)), `${pv}: no links for 12:30, Node.js, example.com/…; the URL stays one link ` + hrefs.join(' '));
    check([...hh.querySelectorAll('a')].every(e => e.rel === 'noopener noreferrer' && e.target === '_blank'), `${pv}: external links get rel="noopener noreferrer"`);
  }
  check(!frag(R(TXT)).querySelector(`a[href*="app.py"]`), 'without a list (no repository): no file links');
  check(!frag(R(TXT, EM + 1000)).querySelector(`a[href*="app.py"]`), 'a list without a repository: no file links');
  w.eval(`listById(${L}).repos = [{id: 1, full_name: 'acme/app', provider: 'github', web_url: 'https://github.com/acme/app', default_branch: 'feat/x'}]`);
  check(frag(R('see ../etc/passwd.txt:1 and a/b c.py:3', L)).querySelectorAll('a').length === 1 && frag(R('`lib/x y.py`', L)).querySelectorAll('a').length === 0, 'no links for .. paths or paths with spaces');
  check(frag(R('src/app.py:1', L)).querySelector('a').getAttribute('href') === 'https://github.com/acme/app/blob/feat/x/src/app.py#L1', 'a branch with a slash keeps its path');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, theme = 'light', accent = '') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); ${accent ? `localStorage.setItem('tasks.accent', '"${accent}"');` : ''} return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const SMALL = sel => `(() => { const out = []; for (const e of document.querySelectorAll(${JSON.stringify(sel)})) { const r = e.getBoundingClientRect(); if (!r.width) continue; if (r.width < 43.5 || r.height < 43.5) out.push((e.id || e.dataset.pto || e.dataset.act || e.className) + ' ' + Math.round(r.width) + 'x' + Math.round(r.height)); } return out; })()`;
  const CONTRAST = `(() => { const lum = c => { const m = c.match(/[\\d.]+/g).slice(0, 3).map(Number).map(v => { v /= 255; return v <= .03928 ? v / 12.92 : ((v + .055) / 1.055) ** 2.4; }); return .2126 * m[0] + .7152 * m[1] + .0722 * m[2]; };
    const pres = [...document.querySelectorAll('#d-md pre.mdpre')]; if (!pres.length) return null; const out = {};
    for (const pre of pres) for (const s of pre.querySelectorAll('[class^="hl-"]')) { const lb = lum(getComputedStyle(pre).backgroundColor); const l1 = lum(getComputedStyle(s).color); out[s.className] = Math.round(((Math.max(l1, lb) + .05) / (Math.min(l1, lb) + .05)) * 100) / 100; } return out; })()`;
  await call('PATCH', `/api/tasks/${T1}`, {content: 'Code:\n```js\nconst x = "s"; // c\nreturn 42;\n```\n```diff\n@@ x\n-a\n+b\n```\n```html\n<a href="x">t</a>\n```\nSee src/app.py:42'});
  const MAXC = 'a-very-long-path/that/never/ends/'.repeat(4) + 'file.py';
  await call('PATCH', `/api/tasks/${OLD}`, {content: '```sh\n' + 'echo ' + 'x'.repeat(300) + '\n```\n' + MAXC + ':1'});
  for (const [vw, touch] of [[390, true], [1440, false]]) for (const th of ['light', 'dark']) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = `${vw} ${th}`;
    check(await ffLogin(o, th) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vw < 500 ? 844 : 900}});
    await o.nav(B + '#l/' + L); await ready(ev);
    await ev(`(() => { listById(${L}).repos = [{id: 1, full_name: 'acme/app', provider: 'github', web_url: 'https://github.com/acme/app', default_branch: 'main'}]; listModal(${L}); return 1; })()`); await sleep(600);
    await ev(`(() => { document.querySelector('.lmodal .lrepo').scrollIntoView({block: 'center'}); return 1; })()`);
    const lm = await ev(`(() => { const m = document.querySelector('.lmodal .mbox, .lmodal > div') || document.querySelector('.lmodal'); const s = document.querySelector('#l-ptype'); return {sw: document.documentElement.scrollWidth - innerWidth, mw: m.scrollWidth - m.clientWidth, sel: !!s && s.getBoundingClientRect().width > 0, repo: !document.querySelector('.lmodal .lrepo').hidden}; })()`);
    check(lm.sw <= 0 && lm.mw <= 1 && lm.sel && lm.repo, `${tag}: list dialog: Project type + Repository, nothing sideways ` + JSON.stringify(lm));
    if (touch) { const sm = await ev(SMALL('.lmodal #l-ptype')); check(!sm.length, `${tag}: the type select is 44 px ` + JSON.stringify(sm)); }
    await shot(`p2180-soft-${th}-${vw}-dialog.png`);
    await ev(`(() => { [...document.querySelectorAll('.modal')].forEach(m => m.remove()); return 1; })()`);
    await o.nav(B + '#t/' + T1); await ready(ev); await sleep(400);
    await ev(`(() => { listById(${L}).repos = [{id: 1, full_name: 'acme/app', provider: 'github', web_url: 'https://github.com/acme/app', default_branch: 'main'}]; renderDetail(); return 1; })()`); await sleep(300);
    const c = await ev(CONTRAST);
    check(c && Object.keys(c).length >= 5 && Object.values(c).every(v => v >= 4.5), `${tag}: code colours AA on the code background ` + JSON.stringify(c));
    const lk = await ev(`(() => { const a = [...document.querySelectorAll('#d-md a')].find(x => /app\\.py#L42/.test(x.href)); return a ? a.rel : null; })()`);
    check(lk === 'noopener noreferrer', `${tag}: the file link in the notes`);
    if (touch) {
      const sm = await ev(SMALL('#detail .mdcopy, #detail .gcopy .gbranch'));
      check(!sm.length, `${tag}: Copy + branch / reference buttons 44 px ` + JSON.stringify(sm));
    }
    const ov = await ev(`(() => ({o: document.documentElement.scrollWidth - innerWidth, d: (document.querySelector('#detail').scrollWidth - document.querySelector('#detail').clientWidth)}))()`);
    check(ov.o <= 0 && ov.d <= 1, `${tag}: task panel: nothing sideways ` + JSON.stringify(ov));
    await shot(`p2180-soft-${th}-${vw}-code.png`);
    // 2.18.0 review (R7): opening a DIFFERENT task starts at its top
    // 2.31.0 (#344): on a desktop the properties scroll in .dbody (the comments have their own area below), else #detail
    const sc = await ev(`(() => { const sx = () => { const d = document.querySelector('#detail'); return d.classList.contains('dsplit') ? d.querySelector('.dbody') : d; };
      const m = document.querySelector('#d-more'); if (m) m.open = true; sx().scrollTop = 600; const was = sx().scrollTop; openDetail(${OLD}); return {was, now: sx().scrollTop, split: document.querySelector('#detail').classList.contains('dsplit')}; })()`);
    check(sc.was > 0 && sc.now === 0, `${tag}: another task opens at its top ` + JSON.stringify(sc));
    await o.nav(B + '#t/' + OLD); await ready(ev); await sleep(400);
    const ov2 = await ev(`(() => ({o: document.documentElement.scrollWidth - innerWidth, d: (document.querySelector('#detail').scrollWidth - document.querySelector('#detail').clientWidth), pre: (() => { const p = document.querySelector('#d-md pre'); return p ? p.scrollWidth > p.clientWidth : null; })()}))()`);
    // 2.36.0 (#1119): code blocks in the description wrap like in the chat instead of scrolling sideways
    check(ov2.o <= 0 && ov2.d <= 1 && ov2.pre === false, `${tag}: a long code line wraps inside its block, a long path wraps ` + JSON.stringify(ov2));
  }, touch);
  // another accent: the code colours do not depend on it
  await firefox(async o => {
    const {cmd, ev, ctx} = o;
    for (const th of ['light', 'dark']) {
      check(await ffLogin(o, th, 'lime') === 200, 'lime: login');
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
      await o.nav(B + '#t/' + T1); await ready(ev); await sleep(400);
      const c = await ev(CONTRAST);
      check(c && Object.values(c).every(v => v >= 4.5), `${th} lime accent: code colours AA ` + JSON.stringify(c));
    }
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
