// 2.805.0 UI test (#5357: the settings open at the width their content needs again, and five dialogs get a size grip), own
// kalmido-suite:
// container (start.sh), Firefox with a mouse at 1440 / 1920 px, and 460 px. Invented data only. P2805_NOSTART=1 = the container runs.
// - Settings: the same width at 1440 and 1920 px (the tabs, one form column, no 96rem any more); the form column is as wide as
//   the pane (no --w-form limit inside); the grip (right edge + corner) makes the dialog wider and the settings rows with it
// - for each of Settings, Edit contact, a mail of the hub, Video review, Set up an agent: the grips are there (labelled); a real
//   mouse drag on the right edge makes the dialog and its content wider (the height stays), the corner also taller; closed and
//   opened again it keeps its size (own key per dialog); double click = default size; arrow keys on the grip resize, Enter =
//   default; the dialog never gets wider than the window minus 4rem
// - 460 px (no mouse width): no grip, the dialog as before
// P4: alice works without an organisation (her own private settings, contacts, mails, reviews and agents)
// freelancer-matrix: n/a - no route of its own, dialogs in the browser
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2805_dlgsize_ui', check, shots: 'P2805_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
// the mail of the hub comes in through the stub mail server of tests/stub_mail.py (as in p2141_b_ui.js)
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const MAILENV = '-e KALMIDO_MAIL_ADDRESS=tasks@example.test -e KALMIDO_IMAP_HOST=127.0.0.1 -e KALMIDO_IMAP_PORT=1143 -e KALMIDO_IMAP_SSL=0 '
  + '-e KALMIDO_IMAP_USER=kalmido -e KALMIDO_IMAP_PASSWORD=secret -e KALMIDO_IMAP_INTERVAL=600';
