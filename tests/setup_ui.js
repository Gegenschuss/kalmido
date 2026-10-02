// First-run setup (jsdom): step 1 creates the admin, step 2 "What do you want to use?" (presets "Simple list" (2.7.0: the
// preselected start of a new instance, comments off too) / "Just me" / "Projects & team", fine-tuning, skip, language) and
// "Start with" (2.7.0, K21: Empty / Sample project / Agency / Software / Personal as cards) sets the instance switches +
// default modules. Then: the admin
// creates the second user while collaboration is off -> "Turn on collaboration now?".
// Restarts the test container (start.sh) for every fresh install.
const {execFileSync} = require('child_process');
const path = require('path');
const {JSDOM, VirtualConsole} = require('jsdom');
const B = process.env.BASE || `http://127.0.0.1:${process.env.KALMIDO_TEST_PROXY_PORT || 3041}/`;
const F = []; let ok = 0; const errs = [];
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const sleep = ms => new Promise(r => setTimeout(r, ms));
const fresh = () => execFileSync('bash', [path.join(__dirname, 'start.sh')], {stdio: 'ignore'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};

async function open(jar) {  // the app with a cookie jar of its own (the setup response logs the admin in)
  const vc = new VirtualConsole(); vc.on('jsdomError', e => { if (!/navigation|Not implemented/.test(e.message)) errs.push(e.message); });
  const dom = await JSDOM.fromURL(B, {runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(w) {
      const store = {};
      w.matchMedia = q => ({matches: false, addEventListener() {}, addListener() {}});
      Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; }, key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
      w.fetch = async (u, o = {}) => {
        const r = await fetch(new URL(String(u), B), {...o, headers: {...(o.headers || {}), ...(jar.c ? {Cookie: jar.c} : {})}});
        const sc = r.headers.get('set-cookie'); if (sc) jar.c = sc.split(';')[0];
        return r;
      };
      w.Request = Request; w.Response = Response; w.Headers = Headers; w.FormData = FormData;
      Object.defineProperty(w.navigator, 'serviceWorker', {value: {register: () => Promise.resolve(), addEventListener() {}, controller: null}});
      w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
      w.confirm = () => true; w.prompt = () => null;
      require('./boot').dialogBridge(w);
    }});
  await sleep(1500);
  return dom.window;
}
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const api = async (jar, method, url, body) => (await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: jar.c}, body: body ? JSON.stringify(body) : undefined})).json();

async function step1(w, user = 'admin') {
  const d = w.document;
  const form = d.querySelector('.authscreen #auth-form');
  if (!form) return false;
  d.querySelector('#au-user').value = user; d.querySelector('#au-name').value = 'Admin'; d.querySelector('#au-pw').value = 'password123';
  form.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  for (let i = 0; i < 30 && !d.querySelector('.setupcard'); i++) await sleep(100);
  return !!d.querySelector('.setupcard');
}
const feats = st => st.settings.features.split(',');

