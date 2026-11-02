// kalmido-suite: fresh
// 2.490.0 B UI tests, own container (start.sh). #4026: the interface in the colour of the shown workspace -- the accent (main
// buttons, active navigation, ticks, progress, focus) follows the workspace: an organisation's colour (my own choice first), Private
// keeps Kalmido's accent (my own choice first), "All workspaces" a neutral grey; each tone fitted so text on a button reaches 4.5:1
// (dark and light theme); setting ws_accent (Settings > Appearance, default on, off = the accent as before); the last shown colour
// is set from localStorage before the app draws; an open list's colour stays its own signal; backgrounds stay untinted.
// freelancer-matrix: n/a - nur Oberfläche (Person ohne Organisation: Privat-Fall + eigene Wahl, in der Datei geprüft)
// jsdom (classes / variables / the setting / freelancer) + Firefox at 1280, dark + light (computed accent, contrast on .btn.pri).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2490_b_ui', check, shots: 'P2490B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
// WCAG contrast of '#rrggbb' or 'rgb(r, g, b)'
const rgbOf = c => /^#/.test(c) ? [0, 2, 4].map(i => parseInt(c.slice(1).slice(i, i + 2), 16)) : (c.match(/\d+(\.\d+)?/g) || []).slice(0, 3).map(Number);
const lum = c => { const l = rgbOf(c).map(v => v / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2]; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => m - n); return (y + 0.05) / (x + 0.05); };
const PETROL = ['rgb(79, 179, 193)', 'rgb(24, 115, 129)'];  // Kalmido's accent, dark / light (app.css --acc-d / --acc-l)

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Studio', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', ws_colors: '{}'});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  check((await call('PATCH', '/api/orgs/' + ORG, {color: '#e0b05c'})).http === 200, 'the admins set the organisation colour');
  const WL = (await call('POST', '/api/lists', {name: 'Website', org_id: ORG})).id;
  const RL = (await call('POST', '/api/lists', {name: 'Red project', org_id: ORG, color: '#f87171'})).id;
  await call('POST', '/api/lists', {name: 'Garden', org_id: null});
  check((await call('GET', '/api/state')).settings.ws_accent === '1', '#4026: the setting is on by default');
  await call('PATCH', '/api/settings', {workspace: 'org:' + ORG});

  // ================= jsdom: the accent per workspace
  let w = await boot({hash: 'inbox'}), d = w.document;
  const html = () => d.documentElement, v = n => html().style.getPropertyValue(n);
  await until(() => html().classList.contains('wac-on'));
  const want = w.eval(`(() => { const t = WSC_TONES[wsc_ix(wsOrg(${ORG}).color, ${ORG})]; return [wac_fit(t[0], false), wac_fit(t[1], true)]; })()`);
  check(html().classList.contains('wac-on') && v('--wad') === want[0] && v('--wal') === want[1] && v('--waid') === '#0b0c0e' && v('--wail') === '#ffffff', '#4026: an organisation: the accent = its colour (fitted) ' + html().getAttribute('style'));
  check(!d.querySelector('#side').getAttribute('style')?.includes('--accent') && !d.querySelector('#app').getAttribute('style')?.includes('--accent'), '#4026: no background tint, only the accent variables on :root');
  check(w.__store['tasks.wsAccent'] === JSON.stringify([want[0], '#0b0c0e', want[1], '#ffffff'].join()), '#4026: the colour is remembered for the next start ' + w.__store['tasks.wsAccent']);
  // my own choice for the organisation wins
  w.eval(`S.settings.ws_colors = JSON.stringify({'org:${ORG}': 'teal'}); render()`);
  check(v('--wad') === '#2dd4bf' && v('--wal') === '#0f766e', '#4026: my own colour for the organisation wins ' + v('--wad'));
  w.eval(`S.settings.ws_colors = JSON.stringify({'org:${ORG}': 'none'}); render()`);
  check(v('--wad') === w.eval('wac_fit(WAC_GREY[0], false)') && v('--wal') === w.eval('wac_fit(WAC_GREY[1], true)'), '#4026: "No colour": the neutral grey');
  w.eval(`S.settings.ws_colors = '{}'; render()`);
  // Private: Kalmido's accent (no override), my own choice first
  await w.eval(`wsSet('private')`);
  await until(() => !html().classList.contains('wac-on'));
  check(!html().classList.contains('wac-on') && !v('--wad'), '#4026: Private without a choice: Kalmido\'s accent');
  check(!('tasks.wsAccent' in w.__store), '#4026: nothing remembered for Kalmido\'s accent');
  w.eval(`S.settings.ws_colors = JSON.stringify({private: 'blue'}); render()`);
  check(html().classList.contains('wac-on') && v('--wad') === '#6d8cff' && v('--wal') === '#3b5bdb', '#4026: Private: my own choice is the accent');
  w.eval(`S.settings.ws_colors = '{}'; render()`);
  // All workspaces: grey; every organisation list in the sidebar keeps its stripe on the left
  await w.eval(`wsSet('all')`);
  await until(() => v('--wad') === w.eval('wac_fit(WAC_GREY[0], false)'));
  check(html().classList.contains('wac-on') && v('--wad') === w.eval('wac_fit(WAC_GREY[0], false)'), '#4026: "All workspaces": the neutral grey');
  check(!!d.querySelector(`#side .srow[data-list="${WL}"][data-wsc]`), '#4026: "All workspaces": an organisation\'s list shows its workspace as a stripe on the left');
  // an open list with a colour: its own accent on #main stays (the list colour is its own signal)
  await w.eval(`wsSet('org:${ORG}')`);
  w.location.hash = 'l/' + RL;
  await until(() => d.querySelector('#main').classList.contains('lp-acc'));
  check(d.querySelector('#main').classList.contains('lp-acc') && d.querySelector('#main').style.getPropertyValue('--lpd') === '#f87171' && html().classList.contains('wac-on'), '#4026: an open list keeps its own colour as the accent of the list view');
  // contrast fitting: every tone (organisation palette, my list tones, grey, extreme colours) reaches 4.5:1 with its ink
  const fits = w.eval(`(() => { const out = []; const all = [...WSC_TONES.map(t => [t[0], t[1]]), ...LP_TONES.map(t => [t[2], t[4]]), WAC_GREY, ['#ffff00', '#ffff00'], ['#101010', '#101010'], ['#ffffff', '#000000']];
    for (const [dk, lt] of all) out.push([dk, wac_fit(dk, false), lt, wac_fit(lt, true)]); return out; })()`);
  const bad = fits.filter(([, fd, , fl]) => ratio(fd, '#0b0c0e') < 4.5 || ratio(fl, '#ffffff') < 4.5);
  check(fits.length > 20 && !bad.length, '#4026: every fitted tone reaches 4.5:1 for its ink (dark / light) ' + JSON.stringify(bad));
  check(w.eval(`wac_fit('#e0b05c', false)`) === '#e0b05c', '#4026: a tone already readable stays as it is');
  // the setting: Settings > Appearance, off = the accent as before (also for an organisation)
  w.eval(`settingsModal('look')`);
  const sw = await until(() => d.querySelector('#s-wacc'));
  check(sw && sw.checked && /Interface in the colour of the workspace/.test(sw.closest('label')?.textContent || ''), '#4026: the switch in Settings > Appearance, on by default');
  if (sw) { sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(await until(async () => (await call('GET', '/api/state')).settings.ws_accent === '0'), '#4026: switching off is saved');
  check(await until(() => !html().classList.contains('wac-on')), '#4026: off: Kalmido\'s accent in an organisation');
  check(!('tasks.wsAccent' in w.__store), '#4026: off: nothing remembered for the next start');
  d.querySelectorAll('.modal').forEach(x => x.remove());
  await call('PATCH', '/api/settings', {ws_accent: '1'});
  check((await call('PATCH', '/api/settings', {ws_accent: 'yes'})).http === 400, '#4026: the server takes only 0 / 1');
  w.close();

  // ================= jsdom: the remembered colour is on :root before the app draws (no flicker)
  const early = {};
  w = await boot({hash: 'inbox', ls: {'tasks.wsAccent': JSON.stringify('#123456,#0b0c0e,#654321,#ffffff')}, setup: win => {
    win.document.addEventListener('DOMContentLoaded', () => { early.cls = win.document.documentElement.className; early.wad = win.document.documentElement.style.getPropertyValue('--wad'); early.drawn = !!win.document.querySelector('#side .srow'); });
  }});
  check(/\bwac-on\b/.test(early.cls || '') && early.wad === '#123456' && !early.drawn, '#4026: the remembered colour is set before the first drawing ' + JSON.stringify(early));
  d = w.document;
  await until(() => d.documentElement.style.getPropertyValue('--wad') && d.documentElement.style.getPropertyValue('--wad') !== '#123456');
  check(d.documentElement.style.getPropertyValue('--wad') === want[0], '#4026: then the shown workspace\'s colour takes over');
  w.close();

  // ================= jsdom: a person without an organisation (Private + own choice)
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'}, FCK);
  check(((await call('GET', '/api/state', null, FCK)).me.workspaces || []).length === 0, 'frida has no organisation');
  w = await boot({user: 'frida', hash: 'inbox'}); d = w.document;
  await until(() => d.querySelector('#side .srow'), 60);
  check(!d.documentElement.classList.contains('wac-on'), 'freelancer: Private without a choice: Kalmido\'s accent');
  await call('PATCH', '/api/settings', {ws_colors: '{"private":"teal"}'}, FCK);
  w.eval(`S.settings.ws_colors = '{"private":"teal"}'; render()`);
  check(d.documentElement.classList.contains('wac-on') && d.documentElement.style.getPropertyValue('--wad') === '#2dd4bf', 'freelancer: my own choice is the accent');
  w.eval(`settingsModal('look')`);
  check(!!(await until(() => d.querySelector('#s-wacc'))), 'freelancer: the switch is there too');
  d.querySelectorAll('.modal').forEach(x => x.remove());
  w.close();

  // ================= Firefox 1280, dark + light: the computed accent and the contrast of text on .btn.pri
  const login2 = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); localStorage.setItem('tasks.lookLocal', 'true'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async ev => { for (let i = 0; i < 40 && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(250); };
  const PROBE = `(() => { const b = document.createElement('button'); b.className = 'btn pri'; b.textContent = 'Add'; document.querySelector('#view').append(b);
    const c = getComputedStyle(b), r = {bg: c.backgroundColor, fg: c.color, acc: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim(), cls: document.documentElement.className}; b.remove(); return r; })()`;
  for (const theme of ['dark', 'light']) {
    await call('PATCH', '/api/settings', {workspace: 'org:' + ORG, ws_colors: '{}'});
    await firefox(async o => {
      const {cmd, ev, ctx, shot} = o;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
      check(await login2(o, theme) === 200, `${theme}: login`);
      await o.nav(B + '#inbox'); await ready(ev);
      await ev(`(() => { document.querySelectorAll('.authscreen').forEach(e => e.remove()); document.querySelector('#app')?.removeAttribute('inert'); return 1; })()`);
      const want2 = theme === 'dark' ? want[0] : want[1];
      let p = await o.until(`(() => { const p = ${PROBE}; return /wac-on/.test(p.cls) ? p : null; })()`);
      check(p && p.bg === `rgb(${rgbOf(want2).join(', ')})` && ratio(p.bg, p.fg) >= 4.5, `${theme}: #4026 an organisation: .btn.pri in its colour, text >= 4.5:1 ` + JSON.stringify(p) + ' ' + (p && ratio(p.bg, p.fg).toFixed(2)));
      await shot(`p2490b-1280-${theme}-org.png`);
      await ev(`(() => { wsSet('private'); return 1; })()`);
      p = await o.until(`(() => { const p = ${PROBE}; return /wac-on/.test(p.cls) ? null : p; })()`);
      check(p && PETROL.includes(p.bg) && ratio(p.bg, p.fg) >= 4.5, `${theme}: #4026 Private: Kalmido's petrol ` + JSON.stringify(p));
      await ev(`(() => { wsSet('all'); return 1; })()`);
      p = await o.until(`(() => { const p = ${PROBE}; return /wac-on/.test(p.cls) ? p : null; })()`);
      const g = p && rgbOf(p.bg);
      check(p && g && Math.max(...g) - Math.min(...g) <= 12 && ratio(p.bg, p.fg) >= 4.5, `${theme}: #4026 All workspaces: a neutral grey, text >= 4.5:1 ` + JSON.stringify(p));
      await shot(`p2490b-1280-${theme}-all.png`);
      // the switch to "All" is saved before this browser closes, so the next round starts from the state set below
      check(await until(async () => (await call('GET', '/api/state')).settings.workspace === 'all'), `${theme}: the switch to All is saved`);
    }, false);
  }
  console.log(`p2490_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
