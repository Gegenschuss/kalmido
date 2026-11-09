// 2.800.0 UI test, part A (calendar polish): own container (start.sh), jsdom + Firefox (real layout). Invented names only.
// kalmido-suite: fresh
// - #5460: an event in the lower half of the month opens its window after the details are loaded inside the browser window
//   (1280x800 and 820x800): its lower edge stays in the window, Edit (owner) and Accept (invited person) are in sight and take
//   the click; the actions run Edit - Preparation task - Delete (Delete last); "Hide on Today" is no longer in the window
// - #5468: dated tasks in the calendar follow the workspace like the events: in Private only the private list's task, in the
//   organisation only its list's task, under "All" both; an event of a subscribed calendar shows in each, with its mark;
//   a person without an organisation (bob) sees all of their own dated tasks
// freelancer-matrix: events (alice has no organisation: her private workspace)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login, boot, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2800_a_cal_ui', check, shots: 'P2800A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
const py = code => execFileSync('docker', ['exec', CT, 'python', '-c', code], {encoding: 'utf8'}).trim();
const until = fn => until0(fn, {timeout: 15000, step: 100});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const pad = n => String(n).padStart(2, '0');
const dstr = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events,collab'});
  const BOB = (await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.org'})).id;
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,events,collab'});

  // the event of #5460 (below), made before the organisation exists: an invitation to bob, who stays without one
  const now = new Date(), LAST = dstr(new Date(now.getFullYear(), now.getMonth() + 1, 0));  // the month's last day: its lowest rows
  const W = await call(CA, 'POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  const long = Array.from({length: 14}, (_, i) => `Point ${i + 1}: go through the cut list with the studio and note what is left.`).join('\n');
  const EV = await call(CA, 'POST', '/api/events', {title: 'Review late in the month', cal_id: W.id, start: `${LAST}T10:00`, end: `${LAST}T11:00`,
    location: 'Studio 2, back entrance', description: long, attendees: [{user_id: BOB}], reminders: [30]});
  check(EV.id, '#5460: the event on the server ' + EV.http);


  // ================= #5468: dated tasks follow the workspace in the calendar
  const D = dstr(new Date()), ME = (await call(CA, 'GET', '/api/me')).id;
  const ORG = (await call(CA, 'POST', '/api/admin/orgs', {name: 'Studio North', admin_id: ME})).id;
  check(ORG, '#5468: an organisation');
  const OL = await call(CA, 'POST', '/api/lists', {name: 'Client work', org_id: ORG});
  const PL = await call(CA, 'POST', '/api/lists', {name: 'Home matters', org_id: null});  // private (with one organisation a new list would go there)
  const TO = await call(CA, 'POST', '/api/tasks', {title: 'Send the rough cut', list_id: OL.id, due: D});
  const TP = await call(CA, 'POST', '/api/tasks', {title: 'File the tax return', list_id: PL.id, due: D});
  check(OL.id && PL.id && TO.id && TP.id, '#5468: a dated task in an organisation list and in a private list');
  // a synced subscription of alice with one event today, written like the sync does
  py(`from kalmido.core.db import connect
c = connect()
c.execute("INSERT INTO cal_subs(user_id,kind,name,color,visible,url,status,created_at) VALUES(${ME},'ics','Club fixtures','#f5b041',1,'x','ok','2026-01-01T00:00:00Z')")
sid = c.execute('SELECT MAX(id) FROM cal_subs').fetchone()[0]
c.execute('INSERT INTO cal_events(sub_id,uid,title,all_day,start,"end",d0,d1) VALUES(?,?,?,?,?,?,?,?)', (sid, 'm1', 'Home match', 1, '${D}', '${D}', '${D}', '${D}'))
c.commit(); c.close()`);
  for (const [ws, want, not] of [['private', [TP.id], [TO.id]], [`org:${ORG}`, [TO.id], [TP.id]], ['all', [TO.id, TP.id], []]]) {
    await call(CA, 'PATCH', '/api/settings', {workspace: ws});
    const w = await boot({user: 'alice', hash: 'cal', ls: {'tasks.calMode': '"month"'}}), d = w.document;
    const cell = () => d.querySelector(`#view .cell[data-day="${D}"]`);
    const ids = () => [...(cell()?.querySelectorAll('.ev[data-id]') || [])].map(x => +x.dataset.id);
    check(await until(() => want.every(id => ids().includes(id))), `#5468 ${ws}: the workspace's dated task is in the month ` + JSON.stringify(ids()) + ' ' + w.eval(`JSON.stringify({ws: wsCur(), cell: !!document.querySelector('#view .cell[data-day="${D}"]'), route: S.route?.key, n: S.tasks.size, t: [...S.tasks.values()].filter(t => t.due).map(t => [t.id, t.list_id, listById(t.list_id)?.org_id, wsHidden(t), cvxTaskOn(t)]), sel: S.calMonth})`));
    check(not.every(id => !ids().includes(id)), `#5468 ${ws}: the other workspace's task is not ` + JSON.stringify(ids()));
    const sub = await until(() => [...(cell()?.querySelectorAll('.cev') || [])].find(x => /Home match/.test(x.textContent)));
    check(sub && sub.querySelector('.cevsub[aria-label="Subscribed calendar"]'), `#5468 ${ws}: the subscribed calendar's event shows, with its mark`);
    // into the task and back: the month stays as it was
    if (want[0] && cell()?.querySelector(`.ev[data-id="${want[0]}"]`)) {
      click(w, cell().querySelector(`.ev[data-id="${want[0]}"]`));
      check(await until(() => d.querySelector(`#detail:not(.hidden) [data-id="${want[0]}"], #detail:not(.hidden)`) && w.eval('S.sel') === want[0]), `#5468 ${ws}: the task opens from the calendar`);
      w.eval('closeDetail()');
      check(await until(() => !w.eval('S.sel') && want.every(id => ids().includes(id))), `#5468 ${ws}: back in the month, the task still there`);
    }
    w.close();
  }
  await call(CA, 'PATCH', '/api/settings', {workspace: 'all'});
  // a person without an organisation: every own dated task shows (Private is all they have)
  const BL = await call(CB, 'POST', '/api/lists', {name: 'Errands'});
  const TB = await call(CB, 'POST', '/api/tasks', {title: 'Pick up the parcel', list_id: BL.id, due: D});
  const TI = await call(CB, 'POST', '/api/tasks', {title: 'Call the landlord', due: D});
  {
    const w = await boot({user: 'bob', hash: 'cal', ls: {'tasks.calMode': '"month"'}}), d = w.document;
    const ids = () => [...(d.querySelector(`#view .cell[data-day="${D}"]`)?.querySelectorAll('.ev[data-id]') || [])].map(x => +x.dataset.id);
    check(await until(() => ids().includes(TB.id) && ids().includes(TI.id)), '#5468 without an organisation: list and inbox task in the month ' + JSON.stringify(ids()));
    w.close();
  }

  // ================= #5460: the event window in the lower half of the month
  const signIn = (ev, user) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  // the open window and one button in it: rects, and whether the button is the element at its own centre (in sight, not covered)
  const geo = sel => `(() => { const p = document.querySelector('#pop'), b = p.querySelector(${JSON.stringify(sel)}); if (!b) return null;
    const pr = p.getBoundingClientRect(), br = b.getBoundingClientRect(), cx = br.left + br.width / 2, cy = br.top + br.height / 2, at = document.elementFromPoint(cx, cy);
    return {pb: Math.round(pr.bottom), pt: Math.round(pr.top), H: innerHeight, bt: Math.round(br.top), bb: Math.round(br.bottom), hit: !!(at && at.closest(${JSON.stringify(sel)}) === b), cx: Math.round(cx), cy: Math.round(cy),
      acts: [...p.querySelectorAll('.cevact:not(.apdraftact) [data-evp]')].map(x => x.dataset.evp), flip: !!p.querySelector('[data-act="cvx-today-flip"]')}; })()`;
  const openChip = async (ev, until) => {
    await ev(`(() => { closePop(); S.calMode = 'month'; S.calSel = '${LAST}'; renderView(); return 1; })()`);
    const at = await until(`(() => { const c = [...document.querySelectorAll('#view .cev')].find(x => /Review late/.test(x.textContent + (x.title || ''))); if (!c) return null; const r = c.getBoundingClientRect(); return {top: Math.round(r.top), H: innerHeight}; })()`);
    check(at && at.top > at.H / 2, '#5460: the event stands in the lower half of the window ' + JSON.stringify(at));
    await ev(`(() => { const c = [...document.querySelectorAll('#view .cev')].find(x => /Review late/.test(x.textContent + (x.title || ''))); c.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true})); return 1; })()`);
    return until(`!!document.querySelector('#pop:not(.hidden) .evpfoot')`);
  };
  const tap = (cmd, ctx, x, y) => cmd('input.performActions', {context: ctx, actions: [{type: 'pointer', id: 'm1', parameters: {pointerType: 'mouse'},
    actions: [{type: 'pointerMove', x, y}, {type: 'pointerDown', button: 0}, {type: 'pointerUp', button: 0}]}]}).then(() => cmd('input.releaseActions', {context: ctx}));

  await firefox(async ({cmd, ev, ctx, nav, shot, until}) => {
    for (const [user, width] of [['alice', 1280], ['alice', 820], ['bob', 1280], ['bob', 820]]) {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width, height: 800}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); localStorage.setItem('tasks.calMode', '"month"'); return 1; })()`);
      await signIn(ev, user);
      await nav(B + '#cal');
      await until(`typeof evPop === 'function' && typeof placePop === 'function' && !!document.querySelector('#view .calbar')`, {timeout: 30000});
      check(await openChip(ev, until), `#5460 ${user} ${width}: the window opens with its details`);
      const sel = user === 'alice' ? '[data-evp="edit"]' : '[data-evps="accepted"]';
      const g = await ev(geo(sel));
      check(g && g.pb <= g.H && g.pt >= 0, `#5460 ${user} ${width}: the window ends inside the browser window ` + JSON.stringify(g));
      check(g && g.bt >= 0 && g.bb <= g.H && g.hit, `#5460 ${user} ${width}: ${sel} is in sight and takes the click ` + JSON.stringify(g));
      check(g && !g.flip, `#5460 ${user} ${width}: no "Hide on Today" in the event window`);
      if (user === 'alice') check(g && g.acts.join() === 'edit,prep,del', `#5460 ${width}: Edit - Preparation task - Delete (Delete last) ` + JSON.stringify(g && g.acts));
      await shot(`p2800-a-pop-${user}-${width}.png`);
      if (g && g.hit) {  // a real click on the spot: Edit opens the editor, Accept is sent
        await tap(cmd, ctx, g.cx, g.cy);
        if (user === 'alice') check(await until(`[...document.querySelectorAll('.modal h3')].some(h => /Edit event/.test(h.textContent))`), `#5460 ${width}: Edit opens the editor`);
        else check(await until(async () => (await call(CB, 'GET', `/api/events/${EV.id}`)).partstat === 'accepted'), `#5460 ${width}: Accept was sent`);
        if (user === 'bob') await call(CB, 'POST', `/api/events/${EV.id}/rsvp`, {partstat: 'needs-action'});
      }
    }
  });

  console.log(`p2800_a_cal_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
