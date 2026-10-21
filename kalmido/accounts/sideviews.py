"""2.156.0 D (#2186): saved views of the sidebar ("On the road", "Planning"), per person and the same on every device.
A view remembers which groups of the sidebar are open, which folders are closed and which entries it hides (they wait under
"More (N)" in the sidebar, nothing is lost), optionally a start page. Two user settings, synced like the others:
side_views = json list of views, side_view = the id of the active one ('' = the fixed view "Everything").
Only the person themselves reads and writes them (user settings); agents get no way in (not asked for)."""
import json
import re

from ..core.i18n import tr

SV_MAX = 20            # views per person
SV_NAME_MAX = 60
SV_HIDE_MAX = 300      # hidden entries per view
SV_ID_RE = re.compile(r"[a-z0-9]{1,16}")
SV_ICON_RE = re.compile(r"[a-z][a-z0-9]{0,23}")
SV_GROUP_RE = re.compile(r"[a-z][a-z0-9]{0,23}")
# a start page = a route of the app (hash without '#'): "today", "l/12", "folder/Work%20stuff", "office/receipts", ...
SV_START_RE = re.compile(r"[A-Za-z0-9/_:%.,~=+-]{0,200}")


def _bad():
    from ..personal.timetrack import BadInput
    return BadInput(tr("Invalid value: {0}", "side_views"))


def _key(x):
    """A hidden entry: "g:<group>" or a favourites key of favtiles.js (l:, folder:, v:, m:, f:, tag:, p:, g:, a:)."""
    if not isinstance(x, str) or not 2 < len(x) <= 220 or ":" not in x or re.search(r"[\x00-\x1f]", x):
        raise _bad()
    return x


def sv_clean_view(o):
    from ..lists.lists import clean_folder
    from ..personal.timetrack import BadInput
    if not isinstance(o, dict):
        raise _bad()
    vid, name = o.get("id"), o.get("name")
    if not isinstance(vid, str) or not SV_ID_RE.fullmatch(vid) or not isinstance(name, str):
        raise _bad()
    name = re.sub(r"[\x00-\x1f]", "", name).strip()[:SV_NAME_MAX]
    if not name:
        raise BadInput(tr("Give the view a name"))
    icon = o.get("icon") or "panel"
    if not isinstance(icon, str) or not SV_ICON_RE.fullmatch(icon):
        raise _bad()
    lists = {}
    for k, n in (("open", 40), ("fclosed", 200), ("hide", SV_HIDE_MAX)):
        a = o.get(k) or []
        if not isinstance(a, list) or len(a) > n:
            raise _bad()
        lists[k] = a
    if not all(isinstance(g, str) and SV_GROUP_RE.fullmatch(g) for g in lists["open"]):
        raise _bad()
    fc = []
    for f in lists["fclosed"]:
        f = clean_folder(f, False) if isinstance(f, str) else None
        if not f:
            raise _bad()
        fc.append(f)
    start = o.get("start") or ""
    if not isinstance(start, str) or not SV_START_RE.fullmatch(start):
        raise _bad()
    return {"id": vid, "name": name, "icon": icon, "open": list(dict.fromkeys(lists["open"])),
            "fclosed": list(dict.fromkeys(fc)), "hide": list(dict.fromkeys(_key(x) for x in lists["hide"])), "start": start}


def sv_clean(k, v):
    """The stored text of side_views (a json list of views, or its text) / side_view (an id or ''); BadInput otherwise."""
    from ..personal.timetrack import BadInput
    if k == "side_view":
        s = "" if v is None else v
        if not isinstance(s, str) or (s and not SV_ID_RE.fullmatch(s)):
            raise BadInput(tr("Invalid value: {0}", k))
        return s
    try:
        arr = json.loads(v or "[]") if isinstance(v, str) else v
    except ValueError:
        raise _bad() from None
    if not isinstance(arr, list) or len(arr) > SV_MAX:
        raise _bad()
    out = [sv_clean_view(o) for o in arr]
    if len({o["id"] for o in out}) != len(out):
        raise _bad()
    s = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    if len(s) > 60000:
        raise _bad()
    return s
