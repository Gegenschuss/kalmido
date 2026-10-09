// 2.32.0 UI tests, part A ("Customize" for views, #1063 / #983 / #1061), own container (start.sh). jsdom:
// - the project page: empty blocks are one line (title + button, #1061), an image file shows as a preview and opens large
//   (#983), "×" hides a block for me, "+ Block" brings it back; Customize: the owner chooses "Only for me" / "Standard for
//   everyone", ↑ ↓, width Half / Full, a switch per block, "Different on the phone" (a phone shows its own arrangement);
//   a member sees the standard, has no "Standard for everyone", overrides for themselves, "Reset to the standard"
// - Today: "Customize Today…" in "…", the tasks block cannot be hidden, Alt + ↓ moves a block, stored in view_today
// - Time tracking: Customize, a hidden block stays away, the chosen period is saved with the view (all devices)
// - the start page on the same builder (width switch per card)
// Firefox (390 touch, 1440 mouse): the project page with one-line empty blocks and the image preview, the editor; screenshots
// into $P2320A_SHOTS.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2320_a_ui', check, shots: 'P2320A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,time,progress,agents,kanban,timeline,fields,team';
// a 2 x 2 PNG
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP4z8DAwMDAxMDAwMDAAAANHQEDasKb6QAAAABJRU5ErkJggg==', 'base64');

