// 2.283.0 UI tests (own container, Firefox 402 touch):
// #3124 a real finger tap on the + button (phone) opens the quick add sheet with the focus in its field, in the inbox and in
// a project of an organisation shared with an agent (the iOS device test of 2.277.3: in the project only a script click
// worked); nothing lies over the button (elementFromPoint at its middle and edges)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2283_ui', check, shots: 'P2283_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2283_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };

(async () => {
  await sleep(800);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  let s = await call('GET', '/api/state');
  const feats = new Set((s.settings.features || '').split(',').filter(Boolean)); feats.add('agents');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: [...feats].join(',')});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  const ag = await call('POST', '/api/admin/agents', {scopes: ['read', 'tasks:write', 'comments'], username: 'devbot', display_name: 'Dev Bot'});
  await call('PATCH', `/api/admin/agents/${ag.id}`, {org_id: ORG});
  const W = (await call('POST', '/api/lists', {name: 'Work', org_id: ORG})).id;
  await call('PUT', `/api/lists/${W}/members`, {user_id: ag.id, role: 'edit'});
  for (let i = 0; i < 3; i++) await call('POST', '/api/tasks', {title: 'Task ' + i, list_id: W});
  await call('POST', `/api/agents/${ag.id}/chat`, {body: 'Hello'});
  check(W > 0 && ag.id > 0, 'seed: project of the organisation, shared with an agent');
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    await o.nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    const st = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
    check(st === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 402, height: 874}});
    const tap = (x, y) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(x), y: Math.round(y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 60}, {type: 'pointerUp', button: 0}]}]}).then(() => cmd('input.releaseActions', {context: ctx}));
    for (const [where, hash] of [['inbox', '#inbox'], ['project', `#l/${W}`]]) {
      await o.nav(B + hash);
      for (let i = 0; i < 40 && !(await ev(`!!(window.S && S.booted && document.querySelector('#fab:not(.gone)'))`).catch(() => false)); i++) await sleep(250);
      for (let i = 0; i < 40 && (await ev(`document.getAnimations().filter(a => a.playState === 'running').length`).catch(() => 0)); i++) await sleep(100);
      const p = await ev(`(() => {
        const f = document.querySelector('#fab'), r = f.getBoundingClientRect(), out = {r: [r.left, r.top, r.width, r.height], hits: []};
        for (const [dx, dy] of [[0, 0], [-0.35, -0.35], [0.35, -0.35], [-0.35, 0.35], [0.35, 0.35]]) {
          const x = r.left + r.width * (0.5 + dx), y = r.top + r.height * (0.5 + dy), h = document.elementFromPoint(x, y);
          out.hits.push(h && f.contains(h) ? 'fab' : h ? h.tagName + '#' + h.id + '.' + String(h.className?.baseVal ?? h.className) : 'null');
        }
        out.pe = getComputedStyle(f).pointerEvents; out.inert = f.inert;
        return out; })()`);
      check(p.hits.every(h => h === 'fab') && p.pe !== 'none' && !p.inert, `${where}: nothing lies over the + button ` + JSON.stringify(p));
      await shot(`p2283_${where}_before.png`);
      await tap(p.r[0] + p.r[2] / 2, p.r[1] + p.r[3] / 2);
      let open = false;
      for (let i = 0; i < 30 && !(open = await ev(`!!document.querySelector('.qadd.sheet') && document.activeElement?.id === 'qsheet'`)); i++) await sleep(100);
      await shot(`p2283_${where}_after.png`);
      check(open, `${where}: a finger tap on + opens the quick add with the focus in its field ` + JSON.stringify(await ev(`[!!document.querySelector('.qadd.sheet'), document.activeElement?.id || document.activeElement?.tagName]`)));
      if (where === 'project') {  // the device test missed only after the sheet had been used: add a task, close by a tap beside it, + again
        await ev(`(() => { const i = document.querySelector('#qsheet'); i.value = 'Tapped task'; i.dispatchEvent(new InputEvent('input', {bubbles: true})); document.querySelector('[data-act="qsheet-send"]').click(); return 1; })()`);
        let made = false;
        // 2.381.0 (#3543): up to 15 s - under a loaded runner the new task was not there after 3 s (alone green)
        for (let i = 0; i < 150 && !(made = await ev(`[...S.tasks.values()].some(t => t.title === 'Tapped task' && t.list_id === ${W})`)); i++) await sleep(100);
        check(made, 'project: the task from the sheet is in the project');
        await tap(200, 120);
        for (let i = 0; i < 30 && (await ev(`!!document.querySelector('.qadd.sheet') || !document.querySelector('#fab:not(.gone)') || !!document.querySelector('.an-out')`)); i++) await sleep(100);
        for (let i = 0; i < 40 && (await ev(`document.getAnimations().filter(a => a.playState === 'running').length`).catch(() => 0)); i++) await sleep(100);
        check(await ev(`!document.querySelector('.qadd.sheet') && !!document.querySelector('#fab:not(.gone)')`), 'project: a tap beside the sheet closes it, + is back');
        const q = await ev(`(() => { const f = document.querySelector('#fab'), r = f.getBoundingClientRect(), h = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2); return [r.left + r.width / 2, r.top + r.height / 2, !!h && f.contains(h)]; })()`);
        check(q[2], 'project: nothing over + after the sheet ' + JSON.stringify(q));
        await tap(q[0], q[1]);
        let again = false;
        for (let i = 0; i < 30 && !(again = await ev(`!!document.querySelector('.qadd.sheet') && document.activeElement?.id === 'qsheet'`)); i++) await sleep(100);
        check(again, 'project: the second finger tap on + opens the quick add again');
      }
      await ev(`(() => { closePop(); return 1; })()`);
    }
  }, true);
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
