// 2.120.0 UI tests, part D (#2089), own container (start.sh), Firefox (desktop + phone width). Invented companies and figures only.
// freelancer-matrix: office
// - the tab "Delivery notes": list, "New delivery note", editor without prices (no rate / tax / sums), title choice,
//   "Delivery note" button on a quotation / invoice (menu: delivery note / proof of service), no horizontal scrolling
// run as the admin of an organisation AND as a person without organisation
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2120_d_ui', check, shots: 'P2120D_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P2120D_NOSTART !== '1' && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const svc = (title, qty, rate) => ({kind: 'service', title, qty, unit: 'day', rate, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1});

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
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  // 2.308.0 (#3249): a sign-in that hangs in the browser ends after 30 s with a name (rare, seen once under load), and the
  // same sign-in from here tells whether the server answers (server or browser side)
  // 2.358.0 A (#3249): when the server answers the same sign-in from here, the browser's request alone hung: once more
  // (only this network step, never a check) on a freshly loaded page
  const signIn = async (ev, nav, u) => {
    const once = () => ev(`(() => { const ac = new AbortController(), t = setTimeout(() => ac.abort(), 30000); return fetch('/api/auth/login', {method: 'POST', signal: ac.signal, headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status, e => 'browser: ' + e.name).finally(() => clearTimeout(t)); })()`).catch(e => 'ev: ' + e.message);
    let st = await once();
    if (st !== 200) {
      const t0 = Date.now(), nr = await fetch(B + 'api/auth/login', {method: 'POST', headers: H, body: JSON.stringify({username: u, password: 'password123'}), signal: AbortSignal.timeout(30000)}).then(r => r.status, e => e.name);
      console.log(`sign-in ${u}: ${st} in Firefox, ${nr} from the test (${Date.now() - t0} ms)`);
      if (nr === 200) {
        await nav(B + 'static/icon.svg');
        st = await once();
        console.log(`sign-in ${u}: once more in Firefox on a fresh page: ${st}`);
      }
    }
    return st;
  };
  const noScroll = `document.documentElement.scrollWidth <= window.innerWidth + 1`;
  const prep = {};
  for (const [u, ck] of [['alice', CA], ['frida', CF]]) {
    const doc = await call(ck, 'POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Campaign ' + u, items: [svc('Concept', 1, 800), svc('Animation', 2, 500)]});
    check(doc.http === 201, u + ': a quotation ' + doc.http);
    const ls = await call(ck, 'POST', `/api/office/docs/${doc.id}/delivery`, {});
    check(ls.http === 201 && ls.kind === 'delivery', u + ': a delivery note ' + ls.http);
    prep[u] = {doc: doc.id, ls: ls.id};
  }
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    for (const [w, h] of [[1280, 900], [390, 844]]) for (const u of ['alice', 'frida']) {
      const tag = `${u} ${w}px: `;
      await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
      await nav(B + 'static/icon.svg');
      await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
      // 2.308.0 (#3249): a failed sign-in names itself instead of timing out in every later wait
      const st = await signIn(ev, nav, u);
      check(st === 200, tag + 'signs in ' + st);
      // the delivery note editor: positions without prices
      await nav(B + `#office/offers/${prep[u].ls}`);
      check(await ready(ev, `!!document.querySelector('.ofdeditor.ofdls .ofdit')`, 80), tag + 'the delivery note editor');
      check(await ev(`[...document.querySelectorAll('.ofdls .ofdrate, .ofdls .ofdit .ofdlt, .ofdls select[data-k="tax"]')].every(e => e.offsetParent === null)`), tag + 'no rate / tax / line total shown');
      check(await ev(`!document.querySelector('#ofd-totals') && !document.querySelector('#ofd-vat_mode') && !document.querySelector('#ofd-einvoice_format')`), tag + 'no sums, VAT or e-invoice fields');
      check(await ev(`!!document.querySelector('#ofd-delivery_title') && document.querySelector('#ofd-delivery_title').options.length === 2`), tag + 'the title choice');
      check(await ev(`!document.querySelector('[data-ofd="it-disc"]')`), tag + 'no discount button');
      check(await ev(noScroll), tag + 'editor: no horizontal scrolling');
      await shot(`p2120-d-editor-${u}-${w}.png`);
      // the list
      await nav(B + '#office/offers');
      check(await ready(ev, `!!document.querySelector('.ofdkinds [data-kind="delivery"]')`, 80), tag + 'the tab Delivery notes');
      await ev(`document.querySelector('.ofdkinds [data-kind="delivery"]').click()`);
      check(await ready(ev, `document.querySelectorAll('.ofdlist .ofdrow').length === 1 && !!document.querySelector('[data-ofd="new-ls"]')`, 80), tag + 'the list with its button');
      check(await ev(noScroll), tag + 'list: no horizontal scrolling');
      // from a quotation: the menu offers both
      await nav(B + `#office/offers/${prep[u].doc}`);
      check(await ready(ev, `!!document.querySelector('[data-ofd="to-ls"]')`, 80), tag + 'the quotation has the delivery note button');
      await ev(`document.querySelector('[data-ofd="to-ls"]').click()`);
      check(await ready(ev, `document.querySelectorAll('#pop [role="menuitem"]').length >= 2`, 40), tag + 'menu: delivery note / proof of service');
      await shot(`p2120-d-menu-${u}-${w}.png`);
      await ev(`document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape'}))`);
    }
  });
  console.log(F.length ? `FAILED ${F.length}:\n` + F.join('\n') : `p2120_d_ui: ${ok} checks passed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERR', e); process.exit(1); });
