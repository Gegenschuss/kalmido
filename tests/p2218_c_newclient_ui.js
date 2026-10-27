// 2.218.0 C (#2804) UI test: "New client" on the phone. jsdom, invented data only:
// - the empty clients page: one "New client", no filters / selection / e-mail filing, the import way
// - the new sheet is short (name, e-mail, city), the rest under "More details" (values stay while it folds), "Add" in a sticky foot
// - the symbol is picked from app icons ("ic:" value), a saved emoji still shows; phone and desktop width, private (no organisation) too
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return r.json().catch(() => ({})); };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const typeIn = (w, el, v) => { el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments', 'contacts']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,contacts,office,clients,time'});

  for (const mobile of [true, false]) {
    const tag = mobile ? 'phone' : 'desktop';
    // ---- empty page
    let w = await boot({hash: 'clients', mobile}); let d = w.document;
    await until(() => d.querySelector('#view .msclempty'), 60);
    check(!d.querySelector('#view .ctbar') && !d.querySelector('#mscl-arch') && !d.querySelector('#mscl-dsb') && !d.querySelector('a[href="#mailhub"]'), tag + ': empty page without filters / e-mail filing');
    check(d.querySelectorAll('#view [data-act="client-new"]').length === 1, tag + ': "New client" only once');
    // ---- the short sheet (private: no organisation)
    w.eval("clientModal(null, {org_id: null})"); await sleep(100);
    const md = d.querySelector('.modal.cldlg');
    const more = md.querySelector('details#cl-more');
    check(md && more && !more.open, tag + ': details folded');
    const vis = [...md.querySelectorAll('input:not([type=hidden]),textarea,select')].filter(x => !more.contains(x)).map(x => x.id);
    check(JSON.stringify(vis) === JSON.stringify(['cl-name', 'cl-email', 'clb-city']), tag + ': short form = name, e-mail, city: ' + vis);
    check(more.querySelector('#cl-phone') && more.querySelector('#cl-note') && more.querySelector('#clb-street') && more.querySelector('#cl-nx') && !more.querySelector('#clb-city'), tag + ': the rest sits under More details');
    check(md.querySelector('.foot.clfoot [data-m="save"]'), tag + ': "Add" in the sticky foot');
    check(md.querySelectorAll('[data-clico]').length > 10 && md.querySelector('[data-clico] svg') && !/🏢/.test(md.innerHTML), tag + ': app icons, no emoji');
    md.querySelector('[data-clico="ic:home"]').click();
    check(md.querySelector('#cl-icon').value === 'ic:home' && md.querySelector('[data-clico="ic:home"]').getAttribute('aria-pressed') === 'true', tag + ': icon picked');
    typeIn(w, md.querySelector('#cl-name'), 'Phone Test ' + tag); typeIn(w, md.querySelector('#cl-email'), `p-${tag}@example.com`); typeIn(w, md.querySelector('#clb-city'), 'Teststadt');
    more.open = true; typeIn(w, md.querySelector('#cl-phone'), '123'); more.open = false;
    md.querySelector('[data-m="save"]').click();
    const cl = await until(async () => ((await call('GET', '/api/clients?archived=1')).clients || []).find(x => x.name === 'Phone Test ' + tag), 40);
    check(cl && cl.icon === 'ic:home' && cl.email === `p-${tag}@example.com` && cl.phone === '123', tag + ': everything saved, also the folded phone: ' + JSON.stringify(cl && [cl.icon, cl.email, cl.phone]));
    w.close();
    // ---- the list shows the app icon, an old emoji still shows
    await call('PATCH', `/api/clients/${cl.id}`, {icon: '☕'});
    w = await boot({hash: 'clients', mobile}); d = w.document;
    await until(() => d.querySelector('#view .ctrow'), 60);
    check(d.querySelector('#view #mscl-arch') && d.querySelector('#view .ctrow .mscav')?.textContent.includes('☕'), tag + ': filters back with clients; emoji still shown');
    await call('PATCH', `/api/clients/${cl.id}`, {icon: 'ic:star'});
    w.eval('ms_clDirty && ms_clDirty()'); w.close();
    w = await boot({hash: 'clients', mobile}); d = w.document;
    await until(() => d.querySelector('#view .ctrow'), 60);
    check(d.querySelector('#view .ctrow .mscav svg') && !/ic:star/.test(d.querySelector('#view .ctrow').textContent), tag + ': app icon in the list');
    // edit sheet: unchanged order, not folded, the picked icon marked
    w.eval(`clientModal(S.clients.find(c => c.id === ${cl.id}) && Object.assign({}, S.clients.find(c => c.id === ${cl.id}), {billing: {}}))`); await sleep(100);
    const ed = d.querySelector('.modal.cldlg');
    check(ed && !ed.querySelector('#cl-more') && ed.querySelector('#cl-phone') && ed.querySelector('[data-clico="ic:star"][aria-pressed="true"]'), tag + ': edit sheet is the full form');
    w.close();
    for (const c of ((await call('GET', '/api/clients?archived=1')).clients || [])) await call('DELETE', `/api/clients/${c.id}`);
  }
  console.log(`p2218_c_newclient_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
