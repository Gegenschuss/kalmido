// 1.0 UI tests (jsdom): Settings > Collaboration (personal + instance switch), version in Help, update dot for admins.
// Runs after v1_test.py on the same container (alice = admin, bob = member of alice's list "Shared").
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, errs, sleep} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const DATA = process.argv[2];
const sql = q => execFileSync('python3', ['-c', 'import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2]); c.commit()', path.join(DATA, 'tasks.db'), q]);
(async () => {
  // an update is known (as if the daily check had found one)
  sql(`UPDATE settings SET value='1' WHERE key='update_check'`);
  sql(`UPDATE settings SET value='{"checked_at": "2026-09-01T00:00:00Z", "latest": "99.0.0", "url": "https://github.com/example/kalmido/releases/tag/v99.0.0"}' WHERE key='update_info'`);
  let w = await boot({user: 'alice'}), d = w.document;
  check(d.querySelector('#rail .rbtn[data-act="settings"] .dot') || d.querySelector('.srow[data-act="settings"] .nunread'), 'admin: update dot on the settings gear');
  w.eval(`settingsModal('help')`); await sleep(300);
  let md = d.querySelector('.smodal');
  const help = md.querySelector('[data-pane="help"]').textContent;
  check(/installed — v99\.0\.0 available/.test(help) && md.querySelector('[data-pane="help"] a[href$="/v99.0.0"]'), 'help: update line + release notes link');
  check(/update\.sh/.test(help) && /docker compose pull/.test(help), 'help: update commands');
  // 1.7.1: the Markdown syntax lives in Help (not in the description placeholder); comments line only with collaboration
  const fmtH = [...md.querySelectorAll('[data-pane="help"] h4')].find(h => h.textContent === 'Formatting (Markdown)');
  const fmtT = fmtH?.nextElementSibling?.textContent || '';
  check(fmtH && ['**bold**', '*italic*', '~~strikethrough~~', '`code`', '[text](https://…)', '###', '1. item', '- [ ]', '- [x]', 'Turn the open checklist items into subtasks'].every(x => fmtT.includes(x)) && /Comments:.*no headings, lists or checklists/.test(fmtT), 'help: Formatting (Markdown) entry for descriptions + comments');
  check(md.querySelector('[data-pane="users"] #s-updcheck')?.checked === true, 'users > whole server: update check switch');
  check(md.querySelector('[data-pane="modules"] #s-timeall')?.checked === true && md.querySelector('[data-pane="modules"] #s-collaball'), 'modules: collaboration + time switches for everyone (admin)');
  check(!md.querySelector('[data-pane="users"] #s-collaball') && /Settings > Modules/.test(md.querySelector('[data-pane="users"]').textContent), 'administration: pointer to Modules');
  // instance switch off -> applies at once (1.5: own dialog, answered by the test bridge), personal switch disabled + note
  click(w, md.querySelector('.snav [data-sec="modules"]')); await sleep(50);
  const all = md.querySelector('#s-collaball');
  check(all && all.checked, 'instance switch on');
  all.checked = false; all.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(1500);
  md = d.querySelector('.smodal');
  check(md.querySelector('[data-feat="collab"]').disabled && md.querySelector('#s-collabnote'), 'off: personal switch disabled, note shown');
  check(w.eval('collab()') === false && !d.querySelector('.srow[data-go="news"]'), 'off: collaboration UI gone for the admin too');
  md.remove(); w.close();
  w = await boot({user: 'bob'}); d = w.document;
  check(!d.querySelector('#rail .rbtn[data-act="settings"] .dot') && !d.querySelector('.srow[data-act="settings"] .nunread'), 'non-admin: no update dot');
  check(!w.eval('S.lists').some(l => l.name === 'Shared'), 'off: bob no longer sees the shared list');
  w.eval(`settingsModal('collab')`); await sleep(300); md = d.querySelector('.smodal');
  check(md.querySelector('[data-feat="collab"]').disabled && !md.querySelector('#s-collaball'), 'non-admin: disabled personal switch, no instance switch');
  check(!/v99/.test(md.querySelector('[data-pane="help"]').textContent) && /Kalmido v\d/.test(md.querySelector('[data-pane="help"]').textContent), 'non-admin: version, no update info');
  check(/Formatting \(Markdown\)/.test(md.querySelector('[data-pane="help"]').textContent) && !/Comments:/.test(md.querySelector('[data-pane="help"]').textContent), 'help without collaboration: formatting entry, no comments line');
  // changing another module keeps the (disabled) personal choice (1.5: saved at once)
  const hb = md.querySelector('[data-feat="habits"]'); hb.checked = !hb.checked; hb.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(800);
  check(w.eval('S.settings.features').split(',').includes('collab'), 'another module change keeps the personal setting');
  hb.checked = !hb.checked; hb.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(800);
  w.close();
  w = await boot({user: 'alice'}); d = w.document;
  w.eval(`settingsModal('modules')`); await sleep(300); md = d.querySelector('.smodal');
  const sw = md.querySelector('#s-collaball');
  check(sw && !sw.checked, 'switch shows off after reload');
  sw.checked = true; sw.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(900); md = d.querySelector('.smodal');
  check(!md.querySelector('[data-feat="collab"]').disabled && w.eval('collab()') === true, 'on again: personal switch enabled, UI back');
  // time tracking for everyone: off -> module gone, personal switch disabled with a note, options hidden
  const ta = md.querySelector('#s-timeall');
  ta.checked = false; ta.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(1500); md = d.querySelector('.smodal');
  check(w.eval('timeOn()') === false && !d.querySelector('#rail [data-go="time"]') && !d.querySelector('#side [data-go="time"]'), 'time off: module gone from the navigation');
  md.remove();
  w.eval(`settingsModal('layout')`); await sleep(300); md = d.querySelector('.smodal');
  check(md.querySelector('[data-pane="modules"] [data-feat="time"]').disabled && /Turned off on this server/.test(md.querySelector('[data-modrow="time"]').textContent), 'time off: personal switch disabled + note');
  check(!md.querySelector('#s-trnd'), 'time off: no time tracking options');
  md.remove();
  w.eval(`openDetail([...S.tasks.keys()][0])`); await sleep(300);
  check(!d.querySelector('#d-time') && !d.querySelector('[data-act="timer-toggle"]'), 'time off: no time section / timer button in the task panel');
  w.eval(`settingsModal('modules')`); await sleep(300); md = d.querySelector('.smodal');
  const tb = md.querySelector('#s-timeall'); tb.checked = true; tb.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(1500); md = d.querySelector('.smodal');
  check(w.eval('timeOn()') === true, 'time on again: ' + w.eval('S.timeAll') + ' ' + w.eval('S.settings.features'));
  check(!md.querySelector('[data-feat="time"]')?.disabled, 'time on again: personal switch enabled');
  md.remove(); w.close();
  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