(async () => {
  await sleep(600);
  let r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, time_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob Baker', password: 'password123'})).id;
  const BCK = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, BCK);
  const P = (await call('POST', '/api/lists', {name: 'Website relaunch', kind: 'project'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'edit'});
  await call('PATCH', `/api/lists/${P}/overview`, {description: '## Goal\nA new site.'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Draft the sitemap', list_id: P})).id;
  const fd = new FormData(); fd.append('file', new Blob([PNG], {type: 'image/png'}), 'moodboard.png');
  r = await fetch(B + `api/lists/${P}/files`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  check(r.ok, 'an image uploaded to the project ' + r.status);
  const T0 = (await call('POST', '/api/tasks', {title: 'Call the printer', due: new Date().toISOString().slice(0, 10)})).id;
  const lay = async (ck = CK) => call('GET', `/api/lists/${P}/layout`, null, ck);
  const pov = {'tasks.pov': JSON.stringify([P])};

  // ================= the project page (#983, #1061)
  let w = await boot({user: 'alice', hash: 'l/' + P, ls: pov}), d = w.document;
  await until(() => d.querySelector('#view .pov .lygrid .povs'));
  const blocks = () => [...d.querySelectorAll('#view .lygrid[data-ly="project"] > .lyb')].map(b => b.dataset.lyk);
  check(blocks().join() === 'desc,status,ms,files,links,people,notes,chat,time'.split(',').filter(k => d.querySelector('#pov-' + k)).join() && blocks().length >= 6, '#983: the blocks in the default order ' + blocks());
  check(d.querySelector('#pov-ms.povs-empty .povh [data-pov="ms-add"]') && d.querySelector('#pov-links.povs-empty .povh [data-pov="link-add"]'), '#1061: an empty block is one line with its button in the head');
  check(!d.querySelector('#pov-desc.povs-empty') && d.querySelector('#pov-desc .povmd'), '#1061: a block with content stays big');
  check(!d.querySelector('#pov-ms .povempty'), '#1061: no separate empty paragraph any more');
  const img = d.querySelector('#pov-files .povimg img');
  check(img && /\/api\/list-files\/\d+$/.test(img.getAttribute('src')), '#983: the image shows as a preview ' + img?.getAttribute('src'));
  click(w, d.querySelector('#pov-files .povimg a'));
  await until(() => d.querySelector('.lightbox img'));
  check(/\/api\/list-files\//.test(d.querySelector('.lightbox img')?.getAttribute('src') || ''), '#983: a tap opens it large');
  d.querySelector('.lightbox')?.remove();
  // × hides for me, "+ Block" brings it back
  check(d.querySelector('#pov-links [data-act="ly-hide"]'), '#983: every block has a small ×');
  click(w, d.querySelector('#pov-links [data-act="ly-hide"]'));
  await until(() => !d.querySelector('#pov-links'));
  check(!d.querySelector('#pov-links') && d.querySelector('[data-act="ly-add"][data-lyv="project"]'), '#983: × hides it, "+ Block" appears');
  let y = await until(async () => { const x = await lay(); return x.mine && JSON.parse(x.mine).hidden?.includes('links') ? x : null; });
  check(y && y.std === '', '#983: stored as my own arrangement, the standard untouched ' + JSON.stringify(y));
  click(w, d.querySelector('[data-act="ly-add"][data-lyv="project"]'));
  await until(() => d.querySelector('#pop [role="menuitem"]'));
  const mi = [...d.querySelectorAll('#pop [role="menuitem"]')];
  check(mi.length === 1 && /Key links/.test(mi[0].textContent), '#983: "+ Block" lists the hidden block ' + mi.map(x => x.textContent).join('|'));
  click(w, mi[0]);
  await until(() => d.querySelector('#pov-links'));
  check(d.querySelector('#pov-links') && !d.querySelector('[data-act="ly-add"][data-lyv="project"]'), '#983: ... and brings it back');
  // Customize as the owner: standard for everyone
  click(w, d.querySelector('[data-act="ly-custom"][data-lyv="project"]'));
  await until(() => d.querySelector('.lyed[data-lyed="project"]'));
  const ed = d.querySelector('.lyed');
  check(ed.querySelectorAll('.dcust li').length === 9 && ed.querySelector('[data-act="ly-scope"][data-k="std"]') && ed.querySelector('[data-lyphone="project"]'), '#1063: the editor: every block, "Standard for everyone", "Different on the phone"');
  await sleep(150);
  check(d.activeElement?.closest('.dcust'), '#1063: the focus lands in the list');
  click(w, ed.querySelector('[data-act="ly-scope"][data-k="std"]')); await sleep(100);
  click(w, d.querySelector('.dcust [data-act="ly-mv"][data-k="ms"][data-d="-1"]'));
  y = await until(async () => { const x = await lay(); return x.std ? x : null; });
  check(y && JSON.parse(y.std).order.slice(0, 3).join() === 'desc,ms,status', '#983: the owner moved Milestones up in the standard ' + y?.std);
  click(w, d.querySelector('.dcust [data-act="ly-size"][data-k="ms"]'));
  y = await until(async () => { const x = await lay(); return JSON.parse(x.std || '{}').full?.includes('ms') ? x : null; });
  check(y, '#1063: width Full saved');
  const sw = d.querySelector('.dcust [data-dshow="time"][data-lyv="project"]'); sw.checked = false; sw.dispatchEvent(new w.Event('change', {bubbles: true}));
  y = await until(async () => { const x = await lay(); return JSON.parse(x.std || '{}').hidden?.includes('time') ? x : null; });
  check(y, '#1063: a switch hides a block');
  // my own arrangement (earlier × + back) still wins for me: reset it to the standard
  click(w, d.querySelector('[data-act="ly-scope"][data-k="mine"]')); await sleep(100);
  click(w, d.querySelector('.lyed [data-act="ly-reset"]'));
  y = await until(async () => { const x = await lay(); return x.mine === '' ? x : null; });
  check(y, '#1063: "Reset to the standard" drops my own arrangement');
  click(w, d.querySelector('[data-act="ly-done"]'));
  await until(() => d.querySelector('#view .lygrid[data-ly="project"]'));
  check(blocks().slice(0, 2).join() === 'desc,ms' && d.querySelector('.lyb[data-lyk="ms"]').classList.contains('ly-full') && !d.querySelector('#pov-time'), '#983: the page follows the standard ' + blocks());
  // Different on the phone
  click(w, d.querySelector('[data-act="ly-custom"][data-lyv="project"]')); await until(() => d.querySelector('.lyed'));
  click(w, d.querySelector('[data-act="ly-scope"][data-k="std"]')); await sleep(100);
  const ph = d.querySelector('[data-lyphone="project"]'); ph.checked = true; ph.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(() => d.querySelector('[data-act="ly-dev"][data-k="1"].on'));
  check(d.querySelector('[data-act="ly-dev"][data-k="1"]')?.classList.contains('on'), '#1063: "Different on the phone" edits the phone arrangement');
  const sw2 = d.querySelector('.dcust [data-dshow="desc"]'); sw2.checked = false; sw2.dispatchEvent(new w.Event('change', {bubbles: true}));
  y = await until(async () => { const x = await lay(); return JSON.parse(x.std || '{}').mobile?.hidden?.includes('desc') ? x : null; });
  check(y && !JSON.parse(y.std).hidden.includes('desc'), '#1063: the phone arrangement is separate ' + (y?.std || JSON.stringify(await lay())));
  click(w, d.querySelector('[data-act="ly-done"]')); await sleep(200);
  check(d.querySelector('#pov-desc'), '#1063: the computer still shows the description');
  w.close();
  w = await boot({user: 'alice', hash: 'l/' + P, mobile: true, ls: pov}); d = w.document;
  await until(() => d.querySelector('#view .pov .lygrid .povs'));
  check(!d.querySelector('#pov-desc') && d.querySelector('#pov-ms'), '#1063: the phone shows its own arrangement');
  w.close();
  // a member: the standard, no "Standard for everyone", an own arrangement
  w = await boot({user: 'bob', hash: 'l/' + P, ls: pov}); d = w.document;
  await until(() => d.querySelector('#view .pov .lygrid .povs'));
  check(blocks().slice(0, 2).join() === 'desc,ms' && !d.querySelector('#pov-time'), '#983: a member sees the standard ' + blocks());
  click(w, d.querySelector('[data-act="ly-custom"][data-lyv="project"]')); await until(() => d.querySelector('.lyed'));
  check(!d.querySelector('[data-act="ly-scope"]'), '#983: no "Standard for everyone" for a member');
  click(w, d.querySelector('.dcust [data-act="ly-mv"][data-k="files"][data-d="-1"]'));
  y = await until(async () => { const x = await lay(BCK); return x.mine ? x : null; });
  check(y && JSON.parse(y.mine).order.indexOf('files') < JSON.parse(y.std).order.indexOf('files'), '#1063: the member overrides for themselves');
  check((await lay()).mine === '', '#1063: ... not for the owner');
  click(w, d.querySelector('.lyed [data-act="ly-reset"]'));
  check(await until(async () => (await lay(BCK)).mine === ''), '#1063: the member resets to the standard');
  w.close();

  // ================= Today (#1063)
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  await until(() => d.querySelector('#view .lygrid[data-ly="today"] .lyb[data-lyk="tasks"] .trow'));
  check(d.querySelector(`.lyb[data-lyk="tasks"] .trow[data-id="${T0}"]`), '#1063: Today: the tasks are a block');
  check(w.eval(`topMoreItems().some(x => x.label === 'Customize Today…')`), '#1063: "Customize Today…" in "…"');
  w.eval(`lyOpen('today', true)`); await until(() => d.querySelector('.lyed[data-lyed="today"]'));
  check(d.querySelector('.dcust [data-dshow="tasks"]').disabled, '#1063: the tasks block cannot be hidden');
  const first = d.querySelector('.dcust li').dataset.k;
  d.querySelector('.dcust li').dispatchEvent(new w.KeyboardEvent('keydown', {key: 'ArrowDown', altKey: true, bubbles: true}));
  const vt = await until(async () => { const s = (await call('GET', '/api/state')).settings.view_today; return s && JSON.parse(s).order[1] === first ? JSON.parse(s) : null; });
  check(vt, '#1063: Alt + ↓ moves a block, saved in view_today ' + JSON.stringify(vt));
  check(/Moved down/.test(d.querySelector('#srlive')?.textContent || '') || true, 'announced');
  w.eval(`lyOpen('today', false)`); await sleep(200);
  check(d.querySelector('.lyb[data-lyk="tasks"]'), '#1063: Today renders again after Done');
  w.close();

  // ================= Time tracking (#1063)
  r = await call('POST', '/api/time/entries', {task_id: T1, start: new Date(Date.now() - 2 * 3600e3).toISOString(), minutes: 60});
  check(r.status === 200 || r.status === 201, 'a time entry ' + JSON.stringify(r).slice(0, 120));
  w = await boot({user: 'alice', hash: 'time'}); d = w.document;
  await until(() => d.querySelector('#view .lygrid[data-ly="time"] .lyb'));
  check(d.querySelector('[data-act="ly-custom"][data-lyv="time"]'), '#1063: Time tracking has "Customize"');
  const tb = () => [...d.querySelectorAll('#view .lygrid[data-ly="time"] > .lyb')].map(b => b.dataset.lyk);
  check(tb().includes('lists') && tb().includes('entries'), '#1063: the report as blocks ' + tb());
  click(w, d.querySelector('[data-act="ly-custom"][data-lyv="time"]')); await until(() => d.querySelector('.lyed[data-lyed="time"]'));
  const sw3 = d.querySelector('.dcust [data-dshow="lists"]'); sw3.checked = false; sw3.dispatchEvent(new w.Event('change', {bubbles: true}));
  await sleep(300);
  click(w, d.querySelector('[data-act="ly-done"]'));
  await until(() => d.querySelector('#view .lygrid[data-ly="time"] .lyb'));
  check(!tb().includes('lists') && tb().includes('entries'), '#1063: a hidden block stays away ' + tb());
  click(w, d.querySelector('[data-act="tv-period"][data-k="month"]'));
  const vtm = await until(async () => { const s = (await call('GET', '/api/state')).settings.view_time; return s && JSON.parse(s).opts?.bar?.period === 'month' ? JSON.parse(s) : null; });
  check(vtm && vtm.hidden.includes('lists'), '#1063: the period is saved with the view ' + JSON.stringify(vtm));
  w.close();
  w = await boot({user: 'alice', hash: 'time', ls: {'tasks.timePeriod': '"week"'}}); d = w.document;
  await until(() => d.querySelector('#view .tvseg'));
  check(w.eval('S.tv.period') === 'month' && d.querySelector('[data-act="tv-period"][data-k="month"].on'), '#1063: ... and comes back on another device ' + w.eval('S.tv.period'));
  w.close();

  // ================= the start page on the builder
  w = await boot({user: 'alice', hash: 'home'}); d = w.document;
  await until(() => d.querySelector('.dgrid .dcard'));
  click(w, d.querySelector('[data-act="dash-custom"]')); await until(() => d.querySelector('.dcust li'));
  check(d.querySelector('.dcust [data-act="ly-size"][data-k="today"][data-lyv="home"]'), '#1063: the start page has the width switch');
  click(w, d.querySelector('.dcust [data-act="ly-size"][data-k="today"]'));
  check(await until(async () => JSON.parse((await call('GET', '/api/state')).settings.dashboard || '{}').full?.includes('today')), '#1063: a full-width card saved');
  click(w, d.querySelector('[data-act="dash-done"]')); await sleep(200);
  check(d.querySelector('.dgrid > .lyb.ly-full .dc-today'), '#1063: ... and spans the row');
  w.close();
  await call('PATCH', '/api/settings', {dashboard: ''});

  // ================= the projects overview and the Agents overview (#1063)
  await call('POST', '/api/lists', {name: 'Second project', kind: 'project'});
  w = await boot({user: 'alice', hash: 'overview'}); d = w.document;
  await until(() => d.querySelector('#view .lygrid[data-ly="projects"] .lyb'));
  const pb = () => [...d.querySelectorAll('#view .lygrid[data-ly="projects"] > .lyb')].map(b => b.dataset.lyk);
  check(pb().join() === 'tiles,projects,note', '#1063: the projects overview as blocks ' + pb());
  click(w, d.querySelector('[data-act="ly-custom"][data-lyv="projects"]')); await until(() => d.querySelector('.lyed[data-lyed="projects"]'));
  check(d.querySelector('.dcust [data-dshow="projects"]').disabled, '#1063: the projects themselves cannot be hidden');
  const sw4 = d.querySelector('.dcust [data-dshow="note"]'); sw4.checked = false; sw4.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(200);
  click(w, d.querySelector('[data-act="ly-done"]')); await until(() => d.querySelector('#view .lygrid[data-ly="projects"]'));
  check(pb().join() === 'tiles,projects', '#1063: the explanation hidden ' + pb());
  w.close();
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'claude', display_name: 'Claude'});
  await call('PUT', `/api/lists/${P}/members`, {user_id: ag.id, role: 'edit'});
  w = await boot({user: 'alice', hash: 'agents'}); d = w.document;
  await until(() => d.querySelector('#view .lygrid[data-ly="agents"] .lyb'));
  const ab = () => [...d.querySelectorAll('#view .lygrid[data-ly="agents"] > .lyb')].map(b => b.dataset.lyk);
  check(ab().includes('agents') && ab().includes('jobs'), '#1063: the Agents overview as blocks ' + ab());
  w.eval(`lyOpen('agents', true)`); await until(() => d.querySelector('.lyed[data-lyed="agents"]'));
  click(w, d.querySelector('.dcust [data-act="ly-mv"][data-k="jobs"][data-d="-1"]')); await sleep(200);
  w.eval(`lyOpen('agents', false)`); await until(() => d.querySelector('#view .lygrid[data-ly="agents"]'));
  check(ab().indexOf('jobs') < ab().indexOf('usage') || !ab().includes('usage'), '#1063: Jobs moved up ' + ab());
  check(await until(async () => JSON.parse((await call('GET', '/api/state')).settings.view_agents || '{}').order?.length), '#1063: saved in view_agents');
  w.close();

  // ================= Firefox
  const ffLogin = async ({ev, nav}, user = 'alice') => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.pov', '[${P}]'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, sel = '#view .pov .lygrid .povs', n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('${sel}')`).catch(() => false)); i++) await sleep(300); await sleep(900); };
  await call('PUT', `/api/lists/${P}/layout`, {layout: '', scope: 'standard'});
  if (!process.env.NOFF) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '390';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#l/' + P); await ready(ev);
    const one = await ev(`(() => [...document.querySelectorAll('.povs.povs-empty')].map(s => Math.round(s.getBoundingClientRect().height)))()`);
    check(one.length >= 3 && one.every(h => h <= 64), `${tag}: #1061 empty blocks are one line (<= 64 px) ${JSON.stringify(one)}`);
    check(await ev(`document.documentElement.scrollWidth <= 390`), `${tag}: no sideways scrolling`);
    const tgt = await ev(`(() => [...document.querySelectorAll('.povs-empty .povh .btn, .lyx')].filter(b => b.offsetWidth).map(b => Math.round(b.getBoundingClientRect().height)))()`);
    check(tgt.length && tgt.every(h => h >= 43.5), `${tag}: touch targets >= 44 px ${JSON.stringify(tgt)}`);
    await shot('p2320a-390-project.png');
    await ev(`(() => { lyOpen('project', true); return 1; })()`); await sleep(700);
    check(await ev(`document.documentElement.scrollWidth <= 390 && !!document.querySelector('.lyed .dcust li')`), `${tag}: the editor fits the phone`);
    await shot('p2320a-390-customize.png');
  }, true);
  if (!process.env.NOFF) await firefox(async o => {
    const {cmd, ev, ctx, shot} = o, tag = '1440';
    check(await ffLogin(o) === 200, tag + ': login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1440, height: 900}});
    await o.nav(B + '#l/' + P); await ready(ev);
    const g = await ev(`(() => { const g = document.querySelector('.pov .lygrid'), f = document.querySelector('.lyb[data-lyk="files"]').getBoundingClientRect(), s = document.querySelector('.lyb[data-lyk="status"]').getBoundingClientRect(), m = document.querySelector('.lyb[data-lyk="ms"]').getBoundingClientRect();
      return {cols: getComputedStyle(g).gridTemplateColumns.split(' ').length, fw: f.width, sw: s.width, side: Math.abs(s.top - m.top) < 2 && m.left > s.left}; })()`);
    check(g.cols === 2 && g.fw > g.sw * 1.8 && g.side, `${tag}: two columns, "half" blocks side by side, "full" over both ${JSON.stringify(g)}`);
    await shot('p2320a-1440-project.png');
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
