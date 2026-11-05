// 2.559.0 UI test, part B (#4659): the document sheet shows its changes at once (optimistic), jsdom, invented names only:
// kalmido-suite: fresh
// - sender, type, tags, date: the sheet (DC.doc, the field after the redraw) has the new value while the PATCH is held;
//   a refusal (500) puts the old value back; the answer keeps it (saved on the server)
// - "Checked" in "To review": the next document opens while the POST is held; a refusal marks the first one "To review"
//   again (its card, the list); a second try saves it
// - none of these fetches GET /api/state while the request is on its way
// freelancer-matrix: docs (alice has no organisation: her private workspace)
// The held answers wait in the page (window.fetch wrapped) until the test lets them go: every wait is on a real state.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, until: until0} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const until = (fn, ms = 15000) => until0(fn, {timeout: ms, step: 150});
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const hold = (w, re) => {
  w.__held = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => { const k = `${o.method || 'GET'} ${u}`; (w.__log = w.__log || []).push(k);
    return re.test(k) ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: (st = 500) => res(new Response(JSON.stringify({error: 'Refused for the test'}), {status: st, headers: {'content-type': 'application/json'}}))})) : f1(u, o); };
};
// no load() of the own action since mark i (no GET /api/state before or after the answer): load() is wrapped once and notes
// whether it was the live update's (load(true, ...), it may come on its own after any write) or an action's own (load())
const mark = w => {
  if (!w.__lw) { w.__lw = 1; w.eval(`{ const l0 = load; load = (...a) => { (window.__loads = window.__loads || []).push(a[0] ? 'auto' : 'own'); return l0(...a); }; }`); }
  return (w.__loads || []).length;
};
const noState = (w, i) => !(w.__loads || []).slice(i).includes('own');

