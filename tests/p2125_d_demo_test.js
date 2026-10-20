// 2.125.0 D (#1653): the browser demo with ALL modules. Builds the demo (tools/build_demo.py) into tests/.demo-all, serves it
// from a local static server and opens it in jsdom (no container, no API): the first start is the one of a new account
// (intro with language, "What do you use Kalmido for?" and the module choice, then the "Getting started" list and the
// tour); with every module switched on each module's start view (and every office page) opens without an exception and
// without a call the shim does not know; the server-only parts say so at the place; the page forbids the network (CSP),
// the data stays after a reload and "Reset demo" empties it. The build lists the client's API calls the shim does not
// know (a warning, no failure).
// usage: node p2125_d_demo_test.js          (needs python3 + jsdom)
const {JSDOM, VirtualConsole} = require('jsdom');
const http = require('http'), fs = require('fs'), path = require('path'), {execFileSync} = require('child_process');
const ROOT = path.join(__dirname, '..'), OUT = path.join(__dirname, '.demo-all');
const sleep = ms => new Promise(r => setTimeout(r, ms));
const PROBE = process.env.P2125D_PROBE === '1';  // prints every view's answers (inventory), checks nothing about them
let ok = 0; const fails = [];
const check = (c, what) => { if (c) ok++; else { fails.push(what); console.log('FAIL:', what); } };

