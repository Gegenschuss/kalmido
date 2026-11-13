#!/usr/bin/env python3
"""2.1092.0 (#5948): the PostgreSQL version of Kalmido stands in ONE place - the image line of the "db" service in
docker-compose.yml (postgres:<major>.<minor>, e.g. postgres:17.12). Everything else reads it from there:
the CI (.github/workflows/ci.yml), the test start (tests/start.sh), the test helpers (tests/p2521_e_dbmem_test.py) and with
them the Mac run. Places that cannot read a file at run time (the Dockerfile's ARG PG_VERSION, the uninstall text of
install.sh / install.ps1, the docs) carry the same text; --check keeps them equal.

Why: "postgres:17" is a moving tag. On 12.11.2026 it moved to 17.12 while the app image still had pg_dump 17.11 from
Debian; the CI pulled the new image, the Mac still had the old one, so backups were red in the CI only (2.1077.0, job 4320).
A version update is now a deliberate commit: python3 tools/pg_image.py --set 17.13 (then build and test).
The app image installs pg_dump / pg_restore from the PostgreSQL project's own packages (PGDG) and stops the build when
that pg_dump is older than PG_VERSION (Dockerfile), so pg_dump is never older than the server.

usage: pg_image.py            -> postgres:17.12   (the image)
       pg_image.py --version  -> 17.12
       pg_image.py --major    -> 17
       pg_image.py --check [-v]   lint: no bare postgres:<major> anywhere, every postgres:<x.y> and the Dockerfile's
                                  ARG PG_VERSION equal to docker-compose.yml (exit 1 with the places)
       pg_image.py --set X.Y      write the new version into every place (docker-compose.yml first)
Standard library only."""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE = "docker-compose.yml"
# the image line of the db service: "    image: postgres:17.12" right below "  db:" (comments in between are allowed)
_DB_IMAGE = re.compile(r"^  db:\n(?:    #.*\n)*    image: (postgres:\S+)[ \t]*$", re.M)
_FULL = re.compile(r"^postgres:(\d{2,3})\.(\d{1,3})$")
# any postgres:<digits> tag in a text; group 2 = the minor part (None = a bare major tag such as postgres:17)
_ANY = re.compile(r"(?<![\w/.-])postgres:(\d{1,3})(\.\d{1,3})?(?![\w.-]*\w)")
_ARG = re.compile(r"^ARG PG_VERSION=(\S*)[ \t]*$", re.M)
# history is history: the changelogs keep the tags of their time (postgres:17 in 2.37.0 was right then).
# README.md is written by the live train only (jobs never change it); its uninstall line follows with the next train.
SKIP = ("CHANGELOG.md", "README.md", "docs/changelog/", "changelog.d/", "tools/pg_image.py", "tests/p5948_pg_image_test.py")
_TEXT = (".py", ".sh", ".ps1", ".yml", ".yaml", ".md", ".txt", ".json", ".env", ".example", ".toml", ".cfg", "Dockerfile")


def image(root=ROOT):
    """postgres:<major>.<minor> from docker-compose.yml; ValueError when the line is missing or not pinned to a minor."""
    with open(os.path.join(root, COMPOSE), encoding="utf-8") as f:
        m = _DB_IMAGE.search(f.read())
    if not m:
        raise ValueError(f"{COMPOSE}: no 'image: postgres:...' line in the db service")
    if not _FULL.match(m.group(1)):
        raise ValueError(f"{COMPOSE}: db image {m.group(1)} is not pinned to a minor version (postgres:<major>.<minor>, #5948)")
    return m.group(1)


def version(root=ROOT):
    return image(root).split(":", 1)[1]


def major(root=ROOT):
    return version(root).split(".", 1)[0]


def _files(root):
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=root, capture_output=True, text=True, check=True).stdout
        names = [n for n in out.split("\0") if n]
    except (OSError, subprocess.CalledProcessError):  # no git (a source archive): walk the tree
        names = [os.path.relpath(os.path.join(d, n), root) for d, ds, ns in os.walk(root)
                 for n in ns if ".git" not in d.split(os.sep)]
    return sorted(n for n in names if not n.startswith(SKIP) and (n.endswith(_TEXT) or os.path.basename(n) == "Dockerfile"))


def problems(root=ROOT):
    """[(file, line, text)] - every place that does not follow docker-compose.yml."""
    try:
        img = image(root)
    except (OSError, ValueError) as e:
        return [(COMPOSE, 0, str(e))]
    want = img.split(":", 1)[1]
    out = []
    for rel in _files(root):
        try:
            with open(os.path.join(root, rel), encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        for no, ln in enumerate(text.splitlines(), 1):
            for m in _ANY.finditer(ln):
                got = m.group(1) + (m.group(2) or "")
                if not m.group(2):
                    out.append((rel, no, f"bare {m.group(0)} - a moving tag; write {img} (or 'the postgres image' in prose)"))
                elif got != want:
                    out.append((rel, no, f"{m.group(0)} differs from {COMPOSE} ({img})"))
    try:
        with open(os.path.join(root, "Dockerfile"), encoding="utf-8") as f:
            args = _ARG.findall(f.read())
        if args != [want]:
            out.append(("Dockerfile", 0, f"needs exactly one 'ARG PG_VERSION={want}' (found {args or 'none'})"))
    except OSError:
        out.append(("Dockerfile", 0, "missing"))
    return out


def set_version(new, root=ROOT):
    """Write NEW (e.g. 17.13) into docker-compose.yml, the Dockerfile and every postgres:<x.y> of the checked files."""
    if not _FULL.match("postgres:" + new):
        raise ValueError(f"{new}: give <major>.<minor>, e.g. 17.13")
    old = version(root)
    changed = []
    for rel in _files(root) + ["Dockerfile"]:
        p = os.path.join(root, rel)
        try:
            with open(p, encoding="utf-8") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError):
            continue
        nt = re.sub(rf"(?<![\w/.-])postgres:{re.escape(old)}(?![\w.-]*\w)", "postgres:" + new, text)
        if rel == "Dockerfile":
            nt = _ARG.sub("ARG PG_VERSION=" + new, nt)
        if nt != text and rel not in changed:
            with open(p, "w", encoding="utf-8") as f:
                f.write(nt)
            changed.append(rel)
    return old, changed


def main(argv):
    if not argv:
        print(image())
    elif argv[0] == "--version":
        print(version())
    elif argv[0] == "--major":
        print(major())
    elif argv[0] == "--check":
        found = problems()
        for rel, no, msg in found:
            print(f"{rel}:{no}: {msg}")
        if found:
            print(f"pg_image: {len(found)} place(s) do not follow {COMPOSE} - the PostgreSQL version stands in one place (#5948);"
                  " change it with python3 tools/pg_image.py --set X.Y", file=sys.stderr)
            return 1
        if "-v" in argv:
            print(f"pg_image: {image()} everywhere (docker-compose.yml, Dockerfile, CI, tests, installer, docs)")
    elif argv[0] == "--set" and len(argv) == 2:
        old, changed = set_version(argv[1])
        print(f"pg_image: {old} -> {argv[1]} in " + (", ".join(changed) or "nothing"))
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except ValueError as e:
        print(f"pg_image: {e}", file=sys.stderr)
        sys.exit(1)
