// 2.559.0 UI tests, part D (#4660): budget entries are added, changed and deleted at once (optimistic), own container
// kalmido-suite: fresh
// (start.sh, mode workspaces), jsdom. Invented people and figures only. Run for a member of an organisation and for a
// person without an organisation (freelancer parity).
// - Add: the dialog closes and the row (provisional id) shows while the answer is still held; a refusal (500) takes the row
//   away with the server's message; let through, the row carries the real id and the undo is offered
// - Change: the dialog closes, the row shows the new amount before the answer; a refusal (400) puts the old amount back; saved
//   elsewhere in between (a real 409): the row goes back and the dialog opens again with the input and "Reload"
// - Delete with a receipt: the row goes at once (2.567.0, #4707: no question, it waits in the trash); a refusal brings it back
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
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const FEAT = 'collab,contracts,budget';
const DAY = TC.today(), MONTH = DAY.slice(0, 7);
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

async function round(who, ck) {
  const LID = (await call(ck, 'POST', '/api/budget/lists', {})).list_id;
  check(LID > 0, `${who}: a budget`);
  const rent = await call(ck, 'POST', `/api/budget/${LID}/entries`, {day: DAY, amount: 800, kind: 'out', title: 'Rent'});
  const books = await call(ck, 'POST', `/api/budget/${LID}/entries`, {day: DAY, amount: 30, kind: 'out', title: 'Books'});
  { const fd = new FormData(); fd.append('file', new Blob([tinyPdf('Quittung')], {type: 'application/pdf'}), 'quittung.pdf');
    const r = await fetch(B + `api/budget/entries/${books.id}/files`, {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
    check(r.ok, `${who}: a receipt on "Books" ${r.status}`); }
  const onServer = async () => (await call(ck, 'GET', `/api/budget/${LID}?month=${MONTH}`)).entries || [];

  const w = await boot({user: who, hash: `budget/${LID}`}), d = w.document;
  const dlg = () => d.querySelector('.modal.bgdlg');
  const rowOf = re => [...d.querySelectorAll('.bgview [data-bg="entry"]')].find(b => re.test(b.textContent));
  const toastHas = re => re.test(d.querySelector('#toast')?.textContent || '');
  check(await until(() => rowOf(/Rent/) && rowOf(/Books/) && d.querySelector('.bgview [data-bg="add"]')), `${who}: the budget shows its entries`);
  watch(w);

  // ================= add: at once, a refusal takes the row away
  const add = async () => {
    click(w, d.querySelector('.bgview [data-bg="add"]')); await until(() => dlg()?.querySelector('#bg-amt'));
    dlg().querySelector('#bg-amt').value = '12,50'; dlg().querySelector('#bg-title').value = 'Bakery'; dlg().querySelector('#bg-day').value = DAY;
    click(w, dlg().querySelector('[data-m="save"]'));
  };
  hold(w, /^POST \/api\/budget\/\d+\/entries$/);
  await add();
  check(await until(() => w.__held.length === 1), `${who}: Add: the request is on its way (held)`);
  check(!dlg() && rowOf(/Bakery/) && +rowOf(/Bakery/).dataset.id < 0, `${who}: the dialog closed and the row (provisional id) shows before the answer`);
  check(!(await onServer()).some(x => x.title === 'Bakery'), `${who}: the server has no entry yet`);
  w.__held[0].fail('Refused for the test', 500);
  check(await until(() => !rowOf(/Bakery/)), `${who}: the refusal takes the row away`);
  check(await until(() => toastHas(/Refused for the test/)), `${who}: with the server's message`);
  await add();
  check(await until(() => w.__held.length === 2), `${who}: the second Add is held`);
  check(!dlg() && rowOf(/Bakery/), `${who}: it shows at once again`);
  w.__held[1].go();
  check(await until(async () => (await onServer()).some(x => x.title === 'Bakery')), `${who}: the server stores the entry`);
  check(await until(() => +rowOf(/Bakery/)?.dataset.id > 0), `${who}: the row carries the real id`);
  check(await until(() => toastHas(/Added: Bakery/)), `${who}: the undo is offered after the answer`);
  unhold(w);

  // ================= change: at once, a refusal puts the old amount back
  const edit = async amt => {
    click(w, rowOf(/Rent/)); await until(() => dlg()?.querySelector('#bg-title')?.value === 'Rent');
    dlg().querySelector('#bg-amt').value = amt; click(w, dlg().querySelector('[data-m="save"]'));
  };
  hold(w, /^PATCH \/api\/budget\/entries\/\d+$/);
  await edit('99');
  check(await until(() => w.__held.length === 1), `${who}: Save: the request is held`);
  check(!dlg() && /99[.,]00/.test(rowOf(/Rent/)?.textContent || ''), `${who}: the dialog closed, the row shows the new amount before the answer`);
  w.__held[0].fail('Refused for the test');
  check(await until(() => /800[.,]00/.test(rowOf(/Rent/)?.textContent || '')), `${who}: the refusal puts the old amount back`);
  check(await until(() => toastHas(/Refused for the test/)), `${who}: with the server's message`);
  // saved elsewhere while the own save was on its way: the real 409 of the server
  await edit('99');
  check(await until(() => w.__held.length === 2), `${who}: the second Save is held`);
  check((await call(ck, 'PATCH', `/api/budget/entries/${rent.id}`, {title: 'Rent', amount: 850})).http === 200, `${who}: changed elsewhere in between`);
  w.__held[1].go();
  check(await until(() => /Changed in the meantime/.test(dlg()?.querySelector('.aerr')?.textContent || '')), `${who}: the conflict opens the dialog again with "Changed in the meantime"`);
  check(dlg()?.querySelector('#bg-amt')?.value.replace(/[.,]00$/, '') === '99', `${who}: ... with the own input ` + dlg()?.querySelector('#bg-amt')?.value);
  check(+(await onServer()).find(x => x.id === rent.id)?.amount === 850, `${who}: the other change stays on the server`);
  click(w, dlg().querySelector('[data-lf-reload]'));
  check(await until(() => /^850/.test(dlg()?.querySelector('#bg-amt')?.value || '')), `${who}: Reload shows the saved version`);
  check(await until(() => /850[.,]00/.test(rowOf(/Rent/)?.textContent || '')), `${who}: the row shows the saved version`);
  // the saved version changed and let through
  dlg().querySelector('#bg-amt').value = '99'; click(w, dlg().querySelector('[data-m="save"]'));
  check(await until(() => w.__held.length === 3), `${who}: the third Save is held`);
  check(!dlg() && /99[.,]00/.test(rowOf(/Rent/)?.textContent || ''), `${who}: shown at once again`);
  w.__held[2].go();
  check(await until(async () => +(await onServer()).find(x => x.id === rent.id)?.amount === 99), `${who}: the server stores 99`);
  check(await until(() => toastHas(/Saved/)), `${who}: "Saved" after the answer`);
  unhold(w);

  // ================= delete with a receipt: at once (2.567.0 #4707: no question any more, the trash keeps it); a refusal brings it back
  const asked = []; w.confirm = t => { asked.push(t); return true; };
  const del = async () => {
    click(w, rowOf(/Books/)); await until(() => dlg()?.querySelector('[data-bg-del]'));
    click(w, dlg().querySelector('[data-bg-del]'));
  };
  hold(w, /^DELETE \/api\/budget\/entries\/\d+$/);
  await del();
  check(await until(() => w.__held.length === 1), `${who}: Delete: the request is held`);
  // 2.567.0 (#4707): the entry and its receipt go to the trash, so there is no question any more
  check(asked.length === 0, `${who}: no question before the delete (the trash keeps the receipt) ` + asked.join(' | '));
  check(!dlg() && !rowOf(/Books/), `${who}: the dialog closed and the row is gone before the answer`);
  w.__held[0].fail('Refused for the test', 500);
  check(await until(() => rowOf(/Books/)), `${who}: the refusal brings the row back`);
  await del();
  check(await until(() => w.__held.length === 2), `${who}: the second Delete is held`);
  check(!rowOf(/Books/), `${who}: gone at once again`);
  w.__held[1].go();
  check(await until(async () => !(await onServer()).some(x => x.title === 'Books')), `${who}: the server deleted it`);
  check(await until(() => toastHas(/Deleted: Books/)), `${who}: the undo is offered after the answer`);
  unhold(w);
  await sleep(300);  // a reload the actions might start would be on its way by now
  check(!stateFetches(w).length, `${who}: no action fetched the whole state again: ` + stateFetches(w).join(' | '));
  w.close();
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
  await round('alice', CA);

  // ================= a person without an organisation: the same at once
  await call(CA, 'POST', '/api/users', {username: 'frida', display_name: 'Frida', password: 'password123', email: 'frida@example.com', orgs: []});
  const CF = await login('frida');
  await call(CF, 'PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT, workspace: 'private'});
  check(((await call(CF, 'GET', '/api/state')).me.workspaces || []).length === 0, 'frida has no organisation');
  await round('frida', CF);

  console.log(`p2559_d_budget_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
