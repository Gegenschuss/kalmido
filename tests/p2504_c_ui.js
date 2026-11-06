// kalmido-suite: fresh
// 2.504.0 C UI tests, own container (start.sh). #4222: "All workspaces" has no colour of its own and no grey: what belongs to a
// workspace wears that workspace's accent (a row of a mixed view, the open list's view, the task panel), everything else (navigation,
// head bar, sidebar, + button) Kalmido's accent; a list's own colour still wins in the open list; "No colour" = global; the switch
// ws_accent off keeps the old look (grey stripe, hollow dot); a person without an organisation stays unchanged.
// freelancer-matrix: n/a - nur Oberfläche (Person ohne Organisation in der Datei geprüft)
// jsdom (classes / variables / memo) + Firefox at 1280, dark + light (the computed colours, derived ones included).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2504_c_ui', check, shots: 'P2504C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});
const rgbOf = c => /^#/.test(c) ? [0, 2, 4].map(i => parseInt(c.slice(1).slice(i, i + 2), 16)) : (c.match(/\d+(\.\d+)?/g) || []).slice(0, 3).map(Number);
const rgb = c => `rgb(${rgbOf(c).join(', ')})`;
const lum = c => { const l = rgbOf(c).map(v => v / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); return 0.2126 * l[0] + 0.7152 * l[1] + 0.0722 * l[2]; };
const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((m, n) => m - n); return (y + 0.05) / (x + 0.05); };
const PETROL = {dark: 'rgb(79, 179, 193)', light: 'rgb(24, 115, 129)'};  // Kalmido's accent (app.css --acc-d / --acc-l)
const ORG_TONE = {dark: '#e0b05c', light: '#85600f'};  // WSC_TONES, nearest to the colour the admins set below
const RED = {dark: 'rgb(248, 113, 113)', light: 'rgb(196, 48, 43)'};  // LP_TONES red

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Studio', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', ws_colors: '{}', workspace: 'all'});
  const st = await call('GET', '/api/state'), ORG = st.me.workspaces[0].id, INBOX = st.lists.find(l => l.is_inbox).id;
  check((await call('PATCH', '/api/orgs/' + ORG, {color: '#e0b05c'})).http === 200, 'the admins set the organisation colour');
  const WL = (await call('POST', '/api/lists', {name: 'Website', org_id: ORG})).id;
  const RL = (await call('POST', '/api/lists', {name: 'Red project', org_id: ORG, color: '#f87171'})).id;
  const PL = (await call('POST', '/api/lists', {name: 'Garden', org_id: null})).id;

  // ================= jsdom
  let w = await boot({hash: 'today'}), d = w.document;
  await until(() => d.querySelector('#side .srow'));
  const TODAY = w.eval('today()');
  const task = async (list_id, title) => (await call('POST', '/api/tasks', {list_id, title, due: TODAY})).id;
  const TW = await task(WL, 'Org row'), TP = await task(PL, 'Private row'), TI = await task(INBOX, 'Inbox row'), TR = await task(RL, 'Red row');
  await call('PATCH', '/api/tasks/' + TR, {status: 2});  // a done row: its tick wears the accent
  w.close();

  w = await boot({hash: 'today'}); d = w.document;
  const html = () => d.documentElement, app = () => d.querySelector('#app');
  const row = id => d.querySelector(`#view .trow[data-id="${id}"]`);
  await until(() => row(TW) && row(TP));
  const want = w.eval(`(() => { const t = WSC_TONES[wsc_ix(wsOrg(${ORG}).color, ${ORG})]; return [wac_fit(t[0], false), wac_fit(t[1], true)]; })()`);
  const isOrgTone = el => el?.classList.contains('wac-loc') && el.style.getPropertyValue('--wad') === want[0] && el.style.getPropertyValue('--wal') === want[1] && el.style.getPropertyValue('--waid') === '#0b0c0e' && el.style.getPropertyValue('--wail') === '#ffffff';

  // "All": no grey, no colour of its own
  check(!html().classList.contains('wac-on') && !html().style.getPropertyValue('--wad'), '#4222: "All": :root keeps Kalmido\'s accent, no grey');
  check(!('tasks.wsAccent' in w.__store), '#4222: "All": nothing remembered for the next start');
  check(app().classList.contains('wsb-on') && app().style.getPropertyValue('--wbd') === 'var(--accent)' && app().style.getPropertyValue('--wbl') === 'var(--accent)', '#4222: "All": the stripe in the global accent');
  check(w.eval(`wsp_dot('all')`).includes('var(--accent)'), '#4222: "All": the dot is not a hollow ring');
  check(w.eval(`typeof WAC_GREY`) === 'undefined', '#4222: the grey is gone');
  // the rows of a mixed view: only variables on the row, no new mark
  check(isOrgTone(row(TW)), '#4222: a row of an organisation wears its tone ' + row(TW)?.getAttribute('style'));
  check(!row(TP).classList.contains('wac-loc') && !row(TI)?.classList.contains('wac-loc'), '#4222: Private without a choice and the inbox stay global');
  check(!d.querySelector('#kbar .wac-loc, #side .wac-loc, #top .wac-loc, #tabs .wac-loc') && !d.querySelector('#fab').classList.contains('wac-loc') && !d.querySelector('#main').classList.contains('wac-loc'), '#4222: head bar, sidebar, header, + button stay global');
  check(!d.querySelector('#view').classList.contains('wac-loc'), '#4222: a mixed view itself has no tone');
  // the calendar cards take it through the same place
  check(w.eval(`lp_cls(taskById(${TW}))`).includes('wac-loc') && w.eval(`lp_sty(taskById(${TW}))`).includes('--wad:' + want[0]), '#4222: the shared place of rows and cards');
  // the kept tone follows the settings and the organisation's colour
  w.eval(`S.settings.ws_colors = JSON.stringify({private: 'blue', 'org:${ORG}': 'teal'}); render()`);
  await until(() => row(TP)?.classList.contains('wac-loc'));
  check(row(TP)?.classList.contains('wac-loc') && row(TP).style.getPropertyValue('--wad') === '#6d8cff' && row(TP).style.getPropertyValue('--wal') === '#3b5bdb', '#4222: Private with my own choice wears it');
  check(row(TI)?.classList.contains('wac-loc') && row(TI).style.getPropertyValue('--wad') === '#6d8cff', '#4222: the inbox counts as Private');
  check(row(TW)?.style.getPropertyValue('--wad') === '#2dd4bf', '#4222: my own colour for the organisation, the kept tone is not stale');
  w.eval(`S.settings.ws_colors = '{}'; wsOrg(${ORG}).color = '#ef8a6b'; render()`);
  await until(() => row(TW)?.style.getPropertyValue('--wad') === '#ef8a6b');
  check(row(TW)?.style.getPropertyValue('--wad') === '#ef8a6b', '#4222: the organisation\'s colour changes, the kept tone follows');
  w.eval(`wsOrg(${ORG}).color = '#e0b05c'; render()`);
  await until(() => isOrgTone(row(TW)));
  // "No colour": global
  w.eval(`S.settings.ws_colors = JSON.stringify({'org:${ORG}': 'none'}); render()`);
  await until(() => !row(TW)?.classList.contains('wac-loc'));
  check(row(TW) && !row(TW).classList.contains('wac-loc') && !row(TW).style.getPropertyValue('--wad'), '#4222: a workspace with "No colour": its rows stay global');
  w.eval(`S.settings.ws_colors = '{}'; render()`);
  await until(() => isOrgTone(row(TW)));

  // an open list in "All": the view, not the row nor the header; a list's own colour wins
  w.location.hash = 'l/' + WL;
  await until(() => d.querySelector('#view').classList.contains('wac-loc'));
  check(isOrgTone(d.querySelector('#view')), '#4222: an open list: its view in the workspace\'s tone');
  check(!row(TW)?.classList.contains('wac-loc'), '#4222: an open list: the rows need no tone of their own');
  check(!d.querySelector('#main').classList.contains('wac-loc') && !d.querySelector('#top').classList.contains('wac-loc'), '#4222: an open list: the header stays global');
  w.location.hash = 'l/' + RL;
  await until(() => d.querySelector('#main').classList.contains('lp-acc'));
  check(!d.querySelector('#view').classList.contains('wac-loc') && d.querySelector('#main').style.getPropertyValue('--lpd') === '#f87171', '#4222: a list\'s own colour wins in the open list');
  w.location.hash = 'l/' + PL;
  await until(() => !d.querySelector('#main').classList.contains('lp-acc'));
  check(!d.querySelector('#view').classList.contains('wac-loc'), '#4222: an open private list without a choice: global');
  // the task panel: the task's workspace
  w.location.hash = 'today';
  await until(() => row(TW));
  w.eval(`openDetail(${TW})`);
  await until(() => d.querySelector('#detail').classList.contains('wac-loc'));
  check(isOrgTone(d.querySelector('#detail')), '#4222: the task panel in the tone of the task\'s workspace');
  w.eval(`openDetail(${TP})`);
  await until(() => !d.querySelector('#detail').classList.contains('wac-loc'));
  check(!d.querySelector('#detail').classList.contains('wac-loc'), '#4222: the panel of a private task: global');
  w.eval(`closeDetail()`);
  // one workspace shown: the tone is at :root, nothing local
  await w.eval(`wsSet('org:${ORG}')`);
  await until(() => html().classList.contains('wac-on'));
  await until(() => row(TW) && !row(TW).classList.contains('wac-loc'));
  check(html().style.getPropertyValue('--wad') === want[0] && !d.querySelector('#view .wac-loc'), '#4222: one workspace shown: the tone at :root, no local one');
  await w.eval(`wsSet('all')`);
  await until(() => !html().classList.contains('wac-on') && row(TW)?.classList.contains('wac-loc'));
  // the switch off: everything as before, grey stripe and hollow dot in "All"
  w.eval(`S.settings.ws_accent = '0'; render()`);
  await until(() => !app().classList.contains('wsb-on'));
  check(!app().classList.contains('wsb-on') && !app().style.getPropertyValue('--wbd'), '#4222: off: "All" has the grey stripe');
  check(!w.eval(`wsp_dot('all')`).includes('data-wsc'), '#4222: off: the hollow dot');
  check(row(TW) && !d.querySelector('.wac-loc') && !html().classList.contains('wac-on'), '#4222: off: no local tone anywhere');
  w.eval(`S.settings.ws_colors = JSON.stringify({'org:${ORG}': 'none'}); render()`);
  check(!w.eval(`wsp_dot('org:${ORG}')`).includes('data-wsc'), '#4222: off: "No colour" keeps the hollow dot');
  w.eval(`S.settings.ws_colors = '{}'; S.settings.ws_accent = '1'; render()`);
  w.close();

  // ================= jsdom: a person without an organisation (wsCur() is 'all' there too): unchanged
  await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const FCK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', ws_colors: '{"private":"teal"}'}, FCK);
  const FL = (await call('POST', '/api/lists', {name: 'Frida list'}, FCK)).id;
  const FT = (await call('POST', '/api/tasks', {list_id: FL, title: 'Frida row', due: TODAY}, FCK)).id;
  w = await boot({user: 'frida', hash: 'today'}); d = w.document;
  await until(() => d.querySelector(`#view .trow[data-id="${FT}"]`));
  const frow = d.querySelector(`#view .trow[data-id="${FT}"]`);
  check(frow && !frow.classList.contains('wac-loc') && !d.querySelector('.wac-loc'), 'freelancer: no local tone');
  check(d.documentElement.classList.contains('wac-on') && d.documentElement.style.getPropertyValue('--wad') === '#2dd4bf', 'freelancer: my own choice at :root as before');
  check(d.querySelector('#app').style.getPropertyValue('--wbd') === '#2dd4bf', 'freelancer: the stripe in my choice');
  w.close();

  // ================= Firefox 1280, dark + light: the computed colours (the derived ones follow, the header does not)
  const signIn = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); localStorage.setItem('tasks.lookLocal', 'true'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  // what a real element shows inside a part of the page: a main button, a progress bar, the soft fill and the fill of a finished status (a checked tick itself is --faint in every workspace since 2.41.0, #1477)
  const PROBE = host => `(() => { const h = ${host}; if (!h) return null; const b = document.createElement('button'); b.className = 'btn pri'; b.textContent = 'Add'; const k = document.createElement('span'); k.className = 'lprog'; k.innerHTML = '<span class="pbar"><i></i></span>'; const p = document.createElement('i'); p.style.background = 'var(--accent-soft)'; const c = document.createElement('i'); c.style.background = 'var(--st-complete)'; h.append(b, k, p, c);
    const r = {bg: getComputedStyle(b).backgroundColor, fg: getComputedStyle(b).color, prog: getComputedStyle(k.querySelector('i')).backgroundColor, soft: getComputedStyle(p).backgroundColor, done: getComputedStyle(c).backgroundColor}; b.remove(); k.remove(); p.remove(); c.remove(); return r; })()`;
  for (const theme of ['dark', 'light']) {
    await firefox(async o => {
      const {cmd, ev, ctx, shot, until: u} = o;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 800}});
      check(await signIn(o, theme) === 200, `${theme}: login`);
      await o.nav(B + '#today');
      await u(`!!document.querySelector('#view .trow[data-id="${TW}"].wac-loc')`);
      await ev(`(() => { document.querySelectorAll('.authscreen').forEach(e => e.remove()); document.querySelector('#app')?.removeAttribute('inert'); return 1; })()`);
      const tone = rgb(theme === 'dark' ? want[0] : want[1]), glob = PETROL[theme];
      const rowP = await ev(PROBE(`document.querySelector('#view .trow[data-id="${TW}"]')`));
      check(rowP && rowP.bg === tone && rowP.prog === tone && ratio(rowP.bg, rowP.fg) >= 4.5, `${theme}: #4222 a row of the organisation: button and progress in its tone, text >= 4.5:1 ` + JSON.stringify(rowP));
      check(rowP && rowP.done === tone, `${theme}: #4222 the derived --st-complete follows ` + JSON.stringify(rowP));
      // a marked row is tinted with its own tone (.trow.msel; the tick's edge is not the accent there)
      const rows2 = `[${TW}, ${TP}].map(id => document.querySelector('#view .trow[data-id="' + id + '"]'))`;
      await ev(`(() => { ${rows2}.forEach(r => r.classList.add('msel')); return 1; })()`);
      // CI red of 2.570.0: on the slower CI runner a late redraw of the list replaced the rows (their msel gone) and the
      // row's background transition outlasted 3 s - mark the rows again on every look, wait longer
      const msel = await u(`(() => { const rs = ${rows2}; if (rs.some(r => !r)) return null; rs.forEach(r => r.classList.add('msel')); const [a, b] = rs.map(r => getComputedStyle(r).backgroundColor); return a !== b ? [a, b] : null; })()`, {timeout: 10000});
      await ev(`(() => { ${rows2}.forEach(r => r.classList.remove('msel')); return 1; })()`);
      check(msel, `${theme}: #4222 a marked row in its workspace's tone ` + JSON.stringify(msel));
      const rowQ = await ev(PROBE(`document.querySelector('#view .trow[data-id="${TP}"]')`));
      check(rowQ && rowQ.bg === glob && rowQ.prog === glob, `${theme}: #4222 a private row: Kalmido's accent ` + JSON.stringify(rowQ));
      check(rowP && rowQ && rowP.soft !== rowQ.soft, `${theme}: #4222 the derived --accent-soft follows ` + JSON.stringify([rowP?.soft, rowQ?.soft]));
      for (const [n, sel] of [['head bar', '#kbar'], ['sidebar', '#side'], ['header', '#top']]) {
        const p = await ev(PROBE(`document.querySelector('${sel}')`));
        check(p && p.bg === glob, `${theme}: #4222 ${n}: Kalmido's accent ` + JSON.stringify(p));
      }
      const strip = await ev(`getComputedStyle(document.querySelector('#side')).borderTopColor`);
      check(strip === glob, `${theme}: #4222 the stripe of "All" in Kalmido's accent, no grey ` + strip);
      await shot(`p2504c-1280-${theme}-today.png`);
      // the task panel of the organisation's task
      await ev(`(() => { openDetail(${TW}); return 1; })()`);
      await u(`document.querySelector('#detail.wac-loc:not(.hidden)') && !!document.querySelector('#view .trow.sel')`);
      const det = await ev(PROBE(`document.querySelector('#detail')`));
      check(det && det.bg === tone, `${theme}: #4222 the task panel in the tone ` + JSON.stringify(det));
      const selBg = await ev(`getComputedStyle(document.querySelector('#view .trow[data-id="${TW}"].sel')).backgroundColor`);
      const plainBg = await ev(`(() => { const e = document.createElement('div'); e.className = 'trow sel'; document.querySelector('#top').append(e); const c = getComputedStyle(e).backgroundColor; e.remove(); return c; })()`);
      check(selBg && plainBg && selBg !== plainBg, `${theme}: #4222 the selected row is tinted with the tone ` + JSON.stringify([selBg, plainBg]));
      await shot(`p2504c-1280-${theme}-detail.png`);
      await ev(`(() => { closeDetail(); return 1; })()`);
      // an open list: the view in the tone, the header global
      await ev(`(() => { location.hash = 'l/${WL}'; return 1; })()`);
      await u(`document.querySelector('#view').classList.contains('wac-loc') && !!document.querySelector('#view .trow[data-id="${TW}"]')`);
      const lv = await ev(PROBE(`document.querySelector('#view')`)), lt = await ev(PROBE(`document.querySelector('#top')`));
      check(lv && lv.bg === tone && lv.prog === tone, `${theme}: #4222 the open list's view in the tone ` + JSON.stringify(lv));
      check(lt && lt.bg === glob, `${theme}: #4222 the open list's header global ` + JSON.stringify(lt));
      await shot(`p2504c-1280-${theme}-list.png`);
      // a list's own colour wins, in the view
      await ev(`(() => { location.hash = 'l/${RL}'; return 1; })()`);
      await u(`document.querySelector('#main').classList.contains('lp-acc') && !document.querySelector('#view').classList.contains('wac-loc')`);
      const rv = await ev(PROBE(`document.querySelector('#view')`));
      check(rv && rv.bg === RED[theme] && rv.prog === RED[theme], `${theme}: #4222 a list's own colour wins ` + JSON.stringify(rv));
      await shot(`p2504c-1280-${theme}-redlist.png`);
      await ev(`(() => { location.hash = 'today'; return 1; })()`);
      await u(`!!document.querySelector('#view .trow[data-id="${TW}"]')`);
    }, false);
  }
  console.log(`p2504_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
