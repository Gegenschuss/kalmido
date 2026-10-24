// 2.298.0 A2 (#3186) UI tests "less text" in the office parts outside office.js / office_docs.js: own container (start.sh),
// jsdom, invented data. Help lines that only explain sit behind the (i) of infoize() (class .shint -> .iisrc + an .ib
// button), short facts and promises stay visible:
// - cash flow: the actual / planned + net / gross legend behind (i), the column heads with a title, the arrows with a title
// - figures: the tile sublines (net, received / value x probability / incl. expected payments), the margin rule behind (i)
// - bookkeeping: "No tax advice; figures without guarantee." once per page (R7)
// - travel expenses "Edit days": the meal ticks say their cut, the country rule behind (i)
// - pipeline: the sum of a column says "net" as its title, the drag hint marked for the column layout only
// - forms of a project: the how of the status link behind (i), its privacy promise visible word for word (R8)
// freelancer-matrix: office -- once as a person without an organisation (own private office), once as the org admin.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2298A2_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const FEAT = 'cal,comments,collab,clients,office';
const call = async (method, url, body, ck) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { let x = null; try { x = await fn(); } catch { /* not there yet */ } if (x) return x; await sleep(150); } try { return await fn(); } catch { return null; } };
// a .shint behind (i): infoize marked it as the source of an (i) button
const behindI = (d, el) => !!el && el.classList.contains('iisrc') && !!d.querySelector(`.ib[data-ii="${el.id}"]`);

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const ACK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Example Studio', lang: 'en', collab_all: true, modules: ['cal', 'comments']}, ACK);
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, ACK);
  const FID = (await call('POST', '/api/users', {username: 'fiona', display_name: 'Fiona', password: 'password123'}, ACK)).id;  // no orgs = a freelancer
  check(!!FID, 'setup: fiona without an organisation');
  const FCK = await login('fiona');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, FCK);

  for (const [user, ck] of [['fiona', FCK], ['alice', ACK]]) {
    const tag = user + ': ';
    check((await call('POST', '/api/office/deals', {title: 'Studio film', value: '1000.00', probability: 20, expected_date: '2026-11-12'}, ck)).status === 201, tag + 'a deal');
    const P = (await call('POST', '/api/lists', {name: 'Website ' + user}, ck)).id;
    check(!!P, tag + 'a project');
    const w = await boot({user, hash: 'office/cashflow'}); const d = w.document;
    const go = h => { w.location.hash = h; };

    // cash flow: the legend behind (i), titles on the heads and arrows
    const leg = await until(() => d.querySelector('#view .rkcfleg'), 80);
    check(behindI(d, leg) && /Actual = paid or already past/.test(leg.textContent), tag + 'cash flow: the legend sits behind (i)');
    check(!d.querySelector('.rkcfms ~ p.ofchint'), tag + 'cash flow: no legend paragraph under the months');
    check(d.querySelector('.rkcftab th[title="Paid or already past"]') && d.querySelector('.rkcftab th[title="Expected"]'), tag + 'cash flow: the column heads explain themselves');
    check(d.querySelector('[data-rkf="prev"]')?.title === 'Earlier' && d.querySelector('[data-rkf="next"]')?.title === 'Later', tag + 'cash flow: the arrows have a title');

    // figures: tile sublines, the margin rule behind (i), the revenue rule visible
    go('#office/kpi');
    const tiles = await until(() => d.querySelectorAll('#view .kptiles .kptile').length === 6 && d.querySelector('#view .kptiles'), 80);
    const tt = [...(tiles?.querySelectorAll('.kptile') || [])].map(t => t.textContent);
    check(tt.filter(t => /net, received/.test(t)).length === 2, tag + 'figures: both revenue tiles say net, received ' + JSON.stringify(tt));
    check(tt.some(t => /Pipeline, weighted/.test(t) && /value × probability/.test(t)), tag + 'figures: the weighted pipeline says how it is weighted');
    check(tt.some(t => /Balance incl\. expected payments/.test(t)), tag + 'figures: the cash flow tile says expected payments count');
    const mg = [...d.querySelectorAll('#view .shint')].find(x => /^Margin = invoiced/.test(x.textContent));
    check(behindI(d, mg), tag + 'figures: the margin rule sits behind (i)');
    check([...d.querySelectorAll('#view p.ofchint')].some(p => p.textContent.trim() === 'Revenue = payments received on invoices, net.'), tag + 'figures: the revenue rule stays visible');

    // bookkeeping: the tax note once per page
    go('#office/books');
    await until(() => d.querySelector('#view .bk-sec') && !d.querySelector('#view .lempty'), 80);
    await sleep(300);
    const notes = (d.querySelector('#view')?.textContent.match(/No tax advice; figures without guarantee\./g) || []).length;
    check(notes === 1, tag + 'bookkeeping: the tax note once, not per part: ' + notes);

    // travel expenses: the days dialog
    go('#office/travel');
    await until(() => w.eval('typeof rk_vmaDaysModal') === 'function', 80);
    w.eval(`rk_vmaDaysModal({date_from: '2026-03-02', date_to: '2026-03-03', country: 'DE', place: '', vma_days: []})`);
    const dm = await until(() => [...d.querySelectorAll('.modal')].find(m => m.querySelector('.rkv-days')), 60);
    const meals = [...(dm?.querySelector('.rkv-day')?.querySelectorAll('.rkv-meal') || [])].map(l => l.textContent.trim());
    check(meals.join('|') === 'Breakfast −20 %|Lunch −40 %|Dinner −40 %', tag + 'travel: the meal ticks say their cut ' + JSON.stringify(meals));
    const cr = dm?.querySelector('.shint');
    check(behindI(d, cr) && /^Country = where you are before midnight/.test(cr.textContent.trim()) && !/breakfast cuts/.test(dm.textContent), tag + 'travel: the country rule behind (i), no paragraph about the meals');
    dm?.querySelector('[data-m="close"]')?.click();

    // pipeline: "net" as the title of the column sum, the drag hint only for the column layout
    go('#office/pipeline');
    const sum = await until(() => d.querySelector('#view .pipcol header .rksum'), 80);
    check(sum?.title === 'Values net, in the office currency.', tag + 'pipeline: the column sum says net in its title');
    check(d.querySelector('#view p.pphint')?.textContent.trim() === 'Drag a card into another column to change its stage.', tag + 'pipeline: the drag hint without the net sentence');
    check(d.querySelector('#view .ppcard [title="Probability"]') && d.querySelector('#view .ppcard [title="Expected date"]'), tag + 'pipeline: probability and date on a card have a title');

    // forms: the status link's how behind (i), the privacy promise visible (R8)
    w.eval(`formsModal(${P})`);
    const fm = await until(() => [...d.querySelectorAll('.modal')].find(m => m.querySelector('[data-fm="new"]')), 60);
    check(/A form is a link with a small page/.test(fm?.textContent || ''), tag + 'forms: no form yet, the explanation is there');
    fm?.querySelector('[data-fm="new"]')?.click();
    const ed = await until(() => [...d.querySelectorAll('.modal')].find(m => m.querySelector('#fm-portal')), 40);
    const pr = ed?.querySelector('.frm-hint');
    check(pr && !pr.classList.contains('shint') && pr.textContent.trim() === 'It shows only their report: title, status and the answers you send to them, never internal comments or your team.', tag + 'forms: the privacy promise stays visible word for word');
    const how = [...(ed?.querySelectorAll('.shint') || [])].find(x => /^Without login, the sender sees a link/.test(x.textContent));
    check(behindI(d, how), tag + 'forms: the how of the status link sits behind (i)');
    w.close();
  }

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
