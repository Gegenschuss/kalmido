// 2.65.0 part B (#1823, #1824): more areas load on demand (static/js/lazyload.js), their styles with them (static/css/). Own
// container (start.sh).
// - layout: no script tag for the new modules (agentchat, pdf, mindmap, wiki, stats, calendar, docs, life, integrations, playbook,
//   timeline), sw.js precaches their files
//   (LAZY = LD_MODS) and their stylesheets (LAZY_CSS = LD_CSS = static/css/*.css); the start parts (chatbase.js) load at start;
//   the start is smaller than 2.56.3 (scripts with a tag + app.css + i18n.js)
// - jsdom (boot lazy: true): a cold start loads no module and no module stylesheet, no script error; the no-op stand-ins answer
//   without loading; every module opens through its normal way in (route, the settings dialog, a preview link) and brings its
//   stylesheet (parsed, a rule of it applies); modules a module needs come first (settings -> agentchat + calendar, wiki -> mindmap)
// - Firefox (real browser, skipped without firefox): the start fetches none of the new modules / stylesheets, the documents view
//   gets its style, the service worker's cache holds every LAZY and LAZY_CSS file
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p265_b_ui', check: (c, w) => check(c, w), shots: 'P265B_SHOTS', lazy: true});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P265B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const t = await r.text(); let j; try { j = JSON.parse(t); } catch { j = t; } return j; };
const until = async (fn, n = 50) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(100); } return fn(); };
const get = async u => (await fetch(B + u)).text();
// 2.94.1 (#1929): apptbook.js (booking settings) loads with the calendar module
// 2.156.0 (#2071): listcal.js (a list's calendar view) too; 2.164.0 (#2625): calgest.js (swipe / pinch)
const NEW = {agentchat: ['agentchat', 'agentsetup'], pdf: ['pdfview', 'docpreview'],  // 2.92.0 (#1926): the Word / Excel preview
  // 2.155.0 C (#2078): calendar + calyear (the year view)
  mindmap: ['mindmap'], wiki: ['wiki'], stats: ['stats'], calendar: ['calview', 'caldrag', 'apptbook', 'calyear', 'listcal', 'calgest'], docs: ['docs', 'paperless', 'receipts', 'letterdoc', 'letteragent', 'docsplit', 'docscan'],  // 2.153.0 (#2028, #2031): letter modules load with the documents
  life: ['life'], integrations: ['integrations'], playbook: ['playbook'], timeline: ['timeline', 'roadmap'],
  polls: ['polls'], formq: ['formq']};  // 2.102.0 C (#2208): scheduling polls and questionnaires load on demand

