#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.539.0 D (#4379, #4381) API tests: a total time limit for the deliveries to outside servers, the sender check of
incoming mails without KALMIDO_MAIL_AUTHSERV_ID. Own container (start.sh). Invented addresses (example.com / .test) only.
freelancer-matrix: own
 - #4379 (audit #2483 M1): a server inside the container that answers drop by drop (a byte every 0.3 s, far below the
   socket timeouts of 8 / 10 / 20 s) ends at the total limit (CAL_SEND_S, shortened to 2 s here) with "timeout", for
   all four deliveries: a webhook POST (headers dripping and body dripping), a notification channel (Slack-style
   webhook), a git API call (git_http), a newsletter API call (listmonk check); also cal_http(until) after its watchdog
   moved into cal_until; a fast server still answers (webhook ok), no watchdog stays registered
 - #4379: the webhook tick tries a webhook that timed out only once per tick (its other deliveries wait unchanged);
   the channel tick likewise (the other messages go back into the queue, one failure counted) - both set up by a
   person without an organisation (personal webhook / channel)
 - #4381 (audit #2483 M2): hub/hubmail.py hbm_from_verified never confirms without KALMIDO_MAIL_AUTHSERV_ID (even a
   dkim=pass on top); with it only that server's header counts (another server's pass, a failing own header = no)
   (the mail replies of a task: tests/p2393_2_b_api_test.py, the hub's filing: tests/p284_a_api_test.py)
usage: p2539_d_api_test.py <datadir>"""
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from freelancer_fixture import freelancer  # noqa: E402
import kt  # noqa: E402
from kt import B, CT, check, done  # noqa: E402

HOOK = "http://127.0.0.1:8099"
kt.fresh({"KALMIDO_WEBHOOK_ALLOW_HOSTS": "127.0.0.1:8099", "KALMIDO_WEBHOOK_TICK": "3600", "KALMIDO_CHANNEL_TICK": "3600"})
A = kt.setup()
FU, Fr = freelancer(B, A, "fenja")  # the person without an organisation: her own webhook and channel


def py(code):
    """Runs code inside the test container (the app's modules importable); -> the last JSON line it printed."""
    r = subprocess.run(["docker", "exec", "-i", CT, "python", "-c", code], capture_output=True, text=True, timeout=300)
    if r.returncode:
        print("PY FAILED:", r.stdout[-2000:], r.stderr[-3000:], flush=True)
    for ln in reversed((r.stdout or "").splitlines()):
        if ln.startswith("{"):
            return json.loads(ln)
    return {}


# ---------------------------------------------------------------- 1. #4379: a dripping server ends at the total limit
DRIP = r"""
import http.server, json, threading, time, app
from kalmido.calendars import subscriptions as S
from kalmido.integrations import webhooks as WH, git as G
from kalmido.notify import channels as CH
from kalmido.newsletter.adapters import nwl_adapter, NwlError
S.CAL_SEND_S = WH.CAL_SEND_S = G.CAL_SEND_S = 2
class Drip(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a):
        pass
    def answer(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        try:
            if self.path.startswith("/ok"):
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nContent-Type: application/json\r\n\r\n{}")
                return
            if self.path.startswith("/body"):  # headers at once, then the body drop by drop
                self.wfile.write(b"HTTP/1.1 200 OK\r\nContent-Length: 5000\r\nContent-Type: application/json\r\n\r\n")
            else:  # the status line, then a header drop by drop
                self.wfile.write(b"HTTP/1.1 200 OK\r\nX-Slow: ")
            self.wfile.flush()
            for _ in range(100):  # 30 s
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.3)
        except OSError:
            pass
    do_GET = do_POST = answer
srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Drip)
srv.daemon_threads = True
PORT = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
U = f"http://127.0.0.1:{PORT}"
AL = frozenset({("127.0.0.1", PORT)})
out = {}
def run(k, fn):
    t0 = time.monotonic()
    try:
        out[k] = fn()
    except (S.CalError, NwlError) as e:
        out[k] = e.code
    out[k + "_s"] = round(time.monotonic() - t0, 1)
run("wh_head", lambda: WH._wh_post(U + "/head", "s3cret", "ping", "d1", 1, b"{}", AL)[3])
run("wh_body", lambda: WH._wh_post(U + "/body", "s3cret", "ping", "d2", 1, b"{}", AL)[3])
run("wh_ok", lambda: list(WH._wh_post(U + "/ok", "s3cret", "ping", "d3", 1, b"{}", AL)[:2]))
run("chn", lambda: CH.chn_send("slack", {"url": U + "/head"}, "Hello", AL)[2])
run("git", lambda: G.git_http({"provider": "github", "token": "t0ken", "api": U, "allow": AL}, "/repos/a/b")[0])
run("nwl", lambda: nwl_adapter("listmonk", U, {"user": "u", "token": "t"}, AL).check())
run("cal", lambda: S.cal_http(U + "/head", allow=AL, until=time.monotonic() + 2)[0])
out["stack"] = getattr(S._CAL_WATCH, "stack", None) or []
print(json.dumps(out))
"""
j = py(DRIP)
for k, what in (("wh_head", "webhook, headers dripping"), ("wh_body", "webhook, body dripping"), ("chn", "notification channel"),
                ("git", "git API call"), ("nwl", "newsletter API call"), ("cal", "cal_http(until) after the move into cal_until")):
    check(j.get(k) == "timeout" and j.get(k + "_s", 99) < 6,
          f"#4379: {what}: ends at the total limit of 2 s ({j.get(k)}, {j.get(k + '_s')} s)")
check(j.get("wh_ok") == [True, 200] and j.get("wh_ok_s", 99) < 2, f"#4379: a fast server still answers ({j.get('wh_ok')}, {j.get('wh_ok_s')} s)")
check(j.get("stack") == [], f"#4379: no watchdog stays registered ({j.get('stack')})")

# ---------------------------------------------------------------- 2. #4379: one slow target per tick, the others go on
r = Fr.post(B + "/api/me/webhooks", json={"name": "Slow", "url": HOOK + "/slow", "events": ["task.created"]})
check(r.status_code in (200, 201), f"the freelancer's webhook {r.status_code} {r.text[:200]}")
WID = (r.json() or {}).get("id") if r.ok else 0
r = Fr.post(B + "/api/me/channels", json={"kind": "slack", "name": "Slow", "url": HOOK + "/chn"})
check(r.status_code in (200, 201), f"the freelancer's channel {r.status_code} {r.text[:200]}")
CID = (r.json() or {}).get("id") if r.ok else 0
for i in range(3):
    Fr.post(B + "/api/tasks", json={"title": f"Fence {i}"})
TICK = r"""
import json, app
from kalmido.core.db import connect
from kalmido.core.pg import system_ctx
from kalmido.integrations import webhooks as WH
from kalmido.notify import channels as CH
WID, CID = %d, %d
out = {}
c = connect()
with system_ctx(c):
    out["queued"] = c.execute("SELECT COUNT(*) FROM webhook_queue WHERE webhook_id=?", (WID,)).fetchone()[0]
    c.execute("DELETE FROM notify_channel_queue WHERE channel_id=?", (CID,))
    for i in range(3):
        CH.chn_enqueue(c, CID, f"Message {i}")
c.commit()
calls = []
WH.wh_send = lambda url, *a: calls.append(("wh", url)) or (False, None, 2000, "timeout")
CH.chn_send = lambda kind, t, text, allow: calls.append(("chn", text)) or (False, None, "timeout")
WH.wh_tick()
CH.chn_tick()
out["calls"] = calls
with system_ctx(c):
    out["wh_rows"] = sorted(r[0] for r in c.execute("SELECT attempt FROM webhook_queue WHERE webhook_id=?", (WID,)))
    out["chn_rows"] = sorted((r[0], r[1] > 0) for r in c.execute("SELECT text, retry_at FROM notify_channel_queue WHERE channel_id=?", (CID,)))
    out["chn_fails"] = c.execute("SELECT fails FROM notify_channels WHERE id=?", (CID,)).fetchone()[0]
c.close()
print(json.dumps(out))
"""
j = py(TICK % (int(WID or 0), int(CID or 0)))
wh = [x for x in j.get("calls") or [] if x[0] == "wh"]
ch = [x for x in j.get("calls") or [] if x[0] == "chn"]
check(j.get("queued") == 3, f"three deliveries wait for the webhook ({j.get('queued')})")
check(len(wh) == 1 and j.get("wh_rows") == [0, 0, 1],
      f"#4379: a webhook that timed out is tried once per tick, its other deliveries wait unchanged ({wh}, {j.get('wh_rows')})")
check(len(ch) == 1 and j.get("chn_rows") == [["Message 0", True], ["Message 1", False], ["Message 2", False]] and j.get("chn_fails") == 1,
      f"#4379: a channel that timed out is tried once per tick, the other messages back in the queue, one failure "
      f"({ch}, {j.get('chn_rows')}, fails {j.get('chn_fails')})")

# ---------------------------------------------------------------- 3. #4381: no AUTHSERV name = never confirmed
AUTH = r"""
import email.message, json, app
from kalmido.hub import hubmail as HM
def m(*auth):
    x = email.message.EmailMessage()
    for a in auth:
        x["Authentication-Results"] = a
    x["From"] = "bea@example.com"
    return x
OWN = "mx.example.test; dkim=pass header.d=example.com; spf=pass smtp.mailfrom=bea@example.com"
out = {}
HM.HBM_AUTHSERV = ""
out["unset"] = [HM.hbm_from_verified(m(OWN), "bea@example.com"), HM.hbm_from_verified(m("evil.example; dmarc=pass header.from=example.com"), "bea@example.com")]
HM.HBM_AUTHSERV = "mx.example.test"
out["set"] = [HM.hbm_from_verified(m(OWN), "bea@example.com"),
              HM.hbm_from_verified(m("evil.example; dkim=pass header.d=example.com"), "bea@example.com"),
              HM.hbm_from_verified(m("mx.example.test; dkim=fail header.d=example.com", OWN), "bea@example.com"),
              HM.hbm_from_verified(m(OWN), "bea@other.example")]
print(json.dumps(out))
"""
j = py(AUTH)
check(j.get("unset") == [False, False], f"#4381: without KALMIDO_MAIL_AUTHSERV_ID nothing is confirmed, not even a pass on top ({j.get('unset')})")
check(j.get("set") == [True, False, False, False],
      f"#4381: with it only that server's pass for the domain counts (own pass / other server / own fails / other domain: {j.get('set')})")

sys.exit(done("p2539_d_api"))
