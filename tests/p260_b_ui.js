// 2.60.0 part B UI test, own container (start.sh), Firefox (the real layout).
// #1510: the kanban column head shows "open/limit" (In progress 4/3 marked in the warning tone, Review 2/3 not), a column
//        without a limit only its count; the column menu offers the WIP limit; setting it in the dialog is one undo step;
//        the list view's section head shows the limit too.
// #1511: with story points on, the cards show their points and the column heads add them up; the task panel has the field
//        Story points (1 2 3 5 8 13) and saving it is one undo step; with points off nothing of it shows.
// Screenshots with P260B_SHOTS=<dir>.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p260_b_ui', check, shots: 'P260B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, status: r.status}; };
const FEAT = 'cal,kanban,collab,comments,progress,deps';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const P = (await call('POST', '/api/lists', {name: 'App Alpha', ptype: 'software', sections: true})).id;
  await call('PATCH', `/api/lists/${P}`, {view: 'kanban', points_on: true});
  const st = await call('GET', '/api/state');
  const sec = n => st.sections.find(s => s.list_id === P && s.name === n).id;
  const INP = sec('In progress'), REV = sec('Review'), BACK = sec('Backlog');
  const mk = async (title, sid, points) => (await call('POST', '/api/tasks', {title, list_id: P, section_id: sid, ...(points ? {points} : {})})).id;
  const T = [];
  for (const [t, p] of [['Login page', 5], ['Signup page', 3], ['Password reset', 8], ['Profile', null]]) T.push(await mk(t, INP, p));
  await mk('Review one', REV, 2); await mk('Review two', REV, 1);
  const TB = await mk('Backlog item', BACK, null);
  // a second list with points off
  const Q = (await call('POST', '/api/lists', {name: 'Plain project', kind: 'project'})).id;
  const TQ = (await call('POST', '/api/tasks', {title: 'Quiet task', list_id: Q, points: 5})).id;

  const ffLogin = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel, n = 40) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(250); await sleep(700); };
  const HEAD = id => `(() => { const h = document.querySelector('.kcol[data-kcol="${id}"] .khead'); if (!h) return null;
    const w = h.querySelector('.wipc'), s = h.querySelector('.sptsum'), c = w ? getComputedStyle(w).color : '';
    return {wip: w ? w.textContent.trim() : '', over: !!w && w.classList.contains('wip-over'), pts: s ? s.textContent.trim() : '', color: c,
      plain: h.querySelector('.c:not(.wipc):not(.sptsum)')?.textContent.trim() || '', base: s ? getComputedStyle(s).color : ''}; })()`;

  const run = async (o, w, theme) => {
    const {ev, shot} = o, tag = `${w} ${theme}`;
    await o.cmd('browsingContext.setViewport', {context: o.ctx, viewport: {width: w, height: 900}});
    check(await ffLogin(o, theme) === 200, tag + ': login');
    await o.nav(B + '#l/' + P); await ready(ev, '.kanban .kcol');
    const hi = await ev(HEAD(INP)), hr = await ev(HEAD(REV)), hb = await ev(HEAD(BACK));
    check(hi && hi.wip === '4/3' && hi.over && hi.color !== hi.base, `${tag}: #1510: In progress 4/3 marked ` + JSON.stringify(hi));
    check(hr && hr.wip === '2/3' && !hr.over, `${tag}: #1510: Review 2/3 not marked ` + JSON.stringify(hr));
    check(hb && !hb.wip && hb.plain === '1', `${tag}: #1510: a column without a limit shows its count ` + JSON.stringify(hb));
    check(hi && /16/.test(hi.pts) && hr && /3/.test(hr.pts), `${tag}: #1511: the column heads add up the points ` + JSON.stringify([hi?.pts, hr?.pts]));
    const card = await ev(`(() => { const r = document.querySelector('.kcol [data-id="${T[2]}"] .sptm'); return r ? r.textContent.replace(/\\s+/g, ' ').trim() : ''; })()`);
    check(/8$/.test(card), `${tag}: #1511: the card shows its points ` + card);
    check(await ev(`!document.querySelector('.kcol [data-id="${T[3]}"] .sptm')`), `${tag}: #1511: no points, no number`);
    await shot(`p260b-kanban-${w}-${theme}.png`);
    if (w > 900 && theme === 'light') {
      // the column menu: WIP limit…, set 5 in the dialog, one undo step
      await ev(`(() => { document.querySelector('.kcol[data-kcol="${INP}"] [data-act="section-menu"]').click(); return 1; })()`); await sleep(400);
      const mi = await ev(`[...document.querySelectorAll('.menu-list [role="menuitem"]')].map(b => b.textContent.trim()).filter(t => /WIP/.test(t))`);
      check(mi.length === 1 && /3/.test(mi[0]), `${tag}: #1510: the column menu offers the limit ` + JSON.stringify(mi));
      await ev(`(() => { [...document.querySelectorAll('.menu-list [role="menuitem"]')].find(b => /WIP/.test(b.textContent)).click(); return 1; })()`); await sleep(500);
      await ev(`(() => { const i = document.querySelector('#cdlg-in'); i.value = '5'; i.closest('form').requestSubmit(); return 1; })()`); await sleep(900);
      const h5 = await ev(HEAD(INP));
      check(h5 && h5.wip === '4/5' && !h5.over, `${tag}: #1510: set to 5 in the dialog ` + JSON.stringify(h5));
      check((await call('GET', '/api/state')).sections.find(s => s.id === INP).wip_limit === 5, `${tag}: #1510: saved`);
      await ev(`(() => { histStep('undo'); return 1; })()`); await sleep(1200);
      check((await call('GET', '/api/state')).sections.find(s => s.id === INP).wip_limit === 3, `${tag}: #1510: one undo puts 3 back`);
      // the task panel: Story points
      await ev(`(() => { openDetail(${T[3]}); return 1; })()`); await sleep(900);
      const opts = await ev(`[...(document.querySelector('#d-spt')?.options || [])].map(o => o.value).join(',')`);
      check(opts === ',1,2,3,5,8,13', `${tag}: #1511: the field Story points in the panel ` + opts);
      await shot(`p260b-detail-${w}-${theme}.png`);
      await ev(`(() => { const s = document.querySelector('#d-spt'); s.value = '13'; s.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`); await sleep(1200);
      check((await call('GET', `/api/tasks/${T[3]}`)).points === 13, `${tag}: #1511: saved from the panel`);
      await ev(`(() => { histStep('undo'); return 1; })()`); await sleep(1200);
      check((await call('GET', `/api/tasks/${T[3]}`)).points === undefined, `${tag}: #1511: one undo removes them again`);
      await ev(`(() => { closeDetail?.(); return 1; })()`).catch(() => 0);
      // a list with points off: no field, no number
      await o.nav(B + '#l/' + Q); await ready(ev, '#view .trow');
      check(await ev(`!document.querySelector('#view .sptm')`), `${tag}: #1511: points off: no number in the row`);
      await ev(`(() => { openDetail(${TQ}); return 1; })()`); await sleep(900);
      check(await ev(`!document.querySelector('#d-spt')`), `${tag}: #1511: points off: no field in the panel`);
      // the list view of the project: the section head shows the limit
      await call('PATCH', `/api/lists/${P}`, {view: 'list'});
      await o.nav(B + '#l/' + Q); await sleep(300); await o.nav(B + '#l/' + P); await ready(ev, '#view .ghead');
      const gh = await ev(`document.querySelector('#view .ghead[data-section="${INP}"] .wipc')?.textContent.trim() || ''`);
      check(gh === '4/3', `${tag}: #1510: the list view's section head shows the limit ` + gh);
      await shot(`p260b-list-${w}-${theme}.png`);
      await call('PATCH', `/api/lists/${P}`, {view: 'kanban'});
    }
  };
  await firefox(async o => { await run(o, 1440, 'light'); await run(o, 1440, 'dark'); }, false);
  await firefox(async o => { await run(o, 390, 'light'); }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
