// 2.138.3 UI tests, part B, own container (start.sh). Invented data only.
// jsdom:
// - #2407: "Edit organisation" lists the people as rows like Users (avatar, name, user name, "Admin" for server admins) with
//   a search (name, user name, e-mail) and the filter Members (default) / All; per row a Member and an Admin box, Admin only
//   active for members, untick Member takes Admin along; the counter "N members · M admins"; Save sends members / admins;
//   the symbol field has no emoji placeholder (app icon preview), the domain hint sits under its field; "New organisation"
//   has no member list
// Firefox (desktop + narrow): the list scrolls inside the dialog, head and foot stay; rows are at least 2.75rem high
// P4: an organisation is managed by the server admin; a person without an organisation has no such dialog (no new route)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21382_b_ui', check, shots: 'P21382B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21382B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); j.http = r.status; return j; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const change = (w, el) => el && el.dispatchEvent(new w.Event('change', {bubbles: true}));
const tick = (w, el, on) => { if (!el) return; el.checked = on; change(w, el); };
const typeIn = (w, el, v) => { if (!el) return; el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };
const EMOJI = /\p{Extended_Pictographic}/u;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab'});
  const me = (await call('GET', '/api/state')).me.id;
  const mk = (u, n, mail, extra = {}) => call('POST', '/api/users', {username: u, display_name: n, password: 'password123', email: mail, ...extra}).then(j => j.id);
  const BOB = await mk('bob', 'Bob Builder', 'bob@example.com');
  const CAROL = await mk('carol', 'Carol', 'carol.x@example.com');
  const DAVE = await mk('dave', 'Dave', 'dave@example.com', {is_admin: true});
  const ERIN = await mk('erin', 'Erin', 'erin@example.com');
  check(BOB && CAROL && DAVE && ERIN, 'four more people');
  const ORG = (await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me, domains: 'example.org'})).id;
  const p0 = await call('PATCH', `/api/admin/orgs/${ORG}`, {members: [me, BOB, DAVE], admins: [me]});
  check(p0.http === 200, 'org members prepared ' + p0.http);
  const orgOf = async () => ((await call('GET', '/api/admin/orgs')).orgs || []).find(o => o.id === ORG);

  // ================= #2407: the member list (jsdom)
  let w = await boot({user: 'alice', hash: 'inbox'}), d = w.document;
  await until(() => w.eval(`typeof orgModal === 'function'`), 40);
  await w.eval(`S.orgs = []; window.__done = 0; orgModal({id: ${ORG}}, () => { window.__done++; })`);
  let md = await until(() => d.querySelector('.modal.ogmodal'), 40);
  check(!!md, '#2407: the dialog opens');
  const list = () => md.querySelector('#og-list');
  const rows = () => [...md.querySelectorAll('#og-list [data-ogrow]')].map(x => +x.dataset.ogrow);
  check(md && !md.querySelector('.fperson') && !md.querySelector('#og-adm'), '#2407: no person buttons, no second admin wall');
  check(rows().sort().join() === [me, BOB, DAVE].sort().join(), '#2407: filter Members (default) shows the members ' + rows());
  check(md?.querySelector('#og-flt')?.value === 'mem', '#2407: the filter starts on Members');
  const bobRow = md?.querySelector(`[data-ogrow="${BOB}"]`);
  check(bobRow && bobRow.classList.contains('mrow') && bobRow.querySelector('.avatar') && /Bob Builder/.test(bobRow.querySelector('.n')?.textContent || '') && /bob/.test(bobRow.querySelector('.n .muted')?.textContent || ''), '#2407: a row = avatar, name, user name (like Users)');
  // 2.364.0 C (#3041): one role vocabulary: a server admin is "Manages the server" (Admin = the organisation's role)
  check(/Manages the server/.test(md?.querySelector(`[data-ogrow="${DAVE}"] .n .muted`)?.textContent || '') && !/Manages the server/.test(bobRow?.querySelector('.n .muted')?.textContent || ''), '#2407: a server admin is marked "Manages the server" in the row');
  check(md?.querySelector('#og-cnt')?.textContent === '3 members · 1 admin', '#2407: counter ' + md?.querySelector('#og-cnt')?.textContent);
  // the boxes
  const mBox = id => md.querySelector(`[data-ogm="${id}"]`), aBox = id => md.querySelector(`[data-oga="${id}"]`);
  check(mBox(BOB)?.checked && !aBox(BOB)?.checked && !aBox(BOB)?.disabled && aBox(me)?.checked, '#2407: Member / Admin boxes reflect the organisation');
  // filter All, search
  const flt = md.querySelector('#og-flt'); flt.value = 'all'; change(w, flt);
  check(rows().length === 5, '#2407: filter All lists everyone ' + rows().length);
  check(!mBox(CAROL)?.checked && aBox(CAROL)?.disabled && aBox(CAROL)?.closest('.ogchk')?.classList.contains('off'), '#2407: Admin is inactive for a non-member');
  typeIn(w, md.querySelector('#og-q'), 'carol.x@');
  check(rows().join() === String(CAROL), '#2407: the search finds by e-mail');
  typeIn(w, md.querySelector('#og-q'), 'BUILD');
  check(rows().join() === String(BOB), '#2407: the search finds by name (any case)');
  typeIn(w, md.querySelector('#og-q'), 'erin');
  check(rows().join() === String(ERIN), '#2407: the search finds by user name');
  typeIn(w, md.querySelector('#og-q'), 'nobody-here');
  check(!rows().length && /Nothing found/.test(list()?.textContent || ''), '#2407: nothing found');
  typeIn(w, md.querySelector('#og-q'), '');
  // Member on -> Admin active; Admin on; Member off takes Admin along
  tick(w, mBox(CAROL), true);
  check(!aBox(CAROL).disabled && !aBox(CAROL).closest('.ogchk').classList.contains('off'), '#2407: ticking Member makes Admin active');
  tick(w, aBox(CAROL), true);
  check(md.querySelector('#og-cnt').textContent === '4 members · 2 admins', '#2407: counter follows ' + md.querySelector('#og-cnt').textContent);
  tick(w, aBox(BOB), true);
  tick(w, mBox(BOB), false);
  check(!aBox(BOB).checked && aBox(BOB).disabled, '#2407: unticking Member takes Admin along');
  check(md.querySelector('#og-cnt').textContent === '3 members · 2 admins', '#2407: counter after taking Bob out ' + md.querySelector('#og-cnt').textContent);
  tick(w, mBox(ERIN), true);
  // the head: symbol without emoji placeholder, domain hint under its field
  const icon = md.querySelector('#og-icon');
  check(icon && !EMOJI.test(icon.getAttribute('placeholder') || '') && md.querySelector('#og-icprev svg'), '#2407: the symbol field has no emoji placeholder, an app icon preview');
  const dom = md.querySelector('#og-dom'), domh = md.querySelector('#og-domh');
  check(dom && domh && dom.parentElement === domh.parentElement && dom.parentElement.classList.contains('ogfld') && dom.nextElementSibling === domh && dom.getAttribute('aria-describedby') === 'og-domh', '#2407: the domain hint sits under the field');
  // Save
  md.querySelector('[data-m="save"]').click();
  await until(() => !d.querySelector('.modal.ogmodal'), 40);
  const o1 = await until(async () => { const o = await orgOf(); return o && o.members.includes(ERIN) ? o : null; }, 40);
  check(o1 && [...o1.members].sort().join() === [me, CAROL, DAVE, ERIN].sort().join(), '#2407: Save sends the members ' + (o1 && o1.members));
  check(o1 && [...o1.admins].sort().join() === [me, CAROL].sort().join(), '#2407: Save sends the admins (only members) ' + (o1 && o1.admins));
  check(w.eval('__done') === 1, '#2407: the caller is told');
  // the filter Members after saving, Cancel sends nothing
  await w.eval(`orgModal({id: ${ORG}}, () => {})`);
  md = await until(() => d.querySelector('.modal.ogmodal'), 40);
  check(rows().sort().join() === [me, CAROL, DAVE, ERIN].sort().join(), '#2407: reopened: the new members');
  tick(w, mBox(DAVE), false);
  md.querySelector('[data-m="close"]').click();
  await sleep(400);
  check(((await orgOf()).members || []).includes(DAVE), '#2407: Cancel keeps everything');
  // the symbol preview follows the typed symbol; with a picture the picture is shown
  await w.eval(`orgModal({id: ${ORG}}, () => {})`);
  md = await until(() => d.querySelector('.modal.ogmodal'), 40);
  typeIn(w, md.querySelector('#og-icon'), 'AB');
  check(/AB/.test(md.querySelector('#og-icprev')?.textContent || ''), '#2407: the preview shows the typed symbol');
  md.querySelector('[data-m="close"]').click(); await sleep(300);
  // "New organisation": no member list
  await w.eval(`orgModal(null, () => {})`);
  md = await until(() => d.querySelector('.modal.ogmodal'), 40);
  check(md && !md.querySelector('#og-list') && !md.querySelector('#og-q') && /first member/.test(md.textContent), '#2407: New organisation has no member list');
  check(md && !EMOJI.test(md.querySelector('#og-icon')?.getAttribute('placeholder') || ''), '#2407: New organisation: no emoji placeholder either');
  md?.querySelector('[data-m="close"]')?.click();
  w.close();

  // ================= #2407: layout (Firefox): the list scrolls inside the dialog, head and foot stay
  for (let i = 0; i < 26; i++) await mk(`p${i}`, `Person ${String(i).padStart(2, '0')}`, `p${i}@example.com`);
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  for (const [vw, vh, tag] of [[1280, 800, 'desktop'], [390, 760, 'narrow']]) {
    await firefox(async ({cmd, ev, ctx, nav, shot}) => {
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: vh}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      await ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(() => 1)`);
      await nav(B + '#inbox');
      await ready(ev, `typeof orgModal === 'function' && !!document.getElementById('app')`, 80);
      await ev(`(() => { orgModal({id: ${ORG}}, () => {}); return 1; })()`);
      await ready(ev, `!!document.querySelector('.modal.ogmodal #og-list .ogrow')`);
      await ev(`(() => { const f = document.querySelector('#og-flt'); f.value = 'all'; f.dispatchEvent(new Event('change', {bubbles: true})); return 1; })()`);
      await sleep(300);
      const m = await ev(`(() => { const c = document.querySelector('.modal.ogmodal .card'), l = c.querySelector('#og-list'), f = c.querySelector('.foot'), h = c.querySelector('h3');
        const cr = c.getBoundingClientRect(), fr = f.getBoundingClientRect(), r = l.querySelector('.ogrow').getBoundingClientRect(), b = l.querySelector('.ogchk').getBoundingClientRect();
        return {lscroll: l.scrollHeight > l.clientHeight + 4, cscroll: c.scrollHeight - c.clientHeight, footIn: fr.bottom <= cr.bottom + 1 && fr.top >= cr.top, headTop: h.getBoundingClientRect().top >= cr.top - 1,
          rowH: r.height, boxH: b.height, inRow: [...l.querySelectorAll('.ogrow')].slice(0, 6).every(x => { const xr = x.getBoundingClientRect(); return [...x.querySelectorAll('.ogchk')].every(k => { const kr = k.getBoundingClientRect(); return kr.top >= xr.top - 1 && kr.bottom <= xr.bottom + 1; }); }), rem: parseFloat(getComputedStyle(document.documentElement).fontSize), wide: c.scrollWidth <= c.clientWidth + 1}; })()`);
      check(m.lscroll, `#2407 ${tag}: the long list scrolls inside`);
      check(m.cscroll <= 2 && m.footIn && m.headTop, `#2407 ${tag}: head and foot stay in view (card overflow ${m.cscroll})`);
      check(m.rowH >= 2.75 * m.rem - 0.5 && m.boxH >= 2.75 * m.rem - 0.5, `#2407 ${tag}: rows and boxes are at least 2.75rem high (${m.rowH}, ${m.boxH})`);
      check(m.wide, `#2407 ${tag}: no sideways scrolling`);
      check(m.inRow, `#2407 ${tag}: the boxes stay inside their row (a wrapped row grows)`);
      await shot(`p21382-b-${tag}.png`);
    }, tag === 'narrow' ? true : false);
  }

  console.log(`p21382_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
