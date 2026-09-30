#!/usr/bin/env python3
"""External calendar subscriptions (read-only ICS / CalDAV events next to the tasks): adding ICS links and CalDAV
calendars (discovery via current-user-principal -> calendar-home-set), recurrence expansion (RRULE, EXDATE,
RECURRENCE-ID override, all-day ranges, TZID across a DST change, floating times, cancelled events, rules below daily,
ancient / never-matching rules), the event cap, the size limit, the SSRF guard (private / loopback / link-local names
and addresses, redirects to internal ports, cross-host redirects, the admin allow-list + env), encrypted secrets that
are never returned, ETag / ctag, the background sync, failure alerts for admins (no content), per-user isolation (IDOR),
rate limits, settings, export, cascade on user delete, and KALMIDO_CALENDARS=0.
Starts its OWN test containers (start.sh) with a fake ICS / CalDAV server inside (stub_calendar.py) and host names that
resolve to internal addresses (--add-host). Leaves the main container running for calendars_ui.js (ids in cal_ids.json).
usage: calendars_test.py <datadir>"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

N = os.path.dirname(os.path.abspath(__file__))
DATA = sys.argv[1]
B = "http://127.0.0.1:" + os.environ.get("KALMIDO_TEST_PORT", "3048")
H = {"X-Requested-With": "kalmido"}
CT = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test")
TZ = ZoneInfo("Europe/Berlin")
STUB = "http://127.0.0.1:8095"
FAILS, OKS = [], [0]
T = date.today()


def check(cond, what):
    if cond:
        OKS[0] += 1
    else:
        FAILS.append(what)
        print("FAIL:", what, flush=True)


def sess(user=None, pw="password123"):
    s = requests.Session()
    s.headers.update(H)
    if user:
        r = s.post(B + "/api/auth/login", json={"username": user, "password": pw})
        assert r.ok, (user, r.text)
    return s


def dbx(sql, args=()):
    c = sqlite3.connect(os.path.join(DATA, "tasks.db"), timeout=10)
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def stub_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "calstub.log")) if x.strip()]
    except FileNotFoundError:
        return []


def ntfy_log():
    try:
        return [json.loads(x) for x in open(os.path.join(DATA, "ntfy.log"), encoding="utf-8") if x.strip()]
    except FileNotFoundError:
        return []


def start(extra, env_extra=None):
    subprocess.run(["rm", "-rf", DATA])
    os.makedirs(DATA)
    subprocess.run(["cp", os.path.join(N, "stub_calendar.py"), DATA])
    env = dict(os.environ, KEEP="1", EXTRA=" ".join(extra), **(env_extra or {}))
    r = subprocess.run(["bash", os.path.join(N, "start.sh"), DATA], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    subprocess.run(["docker", "exec", "-d", CT, "python", "/data/stub_calendar.py"])
    time.sleep(0.8)


def py_in_app(code):
    """Runs Python inside the app container with the app module imported (unit checks of the guard)."""
    r = subprocess.run(["docker", "exec", "-w", "/app", "-e", "TASKS_WATCHDOG=0", CT, "python", "-c",
                        "import app, json\n" + code], capture_output=True, text=True)
    return r.stdout.strip().splitlines()[-1] if r.stdout.strip() else "ERR " + r.stderr[-400:]


def events(s, lo=-65, hi=334):
    r = s.get(B + f"/api/calendars/events?from={T + timedelta(days=lo)}&to={T + timedelta(days=hi)}")
    assert r.ok, r.text
    return r.json()


def local(ev):
    return datetime.fromisoformat(ev["start"].replace("Z", "+00:00")).astimezone(TZ)


# ================================================================== 1. feature off (KALMIDO_CALENDARS=0)
start(["-e KALMIDO_CALENDARS=0"])
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
st = A.get(B + "/api/state").json()
check(st["calendars"] == {"enabled": False, "subs": 0}, "feature off: state says disabled " + str(st.get("calendars")))
r = A.post(B + "/api/calendars", json={"kind": "ics", "url": STUB + "/good.ics"})
check(r.status_code == 409, f"feature off: adding refused ({r.status_code})")
check(A.get(B + "/api/calendars").json()["enabled"] is False, "feature off: list says disabled")
check(A.get(B + f"/api/calendars/events?from={T}&to={T}").json() == {"events": [], "subs": {}}, "feature off: no events")
check(not [x for x in stub_log()], "feature off: nothing fetched")

# ================================================================== 2. main container
start(["--add-host evil.test:127.0.0.1", "--add-host meta.test:169.254.169.254", "--add-host ten.test:10.1.2.3",
       "--add-host cgnat.test:100.64.1.1", "--add-host v6local.test:fd00::1",
       "-e KALMIDO_CALENDAR_ALLOW_HOSTS=127.0.0.1:8095", "-e KALMIDO_CALENDAR_MAX_MB=1", "-e KALMIDO_CALENDAR_MAX_EVENTS=200",
       "-e KALMIDO_CALENDAR_REFRESH_GAP=0", "-e KALMIDO_CALENDAR_RATE=60", "-e KALMIDO_CALENDAR_TICK=1", "-e KALMIDO_ADMIN_ALERT_WINDOW=3"],
      {"KALMIDO_ADMIN_ALERTS": "1"})
s0 = sess()
assert s0.post(B + "/api/auth/setup", json={"username": "alice", "display_name": "Alice", "password": "password123"}).ok
A = sess("alice")
ids = {"alice": 1}
for u in ("bob", "carol"):
    r = A.post(B + "/api/users", json={"username": u, "display_name": u.title(), "password": "password123", "ntfy_topic": "t-" + u})
    assert r.ok, r.text
    ids[u] = r.json()["id"]
Bo, Ca = sess("bob"), sess("carol")
admin_topic = dbx("SELECT value FROM user_settings WHERE user_id=1 AND key='ntfy_topic'")[0][0]

# ---- unit checks of the guard inside the container
r = py_in_app("print(json.dumps([app.cal_ip_public(x) for x in ['127.0.0.1','10.1.2.3','172.16.5.4','192.0.0.8','169.254.169.254',"
              "'100.64.1.1','100.127.255.254','0.0.0.0','224.0.0.1','255.255.255.255','::1','fd00::1','fe80::1','::ffff:127.0.0.1',"
              "'::ffff:10.0.0.1','64:ff9b::7f00:1','2002:7f00:1::1','2001::1','::','198.18.0.1','93.184.215.14','2606:4700::1111',"
              "'::ffff:93.184.215.14','1.1.1.1']]))")
check(r == json.dumps([False] * 20 + [True, True, True, True]), "cal_ip_public: private / special addresses refused, public ones allowed: " + r)
r = py_in_app("print(json.dumps([app.cal_norm_url(x) for x in ['webcal://ex.com/a.ics','WEBCALS://ex.com/b','https://ex.com/c','ftp://ex.com/x',"
              "'file:///etc/passwd','http://u:p@ex.com/','javascript:alert(1)','https://ex.com:99999/','http:///nohost','https://ex.com/a b']]))")
check(r == json.dumps(["https://ex.com/a.ics", "https://ex.com/b", "https://ex.com/c", None, None, None, None, None, None, None]),
      "cal_norm_url: webcal -> https, other schemes / userinfo / bad ports refused: " + r)
r = py_in_app("print(json.dumps(app.cal_allow_parse('nextcloud.lan, 10.0.0.20:5232;[fd00::5]:8443 http://x bad_host:0 radicale')))")
check(r == json.dumps([[["nextcloud.lan", None], ["10.0.0.20", 5232], ["fd00::5", 8443], ["radicale", None]], ["http://x", "bad_host:0"]]),
      "allow-list parser: host, host:port, [v6]:port; URLs / port 0 refused: " + r)
# the socket connects to the address that was checked (no second DNS lookup) and never to a private one
r = py_in_app("""import socket
calls = []
socket.getaddrinfo = lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.9.9.9', p)), (socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.215.14', p))]
class S:
    def __init__(self, *a): pass
    def settimeout(self, t): pass
    def connect(self, sa): calls.append(sa[0]); raise OSError('stop')
    def close(self): pass
