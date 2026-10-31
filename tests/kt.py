"""kt.py - shared helpers for the Python suites (2.149.0 E, #2513 #2514). New suites import these instead of copying them;
the older suites keep their own copies (they keep working, nothing has to move).

    import kt
    from kt import B, DATA, check, sess, until
    kt.fresh(env={"KALMIDO_DOCS_SCAN_S": "2"})      # (re)start the container unless <PREFIX>_NOSTART / KMT_NOSTART is set
    A = kt.setup()                                     # first admin "alice" + instance setup, logged in
    s = sess("bob")                                    # a logged-in session (password123)
    row = until(lambda: kt.dbx("SELECT ..."), 20)      # wait for a state instead of a fixed sleep
    check(cond, "what")  ...  sys.exit(kt.done("p2149_e_api"))

Settings come from the environment like in start.sh (KALMIDO_TEST_PORT, KALMIDO_TEST_CONTAINER, KALMIDO_TEST_DATA / argv[1]).
The test time: testclock.now() / today() (KALMIDO_TEST_NOW, run_all.sh `now <instant>; fresh`) - re-exported here."""
import os
import subprocess
import sys
import time

N = os.path.dirname(os.path.abspath(__file__))
if N not in sys.path:
    sys.path.insert(0, N)
import dbx as _dbx  # noqa: E402
from testclock import now, today  # noqa: E402,F401  (re-exported)

DATA = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else os.environ.get("KALMIDO_TEST_DATA") or os.path.join(N, ".data")
PORT = os.environ.get("KALMIDO_TEST_PORT", "3048")
B = "http://127.0.0.1:" + PORT
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
H = {"X-Requested-With": "kalmido"}
PASSWORD = "password123"
FAILS, OKS = [], [0]


FIRST_FAIL = []


def on_first_fail(fn):
    """2.358.0 D (#2783): call fn() once, right after the first failed check (e.g. print the container's log)."""
    FIRST_FAIL.append(fn)


def docker_logs_on_first_fail(tail=60, chars=6000):
    """2.358.0 D (#2783): the server's side of the first failure (a traceback of a background thread) into the output."""
    def show():
        r = subprocess.run(["docker", "logs", "--tail", str(tail), CT], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(r.stdout[-chars:], flush=True)
    on_first_fail(show)


def check(cond, what):
    """Count a passed check or print and remember a failed one (the suite ends with sys.exit(done(name)))."""
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)
        if len(FAILS) == 1:
            for fn in FIRST_FAIL:
                fn()
    return bool(cond)


def done(name):
    """Print the summary line run_all.sh greps for; -> the exit code."""
    print(f"{name}: {OKS[0]} ok, {len(FAILS)} failed", flush=True)
    return 1 if FAILS else 0


def sess(user=None, pw=PASSWORD, ip=None, ua=None, headers=None, session_cls=None, hooks=(), soft=False, json_ok=False):
    """A logged-in session with the X-Requested-With header (user None: a session that is not logged in, 2.206.0 #2762).
    2.358.0 D (#2783), all optional: ip = X-Forwarded-For on the login request only; headers = extra headers of the whole
    session (ua = its User-Agent); session_cls = a requests.Session subclass; hooks = response hooks; json_ok = the login
    answer must carry ok=true too; soft = -> None instead of an assert error when the login fails."""
    import requests  # here, not at the top: the lint job runs i18n/mcp suites without requests installed (CI of 2.168.4)
    s = (session_cls or requests.Session)()
    s.headers.update(H)
    if ua:
        s.headers["User-Agent"] = ua
    if headers:
        s.headers.update(headers)
    for h in hooks:
        s.hooks["response"].append(h)
    if user is None:
        return s
    r = s.post(B + "/api/auth/login", json={"username": user, "password": pw}, headers={"X-Forwarded-For": ip} if ip else {})
    good = r.ok and (not json_ok or r.json().get("ok"))
    if soft:
        return s if good else None
    assert good, (user, r.text)
    return s


def until(fn, timeout=30, step=0.25, secs=None):
    """Call fn until it returns something truthy (-> that value) or timeout seconds are over (-> fn's last value).
    The one way to wait for a state: no fixed sleeps for things the server does in the background.
    secs = timeout (the name of the older suites' own copies, 2.206.0 #2762)."""
    end = time.monotonic() + (timeout if secs is None else secs)
    while True:
        x = fn()
        if x or time.monotonic() >= end:
            return x
        time.sleep(step)


def dbx(sql, args=(), data=None):
    """Rows of a query in the suite's database (tests/dbx.py, the data dir names it)."""
    c = _dbx.connect(os.path.join(data or DATA, "tasks.db"))
    try:
        return c.execute(sql, args).fetchall()
    finally:
        c.close()


def nostart(prefix=""):
    """True when the container runs already: <PREFIX>_NOSTART=1 (e.g. P2149E_NOSTART) or KMT_NOSTART=1."""
    return bool((prefix and os.environ.get(prefix + "_NOSTART")) or os.environ.get("KMT_NOSTART"))


def fresh(env=None, prefix="", keep=False, data=None):
    """(Re)start the test container through start.sh with extra container settings (env: {name: value} -> docker -e), unless
    nostart(prefix). keep=True keeps the data dir and database (KEEP=1). Waits until /api/health answers (start.sh does)."""
    if nostart(prefix):
        return False
    extra = os.environ.get("EXTRA", "")
    for k, v in (env or {}).items():
        extra += f" -e {k}={v}"
    e = dict(os.environ, EXTRA=extra.strip())
    if keep:
        e["KEEP"] = "1"
    else:
        e.pop("KEEP", None)
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), data or DATA], env=e, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    return True


def setup(user="alice", name="Alice Admin", lang="en", collab_all=True):
    """The first account (instance admin) on an empty server plus the instance setup -> its logged-in session."""
    import requests
    s0 = requests.Session()
    s0.headers.update(H)
    r = s0.post(B + "/api/auth/setup", json={"username": user, "display_name": name, "password": PASSWORD})
    assert r.ok, r.text
    a = sess(user)
    a.post(B + "/api/admin/setup", json={"lang": lang, "collab_all": collab_all})
    return a


def container_env(name):
    """The value of an environment variable inside the running test container ('' when unset)."""
    r = subprocess.run(["docker", "exec", CT, "printenv", name], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def su_get(s, url, pw=PASSWORD, **kw):
    """2.223.2 C (#2871): a download behind the step-up (retention exports, the own office's export): POST with the password
    -> a one-time ticket, then GET with it. -> the GET response (or the refused POST's one)."""
    r = s.post(url, json={"password": pw})
    if not r.ok:
        return r
    return s.get(url, params={"t": r.json().get("ticket", "")}, **kw)
