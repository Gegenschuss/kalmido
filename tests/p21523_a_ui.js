// 2.152.3 part A UI tests (#2619, head part): ONE head bar over everything on a computer (direction 4, sketch of 22.10.).
// Own container (start.sh), Firefox, 1280 px, light theme (one dark shot). Invented people and companies only.
// freelancer-matrix: tasks / workspace switch -- carol has no organisation (P4): her menu has only Private + "Add a company".
// - #kbar spans the bar of the areas, the panel and the page: brand (logo + word mark) + workspace (dot, name cut with …,
//   arrow), the search (palette, Mod+K), the bell, the account; #top keeps only the title and its own buttons
// - the brand is no longer in the panel's head (.sbbrand), no search on top of the panel, no account at the bottom of the bar
// - the workspace menu: "Switch to", the company with its own sign, Private, a tick on the shown one, "Add a company",
//   "Company settings" only while a company is shown; Escape closes, arrow keys move
// - the panel's head: the area's name, "Fold all" switches the groups (Tasks, Office), none on Time; "Hide the panel" hides
//   it (kept after reloading), the button on top of the bar brings it back
// - a phone (402 px) has no head bar, its header keeps the bell
// P21523A_NOSTART=1 = the server already runs. Screenshots: P21523A_SHOTS (a screenshot run of the UI test runner).
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21523_a_ui', check, shots: 'P21523A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21523A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => {
  for (let i = 0; ; i++) {
    const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined});
    if (r.status === 429 && i < 8) { await sleep(500 * (i + 1)); continue; }
    const j = await r.json().catch(() => ({})); return {...j, http: r.status};
  }
};
const FEAT = 'cal,comments,collab,contacts,office,clients,time,pomo,review,stats,timeline,matrix,progress';
const ORG = 'Lindenhof Filmproduktion und Postproduktion GbR';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: ORG, admin_id: me.id});
  check(org.id > 0, 'a company for alice');
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const L = (await call(CA, 'POST', '/api/lists', {name: 'Shoot Miller', org_id: org.id})).id;
  for (const t of ['Call the location', 'Book the crew']) await call(CA, 'POST', '/api/tasks', {title: t, list_id: L});
  await call(CA, 'POST', '/api/users', {username: 'carol', display_name: 'Carol Solo', password: 'password123', email: 'carol@example.com'});
  const CC = await login('carol');
  await call(CC, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  check(!((await call(CC, 'GET', '/api/state')).me.workspaces || []).length, 'P4: carol has no organisation');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const click = (ev, sel) => ev(`(() => { const b = document.querySelector(${JSON.stringify(sel)}); if (!b) return 0; b.click(); return 1; })()`);
  const key = (ev, k, mod = false) => ev(`(() => { const t = document.activeElement || document.body; t.dispatchEvent(new KeyboardEvent('keydown', {key: ${JSON.stringify(k)}, ctrlKey: ${mod}, metaKey: ${mod}, bubbles: true, cancelable: true})); return 1; })()`);
  const menuLabels = `[...document.querySelectorAll('#pop [role="menuitem"]')].map(b => b.querySelector('.ml')?.textContent.trim()).join('|')`;
  const popOpen = `!document.querySelector('#pop').classList.contains('hidden') && !!document.querySelector('#pop [role="menuitem"]')`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    check(await signIn(ev, 'alice') === 200, 'alice signs in');
    await nav(B + `#l/${L}`);
    check(await ready(ev, `!!document.querySelector('#kbar .kbsw') && !!document.querySelector('#srail .srb.on')`, 80), 'the head bar is drawn');
    await sleep(600);

    // ================= the head bar over everything
    const geo = await ev(`(() => { const R = s => document.querySelector(s)?.getBoundingClientRect(); const k = R('#kbar'), r = R('#srail'), s = R('#side'), m = R('#main');
      return {kl: k.left, kr: k.right, kb: k.bottom, h: k.height, rl: r.left, rt: r.top, st: s.top, mt: m.top, mr: m.right}; })()`);
    check(geo.kl <= geo.rl + 1 && geo.kr >= geo.mr - 1, 'the head bar spans the full width ' + JSON.stringify(geo));
    check(geo.kb <= geo.rt + 1 && geo.kb <= geo.st + 1 && geo.kb <= geo.mt + 1, 'the head bar sits above the bar, the panel and the page');
    check(geo.h >= 40 && geo.h <= 50, 'a low bar (about 46 px) ' + geo.h);
    check(await ev(`!!document.querySelector('#kbar .kbbrand svg.logo') && !!document.querySelector('#kbar .kbbrand svg.kword')`), 'brand: logo + word mark');
    const firm = await ev(`(() => { const n = document.querySelector('#kbar .kbfirm .wsn'); return {t: n?.textContent, cut: n ? n.scrollWidth > n.clientWidth : false, w: document.querySelector('#kbar .kbfirm').getBoundingClientRect().width, dot: !!document.querySelector('#kbar .kbfirm .wsp-dot')}; })()`);
    check(firm.t === ORG && firm.dot, 'the company with its dot ' + JSON.stringify(firm));
    check(firm.cut && firm.w <= 15 * 16 + 1, 'a long company name is cut with … at a fixed width ' + JSON.stringify(firm));
    check(await ev(`!!document.querySelector('#kbar .kbsrch[data-act="palette"]') && /Search, create, ask/.test(document.querySelector('#kbar .kbsrch').textContent)`), 'the search in the head bar');
    check(await ev(`!!document.querySelector('#kbar .bell') && !!document.querySelector('#kbar .kbacct[data-act="user-menu"] .avatar')`), 'bell and account in the head bar');
    check(await ev(`!document.querySelector('#top .bell') && !document.querySelector('#top .cmdbar') && !document.querySelector('#top .wschip')`), '#top keeps only the title and its own buttons');
    check(await ev(`!document.querySelector('#side .sbbrand') && !document.querySelector('#side .sbbtop') && !document.querySelector('#srail .sbacct')`), 'no brand in the panel, no search on it, no account at the bottom of the bar');
    check(await ev(`[...document.querySelectorAll('#srail .srfoot .srb')].map(b => b.dataset.act).join() === 'settings'`), 'the bottom of the bar: only Settings');
    check(await ev(`(() => { const b = document.querySelector('#srail .srb.on'); return !!b && getComputedStyle(b).backgroundColor !== 'rgba(0, 0, 0, 0)'; })()`), 'the open area tile is tinted');
    await shot('p21523a-head-light.png');

    // the search: a click and Mod+K open the palette
    await click(ev, '#kbar .kbsrch');
    check(await ready(ev, `!!document.querySelector('.palette')`, 20), 'the search opens the palette');
    await key(ev, 'Escape'); await ready(ev, `!document.querySelector('.palette')`, 20);
    await ev(`document.body.focus()`); await key(ev, 'k', true);
    check(await ready(ev, `!!document.querySelector('.palette')`, 20), 'Mod+K opens the palette');
    await key(ev, 'Escape'); await ready(ev, `!document.querySelector('.palette')`, 20);
    // the bell and the account menu
    await click(ev, '#kbar .bell');
    check(await ready(ev, `!!document.querySelector('#pop .bpop')`, 20), 'the bell opens the News');
    await key(ev, 'Escape'); await sleep(300);
    await click(ev, '#kbar .kbacct');
    check(await ready(ev, popOpen, 20) && /\|Settings\|/.test('|' + await ev(menuLabels) + '|'), 'the account menu has Settings');
    await key(ev, 'Escape'); await sleep(300);

    // ================= the workspace menu
    await click(ev, '#kbar .kbsw');
    check(await ready(ev, popOpen, 20), 'the switch opens its menu');
    check(await ev(`document.querySelector('#pop .mgh')?.textContent.trim() === 'Switch to'`), 'heading "Switch to"');
    const items = await ev(`[...document.querySelectorAll('#pop .kbwsi')].map(b => b.querySelector('.ml').textContent.trim() + (b.classList.contains('on') ? '*' : '')).join('|')`);
    check(items.startsWith(ORG + '*|Private'), 'the company first and ticked, then Private ' + items);
    check(await ev(`!!document.querySelector('#pop .kbwsi.on .mchk') && !!document.querySelector('#pop .kbwsi .kbwsic .kbini') && !!document.querySelectorAll('#pop .kbwsi')[1]?.querySelector('svg.i')`), 'the company with its own sign (initial), Private with the house, the tick');
    check(await ev(`!!document.querySelector('#pop .kbws-add') && !!document.querySelector('#pop .kbws-set') && !!document.querySelector('#pop hr')`), '"Add a company" and "Company settings" below a separator');
    check(!/Start|Hide the sidebar/.test(await ev(menuLabels)), 'no Start / Hide the sidebar in this menu');
    await shot('p21523a-menu-light.png');
    const f0 = await ev(`document.activeElement?.textContent.trim()`);
    await key(ev, 'ArrowDown');
    check(await ev(`document.activeElement?.textContent.trim()`) !== f0, 'arrow keys move in the menu');
    await key(ev, 'Escape');
    check(await ready(ev, `document.querySelector('#pop').classList.contains('hidden')`, 20), 'Escape closes the menu');
    // switch to Private: the bar names it, the menu has no company settings
    await click(ev, '#kbar .kbsw'); await ready(ev, popOpen, 20);
    await ev(`[...document.querySelectorAll('#pop .kbwsi')].find(b => b.textContent.includes('Private'))?.click()`);
    check(await ready(ev, `document.querySelector('#kbar .kbfirm .wsn')?.textContent === 'Private'`, 40), 'the switch to Private');
    await click(ev, '#kbar .kbsw'); await ready(ev, popOpen, 20);
    check(await ev(`!document.querySelector('#pop .kbws-set') && !!document.querySelector('#pop .kbws-add')`), 'Private: no company settings');
    await key(ev, 'Escape'); await sleep(300);
    await click(ev, '#kbar .kbsw'); await ready(ev, popOpen, 20);
    await ev(`[...document.querySelectorAll('#pop .kbwsi')].find(b => b.textContent.includes(${JSON.stringify(ORG)}))?.click()`);
    check(await ready(ev, `document.querySelector('#kbar .kbfirm .wsn')?.textContent === ${JSON.stringify(ORG)}`, 40), 'back to the company');

    // ================= the panel's head: name, fold all, hide
    await nav(B + `#l/${L}`);
    await ready(ev, `!!document.querySelector('#side .sbhead .sbbpt')`, 60);
    check(await ev(`document.querySelector('#side .sbhead .sbbpt')?.textContent.trim() === 'Projects' /* 2.208.0 (#2771) */ && !!document.querySelector('#side .sbhead .sbbfa') && !!document.querySelector('#side .sbhead .sbbhide')`), 'Tasks: name, fold all, hide the panel in the head');
    const openG = `document.querySelectorAll('#side [data-act="side-group"][aria-expanded="true"]').length`;
    check(await ev(openG) > 0, 'some groups are open');
    await click(ev, '#side .sbbfa');
    check(await ready(ev, `${openG} === 0 && document.querySelector('#side .sbbfa')?.getAttribute('aria-pressed') === 'true'`, 20), 'Fold all folds every group');
    await click(ev, '#side .sbbfa');
    check(await ready(ev, `${openG} > 0`, 20), 'Unfold all opens them again');
    await nav(B + '#office/offers');
    check(await ready(ev, `document.querySelectorAll('#side [data-act="sbb-group"]').length >= 3 && !!document.querySelector('#side .sbbfa')`, 80), 'Office: the fold button');
    await click(ev, '#side .sbbfa');
    check(await ready(ev, `document.querySelectorAll('#side [data-act="sbb-group"][aria-expanded="true"]').length === 0`, 20), 'Office: Fold all folds Sell / Money / Administration');
    await click(ev, '#side .sbbfa');
    check(await ready(ev, `document.querySelectorAll('#side [data-act="sbb-group"][aria-expanded="false"]').length === 0`, 20), 'Office: Unfold all');
    await nav(B + '#time');
    check(await ready(ev, `document.querySelector('#side .sbbpt')?.textContent.trim() === 'Time'`, 60) && await ev(`!document.querySelector('#side .sbbfa') && !!document.querySelector('#side .sbbhide')`), 'Time: no fold button, the hide button stays');

    await nav(B + `#l/${L}`);
    await ready(ev, `!!document.querySelector('#side .sbbhide')`, 60);
    await click(ev, '#side .sbbhide');
    const hidden = `document.querySelector('#app').classList.contains('side-rail') && !document.querySelector('#side').getClientRects().length || getComputedStyle(document.querySelector('#side')).visibility === 'hidden'`;
    check(await ready(ev, hidden, 20), 'Hide the panel hides it');
    check(await ev(`(() => { const r = document.querySelector('#srail').getBoundingClientRect(), m = document.querySelector('#main').getBoundingClientRect(); return Math.abs(m.left - r.right) <= 2 && !!document.querySelector('#kbar .kbsw').getClientRects().length; })()`), 'the page moves up to the bar, the head bar stays');
    check(await ev(`!!document.querySelector('#srail .srpanel')?.getClientRects().length`), 'the button to show the panel on top of the bar');
    await shot('p21523a-hidden-light.png');
    await nav(B + 'static/icon.svg'); await nav(B + `#l/${L}`);
    check(await ready(ev, `!!document.querySelector('#kbar .kbsw')`, 60) && await ready(ev, hidden, 20), 'the hidden panel stays hidden after reloading (per device)');
    await click(ev, '#srail .srpanel');
    check(await ready(ev, `!document.querySelector('#app').classList.contains('side-rail') && !!document.querySelector('#side .sbbhide')?.getClientRects().length`, 20), 'the button brings the panel back');

    // dark
    await ev(`(() => { localStorage.setItem('tasks.theme', '"dark"'); return 1; })()`);
    await nav(B + 'static/icon.svg'); await nav(B + `#l/${L}`);
    await ready(ev, `!!document.querySelector('#kbar .kbsw')`, 60); await sleep(500);
    await ev(`(() => { document.documentElement.dataset.theme = 'dark'; return 1; })()`); await sleep(200);  // the account's theme can win over the device's at loading
    check(await ev(`getComputedStyle(document.querySelector('#kbar')).backgroundColor !== 'rgb(255, 255, 255)'`), 'dark: the head bar is not white');
    await shot('p21523a-head-dark.png');
    await click(ev, '#kbar .kbsw'); await ready(ev, popOpen, 20); await shot('p21523a-menu-dark.png'); await key(ev, 'Escape');
    await ev(`(() => { localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);

    // ================= P4: carol without an organisation
    await ev(`fetch('/api/auth/logout', {method: 'POST', headers: {'X-Requested-With': 'kalmido'}}).then(r => r.status)`).catch(() => 0);
    check(await signIn(ev, 'carol') === 200, 'carol signs in');
    await nav(B + 'static/icon.svg'); await nav(B + '#today');
    check(await ready(ev, `document.querySelector('#kbar .kbfirm .wsn')?.textContent === 'Private'`, 80), 'P4: the bar shows Private');
    await click(ev, '#kbar .kbsw'); await ready(ev, popOpen, 20);
    check(await ev(`[...document.querySelectorAll('#pop .kbwsi')].map(b => b.querySelector('.ml').textContent.trim() + (b.classList.contains('on') ? '*' : '')).join('|')`) === 'Private*', 'P4: the menu lists only Private, ticked');
    check(await ev(`!!document.querySelector('#pop .kbws-add') && !document.querySelector('#pop .kbws-set')`), 'P4: "Add a company", no company settings');
    await click(ev, '#pop .kbws-add');
    check(await ready(ev, `!!document.querySelector('.modal.cdlg') && /admin/.test(document.querySelector('.modal.cdlg').textContent)`, 20), 'P4: "Add a company" explains how a company comes');
    await click(ev, '.modal.cdlg [data-cd="no"]'); await sleep(300);
    check(await ev(`!!document.querySelector('#side .sbbfa') && !!document.querySelector('#side .sbbhide')`), 'P4: the panel head works the same');

    // ================= a phone: no head bar, its header keeps the bell
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 874}});
    await nav(B + '#today');
    check(await ready(ev, `!!document.querySelector('#top .bell')`, 60), 'phone: the bell stays in the header');
    check(await ev(`!document.querySelector('#kbar')?.getClientRects().length && !document.querySelector('#app.sb-b')`), 'phone: no head bar');
  }, false);

  console.log(`p21523_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
