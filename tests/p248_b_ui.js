// 2.48.0 UI tests of part B (#1111, own container, start.sh; P248B_NOSTART=1: the container runs already). jsdom:
// - the area Documents (route #docs): cards with name / sender, the counter "To review", the search, the filter "To review"
// - opening a document (#docs/<id>): the sheet with its fields, changing the sender = one undo step (Undo restores it)
// - a value set by a rule carries the "automatic" mark; one click on it puts the focus into the field
// - "Checked" takes the document out of "To review" (one undo step); a document a rule sorted surely needs no review
// - settings: a level per feature, renaming a type (one undo step); the share sheet offers "File as document"
// - adding by the button (FormData) = one undo step; phone width: cards and the sheet work
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P248B_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 200 : 15000, step: 200});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

function textPdf(lines) {  // a one-page PDF with a text layer, written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c);
  const stream = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
async function upload(name, lines) {
  const fd = new FormData();
  fd.append('files', new Blob([textPdf(lines)], {type: 'application/pdf'}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  return (await r.json()).ids[0];
}
const ready = id => until(async () => { const d = await call('GET', `/api/docs/${id}`); return d.state === 'done' ? d : null; }, 150);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const st = await call('GET', '/api/state');
  check((st.settings?.features || '').split(',').includes('docs'), 'the module "docs" is on by default ' + st.settings?.features);
  await call('POST', '/api/docs/rules', {ws: 'private', kind: 'any', match: 'Kilowattstunden', type: 'Abschlag'});
  const D1 = await upload('insurance.pdf', ['Versicherung Beispiel AG', 'Police Haftpflicht', 'Rechnungsbetrag 89,90 EUR', 'Datum 01.09.2026']);
  const D2 = await upload('power.pdf', ['Stadtwerke Musterstadt', 'Kilowattstunden Abschlag', 'Datum 03.10.2026']);
  await ready(D1); await ready(D2);

  const w = await boot({user: 'alice', hash: 'docs'}), d = w.document;
  await until(() => d.querySelectorAll('.dc-card').length === 2);
  check(d.querySelector('#view .dc-view'), 'route #docs shows the documents');
  check(d.querySelectorAll('.dc-card').length === 2, 'two cards');
  check(d.querySelector('#srail [data-sbb="ablage"]'), 'the bar has the area icon');  // 2.152.2 (#2622): the area row is an icon of the bar
  check(/To review/.test(d.querySelector('[data-dc="review"]')?.textContent || '') && d.querySelector('.dc-count'), 'the counter "To review"');

  // ================= search
  const q = d.querySelector('#dc-q');
  q.value = 'haftpflicht'; q.dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(() => d.querySelectorAll('.dc-card').length === 1);
  check(d.querySelectorAll('.dc-card').length === 1 && d.querySelector(`[data-dco="${D1}"]`), 'search: one card with the word');
  d.querySelector('#dc-q').value = ''; d.querySelector('#dc-q').dispatchEvent(new w.Event('input', {bubbles: true}));
  await until(() => d.querySelectorAll('.dc-card').length === 2);

  // ================= open, change the sender, undo
  d.querySelector(`[data-dco="${D1}"]`).click();
  const md = await until(() => d.querySelector('.dc-md #dc-sender'));
  check(md, 'the document sheet with its fields');
  check(w.location.hash === `#docs/${D1}`, 'the address names the document ' + w.location.hash);
  check(/89[.,]90/.test(d.querySelector('#dc-amount')?.value || '') && d.querySelector('#dc-date')?.value === '2026-09-01', 'amount and date recognised');
  const sIn = d.querySelector('#dc-sender');
  sIn.value = 'Versicherung Beispiel AG'; sIn.dispatchEvent(new w.Event('change', {bubbles: true}));
  await until(async () => (await call('GET', `/api/docs/${D1}`)).sender?.name === 'Versicherung Beispiel AG');
  check((await call('GET', `/api/docs/${D1}`)).sender?.name === 'Versicherung Beispiel AG', 'changing the sender saves it');
  check(w.eval(`HIST.undo.length && /Sender/.test(HIST.undo[HIST.undo.length - 1].label)`), 'the change = one undo step');
  await w.eval(`histStep('undo')`);
  await until(async () => !(await call('GET', `/api/docs/${D1}`)).sender);
  check(!(await call('GET', `/api/docs/${D1}`)).sender, 'Undo takes the sender back');

  // ================= "Checked"
  await until(() => d.querySelector('.dc-md [data-dc="checked"]'));
  d.querySelector('.dc-md [data-dc="checked"]').click();
  await until(async () => !(await call('GET', `/api/docs/${D1}`)).review);
  check(!(await call('GET', `/api/docs/${D1}`)).review, '"Checked" takes it out of To review');
  check(w.eval(`/checked/.test(HIST.undo[HIST.undo.length - 1].label)`), '"Checked" = one undo step');
  d.querySelector('.dc-md [data-dc="close"]')?.click();
  await sleep(300);

  // ================= the "automatic" mark of a rule
  d.querySelector(`[data-dco="${D2}"]`).click();
  const auto = await until(() => d.querySelector('.dc-md [data-dc="edit:type"]'));
  check(auto && /automatic/.test(auto.textContent) && d.querySelector('#dc-type').value === 'Abschlag', 'a rule\'s value is marked automatic');
  if (auto) { auto.click(); check(d.activeElement === d.querySelector('#dc-type'), 'one click on the mark: into the field'); }
  d.querySelector('.dc-md [data-dc="close"]')?.click();
  await sleep(300);

  // ================= filter "To review"
  d.querySelector('[data-dc="review"]').click();
  await until(() => d.querySelectorAll('.dc-card').length === 0);
  check(d.querySelectorAll('.dc-card').length === 0 && /No documents found/.test(d.querySelector('.dc-empty')?.textContent || ''),
    'To review: empty (one checked, the other sorted by a sure rule)');
  d.querySelector('[data-dc="all"]').click();
  await until(() => d.querySelectorAll('.dc-card').length === 2);

  // ================= settings: rename a type (one undo step)
  await w.eval(`dc_settings()`);
  await until(() => d.querySelector('.dc-smd .dc-lbls'));
  check(d.querySelectorAll('.dc-smd [data-dcl]').length === 4, 'settings: a level per feature');
  const tid = (await call('GET', `/api/docs/${D2}`)).type?.id;
  w.prompt = () => 'Monthly payment';
  d.querySelector(`.dc-smd [data-dcs="lren:type:${tid}"]`)?.click();
  await until(async () => (await call('GET', `/api/docs/${D2}`)).type?.name === 'Monthly payment');
  check((await call('GET', `/api/docs/${D2}`)).type?.name === 'Monthly payment', 'rename a type in the settings');
  await w.eval(`histStep('undo')`);
  await until(async () => (await call('GET', `/api/docs/${D2}`)).type?.name === 'Abschlag');
  check((await call('GET', `/api/docs/${D2}`)).type?.name === 'Abschlag', 'Undo: the old name');
  d.querySelector('.dc-smd [data-dcs="close"]')?.click();
  await sleep(300);
  // the share sheet offers "File as document" when files come
  w.eval(`shareDest([], true)`);
  check(await until(() => d.querySelector('.modal [data-sd="doc"]')), 'share sheet: "File as document"');
  d.querySelector('.modal [data-sd="task"]')?.click();
  await sleep(200);

  // ================= add by the button
  await w.eval(`dc_upload([new File(['Notiz zum Vertrag 12.10.2026'], 'note.txt', {type: 'text/plain'})])`);
  await until(() => d.querySelectorAll('.dc-card').length === 3);
  check(d.querySelectorAll('.dc-card').length === 3, 'added by the button: a third card');
  check(w.eval(`/added/.test(HIST.undo[HIST.undo.length - 1].label)`), 'adding = one undo step');
  w.close();

  // ================= phone width
  const m = await boot({user: 'alice', hash: 'docs', mobile: true}), d2 = m.document;
  await until(() => d2.querySelectorAll('.dc-card').length === 3);
  check(d2.querySelectorAll('.dc-card').length === 3, 'phone: the cards');
  d2.querySelector(`[data-dco="${D2}"]`).click();
  check(await until(() => d2.querySelector('.dc-md #dc-type')), 'phone: the sheet opens');
  m.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
