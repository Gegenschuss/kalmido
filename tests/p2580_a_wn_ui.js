// kalmido-suite:
// 2.580.0 A (#4822) UI test, own container (start.sh), Firefox with real layout. Invented data only.
// The dialog "New for you" with a long list: a clear gap (>= 10 px) between the scrolling list and the hint below, the last
// entry ends fully visible after scrolling to the end, a thin line under the list only while more can be scrolled, hint and
// button stay inside the screen. Desktop 1280 x 800 and 320 x 640.
// freelancer-matrix: Neu fuer dich (alice has no organisation; the dialog does not depend on the workspace)
const path = require('path');
const fs = require('fs');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2580_a_wn_ui', check, shots: 'P2580A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const dbx = (sql, args = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, sql, JSON.stringify(args)]).toString() || '[]');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CA = await login('alice');
  const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CA}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const ME = (await call('GET', '/api/state')).me.id;
  const CUR = (await call('GET', '/api/about')).version;
  const [MA, MI] = CUR.split('.').map(Number), V = m => `${MA}.${m}.0`;
  const versions = [];
  for (let k = 0; k < 14; k++) versions.push({version: k ? V(MI - k) : CUR, date: '2026-11-05', items: [1, 2, 3, 4].map(i => ({en: `Sentence ${k}-${i} describes a small change in a few words so that it wraps on a phone`}))});
  fs.writeFileSync(path.join(DATA, 'whatsnew-test.json'), JSON.stringify({versions}));
  const setSeen = () => dbx("INSERT INTO user_settings(user_id, key, value) VALUES(?, 'whatsnew_seen', ?) ON CONFLICT(user_id, key) DO UPDATE SET value=excluded.value", [ME, V(MI - 30)]);

  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    await nav(B + 'static/icon.svg');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'ff: login');
    for (const [vw, vh] of [[1280, 800], [320, 640]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      for (const theme of ['light', 'dark']) {
        setSeen();
        await nav(B + '?w=' + vw + '&t=' + theme + '#home');
        await ev(`document.documentElement.dataset.theme = ${JSON.stringify(theme)}`);
        const tag = `${vw}px ${theme}`;
        const ready = await until(`!!document.querySelector('.wnmd .wnlist') && document.querySelector('.wnmd .wnlist').scrollHeight > document.querySelector('.wnmd .wnlist').clientHeight`);
        check(!!ready, `${tag}: the dialog opens with a list that scrolls`);
        if (!ready) continue;
        const M = `(() => { const l = document.querySelector('.wnmd .wnlist'), h = document.querySelector('.wnmd .lhint'), b = document.querySelector('.wnmd [data-m="close"]'),
          li = [...l.querySelectorAll('li')].pop(), lr = l.getBoundingClientRect(), hr = h.getBoundingClientRect(), br = b.getBoundingClientRect(), r = li.getBoundingClientRect();
          return {gap: hr.top - lr.bottom, liBottom: r.bottom, listBottom: lr.bottom, hintBottom: hr.bottom, btnBottom: br.bottom, vh: innerHeight, more: l.classList.contains('wnmore'), padB: parseFloat(getComputedStyle(l).paddingBottom),
            line: getComputedStyle(l).borderBottomColor, atEnd: l.scrollTop + l.clientHeight >= l.scrollHeight - 1}; })()`;
        let m = await ev(M);
        check(m.gap >= 10, `${tag}: gap list - hint >= 10 px (${m.gap})`);
        check(m.hintBottom <= m.vh && m.btnBottom <= m.vh, `${tag}: hint and button inside the screen ` + JSON.stringify(m));
        check(m.more && m.line !== 'rgba(0, 0, 0, 0)', `${tag}: line under the list while more can be scrolled ` + JSON.stringify(m));
        await shot(`p2580a-wn-${vw}-${theme}-top.png`);
        await ev(`(() => { const l = document.querySelector('.wnmd .wnlist'); l.scrollTop = l.scrollHeight; })()`);
        await until(`document.querySelector('.wnmd .wnlist').scrollTop + document.querySelector('.wnmd .wnlist').clientHeight >= document.querySelector('.wnmd .wnlist').scrollHeight - 1`);
        m = await ev(M);
        check(m.atEnd && m.liBottom <= m.listBottom - 4, `${tag}: the last entry ends fully visible, with room below it ` + JSON.stringify(m));
        check(await until(`!document.querySelector('.wnmd .wnlist').classList.contains('wnmore')`), `${tag}: no line at the end of the list`);
        await shot(`p2580a-wn-${vw}-${theme}-end.png`);
        await ev(`document.querySelector('.wnmd [data-m="close"]').click()`);
        await until(`!document.querySelector('.wnmd')`);
        await until(() => dbx("SELECT value FROM user_settings WHERE user_id=? AND key='whatsnew_seen'", [ME])[0]?.value === CUR);  // the close is stored before the next round resets it
      }
    }
  }, false);
  console.log(`p2580_a_wn_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
