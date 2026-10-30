// kalmido-suite: fresh
// 2.437.0 part B UI tests (jsdom), fresh DB (#3621): duplicating a sent quotation asks "Mark the old quotation as superseded?"
// with the box ticked; yes supersedes the old one and the editors link each other; unticked leaves it; cancelling makes no
// copy; a draft does not ask. Invented companies only.
const {boot, errs, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,collab,office,clients'});
  await call('PUT', '/api/office/settings', {lang: 'de', company: {name: 'Studio Beispiel'}});
  const CL = (await call('POST', '/api/clients', {name: 'Beispielkunde AG', street: 'Marktstrasse 5', zip: '50667', city: 'Koeln', country: 'DE'})).id;
  const offer = async st => { const d = await call('POST', '/api/office/docs', {kind: 'offer', client_id: CL, items: [{title: 'Schnitt', qty: 1, rate: 100}]}); if (st) await call('POST', `/api/office/docs/${d.id}/status`, {status: st}); return d.id; };
  const q = await offer('sent'), q2 = await offer('sent'), q3 = await offer('sent'), dr = await offer('');

  const w = await boot({hash: `office/offers/${q}`});
  await until(() => w.eval('typeof ofdDupAsk') === 'function');
  const box = () => w.document.querySelector('#ofd-dup-replaces');
  // the answer lands in a page variable, the dialog stays open meanwhile
  const ask = id => w.eval(`api('GET', '/api/office/docs/${id}').then(d => { window.__ask = undefined; ofdDupAsk(d).then(x => { window.__ask = x; }); })`);
  const answer = () => w.eval('window.__ask');
  const press = m => w.document.querySelector('.ofddlg').parentElement.querySelector(`[data-m="${m}"]`).click();

  await ask(q);
  check(await until(box), 'a sent quotation asks');
  check(box().checked, 'yes is preselected');
  check(/Mark the old quotation as superseded\?/.test(w.document.body.textContent), 'the question: ' + w.document.body.textContent.slice(0, 80));
  press('ok');
  check(await until(() => answer() !== undefined), 'the dialog answers');
  check(JSON.stringify(answer()) === '{"replaces":true}', 'ticked = replaces: ' + JSON.stringify(answer()));

  await ask(q2); await until(box);
  box().checked = false; press('ok');
  await until(() => answer() !== undefined);
  check(JSON.stringify(answer()) === '{"replaces":false}', 'unticked = no reference: ' + JSON.stringify(answer()));

  await ask(q3); await until(box);
  press('close');
  await until(() => answer() !== undefined);
  check(answer() === false, 'cancel = no copy: ' + JSON.stringify(answer()));

  await ask(dr); await until(() => answer() !== undefined);
  check(answer() === true && !box(), 'a draft does not ask');

  // the whole way through the menu of the editor, then the links
  await w.eval(`api('GET', '/api/office/docs/${q}').then(d => { ofdMoreItems(d, false).find(x => x?.label === 'Duplicate').fn(); })`);  // no wait: fn ends after the dialog
  check(await until(box), 'the menu entry asks');
  press('ok');
  await until(() => w.eval(`OFD.doc && OFD.doc.id !== ${q}`));
  const nid = w.eval('OFD.doc.id');
  check((await call('GET', `/api/office/docs/${q}`)).status === 'superseded', 'yes: the old quotation is superseded');
  const html = await w.eval(`api('GET', '/api/office/docs/${q}').then(d => ofr_linkHtml(d))`);
  check(html.includes('Replaced by') && html.includes(`#office/offers/${nid}`), 'the old one links the new one: ' + html);
  const html2 = await w.eval(`api('GET', '/api/office/docs/${nid}').then(d => ofr_linkHtml(d))`);
  check(html2.includes('Replaces') && html2.includes(`#office/offers/${q}`), 'the new one links the old one: ' + html2);
  check(w.eval(`OFD_STATUS.some(x => x[0] === 'superseded')`), 'the status list has it');
  check(!errs.length, 'no script errors: ' + errs.join(' | '));
  w.close();

  console.log(`p2437_b_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack); process.exit(1); });