const build = execFileSync(process.env.PYTHON || 'python3', [path.join(ROOT, 'tools', 'build_demo.py'), OUT], {encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe']});
check(/build_demo: /.test(build), 'demo build: ' + build.trim().split('\n').pop());
console.log(build.trim().split('\n').filter(l => /unknown|warn/i.test(l)).slice(0, 80).join('\n'));
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
  const store = {}, errs = [], warns = [];
  // an exception in a timer of the page reaches node: counted as an error of the page (the next view still gets looked at)
  process.on('uncaughtException', e => errs.push('uncaught: ' + String(e && e.stack || e).slice(0, 400)));
  const open = async (lang = 'de-DE', wait = 2500, width = 1280) => {
    const vc = new VirtualConsole();
    vc.on('jsdomError', e => { if (!/navigation|Not implemented|Could not load (img|link)/.test(e.message)) errs.push(e.message); });
    vc.on('error', e => errs.push(String(e && e.stack || e)));
    vc.on('warn', (...a) => warns.push(a.map(String).join(' ')));
    const dom = await JSDOM.fromURL(B, {runScripts: 'dangerously', resources: 'usable', pretendToBeVisual: true, virtualConsole: vc,
      beforeParse(w) {
        w.innerWidth = width;
        w.matchMedia = q => ({matches: /min-width:\s*(\d+)/.test(q) ? width >= +q.match(/min-width:\s*(\d+)/)[1] : false, addEventListener() {}, addListener() {}, removeEventListener() {}});
        Object.defineProperty(w, 'localStorage', {value: {getItem: k => k in store ? store[k] : null, setItem: (k, v) => { store[k] = String(v); }, removeItem: k => { delete store[k]; },
          key: i => Object.keys(store)[i], get length() { return Object.keys(store).length; }}});
        Object.defineProperty(w.navigator, 'languages', {configurable: true, value: [lang]});
        Object.defineProperty(w.navigator, 'language', {configurable: true, value: lang});
        w.__net = 0;
        w.fetch = () => { w.__net++; return Promise.reject(new TypeError('network')); };
        w.XMLHttpRequest = function () { w.__net++; throw new Error('XHR in the demo'); };
        w.WebSocket = function () { w.__net++; throw new Error('WebSocket in the demo'); };
        w.EventSource = function () { w.__net++; throw new Error('EventSource in the demo'); };
        w.navigator.sendBeacon = () => { w.__net++; return false; };
        w.print = () => {}; w.scrollTo = () => {}; w.Element.prototype.scrollIntoView = () => {};
        w.confirm = () => true; w.prompt = () => null;
        w.addEventListener('unhandledrejection', e => errs.push('unhandled: ' + String(e.reason && (e.reason.stack || e.reason))));
        w.addEventListener('error', e => errs.push('error: ' + String(e.error && e.error.stack || e.message)));
      }});
    await sleep(wait);
    return dom.window;
  };

  // 1. first start: the intro of a new account (language, purpose, modules, "Start with"), the app behind it inert
  let w = await open('de-DE'), d = w.document;
  const card = d.querySelector('.authscreen .setupcard');
  check(!!card && /Wofür nutzt du Kalmido/.test(card.textContent) && card.querySelectorAll('[data-su-preset]').length >= 5 && card.querySelectorAll('[data-su-lang]').length === 6,
    'intro: purpose, presets and the six languages: ' + (card ? card.textContent.slice(0, 160) : d.body.textContent.slice(0, 200)));
  check(d.querySelector('#app')?.hasAttribute('inert') && !d.querySelector('.tour'), 'intro: the app waits behind it, no tour yet');
  // every module: "Switch on all modules" + every box under "Customize…"
  const all = d.querySelector('#su-modsall');
  check(!!all, 'intro: switch "all modules"');
  if (all) { all.checked = true; all.dispatchEvent(new w.Event('change', {bubbles: true})); await sleep(200); }
  for (const c of d.querySelectorAll('.authscreen [data-use]')) if (!c.checked) { c.checked = true; c.dispatchEvent(new w.Event('change', {bubbles: true})); }
  d.querySelector('.authscreen [data-su="go"]')?.click(); await sleep(800);
  check(w.KDEMO.db().settings.setup === 'done', 'intro: Start stores the choice: ' + (d.querySelector('#su-err')?.textContent || '') + ' ' + JSON.stringify(w.KDEMO.calls.slice(-8)) + ' go:' + !!d.querySelector('.authscreen [data-su="go"]'));
  w.close();

  // 2. after the intro: "Getting started" + the tour, every module on
  w = await open('de-DE', 3000); d = w.document;
  const feats = w.eval(`S.settings.features`).split(',');
  const allFeats = w.eval(`JSON.stringify(FEATS.map(x => x[0]))`);
  const offF = JSON.parse(allFeats).filter(f => !feats.includes(f) && f !== 'family' && f !== 'docs');  // documents: not part of the intro (as on a server)
  check(!offF.length, 'all modules on after the intro (missing: ' + offF.join(', ') + ')');
  check(!d.querySelector('.authscreen'), 'intro gone after the start');
  check(/Erste Schritte/.test(d.querySelector('#side')?.textContent || ''), 'onboarding list "Erste Schritte"');
  check(!!d.querySelector('.tour .tcard'), 'tour after the intro');
  w.eval('tourEnd(true)'); await sleep(300);
  if (offF.length) { await w.eval(`api('POST', '/api/me/purpose', {purpose: 'office', all_modules: true}).then(load).then(render)`); await sleep(300); }  // the views below still get looked at
  // the documents (Settings > Modules, not in the intro)
  if (!w.eval(`feat('docs')`)) { await w.eval(`api('PATCH', '/api/settings', {features: S.settings.features + ',docs'}).then(load).then(render)`); await sleep(300); }
  // the sample on request, so that the views have something to show
  await w.eval(`api('POST', '/api/sample', {}).then(load).then(render)`); await sleep(500);

  // 3. every module's start view + every office page: no exception, no unknown call, no empty page
  const views = JSON.parse(w.eval(`JSON.stringify(['today', 'cal', 'matrix', 'habits', 'pomo', 'news', 'stats', 'time', 'overview', 'agents', 'team', 'notes', 'home', 'family',
    'contacts', 'life', 'budget', 'feeds', 'bookmarks', 'review', 'clients', 'workload', 'tags', 'office', 'wiki', 'sheets', 'ablage', 'docs'].filter(m => modOn(m) || m === 'today'))`));
  const offV = ['cal', 'matrix', 'habits', 'time', 'agents', 'contacts', 'life', 'budget', 'feeds', 'review', 'clients', 'workload', 'office', 'wiki', 'sheets', 'ablage', 'docs'].filter(m => !views.includes(m));
  check(!offV.length, 'module views switched on: missing ' + offV.join(', '));
  const visit = async (route, label) => {
    const m0 = w.KDEMO.miss.length, g0 = w.KDEMO.gated.length, e0 = errs.length, n0 = w.KDEMO.unknown.length;
    w.eval(`go(${JSON.stringify(route)})`); await sleep(1600);
    const txt = (d.querySelector('#view')?.textContent || '').replace(/\s+/g, ' ').trim();
    const r = {label, miss: w.KDEMO.miss.slice(m0), gated: w.KDEMO.gated.slice(g0), errs: errs.slice(e0).map(x => x.slice(0, 300)), unknown: w.KDEMO.unknown.slice(n0), txt: txt.slice(0, 140)};
    console.log('VIEW', JSON.stringify(r));
    if (!PROBE) {
      check(!r.errs.length, `${label}: no exception: ${r.errs.slice(0, 2).join(' | ')}`);
      check(!r.miss.length && !r.unknown.length, `${label}: every call known to the shim: ${JSON.stringify([...r.miss, ...r.unknown].slice(0, 6))}`);
      check(txt.length > 10, `${label}: the view shows something: ${txt.slice(0, 80)}`);
    }
    return r;
  };
  for (const v of views) await visit(v, v);
  // the office's pages (rail on a computer)
  const opages = JSON.parse(w.eval(`JSON.stringify(typeof ofm_all === 'function' ? ofm_all().filter(i => i.go.startsWith('office/') && (!i.on || i.on())).map(i => i.go) : [])`));
  check(opages.length >= 8, 'office pages: ' + opages.join(' '));
  for (const p of opages) await visit(p, p);
  // a project list in its views (list, kanban, timeline)
  const pid = w.eval(`S.lists.find(l => l.kind === 'project')?.id`);
  if (pid) for (const v of ['list', 'kanban', 'timeline']) { await w.eval(`api('PATCH', '/api/lists/${pid}', {view: '${v}'}).then(load)`); await visit('l/' + pid, 'project ' + v); }

  // 3b. the stand-ins work like the server for the common steps
  const J = async expr => JSON.parse(await w.eval(`(async () => JSON.stringify(await (${expr})))()`));
  // tables: a sheet with formulas, evaluated in the browser (German formats)
  const sh = await J(`api('POST', '/api/sheets', {title: 'Probe', space: 'private'})`);
  const col = sh.columns[1].id, rws = sh.rows.map(r => r.id);
  await J(`api('PATCH', '/api/sheets/${sh.id}/columns/${col}', {kind: 'number'})`);
  const put = await J(`api('PUT', '/api/sheets/${sh.id}/cells', {cells: [{row_id: ${rws[0]}, col_id: ${col}, raw: '4'}, {row_id: ${rws[1]}, col_id: ${col}, raw: '=B1*2.5'},
    {row_id: ${rws[2]}, col_id: ${col}, raw: '=SUMME(B1:B2)'}, {row_id: ${rws[3]}, col_id: ${col}, raw: '=B1/0'}, {row_id: ${rws[4]}, col_id: ${col}, raw: '=WENN(B1>3;"groß";"klein")'},
    {row_id: ${rws[5]}, col_id: ${col}, raw: '=SVERWEIS(1;B1:B2;1)'}, {row_id: ${rws[8]}, col_id: ${col}, raw: '=RUNDEN(1234,5678;2)'}, {row_id: ${rws[6]}, col_id: ${col}, raw: '=B8'}, {row_id: ${rws[7]}, col_id: ${col}, raw: '=B7'}]})`);
  const cv = a => put.cells.find(c => c.addr === a) || {};
  check(cv('B2').display === '10' && cv('B3').value === 14 && cv('B3').refs.length === 2, 'sheet: B1*2.5 = 10, SUMME(B1:B2) = 14: ' + JSON.stringify([cv('B2').display, cv('B3').display]));
  check(cv('B9').display === '1.234,57', 'sheet: decimal comma with ";" and the German number format: ' + cv('B9').display);
  check(cv('B4').error === 'div0' && cv('B5').value === 'groß' && !!cv('B6').error && cv('B7').error === 'cycle', 'sheet: division by zero, WENN, unknown function, cycle: ' + JSON.stringify([cv('B4').error, cv('B5').value, cv('B6').error_text, cv('B7').error]));
  await visit('sheets/' + sh.id, 'sheet open');
  // knowledge pages: links, backlinks, rename relinks
  const pa = await J(`api('POST', '/api/wiki/pages', {space: 'private', path: 'Abläufe/Start', body: 'Siehe [[Checkliste]]'})`);
  const pb = await J(`api('POST', '/api/wiki/pages', {space: 'private', path: 'Checkliste', body: '- [ ] eins'})`);
  const pb2 = await J(`api('GET', '/api/wiki/pages/${pb.id}')`);
  check(pb2.backlinks.some(x => x.id === pa.id), 'wiki: backlink of the linked page');
  const rn = await J(`api('PATCH', '/api/wiki/pages/${pb.id}', {path: 'Checkliste Dreh'})`);
  const pa2 = await J(`api('GET', '/api/wiki/pages/${pa.id}')`);
  check(rn.relinked === 1 && /\[\[Checkliste Dreh\]\]/.test(pa2.body), 'wiki: rename relinks: ' + pa2.body);
  await visit('wiki/' + pa.id, 'wiki page open');
  // file store: an upload stays in the browser (FormData through the fetch stand-in)
  const up = await w.eval(`(async () => { const fd = new FormData(); fd.append('file', new File(['hallo demo'], 'notiz.txt', {type: 'text/plain'})); fd.append('space', 'private');
    const r = await fetch('/api/files/upload', {method: 'POST', body: fd}); return JSON.stringify(await r.json()); })()`);
  const fl = await J(`api('GET', '/api/files?space=private')`);
  check(/notiz\.txt/.test(up) && fl.items.some(n => n.name === 'notiz.txt' && n.size === 10) && !!w.KDEMO.db().m.nodes.find(n => n.name === 'notiz.txt').data, 'files: upload kept with its content: ' + up.slice(0, 120));
  await visit('ablage', 'file store with a file');
  // own events in the calendar (module events), a weekly one expanded
  const td = w.eval('today()');
  await J(`api('POST', '/api/events', {title: 'Drehtag', all_day: false, start: '${td}T10:00', end: '${td}T12:00', cal_id: S.evcals[0].id, rrule: 'FREQ=WEEKLY'})`);
  const evs = await J(`api('GET', '/api/calendars/events?from=${td}&to=' + addDays('${td}', 20))`);
  check(evs.events.filter(e => e.own && e.title === 'Drehtag').length === 3 && evs.evcals[w.eval('S.evcals[0].id')], 'events: own weekly event, three times in three weeks: ' + evs.events.length);
  await visit('cal', 'calendar with an event');
  // contacts, budget, absences
  await J(`api('POST', '/api/contacts', {given: 'Erika', family: 'Muster', emails: [{value: 'erika@example.com', type: ['work']}]})`);
  const cts = await J(`api('GET', '/api/contacts?q=muster&limit=500')`);
  check(cts.total === 1 && cts.items[0].fn === 'Erika Muster' && cts.items[0].email === 'erika@example.com', 'contacts: created and found');
  const bl = await J(`api('POST', '/api/budget/lists', {})`);
  const m0 = new Date().toISOString().slice(0, 7);
  await J(`api('POST', '/api/budget/${bl.list_id}/entries', {day: '${m0}-02', amount: 52.3, kind: 'out', title: 'Einkauf', note: '', counterpart: '', cat_id: null})`);
  const bm = await J(`api('GET', '/api/budget/${bl.list_id}?month=${m0}')`);
  check(bm.totals.ist_out === 52.3 && bm.totals.saldo === -52.3 && bm.trend.length === 6, 'budget: entry in the month totals');
  await visit('budget', 'budget with an entry');
  await J(`api('POST', '/api/team/absences', {kind: 'vacation', start_date: '${m0}-10', end_date: '${m0}-11', half_day: '', note: ''})`);
  const ab = await J(`api('GET', '/api/team/absences?start=${m0}-01&end=${m0}-28')`);
  check(ab.items.length === 1 && ab.items[0].can_edit, 'absences: own vacation listed');
  // 2.125.0 (#2117 #2118 #2119): vacation account, working week and the monthly timesheet in the demo
  await J(`api('PUT', '/api/team/leave/quota', {user_id: 1, year: ${m0.slice(0, 4)}, days: 30, carry: 0})`);
  const lv = await J(`api('GET', '/api/team/leave?year=${m0.slice(0, 4)}')`);
  check(lv.people.length === 1 && lv.people[0].quota.days === 30 && lv.people[0].taken >= 0 && lv.people[0].taken <= 2 && lv.people[0].rest === 30 - lv.people[0].taken && !lv.approval, 'leave: account counts the vacation');
  const wt = await J(`api('PUT', '/api/team/leave/worktime/1', {workdays: [0, 1, 2, 3], hours: 32})`);
  check(wt.workdays.length === 4 && wt.capacity_h === 32, 'leave: working week saved');
  const ts0 = await J(`api('GET', '/api/time/sheets')`);
  check(ts0.sheet.state === 'open' && ts0.can.close, 'timesheet: month open');
  await J(`api('POST', '/api/time/sheets', {month: '${ts0.month}', action: 'close'})`);
  const ts2 = await J(`api('GET', '/api/time/sheets')`);
  check(ts2.sheet.state === 'closed' && ts2.can.reopen && ts2.locked.includes(ts0.month), 'timesheet: month closed');
  await visit('workload', 'workload after an absence');

  // 4. server-only features answer at the place (the notice), never silently
  const n0 = w.document.querySelectorAll('#kd-note').length;
  await w.eval(`api('POST', '/api/me/webhooks', {url: 'https://example.com/x'}).catch(() => 0)`); await sleep(200);
  check(!!w.document.querySelector('#kd-note') && n0 === 0, 'a server-only write shows the "not available in the demo" notice');
  w.document.querySelector('#kd-note button')?.click();
  // an unknown call: a visible message + console.warn, no crash
  const wn = warns.length;
  const unk = await w.eval(`api('GET', '/api/no-such-route-p2125d').then(j => JSON.stringify(j)).catch(e => 'err:' + e.message)`);
  check(warns.slice(wn).some(x => /no-such-route-p2125d/.test(x)) && w.KDEMO.unknown.includes('GET /api/no-such-route-p2125d'), 'unknown call: console.warn + listed: ' + unk + ' ' + warns.slice(wn).join('|').slice(0, 120));
  check(!!w.document.querySelector('#kd-note, .kd-unknown'), 'unknown call: a visible message');
  w.KDEMO.unknown.length = 0;

  // 5. nothing leaves the page: CSP connect-src 'none', no network of the browser, only the demo's own files served
  const csp = d.querySelector('meta[http-equiv="Content-Security-Policy"]')?.content || '';
  check(/connect-src 'none'/.test(csp) && /default-src 'none'/.test(csp), 'CSP forbids the network: ' + csp.slice(0, 80));
  check(w.__net === 0, `no fetch / XHR / WebSocket / sendBeacon of the browser (${w.__net})`);
  check(!w.KDEMO.csp.length, 'nothing blocked by the CSP');
  const bad = hits.filter(h => !/^GET \/demo\/(index\.html|static\/[\w./-]+)?$/.test(h) || /\/api\//.test(h));
  check(!bad.length, 'only the demo files requested: ' + bad.slice(0, 4).join(' '));

  // 6. a reload keeps the data (own task, a page, a time entry); "Reset demo" = a new account again (intro)
  await w.eval(`api('POST', '/api/tasks', {title: 'Probe p2125d', list_id: S.lists[0].id}).then(load)`);
  const nT = w.KDEMO.db().tasks.length;
  w.close();
  w = await open('de-DE', 2500); d = w.document;
  check(w.eval(`[...S.tasks.values()].some(t => t.title === 'Probe p2125d')`) && w.KDEMO.db().tasks.length === nT && !d.querySelector('.authscreen'), 'reload: data stays, no intro');
  w.KDEMO.reset(); await sleep(300); w.close();
  w = await open('de-DE', 2500); d = w.document;
  check(!w.KDEMO.db().tasks.length && !!d.querySelector('.authscreen .setupcard'), 'reset: empty, the intro again');
  w.close();

  if (!PROBE) check(!errs.length, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  srv.close();
  try { fs.rmSync(OUT, {recursive: true, force: true}); } catch { /* left for a look */ }
  console.log(`p2125_d_demo: ${ok} ok, ${fails.length} failed`);
  process.exit(fails.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
