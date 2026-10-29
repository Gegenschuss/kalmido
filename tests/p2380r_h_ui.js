// kalmido-suite: fresh
// 2.380 H UI tests (jsdom), own container (start.sh with a mail server set, so invitations are offered). Invented names only.
// - #3392: the event editor shows "Guest list visible to guests" once an external guest is in the list (off by default);
//   switched on and saved, the event has guests_visible; opened again, the switch is on
// - #3387: the temporary id map of new tasks keeps an entry for 24 hours (another tab may still hold its -N), not 10 minutes
// - #3387: back from the back-forward cache (pageshow persisted) an open note loads again: its base (updated_at) is the
//   server's, so the next key press is no false conflict
// - #2356: the share dialog of a page has the switch "Show embedded pictures" (off); on, a new public link shows pictures;
//   "Hide pictures" on the link turns it off again
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, errs, B, login, until} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
if (!process.env.P2380RH_NOSTART) {
  execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore', env: {...process.env, EXTRA: (process.env.EXTRA || '')
    + ' -e KALMIDO_SMTP_HOST=127.0.0.1 -e KALMIDO_SMTP_PORT=1025 -e KALMIDO_SMTP_TLS=none -e KALMIDO_MAIL_FROM=kalmido@example.test'}});
}
const sql = (q, a = []) => JSON.parse(execFileSync('python3', [path.join(__dirname, 'dbx.py'), DATA, q, JSON.stringify(a)]).toString() || '[]');
let CK;
const call = async (method, url, body, ck = CK) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: ck}, body: body ? JSON.stringify(body) : undefined}); return {http: r.status, ...(await r.json().catch(() => ({})))}; };
const online = w => { w.__offline = false; w.eval('OUT.retryAt = 0'); w.dispatchEvent(new w.Event('online')); };

