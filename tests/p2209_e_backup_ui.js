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
const until = async (fn, n = 60) => { for (let i = 0; i < n; i++) { const x = await fn(); if (x) return x; await sleep(250); } return fn(); };

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
