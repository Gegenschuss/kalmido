// 2.142.0 UI tests (part A, #2145, #2146), own container (start.sh with SMTP set, nothing is sent). jsdom:
// Settings > Notifications: the section Channels (none yet), "Add channel" opens the dialog with the service, its fields
// (Slack: webhook URL; Telegram: bot token + chat ID) and the events (reminders, assignments, mentions checked by default);
// saved, the row shows the service and the masked end only -- never the address; editing leaves the address empty
// ("unchanged"). The section "E-mail for single events" offers off / only without a push device / always per kind and saves
// through the settings. Settings > Workspaces: an admin sees the organisation's Channels, a member does not.
const {execFileSync} = require('child_process');
const path = require('path');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2142A_NOSTART) {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env,
    EXTRA: (process.env.EXTRA || '') + ' -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test'}});
}
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = async (fn, n = 40) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(150); } return fn(); };
const click = (w, el, o = {}) => el && el.dispatchEvent(new w.MouseEvent('click', {bubbles: true, cancelable: true, ...o}));
const FEAT = 'cal,comments,collab,events,files,time';
const SLACK = 'https://hooks.slack.com/services/T000/B000/abcdefgh1234';

(async () => {
  await sleep(600);
  const r = await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123', wizard: true, lang: 'en'})});
  check(r.ok, 'setup');
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {org_name: 'Kalmido', lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT});
  const ORG = (await call('GET', '/api/state')).me.workspaces[0].id;
  await call('POST', '/api/users', {orgs: [ORG], username: 'bob', display_name: 'Bob', password: 'password123', email: 'bob@example.test'});
  const CB = await login('bob');
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: FEAT}, CB);

  // ================= Settings > Notifications > Channels
  let w = await boot({user: 'alice'}), d = w.document;
  w.__dialogs = 'manual';
  w.eval(`settingsModal('notify')`);
  await until(() => d.querySelector('#s-chn [data-chn="new"]'), 60);
  const box = () => d.querySelector('#s-chn');
  check(/Forwardings/.test(box()?.querySelector('#s-chn-h')?.textContent || ''), '#2145: the notification settings have the section Forwardings');  // 2.165.3 (#2657): Weiterleitungen / Forwardings
  check(/No forwardings yet/.test(box()?.querySelector('.chnrows')?.textContent || ''), '#2145: none yet');  // 2.165.3 (#2657)
  click(w, box().querySelector('[data-chn="new"]'));
  await until(() => d.querySelector('#chn-kind'));
  const dlg = () => [...d.querySelectorAll('.modal')].pop();
  check(['slack', 'matrix', 'telegram', 'signal'].every(k => d.querySelector(`#chn-kind option[value="${k}"]`)), '#2145: the four services');
  check(!!d.querySelector('#chn-url') && !d.querySelector('#chn-token'), '#2145: Slack asks for the webhook URL');
  const evs = [...dlg().querySelectorAll('[data-chnev]')];
  check(evs.filter(x => x.checked).map(x => x.dataset.chnev).join(',') === 'reminder,assign,comment', '#2145: reminders, assignments, mentions checked by default: ' + evs.filter(x => x.checked).map(x => x.dataset.chnev));
  check(evs.some(x => x.dataset.chnev === 'lists') && evs.some(x => x.dataset.chnev === 'digest'), '#2145: also own lists and the digest');
  const kind = d.querySelector('#chn-kind');
  kind.value = 'telegram'; kind.dispatchEvent(new w.Event('change', {bubbles: true}));
  check(!!d.querySelector('#chn-token') && !!d.querySelector('#chn-chat_id') && !d.querySelector('#chn-url'), '#2145: Telegram asks for bot token and chat ID');
  check(/BotFather/.test(dlg().querySelector('.chnhelp')?.textContent || ''), '#2145: a short help per service');
  kind.value = 'slack'; kind.dispatchEvent(new w.Event('change', {bubbles: true}));
  d.querySelector('#chn-name').value = 'Team Slack';
  d.querySelector('#chn-url').value = SLACK;
  click(w, dlg().querySelector('[data-m="ok"]'));
  await until(() => box()?.querySelector('.chnrow'), 60);
  const row = box()?.querySelector('.chnrow');
  check(/Team Slack/.test(row?.textContent || '') && /hooks\.slack\.com …1234/.test(row?.textContent || ''), '#2145: the row: name, service, masked end: ' + (row?.textContent || '').trim().slice(0, 120));
  check(!box().innerHTML.includes('abcdefgh1234') && !box().innerHTML.includes('/services/'), '#2145: the address never shows');
  const list = (await call('GET', '/api/me/channels')).channels || [];
  check(list.length === 1 && list[0].kind === 'slack' && !JSON.stringify(list).includes('abcdefgh'), '#2145: saved on the server, no address in GET');
  click(w, row.querySelector('[data-chn="edit"]'));
  await until(() => d.querySelector('#chn-url'));
  check(d.querySelector('#chn-url').value === '' && /unchanged/.test(d.querySelector('#chn-url').placeholder), '#2145: editing leaves the address empty (unchanged)');
  check(d.querySelector('#chn-kind').disabled, '#2145: the service stays');
  d.querySelector('#chn-name').value = 'Renamed';
  click(w, dlg().querySelector('[data-m="ok"]'));
  await until(async () => ((await call('GET', '/api/me/channels')).channels || [])[0]?.name === 'Renamed');
  check(((await call('GET', '/api/me/channels')).channels || [])[0]?.name === 'Renamed', '#2145: renamed without typing the address again');

  // ================= E-mail for single events
  const sel = d.querySelector('#s-evm-assign');
  check(!!sel && sel.value === 'nopush' && d.querySelector('#s-evm-mention')?.value === 'nopush', '#2146: assignments / mentions: only without a push device by default');
  check([...(sel?.options || [])].map(o => o.value).join(',') === 'nopush,always,off', '#2146: the three choices');
  if (sel) { sel.value = 'always'; sel.dispatchEvent(new w.Event('change', {bubbles: true})); }
  await until(async () => (await call('GET', '/api/state')).settings?.mail_assign === 'always');
  check((await call('GET', '/api/state')).settings?.mail_assign === 'always', '#2146: the choice is saved');
  d.querySelectorAll('.modal').forEach(m => m.remove());

  // ================= Settings > Workspaces > the organisation's channels
  w.eval(`settingsModal('org')`);
  await until(() => d.querySelector(`.chnbox[data-chnorg="${ORG}"]:not([hidden]) [data-chn="new"]`), 60);
  const ob = d.querySelector(`.chnbox[data-chnorg="${ORG}"]`);
  check(!!ob && !ob.hidden && /Forwardings/.test(ob.querySelector('h5')?.textContent || ''), '#2145: the organisation has a section Forwardings');  // 2.165.3 (#2657)
  check(/never private areas/i.test(ob.textContent), '#2145: it says: never private areas');
  click(w, ob.querySelector('[data-chn="new"]'));
  await until(() => d.querySelector('#chn-kind'));
  const oev = [...dlg().querySelectorAll('[data-chnev]')].map(x => x.dataset.chnev + (x.checked ? '+' : ''));
  check(oev.join(',') === 'newtask+,complete+,assign+,comment+', '#2145: the organisation\'s events, all checked: ' + oev);
  w.close();
  const wb = await boot({user: 'bob'});
  wb.eval(`settingsModal('org')`); await sleep(1500);
  check(!wb.document.querySelector('.chnbox'), '#2145: a member does not see the organisation\'s channels');
  wb.close();

  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
