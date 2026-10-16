"""2.55.0 (#1069): several saved arrangements per view and person (table view_layouts), e.g. "Focus" and "Overview",
switched in the view's header and the same on all devices. The person's current value (user setting / list_layouts) stays
what the view shows, so 2.53 keeps working with the new table; a saved arrangement is a named copy of such a value.
lyv_save() is the one way in: the person saving (#1069), a template taken over (#1068) and an accepted agent proposal
(#1066) all land here as one more saved arrangement."""
import re

from ..core.config import app  # noqa: F401  (routes of #1069 live here)
from ..core.i18n import tr
from ..core.db import iso, now_utc
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .layouts import WG_STD_KEYS, clean_layout

LYV_MAX = 12          # saved arrangements per person and view
LYV_NAME_MAX = 60
LYV_SOURCES = ("", "template", "agent")
LYV_LIST_RE = re.compile(r"list:[1-9][0-9]{0,15}")


def lyv_key_ok(key):
    """A view that can have saved arrangements. For "list:<id>" the caller checks the person may see that project page."""
    return isinstance(key, str) and (key in WG_STD_KEYS or bool(LYV_LIST_RE.fullmatch(key)))


def lyv_clean(key, layout):
    from .settings import DASH_WIDGETS
    return clean_layout(layout, DASH_WIDGETS if key == "dashboard" else None)


def lyv_name(c, uid, key, name):
    """The name trimmed and made unique among the person's arrangements of that view ("Focus", "Focus (2)", ...)."""
    n = (name or "").strip()[:LYV_NAME_MAX] if isinstance(name, str) else ""
    if not n:
        raise BadInput(tr("Give the arrangement a name"))
    have = {r["name"] for r in c.execute("SELECT name FROM view_layouts WHERE user_id=? AND view_key=?", (uid, key))}
    base, i = n, 2
    while n in have:
        suf = f" ({i})"
        n, i = base[:LYV_NAME_MAX - len(suf)] + suf, i + 1
    return n


def lyv_save(c, uid, key, name, layout, source="", source_ref=None):
    """Store one more saved arrangement of view key for person uid and return its id (no commit, no bump: the caller does).
    layout = json text / dict as the view stores it (cleaned here). 409 at LYV_MAX per view."""
    from ..core.pg import insert_id
    if not lyv_key_ok(key) or source not in LYV_SOURCES:
        raise BadInput(tr("Invalid layout"))
    v = lyv_clean(key, layout)
    if c.execute("SELECT COUNT(*) FROM view_layouts WHERE user_id=? AND view_key=?", (uid, key)).fetchone()[0] >= LYV_MAX:
        raise Denied(409, tr("At most {0} saved arrangements per view", LYV_MAX))
    pos = c.execute("SELECT COALESCE(MAX(pos), 0) + 1 FROM view_layouts WHERE user_id=? AND view_key=?", (uid, key)).fetchone()[0]
    ts = iso(now_utc())
    return insert_id(c, """INSERT INTO view_layouts(user_id,view_key,name,layout,pos,source,source_ref,created_at,updated_at)
                            VALUES(?,?,?,?,?,?,?,?,?)""",
                     (uid, key, lyv_name(c, uid, key, name), v, pos, source, source_ref, ts, ts))
