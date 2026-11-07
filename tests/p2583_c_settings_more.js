// 2.583.0 UI test, part C (#4833): the settings are ONE column again, the rarely changed part of a tab lies under "Further options"
// kalmido-suite: fresh
// Own container (start.sh), Firefox at 1920 px, German, invented data only. Alice has no organisation (her private workspace
// only), so every case is the freelancer case too (tests/freelancer_fixture.py idea: a person without an organisation).
// - 1920 px: Appearance is one column of form width (no CSS columns), "Weitere Optionen" is closed, its switches are not shown
// - the search finds a folded switch: the hit opens the fold and lights the row up; the server keeps the fold closed (search only)
// - a change under the fold: the fold says "1 geändert" (the default comes from GET /api/settings/defaults)
// - opening the fold by hand is the person's setting settings_more: after a reload the fold is open again
// - a jump of settingsModal('caldav') to a folded section opens the fold; set_delta settings_more refuses a wrong entry
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2583_c_settings_more', check, shots: 'P2583C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2583C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  await call(CA, 'PATCH', '/api/settings', {lang: 'de', tour: 'done'});
  // the server side: the defaults and the setting itself
  const df = await call(CA, 'GET', '/api/settings/defaults');
  check(df.http === 200 && df.defaults?.list_emoji === '1' && df.defaults?.settings_more === '[]' && !('ntfy_topic' in (df.defaults || {})), 'defaults: list_emoji 1, settings_more [], no server-only key ' + df.http);
  check(df.defaults?.show_done_default === '0', 'defaults: the start value of a new account (completed tasks hidden, #1535), not the bare USER_DEFAULTS');
  check((await call(CA, 'PATCH', '/api/settings', {set_delta: {settings_more: {add: ['../x']}}})).http === 400, 'settings_more: a wrong entry is 400');
  const st = await call(CA, 'GET', '/api/state');
  check((st.settings?.settings_more || '[]') === '[]', 'settings_more: nothing stored by the wrong entry');

  const ready = async (ev, expr, n = 80) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const open = async (ev, sec) => { await ev(`(() => { document.querySelectorAll('.smodal').forEach(m => m.remove()); settingsModal('${sec}'); return 1; })()`);
    return ready(ev, `!!document.querySelector('.smodal .spane:not(.hidden) .row')`); };
  const FOLD = `document.querySelector('.smodal .spane:not(.hidden) details.setmore')`;
  // shown = laid out and not inside a closed fold (Firefox lays out the content of a closed details with content-visibility: hidden)
  const seen = sel => `(() => { const e = document.querySelector(${JSON.stringify(sel)}); return !!e && e.getClientRects().length > 0 && e.getBoundingClientRect().height > 0 && (!e.checkVisibility || e.checkVisibility()); })()`;
  const stored = `fetch('/api/state', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.settings.settings_more || '[]')`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1920, height: 1080}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    await nav(B + '#home');
    await ready(ev, `typeof settingsModal === 'function' && !!document.querySelector('#view')`);
    check(await ready(ev, `document.documentElement.lang === 'de' && tr('Settings') !== 'Settings'`), 'the app runs in German');
    check(await open(ev, 'look'), '1920: the settings open on Appearance');

    // one column of form width, the fold closed and at the end of the tab
    const lay = JSON.parse(await ev(`(() => { const sp = document.querySelector('.smodal .spane:not(.hidden)'), d = sp.querySelector('details.setmore');
      return JSON.stringify({cols: getComputedStyle(sp).columnCount, w: Math.round(sp.getBoundingClientRect().width), sw: Math.round(sp.parentElement.getBoundingClientRect().width), fold: !!d, open: d ? d.open : null,
        last: sp.lastElementChild === d, sum: d ? d.querySelector('summary').textContent.trim() : '', inFold: !!d?.querySelector('#s-lemo')}); })()`));
    check(lay.cols === 'auto' && lay.w <= 642 && lay.w >= 500, '1920: one column of form width ' + JSON.stringify(lay));
    check(lay.fold && lay.open === false && lay.last && /^Weitere Optionen/.test(lay.sum) && lay.inFold, '1920: "Weitere Optionen" closed at the end, with "Suggest icons" in it ' + JSON.stringify(lay));
    const vis = JSON.parse(await ev(`JSON.stringify([${seen('#s-lemo')}, ${seen('#s-tabbar-h')}])`));
    check(!vis[0] && vis[1], 'the folded switch is not shown, the tab bar (often used) is ' + JSON.stringify(vis));
    const CNT = `${FOLD}.querySelector('.setmorec').textContent.trim()`;
    check(await ready(ev, `${CNT} === '' && !!SOM.defs`), 'nothing changed yet: no count ' + await ev(`JSON.stringify({c: ${CNT}, defs: !!SOM.defs, diff: Object.keys(SETS).filter(id => document.querySelector('details.setmore #' + id)).map(id => SETS[id][0]).filter(k => SOM.defs && k in SOM.defs && String(S.settings[k] ?? '') !== String(SOM.defs[k] ?? ''))})`).catch(e => String(e)));
    await shot('p2583-c-look-1920.png');

    // the search finds the folded switch, opens the fold and lights the row up; nothing saved by that
    const lab = await ev(`document.querySelector('#s-lemo').closest('label').textContent.trim()`);
    await ev(`(() => { const q = document.querySelector('#s-search'); q.focus(); q.removeAttribute('readonly'); q.value = ${JSON.stringify(lab.slice(0, 18))}; q._typed = true; q.dispatchEvent(new Event('input', {bubbles: true})); return 1; })()`);
    check(await ready(ev, `[...document.querySelectorAll('#s-sres [data-hit]')].some(b => b.textContent.includes(${JSON.stringify(lab.slice(0, 18))}))`), 'search: the folded switch is a hit ' + lab);
    await ev(`(() => { [...document.querySelectorAll('#s-sres [data-hit]')].find(b => b.textContent.includes(${JSON.stringify(lab.slice(0, 18))})).click(); return 1; })()`);
    check(await ready(ev, `${FOLD}.open && !!document.querySelector('#s-lemo').closest('.sflash')`, 20), 'search: the hit opens the fold and lights the switch up');
    check(await ev(seen('#s-lemo')), 'search: the switch is shown now');
    await shot('p2583-c-search-1920.png');
    check(await ev(stored) === '[]', 'search: the open fold is not saved');

    // a change under the fold: "1 geändert"
    await ev(`(() => { document.querySelector('#s-lemo').click(); return 1; })()`);
    check(await ready(ev, `${CNT} === '1 geändert'`), 'the fold says "1 geändert" after the change ' + await ev(CNT));
    check(await ready(ev, `fetch('/api/state', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json()).then(j => j.settings.list_emoji === '0')`), 'the change is saved');

    // closed again, then opened by hand: saved for the person, open after a reload
    await open(ev, 'look');
    check(await ev(`${FOLD}.open === false`), 'reopened: the fold is closed again (the search did not save it)');
    check(await ev(`${CNT} === '1 geändert'`), 'reopened: the count is there at once');
    await ev(`(() => { ${FOLD}.querySelector('summary').click(); return 1; })()`);
    check(await ready(ev, `${stored}.then(v => JSON.parse(v).includes('look'))`), 'a click on "Weitere Optionen": settings_more holds look');
    await nav(B + 'static/icon.svg'); await nav(B + '#home');
    await ready(ev, `typeof settingsModal === 'function' && !!document.querySelector('#view')`);
    check(await open(ev, 'look'), 'after the reload: Appearance opens');
    check(await ready(ev, `${FOLD}.open === true`, 20) && await ev(seen('#s-lemo')), 'after the reload: the fold is open (server setting)');
    check(await ready(ev, `${FOLD}.querySelector('summary').textContent.includes('1 geändert')`), 'after the reload: "1 geändert"');
    check(await open(ev, 'general') && await ev(`${FOLD}.open === false`), 'another tab keeps its own fold closed');

    // a jump to a folded section opens the fold (Integrations > Calendar apps)
    await ev(`(() => { document.querySelectorAll('.smodal').forEach(m => m.remove()); settingsModal('caldav'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.smodal #s-dav-h') && document.querySelector('.smodal #s-dav-h').closest('details.setmore')?.open === true`), 'settingsModal(caldav): the fold with Calendar apps opens');
    check(await ready(ev, seen('.smodal #s-dav-h')), 'settingsModal(caldav): the heading is shown');
    await shot('p2583-c-caldav-1920.png');
  }, false);

  console.log(`p2583_c_settings_more: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
