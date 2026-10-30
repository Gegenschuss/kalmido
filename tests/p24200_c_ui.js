// kalmido-suite: fresh
// 2.420.0 UI tests, part C (#3448): receipts ticked as checked, own container (start.sh, mode workspaces), Firefox (desktop +
// phone width). Invented companies, people and figures only.
// - All receipts: "Select" -> a box per row, "Mark as checked" ticks the chosen ones (mark "Checked" on the rows), undo
//   takes it back, "Remove check" unticks
// - the filter Checked / Not checked makes the list shorter
// - the receipt sheet has the box "Checked" with "Checked by <name> on <day>"; ticking there is stored at once
// - on a phone the bar of the multiple choice fits and its targets are large
const path = require('path');
const {execFileSync} = require('child_process');
const {sleep, B, login} = require('./boot');
const TC = require('./testclock');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const firefox = require('./ff')({tag: 'p24200_c_ui', check, shots: 'P24200C_SHOTS'});
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (process.env.P24200C_NOSTART !== '1') execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_INSTANCE_MODE=workspaces'}});
const call = async (ck, method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); const j = await r.json().catch(() => ({})); return {...j, http: r.status}; };
const FEAT = 'cal,comments,collab,office,clients,docs';
const today = TC.today();

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
  const R3 = await receipt(CA, ws, 'kabel.pdf', '23.80', today);
  const checkedIds = async () => ((await call(CA, 'GET', '/api/office/books/receipts?checked=yes')).rows || []).map(x => x.node_id).sort((a, b) => a - b);

  const ready = async (ev, expr, n = 40) => { for (let i = 0; i < n; i++) { if (await ev(expr).catch(() => false)) return true; await sleep(250); } return false; };
  const signIn = (ev, u) => ev(`fetch('/api/auth/login', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'}, body: JSON.stringify({username: '${u}', password: 'password123'})}).then(r => r.status)`);
  const rows = `document.querySelectorAll('.rcl-list > li').length`;
  const marks = `document.querySelectorAll('.rcl-list .rcl-chk').length`;
  const pick = id => `(() => { const b = document.querySelector('.rcl-pickin[data-id="${id}"]'); if (!b) return 0; b.click(); return 1; })()`;
  const click = sel => `(() => { const b = document.querySelector('${sel}'); if (!b || b.disabled) return 0; b.click(); return 1; })()`;
  const noSide = `(() => { const W = document.documentElement.clientWidth; return [...document.querySelectorAll('.office .ofcbody *')].filter(e => e.getClientRects().length && !e.closest('.seg')).every(e => e.getBoundingClientRect().right <= W + 1); })()`;
  await firefox(async ({cmd, ev, ctx, nav, shot}) => {
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 1280, height: 900}});
    await nav(B + 'static/icon.svg');
    await ev(`(() => { localStorage.clear(); sessionStorage.clear(); localStorage.setItem('tasks.theme', '"light"'); return 1; })()`);
    await signIn(ev, 'alice');
    await nav(B + '#office/books/receipts');
    check(await ready(ev, `${rows} === 3 && !!document.querySelector('.rcl-selbar [data-rcl="sel"]')`, 80), 'all receipts with the button "Select" ' + await ev(`location.hash + ' ' + ${rows}`).catch(e => String(e)));
    check(await ev(`${marks} === 0 && !!document.querySelector('.rcl-chkf [data-rcl="checked"][data-v="no"]')`), 'nothing checked yet, the filter Checked is there');
    // the multiple choice
    await ev(click('.rcl-selbar [data-rcl="sel"]'));
    check(await ready(ev, `document.querySelectorAll('.rcl-pickin').length === 3 && document.querySelector('.rcl-selbar [data-rcl="chk"]').disabled`), 'Select: a box per row, the action waits for a choice');
    await ev(pick(R1)); await ev(pick(R2));
    check(await ready(ev, `/2 selected/.test(document.querySelector('.rcl-seln')?.textContent || '') && !document.querySelector('.rcl-selbar [data-rcl="chk"]').disabled`), 'two rows chosen');
    await shot('p24200-c-select.png');
    await ev(click('.rcl-selbar [data-rcl="chk"]'));
    check(await ready(ev, `${marks} === 2 && !document.querySelector('.rcl-pickin')`, 60), 'Mark as checked: two rows carry "Checked", the choice ends ' + await ev(marks));
    check(JSON.stringify(await checkedIds()) === JSON.stringify([R1, R2].sort((a, b) => a - b)), 'stored on the server');
    check(await ev(`/Checked by Alice/.test(document.querySelector('.rcl-chk')?.title || '')`), 'the mark tells who checked');
    // undo of the toast
    check(await ready(ev, `/2 receipts marked as checked/.test(document.querySelector('#toast:not(.hidden)')?.textContent || '') && !!document.querySelector('#toast:not(.hidden) button:not(.tx)')`), 'the toast tells it and offers Undo');
    await ev(click('#toast:not(.hidden) button:not(.tx)'));
    check(await ready(ev, `${marks} === 0`, 60), 'Undo takes the ticks back');
    check((await checkedIds()).length === 0, 'Undo: nothing checked on the server');
    // tick all three, remove the check of one
    await ev(click('.rcl-selbar [data-rcl="sel"]'));
    await ready(ev, `document.querySelectorAll('.rcl-pickin').length === 3`);
    await ev(click('.rcl-selbar [data-rcl="selall"]'));
    check(await ready(ev, `/3 selected/.test(document.querySelector('.rcl-seln')?.textContent || '')`), 'Select all');
    await ev(click('.rcl-selbar [data-rcl="chk"]'));
    check(await ready(ev, `${marks} === 3`, 60), 'all three checked');
    await ev(click('.rcl-selbar [data-rcl="sel"]'));
    await ready(ev, `document.querySelectorAll('.rcl-pickin').length === 3`);
    await ev(pick(R3));
    await ready(ev, `!document.querySelector('.rcl-selbar [data-rcl="unchk"]').disabled`);
    await ev(click('.rcl-selbar [data-rcl="unchk"]'));
    check(await ready(ev, `${marks} === 2`, 60), 'Remove check: one row less with the mark');
    // the filter
    await ev(click('.rcl-chkf [data-rcl="checked"][data-v="no"]'));
    check(await ready(ev, `${rows} === 1 && !!document.querySelector('.rcl-list [data-id="${R3}"]')`, 60), 'filter Not checked: only the unchecked receipt');
    await ev(click('.rcl-chkf [data-rcl="checked"][data-v="yes"]'));
    check(await ready(ev, `${rows} === 2 && ${marks} === 2`, 60), 'filter Checked: the two checked receipts');
    await ev(click('.rcl-chkf [data-rcl="checked"][data-v="all"]'));
    await ready(ev, `${rows} === 3`, 60);
    // the receipt sheet
    await ev(click(`.rcl-list [data-rcl="rc"][data-id="${R3}"]`));
    check(await ready(ev, `!!document.querySelector('.bk-sheet #bk-chk') && !document.querySelector('.bk-sheet #bk-chk').checked`, 60), 'the receipt sheet has the box Checked (empty)');
    await ev(click('.bk-sheet #bk-chk'));
    check(await ready(ev, `/Checked by Alice on/.test(document.querySelector('.bk-sheet .bk-chkby')?.textContent || '')`, 60), 'ticked in the sheet: who and when');
    check((await checkedIds()).includes(R3), 'the sheet stores the tick at once');
    await shot('p24200-c-sheet.png');
    await ev(click('.bk-sheet [data-m="close"]'));
    check(await ready(ev, `${marks} === 3`, 60), 'the list follows the sheet');
    // phone width
    await cmd('browsingContext.setViewport', {context: ctx, viewport: {width: 390, height: 844}});
    await sleep(300);
    await ev(click('.rcl-selbar [data-rcl="sel"]'));
    await ready(ev, `document.querySelectorAll('.rcl-pickin').length === 3`);
    check(await ev(noSide), 'on a phone the bar of the multiple choice fits');
    check(await ev(`[...document.querySelectorAll('.rcl-selbar .btn')].every(b => b.getBoundingClientRect().height >= 44)`), 'on a phone its targets are large');
    await shot('p24200-c-phone.png');
  }, false);

  console.log(`p24200_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
