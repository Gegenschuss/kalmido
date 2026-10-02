// 2.12.0 (#436): the browser demo ("Try it without an account"). Builds it with tools/build_demo.py into tests/.demo, serves
// the folder from a local static server and opens it in jsdom (no container, no API): the app boots on the in-browser shim
// with the sample data in the browser's language, the demo bar is there, a task added through quick add survives a reload
// (localStorage), the main views render, a server feature shows the "not available" notice, the simulated agent waits for
// an approval, "Reset demo" brings the sample back, and the page never asks for anything but its own static files (the
// server log: no /api/, nothing outside the demo folder; window.fetch of the browser is never reached).
// usage: node demo_test.js          (needs python3 + jsdom)
const {JSDOM, VirtualConsole} = require('jsdom');
const http = require('http'), fs = require('fs'), path = require('path'), {execFileSync} = require('child_process');
const ROOT = path.join(__dirname, '..'), OUT = path.join(__dirname, '.demo');
const sleep = ms => new Promise(r => setTimeout(r, ms));
let ok = 0; const fails = [];
const check = (c, what) => { if (c) ok++; else { fails.push(what); console.log('FAIL:', what); } };

const build = execFileSync(process.env.PYTHON || 'python3', [path.join(ROOT, 'tools', 'build_demo.py'), OUT], {encoding: 'utf-8'});
check(/build_demo: .* languages: en de es fr it nl/.test(build), 'demo build: ' + build.trim());
const html = fs.readFileSync(path.join(OUT, 'index.html'), 'utf-8');
check(/connect-src 'none'/.test(html) && /<meta name="robots" content="noindex/.test(html), 'index.html: CSP connect-src none + noindex');
check(!/\/static\/|rel="manifest"|sw\.js/.test(html), 'index.html: relative paths, no manifest, no service worker');
const app = fs.readFileSync(path.join(OUT, 'static', 'app.js'), 'utf-8');
check(!/serviceWorker\.register\(/.test(app), 'app.js: no service worker registration');
check(!/googletagmanager|google-analytics|plausible|matomo|umami/i.test(html + app), 'no analytics');
check(fs.existsSync(path.join(OUT, '.htaccess')) && /connect-src 'none'/.test(fs.readFileSync(path.join(OUT, '.htaccess'), 'utf-8')), '.htaccess with the same CSP');

const TYPES = {'.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml', '.png': 'image/png', '.woff2': 'font/woff2'};
const hits = [];
const srv = http.createServer((req, res) => {
  const u = decodeURIComponent(req.url.split('?')[0]); hits.push(req.method + ' ' + u);
  const p = path.join(OUT, u.replace(/^\/demo\//, '/').replace(/\/$/, '/index.html'));
  if (!u.startsWith('/demo/') || !p.startsWith(OUT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, {'Content-Type': TYPES[path.extname(p)] || 'application/octet-stream'}); fs.createReadStream(p).pipe(res);
});

(async () => {
  await new Promise(r => srv.listen(0, '127.0.0.1', r));
  const B = `http://127.0.0.1:${srv.address().port}/demo/`;
  const store = {}, errs = [];
  const open = async (lang = 'de-DE', wait = 2500, width = 1280) => {
    const vc = new VirtualConsole();
    vc.on('jsdomError', e => { if (!/navigation|Not implemented|Could not load (img|link)/.test(e.message)) errs.push(e.message); });
    vc.on('error', e => errs.push(String(e && e.stack || e)));
    const dom = await JSDOM.fromURL(B, {runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
      beforeParse(w) {
        w.matchMedia = q => ({matches: /max-width/.test(q) ? width < 700 : false, addEventListener() {}, addListener() {}});
        Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; },
          key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
        Object.defineProperty(w.navigator, 'languages', {configurable: true, value: [lang]});
        Object.defineProperty(w.navigator, 'language', {configurable: true, value: lang});
        w.__netFetch = 0;
        // the browser's own fetch must never be reached: the shim replaces it before the app runs
        w.fetch = () => { w.__netFetch++; return Promise.reject(new TypeError('network')); };
        w.XMLHttpRequest = function () { w.__netFetch++; throw new Error('XHR in the demo'); };
        w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
        w.confirm = () => true; w.prompt = () => null;
      }});
    await sleep(wait);
    return dom.window;
  };

  // 1. first visit (German browser): sample data in German, demo bar
  let w = await open('de-DE');
  let d = w.document;
  check(w.__netFetch === 0, `browser fetch never reached (${w.__netFetch})`);
  check(!!d.querySelector('#kd-bar') && /Demo – deine Daten bleiben in diesem Browser/.test(d.querySelector('#kd-bar').textContent), 'demo bar in German');
  check(/Demo zurücksetzen/.test(d.querySelector('#kd-reset')?.textContent || ''), 'reset button');
  const side = d.querySelector('#side')?.textContent || '';
  check(/Website-Relaunch für Café Aurora/.test(side) && /Privat/.test(side), 'sidebar: German sample project + personal list');
  check(w.eval('I18N.code') === 'de', 'app runs in German (' + w.eval('I18N.code') + ')');
  const nTasks = w.eval('S.tasks.size');
  check(nTasks > 20, `sample tasks loaded (${nTasks})`);
  // 2. add a task via quick add (German words), it is parsed and stored
  const qi = d.querySelector('#qinput');
  check(!!qi, 'quick add input');
  if (qi) { qi.value = 'Rauchtest Demo morgen 15 Uhr !!! #demo'; await w.eval(`submitQuick(document.querySelector('#qinput'))`); await sleep(800); }
  const added = w.eval(`JSON.stringify([...S.tasks.values()].find(t => t.title === 'Rauchtest Demo') || null)`);
  const at = JSON.parse(added);
  check(at && at.priority === 5 && at.due_time === '15:00' && at.tags.includes('demo'), 'quick add: task stored with time, priority, tag: ' + added);
  // 3. views render without errors
  for (const h of ['today', 'week', 'cal', 'matrix', 'time', 'agents', 'habits']) {
    w.location.hash = h; await sleep(500);
    check((d.querySelector('#view')?.innerHTML || '').length > 50, `view ${h} renders`);
  }
  const pid = w.eval(`S.lists.find(l => l.kind === 'project').id`);
  for (const v of ['kanban', 'timeline', 'list']) {
    w.location.hash = 'l/' + pid; await sleep(300);
    await w.eval(`api('PATCH', '/api/lists/${pid}', {view: '${v}'}).then(load).then(render)`); await sleep(500);
    check((d.querySelector('#view')?.innerHTML || '').length > 200, `project view ${v} renders`);
  }
  // 4. the simulated agent: one approval waiting, marked as simulated
  const ag = JSON.parse(w.eval('JSON.stringify(S.agents)'));
  check(ag.length === 1 && /simuliert/.test(ag[0].name) && ag[0].waiting === 1, 'simulated agent with one waiting job: ' + JSON.stringify(ag.map(a => [a.name, a.waiting])));
  const jobs = JSON.parse(await w.eval(`api('GET', '/api/agents/jobs?state=open').then(j => JSON.stringify(j.jobs))`));
  check(jobs.length === 1 && jobs[0].state === 'waiting' && jobs[0].can_act, 'agent job waiting for approval');
  await w.eval(`api('POST', '/api/agents/jobs/${jobs[0].id}/action', {action: 'approve'})`);
  const after = JSON.parse(await w.eval(`api('GET', '/api/agents/jobs').then(j => JSON.stringify(j.jobs))`));
  check(after[0].state === 'done', 'approve: job done');
  // 5. a server feature: calm notice with the install link, no request
  await w.eval(`api('POST', '/api/push/test', {}).catch(() => {})`); await sleep(100);
  const note = d.querySelector('#kd-note');
  check(!!note && /In der Demo nicht verfügbar/.test(note.textContent) && /installation\.html$/.test(note.querySelector('a').href), 'gated feature: notice + install link');
  // comments stay local
  const tid = at ? at.id : 1;
  await w.eval(`api('POST', '/api/tasks/${tid}/comments', {body: 'lokal'})`);
  const tl = JSON.parse(await w.eval(`api('GET', '/api/tasks/${tid}/timeline').then(j => JSON.stringify(j))`));
  check(tl.comments.length === 1 && tl.comments[0].body === 'lokal', 'comment stored locally');
  // time tracking
  await w.eval(`api('POST', '/api/time/start', {task_id: ${tid}})`);
  check(!!JSON.parse(await w.eval(`api('GET', '/api/state').then(j => JSON.stringify(j.timer))`)), 'timer runs');
  await w.eval(`api('POST', '/api/time/stop', {})`);
  w.close();

  // 6. reload: the task is still there (same browser storage)
  w = await open('de-DE'); d = w.document;
  check(w.eval(`[...S.tasks.values()].some(t => t.title === 'Rauchtest Demo')`), 'after reload the added task is still there');
  // 7. reset: sample data back, the added task gone
  w.KDEMO.reset(); await sleep(300);
  w.close();
  w = await open('de-DE'); d = w.document;
  check(!w.eval(`[...S.tasks.values()].some(t => t.title === 'Rauchtest Demo')`) && w.eval('S.tasks.size') === nTasks, 'reset: sample data back, own task gone');
  check(w.eval('S.agents[0].waiting') === 1, 'reset: agent waits again');
  w.close();

  // 8. another browser language on a fresh storage: French sample
  for (const k of Object.keys(store)) delete store[k];
  w = await open('fr-FR');
  check(/Refonte du site du Café Aurora/.test(w.document.querySelector('#side')?.textContent || '') && w.eval('I18N.code') === 'fr', 'French browser: French sample + UI');
  w.close();
  for (const k of Object.keys(store)) delete store[k];
  w = await open('pt-BR');
  check(/Website relaunch for Café Aurora/.test(w.document.querySelector('#side')?.textContent || '') && /your data stays in this browser/.test(w.document.querySelector('#kd-bar')?.textContent || ''), 'other browser language: English');
  w.close();

  // 9. real layout in Firefox (skipped without firefox): phone 390 px (touch) and desktop 1280 px, light and dark; the demo bar
  // fits, its buttons are 44 px on touch, no horizontal scrolling, the CSP blocks nothing, the app shows the sample.
  // DEMO_SHOTS=<dir> saves screenshots (README / website).
  const firefox = require('./ff')({tag: 'demo', check, shots: 'DEMO_SHOTS'});
  for (const [vw, vh, touch] of [[390, 844, true], [1280, 800, false]]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      for (const theme of ['light', 'dark']) {
        await nav(B); await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
        await nav(B); await sleep(2500);
        const pid = await ev(`String(S.lists.find(l => l.kind === 'project').id)`);
        await ev(`(() => { location.hash = '${vw < 600 ? 'today' : 'l/'}${vw < 600 ? '' : pid}'; return 1; })()`); await sleep(1200);
        const r = await ev(`JSON.stringify({n: S.tasks.size, bar: document.querySelector('#kd-bar').getBoundingClientRect().height, rows: document.querySelectorAll('#view .task, #view [data-id]').length,
          over: document.documentElement.scrollWidth - innerWidth, csp: KDEMO.csp, theme: document.documentElement.dataset.theme || '',
          btn: Math.min(...[...document.querySelectorAll('#kd-bar .kd-btn')].filter(b => b.offsetParent).map(b => b.getBoundingClientRect().height)),
          appH: Math.round(document.querySelector('#app').getBoundingClientRect().bottom), vh: innerHeight})`);
        const j = JSON.parse(r), tag = `Firefox ${vw}px ${theme}`;
        check(j.n > 20 && j.rows > 0, `${tag}: app with the sample (${j.n} tasks, ${j.rows} rows)`);
        check(!j.csp.length, `${tag}: nothing blocked by the CSP ${JSON.stringify(j.csp)}`);
        check(j.over <= 0, `${tag}: no horizontal scrolling (${j.over})`);
        check(j.bar >= 40 && j.bar <= 48 && j.appH <= j.vh + 1, `${tag}: demo bar ${j.bar}px, app fits below (${j.appH}/${j.vh})`);
        if (touch) check(j.btn >= 43.9, `${tag}: demo bar buttons 44 px on touch (${j.btn})`);
        await shot(`demo-${vw}-${theme}.png`);
      }
    }, touch);
  }

  // no network: only static files of the demo folder were requested
  const bad = hits.filter(h => h !== 'GET /favicon.ico' && !/^GET \/demo\/(index\.html|static\/[\w./-]+)?$/.test(h) || /\/api\//.test(h));
  check(!bad.length, 'only static demo files requested: ' + JSON.stringify(bad.slice(0, 5)));
  check(!hits.some(h => /\/api\//.test(h)), 'no /api/ request');
  check(!errs.length, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  srv.close();
  console.log(`demo: ${ok} ok, ${fails.length} failed`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
