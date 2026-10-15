// 2.44.0 UI tests, part C (#1517 set up an agent on a computer with one command), own container (start.sh). jsdom:
// - Settings > Agents > Set up: the personal agent's row has "Set up on a computer"; the dialog offers Mac / Windows / Linux
//   and the project folder (required), "Create command" shows ONE command with the one-time code (curl ... | bash for Mac /
//   Linux, the PowerShell form for Windows), how long it is valid, a copy button and "New code" (a new code)
// - the computers list: a redeemed code shows the computer with its name and "connected"; "Remove computer" asks first
//   (cannot be undone) and the computer's token stops working
// - the admin's agent dialog has "Set up on a computer" too; German labels
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body, ck = CK, hd = {}) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {}), ...hd}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true}));
const lastModal = d => [...d.querySelectorAll('.modal')].pop();

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'agents,comments,collab'});
  await call('PUT', '/api/admin/agent-policy', {user_agents: true});
  const PA = (await call('POST', '/api/my/agents', {username: 'deskbot', display_name: 'Deskbot'})).id;
  check(PA, 'personal agent created');

  let w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`settingsModal('ai')`); await sleep(500);
  await w.eval(`aiSubShow(document.querySelector('.smodal'), 'setup', false)`);
  await until(() => d.querySelector(`#s-myown [data-myag="${PA}"] [data-myag-act="setup"]`));
  const btn = d.querySelector(`#s-myown [data-myag="${PA}"] [data-myag-act="setup"]`);
  check(btn && /Set up Deskbot on a computer/.test(btn.getAttribute('aria-label') || ''), 'the agent row has "Set up on a computer"');
  click(w, btn); await until(() => lastModal(d)?.querySelector('#ains-dir'));
  let md = lastModal(d);
  check(/Set up Deskbot on a computer/.test(md.querySelector('h3').textContent), 'the dialog opens');
  check(['mac', 'windows', 'linux'].every(o => md.querySelector(`[data-ainsos="${o}"]`)), 'Mac / Windows / Linux to choose');
  click(w, md.querySelector(`[data-ainsos="linux"]`));
  click(w, md.querySelector('[data-m="ains-make"]')); await sleep(300);
  check(md.querySelector('#ains-out').hidden, 'no folder: no command (the folder is required)');
  md.querySelector('#ains-dir').value = "~/projects/bob's site";
  click(w, md.querySelector('[data-m="ains-make"]'));
  await until(() => !md.querySelector('#ains-out').hidden);
  const cmd = md.querySelector('#ains-cmd').value;
  const code = (cmd.match(/--code (ks_[\w-]+)/) || [])[1];
  check(code && cmd.startsWith("curl -fsSL '") && cmd.includes("/agent-setup.sh' | bash -s -- --url '") && cmd.includes(`--dir '~/projects/bob'\\''s site'`), 'one command with the code (shell quoting) ' + cmd);
  check(/Valid for 15 more minutes, works once/.test(md.querySelector('#ains-exp').textContent), 'how long the code is valid: ' + md.querySelector('#ains-exp').textContent);
  check(md.querySelector('[data-m="ains-copy"]') && /Terminal/.test(md.querySelector('#ains-how').textContent), 'copy button + where to paste it');
  // Windows: the PowerShell form
  click(w, md.querySelector(`[data-ainsos="windows"]`));
  check(md.querySelector('#ains-out').hidden, 'another system hides the old command');
  md.querySelector('#ains-dir').value = 'C:\\work\\site';
  click(w, md.querySelector('[data-m="ains-make"]'));
  await until(() => !md.querySelector('#ains-out').hidden);
  const wcmd = md.querySelector('#ains-cmd').value;
  // 2.46.6 (#1713): the command ends with the account language (-Lang de|en)
  check(wcmd.startsWith('& ([scriptblock]::Create((irm ') && wcmd.includes("/agent-setup.ps1'))) -Url '") && /-Code ks_[\w-]+ -Dir 'C:\\work\\site' -Lang (de|en)$/.test(wcmd), 'Windows: the PowerShell command ' + wcmd);
  check(/PowerShell/.test(md.querySelector('#ains-how').textContent), 'Windows: paste into PowerShell');
  const wcode = wcmd.match(/-Code (ks_[\w-]+)/)[1];
  check(wcode !== code, 'every press makes a new code');
  // the computer shows up
  const red = await call('POST', '/api/agent-setup/redeem', {code, host: 'studio-laptop'}, null);
  check(red.token, 'the code of the dialog redeems');
  await call('PUT', '/api/v1/agent/status', {status: 'idle', host: 'studio-laptop'}, null, {Authorization: 'Bearer ' + red.token});
  click(w, md.querySelector('[data-m="close"]'));
  click(w, d.querySelector(`#s-myown [data-myag="${PA}"] [data-myag-act="setup"]`));
  await until(() => lastModal(d)?.querySelector('[data-ainsm]'));
  md = lastModal(d);
  const row = md.querySelector('[data-ainsm]');
  check(row && /studio-laptop/.test(row.textContent) && /connected/.test(row.textContent) && /Linux/.test(row.textContent) && row.querySelector('.hdot.hs-ready'), 'the computer with name, connected, green dot ' + row?.textContent.trim());
  click(w, row.querySelector('[data-m="ains-del"]'));
  await until(() => d.querySelector('.modal .card') && /cannot be undone/.test(lastModal(d).textContent));
  const cf = lastModal(d);
  check(/Remove computer studio-laptop\?/.test(cf.textContent), 'remove asks first');
  const okb = [...cf.querySelectorAll('button')].find(b => /Remove computer/.test(b.textContent));
  click(w, okb);
  await until(() => !/studio-laptop/.test(md.querySelector('#ains-ms').textContent));
  // (the token of "Create agent" stays: a token made by hand counts as a computer that never connected)
  check(!/studio-laptop/.test(md.querySelector('#ains-ms').textContent) && /never connected/.test(md.querySelector('#ains-ms').textContent), 'the computer is gone from the list');
  check((await call('GET', '/api/v1/agent', null, null, {Authorization: 'Bearer ' + red.token})).status === 401, "its token stops working");
  w.close();

  // the admin's agent dialog + German
  await call('PATCH', '/api/settings', {lang: 'de'});
  w = await boot({user: 'alice', hash: 'today'}); d = w.document;
  await until(() => w.ains_setupModal);
  w.eval(`ains_setupModal({id: ${PA}, name: 'Deskbot'}, '/api/admin/agents/${PA}')`);
  await until(() => lastModal(d)?.querySelector('#ains-dir'));
  md = lastModal(d);
  check(/Deskbot auf einem Rechner einrichten/.test(md.querySelector('h3').textContent) && /Projektordner/.test(md.textContent) && /Befehl erzeugen/.test(md.textContent), 'German labels');
  md.querySelector('#ains-dir').value = '~/x';
  click(w, md.querySelector('[data-m="ains-make"]'));
  await until(() => !md.querySelector('#ains-out').hidden);
  check(/--code ks_/.test(md.querySelector('#ains-cmd').value) || /-Code ks_/.test(md.querySelector('#ains-cmd').value), 'the admin route makes a code too');
  const src = await (await fetch(B + 'static/js/agentchat.js')).text();
  check(src.includes('data-m="ains-setup"'), "the admin's agent dialog has the button");
  w.close();

  console.log(`p2440_c_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
