#!/usr/bin/env python3
# kalmido-suite: fresh
"""2.519.0 B (#4378): an incoming mail can no longer hold the mail poll and the background gate.
 - mail_text of an HTML-only mail with 100.000 <script> without an end tag, one with 1 MB of "<" and one of 5 MB HTML ends
   fast (under 2 s each) and still gives the mail's text (the HTML part is cut to MAIL_HTML_MAX before its tags go)
 - a normal HTML mail with <script> / <style> / <br> / </p> gives the same text as the regexes before 2.519.0
 - mail_fetch marks a mail \\Seen before its import runs: one whose import is cut off does not come back in every round
Runs the functions inside the test container (fake IMAP object, no mail server).
usage: p2519_b_mail_regex_test.py <datadir>"""
import json
import os
import subprocess
import sys

N = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, N)
from kt import CT, check, done  # noqa: E402


def py(code, limit=60):
    """code in the container, killed there after limit seconds (the regexes before 2.519.0 ran for minutes)."""
    try:
        r = subprocess.run(["docker", "exec", "-i", CT, "timeout", str(limit), "python", "-c", code], capture_output=True, text=True,
                           timeout=limit + 30)
    except subprocess.TimeoutExpired:
        return {}
    if r.returncode:
        print("PY FAILED:", r.returncode, r.stdout[-2000:], r.stderr[-3000:], flush=True)
    for ln in reversed((r.stdout or "").splitlines()):
        if ln.startswith("{"):
            return json.loads(ln)
    return {}


# ---- 1. hostile HTML parts: fast, the text survives
SLOW = """
import json, time, app
from email.message import EmailMessage
from kalmido.integrations import mail as M
def msg(h):
    m = EmailMessage(); m["From"] = "x@example.com"; m["Subject"] = "s"; m.set_content(h, subtype="html"); return m
out = {}
for name, h in (("scripts", "<p>Hallo Welt</p>" + "<script>" * 100000 + "<b>Ende</b>"),
                ("styles", "<p>Hallo Welt</p>" + "<style a=1>" * 100000),
                ("lt", "<p>Hallo Welt</p>" + "<" * 1000000),
                ("big", "<p>Hallo Welt</p>" + "<div>abc</div>" * 400000)):
    t = time.monotonic()
    text, files = M.mail_text(msg(h))
    out[name] = [round(time.monotonic() - t, 2), text[:40], len(text)]
out["max"] = M.MAIL_HTML_MAX
out["cut"] = len(M.mail_html_plain("a" * (M.MAIL_HTML_MAX + 5000)))
print(json.dumps(out))
"""
j = py(SLOW)
for k in ("scripts", "styles", "lt", "big"):
    v = j.get(k) or [99, "", 0]
    check(v[0] < 2 and v[1].startswith("Hallo Welt"), f"hostile HTML ({k}) ends fast with the text {v}")
check(j.get("cut") == j.get("max") == 2 * 1024 * 1024, f"a large HTML part is cut to MAIL_HTML_MAX (2 MB) first {j.get('cut')} {j.get('max')}")

# ---- 2. normal HTML: the same text as the regexes before 2.519.0
SAME = r"""
import html, json, re, app
from email.message import EmailMessage
from kalmido.integrations import mail as M
def old(h):  # mail_text's HTML branch up to 2.518
    t = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", h)
    t = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</h\d>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    return html.unescape(t)
docs = [
    "<html><head><style type='text/css'>p {color: red}</style><script>var a = '<b>';</script></head>"
    "<body><h1>Termin</h1><p>Hallo Anna,<br>am Freitag um 10 Uhr.<BR/>Gruss</p><ul><li>eins</li><li>zwei</li></ul>"
    "<div>A &amp; B &lt;3</div><SCRIPT src='x.js'></SCRIPT><p>Ende</p></body></html>",
    "<p>a</p><style>x</style><style>y</style><p>b</p><script>1</script>c",
    "<p>ohne Ende <script>alert(1)",
    "Text a < b und c > d <> e",
    "<table><tr><td>1</td><td>2</td></tr></table><h3>Kopf</h3>Rest",
]
out = []
for h in docs:
    m = EmailMessage(); m["From"] = "x@example.com"; m["Subject"] = "s"; m.set_content(h, subtype="html")
    want = re.sub(r"\n{3,}", "\n\n", old(m.get_content()).replace("\r\n", "\n")).strip()
    out.append([M.mail_text(m)[0] == want, html.unescape(M.mail_html_plain(h)) == old(h)])
print(json.dumps({"same": out}))
"""
j = py(SAME)
check(len(j.get("same") or []) == 5 and all(a and b for a, b in j["same"]), f"normal HTML mails give the text as before {j}")

# ---- 3. mail_fetch: \\Seen before the import
SEEN = """
import json, app
from kalmido.integrations import mail as M
ev = []
class FakeIMAP:
    def read(self, n): return b""
    def select(self, folder): return "OK", [b"2"]
    def uid(self, cmd, *a):
        if cmd == "SEARCH": return "OK", [b"5 6"]
        if cmd == "FETCH":
            if "SIZE" in a[1]: return "OK", [b"1 (UID %s RFC822.SIZE 100)" % a[0]]
            return "OK", [(b"1 (UID %s RFC822 {5}" % a[0], b"mail" + a[0]), b")"]
        if cmd == "STORE": ev.append(["store", a[0].decode(), a[2]])
        return "OK", []
def importer(c, raw):
    ev.append(["import", raw[4:].decode()])
    if raw == b"mail6": raise RuntimeError("cut off")
    return 1
n = M.mail_fetch(FakeIMAP(), "INBOX", importer)
print(json.dumps({"n": n, "ev": ev}))
"""
j = py(SEEN)
ev = j.get("ev") or []


def first(kind, u):
    return next((i for i, e in enumerate(ev) if e[0] == kind and e[1] == u), None)


check(j.get("n") == 1 and all(first("store", u) is not None and first("import", u) is not None and first("store", u) < first("import", u)
                              for u in ("5", "6")), f"mail_fetch: each mail is marked seen before its import runs {j}")
check(all(e[2] == "(\\Seen)" for e in ev if e[0] == "store"), f"mail_fetch: only \\Seen (no delete without the switch) {ev}")

sys.exit(done("p2519_b_mail_regex"))
