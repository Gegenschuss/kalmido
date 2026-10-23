"""2.191.0 A (#1410 #2518): the web client's texts per module.

static/i18n/<code>.json stays ONE file per language (the server's translations, the translators' file, older clients). The
web client loads at start only the core texts and the texts of a module loaded on demand together with the module:
  GET /static/i18n/<code>.core.json        every key outside the modules' parts; "_mods" = the modules with a part
  GET /static/i18n/<code>.mod-<name>.json  the keys only that module uses (core/i18nkeys.py module_keys)
Split here at run time from the code (no build step: the same for self-hosting, the test image and the demo), built again
when a source or language file changes. Like the other static files: no sign-in and no database (accounts/session.py
skips /static/); asked with ?v=<i18np_ver()> (index.html meta kalmido-i18n) the answer is immutable."""
import gzip
import hashlib
import json
import os
import re
import threading
import time
from flask import abort, request, Response

from ..core.config import app, APP_DIR
from ..core.i18n import I18N_DIR
from ..core.i18nkeys import key_sources, module_keys, split_lang

_I18NP = {}
_I18NP_LOCK = threading.Lock()
_I18NP_CODE = re.compile(r"[a-z]{2,3}(-[A-Za-z0-9]{2,8})?")


def _i18np_sig():
    """What the split depends on: the sources with keys, lazyload.js (LD_MODS) and the language files."""
    paths = [os.path.join(APP_DIR, r) for r in key_sources(APP_DIR)] + [os.path.join(APP_DIR, "static", "js", "lazyload.js")]
    paths += sorted(os.path.join(I18N_DIR, f) for f in os.listdir(I18N_DIR) if f.endswith(".json"))
    out = []
    for p in paths:
        try:
            st = os.stat(p)
            out.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    return tuple(out)


def i18np_state():
    """The split ({key: module}, the modules, the version), checked against the files at most every 5 seconds."""
    now = time.monotonic()
    st = _I18NP.get("st")
    if st and now - st["at"] < 5:
        return st
    with _I18NP_LOCK:
        st = _I18NP.get("st")
        if st and now - st["at"] < 5:
            return st
        sig = _i18np_sig()
        if not st or st["sig"] != sig:
            mod_of, mods = module_keys(APP_DIR)
            h = hashlib.sha256(json.dumps(sorted(mod_of.items()), ensure_ascii=False).encode())
            for p, _, _ in sig:
                if p.startswith(I18N_DIR + os.sep):
                    with open(p, "rb") as f:
                        h.update(os.path.basename(p).encode() + b"\0" + f.read())
            st = {"sig": sig, "mod_of": mod_of, "mods": set(mods), "ver": h.hexdigest()[:12], "langs": {}}
        _I18NP["st"] = st = {**st, "at": now}
    return st


def i18np_ver():
    """The version of the split texts for ?v= (12 hex digits like the content hashes of the static files); '' on an error."""
    try:
        return i18np_state()["ver"]
    except (OSError, ValueError) as e:
        print("i18n parts:", e, flush=True)
        return ""


def i18np_url_ver(url):
    """sw-manifest.json: the version of a split language file (/static/i18n/<code>.core.json, .mod-<name>.json); None: none."""
    m = re.fullmatch(r"/static/i18n/([\w-]+)\.(core|mod-\w+)\.json", url)
    return (i18np_ver() or None) if m else None


def _i18np_lang(st, code):
    """{part: (plain bytes, gzip bytes)} of one language ("core", "mod-<name>"); None: no such language."""
    hit = st["langs"].get(code)
    if hit is not None:
        return hit
    path = os.path.join(I18N_DIR, code + ".json")
    if not _I18NP_CODE.fullmatch(code) or not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    core, parts = split_lang(d, st["mod_of"])
    enc = lambda o: json.dumps(o, ensure_ascii=False, separators=(",", ":")).encode()  # noqa: E731
    out = {"core": enc(core)}
    for m in st["mods"]:
        out["mod-" + m] = enc(parts.get(m, {}))
    with _I18NP_LOCK:
        st["langs"][code] = out = {k: (v, gzip.compress(v, 6, mtime=0)) for k, v in out.items()}
    return out


def _i18np_send(code, part):
    st = i18np_state()
    lang = _i18np_lang(st, code)
    if lang is None or part not in lang:
        abort(404)
    plain, gz = lang[part]
    zipped = request.accept_encodings["gzip"] > 0 and len(plain) >= 1024
    r = Response(gz if zipped else plain, mimetype="application/json")
    if zipped:  # core/compress.py leaves an answer with a Content-Encoding alone
        r.headers["Content-Encoding"] = "gzip"
    r.vary.add("Accept-Encoding")
    r.headers["Cache-Control"] = "public, max-age=31536000, immutable" if request.args.get("v") == st["ver"] else "no-cache"
    return r


@app.get("/static/i18n/<code>.core.json")
def i18np_core(code):
    return _i18np_send(code, "core")


@app.get("/static/i18n/<code>.mod-<name>.json")
def i18np_mod(code, name):
    return _i18np_send(code, "mod-" + name)


def i18np_warm():
    try:
        i18np_state()
    except (OSError, ValueError) as e:
        print("i18n parts:", e, flush=True)


# the split reads the whole code once (about a second): done in the background at start, not on the first app start
if os.environ.get("KALMIDO_ROLE") != "worker":
    threading.Thread(target=i18np_warm, daemon=True, name="i18n-parts").start()
