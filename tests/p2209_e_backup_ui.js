// 2.209.0 test, part E (#1627): backups on a small disk and a restore that meets a deadlock. Own container (start.sh), jsdom.
// freelancer-matrix: admin  (the server's backups are the operator's administration, no organisation involved; no new route)
// - Settings > Whole server > Backups: with room for many more archives no space note; once less than about three more
//   archives of the newest one's size fit, a note says so (the free space comes from the server, here set in the page data)
// - the restore (admin/backup.py _pg_restore) runs pg_restore again after a deadlock (one transaction: nothing changed),
//   at most BK_RESTORE_TRIES times, and never after another error (checked in the container with pg_restore stubbed)
const path = require('path');
const {execFileSync} = require('child_process');
const {boot, sleep, B, login, errs} = require('./boot');
const F = []; let ok = 0;
const check = (c, what) => { if (c) ok++; else { F.push(what); console.log('FAIL:', what); } };
const H = {'Content-Type': 'application/json', 'X-Requested-With': 'kalmido'};
const DATA = process.argv[2] || path.join(__dirname, '.data');
const CT = process.env.KALMIDO_TEST_CONTAINER || 'kalmido-test';
if (!process.env.P2209E_NOSTART && !process.env.KMT_NOSTART) execFileSync('bash', [path.join(__dirname, 'start.sh'), DATA], {stdio: 'ignore'});
let CK;
const call = async (method, url, body) => { const r = await fetch(B + url.replace(/^\//, ''), {method, headers: {...H, Cookie: CK}, body: body ? JSON.stringify(body) : undefined}); return {...(await r.json().catch(() => ({}))), status: r.status}; };
const until = (fn, n) => require('./boot').until(fn, {timeout: n ? n * 250 : 15000, step: 250});  // 2.358.0 (#3286): the shared wait of tests/boot.js (default at least 15 s); an explicit n/ms keeps its window

// the retry around pg_restore, with pg_restore itself stubbed (no database is restored)
const RETRY = String.raw`
import json, time
from kalmido.admin import backup as bk
c = bk._pg.connect_direct(bk.DATABASE_URL)
tables = {r[0] for r in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
c.close()
bk._toc_file = lambda dump: ("toc", tables)
time.sleep = lambda s: None
def case(fail_times, raw):
    calls = []
    def run(args, err_code="io", timeout=None):
        calls.append(args[0])
        if len(calls) <= fail_times:
            e = bk.BackupError(err_code, "pg_restore: while PROCESSING TOC:")
            e.raw = raw
            raise e
    bk._pg_run = run
    try:
        bk._pg_restore("dump")
        return [len(calls), ""]
    except bk.BackupError as e:
        return [len(calls), e.code]
dl = b"pg_restore: while PROCESSING TOC:\npg_restore: error: could not execute query: ERROR:  deadlock detected\n"
print(json.dumps({"tries": bk.BK_RESTORE_TRIES, "once": case(1, dl), "always": case(99, dl),
                  "other": case(1, b"pg_restore: error: could not execute query: ERROR:  relation does not exist\n")}))
`;

(async () => {
  await sleep(600);
  await fetch(B + 'api/auth/setup', {method: 'POST', headers: H, body: JSON.stringify({username: 'alice', display_name: 'Alice', password: 'password123'})});
  CK = await login('alice');
  await call('POST', '/api/admin/setup', {lang: 'en', collab_all: true});
  await call('PATCH', '/api/settings', {lang: 'en', tour: 'done'});
  const now = await fetch(B + 'api/admin/backups', {method: 'POST', headers: {...H, Cookie: CK}});
  const st = await until(async () => { const j = await call('GET', '/api/admin/backups'); return !j.running && j.items?.length && j; });
  check(now.status === 202 && st && st.items[0].size > 0 && st.free_bytes > 0, `setup: one backup, the free space known (${now.status})`);

  // ---- the space note on the backup page
  const w = await boot({user: 'alice', hash: 'today'}), d = w.document;
  w.eval(`settingsModal('users')`);
  const md = await until(() => d.querySelector('.smodal #s-bk .bklist') && d.querySelector('.smodal'));
  const box = md && md.querySelector('#s-bk');
  check(!!box && !box.querySelector('.bkspace'), 'plenty of room: no space note');
  const size = st.items[0].size;
  await w.bkDraw(md, {...box._j, free_bytes: size * 2});
  const note = box.querySelector('.bkspace');
  check(!!note && /Little space left on the disk for further backups/.test(note.textContent) && note.classList.contains('cnote'), 'room for less than three more archives: the note ' + (note && note.textContent));
  await w.bkDraw(md, {...box._j, free_bytes: size * 4});
  check(!box.querySelector('.bkspace'), 'room for four more: no note');
  await w.bkDraw(md, {...box._j, free_bytes: 1, items: []});
  check(!box.querySelector('.bkspace'), 'no backup yet: no note (nothing to measure by)');
  // ---- 2.446.0 (#3613): a backup of an earlier passphrase: the download asks for it in the same step, the ticket carries it
  w.__dialogs = 'manual';
  const DL = '/api/admin/backups/older.zip.enc/download', sent = [], clicked = [], fetch0 = w.fetch;
  const J = (st, o) => new Response(JSON.stringify(o), {status: st, headers: {'Content-Type': 'application/json'}});
  w.fetch = async (u, o) => {
    if (!String(u).startsWith(DL)) return fetch0(u, o);
    const b = JSON.parse(o.body); sent.push(b);
    return b.passphrase === 'the older one' ? J(200, {ticket: 'tk'}) : J(400, {code: b.passphrase ? 'passphrase' : 'old_passphrase', error: b.passphrase ? 'Wrong passphrase' : 'An earlier passphrase'});
  };
  const aclick = w.HTMLAnchorElement.prototype.click;
  w.HTMLAnchorElement.prototype.click = function () { if (this.hidden) clicked.push(this.getAttribute('href')); else aclick.call(this); };
  d.body.insertAdjacentHTML('beforeend', `<a id="t3613" href="${DL}" data-sudl>x</a>`);
  const answer = async (text, pass) => {
    const inp = await until(() => { const x = d.querySelector('#cdlg-in'); return x && x.closest('.modal,.smodal,dialog,div')?.isConnected && d.body.textContent.includes(text) && x; });
    check(!!inp, `the passphrase is asked for: ${text}`);
    inp.value = pass; d.querySelector('[data-cd="yes"]').click();
  };
  d.querySelector('#t3613').click();
  await answer('An earlier passphrase', 'wrong one');
  await until(() => sent.length === 2);
  await answer('Wrong passphrase', 'the older one');
  await until(() => clicked.length);
  check(JSON.stringify(sent.map(x => x.passphrase || '')) === '["","wrong one","the older one"]', 'the passphrases sent: ' + JSON.stringify(sent));
  check(clicked[0] === `${DL}?t=tk`, 'the file comes with the ticket: ' + clicked[0]);
  // ---- 2.525.0 (#4303): the check of a backup of an earlier passphrase asks for it the same way, then checks with it
  const VF = '/api/admin/backups/older.zip.enc/verify', vsent = [];
  w.fetch = async (u, o) => {
    if (!String(u).startsWith(VF)) return fetch0(u, o);
    const b = JSON.parse(o.body); vsent.push(b);
    return b.passphrase === 'the older one' ? J(200, {ok: true, counts: {tasks: 7}, attachment_files: 2})
      : J(400, {code: b.passphrase ? 'passphrase' : 'old_passphrase', error: b.passphrase ? 'Wrong passphrase (check)' : 'An earlier passphrase (check)'});
  };
  await w.bkDraw(md, {...box._j, passphrase_set: true, items: [{...st.items[0], name: 'older.zip.enc', encrypted: true}]});
  const vb = box.querySelector('[data-bkn="older.zip.enc"] [data-bk="verify"]');
  check(!!vb, 'the check button of the older backup');
  vb?.click();
  await answer('An earlier passphrase (check)', 'wrong one');
  await until(() => vsent.length === 2);
  await answer('Wrong passphrase (check)', 'the older one');
  const vok = await until(() => vsent.length === 3 && d.body.textContent.includes('Backup is complete and readable'));
  check(!!vok && JSON.stringify(vsent.map(x => x.passphrase || '')) === '["","wrong one","the older one"]', 'the check asks for the earlier passphrase and then passes: ' + JSON.stringify(vsent));
  w.fetch = fetch0; w.HTMLAnchorElement.prototype.click = aclick; w.__dialogs = undefined;
  check(!errs.length, 'no script errors: ' + errs.join(' | '));

  // ---- the restore tries pg_restore again after a deadlock only
  let out = '';
  for (let i = 0; i < 3; i++) {  // (importing the app in a second process may meet the server's start-up DDL, as backup_test)
    try { out = execFileSync('docker', ['exec', CT, 'python3', '-c', RETRY], {encoding: 'utf8'}); break; } catch (e) { out = String(e.stdout || '') + String(e.stderr || ''); await sleep(1000); }
  }
  let j = null;
  try { j = JSON.parse(out.trim().split('\n').pop()); } catch { j = null; }
  check(j && j.tries === 3, 'three tries at most ' + out.slice(-300));
  check(j && JSON.stringify(j.once) === '[2,""]', 'a deadlock once: the second run restores ' + JSON.stringify(j && j.once));
  check(j && JSON.stringify(j.always) === '[3,"restore"]', 'a deadlock every time: the restore fails after three runs ' + JSON.stringify(j && j.always));
  check(j && JSON.stringify(j.other) === '[1,"restore"]', 'another error: no second run ' + JSON.stringify(j && j.other));

  console.log(`p2209_e_backup_ui: ${ok} ok, ${F.length} failed`);
  process.exit(F.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(1); });