(async () => {
  // ---- 1: preset "Just me" -> collaboration + time tracking off, all other modules on (2.7.0: "Simple list" is preselected)
  fresh();
  let jar = {}, w = await open(jar), d = w.document;
  check(await step1(w), 'setup: step 2 appears after the admin was created');
  check(/What do you want to use\?/.test(d.querySelector('.setupcard').textContent), 'step 2 title');
  check([...d.querySelectorAll('[data-su-preset]')].map(b => b.dataset.suPreset).join() === 'simple,solo,team', 'three preset cards: Simple list, Just me, Projects & team');
  check(d.querySelector('[data-su-preset="simple"]').classList.contains('on') && d.querySelector('[data-su-preset="simple"]').getAttribute('aria-pressed') === 'true' && !d.querySelector('[data-su-preset="solo"]').classList.contains('on'), '2.7.0: "Simple list" preselected');
  check(!d.querySelector('[data-use="comments"]').checked && !d.querySelector('[data-use="collab"]').checked, '2.7.0: Simple list: comments + collaboration off');
  check([...d.querySelectorAll('[data-su-start]')].map(b => b.dataset.suStart).join() === ',sample,agency,software,private' && d.querySelector('[data-su-start=""]').classList.contains('on'), 'K21: "Start with": Empty (preselected), Sample, Agency, Software, Personal');
  check(!d.querySelector('#su-ptype') && !d.querySelector('[data-su-sample]'), 'K21: no project select, no sample checkbox any more');
  click(w, d.querySelector('[data-su-preset="solo"]')); await sleep(100);
  check(d.querySelector('[data-su-preset="solo"]').classList.contains('on'), '"Just me" picked');
  check(!d.querySelector('[data-use="collab"]').checked && !d.querySelector('[data-use="time"]').checked && d.querySelector('[data-use="habits"]').checked && d.querySelector('[data-use="timeline"]').checked, 'Just me: collab + time unticked, views ticked');
  check(d.querySelector('[data-use="deps"]') && !d.querySelector('[data-use="deps"]').checked && !d.querySelector('[data-use="fields"]').checked, 'Just me: dependencies + custom fields listed, unticked');
  check(!d.querySelector('[data-use="paperless"]'), 'Paperless hidden when not configured');
  check(/changed later in Settings/.test(d.querySelector('.setupcard').textContent), 'mentions Settings');
  click(w, d.querySelector('[data-su="go"]')); await sleep(800);
  let st = await api(jar, 'GET', '/api/state');
  check(st.collab_all === false && st.time_all === false, 'Just me: instance switches off');
  check(['cal', 'timeline', 'matrix', 'kanban', 'habits', 'pomo', 'stats', 'progress'].every(f => feats(st).includes(f)) && !feats(st).includes('deps') && !feats(st).includes('fields'), 'Just me: modules on for the admin, deps + fields off');
  // later changes still work: turn time tracking on in "Whole server"
  await api(jar, 'PATCH', '/api/admin/settings', {time_all: true});
  st = await api(jar, 'GET', '/api/state');
  check(st.time_all === true && feats(st).includes('time'), 'later: time tracking on for everyone works at once');
  await api(jar, 'PATCH', '/api/admin/settings', {time_all: false});
  w.close();
  // second user while collaboration is off -> prompt, "Yes" turns it on (+ personal switches of both)
  await api(jar, 'PATCH', '/api/settings', {features: feats(st).filter(f => f !== 'collab').join(',')});  // admin's own switch off too
  w = await open(jar); d = w.document; await sleep(300);
  const addUser = async name => {
    w.eval(`settingsModal('users')`); await sleep(400);
    click(w, d.querySelector('[data-acc="user-new"]')); await sleep(200);
    const um = [...d.querySelectorAll('.modal')].pop();
    um.querySelector('#u-user').value = name; um.querySelector('#u-name').value = name; um.querySelector('#u-pw').value = 'password123';
    click(w, um.querySelector('[data-m="save"]')); await sleep(900);
  };
  await addUser('bob');
  let ask = d.querySelector('.modal.collabask');
  check(ask && /Turn on collaboration now\?/.test(ask.textContent), 'second user: "Turn on collaboration now?"');
  click(w, ask.querySelector('[data-m="yes"]')); await sleep(900);
  st = await api(jar, 'GET', '/api/state');
  const bj = {}; await fetch(B + 'api/auth/login', {method: 'POST', headers: H, body: JSON.stringify({username: 'bob', password: 'password123'})}).then(r => { bj.c = r.headers.get('set-cookie').split(';')[0]; });
  const bst = await api(bj, 'GET', '/api/state');
  check(st.collab_all === true && feats(st).includes('collab') && feats(bst).includes('collab'), 'Yes: collaboration on for the server and both users');
  check(!['collab', 'time'].some(f => !feats(bst).includes(f)) && bst.time_all === false, 'second user got the default modules (time switch still off)');
  d.querySelectorAll('.modal').forEach(m => m.remove());
  // third user: no prompt (only for the second)
  await api(jar, 'PATCH', '/api/admin/settings', {collab_all: false});
  await w.eval('load()');
  await addUser('carol');
  check(!d.querySelector('.modal.collabask'), 'third user: no prompt');
  w.close();

  // ---- 2: second user, "Not now" keeps it off
  fresh();
  jar = {}; w = await open(jar); d = w.document;
  await step1(w); click(w, d.querySelector('[data-su="go"]')); await sleep(800);
  w.close(); w = await open(jar); d = w.document; await sleep(300);
  w.eval(`settingsModal('users')`); await sleep(400);
  click(w, d.querySelector('[data-acc="user-new"]')); await sleep(200);
  let um = [...d.querySelectorAll('.modal')].pop();
  um.querySelector('#u-user').value = 'dave'; um.querySelector('#u-pw').value = 'password123';
  click(w, um.querySelector('[data-m="save"]')); await sleep(900);
  ask = d.querySelector('.modal.collabask');
  check(!!ask, 'prompt shown again on a fresh install');
  click(w, ask.querySelector('[data-m="no"]')); await sleep(400);
  st = await api(jar, 'GET', '/api/state');
  check(st.collab_all === false && !d.querySelector('.modal.collabask'), '"Not now": stays off');
  w.close();

  // ---- 3: preset "Projects & team" (everything)
  fresh();
  jar = {}; w = await open(jar); d = w.document;
  await step1(w);
  click(w, d.querySelector('[data-su-preset="team"]')); await sleep(100);
  check([...d.querySelectorAll('[data-use]')].every(c => c.checked) && d.querySelector('[data-su-preset="team"]').classList.contains('on') && !d.querySelector('[data-su-preset="solo"]').classList.contains('on'), 'Projects & team: all ticked');
  click(w, d.querySelector('[data-su="go"]')); await sleep(800);
  st = await api(jar, 'GET', '/api/state');
  check(st.collab_all === true && st.time_all === true && ['collab', 'time', 'habits', 'kanban', 'timeline', 'deps', 'fields', 'progress'].every(f => feats(st).includes(f)), 'Projects & team: switches + modules on');
  w.close();

  // ---- 3b: preset "Simple list": lists, subtasks, reminders, calendar; everything else off
  fresh();
  jar = {}; w = await open(jar); d = w.document;
  await step1(w);
  click(w, d.querySelector('[data-su-preset="simple"]')); await sleep(100);
  check(d.querySelector('[data-use="cal"]').checked && ['timeline', 'kanban', 'matrix', 'habits', 'pomo', 'stats', 'progress', 'deps', 'fields', 'collab', 'time'].every(k => !d.querySelector(`[data-use="${k}"]`).checked), 'Simple list: only the calendar ticked');
  check(d.querySelector('[data-su-preset="simple"]').classList.contains('on') && d.querySelector('[data-su-preset="simple"] .i'), 'Simple list highlighted (with its icon)');
  // fine-tuning back to a preset highlights it again
  const hb = d.querySelector('[data-use="habits"]'); hb.checked = true; hb.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(!d.querySelector('.supreset.on'), 'one extra module: no preset matches');
  hb.checked = false; hb.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(d.querySelector('[data-su-preset="simple"]').classList.contains('on'), 'back to the preset: highlighted again');
  click(w, d.querySelector('[data-su="go"]')); await sleep(800);
  st = await api(jar, 'GET', '/api/state');
  check(st.collab_all === false && st.time_all === false && feats(st).includes('cal') && !['timeline', 'kanban', 'matrix', 'habits', 'pomo', 'stats', 'progress', 'deps', 'fields'].some(f => feats(st).includes(f)), `Simple list: only the calendar on: ${feats(st)}`);
  w.close();
  w = await open(jar); d = w.document; await sleep(300);
  check(!d.querySelector('[data-act="view-timeline"]') && !d.querySelector('#side [data-go="habits"]'), 'Simple list: no timeline / habits in the app');
  check(!w.eval('tourSteps()').some(x => x.id === 'news') && !/habits/.test(w.eval('tourSteps()').map(x => x.d).join(' ')), 'tour: no steps for modules that are off');
  w.close();

  // ---- 4: fine-tuning + language: German, Just me + time tracking, without habits and matrix
  fresh();
  jar = {}; w = await open(jar); d = w.document;
  await step1(w);
  click(w, d.querySelector('[data-su-lang="de"]')); await sleep(600);
  check(/Was möchtest du nutzen\?/.test(d.querySelector('.setupcard').textContent) && /Für mich/.test(d.querySelector('.setupcard').textContent) && /Womit starten\?/.test(d.querySelector('.setupcard').textContent), 'language switch: step 2 in German');
  click(w, d.querySelector('[data-su-preset="solo"]')); await sleep(100);
  for (const k of ['time', 'habits', 'matrix']) { const c = d.querySelector(`[data-use="${k}"]`); c.checked = !c.checked; c.dispatchEvent(new w.Event('change', {bubbles: true})); }
  check(!d.querySelector('.supreset.on'), 'custom choice: no preset highlighted');
  click(w, d.querySelector('[data-su="go"]')); await sleep(800);
  st = await api(jar, 'GET', '/api/state');
  check(st.collab_all === false && st.time_all === true, 'fine-tuned: collab off, time on');
  check(!feats(st).includes('habits') && !feats(st).includes('matrix') && feats(st).includes('cal'), 'fine-tuned: habits + matrix off for the admin');
  check(st.settings.lang === 'de', 'language saved');
  const nu = await api(jar, 'POST', '/api/users', {username: 'erin', password: 'password123'});
  const ej = {}; await fetch(B + 'api/auth/login', {method: 'POST', headers: H, body: JSON.stringify({username: 'erin', password: 'password123'})}).then(r => { ej.c = r.headers.get('set-cookie').split(';')[0]; });
  const est = await api(ej, 'GET', '/api/state');
  check(nu.id && !feats(est).includes('habits') && feats(est).includes('time') && feats(est).includes('collab') && est.settings.lang === 'de', 'new users get the chosen modules + language');
  // later: the admin turns habits back on for themselves in Settings
  await api(jar, 'PATCH', '/api/settings', {features: [...feats(st), 'habits'].join(',')});
  check(feats(await api(jar, 'GET', '/api/state')).includes('habits'), 'later: modules can be switched on again');
  w.close();

  // ---- 5: 1.5: no "Skip"; the single modules sit under "Customize…"; "Projects & team" = everything on
  fresh();
  jar = {}; w = await open(jar); d = w.document;
  await step1(w);
  check(!d.querySelector('[data-su="skip"]') && d.querySelector('details.sucust') && !d.querySelector('details.sucust').open && d.querySelector('details.sucust [data-use="habits"]'), 'no Skip; modules folded under Customize…');
  check(/\d+ of \d+ modules on/.test(d.querySelector('details.sucust summary').textContent), 'Customize… shows how many are on');
  click(w, d.querySelector('[data-su-preset="team"]')); await sleep(100);
  click(w, d.querySelector('[data-su="go"]')); await sleep(600);
  st = await api(jar, 'GET', '/api/state');
  check(st.collab_all === true && st.time_all === true && feats(st).length >= 11, 'Projects & team: everything on');
  w.close();
  // existing installs never see step 2: a normal login shows the login form, not the setup
  w = await open({}); d = w.document;
  check(d.querySelector('.authscreen #auth-form') && !d.querySelector('#au-name') && !d.querySelector('.setupcard'), 'existing install: login only, no setup step');
  w.close();
  // 1.8.1: the sign-in / setup screens are centered on every width (tablets in portrait got a bottom sheet under 900 px)
  // and opaque in every theme; a tour card without a target sits in the middle of the screen
  const css = await (await fetch(B + 'static/app.css')).text();
  const rule = (css.match(/\.modal\.authscreen,:root\[data-theme\] \.modal\.authscreen\{([^}]*)\}/) || [])[1] || '';
  check(/align-items:center/.test(rule) && /background:var\(--bg\)/.test(rule), 'CSS: auth screen centered + opaque, after the phone bottom-sheet rule: ' + rule);
  check(css.lastIndexOf('.modal{align-items:end') < css.indexOf('.modal.authscreen,'), 'CSS: the centering rule comes after the bottom-sheet rule');
  check(/\.modal\.authscreen>\.card\{border-radius:var\(--r-l\)\}/.test(css), 'CSS: rounded on all corners');
  w = await open({}); d = w.document;
  const tp = w.eval('tourPlace(null, 800, 1000)');
  check(tp.ring === '' && /top:50%/.test(tp.card) && /translate\(-50%,-50%\)/.test(tp.card), 'tour card without a target: centered: ' + tp.card);
  const tp2 = w.eval('tourPlace({left: 10, top: 10, right: 50, bottom: 50, width: 40, height: 40}, 800, 1000)');
  check(tp2.ring && !/top:50%/.test(tp2.card), 'tour card with a target: next to it');
  w.close();

  if (errs.length) console.log('JS ERRORS', [...new Set(errs)]);
  console.log(`\n${ok} ok, ${F.length} failed`);
  process.exit(F.length || errs.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
