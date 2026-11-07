// 2.634.0 B UI tests (#4774), own container (start.sh), invented names only. jsdom:
// kalmido-suite: fresh
// #4774 the dialog of a new rule shows "Templates" on top: a click fills name, when and then; saving makes a normal rule
//       (the server has it with the template's trigger / action). Columns are proposed by name (English / German, any
//       case); none fits = the field stays empty ("Select a column") and Save asks for it instead of saving. "Created ->
//       assign to me" picks the person; "Comes into Review -> assign" leaves the person to pick. Sorted by project type:
//       software Review / Done first, agency Approval / Billing (its sections). The template "-> mark as done" only when
//       the dialog offers the action "done" (#4781); the edit dialog of a rule has no templates.
// A person without an organisation (tests/freelancer_fixture.py): the templates in an own private list (freelancer-matrix: lists).
// Firefox 320 px (touch): the dialog with its templates does not overflow sideways, every chip inside the card, screenshot.
// Screenshots with P2634B_SHOTS=<dir>.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2634_b_rules_tpl_ui', check, shots: 'P2634B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Acme', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,fields,kanban'});
  const st = await call(CA, 'GET', '/api/state'), ORG = st.me.workspaces[0].id, ME = st.me.id;
  const SW = (await call(CA, 'POST', '/api/lists', {name: 'App', ptype: 'software', sections: true, org_id: ORG})).id;
  const AG = (await call(CA, 'POST', '/api/lists', {name: 'Campaign', ptype: 'agency', sections: true, org_id: ORG})).id;
  const PL = (await call(CA, 'POST', '/api/lists', {name: 'Plain', org_id: ORG})).id;
  const DE = (await call(CA, 'POST', '/api/lists', {name: 'Mixed', org_id: ORG})).id;
  const deFertig = (await call(CA, 'POST', '/api/sections', {list_id: DE, name: 'fertig'})).id;  // German, lower case
  const deWip = (await call(CA, 'POST', '/api/sections', {list_id: DE, name: 'In Arbeit'})).id;
  const secs = async lid => Object.fromEntries(((await call(CA, 'GET', '/api/state')).sections || []).filter(s => s.list_id === lid).map(s => [s.name, s.id]));
  const SWS = await secs(SW), AGS = await secs(AG);
  check(SWS.Review && SWS.Done && AGS.Approval && AGS.Billing, 'the type sections are there ' + JSON.stringify([SWS, AGS]));
  const rules = async lid => (await call(CA, 'GET', `/api/lists/${lid}/rules`)).rules || [];

  const w = await boot({user: 'alice', hash: 'l/' + SW}), d = w.document;
  const hasDone = w.eval(`RUL_ACT.some(x => x[0] === 'done')`);
  const dl = () => d.querySelector('.rul-dlg');
  const chips = () => [...(dl()?.querySelectorAll('[data-rul-tpl]') || [])];
  const chip = k => dl()?.querySelector(`[data-rul-tpl="${k}"]`);
  const val = id => dl()?.querySelector('#' + id)?.value;
  const picking = id => !!dl()?.querySelector('#' + id)?.selectedOptions[0]?.dataset.rulPick;
  const closeAll = () => d.querySelectorAll('.modal').forEach(m => m.remove());
  const open = async lid => {
    closeAll();
    w.eval(`listModal(${lid})`);
    await until(() => d.querySelector('#l-rules [data-rul-add]'));
    click(w, d.querySelector('#l-rules [data-rul-add]'));
    await until(() => dl());
  };
  const save = async lid => { const n = (await rules(lid)).length; click(w, dl().querySelector('[data-m="save"]')); await until(() => !dl()); return (await rules(lid)).length === n + 1; };

  // ---- software: the templates, Review / Done first
  await open(SW);
  check(!!dl().querySelector('.rul-tpl .mschips'), '#4774: the dialog of a new rule shows the templates on top');
  const ks = chips().map(b => b.dataset.rulTpl);
  const first = hasDone ? ['review_assign', 'done_move', 'done_mark'] : ['review_assign', 'done_move'];
  check(ks.slice(0, first.length).join() === first.join(), '#4774: software: Review / Done first ' + ks);
  check(['reopen_move', 'created_me', 'due_prio', 'urgent_prio'].every(k => ks.includes(k)), '#4774: the start set ' + ks);
  check(ks.includes('done_mark') === hasDone, `#4774: "mark as done" only with the action done (offered: ${hasDone}) ` + ks);
  check(/Review/.test(chip('review_assign')?.textContent) && /Done/.test(chip('done_move')?.textContent), '#4774: the labels name the column ' + chip('done_move')?.textContent);

  // Completed -> move to Done: fills the dialog, saving makes a normal rule
  click(w, chip('done_move'));
  check(val('rul-trig') === 'done' && val('rul-act') === 'move' && val('rul-list') === String(SW) && val('rul-sec') === String(SWS.Done),
    '#4774: "Completed -> move to Done" fills when / then / column ' + [val('rul-trig'), val('rul-act'), val('rul-list'), val('rul-sec')]);
  check(/Completed/.test(val('rul-name')) && chip('done_move').getAttribute('aria-pressed') === 'true', '#4774: the name is filled, the chip is marked');
  check(await save(SW), '#4774: saved as a rule');
  let rs = await rules(SW), x = rs[rs.length - 1];
  check(x && x.trigger.kind === 'done' && x.action.kind === 'move' && x.action.section_id === SWS.Done && !('template' in x), '#4774: a normal rule on the server ' + JSON.stringify(x));

  // Created -> assign to me
  await open(SW);
  click(w, chip('created_me'));
  check(val('rul-trig') === 'created' && val('rul-act') === 'assign' && val('rul-user') === String(ME), '#4774: "Created -> assign to me" picks me ' + val('rul-user'));
  check(await save(SW), '#4774: assign-to-me saved');
  rs = await rules(SW); x = rs[rs.length - 1];
  check(x && x.trigger.kind === 'created' && x.action.user_id === ME, '#4774: the rule assigns to me ' + JSON.stringify(x));

  // Comes into Review -> assign to a person: the column proposed, the person left open; Save asks for it
  await open(SW);
  click(w, chip('review_assign'));
  check(val('rul-trig') === 'section' && val('rul-tsec') === String(SWS.Review), '#4774: the column Review proposed ' + val('rul-tsec'));
  check(picking('rul-user') && val('rul-user') === '', '#4774: the person stays empty to pick');
  const n0 = (await rules(SW)).length;
  click(w, dl().querySelector('[data-m="save"]'));
  await until(() => !dl().querySelector('#rul-err').hidden);
  check(!!dl() && /Select a person/.test(dl().querySelector('#rul-err').textContent), '#4774: Save asks for the person instead of saving');
  check((await rules(SW)).length === n0, '#4774: nothing saved without the person');
  change(w, dl().querySelector('#rul-user'), String(ME));
  check(await save(SW), '#4774: saved once the person is picked');

  // Due today -> priority high; tag Urgent -> no such tag: the tag stays empty
  await open(SW);
  click(w, chip('due_prio'));
  check(val('rul-trig') === 'due' && val('rul-act') === 'priority' && val('rul-prio') === 'high', '#4774: "Due today -> priority high"');
  click(w, chip('urgent_prio'));
  check(val('rul-trig') === 'ltag' && picking('rul-ttag') && val('rul-prio') === 'high', '#4774: no tag Urgent: the tag stays empty');
  check(chips().filter(b => b.classList.contains('on')).length === 1 && chip('urgent_prio').classList.contains('on'), '#4774: one chip marked');

  // "mark as done": only with the action; offered -> fills "Comes into Done"
  if (!hasDone) { closeAll(); w.eval(`RUL_ACT.push(['done', 'Mark it as done'])`); }  // as after #4781
  await open(SW);
  check(!!chip('done_mark'), '#4774: with the action done the template "-> mark as done" shows');
  click(w, chip('done_mark'));
  check(val('rul-trig') === 'section' && val('rul-tsec') === String(SWS.Done) && val('rul-act') === 'done', '#4774: "Comes into Done -> mark as done" fills ' + [val('rul-tsec'), val('rul-act')]);
  if (!hasDone) { closeAll(); w.eval(`RUL_ACT.splice(RUL_ACT.findIndex(x => x[0] === 'done'), 1)`); }

  // ---- agency: Approval / Billing
  await open(AG);
  check(chips().map(b => b.dataset.rulTpl)[0] === 'review_assign' && /Approval/.test(chip('review_assign').textContent), '#4774: agency: Approval first ' + chip('review_assign')?.textContent);
  click(w, chip('done_move'));
  check(val('rul-sec') === String(AGS.Billing) && /Billing/.test(chip('done_move').textContent), '#4774: agency: completed -> Billing');
  click(w, chip('review_assign'));
  check(val('rul-tsec') === String(AGS.Approval), '#4774: agency: comes into Approval');

  // ---- no fitting column: the field stays empty; German names fit
  await open(PL);
  click(w, chip('done_move'));
  check(picking('rul-sec') && val('rul-sec') === '', '#4774: no column Done: the column stays empty to pick');
  const n1 = (await rules(PL)).length;
  click(w, dl().querySelector('[data-m="save"]'));
  await until(() => !dl().querySelector('#rul-err').hidden);
  check(/Select a column/.test(dl().querySelector('#rul-err').textContent) && (await rules(PL)).length === n1, '#4774: Save asks for the column');
  await open(DE);
  click(w, chip('done_move'));
  check(val('rul-sec') === String(deFertig), '#4774: "fertig" fits Done (German, any case)');
  click(w, chip('reopen_move'));
  check(val('rul-trig') === 'reopen' && val('rul-sec') === String(deWip), '#4774: "In Arbeit" fits In progress');

  // ---- the edit dialog has no templates
  closeAll();
  w.eval(`listModal(${SW})`);
  await until(() => d.querySelector('#l-rules [data-rul-edit]'));
  click(w, d.querySelector('#l-rules [data-rul-edit]'));
  await until(() => dl());
  check(!dl().querySelector('.rul-tpl'), '#4774: editing a rule shows no templates');
  closeAll(); w.close();

  // ---- a person without an organisation: an own private list (freelancer-matrix: lists)
  const fr = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fr.status === 200 && fr.id, 'freelancer created');
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,fields'});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  const FL = (await call(CF, 'POST', '/api/lists', {name: 'Own things'})).id;
  const wf = await boot({user: 'frida', hash: 'l/' + FL}), df = wf.document;
  wf.eval(`listModal(${FL})`);
  await until(() => df.querySelector('#l-rules [data-rul-add]'));
  click(wf, df.querySelector('#l-rules [data-rul-add]'));
  await until(() => df.querySelector('.rul-dlg [data-rul-tpl="due_prio"]'));
  click(wf, df.querySelector('[data-rul-tpl="due_prio"]'));
  click(wf, df.querySelector('.rul-dlg [data-m="save"]'));
  await until(() => !df.querySelector('.rul-dlg'));
  const fx = (await call(CF, 'GET', `/api/lists/${FL}/rules`)).rules || [];
  check(fx.length === 1 && fx[0].trigger.kind === 'due' && fx[0].action.priority === 'high', '#4774: freelancer: a template saved in an own list ' + JSON.stringify(fx));
  wf.close();

  // ================= Firefox: 320 px, touch
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '320';
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}});
    await o.nav(B + '#today');
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#top h1, .agview')`).catch(() => false)); i++) await sleep(300);
    await ev(`(() => { listModal(${SW}); return 1; })()`);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#l-rules [data-rul-add]')`)); i++) await sleep(200);
    await ev(`(() => { document.querySelector('#l-rules [data-rul-add]').click(); return 1; })()`);
    for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('.rul-dlg [data-rul-tpl]')`)); i++) await sleep(200);
    await ev(`(() => { document.querySelector('.rul-dlg [data-rul-tpl="review_assign"]').click(); return 1; })()`);
    const g = await ev(`(() => { const c = document.querySelector('.rul-dlg .card'); if (!c) return null; const r = c.getBoundingClientRect();
      const out = [...c.querySelectorAll('[data-rul-tpl]')].filter(b => { const x = b.getBoundingClientRect(); return x.left < r.left - 0.5 || x.right > r.right + 0.5; }).length;
      return {left: r.left, right: r.right, out, n: c.querySelectorAll('[data-rul-tpl]').length, wide: document.documentElement.scrollWidth <= 320, inner: c.scrollWidth <= c.clientWidth + 1}; })()`);
    check(g && g.n >= 6 && g.left >= 0 && g.right <= 320 && g.wide && g.inner && g.out === 0, `${tag}: #4774 the dialog with its templates fits 320 px ` + JSON.stringify(g));
    await shot('p2634b-320-rule-templates.png');
  }, true);

  console.log(`p2634_b_rules_tpl_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
