#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.521.0 E (#4475): the database stays inside its memory limit while a stack is split and its parts are recognised.
Own database container "<container>-memdb" (postgres:17 with the db settings of docker-compose.yml - their defaults -,
data on an anonymous volume like a server's folder) and its own app container (start.sh). The database gets a hard limit
(docker update --memory 512m --memory-swap 512m, P2521E_CAP overrides) after the start; then, as a person without an
organisation (freelancer-matrix: files), a drawn stack of 30 parts (archive number codes) is uploaded, recognised, split,
and its 30 parts recognised while 30 parallel readers keep the web threads busy. Every half second the suite notes the
database's memory (cgroup memory.current / memory.stat, docker stats as fallback) and its connections (pg_stat_activity).
 - the database never restarts (pg_postmaster_start_time unchanged, not OOMKilled), every part is recognised
 - the app's pool fits the database: pool max + direct connections <= max_connections less the reserve (/api/admin/health)
 - the connections the app opened stay at or below its pool max + direct connections
 - #4475 (4): one backend of the database killed (kill -9, as the OOM killer does: Postgres restarts every backend) while a
   document is being recognised: the queue takes the cut-off run up again within seconds, not after RUN_STALE minutes
The limit goes with the container at the end (docker rm -f -v). PERF lines in the log (run_all.sh shows them): the numbers before / after.
Invented names only; every PDF is drawn here (Pillow + segno in the test container).
usage: p2521_e_dbmem_test.py <datadir>"""
import base64
import json
import os
import re
import subprocess
import sys
import threading
import time

import requests

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
from kt import FAILS, OKS, check, done as kt_done, sess, until  # noqa: E402

DATA = sys.argv[1] if len(sys.argv) > 1 else os.path.join(N, ".data")
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
DBC = CT + "-memdb"
CAP = os.environ.get("P2521E_CAP", "512m")
PARTS = int(os.environ.get("P2521E_PARTS", "30"))
H = {"X-Requested-With": "kalmido"}


def compose_db_args():
    """The `-c name=value` settings of the db service in docker-compose.yml, ${VAR:-default} read as the default."""
    with open(os.path.join(N, "..", "docker-compose.yml"), encoding="utf-8") as f:
        y = f.read()
    m = re.search(r"\n  db:\n(.*?)(?=\n  [a-z][\w-]*:\n|\Z)", y, re.S)
    cmd = re.search(r'command:\s*\[(.*?)\]', m.group(1), re.S) if m else None
    assert cmd, "docker-compose.yml: no command of the db service"
    words = re.findall(r'"([^"]*)"', cmd.group(1))
    words = [re.sub(r"\$\{\w+:-([^}]*)\}", r"\1", w) for w in words]
    out = []
    for i, w in enumerate(words):
        if w == "-c" and i + 1 < len(words):
            out += ["-c", words[i + 1]]
    return out


def dbq(q):
    r = subprocess.run(["docker", "exec", DBC, "psql", "-U", "kalmido", "-d", DBN, "-Atqc", q], capture_output=True, text=True, timeout=20)
    return r.stdout.strip() if r.returncode == 0 else None


def mem():
    """(current bytes, anon bytes, shmem bytes) of the database container."""
    r = subprocess.run(["docker", "exec", DBC, "sh", "-c", "cat /sys/fs/cgroup/memory.current /sys/fs/cgroup/memory.stat 2>/dev/null"],
                       capture_output=True, text=True, timeout=20)
    ln = r.stdout.split("\n")
    if r.returncode == 0 and ln and ln[0].strip().isdigit():
        st = dict(x.split(" ", 1) for x in ln[1:] if " " in x)
        return int(ln[0]), int(st.get("anon", 0)), int(st.get("shmem", 0))
    s = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", DBC], capture_output=True, text=True).stdout
    m = re.match(r"([\d.]+)\s*([KMG]i?B)", s.strip())
    f = {"KiB": 1 << 10, "MiB": 1 << 20, "GiB": 1 << 30, "KB": 1e3, "MB": 1e6, "GB": 1e9}
    return (int(float(m.group(1)) * f.get(m.group(2), 1)) if m else 0), 0, 0


MB = lambda b: round(b / 1048576)  # noqa: E731

# ---- the database container (the compose settings) and the app on it
subprocess.run(["docker", "rm", "-f", "-v", DBC], capture_output=True)
ARGS = compose_db_args()
print("PERF db settings from docker-compose.yml:", " ".join(ARGS), flush=True)
subprocess.run(["docker", "run", "-d", "--name", DBC, "--network", "bridge", "-e", "POSTGRES_USER=kalmido", "-e", "POSTGRES_PASSWORD=kalmido",
                "-e", "POSTGRES_DB=kalmido", "-v", "/var/lib/postgresql/data", "postgres:17", *ARGS, "-c", "fsync=off",
                "-c", "synchronous_commit=off"], check=True, stdout=subprocess.DEVNULL)
assert until(lambda: subprocess.run(["docker", "exec", DBC, "psql", "-U", "kalmido", "-d", "kalmido", "-Atqc", "SELECT 1"],
                                    capture_output=True).returncode == 0, 60), "database container did not come up"
until(lambda: subprocess.run(["docker", "logs", DBC], capture_output=True, text=True).stderr.count("ready to accept connections") >= 2, 30)
assert until(lambda: subprocess.run(["docker", "exec", DBC, "psql", "-U", "kalmido", "-d", "kalmido", "-Atqc", "SELECT 1"],
                                    capture_output=True).returncode == 0, 60), "database container did not come back after its init"
try:
    key = base64.b64encode(os.urandom(32)).decode()
    env = dict(os.environ, KALMIDO_TEST_DB_CONTAINER=DBC,
               EXTRA=os.environ.get("EXTRA", "") + f" -e KALMIDO_ORGCRYPT_DELAY=0 -e KALMIDO_SECRET_KEY={key} -e TASKS_MAX_FILE_MB=40")
    env.pop("KEEP", None)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    DBN = open(os.path.join(DATA, ".kalmido-db"), encoding="utf-8").read().split()[1]
    s0 = requests.Session()
    s0.headers.update(H)
    assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice Admin", "password": "password123"}).ok
    A = sess("alice")
    A.post(B + "/api/admin/setup", json={"lang": "en", "collab_all": True})
    FID, Fr = freelancer(B, A)

    hl = A.get(B + "/api/admin/health").json()
    pool, cb = hl.get("pool") or {}, hl.get("connections") or {}
    print(f"PERF app pool max {pool.get('max')}, threads {(hl.get('threads') or {}).get('configured')}, "
          f"max_connections {cb.get('max_connections')} (reserved {cb.get('reserved')}), need {cb.get('need')}", flush=True)
    check(cb.get("ok") is True, f"the app's pool fits the database: need {cb.get('need')} <= max_connections {cb.get('max_connections')} - {cb.get('reserved')}")
    START0 = dbq("SELECT pg_postmaster_start_time()")

    cap = subprocess.run(["docker", "update", "--memory", CAP, "--memory-swap", CAP, DBC], capture_output=True, text=True)
    assert cap.returncode == 0, "docker update --memory: " + cap.stderr
    m0 = mem()
    print(f"PERF start under the {CAP} limit: {MB(m0[0])} MB (anon {MB(m0[1])}, shmem {MB(m0[2])})", flush=True)

    # ---- the sampler: memory + connections every half second
    SAMPLES, STOP = [], threading.Event()

    def sampler():
        while not STOP.is_set():
            try:
                cur, anon, shm = mem()
                n = dbq(f"SELECT count(*) FROM pg_stat_activity WHERE datname='{DBN}' AND backend_type='client backend'")
                SAMPLES.append((time.monotonic(), cur, anon, shm, int(n) if n and n.isdigit() else -1))
            except Exception as e:  # noqa: BLE001 - one missed sample is no failure
                print("sample:", type(e).__name__, e, flush=True)
            STOP.wait(0.5)

    th = threading.Thread(target=sampler, daemon=True)
    th.start()

    # ---- readers: 30 parallel sessions keep the web threads busy (as many people looking at their documents)
    READ_STOP, READS = threading.Event(), {"ok": 0, "err": 0}

    def reader(i):
        s = A if i % 3 else Fr  # shared sessions: 30 logins would only meet the login limit
        paths = ["/api/state", "/api/docs?ws=private&facets=1&limit=50", "/api/docs?ws=private&review=1&facets=0"]
        k = 0
        while not READ_STOP.is_set():
            try:
                r = s.get(B + paths[k % len(paths)], timeout=60)
                READS["ok" if r.status_code < 500 else "err"] += 1
            except requests.RequestException:
                READS["err"] += 1
            k += 1

    STACK_CODE = r"""
import base64, io, json, sys, segno
from PIL import Image, ImageDraw, ImageFont
f = ImageFont.load_default(size=40)
pages = []
for spec in json.loads(sys.argv[1]):
    im = Image.new('L', (1654, 2339), 255)
    d = ImageDraw.Draw(im)
    lines = spec.split('\n') if spec else []
    if lines and lines[0].startswith('qr:'):
        q = segno.make(lines.pop(0)[3:], micro=False)
        b = io.BytesIO()
        q.save(b, kind='png', scale=8, border=4)
        im.paste(Image.open(b).convert('L'), (1200, 100))
    for i, ln in enumerate(lines):
        d.text((150, 400 + i * 70), ln, fill=0, font=f)
    pages.append(im)
o = io.BytesIO()
pages[0].save(o, 'PDF', resolution=200, save_all=True, append_images=pages[1:])
print(base64.b64encode(o.getvalue()).decode())
"""
    BODY = "\n".join(f"Position {k}: Beispiel Leistung Nummer {k} zum Preis von {k},00 EUR" for k in range(1, 24))
    # 2.628.0 (#4983): a cover page without an archive number code first -- since 2.580.0 (#4401) a clear stack (every
    # document starting with a code) is split by the docs queue itself as soon as it is recognised, so the suite's own
    # split below raced the queue and got 404 (the stack already in the trash) whenever the queue was first (the CI).
    # With the cover page the stack stays "Stack - split?" (open) and only the route below splits it.
    pages = ["Deckblatt Scan\nBeispiel Stapel ohne Nummer"]
    for p in range(PARTS):
        pages.append(f"qr:ASN{1000 + p:05d}\nRechnung {p + 1}\nBeispiel Lieferant {p + 1} GmbH\nDatum 0{1 + p % 9}.10.2026\n{BODY}")
        pages.append(f"Seite zwei der Rechnung {p + 1}\n{BODY}\nSumme {p + 10},00 EUR")
    pdf = base64.b64decode(subprocess.run(["docker", "exec", CT, "python", "-c", STACK_CODE, json.dumps(pages)],
                                          capture_output=True, text=True, check=True).stdout)
    print(f"PERF stack: {PARTS} parts, {len(pages)} pages, {len(pdf) // 1024} KB", flush=True)

    def stack_state(nid):  # 2.628.0 (#4983): the stack's split state (doc_meta.split_scan) as the server keeps it
        v = dbq(f"SELECT split_scan FROM doc_meta WHERE node_id={int(nid)}")
        return (json.loads(v) if v else {}).get("state")

    def doc(nid):
        r = Fr.get(B + f"/api/docs/{nid}")
        return r.json() if r.ok else None

    T0 = time.monotonic()
    readers = [threading.Thread(target=reader, args=(i,), daemon=True) for i in range(30)]
    for t in readers:
        t.start()
    r = Fr.post(B + "/api/docs", data={"ws": "private"}, files=[("files", ("stapel.pdf", pdf, "application/pdf"))])
    assert r.status_code == 201, r.text
    SID = r.json()["ids"][0]
    d = until(lambda: (lambda x: x if x and x["state"] in ("done", "failed") else None)(doc(SID)), 600)
    check(d and d["state"] == "done" and d["pages"] == len(pages), f"stack recognised ({d and d['state']} {d and d.get('pages')})")
    T1 = time.monotonic()
    s0 = stack_state(SID)
    check(s0 == "open", f"the stack waits for a person, no automatic split ({s0})")
    parts = [[2 * p + 2, 2 * p + 3] for p in range(PARTS)]  # 2.628.0 (#4983): page 1 is the cover page, left out
    r = Fr.post(B + f"/api/docs/{SID}/split", json={"parts": parts}, timeout=300)
    check(r.status_code == 201 and len(r.json().get("ids") or []) == PARTS, f"split into {PARTS} parts ({r.status_code} {r.text[:160]})")
    P = r.json().get("ids") or [] if r.status_code == 201 else []
    T2 = time.monotonic()

    def all_done():
        ds = [doc(p) for p in P]
        return ds if ds and all(x and x["state"] in ("done", "failed") for x in ds) else None

    ds = until(all_done, 900, step=2) or []
    T3 = time.monotonic()
    READ_STOP.set()
    for t in readers:
        t.join(70)
    STOP.set()
    th.join(30)
    check(len(ds) == PARTS and all(x and x["state"] == "done" for x in ds),
          f"every part recognised ({sum(1 for x in ds if x and x['state'] == 'done')}/{PARTS})")

    START1 = dbq("SELECT pg_postmaster_start_time()")
    ins = json.loads(subprocess.run(["docker", "inspect", DBC], capture_output=True, text=True).stdout)[0]["State"]
    logs = subprocess.run(["docker", "logs", DBC], capture_output=True, text=True).stderr
    crash = "terminated by signal 9" in logs or "reinitializing" in logs
    check(START0 and START1 == START0 and not ins.get("OOMKilled") and not crash and ins.get("Restarting") is False,
          f"the database did not restart under {CAP} (start {START0} -> {START1}, OOMKilled {ins.get('OOMKilled')}, crash in log {crash})")
    peak = max(SAMPLES, key=lambda x: x[1]) if SAMPLES else (0, 0, 0, 0, 0)
    conns = max((x[4] for x in SAMPLES), default=-1)
    pk = subprocess.run(["docker", "exec", DBC, "cat", "/sys/fs/cgroup/memory.peak"], capture_output=True, text=True).stdout.strip()
    print(f"PERF times: stack recognised {T1 - T0:.0f} s, split {T2 - T1:.1f} s, {PARTS} parts recognised {T3 - T2:.0f} s; "
          f"reads {READS['ok']} ok / {READS['err']} errors", flush=True)
    print(f"PERF database memory: peak {MB(peak[1])} MB (anon {MB(peak[2])}, shmem {MB(peak[3])}), cgroup memory.peak "
          f"{MB(int(pk)) if pk.isdigit() else '-'} MB, limit {CAP}; connections of the app at most {conns} "
          f"(pool max {pool.get('max')}); {len(SAMPLES)} samples", flush=True)
    for x in SAMPLES[::max(1, len(SAMPLES) // 12)]:
        print(f"PERF   t+{x[0] - T0:5.0f} s  {MB(x[1]):4d} MB  anon {MB(x[2]):4d}  shmem {MB(x[3]):4d}  connections {x[4]}", flush=True)
    pl2 = (A.get(B + "/api/admin/health").json().get("pool") or {})
    print(f"PERF pool after the load: size {pl2.get('pool_size')}, waits that ran out {pl2.get('timeouts')}, "
          f"requests that waited {pl2.get('requests_queued')} ({pl2.get('requests_wait_ms')} ms)", flush=True)
    check(pl2.get("timeouts") == 0, f"no request waited in vain for a connection ({pl2.get('timeouts')})")
    check(0 < conns <= int(pool.get("max") or 0) + 6, f"connections of the app <= its pool max + 6 direct ones ({conns} / {pool.get('max')})")

    # ---- (4) a backend killed while a document is recognised: the cut-off run is taken up again within seconds
    for p in P[:6]:
        Fr.post(B + f"/api/docs/{p}/redo")
    Q = [p for p in P[:6]]
    ids = ",".join(str(int(p)) for p in Q)
    seen = until(lambda: dbq(f"SELECT node_id FROM doc_meta WHERE state='run' AND node_id IN ({ids}) LIMIT 1") or None, 120, step=0.1)
    pid = dbq("SELECT pid FROM pg_stat_activity WHERE backend_type='client backend' AND pid<>pg_backend_pid() LIMIT 1")
    if seen and pid:
        before = dbq(f"SELECT state || ' ' || tries FROM doc_meta WHERE node_id={int(seen)}")
        subprocess.run(["docker", "exec", DBC, "kill", "-9", pid], capture_output=True)
        TK = time.monotonic()
        back = until(lambda: dbq("SELECT 1") == "1", 60)
        check(back, "the database is back after the killed backend")
        after = until(lambda: dbq(f"SELECT state || ' ' || tries FROM doc_meta WHERE node_id={int(seen)}"), 30)
        print(f"PERF resume: document {seen} was '{before}' at the kill, '{after}' once the database was back", flush=True)
        st = until(lambda: (lambda v: v if v == "done" else None)(dbq(f"SELECT state FROM doc_meta WHERE node_id={int(seen)}")), 120, step=0.5)
        took = time.monotonic() - TK
        print(f"PERF resume: the cut-off run of document {seen} done again {took:.0f} s after the kill", flush=True)
        check(st == "done" and took < 120, f"the cut-off run is taken up again within 2 minutes ({st}, {took:.0f} s)")
        rest = until(lambda: dbq(f"SELECT count(*) FROM doc_meta WHERE node_id IN ({ids}) AND state<>'done'") == "0", 180, step=1)
        check(rest, "every document of the redo is recognised after the kill")
    else:
        check(False, f"a run to cut off was seen ({seen}, backend {pid})")
finally:
    subprocess.run(["docker", "rm", "-f", CT], capture_output=True)
    subprocess.run(["docker", "rm", "-f", "-v", DBC], capture_output=True)
sys.exit(kt_done("p2521_e_dbmem"))
