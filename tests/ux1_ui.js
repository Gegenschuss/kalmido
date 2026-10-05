// 1.5 (UX1) UI tests (jsdom), fresh DB: the usability package. Settings save themselves and land in the undo history
// (select, text on blur / Enter / pause, invalid numbers refused, the display name, modules, pending text saved on close,
// "Saved · Undo", no Save buttons); the Modules page (sections, groups, one sentence each, admin "for everyone", focus
// options); the slim checklist panel (title, note, assignee only when shared; data kept); comments only in shared lists
// (old ones read-only and folded); "Archive" instead of "Delete" (undo, delete for good only from the archive, the dialog
// names what is lost); the app's own confirm / prompt dialogs (never window.confirm / prompt; Esc = no, danger action,
// undoable things ask nothing); the own date and time pickers (keyboard and touch, German and English: month names,
// first weekday, 12 / 24 h, typing a time); phones: undo / redo in the header "…" menu, no ← →; the Fold layout (sidebar
// folds into the rail while the task panel is open, the rail opens it as an overlay); the touch-target rules in the CSS.
const {boot, errs, sleep, B, login, clientSource} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const st = (ck = CK) => call('GET', '/api/state', null, ck);
const until = async (fn, ms = 5000) => { const t0 = Date.now(); while (Date.now() - t0 < ms) { if (await fn()) return true; await sleep(80); } return false; };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const key = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const closeW = async w => { try { w.eval('if (S.sel) closeDetail()'); } catch { /* gone */ } await sleep(1000); w.close(); };  // let late loads (timeline, deps, time) finish first
const today = () => { const d = new Date(); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
const addD = (s, n) => { const [y, m, d] = s.split('-').map(Number); const x = new Date(y, m - 1, d + n); return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, '0')}-${String(x.getDate()).padStart(2, '0')}`; };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const BK = await login('bob');
  await call('PATCH', '/api/settings', {features: 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,comments'});
  await call('PATCH', '/api/settings', {lang: 'de'}, BK);
  const WORK = (await call('POST', '/api/lists', {name: 'Work'})).id;
  const SHOP = (await call('POST', '/api/lists', {name: 'Shopping', kind: 'checklist'})).id;
  const TEAM = (await call('POST', '/api/lists', {name: 'Team', kind: 'project'})).id;
  await call('PUT', `/api/lists/${TEAM}/members`, {user_id: BOB, role: 'edit'});
  const mk = async (title, list_id, extra = {}) => (await call('POST', '/api/tasks', {title, list_id, ...extra})).id;
  const t1 = await mk('Pay invoice', WORK, {tags: ['money'], url: 'https://example.org/x'});
  const milk = await mk('Milk', SHOP, {tags: ['dairy'], url: 'https://example.org/milk', content: 'the good one'});
  const plan = await mk('Plan trip', TEAM);

  // ================= Settings: autosave + undo (U03)
  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.__dialogs = 'manual';
  const smd = () => d.querySelector('.modal.smodal');
  w.eval(`settingsModal('notify')`); await sleep(300);
  check(!smd().querySelector('[data-m="save"]') && !smd().querySelector('.sfoot') && !smd().querySelector('.sdirty'), 'no Save / Close footer, no "unsaved" marker');
  const defrem = smd().querySelector('#s-defrem'), before = (await st()).settings.default_reminder;
  defrem.value = '15'; defrem.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await st()).settings.default_reminder === '15'), 'select saves at once');
  check(smd().querySelector('.ssaved.on') && /Saved/.test(smd().querySelector('.ssaved').textContent) && smd().querySelector('.ssaved [data-m="s-undo"]'), '"Saved · Undo" shows in the header');
  check(w.eval('HIST.undo[HIST.undo.length - 1].label') === 'Changed setting: Default reminder', 'history step "Changed setting: Default reminder": ' + w.eval('HIST.undo[HIST.undo.length - 1]?.label'));
  click(w, smd().querySelector('[data-m="s-undo"]'));
  check(await until(async () => (await st()).settings.default_reminder === before), 'Undo in the header puts the old value back');
  check(await until(() => smd().querySelector('#s-defrem').value === before), 'the dialog shows the old value again');
  check(w.eval('HIST.redo.length') === 1, 'the step can be redone');
  await w.eval(`histStep('redo')`);
  check((await st()).settings.default_reminder === '15' && smd().querySelector('#s-defrem').value === '15', 'redo: value and control in step');
  // time field (own picker) saves through its hidden input
  w.eval(`dpSet(document.querySelector('#s-digest'), '06:45')`);
  check(await until(async () => (await st()).settings.digest_time === '06:45'), 'time field saves at once');
  // numbers: on change (blur), invalid ones are refused and reverted
  smd().remove();
  w.eval(`settingsModal('modules')`); await sleep(300);
  let md = [...d.querySelectorAll('.modal.smodal')].pop();
  const pf = md.querySelector('#s-pf'), pf0 = (await st()).settings.pomo_focus;
  pf.value = '0'; pf.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(400);
  check((await st()).settings.pomo_focus === pf0 && pf.value === String(pf0), 'invalid number (0 minutes) not saved, field reverted');
  pf.value = '42'; pf.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(async () => (await st()).settings.pomo_focus === '42', 3000), 'number saves after a short pause while typing');
  const cur = md.querySelector('#s-tcur'); cur.value = ' CHF '; key(w, cur, 'Enter');
  check(await until(async () => (await st()).settings.time_currency === 'CHF'), 'text field saves on Enter (trimmed)');
  // modules
  const hab = md.querySelector('[data-feat="habits"]'); hab.checked = false; hab.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => !(await st()).settings.features.split(',').includes('habits')), 'module switch saves at once');
  check(await until(() => !d.querySelector('#side [data-go="habits"]')), 'the module disappears from the sidebar');
  check(/Habits off/.test(w.eval('HIST.undo[HIST.undo.length - 1].label')), 'history: "Changed setting: Habits off"');
  md.remove(); await w.eval(`histStep('undo')`);
  check((await st()).settings.features.split(',').includes('habits') && d.querySelector('#side [data-go="habits"]'), 'undo (← / Ctrl+Z path) brings the module back');
  // display name: pending text is saved when the dialog closes
  w.eval(`settingsModal('account')`); await sleep(300); md = [...d.querySelectorAll('.modal.smodal')].pop();
  check(!md.querySelector('[data-acc="name"]'), 'no separate "Save" for the display name');
  const nm = md.querySelector('#a-name'); nm.value = 'Alice B.'; nm.dispatchEvent(new w.Event('input', {bubbles: true}));
  md.remove();
  check(await until(async () => (await call('GET', '/api/me')).display_name === 'Alice B.'), 'closing the dialog saves what was typed');
  check(/Display name/.test(w.eval('HIST.undo[HIST.undo.length - 1].label')), 'display name change in the history');
  await w.eval(`histStep('undo')`);
  check((await call('GET', '/api/me')).display_name === 'Alice', 'undo of the display name');
  // appearance (per device) goes into the history too
  w.eval(`settingsModal('look')`); await sleep(300); md = [...d.querySelectorAll('.modal.smodal')].pop();
  click(w, md.querySelector('[data-look="theme"][data-v="light"]'));
  check(d.documentElement.dataset.theme === 'light' && /Color scheme/.test(w.eval('HIST.undo[HIST.undo.length - 1].label')), 'theme applies at once and is a history step');
  await w.eval(`histStep('undo')`);
  check(d.documentElement.dataset.theme !== 'light', 'undo of the theme');
  md.remove();

  // ================= Settings > Modules (U04, U05, U06)
  w.eval(`settingsModal('layout')`); await sleep(300); md = [...d.querySelectorAll('.modal.smodal')].pop();
  const secs = [...md.querySelectorAll('.snav [data-sec]')].map(b => b.dataset.sec);
  check(JSON.stringify(secs) === JSON.stringify(['account', 'general', 'look', 'modules', 'notify', 'integr', 'data', 'users', 'help']), 'sections (2.7.0: no Agents page without the module and agents): ' + secs);
  check(md.querySelector('.snav .on')?.dataset.sec === 'modules', 'old link "layout" opens Modules');
  const mp = md.querySelector('[data-pane="modules"]');
  const rows = [...mp.querySelectorAll('[data-modrow]')];
  check(rows.length >= 12 && rows.every(r => r.querySelector('small')?.textContent.trim().length > 10), `every module with one sentence (${rows.length})`);
  check([...mp.querySelectorAll('h4')].map(h => h.textContent).join('|') === 'Views|For you|Projects and team' || mp.querySelectorAll('h4').length >= 3, 'modules grouped');
  check(mp.querySelector('#s-collaball') && mp.querySelector('#s-timeall'), 'admin: "for everyone" next to collaboration and time tracking');
  check(!md.querySelector('[data-pane="users"] #s-collaball'), 'no second copy under Administration');
  check(mp.querySelector('[data-modrow="pomo"] details #s-pf') && mp.querySelector('[data-modrow="time"] details #s-trnd'), 'focus and time options folded under their module');
  check(!md.querySelector('#s-nav') && !md.querySelector('[data-pane="layout"]') && !md.querySelector('[data-pane="collab"]'), 'the duplicate module list and the Collaboration tab are gone');
  check(md.querySelector('[data-pane="look"] #s-tabbar'), 'tab bar under Appearance');
  check(md.querySelector('[data-pane="account"] details.sdev [data-m="go-share"]') && !md.querySelector('[data-acc="token"]'), 'API tokens folded under "Advanced · for developers"; 2.7.0 (#405 S3): the upload token only under Share from your phone, a link here');
  // 1.9.0: /drop moved out of "Advanced" into Integrations > Share from your phone (the address to copy)
  check(md.querySelector('[data-pane="integr"] #s-share-h') && /^https?:\/\/[^/]+$/.test(md.querySelector('[data-pane="integr"] #s-dropurl')?.value || ''), 'server address (2.0.2: without /drop) in Integrations > Share from your phone');
  const prio = [...md.querySelectorAll('#s-pushprio option')].map(o => o.textContent);
  check(prio.length === 3 && prio.every(x => !/\d/.test(x)), 'push priority in words: ' + prio);
  md.remove();
  await closeW(w);
  let wb = await boot({user: 'bob'}); let db = wb.document;
  wb.eval(`settingsModal('modules')`); await sleep(300);
  const bm = db.querySelector('.smodal');
  check(!bm.querySelector('#s-collaball') && ![...bm.querySelectorAll('.snav [data-sec]')].some(b => b.dataset.sec === 'users'), 'non-admin: no server switches, no Administration');
  check(/Module/.test(bm.querySelector('.snav .on').textContent) && /Ansichten/.test(bm.textContent), 'German: Module / Ansichten');
  await closeW(wb);

  // ================= 2.7.2 (#414): the checklist type is gone (U07's slim panel with it): an item of a list with
  // "Show completed at the bottom" is a full task
  w = await boot({user: 'alice', hash: 'l/' + SHOP}); d = w.document;
  w.eval(`openDetail(${milk})`); await sleep(300);
  const det = d.querySelector('#detail');
  check(det.querySelector('#d-title') && det.querySelector('#d-content')?.getAttribute('placeholder') === 'Description', 'item: title and description (2.7.2)');
  check(det.querySelector('#d-sub') && det.querySelector('#d-list') && det.querySelector('[data-act="date"]') && det.querySelector('[data-act="prio"]'),
    'full task: subtasks, list, date, priority (2.7.2)');
  check(!det.querySelector('#d-assignee'), 'not shared: no assignee');
  const m0 = (await st()).tasks.find(t => t.id === milk);
  check(m0.tags.includes('dairy') && m0.url === 'https://example.org/milk' && m0.content === 'the good one', 'the data stays (tags, link, note)');
  click(w, det.querySelector('[data-act="task-menu"]')); await sleep(80);
  const ckm = [...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent);
  check(ckm.some(x => /Snooze/i.test(x)), 'the full task menu (2.7.2): ' + ckm);
  w.eval('closePop()');
  await call('PUT', `/api/lists/${SHOP}/members`, {user_id: BOB, role: 'edit'});
  await w.eval('load()'); w.eval('render(); renderDetail()'); await sleep(200);
  check(d.querySelector('#detail #d-assignee'), 'shared (collaboration on): the assignee shows');
  await call('DELETE', `/api/lists/${SHOP}/members/${BOB}`);
  await closeW(w);

  // ================= comments in shared lists + U19 toggle state (2.0.6: private lists below)
  w = await boot({user: 'alice', hash: 'l/' + TEAM}); d = w.document;
  w.eval(`openDetail(${plan})`); await sleep(500);
  check(d.querySelector('#detail #d-tl') && d.querySelector('#detail .dcomp #c-input'), 'shared list: comments with composer (2.0.6: the box at the bottom edge)');
  check(!d.querySelector('#detail #d-hist'), 'shared list: no separate history (it lives between the comments)');
  check(d.querySelector('#detail #d-content')?.getAttribute('placeholder') === 'Description' && d.querySelector('#detail #d-content').getAttribute('aria-label') === 'Description', '1.7.1: plain "Description" placeholder (Markdown explained in Help)');
  const tg = d.querySelector('#detail [data-act="tl-act"]');
  check(tg && tg.getAttribute('aria-pressed') === 'true' && /With activity/.test(tg.textContent), 'activity toggle names its state');
  click(w, tg); await sleep(50);
  check(tg.getAttribute('aria-pressed') === 'false' && /Comments only/.test(tg.textContent), 'toggled: "Comments only"');
  await call('POST', `/api/tasks/${plan}/comments`, {body: 'Ping from the old days'});
  await closeW(w);
  await call('DELETE', `/api/lists/${TEAM}/members/${BOB}`);
  w = await boot({user: 'alice', hash: 'l/' + WORK}); d = w.document;
  w.eval(`openDetail(${t1})`); await sleep(400);
  // 2.0.6 (#315) replaces U18: private lists get comments too (personal notes): no list yet, only the box (one line)
  check(!d.querySelector('#detail #d-tl') && d.querySelector('#detail .dcomp #c-input')?.placeholder === 'Write a comment…' && !d.querySelector('#detail [data-act="tl-act"]'), 'private list, no comments: only the comment box, without the @ hint');
  const hist = d.querySelector('#detail #d-hist');
  check(hist && hist.tagName === 'DETAILS' && !hist.open && /^History/.test(hist.querySelector('summary').textContent) && !hist.closest('#d-tl'), '2.0.7: private list keeps the folded history of 2.0.5, outside the notes');
  w.eval(`go('l/${TEAM}'); openDetail(${plan})`); await sleep(600);
  const ro = d.querySelector('#detail #d-tl');
  check(ro && d.querySelector('#detail .dcomp #c-input') && /Ping from the old days/.test(ro.textContent), 'now private, old comments: a normal list again, with the box');
  check(ro.querySelector('[data-act="c-edit"]') && ro.querySelector('[data-act="c-del"]') && !ro.querySelector('[data-act="tl-act"]') && !ro.querySelector('.actl'), 'editable, no activity (private list)');
  await closeW(w);

  // ================= Archive instead of Delete (U12, owner decision 7) + the own dialog
  w = await boot({user: 'alice', hash: 'l/' + WORK}); d = w.document;
  w.__dialogs = 'manual'; w.confirm = () => { throw new Error('native confirm'); }; w.prompt = () => { throw new Error('native prompt'); };
  w.eval(`listModal(${WORK})`); await sleep(200);
  let lm = d.querySelector('.modal:not(.smodal)');
  check(!lm.querySelector('[data-m="del"]') && /Archive/.test(lm.querySelector('[data-m="arch"]').textContent), 'list dialog: "Archive", no "Delete"');
  click(w, lm.querySelector('[data-m="arch"]'));
  check(await until(async () => (await st()).lists.find(l => l.id === WORK).archived), 'archived (no question asked)');
  check(!d.querySelector('.modal.cdlg'), 'archive asks nothing (it can be undone)');
  await until(() => w.eval(`HIST.undo.length && HIST.undo[HIST.undo.length - 1].label === 'Archived “Work”'`));
  check(/archived/.test(d.querySelector('#toast')?.textContent || '') && w.eval(`HIST.undo[HIST.undo.length - 1].label`) === 'Archived “Work”', 'toast + history step');
  await w.eval(`histStep('undo')`);
  check(!(await st()).lists.find(l => l.id === WORK).archived, 'undo brings the list back');
  await w.eval(`histStep('redo')`);
  check((await st()).lists.find(l => l.id === WORK).archived, 'redo archives it again');
  // header "…" of an archived list: restore / delete permanently
  w.eval(`go('l/${WORK}')`); await sleep(300);
  click(w, d.querySelector('#top [data-act="top-more"]')); await sleep(80);
  const lab = [...d.querySelectorAll('#pop .menu-list button')].map(b => b.textContent);
  check(lab.includes('Restore from the archive') && lab.includes('Delete permanently…') && !lab.includes('Archive'), 'archived list menu: restore / delete permanently: ' + lab);
  w.eval('closePop()');
  // delete for good: the dialog names what is lost; Esc = no
  let p = w.eval(`listDeleteForGood(${WORK})`); await sleep(100);
  let cd = d.querySelector('.modal.cdlg');
  check(cd && cd.getAttribute('role') === 'alertdialog' && cd.querySelector('.btn.danger.solid[data-cd="yes"]') && /permanently/.test(cd.querySelector('h3').textContent), 'own dialog: alertdialog, red action');
  check(cd && /sections/.test(cd.textContent) && /trash/.test(cd.textContent) && cd.querySelectorAll('.cdlg-l li').length >= 2, 'names what is lost and where the tasks go');
  check(d.activeElement === cd?.querySelector('[data-cd="no"]'), 'focus on "Cancel" for a destructive action');
  key(w, d.activeElement, 'Escape'); 
  check(await p === false && !d.querySelector('.modal.cdlg') && (await st()).lists.some(l => l.id === WORK), 'Esc = no, nothing deleted');
  p = w.eval(`listDeleteForGood(${WORK})`); await sleep(100);
  click(w, d.querySelector('.modal.cdlg [data-cd="yes"]'));
  check(await p === true && !(await st()).lists.some(l => l.id === WORK), 'confirmed: deleted for good');
  // other confirms: the own dialog, never window.confirm; undoable things ask nothing
  const S1 = (await call('POST', '/api/lists', {name: 'Scratch'})).id;
  const s1 = await mk('Throwaway', S1), s2 = await mk('Second', S1);
  w.eval(`go('l/${S1}')`); await w.eval('load()'); w.eval('render()'); await sleep(200);
  w.eval(`S.multi = new Set([${s1}, ${s2}])`); click(w, (() => { const b = d.createElement('button'); b.dataset.act = 'mb-del'; d.body.appendChild(b); return b; })());
  check(await until(async () => (await st()).tasks.filter(t => t.id === s1 || t.id === s2).length === 0), 'deleting selected tasks: no question (undo instead)');
  check(!d.querySelector('.modal.cdlg') && /deleted/.test(d.querySelector('#toast')?.textContent || ''), 'toast with undo');
  // prompt: a new section through the own dialog
  const sb = d.createElement('button'); sb.dataset.act = 'section-new'; d.body.appendChild(sb); click(w, sb); await sleep(100);
  cd = d.querySelector('.modal.cdlg');
  check(cd && cd.querySelector('#cdlg-in') && d.activeElement === cd.querySelector('#cdlg-in'), 'prompt: own dialog with the field focused');
  cd.querySelector('#cdlg-in').value = 'Later'; click(w, cd.querySelector('[data-cd="yes"]'));
  check(await until(async () => (await st()).sections.some(s => s.list_id === S1 && s.name === 'Later')), 'prompt answer used (section created)');
  const src = await clientSource();
  check(!/[^.\w$]confirm\(/.test(src) && !/[^.\w$]prompt\(/.test(src), 'no window.confirm / window.prompt left in the app');
  check(!errs.some(e => /native/.test(e)), 'native dialogs never called');
  await closeW(w);

  // ================= own date / time pickers (U23, owner decision 8)
  w = await boot({user: 'alice', hash: 'l/' + TEAM}); d = w.document;
  check(!/type="(date|time)"/.test(src), 'no native date / time inputs in the app');
  w.eval(`openDetail(${plan})`); await sleep(200);
  w.eval(`datePop(document.querySelector('#detail [data-act="date"]'), ${plan})`); await sleep(100);
  click(w, d.querySelector('#pop [data-dpfor="p-start"]')); await sleep(80);
  let dp = d.querySelector('#dpop');
  check(dp && dp.getAttribute('role') === 'dialog' && dp.querySelector('.dpg[role="grid"]'), 'date picker opens (grid)');
  const hdr = [...dp.querySelectorAll('.dpwd span')].map(x => x.textContent);
  check(hdr[0] === (new Intl.Locale(w.navigator.language || 'en').maximize().region === 'US' ? 'Sun' : 'Mon'), 'English: first weekday from the locale: ' + hdr[0]);
  check(/\d{4}$/.test(dp.querySelector('.dpt').textContent) && !/[A-Z][a-z]+ \d{4}/.test('') , 'month title');
  const f0 = dp.querySelector('.dpg [tabindex="0"]');
  f0.focus(); key(w, f0, 'ArrowRight'); await sleep(20);
  let foc = d.activeElement;
  check(foc?.dataset.d === addD(f0.dataset.d, 1), 'ArrowRight moves one day');
  key(w, foc, 'ArrowDown'); foc = d.activeElement;
  check(foc?.dataset.d === addD(f0.dataset.d, 8), 'ArrowDown moves one week');
  key(w, foc, 'PageDown'); foc = d.activeElement;
  check(foc?.dataset.d?.slice(5, 7) !== f0.dataset.d.slice(5, 7), 'PageDown: next month');
  key(w, foc, 'PageUp'); foc = d.activeElement;
  const pick = foc.dataset.d;
  key(w, foc, 'Escape');
  check(!d.querySelector('#dpop') && !d.querySelector('#pop').classList.contains('hidden'), 'Esc closes only the picker, the date dialog stays');
  click(w, d.querySelector('#pop [data-dpfor="p-start"]')); await sleep(60);
  foc = d.querySelector('#dpop .dpg [tabindex="0"]'); foc.focus(); key(w, foc, 'Enter');
  check(d.querySelector('#p-start')?.value === foc.dataset.d || d.querySelector('#pop #p-start')?.value, 'Enter picks the day');
  // touch: a tap on a day
  click(w, d.querySelector('#pop [data-dpfor="p-start"]')); await sleep(60);
  // the start may not be after the due date: on the 1st of a month only one day of the month may be enabled -> take the last enabled one
  const tapDay = [...d.querySelectorAll('#dpop .dpd:not(.out):not([disabled])')].at(-1);
  tapDay.dispatchEvent(new w.Event('touchstart', {bubbles: true})); click(w, tapDay);
  check(d.querySelector('#pop #p-start')?.value === tapDay.dataset.d && /\w/.test(d.querySelector('#pop [data-dpfor="p-start"]').textContent), 'tap picks the day, the button shows it');
  // time: typing and the 12 / 24 h display
  click(w, d.querySelector('#pop [data-dpfor="p-time"]')); await sleep(60);
  const tin = d.querySelector('#dpop #dp-tin');
  check(tin && d.activeElement === tin, 'time picker: the text field has the focus');
  tin.value = '930'; key(w, tin, 'Enter'); await sleep(60);
  check(d.querySelector('#pop #p-time')?.value === '09:30', 'typed "930" -> 09:30');
  const tl = d.querySelector('#pop [data-dpfor="p-time"]').textContent;
  check(/9:30/.test(tl), 'time shown in the app language: ' + tl);
  click(w, d.querySelector('#pop [data-dpfor="p-time"]')); await sleep(60);
  click(w, d.querySelector('#dpop [data-th="14"]')); click(w, d.querySelector('#dpop [data-tm="45"]')); await sleep(40);
  check(d.querySelector('#pop #p-time')?.value === '14:45', 'tap hour + minutes -> 14:45');
  click(w, d.querySelector('#pop [data-q="ok"]') || d.querySelector('#pop [data-q="done"]'));  // 2.6.1 (#401): saved at once, "Done" closes
  check(await until(async () => (await st()).tasks.find(t => t.id === plan).due_time === '14:45'), 'saved with the task (stored format HH:MM)');
  check(w.eval(`parseHM('9:30 pm')`) === '21:30' && w.eval(`parseHM('21 Uhr')`) === '21:00' && w.eval(`parseHM('25:00')`) === null, 'time parser (pm, "Uhr", invalid)');
  // custom repeat: a small form, RRULE only as expert field (U06)
  w.eval(`datePop(document.querySelector('#detail [data-act="date"]'), ${plan})`); await sleep(80);
  const rep = d.querySelector('#p-rep'); rep.value = '__custom'; rep.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(60);
  check(d.querySelector('#pop .rrcust #p-rn') && d.querySelector('#pop .rrcust #p-rf') && d.querySelector('#pop details.rrx #p-rrule'), 'custom repeat: interval + unit, RRULE folded away');
  const rn = d.querySelector('#p-rn'); rn.value = '3'; rn.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(40);
  click(w, d.querySelector('#pop [data-rwd="TH"]')); await sleep(40);
  check(/INTERVAL=3/.test(w.eval(`document.querySelector('#p-rrule').value`)) && /TH/.test(w.eval(`document.querySelector('#p-rrule').value`)), 'form builds the rule: ' + w.eval(`document.querySelector('#p-rrule').value`));
  w.eval('closePop()');
  await closeW(w);
  // German
  wb = await boot({user: 'bob', hash: 'today'}); db = wb.document;
  wb.eval(`dpOpen(document.querySelector('#top h1'), {kind: 'date', value: '2026-03-10', onPick: v => { window.__v = v; }})`); await sleep(60);
  dp = db.querySelector('#dpop');
  check(/März 2026/.test(dp.querySelector('.dpt').textContent) && dp.querySelector('.dpwd span').textContent === 'Mo', 'German: "März 2026", week starts on Monday');
  check(/Heute/.test(dp.querySelector('[data-dq="today"]').textContent), 'German buttons');
  click(wb, dp.querySelector('.dpd[data-d="2026-03-12"]'));
  check(wb.__v === '2026-03-12', 'German picker returns the stored format');
  wb.eval(`dpOpen(document.querySelector('#top h1'), {kind: 'time', value: '21:05', onPick: v => { window.__t = v; }})`); await sleep(60);
  check(db.querySelector('#dp-tin').value === '21:05' && db.querySelector('#dpop [data-th="21"]').textContent === '21', 'German: 24 h clock');
  await closeW(wb);

  // ================= phone: undo / redo in the header "…" menu (owner decision 4), U01 title first
  w = await boot({user: 'alice', mobile: true, hash: 'l/' + TEAM}); d = w.document;
  check(!d.querySelector('#top [data-act="hist-undo"]') && !d.querySelector('#top [data-act="hist-redo"]'), 'phone: no ← → in the header');
  check(!d.querySelector('#top [data-act="multi"]') && !d.querySelector('#top [data-act="sort"]'), 'select / sort not in the header');
  await w.eval(`patchTask(${plan}, {priority: 5})`); await sleep(100);
  click(w, d.querySelector('#top [data-act="top-more"]')); await sleep(80);
  let items = [...d.querySelectorAll('#pop .menu-list button')];
  check(items[0]?.textContent.startsWith('Undo: ') && items[1]?.textContent === 'Nothing to redo' && items[1].disabled, 'menu starts with "Undo: …", "Redo" disabled: ' + items.slice(0, 2).map(b => b.textContent));
  check(items.some(b => /Select multiple/.test(b.textContent)) && items.some(b => /Sort/.test(b.textContent)) && items.some(b => /Edit list/.test(b.textContent)), 'then select, sort and the list menu');
  click(w, items[0]);
  check(await until(async () => (await st()).tasks.find(t => t.id === plan).priority === 0), 'undo from the menu');
  await until(() => !w.eval('HIST.busy') && w.eval('HIST.redo.length') === 1);
  click(w, d.querySelector('#top [data-act="top-more"]')); await sleep(80);
  items = [...d.querySelectorAll('#pop .menu-list button')];
  check(items[1]?.textContent.startsWith('Redo: ') && !items[1].disabled, '"Redo: …" offered');
  w.eval('closePop()');
  await closeW(w);
  // desktop keeps the arrows
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  check(d.querySelector('#top [data-act="hist-undo"]') && d.querySelector('#top [data-act="top-more"]'), 'desktop: ← → stay, "…" for the rest');
  await closeW(w);

  // ================= Fold (U02, owner decision 1)
  w = await boot({user: 'alice', hash: 'l/' + TEAM, media: {'(hover: none)': true}, setup: x => { Object.defineProperty(x, 'innerWidth', {configurable: true, value: 1000}); }}); d = w.document;
  check(!d.querySelector('#app').classList.contains('side-rail'), 'no panel: sidebar stays');
  w.eval(`openDetail(${plan})`); await sleep(100);
  check(d.querySelector('#app').classList.contains('side-rail') && d.querySelector('#top .menu'), 'panel open at 1000 px: the sidebar becomes a drawer (menu button)');
  click(w, d.querySelector('#top .menu')); await sleep(50);
  check(d.querySelector('#side').classList.contains('open') && !d.querySelector('#scrim').classList.contains('hidden'), 'the menu button opens the sidebar as an overlay');
  click(w, d.querySelector('#scrim')); await sleep(50);
  check(!d.querySelector('#side').classList.contains('open'), 'tap next to it closes it');
  check(d.querySelector('#top [data-act="hist-undo"]'), '2.7.0 (#405): touch tablet with room: undo / redo in the header (they fold into "…" when tight)');
  w.eval('closeDetail()'); await sleep(50);
  check(!d.querySelector('#app').classList.contains('side-rail'), 'panel closed: sidebar back');
  Object.defineProperty(w, 'innerWidth', {configurable: true, value: 1600});
  w.eval(`openDetail(${plan})`); await sleep(50);
  check(!d.querySelector('#app').classList.contains('side-rail'), 'wide screen: all side by side');
  await closeW(w);

  // ================= touch targets (U13): the rules in the stylesheet (layout itself: Firefox harness, see README)
  const css = await (await fetch(B + 'static/app.css')).text();
  const coarse = [...css.matchAll(/@media \(pointer:coarse\)\{([\s\S]*?)\n\}/g)].map(m => m[1]).join('\n');
  check(/#top \.iconbtn[^{]*\{[^}]*min-width:2\.75rem;min-height:2\.75rem/.test(coarse), 'header icons 44 px');
  check(/\.chk::after\{inset:-1\.0625rem\}/.test(coarse), 'status glyph hit area 14 + 2 x 17 >= 44 px (2.8.0)');
  check(/\.hc::before\{[^}]*1\.375rem/.test(coarse) && /\.shead button::before/.test(coarse), 'habit cells and sidebar "+" hit areas');
  check(/\.mcal \.d,\.dpd\{min-height:2\.75rem\}/.test(coarse), 'calendar days 44 px high');
  // U24: light red one step darker
  check(/--p5:#b3372f/.test(css) && !/c2413a/.test(css), 'light theme red darkened (AA on the active row)');

  check(errs.length === 0, 'no script errors: ' + errs.join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
