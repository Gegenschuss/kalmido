"""2.89.0 (#1916): Kalmido variables of table formulas -- projekt.<name>.<field>, liste.<name>.<field>, kunde.<name>.<field>,
hier.<field> (the sheet's attached project / list), evaluated PER VIEWER.

A source counts for a viewer only when they see it right now (lists: list_role, which already applies the organisation
boundary, health / budget lists, an API token's list limit; agents also their own list limit and never a list with the lock;
clients: like team/clients.py, an agent through a list of the client it sees) AND it lies in the sheet's space (an
organisation's sheet: sources of that organisation only; a private sheet: what its viewer sees). Anything else is "denied":
no value and no name (the formula shows the bare id, the cell "No access"). A source that no longer exists is "deleted".
The <name> is the lower-case slug of the source's current name among the sources the viewer may use (equal slugs: _2, _3 in
the order of the ids), so the display follows renames while the stored formula keeps the id.
"""
import math

from flask import g, has_request_context

from ..core.access import list_role, tvis, vis_sql
from ..core.i18n import N_
from .formula import ShErr, sh_slug

SH_LIST_FIELDS = ("zeit_gesamt", "aufgaben", "offen", "erledigt", "budget_h")
SH_CLIENT_FIELDS = ("satz", "budget_h", "budget_betrag", "zeit_gesamt")
SH_FIELD_HELP = {"zeit_gesamt": N_("Tracked time in hours"), "aufgaben": N_("Number of tasks"), "offen": N_("Open tasks"),
                 "erledigt": N_("Completed tasks"), "budget_h": N_("Budget in hours"), "satz": N_("Hourly rate"),
                 "budget_betrag": N_("Budget amount")}
SH_VAR_WORD = {"p": "projekt", "l": "liste", "k": "kunde"}


def sh_fields_of(typ):
    return SH_CLIENT_FIELDS if typ == "k" else SH_LIST_FIELDS


def _is_agent(c, uid):
    r = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r and r[0] == "agent")


def _cache(c, uid):
    """Per request (and viewer): the source rows and values already looked up."""
    if has_request_context():
        root = g.setdefault("sh_var_cache", {})
        return root.setdefault(uid, {})
    return {}


def _agent_cap(c, uid):
    from ..agents.safety import ids_parse
    r = c.execute("SELECT list_ids FROM agents WHERE user_id=?", (uid,)).fetchone()
    ids = ids_parse(r[0]) if r and r[0] else None
    return ids or None


