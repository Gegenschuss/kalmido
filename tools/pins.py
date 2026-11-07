#!/usr/bin/env python3
"""The pinned dependencies stay pinned (2.360.3, #2915).

    python3 tools/pins.py            offline: exit 1 when a build pin is missing (CI lint, no network)
    python3 tools/pins.py --osv      + pdf.js, mermaid, katex and the DOMPurify inside mermaid.min.js against the OSV database
                                     (exit 1 on a known hole, except those listed with a reason in tools/pins_osv_ignore.json)
    python3 tools/pins.py --update   rewrites the digests of the base images to what their tags point at today
    python3 tools/pins.py --wheels   2.630.0 (#4671): only the image libraries inside the Pillow wheel (PIL.features.version)
                                     against WHEEL_MIN; exit 1 when one is older or missing. Runs in the image build (Dockerfile)

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


# 2.630.0 (#4671): the C libraries the Pillow wheel brings along parse every uploaded image, but no lock file names them, so
# neither pip-audit nor the base image updates see them. Minimums = what the Pillow 13.0.0 wheels bundle (Pillow's
# .github/dependencies.json at tag 13.0.0, read 07.11.2026): all of them past their last known CVE fixes then (libwebp
# CVE-2023-4863 in 1.3.2, freetype CVE-2025-27363 in 2.13.1). A Pillow update raises them to its new bundle by hand; the
# quarterly upkeep compares them with the NVD. (name, PIL.features name, minimum). libpng is in the wheel only for freetype
# (Pillow reads PNG with zlib) and reports no version; lcms2 2.19.1 may report itself as 2.19, hence the minimum 2.19.
WHEEL_MIN = (("libjpeg-turbo", "libjpeg_turbo", "3.2.0"), ("zlib-ng", "zlib_ng", "2.3.3"), ("libtiff", "libtiff", "4.7.2"),
             ("libwebp", "webp", "1.6.0"), ("freetype", "freetype2", "2.14.3"), ("openjpeg", "jpg_2000", "2.5.4"),
             ("lcms2", "littlecms2", "2.19"))


def _vtuple(v):
    """'2.14.3' / '1.3.1.zlib-ng' / '4.7.2' -> (2, 14, 3); None when it starts with no number."""
    m = re.match(r"\s*(\d+(?:\.\d+)*)", str(v or ""))
    return tuple(int(x) for x in m.group(1).split(".")) if m else None


def _older(have, want):
    n = max(len(have), len(want))
    return have + (0,) * (n - len(have)) < want + (0,) * (n - len(want))


def wheel_problems(version=None, minimums=WHEEL_MIN):
    """version(feature) -> the version string or None (default PIL.features.version). -> problems, [] = all new enough."""
    if version is None:
        try:
            from PIL import features
        except ImportError as e:
            return [f"Pillow not importable: {e}"]
        version = features.version
    out = []
    for name, feat, want in minimums:
        try:
            have = version(feat)
        except Exception as e:  # noqa: BLE001 -- a feature this Pillow does not know is a missing library
            have, err = None, e
        else:
            err = None
        hv = _vtuple(have)
        if hv is None:
            out.append(f"{name}: no version in this Pillow ({feat}: {have!r}{f', {err}' if err else ''}), minimum {want}")
        elif _older(hv, _vtuple(want)):
            out.append(f"{name} {have} is older than the minimum {want} (tools/pins.py WHEEL_MIN)")
        else:
            print(f"pins: {name} {have} ok (minimum {want})")
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
    if "--wheels" in sys.argv:  # 2.630.0 (#4671): in the image, without the repository around it
        out = wheel_problems()
        for p in out:
            print("pins:", p)
        print(f"pins: wheel libraries, {len(out)} problem(s)")
        return 1 if out else 0
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
