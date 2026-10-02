// 2.10.0 UI tests, own container (start.sh, isolated test database). jsdom: #441 Settings > Administration > Groups (list,
// create with members, sign-in group makes the members read-only), the share dialog's Groups part (shared directly with a
// role, through a folder read-only, add / change / remove), the folder menu "Share with a group…", assigning a task to a
// group (row menu, the panel's select with the groups), the group chip, "Assigned to me" with the group's tasks, the
// sidebar group under Team and its view, "Take it" (panel button, menu) with undo; #440 Settings > General > Day planning,
// Today's "Plan my day" / "Fill free time" (the timeline with events, fixed tasks, entries, "does not fit"; leaving an
// entry out, Apply = one undo step), "Let an agent plan" (only with an online agent) and the agent's dayplan proposal in
// the same timeline, the daily review card (counts, hide for today, #today/review), German texts, SW v79. 2.11.0: Apply
// sets only the planned start + duration (due dates untouched), "Does not fit today" is listed without a checkbox, the
// planned slot as a row chip + in the task panel (Unplan, undo), a planned task shows in Today. Then Firefox
// headless (ff.js): touch 360 x 780 / 390 x 844 and a mouse at 1280 x 800, dark + light: the planner, the review card, the
// group settings and the share dialog without horizontal overflow, 44 px touch targets.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2100_ui', check, shots: 'P2100_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const last = d => [...d.querySelectorAll('.modal')].pop();
const ds = d => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;  // local date (2.13.0: the UTC date failed between 0 and 2 o'clock)
const SMALL = sel => `(() => [...document.querySelectorAll('${sel}')].filter(e => e.offsetWidth && getComputedStyle(e).visibility !== 'hidden').map(e => {
  const b = e.getBoundingClientRect(); return [e.className || e.tagName, (e.textContent || '').trim().slice(0, 16), Math.round(b.width), Math.round(b.height)]; }).filter(x => x[2] < 43.5 || x[3] < 43.5))()`;

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:79|8[0-9])'/.test(SW), 'service worker cache v79');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', work_start: '08:00', work_end: '18:00'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CAROL = (await call('POST', '/api/users', {username: 'carol', display_name: 'Carol', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, CKB);
  const G1 = (await call('POST', '/api/admin/groups', {name: 'Office', members: [BOB]})).id;
  const L = (await call('POST', '/api/lists', {name: 'Office tasks'})).id;
  const FL = (await call('POST', '/api/lists', {name: 'Plans', folder: 'Team'})).id;
  await call('PUT', `/api/lists/${L}/groups/${G1}`, {role: 'edit'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Order paper', list_id: L})).id;

  // ================= Settings > Administration > Groups
  let w = await boot({user: 'alice'}), d = w.document;
  w.settingsModal('groups'); await sleep(400);
  const us = d.querySelector('[data-pane="users"]');
  check(us && !us.classList.contains('hidden') && us.querySelector('#s-groups-h'), 'focus "groups" opens Administration at Groups');
  check(/Office/.test(us.querySelector('#a-groups')?.textContent || '') && /Bob/.test(us.querySelector('#a-groups').textContent), 'the group with its members');
  click(w, us.querySelector('[data-grp="new"]'));
  let md = await until(() => d.querySelector('.grpmodal'));
  check(md && md.querySelector('#gr-name') && md.querySelectorAll('[data-gm]').length === 3, 'new group dialog: name + every person (alice, bob, carol)');
  md.querySelector('#gr-name').value = 'Field';
  md.querySelector(`[data-gm="${CAROL}"]`).checked = true;
  md.querySelector('#gr-oidc').value = 'field';
  md.querySelector('#gr-oidc').dispatchEvent(new w.Event('input', {bubbles: true}));
  check([...md.querySelectorAll('[data-gm]')].every(x => x.disabled), 'a sign-in group makes the members read-only');
  md.querySelector('#gr-oidc').value = '';
  md.querySelector('#gr-oidc').dispatchEvent(new w.Event('input', {bubbles: true}));
  click(w, md.querySelector('[data-m="ok"]'));
  check(await until(() => /Field/.test(us.querySelector('#a-groups')?.textContent || '') && /Carol/.test(us.querySelector('#a-groups').textContent)), 'created: Field with Carol');
  const G2 = (await call('GET', '/api/groups')).groups.find(g => g.name === 'Field').id;
  click(w, d.querySelector('.smodal [data-m="close"]')); await sleep(200);

  // ================= share dialog: Groups
  w.shareModal(L); await sleep(500);
  md = last(d);
  const sg = md.querySelector('#sh-groups');
  check(sg && /Office/.test(sg.textContent) && sg.querySelector(`[data-grole="${G1}"]`)?.value === 'edit', 'share dialog: Office with its role');
  check(/via a group/.test(md.querySelector('#l-members').textContent) && !md.querySelector(`#l-members [data-mrm="${BOB}"]`), 'bob shows as "via a group" (no remove button)');
  change(w, md.querySelector('#l-addgrp'), String(G2));
  click(w, md.querySelector('[data-m="share-grp"]'));
  check(await until(async () => ((await call('GET', `/api/lists/${L}/groups`)).groups || []).length === 2), 'add Field from the dialog');
  change(w, await until(() => last(d).querySelector(`[data-grole="${G2}"]`)), 'view');
  check(await until(async () => ((await call('GET', `/api/lists/${L}/groups`)).groups || []).find(x => x.group_id === G2)?.role === 'view'), 'change the group role');
  click(w, await until(() => last(d).querySelector(`[data-grm="${G2}"]`)));
  check(await until(async () => ((await call('GET', `/api/lists/${L}/groups`)).groups || []).length === 1), 'remove the group (confirmed)');
  click(w, last(d).querySelector('[data-m="close"]')); await sleep(200);
  // folder menu
  w.eval('folderGroupsModal("Team")'); await sleep(500);
  md = last(d);
  check(/Share the folder “Team”/.test(md.textContent) && md.querySelector('#fg-add'), 'folder dialog');
  change(w, md.querySelector('#fg-add'), String(G1));
  click(w, md.querySelector('[data-m="fg-add"]'));
  check(await until(async () => ((await call('GET', '/api/folders/groups?folder=Team')).groups || []).length === 1), 'folder shared with Office');
  click(w, last(d).querySelector('[data-m="close"]'));
  await sleep(500);
  check(w.eval(`JSON.stringify(listById(${FL}).groups)`).includes('"via":"Team"'), 'the folder list knows its group (via Team)');

  // ================= assign to a group
  w.go(`l/${L}`); await sleep(600);
  let row = d.querySelector(`.trow[data-id="${T1}"]`);
  w.eval(`assignMenu(document.querySelector('.trow[data-id="${T1}"]'), ${T1})`); await sleep(200);
  const mi = [...d.querySelectorAll('[role="menuitem"]')].find(b => /Office · Group/.test(b.textContent));
  check(mi, 'the row menu offers the list\'s group');
  if (mi) click(w, mi);
  check(await until(async () => (await call('GET', `/api/tasks/${T1}`)).assignee_group_id === G1), 'assigned to Office');
  await sleep(500);
  row = d.querySelector(`.trow[data-id="${T1}"]`);
  check(row && row.querySelector('.gchip') && /Office/.test(row.querySelector('.gchip').textContent), 'the row shows the group chip');
  w.openDetail(T1); await sleep(400);
  const sel = d.querySelector('#d-assignee');
  check(sel && [...sel.querySelectorAll('optgroup option')].some(o => o.value === `g:${G1}` && o.selected), 'panel select: the group is selected');
  w.close();

  // ================= bob: Assigned to me, sidebar group, Take it
  w = await boot({user: 'bob', hash: 'assigned'}); d = w.document;
  await sleep(300);
  check(d.querySelector(`.trow[data-id="${T1}"] .gchip.me`), 'bob: the group task is in "Assigned to me" (my group chip)');
  check(d.querySelector(`#side .sgrp[data-go="grp/${G1}"]`), 'sidebar Team: the group row');
  w.go(`grp/${G1}`); await sleep(500);
  check(d.querySelector(`.trow[data-id="${T1}"]`) && /Group Office/.test(d.querySelector('#top h1')?.textContent || ''), 'the group view lists its task');
  w.openDetail(T1); await sleep(400);
  click(w, d.querySelector('.dtake'));
  check(await until(async () => (await call('GET', `/api/tasks/${T1}`)).assignee_id === BOB), '"Take it": the task is bob\'s');
  await sleep(300);
  w.eval("histStep('undo')");
  check(await until(async () => { const t = await call('GET', `/api/tasks/${T1}`); return t.assignee_group_id === G1 && !t.assignee_id; }), 'undo: back to the group');
  w.close();

  // ================= #440 Settings > General > Day planning
  w = await boot({user: 'alice'}); d = w.document;
  w.settingsModal('dayplan'); await sleep(400);
  const gp = d.querySelector('[data-pane="general"]');
  check(gp && gp.querySelector('#s-plan-h') && gp.querySelector('#s-wfrom') && gp.querySelector('#s-wto') && gp.querySelector('#s-review'), 'General: Day planning (hours + review time)');
  check(!gp.querySelector('#s-plan-h').parentElement.querySelector('input[type="date"]'), 'no native date inputs');
  click(w, d.querySelector('.smodal [data-m="close"]')); await sleep(200);
  w.close();

  // tasks + one calendar event for TOMORROW (a full working day)
  const TM = ds(new Date(Date.now() + 86400000));
  const mk = async (title, x = {}) => (await call('POST', '/api/tasks', {title, list_id: L, ...x})).id;
  const FIX = await mk('Standup', {due: TM, due_time: '08:00', duration: 30});
  const A1 = await mk('Write report', {due: TM, priority: 5, duration: 90});
  const A2 = await mk('Call supplier', {due: TM});
  const A3 = await mk('Huge migration', {due: TM, duration: 900});
  w = await boot({user: 'alice'}); d = w.document;
  check(d.querySelector('.dpbar [data-act="dayplan"][data-mode="day"]') && d.querySelector('.dpbar [data-mode="fill"]'), 'Today: "Plan my day" + "Fill free time"');
  w.dayplanModal('day', TM); await sleep(700);
  md = d.querySelector('.dpm');
  const rows = [...md.querySelectorAll('.dprow')];
  check(rows.some(r => r.classList.contains('fixed') && /Standup/.test(r.textContent)), 'timeline: the timed task stays fixed');
  check(rows.some(r => r.classList.contains('plan') && /Write report/.test(r.textContent) && /08:30/.test(r.textContent)), 'timeline: the report right after the standup');
  check(rows.some(r => r.classList.contains('plan') && /Call supplier/.test(r.textContent) && /≈/.test(r.textContent)), 'no duration: estimated (≈ 30m)');
  const nf = rows.find(r => r.classList.contains('nofit') && /Huge migration/.test(r.textContent));
  check(nf && !nf.querySelector('.ppc') && /Does not fit today/.test(md.textContent), '"Does not fit today": the 15 h task, only listed (no checkbox)');
  check(/due dates and deadlines stay as they are/.test(md.textContent), 'the hint says due dates stay');
  check(/working hours 08:00–18:00/.test(md.querySelector('.dpsum').textContent), 'summary with the working hours');
  check(!md.querySelector('[data-dp="agent"]'), 'no agent online: no "Let an agent plan"');
  const callRow = rows.find(r => /Call supplier/.test(r.textContent));
  callRow.querySelector('.ppc').checked = false;
  callRow.querySelector('.ppc').dispatchEvent(new w.Event('change', {bubbles: true}));
  check(/Apply 1 entry/.test(md.querySelector('[data-dp="apply"]').textContent), 'leaving one out: Apply 1 entry (nofit is not an entry)');
  click(w, md.querySelector('[data-dp="apply"]'));
  check(await until(async () => (await call('GET', `/api/tasks/${A1}`)).plan_start === TM + 'T08:30'), 'applied: the report planned at 08:30');
  const a1 = await call('GET', `/api/tasks/${A1}`);
  check(a1.due === TM && a1.due_time === null && a1.duration === 90, `due date + time untouched, duration kept (${a1.due} ${a1.due_time})`);
  check((await call('GET', `/api/tasks/${A2}`)).plan_start === null, 'the left-out task is unchanged');
  const huge = await call('GET', `/api/tasks/${A3}`);
  check(huge.due === TM && huge.plan_start === null, `the huge task is not moved (${huge.due})`);
  await sleep(300);
  w.eval("histStep('undo')");
  check(await until(async () => (await call('GET', `/api/tasks/${A1}`)).plan_start === null), 'one undo takes the whole plan back');
  w.close();
  // a task planned for today: in Today (even when due later), the row chip, the panel line, Unplan (undo)
  const LATER = await mk('Later report', {due: ds(new Date(Date.now() + 5 * 86400000)), duration: 30});
  await call('PATCH', `/api/tasks/${LATER}`, {plan_start: ds(new Date()) + 'T23:30'});
  w = await boot({user: 'alice'}); d = w.document;
  const prow = await until(() => [...d.querySelectorAll('.trow')].find(r => /Later report/.test(r.textContent)));
  check(prow && prow.querySelector('.pchip') && /23:30|11:30\s?PM/i.test(prow.querySelector('.pchip').textContent), 'Today: the planned task with its slot chip (locale time)');
  w.openDetail(LATER); await sleep(400);
  const dpl = d.querySelector('#detail .dplan');
  check(dpl && /Planned: (23:30|11:30\s?PM)/i.test(dpl.textContent) && dpl.querySelector('[data-act="unplan"]'), 'panel: "Planned: 23:30" + Unplan');
  click(w, dpl.querySelector('[data-act="unplan"]'));
  check(await until(async () => (await call('GET', `/api/tasks/${LATER}`)).plan_start === null), 'Unplan clears the slot only');
  check((await call('GET', `/api/tasks/${LATER}`)).due === ds(new Date(Date.now() + 5 * 86400000)), 'Unplan keeps the due date');
  await sleep(300); w.eval("histStep('undo')");
  check(await until(async () => (await call('GET', `/api/tasks/${LATER}`)).plan_start === ds(new Date()) + 'T23:30'), 'undo brings the slot back');
  await call('DELETE', `/api/tasks/${LATER}`);
  w.close();

  // agent: online (never polled = cannot tell = offered), its dayplan proposal in the same timeline
  const ag = await call('POST', '/api/admin/agents', {username: 'planner', display_name: 'Planner'});
  await call('PATCH', `/api/admin/agents/${ag.id}`, {proposals: 'all'});
  w = await boot({user: 'alice'}); d = w.document;
  w.dayplanModal('day', TM); await sleep(700);
  md = d.querySelector('.dpm');
  check(md.querySelector('[data-dp="agent"]'), 'an agent online: "Let an agent plan"');
  click(w, md.querySelector('[data-dp="agent"]'));
  const job = await until(async () => ((await call('GET', '/api/agents/jobs')).jobs || []).find(j => j.kind === 'dayplan'));
  check(job, 'the request reached the agent (a dayplan job)');
  const at = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const r = await fetch(B + `api/v1/agent/jobs/${job.id}/proposal`, {method: 'POST', headers: at, body: JSON.stringify({kind: 'dayplan', summary: 'Deep work first',
    items: [{task_id: A2, start: '09:00', note: 'quick'}, {task_id: A1, start: '10:00'}], defer: [{task_id: A3, to: null}]})});
  check(r.status === 201, `agent proposal accepted (${r.status})`);
  w.propOpen(job.id); await sleep(700);
  md = d.querySelector('.ppm');
  check(md && md.querySelectorAll('.dprow.plan').length === 2 && md.querySelector('.dprow.fixed') && md.querySelector('.dprow.nofit'), 'the proposal shows as the same timeline');
  check(/Deep work first/.test(md.textContent) && /Does not fit today/.test(md.textContent) && !md.querySelector('.dprow.nofit .ppc'), 'summary + "Does not fit today" (old defer answer, only listed)');
  click(w, md.querySelector('[data-pp="apply"]'));
  check(await until(async () => (await call('GET', `/api/tasks/${A2}`)).plan_start === TM + 'T09:00'), 'applied as alice (planned start)');
  check((await call('GET', `/api/tasks/${A3}`)).due === TM && (await call('GET', `/api/tasks/${A2}`)).due === TM, 'no due date moved by the agent plan');
  w.close();

  // ================= the daily review card
  const D1 = await mk('Done thing', {due: ds(new Date())});
  await call('POST', `/api/tasks/${D1}/complete`, {});
  w = await boot({user: 'alice', hash: 'today/review'}); d = w.document;
  const card = await until(() => d.querySelector('.rvcard'));
  check(card && /Daily review/.test(card.textContent) && /Done thing/.test(card.textContent), 'review card: done today');
  check(card && card.querySelector('[data-act="dayplan"][data-day]'), 'review card: "Plan tomorrow"');
  click(w, card.querySelector('[data-act="review-hide"]'));
  w.go('today'); await sleep(400);
  check(!d.querySelector('.rvcard') || /review/.test(w.location.hash), 'hidden for today');
  w.close();

  // German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice'}); d = w.document;
  check(/Tag planen/.test(d.querySelector('.dpbar')?.textContent || '') && /Freie Zeit füllen/.test(d.querySelector('.dpbar').textContent), 'German: Tag planen / Freie Zeit füllen');
  w.settingsModal('groups'); await sleep(400);
  check(/Gruppen/.test(d.querySelector('#s-groups-h')?.textContent || ''), 'German: Gruppen');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= Firefox: real layout
  await mk('Tidy inbox', {due: TM, duration: 20});  // something left to plan
  for (const touch of [true, false]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
      let nr = 0;
      for (const [vw, vh] of touch ? [[360, 780], [390, 844]] : [[1280, 800]]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
        for (const theme of ['dark', 'light']) {
          await nav(B + 'static/icon.svg');
          await ev(`(() => { localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
          await nav(B + '?v=' + (++nr) + '#today/review');
          for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300);
          await sleep(1200);
          const lay = await ev(`(() => { const c = document.querySelector('.rvcard'), b = document.querySelector('.dpbar');
            return {card: !!(c && c.offsetWidth), bar: !!(b && b.offsetWidth), doc: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1}; })()`);
          check(lay.card && lay.bar && lay.doc, `${vw}px ${theme}: Today with the review card + planner buttons, no horizontal overflow ${JSON.stringify(lay)}`);
          if (touch) {
            const small = await ev(SMALL('.dpbar .btn, .rvcard .btn, .rvhd .iconbtn'));
            check(!small.length, `${vw}px ${theme}: Today buttons >= 44 px ${JSON.stringify(small)}`);
          }
          if (vw === 390 || vw === 1280) await shot(`p2100-today-${vw}-${theme}.png`);
          await ev(`(() => { dayplanModal('day', '${TM}'); return 1; })()`); await sleep(1200);
          const pl = await ev(`(() => { const m = document.querySelector('.dpm .card'); const r = document.querySelector('.dpm .dprow.plan');
            return {sw: m.scrollWidth, cw: m.clientWidth, row: !!(r && r.offsetWidth), doc: document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1}; })()`);
          check(pl.row && pl.sw <= pl.cw + 1 && pl.doc, `${vw}px ${theme}: planner without horizontal overflow ${JSON.stringify(pl)}`);
          if (touch) {
            const small = await ev(SMALL('.dpm .foot .btn, .dpm .seg button, .dpm [data-dp="close"], .dpm .ppcl'));
            check(!small.length, `${vw}px ${theme}: planner targets >= 44 px ${JSON.stringify(small)}`);
          }
          if (vw === 390 || vw === 1280) await shot(`p2100-plan-${vw}-${theme}.png`);
          await ev(`(() => { document.querySelector('.dpm')?.remove(); settingsModal('groups'); return 1; })()`); await sleep(900);
          const gs = await ev(`(() => { const m = document.querySelector('.smodal .spanes'); const s = document.querySelector('#a-groups');
            return {sw: m.scrollWidth, cw: m.clientWidth, g: !!(s && s.offsetWidth)}; })()`);
          check(gs.g && gs.sw <= gs.cw + 1, `${vw}px ${theme}: Groups settings without horizontal overflow ${JSON.stringify(gs)}`);
          if (touch) {
            const small = await ev(SMALL('#a-groups .iconbtn, [data-grp="new"]'));
            check(!small.length, `${vw}px ${theme}: group buttons >= 44 px ${JSON.stringify(small)}`);
          }
          if (vw === 390 || vw === 1280) await shot(`p2100-groups-${vw}-${theme}.png`);
          await ev(`(() => { document.querySelector('.smodal')?.remove(); shareModal(${L}); return 1; })()`); await sleep(900);
          const sh = await ev(`(() => { const m = [...document.querySelectorAll('.modal .card')].pop(); const g = document.querySelector('#sh-groups');
            return {sw: m.scrollWidth, cw: m.clientWidth, g: !!(g && g.offsetWidth)}; })()`);
          check(sh.g && sh.sw <= sh.cw + 1, `${vw}px ${theme}: share dialog with groups without overflow ${JSON.stringify(sh)}`);
          if (touch) {
            const small = await ev(SMALL('#sh-groups .iconbtn, #sh-groups select'));
            check(!small.length, `${vw}px ${theme}: share-group controls >= 44 px ${JSON.stringify(small)}`);
          }
          await ev(`(() => { document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
        }
      }
    }, touch);
  }

  console.log(`p2100_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})();
