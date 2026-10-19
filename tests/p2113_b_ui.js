// 2.113.0 UI tests, part B (#2248 parts of a quotation open in place on the title page, a colour per part), own container
// (start.sh), jsdom + Firefox. Everything as a person WITHOUT an organisation (her personal office; freelancer-matrix: office).
// Invented services and amounts. P2113B_NOSTART=1 = the server already runs.
// - the rows under "Parts" open / close their part right on the title page, several at once; no "Title page" back button
// - every action inside an open part hits that part: a quantity, "Add service", a heading, moving, a calculation value;
//   a change on the title page hits the title page; no element id twice on the page
// - colours: fixed by the place in the list, the dot in the row = the row's edge = the dot on the title page's part line;
//   "Open part" on a title page line opens the part; the shoot sheet opens in place too
// - a sent quotation: parts open in place with their colours, the fields locked
// - Firefox: 390 px dark: nothing sticks out, the head of an open part readable (contrast >= 4.5); screenshots dark / light
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2113_b_ui', check, shots: 'P2113B_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2113B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const change = (w, el, v) => { if (!el) return; if (v !== undefined) el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
const svc = (title, qty, rate) => ({kind: 'service', title, qty, unit: 'day', rate, tax: 'standard', raw_fee: 0, producing: 0, intext: 'intern', cost: 0, discountable: 1});
const FEATURES = 'cal,collab,comments,contacts,files,clients,office';

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const AK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']}, AK);
  await call('POST', '/api/admin/orgs', {name: 'Alpha', admin_id: (await call('GET', '/api/state', null, AK)).me.id}, AK);  // a server with organisations
  // the person without an organisation (as tests/freelancer_fixture.py)
  const fu = await call('POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []}, AK);
  check(fu.http < 300, 'a person without an organisation ' + fu.http);
  CK = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEATURES});
  check(((await call('GET', '/api/state')).me.workspaces || []).length === 0, 'frida is in no organisation');
  const pk = await call('PUT', '/api/office/settings', {industry_packs: ['film']});
  check(pk.http === 200, 'her own office: the pack Film & Video on ' + pk.http);

  const doc = await call('POST', '/api/office/docs', {kind: 'offer', lang: 'en', project_title: 'Campaign', items: [svc('Concept', 1, 800)]});
  check(doc.http === 201, 'a quotation ' + doc.http);
  const D = doc.id;
  const PA = (await call('POST', `/api/office/docs/${D}/parts`, {title: 'Module A'})).part.id;
  await call('PUT', `/api/office/docs/${D}/parts/${PA}/items`, {items: [svc('Animation', 2, 500)]});
  const PB = (await call('POST', `/api/office/docs/${D}/parts`, {title: 'Module B'})).part.id;
  await call('PUT', `/api/office/docs/${D}/parts/${PB}/items`, {items: [svc('Sound', 1, 300)]});
  const sh = await call('POST', `/api/office/docs/${D}/parts`, {kind: 'shoot', title: 'Shooting'});
  const PS = sh.part?.id;
  check(PS, 'a shoot part ' + sh.http);
  const get = () => call('GET', `/api/office/docs/${D}`);
  const part = (x, pid) => (x.parts || []).find(p => p.id === pid) || {};
  const sig = it => (it || []).map(i => `${i.kind}:${i.title}:${+i.qty}`).join('|');
  const before = await get();
  const T0 = sig(before.items), A0 = sig(part(before, PA).items), B0 = sig(part(before, PB).items);

  // ================= jsdom: the title page with its parts
  let w = await boot({user: 'frida', hash: `office/offers/${D}`}), d = w.document;
  await until(() => d.querySelectorAll('.tplist .tprow').length === 3, 60);
  const rows = () => [...d.querySelectorAll('.tplist .tprow')];
  const row = pid => rows().find(r => r.querySelector(`[data-tog][data-pid="${pid}"]`));
  const cls = el => ((el?.className || '').match(/tpf-c\d/) || [''])[0];
  check(rows().length === 3, 'the section "Parts" lists three parts');
  const cs = rows().map(cls);
  check(cs.join() === 'tpf-c0,tpf-c1,tpf-c2', 'colours by the place in the list ' + cs.join());
  check(rows().every(r => r.querySelector('.tpopen .tpfdot')), 'every row has its colour dot');
  check(!d.querySelector('.tpfbox') && !d.querySelector('[data-ofd="tp-back"]'), 'nothing open yet, no "Title page" button');
  const lineB = [...d.querySelectorAll('.tppl [data-ofd="tp-open"]')].find(b => +b.dataset.pid === PB);
  check(lineB && cls(lineB) === 'tpf-c1' && lineB.querySelector('.tpfdot'), 'the title page line of part 2 carries the same colour dot');

  // ---- two parts open at once
  click(w, row(PA).querySelector('.tpopen'));
  await until(() => d.querySelector(`.tpfbox[data-pid="${PA}"]`));
  click(w, row(PB).querySelector('.tpopen'));
  await until(() => d.querySelector(`.tpfbox[data-pid="${PB}"]`));
  const BA = `.tpfbox[data-pid="${PA}"]`, BB = `.tpfbox[data-pid="${PB}"]`;
  check(d.querySelector(BA) && d.querySelector(BB), 'both parts open at the same time');
  check(d.querySelector('.tppl') && d.querySelector('#ofd-totals'), 'the title page stays (its positions and sums)');
  check(row(PA).classList.contains('tpfon') && row(PA).querySelector('.tpopen')?.getAttribute('aria-expanded') === 'true', 'the open row: marked open (aria-expanded)');
  check(/Part 1 of 3/.test(d.querySelector(`${BA} .tpfkick`)?.textContent || '') && /Part 2 of 3/.test(d.querySelector(`${BB} .tpfkick`)?.textContent || ''), 'the heads: "Part 1 of 3", "Part 2 of 3"');
  check(d.querySelector(`${BA} .tptitle`)?.value === 'Module A' && d.querySelector(`${BB} [data-k="title"]`)?.value === 'Sound', 'each open part shows its own title and positions');
  const ids = [...d.querySelectorAll('[id]')].map(e => e.id), dup = ids.filter((x, i) => ids.indexOf(x) !== i);
  check(!dup.length, 'no element id twice on the page ' + [...new Set(dup)].join(' '));
  check(d.querySelector(`${BA} #tpf${PA}-discount_pct`) && d.querySelector(`${BA} label[for="tpf${PA}-discount_pct"]`), 'the part\'s fields have their own ids (label for follows)');

  // ---- a quantity in part 2: only part 2 (and the title page's sum of it) changes
  change(w, d.querySelector(`${BB} [data-k="qty"]`), '2');
  let x = await until(async () => { const j = await get(); return part(j, PB).items?.[0]?.qty === 2 ? j : null; });
  check(x && sig(part(x, PA).items) === A0 && sig(x.items) === T0, 'qty in part 2: part 1 and the title page positions unchanged');
  check(x && part(x, PB).totals?.net === 600, 'part 2: net 600 ' + (x && part(x, PB).totals?.net));
  await until(() => /600\.00/.test(d.querySelector(`${BB} .tptotals`)?.textContent || ''));
  check(/600\.00/.test(d.querySelector(`${BB} .tptotals`)?.textContent || '') && /1,000\.00/.test(d.querySelector(`${BA} .tptotals`)?.textContent || ''), 'on screen: part 2 600.00, part 1 still 1,000.00');
  check(d.querySelector(BA) && d.querySelector(BB), 'both stay open after the redraw');

  // ---- "Add service" in part 1 lands in part 1
  click(w, d.querySelector(`${BA} [data-ofd="it-svc"]`));
  await until(() => d.querySelector('.ofdpick [data-m="free"], .modal [data-m="free"]'));
  check(!d.querySelector('.modal [data-m="part"]'), 'the choice inside a part offers no parts');
  click(w, d.querySelector('.modal [data-m="free"]'));
  x = await until(async () => { const j = await get(); return (part(j, PA).items || []).length === 2 ? j : null; });
  check(x && (part(x, PB).items || []).length === 1 && (x.items || []).length === before.items.length, 'a free position in part 1: only part 1 grows');
  // ---- a heading in part 2
  // (an empty heading is kept on screen until it has a title, as on the title page: tests/p2361_c_ui.js)
  click(w, d.querySelector(`${BB} [data-ofd="it-head"]`));
  const hd = await until(() => d.querySelector(`${BB} .ofdhd [data-k="title"]`));
  check(hd && !d.querySelector(`${BA} .ofdhd`), 'the heading row appears in part 2 only');
  change(w, hd, 'Video');
  x = await until(async () => { const j = await get(); return (part(j, PB).items || []).some(i => i.kind === 'heading' && i.title === 'Video') ? j : null; });
  check(x && !(part(x, PA).items || []).some(i => i.kind === 'heading') && !(x.items || []).some(i => i.kind === 'heading'), 'a heading in part 2: only in part 2');
  // ---- moving in part 1
  await until(() => d.querySelectorAll(`${BA} .ofdits [data-ofd="it-down"]`).length === 2);
  click(w, d.querySelector(`${BA} .ofdits [data-ofd="it-down"][data-i="0"]`));
  x = await until(async () => { const j = await get(); return part(j, PA).items?.[1]?.title === 'Animation' ? j : null; });
  check(x && part(x, PB).items?.[0]?.title === 'Sound' && x.items?.[0]?.title === 'Concept', 'moving in part 1: part 2 and the title page keep their order');
  // ---- a calculation value in part 1 goes to part 1's settings
  change(w, d.querySelector(`${BA} [data-f="discount_pct"]`), '10');
  x = await until(async () => { const j = await get(); return +(part(j, PA).settings || {}).discount_pct === 10 ? j : null; });
  check(x && !+(part(x, PB).settings || {}).discount_pct && !+x.discount_pct, 'discount in part 1: not in part 2, not on the title page');
  // ---- the title page itself
  const tq = [...d.querySelectorAll('.ofdeditor [data-k="qty"]')].find(el => !el.closest('.tpfbox') && !el.closest('.tppl'));
  change(w, tq, '3');
  x = await until(async () => { const j = await get(); return +j.items?.[0]?.qty === 3 ? j : null; });
  check(x && part(x, PB).items?.length === 2 && part(x, PA).items?.length === 2, 'a quantity on the title page: the title page, the parts unchanged');
  await sleep(300);
  check(d.querySelector(BA) && d.querySelector(BB), 'the parts stay open');

  // ---- colours: dot in the row = the open part's edge (classes), the shoot sheet opens in place
  check(cls(d.querySelector(BA)?.closest('.tprow')) === 'tpf-c0' && cls(d.querySelector(BB)?.closest('.tprow')) === 'tpf-c1', 'the open parts keep the colour of their rows');
  click(w, row(PS).querySelector('.tpopen'));
  await until(() => d.querySelector(`.tpfbox[data-pid="${PS}"] .tpsheet .dksheet[data-pid="${PS}"]`));
  check(d.querySelector(`.tpfbox[data-pid="${PS}"] .tpsheet .dksheet`) && cls(row(PS)) === 'tpf-c2', 'the shoot sheet opens in place, third colour');
  check(d.querySelectorAll('.tpfbox').length === 3, 'three parts open');
  // ---- closing by the row, opening by "Open part" on the title page line
  click(w, row(PB).querySelector('.tpopen'));
  await until(() => !d.querySelector(BB));
  check(!d.querySelector(BB) && d.querySelector(BA), 'the row closes its part, the other stays');
  click(w, [...d.querySelectorAll('.tppl [data-ofd="tp-open"]')].find(b => +b.dataset.pid === PB));
  await until(() => d.querySelector(BB));
  check(d.querySelector(BB), '"Open part" on the title page line opens the part');
  click(w, [...d.querySelectorAll('.tppl [data-ofd="tp-open"]')].find(b => +b.dataset.pid === PB));
  await sleep(300);
  check(d.querySelector(BB), '"Open part" again keeps it open (only the row closes)');
  check(!errs.length, 'jsdom: no script errors ' + errs.join(' | ')); errs.splice(0);
  w.close();

  // ================= a sent quotation: read only, the same colours
  await call('POST', `/api/office/docs/${D}/status`, {status: 'sent'});
  w = await boot({user: 'frida', hash: `office/offers/${D}`}); d = w.document;
  await until(() => d.querySelectorAll('.tplist .tprow').length === 3, 60);
  click(w, row(PA).querySelector('.tpopen'));
  await until(() => d.querySelector(BA));
  const q = d.querySelector(`${BA} [data-k="qty"]`);
  check(q && q.closest('fieldset')?.disabled, 'sent: the open part\'s fields are locked');
  check(rows().map(cls).join() === 'tpf-c0,tpf-c1,tpf-c2' && cls(d.querySelector(BA).closest('.tprow')) === 'tpf-c0', 'sent: the colours stay');
  click(w, row(PA).querySelector('.tpopen'));
  await until(() => !d.querySelector(BA));
  check(!d.querySelector(BA), 'sent: the row closes it again (a link)');
  check(!errs.length, 'jsdom (sent): no script errors ' + errs.join(' | ')); errs.splice(0);
  w.close();
  await call('POST', `/api/office/docs/${D}/status`, {status: 'draft'}).catch(() => null);

  // ================= Firefox: 390 px, dark and light
  const ffLogin = async ({ev, nav}, theme) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.setItem('tasks.theme', '"${theme}"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'frida', password: 'password123'})}).then(r => r.status)`);
  };
  const LUM = `const rgb = s => { const m = String(s).match(/[\\d.]+/g) || []; const v = m.slice(0, 3).map(Number); return /color\\(srgb/.test(s) ? v.map(x => x * 255) : v; };
    const lum = c => { const f = x => { x /= 255; return x <= 0.03928 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4); }; const [r, g, b] = c.map(f); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
    const cr = (a, b) => { const x = lum(rgb(a)), y = lum(rgb(b)); return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05); };`;
  for (const [theme, vw] of [['dark', 390], ['light', 390], ['light', 1280]]) await firefox(async ({cmd, ev, nav, ctx, shot}) => {
    check(await ffLogin({ev, nav}, theme) === 200, `${theme} ${vw}: login`);
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: vw, height: 900}});
    await nav(B + `#office/offers/${D}`);
    for (let i = 0; i < 40 && !(await ev(`document.querySelectorAll('.tplist .tprow').length === 3`).catch(() => false)); i++) await sleep(300);
    await ev(`(() => { for (const pid of [${PA}, ${PB}]) document.querySelector('.tprow [data-tog][data-pid="' + pid + '"]').click(); return 1; })()`);
    await sleep(800);
    await ev(`(() => { if (!document.querySelector('.tpfbox[data-pid="${PB}"]')) document.querySelector('.tprow [data-tog][data-pid="${PB}"]').click(); return 1; })()`);
    await sleep(800);
    const r = await ev(`(() => { ${LUM}
      const boxes = [...document.querySelectorAll('.tpfbox')], W = document.documentElement.clientWidth;
      const out = [...document.querySelectorAll('.ofdeditor *')].filter(e => { const b = e.getBoundingClientRect(); return b.width && b.right > W + 1 && getComputedStyle(e).position !== 'fixed'; }).slice(0, 3).map(e => e.className || e.tagName);
      const heads = boxes.map(bx => { const row = bx.closest('.tprow'), a = row.querySelector(':scope > .tpopen'), t = a.querySelector('.ofcn b'), k = bx.querySelector('.tpfkick');
        return {c: cr(getComputedStyle(t).color, getComputedStyle(a).backgroundColor), k: cr(getComputedStyle(k).color, getComputedStyle(bx).backgroundColor === 'rgba(0, 0, 0, 0)' ? getComputedStyle(row).backgroundColor : getComputedStyle(bx).backgroundColor),
          edge: getComputedStyle(row).borderLeftColor, dot: getComputedStyle(row.querySelector('.tpfdot')).backgroundColor}; });
      return {n: boxes.length, sw: document.documentElement.scrollWidth, W, out, heads}; })()`);
    check(r.n === 2, `${theme} ${vw}: two parts open (${r.n})`);
    check(r.sw <= r.W + 1 && !r.out.length, `${theme} ${vw}: nothing sticks out (${r.sw} / ${r.W}) ${r.out.join(' ')}`);
    check(r.heads.every(h => h.c >= 4.5 && h.k >= 4.5), `${theme} ${vw}: the heads readable ` + JSON.stringify(r.heads.map(h => [h.c.toFixed(2), h.k.toFixed(2)])));
    check(r.heads.every(h => h.edge === h.dot) && r.heads[0]?.dot !== r.heads[1]?.dot, `${theme} ${vw}: the dot = the edge, two colours ` + JSON.stringify(r.heads.map(h => [h.edge, h.dot])));
    await ev(`(() => { document.querySelector('details[data-sec="parts"]').scrollIntoView({block: 'start'}); return 1; })()`); await sleep(300);
    await shot(`p2113_b_${theme}_${vw}.png`);
  });

  console.log(`p2113_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
