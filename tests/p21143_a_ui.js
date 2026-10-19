// 2.114.3 UI test (#2266, office: the producing calculation made visible), own container (start.sh, mode workspaces),
// Firefox in a phone viewport. Invented companies, services and figures only. freelancer-matrix: office
// - a person without organisation (personal office) builds a quotation: title page with a producing position, an items
//   part that takes over the document's switch (1.5 producing days), an items part with its own setting (producing off)
//   and a shoot part with a producing share; the sums are the same as before 2.114.3 (display only, figures by hand)
// - the title page: the hint at the switch names the parts, each part line says "inkl. Producing 1,5 Tage" (German
//   number format, only when > 0; the shoot part its share), the ticked producing flag of a position is marked
// - an open part shows "wie Dokument" or "eigene Einstellung"; "Werte vom Dokument übernehmen" removes the own values,
//   the part then takes over the switch and its line names its new producing days; no horizontal scrolling on the phone
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p21143_a_ui', check, shots: 'P21143A_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P21143A_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs,files';
const svc = (title, qty, rate, producing) => ({kind: 'service', title, qty, unit: 'day', rate, tax: 'standard', raw_fee: 0, producing, intext: 'intern', cost: 0, discountable: 1});
const near = (a, b) => Math.abs(+a - +b) < 0.005;

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  // the person without organisation (tests/freelancer_fixture.py does the same in Python)
  const fu = await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  check(fu.http < 300, 'a person without organisation ' + fu.http);
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'de', tour: 'done', features: FEAT});
  check(((await call(CF, 'GET', '/api/state')).me?.workspaces || []).length === 0, 'frida is in no organisation');
  const st = await call(CF, 'PUT', '/api/office/settings', {industry_packs: ['film']});
  check(st.http === 200, 'the pack Film & Video in the personal office ' + st.http);
  const cl = await call(CF, 'POST', '/api/clients', {name: 'Beispiel Medien GmbH'});
  const q = await call(CF, 'POST', '/api/office/docs', {project_title: 'Imagefilm', client_id: cl.id});
  const D = `/api/office/docs/${q.id}`;
  check((await call(CF, 'PATCH', D, {producing_on: 1, prod_quotient: 3, producing_rate: 500, raw_mode: 'none', discount_pct: 0})).http === 200, 'the calculation values of the document');
  // part A: takes over the document (4.5 producing days / 3 = 1.5 days), part B: own setting, producing off
  const pa = (await call(CF, 'POST', D + '/parts', {kind: 'items', title: 'Modul Dreh'})).part;
  const pb = (await call(CF, 'POST', D + '/parts', {kind: 'items', title: 'Modul Schnitt'})).part;
  check(pa?.id && pb?.id, 'two items parts');
  await call(CF, 'PUT', `${D}/parts/${pa.id}/items`, {items: [svc('Dreh', 4.5, 100, 1)]});
  await call(CF, 'PUT', `${D}/parts/${pb.id}/items`, {items: [svc('Schnitt', 2, 100, 1)]});
  await call(CF, 'PATCH', `${D}/parts/${pb.id}`, {settings: {producing_on: 0}});
  // the shoot part: one crew row, producing share 20 %
  const cam = await call(CF, 'POST', '/api/office/crew', {name_de: 'Kamera', name_en: 'Camera', rate_day: 650, intext: 'intern'});
  const ps = (await call(CF, 'POST', D + '/parts', {kind: 'shoot', title: 'Drehtag'})).part;
  check(cam.id && ps?.id, 'crew role and shoot part ' + JSON.stringify(cam).slice(0, 120));
  const sh = await call(CF, 'PATCH', `${D}/parts/${ps.id}`, {sheet: {head: {shoot_days: 1, travel_days: 0, prep_days: 0, nights: 0}, staff: [{role_id: cam.id, qty: 1, prep: 0}], producing: {on: 1, share: 0.2}}});
  check(sh.http === 200, 'the shoot sheet ' + sh.http);
  // the title page: its own producing position (3 days / 3 = 1 producing day) after the three part lines
  const cur = await call(CF, 'GET', D);
  const title = (cur.items || []).filter(it => it.kind === 'part').map(it => ({id: it.id, kind: 'part', ref_part_id: it.ref_part_id, title: it.title, qty: it.qty, unit: it.unit, discountable: it.discountable}));
  check(title.length === 3, 'the three parts stand on the title page ' + title.length);
  await call(CF, 'PUT', D + '/items', {items: [svc('Konzept', 3, 200, 1), ...title]});
  const doc = await call(CF, 'GET', D);
  const part = id => (doc.parts || []).find(p => p.id === id) || {};
  const sNet = +part(ps.id).totals?.net;
  // display only: the figures by hand -- title 600 + producing 1 x 500, part A 450 + 1.5 x 500, part B 200, the shoot part
  check(near(part(pa.id).totals?.net, 1200) && near(part(pa.id).totals?.producing_days, 1.5), 'part A: 1.5 producing days, net 1200 ' + JSON.stringify(part(pa.id).totals || {}).slice(0, 160));
  check(near(part(pb.id).totals?.net, 200) && !+part(pb.id).totals?.producing_days, 'part B (own setting, off): no producing, net 200');
  check(sNet > 0 && (part(ps.id).totals?.lines || []).some(l => l.block === 'share' && near(l.total, 130)), 'shoot part: producing share 0.2 x 650 = 130 ' + sNet);
  check(near(doc.totals?.net, 600 + 500 + 1200 + 200 + sNet) && (doc.totals?.lines || []).some(l => l.kind === 'producing' && near(l.total, 500)), `the quotation's net as before: ${doc.totals?.net} = ${600 + 500 + 1200 + 200 + sNet}`);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const line = pid => `[...document.querySelectorAll('.tppl')].find(li => li.querySelector('[data-ofd="tp-open"][data-pid="${pid}"]'))`;
  const note = pid => `((${line(pid)})?.querySelector('.tpprod')?.textContent || '').trim()`;
  const noScroll = `document.documentElement.scrollWidth <= window.innerWidth + 1`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'frida');
    await nav(B + `#office/offers/${q.id}`);
    check(await ready(ev, `!!(${line(pa.id)})`, 80), 'the title page lists the part lines');
    check(await ev(`${note(pa.id)} === 'inkl. Producing 1,5 Tage'`), 'part A line: "inkl. Producing 1,5 Tage" -- ' + await ev(note(pa.id)));
    check(await ev(`${note(pb.id)} === '' && !!(${line(pb.id)})`), 'part B line (producing off): no note -- ' + await ev(note(pb.id)));
    check(await ev(`/^inkl\\. Producing \\(20\\s?% (der Personalkosten|of the crew costs)\\)$/.test(${note(ps.id)})`), 'shoot part line names its share -- ' + await ev(note(ps.id)));
    check(await ev(`/Teilangebote ohne eigene Einstellung übernehmen den Schalter/.test(document.querySelector('.ofdrules .ofdprodhint')?.textContent || '')`), 'the hint at the switch of the title page');
    check(await ev(`!!document.querySelector('.ofdit.ofdprod .ofdprodf.on input[data-k="producing"]:checked')`), 'the ticked producing flag of "Konzept" is marked');
    check(await ev(`[...document.querySelectorAll('.ofdits .ofdflags .ofdprodf')].every(l => l.classList.contains('on') === !!l.querySelector('input').checked)`), 'only ticked producing flags are marked');
    check(await ev(`/Modul Dreh[\\s\\S]*inkl\\. Producing 1,5 Tage/.test(document.querySelector('.tplist')?.textContent || '')`), 'the parts list names the producing days too');
    check(await ev(noScroll), 'title page: no horizontal scrolling on the phone');
    await ev(`(() => { (${line(pa.id)})?.scrollIntoView({block: 'start'}); return 1; })()`); await sleep(300);
    await shot('p21143-a-title.png');
    // part A: takes over the document
    await ev(`(() => { document.querySelector('[data-ofd="tp-open"][data-pid="${pa.id}"]').click(); return 1; })()`);
    check(await ready(ev, `(document.querySelector('.tpprodsrc .rotag')?.textContent || '').trim() === 'wie Dokument'`), 'part A: "wie Dokument" -- ' + await ev(`document.querySelector('.tpprodsrc')?.textContent || ''`));
    check(await ev(`/dieses Teils mit Producing-Haken/.test(document.querySelector('.ofdprodhint')?.textContent || '') && !document.querySelector('[data-ofd="tp-prod-doc"]')`), 'part A: the hint for a part, no reset button');
    check(await ev(noScroll), 'part A: no horizontal scrolling on the phone');
    await ev(`(() => { document.querySelector('[data-ofd="tp-back"]').click(); return 1; })()`);
    // part B: own setting -> back to the document's values
    check(await ready(ev, `!!document.querySelector('[data-ofd="tp-open"][data-pid="${pb.id}"]')`), 'back on the title page');
    await ev(`(() => { document.querySelector('[data-ofd="tp-open"][data-pid="${pb.id}"]').click(); return 1; })()`);
    check(await ready(ev, `(document.querySelector('.tpprodsrc.own .rotag')?.textContent || '').trim() === 'eigene Einstellung' && !!document.querySelector('[data-ofd="tp-prod-doc"]')`), 'part B: "eigene Einstellung" with the reset button');
    check(await ev(noScroll), 'part B: no horizontal scrolling on the phone');
    await ev(`(() => { document.querySelector('.ofdits .ofdflags')?.scrollIntoView({block: 'start'}); return 1; })()`); await sleep(300);
    await shot('p21143-a-part.png');
    await ev(`(() => { document.querySelector('[data-ofd="tp-prod-doc"]').click(); return 1; })()`);
    check(await ready(ev, `(document.querySelector('.tpprodsrc .rotag')?.textContent || '').trim() === 'wie Dokument'`), 'part B after the reset: "wie Dokument"');
    await ev(`(() => { document.querySelector('[data-ofd="tp-back"]').click(); return 1; })()`);
    // 2 producing days / 3 = 0.67, rounded to half days = 0.5
    check(await ready(ev, `${note(pb.id)} === 'inkl. Producing 0,5 Tage'`), 'part B line now: "inkl. Producing 0,5 Tage" -- ' + await ev(note(pb.id)));
  }, true);

  const after = await call(CF, 'GET', D);
  const pB = (after.parts || []).find(p => p.id === pb.id) || {};
  check(!['producing_on', 'prod_quotient', 'producing_rate'].some(k => k in (pB.settings || {})), 'part B has no own producing values any more ' + JSON.stringify(pB.settings));
  check(near(pB.totals?.net, 450) && near(after.totals?.net, 600 + 500 + 1200 + 450 + sNet), `part B takes over the switch: 200 + 0.5 x 500; quotation ${after.totals?.net}`);
  console.log(`p21143_a_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