(async () => {
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true, modules: ['cal', 'comments']});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done', features: 'cal,comments,events,contacts,wiki,files'});
  sql("UPDATE users SET email='alice@example.com' WHERE username='alice'");
  const cal = await call('POST', '/api/evcals', {name: 'Alice Termine'});
  const P = (await call('POST', '/api/lists', {name: 'Flyer'})).id;
  const T = (await call('POST', '/api/tasks', {title: 'Drucken', list_id: P})).id;
  const N1 = await call('POST', `/api/lists/${P}/notes`, {title: 'Briefing', body: 'Start'});
  const PG = (await call('POST', '/api/wiki/pages', {space: 'private', path: 'Doku/Bilder', body: 'Mit Bild.'})).id;
  check(cal.id > 0 && T > 0 && N1.id > 0 && PG > 0, 'setup');

  // ================= #3392: the switch in the event editor
  let w = await boot({user: 'alice', hash: 'cal'}), d = w.document;
  check(await until(() => typeof w.evEditor === 'function' || w.eval('typeof evEditor') === 'function'), 'the calendar is loaded');
  w.eval(`evEditor({start: '2030-03-04T10:00', end: '2030-03-04T11:00', cal_id: ${cal.id}})`);
  check(!!await until(() => d.querySelector('.evmodal #ev-attin')), 'the event editor');
  check(await until(() => w.eval(`!!document.querySelector('.evmodal')._evi?.info`)), 'the invitation info is there');
  check(!d.querySelector('#ev-gvrow') || d.querySelector('#ev-gvrow').hidden, '#3392: no guest list switch without external guests');
  const m = d.querySelector('.evmodal');
  m.querySelector('#ev-attin').value = 'gast.eins@example.com'; m.querySelector('[data-evm="attadd"]').click();
  check(await until(() => d.querySelector('#ev-gvrow') && !d.querySelector('#ev-gvrow').hidden && d.querySelector('#ev-gv')?.checked === false),
    '#3392: an external guest brings "Guest list visible to guests", off');
  check(/Guest list visible to guests/.test(d.querySelector('#ev-gvrow')?.textContent || ''), '#3392: the switch is labelled');
  d.querySelector('#ev-gv').click();
  d.querySelector('#ev-gv').dispatchEvent(new w.Event('change', {bubbles: true}));
  check(w.eval(`evi_gv(document.querySelector('.evmodal'))`) === true, '#3392: switched on');
  const inv = d.querySelector('#ev-inv'); if (inv?.checked) inv.click();  // no mail needed here
  m.querySelector('#ev-title').value = 'Abstimmung Gaeste'; m.querySelector('[data-evm="save"]').click();
  check(await until(() => !d.querySelector('.evmodal')), 'saved');
  const evs = await call('GET', '/api/events?from=2030-03-04&to=2030-03-04');
  const e1 = (evs.items || []).find(x => x.title === 'Abstimmung Gaeste');
  const full = e1 ? await call('GET', `/api/events/${e1.eid}`) : {};
  check(full.guests_visible === true, '#3392: the event has the guest list visible ' + JSON.stringify(full).slice(0, 200));
  if (e1) {
    delete full.http;
    w.eval(`evEditor({ev: ${JSON.stringify(full)}})`);
    check(await until(() => d.querySelector('#ev-gv')?.checked === true), '#3392: opened again, the switch is on');
    d.querySelector('.evmodal [data-m="close"], .evmodal [data-evm="cancel"]')?.click();
    d.querySelector('.evmodal')?.remove();
  }

  // ================= #3387: the temporary id map keeps an entry 24 hours
  const now = w.eval('Date.now()');
  w.eval(`LS.set('idmap', {'${-(now - 2 * 3600e3)}': 901, '${-(now - 25 * 3600e3)}': 902})`);
  w.__offline = true;
  await w.eval(`api('PATCH', '/api/tasks/${T}', {title: 'Drucken offline'})`);
  check(w.eval('OUT.q.length') === 1, '#3387: the change waits');
  online(w);
  check(await until(() => w.eval('OUT.q.length') === 0 && !w.eval('OUT.flushing'), {timeout: 20000}), '#3387: the queue went out');
  const idm = w.eval(`LS.get('idmap', {})`);
  check(Object.values(idm).includes(901), '#3387: an entry of 2 hours stays (was gone after 10 minutes) ' + JSON.stringify(idm));
  check(!Object.values(idm).includes(902), '#3387: an entry older than 24 hours goes');
  w.close();

  // ================= #3387: a note loads again after the back-forward cache
  w = await boot({user: 'alice', hash: 'note/' + N1.id}); d = w.document;
  check(await until(() => w.eval(`!!(S.nt.notes || []).find(n => n.id === ${N1.id})`)), 'the note is open');
  const before = w.eval(`S.nt.notes.find(n => n.id === ${N1.id}).updated_at`);
  const srv = await call('PATCH', `/api/notes/${N1.id}`, {body: 'Sent at pagehide', expect_updated_at: before});
  check(srv.http === 200 && srv.updated_at && srv.updated_at !== before, 'the server has a newer version (as after the keepalive at pagehide) ' + JSON.stringify(srv).slice(0, 160));
  const ps = new w.Event('pageshow'); Object.defineProperty(ps, 'persisted', {value: true}); w.dispatchEvent(ps);
  check(await until(() => w.eval(`S.nt.notes.find(n => n.id === ${N1.id})?.updated_at`) === srv.updated_at),
    '#3387: back from the cache the note has the server\'s base ' + w.eval(`S.nt.notes.find(n => n.id === ${N1.id})?.updated_at`));
  const r = await w.eval(`(() => { const n = S.nt.notes.find(x => x.id === ${N1.id}); return ntWrite(n, {body: 'Next key press', expect_updated_at: n.updated_at}).then(x => x.body || x.queued, e => 'err ' + e.status); })()`);
  check(r === 'Next key press', '#3387: the next change is no conflict ' + r);
  w.close();

  // ================= #2356: the switch in the share dialog of a page
  w = await boot({user: 'alice', hash: 'wiki/' + PG}); d = w.document;
  (await until(() => d.querySelector(`[data-wsh-share="${PG}"]`)))?.click();
  check(!!await until(() => d.querySelector('.abshdlg .fsextra [data-wsh="link"]')), 'the share dialog with the links section');
  const sw = await until(() => d.querySelector('.abshdlg #wsh-img'));
  check(!!sw && sw.checked === false && /Show embedded pictures/.test(d.querySelector('.abshdlg .fsextra')?.textContent || ''), '#2356: "Show embedded pictures", off');
  sw && (sw.checked = true);
  d.querySelector('.abshdlg .fsextra [data-wsh="link"]').click();
  check(await until(() => sql('SELECT images FROM wiki_shares WHERE page_id=? AND kind=?', [PG, 'link']).some(x => +x.images === 1)), '#2356: the new link shows pictures');
  const hide = await until(() => [...d.querySelectorAll('.abshdlg [data-wsh="img"]')].find(b => /Hide pictures/.test(b.textContent)));
  check(!!hide && /Pictures shown/.test(d.querySelector('.abshdlg .fsextra')?.textContent || ''), '#2356: the link says so and offers "Hide pictures"');
  hide?.click();
  check(await until(() => sql('SELECT images FROM wiki_shares WHERE page_id=? AND kind=?', [PG, 'link']).every(x => +x.images === 0)), '#2356: "Hide pictures" turns it off');
  check(!!await until(() => [...d.querySelectorAll('.abshdlg [data-wsh="img"]')].find(b => /Show pictures/.test(b.textContent))), '#2356: then "Show pictures"');
  w.close();

  check(!errs.length, 'no script errors: ' + errs.slice(0, 3).join(' | '));
  console.log(`p2380r_h_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.log('FAIL: crashed', e.stack); process.exit(1); });
