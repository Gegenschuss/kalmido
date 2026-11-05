// 2.555.0 C (#4664) UI tests, own container (start.sh), jsdom, invented data only: the settings outside Company & office
// kalmido-suite: fresh
// (findings 14-34 of the settings review of 05.11.):
// - Organisation > Agents: ONE switch for user_agents (s-uag) with one hint, the state stays after reopening
// - Server > Server: after "Publish" of the notice the pane keeps every part (one serverPaneHtml for both draws)
// - Integrations > Karakeep: once connected the fields save on change, no "Save" button; "Connect" only the first time
// - Server > Errors in the browser: "Report to" shows "(Project of another admin)" instead of "Off"
// - texts: no h4 under a sub-tab with the sub-tab's name, the renamed labels / headings / hints, one test button per kind
// - a person without an organisation: Notifications and Karakeep the same way
// freelancer-matrix: settings
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, errs, until: untilT} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2555C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = fn => untilT(fn, {timeout: 15000, step: 100}).catch(() => null);
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el) => el && el.dispatchEvent(new w.Event('change', {bubbles: true}));
const txt = el => (el?.textContent || '').replace(/\s+/g, ' ').trim();
const count = (hay, needle) => hay.split(needle).length - 1;
const FEATS = 'cal,timeline,matrix,kanban,collab,progress,deps,fields,comments,agents,reading,time';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com'});  // no organisation
  const FK = await login('frida');
  for (const ck of [CK, FK]) await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEATS}, ck);
  check((await call('GET', '/api/state', null, FK)).me.workspaces?.length === 0, 'setup: frida has no organisation');

  // ================= Organisation > Agents: one switch for user_agents
  let w = await boot({user: 'alice'}), d = w.document;
  w.eval(`settingsModal('agentpolicy')`);
  let md = await until(() => d.querySelector('.smodal #admp-agents #s-uag') && d.querySelector('.smodal'));
  check(!!md, 'Organisation > Agents opens with the switch');
  const ap = md.querySelector('#admp-agents');
  check(ap && ap.querySelectorAll('#s-uag').length === 1 && !md.querySelector('#s-orgagents'), 'one switch for user_agents (the second one is gone)');
  check(ap && count(ap.textContent, 'On: everyone on this server, in every workspace.') === 1 && count(ap.textContent, 'They are responsible for what that provider receives') === 1, 'the hint once');
  let sw = md.querySelector('#s-uag');
  check(await until(() => !w.eval('!!S.about?.user_agents') && sw.checked === false), 'off by default');
  sw.checked = true; change(w, sw);
  check(await until(async () => (await call('GET', '/api/admin/agent-policy')).user_agents === true), 'the switch sets the policy');
  check(await until(() => w.eval('S.about.user_agents') === true), 'the app knows the new state (S.about)');
  w.eval(`document.querySelectorAll('.modal').forEach(m => m.remove()); settingsModal('agentpolicy')`);
  md = await until(() => d.querySelector('.smodal #admp-agents #s-uag') && d.querySelector('.smodal'));
  check(md?.querySelector('#s-uag').checked === true, 'reopened: the same state at once');
  sw = md.querySelector('#s-uag'); sw.checked = false; change(w, sw);
  check(await until(async () => (await call('GET', '/api/admin/agent-policy')).user_agents === false), 'switched back off');

  // ================= texts: no h4 under a sub-tab with the sub-tab's name
  // the sub-tabs of the findings (Agents, Sign-in, Admin alerts, Assistant); "People" over the server's people list is not one of them
  const dup = [...md.querySelectorAll('[data-admsub="agents"], [data-admsub="signin"], [data-admsub="log"], [data-aisub="assistant"]')].flatMap(b => {
    const k = b.dataset.admsub || b.dataset.aisub, p = md.querySelector(b.dataset.admsub ? `#admp-${k}` : `#aisp-${k}`), n = txt(b);
    return p ? [...p.querySelectorAll('h4')].filter(h => txt(h) === n).map(() => n) : [];
  });
  check(md.querySelectorAll('[data-admsub="agents"], [data-admsub="signin"], [data-admsub="log"]').length === 3 && !dup.length, 'no heading repeats its sub-tab: ' + dup.join());
  check(txt(md.querySelector('#adms-log')) === 'Admin alerts' && !md.querySelector('#s-aa-h'), 'the sub-tab Log & errors is called Admin alerts, no heading of the same name');
  check(txt(md.querySelector('#s-signin-h')) === 'Two-factor and passkeys', 'Server > Sign-in: heading "Two-factor and passkeys"');
  check(txt(md.querySelector('#s-account-h')) === 'Profile', 'Account starts with "Profile"');
  const mv = md.querySelector('#s-mview');
  check(mv && txt(md.querySelector('#s-mview-h')) === 'View as member' && txt(mv.closest('label')) === 'Show Kalmido as a member sees it', 'View as member: the tick says something else than the heading');
  const ex = md.querySelector('#s-exp-h')?.nextElementSibling;
  check(ex && ex.querySelector('a[href="/api/export.json"]') && !ex.querySelector('label'), 'Export: no row label "Export" under the heading');
  check(txt(md.querySelector('label[for="s-quota"]')) === 'Limit' && txt(md.querySelector('#s-quota-h')) === 'Storage per person', 'Storage per person: the field is called Limit');
  const helpH = [...md.querySelectorAll('[data-pane="help"] h4')].map(txt);
  check(helpH.filter(x => x === 'Projects').length === 1 && helpH.includes('Dependencies, fields, status'), 'Help: "Projects" once, the second part has its own name: ' + helpH.join('|'));
  // "lists" is left out while it is in the tab bar already (the default bar has it): then the builder itself is checked
  const tl = w.eval(`(tabAddGroups().find(g => g.k === 'o')?.items || []).find(x => x.id === 'lists')?.label || (tabIds().includes('lists') && /it\\('lists', tr\\('All projects \\(overview\\)'\\)\\)/.test(tabAddGroups.toString()) ? 'All projects (overview)' : '')`);
  check(tl === 'All projects (overview)' && !/it\('lists', tr\('Projects'\)\)/.test(w.eval('tabAddGroups.toString()')), 'Add tab: "All projects (overview)" under Other: ' + tl);
  check(/Off: a video first shows a note/.test(md.querySelector('[data-pane="data"]').textContent), 'Videos: "a video first shows a note"');
  const np = md.querySelector('[data-pane="notify"]');
  check(/the time zone under General > Region and formats/.test(np.textContent), 'Quiet hours: the time zone is under General > Region and formats');
  check(/A new project gets an icon matching its name/.test(txt(md.querySelector('#s-lemo').closest('.row').nextElementSibling)), 'Appearance: the icon hint under "Suggest icons"');
  check(/^Lines: a calm grey icon/.test(txt(md.querySelector('#s-sideic').closest('.row').nextElementSibling)), 'Appearance: the project icon hint under "Project icons"');
  w.eval(`wpState(document.querySelector('.smodal'), {channel: 'webpush', subs: [], ntfy: false})`);
  check(/Turn on “Notify on this device” below\./.test(txt(md.querySelector('#s-wpstate'))), 'the push hint says below: ' + txt(md.querySelector('#s-wpstate')));
  if (w.eval('!!S.webpush?.enabled')) {
    check(txt(np.querySelector('[data-m="ptest"]')) === 'Test all channels' && !np.querySelector('[data-m="test"]'), 'Notifications: "Test all channels", no second channel test at the ntfy topic');
    // a browser without Web Push (jsdom has none): the sentence once, in the status line on top, not again under "This device"
    w.eval(`wpDraw(document.querySelector('.smodal'))`);
    check(await until(() => txt(np.querySelector('#s-pushnow')) && !/Loading/.test(txt(np.querySelector('#s-wp'))) && np), 'Notifications: the device part is drawn');
    check(count(np.textContent, 'This browser does not support Web Push') === 1, 'without Web Push: the sentence once: ' + count(np.textContent, 'This browser does not support Web Push'));
    check(!np.querySelector('[data-m="wp-test"]'), 'no device test without a subscribed device');
  }
  // the assistant under its sub-tab: no second heading, no row label of the same name
  const ah = w.eval(`(() => { const a = S.assistant; S.assistant = {on: false, list_ids: [], provider: 'x', host: 'y', model: 'z'}; const r = [asst_paneHtml(t => t, true), asst_paneHtml(t => t)]; S.assistant = a; return r; })()`);
  check(!/s-asst-h/.test(ah[0]) && /s-asst-h/.test(ah[1]) && !/<label>Assistant<\/label>/.test(ah[0]), 'Assistant: no heading under the sub-tab (only when shown alone), no label "Assistant"');

  // ================= Server > Server: "Publish" keeps every part
  click(w, md.querySelector('[data-admsub="server"]'));
  const sp = await until(() => !md.querySelector('#admp-server').hidden && md.querySelector('#admp-server'));
  const ids0 = [...sp.querySelectorAll('h4[id]')].map(h => h.id);
  check(ids0.includes('s-ann-h') && ids0.includes('s-rt9-h'), 'Server: notice and related tasks: ' + ids0.join());
  check(typeof w.eval('serverPaneHtml') === 'function', 'one builder serverPaneHtml');
  sp.querySelector('#s-ann-text').value = 'Maintenance tonight';
  click(w, sp.querySelector('[data-m="ann-save"]'));
  check(await until(() => /Notice published/.test(d.querySelector('#toast')?.textContent || '')), 'the notice is published');
  const sp2 = md.querySelector('#admp-server');
  const ids1 = [...sp2.querySelectorAll('h4[id]')].map(h => h.id);
  check(ids1.join() === ids0.join(), 'after Publish the same parts (updates, related tasks, assistant stay): ' + ids1.join());
  check(sp2.querySelector('[data-m="ann-clear"]') && sp2.querySelector('#s-ann-text').value === 'Maintenance tonight', 'the pane shows the published notice');
  await call('PUT', '/api/admin/announcement', {text: ''});
  // "Report to": a project of another admin is not shown as Off
  const cer = cur => w.eval(`(() => { const x = document.createElement('div'); x.innerHTML = cer_html({client_errors_list: ${cur}, client_errors_lists: [{id: 5, name: 'Mine'}]}, t => t); const o = x.querySelector('#s-cerlist').selectedOptions[0]; return o.value + '|' + o.textContent + '|' + x.querySelectorAll('option').length; })()`);
  check(cer(999) === '999|(Project of another admin)|3', 'Report to: "(Project of another admin)" selected: ' + cer(999));
  check(cer(5) === '5|Mine|2' && cer(0) === '0|Off|2', 'Report to: own project / Off as before, no extra option');
  // Admin alerts: the switch has its own words
  click(w, md.querySelector('[data-admsub="log"]'));
  const aa = await until(() => md.querySelector('#aa-on'));
  check(aa && /^Send alerts/.test(txt(aa.closest('label'))), 'Admin alerts: the switch says "Send alerts"');
  // Karakeep not connected: "Connect"
  w.eval(`document.querySelectorAll('.modal').forEach(m => m.remove()); settingsModal('karakeep')`);
  const kb = await until(() => d.querySelector('.smodal #s-kk [data-kks="save"]'));
  check(kb && txt(kb) === 'Connect', 'Karakeep without a connection: "Connect"');
  w.close();

  // ================= without an organisation: Notifications, Account and Karakeep with autosave
  check((await call('PUT', '/api/life/karakeep', {url: 'https://karakeep.example.com', token: 'kk-test-key', archive: true}, FK)).status === 200, 'frida: Karakeep connected (API)');
  w = await boot({user: 'frida'}); d = w.document;
  w.eval(`settingsModal('karakeep')`);
  md = await until(() => d.querySelector('.smodal #s-kk #kk-arch') && d.querySelector('.smodal'));
  check(md && !md.querySelector('[data-pane="org"] #s-uag') && txt(md.querySelector('#s-account-h')) === 'Profile', 'frida: no Organisation / Server, Account starts with Profile');
  const kk = md?.querySelector('#s-kk');
  check(kk && !kk.querySelector('[data-kks="save"]') && kk.querySelector('[data-kks="sync"]') && kk.querySelector('[data-kks="del"]'), 'connected: no Save button (Fetch now and Disconnect stay)');
  const arch = kk.querySelector('#kk-arch'); arch.checked = false; change(w, arch);
  check(await until(async () => (await call('GET', '/api/life/karakeep', null, FK)).archive === false), 'the tick saves itself on change');
  const url = kk.querySelector('#kk-url'); url.value = 'https://karakeep.example.com/'; change(w, url);
  check(await until(async () => { const j = await call('GET', '/api/life/karakeep', null, FK); return j.url === 'https://karakeep.example.com' && j.token_set; }), 'the address saves on change, the key stays for the same server');
  const np2 = md.querySelector('[data-pane="notify"]');
  if (w.eval('!!S.webpush?.enabled')) check(txt(np2.querySelector('[data-m="ptest"]')) === 'Test all channels' && !np2.querySelector('[data-m="test"]'), 'frida: "Test all channels", no second channel test');
  w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2555_c_settings_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
