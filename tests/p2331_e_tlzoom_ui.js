// kalmido-suite: fresh
// 2.331.0 E UI tests (#3311 two fingers / Ctrl + wheel zoom only the timelines and the picture view, not the page): own container
// (start.sh), Firefox (real layout). Invented tasks only, the picture is a generated 4 x 3 PNG.
// - roadmap: Ctrl + wheel on the timeline is taken (no page zoom), the day width grows without steps, the day under the pointer
//   stays under it, kept on the server (prefs zf); zoomed out beyond the bound the zoom changes week -> month (the tab follows);
//   the tab "Week" gives the week its own day width again; a two-finger pinch (two touches) zooms the same way
// - the list timeline: Ctrl + wheel and a pinch change the day width (kept on the device, tasks.tlPx), zoomed out it shows more days
// - the calendar's timeline zooms too; Ctrl + wheel on the list view (no timeline) stays the browser's page zoom
// - the picture view: a pinch / Ctrl + wheel zooms the picture (not the page), a tap on the zoomed picture keeps the view open,
//   back to its size a tap closes it as before
// - the server takes zf only as a number in its range
// freelancer-matrix: tasks (no new route; the roadmap prefs gain "zf"; tested as alice without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2331_e_tlzoom_ui', check, shots: 'P2331E_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const ds = n => { const t = new Date(), d = new Date(t.getFullYear(), t.getMonth(), t.getDate() + n); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
// a 4 x 3 red PNG
const PNG = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAQAAAADCAIAAAA7ljmRAAAAFElEQVR4nGO8IyfHAANMDEgAhQMAKdIBHjGGQBcAAAAASUVORK5CYII=', 'base64');

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', modules: ['cal', 'timeline', 'progress', 'deps']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,timeline,progress,deps'});
  const P = (await call('POST', '/api/lists', {name: 'Relaunch', kind: 'project', view: 'timeline'})).id;
  const LI = (await call('POST', '/api/lists', {name: 'Errands', kind: 'list'})).id;
  for (const [title, s, e] of [['Kickoff', null, 1], ['Design', 2, 12], ['Build', 13, 40], ['Launch', null, 44]]) {
    const r = await call('POST', '/api/tasks', {title, list_id: P, ...(s != null ? {start: ds(s)} : {}), due: ds(e)});
    check(r.http === 200 || r.http === 201, 'task ' + title + ' ' + r.http);
  }
  const T = (await call('POST', '/api/tasks', {title: 'Buy paper', list_id: LI, due: ds(3)})).id;
  const fd = new FormData(); fd.append('file', new Blob([PNG], {type: 'image/png'}), 'red.png');
  const up = await fetch(B + `api/tasks/${T}/attachments`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  check(up.status === 200 || up.status === 201, 'picture attached ' + up.status);
  // the server: zf is a number in its range, nothing else
  check((await call('PATCH', '/api/settings', {roadmap: JSON.stringify({v: 'timeline', zf: 'big'})})).http === 400, 'zf: a text is refused');
  check((await call('PATCH', '/api/settings', {roadmap: JSON.stringify({v: 'timeline', zf: 50})})).http === 400, 'zf: out of range is refused');
  check((await call('PATCH', '/api/settings', {roadmap: JSON.stringify({v: 'timeline', z: 'week'})})).http === 200, 'roadmap prefs: week');
  const prefs = async () => { const s = (await call('GET', '/api/state')).settings.roadmap; return s ? JSON.parse(s) : {}; };

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  // the point in the middle of the timeline's days (right of the names), the day under it, the day width, the page's zoom
  const at = `(() => { const sc = document.querySelector('#tlscroll'), r = sc.getBoundingClientRect(), nw = tlNameW(), x = Math.round(r.left + nw + (r.width - nw) / 2), y = Math.round(r.top + Math.min(r.height - 20, 140));
    const dw = isRoadmap() ? S.rmV.G.dw : tlDW(), s0 = isRoadmap() ? S.rmV.G.start : S.tlStart;
    return {x, y, dw, day: (x - r.left - nw + sc.scrollLeft) / dw + diffDays('2000-01-01', s0), days: +getComputedStyle(document.querySelector('#view .tl')).getPropertyValue('--days'),
      dpr: devicePixelRatio, vv: window.visualViewport ? visualViewport.scale : 1}; })()`;
  // Ctrl + wheel at the middle of the timeline: n steps of dy (< 0 = nearer); returns whether every event was taken
  const wheel = (sel, dy, n) => `(async () => { let taken = true; const sc = document.querySelector('#tlscroll'), r = sc.getBoundingClientRect(), nw = tlNameW();
    const x = Math.round(r.left + nw + (r.width - nw) / 2), y = Math.round(r.top + Math.min(r.height - 20, 140));
    for (let i = 0; i < ${n}; i++) { const el = document.elementFromPoint(x, y) || document.querySelector('${sel}'); taken = !el.dispatchEvent(new WheelEvent('wheel', {deltaY: ${dy}, ctrlKey: true, clientX: x, clientY: y, bubbles: true, cancelable: true})) && taken; await new Promise(r => requestAnimationFrame(r)); }
    return taken; })()`;
  // two fingers on the timeline (touch events with two touches, as the phone sends them) from 100 px apart to k * 100
  const pinch = k => `(async () => { const sc = document.querySelector('#tlscroll'), r = sc.getBoundingClientRect(), nw = tlNameW();
    const x = Math.round(r.left + nw + (r.width - nw) / 2), y = Math.round(r.top + Math.min(r.height - 20, 140)), el = document.elementFromPoint(x, y);
    const fire = (t, type, f) => { const e = new Event(type, {bubbles: true, cancelable: true}); e.touches = f == null ? [] : [{clientX: x - 50 * f, clientY: y, target: el}, {clientX: x + 50 * f, clientY: y, target: el}]; e.changedTouches = e.touches; t.dispatchEvent(e); return e; };
    fire(el, 'touchstart', 1); let prevented = true;
    for (const f of [(1 + ${k}) / 2, ${k}]) { prevented = fire(el, 'touchmove', f).defaultPrevented && prevented; await new Promise(r => requestAnimationFrame(r)); await new Promise(r => requestAnimationFrame(r)); }
    fire(el, 'touchend', null);
    return prevented; })()`;
  const ended = `pz_busy() === false && !S.rmLive && !S.tlLive`;

  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 860}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev);

    // ================= the roadmap
    await nav(B + '#all');
    check(await ready(ev, `!!document.querySelector('#view .tl.rm #tlscroll') && rmZoom() === 'week'`, 80), 'roadmap: week');
    let a = await ev(at);
    check(Math.abs(a.dw - 36) < .5 && a.dpr === 1, 'roadmap: 36 px a day at the start ' + a.dw);
    check(await ev(wheel('#tlscroll', -100, 3)), 'roadmap: Ctrl + wheel taken (not the page zoom)');
    check(await ready(ev, ended), 'roadmap: the zoom ends after the wheel');
    let b = await ev(at);
    check(b.dw > a.dw * 1.8 && b.dw < a.dw * 2.3 && b.dpr === 1 && b.vv === 1, 'roadmap: wider days, the page not zoomed ' + JSON.stringify([a.dw, b.dw, b.dpr, b.vv]));
    check(Math.abs(b.day - a.day) < 1, 'roadmap: the day under the pointer stays under it ' + a.day + ' ' + b.day);
    check(await ready(ev, `rmZoom() === 'week' && !!document.querySelector('#view .rm-bar [data-k="week"].on')`), 'roadmap: still the week');
    let p = null;
    for (let i = 0; i < 20 && !(p?.zf > 1.5); i++) { p = await prefs(); await sleep(150); }
    check(p.z === 'week' && p.zf > 1.8 && p.zf <= 2, 'roadmap: kept in the prefs on the server ' + JSON.stringify(p));
    await shot('p2331-e-roadmap-wide.png');
    // farther out than the week's bound: the month
    check(await ev(wheel('#tlscroll', 100, 8)), 'roadmap: Ctrl + wheel out taken');
    check(await ready(ev, ended), 'roadmap: zoom out ended');
    check(await ready(ev, `rmZoom() === 'month' && !!document.querySelector('#view .rm-bar [data-k="month"].on')`), 'roadmap: beyond the bound the month (tab follows)');
    b = await ev(at);
    check(b.dw < 21 && b.dw >= 7 && b.dpr === 1, 'roadmap: the month without steps ' + b.dw);
    for (let i = 0; i < 20 && p.z !== 'month'; i++) { p = await prefs(); await sleep(150); }
    check(p.z === 'month' && p.zf > 0 && p.zf < 1.75, 'roadmap: month + its factor on the server ' + JSON.stringify(p));
    // the tab gives the week its own width again
    await ev(`(() => { document.querySelector('#view .rm-bar [data-k="week"]').click(); return 1; })()`);
    check(await ready(ev, `rmZoom() === 'week' && Math.abs(S.rmV.G.dw - 36) < .5`), 'roadmap: the tab "Week" = 36 px again');
    for (let i = 0; i < 20 && p.zf != null; i++) { p = await prefs(); await sleep(150); }
    check(p.z === 'week' && p.zf == null, 'roadmap: the tab drops the own factor ' + JSON.stringify(p));
    // two fingers
    a = await ev(at);
    check(await ev(pinch(1.5)), 'roadmap: the pinch is taken (no page zoom, no scroll)');
    check(await ready(ev, ended), 'roadmap: the pinch ended with the fingers');
    b = await ev(at);
    check(b.dw > a.dw * 1.35 && b.dw < a.dw * 1.65 && b.dpr === 1, 'roadmap: pinch 1.5 = 1.5 times the day width ' + a.dw + ' ' + b.dw);
    check(Math.abs(b.day - a.day) < 1, 'roadmap: pinch keeps the day between the fingers ' + a.day + ' ' + b.day);
    check(await ev(`getComputedStyle(document.querySelector('#view .tl')).touchAction`) === 'pan-x pan-y', 'roadmap: the browser does not pinch-zoom the timeline (touch-action)');

    // ================= the list timeline
    await nav(B + '#l/' + P);
    check(await ready(ev, `!!document.querySelector('#view .tl #tlscroll') && isTimeline()`, 80), 'list timeline shown');
    a = await ev(at);
    check(Math.abs(a.dw - 36) < .5 && a.days === 70, 'list timeline: 36 px, 70 days ' + a.dw + ' ' + a.days);
    check(await ev(wheel('#tlscroll', 100, 4)), 'list timeline: Ctrl + wheel taken');
    check(await ready(ev, ended), 'list timeline: zoom ended');
    b = await ev(at);
    check(b.dw < a.dw * .45 && b.dw >= 16 && b.days > 70 && b.dpr === 1, 'list timeline: narrower days, more of them, page not zoomed ' + JSON.stringify([b.dw, b.days]));
    check(Math.abs(b.day - a.day) < 1, 'list timeline: the day under the pointer stays ' + a.day + ' ' + b.day);
    check(await ev(`+LS.get('tlPx') < 18 && !!document.querySelector('#view .tl.tl-sm')`), 'list timeline: kept on the device, narrow head');
    await shot('p2331-e-list-narrow.png');
    a = b;
    check(await ev(pinch(2)), 'list timeline: pinch taken');
    check(await ready(ev, ended), 'list timeline: pinch ended');
    b = await ev(at);
    check(b.dw > a.dw * 1.8 && b.dw < a.dw * 2.2, 'list timeline: pinch 2 = twice the day width ' + a.dw + ' ' + b.dw);
    await nav(B + '#l/' + P);  // after a reload the width is back
    check(await ready(ev, `!!document.querySelector('#view .tl #tlscroll') && Math.abs(tlDW() - ${b.dw}) <= 1`, 80), 'list timeline: the width after a reload');

    // ================= the calendar's timeline
    await ev(`(() => { LS.set('calMode', 'timeline'); S.calMode = 'timeline'; return 1; })()`);
    await nav(B + '#cal');
    check(await ready(ev, `S.calMode === 'timeline' && !!document.querySelector('#view .tl #tlscroll')`, 80), 'calendar timeline shown');
    a = await ev(at);
    check(await ev(wheel('#tlscroll', -100, 2)), 'calendar timeline: Ctrl + wheel taken');
    check(await ready(ev, ended), 'calendar timeline: ended');
    b = await ev(at);
    check(b.dw > a.dw * 1.3 && b.dpr === 1, 'calendar timeline: wider days ' + a.dw + ' ' + b.dw);

    // ================= no timeline: the browser's zoom stays
    await nav(B + '#l/' + LI);
    check(await ready(ev, `!!document.querySelector('#view .trow')`, 80), 'list view shown');
    check(!(await ev(`(() => { const el = document.querySelector('#view .trow'), r = el.getBoundingClientRect(); return !el.dispatchEvent(new WheelEvent('wheel', {deltaY: -100, ctrlKey: true, clientX: r.left + 20, clientY: r.top + 10, bubbles: true, cancelable: true})); })()`)), 'list view: Ctrl + wheel stays the browser\'s page zoom');

    // ================= the picture view
    await ev(`(() => { S.sel = ${T}; attLightbox(taskById(${T}).attachments[0].id); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.lightbox > img') && document.querySelector('.lightbox > img').complete`), 'picture view open');
    const img = `document.querySelector('.lightbox > img')`;
    const imgWheel = (dy, n) => `(async () => { const el = ${img}, r = el.getBoundingClientRect(); let taken = true;
      for (let i = 0; i < ${n}; i++) { taken = !el.dispatchEvent(new WheelEvent('wheel', {deltaY: ${dy}, ctrlKey: true, clientX: r.left + r.width / 2, clientY: r.top + r.height / 2, bubbles: true, cancelable: true})) && taken; await new Promise(r => requestAnimationFrame(r)); }
      return taken; })()`;
    const scale = `(() => { const m = /scale\\(([\\d.]+)\\)/.exec(${img}.style.transform); return m ? +m[1] : 1; })()`;
    check(await ev(imgWheel(-100, 3)), 'picture: Ctrl + wheel taken');
    check(await ready(ev, `pz_busy() === false`), 'picture: zoom ended');
    const s1 = await ev(scale);
    check(s1 > 1.8 && await ev(`document.querySelector('.lightbox').classList.contains('lbz') && devicePixelRatio === 1`), 'picture: zoomed itself, the page not ' + s1);
    await shot('p2331-e-picture.png');
    await ev(`(() => { ${img}.click(); return 1; })()`);
    check(await ev(`!!document.querySelector('.lightbox')`), 'picture: a tap on the zoomed picture keeps the view open');
    await ev(`(() => { const el = ${img}, r = el.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
      const fire = (type, f) => { const e = new Event(type, {bubbles: true, cancelable: true}); e.touches = f == null ? [] : [{clientX: x - 40 * f, clientY: y, target: el}, {clientX: x + 40 * f, clientY: y, target: el}]; el.dispatchEvent(e); };
      fire('touchstart', 1); fire('touchmove', .2); fire('touchend', null); return 1; })()`);
    check(await ready(ev, `pz_busy() === false && !${img}.style.transform`), 'picture: pinched together = its own size again');
    await ev(`(() => { ${img}.click(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('.lightbox')`), 'picture: at its size a tap closes the view as before');
  }, false);

  console.log(`p2331_e_tlzoom_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
