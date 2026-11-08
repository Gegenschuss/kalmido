"""2.742.0 (#5217): code integrity stage 1 - the web manifest: the full SHA-256 of every file the browser gets from a version.

The web app cannot check itself against the server (the server hands out the checking code too), so a later outside watcher
(stage 2) and a check page (stage 3) compare what a server sends with a list built from the tagged source. This module is
that list's one recipe, used by both sides:
  * tools/web_manifest.py builds it from a checkout without the app (the release attaches web-manifest-X.Y.Z.json next to
    SHA256SUMS, the CI builds it twice in two copies of the tree and stops on any difference);
  * the server answers GET /api/code-manifest with the same JSON (core/pages.py code_manifest), computed from what it really
    sends: the content hashes of core/pages.py st_asset, the language parts of core/i18nparts.py, index_page's page.

What counts is the bytes that go out, not the files in the repo: .js / .css without comments (core/strip.py), app.css with
the start style files behind it, /sw.js as it is, the language parts as the server splits them, "/" (also /capture, /share)
the app page as index_page renders it. The rendered page holds only values derived from the code (version, content
hashes, versions of the language parts) - no nonce, no instance name, nothing from the environment - so the tool renders it
the same way (cm_index). /manifest.json is no code (texts in the visitor's language, the shortcuts of the signed-in person)
and stays out. The first 12 hex digits of every entry are the ?v= / sw-manifest.json value of that file.

Only the standard library and two files of this folder without imports from the app (strip.py, i18nkeys.py)."""
import hashlib
import json
import os
import re

try:
    from .strip import strip_asset, start_css_files, with_start_css
    from .i18nkeys import module_keys, split_lang
except ImportError:  # tools/web_manifest.py loads this folder by its path, without the app
    from strip import strip_asset, start_css_files, with_start_css  # type: ignore
    from i18nkeys import module_keys, split_lang  # type: ignore

CM_V = 1  # the format of the manifest
CM_ASSET_RE = re.compile(r'(<(?:script|link)\b[^>]*?\b(?:src|href)="/static/)([\w./-]+\.(?:js|css))"')
CM_SW_LIST_RE = re.compile(r"const (SHELL|LAZY|LAZY_CSS) = \[(.*?)\];", re.S)
_CM_LANG = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})?")  # as core/i18nparts.py _I18NP_CODE


def cm_sha(data):
    return hashlib.sha256(data).hexdigest()


def cm_served(root, rel, data, starts=None):
    """-> (the bytes of static/<rel> as they go out, stripped). data = the file's bytes; .js / .css outside vendor/ without
    comments (core/strip.py; unsure = the original), app.css with the start style files behind it (starts: their paths, None =
    find them). core/pages.py st_asset hashes exactly these bytes."""
    if not rel.endswith((".js", ".css")) or rel.startswith("vendor/"):
        return data, False
    if rel == "app.css":
        starts = start_css_files(root) if starts is None else starts
        if starts:
            data = with_start_css(root, data, starts)
    out = strip_asset(rel, data)
    return (data, False) if out is None else (out, True)


def cm_static_rels(root):
    """Every file under the static folder ("js/core.js", sorted); hidden files and __pycache__ stay out."""
    out = []
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for n in names:
            if not n.startswith("."):
                out.append(os.path.relpath(os.path.join(base, n), root).replace(os.sep, "/"))
    return sorted(out)


def cm_sw_lists(sw_js):
    """The lists SHELL / LAZY / LAZY_CSS of static/sw.js -> {list: [urls]}."""
    return {m.group(1): re.findall(r"'(/static/[\w./-]+)'", m.group(2)) for m in CM_SW_LIST_RE.finditer(sw_js)}


def cm_versioned(html, hash12):
    """Every start script and stylesheet under /static/ of the app page gets ?v=<content hash> (hash12(rel) -> 12 hex or None)."""
    def sub(m):
        h = hash12(m.group(2))
        return m.group(0) if not h else f'{m.group(1)}{m.group(2)}?v={h}"'
    return CM_ASSET_RE.sub(sub, html)


def cm_ld_metas(lists, hash12):
    """The two meta tags with the content hash of every module file loaded on demand (core/pages.py ld_hash_metas)."""
    out = ""
    for meta, lst, rx in (("kalmido-ldjs", "LAZY", r"/static/js/([\w-]+)\.js"), ("kalmido-ldcss", "LAZY_CSS", r"/static/css/([\w-]+)\.css")):
        pairs = []
        for u in lists.get(lst, []):
            m, h = re.fullmatch(rx, u), hash12(u[8:])
            if m and h:
                pairs.append(f"{m.group(1)}={h}")
        out += f'\n<meta name="{meta}" content="{" ".join(pairs)}">'
    return out


