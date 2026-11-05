"""2.556.0 (#4685): "New for you" -- after an update every person sees once the sentences written for users of the versions
since the version they saw last (static/js/whatsnew.js draws the dialog).

The source is static/whatsnew.json, written by the release process only (never edited by hand):
    {"versions": [{"version": "2.553.0", "date": "2026-11-05", "items": [{"de": "...", "en": "..."}]}]}   newest first
A missing or broken file is no error: there is nothing new then. The version a person saw last (whatsnew_seen) and the
switch (whatsnew_on, Settings > Help) are user settings, so they hold on every device. A person without a stored version
(a new account, or the first start after this feature came) gets the current version and no dialog.
Test containers (KALMIDO_TEST=1) read <data dir>/whatsnew-test.json instead when it exists: the suites bring their own
example file without checking in the real one."""
import json
import os
import threading

from flask import jsonify

from ..core.config import app, APP_DIR, APP_VERSION, DB
from ..core.db import db, uset, usettings
from ..core.i18n import lang
from ..core.schema import USER_DEFAULTS
from ..core.ctx import me

USER_DEFAULTS.setdefault("whatsnew_on", "1")  # the dialog after an update (0 = never)
USER_DEFAULTS.setdefault("whatsnew_seen", "")  # the version whose news the person saw last ('' = not set yet)
WN_FILE = os.path.join(APP_DIR, "static", "whatsnew.json")
WN_CHANGELOG = "https://github.com/Gegenschuss/kalmido/blob/main/CHANGELOG.md"  # "Older changes": the public change log
_WN = {"key": None, "versions": []}
_WN_LOCK = threading.Lock()


def wn_ver(v):
    """'2.553.0' -> (2, 553, 0) for comparing the parts as numbers (2.60 < 2.553); None when it is no version."""
    parts = str(v or "").strip().lstrip("v").split(".")
    if not 1 <= len(parts) <= 4 or not all(p.isdigit() and len(p) <= 6 for p in parts):
        return None
    return tuple(int(p) for p in parts) + (0,) * (4 - len(parts))


def wn_path():
    if os.environ.get("KALMIDO_TEST") == "1":  # tests only: the suite's example file in the data dir
        p = os.path.join(os.path.dirname(DB), "whatsnew-test.json")
        if os.path.exists(p):
            return p
    return WN_FILE


def wn_versions():
    """The versions of the file with their items, newest first (read again when the file changes); [] without a file."""
    p = wn_path()
    try:
        st = os.stat(p)
        key = (p, st.st_mtime_ns, st.st_size)
    except OSError:
        return []
    with _WN_LOCK:
        if _WN["key"] == key:
            return _WN["versions"]
        out = []
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            for v in (d.get("versions") if isinstance(d, dict) else None) or []:
                if not isinstance(v, dict) or wn_ver(v.get("version")) is None:
                    continue
                items = [{k: x for k, x in it.items() if isinstance(k, str) and isinstance(x, str) and x.strip()}
                         for it in (v.get("items") or []) if isinstance(it, dict)]
                out.append({"version": str(v["version"]).strip().lstrip("v"), "date": str(v.get("date") or "")[:10],
                            "items": [it for it in items if it]})
        except (OSError, ValueError, AttributeError, TypeError):
            out = []
        out.sort(key=lambda v: wn_ver(v["version"]), reverse=True)
        _WN.update(key=key, versions=out)
        return out


def wn_text(item, lg):
    """The sentence in the person's language, else English, else the first one there is."""
    return item.get(lg) or item.get("en") or next(iter(item.values()), "")


@app.get("/api/whatsnew")
def whatsnew_get():
    """What is new for me: the versions after my seen one up to the running one, each with its sentences in my language.
    Without a seen version it becomes the running one (nothing to show). older: my seen version is older than the file
    reaches (the dialog links the change log for the rest)."""
    c = db()
    s = usettings(c, me())
    cur = wn_ver(APP_VERSION)
    seen = s.get("whatsnew_seen") or ""
    on = s.get("whatsnew_on") != "0"
    if wn_ver(seen) is None:
        uset(c, me(), "whatsnew_seen", APP_VERSION)
        c.commit()
        return jsonify(on=on, seen=APP_VERSION, current=APP_VERSION, versions=[], older=False, link=WN_CHANGELOG)
    sv, lg = wn_ver(seen), lang(c)
    allv = wn_versions()
    vs = [{"version": v["version"], "date": v["date"], "items": [wn_text(it, lg) for it in v["items"]]}
          for v in allv if sv < wn_ver(v["version"]) <= cur and v["items"]]
    older = bool(vs) and sv < wn_ver(allv[-1]["version"])
    return jsonify(on=on, seen=seen, current=APP_VERSION, versions=vs if on else [], older=older and on, link=WN_CHANGELOG)


@app.post("/api/whatsnew/seen")
def whatsnew_mark_seen():
    """The dialog was closed (or there was nothing to show): the running version is seen, on every device."""
    c = db()
    uset(c, me(), "whatsnew_seen", APP_VERSION)
    c.commit()
    return jsonify(ok=True, seen=APP_VERSION)
