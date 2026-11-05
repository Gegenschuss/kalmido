// 2.559.0 UI tests, part D (#4659): receipts are ticked and changed at once (optimistic), own container (start.sh, mode
// kalmido-suite: fresh
// workspaces), jsdom. Invented companies, people and figures only.
// - All receipts, multiple choice "Mark as checked": the rows carry "Checked" and the choice closes while the server's answer
//   is still held; a refusal takes the ticks back and brings the choice back, with the server's message
// - the box "Checked" of the receipt sheet stays usable, "Checked by Alice" shows before the answer; a refusal (409, locked
//   month) unticks it, the line goes back, the sheet says why
// - Save of the receipt sheet: the sheet closes at once, the row shows the new category while the first request is held; a
//   refusal puts the old category back
// - none of these actions fetches the whole state again (no GET /api/state)
// The held answers wait in the page (window.fetch wrapped) until the test lets them go: every wait is on a real state.
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, until: until0} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const until = fn => until0(fn, {timeout: 15000, step: 100});
const FEAT = 'cal,comments,collab,office,clients,docs';
const today = TC.today();
// requests matching re ("METHOD /url") wait in w.__held until the test calls go() (the real request) or fail(text, status)
const hold = (w, re) => {
  w.__held = []; const f1 = w.__f1 || (w.__f1 = w.fetch);
  w.fetch = (u, o = {}) => re.test(`${o.method || 'GET'} ${u}`)
    ? new Promise(res => w.__held.push({u: String(u), go: () => res(f1(u, o)), fail: (msg, st = 400) => res(new Response(JSON.stringify({error: msg}), {status: st, headers: {'content-type': 'application/json'}}))}))
    : f1(u, o);
};
const unhold = w => { if (w.__f1) w.fetch = w.__f1; };
// every request of the page in w.__sent (to see that no action fetches the whole state again)
const watch = w => { w.__sent = []; const f0 = w.fetch; w.fetch = (u, o = {}) => { w.__sent.push(`${o.method || 'GET'} ${u}`); return f0(u, o); }; };
const stateFetches = w => { let rep = 0; return w.__sent.filter(s => { if (!/^GET \/api\/state(\?|$)/.test(s)) return false; if (/auto=1/.test(s)) { rep = 2; return false; } if (rep) { rep--; return false; } return true; }); };  // the live poll (auto=1) and load()'s up to two repeats when a write crossed it are no reload of the action

