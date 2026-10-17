"""2.59.0 (#1375): the real embedding service image (embed/Dockerfile) builds, runs WITHOUT network and answers like the stub.

Builds embed/ (downloads the pinned model once, SHA-256 checked), starts it with --network none, waits for /health, then
checks over `docker exec` (no published port): dimension 384, unit vectors, a paraphrase is closer than an unrelated text,
German and English of the same thing are close (multilingual), query and passage prefixes differ, the limits answer 400.
Removes its container and image at the end.
"""
import json
import math
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NAME = os.environ.get("KALMIDO_TEST_CONTAINER", "kalmido-test") + "-embed"
IMAGE = "kalmido-embed:" + NAME.replace("_", "-")
fails = 0


def check(ok, msg):
    global fails
    print(("ok   " if ok else "FAIL ") + msg)
    if not ok:
        fails += 1


def sh(*a, timeout=900):
    return subprocess.run(a, capture_output=True, text=True, timeout=timeout)


def call(path, body=None):
    """GET / POST inside the container (it has no network to the outside, not even a published port)."""
    code = ("import json,sys,urllib.request,urllib.error\n"
            "b=sys.argv[2]\n"
            "r=urllib.request.Request('http://127.0.0.1:8090'+sys.argv[1],data=b.encode() if b else None,"
            "headers={'Content-Type':'application/json'})\n"
            "try:\n s=urllib.request.urlopen(r,timeout=60);print(s.status);print(s.read().decode())\n"
            "except urllib.error.HTTPError as e:\n print(e.code);print(e.read().decode())\n")
    p = sh("docker", "exec", NAME, "python3", "-c", code, path, json.dumps(body) if body is not None else "", timeout=120)
    lines = p.stdout.split("\n", 1)
    try:
        return int(lines[0]), json.loads(lines[1]) if len(lines) > 1 and lines[1].strip() else None
    except ValueError:
        return 0, p.stdout + p.stderr


def cos(a, b):
    return sum(x * y for x, y in zip(a, b))


sh("docker", "rm", "-f", NAME)
t0 = time.time()
b = sh("docker", "build", "-q", "-t", IMAGE, os.path.join(ROOT, "embed"), timeout=1800)
check(b.returncode == 0, f"the embed image builds ({time.time() - t0:.0f} s) {b.stderr[-400:] if b.returncode else ''}")
if b.returncode:
    sys.exit(1)
r = sh("docker", "run", "-d", "--name", NAME, "--network", "none", IMAGE)
check(r.returncode == 0, "the container starts without network " + r.stderr[-200:])
try:
    st, h = 0, None
    for _ in range(90):
        st, h = call("/health")
        if st == 200:
            break
        time.sleep(2)
    check(st == 200 and h.get("ok") and h.get("dim") == 384 and h.get("model") == "multilingual-e5-small-int8", f"health: {st} {h}")
    texts = ["Invoice from parts: the rest cent goes to the last line",
             "Rechnung aus Teilen: der Rest-Cent landet auf der letzten Position",
             "Rounding of invoice totals when positions come from parts",
             "Water the plants on the balcony"]
    t1 = time.time()
    st, e = call("/embed", {"texts": texts, "kind": "passage"})
    ms = (time.time() - t1) * 1000 / len(texts)
    check(st == 200 and e["dim"] == 384 and len(e["vectors"]) == 4 and all(len(v) == 384 for v in e["vectors"]), f"embed: {st} dim/count")
    if st == 200:
        v = e["vectors"]
        check(all(abs(math.sqrt(cos(x, x)) - 1) < 1e-3 for x in v), "vectors are L2-normalised")
        check(cos(v[0], v[1]) > cos(v[0], v[3]) and cos(v[0], v[2]) > cos(v[0], v[3]),
              f"related texts closer than unrelated: de {cos(v[0], v[1]):.3f} para {cos(v[0], v[2]):.3f} other {cos(v[0], v[3]):.3f}")
        check(cos(v[0], v[1]) > 0.85, f"German and English of the same thing are close (multilingual): {cos(v[0], v[1]):.3f}")
        print(f"info {ms:.0f} ms per text (incl. docker exec)")
        st, q = call("/embed", {"texts": texts[:1], "kind": "query"})
        check(st == 200 and 0.8 < cos(q["vectors"][0], v[0]) < 0.9999, f"query prefix differs from passage: {st}")
    st, _ = call("/embed", {"texts": ["x"] * 65, "kind": "passage"})
    check(st == 400, f"more than 64 texts: 400 ({st})")
    st, _ = call("/embed", {"texts": "no list"})
    check(st == 400, f"texts not a list: 400 ({st})")
    lg = sh("docker", "logs", NAME)
    check("Rest-Cent" not in lg.stdout + lg.stderr and "balcony" not in lg.stdout + lg.stderr, "no text in the log")
    u = sh("docker", "exec", NAME, "id", "-u")
    check(u.stdout.strip() not in ("", "0"), f"runs as non-root ({u.stdout.strip()})")
finally:
    sh("docker", "rm", "-f", NAME)
    sh("docker", "rmi", IMAGE)
print(f"{'PASSED' if not fails else 'FAILED'}: p259_b_embed ({fails} failures)")
sys.exit(1 if fails else 0)