def sh_list_ok(c, sheet, uid, lid, cache=None):
    """The list row when uid may use list lid in this sheet (sees it, same space, no lock), else None; "deleted" when gone."""
    cache = _cache(c, uid) if cache is None else cache
    key = ("L", lid, sheet["org_id"])
    if key in cache:
        return cache[key]
    r = c.execute("SELECT id, name, kind, org_id, e2e, client_id, is_inbox FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        out = "deleted"
    elif r["e2e"] is not None or not list_role(c, lid, uid):
        out = None
    elif sheet["org_id"] is not None and r["org_id"] != sheet["org_id"]:
        out = None
    else:
        out = r
        if _is_agent(c, uid):
            cap = _agent_cap(c, uid)
            if cap is not None and lid not in cap:
                out = None
    cache[key] = out
    return out


def _client_visible_ids(c, uid, cache):
    if "clients" not in cache:
        if _is_agent(c, uid):
            ids = set()
            for r in c.execute("SELECT id, client_id FROM lists WHERE client_id IS NOT NULL").fetchall():
                if r["client_id"] not in ids and list_role(c, r["id"], uid):
                    cap = _agent_cap(c, uid)
                    if cap is None or r["id"] in cap:
                        ids.add(r["client_id"])
        else:
            from ..team.clients import client_rows
            ids = {r["id"] for r in client_rows(c, uid)}
        cache["clients"] = ids
    return cache["clients"]


def sh_client_ok(c, sheet, uid, cid, cache=None):
    cache = _cache(c, uid) if cache is None else cache
    key = ("K", cid, sheet["org_id"])
    if key in cache:
        return cache[key]
    r = c.execute("SELECT id, name, org_id, rate, budget_h, budget_amount FROM clients WHERE id=?", (cid,)).fetchone()
    if not r:
        out = "deleted"
    elif cid not in _client_visible_ids(c, uid, cache):
        out = None
    elif sheet["org_id"] is not None and r["org_id"] != sheet["org_id"]:
        out = None
    else:
        out = r
    cache[key] = out
    return out


def sh_source(c, sheet, uid, typ, sid):
    """The source row the viewer may use, None (denied) or "deleted"."""
    if typ == "k":
        return sh_client_ok(c, sheet, uid, sid)
    return sh_list_ok(c, sheet, uid, sid)  # a project that became a list keeps its values (the id decides)


def sh_sources(c, sheet, uid, typ):
    """[(id, slug, name)] of the sources of a kind the viewer may use in this sheet, slugs unique (_2, _3 by id)."""
    cache = _cache(c, uid)
    key = ("S", typ, sheet["org_id"])
    if key in cache:
        return cache[key]
    if typ == "k":
        ids = sorted(_client_visible_ids(c, uid, cache))
        rows = c.execute(f"SELECT id, name, org_id FROM clients WHERE id IN ({','.join(str(int(x)) for x in ids) or '0'}) ORDER BY id").fetchall()
        rows = [r for r in rows if sheet["org_id"] is None or r["org_id"] == sheet["org_id"]]
    else:
        q = f"SELECT id, name, org_id, kind FROM lists WHERE id IN {vis_sql()} AND e2e IS NULL AND is_inbox=0"
        if typ == "p":
            q += " AND kind='project'"
        rows = [r for r in c.execute(q + " ORDER BY id", (uid, uid)).fetchall()
                if (sheet["org_id"] is None or r["org_id"] == sheet["org_id"]) and sh_list_ok(c, sheet, uid, r["id"]) not in (None, "deleted")]
    out, seen = [], {}
    for r in rows:
        base = sh_slug(r["name"]) or f"{SH_VAR_WORD[typ]}{r['id']}"
        n = seen.get(base, 0) + 1
        seen[base] = n
        out.append((r["id"], base if n == 1 else f"{base}_{n}", r["name"]))
    cache[key] = out
    return out


def sh_slug_of(c, sheet, uid, typ, sid):
    return next((s for i, s, _ in sh_sources(c, sheet, uid, typ) if i == sid), None)


def sh_id_of(c, sheet, uid, typ, slug):
    slug = slug.lower()
    return next((i for i, s, _ in sh_sources(c, sheet, uid, typ) if s == slug), None)


def _list_hours(c, uid, lid):
    from ..personal.timetrack import evis, th_sql
    s = c.execute(f'SELECT COALESCE(SUM(seconds), 0) FROM time_entries WHERE "end" IS NOT NULL AND list_id=? '
                  f'AND {evis(c, uid, "")} AND {th_sql("")}', (lid,)).fetchone()[0]
    return round((s or 0) / 3600, 2)


def _list_budget(c, uid, lid):
    """The sum of the list's number field called "Budget h" (any language, like personal/timetrack.py time_list_totals);
    None without one or for a participant (who sees only some tasks)."""
    from ..core.access import plists
    from ..core.i18n import LANGS, tr
    from ..personal.timetrack import BUDGET_FIELD_NAMES
    if lid in set(plists(c, uid)):
        return None
    names = set(BUDGET_FIELD_NAMES) | {tr("Budget h", lg=x).lower() for x in LANGS}
    tot, found = 0.0, False
    for f in c.execute("SELECT id, name FROM list_fields WHERE list_id=? AND type='number'", (lid,)).fetchall():
        if (f["name"] or "").strip().lower() not in names:
            continue
        found = True
        for (v,) in c.execute("SELECT v.value FROM task_field_values v JOIN tasks t ON t.id=v.task_id WHERE v.field_id=? "
                              "AND t.deleted_at IS NULL", (f["id"],)):
            try:
                x = float(str(v).replace(",", "."))
            except (TypeError, ValueError):
                continue
            if math.isfinite(x) and x > 0:
                tot += x
    return round(tot, 2) if found else None


def _list_counts(c, uid, lid):
    r = c.execute(f"SELECT COUNT(*), SUM(CASE WHEN status=0 THEN 1 ELSE 0 END), SUM(CASE WHEN status=2 THEN 1 ELSE 0 END) "
                  f"FROM tasks WHERE list_id=? AND deleted_at IS NULL AND {tvis(c, uid)}", (lid,)).fetchone()
    return float(r[0] or 0), float(r[1] or 0), float(r[2] or 0)


def sh_list_field(c, uid, lid, field):
    cache = _cache(c, uid)
    key = ("LF", lid, field)
    if key in cache:
        return cache[key]
    if field == "zeit_gesamt":
        v = _list_hours(c, uid, lid)
    elif field in ("aufgaben", "offen", "erledigt"):
        a, o, e = _list_counts(c, uid, lid)
        v = {"aufgaben": a, "offen": o, "erledigt": e}[field]
    elif field == "budget_h":
        v = _list_budget(c, uid, lid)
    else:
        raise ShErr("ref")
    v = float(v) if v is not None else None
    cache[key] = v
    return v


def sh_client_field(c, sheet, uid, r, field):
    if field == "satz":
        return float(r["rate"]) if r["rate"] is not None else None
    if field == "budget_h":
        return float(r["budget_h"]) if r["budget_h"] is not None else None
    if field == "budget_betrag":
        return float(r["budget_amount"]) if r["budget_amount"] is not None else None
    if field == "zeit_gesamt":
        tot, cap = 0.0, _agent_cap(c, uid) if _is_agent(c, uid) else None
        for (lid,) in c.execute("SELECT id FROM lists WHERE client_id=?", (r["id"],)).fetchall():
            if list_role(c, lid, uid) and (cap is None or lid in cap):
                tot += sh_list_field(c, uid, lid, "zeit_gesamt") or 0.0
        return round(tot, 2)
    raise ShErr("ref")


def sh_var_value(c, sheet, uid, typ, sid, field):
    """The value of {typ:sid}.field for viewer uid (float | None); ShErr denied / deleted / ref."""
    if field not in sh_fields_of(typ):
        raise ShErr("ref")
    r = sh_source(c, sheet, uid, typ, sid)
    if r == "deleted":
        raise ShErr("deleted")
    if r is None:
        raise ShErr("denied")
    if typ == "k":
        return sh_client_field(c, sheet, uid, r, field)
    return sh_list_field(c, uid, sid, field)


def sh_here_value(c, sheet, uid, field):
    """hier.<field> = the attached project / list (a sheet without one: "ref")."""
    if not sheet["list_id"]:
        raise ShErr("ref")
    if field not in SH_LIST_FIELDS:
        raise ShErr("ref")
    return sh_var_value(c, sheet, uid, "l", sheet["list_id"], field)