socket.socket = S
try:
    app._cal_connector(frozenset())(('rebind.example', 443), 5)
except Exception as e:
    calls.append(type(e).__name__)
print(json.dumps(calls))""")
check(r == json.dumps(["93.184.215.14", "OSError"]), "connector: private address skipped, connects to the checked public one: " + r)
r = py_in_app("""import socket
socket.getaddrinfo = lambda h, p, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('127.0.0.1', p))]
try:
    app._cal_connector(frozenset())(('only-private.example', 80), 5); print('connected')
except app.CalError as e:
    print(e.code)""")
check(r == "blocked", "connector: a name with only private addresses is blocked: " + r)

# ---- ICS: the full fixture
r = A.post(B + "/api/calendars", json={"kind": "ics", "url": STUB + "/good.ics"})
check(r.ok and r.json()["created"], "ICS added: " + r.text[:200])
good = r.json()["created"][0]
sub = next(x for x in r.json()["subs"] if x["id"] == good)
check(sub["name"] == "Team Calendar" and sub["status"] == "ok" and sub["kind"] == "ics", "name from X-WR-CALNAME, status ok")
check(sub["url_hint"] == "http://127.0.0.1:8095/…" and "good.ics" not in json.dumps(r.json()), "link never returned (only scheme://host/…)")
check("good.ics" not in dbx("SELECT url FROM cal_subs WHERE id=?", (good,))[0][0], "link stored encrypted")
ev = events(A)["events"]
by = {}
for e in ev:
    by.setdefault(e["title"], []).append(e)
m0 = T - timedelta(days=T.weekday()) - timedelta(weeks=2)
weekly = sorted(local(e).date() for e in by.get("Weekly planning", []))
check(weekly == [m0 + timedelta(weeks=i) for i in range(10) if i not in (3, 4)], f"weekly COUNT=10 minus EXDATE and the moved one: {weekly}")
mv = by.get("Weekly planning (moved)", [])
check(len(mv) == 1 and local(mv[0]).date() == m0 + timedelta(weeks=4) and local(mv[0]).hour == 15, "override (RECURRENCE-ID) moved to 15:00")
check(all(local(e).hour == 10 for e in by.get("Weekly planning", [])), "weekly stays at 10:00 local across the DST change")
conf = by.get("Conference trip", [])
check(len(conf) == 1 and conf[0]["all_day"] and conf[0]["start"] == str(T + timedelta(days=3)) and conf[0]["end"] == str(T + timedelta(days=6)),
      "all-day 3-day event: dates, end exclusive " + str(conf))
ny = by.get("New York standup", [])
ny_utc = {datetime.fromisoformat(e["start"].replace("Z", "+00:00")).hour for e in ny}
check(len(ny) == 20 and ny_utc <= {13, 14} and all(
    datetime.fromisoformat(e["start"].replace("Z", "+00:00")).astimezone(ZoneInfo("America/New_York")).hour == 9 for e in ny),
    f"TZID America/New_York: 20 occurrences, always 09:00 New York time ({len(ny)}, UTC hours {ny_utc})")
fl = by.get("Floating breakfast", [])
check(len(fl) == 1 and local(fl[0]).strftime("%H:%M") == "08:30", "floating time = server time zone (08:30)")
check("Cancelled meeting" not in by, "cancelled event left out")
check("A task, not an event" not in by, "VTODO left out")
check(len(by.get("Every minute", [])) == 1, "MINUTELY rule not expanded (the first occurrence only)")
check(len(by.get("Never repeats", [])) == 1, "rule that never matches: single event")
anc = by.get("Ancient weekly", [])
check(50 <= len(anc) <= 60 and all(date.fromisoformat(e["start"]).weekday() == 0 for e in anc),
      f"DAILY;INTERVAL=7 from the year 1: expanded cheaply, still on Mondays ({len(anc)})")
xss = [e for e in ev if e["title"].startswith("<img")]
check(len(xss) == 1 and xss[0]["location"] == "<script>window.__xss=2</script>", "HTML in SUMMARY / LOCATION kept as text (escaped by the client)")
check(xss and "<a" not in xss[0]["description"] and "<img" not in xss[0]["description"] and "https://ok.example/path" in xss[0]["description"]
      and "click" in xss[0]["description"], "DESCRIPTION: HTML tags removed, text + URL kept: " + (xss[0]["description"] if xss else ""))
lunch = by.get("Lunch with Sam", [])
check(lunch and lunch[0]["location"] == "Cafe Central" and "second line" in lunch[0]["description"] and "\n" in lunch[0]["description"],
      "location + multi-line description")
rng = events(A, 0, 0)["events"]
check({e["title"] for e in rng} >= {"Lunch with Sam", "Never repeats"} and "Conference trip" not in {e["title"] for e in rng},
      "events endpoint: only the asked range")
check(A.get(B + f"/api/calendars/events?from={T}&to={T + timedelta(days=500)}").status_code == 400, "range above 400 days refused")
check(A.get(B + "/api/calendars/events?from=x&to=y").status_code == 400, "bad dates refused")

# ---- Google-style ICS (X-WR-TIMEZONE, UTC times, HTML description, yearly all-day)
r = A.post(B + "/api/calendars", json={"kind": "ics", "url": STUB + "/google.ics", "name": "Google", "color": "#f472b6", "interval": 60})
check(r.ok, "Google ICS added: " + r.text[:200])
gid = r.json()["created"][0] if r.ok else 0
gs = next((x for x in r.json()["subs"] if x["id"] == gid), {}) if r.ok else {}
check(gs.get("name") == "Google" and gs.get("color") == "#f472b6" and gs.get("interval") == 60, "given name / colour / interval kept")
ge = [e for e in events(A)["events"] if e["sub"] == gid]
den = [e for e in ge if e["title"] == "Dentist"]
check(den and local(den[0]).strftime("%H:%M") in ("09:00", "10:00") and den[0]["description"] == "Join: https://meet.example.com/abc\n\nBring & share",
      "Google: UTC time converted, HTML description as plain text: " + (repr(den[0]["description"]) if den else "none"))
bd = sorted(e["start"] for e in ge if e["title"] == "Birthday Kim")
check(len(bd) >= 1 and all(len(x) == 10 for x in bd), "yearly all-day birthday expanded: " + str(bd))

# ---- cap: KALMIDO_CALENDAR_MAX_EVENTS=200, the ones closest to today are kept
r = A.post(B + "/api/calendars", json={"kind": "ics", "url": STUB + "/daily.ics"})
did = r.json()["created"][0]
ds_ = next(x for x in r.json()["subs"] if x["id"] == did)
check(ds_["events"] == 200 and ds_["truncated"], f"daily COUNT=3000: capped at 200, marked truncated ({ds_['events']}, {ds_['truncated']})")
de_ = sorted(date.fromisoformat(local(e).date().isoformat()) for e in events(A)["events"] if e["sub"] == did)
check(de_ and de_[0] <= T <= de_[-1] and (de_[-1] - de_[0]).days <= 201, f"cap keeps the days around today ({de_[0]} .. {de_[-1]})")

# ---- limits, bad content, SSRF
def add_err(url, s=A):
    r = s.post(B + "/api/calendars", json={"kind": "ics", "url": url})
    return r.status_code, r.json().get("code"), r.json().get("error", "")


for path, code in (("/huge.ics", "too_large"), ("/huge-nolen.ics", "too_large"), ("/login.html", "not_calendar"),
                   ("/redir-port.ics", "blocked"), ("/redir-evil.ics", "redirect"), ("/redir-meta.ics", "redirect"),
                   ("/redir-loop.ics", "redirect"), ("/nothing.ics", "not_found")):
    st_, c_, e_ = add_err(STUB + path)
    check(st_ == 400 and c_ == code, f"{path}: refused with {code} (got {st_} {c_} {e_})")
st_, c_, _ = add_err(STUB + "/garbage.ics")
check(st_ == 400 and c_ in ("parse", "not_calendar"), f"broken ICS refused ({c_})")
for url in ("http://evil.test:8095/good.ics", "http://meta.test/latest/meta-data/", "http://ten.test/x.ics", "http://cgnat.test/x.ics",
            "http://v6local.test/x.ics", "http://localhost:8095/good.ics", "http://127.0.0.2:8095/good.ics", "http://[::1]:8095/good.ics",
            "http://0.0.0.0:8095/good.ics", "http://2130706433:8095/good.ics", "http://127.0.0.1:8096/secret", "http://169.254.169.254/latest"):
    st_, c_, e_ = add_err(url)
    check(st_ == 400 and c_ == "blocked" and "private network" in e_, f"SSRF: {url} blocked (got {st_} {c_})")
for url in ("file:///etc/passwd", "ftp://127.0.0.1/x", "http://user:pw@127.0.0.1:8095/good.ics", "gopher://x", ""):
    r = A.post(B + "/api/calendars", json={"kind": "ics", "url": url})
    check(r.status_code == 400, f"invalid link refused: {url!r}")
check(not [x for x in stub_log() if x["port"] == 8096], "the internal service on :8096 was never reached")
check(dbx("SELECT COUNT(*) FROM cal_subs WHERE status!='ok'")[0][0] == 0, "failed adds are not kept")
r = A.post(B + "/api/calendars", json={"kind": "ics", "url": STUB + "/redir-same.ics", "name": "via redirect"})
check(r.ok, "same-host redirect followed")
if r.ok:
    A.delete(B + f"/api/calendars/{r.json()['created'][0]}")

# ---- admin allow-list (settings) + the security alert
r = Bo.patch(B + "/api/admin/settings", json={"cal_allow_hosts": "evil.test"})
check(r.status_code == 403, "allow-list: only admins")
check(A.patch(B + "/api/admin/settings", json={"cal_allow_hosts": "http://evil.test/"}).status_code == 400, "allow-list: URL refused")
st_, c_, _ = add_err("http://evil.test:8095/good.ics", Bo)
check(c_ == "blocked", "before the allow-list: evil.test blocked for bob")
r = A.patch(B + "/api/admin/settings", json={"cal_allow_hosts": "evil.test:8095, other.lan"})
check(r.ok and r.json()["cal_allow_hosts"] == "evil.test:8095, other.lan" and r.json()["cal_allow_env"] == "127.0.0.1:8095",
      "allow-list saved, env list shown: " + r.text[:200])
r = Bo.post(B + "/api/calendars", json={"kind": "ics", "url": "http://evil.test:8095/good.ics"})
check(r.ok, "after the allow-list: bob can subscribe to evil.test:8095 " + r.text[:120])
bob_sub = r.json()["created"][0] if r.ok else 0
st_, c_, _ = add_err("http://evil.test:8096/secret", Bo)
check(c_ == "blocked", "allow-list entry host:port does not open other ports")
check(Bo.get(B + "/api/about").json().get("cal_allow_hosts") is None, "non-admins do not see the allow-list")

# ---- CalDAV
r = A.post(B + "/api/calendars/discover", json={"url": STUB + "/", "username": "alice", "password": "wrong"})
check(r.status_code == 400 and r.json().get("code") == "auth", "CalDAV: wrong password -> auth error")
r = A.post(B + "/api/calendars/discover", json={"url": STUB + "/", "username": "alice", "password": "secret-pw"})
check(r.ok, "CalDAV discovery via /.well-known/caldav: " + r.text[:200])
cals = r.json().get("calendars", []) if r.ok else []
check([c["name"] for c in cals] == ["Work"] and cals[0]["color"] == "#ff8800" and cals[0]["url"].endswith("/dav/calendars/alice/work/"),
      "only event calendars on the same origin (no VTODO list, no other host): " + str(cals))
check("secret-pw" not in r.text, "discovery answer has no password")
r = py_in_app("""try:
    app._dav_xml(b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><a>&e;</a>'); print('parsed')
except app.CalError as e:
    print(e.code)""")
check(r == "parse", "DTD / entity in a CalDAV answer refused: " + r)
r = A.post(B + "/api/calendars/discover", json={"url": STUB + "/dav/xxe/", "username": "alice", "password": "secret-pw"})
check("root:" not in r.text, "no file content through an XML entity")
r = A.post(B + "/api/calendars", json={"kind": "caldav", "url": STUB + "/", "username": "alice", "password": "secret-pw",
                                        "calendars": [{"url": "http://evil.test:8095/dav/calendars/alice/stolen/", "name": "x"}]})
check(r.status_code == 400, "CalDAV: a calendar URL on another origin is refused")
r = A.post(B + "/api/calendars", json={"kind": "caldav", "url": STUB + "/", "username": "alice", "password": "secret-pw", "calendars": cals})
check(r.ok, "CalDAV calendar added: " + r.text[:200])
dav = r.json()["created"][0] if r.ok else 0
dsub = next((x for x in r.json()["subs"] if x["id"] == dav), {}) if r.ok else {}
check(dsub.get("name") == "Work" and dsub.get("color") == "#ff8800" and dsub.get("password_saved") is True and dsub.get("username") == "alice",
      "CalDAV: name / colour from the server, password saved")
check("secret-pw" not in r.text and "secret-pw" not in A.get(B + "/api/calendars").text, "password never returned")
check("secret-pw" not in dbx("SELECT password FROM cal_subs WHERE id=?", (dav,))[0][0], "password stored encrypted")
de2 = [e for e in events(A)["events"] if e["sub"] == dav]
check(sorted(e["title"] for e in de2) == ["Gym week"] * 4 + ["Project review"], "CalDAV events expanded: " + str(sorted(e["title"] for e in de2)))
check(not [x for x in stub_log() if x["auth"] and (x["host"] or "").startswith("evil.test")], "credentials never sent to another host")
logs = subprocess.run(["docker", "logs", CT], capture_output=True, text=True)
check("secret-pw" not in logs.stdout + logs.stderr and "good.ics" not in logs.stdout + logs.stderr, "no secrets / links in the server log")

# ---- ctag: unchanged -> only PROPFIND; changed -> REPORT
def since(t):
    return [x for x in stub_log() if x["t"] >= t]


n0 = time.time()
dbx("UPDATE cal_subs SET tried_at='2000-01-01T00:00:00+00:00' WHERE id=?", (dav,))
for _ in range(40):
    if any(x["method"] == "PROPFIND" for x in since(n0)):
        break
    time.sleep(0.5)
time.sleep(1)
m = [x["method"] for x in since(n0) if x["path"].startswith("/dav/")]
check("PROPFIND" in m and "REPORT" not in m, "background sync, ctag unchanged: no REPORT " + str(m))
open(os.path.join(DATA, "ctag"), "w").write("ctag-2")
n0 = time.time()
dbx("UPDATE cal_subs SET tried_at='2000-01-01T00:00:00+00:00' WHERE id=?", (dav,))
for _ in range(40):
    if any(x["method"] == "REPORT" for x in since(n0)):
        break
    time.sleep(0.5)
check(any(x["method"] == "REPORT" for x in since(n0)), "ctag changed: events fetched again")

# ---- ETag / If-None-Match on the background sync of the ICS link
n0 = time.time()
dbx("UPDATE cal_subs SET tried_at='2000-01-01T00:00:00+00:00' WHERE id=?", (good,))
for _ in range(40):
    if any(x["path"] == "/good.ics" for x in since(n0)):
        break
    time.sleep(0.5)
hit = [x for x in since(n0) if x["path"] == "/good.ics"]
check(hit and (hit[0]["inm"] or "").startswith('"good-'), "background sync sends If-None-Match " + str(hit[:1]))
check(dbx("SELECT status FROM cal_subs WHERE id=?", (good,))[0][0] == "ok", "304 keeps the subscription ok")
check(len([e for e in events(A)["events"] if e["sub"] == good]) == len([e for e in ev if e["sub"] == good]), "304: events unchanged")

# ---- PATCH / visibility / version signature
sig0 = A.get(B + "/api/version").json()["c"]
r = A.patch(B + f"/api/calendars/{good}", json={"name": "Team", "color": "#2dd4bf", "visible": False, "interval": 60})
check(r.ok and r.json()["name"] == "Team" and r.json()["visible"] is False and r.json()["interval"] == 60, "PATCH name / colour / visible / interval")
check(A.get(B + "/api/version").json()["c"] != sig0, "/api/version signature changes")
check(not [e for e in events(A)["events"] if e["sub"] == good] and str(good) not in events(A)["subs"], "hidden calendar: no events")
check(A.get(B + "/api/state").json()["calendars"]["subs"] == 3, "state counts the visible subscriptions")
A.patch(B + f"/api/calendars/{good}", json={"visible": True})
for body in ({"color": "red"}, {"color": "#12345"}, {"interval": 30}, {"visible": "yes"}, {"name": ""}, {"name": 5}):
    check(A.patch(B + f"/api/calendars/{good}", json=body).status_code == 400, f"PATCH refuses {body}")
r = A.patch(B + f"/api/calendars/{dav}", json={"password": "wrong-now"})
check(r.ok and r.json()["status"] == "error" and r.json()["error"].startswith("auth"), "CalDAV: a wrong new password shows the auth error")
r = A.patch(B + f"/api/calendars/{dav}", json={"password": "secret-pw"})
check(r.ok and r.json()["status"] == "ok", "CalDAV: fixed again")

# ---- per-user isolation
check(Ca.get(B + "/api/calendars").json()["subs"] == [], "carol sees no subscriptions of others")
for method, path in (("PATCH", f"/api/calendars/{good}"), ("DELETE", f"/api/calendars/{good}"), ("POST", f"/api/calendars/{good}/refresh")):
    r = Ca.request(method, B + path, json={"name": "hijack"})
    check(r.status_code == 404, f"IDOR: carol {method} {path} -> {r.status_code}")
check(Ca.get(B + f"/api/calendars/events?from={T - timedelta(days=60)}&to={T + timedelta(days=300)}").json() == {"events": [], "subs": {}},
      "carol gets none of alice's events")
check(dbx("SELECT name FROM cal_subs WHERE id=?", (good,))[0][0] == "Team", "alice's subscription untouched")
check(sess().get(B + "/api/calendars").status_code == 401, "not logged in: 401")
check(requests.post(B + "/api/calendars", cookies=A.cookies, json={"kind": "ics", "url": STUB + "/good.ics"}).status_code == 403,
      "CSRF header needed")

# ---- failures -> admin alert (no content)
r = A.post(B + "/api/calendars", json={"kind": "ics", "url": STUB + "/flaky.ics", "name": "Flaky SECRET-NAME"})
fid = r.json()["created"][0]
open(os.path.join(DATA, "flaky"), "w").write("1")
for i in range(5):
    r = A.post(B + f"/api/calendars/{fid}/refresh")
check(r.ok and r.json()["status"] == "error" and r.json()["error"] == "http:500" and r.json()["fails"] == 5
      and "(500)" in r.json()["error_text"], "5 failed refreshes: status error http:500 " + r.text[:200])
for _ in range(30):
    al = [x for x in ntfy_log() if x["topic"] == admin_topic and f"#{fid}" in x.get("msg", "")]
    if al:
        break
    time.sleep(0.5)
check(al and "alice" in al[0]["msg"] and "5" in al[0]["msg"] and "http:500" in al[0]["msg"], "admin alert: id, user, count, error class " + str(al[:1]))
check(al and "SECRET-NAME" not in json.dumps(al) and "flaky" not in json.dumps(al).lower() and "127.0.0.1" not in json.dumps(al), "admin alert without name / link")
calhost_alert = [x for x in ntfy_log() if x["topic"] == admin_topic and "evil.test:8095" in x.get("msg", "")]
check(calhost_alert, "security alert when the allow-list changes")
os.remove(os.path.join(DATA, "flaky"))
r = A.post(B + f"/api/calendars/{fid}/refresh")
check(r.json()["status"] == "ok" and r.json()["fails"] == 0, "recovers after the server is fixed")

# ---- rate limits (bob: KALMIDO_CALENDAR_RATE=60 outbound actions per 15 min; three adds were used above)
codes = [Bo.post(B + f"/api/calendars/{bob_sub}/refresh").status_code for _ in range(60)]
check(codes.count(429) >= 2 and codes[0] == 200, f"manual refresh rate-limited per user ({codes.count(200)} ok, {codes.count(429)} x 429)")

# ---- settings, export, delete, cascade
check(A.patch(B + "/api/settings", json={"cal_today": "0"}).ok and A.get(B + "/api/state").json()["settings"]["cal_today"] == "0", "setting cal_today")
check(A.patch(B + "/api/settings", json={"cal_today": "maybe"}).status_code == 400, "cal_today validated")
A.patch(B + "/api/settings", json={"cal_today": "1"})
ex = A.get(B + "/api/export.json").json()
cs = ex.get("calendar_subscriptions", [])
check(len(cs) == 5 and all("url" not in x and "password" not in x for x in cs) and "secret-pw" not in json.dumps(ex), "export: subscriptions without secrets")
r = A.delete(B + f"/api/calendars/{fid}")
check(r.ok and fid not in [x["id"] for x in r.json()["subs"]] and dbx("SELECT COUNT(*) FROM cal_events WHERE sub_id=?", (fid,))[0][0] == 0,
      "delete removes the events too")
check(A.delete(B + f"/api/users/{ids['bob']}").ok, "bob deleted")
check(dbx("SELECT COUNT(*) FROM cal_subs WHERE user_id=?", (ids["bob"],))[0][0] == 0 and
      dbx("SELECT COUNT(*) FROM cal_events WHERE sub_id=?", (bob_sub,))[0][0] == 0, "user delete cascades to subscriptions + events")
check(A.post(B + "/api/calendars", json={"kind": "nope"}).status_code == 400, "unknown kind refused")
for i in range(21):
    r = Ca.post(B + "/api/calendars", json={"kind": "ics", "url": STUB + "/daily.ics"})
    if r.status_code != 200:
        break
check(r.status_code == 409 and len(Ca.get(B + "/api/calendars").json()["subs"]) == 20, f"at most 20 subscriptions per user ({r.status_code})")

json.dump({"good": good, "google": gid, "daily": did, "dav": dav}, open(os.path.join(N, "cal_ids.json"), "w"))
print(f"{OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
