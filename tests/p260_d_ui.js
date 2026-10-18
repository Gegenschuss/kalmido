// 2.60.0 UI tests, part D: environments of a project (#1514) and the Office tabs that wrap (#1830); own container (start.sh).
// jsdom: the "Milestones" block of the project page lists the environments with "since" and, for an editor, "Put here…" / edit
//   buttons plus the suggestions (Staging / Live) of a software project; a viewer sees no buttons; the milestone's task row text and
//   its panel note say "Staging since ..."; the milestone panel offers "Put on Live" only where it does not run yet
// Firefox 1345 / 760 (a chat window open beside the app) / 390: every Office tab is inside the tab bar's box, the bar wraps (flex-wrap)
//   and does not scroll, the page has no horizontal overflow; the tab row of the document kinds too
// Screenshots into $P260D_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p260_d_ui', check, shots: 'P260D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), _status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,clients,office';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('POST', '/api/admin/orgs', {name: 'Kalmido'});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const P = (await call('POST', '/api/lists', {name: 'App', kind: 'project'})).id;
  await call('PATCH', `/api/lists/${P}`, {ptype: 'software'});
  const M1 = (await call('POST', `/api/lists/${P}/milestones`, {name: 'Release 2.61.0', day: '2030-05-02'})).id;
  const T1 = (await call('POST', '/api/tasks', {title: 'Ship it', list_id: P, milestone_id: M1})).id;
  const E1 = (await call('POST', `/api/lists/${P}/envs`, {name: 'Staging'})).id;
  await call('POST', `/api/lists/${P}/envs`, {name: 'Live'});
  check((await call('POST', `/api/envs/${E1}/deploy`, {milestone_id: M1}))._status === 201, 'setup: Release 2.61.0 is on Staging');

  // ================= jsdom
  let w = await boot({hash: 'l/' + P}), d = w.document;
  await until(() => d.querySelector('#view'), 60);
  await w.eval(`env_load(${P}, true)`);
  const ov = w.eval(`env_ovHtml(listById(${P}), true)`);
  check(/Environments/.test(ov) && /Staging/.test(ov) && /Live/.test(ov) && /Release 2\.61\.0/.test(ov) && /since/.test(ov), '#1514: the milestones block lists Staging (with the milestone and since) and Live: ' + ov.slice(0, 160));
  check(/data-env="set"/.test(ov) && /data-env="edit"/.test(ov) && /data-env="add"/.test(ov), '#1514: an editor gets Put here / edit / Add environment');
  check(!/data-env="add" data-name/.test(ov), '#1514: both suggestions are taken, none is offered again');
  const ro = w.eval(`env_ovHtml(listById(${P}), false)`);
  check(/Staging/.test(ro) && !/data-env=/.test(ro), '#1514: a viewer sees the environments without buttons');
  const t = w.eval(`S.tasks.get(${T1})`);
  check(/Staging since/.test(w.eval(`env_chipText(S.tasks.get(${T1}))`)), '#1514: the task row text says "Staging since ..."');
  check(/Staging since/.test(w.eval(`env_taskNote(S.tasks.get(${T1}))`)), '#1514: the task panel says it too');
  check(w.eval(`msChip(S.tasks.get(${T1}))`).includes('Staging since'), '#1514: the milestone mark in the row carries it');
  const mh = w.eval(`env_msHtml(S.tasks.get(${M1}), {envs: [{name: 'Staging', since: '2030-01-01T10:00:00+00:00'}]})`);
  check(/Put on Live/.test(mh) && !/Put on Staging/.test(mh), '#1514: the milestone panel offers Live, not Staging (it is there)');
  w.close();

  // ================= Firefox: the Office tabs
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  // 2.87.9 (#1917): the office menu (computer: four groups; phone: the group's points) replaces the tab row; the same rules
  // 2.98.0 (#2180): computer = the office rail (one point per line, nothing cut off); phone = ONE row of tabs that scrolls
  // sideways instead of wrapping (Moritz' choice of variant A, 18.10.2026), the active tab in sight
  const tabs = `(() => { const bar = document.querySelector('#view .ofrail, #view .ofpb'); if (!bar) return null; const b = bar.getBoundingClientRect(); const bs = [...bar.querySelectorAll('[data-ofm]')], ts = bs.map(x => x.getBoundingClientRect());
    const row = bar.querySelector('.ofpts'), rb = row && row.getBoundingClientRect(), on = bar.querySelector('[data-ofm].on'), ob = on && on.getBoundingClientRect();
    const k = document.querySelector('.office .ofdkinds'); const kb = k && k.getBoundingClientRect();
    return JSON.stringify({rail: bar.classList.contains('ofrail'), n: ts.length, inside: ts.every(r => r.left >= b.left - 1 && r.right <= b.right + 1 && r.width > 0), wrap: row ? getComputedStyle(row).flexWrap : '', ox: row ? getComputedStyle(row).overflowX : '',
      rows: new Set(ts.map(r => Math.round(r.top))).size, onSeen: !!ob && (!rb || ob.left >= rb.left - 1 && ob.right <= rb.right + 1), kinds: kb ? [...k.querySelectorAll('button')].every(x => { const r = x.getBoundingClientRect(); return r.right <= kb.right + 1 && r.width > 0; }) : true,
      over: document.documentElement.scrollWidth > window.innerWidth + 1}); })()`;
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, 'office: login');
    for (const [wd, tag] of [[1345, '1345'], [760, '760-chat'], [390, '390']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: wd, height: 850}});
      await o.nav(B + '#office/offers');
      await until(() => ev(`!!document.querySelector('#view .ofrail, #view .ofpb')`).catch(() => false), 60); await sleep(900);
      const g = JSON.parse(await ev(tabs));
      check(g && g.n >= (wd < 900 ? 2 : 6) && g.onSeen, `#1830 ${tag}: the points are there, the active one in sight ` + JSON.stringify(g));
      check(g && (wd < 900 ? !g.rail && g.wrap === 'nowrap' && g.ox === 'auto' && g.rows === 1 : g.rail && g.inside && g.rows === g.n), `#1830 ${tag}: ${wd < 900 ? 'one row that scrolls sideways' : 'the rail, one point per line'} ` + JSON.stringify(g));
      check(g && g.kinds && !g.over, `#1830 ${tag}: the kind switches fit, no horizontal overflow ` + JSON.stringify(g));
      await shot(`p260d-office-${tag}.png`);
    }
  }, undefined);

  console.log(`p260_d_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
