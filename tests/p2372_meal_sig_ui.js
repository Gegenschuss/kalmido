// kalmido-suite: fresh
// 2.372.0 (#3316) UI test: a staff member (office group "Staff", no correspondence) approves an entertainment receipt as its
// host and has no signature picture yet. Own container (start.sh), Firefox desktop.
// - the approve dialog offers "Add signature picture" instead of the switch
// - the button opens the signature dialog with the drawing field, without greeting and name of the letters
// - drawn and saved: the receipt dialog stays open and now shows "With my signature" (on); approving puts the picture on (sign_image 1)
// Invented names only; the strokes are drawn by the test.
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2372_meal_sig_ui', check, shots: 'P2372_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2372_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,travel';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const sam = await call(CA, 'POST', '/api/users', {username: 'sam', display_name: 'Sam Staff', password: 'password123', email: 'sam@example.com'});
  check(sam.id, 'sam created ' + sam.http);
  check((await call(CA, 'PUT', `/api/orgs/${org.id}/members`, {email: 'sam@example.com', role: 'member'})).http < 300, 'sam is a member');
  check((await call(CA, 'PUT', `/api/office/rights/people/${sam.id}`, {groups: ['tpl:staff']})).http < 300, 'sam in the group Staff');
  const CS = await login('sam');
  await call(CS, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${org.id}`});
  check((await call(CS, 'GET', '/api/office/letters/profile')).http === 403, 'sam has no correspondence (letters profile 403)');
  const y = String(new Date().getFullYear());
  const meal = await call(CA, 'POST', '/api/office/meals', {date: `${y}-01-10`, place_name: 'Bistro Beispiel', place_address: 'Hauptstraße 5, 12345 Musterstadt',
    occasion: 'Planning of the trade fair stand', host: {id: sam.id}, guests: [{name: 'Otto Beispiel', extra: 'Example AG'}], amounts: [{kind: 'food', rate: 19, gross: 59.5}]});
  check(meal.http === 201, 'a draft receipt with sam as host ' + meal.http);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const getJ = url => `fetch('${url}', {headers: {'X-Requested-With': 'kalmido'}}).then(r => r.json())`;
  const clk = sel => `(() => { const x = document.querySelector('${sel}'); if (!x) return 0; x.click(); return 1; })()`;
  const pad = `(() => { const c = document.querySelector('.modal canvas.lt-pad'); if (!c) return null; const r = c.getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height}; })()`;

  await firefox(async ({cmd, ev, ctx, nav, shot, drag}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'sam');
    await nav(B + '#office/meals');
    // CI of 2.496.1: bw_html empties BW.data once when it first sees the office area (BW.oid); a load before that was thrown away
    // between this check and bw_modal below ("BW.data is null"), so only data of the area the tab has already taken count
    check(await ready(ev, `typeof BW === 'object' && !!OFC.info && BW.oid === OFC.info.org_id && (BW.data || (BW.loading || bw_load(), false)) && BW.data.my_sig === 0 && BW.data.meals.some(m => m.id === ${meal.id})`, 80), 'the receipts: sam sees the receipt, no picture yet (my_sig 0)');
    await ev(`(() => { bw_modal(BW.data.meals.find(m => m.id === ${meal.id})); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal [data-bwm="approve"]')`), 'the approve dialog for the host');
    check(await ready(ev, `(() => { const b = document.querySelector('.modal [data-bwm="sigset"]'); return !!b && !b.closest('[hidden]') && !!document.querySelector('.modal .bwsigon[hidden]'); })()`),
      'without a picture: "Add signature picture", the switch hidden');
    await shot('p2372-add-sig.png');
    await ev(clk('.modal [data-bwm="sigset"]'));
    check(await ready(ev, `document.querySelectorAll('.modal').length === 2 && !!document.querySelector('.modal canvas.lt-pad')`), 'the signature dialog opens on top, with the drawing field');
    check(await ev(`!document.querySelector('#lt-pgreet') && !document.querySelector('#lt-pname')`), 'only the picture: no greeting / name of the letters');
    const p = await ev(pad);
    await drag(p.x + 30, p.y + 50, 140, 25, 'mouse');
    await drag(p.x + 60, p.y + 30, 90, 50, 'mouse');
    await ev(`(() => { const m = [...document.querySelectorAll('.modal')].pop(); m.querySelector('[data-m="save"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.modal').length === 1 && !!document.querySelector('.modal.bwdlg')`, 60), 'saved: the signature dialog closes, the receipt stays open');
    check(await ready(ev, `${getJ('/api/office/meals/signature')}.then(s => s.has_image === true)`), 'the own picture is stored');
    check(await ready(ev, `(() => { const c = document.querySelector('.modal #bw-sig'); return !!c && c.checked && !c.closest('[hidden]') && !!document.querySelector('.modal .bwsigoff[hidden]'); })()`),
      'now "With my signature" (on), the button gone');
    await shot('p2372-with-sig.png');
    await ev(clk('.modal [data-bwm="approve"]'));
    check(await ready(ev, `${getJ('/api/office/meals/' + meal.id)}.then(m => m.status === 'approved' && m.sign_image === 1)`, 60), 'approved with the picture (sign_image 1)');
  });

  console.log(`p2372_meal_sig_ui: ${ok} passed, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL:', e); process.exit(1); });
