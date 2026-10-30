"""2.418.0 (#3560): the menus of the areas, arranged by each person.

Every area (the office's points one by one, the parts of Home, Reading, Time, Review, File store) and the phone's tab bar
have a menu the person arranges: the order, which points are hidden (only not in the menu: data, function and rights stay,
the search still finds them) and which points that start hidden (an office point not used yet) were brought back.
  - user setting "nav_menus": json {area: {"order": [key], "hidden": [key], "shown": [key]}}; the same on phone and computer,
  - orgs.nav_off: the points an organisation's admins switched off for all its members ("<area>:<key>" csv). They are not in
    the members' menus, not even under Hidden; in a private workspace the person is the own admin (nothing to switch).
The server only bounds the values; the client (navmenu.js) decides what the keys mean, so a new point needs no change here."""
import json
import re

from ..core.errors import BadInput
from ..core.i18n import tr

# the menus that can be arranged (the ids of MG_AREAS in areas.js, and the phone's tab bar)
NAV_AREAS = ("office", "time", "review", "life", "reading", "ablage", "tabbar")
NAV_LISTS = ("order", "hidden", "shown")
NAV_MAX = 80  # entries per list (the office has about 25 points, the tab bar a handful)
# a point: a route word of the office / an area ("cashflow", "family"); the tab bar also pins views, lists and filters
# ("s:today", "l:12", "tag:Büro", "f:3", "a:office")
NAV_KEY_RE = re.compile(r"[^\x00-\x1f\x7f]{1,120}")
NAV_OFF_RE = re.compile(r"(office|time|review|life|reading|ablage):[a-z0-9_]{1,40}")


def nav_clean_menus(v):
    """The user setting nav_menus -> stored json. Strict: an unknown area or list, a non-string key or too many is a 400;
    empty lists and empty areas are dropped, duplicates removed (first one wins)."""
    bad = BadInput(tr("Invalid value: {0}", "nav_menus"))
    try:
        o = json.loads(v or "{}") if isinstance(v, str) else v
    except ValueError:
        raise bad from None
    if not isinstance(o, dict):
        raise bad
    out = {}
    for area, m in o.items():
        if area not in NAV_AREAS or not isinstance(m, dict) or any(k not in NAV_LISTS for k in m):
            raise bad
        a = {}
        for k in NAV_LISTS:
            xs = m.get(k) or []
            if not isinstance(xs, list) or len(xs) > NAV_MAX or not all(isinstance(x, str) and NAV_KEY_RE.fullmatch(x) for x in xs):
                raise bad
            if xs:
                a[k] = list(dict.fromkeys(xs))
        if a:
            out[area] = a
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def nav_clean_org(v):
    """orgs.nav_off from a request (["office:travel", ...] or csv) -> stored csv; a malformed point is a 400."""
    xs = v.split(",") if isinstance(v, str) else v
    if not isinstance(xs, list) or len(xs) > 200 or not all(isinstance(x, str) for x in xs):
        raise BadInput(tr("Invalid value: {0}", "nav_off"))
    xs = [x.strip() for x in xs if x.strip()]
    if any(not NAV_OFF_RE.fullmatch(x) for x in xs):
        raise BadInput(tr("Invalid value: {0}", "nav_off"))
    return ",".join(dict.fromkeys(xs))


def nav_org_off(r):
    """The points switched off of an orgs row (a list)."""
    return [x for x in (r["nav_off"] or "").split(",") if x]