(async () => {
  // ================= layout (no browser)
  const html = await get(''), sw = await get('sw.js'), ld = await get('static/js/lazyload.js');
  // 2.149.0 (#2505): the served page adds ?v=<content hash>
  const tags = [...html.matchAll(/<script src="\/static\/js\/([\w-]+)\.js(?:\?v=\w+)?"(?: defer)?><\/script>/g)].map(m => m[1]);  // 2.191.0 B (#2505): defer
  const LAZY = [...(sw.match(/const LAZY = \[(.*?)\];/s) || [, ''])[1].matchAll(/'\/static\/js\/([\w-]+)\.js'/g)].map(m => m[1]);
  const LAZY_CSS = [...(sw.match(/const LAZY_CSS = \[(.*?)\];/s) || [, ''])[1].matchAll(/'\/static\/css\/([\w-]+)\.css'/g)].map(m => m[1]);
  const ldCss = [...(ld.match(/const LD_CSS = \{(.*?)\};/s) || [, ''])[1].replace(/\w+:/g, '').matchAll(/'([\w-]+)'/g)].map(m => m[1]);
  for (const [m, fs] of Object.entries(NEW)) check(new RegExp(`\\b${m}: \\[${fs.map(f => `'${f}'`).join(', ')}\\]`).test(ld) && fs.every(f => LAZY.includes(f) && !tags.includes(f)), `module ${m}: ${fs.join(', ')} in LD_MODS + LAZY, no script tag`);
  check(['chatbase', 'calendar', 'templates', 'calevents', 'lazyload'].every(f => tags.includes(f)) && tags.indexOf('lazyload') === tags.indexOf('core') + 1, 'start parts load at start (chatbase.js, calendar.js, templates.js, calevents.js)');
  check(LAZY_CSS.length >= 10 && JSON.stringify(LAZY_CSS) === JSON.stringify(ldCss), 'sw.js LAZY_CSS = the stylesheets of LD_CSS: ' + LAZY_CSS.join(' '));
  const sheets = await Promise.all(LAZY_CSS.map(async f => { const r = await fetch(B + 'static/css/' + f + '.css'); return {f, ok: r.ok, n: (await r.text()).length}; }));
  check(sheets.every(s => s.ok && s.n > 500), 'every module stylesheet is served: ' + sheets.map(s => `${s.f} ${s.n}`).join(', '));
  const appCss = await get('static/app.css');
  check(!/^\.dc-view\{/m.test(appCss) && !/^\.wktree\{/m.test(appCss) && /^\.dc-view\{/m.test(await get('static/css/docs.css')), 'area rules moved out of app.css (documents, knowledge pages)');
  // the start: scripts with a tag + app.css + i18n.js (the budget of tools/perf_budget.py measures the same)
  const sizes = await Promise.all(tags.map(async f => (await get('static/js/' + f + '.js')).length));
  const start = sizes.reduce((a, b) => a + b, 0) + appCss.length + (await get('static/i18n.js')).length;
  console.log(`start: ${tags.length} scripts, ${start} characters (scripts + app.css + i18n.js), app.css ${appCss.length}`);
  // vorint G4 (17.10.2026): the parked releases 2.57-2.76 add start scripts; the limit stays below 2.56.3 (see tools/perf_budget.json)
  // 2.141.0 (#2140 #2141): + the HTML view / mailbox styles on top of 2.140.0 -- 4.05 MB / 634.2 KB on purpose
  // 2.143.0 (#2153 #2155): + the outbox / install hint / appearance sync at start on top of 2.142.0 -- 4.08 MB on purpose
  // 2.145.0 (#2437 #2438 #2444 #2432): sidebar mark, workspace head, news hint, print head styles on top of 2.144.2 -- 4.10 MB / 640.5 KB on purpose = tools/perf_budget.json start_css_bytes (measured 4089619 / 637192)
  // 2.156.0 (#2069 #1948 #1949 #2186 #2073): field kinds, mind map, sidebar view hooks on top of 2.147.1 -- 4.16 MB / 645.4 KB on purpose = tools/perf_budget.json start_css_bytes (measured about 4134000 / 641970)
  // 2.154.0 (#1111 #1960 #2192 #1876): hooks of stack split / task documents, Peppol and data protection sheets at start -- 4.12 MB on purpose (measured 4113574 / 639319)
  // 2.153.0 (#1962 #2179): job chat link / progress lines and the agent rules on custom fields + the job chat -- 4.12 MB on purpose (measured 4110616)
  // 2.144.6 A (#2053): billable / billed in the time rows and the invoice-from-time dialog (time.js, office_docs.js at start) -- 4.11 MB on purpose (measured 4103574 / 638107); 4.12 MB on top of main 2.147.1 (measured 4110402 / 639038)
  // 2.149.0 F (#2519): app.css 642 KB (base 2.146 already measured 637959 bytes; + the 5 defined variables); start 4.15 MB from the 2.147.1 CI fix
  // bundle C (2.155 calendar rules / absences, 2.156 field kinds / views in app.css on top of bundles A + B): app.css 646 KB on purpose (measured 644733)
  // 2.161.2 (#2607 #2608 #2609-#2611): + the brand on top and the bot figure's motion: app.css 650 KB on purpose (measured 648114)
  // 2.152.3 (#2619 #2620 #2621): + the head bar, workspace menu, panel head and panel folder trees: app.css 662 KB on purpose like tools/perf_budget.json start_css_bytes (measured 658623)
  // 2.165.0 CI (#2612-#2614): + the greeting, startle and pull-to-refresh bot styles: app.css 653 KB on purpose like tools/perf_budget.json start_css_bytes (measured 650078)
  check(start < 4150000 && appCss.length < 662000, `the start stays in its budget (4.15 MB, app.css 662 KB): ${start}, app.css ${appCss.length}`);  // 2.147.1 CI (2.144.1-2.147.1 on top of 2.144.0: e-invoice view, duplicates, budget import, country switch, chat references): 4.15 MB on purpose (measured 4108208; tools/perf_budget.json stays green); 2.140.0 (#2131-#2136 family / journal / habits code and styles at start): 4.04 MB / 632.2 KB on purpose = tools/perf_budget.json start_css_bytes (measured 4019311 / 628876); 2.139.0 (#2127 #2128 #2129 thread pane, read receipts, voice styles): 3.99 MB / 626.9 KB on purpose = tools/perf_budget.json start_css_bytes; 2.138.1 (job #692, parked releases 2.111-2.116 on top of 2.138.0): 3.97 MB / 618.8 KB on purpose; 2.138.2 (#2392 #2389 #2405, sidebar head / stripe / news styles): app.css 622.3 KB like tools/perf_budget.json = tools/perf_budget.json start_css_bytes; 2.138.0 (#2060 swimlanes.js at start, #2234 #2161 styles): 3.91 MB / 614.1 KB  // 2.97.0 (#1950 #1951): 3.76 MB (was 3.75 MB); 2.98.0 (#1953 #1954): 3.81 MB on purpose (polls.js, formq.js at start; follow-up: load them on demand); 2.114.1 CI: app.css 603 KB as tools/perf_budget.json start_css_bytes (2.136.0 #2193 bot figure states, measured 600611); 2.124.2 CI: on purpose 3.89 MB / app.css 610.3 KB like tools/perf_budget.json after 2.123-2.125 (measured 3844417 / 607056)

  // ================= jsdom: the app
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const st0 = await call('GET', '/api/state');
  const feats = (st0.settings.features || '').split(',').filter(Boolean);
  await call('PATCH', '/api/settings', {features: [...new Set([...feats, 'cal', 'stats', 'wiki', 'docs', 'agents', 'events', 'timeline', 'contracts'])].join(',')});
  const LID = (st0.lists || []).find(l => !l.archived)?.id || (await call('POST', '/api/lists', {name: 'Lazy'})).id;
  const TID = (await call('POST', '/api/tasks', {list_id: LID, title: 'Lazy task'})).id;
  check(LID > 0 && TID > 0, 'setup: a list and a task');

  const ready = w => until(() => { try { return w.eval('!!(S.me && S.lists && S.lists.length)'); } catch { return false; } }, 100);
  const e0 = errs.length;
  let w = await boot({user: 'alice', lazy: true}), d = w.document;
  await ready(w);
  const lazyTags = () => [...d.querySelectorAll('script[src*="/static/js/"]')].map(s => (s.getAttribute('src').match(/\/static\/js\/([\w-]+)\.js/) || [])[1]).filter(f => LAZY.includes(f));
  const cssOn = m => { const l = d.querySelector(`link[data-ldcss="${m}"]`); return !!l && !!l.sheet && l.sheet.cssRules.length > 3; };
  const why = () => ` [modules ${lazyTags().join(' ')}; sheets ${[...d.querySelectorAll('link[data-ldcss]')].map(l => l.dataset.ldcss + ':' + (l.sheet ? l.sheet.cssRules.length : 'none')).join(' ')}; view ${(d.querySelector('#view')?.textContent || '').trim().slice(0, 60)}]`;
  check(lazyTags().length === 0 && !d.querySelector('link[data-ldcss]'), 'cold start: no module, no module stylesheet loaded');
  check(w.eval('typeof isRoadmap') === 'function' && w.eval('typeof tlReaches') === 'function' && w.eval('typeof lifeOn') === 'function' && w.eval('typeof pbMenuItem') === 'function' && w.eval('typeof API_DOCS') === 'string' && w.eval('typeof fmtMoney') === 'function', 'start parts of timeline, life, playbook, integrations there');
  check(w.eval('typeof chatFull') === 'function' && w.eval('typeof rxRow') === 'function' && w.eval('typeof patchKids') === 'function' && w.eval('typeof pv_attr') === 'function' && w.eval('typeof calReq') === 'function' && w.eval('typeof barChart') === 'function', 'start parts there: chatbase.js, pv_attr, calReq, the charts');
  check(w.eval(`[chatPatch(), chatFit(), chatTypers(null), stepsChanged()].join('')`) === '' && lazyTags().length === 0, 'no-op stand-ins answer without loading the chat');
  check(w.eval(`FEATS.some(f => f[0] === 'docs')`) && w.eval(`typeof dc_shareOk`) === 'function', 'the documents module switch is there before docs.js');
  // the task panel draws without wiki.js ("Mentioned in" loads it in the background)
  w.location.hash = '#t/' + TID; await until(() => d.querySelector('#detail .dtitle, #detail [data-act="ct-link"]'));
  check(!!d.querySelector('#detail'), 'task panel opens');
  await until(() => lazyTags().includes('wiki'));
  check(lazyTags().includes('wiki') && lazyTags().includes('mindmap') && lazyTags().indexOf('mindmap') < lazyTags().indexOf('wiki'), 'wiki on: the task panel loads wiki.js in the background, mindmap.js first');
  w.location.hash = '#today';
  // statistics
  w.eval(`go('stats')`);
  await until(() => lazyTags().includes('stats') && cssOn('stats') && d.querySelector('#view .stats, #view .empty') && !/Loading…/.test(d.querySelector('#view').textContent || ''), 80);
  check(lazyTags().includes('stats') && cssOn('stats') && !!d.querySelector('#view .stats'), 'statistics: stats.js + stats.css loaded, the view drawn' + why());
  // calendar
  w.eval(`go('cal')`);
  await until(() => lazyTags().includes('calview') && d.querySelector('#view .calbar'), 80);
  check(['calview', 'caldrag'].every(f => lazyTags().includes(f)) && cssOn('calendar') && !!d.querySelector('#view .calbar'), 'calendar: calview.js + caldrag.js + calendar.css, the month drawn' + why());
  w.eval(`S.calMode = 'week'; renderView()`); await sleep(100);
  const wt = d.querySelector('#view .wtime');
  check(!!wt && w.getComputedStyle(wt).position === 'absolute', 'calendar week: a rule of calendar.css applies (.wtime absolute)');
  // documents
  w.eval(`go('docs')`);
  await until(() => lazyTags().includes('docs') && d.querySelector('#view .dc-view'), 80);
  check(['docs', 'paperless', 'receipts'].every(f => lazyTags().includes(f)) && cssOn('docs') && w.getComputedStyle(d.querySelector('#view .dc-view')).position === 'relative', 'documents: docs.js + paperless.js + receipts.js + docs.css, style applies' + why());
  // knowledge pages (already loaded by the task panel): the view
  w.eval(`go('wiki')`);
  await until(() => d.querySelector('#view .wkspace, #view .wkside, #view .wk-view') || !/Loading…/.test(d.querySelector('#view').textContent || ''), 80);
  check(cssOn('wiki') && cssOn('mindmap') && !/^\s*Loading…\s*$/.test(d.querySelector('#view').textContent || ''), 'knowledge pages: wiki.css + mindmap.css, the view drawn' + why());
  // timeline / roadmap: the command bar's "Timeline" (rmSet loads the module, then shows the roadmap)
  w.eval(`rmSet({v: 'timeline'}, 'none'); go('all')`);
  await until(() => lazyTags().includes('roadmap') && d.querySelector('#view #tlscroll, #view .rm-empty'), 80);
  check(['timeline', 'roadmap'].every(f => lazyTags().includes(f)) && cssOn('timeline') && !!d.querySelector('#view #tlscroll, #view .rm-empty') && w.eval('isRoadmap()'), 'timeline: timeline.js + roadmap.js + timeline.css, the roadmap drawn' + why());
  w.eval(`rmSet({v: 'list'}, 'none')`);
  // home & life
  w.eval(`go('life')`);
  await until(() => w.eval('S.route.mod') === 'life' && d.querySelector('#view .lcard, #view .dcard'), 80);
  check(lazyTags().includes('life') && cssOn('life') && !!d.querySelector('#view .lcard, #view .dcard'), 'home & life: life.js + life.css, the view drawn' + why());
  // PDF preview: a preview link drawn at start, the click loads pdfview.js
  const a = d.createElement('a'); a.href = '/static/x.pdf'; a.setAttribute('data-pview', JSON.stringify({url: '/static/x.pdf', name: 'x.pdf'})); a.textContent = 'x'; d.body.appendChild(a);
  a.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, button: 0}));
  await until(() => lazyTags().includes('pdfview') && d.querySelector('.lightbox'), 60);
  check(lazyTags().includes('pdfview') && cssOn('pdf') && !!d.querySelector('.lightbox') && !/loadModule/.test(w.eval('String(pdfView)')), 'a preview link loads pdfview.js + pdf.css and opens the preview' + why());
  d.querySelector('.lightbox')?.remove(); a.remove();
  // settings: needs the agent chat (its panes) and the calendar (Integrations > Calendars) first
  await w.eval(`settingsModal('look')`);
  await until(() => d.querySelector('.smodal'));
  check(['agentchat', 'agentsetup', 'integrations', 'playbook', 'settings'].every(f => lazyTags().includes(f)) && lazyTags().indexOf('integrations') < lazyTags().indexOf('agentchat') && lazyTags().indexOf('agentchat') < lazyTags().indexOf('settings') && cssOn('agentchat') && cssOn('settings'), 'settings: integrations.js, agentchat.js + agentsetup.js, playbook.js before settings.js, with their stylesheets' + why());
  check(!/loadModule/.test(w.eval('String(chatOpen)')) && w.eval('chatPatch.name') === 'chatPatch', 'after loading: the real chatOpen / chatPatch replace the stand-ins');
  d.querySelector('.smodal')?.remove();
  const own = errs.slice(e0).filter(e => !/pdf\.min\.mjs|dynamic import|import\(\)|Could not parse CSS/i.test(e));
  check(!own.length, 'no script errors: ' + own.join(' | '));
  w.close();

  // cold start straight into the calendar: it loads at once (no empty view)
  w = await boot({user: 'alice', lazy: true, hash: 'cal'}); d = w.document; await ready(w);
  await until(() => d.querySelector('#view .calbar'), 80);
  check(!!d.querySelector('#view .calbar') && cssOn('calendar') && !['stats', 'pdfview'].some(f => lazyTags().includes(f)), 'cold start #cal: the calendar, not the other new modules' + why());
  w.close();

  // ================= Firefox: real browser + service worker
  await firefox(async ({ev, nav, cmd, ctx, shot}) => {
    await nav(B + 'static/icon.svg');
    await ev('(() => { localStorage.clear(); return 1; })()');
    check(await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.ok)`), 'Firefox: login');
    await nav(B);
    for (let i = 0; i < 40 && !(await ev('!!(window.S && S.me)').catch(() => false)); i++) await sleep(250);
    // the idle preload (5 s after the start) may fetch settings + what it needs: only what started before counts
    const fetched = await ev(`JSON.stringify(performance.getEntriesByType('resource').filter(e => /\\/static\\/(js\\/(${LAZY.join('|')})\\.js|css\\/)/.test(e.name) && e.startTime < 4500).map(e => e.name.replace(/^.*\\/static\\//, '')))`);
    check(fetched === '[]', 'Firefox: the start fetches no module and no module stylesheet ' + fetched);
    await nav(B + '#docs');
    for (let i = 0; i < 60 && !(await ev('!!document.querySelector("#view .dc-view")').catch(() => false)); i++) await sleep(150);
    check(await ev(`(() => { const v = document.querySelector('#view .dc-view'); return !!v && getComputedStyle(v).maxWidth !== 'none'; })()`), 'Firefox: the documents view is drawn with its style (docs.css)');
    const cached = await ev(`(async () => { const reg = await navigator.serviceWorker.ready; const want = ${JSON.stringify(LAZY.map(f => '/static/js/' + f + '.js').concat(LAZY_CSS.map(f => '/static/css/' + f + '.css')))};
      let c, miss = want; for (let i = 0; i < 60 && miss.length; i++) { const ks = (await caches.keys()).filter(k => k.startsWith('tasks-shell')); c = ks.length ? await caches.open(ks.pop()) : null;
        if (c) { const m = []; for (const u of want) if (!await c.match(u, {ignoreSearch: true})) m.push(u); miss = m; } if (miss.length) await new Promise(r => setTimeout(r, 250)); }
      return {sw: !!reg.active, miss}; })()`);
    check(cached.sw && !cached.miss.length, 'Firefox: the service worker cache holds every LAZY + LAZY_CSS file (offline) ' + JSON.stringify(cached));
    // start time and what the start fetched (a screenshot run of the UI test runner writes them next to the screenshots: perf-b.txt)
    if (process.env.P265B_SHOTS) {
      const res = [];
      for (const [vw, vh] of [[1440, 900], [390, 844]]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}}).catch(() => 0);
        for (let r = 0; r < 3; r++) {
          await nav(B + 'static/icon.svg');
          const t0 = Date.now(); await nav(B + '#all');
          for (let i = 0; i < 200 && !(await ev(`!!document.querySelector('#view .trow, #view .lempty, #view .empty')`).catch(() => false)); i++) await sleep(25);
          const ms = Date.now() - t0;
          const got = await ev(`JSON.stringify((() => { const r = performance.getEntriesByType('resource').filter(e => /\\/static\\/(js|css|app\\.css|i18n\\.js)/.test(e.name) && e.startTime < 3000); return {n: r.length, js: r.filter(e => /\\.js/.test(e.name)).length, bytes: r.reduce((a, e) => a + (e.decodedBodySize || 0), 0)}; })())`).catch(() => '{}');
          res.push(`${vw}px run ${r + 1}: start until the list shows ${ms} ms, fetched in the first 3 s: ${got}`);
        }
      }
      require('fs').writeFileSync(path.join(process.env.P265B_SHOTS, 'perf-b.txt'), res.join('\n') + '\n');
    }
    // screenshots of the areas whose styles moved (a screenshot run of the UI test runner), desktop and phone width
    if (process.env.P265B_SHOTS) for (const [vw, vh, tag] of [[1280, 800, 'desk'], [390, 844, 'phone']]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}}).catch(() => 0);
      for (const h of ['docs', 'cal', 'stats', 'wiki', 'life', 'agents']) {
        await nav(B + '#' + h);
        for (let i = 0; i < 30 && await ev(`/^\\s*Loading…\\s*$/.test(document.querySelector('#view')?.textContent || 'Loading…')`).catch(() => true); i++) await sleep(200);
        await sleep(600); await shot(`${tag}-${h}`);
      }
      await ev(`(document.querySelector('[data-act="settings"]')?.click(), 1)`).catch(() => 0);
      for (let i = 0; i < 30 && !(await ev('!!document.querySelector(".smodal")').catch(() => false)); i++) await sleep(200);
      await sleep(600); await shot(`${tag}-settings`);
      await ev(`(document.querySelectorAll('.smodal, .modal').forEach(m => m.remove()), 1)`).catch(() => 0);
    }
  }, false);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
