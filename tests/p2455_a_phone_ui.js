// 2.455.0 A UI tests (Firefox, touch widths, own container via start.sh):
// #3847 the phone's open drawer stays open when the workspace is switched (with and without a kept view) and shows the new one
// #3852 at 320 px a member's name in Settings > Organisation gets the whole first line (role choice + buttons below), a receipt
//       row with labels gives the file name the whole first line; the wide view is unchanged
// freelancer-matrix: n/a (no new route; the workspace switch is the same for a person without an organisation)
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2455_a_phone_ui', check, shots: 'P2455A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2455A_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return Array.isArray(j) ? j : {...j, http: r.status}; };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {org_name: 'Studio', lang: 'en', collab_all: true, modules: ['comments', 'cal', 'office']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', workspace: 'private'});
  await call(CA, 'POST', '/api/lists', {name: 'Home'});
  const ORG = ((await call(CA, 'GET', '/api/state')).me.workspaces || [])[0]?.id;
  check(!!ORG, 'the fixture organisation ' + ORG);
  if (!ORG) throw new Error('no organisation in the fixture');

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = async o => {
    await o.nav(B + 'static/icon.svg');
    await o.ev(`(() => { localStorage.clear(); sessionStorage.clear(); return 1; })()`);
    return o.ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const drawer = `(() => ({open: !!document.querySelector('#side.open'), scrim: !document.querySelector('#scrim').classList.contains('hidden'), ws: wsCur(), hash: location.hash}))()`;
  const open = async ev => { await ev(`(() => { if (!document.querySelector('#side.open')) document.querySelector('#top .menu')?.click(); return 1; })()`); return ready(ev, `!!document.querySelector('#side.open')`, 20); };

  await firefox(async o => {
    const {cmd, ev, ctx, nav} = o;
    check(await signIn(o) === 200, 'login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + '#today');
    check(await ready(ev, `!!document.querySelector('#top .menu') && !!S.booted`, 80), 'the app is up');

    // #3847 first visit of the organisation (no kept view)
    check(await open(ev), '#3847: the drawer opens');
    await ev(`(() => { LS.set('wsView', {}); wsSet('org:${ORG}'); return 1; })()`);
    check(await ready(ev, `wsCur() === 'org:${ORG}'`, 20), '#3847: the workspace is the organisation');
    await sleep(600);
    let d = await ev(drawer);
    check(d.open && d.scrim, '#3847: no kept view: the drawer stays open ' + JSON.stringify(d));
    // a view in the organisation, then away and back: the kept view is restored, the drawer still stays
    await ev(`(() => { go('cal'); return 1; })()`);
    check(await ready(ev, `!document.querySelector('#side.open')`, 20), '#3847: an entry tapped right after a switch without a route closes the drawer');
    await open(ev);
    await ev(`(() => { wsSet('private'); return 1; })()`); await sleep(700);
    d = await ev(drawer);
    check(d.open && d.ws === 'private', '#3847: switch to Private: the drawer stays ' + JSON.stringify(d));
    await ev(`(() => { wsSet('org:${ORG}'); return 1; })()`); await sleep(900);
    d = await ev(drawer);
    check(d.open && d.scrim && d.ws === 'org:' + ORG && /cal/.test(d.hash), '#3847: kept view restored (calendar) and the drawer stays ' + JSON.stringify(d));
    check(await ev(`(() => { const t = document.querySelector('#kbar .kbsw, #side .wsbar'); return !!t && (t.textContent || '').includes('Studio'); })()`), '#3847: the switch shows the new workspace');
    // the hold does not leak: a later page change closes the drawer as before
    await ev(`(() => { go('today'); return 1; })()`); await sleep(700);
    check(!(await ev(drawer)).open, '#3847: a later page change closes the drawer again');
    // focus / Back: the drawer opened again closes with the scrim and Esc
    await open(ev);
    await ev(`(() => { document.querySelector('#scrim').click(); return 1; })()`); await sleep(300);
    check(!(await ev(drawer)).open, '#3847: the scrim still closes the drawer');
    await open(ev);
    await ev(`(() => { wsSet('private'); return 1; })()`);
    check(await ready(ev, `wsCur() === 'private' && !SBM.keep`, 20), '#3847: the hold ends with the switch');
    await ev(`(() => { history.back(); return 1; })()`);
    check(await ready(ev, `!document.querySelector('#side.open')`, 20), '#3847: Back closes the drawer after a switch');

    // #3852 at 320 x 640
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 320, height: 640}});
    await nav(B + '#today');
    await ready(ev, `!!S.booted`, 80);
    await ev(`(() => { settingsModal('org'); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.wsorg .mrow select')`, 40), '#3852: the member row is there');
    const m = await ev(`(() => { const r = document.querySelector('.wsorg .mrow'), n = r.querySelector('.n'), s = r.querySelector('select'), R = e => e.getBoundingClientRect(); return {rw: R(r).width, nw: R(n).width, nb: R(n).bottom, st: R(s).top, over: document.documentElement.scrollWidth > innerWidth + 1}; })()`);
    check(m.nw >= m.rw - 60 && m.st >= m.nb - 1, '#3852: name on its own first line, role below ' + JSON.stringify(m));
    await ev(`(() => { document.querySelectorAll('.modal').forEach(x => x.remove()); return 1; })()`);
    await nav(B + '#today');
    await ready(ev, `!!S.booted && typeof loadCss === 'function'`, 80);
    await ev(`loadCss('office').then(() => 1)`); await sleep(300);  // the office stylesheet is loaded lazily
    const r = await ev(`(() => { const ul = document.createElement('ul'); ul.id = 'p2455ul'; ul.className = 'ofclist rcl-list'; ul.style.cssText = 'position:fixed;left:0;right:0;top:0;z-index:9999;background:#000;padding:0;margin:0';
      ul.innerHTML = '<li><button type="button" class="ofcrow"><span class="ofcn"><b>Rechnung_2026_10_Beispielfirma_Dienstleistungen.pdf</b><small class="muted">12.10.2026</small></span><span class="rotag">With hints</span><span class="rotag">E-invoice</span><span class="rksum">120,00</span></button></li>';
      document.body.appendChild(ul); const row = ul.querySelector('.ofcrow'), b = row.querySelector('.ofcn b'), t = row.querySelector('.rotag'); const R = e => e.getBoundingClientRect();
      return {rw: R(row).width, bw: R(b).width, bb: R(b).bottom, tt: R(t).top, cut: b.scrollWidth > b.clientWidth + 1}; })()`);
    check(r.bw >= r.rw - 24 && r.tt >= r.bb - 1, '#3852: the file name has the first line, the labels the second ' + JSON.stringify(r));
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1000, height: 700}});
    await sleep(300);
    const w = await ev(`(() => { const row = document.querySelector('#p2455ul .ofcrow'), b = row.querySelector('.ofcn b'), t = row.querySelector('.rotag'); const R = e => e.getBoundingClientRect(); return {same: Math.abs(R(b).top - R(t).top) < R(row).height}; })()`);
    check(w.same, '#3852: wide view: still one line ' + JSON.stringify(w));
  }, true);

  console.log(`p2455_a_phone_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
