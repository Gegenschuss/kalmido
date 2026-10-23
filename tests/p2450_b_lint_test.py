#!/usr/bin/env python3
"""2.45.0 part B (#1515): self-hosting files, checked without a container.
 - install.sh: POSIX syntax (sh -n), creates secret/, shows the setup code from the log, no fixed old version
 - install.ps1: parses (pwsh, when installed), the same steps
 - docker-compose.yml: loads, health check with python3 on /api/health, the server key file on its own volume (not ./data)
 - examples/: Caddy, nginx, Traefik templates with only example.com addresses and the long-polling / WebSocket note
 - .env.example + README: no active KALMIDO_SETUP_CODE, no v2.5.0, no SQLite "PRAGMA quick_check" left
usage: p2450_b_lint_test.py"""
import os
import re
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
from kt import FAILS, OKS, check  # 2.192.0 (#2514): shared helpers (tests/kt.py)


def read(*p):
    with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
        return f.read()


def load_yaml(text):
    """PyYAML when available (Compose tags !reset / !override accepted), else None."""
    try:
        import yaml
    except ImportError:
        return None

    class L(yaml.SafeLoader):
        pass
    for tag in ("!reset", "!override"):
        L.add_constructor(tag, lambda loader, node: loader.construct_sequence(node) if isinstance(node, yaml.SequenceNode)
                          else loader.construct_mapping(node) if isinstance(node, yaml.MappingNode) else loader.construct_scalar(node))
    return yaml.load(text, Loader=L)


# ---- install.sh
sh = read("install.sh")
r = subprocess.run(["sh", "-n", os.path.join(ROOT, "install.sh")], capture_output=True, text=True)
check(r.returncode == 0, f"install.sh: sh -n {r.stderr[:200]}")
check(sh.startswith("#!/bin/sh") and sh.rstrip().endswith('main "$@"'), "install.sh: sh script that only runs main at the very end")
check('mkdir -p "$DIR/data" "$DIR/secret"' in sh, "install.sh creates secret/ next to data/")
check("Setup code" in sh and "setup_code()" in sh, "install.sh shows the setup code from the log")
check("becomes the admin" in sh and "first account you create becomes the admin" not in sh, "install.sh: no 'first account becomes admin' without a code")
check(not re.search(r"v2\.5\.0|kalmido:2\.5\.0", sh), "install.sh: no fixed old version")
if shutil.which("shellcheck"):
    r = subprocess.run(["shellcheck", "-S", "error", os.path.join(ROOT, "install.sh")], capture_output=True, text=True)
    check(r.returncode == 0, f"install.sh: shellcheck errors {r.stdout[:300]}")

# ---- install.ps1
ps = read("install.ps1")
check("'secret'" in ps and "Setup code" in ps, "install.ps1 creates secret\\ and shows the setup code")
check(ps.count("{") == ps.count("}"), "install.ps1: braces balanced")
if shutil.which("pwsh"):
    cmd = ("$e = $null; [void][System.Management.Automation.Language.Parser]::ParseFile('%s', [ref]$null, [ref]$e); "
           "if ($e.Count) { $e | ForEach-Object { $_.Message }; exit 1 }" % os.path.join(ROOT, "install.ps1"))
    r = subprocess.run(["pwsh", "-NoProfile", "-Command", cmd], capture_output=True, text=True)
    check(r.returncode == 0, f"install.ps1 parses: {r.stdout[:300]}")

# ---- docker-compose.yml
dc = read("docker-compose.yml")
y = load_yaml(dc)
if y is not None:
    k = y["services"]["kalmido"]
    hc = k.get("healthcheck") or {}
    test = " ".join(hc.get("test") or [])
    check("python3" in test and "/api/health" in test and "curl" not in test, f"compose: health check with python3 on /api/health: {test}")
    check(hc.get("start_period") and hc.get("interval"), "compose: health check has interval + start_period")
    check("/secret/kalmido.key" in k["environment"].get("KALMIDO_SECRET_FILE", ""), "compose: KALMIDO_SECRET_FILE set")
    vols = k.get("volumes") or []
    check("./secret:/secret" in vols and "./data:/data" in vols, f"compose: ./secret on its own volume: {vols}")
    check(y["services"]["db"].get("healthcheck"), "compose: the db health check stays")
else:
    print("(PyYAML missing: docker-compose.yml checked as text)")
    check("/api/health" in dc and "python3" in dc and "./secret:/secret" in dc, "compose (text): health check + secret volume")
check("/data/" not in re.sub(r"#.*", "", dc).split("KALMIDO_SECRET_FILE", 1)[1].split("\n", 1)[0], "compose: the key file is not under /data")

# ---- examples
ex = os.path.join(ROOT, "examples")
for f in ("README.md", "Caddyfile", "nginx.conf", "traefik.docker-compose.override.yml"):
    p = os.path.join(ex, f)
    check(os.path.isfile(p), f"examples/{f} exists")
    if not os.path.isfile(p):
        continue
    t = read("examples", f)
    hosts = set(re.findall(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|de|io|example)\b", t, re.I))
    bad = {h for h in hosts if not h.lower().endswith(("example.com", ".example")) and h.lower() not in
           ("docker-compose.yml", "docker-compose.override.yml", "kalmido.conf", "nginx.conf")}
    check(not bad, f"examples/{f}: only example.com addresses ({sorted(bad)})")
    check("WebSocket" in t or f == "README.md" and "WebSockets" in t, f"examples/{f}: WebSocket note")
check("reverse_proxy 127.0.0.1:3040" in read("examples", "Caddyfile"), "Caddyfile proxies to 3040")
ng = read("examples", "nginx.conf")
check("proxy_read_timeout 120s" in ng and "X-Forwarded-Proto" in ng and "client_max_body_size" in ng, "nginx.conf: timeout, headers, body size")
tr = read("examples", "traefik.docker-compose.override.yml")
ty = load_yaml(tr)
if ty is not None:
    labels = ty["services"]["kalmido"]["labels"]
    check(any("loadbalancer.server.port=3040" in x for x in labels) and any("Host(`kalmido.example.com`)" in x for x in labels),
          "traefik override: router + port labels")

# ---- .env.example, README, start.sh
env = read(".env.example")
check(not re.search(r"^KALMIDO_SETUP_CODE=", env, re.M) and "#KALMIDO_SETUP_CODE=" in env, ".env.example: setup code only as a comment")
check("#KALMIDO_SECRET_FILE=/secret/kalmido.key" in env, ".env.example documents KALMIDO_SECRET_FILE")
check("kalmido:2.5.0" not in env, ".env.example: no fixed old image version")
rd = read("README.md")
check("v2.5.0" not in rd and "kalmido:2.5.0" not in rd, "README: no fixed v2.5.0 any more")
check("PRAGMA quick_check" not in rd, "README: no SQLite PRAGMA quick_check")
check("install.sh](install.sh)" in rd and "examples/" in read("docs", "SELF-HOSTING.md"), "README links the install script, SELF-HOSTING the examples")
check("## Requirements" in read("docs", "SELF-HOSTING.md") and "Raspberry" in rd, "requirements documented")
check('KALMIDO_SETUP_CODE="${KALMIDO_SETUP_CODE-off}"' in read("tests", "start.sh"), "tests/start.sh switches the setup code off")

print(f"p2450_b_lint: {OKS[0]} ok, {len(FAILS)} failed")
sys.exit(1 if FAILS else 0)
