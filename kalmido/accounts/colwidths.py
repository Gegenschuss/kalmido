"""2.742.0 (#4857): the column widths of the lists, per person on every device (user setting "col_widths").

Stored json {"<list id>": {"<column key>": rem}}; the web client (static/js/render.js lcwGet / lcwSet) drags a column title's
grip and sends only the list it changed: PATCH /api/settings {"col_widths": {"<list id>": {...} | null}} is merged into the
stored value under the settings lock (accounts/settings.py settings_update), null or {} = the list's standard widths again.
Only the person's own view: nothing of the list or the other members changes. Bounded, because the setting travels with
every state load: at most LCW_LISTS lists (the oldest fall away), LCW_COLS columns per list."""
import json
import math
import re

from ..core.i18n import tr
from ..core.errors import BadInput

LCW_LISTS, LCW_COLS = 300, 40
LCW_MIN, LCW_MAX = 2.5, 1000  # rem; no real upper limit (#4830): the client keeps the title column at its minimum
LCW_LID_RE = re.compile(r"[1-9][0-9]{0,11}|v")  # 2.750.0 (#4502): "v" = the collected views (Today, My tasks, filters: render.js VC)
LCW_KEY_RE = re.compile(r"[a-z]{2,16}|f:[1-9][0-9]{0,11}")  # due, prio, tags ... or f:<field id>


def lcw_parse(v, bad):
    """A json string or object -> dict; '' / None = {}."""
    if v in (None, ""):
        return {}
    try:
        o = json.loads(v) if isinstance(v, str) else v
    except ValueError:
        raise bad from None
    if not isinstance(o, dict):
        raise bad
    return o


def lcw_list(cols, bad):
    """One list's widths {key: rem} -> cleaned dict (empty = the standard widths); BadInput if malformed."""
    if cols is None:
        return {}
    if not isinstance(cols, dict) or len(cols) > LCW_COLS:
        raise bad
    out = {}
    for k, w in cols.items():
        if not isinstance(k, str) or not LCW_KEY_RE.fullmatch(k) or isinstance(w, bool) or not isinstance(w, (int, float)) \
                or not math.isfinite(w):
            raise bad
        out[k] = round(max(LCW_MIN, min(LCW_MAX, float(w))), 2)
    return out


def lcw_clean(v):
    """The whole stored value -> stored json; BadInput if malformed (list ids, column keys, numbers)."""
    bad = BadInput(tr("Invalid value: {0}", "col_widths"))
    o = lcw_parse(v, bad)
    if len(o) > LCW_LISTS * 2:
        raise bad
    out = {}
    for lid, cols in o.items():
        if not isinstance(lid, str) or not LCW_LID_RE.fullmatch(lid):
            raise bad
        c = lcw_list(cols, bad)
        if c:
            out[lid] = c
    out = dict(list(out.items())[-LCW_LISTS:])
    return json.dumps(out, separators=(",", ":"))


def lcw_merge(stored, patch):
    """The stored value plus a patch {list id: widths | null} -> json for lcw_clean; the changed lists move to the end (the
    newest, kept when LCW_LISTS cuts). BadInput if the patch is malformed."""
    bad = BadInput(tr("Invalid value: {0}", "col_widths"))
    p = lcw_parse(patch, bad)
    if len(p) > LCW_LISTS:
        raise bad
    try:
        cur = json.loads(stored or "{}")
    except ValueError:
        cur = {}
    cur = cur if isinstance(cur, dict) else {}
    for lid, cols in p.items():
        if not isinstance(lid, str) or not LCW_LID_RE.fullmatch(lid):
            raise bad
        c = lcw_list(cols, bad)
        cur.pop(lid, None)
        if c:
            cur[lid] = c
    return json.dumps(cur, separators=(",", ":"))
