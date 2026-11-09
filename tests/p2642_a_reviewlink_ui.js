// 2.642.0 part A UI test (#4772), own container (start.sh): the client links in the sign-off dialog (mobile layout).
// kalmido-suite: fresh
// - a sign-off with two versions: the dialog offers "Valid until (optional)" and "The client may also see the older versions"
// - "Create client link" with the tick: the link runs with show_old, the list says "older versions too"
// - a second link without the tick: both run at once, each with its own Copy / Switch off
// - a client's comment (through the link, no account) shows as "Name (Guest)"
// P2642AUI_NOSTART=1 = the server already runs.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2642AUI_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 150 : 15000, step: 150});

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Alpha', lang: 'en', collab_all: true, modules: ['comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'collab,comments,clients,videos'});
  const L = await call('POST', '/api/lists', {name: 'Imagefilm', kind: 'project'});
  const T = await call('POST', '/api/tasks', {title: 'Rohschnitt', list_id: L.id});
  const R = await call('POST', '/api/videos', {task_id: T.id, url: 'https://vimeo.com/123456789', title: 'Imagefilm Schnitt'});
  const R2 = await call('POST', `/api/videos/${R.id}/versions`, {url: 'https://vimeo.com/123456790'});
  check(R.id && R2.versions && R2.versions.length === 2, 'a sign-off with two versions');
  // a client's comment through a link (no account)
  const S0 = await call('POST', `/api/videos/${R.id}/signoff`, {expires: null});
  const tok = (S0.url || '').split('/s/q/')[1] || '';
  const pg = await (await fetch(B + 's/q/' + tok, {headers: {'Accept-Language': 'en'}})).text();
  const f = (pg.match(/name="f" value="([0-9a-f]+)"/) || [])[1], v = (pg.match(/name="v" value="(\d+)"/) || [])[1];
  const pr = await fetch(B + `s/q/${tok}/comments`, {method: 'POST', redirect: 'manual', headers: {'Content-Type': 'application/x-www-form-urlencoded'},
    body: new URLSearchParams({f: f || '', v: v || '', name: 'Erika Gast', text: 'Bitte heller', at: '00:05'}).toString()});
  check(pr.status === 303, 'the client comments through the link ' + pr.status);
  await call('POST', `/api/videos/${R.id}/signoffs/${S0.id}/revoke`);

  const w = await boot({user: 'alice', mobile: true, hash: 't/' + T.id}), d = w.document;
  await until(() => w.eval("typeof vdr_open === 'function'"));
  w.eval(`vdr_open(${R.id})`);
  const dlg = await until(() => d.querySelector('.vdrdlg .vdrsig .vdrsignew') && d.querySelector('.vdrdlg'));
  const sig = dlg && dlg.querySelector('.vdrsig');
  // 2.766.0 (#5321): the expiry is the app's own date picker (ux1_ui: no native date inputs)
  check(sig && sig.querySelector('input.vdrsigdate[type="hidden"][data-dp="date"]') && sig.querySelector('.dpbtn[data-dpfor="vdrsigdate"]') && sig.querySelector('input.vdrsigold') && /older versions/.test(sig.textContent),
    'the dialog offers the expiry and "older versions too" ' + (sig && sig.textContent.replace(/\s+/g, ' ').slice(0, 300)));
  const cust = [...dlg.querySelectorAll('.vdrc.cust b')].map(b => b.textContent);
  check(cust.includes('Erika Gast (Guest)'), 'the client comment shows as Name (Guest) ' + JSON.stringify(cust));
  sig.querySelector('input.vdrsigold').checked = true;
  sig.querySelector('[data-vdr="signew"]').click();
  const live1 = await until(async () => { const x = (await call('GET', `/api/videos/${R.id}`)).signoffs || []; return x.filter(s => s.live).length === 1 && x; });
  check(live1 && live1.find(s => s.live).show_old === true, 'the link runs with the older versions');
  check(await until(() => /older versions too/.test(d.querySelector('.vdrdlg .vdrsig .sglist')?.textContent || '')), 'the list says "older versions too"');
  d.querySelector('.vdrdlg .vdrsig [data-vdr="signew"]').click();
  const live2 = await until(async () => ((await call('GET', `/api/videos/${R.id}`)).signoffs || []).filter(s => s.live).length === 2);
  check(live2, 'a second link: both run');
  check(await until(() => d.querySelectorAll('.vdrdlg .vdrsig [data-vdr="sigstop"]').length === 2), 'two running links, each with Switch off');
  check(errs.length === 0, 'no JS errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
