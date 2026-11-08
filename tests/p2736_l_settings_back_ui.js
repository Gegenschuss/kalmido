// 2.736.0 UI test (#5214: Back in the settings goes to the view shown before, the last Back closes them), own container
// kalmido-suite:
// (start.sh), Firefox as a touch screen (Android Back = history.back()) in phone widths 320 / 460 px and tablet width 840 px
// (an unfolded Fold, the areas as tabs). Invented data only. P2736L_NOSTART=1 = the container runs.
// - phone: overview -> area A -> arrow (overview) -> area B -> jump go-modules: one history entry per view; Back shows
//   Modules -> B -> overview -> A -> overview, the next Back closes the settings; no entry is pushed again in between (#5070)
// - phone: the arrow in the header does what Back does (one view back, its history entry goes)
// - phone opened straight into an area (settingsModal('modules')): Back shows the overview, the next closes
// - tablet: tab A -> tab B: Back shows A, the next Back closes; folding a part open inside an area is no step
// P4: alice works without an organisation (her own private settings): the person without an organisation
// freelancer-matrix: n/a - no route of its own, the settings dialog in the browser
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2736_l_settings_back_ui', check, shots: 'P2736L_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2736L_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});

  await firefox(async ({cmd, ev, nav: go, ctx, shot, until: wait}) => {
    await go(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');
    // the shown view of the settings: 'idx' (the overview of a phone), the area's key, or 'closed'
    const VIEW = `(() => { const m = document.querySelector('.modal.smodal:not(.an-out)'); if (!m) return 'closed';
      return m.classList.contains('sidx') ? 'idx' : m.querySelector('.spane:not(.hidden)')?.dataset.pane; })()`;
    const STATE = `JSON.stringify({v: ${VIEW}, f8d: history.state?.f8d, p: f8d_bk.pushed, skip: f8d_bk.skip})`;
    // settled: the view is w, our entries match the open levels, the history stands on the top one
    const at = (w, n) => wait(`${VIEW} === ${JSON.stringify(w)} && !f8d_bk.skip && f8d_bk.pushed === ${n} && (history.state?.f8d || 0) === ${n}`, {timeout: 6000});
    const tab = k => ev(`(document.querySelector('.smodal .snav [data-sec="${k}"]').click(), 1)`);
    const back = () => ev(`(history.back(), 1)`);
    const start = async () => {
      await go(B + '#today');
      check(await wait(`!!document.querySelector('#view') && typeof settingsModal === 'function'`, {timeout: 20000}), 'the app is there');
      await ev(`(history.replaceState({p2736l: 1}, '', location.href), 1)`);  // the entry below the settings
      await ev(`(window.__push = 0, window.__p0 || (window.__p0 = history.pushState), history.pushState = function () { window.__push++; return window.__p0.apply(this, arguments); }, 1)`);
    };

    for (const W of [320, 460]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: 760}});
      await start();
      check(await ev(`isTouch() && isMobile()`), `${W}: a touch screen in phone width`);
      await ev(`(settingsModal(), 1)`);
      check(await at('idx', 1), `${W}: the settings open on the overview, one entry ` + await ev(STATE));
      const secs = await ev(`[...document.querySelectorAll('.smodal .snav [data-sec]:not([hidden])')].map(b => b.dataset.sec)`);
      const [A, Bk] = secs.filter(k => k !== 'modules');
      check(A && Bk && secs.includes('modules'), `${W}: two areas besides Modules ` + JSON.stringify(secs));
      await tab(A);
      check(await at(A, 2), `${W}: area A, an entry of its own ` + await ev(STATE));
      await ev(`(document.querySelector('.smodal [data-m="s-index"]').click(), 1)`);  // the arrow: one view back = the overview
      check(await at('idx', 1), `${W}: the arrow goes back to the overview, its entry goes ` + await ev(STATE));
      await tab(A); await at(A, 2);
      await tab(Bk);  // the overview is hidden in an area; the tab of the strip stands for a jump from area to area
      check(await at(Bk, 3), `${W}: area B, a third entry ` + await ev(STATE));
      await ev(`(document.querySelector('.smodal').querySelector('[data-pane="${Bk}"]').insertAdjacentHTML('beforeend', '<button type="button" data-m="go-modules" id="p2736l-go">go</button>'), document.getElementById('p2736l-go').click(), 1)`);
      check(await at('modules', 4), `${W}: the jump go-modules counts as a step too ` + await ev(STATE));
      // folding a module group open inside the area: no step
      await ev(`(() => { const d = document.querySelector('.smodal [data-pane="modules"] details'); if (d) d.open = !d.open; return 1; })()`);
      await sleep(100);
      check(await ev(`f8d_bk.pushed`) === 4, `${W}: folding inside an area is no step`);
      await shot(`p2736l-modules-${W}.png`);
      const pushes = await ev(`window.__push`);
      await back();
      check(await at(Bk, 3), `${W}: Back 1 shows area B ` + await ev(STATE));
      await back();
      check(await at(A, 2), `${W}: Back 2 shows area A ` + await ev(STATE));
      await back();
      check(await at('idx', 1), `${W}: Back 3 shows the overview ` + await ev(STATE));
      check(await ev(`window.__push`) === pushes, `${W}: Back pushed no entry again (Chrome skips such an entry, #5070)`);
      await back();
      check(await wait(`${VIEW} === 'closed' && f8d_bk.pushed === 0 && history.state?.p2736l === 1`, {timeout: 6000}), `${W}: the last Back closes the settings, the page below stays ` + await ev(STATE));

      // straight into an area: the overview below it, then closed
      await ev(`(settingsModal('modules'), 1)`);
      check(await at('modules', 2), `${W}: opened straight into Modules: the overview counts below it ` + await ev(STATE));
      await back();
      check(await at('idx', 1), `${W}: Back from there shows the overview ` + await ev(STATE));
      await back();
      check(await wait(`${VIEW} === 'closed' && f8d_bk.pushed === 0`, {timeout: 6000}), `${W}: and the next Back closes`);
    }

    // tablet / unfolded Fold: the areas as tabs, no overview
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 840, height: 1000}});
    await start();
    check(await ev(`isTouch() && !isMobile()`), '840: a touch screen with tabs');
    await ev(`(settingsModal(), 1)`);
    const first = await wait(VIEW + ` !== 'closed' && ${VIEW}`, {timeout: 6000});
    check(first && first !== 'idx' && await at(first, 1), '840: the settings open on an area, one entry ' + await ev(STATE));
    const other = await ev(`[...document.querySelectorAll('.smodal .snav [data-sec]:not([hidden])')].map(b => b.dataset.sec).find(k => k !== ${JSON.stringify(first)})`);
    await tab(other);
    check(await at(other, 2), '840: another tab, an entry of its own ' + await ev(STATE));
    await tab(other);  // the same tab again: no step
    await sleep(100);
    check(await ev(`f8d_bk.pushed`) === 2, '840: the tab already shown is no step');
    await back();
    check(await at(first, 1), '840: Back shows the tab before ' + await ev(STATE));
    await back();
    check(await wait(`${VIEW} === 'closed' && f8d_bk.pushed === 0 && history.state?.p2736l === 1`, {timeout: 6000}), '840: the next Back closes the settings');
  }, true);

  console.log(`p2736_l_settings_back_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
