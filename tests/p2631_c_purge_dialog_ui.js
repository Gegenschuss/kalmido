// 2.631.0 (#4584) UI test (jsdom), fresh DB, people without an organisation: the account's delete dialog says per shared
// folder that is handed on what of it does not go along (here: a file in the trash) and that a file that cannot be sealed
// again for the new owner goes too; cancelled, nothing is deleted
// kalmido-suite: fresh
const {boot, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
let CA;
const call = async (method, url, body, ck = CA) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const upload = async (ck, parent, name, text) => {
  const fd = new FormData(); fd.append('parent_id', String(parent)); fd.append('file', new Blob([text]), name);
  const r = await fetch(B + 'api/files/upload', {method: 'POST', headers: {'X-Requested-With': 'kalmido', Cookie: ck}, body: fd});
  return (await r.json()).items?.[0]?.id;
};
const click = (w, el) => el.dispatchEvent(new w.MouseEvent('click', {bubbles: true}));

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CA = await login('alice');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const mk = async u => (await call('POST', '/api/users', {orgs: [], username: u, display_name: u[0].toUpperCase() + u.slice(1), password: 'password123', email: `${u}@example.com`})).id;
  const FID = await mk('frida'), GID = await mk('gina');
  const CF = await login('frida');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'files,docs,collab'}, CF);
  const GB = (await call('POST', '/api/files/folders', {name: 'Studio', space: 'private'}, CF)).id;
  check(!!GB && (await call('POST', `/api/files/nodes/${GB}/shares`, {user_id: GID, role: 'edit'}, CF)).status === 201, 'setup: a folder shared with gina to edit');
  await upload(CF, GB, 'keep.txt', 'stays');
  const TR = await upload(CF, GB, 'old.txt', 'thrown away');
  check(!!TR && (await call('DELETE', `/api/files/nodes/${TR}`, null, CF)).status < 300, 'setup: a file of it in the trash');
  const info = (await call('GET', `/api/users/${FID}/delete-info`)).purge?.shared || {};
  check(JSON.stringify((info.branches || []).map(b => [b.stay, b.ends, b.agents])) === "[[1,0,0]]", 'setup: the server counts one entry staying behind ' + JSON.stringify(info));

  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.__dialogs = 'manual';
  await until(() => d.querySelector('#side .srow'));
  w.eval(`settingsModal('users')`);
  check(await until(() => w.eval(`typeof ua8_delete === 'function'`)), 'the admin code is loaded');
  w.eval(`window.__ud = ua8_delete({id: ${FID}, display_name: 'Frida'})`);
  const ud = await until(() => [...d.querySelectorAll('.modal.cdlg')].find(m => /Delete account “Frida”/.test(m.textContent)));
  const rows = [...(ud?.querySelectorAll('.ua8purge') || [])].map(n => n.textContent.replace(/\s+/g, ' ').trim());
  const line = rows.find(t => /A shared folder or file that is handed on:/.test(t));
  check(line && /1 entry in it does not go along and goes with the account \(locked folders, shortcuts, agent folders, the trash, e-mail copies\)\./.test(line), 'the dialog names what stays behind in the folder ' + JSON.stringify(rows));
  check(line && !/link|agent of/.test(line.replace(/agent folders/, '')), 'and nothing about links or agents when there are none');
  check(rows.some(t => /A file that cannot be sealed again for the new owner goes with the account\./.test(t)), 'and that a file that cannot be sealed again goes');
  check(rows.some(t => /go to the longest-standing person who may change them \(Gina\): 1 folder or file\./.test(t)), 'the hand-on line as before');
  click(w, ud.querySelector('[data-cd="no"]'));
  check(await w.eval('window.__ud') === false, 'cancelled');
  check((await call('GET', `/api/users/${FID}/delete-info`)).status === 200, 'frida is still there');

  console.log(`p2631_c_purge_dialog_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