def cm_index(html, version, i18n_ver, ld_metas, i18n_table, hash12):
    """The app page as it goes out (core/pages.py index_page): static/index.html with the version of the code, the versions of
    the language parts, the hashes of the modules loaded on demand and ?v= on every start file."""
    html = html.replace('<meta name="kalmido-version" content="">', f'<meta name="kalmido-version" content="{version}">', 1)
    html = html.replace('<meta name="kalmido-i18n" content="">', f'<meta name="kalmido-i18n" content="{i18n_ver}">'
                        + ld_metas + f'\n<meta name="kalmido-i18nv" content="{i18n_table}">', 1)
    return cm_versioned(html, hash12)


def cm_json(version, files):
    """The manifest as bytes: the same for the release file and /api/code-manifest (sorted keys, one entry per line)."""
    doc = {"v": CM_V, "version": version, "algo": "sha256", "files": dict(sorted(files.items()))}
    return (json.dumps(doc, ensure_ascii=False, indent=0, sort_keys=False) + "\n").encode("utf-8")


def cm_i18n(app_dir):
    """The language parts as core/i18nparts.py splits them, without the app -> (version of all parts, the table of the meta
    kalmido-i18nv, {url: bytes}). ValueError: the split fails (the server would then turn it off; a release must not)."""
    i18n_dir = os.path.join(app_dir, "static", "i18n")
    mod_of, mods = module_keys(app_dir)
    h = hashlib.sha256(json.dumps(sorted(mod_of.items()), ensure_ascii=False).encode())
    for f in sorted(os.path.join(i18n_dir, n) for n in os.listdir(i18n_dir) if n.endswith(".json")):
        with open(f, "rb") as fh:
            h.update(os.path.basename(f).encode() + b"\0" + fh.read())
    ver = h.hexdigest()[:12]
    enc = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()  # noqa: E731 (i18nparts _i18np_lang)
    names = ["core"] + sorted(mods)
    rows, urls = [], {}
    for code in sorted(n[:-5] for n in os.listdir(i18n_dir) if n.endswith(".json") and _CM_LANG.fullmatch(n[:-5])):
        with open(os.path.join(i18n_dir, code + ".json"), encoding="utf-8") as f:
            core, parts = split_lang(json.load(f), mod_of)
        out = {"core": enc(core)} | {"mod-" + m: enc(parts.get(m, {})) for m in mods}
        for part, data in out.items():
            urls[f"/static/i18n/{code}.{part}.json"] = data
        rows.append(code + "=" + "".join(cm_sha(out[n if n == "core" else "mod-" + n])[:12] for n in names))
    return ver, ";".join([",".join(names)] + rows), urls


def cm_version(app_dir):
    """VERSION next to app.py (core/config.py _read_version)."""
    try:
        with open(os.path.join(app_dir, "VERSION"), encoding="utf-8") as f:
            v = f.read().strip()
    except OSError:
        return "0.0.0"
    return v if re.fullmatch(r"\d+\.\d+\.\d+", v) else "0.0.0"


def cm_build(app_dir):
    """The manifest of a source tree (the folder of app.py) -> (version, {url: full sha256})."""
    root = os.path.join(app_dir, "static")
    files = {}
    for rel in cm_static_rels(root):
        with open(os.path.join(root, rel), "rb") as f:
            files["/static/" + rel] = cm_sha(cm_served(root, rel, f.read())[0])
    with open(os.path.join(root, "sw.js"), "rb") as f:
        sw = f.read()
    files["/sw.js"] = cm_sha(sw)  # core/pages.py sw: the file as it is (/static/sw.js goes out stripped)
    ver, table, parts = cm_i18n(app_dir)
    for url, data in parts.items():
        files[url] = cm_sha(data)
    hash12 = lambda rel: (files.get("/static/" + rel) or "")[:12] or None  # noqa: E731
    with open(os.path.join(root, "index.html"), encoding="utf-8") as f:
        page = cm_index(f.read(), cm_version(app_dir), ver, cm_ld_metas(cm_sw_lists(sw.decode("utf-8")), hash12), table, hash12)
    files["/"] = cm_sha(page.encode("utf-8"))
    return cm_version(app_dir), files
