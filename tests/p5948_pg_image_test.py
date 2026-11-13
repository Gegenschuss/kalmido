#!/usr/bin/env python3
# kalmido-suite: nodata
"""2.1092.0 (#5948): the PostgreSQL version stands in ONE place (docker-compose.yml, db image postgres:<major>.<minor>) and
tools/pg_image.py keeps everything else equal. The moving tag postgres:17 moved to 17.12 on 12.11.2026 while the app image
had pg_dump 17.11: the CI pulled the new database, the Mac kept the old one, backups were red in the CI only (2.1077.0).
 1. the real tree: compose pinned to a minor version, --check green, Dockerfile ARG PG_VERSION equal, every reader reads it
    (CI step, tests/start.sh, tests/p2521_e_dbmem_test.py) and none of them names a postgres image tag of its own
 2. a bare postgres:17 anywhere (a script, a doc) is red with file and line (without the fix nothing looked)
 3. another minor version than compose (postgres:17.11 in a test) is red
 4. Dockerfile ARG PG_VERSION different from compose is red; a compose with the bare major tag is red
 5. --set X.Y moves compose, Dockerfile and the other places together, --check is green afterwards; changelogs stay
 6. the Dockerfile stops the build when pg_dump is older than PG_VERSION (dpkg --compare-versions ... ge)
Temporary trees only, standard library only. usage: python3 tests/p5948_pg_image_test.py"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from kt import check, done  # noqa: E402

TOOL = os.path.join(ROOT, "tools", "pg_image.py")


def tool(*args, cwd=None):
    r = subprocess.run([sys.executable, os.path.join(cwd, "tools", "pg_image.py") if cwd else TOOL, *args],
                       capture_output=True, text=True, timeout=60)
    return r.returncode, r.stdout + r.stderr


def read(rel, root=ROOT):
    with open(os.path.join(root, rel), encoding="utf-8") as f:
        return f.read()


def tree(files):
    """A small checkout without git: tools/pg_image.py + FILES {rel: text}."""
    d = tempfile.mkdtemp(prefix="p5948-")
    os.makedirs(os.path.join(d, "tools"))
    shutil.copy(TOOL, os.path.join(d, "tools", "pg_image.py"))
    for rel, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(d, rel)), exist_ok=True)
        with open(os.path.join(d, rel), "w", encoding="utf-8") as f:
            f.write(text)
    return d


COMPOSE = "services:\n  db:\n    # the database\n    image: postgres:{v}\n    restart: unless-stopped\n"
DOCKER = "FROM python:3.12-slim\nARG PG_VERSION={v}\nRUN apt-get install postgresql-client-${{PG_VERSION%%.*}}\n"
GOOD = {"docker-compose.yml": COMPOSE.format(v="17.12"), "Dockerfile": DOCKER.format(v="17.12"),
        "install.sh": 'say "docker image rm kalmido postgres:17.12 clamav/clamav:1.4"\n',
        "CHANGELOG.md": "- 2.37.0: the db service runs postgres:17\n"}

# 1. the real tree
rc, out = tool()
img = out.strip()
check(rc == 0 and re.fullmatch(r"postgres:\d{2,3}\.\d{1,3}", img), f"1: docker-compose.yml pins a minor version ({out!r})")
rc, out = tool("--check", "-v")
check(rc == 0, f"1: --check is green on this tree ({out[-400:]!r})")
ver = img.split(":", 1)[1]
check(f"\nARG PG_VERSION={ver}\n" in read("Dockerfile"), f"1: Dockerfile ARG PG_VERSION={ver}")
check('dpkg --compare-versions "$have" ge "$PG_VERSION"' in read("Dockerfile"), "6: the build stops when pg_dump is older than PG_VERSION")
check("apt.postgresql.org" in read("Dockerfile") and "postgresql-client-${PG_VERSION%%.*}" in read("Dockerfile"),
      "6: the client comes from PGDG with the major of PG_VERSION")
check("COPY tools/pgdg-ACCC4CF8.asc /etc/apt/keyrings/pgdg.asc" in read("Dockerfile")
      and read(os.path.join("tools", "pgdg-ACCC4CF8.asc")).startswith("-----BEGIN PGP PUBLIC KEY BLOCK-----"),
      "6: the PGDG signing key comes from the repository, not from a download at build time")
ci = read(os.path.join(".github", "workflows", "ci.yml"))
check('PG_IMAGE="$(python3 tools/pg_image.py)"' in ci and '"$PG_IMAGE" -c max_connections' in ci, "1: the CI's ZAP database reads tools/pg_image.py")
check("python tools/pg_image.py --check" in ci, "1: the lint job runs pg_image.py --check")
check('"$(python3 "$HERE/../tools/pg_image.py")"' in read(os.path.join("tests", "start.sh")), "1: tests/start.sh reads tools/pg_image.py")
check("PG_IMAGE, *ARGS" in read(os.path.join("tests", "p2521_e_dbmem_test.py")), "1: the memory suite starts the pinned image")
for rel in (os.path.join(".github", "workflows", "ci.yml"), os.path.join("tests", "start.sh"), os.path.join("tests", "p2521_e_dbmem_test.py")):
    check(not re.search(r"postgres:\d", read(rel)), f"1: {rel} names no postgres tag of its own")

# 2. a bare major tag is red, with the place
d = tree(dict(GOOD, **{"tests/start.sh": "docker run -d --name db postgres:17 -c fsync=off\n",
                       "docs/SELF-HOSTING.md": "The service `db` runs `postgres:17`.\n"}))
rc, out = tool("--check", cwd=d)
check(rc == 1 and "tests/start.sh:1: bare postgres:17" in out and "docs/SELF-HOSTING.md:1: bare postgres:17" in out,
      f"2: bare postgres:17 is red with file and line ({out!r})")
check("CHANGELOG.md" not in out, f"2: the changelog keeps its history ({out!r})")
shutil.rmtree(d)

# 3. another minor version
d = tree(dict(GOOD, **{"tests/p_x_test.py": 'IMG = "postgres:17.11"\n'}))
rc, out = tool("--check", cwd=d)
check(rc == 1 and "tests/p_x_test.py:1: postgres:17.11 differs" in out, f"3: postgres:17.11 against compose 17.12 is red ({out!r})")
shutil.rmtree(d)

# 4. Dockerfile and compose
d = tree(dict(GOOD, Dockerfile=DOCKER.format(v="17.11")))
rc, out = tool("--check", cwd=d)
check(rc == 1 and "ARG PG_VERSION=17.12" in out, f"4: Dockerfile PG_VERSION 17.11 against compose 17.12 is red ({out!r})")
shutil.rmtree(d)
d = tree(dict(GOOD, **{"docker-compose.yml": COMPOSE.format(v="17")}))
rc, out = tool("--check", cwd=d)
check(rc == 1 and "not pinned to a minor version" in out, f"4: compose with postgres:17 is red ({out!r})")
rc, out = tool(cwd=d)
check(rc == 1, f"4: the readers get no image from an unpinned compose (exit {rc})")
shutil.rmtree(d)
d = tree(dict(GOOD))
rc, out = tool("--check", cwd=d)
check(rc == 0, f"4: the small good tree is green ({out!r})")

# 5. --set moves everything together
rc, out = tool("--set", "17.13", cwd=d)
check(rc == 0, f"5: --set 17.13 ({out!r})")
check("image: postgres:17.13" in read("docker-compose.yml", d) and "ARG PG_VERSION=17.13" in read("Dockerfile", d)
      and "postgres:17.13 clamav" in read("install.sh", d), "5: compose, Dockerfile and installer moved to 17.13")
check("postgres:17\n" in read("CHANGELOG.md", d), "5: the changelog is not rewritten")
rc, out = tool("--check", cwd=d)
check(rc == 0, f"5: --check green after --set ({out!r})")
rc, out = tool("--set", "17", cwd=d)
check(rc != 0 and "image: postgres:17.13" in read("docker-compose.yml", d), f"5: --set 17 (no minor) is refused ({out!r})")
shutil.rmtree(d)

sys.exit(done("p5948_pg_image"))
