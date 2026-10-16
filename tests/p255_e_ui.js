// 2.55.0 UI tests of part E (#1455; own container, start.sh with the fake newsletter services inside it). jsdom:
// - Contacts > More > Newsletter…: the sheet explains why Kalmido sends nothing itself, the form (service, address, access
//   data); wrong access data show the reason in place; connected: service + address, never the access data
// - a segment (new list at the service), "Sync now", the log line
// - the contact card: menu > Newsletter consent…; "Consented" asks for the source, the line shows it; Undo = Unknown (ONE step)
// - phone width: the sheet is usable
const {execFileSync} = require('child_process');
const fs = require('fs');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
if (!process.env.P255E_NOSTART) {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore',
    env: {...process.env, EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8086 -e KALMIDO_SECRET_KEY=AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8='}});
}
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, ...(ck ? {Cookie: ck} : {})}, body: body ? JSON.stringify(body) : undefined}); return {status: r.status, ...(await r.json().catch(() => ({})))}; };
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(200); } return fn(); };
const menuItems = d => [...d.querySelectorAll('.menu-list [role="menuitem"]')];
const TOKEN = 'lm-secret-token-1234';
for (const f of ['nl.json', 'nl.log']) { try { fs.unlinkSync(path.join(DATA, f)); } catch { /* none */ } }
fs.copyFileSync(path.join(__dirname, 'fake_newsletter.py'), path.join(DATA, 'fake_newsletter.py'));
execFileSync('docker', ['exec', '-d', CT, 'python', '/data/fake_newsletter.py']);

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  const st = await call('GET', '/api/state');
  const feats = new Set(((st.settings || {}).features || '').split(',').filter(Boolean)); feats.add('contacts');
  await call('PATCH', '/api/settings', {tour: 'done', lang: 'en', features: [...feats].join(',')});
  const bk = await call('POST', '/api/books', {name: 'Customers'});
  const c1 = await call('POST', '/api/contacts', {book_id: bk.id, fn: 'Anna Alpha', emails: [{value: 'anna@example.com'}], groups: ['VIP']});

  // ================= the sheet
  const w = await boot({user: 'alice', hash: 'contacts'}), d = w.document;
  const mb = await until(() => d.querySelector('#view [data-ct="menu"]'));
  mb.click();
  const it = await until(() => menuItems(d).find(b => /Newsletter/.test(b.textContent)));
  check(it, 'Contacts > More has "Newsletter…"');
  it?.click();
  const md = await until(() => d.querySelector('.nwl-md #nwl-url') && d.querySelector('.nwl-md'));
  check(md && /does not send newsletters itself/.test(md.textContent), 'the sheet says why Kalmido sends nothing itself');
  check(md && md.querySelector('#nwl-kind') && md.querySelector('#nwl-user') && md.querySelector('#nwl-tok'), 'the form: service, user, token');
  check([...(md?.querySelectorAll('#nwl-kind option') || [])].some(o => /Brevo.*Preview/.test(o.textContent)), 'Brevo is marked as a preview');
  d.querySelector('#nwl-url').value = 'http://127.0.0.1:8086';
  d.querySelector('#nwl-user').value = 'lmuser';
  d.querySelector('#nwl-tok').value = 'wrong-token-value-1';
  d.querySelector('[data-nwl="connect"]').click();
  await until(() => /refused/.test(d.querySelector('.nwl-md .nwl-err')?.textContent || ''));
  check(/refused the access data/.test(d.querySelector('.nwl-md .nwl-err')?.textContent || ''), 'wrong access data: the reason in place');
  d.querySelector('#nwl-tok').value = TOKEN;
  d.querySelector('[data-nwl="connect"]').click();
  await until(() => d.querySelector('.nwl-md [data-nwl="seg-new"]'));
  const body = () => d.querySelector('.nwl-md .nwl-body');
  check(/listmonk/.test(body()?.textContent || '') && /…1234/.test(body()?.textContent || '') && !body().innerHTML.includes(TOKEN), 'connected: the service and the hint, never the token');
  check(d.querySelector('[data-nwl="sync"]')?.disabled, 'Sync now is off without segments');

  // ================= a segment, then a sync
  d.querySelector('[data-nwl="seg-new"]').click();
  const sm = await until(() => d.querySelector('.nwl-smd'));
  await until(() => sm.querySelector('#ns-list option[value="__new"]'));
  sm.querySelector('#ns-name').value = 'VIP list';
  const vip = [...sm.querySelectorAll('.nwl-chips[data-k="tags"] [data-v]')].find(b => b.dataset.v === 'VIP');
  vip?.click();
  check(vip?.classList.contains('on'), 'a group can be picked');
  sm.querySelector('[data-ns="save"]').click();
  await until(() => body()?.querySelector('.nwl-segs li'));
  check(/VIP list/.test(body()?.querySelector('.nwl-segs')?.textContent || ''), 'the segment is listed with its list');
  await call('PUT', '/api/newsletter/consent', {ids: [c1.id], status: 'yes', source: 'Form'});
  const sb = await until(() => { const b = d.querySelector('[data-nwl="sync"]'); return b && !b.disabled && b; });
  sb?.click();
  await until(async () => ((await call('GET', '/api/newsletter?ws=private')).runs || [])[0]?.state === 'ok', 100);
  await until(() => /1 added/.test(body()?.textContent || ''), 60);
  check(/1 added/.test(body()?.querySelector('.nwl-log')?.textContent || ''), 'the log shows the run');
  d.querySelector('.nwl-md [data-nwl="close"]').click();
  w.close();

  // ================= the consent in the contact card
  const c2 = await call('POST', '/api/contacts', {book_id: bk.id, fn: 'Ben Beta', emails: [{value: 'ben@example.com'}]});
  const v = await boot({user: 'alice', hash: `contacts/${c2.id}`}), e = v.document;
  await until(() => e.querySelector('#view [data-ct="cmenu"]'));
  check(!e.querySelector('.nwl-ctf'), 'no consent line while the consent is unknown');
  e.querySelector('#view [data-ct="cmenu"]').click();
  const ci = await until(() => menuItems(e).find(b => /Newsletter consent/.test(b.textContent)));
  check(ci, 'the contact menu has "Newsletter consent…"');
  ci?.click();
  const yes = await until(() => menuItems(e).find(b => /^Consented$/.test(b.textContent.trim())));
  yes?.click();
  const inp = await until(() => e.querySelector('#cdlg-in'));
  if (inp) { inp.value = 'Trade fair 2026'; e.querySelector('.cdlg [data-cd="yes"]').click(); }
  await until(async () => (await call('GET', `/api/contacts/${c2.id}`)).newsletter?.status === 'yes');
  check((await call('GET', `/api/contacts/${c2.id}`)).newsletter?.source === 'Trade fair 2026', 'Consented with the source');
  await until(() => /Consented/.test(e.querySelector('.nwl-ctf')?.textContent || ''));
  check(/Trade fair 2026/.test(e.querySelector('.nwl-ctf')?.textContent || ''), 'the card shows the source');
  e.dispatchEvent(new v.KeyboardEvent('keydown', {key: 'z', ctrlKey: true, bubbles: true, cancelable: true}));
  await until(async () => (await call('GET', `/api/contacts/${c2.id}`)).newsletter?.status === '');
  check((await call('GET', `/api/contacts/${c2.id}`)).newsletter?.status === '', 'Undo: Unknown again (one step)');
  await until(() => !e.querySelector('.nwl-ctf'));
  check(!e.querySelector('.nwl-ctf'), 'Undo: the line is gone again');
  v.close();

  // ================= phone width
  const m = await boot({user: 'alice', hash: 'contacts', mobile: true}), f = m.document;
  (await until(() => f.querySelector('#view [data-ct="menu"]')))?.click();
  (await until(() => menuItems(f).find(b => /Newsletter/.test(b.textContent))))?.click();
  const pm = await until(() => f.querySelector('.nwl-md [data-nwl="sync"]'));
  check(pm, 'phone: the sheet with Sync now');
  m.close();

  console.log(`p255_e_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e); process.exit(1); });