function textPdf(lines) {  // a one-page PDF with a text layer, written by hand (like p248_b_ui.js)
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
const ready = id => until(async () => { const d = await call('GET', `/api/docs/${id}`); return d.state === 'done' ? d : null; }, 30000);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en'});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const D1 = await upload('letter-one.pdf', ['Example Insurance Ltd', 'Policy letter', 'Date 01.09.2026']);
  const D2 = await upload('letter-two.pdf', ['Sample Utility Co', 'Meter reading', 'Date 03.10.2026']);
  const r1 = await ready(D1), r2 = await ready(D2);
  check(r1 && r2, 'two documents recognised');
  // both to review (whatever the recognition decided)
  for (const id of [D1, D2]) await call('POST', `/api/docs/${id}/review`, {done: false});

  const w = await boot({user: 'alice', hash: 'docs/review'}), d = w.document;
  check(await until(() => d.querySelectorAll('.dc-card').length === 2), 'To review: two cards');
  const order = w.eval(`DC.docs.map(x => x.id)`), A = order[0], N = order[1];
  click(w, d.querySelector(`[data-dco="${A}"]`));
  check(await until(() => d.querySelector('.dc-md #dc-sender') && w.eval(`DC.doc?.id === ${A}`)), 'the sheet of the first document');
  const oldSender = w.eval(`DC.doc.sender?.name || ''`);

  // ================= fields: the new value stands while the PATCH is held; a refusal puts the old one back
  const setField = (id, v) => { const el = d.querySelector('.dc-md #' + id); el.value = v; el.dispatchEvent(new w.Event('change', {bubbles: true})); };
  hold(w, /^PATCH \/api\/docs\/\d+$/);
  let i0 = mark(w);
  setField('dc-sender', 'Acme Paper');
  check(await until(() => w.__held.length === 1), 'sender: the request is held');
  check(w.eval(`DC.doc.sender?.name`) === 'Acme Paper' && d.querySelector('.dc-md #dc-sender').value === 'Acme Paper', 'sender: the sheet has the new value before the answer');
  check(noState(w, i0), 'sender: no GET /api/state');
  w.__held[0].fail(500);
  check(await until(() => w.eval(`(DC.doc.sender?.name || '')`) === oldSender && d.querySelector('.dc-md #dc-sender').value === oldSender), 'sender: a refusal puts the old value back');
  hold(w, /^PATCH \/api\/docs\/\d+$/);
  setField('dc-sender', 'Acme Paper');
  check(await until(() => w.__held.length === 1 && w.eval(`DC.doc.sender?.name`) === 'Acme Paper'), 'sender again: at once');
  w.__held[0].go();
  check(await until(async () => (await call('GET', `/api/docs/${A}`)).sender?.name === 'Acme Paper'), 'sender: saved on the server');
  check(await until(() => d.querySelector('.dc-md #dc-sender')?.value === 'Acme Paper'), 'sender: the answer keeps it');

  hold(w, /^PATCH \/api\/docs\/\d+$/);
  setField('dc-type', 'Letter');
  check(await until(() => w.__held.length === 1 && w.eval(`DC.doc.type?.name`) === 'Letter'), 'type: at once');
  w.__held[0].go();
  hold(w, /^PATCH \/api\/docs\/\d+$/);
  setField('dc-tags', 'home, insurance');
  check(await until(() => w.__held.length === 1 && w.eval(`DC.doc.tags.map(t => t.name).join('|')`) === 'home|insurance'), 'tags: at once (two tags) ' + w.eval(`JSON.stringify([DC.doc.tags, window.__held.length])`));
  check(d.querySelector('.dc-md #dc-tags').value === 'home, insurance', 'tags: the field after the redraw');
  w.__held[0].fail(500);
  check(await until(() => !w.eval(`DC.doc.tags.length`)), 'tags: a refusal takes them back');
  hold(w, /^PATCH \/api\/docs\/\d+$/);
  setField('dc-date', '2026-09-02');
  check(await until(() => w.__held.length === 1 && w.eval(`DC.doc.date`) === '2026-09-02'), 'date: at once ' + w.eval(`JSON.stringify([DC.doc.date, window.__held.length])`));
  w.__held[0].go();
  check(await until(async () => { const x = await call('GET', `/api/docs/${A}`); return x.type?.name === 'Letter' && x.date === '2026-09-02' && !x.tags.length; }), 'type + date saved, the refused tags not');

  // ================= "Checked": the next document at once, the POST held; a refusal marks it "To review" again
  hold(w, /^POST \/api\/docs\/\d+\/review$/);
  i0 = mark(w);
  click(w, d.querySelector('.dc-md [data-dc="checked"]'));
  check(await until(() => w.__held.length === 1), 'checked: the request is held');
  check(await until(() => w.eval(`DC.doc?.id === ${N}`) && d.querySelector('.dc-md [data-dc="checked"]')), 'checked: the next document opened before the answer');
  check(w.eval(`DC.docs.find(x => x.id === ${A}).review === false`) && !d.querySelector(`.dc-card[data-k="dc${A}"]`)?.classList.contains('rev'), 'checked: the card is no longer "To review" at once');
  check(noState(w, i0), 'checked: no GET /api/state');
  w.__held[0].fail(500);
  check(await until(() => w.eval(`DC.docs.find(x => x.id === ${A})?.review === true`) && d.querySelector(`.dc-card[data-k="dc${A}"]`)?.classList.contains('rev')), 'checked: a refusal marks it "To review" again');
  check((await call('GET', `/api/docs/${A}`)).review === true, 'checked: the server still has it to review');
  // a second try from its own sheet
  click(w, d.querySelector(`[data-dco="${A}"]`));
  await until(() => w.eval(`DC.doc?.id === ${A}`) && d.querySelector('.dc-md [data-dc="checked"]'));
  hold(w, /^POST \/api\/docs\/\d+\/review$/);
  click(w, d.querySelector('.dc-md [data-dc="checked"]'));
  check(await until(() => w.__held.length === 1 && w.eval(`DC.doc?.id === ${N}`)), 'checked again: on to the next at once');
  w.__held[0].go();
  check(await until(async () => (await call('GET', `/api/docs/${A}`)).review === false), 'checked: saved on the server');

  w.close();
  console.log(`p2559_b_docs_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
