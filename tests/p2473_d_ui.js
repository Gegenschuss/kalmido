// 2.47.3 UI tests of part D (own container, start.sh). jsdom:
// - #1729: deleting an agent / removing a computer shows the uninstall command of each computer set up with the one-command
//   setup (Mac/Linux or Windows after the stored OS, with its folder), only when computers exist; Copy / Cancel work
// - #1764: messages of background jobs ("Job #163: …", "✅ Job #163 … fertig:") get a stripe + tag in the job's colour; a part job
//   (job_parent) takes its leader's colour, lighter; other messages stay plain
// - #1382: (i) explanations: the quotation/invoice editor rows and ux_info() for other parts of the office
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en'});
  const AG = (await call('POST', '/api/admin/agents', {username: 'helperbot', display_name: 'Helper bot'})).id;
  const AG2 = (await call('POST', '/api/admin/agents', {username: 'lonelybot', display_name: 'Lonely bot'})).id;
  const redeem = async (os, folder, host) => {
    const c = await call('POST', `/api/admin/agents/${AG}/setup-code`, {os, folder});
    const r = await fetch(B + 'api/agent-setup/redeem', {method: 'POST', headers: H, body: JSON.stringify({code: c.code, host})});
    return r.status;
  };
  check(await redeem('mac', '/Users/me/my site', 'MacBook') === 200 && await redeem('windows', 'C:\\Work\\site', 'WinPC') === 200, 'setup: two computers (Mac, Windows) of the agent');
  const w = await boot({user: 'alice', hash: 'agents'}), d = w.document;
  w.__dialogs = 'manual';  // the suite drives the dialogs itself
  await until(() => w.ains_askRemove && w.AC_COLORS);
  const ask = (base, only) => { w.eval(`window.__ask = ains_askRemove('${base}', 'Delete the agent?', 'Its tokens are deleted.', {ok: 'Delete', danger: true}${only ? ', ' + only : ''}).then(v => { window.__askRes = v; })`); };

  // ================= delete agent with computers
  ask(`/api/admin/agents/${AG}`);
  const dlg = await until(() => d.querySelector('.cdlg .ainsun') && d.querySelector('.cdlg'));
  const cmds = [...d.querySelectorAll('.cdlg .ainsuncmd')].map(x => x.value);
  check(cmds.length === 2, 'the dialog lists both computers: ' + cmds.length);
  const mac = cmds.find(x => x.startsWith('curl')), win = cmds.find(x => x.startsWith('&'));
  check(mac && mac.includes('--uninstall') && mac.includes("--dir '/Users/me/my site'") && mac.includes('/agent-setup.sh'), 'Mac: bash command with --uninstall and the folder: ' + mac);
  check(win && win.includes('-Uninstall') && win.includes("-Dir 'C:\\Work\\site'") && win.includes('agent-setup.ps1'), 'Windows: PowerShell command with -Uninstall and the folder: ' + win);
  const txt = d.querySelector('.cdlg').textContent;
  check(/MacBook/.test(txt) && /WinPC/.test(txt) && /Mac/.test(txt) && /Windows/.test(txt) && /run the command on each computer first/i.test(txt), 'names, operating systems and the hint "first on the computer, then delete"');
  check(!!d.querySelector('.cdlg .hdot'), 'the connected state is shown as a dot');
  check(d.querySelectorAll('.cdlg [data-ainsun="copy"]').length === 2, 'a Copy button per computer');
  d.querySelector('.cdlg [data-cd="no"]').click();
  check(await until(() => w.eval('window.__askRes') === false), 'Cancel: nothing is deleted (false)');

  // ================= delete with Delete works without running the command
  ask(`/api/admin/agents/${AG}`);
  await until(() => d.querySelector('.cdlg .ainsun'));
  d.querySelector('.cdlg [data-cd="yes"]').click();
  check(await until(() => w.eval('window.__askRes') === true), 'Delete answers yes without having run the command');

  // ================= remove one computer: only its command
  const ms = (await call('GET', `/api/admin/agents/${AG}/machines`)).machines;
  const winM = ms.find(m => m.os === 'windows');
  w.eval('window.__askRes = undefined');
  ask(`/api/admin/agents/${AG}`, winM.id);
  await until(() => d.querySelector('.cdlg .ainsun'));
  check(d.querySelectorAll('.cdlg .ainsun').length === 1 && d.querySelector('.cdlg .ainsuncmd').value.startsWith('&') && /stop the agent there/.test(d.querySelector('.cdlg').textContent), 'remove computer: only that computer, with its own hint');
  d.querySelector('.cdlg [data-cd="no"]').click();

  // ================= no computers: the plain question
  w.eval('window.__askRes = undefined');
  ask(`/api/admin/agents/${AG2}`);
  await until(() => d.querySelector('.cdlg'));
  check(!d.querySelector('.cdlg .ainsun') && !d.querySelector('.cdlg .ainsuncmd'), 'an agent without computers: no uninstall command');
  d.querySelector('.cdlg [data-cd="no"]').click();

  // ================= #1764 job colours in the agent chat
  const html = w.eval(`S.chat.aid = ${AG}; S.chat.msgs = ${JSON.stringify([
    {id: 901, from: 'agent', kind: 'message', body: 'Job #163: build runs', created_at: '2026-10-15T10:00:00Z', reactions: []},
    {id: 902, from: 'agent', kind: 'message', body: '\u2705 Job #163 \u201eRelease\u201c fertig:\n\nAll green.', created_at: '2026-10-15T10:01:00Z', reactions: []},
    {id: 903, from: 'agent', kind: 'message', body: 'Job #164: part speaks', job_id: 164, job_parent: 163, created_at: '2026-10-15T10:02:00Z', reactions: []},
    {id: 904, from: 'agent', kind: 'message', body: 'Job #165: another job', created_at: '2026-10-15T10:03:00Z', reactions: []},
    {id: 905, from: 'agent', kind: 'message', body: 'Plain answer, see Job #163 for details', created_at: '2026-10-15T10:04:00Z', reactions: []},
    {id: 906, from: 'user', kind: 'message', body: 'Job #163: me, not a job', created_at: '2026-10-15T10:05:00Z', reactions: []}])}; chatMsgs()`);
  const box = d.createElement('div'); box.innerHTML = html;
  const msg = id => box.querySelector(`[data-mid="a:${id}"]`);
  const col = id => msg(id)?.style.getPropertyValue('--jcol');
  check(msg(901).classList.contains('jobm') && /^#[0-9a-f]{6}$/i.test(col(901)) && msg(901).querySelector('.jobtag')?.textContent.trim() === 'Job #163', '"Job #163: …": stripe class, colour and the tag "Job #163"');
  check(msg(902).classList.contains('jobm') && col(902) === col(901), 'the end message ("✅ Job #163 …") has the same colour as the job\'s other messages');
  check(msg(903).classList.contains('jpart') && col(903) === col(901) && msg(903).querySelector('.jobtag')?.textContent.trim() === 'Job #164', 'a part job: its own tag, the colour of its leader (jpart = lighter)');
  check(msg(904).classList.contains('jobm') && col(904) && col(904) !== col(901), 'another job: another colour (neighbouring numbers differ)');
  check(!msg(905).classList.contains('jobm') && !msg(905).querySelector('.jobtag'), 'a normal answer that only mentions a job stays plain');
  check(!msg(906).classList.contains('jobm'), 'my own message is never marked');
  const css2 = require('./boot').allCssSync(); // 2.65.0 (#1824): + the module stylesheets
  check(!/\.cmsg\.jobm \.cbub\{box-shadow/.test(css2) && /\.cmsg\.agc\.jobm \.cbub\{background:color-mix\(in srgb,var\(--jcol/.test(require('fs').readFileSync(path.join(__dirname, '..', 'static', 'app.css'), 'utf8')) && /\.jobtag\{[^}]*color:var\(--text\)/.test(css2), 'CSS (2.174.0 #2681: tinted bubble instead of the stripe), tag text in the normal text colour (no coloured text)');

  // ================= #1382 (i) in the editor rows and ux_info for the office
  const row = w.eval(`ofdF('order_ref', 'PO number', '<input id="ofd-order_ref">', 'the client order reference')`);
  // 2.298.0 A1 (#3186): the field's own help joins its (i) text (one (i), two lines: class pl), never a visible line
  check(/<div class="shint( pl)?">/.test(row) && /order number/.test(row) && /the client order reference/.test(row) && !/ofchint/.test(row), '(i) behind the editor field "PO number"');
  check(w.eval(`['ed_vat_mode','ed_raw_mode','ed_contract_id','ed_payment_days','ed_reminder_level','ed_einvoice_format','ed_prod_quotient','currency','color','small_business','cl_customer_no','cl_vat_id'].every(k => ux_info(k).includes('shint'))`), 'ux_info(): texts for settings, editor, client card and the small-business rule');
  check(w.eval(`ofdF('lang', 'Language', '<select></select>')`).indexOf('shint') < 0, 'a field without a text gets no (i)');

  console.log(`p2473_d_ui: ${ok} ok, ${F.length} failed`);
  w.close();
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('ERROR', e); process.exit(1); });
