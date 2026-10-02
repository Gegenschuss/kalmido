// 2.7.1 UI tests (#410), own container (start.sh). jsdom: the view switch of a project list gets "Project overview" (not in
// plain lists; phones: in "…"), the overview (German "Projektübersicht", never the "Where is it stuck?" view): description
// (Markdown rendered, edit + save, viewers read only), key links (add, order, icons from the address, never a fetch),
// milestones (add with the app's date picker, tick, also markers in the timeline), project files (upload, delete) and the
// task files read-only with their task, members (only with collaboration), status updates + "Set status", the time sum;
// leaving the overview keeps the list's own view; SW v75.
// Then Firefox headless (WebDriver BiDi, skipped without firefox), touch at 360 x 780 / 390 x 844, a mouse at 1280 x 800 /
// 1920 x 1080: the overview inside the viewport (no horizontal overflow), "…" + the bell in view, two columns on wide
// screens, touch targets >= 44 px on phones, the milestone marker in the timeline; screenshots with P271_SHOTS=<dir>.
const {spawn, execFileSync} = require('child_process');
const fs = require('fs'), os = require('os'), path = require('path');
const {boot, sleep, B, login, errs} = require('./boot');
const WS = globalThis.WebSocket || require('ws');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const ALL = 'cal,timeline,matrix,habits,pomo,kanban,paperless,collab,stats,time,progress,deps,fields,agents,comments';
const day = n => { const d = new Date(); d.setDate(d.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };

const firefox = require('./ff')({tag: 'p271_ui', check, shots: 'P271_SHOTS'});  // 2.7.2: the shared Firefox helper (with the start retry)
const HEAD = `(() => {
  const t = document.querySelector('#top'); if (!t || !t.querySelector('h1')) return {none: location.href};
  const vw = document.documentElement.clientWidth;
  const R = e => { if (!e || !e.offsetWidth) return null; const b = e.getBoundingClientRect(); return [b.left, b.right, b.top, b.bottom, b.width, b.height]; };
  const out = [...t.children].filter(e => e.offsetWidth && e.getBoundingClientRect().right > vw + 0.5).map(e => e.className || e.tagName);
  return {vw, more: R(t.querySelector('[data-act="top-more"]')), bell: R(t.querySelector('.bell')), out, ht: R(t.querySelector('h1 .ht'))};
})()`;
// every visible button / control in a container that is smaller than 44 x 44 px (touch), counting ::before / ::after zones
const SMALL = sel => `(() => [...document.querySelectorAll('${sel}')].filter(e => e.offsetWidth && getComputedStyle(e).visibility !== 'hidden').map(e => {
  const b = e.getBoundingClientRect(); let w = b.width, h = b.height;
  for (const ps of ['::before', '::after']) { const s = getComputedStyle(e, ps); if (s.content && s.content !== 'none' && s.position === 'absolute') { const iw = b.width - parseFloat(s.left || 0) - parseFloat(s.right || 0), ih = b.height - parseFloat(s.top || 0) - parseFloat(s.bottom || 0); if (Number.isFinite(iw)) w = Math.max(w, iw); if (Number.isFinite(ih)) h = Math.max(h, ih); } }
  return [e.className || e.tagName, (e.textContent || '').trim().slice(0, 16), Math.round(w), Math.round(h)]; }).filter(x => x[2] < 43.5 || x[3] < 43.5))()`;

(async () => {
  await sleep(600);
  const SW = await (await fetch(B + 'sw.js')).text();
  check(/const CACHE = 'tasks-shell-v(?:7[5-9]|8[0-9])'/.test(SW), 'service worker cache v75 (2.7.2: v76, 2.8.0: v77, 2.9.0: v78, 2.10.0: v79, 2.11.0: v80)');
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'});
  const BOB = (await call('POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123'})).id;
  const CKB = await login('bob');
  await call('PATCH', '/api/settings', {features: ALL, lang: 'en', tour: 'done'}, CKB);
  const P = (await call('POST', '/api/lists', {name: 'Website relaunch', kind: 'project'})).id;
  const PL = (await call('POST', '/api/lists', {name: 'Groceries'})).id;
  await call('PUT', `/api/lists/${P}/members`, {user_id: BOB, role: 'view'});
  const T1 = (await call('POST', '/api/tasks', {title: 'Wireframes', list_id: P, start: day(1), due: day(4)})).id;
  await call('POST', `/api/lists/${P}/status`, {status: 'at_risk', note: 'Copy is late'});
  await call('POST', `/api/lists/${P}/milestones`, {name: 'Beta', day: day(3)});
  {  // a task file (multipart, as the app sends it)
    const fd = new FormData(); fd.append('file', new Blob(['hello'], {type: 'text/plain'}), 'notes.txt');
    await fetch(B + `api/tasks/${T1}/attachments`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  }

  // ================= the view switch
  let w = await boot({user: 'alice', hash: 'l/' + P}), d = w.document;
  const seg = () => [...d.querySelectorAll('#top .vseg button')].map(b => b.dataset.act);
  check(seg().join() === 'view-list,view-kanban,view-timeline,view-overview', 'project: List / Kanban / Timeline / Project overview: ' + seg());
  check(d.querySelector('#top [data-act="view-overview"]').title === 'Project overview', 'tab title "Project overview"');
  w.eval(`go('l/${PL}')`); await sleep(300);
  check(!seg().includes('view-overview'), 'a plain list has no overview tab: ' + seg());
  w.eval(`go('l/${P}')`); await sleep(300);
  click(w, d.querySelector('#top [data-act="view-overview"]'));
  await until(() => d.querySelector('#view .pov .povs'));
  check(d.querySelector('#top [data-act="view-overview"]').classList.contains('on') && w.eval('isOverview()'), 'the overview is on');
  check(!d.querySelector('#view .trow') && !d.querySelector('#view #qinput'), 'no task rows / composer in the overview');
  check(w.eval('noFab()'), 'no "+" in the overview');
  check(JSON.parse(w.localStorage.getItem('tasks.pov') || '[]').includes(P), 'remembered on this device');
  check((await call('GET', '/api/lists')).status !== 0 && (await call('GET', '/api/state')).lists.find(l => l.id === P).view === 'list', 'the list\'s own view stays "list" on the server');
  const secs = [...d.querySelectorAll('#view .povs')].map(s => s.id);
  check(['pov-desc', 'pov-status', 'pov-ms', 'pov-files', 'pov-links', 'pov-people'].every(x => secs.includes(x)), 'sections: ' + secs);
  check(/Where is it stuck/.test(w.eval(`tr('Where is it stuck?')`)) && d.querySelector('#top h1 .ht').textContent === 'Website relaunch', 'title stays the list\'s name');
  // status
  check(/Copy is late/.test(d.querySelector('#pov-status').textContent) && d.querySelector('#pov-status [data-act="status"]'), 'status updates + "Set status"');
  // description
  click(w, d.querySelector('[data-pov="desc-edit"]')); await sleep(50);
  d.querySelector('#pov-desc').value = '## Goal\nNew **site** by June\n- [ ] item';
  click(w, d.querySelector('[data-pov="desc-save"]'));
  await until(() => d.querySelector('#pov-desc') === null && d.querySelector('.povmd b'));
  check(d.querySelector('.povmd h5')?.textContent === 'Goal' && d.querySelector('.povmd b')?.textContent === 'site', 'Markdown rendered');
  check(d.querySelector('.povmd input[type="checkbox"]')?.disabled, 'checkboxes in the description are read-only');
  check((await call('GET', `/api/lists/${P}/overview`)).description.startsWith('## Goal'), 'saved on the server');
  // key links
  click(w, d.querySelector('[data-pov="link-add"]')); await sleep(50);
  let md = d.querySelector('.modal.povmodal');
  md.querySelector('#pl-url').value = 'https://github.com/acme/site';
  click(w, md.querySelector('[data-m="save"]'));
  await until(() => d.querySelectorAll('#pov-links .povl').length === 1);
  click(w, d.querySelector('[data-pov="link-add"]')); await sleep(50);
  md = d.querySelector('.modal.povmodal');
  md.querySelector('#pl-url').value = 'https://www.figma.com/file/x'; md.querySelector('#pl-ttl').value = 'Designs';
  click(w, md.querySelector('[data-m="save"]'));
  await until(() => d.querySelectorAll('#pov-links .povl').length === 2);
  let ls = [...d.querySelectorAll('#pov-links .povl a')];
  check(ls[0].textContent.includes('github.com/acme/site') && ls[1].textContent.includes('Designs'), 'links in order, title from the address: ' + ls.map(a => a.textContent));
  check(ls.every(a => a.target === '_blank' && /noopener/.test(a.rel)) && !d.querySelector('#pov-links img'), 'links open in a new tab, no favicons (no images)');
  { const box = d.createElement('div'); box.innerHTML = w.eval(`ic('git', 's') + ic('palette', 's')`);
    check(ls[0].querySelector('svg').innerHTML === box.children[0].innerHTML && ls[1].querySelector('svg').innerHTML === box.children[1].innerHTML
      && w.eval(`povLinkIcon('https://example.org/x')`) === 'link', 'icons from the address (git, design, else a link)'); }
  click(w, d.querySelectorAll('#pov-links [data-pov="link-up"]')[0]);
  await until(() => d.querySelector('#pov-links .povl a')?.textContent.includes('Designs'));
  check(d.querySelector('#pov-links .povl a').textContent.includes('Designs'), 'move up');
  // milestones: the app's date picker, no native date input
  click(w, d.querySelector('[data-pov="ms-add"]')); await sleep(50);
  md = d.querySelector('.modal.povmodal');
  check(!md.querySelector('input[type="date"]') && md.querySelector('.dpbtn'), 'milestone dialog: the app\'s date picker');
  md.querySelector('#pm-name').value = 'Launch';
  w.eval(`dpSet(document.querySelector('#pm-day'), '${day(20)}')`);
  click(w, md.querySelector('[data-m="save"]'));
  await until(() => d.querySelectorAll('#pov-ms .povm').length === 2);
  check([...d.querySelectorAll('#pov-ms .pmn span')].map(s => s.textContent).join() === 'Beta,Launch', 'milestones by day');
  click(w, d.querySelector('#pov-ms [data-pov="ms-done"]'));
  await until(() => d.querySelector('#pov-ms .povm.done'));
  check(d.querySelector('#pov-ms .povm.done .pmn').textContent.includes('Beta'), 'tick a milestone');
  // project files
  const inp = d.querySelector('#pov-file');
  Object.defineProperty(inp, 'files', {configurable: true, value: [new w.File(['%PDF-1.4'], 'brief.pdf', {type: 'application/pdf'})]});
  inp.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(() => [...d.querySelectorAll('#pov-files .povf .pfn')].some(x => x.textContent === 'brief.pdf'));
  const pf = [...d.querySelectorAll('#pov-files .povf a')].find(a => a.textContent.includes('brief.pdf'));
  check(pf && /\/api\/list-files\/\d+$/.test(pf.getAttribute('href')) && pf.target === '_blank', 'project file: PDF opens inline');
  const tf = d.querySelector('#pov-files .povtf');
  check(tf && /Attachments from tasks/.test(tf.querySelector('summary').textContent) && /notes\.txt/.test(tf.textContent) && tf.querySelector('[data-pov="task"]')?.textContent.includes('Wireframes'), 'task files with their task');
  check(!tf.querySelector('.povx'), 'task files are read-only here');
  click(w, tf.querySelector('[data-pov="task"]')); await sleep(300);
  check(w.eval('S.sel') === T1, 'a task file opens its task');
  w.eval('closeDetail && closeDetail()'); await sleep(100);
  // members + time
  check(/Bob/.test(d.querySelector('#pov-people').textContent) && /Viewer/.test(d.querySelector('#pov-people').textContent), 'members with roles');
  // leave the overview: back to the list's own view
  click(w, d.querySelector('#top [data-act="view-timeline"]'));
  await until(() => d.querySelector('#view .tl'));
  check(!w.eval('isOverview()') && (await call('GET', '/api/state')).lists.find(l => l.id === P).view === 'timeline', 'Timeline: overview off, the list\'s view changes');
  check(d.querySelectorAll('.tl-grp .tl-ms').length === 2 && d.querySelectorAll('.tl-msl').length === 2, 'milestones as markers in the timeline: ' + d.querySelectorAll('.tl-ms').length);
  check(d.querySelector('.tl-ms.done') && /Beta/.test(d.querySelector('.tl-ms.done').title), 'a reached milestone looks done');
  await call('PATCH', `/api/lists/${P}`, {view: 'list'});
  w.close();

  // German wording: "Projektübersicht", never the global "Übersicht"
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'l/' + P, ls: {'tasks.pov': JSON.stringify([P])}}); d = w.document;
  await until(() => d.querySelector('#view .pov .povs'));
  check(d.querySelector('#top [data-act="view-overview"]').title === 'Projektübersicht', 'de: Projektübersicht');
  check(/Projektablage/.test(d.querySelector('#pov-files h3').textContent) && /Anhänge aus Aufgaben/.test(d.querySelector('.povtf summary').textContent)
    && /Wichtige Links/.test(d.querySelector('#pov-links h3').textContent) && /Meilensteine/.test(d.querySelector('#pov-ms h3').textContent), 'de: section names');
  check(w.eval(`tr('Where is it stuck?')`) !== 'Projektübersicht', 'the global overview keeps its own name');
  w.close();
  await call('PATCH', '/api/settings', {lang: 'en'});

  // phones: the view switch in "…"
  w = await boot({user: 'alice', hash: 'l/' + P, mobile: true}); d = w.document;
  const items = w.eval('topMoreItems()').map(x => x.label);
  check(items.includes('Project overview') && items.includes('List'), 'phone: "Project overview" in "…": ' + items.slice(0, 6));
  w.eval(`topMoreItems().find(x => x.label === 'Project overview').fn()`);
  await until(() => d.querySelector('#view .pov'));
  check(w.eval('isOverview()'), 'phone: the overview opens from "…"');
  w.close();

  // a viewer reads only; collaboration off: no members section
  w = await boot({user: 'bob', hash: 'l/' + P, ls: {'tasks.pov': JSON.stringify([P])}}); d = w.document;
  await until(() => d.querySelector('#view .pov .povs'));
  check(!d.querySelector('[data-pov="desc-edit"], [data-pov="link-add"], [data-pov="ms-add"], #pov-file, .povx') && d.querySelector('[data-pov="ms-done"]').disabled, 'viewer: read only');
  check(/Goal/.test(d.querySelector('#pov-desc').textContent), 'viewer sees the description');
  w.close();
  await call('PATCH', '/api/settings', {features: ALL.replace(',collab', '').replace(',paperless', '')});
  w = await boot({user: 'alice', hash: 'l/' + P, ls: {'tasks.pov': JSON.stringify([P])}}); d = w.document;
  await until(() => d.querySelector('#view .pov .povs'));
  check(!d.querySelector('#pov-people') && !d.querySelector('#pov-status') && !d.querySelector('[data-pov="pl-add"]'), 'without collaboration / Paperless: no members, status or Paperless');
  w.close();
  await call('PATCH', '/api/settings', {features: ALL});
  if (errs.length) check(false, 'JS errors: ' + [...new Set(errs)].join(' | '));

  // ================= Firefox: layout at 360 / 390 touch, 1280 / 1920 mouse
  await call('PATCH', `/api/lists/${P}`, {view: 'list'});
  for (const touch of [true, false]) {
    await firefox(async ({cmd, ev, nav, ctx, shot}) => {
      await nav(B + 'static/icon.svg');
      const lgi = await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
      check(lgi === 200, 'Firefox: login');
      await ev(`localStorage.setItem('tasks.pov', '[${P}]'); 1`);
      let nr = 0;
      const open = async hash => { await nav(B + 'static/icon.svg'); await nav(B + '?v=' + (++nr) + '#' + hash); for (let i = 0; i < 30 && !(await ev(`!!document.querySelector('#view .pov .povs')`).catch(() => false)); i++) await sleep(300); await sleep(900); };
      for (const [vw, vh] of touch ? [[360, 780], [390, 844]] : [[1280, 800], [1920, 1080]]) {
        await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
        await open('l/' + P);
        const hd = await ev(HEAD);
        check(hd.more && hd.bell && hd.more[1] <= vw + .5 && hd.bell[1] <= vw + .5 && !hd.out.length, `${vw}px: "…" and the bell in view ${JSON.stringify(hd)}`);
        const lay = await ev(`(() => { const v = document.querySelector('#view'), g = document.querySelector('.povg'), cs = [...document.querySelectorAll('.povs')];
          const vr = v.getBoundingClientRect(); return {sw: v.scrollWidth, cw: v.clientWidth, cols: getComputedStyle(g).gridTemplateColumns.split(' ').length,
          out: cs.filter(s => { const r = s.getBoundingClientRect(); return r.right > vr.right + .5 || r.left < vr.left - .5; }).map(s => s.id), n: cs.length,
          links: document.querySelectorAll('#pov-links .povl').length, ms: document.querySelectorAll('#pov-ms .povm').length}; })()`);
        check(lay.n >= 5 && lay.links === 2 && lay.ms === 2, `${vw}px: overview rendered ${JSON.stringify(lay)}`);
        check(lay.sw <= lay.cw + 1 && !lay.out.length, `${vw}px: no horizontal overflow ${JSON.stringify(lay)}`);
        check(vw >= 1100 ? lay.cols === 2 : lay.cols === 1, `${vw}px: ${vw >= 1100 ? 'two columns' : 'one column'} ${JSON.stringify(lay)}`);
        if (touch) {
          const small = await ev(SMALL('#view .pov button, #view .pov .povup, #view .povl a, #view .povf > a'));
          check(!small.length, `${vw}px: touch targets >= 44 px: ${JSON.stringify(small)}`);
          const seg = await ev(`(() => [...document.querySelectorAll('#top .vseg')].filter(e => e.offsetWidth).length)()`);
          check(seg === 0, `${vw}px: the view switch is not in the phone header (it is in "…")`);
        } else {
          const vs = await ev(`(() => { const b = document.querySelector('#top [data-act="view-overview"]'); if (!b || !b.offsetWidth) return null; const r = b.getBoundingClientRect(); return {on: b.classList.contains('on'), r: r.right, vw: document.documentElement.clientWidth}; })()`);
          check(vs && vs.on && vs.r <= vs.vw + .5, `${vw}px: the tab "Project overview" in the header, on ${JSON.stringify(vs)}`);
        }
        await shot(`p271-overview-${vw}.png`);
        // the milestone dialog's date picker stays inside the viewport
        await ev(`(() => { document.querySelector('[data-pov="ms-add"]').click(); return 1; })()`); await sleep(300);
        await ev(`(() => { document.querySelector('.povmodal .dpbtn').click(); return 1; })()`); await sleep(300);
        const dp = await ev(`(() => { const p = document.querySelector('#dpop'); if (!p) return null; const r = p.getBoundingClientRect(); return {l: r.left, r: r.right, t: r.top, b: r.bottom, iw: innerWidth, ih: innerHeight}; })()`);
        check(dp && dp.l >= -0.5 && dp.r <= dp.iw + .5 && dp.b <= dp.ih + .5, `${vw}px: the date picker of a milestone inside the viewport ${JSON.stringify(dp)}`);
        await shot(`p271-ms-${vw}.png`);
        await ev(`(() => { dpClose(false); document.querySelectorAll('.modal').forEach(m => m.remove()); return 1; })()`);
        // the timeline with its markers
        await ev(`(async () => { await setListView(listById(${P}), 'timeline'); return 1; })()`); await sleep(800);
        const tl = await ev(`(() => { const m = document.querySelector('.tl-grp .tl-ms'); if (!m) return null; const r = m.getBoundingClientRect(), n = document.querySelector('.tl-row:not(.tl-headrow) .tl-name').getBoundingClientRect(); return {w: r.width, l: r.left, nr: n.right, n: document.querySelectorAll('.tl-ms').length}; })()`);
        check(tl && tl.n === 2 && tl.w > 4, `${vw}px: milestone markers in the timeline ${JSON.stringify(tl)}`);
        await shot(`p271-timeline-${vw}.png`);
        await ev(`(async () => { await setListView(listById(${P}), 'overview'); return 1; })()`);
      }
    }, touch);
  }

  console.log(`p271_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
