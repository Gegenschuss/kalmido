// 2.183.0 A (#2661): nothing in the top bars (#kbar on a computer, #top on every page) sticks out of its box when the texts are
// long: a long company name, a long running task, a long page title, in English and French, phone to desktop width.
// Own container (start.sh), Firefox. Invented names only. P2183A_SHOTS=dir keeps the screenshots.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2183_a_topbar_ui', check, shots: 'P2183A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,collab,stats,time,progress,deps,fields,agents,comments';
const LONGORG = 'Beispiel Filmproduktion und Medienservice Gesellschaft mit beschränkter Haftung Nord';
const LONGTASK = 'Abschlussbericht zur überregionalen Koordination der Dreharbeiten samt Nachbereitung und Rechnungsstellung';
// every box in the bars whose own text is wider than the box and not cut off, or whose right edge is outside its bar
const MEASURE = `(() => {
  const out = [];
  for (const bar of document.querySelectorAll('#kbar, #top')) {
    const br = bar.getBoundingClientRect(); if (!bar.getClientRects().length) continue;
    for (const e of bar.querySelectorAll('*')) {
      if (!e.getClientRects().length || e.closest('svg') && e.tagName !== 'svg') continue;
      const cs = getComputedStyle(e), r = e.getBoundingClientRect(); if (!r.width) continue;
      const clipped = /hidden|clip|auto|scroll/.test(cs.overflowX);
      if (!clipped && e.scrollWidth > e.clientWidth + 1 && e.clientWidth > 0 && e.tagName !== 'svg') out.push((e.id || e.className || e.tagName) + ' spills ' + e.scrollWidth + '>' + e.clientWidth);
      if (r.right > br.right + 1 || r.left < br.left - 1) out.push((e.id || e.className || e.tagName) + ' outside bar ' + Math.round(r.left) + '..' + Math.round(r.right) + ' of ' + Math.round(br.right));
    }
  }
  return JSON.stringify([...new Set(out)]);
})()`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alexandra Beispielfrau-Mustermann', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ALL.split(',').filter(x => !['collab', 'time'].includes(x))});
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const me = (await call('GET', '/api/state')).me;
  const L = (await call('POST', '/api/lists', {name: 'Eine Liste mit einem sehr langen Namen für den Test', kind: 'project', time_tracking: true})).id;
  const T = (await call('POST', '/api/tasks', {title: LONGTASK, list_id: L})).id;
  const st = await call('POST', '/api/time/start', {task_id: T});
  check(st.http < 300, 'timer started ' + st.http + ' ' + st.error);
  const org = await call('POST', '/api/admin/orgs', {name: LONGORG, admin_id: me.id});
  check(org.http < 300 && org.id, 'company created ' + org.http + ' ' + (org.error || ''));
  const wsl = (await call('GET', '/api/state')).me.workspaces || [];
  check(wsl.length > 0, 'the company is one of my workspaces ' + JSON.stringify(wsl).slice(0, 200));
  await call('PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#today'); await sleep(900);
    await ev(`typeof wsSet === 'function' ? wsSet('org:${org.id}') : 0`); await sleep(900);
    check(await ev(`wsCur() === 'org:${org.id}'`), 'the long-named company is shown ' + await ev(`String(wsCur())`));
    for (const lang of ['en', 'fr']) {
      await call('PATCH', '/api/settings', {lang});
      for (const [w, h] of [[390, 844], [412, 800], [768, 900], [1024, 800], [1280, 900]]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
        for (const route of ['#today', `#list/${L}`, '#cal', '#news', '#stats']) {
          await nav(B + route); await sleep(900);
          await ev(`wsCur() !== 'org:${org.id}' ? wsSet('org:${org.id}') : 0`); await sleep(700);  // a reload may fall back to the private space
          const res = JSON.parse(await ev(MEASURE));
          console.log(`${lang} ${w} ${route}: ${res.length ? res.join(' | ') : 'ok'}`);
          check(!res.length, `${lang} ${w}px ${route}: ${res.join(' | ')}`);
          if (route === '#today') await shot(`p2183-a-${lang}-${w}.png`);
        }
      }
    }
  });
  console.log(`p2183_a_topbar_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