function tinyPdf(text) {  // a one-page PDF with a text layer
  const s = `BT /F1 12 Tf 40 700 Td (${text}) Tj ET`;
  const o = ['<< /Type /Catalog /Pages 2 0 R >>', '<< /Type /Pages /Kids [3 0 R] /Count 1 >>', '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${s.length} >>\nstream\n${s}\nendstream`, '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>'];
  let out = '%PDF-1.4\n'; const offs = [];
  o.forEach((x, i) => { offs.push(out.length); out += `${i + 1} 0 obj\n${x}\nendobj\n`; });
  const xr = out.length; out += `xref\n0 ${o.length + 1}\n0000000000 65535 f \n` + offs.map(n => String(n).padStart(10, '0') + ' 00000 n \n').join('');
  return out + `trailer\n<< /Size ${o.length + 1} /Root 1 0 R >>\nstartxref\n${xr}\n%%EOF\n`;
}
async function receipt(ck, ws, name, amount, day) {
  const fd = new FormData(); fd.append('ws', ws); fd.append('files', new Blob([tinyPdf('Beleg ' + name)], {type: 'application/pdf'}), name);
  const r = await fetch(B + 'api/docs', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  const j = await r.json(); check(r.status === 201, 'upload ' + name + ' ' + r.status);
  const id = j.ids[0];
  check((await call(ck, 'PATCH', `/api/docs/${id}`, {amount, date: day})).http === 200, 'amount + date ' + name);
  check((await call(ck, 'PUT', `/api/docs/${id}/receipt`, {category: 'Material', vat_pct: '19', keep: true})).http === 200, 'receipt ' + name);
  return id;
}

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', lang: 'en'})});
  check(r.ok, 'setup');
  const CA = await login('alice');
  await call(CA, 'POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call(CA, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const me = (await call(CA, 'GET', '/api/state')).me;
  const org = await call(CA, 'POST', '/api/admin/orgs', {name: 'Alpha', admin_id: me.id});
  await call(CA, 'PATCH', '/api/settings', {workspace: `org:${org.id}`});
  const ws = `org:${org.id}`;
  const R1 = await receipt(CA, ws, 'papier.pdf', '119.00', today);
  const R2 = await receipt(CA, ws, 'toner.pdf', '59.50', today);
  const checkedIds = async () => ((await call(CA, 'GET', '/api/office/books/receipts?checked=yes')).rows || []).map(x => x.node_id);
  const catOf = async id => ((await call(CA, 'GET', '/api/office/books/receipts')).rows || []).find(x => x.node_id === id)?.category;

  const w = await boot({user: 'alice', hash: 'office/books/receipts'}), d = w.document;
  const rowOf = id => d.querySelector(`.rcl-list [data-id="${id}"]`)?.closest('li');
  const marked = id => !!rowOf(id)?.querySelector('.rcl-chk');
  const toastHas = re => re.test(d.querySelector('#toast')?.textContent || '');
  check(await until(() => d.querySelectorAll('.rcl-list > li').length === 2 && d.querySelector('.rcl-selbar [data-rcl="sel"]')), 'all receipts: two rows and "Select"');
  watch(w);

  // ================= multiple choice: a refusal takes the ticks back and brings the choice back
  const choose = async id => {
    d.querySelector('.rcl-selbar [data-rcl="sel"]').click();
    await until(() => d.querySelector(`.rcl-pickin[data-id="${id}"]`));
    d.querySelector(`.rcl-pickin[data-id="${id}"]`).click();
    return until(() => !d.querySelector('.rcl-selbar [data-rcl="chk"]')?.disabled);
  };
  hold(w, /^POST \/api\/office\/books\/receipts\/checked$/);
  check(await choose(R1), 'one receipt chosen');
  d.querySelector('.rcl-selbar [data-rcl="chk"]').click();
  check(await until(() => w.__held.length === 1), 'Mark as checked: the request is on its way (held)');
  check(marked(R1) && !marked(R2) && !d.querySelector('.rcl-pickin'), 'the row carries "Checked" and the choice closed before the answer');
  check(!(await checkedIds()).length, 'the server has no tick yet');
  w.__held[0].fail('Refused for the test');
  check(await until(() => !marked(R1) && d.querySelector(`.rcl-pickin[data-id="${R1}"]`)?.checked), 'the refusal takes the tick back and the choice comes back');
  check(await until(() => toastHas(/Refused for the test/)), 'with the server\'s message');
  // ... and the same once more, let through
  d.querySelector('.rcl-selbar [data-rcl="chk"]').click();
  check(await until(() => w.__held.length === 2), 'the second try is held');
  check(marked(R1) && !d.querySelector('.rcl-pickin'), 'it shows at once again');
  w.__held[1].go();
  check(await until(async () => (await checkedIds()).includes(R1)), 'the server stores the tick');
  check(await until(() => toastHas(/1 receipt marked as checked/)), 'the toast tells it after the answer');
  check(await until(() => marked(R1)), 'the row keeps the tick after the list came again');
  unhold(w);

  // ================= the box of the receipt sheet: at once, a refusal unticks it
  d.querySelector(`.rcl-list [data-rcl="rc"][data-id="${R2}"]`).click();
  check(await until(() => d.querySelector('.bk-sheet #bk-chk')), 'the receipt sheet opens with the box Checked');
  hold(w, /^POST \/api\/office\/books\/receipts\/checked$/);
  const box = d.querySelector('.bk-sheet #bk-chk');
  box.click();
  check(await until(() => w.__held.length === 1), 'the tick is on its way (held)');
  check(box.checked && !box.disabled && /Checked by Alice on/.test(d.querySelector('.bk-sheet .bk-chkby')?.textContent || ''), 'the box stays usable and "Checked by Alice" shows before the answer');
  check(marked(R2), 'the row behind the sheet carries the tick at once');
  w.__held[0].fail('The month is locked', 409);
  check(await until(() => !box.checked && !(d.querySelector('.bk-sheet .bk-chkby')?.textContent || '').trim()), 'the refusal unticks the box and the line goes');
  check(await until(() => /The month is locked/.test(d.querySelector('.bk-sheet .aerr')?.textContent || '')), 'the sheet says why');
  check(!marked(R2), 'the row is unticked again');
  check(!(await checkedIds()).includes(R2), 'the server has no tick for it');
  unhold(w);

  // ================= Save of the sheet: closes at once, the row shows the new category; a refusal puts it back
  hold(w, /^PATCH \/api\/docs\/\d+$/);
  d.querySelector('.bk-sheet #bk-cat').value = 'Software';
  d.querySelector('.bk-sheet [data-m="save"]').click();
  check(await until(() => w.__held.length === 1), 'Save: the first request is on its way (held)');
  check(!d.querySelector('.bk-sheet'), 'the sheet closed at once');
  check(/Software/.test(rowOf(R2)?.textContent || ''), 'the row shows the new category before the answer');
  check(await catOf(R2) === 'Material', 'the server has the old category still');
  w.__held[0].fail('Refused for the test');
  check(await until(() => /Material/.test(rowOf(R2)?.textContent || '') && !/Software/.test(rowOf(R2)?.textContent || '')), 'the refusal puts the old category back');
  // let through: both requests reach the server
  d.querySelector(`.rcl-list [data-rcl="rc"][data-id="${R2}"]`).click();
  check(await until(() => d.querySelector('.bk-sheet #bk-cat')), 'the sheet opens again');
  d.querySelector('.bk-sheet #bk-cat').value = 'Software';
  d.querySelector('.bk-sheet [data-m="save"]').click();
  check(await until(() => w.__held.length === 2), 'the second Save is held');
  check(!d.querySelector('.bk-sheet') && /Software/.test(rowOf(R2)?.textContent || ''), 'closed and shown at once again');
  w.__held[1].go();
  check(await until(async () => await catOf(R2) === 'Software'), 'the server stores the category');
  check(await until(() => toastHas(/Changed receipt/)), 'the undo toast comes after the answer');
  unhold(w);

  check(!stateFetches(w).length, 'no action fetched the whole state again: ' + stateFetches(w).join(' | '));
  w.close();
  console.log(`p2559_d_receipts_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
