// kalmido-suite: fresh
// 2.1041.0 (#5812) UI test (jsdom): "Adjust prices…" in the More menu of a quotation draft opens the dialog; 10 % typed ->
// the preview (from the server) shows the new net; Apply -> the editor's rate fields show the new unit prices, the dialog
// is gone; a sent quotation has no such entry. Invented companies only.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  await call('PUT', '/api/office/settings', {lang: 'de', company: {name: 'Studio Beispiel'}});
  const mk = async () => (await call('POST', '/api/office/docs', {kind: 'offer', project_title: 'Herbstfilm', items: [{title: 'Schnitt', qty: 2, rate: 1000}, {title: 'Ton', qty: 1, rate: 500}]})).id;
  const q = await mk(), sent = await mk();
  await call('POST', `/api/office/docs/${sent}/status`, {status: 'sent'});

  const w = await boot({hash: `office/offers/${q}`});
  const $ = s => w.document.querySelector(s);
  await until(() => $('[data-ofd="more"]') && w.eval(`OFD.doc && OFD.doc.id === ${q}`));
  $('[data-ofd="more"]').click();
  const entry = await until(() => $('[role="menuitem"][data-act="reprice"]'));
  check(entry && /Adjust prices/.test(entry.textContent), 'the More menu of a draft offers "Adjust prices…"');
  entry.click();
  const inp = await until(() => $('#orp-v'));
  check(inp && /Adjust prices/.test($('.orp-dlg h3')?.textContent || ''), 'the dialog opens with its title');
  check(w.document.querySelectorAll('[data-orp-it]').length === 2, 'both priced positions are listed and ticked');
  inp.value = '10'; inp.dispatchEvent(new w.Event('input', {bubbles: true}));
  // net 2500 -> 2750: the preview comes from the server
  const prev = await until(() => /2\.750,00|2,750\.00/.test($('.orp-prev')?.textContent || '') && $('.orp-prev').textContent);
  check(prev && /2\.500,00|2,500\.00/.test(prev) && /10/.test(prev), 'the preview shows old and new net and the percentage: ' + (prev || $('.orp-prev')?.textContent));
  check((await call('GET', `/api/office/docs/${q}`)).items.map(x => +x.rate).join() === '1000,500', 'the preview wrote nothing');
  $('.orp-dlg [data-m="ok"]').click();
  await until(() => !$('.orp-dlg'));
  check(!$('.orp-dlg'), 'Apply closes the dialog');
  const shown = await until(() => { const v = [...w.document.querySelectorAll('#view input[data-k="rate"]')].map(x => x.value); return v.length === 2 && /1[.,]?100/.test(v[0]) && /550/.test(v[1]) && v; });
  check(shown, 'the editor shows the new unit prices: ' + [...w.document.querySelectorAll('#view input[data-k="rate"]')].map(x => x.value).join(' | '));
  check((await call('GET', `/api/office/docs/${q}`)).items.map(x => +x.rate).join() === '1100,550', 'stored: 1100 and 550');

  // a sent quotation: no entry
  w.location.hash = `#office/offers/${sent}`;
  await until(() => w.eval(`OFD.doc && OFD.doc.id === ${sent}`) && $('[data-ofd="more"]'));
  check(!w.eval(`ofdMoreItems(OFD.doc, false).some(x => x && x.act === 'reprice')`), 'a sent quotation has no "Adjust prices…"');
  check(!errs.length, 'no script errors: ' + errs.join(' | '));
  w.close();

  console.log(`p21041_a_reprice_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack); process.exit(1); });
