// kalmido-suite:
// 2.352.0 C (#2751 / #2752) UI tests: the dialog "Edit project" cleaned up. Own container (start.sh), jsdom, a person WITHOUT an
// organisation (as tests/freelancer_fixture.py; freelancer-matrix: tasks), invented names only.
// - no switch "Progress and status" any more; the status is chosen right in the dialog ("No status" = not followed) and saved
// - the basics stay on top (name, folder, view, status, sharing); the rest sits in folding parts, closed at first, each with
//   a short state in its folded line (Time and billing, Display and behaviour, Reminders, Project features, Actions)
// - a field in a folded part saves (autosave), the short state follows
// - open / closed is remembered per device: a part opened stays open when the dialog opens again
// - a part with a setting that differs from the folder carries a dot; the folder's box is one line, its values fold out
// - Firefox, computer and phone: the short state visible, closed parts take no room, a click on a line opens and remembers,
//   nothing sticks out at the side (screenshots with P2352C_SHOTS)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2352C_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const lastModal = d => [...d.querySelectorAll('.modal')].pop();
const change = (w, el) => el.dispatchEvent(new w.Event('change', {bubbles: true}));
const listOf = async id => ((await call('GET', '/api/state')).lists || []).find(l => l.id === id) || {};
const firefox = require('./ff')({tag: 'p2352_c_listmodal_ui', check, shots: 'P2352C_SHOTS'});
const st = (md, k) => md.querySelector(`#lm-sec-${k} .shsecst`)?.textContent || '';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, AK);
  await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: (await call('GET', '/api/state', null, AK)).me.id}, AK);  // a server with organisations
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  CK = await login('frida');
  const st0 = await call('GET', '/api/state');
  const feats = [...new Set([...(st0.settings.features || '').split(',').filter(Boolean), 'progress', 'time', 'deps', 'fields', 'collab'])].join(',');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: feats});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida is in no organisation');
  const P = (await call('POST', '/api/lists', {name: 'Launch', kind: 'project', folder: 'Clients'})).id;
  check(P && (await listOf(P)).kind === 'project', 'a kind=project project in the folder Clients');
  // the folder switches time tracking on, the project switches it off on its own: it differs from the folder
  await call('PUT', '/api/folders/props', {folder: 'Clients', props: {time_tracking: true}});
  await call('PATCH', '/api/lists/' + P, {time_tracking: false});
  check(/time_tracking/.test((await listOf(P)).folder_own || ''), 'setup: the project differs from its folder (time tracking)');

  let w = await boot({user: 'frida', hash: 'l/' + P}), d = w.document;
  await until(() => w.eval(`!!listById(${P})`));
  w.eval(`LS.del('lmSecs')`);
  w.eval(`listModal(${P})`);
  let md = await until(() => d.querySelector('.modal.lmodal'));
  // ================= no switch, the status instead
  check(md && !md.querySelector('#l-kindp') && !md.querySelector('.lkrow') && !/Progress and status/.test(md.textContent), 'no switch "Progress and status" any more');
  const sel = md?.querySelector('#l-status');
  check(sel && !sel.closest('details') && sel.options[0].value === '' && /No status/.test(sel.options[0].textContent) && sel.value === '', 'the status on top, "No status" chosen');
  // ================= the basics on top, the rest folded with a short state
  check(['#l-name', '#l-folder', '#l-view', '#l-shsum'].every(s => md.querySelector(s) && !md.querySelector(s).closest('details.lmsec')), 'name, folder, view and sharing stay on top');
  const secs = [...md.querySelectorAll('details.lmsec')].map(x => x.dataset.lmsec);
  check(['time', 'show', 'remind', 'proj', 'acts'].every(k => secs.includes(k)) && secs.indexOf('acts') === secs.length - 1, 'the parts, Actions last: ' + secs.join(','));
  check([...md.querySelectorAll('details.lmsec')].every(x => !x.open), 'every part closed at first');
  check(md.querySelector('#lm-sec-time #l-time') && md.querySelector('#lm-sec-show #l-dab') && md.querySelector('#lm-sec-remind #l-nag') && md.querySelector('#lm-sec-proj #l-ptype') && md.querySelector('#lm-sec-acts [data-m="arch"]'), 'the fields in their parts');
  check(/Time tracking: Off/.test(st(md, 'time')), 'the folded line says the state: ' + st(md, 'time'));
  check(/Default/.test(st(md, 'remind')), 'reminders: Default ' + st(md, 'remind'));
  // ================= the dot: differs from the folder; the folder's box one line
  check(md.querySelector('#lm-sec-time summary .lmdot') && !md.querySelector('#lm-sec-show summary .lmdot') && !md.querySelector('#lm-sec-remind summary .lmdot'), 'a dot only at the part that differs from the folder');
  const fh = md.querySelector('#l-fhint');
  check(fh && !fh.hidden && fh.querySelector('details.lfhd:not([open]) > summary') && /From the folder “Clients”/.test(fh.querySelector('summary').textContent) && !fh.querySelector('.fown') && fh.querySelector('details [data-freset]'), 'the folder box: one line, values and "Back to the folder" fold out, nothing crossed out');
  // ================= a field in a folded part saves; the short state follows
  const nag = md.querySelector('#l-nag');
  nag.value = nag.options[1].value; change(w, nag);
  check(await until(async () => (await listOf(P)).nag === nag.options[1].value), 'Repeat reminders from the folded part saved');
  check(await until(() => md.querySelector('.ssaved.on')), 'the dialog says Saved');
  check(await until(() => /Repeat reminders: /.test(st(md, 'remind'))), 'the folded line follows: ' + st(md, 'remind'));
  const tt = md.querySelector('#l-time');
  tt.checked = true; change(w, tt);
  check(await until(async () => (await listOf(P)).time_tracking === 1), 'time tracking from the folded part saved');
  const rate = md.querySelector('#l-rate');
  rate.value = '90'; rate.dispatchEvent(new w.Event('input', {bubbles: true}));
  check(await until(async () => +(await listOf(P)).rate === 90), 'the hourly rate (typed, autosave) saved');
  check(await until(() => /Time tracking/.test(st(md, 'time')) && /Hourly rate: 90/.test(st(md, 'time'))), 'time: the state names the switch and the rate: ' + st(md, 'time'));
  check(!/server default|\(Server\)/i.test(md.textContent), 'hours per day: the hint without "(Server)"');
  // ================= the status: set and cleared from the dialog
  sel.value = 'at_risk'; change(w, sel);
  check(await until(async () => (await listOf(P)).status === 'at_risk'), 'status set from the dialog');
  sel.value = ''; change(w, sel);
  check(await until(async () => !(await listOf(P)).status), 'status cleared ("No status")');
  // ================= open / closed remembered
  const rem = md.querySelector('#lm-sec-remind');
  rem.open = true; rem.dispatchEvent(new w.Event('toggle'));
  check(await until(() => w.eval(`(LS.get('lmSecs', {}) || {}).remind === true`)), 'opening a part is remembered');
  md.querySelector('.lhdr [data-m="close"]').click();
  check(await until(() => !d.querySelector('.modal.lmodal')), 'closed');
  w.eval(`listModal(${P})`);
  md = await until(() => d.querySelector('.modal.lmodal'));
  check(md?.querySelector('#lm-sec-remind')?.open && !md.querySelector('#lm-sec-time').open, 'opened again: Reminders open, the others closed');
  md.querySelector('.lhdr [data-m="close"]').click();
  await until(() => !d.querySelector('.modal.lmodal'));
  // ================= a new project: folded parts too, no switch
  w.eval('listModal()');
  md = await until(() => d.querySelector('.modal.lnew'));
  check(md && !md.querySelector('#l-kindp') && md.querySelector('#lm-sec-proj .lptype') && md.querySelector('[data-m="save"]') && !md.querySelector('#lm-sec-acts'), 'new project: Start from in Project features, no actions part');
  md.remove();
  w.close();

  // ================= German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'frida', hash: 'l/' + P}); d = w.document;
  await until(() => w.eval('typeof tr') === 'function' && w.eval("tr('Edit project')") === 'Projekt bearbeiten', 40);
  w.eval(`listModal(${P})`);
  md = await until(() => d.querySelector('.modal.lmodal'));
  const heads = [...(md?.querySelectorAll('details.lmsec > summary h4') || [])].map(x => x.textContent).join('|');
  check(/Zeit & Abrechnung/.test(heads) && /Anzeige & Verhalten/.test(heads) && /Projekt-Funktionen/.test(heads) && /Aktionen/.test(heads), 'de: the parts ' + heads);
  w.close();

  // ================= the real layout (Firefox): computer and phone, the folded parts, a click on a part's line opens it
  await call('PATCH', '/api/settings', {lang: 'en'});
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // the parts of a closed <details> keep their boxes in Firefox (content-visibility): only what is really shown counts
  const noSide = `(() => { const W = document.documentElement.clientWidth; const bad = [...document.querySelectorAll('.modal *')].filter(e => e.getClientRects().length && e.checkVisibility() && e.getBoundingClientRect().right > W + 1); return bad.length ? bad.slice(0, 3).map(e => e.tagName + '#' + e.id + '.' + e.className + ' ' + Math.round(e.getBoundingClientRect().right)).join(', ') : 'ok'; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    for (const [vw, vh, tag] of [[1280, 900, 'desktop'], [390, 844, 'phone']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
      await nav(B + '#l/' + P);
      check(await ready(ev, `typeof listModal === 'function' && !!listById(${P})`, 80), `${tag}: the app is up`);
      await ev(`(() => { listModal(${P}); return 1; })()`);
      check(await ready(ev, `!!document.querySelector('.modal.lmodal #lm-sec-time .shsecst')?.textContent`), `${tag}: the dialog with its parts`);
      check(await ev(`(() => { const s = document.querySelector('#lm-sec-time .shsecst'); const r = s.getBoundingClientRect(); return r.width > 20 && getComputedStyle(s).visibility === 'visible'; })()`), `${tag}: the short state is visible in the folded line`);
      check(await ev(`!document.querySelector('#l-nag').checkVisibility()`), `${tag}: a field of a closed part is not shown`);
      { const r = await ev(noSide); check(r === 'ok', `${tag}: the dialog stays inside the screen ${r}`); }
      await shot(`p2352-c-${tag}-closed.png`);
      await ev(`(() => { document.querySelector('#lm-sec-time > summary').click(); return 1; })()`);
      check(await ready(ev, `document.querySelector('#lm-sec-time').open && document.querySelector('#l-time').getBoundingClientRect().height > 0 && JSON.parse(localStorage.getItem('tasks.lmSecs') || '{}').time === true`), `${tag}: a click on the line opens the part, remembered`);
      { const r = await ev(noSide); check(r === 'ok', `${tag}: open, still inside the screen ${r}`); }
      await shot(`p2352-c-${tag}-time-open.png`);
      await ev(`(() => { document.querySelector('#lm-sec-show > summary').click(); return 1; })()`);
      await ready(ev, `document.querySelector('#lm-sec-show').open`);
      await ev(`(() => { document.querySelector('#lm-sec-show').scrollIntoView({block: 'start'}); return 1; })()`);
      await shot(`p2352-c-${tag}-show-open.png`);
    }
  }, false);

  console.log(`\n${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
