// Settings dialog tests (jsdom). Needs the api_test.py DB (alice en admin, bob de, eve collab off).
const {boot, errs, sleep} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const api = async (w, method, url, body) => (await w.fetch(url, {method, headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: body ? JSON.stringify(body) : undefined})).json();
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
(async () => {
  let w = await boot({user: 'alice'}), d = w.document;
  const before = (await api(w, 'GET', '/api/state')).settings;
  w.eval('settingsModal()'); await sleep(400);
  let md = d.querySelector('.modal.smodal');
  const secs = [...md.querySelectorAll('.snav [data-sec]')].map(b => b.dataset.sec);
  check(JSON.stringify(secs) === JSON.stringify(['account', 'general', 'look', 'modules', 'notify', 'integr', 'data', 'users', 'help']), 'admin: all sections (2.7.0: Agents only with the module or agents) ' + secs);
  check(md.querySelector('.snav .on')?.dataset.sec === 'general', 'default section: General');
  check(md.querySelectorAll('.spane:not(.hidden)').length === 1, 'exactly one pane visible');
  for (const k of secs) {
    click(w, md.querySelector(`.snav [data-sec="${k}"]`)); await sleep(30);
    const p = md.querySelector(`.spane[data-pane="${k}"]`);
    check(!p.classList.contains('hidden') && p.textContent.trim().length > 20 && md.querySelectorAll('.spane:not(.hidden)').length === 1, `pane ${k} renders`);
  }
  await sleep(300);
  check(md.querySelectorAll('#a-users .mrow').length >= 4, 'users pane lists users');
  check(md.querySelector('[data-pane="look"] #s-tabbar') && md.querySelector('[data-pane="look"] .devtag'), 'per-device groups tagged (appearance + tab bar)');
  check(md.querySelector('[data-pane="modules"] [data-feat="collab"]') && /Share lists, assign tasks, @mentions/.test(md.querySelector('[data-pane="modules"]').textContent) && md.querySelector('[data-pane="modules"] [data-feat="comments"]'), 'collab switch with explanation under Modules');
  check(md.querySelector('[data-pane="modules"] #s-collaball')?.checked === true, 'admin: instance switch shown next to it (Modules), on');
  check(/Kalmido v\d+\.\d+\.\d+/.test(md.querySelector('[data-pane="help"]').textContent), 'help: version line');
  check(md.querySelector('[data-pane="notify"] #s-allday') && md.querySelector('[data-pane="notify"] #s-digest') && md.querySelector('[data-pane="notify"] [data-m="test"]'), 'notifications pane: topic test, reminders, digest');
  check(md.querySelector('[data-pane="data"] #s-import') && !md.querySelector('[data-pane="data"] [data-m="purge"]'), 'data pane: import; 2.7.0 (#405 S4): "Delete all completed" only in the Completed view');
  check(md.querySelector('[data-pane="account"] #a-name') && md.querySelector('[data-pane="account"] [data-m="go-share"]'), 'account pane (2.7.0: the upload token is a link to Share from your phone)');
  // last section remembered
  click(w, md.querySelector('.snav [data-sec="modules"]')); await sleep(30);
  click(w, md.querySelector('.shdr [data-m="close"]')); await sleep(50);
  check(!d.querySelector('.modal'), 'X closes');
  w.eval('settingsModal()'); await sleep(200); md = d.querySelector('.smodal');
  check(md.querySelector('.snav .on').dataset.sec === 'modules' && JSON.stringify(w.__store).includes('modules'), 'last section remembered per device');
  d.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); await sleep(50);
  check(!d.querySelector('.modal'), 'Escape closes');
  w.eval(`settingsModal('tabbar')`); await sleep(200); md = d.querySelector('.smodal');
  check(md.querySelector('.snav .on').dataset.sec === 'look' && md.querySelector('#s-tabadd option'), 'settingsModal(tabbar) -> Appearance (tab bar)');
  md.remove();
  w.eval(`settingsModal('account')`); await sleep(200); md = d.querySelector('.smodal');
  check(md.querySelector('.snav .on').dataset.sec === 'account', 'settingsModal(account) -> Account');
  md.remove();
  w.eval(`settingsModal('look')`); await sleep(200); md = d.querySelector('.smodal');
  // immediate: theme + tab bar
  click(w, md.querySelector('[data-look="theme"][data-v="light"]')); await sleep(50);
  check(w.__store['tasks.theme'] === '"light"' && d.documentElement.dataset.theme === 'light', 'theme applies immediately');
  click(w, md.querySelector('[data-look="theme"][data-v="dark"]'));
  const sel = md.querySelector('#s-tabadd'); sel.value = 's:today'; sel.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(50);
  check(JSON.stringify(w.eval(`LS.get('tabbar')`)).includes('s:today'), 'tab bar applies immediately');
  click(w, md.querySelector('[data-m="tab-reset"]')); await sleep(50);
  check(w.eval(`LS.get('tabbar', null)`) === null, 'tab bar back to default');
  md.remove();
  // 1.5: every setting saves itself (no "Save", no "unsaved changes")
  w.eval(`settingsModal('notify')`); await sleep(300); md = d.querySelector('.smodal');
  check(!md.querySelector('[data-m="save"]') && !md.querySelector('.sdirty'), 'no Save button, no unsaved marker');
  const set = (id, v) => { const e = md.querySelector(id); e.value = v; e.dispatchEvent(new w.Event('change', {bubbles: true})); };
  w.eval(`dpSet(document.querySelector('#s-allday'), '07:30')`); set('#s-defrem', '15'); w.eval(`dpSet(document.querySelector('#s-digest'), '06:45')`);
  await sleep(700);
  md.remove();
  w.eval(`settingsModal('modules')`); await sleep(300); md = d.querySelector('.smodal');
  set('#s-pf', '30'); set('#s-ps', '6'); set('#s-pl', '20'); set('#s-pe', '3');
  const tl = md.querySelector('[data-feat="timeline"]'); tl.checked = false; tl.dispatchEvent(new w.Event('change', {bubbles: true}));
  await sleep(800); md.remove();
  w.eval(`settingsModal('general')`); await sleep(300); md = d.querySelector('.smodal');
  check(!md.querySelector('#s-showdone') && !/Show in lists/.test(md.textContent), '1.8.1: no global "Show completed" switch');
  await sleep(800);
  const after = (await api(w, 'GET', '/api/state')).settings;
  check(after.allday_time === '07:30' && after.default_reminder === '15' && after.digest_time === '06:45', 'saved: reminders + digest');
  check(after.pomo_focus === '30' && after.pomo_short === '6' && after.pomo_long === '20' && after.pomo_long_every === '3', 'saved: focus');
  check(!after.features.split(',').includes('timeline') && after.features.split(',').includes('collab'), 'saved: features');
  check(d.querySelector('.smodal'), 'the dialog stays open while saving');
  md.remove();
  await api(w, 'PATCH', '/api/settings', Object.fromEntries(['allday_time', 'default_reminder', 'digest_time', 'pomo_focus', 'pomo_short', 'pomo_long', 'pomo_long_every', 'features', 'nav_order'].map(k => [k, before[k]])));
  w.close();
  // bob: German, non-admin, mobile
  w = await boot({user: 'bob', mobile: true}); d = w.document;
  w.eval('settingsModal()'); await sleep(400); md = d.querySelector('.smodal');
  const bsecs = [...md.querySelectorAll('.snav [data-sec]')].map(b => b.dataset.sec);
  check(!bsecs.includes('users') && bsecs.includes('ai') && bsecs.length === 9, 'non-admin: no Administration section (2.22.0 #739: a new person has the module Agents, so its page) ' + bsecs.join());
  const txt = md.textContent;
  check(/Allgemein/.test(txt) && /Benachrichtigungen/.test(txt) && /Integrationen/.test(txt) && /Hilfe/.test(txt) && /Dieses Gerät/.test(txt), 'German section labels');
  for (const k of bsecs) click(w, md.querySelector(`.snav [data-sec="${k}"]`));
  const left = ['General', 'Notifications', 'Integrations', 'This device', 'Reminders', 'Tab bar', 'Modules', 'Sharing from', 'Import and export', 'Gestures', 'Quick add', 'Appearance', 'Completed tasks', 'Language', 'Advanced', 'for everyone', 'How urgent'].filter(x => txt.includes(x));
  check(!left.length, 'no English leftovers (de): ' + left);
  // language switch reopens the dialog in General, now English
  click(w, md.querySelector('[data-lang-set="en"]')); await sleep(1500);
  md = d.querySelector('.smodal');
  check(md && md.querySelector('.snav .on').dataset.sec === 'general' && /General/.test(md.textContent), 'language applies immediately, dialog reopens in General');
  click(w, md.querySelector('[data-lang-set="de"]')); await sleep(1500);
  check(/Allgemein/.test(d.querySelector('.smodal').textContent), 'back to German');
  w.close();
  // eve: collab off
  w = await boot({user: 'eve'}); d = w.document;
  w.eval(`settingsModal('modules')`); await sleep(300); md = d.querySelector('.smodal');
  check(md.querySelector('[data-feat="collab"]') && !md.querySelector('[data-feat="collab"]').checked, 'collab off: switch visible, unchecked');
  check(![...md.querySelectorAll('#s-tabadd option')].some(o => ['news', 's:assigned'].includes(o.value)), 'collab off: no News / Assigned tab options');
  w.close();
  console.log(`\n${ok} ok, ${F.length} failed`);
  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  process.exit(F.length || errs.length ? 1 : 0);
})();
