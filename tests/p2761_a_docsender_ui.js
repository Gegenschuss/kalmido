// 2.761.0 UI test, part A (#4868): sender and document type with the suggestion field of the tags (tagsel.js tf_html,
// one value), jsdom, own container (start.sh),
// kalmido-suite: fresh
// invented names only. P2761A_NOSTART=1 = the container runs.
// - the document view: sender / type are a combobox in a .tfld.tf1, no <datalist>; the value stands in the field itself
// - "Te" opens the own list with the known senders (the start first), Enter takes the marked one and saves it (PATCH)
// - a new name + Enter makes a new sender; a comma is part of the name; another spelling of a known one = the known one
// - leaving the field after Enter saves nothing a second time (one undo step)
// - the rule form (docflows.js): then sender / then type / sender is / type is use the same field, Enter sets the value
// P4: alice works without an organisation (private documents): the person without an organisation (freelancer-matrix: docs)
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2761A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 75) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const keyOn = (w, el, k, o = {}) => el.dispatchEvent(new w.KeyboardEvent('keydown', {key: k, bubbles: true, cancelable: true, ...o}));
const type = (w, el, v) => { el.focus(); el.value = v; el.dispatchEvent(new w.Event('input', {bubbles: true})); };

function pdf(lines) {  // a one-page PDF with a text layer, written by hand
  const esc = s => s.replace(/[\\()]/g, c => '\\' + c);
  const st = 'BT /F1 12 Tf 60 740 Td 16 TL ' + lines.map(l => `(${esc(l)}) '`).join(' ') + ' ET';
  const objs = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${st.length} >>\nstream\n${st}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  objs.forEach((o, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${o}\nendobj\n`; });
  const x = out.length;
  out += `xref\n0 ${objs.length + 1}\n0000000000 65535 f \n` + offs.map(o => String(o).padStart(10, '0') + ' 00000 n \n').join('');
  out += `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\nstartxref\n${x}\n%%EOF\n`;
  return Buffer.from(out, 'latin1');
}
async function upload(name, lines) {
  const fd = new FormData();
  fd.append('files', new Blob([pdf(lines)], {type: 'application/pdf'}), name);
  fd.append('ws', 'private');
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: CK}, body: fd});
  const id = (await r.json()).ids[0];
  await until(async () => ['done', 'failed'].includes((await call('GET', `/api/docs/${id}`)).state), 150);
  return id;
}
const doc = async id => call('GET', `/api/docs/${id}`);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en'});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const D1 = await upload('letter.pdf', ['Example Insurance Ltd', 'Policy letter', 'Date 01.09.2026']);
  const D2 = await upload('other.pdf', ['Sample Utility Co', 'Meter reading', 'Date 03.10.2026']);
  // the known senders / types of the workspace come from another document
  for (const s of ['Telekom Beispiel', 'Bauamt Nord', 'Hotel Tegernsee']) await call('PATCH', `/api/docs/${D2}`, {sender: s});
  for (const t of ['Rechnung', 'Vertrag']) await call('PATCH', `/api/docs/${D2}`, {type: t});
  check((await call('PATCH', `/api/docs/${D1}`, {sender: '', type: ''})).status === 200, 'the first document without sender / type');

  const w = await boot({user: 'alice', hash: `docs/${D1}`}), d = w.document;
  const snd = () => d.querySelector('.dv-view #dc-sender'), typ = () => d.querySelector('.dv-view #dc-type');
  const lb = () => d.querySelector('body > .tflb'), opts = () => [...(lb()?.querySelectorAll('[role="option"]') || [])];
  const names = () => opts().map(o => o.textContent.trim());
  check(await until(() => snd() && typ() && w.eval(`(DC.set?.senders || []).length >= 3`)), 'the view shows the sender field');
  check(snd()?.closest('.tfld.tf1') && snd()?.getAttribute('role') === 'combobox' && !snd()?.hasAttribute('list') && !d.querySelector('.dv-view #dc-sl, .dv-view #dc-tl'), 'sender: the suggestion field, no datalist');
  check(typ()?.closest('.tfld.tf1') && typ()?.getAttribute('placeholder'), 'type: the same field, the placeholder stays');
  check(snd()?.dataset.dcp === 'sender' && typ()?.dataset.dcp === 'type', 'the text field itself saves (data-dcp)');

  // ================= "Te": the known senders, the start first; Enter takes and saves
  type(w, snd(), 'Te');
  check(await until(() => opts().length), '"Te" opens the list');
  check(names()[0] === 'Telekom Beispiel' && names().includes('Hotel Tegernsee') && !names().includes('Bauamt Nord'), 'the start first, then within: ' + names().join(', '));
  keyOn(w, snd(), 'Enter');
  check(await until(async () => (await doc(D1)).sender?.name === 'Telekom Beispiel'), 'Enter takes the marked sender and saves it');
  check(await until(() => snd()?.value === 'Telekom Beispiel' && !lb()), 'the field shows it, the list is closed');
  w.eval(`window.__p2761 = 0; { const a0 = api; api = (m, u, b) => { if (m === 'PATCH' && /^\\/api\\/docs\\/\\d+$/.test(u)) window.__p2761++; return a0(m, u, b); }; }`);
  snd().dispatchEvent(new w.Event('change', {bubbles: true}));  // the browser's change when leaving the field
  snd().blur();
  keyOn(w, snd(), 'Enter');  // Enter on the saved value
  // a later save is the proof the requests are counted: then the count must be exactly that one
  snd().focus(); snd().value = 'Hotel Tegernsee'; snd().dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await doc(D1)).sender?.name === 'Hotel Tegernsee'), 'a real change saves');
  check(w.eval('window.__p2761') === 1, 'leaving the field after Enter / Enter on the saved value save nothing: ' + w.eval('window.__p2761'));

  // ================= a new name with a comma; another spelling of a known one
  type(w, snd(), 'Müller, Schmidt GbR');
  check(await until(() => /New: Müller, Schmidt GbR/.test(names().pop() || '')), 'a comma stays in the name, "New: …" offered');
  keyOn(w, snd(), 'Enter');
  check(await until(async () => (await doc(D1)).sender?.name === 'Müller, Schmidt GbR'), 'Enter on "New: …" makes the new sender');
  snd().focus(); snd().value = 'bauamt nord'; snd().dispatchEvent(new w.Event('change', {bubbles: true}));
  check(await until(async () => (await doc(D1)).sender?.name === 'Bauamt Nord'), 'another spelling of a known sender = the known one');

  // ================= the type the same way
  type(w, typ(), 'rech');
  check(await until(() => names()[0] === 'Rechnung'), 'type: "rech" offers Rechnung');
  keyOn(w, typ(), 'Tab');
  check(await until(async () => (await doc(D1)).type?.name === 'Rechnung'), 'Tab takes the type and saves it');

  // ================= the rule form (docflows.js): the same field, Enter sets the value
  w.eval(`{ const b = document.createElement('div'); b.id = 'p2761flow'; b.innerHTML = dfl_formHtml(DC.set); document.body.appendChild(b); }`);
  const rs = () => d.querySelector('#p2761flow #dcr-sender');
  for (const id of ['dcr-sender', 'dcr-type', 'dfl-hsender', 'dfl-htype']) check(d.querySelector(`#p2761flow #${id}`)?.closest('.tfld.tf1'), `rule form: ${id} is the suggestion field`);
  check(!d.querySelector('#p2761flow #dcr-sl, #p2761flow #dcr-tl'), 'rule form: no datalist for sender / type');
  type(w, rs(), 'tel');
  check(await until(() => names()[0] === 'Telekom Beispiel'), 'rule form: the list of the senders');
  keyOn(w, rs(), 'Enter');
  check(rs().value === 'Telekom Beispiel' && w.eval(`dfl_collect(document.getElementById('p2761flow'), DC.set).sender`) === 'Telekom Beispiel', 'rule form: Enter sets the value the rule saves');
  w.close();

  console.log(`p2761_a_docsender_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
