// 2.57.0 part B UI test, own container (start.sh). jsdom + Firefox (WebDriver BiDi, skipped without firefox):
// #1807 my own colour per workspace (setting ws_colors {"private" | "org:<id>": tone of the 12 list tones | "none"}):
//       the server checks it strictly (400); without a choice an organisation keeps its admins' colour and Private stays
//       neutral; my choice wins for the sidebar stripe, the switch, the chip and a list's sign; "none" makes an
//       organisation neutral; the sidebar gets a light tint (--sbbg on #side) while one workspace is shown, never under
//       "All"; a dot in front of each workspace in the switch and its menu; Settings > Workspaces has the swatches (one
//       Undo step per change); the tint keeps the sidebar's text readable (contrast, both themes); the phone drawer
//       takes the tint too.
// 2.138.2 (#2389): no tint any more -- the shown workspace's colour is the stripe on top of the sidebar (--wbd / --wbl on
//       #app, class wsb-on; Private without a choice = the accent, "none" / "All" = grey); the checks below follow.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p257_b_ui', check, shots: 'P257B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
// WCAG contrast and color-mix(in srgb, tone p%, base) as the browser computes it (per channel, gamma-encoded)
const rgb = hex => [0, 2, 4].map(i => parseInt(hex.replace('#', '').slice(i, i + 2), 16));
const lum = c => { const l = c.map(v => v / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2]; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => m - n); return (y + 0.05) / (x + 0.05); };
const mix = (tone, p, base) => rgb(tone).map((v, i) => Math.round(v * p + rgb(base)[i] * (1 - p)));

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Org', lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const W = (await call('POST', '/api/lists', {name: 'Website', org_id: ORG})).id;
  const P = (await call('POST', '/api/lists', {name: 'Garden', org_id: null})).id;
  check((await call('PATCH', '/api/orgs/' + ORG, {color: '#ef8a6b'})).color === '#ef8a6b', 'the admins set the organisation colour');

  // ---- the server: strict, per person
  check((await call('GET', '/api/state')).settings.ws_colors === '{}', '#1807: default ws_colors = {}');
  for (const bad of ['{"org:x":"blue"}', '{"private":"magenta"}', '{"Private":"red"}', '[]', '{"org:0":"red"}', 'nojson', '{"private":"#2dd4bf"}',
    JSON.stringify(Object.fromEntries(Array.from({length: 101}, (_, i) => ['org:' + (i + 1), 'red'])))]) {
    check((await call('PATCH', '/api/settings', {ws_colors: bad})).status === 400, '#1807: invalid ws_colors refused: ' + bad.slice(0, 40));
  }
  check((await call('PATCH', '/api/settings', {ws_colors: {private: 'red'}})).status === 400, '#1807: an object instead of the json text is refused');
  check((await call('PATCH', '/api/settings', {ws_colors: `{"private":"teal","org:${ORG}":"blue","org:99999":"none"}`})).status === 200, '#1807: a valid value is stored');
  check((await call('GET', '/api/state')).settings.ws_colors === `{"private":"teal","org:${ORG}":"blue","org:99999":"none"}`, '#1807: read back unchanged');
  const bob = await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com'});
  check(!!bob.id, 'bob created');
  const CB = await login('bob');
  check((await call('GET', '/api/state', null, CB)).settings.ws_colors === '{}', '#1807: another person never gets my colours');
  await call('PATCH', '/api/settings', {ws_colors: '{}', workspace: 'org:' + ORG});

  // ---- without a choice: as before (the admins' colour, Private neutral); the tint follows the shown workspace
  let w = await boot({user: 'alice', hash: 'l/' + W}), d = w.document;
  const side = () => d.querySelector('#app'), bar = () => d.querySelector('#side .wsbar'), sign = () => d.querySelector('#top h1 .wsbadge');
  await until(() => bar());
  check(w.eval(`wsc_tone(${ORG})[0]`) === '#ef8a6b' && w.eval(`wsp_tone('private')`) === null, '#1807: no choice: the organisation shows its admins\' colour, Private none');
  check(side().classList.contains('wsb-on') && side().style.getPropertyValue('--wbd') === '#ef8a6b' && !d.querySelector('#side').classList.contains('wsp-on'), '#1807: an organisation shown: the sidebar stripe in its colour, no tint (2.138.2 #2389)');
  check(bar()?.dataset.wsc === '1' && bar().querySelector('.wsp-dot[data-wsc]'), '#1807: the switch carries a coloured dot in front of the name');
  check(d.querySelector(`#side .srow[data-list="${W}"]`)?.style.getPropertyValue('--wsd') === '#ef8a6b', '#1807: no choice: the sidebar stripe as before');

  // ---- Settings > Workspaces: the swatches; a tap stores, one Undo step
  w.eval(`settingsModal(lmOrgPaneOn() ? 'org' : 'account')`); await until(() => d.querySelector('.wsp-pane'));
  const prow = () => d.querySelector('.wsp-row[data-wsp="private"]'), orow = () => d.querySelector(`.wsp-row[data-wsp="org:${ORG}"]`);
  check(prow()?.querySelectorAll('[data-wspc]').length === 13 && orow()?.querySelectorAll('[data-wspc]').length === 14, '#1807: Private: no colour + 12 tones; an organisation: Default + no colour + 12');
  check(prow().querySelector('[data-wspc=""]').getAttribute('aria-pressed') === 'true' && orow().querySelector('[data-wspc=""].wsp-def[aria-pressed="true"]'), '#1807: no choice: "No color" / "Default" pressed');
  check(orow().querySelector('[data-wspc=""]').getAttribute('aria-label') === 'Default (colour of the organisation)' && orow().querySelector('.colors[role="group"][aria-label]'), '#1807: the swatches are named for screen readers');
  click(w, prow().querySelector('[data-wspc="teal"]'));
  check(await until(async () => (await call('GET', '/api/state')).settings.ws_colors === '{"private":"teal"}'), '#1807: a tap stores my colour of Private');
  check(prow().querySelector('[data-wspc="teal"]').getAttribute('aria-pressed') === 'true', '#1807: the tapped tone is pressed');
  click(w, orow().querySelector('[data-wspc="none"]'));
  check(await until(async () => JSON.parse((await call('GET', '/api/state')).settings.ws_colors)['org:' + ORG] === 'none'), '#1807: "No color" for the organisation');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await call('GET', '/api/state')).settings.ws_colors === '{"private":"teal"}'), '#1807: one Undo step takes the last change back');
  check(orow().querySelector('[data-wspc=""]').getAttribute('aria-pressed') === 'true', '#1807: after Undo "Default" is pressed again');
  await w.eval(`histStep('redo')`);
  check(await until(async () => JSON.parse((await call('GET', '/api/state')).settings.ws_colors)['org:' + ORG] === 'none'), '#1807: Redo');
  d.querySelectorAll('.modal').forEach(x => x.remove());

  // ---- "none": the organisation neutral everywhere (no tint, no stripe, no colour at the switch, a ring as the dot)
  w.eval('render()');
  await until(() => !side().classList.contains('wsb-on'));
  check(!side().classList.contains('wsb-on') && !side().style.getPropertyValue('--wbd'), '#1807: "none": a grey stripe (2.138.2 #2389)');
  check(!d.querySelector(`#side .srow[data-list="${W}"]`)?.dataset.wsc && !d.querySelector('#main').classList.contains('wsc-on'), '#1807: "none": no stripe, no header stripe');
  check(!bar().dataset.wsc && bar().querySelector('.wsp-dot') && !bar().querySelector('.wsp-dot[data-wsc]'), '#1807: "none": the dot is a ring');
  // my own tone wins over the admins' colour
  w.eval(`S.settings.ws_colors = JSON.stringify({private: 'teal', 'org:${ORG}': 'blue'}); render()`);
  check(side().style.getPropertyValue('--wbd') === '#6d8cff' && side().style.getPropertyValue('--wbl') === '#3b5bdb', '#1807: my tone wins: the list tone (dark / light value)');
  check(d.querySelector(`#side .srow[data-list="${W}"]`)?.style.getPropertyValue('--wsd') === '#6d8cff' && sign()?.getAttribute('style')?.includes('#6d8cff'), '#1807: also the sidebar stripe and the list\'s sign');
  // the menu of the switch: a dot in front of each workspace, none in front of "All"
  click(w, bar());
  await until(() => d.querySelector('#pop:not(.hidden) [role="menuitem"]'));
  const items = [...d.querySelectorAll('#pop [role="menuitem"]')];
  check(items.length === 3 && items.filter(x => x.querySelector('.wsp-dot')).length === 2 && items[0].querySelector('.wsp-dot[data-wsc]')?.getAttribute('style')?.includes('#2dd4bf'), '#1807: the switch menu: a dot per workspace (Private in my teal), none for "All"');
  w.eval('closePop()');
  // Private shown: my colour; "All": neutral
  w.eval(`S.settings.workspace = 'private'; go(keyToHash('l:${P}')); render()`);
  await until(() => side().style.getPropertyValue('--wbd') === '#2dd4bf');
  check(side().classList.contains('wsb-on') && side().style.getPropertyValue('--wbd') === '#2dd4bf', '#1807: Private shown: the stripe in my colour');
  check(sign()?.dataset.wsc === '1', '#1807: a private list\'s sign takes my colour of Private');
  check(!d.querySelector(`#side .srow[data-list="${P}"]`)?.dataset.wsc, '#1807: private lists keep no stripe');
  w.eval(`S.settings.workspace = 'all'; render()`);
  check(!side().classList.contains('wsb-on') && !bar().querySelector('.wsp-dot') && !bar().dataset.wsc, '#1807: "All": grey stripe, no dot');
  w.close();

  // ---- contrast: the tinted sidebar keeps text, secondary text and muted readable (every tone, both themes)
  const css = await (await fetch(B + 'static/app.css')).text();
  const vars = sel => { const m = css.match(new RegExp(sel.replace(/[[\]()"=]/g, '\\$&') + '\\{([^}]*)\\}')); const o = {}; if (m) for (const [, k, v] of m[1].matchAll(/--([\w-]+):([^;]+)/g)) o[k] = v.trim(); return o; };
  const dark = vars(':root'), light = vars(':root[data-theme="light"]');
  // 2.138.2 (#2389): the tint is gone -- the sidebar keeps bg2 in every workspace, so its text contrast is the theme's own
  check(!/#side\.wsp-on\{--wsc/.test(css) && /#side\{border-top:\.25rem solid var\(--wbc\)\}/.test(css), '#1807 / #2389: no tint rule any more, a 4 px stripe instead');
  check(/#side\{background:var\(--sbbg,var\(--bg2\)\)\}/.test(css), '#1807: #side takes --sbbg (the fixed head shares it)');

  // ---- the real browser: the computed background of #side differs from bg2 (desktop dark + light, the phone drawer)
  await call('PATCH', '/api/settings', {ws_colors: JSON.stringify({private: 'teal', ['org:' + ORG]: 'blue'}), workspace: 'org:' + ORG});
  const ready = async (ev, expr, n = 60) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  const bgOf = `getComputedStyle(document.querySelector('#side')).backgroundColor`;
  for (const theme of ['dark', 'light']) {
    await firefox(async ({cmd, ev, ctx, nav}) => {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); localStorage.setItem('tasks.lastKey', '"today"'); return 1; })()`);
      await signIn(ev);
      await nav(B + '#today');
      await ready(ev, `typeof S !== 'undefined' && !!S.booted && !!document.querySelector('#side .wsbar')`);
      await ready(ev, `document.querySelector('#app').classList.contains('wsb-on')`);
      const tinted = await ev(bgOf), stripe = await ev(`getComputedStyle(document.querySelector('#side')).borderTopColor`);
      await ev(`(() => { S.settings.workspace = 'all'; render(); return 1; })()`);
      await sleep(400);  // Firefox restyles the sidebar after the script that changed it returned
      const plain = await ev(bgOf);
      const bg2 = await ev(`(() => { const e = document.createElement('div'); e.style.background = 'var(--bg2)'; document.body.append(e); const c = getComputedStyle(e).backgroundColor; e.remove(); return c; })()`);
      const stripeAll = await ev(`getComputedStyle(document.querySelector('#side')).borderTopColor`);
      check(tinted && plain && tinted === plain && plain === bg2, `#1807 ${theme}: 2.138.2 (#2389): no tint, the sidebar stays bg2 (${tinted} vs ${plain})`);
      check(stripe && stripeAll && stripe !== stripeAll && stripe !== 'rgba(0, 0, 0, 0)', `#2389 ${theme}: the stripe takes my tone, grey under "All" (${stripe} / ${stripeAll})`);
      // the phone: the drawer shows the same tint
      await ev(`(() => { S.settings.workspace = 'org:${ORG}'; render(); return 1; })()`);
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
      await sleep(300);
      await ev(`(() => { sideOpenDrawer(); return 1; })()`);
      await ready(ev, `document.querySelector('#side').classList.contains('open')`, 20);
      check(await ev(`document.querySelector('#side').classList.contains('open') && ${bgOf} === ${JSON.stringify(tinted)} && getComputedStyle(document.querySelector('#side')).borderTopColor === ${JSON.stringify(stripe)}`), `#1807 ${theme}: 390 px drawer: no tint, the same stripe`);
    });
  }

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
