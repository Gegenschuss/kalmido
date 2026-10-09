// 2.33.0 UI tests (agent D), own container (start.sh). jsdom:
// #1045 the usage ring right of the agent's name in the chat header: none without a report; filled with the main window
//       (accent / from 75 % yellow / from the limit red with "paused until …" under the name / grey when stale); its label,
//       hover / tap list every window with % and reset time (German: 09.10.2026 14:00); a new report while the chat is open
//       redraws it in place
// #934  the folder repository (see the part below)
// Firefox 390 touch: the ring in the header (tap target >= 24 px, the list opens on a tap, screenshot); #1086 "Customize
//       Today": after scrolling, the head with "Done" stays at the top of the view, under the page header, and takes the tap
//       (screenshot).
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2330_d_ui', check, shots: 'P2330D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
// #934: the fake GitHub inside the container (fake_git.py), a key for tokens
const fs = require('fs');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const KEY = require('crypto').randomBytes(32).toString('base64');
const GH = 'http://127.0.0.1:8090', TOKEN = 'ghp_ui_fake_token_934';
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env,
  EXTRA: `-e KALMIDO_SECRET_KEY=${KEY} -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1 -e KALMIDO_GIT_POLL=2 -e KALMIDO_GIT_TICK=1`}});
fs.writeFileSync(path.join(DATA, 'git.json'), JSON.stringify({'8090': {'acme/app': {token: TOKEN, default_branch: 'main', pulls: [], commits: {main: []}}}}));
fs.copyFileSync(path.join(__dirname, 'fake_git.py'), path.join(DATA, 'fake_git.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_git.py']);
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,agents';
const V = B + 'api/v1';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ME = (await call('GET', '/api/state')).me;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  const AG = ag.id, AGH = {Authorization: 'Bearer ' + ag.token, 'Content-Type': 'application/json'};
  const L = (await call('POST', '/api/lists', {name: 'Software'})).id;
  await call('PUT', `/api/lists/${L}/members`, {user_id: AG, role: 'edit'});
  const v1 = async (method, url, body) => (await fetch(V + url, {method, headers: AGH, body: body ? JSON.stringify(body) : undefined})).json();
  const say = body => v1('POST', `/agent/chats/${ME.id}`, {body});
  const cm = (d, id) => d.querySelector(`#chat-msgs .cmsg[data-mid="a:${id}"]`);
  const reload = async w => { await w.eval('load().then(render)'); await w.eval('chatLoad()'); await sleep(300); };
  const wk = new Date(Date.UTC(2031, 0, 7, 13, 0)).getTime() / 1000, fh = new Date(Date.UTC(2031, 0, 3, 15, 30)).getTime() / 1000;

  // ================= #1045 the ring
  const hello = await say('Hello Alice');
  let w = await boot({user: 'alice', hash: 'l/' + L}), d = w.document;
  w.eval(`chatOpen(${AG})`); await until(() => cm(d, hello.id));
  check(!d.querySelector('.chring'), '#1045: no report, no ring');
  await v1('PUT', '/agent/quota', {rate_limits: {five_hour: {used_percentage: 23.5, resets_at: fh}, seven_day: {used_percentage: 41.2, resets_at: wk}}, limit: 90});
  await reload(w);
  let ring = d.querySelector('.chnm .chring');
  check(ring && ring.classList.contains('q-ok') && ring.getAttribute('aria-label') === 'Usage: 41 %', '#1045: the ring after the report (accent): ' + ring?.outerHTML.slice(0, 160));
  check(ring && ring.previousElementSibling?.tagName === 'B', '#1045: right of the name');
  const fg = ring?.querySelector('.rfg'), da = fg?.getAttribute('stroke-dasharray')?.split(' ').map(Number);
  check(da && Math.abs(da[0] / da[1] - 0.412) < 0.01, '#1045: filled with the week (41 %) ' + fg?.getAttribute('stroke-dasharray'));
  const tip = () => d.getElementById('chat-ring')?.textContent || '';
  check(/Week \(in the ring\): 41 %/.test(tip()) && /5 hours: 24 %/.test(tip()) && /Limit: 90 %/.test(tip()) && /resets /.test(tip()) && /Reported /.test(tip()),
    '#1045: the list names every window, the limit and the time: ' + JSON.stringify(tip()));
  click(w, ring); await sleep(100);
  check(d.querySelector('#iitip:not(.hidden)')?.textContent.includes('5 hours') && ring.getAttribute('aria-expanded') === 'true', '#1045: a tap opens the list');
  click(w, d.body); await sleep(50);
  check(d.querySelector('#iitip')?.classList.contains('hidden'), '#1045: a tap elsewhere closes it');
  // live: a new report while the chat stays open
  await v1('PUT', '/agent/quota', {windows: [{label: 'Week', percent: 80, resets_at: wk}]});
  await reload(w);
  ring = d.querySelector('.chnm .chring');
  check(ring?.classList.contains('q-warn') && d.querySelectorAll('.chnm .chring').length === 1 && d.querySelectorAll('#chat-ring').length === 1, '#1045: from 75 % yellow, redrawn in place');
  check(!d.querySelector('.chqp'), '#1045: no pause line below the limit');
  await v1('PUT', '/agent/quota', {windows: [{label: 'Week', percent: 92, resets_at: wk}, {label: '5 hours', percent: 3}], limit: 90});
  await reload(w);
  ring = d.querySelector('.chnm .chring');
  check(ring?.classList.contains('q-over') && /^paused until /.test(d.querySelector('.chl2 .chqp')?.textContent || ''), '#1045: from the limit red + "paused until" under the name ' + d.querySelector('.chqp')?.textContent);
  w.eval(`agentById(${AG}).quota.stale = true; chatPatch({})`); await sleep(50);
  ring = d.querySelector('.chnm .chring');
  check(ring?.classList.contains('q-stale') && !d.querySelector('.chqp') && /Outdated, last report/.test(tip()), '#1045: an old report is grey, no pause line');
  await v1('DELETE', '/agent/quota');
  await reload(w);
  check(!d.querySelector('.chring') && !d.querySelector('#chat-ring'), '#1045: the report removed, the ring gone');
  w.close();
  // German date format
  await v1('PUT', '/agent/quota', {rate_limits: {seven_day: {used_percentage: 41.2, resets_at: wk}}, limit: 90});
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + L}); d = w.document;
  w.eval(`chatOpen(${AG})`); await until(() => d.querySelector('.chring'));
  check(/Woche: 41 % · zurückgesetzt \d{2}\.\d{2}\.2031 \d{2}:\d{2}/.test(tip()) && d.querySelector('.chring')?.getAttribute('aria-label') === 'Verbrauch: 41 %',
    '#1045: German labels and date format (09.10.2026 14:00): ' + JSON.stringify(tip()));
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // ================= #934 the folder repository
  const PA = (await call('POST', '/api/lists', {name: 'App one', kind: 'project', folder: 'Apps'})).id;
  const PB = (await call('POST', '/api/lists', {name: 'App two', kind: 'project', folder: 'Apps'})).id;
  await call('POST', '/api/lists', {name: 'Notes', folder: 'Apps'});
  w = await boot({user: 'alice', hash: 'l/' + PA}); d = w.document;
  w.eval(`folderPropsModal('Apps')`); await until(() => d.querySelector('.modal [data-m="repos"]'));
  click(w, d.querySelector('.modal [data-m="repos"]'));
  await until(() => d.querySelector('.modal #l-repos #rp-name'));
  check(/Repository of the folder “Apps”/.test(d.querySelector('.modal h3')?.textContent || '') && d.querySelector('.modal #l-repos #rp-name') && !d.querySelector('.modal #rp-tok').disabled,
    '#934: folder settings > Repository opens the form ' + d.querySelector('.modal h3')?.textContent);
  d.querySelector('.modal #rp-prov').value = 'github';
  d.querySelector('.modal #rp-base').value = GH; d.querySelector('.modal #rp-name').value = 'acme/app'; d.querySelector('.modal #rp-tok').value = TOKEN;
  click(w, d.querySelector('.modal [data-rp="add"]'));
  const frow = await until(() => d.querySelector('.modal #l-repos .reporow'));
  check(frow && /acme\/app/.test(frow.textContent) && /Token set/.test(frow.textContent), '#934: connected to the folder: ' + (frow?.textContent.replace(/\s+/g, ' ') || ''));
  check(/Used by 2 of 2 project lists in this folder/.test(d.querySelector('.modal #l-repos').textContent), '#934: how many lists use it: ' + d.querySelector('.modal #l-repos .lhint[role="status"]')?.textContent);
  check(!d.querySelector('.modal').innerHTML.includes(TOKEN), '#934: no token in the page');
  click(w, d.querySelector('.modal [data-m="close"]')); await sleep(100);
  // the list dialog: from the folder, switch off / on
  w.eval(`listModal(${PB})`);
  const fr = await until(() => d.querySelector('.lmodal #l-repos .repofold'));
  check(fr && /From the folder “Apps”/.test(fr.textContent) && /acme\/app/.test(fr.textContent) && /Used by this list/.test(fr.textContent) && !d.querySelector('.lmodal #l-repos .reporow:not(.repofold) [data-rp="menu"]'),
    '#934: the list shows the folder repository (read-only) ' + (fr?.textContent.replace(/\s+/g, ' ') || ''));
  click(w, d.querySelector('.lmodal [data-rp="fold-use"]'));
  await until(() => /Switched off for this list/.test(d.querySelector('.lmodal .repofold')?.textContent || ''));
  check(/Switched off for this list/.test(d.querySelector('.lmodal .repofold')?.textContent || '') && d.querySelector('.lmodal [data-rp="fold-use"]')?.dataset.use === '1', '#934: switched off for the list');
  check((await call('GET', `/api/lists/${PB}/repos`)).folder.off === true, '#934: stored');
  click(w, d.querySelector('.lmodal [data-rp="fold-use"]'));
  await until(() => /Used by this list/.test(d.querySelector('.lmodal .repofold')?.textContent || ''));
  check((await call('GET', `/api/lists/${PB}/repos`)).folder.uses === true, '#934: on again');
  w.close();

  // ================= Firefox: the phone (390, touch)
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1, .chview')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await v1('PUT', '/agent/quota', {rate_limits: {five_hour: {used_percentage: 23.5, resets_at: fh}, seven_day: {used_percentage: 78, resets_at: wk}}, limit: 90});
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#agents/' + AG); await ready(ev); await sleep(1200);
    const g = await ev(`(() => { const r = document.querySelector('.chnm .chring'), n = document.querySelector('.chnm b'); if (!r) return null; const a = r.getBoundingClientRect(), b = n.getBoundingClientRect();
      const af = getComputedStyle(r, '::after'); r.click(); const t = document.querySelector('#iitip:not(.hidden)');
      return {w: a.width, hit: a.width + 2 * Math.abs(parseFloat(af.left) || 0), right: a.left >= b.right - 1, top: a.top, tip: t ? t.textContent : '', col: getComputedStyle(r).color,
        wide: document.documentElement.scrollWidth <= 390}; })()`);
    check(g && g.right && g.w >= 16 && g.hit >= 24, `${tag}: #1045 the ring right of the name, tap target >= 24 px ` + JSON.stringify(g));
    check(g && /5 hours: 24 %/.test(g.tip) && g.wide, `${tag}: #1045 a tap shows every window, nothing sticks out ` + JSON.stringify(g));
    await shot('p2330d-390-usage-ring.png');
    // #1086: Customize Today, scrolled: "Done" stays reachable under the page header
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 520}});
    await o.nav(B + '#today'); await ready(ev);
    await ev(`(() => { lyOpen('today', true); return 1; })()`); await sleep(600);
    const h = await ev(`(() => { const v = document.querySelector('#view'), b = document.querySelector('.lyed [data-act="ly-done"]'); if (!b) return null;
      v.scrollTop = v.scrollHeight; const sc = v.scrollTop; const r = b.getBoundingClientRect(), t = document.querySelector('#top').getBoundingClientRect(), vr = v.getBoundingClientRect();
      const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
      return {sc, top: Math.round(r.top), head: Math.round(t.bottom), view: Math.round(vr.top), h: Math.round(r.height), hit: !!hit && (hit === b || b.contains(hit))}; })()`);
    check(h && h.sc > 0, `${tag}: #1086 the editor scrolls (test needs it) ` + JSON.stringify(h));
    check(h && h.top >= h.head - 1 && h.top >= h.view - 1 && h.hit && h.h >= 32, `${tag}: #1086 "Done" stays under the page header and takes the tap ` + JSON.stringify(h));
    await shot('p2330d-390-customize-today-sticky.png');
    await ev(`(() => { document.querySelector('.lyed [data-act="ly-done"]').click(); return 1; })()`); await sleep(400);
    check(await ev(`!document.querySelector('.lyed')`), `${tag}: #1086 "Done" closes the editor after scrolling`);
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
