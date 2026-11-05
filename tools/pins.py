#!/usr/bin/env python3
"""The pinned dependencies stay pinned (2.360.3, #2915).

    python3 tools/pins.py            offline: exit 1 when a build pin is missing (CI lint, no network)
    python3 tools/pins.py --osv      + pdf.js, mermaid, katex and the DOMPurify inside mermaid.min.js against the OSV database
                                     (exit 1 on a known hole, except those listed with a reason in tools/pins_osv_ignore.json)
    python3 tools/pins.py --update   rewrites the digests of the base images to what their tags point at today

Checked offline: every FROM of Dockerfile and embed/Dockerfile carries @sha256, both install only with --require-hashes from
their lock file, every package of the lock files has a version and hashes, the CI tools carry ==, the version of the bundled
pdf.js matches its README and THIRD_PARTY_NOTICES.md. Standard library only (the CI lint job runs plain Python).
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FILES = ("Dockerfile", "embed/Dockerfile")
LOCKS = {"Dockerfile": "tools/requirements.lock", "embed/Dockerfile": "embed/requirements.lock"}
STATIC_LOCK = "tools/requirements.static.lock"  # the build stage staticpack of Dockerfile
FROM_RE = re.compile(r"^FROM\s+(?:--platform=\S+\s+)?(\S+)", re.M)
IMAGE_RE = re.compile(r"^([a-z0-9._/-]+):([A-Za-z0-9._-]+)@(sha256:[0-9a-f]{64})$")
# a multi-platform image: the digest of its index, the same for every platform
INDEX = "application/vnd.oci.image.index.v1+json,application/vnd.docker.distribution.manifest.list.v2+json"


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def lock_problems(rel, text):
    """Every requirement of a lock file: name==version and at least one hash (the lines hold them after a backslash)."""
    out = []
    blocks = re.split(r"\n(?=[A-Za-z0-9])", "\n".join(x for x in text.split("\n") if not x.lstrip().startswith("#")).strip())
    if not blocks or blocks == [""]:
        return [f"{rel}: empty"]
    for b in blocks:
        name = b.split()[0]
        if "==" not in name:
            out.append(f"{rel}: {name} has no fixed version")
        if "--hash=sha256:" not in b:
            out.append(f"{rel}: {name} has no hash")
    return out


def pdfjs_version():
    m = re.search(r'pdfjs-dist (\d+\.\d+\.\d+)', read("static/vendor/pdfjs/README"))
    return m.group(1) if m else ""


def problems():
    out = []
    for rel in FILES:
        if not os.path.exists(os.path.join(ROOT, rel)):  # the app repository has no embed/
            continue
        text = read(rel)
        for img in FROM_RE.findall(text):
            if not IMAGE_RE.match(img):
                out.append(f"{rel}: FROM {img} has no tag@sha256 digest")
        if "--require-hashes" not in text:
            out.append(f"{rel}: pip install without --require-hashes")
        if re.search(r"pip install[^\n]*==", text):
            out.append(f"{rel}: packages named in the pip install line instead of the lock file")
        out += lock_problems(LOCKS[rel], read(LOCKS[rel]))
    if os.path.exists(os.path.join(ROOT, STATIC_LOCK)):
        out += lock_problems(STATIC_LOCK, read(STATIC_LOCK))
    ci = ".github/workflows/ci.yml"
    if os.path.exists(os.path.join(ROOT, ci)):
        for line in read(ci).split("\n"):
            m = re.search(r"pip install (.*)", line)
            if m and "-r " not in m.group(1):
                out += [f"{ci}: {p} without ==" for p in m.group(1).split() if "==" not in p]
    ver = pdfjs_version()
    if not ver:
        out.append("static/vendor/pdfjs/README: no pdfjs-dist version")
    elif f'"{ver}"' not in read("static/vendor/pdfjs/pdf.min.mjs"):
        out.append(f"static/vendor/pdfjs: pdf.min.mjs is not {ver}")
    if ver and os.path.exists(os.path.join(ROOT, "THIRD_PARTY_NOTICES.md")) and ver not in read("THIRD_PARTY_NOTICES.md"):
        out.append(f"THIRD_PARTY_NOTICES.md: pdfjs-dist {ver} missing")
    return out


def vendor_version(readme, pattern):
    m = re.search(pattern, read(readme))
    return m.group(1) if m else ""


def osv_targets():
    """(npm package, version) of every bundled front-end library; the DOMPurify inside mermaid.min.js has no README."""
    out = [("pdfjs-dist", pdfjs_version()),
           ("mermaid", vendor_version("static/vendor/mermaid/README", r"mermaid (\d+\.\d+\.\d+)")),
           ("katex", vendor_version("static/vendor/katex/README", r"katex (\d+\.\d+\.\d+)"))]
    m = re.search(r"@license DOMPurify (\d+\.\d+\.\d+)", read("static/vendor/mermaid/mermaid.min.js"))
    out.append(("dompurify", m.group(1) if m else ""))
    return out


def osv_ignored():
    """{vulnerability id or alias: reason}: holes checked by hand and not reachable (#4169); a new id turns the check red."""
    path = os.path.join(ROOT, "tools/pins_osv_ignore.json")
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith("_")}


def osv_query(name, ver):
    body = json.dumps({"version": ver, "package": {"name": name, "ecosystem": "npm"}}).encode()
    req = urllib.request.Request("https://api.osv.dev/v1/query", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r).get("vulns") or []


def osv_check(query=osv_query, targets=None, ignored=None):
    """Not in a lock file, so neither pip-audit nor npm audit sees them. A target without a version is a problem itself."""
    ignored = osv_ignored() if ignored is None else ignored
    out = []
    for name, ver in (osv_targets() if targets is None else targets):
        if not ver:
            out.append(f"{name}: version not found in static/vendor, OSV check impossible")
            continue
        for v in query(name, ver):
            if ignored.keys() & {v.get("id"), *(v.get("aliases") or [])}:
                continue
            out.append(f"{name} {ver}: {v.get('id')} {v.get('summary', '')}")
    return out


def digest(image, tag):
    repo = image if "/" in image else "library/" + image
    with urllib.request.urlopen(f"https://auth.docker.io/token?service=registry.docker.io&scope=repository:{repo}:pull", timeout=30) as r:
        tok = json.load(r)["token"]
    req = urllib.request.Request(f"https://registry-1.docker.io/v2/{repo}/manifests/{tag}", method="HEAD",
                                 headers={"Authorization": "Bearer " + tok, "Accept": INDEX})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.headers["Docker-Content-Digest"]


def update():
    for rel in FILES:
        if not os.path.exists(os.path.join(ROOT, rel)):
            continue
        text = new = read(rel)
        for img in FROM_RE.findall(text):
            m = IMAGE_RE.match(img)
            if m:
                new = new.replace(img, f"{m.group(1)}:{m.group(2)}@{digest(m.group(1), m.group(2))}")
        if new != text:
            with open(os.path.join(ROOT, rel), "w", encoding="utf-8") as f:
                f.write(new)
            print(f"{rel}: new digest")


def main():
    if "--update" in sys.argv:
        update()
    out = problems()
    if "--osv" in sys.argv:
        try:
            out += osv_check()
        except (OSError, urllib.error.URLError, ValueError) as e:
            print(f"::warning::pins: OSV not reachable, bundled libraries unchecked: {type(e).__name__}")
    for p in out:
        print("pins:", p)
    print(f"pins: {len(out)} problem(s)")
    return 1 if out else 0


if __name__ == "__main__":
    sys.exit(main())
