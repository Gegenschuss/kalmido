// 2.36.1 UI tests, part C: quotations of Office & finance (#1021), own container (start.sh). jsdom:
// - the tab "Quotations" lists nothing at first; "New quotation" creates a draft on the server and opens the editor
//   (#office/offers/<id>) with its number, head fields, an empty position list and the totals block
// - the service picker lists the catalogue (document language), a tap adds a position with name, rate and flags; three
//   positions -> the server's sums show (net, including raw data, producing line with its explanation); a changed
//   quantity (comma) saves and the totals follow; a heading row; a position removed; the list shows the row with net + status
// - rights block: a catalogue choice fills the text field; the status select posts the status
// Firefox 390 x 844 touch: the editor on a phone -- tap targets >= 24 px, no horizontal overflow, screenshots
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p2361_c_ui', check, shots: 'P2361C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status, status: typeof j.status === 'string' ? j.status : r.status}; };  // a document's own status wins
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const FEAT = 'cal,comments,collab,office,clients';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const st = await call('GET', '/api/office/settings');
  check(st.status === 200 && st.role === 'admin', 'office settings reachable, alice is the organisation admin ' + st.status);
  await call('PUT', '/api/office/settings', {company: {name: 'Studio Nordlicht GmbH', lines: ['Studio Nordlicht GmbH', 'Hafenstraße 12', '20457 Hamburg']}, lang: 'de'});
  const svc = async (name_de, name_en, rate, o = {}) => (await call('POST', '/api/office/services', {name_de, name_en, category: o.cat || 'Video', daily_rate: rate, unit: o.unit || 'day', tax: o.tax || 'standard', raw_fee: o.raw ? 1 : 0, producing: o.prod ? 1 : 0, intext: o.intext || 'intern'})).id;
  const S1 = await svc('Storyboard-Erstellung', 'Storyboard creation', 980);
  const S2 = await svc('Schnitt', 'Editing', 980, {raw: 1, prod: 1});
  const S3 = await svc('Stockfootage HD', 'Stock footage HD', 75, {cat: 'Stock', unit: 'piece', intext: 'extern'});
  check(S1 && S2 && S3, 'three services');

  // ================= jsdom: the empty tab, a new quotation
  let w = await boot({hash: 'office/offers'}); let d = w.document;
  await until(() => d.querySelector('.office .ofcbody .ofdbar'));
  check(!!d.querySelector('.office .ofdbar [data-ofd="new"]') && /No quotations yet/.test(d.querySelector('.office .ofcbody')?.textContent || ''), 'the tab shows the search bar, New and the empty hint');
  d.querySelector('.office .ofdbar [data-ofd="new"]').click();
  await until(() => d.querySelector('.ofdeditor'), 60);
  let doc = (await call('GET', '/api/office/docs')).docs?.[0];
  check(!!doc && /office\/offers\/\d+/.test(w.location.hash) && /^KVA-\d{4}-001$/.test(doc.number), 'New creates a draft on the server and opens it: ' + w.location.hash + ' ' + doc?.number);
  await until(() => d.querySelector('.ofdhead .ofdnum b')?.textContent === doc.number);
  check(d.querySelector('.ofdhead .ofdnum b')?.textContent === doc.number && d.querySelector('#ofd-status')?.value === 'draft', 'the editor head shows number and status');
  check(!!d.querySelector('#ofd-lang') && d.querySelector('#ofd-lang').value === 'de' && !!d.querySelector('#ofd-project_title') && !!d.querySelector('#ofd-date[data-dp="date"]') && !d.querySelector('input[type="date"]'), 'head fields: language de (organisation default), project title, date picker (no native date input)');
  check(!!d.querySelector('#ofd-totals') && /0,00 €/.test(d.querySelector('#ofd-totals .tr-net dd')?.textContent || ''), 'the totals block shows 0,00 € in the document language');
  check(d.querySelectorAll('.ofdits .ofdit').length === 0 && !!d.querySelector('[data-ofd="it-svc"]'), 'no positions yet, Add service is there');

  // ================= the service picker
  d.querySelector('[data-ofd="it-svc"]').click();
  await until(() => d.querySelector('.modal.ofdpick [data-sid]'));
  const picks = [...d.querySelectorAll('.modal.ofdpick [data-sid]')];
  check(picks.length === 3 && picks.some(b => /Storyboard-Erstellung/.test(b.textContent)) && picks.some(b => /980/.test(b.textContent)), 'the picker lists the three services with their German names and rates: ' + picks.length + ' ' + (d.querySelector('.modal.ofdpick')?.textContent || '').slice(0, 160));
  picks.find(b => +b.dataset.sid === S1).click();
  await until(() => !d.querySelector('.modal.ofdpick') && d.querySelectorAll('.ofdits .ofdit').length === 1, 60);
  const add = async sid => { d.querySelector('[data-ofd="it-svc"]').click(); await until(() => d.querySelector('.modal.ofdpick [data-sid]')); const n = d.querySelectorAll('.ofdits .ofdit').length; d.querySelector(`.modal.ofdpick [data-sid="${sid}"]`).click(); await until(() => d.querySelectorAll('.ofdits .ofdit').length === n + 1, 60); };
  await add(S2); await add(S3);
  let its = [...d.querySelectorAll('.ofdits .ofdit')];
  check(its.length === 3 && its[0].querySelector('[data-k="title"]').value === 'Storyboard-Erstellung' && its[1].querySelector('[data-k="rate"]').value.replace(',', '.') === '980' && its[2].querySelector('[data-k="unit"]').value === 'piece', 'three positions with name, rate and unit from the catalogue');
  check(its[1].querySelector('[data-k="raw_fee"]').checked && its[1].querySelector('[data-k="producing"]').checked && !its[0].querySelector('[data-k="raw_fee"]').checked, 'flags from the catalogue');
  doc = await call('GET', `/api/office/docs/${doc.id}`);
  check(doc.totals.net === 980 + 980 + 75 + 300 && doc.totals.producing_days === 0.5, 'server: 3 positions (qty 1) + producing 0.5 day x 600 = 2335: ' + doc.totals.net);
  check(/2\.335,00 €/.test(d.querySelector('#ofd-totals .tr-net dd')?.textContent || ''), 'the totals block shows the net sum 2.335,00 €: ' + d.querySelector('#ofd-totals .tr-net dd')?.textContent);
  check(/inklusive Rohdaten/.test(d.querySelector('#ofd-totals')?.textContent || '') && /2\.580,00 €/.test(d.querySelector('#ofd-totals')?.textContent || ''), 'including raw data 2.580,00 € (980 x 0,25 on top)');
  const prod = d.querySelector('.ofdautos .ofdauto');
  check(!!prod && /Producing/.test(prod.textContent) && /0,5 Tage = 1 Produktionstage \/ 3/.test(prod.textContent) && /300,00 €/.test(prod.textContent), 'the producing line with its explanation: ' + prod?.textContent);
  // a changed quantity with a comma
  const qty = its[1].querySelector('[data-k="qty"]');
  qty.value = '4,5'; qty.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', `/api/office/docs/${doc.id}`)).items[1].qty === 4.5, 60);
  doc = await call('GET', `/api/office/docs/${doc.id}`);
  check(doc.items[1].qty === 4.5 && doc.totals.producing_days === 1.5 && doc.totals.net === 980 + 4410 + 75 + 900, 'qty 4,5 saved: producing 1.5 days, net 6365: ' + doc.totals.net);
  await until(() => /6\.365,00 €/.test(d.querySelector('#ofd-totals .tr-net dd')?.textContent || ''));
  check(/6\.365,00 €/.test(d.querySelector('#ofd-totals .tr-net dd')?.textContent || ''), 'the totals follow the change: ' + d.querySelector('#ofd-totals .tr-net dd')?.textContent);
  check([...d.querySelectorAll('.ofdits .ofdit .ofdlt')].some(x => /4\.410,00 €/.test(x.textContent)), 'the line total 4.410,00 € shows on the position');
  // a heading, a removed position
  d.querySelector('[data-ofd="it-head"]').click();
  await until(() => d.querySelectorAll('.ofdits .ofdit').length === 4, 60);
  const hd = d.querySelector('.ofdits .ofdhd [data-k="title"]'); check(!!hd, 'a heading row appended');
  if (hd) { hd.value = 'Video'; hd.dispatchEvent(new w.Event('change', {bubbles: true})); await until(async () => (await call('GET', `/api/office/docs/${doc.id}`)).items[3]?.title === 'Video', 60); }
  d.querySelector('.ofdits .ofdhd [data-ofd="it-up"]').click();
  await until(async () => (await call('GET', `/api/office/docs/${doc.id}`)).items[2]?.kind === 'heading', 60);
  doc = await call('GET', `/api/office/docs/${doc.id}`);
  check(doc.items[2].kind === 'heading' && doc.items[2].title === 'Video' && doc.items[3].title === 'Stockfootage HD', 'the heading moved up one row: ' + doc.items.map(i => i.kind).join(','));
  d.querySelector('.ofdits .ofdit:last-child [data-ofd="it-del"]').click();
  await until(async () => (await call('GET', `/api/office/docs/${doc.id}`)).items.length === 3, 60);
  doc = await call('GET', `/api/office/docs/${doc.id}`);
  check(doc.items.length === 3 && doc.totals.net === 980 + 4410 + 900, 'the last position removed, net 6290: ' + doc.totals.net);

  // ================= rights, status, the list
  const rt = d.querySelector('#ofd-r-time');
  check(!!rt && rt.options.length > 1, 'the rights block offers the catalogue (duration)');
  if (rt) {
    const opt = [...rt.options].find(o => /unbegrenzt/.test(o.textContent)); rt.value = opt.value; rt.dispatchEvent(new w.Event('change', {bubbles: true}));
    await until(async () => (await call('GET', `/api/office/docs/${doc.id}`)).rights.time.text === 'unbegrenzt', 60);
    doc = await call('GET', `/api/office/docs/${doc.id}`);
    check(doc.rights.time.text === 'unbegrenzt' && d.querySelector('#ofd-r-time-t')?.value === 'unbegrenzt', 'a catalogue choice fills the text and saves the snapshot');
  }
  const ss = d.querySelector('#ofd-status'); ss.value = 'sent'; ss.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', `/api/office/docs/${doc.id}`)).status === 'sent', 60);
  check((await call('GET', `/api/office/docs/${doc.id}`)).status === 'sent', 'the status select posts the status');
  check(d.querySelector('a[data-ofd="pdf"]')?.getAttribute('href') === `/api/office/docs/${doc.id}/pdf`, 'the PDF link');
  d.querySelector('[data-ofd="back"]').click();
  await until(() => d.querySelector('.ofdlist .ofdrow'), 60);
  const row = d.querySelector('.ofdlist .ofdrow');
  check(!!row && /KVA-\d{4}-001/.test(row.textContent) && /6\.290,00 €/.test(row.textContent) && /Sent/.test(row.textContent), 'the list row: number, net, status: ' + row?.textContent);
  const q = d.querySelector('#ofd-q'); q.value = 'nirgends'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  await sleep(100);
  check(!d.querySelector('.ofdlist .ofdrow') && /Nothing matches/.test(d.querySelector('.office .ofcbody')?.textContent || ''), 'search filters the list');
  w.close();

  // ================= Firefox 390 touch: the editor on a phone
  const ffLogin = async ({ev, nav}) => {
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    return ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: 'alice', password: 'password123'})}).then(r => r.status)`);
  };
  const ready = async (ev, n = 30) => { for (let i = 0; i < n && !(await ev(`!!document.querySelector('.office .ofdeditor, .office .ofdlist')`).catch(() => false)); i++) await sleep(300); await sleep(800); };
  await firefox(async o => {
    const {cmd, ev, ctx, shot} = o;
    check(await ffLogin(o) === 200, '390: login');
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await o.nav(B + '#office/offers/' + doc.id); await ready(ev); await sleep(1200);
    const g = await ev(`(() => { const r = [...document.querySelectorAll('.ofdeditor button, .ofdeditor select, .ofdeditor input:not([type=hidden]):not([type=checkbox]), .ofdhead button, .ofdhead select, .ofdhead a')].map(b => b.getBoundingClientRect()).filter(r => r.width && r.height); return {n: r.length, small: r.filter(r => r.width < 24 || r.height < 24).length, wide: document.documentElement.scrollWidth > window.innerWidth + 1, out: [...document.querySelectorAll('.ofdeditor input, .ofdeditor select, .ofdeditor textarea')].filter(e => { const b = e.getBoundingClientRect(); return b.width && b.right > window.innerWidth + 1; }).map(e => (e.id || e.dataset.k || e.tagName) + ':' + Math.round(e.getBoundingClientRect().right)), net: document.querySelector('#ofd-totals .tr-net dd')?.textContent, items: document.querySelectorAll('.ofdits .ofdit').length}; })()`);
    check(g && g.n > 10 && g.small === 0 && !g.wide && g.out.length === 0 && g.items === 3 && /6\.290,00 €/.test(g.net || ''), '390: every control >= 24 px, no horizontal overflow, no field cut off at the right edge, 3 positions, net visible ' + JSON.stringify(g));
    await shot('p2361c-390-editor.png');
    await ev(`(() => { document.querySelector('#ofd-totals').scrollIntoView(); return 1; })()`); await sleep(400);
    await shot('p2361c-390-totals.png');
    await o.nav(B + '#office/offers'); await ready(ev); await sleep(800);
    const l = await ev(`(() => { const r = document.querySelector('.ofdlist .ofdrow'); if (!r) return null; const b = r.getBoundingClientRect(); return {h: Math.round(b.height), t: r.textContent.slice(0, 80)}; })()`);
    check(l && l.h >= 44, '390: the list row is a tap target >= 44 px ' + JSON.stringify(l));
    await shot('p2361c-390-list.png');
  }, true);

  console.log(`p2361_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crash', e); process.exit(1); });
