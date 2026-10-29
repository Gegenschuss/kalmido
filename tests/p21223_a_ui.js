// 2.122.3 UI tests, part A (#2333, #2335), own container (start.sh, mode workspaces), Firefox (desktop + phone width).
// Invented names and figures only.
// - #2333: a fixed cost at 0 % VAT shows one amount and "without VAT" (no net / gross), one at 19 % both amounts
// - #2335: the cash flow's fixed costs bar has no template / import buttons any more, only a quiet "Import…" link at the
//   end; the leads toolbar has no "Import CSV"; empty areas (services, subscriptions, leads, clients) link to their section
//   of Settings > Import legacy data (#office/import/<area>), which scrolls there and marks it; there the fixed costs import
//   opens the known preview dialog and the leads import its preview; a member without the office admin right sees no link
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21223_a_ui', check, shots: 'P21223A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21223A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients';
const ym = TC.today().slice(0, 7);
const CSV = 'Name;Company;E-mail\\nErika Beispiel;Beispiel Studio;erika@example.com\\n';

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
  const f19 = await call(CA, 'POST', '/api/office/fixed-costs', {label: 'Server', amount: 100, start: ym + '-01', repeat: 'monthly', category: 'IT', vat_rate: 19});
  const f0 = await call(CA, 'POST', '/api/office/fixed-costs', {label: 'Miete', amount: 900, start: ym + '-01', repeat: 'monthly', vat_rate: 0});
  check(f19.http === 201 && f0.http === 201 && f0.vat_rate === 0, 'two fixed costs ' + f19.http + ' ' + f0.http);
  const bob = await call(CA, 'POST', '/api/users', {username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.com', orgs: [org.id]});
  check(bob.http === 201 || bob.http === 200, 'a member ' + bob.http);
  const CB = await login('bob');
  await call(CB, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: `org:${org.id}`});

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const row = id => `document.querySelector('[data-rkf="fixed"][data-id="${id}"]')`;
  // the next file picker gets this file (the picker of the app is a hidden input it clicks)
  const pickNext = (url, name, text) => `(async () => { const b = ${url ? `await (await fetch('${url}', {credentials: 'same-origin'})).blob()` : `new Blob(['${text}'], {type: 'text/csv'})`};
    const orig = HTMLInputElement.prototype.click;
    HTMLInputElement.prototype.click = function () { if (this.type !== 'file') return orig.call(this); HTMLInputElement.prototype.click = orig; const dt = new DataTransfer(); dt.items.add(new File([b], '${name}')); this.files = dt.files; this.onchange && this.onchange(); };
    return 1; })()`;
  const inView = sel => `(() => { const e = document.querySelector('${sel}'); if (!e) return false; const t = e.getBoundingClientRect().top; return t >= -2 && t < innerHeight / 2; })()`;

  for (const [w, h, tag] of [[1280, 900, 'desktop'], [390, 844, 'phone']]) await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: w, height: h}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    // ---- #2333: one amount without VAT
    await nav(B + '#office/cashflow');
    check(await ready(ev, `!!${row(f0.id)} && !!${row(f19.id)}`, 80), tag + ': the fixed costs');
    check(await ev(`(() => { const b = ${row(f0.id)}, s = b.querySelector('.fcisum'); return /without VAT/.test(b.textContent) && !/VAT 0 %/.test(b.textContent) && !/\\bnet\\b|gross/.test(s.textContent) && /900\\.00/.test(s.textContent) && s.children.length === 1; })()`),
      tag + ': 0 % = one amount, "without VAT" ' + await ev(`${row(f0.id)}.textContent`));
    check(await ev(`(() => { const b = ${row(f19.id)}; return /100\\.00/.test(b.textContent) && /119\\.00/.test(b.textContent) && /€ ?100\\.00 net|100\\.00 € net/.test(b.textContent) && /€ ?119\\.00 gross|119\\.00 € gross/.test(b.textContent) && /VAT 19 %/.test(b.textContent); })()`), tag + ': 19 % = net and gross ' + await ev(`${row(f19.id)}.textContent`));
    // ---- #2335: no import buttons in the bar, a quiet link at the end
    check(await ev(`!document.querySelector('.fcibar [data-rkf="fimp"]') && !document.querySelector('.fcibar a[href*="import/template"]') && !!document.querySelector('.fcibar [data-rkf="fnew"]')`), tag + ': the bar keeps only "New fixed cost"');
    check(await ev(`(() => { const a = document.querySelector('.oimlink:not(.e) a[href="#office/import/fixed"]'); return !!a && /Import…/.test(a.textContent); })()`), tag + ': "Import…" at the end of the fixed costs');
    if (tag === 'phone') check(await ev(`document.querySelector('.oimlink a').getBoundingClientRect().height >= 43`), 'phone: the link is a large tap target');
    await shot(`p21223-a-cashflow-${tag}.png`);
    // ---- empty services: the link jumps to the master data section
    await nav(B + '#office/services');
    check(await ready(ev, `!!document.querySelector('.oimlink.e a[href="#office/import/master"]')`, 80), tag + ': empty services link to the import');
    check(await ev(`/Already have a list\\? Import from Excel/.test(document.querySelector('.oimlink.e').textContent)`), tag + ': the empty text');
    await ev(`(() => { document.querySelector('.oimlink.e a').click(); return 1; })()`);
    check(await ready(ev, `location.hash === '#office/import/master' && !!document.querySelector('#oim-master.oimflash')`), tag + ': the master data section, marked');
    // ---- empty subscriptions: the link jumps to the fixed costs section (far down the page)
    await nav(B + '#office/subs');
    check(await ready(ev, `!!document.querySelector('.abo-empty .oimlink.e a[href="#office/import/fixed"]')`, 80), tag + ': empty subscriptions link to the import');
    await ev(`(() => { document.querySelector('.abo-empty .oimlink a').click(); return 1; })()`);
    check(await ready(ev, `location.hash === '#office/import/fixed' && !!document.querySelector('#oim-fixed.oimflash')`), tag + ': the fixed costs section, marked');
    check(await ready(ev, inView('#oim-fixed'), 12), tag + ': scrolled to it');
    await shot(`p21223-a-import-${tag}.png`);
    // ---- the import page: the fixed costs import opens the known preview
    check(await ev(`!!document.querySelector('#oim-fixed a[href="/api/office/fixed-costs/import/template"][download]')`), tag + ': the template link on the import page');
    await ev(pickNext('/api/office/fixed-costs/import/template', 'template.xlsx'));
    await ev(`(() => { document.querySelector('#oim-fixed [data-rkf="fimp"]').click(); return 1; })()`);
    check(await ready(ev, `document.querySelectorAll('.fcidlg .fcirow').length === 2`), tag + ': the preview dialog with the two example rows');
    await ev(`(() => { document.querySelector('.fcidlg [data-fci="close"]').click(); return 1; })()`);
    // ---- the leads import from the import page
    await ev(pickNext('', 'leads.csv', CSV));
    await ev(`(() => { document.querySelector('#oim-leads [data-lead="import"]').click(); return 1; })()`);
    check(await ready(ev, `!!document.querySelector('.modal .lead-pv') && /Erika Beispiel/.test(document.querySelector('.modal .lead-pv').textContent)`), tag + ': the leads preview');
    await ev(`(() => { document.querySelector('.modal [data-li="close"]').click(); return 1; })()`);
    await ready(ev, `!document.querySelector('.modal')`); await sleep(600);  // on a phone the dialog's history entry goes first
    // ---- leads: no "Import CSV" in the toolbar, the empty column links to the import
    await nav(B + '#office/pipeline');
    check(await ready(ev, `!!document.querySelector('.ofcbar [data-pp="new"]') && !document.querySelector('[data-pp="newlead"]')`, 80), tag + ': the pipeline ' + await ev(`location.hash + ' ' + (document.querySelector('.modal')?.textContent || '').slice(0, 80) + ' | ' + (document.querySelector('.office')?.textContent || '').slice(0, 200)`));
    // no deal yet: the empty pipeline links to the leads section
    check(await ev(`!document.querySelector('.ofcbar [data-lead="import"]') && !!document.querySelector('.office .nempty .oimlink.e a[href="#office/import/leads"]')`), tag + ': leads link to the CSV import');
    check(await ev(`/Import from CSV/.test(document.querySelector('.office .nempty .oimlink')?.textContent || '')`), tag + ': the CSV wording');
    // ---- clients (outside the office module): the empty list links too
    await nav(B + '#clients');
    check(await ready(ev, `!!document.querySelector('.msclempty .oimlink a[href="#office/import/master"]')`, 80), tag + ': empty clients link to the import');
    if (tag === 'desktop') {
      // ---- a member without the office admin right: no link
      await signIn(ev, 'bob');
      await nav(B + 'static/icon.svg');
      await nav(B + '#office/services');
      check(await ready(ev, `!!document.querySelector('.office .ofcbar') && !/Loading/.test(document.querySelector('.office').textContent)`, 80), 'member: the services');
      check(await ev(`!document.querySelector('.oimlink')`), 'member: no import link');
    }
  }, false);

  console.log(`p21223_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
