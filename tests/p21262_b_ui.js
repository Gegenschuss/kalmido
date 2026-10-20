// 2.126.2 part B (#2355): a person share of a knowledge page shows in the guest's News ("… shared the page … with you"),
// and the item opens the pages view on "Shared with me" (390 px)
const {execFileSync} = require('child_process');
const path = require('path');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21262_b_ui', check, shots: 'P21262B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21262B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const FEAT = 'cal,comments,collab,wiki';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const DAVE = (await call('POST', '/api/users', {username: 'dave', display_name: 'Dave Customer', password: 'password123', email: 'dave@example.com'})).id;
  const DK = await login('dave');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, DK);
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Customer/Guide', body: 'Read this first.'})).id;
  const s = await call('POST', '/api/wiki/shares', {page_id: PG, kind: 'person', user_id: DAVE});
  check(s.status === 201, 'setup: the page shared with Dave ' + JSON.stringify(s));

  const ffLogin = async ({ev, nav}, user) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${user}', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('#top h1')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  const wait = async (ev, js, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(js).catch(() => false)) return true; await sleep(200); } return false; };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o, 'dave') === 200, 'login dave');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#news'); await ready(ev); await sleep(900);
    const sel = `[...document.querySelectorAll('#view .nitem')].find(x => /Alice shared the page Guide with you/.test(x.textContent))`;
    check(await wait(ev, `!!${sel}`), '390: the News item "Alice shared the page Guide with you" ' + await ev(`document.querySelector('#view')?.textContent.slice(0, 300)`));
    check(await ev(`!/Read this first/.test(${sel}?.textContent || '')`), '390: no page text in the item');
    await shot('p21262-b-390-news.png');
    await ev(`(() => { ${sel}.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true})); return 1; })()`);
    check(await wait(ev, `S.route.mod === 'wiki' && !!document.querySelector('.wshside [data-wsh-open="${PG}"]')`), '390: the item opens the pages view with Shared with me');
    check(await wait(ev, `!!document.activeElement?.closest('.wshside')`), '390: the focus is in Shared with me');
    await shot('p21262-b-390-shared.png');
  }, true);

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
