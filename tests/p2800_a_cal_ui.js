// 2.800.0 UI test, part A (calendar polish): own container (start.sh), jsdom + Firefox (real layout). Invented names only.
// kalmido-suite: fresh
// - #5460: an event in the lower half of the month opens its window after the details are loaded inside the browser window
//   (1280x800 and 820x800): its lower edge stays in the window, Edit (owner) and Accept (invited person) are in sight and take
//   the click; the actions run Edit - Preparation task - Delete (Delete last); "Hide on Today" is no longer in the window
// freelancer-matrix: events (alice has no organisation: her private workspace)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2800_a_cal_ui', check, shots: 'P2800A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
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

  // ================= #5460: the event window in the lower half of the month
  const now = new Date(), LAST = dstr(new Date(now.getFullYear(), now.getMonth() + 1, 0));  // the month's last day: its lowest rows
  const W = await call(CA, 'POST', '/api/evcals', {name: 'Work', color: '#2dd4bf'});
  const long = Array.from({length: 14}, (_, i) => `Point ${i + 1}: go through the cut list with the studio and note what is left.`).join('\n');
  const EV = await call(CA, 'POST', '/api/events', {title: 'Review late in the month', cal_id: W.id, start: `${LAST}T10:00`, end: `${LAST}T11:00`,
    location: 'Studio 2, back entrance', description: long, attendees: [{user_id: BOB}], reminders: [30]});
  check(EV.id, '#5460: the event on the server ' + EV.http);

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
