// 2.122.0 UI tests of part A (#2097, own container, start.sh; P2122A_NOSTART=1: the container runs already). jsdom:
// - the folder's menu offers "Request files…"; the dialog lists the folder's requests (none yet), "New file request"
//   opens the form (title from the folder, end date in 14 days, documents + pictures ticked), creating = a row with the
//   link, copy and QR, ONE undo step (Undo removes it again, Redo brings it back)
// - the row's menu: stop the link (the row says "Stopped", one undo step)
// - the public page /u/<token> with its own script: dropped files are listed (a wrong kind is marked at once), the send
//   uploads them with a progress bar, the thank-you line; the file is in the folder
// - the notification settings have the row "Files from file requests"; phone width: the dialog fits
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login, PooledLoader} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2122A_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  await call('PATCH', '/api/admin/settings', {public_links: true});
  const FID = (await call('POST', '/api/files/folders', {name: 'Invoices', space: 'private'})).id;
  check(FID, 'a folder');

  const w = await boot({user: 'alice', hash: 'ablage/' + FID}), d = w.document;
  const mb = await until(() => d.querySelector(`.abtools [data-ab="menu"][data-id="${FID}"]`));
  check(mb, "the open folder's menu button");
  click(w, mb);
  await until(() => d.querySelector('#pop [role="menuitem"]'));
  const item = [...d.querySelectorAll('#pop [role="menuitem"]')].find(b => /Request files/.test(b.textContent));
  check(item, 'the folder menu offers “Request files…” ' + [...d.querySelectorAll('#pop [role="menuitem"]')].map(b => b.textContent.trim()).join('|'));
  click(w, item);
  const dlg = await until(() => d.querySelector('.frqdlg .frq-body .foot'));
  check(dlg && /No file requests yet/.test(d.querySelector('.frqdlg').textContent) && /without an account/.test(d.querySelector('.frqdlg').textContent),
    'the dialog: none yet, the hint for clients');
  click(w, d.querySelector('.frqdlg [data-frq="new"]'));
  const nf = await until(() => d.querySelector('.frqnew form'));
  check(nf && d.querySelector('#frq-title').value === 'Files for Invoices', 'the new request: the title from the folder');
  const exp = d.querySelector('#frq-exp')?.value || '', want = new Date(Date.now() + 14 * 864e5).toISOString().slice(0, 10);
  check(exp && Math.abs(new Date(exp) - new Date(want)) <= 864e5, 'the end date: in 14 days ' + exp);
  check([...d.querySelectorAll('.frq-kinds input:checked')].map(x => x.value).join(',') === 'docs,images', 'documents + pictures ticked');
  d.querySelector('#frq-title').value = 'Acme Example documents';
  d.querySelector('#frq-note').value = 'Please upload the signed contract.';
  nf.dispatchEvent(new w.Event('submit', {bubbles: true, cancelable: true}));
  const row = await until(() => d.querySelector('.frqdlg .frq-row .frq-link input'));
  check(row && /\/u\/[A-Za-z0-9_-]{20,}$/.test(row.value), 'created: the row with its link ' + (row?.value || ''));
  check(d.querySelector('.frqdlg [data-frq="copy"]') && d.querySelector('.frqdlg [data-frq="qr"]'), 'copy and QR code');
  check(/Open until/.test(d.querySelector('.frqdlg .frq-row')?.textContent || '') && /0 files arrived/.test(d.querySelector('.frqdlg .frq-row')?.textContent || ''), 'the row: open until …, 0 files');
  check(w.eval(`HIST.undo.length && /File request/.test(HIST.undo[HIST.undo.length - 1].label)`), 'creating = one undo step');
  const URL0 = row?.value || '', TOK = URL0.split('/u/')[1];
  const list = async () => (await call('GET', `/api/files/nodes/${FID}/requests`)).requests || [];
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await list()).length === 0), 'Undo removes the request');
  await w.eval(`histStep('redo')`);
  check(await until(async () => (await list()).length === 1), 'Redo brings it back');
  check((await fetch(B + 'u/' + TOK)).status === 200, 'the link works after Redo');

  // ---- stop the link from the row's menu
  await until(() => d.querySelector('.frqdlg [data-frq="menu"]'));
  click(w, d.querySelector('.frqdlg [data-frq="menu"]'));
  await until(() => d.querySelector('#pop [role="menuitem"]'));
  const items = [...d.querySelectorAll('#pop [role="menuitem"]')];
  check(items.some(b => /Extend by 14 days/.test(b.textContent)) && items.some(b => /Remove/.test(b.textContent)), 'the row menu: extend, stop, remove');
  click(w, items.find(b => /Stop the link/.test(b.textContent)));
  check(await until(() => /Stopped/.test(d.querySelector('.frqdlg .frq-row')?.textContent || '')), 'stopped: the row says so');
  check((await fetch(B + 'u/' + TOK)).status === 404, 'the link no longer opens');
  await w.eval(`histStep('undo')`);
  check(await until(async () => (await list())[0]?.state === 'active'), 'Undo opens it again');
  check(w.eval(`NOTIF_ROWS.some(r => r[0] === 'filereq')`), 'the notification settings have the row for file requests');
  w.close();

  // ---- the public page with its script
  const {JSDOM} = require('jsdom');
  const dom = await JSDOM.fromURL(B + 'u/' + TOK, {runScripts: 'dangerously', resources: new PooledLoader(), pretendToBeVisual: true});
  const pw = dom.window, pd = pw.document;
  await until(() => pd.readyState === 'complete');
  check(/Acme Example documents/.test(pd.querySelector('h1')?.textContent || '') && /signed contract/.test(pd.querySelector('.intro')?.textContent || ''), 'the page: title and note');
  check(!/Invoices/.test(pd.body.textContent), 'the page does not name the folder');
  const form = pd.querySelector('.frq-form'), drop = pd.querySelector('.frq-drop');
  await sleep(2300);  // the signed stamp counts from 2 s on
  const ev = new pw.Event('drop', {bubbles: true, cancelable: true});
  ev.dataTransfer = {files: [new pw.File(['%PDF-1.4\n%%EOF\n'], 'contract.pdf', {type: 'application/pdf'}), new pw.File(['MZ'], 'setup.exe', {type: 'application/octet-stream'})]};
  drop.dispatchEvent(ev);
  const lis = [...pd.querySelectorAll('.frq-list li')];
  check(lis.length === 2 && lis[1].classList.contains('bad') && /not accepted/.test(lis[1].textContent), 'dropped files are listed, a wrong kind is marked at once');
  form.dispatchEvent(new pw.Event('submit', {bubbles: true, cancelable: true}));
  check(await until(() => pd.querySelector('.frq-list li.ok') && pd.querySelector('.frq-done'), 60), 'the send: uploaded, the thank-you line');
  const kids = (await call('GET', `/api/files?parent=${FID}`)).items || [];
  check(kids.some(n => n.name === 'contract.pdf') && !kids.some(n => n.name === 'setup.exe'), 'the file is in the folder, the program is not');
  pw.close();

  // ---- phone width: the dialog fits
  const m = await boot({user: 'alice', hash: 'ablage/' + FID, mobile: true}), md = m.document;
  await until(() => md.querySelector('#view .abview'));
  await m.eval(`frq_open({id: ${FID}, name: 'Invoices'})`);
  check(await until(() => md.querySelector('.frqdlg .frq-row .frq-link input')), 'phone: the dialog with the link');
  m.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
