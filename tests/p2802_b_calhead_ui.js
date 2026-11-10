// 2.855.0 B UI tests (#5462 the calendar head on a phone and a tablet, real layout): own container (start.sh), Firefox with a finger.
// kalmido-suite: fresh
// Invented data only.
// - 360 x 740: one line of views + one line of the period; the month grid starts in the upper fifth; "..." opens a menu with
//   Find a date / Calendars... / Show completed, each does its job; the round + adds an event; the views say aria-pressed
// - timeline: "No date" waits in "..." too
// - 820 x 1180: the head is one line (nothing wraps), the view names at least 14 px, "+ Event" stays, the rest in "..."
// - 1280: the computer keeps its buttons in the head, no "..."
// freelancer-matrix: n/a (no route; the head is drawn in the client only, tested as alice without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2802_b_calhead_ui', check, shots: 'P2802B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events,timeline'});
  const day = i => { const d = new Date(); d.setDate(d.getDate() + i); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`; };
  for (const [i, title] of [[0, 'Pitch deck review'], [2, 'Edit rough cut']]) await call(CA, 'POST', '/api/tasks', {title, due: day(i)});
  const signIn = ev => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  // the boxes of the head's visible parts (display none = left out)
  const HEAD = `(() => { const b = document.querySelector('#view > .calbar'); if (!b) return null; const r = b.getBoundingClientRect();
    const kids = [...b.children].filter(e => e.getClientRects().length).map(e => { const x = e.getBoundingClientRect(); return {c: e.className || e.tagName, act: e.dataset.act || '', top: Math.round(x.top), bot: Math.round(x.bottom), l: Math.round(x.left), r: Math.round(x.right)}; });
    const g = document.querySelector('#view .cal.calv, #view .week, #view .cyear, #view .agendav, #view .tl, #view .timeline');
    const seg = [...b.querySelectorAll('.seg button')].map(x => ({k: x.dataset.k, p: x.getAttribute('aria-pressed'), fs: parseFloat(getComputedStyle(x).fontSize)}));
    const sg = b.querySelector('.seg'), t = b.querySelector('h2');
    const small = [...b.querySelectorAll('button')].filter(e => e.getClientRects().length).map(e => { const x = e.getBoundingClientRect(); return [e.dataset.act || e.dataset.k || e.className, Math.round(x.width), Math.round(x.height)]; }).filter(x => x[1] < 43.5 || x[2] < 43.5);
    return {small, segSW: sg && [sg.scrollWidth, sg.clientWidth], h2SW: t && [t.scrollWidth, t.clientWidth], segFull: !!sg && sg.scrollWidth <= sg.clientWidth + 1, h2Full: !!t && t.scrollWidth <= t.clientWidth + 1, top: Math.round(r.top), h: Math.round(r.height), bot: Math.round(r.bottom), kids, grid: g ? Math.round(g.getBoundingClientRect().top) : null, seg, W: innerWidth, Hh: innerHeight}; })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    // a real finger tap in the middle of the element, and the element really is the one under the finger there
    const tap = async sel => {
      const p = await ev(`(() => { const e = document.querySelector(${JSON.stringify(sel)}); if (!e || !e.getClientRects().length) return null; const r = e.getBoundingClientRect(); const x = r.left + r.width / 2, y = r.top + r.height / 2;
        const hit = document.elementFromPoint(x, y); return {x, y, hit: !!hit && (hit === e || e.contains(hit))}; })()`);
      if (!p || !p.hit) return false;
      await cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'f1', parameters: {pointerType: 'touch'}, actions: [{type: 'pointerMove', x: Math.round(p.x), y: Math.round(p.y)}, {type: 'pointerDown', button: 0}, {type: 'pause', duration: 40}, {type: 'pointerUp', button: 0}]}]});
      await cmd('input.releaseActions', {context: ctx});
      return true;
    };
    const menuItem = txt => `[...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].find(b => b.textContent.trim().startsWith(${JSON.stringify(txt)}))`;
    const tapItem = async txt => {  // the sheet first stands still (it slides up)
      await until(`!document.querySelector('#pop').getAnimations({subtree: true}).length`);
      const ok = await ev(`(() => { const b = ${menuItem(txt)}; if (!b) return false; b.dataset.t5462 = '1'; return true; })()`); return ok && tap('#pop [data-t5462="1"]'); };
    const closeAll = () => ev(`(() => { closePop?.(); document.querySelectorAll('.modal').forEach(m => m.remove()); document.querySelector('#scrim')?.classList.add('hidden'); return 1; })()`);

    // ================= phone 360 x 740
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 360, height: 740}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.calMode', '"month"'); return 1; })()`);
    await signIn(ev);
    await nav(B + '#cal');
    check(await until(`!!document.querySelector('#view > .calbar .seg') && !!document.querySelector('#view .cal.calv')`), 'phone: the month is drawn');
    let h = await ev(HEAD);
    console.log('phone head', JSON.stringify(h));
    const rows = k => { const c = k.map(x => (x.top + x.bot) / 2).sort((a, b) => a - b); return c.filter((x, i) => i === 0 || x - c[i - 1] > 10).length; };  // lines by their middle
    const segK = h.kids.find(x => /\bseg\b/.test(x.c)), navK = h.kids.find(x => /calnav/.test(x.c)), moreK = h.kids.find(x => x.act === 'cal-more'), h2K = h.kids.find(x => x.c === 'H2');
    check(segK && navK && moreK && h2K, 'phone: views, title, period and "..." are visible ' + JSON.stringify(h.kids.map(x => x.act || x.c)));
    check(!h.kids.some(x => ['cal-done', 'tpo-list', 'ev-cals', 'ev-new'].includes(x.act)), 'phone: Completed / Find a date / Calendars / "+ Event" are not in the head');
    check(segK && navK && segK.bot <= navK.top + 1 && rows(h.kids.filter(x => x !== segK)) === 1, 'phone: one line of views, then one line with the title, back / Today / next and "..."');
    // the app's own top bar (about 60 px) and two lines of 44 px touch targets: about a fifth (before #5462: 265 of 740)
    check(h.grid != null && h.grid <= h.Hh * 0.235, `phone: the month grid starts at about a fifth of the height (${h.grid} of ${h.Hh})`);
    check(h.kids.every(x => x.l >= -1 && x.r <= h.W + 1), 'phone: nothing of the head sticks out to the side');
    check(!h.small.length, 'phone: every button of the head is 44 px for a finger ' + JSON.stringify(h.small));
    await shot('p2802-b-phone-month.png');

    // aria-pressed follows the view
    check(h.seg.find(x => x.k === 'month')?.p === 'true' && h.seg.filter(x => x.p === 'true').length === 1, 'phone: Month says aria-pressed=true, the others false');
    check(await tap('#view .calbar .seg [data-k="week"]'), 'phone: Week can be tapped');
    check(await until(`document.querySelector('#view .calbar .seg [data-k="week"]')?.getAttribute('aria-pressed') === 'true' && document.querySelector('#view .calbar .seg [data-k="month"]')?.getAttribute('aria-pressed') === 'false' && !!document.querySelector('#view .week')`), 'phone: Week: aria-pressed moves along, the week grid is drawn');
    h = await ev(HEAD);
    check(h.grid != null && h.grid <= h.Hh * 0.235, `phone: the week grid starts at about a fifth too (${h.grid})`);
    await shot('p2802-b-phone-week.png');
    await tap('#view .calbar .seg [data-k="month"]');
    await until(`!!document.querySelector('#view .cal.calv')`);

    // the menu: Find a date / Calendars... / Show completed
    check(await tap('#view .calbar [data-act="cal-more"]'), 'phone: "..." can be tapped');
    check(await until(`(() => { const t = [...document.querySelectorAll('#pop:not(.hidden) [role="menuitem"]')].map(b => b.textContent.trim()).join('|'); return /Find a date/.test(t) && /Calendars/.test(t) && /Show completed/.test(t) && /New task/.test(t); })()`), 'phone: the menu has New task, Find a date, Calendars..., Show completed');
    await until(`!document.querySelector('#pop').getAnimations({subtree: true}).length`);
    await shot('p2802-b-phone-menu.png');
    const done0 = await ev(`showDoneCal()`);
    check(await tapItem('Show completed'), 'phone: "Show completed" can be tapped');
    check(await until(`showDoneCal() === ${!done0} && document.querySelector('#view .calbar [data-act="cal-done"]')?.getAttribute('aria-pressed') === '${!done0}'`), 'phone: "Show completed" switches the completed tasks');
    await tap('#view .calbar [data-act="cal-more"]');
    check(await until(`(() => { const b = ${menuItem('Show completed')}; return !!b && b.classList.contains('on') === ${!done0}; })()`), 'phone: the menu shows the new state of "Show completed"');
    check(await tapItem('Calendars'), 'phone: "Calendars..." can be tapped');
    check(await until(`!!document.querySelector('.modal.evcmodal')`), 'phone: "Calendars..." opens the Calendars window');
    await closeAll();
    await until(`!document.querySelector('.modal.evcmodal')`);
    await tap('#view .calbar [data-act="cal-more"]');
    await until(`!!(${menuItem('Find a date')})`);
    check(await tapItem('Find a date'), 'phone: "Find a date" can be tapped');
    check(await until(`!!document.querySelector('.tpo-dlg')`), 'phone: "Find a date" opens the scheduling polls');
    await closeAll();
    await tap('#view .calbar [data-act="cal-more"]');
    await until(`!!(${menuItem('New task')})`);
    check(await tapItem('New task'), 'phone: "New task" can be tapped');
    check(await until(`!!document.querySelector('.qadd.sheet #qsheet')`), 'phone: "New task" opens the task sheet');
    await closeAll();
    await ev(`(() => { closePop(); return 1; })()`).catch(() => 0);

    // the round + adds an event
    check(await until(`(() => { const f = document.querySelector('#fab'); return !!f && !f.classList.contains('gone') && f.getClientRects().length > 0; })()`), 'phone: the round + is there');
    check(await ev(`document.querySelector('#fab').getAttribute('aria-label')`) === 'New event', 'phone: the round + is named "New event" in the calendar');
    check(await tap('#fab'), 'phone: the round + can be tapped');
    check(await until(`!!document.querySelector('.modal.evmodal #ev-title')`), 'phone: the + opens a new event');
    await ev(`(() => { document.querySelector('.modal.evmodal #ev-title').value = 'Plus button event'; document.querySelector('.modal.evmodal [data-evm="save"]').click(); return 1; })()`);
    check(await until(`!document.querySelector('.modal.evmodal') && /Plus button event/.test(document.querySelector('#view').textContent)`), 'phone: the event is saved and shows in the calendar');
    const evs = await until(() => ev(`fetch('/api/calendars/events?from=' + addDays(S.calSel || today(), -2) + '&to=' + addDays(S.calSel || today(), 2), {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.text())`).then(t => /Plus button event/.test(t) ? t : ''));
    check(String(evs).includes('Plus button event'), 'phone: the server has the event ' + String(evs).slice(0, 200));

    // the timeline: "No date" in the menu too
    await tap('#view .calbar .seg [data-k="timeline"]');
    check(await until(`S.calMode === 'timeline' && !!document.querySelector('#view .calbar [data-act="tl-nd"]')`), 'phone: the timeline is drawn');
    h = await ev(HEAD);
    check(!h.kids.some(x => x.act === 'tl-nd') && rows(h.kids.filter(x => !/\bseg\b/.test(x.c))) === 1, 'phone: timeline: "No date" is not in the head, still two lines ' + JSON.stringify(h.kids));
    const nd0 = await ev(`document.querySelector('#view .calbar [data-act="tl-nd"]').classList.contains('on')`);
    await tap('#view .calbar [data-act="cal-more"]');
    check(await until(`!!(${menuItem('No date')})`), 'phone: timeline: the menu has "No date"');
    await until(`!document.querySelector('#pop').getAnimations({subtree: true}).length`);
    await shot('p2802-b-phone-timeline-menu.png');
    await tapItem('No date');
    check(await until(`document.querySelector('#view .calbar [data-act="tl-nd"]')?.classList.contains('on') === ${!nd0}`), 'phone: timeline: "No date" from the menu switches the rows');
    await tap('#view .calbar .seg [data-k="month"]');
    await until(`!!document.querySelector('#view .cal.calv')`);

    // ================= tablet 820 x 1180
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 820, height: 1180}});
    for (const k of ['month', 'week', 'agenda', 'timeline']) {
      await ev(`(() => { S.calMode = '${k}'; renderView(); return 1; })()`);
      await until(`!!document.querySelector('#view > .calbar')`);
      h = await ev(HEAD);
      console.log('820 ' + k, JSON.stringify(h));
      const tops = h.kids.map(x => (x.top + x.bot) / 2);
      check(Math.max(...tops) - Math.min(...tops) <= 10 && h.h <= 60, `820 ${k}: the head is one line (height ${h.h})`);
      check(h.kids.every(x => x.l >= 0 && x.r <= h.W + 1), `820 ${k}: nothing sticks out`);
      check(!h.small.length, `820 ${k}: every button of the head is 44 px for a finger ` + JSON.stringify(h.small));
      check(h.seg.every(x => x.fs >= 13.9), `820 ${k}: the view names are readable (${h.seg.map(x => x.fs).join()})`);
      check(h.kids.some(x => x.act === 'cal-more') && h.kids.some(x => x.act === 'ev-new') && !h.kids.some(x => ['cal-done', 'tpo-list', 'ev-cals', 'tl-nd'].includes(x.act)), `820 ${k}: "+ Event" and "..." in the head, the rest in the menu`);
      check(h.segFull, `820 ${k}: every view name is whole (the views do not scroll)`);
      check(h.seg.filter(x => x.p === 'true').map(x => x.k).join() === k && await ev(`document.querySelectorAll('#view .calbar .seg button.on').length === 1 && document.querySelector('#view .calbar .seg button.on').dataset.k === '${k}'`), `820 ${k}: only this view is marked ` + JSON.stringify(h.seg));
      if (k === 'month') { check(h.h2Full, '820 month: the month title is whole ' + JSON.stringify(h.h2SW)); await shot('p2802-b-820-month.png'); }
      if (k === 'timeline') await shot('p2802-b-820-timeline.png');
    }
    await ev(`(() => { S.calMode = 'month'; renderView(); return 1; })()`);
    await tap('#view .calbar [data-act="cal-more"]');
    check(await until(`!!(${menuItem('Calendars')}) && !(${menuItem('New task')})`), '820: the menu has Calendars..., no "New task" (the head has "+ Event")');
    await closeAll();

    // ================= computer 1280: unchanged
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await ev(`(() => { renderView(); return 1; })()`);
    await until(`!!document.querySelector('#view > .calbar')`);
    h = await ev(HEAD);
    check(!h.kids.some(x => x.act === 'cal-more') && ['cal-done', 'tpo-list', 'ev-cals', 'ev-new'].every(a => h.kids.some(x => x.act === a)), '1280: the head keeps its buttons, no "..." ' + JSON.stringify(h.kids.map(x => x.act || x.c)));
    await shot('p2802-b-1280-month.png');
  }, true);

  console.log(`p2802_b_calhead_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
