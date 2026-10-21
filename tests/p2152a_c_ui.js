// 2.161.2 UI tests, part C (#2626 #2615 #2616). Own container (start.sh), jsdom. freelancer-matrix: office / news
// - #2626: unread Activity only (For you 0): the bell count is 0, the "More" menu and the sidebar row show no number,
//   the app badge number is the bell's; with something for me every place shows the same number
// - #2615: a short dialog (password) is not "growing" (no grip, a kept size is dropped), one with a text field is
// - #2616: Documents come right after Quotes & invoices; the office opens on the point used last (Pipeline for an admin
//   if nothing is kept; Quotes & invoices for a member; a person without an organisation is an admin)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
const ALL = 'office,cal,timeline,matrix,habits,pomo,collab,stats,time,progress,agents,comments,contacts,clients,review,contracts,home';
(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  const CK = await login('alice');
  await fetch(B + 'api/settings', {method: 'PATCH', headers: {...H, Cookie: CK}, body: JSON.stringify({lang: 'en', tour: 'done', features: ALL})});
  const w = await boot({user: 'alice', hash: 'inbox'}); await sleep(600);
  // ---- #2626
  w.eval(`S.news = {unread: 90, unread_me: 0, sig: 'x'}; S.team = Object.assign(S.team || {}, {dm_unread: 0})`);
  check(w.eval('bellCount()') === 0, '#2626: the bell is empty');
  w.eval(`renderSide && renderSide()`); await sleep(200);
  const row = w.document.querySelector('#side [data-go="news"] .c');
  check(!row || row.textContent.trim() === '', '#2626: the sidebar row shows no number ' + row?.textContent);
  w.eval(`S.news.unread_me = 3`);
  check(w.eval('bellCount()') === 3, '#2626: with something for me the bell shows 3');
  // ---- #2615
  const grows = html => w.eval(`(() => { const c = document.createElement('div'); c.className = 'card'; c.innerHTML = ${JSON.stringify(html)}; document.body.appendChild(c); const r = dlg_grows(c); c.remove(); return r; })()`);
  check(grows('<h3>Recovery key</h3><input type="password"><div class="foot"><button>OK</button></div>') === false, '#2615: a password dialog does not grow');
  check(grows('<h3>Note</h3><textarea></textarea><div class="foot"><button>OK</button></div>') === true, '#2615: a text field grows');
  // ---- #2616
  const order = w.eval(`OFR_ORDER.join()`);
  check(/offers,gendocs,clients/.test(order), '#2616: Documents after Quotes & invoices ' + order);
  w.eval(`LS.set('ofmLast', null); ofm_adm = () => true`);
  check(w.eval('ofm_entry().key') === 'pipeline', '#2616: an admin without a kept point: Pipeline ' + w.eval('ofm_entry().key'));
  w.eval(`ofm_adm = () => false`);
  check(w.eval('ofm_entry().key') === 'offers', '#2616: a member: Quotes & invoices');
  w.eval(`ofm_remember('clients')`);
  check(w.eval('ofm_entry().key') === 'clients', '#2616: the point used last');
  w.eval(`ofm_remember('nonsense')`);
  check(w.eval('ofm_entry().key') === 'offers', '#2616: a gone point: the default');
  w.close();
  console.log(`${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