if (!process.env.P2805_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' ' + MAILENV}});
fs.mkdirSync(path.join(DATA, 'mail', 'in'), {recursive: true});
fs.copyFileSync(path.join(__dirname, 'stub_mail.py'), path.join(DATA, 'stub_mail.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/stub_mail.py']);
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const until = (fn, ms) => require('./boot').until(fn, {timeout: ms || 20000, step: 400});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,clients,contacts,videos', workspace: 'all'});
  // a review (Video review) and a filed mail (the mail of the hub)
  const L = await call('POST', '/api/lists', {name: 'Imagefilm', kind: 'project'});
  const T = await call('POST', '/api/tasks', {title: 'Rohschnitt', list_id: L.id});
  const R = await call('POST', '/api/videos', {task_id: T.id, url: 'https://www.youtube.com/watch?v=AbCdEfGhI-9', title: 'Film Probe'});
  check(R.id, 'setup: a review ' + R.status);
  const IN = (await call('POST', '/api/hubmail/address', {ws: 'private'})).address;
  fs.writeFileSync(path.join(DATA, 'mail', 'in', '1.eml'), `From: Pat <pat@example.test>\r\nTo: ${IN}\r\nSubject: Size probe\r\nMessage-ID: <ui2805-1@example.test>\r\n`
    + 'Date: Tue, 20 Oct 2026 10:00:00 +0200\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nA plain mail to read in a bigger window.\r\n');
  // the stub server may still be starting: ask again until the mail is filed
  await until(async () => { await call('POST', '/api/admin/mail/poll', {}); return ((await call('GET', '/api/hubmail/inbox')).mails || []).length >= 1; }, 40000);
  const HM = ((await call('GET', '/api/hubmail/inbox')).mails || []).find(m => m.subject === 'Size probe')?.id;
  check(HM, 'setup: a filed mail');

  // the five dialogs: how to open one, its backdrop, and a part of its content that should go along with the width
  const DLG = [
    {name: 'settings', fixed: true, sel: '.modal.smodal', open: `settingsModal('look')`, ready: `.smodal .spane:not(.hidden) .row`, inner: `.smodal .spane:not(.hidden) .row`},
    {name: 'contact', sel: '.modal.ctmodal', open: `ctEditor(null)`, ready: `.ctmodal #ct-given`, inner: `.ctmodal #ct-given`},
    {name: 'mail', fixed: true, sel: '.modal.hbmdlg', open: `hbm_open(${HM})`, ready: `.hbmdlg .hbmview`, inner: `.hbmdlg .hbmview`, tall: true},
    {name: 'review', sel: '.modal.vdrdlg', open: `vdr_open(${R.id})`, ready: `.vdrdlg .vdrpl > *`, inner: `.vdrdlg .vdrpl`},
    {name: 'agent', sel: '.modal.agguide', open: `agGuideModal()`, ready: `.agguide #agg-prompt`, inner: `.agguide #agg-prompt`},
  ];
  await firefox(async ({cmd, ev, nav, ctx, shot, drag, until: wait}) => {
    const view = async (W, Hh) => {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: W, height: Hh}});
      await nav(B + '#today');
      check(await wait(`!!document.querySelector('#view') && typeof settingsModal === 'function'`, {timeout: 20000}), `${W}: the app is there`);
      await ev(`ld_all().then(() => 1)`);
    };
    const closeAll = () => ev(`(document.querySelectorAll('.modal').forEach(m => m.remove()), 1)`);
    // open, wait for its content and a settled size (two looks in a row agree)
    const open = async d => {
      await closeAll(); await sleep(250);
      await ev(`(${d.open}, 1)`);
      if (!await wait(`!!document.querySelector('${d.ready}')`, {timeout: 15000})) return false;
      let last = ''; for (let i = 0; i < 30; i++) { const v = JSON.stringify(await ev(BOX(d))); if (v === last) return true; last = v; await sleep(150); }
      return false;
    };
    const BOX = d => `(() => { const m = document.querySelector('${d.sel}'), c = m?.querySelector(':scope > .card'), i = document.querySelector('${d.inner}'); if (!c) return null;
      const r = c.getBoundingClientRect(), e = m.querySelector(':scope > .dlgsz-e'), k = m.querySelector(':scope > .dlgsz-c'), vis = g => !!g && getComputedStyle(g).display !== 'none' && g.getBoundingClientRect().width > 0;
      const er = e?.getBoundingClientRect(), kr = k?.getBoundingClientRect();
      return {w: Math.round(r.width), h: Math.round(r.height), sh: c.style.height, right: Math.round(r.right), bottom: Math.round(r.bottom), iw: i ? Math.round(i.getBoundingClientRect().width) : 0, ih: i ? Math.round(i.getBoundingClientRect().height) : 0,
        e: vis(e), k: vis(k), lbl: !!e?.getAttribute('aria-label') && !!k?.getAttribute('aria-label'),
        ex: er ? Math.round(er.left + er.width / 2) : 0, ey: er ? Math.round(er.top + er.height / 2) : 0, kx: kr ? Math.round(kr.left + kr.width / 2) : 0, ky: kr ? Math.round(kr.top + kr.height / 2) : 0,
        eon: er ? Math.abs(er.left + er.width / 2 - r.right) <= 4 : false, kon: kr ? Math.abs(kr.right - r.right) <= 2 && Math.abs(kr.bottom - r.bottom) <= 2 : false}; })()`;
    const box = d => ev(BOX(d));
    const key = (d, which, k) => ev(`(() => { const g = document.querySelector('${d.sel} > .dlgsz-${which}'); g.focus(); g.dispatchEvent(new KeyboardEvent('keydown', {key: '${k}', bubbles: true, cancelable: true})); return document.activeElement === g; })()`);

    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`) === 200, 'Firefox: login');

    // ================= the settings: the width the content needs, on a wide monitor too
    const sw = {};
    for (const [W, Hh] of [[1440, 900], [1920, 1080]]) {
      await view(W, Hh);
      check(await open(DLG[0]), `${W}: the settings open on Appearance`);
      const s = await ev(`(() => { const r = e => e.getBoundingClientRect().width, c = document.querySelector('.smodal .card'), n = document.querySelector('.smodal .snav'), p = document.querySelector('.smodal .spane:not(.hidden)'), ps = document.querySelector('.smodal .spanes'), rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
        return {cw: Math.round(r(c)), nw: Math.round(r(n)), pw: Math.round(r(p)), psw: Math.round(ps.clientWidth), rem, side: ps.scrollWidth > ps.clientWidth + 1}; })()`);
      sw[W] = s;
      // 2.805.0 (#5357): tabs + one form column (40rem) + the pane's padding (3rem) + its scrollbar (1rem): about 57.5rem, no longer 64rem or 96rem
      check(s.cw <= 58 * s.rem + 4 && s.cw >= 56 * s.rem, `${W}: the settings are as wide as their content (about 57.5rem) ` + JSON.stringify(s));
      check(s.pw >= 40 * s.rem - 2 && !s.side, `${W}: one form column fits, nothing scrolls sideways ` + JSON.stringify(s));
      await shot(`p2805-settings-${W}.png`);
    }
    check(sw[1440] && sw[1920] && sw[1440].cw === sw[1920].cw, 'the settings have the same width at 1440 and 1920 px ' + JSON.stringify(sw));

    // ================= the grip of each dialog (1440 px, a mouse; 1080 px high: room above the mail's 60rem)
    await view(1440, 1080);
    const def = {};
    for (const d of DLG) {
      const N = d.name;
      check(await open(d), `${N}: the dialog opens with its content`);
      const b0 = await box(d);
      check(b0 && b0.e && b0.k && b0.lbl, `${N}: a grip on the right edge and one in the corner, labelled ` + JSON.stringify(b0));
      if (!b0 || !b0.e) continue;
      def[N] = b0;
      check(b0.eon && b0.kon, `${N}: the grips sit on the card's right edge and its corner ` + JSON.stringify(b0));
      // the right edge: wider, the content goes along, the height stays
      await drag(b0.ex, b0.ey, 90, 0);
      const b1 = await box(d);
      // (a dialog of its content's height may get shorter when its lines get longer: the edge only sets no height)
      check(b1.w >= b0.w + 150 && b1.iw >= b0.iw + 100 && !b1.sh && (d.fixed ? Math.abs(b1.h - b0.h) <= 2 : true), `${N}: the edge makes the dialog and its content wider, not taller ` + JSON.stringify([b0, b1]));
      check(b1.eon && b1.kon, `${N}: the grips follow the new edge ` + JSON.stringify(b1));
      // the corner: taller as well (the mail view grows with it)
      await drag(b1.kx, b1.ky, 30, 40);
      const b2 = await box(d);
      check(b2.w >= b1.w + 40 && b2.h >= b1.h + 50, `${N}: the corner makes it wider and taller ` + JSON.stringify([b1, b2]));
      if (d.tall) check(b2.ih >= b1.ih + 50, `${N}: the mail grows with the height ` + JSON.stringify([b1, b2]));
      if (N === 'settings') await shot('p2805-settings-wide.png');
      // kept: closed and opened again
      check(await open(d), `${N}: opens again`);
      const b3 = await box(d);
      check(Math.abs(b3.w - b2.w) <= 1 && Math.abs(b3.h - b2.h) <= 1 && b3.iw >= b1.iw - 1, `${N}: the size is kept for the next time ` + JSON.stringify([b2, b3]));
      // never wider than the window minus 4rem
      await drag(b3.ex, b3.ey, 1432 - b3.ex, 0);  // to the window's edge (a pointer outside the window is refused)
      const b4 = await box(d);
      check(b4.w <= 1440 - 64 && b4.w >= 1440 - 64 - 2, `${N}: at most the window minus 4rem wide ` + JSON.stringify(b4));
      // double click = default size, and forgotten
      await ev(`(document.querySelector('${d.sel} > .dlgsz-e').dispatchEvent(new MouseEvent('dblclick', {bubbles: true, cancelable: true})), 1)`);
      const b5 = await box(d);
      check(Math.abs(b5.w - b0.w) <= 1 && !b5.sh, `${N}: double click = the default size ` + JSON.stringify([b0, b5]));
      // the keyboard: arrow right = wider, arrow down on the corner = taller, Enter = default; arrow left never below the default
      check(await key(d, 'e', 'ArrowRight'), `${N}: the edge grip takes the focus`);
      const b6 = await box(d);
      check(b6.w >= b0.w + 20, `${N}: arrow right makes it wider ` + JSON.stringify([b0, b6]));
      await key(d, 'c', 'ArrowDown');
      const b7 = await box(d);
      check(b7.h >= b0.h + 20 && Math.abs(b7.w - b6.w) <= 1, `${N}: arrow down on the corner makes it taller ` + JSON.stringify([b6, b7]));
      await key(d, 'c', 'Enter'); await key(d, 'e', 'ArrowLeft');
      const b8 = await box(d);
      check(Math.abs(b8.w - b0.w) <= 1 && !b8.sh, `${N}: Enter = default, never smaller than the default ` + JSON.stringify([b0, b8]));
      check(await open(d), `${N}: opens again after the reset`);
      const b9 = await box(d);
      check(Math.abs(b9.w - b0.w) <= 1, `${N}: the default size is kept after the reset ` + JSON.stringify([b0, b9]));
    }
    // each dialog has its own size: a wide contact form leaves the agent setup as it was
    check(await open(DLG[1]), 'contact again');
    const c0 = await box(DLG[1]); await drag(c0.ex, c0.ey, 120, 0); const c1 = await box(DLG[1]);
    check(await open(DLG[4]), 'agent setup again');
    const a1 = await box(DLG[4]);
    check(c1.w >= c0.w + 200 && def.agent && Math.abs(a1.w - def.agent.w) <= 1, 'each dialog keeps its own size ' + JSON.stringify([c0, c1, a1, def.agent]));
    await key(DLG[4], 'e', 'Enter');
    check(await open(DLG[1]), 'contact once more');
    await key(DLG[1], 'e', 'Enter');

    // ================= a small window (no mouse width): no grip
    await view(460, 800);
    for (const d of [DLG[0], DLG[1]]) {
      check(await open(d), `460 ${d.name}: opens`);
      const b = await box(d);
      check(b && !b.e && !b.k, `460 ${d.name}: no grip ` + JSON.stringify(b));
    }
    await shot('p2805-settings-460.png');
    await closeAll();
  });

  console.log(`p2805_dlgsize_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
