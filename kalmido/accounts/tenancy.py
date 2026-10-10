"""2.30.0 (#1036): the boundary between workspaces beyond lists -- calendars and address books get their workspace once
(ws_migrate_objs), and a nightly boundary check counts every membership that crosses it (boundary_check): people in an
organisation's list / calendar / address book who are not its members (directly or through a group), agents in an object of
another workspace, owners outside the organisation of their object, agents of an organisation their owner left. A finding
is an admin alert (kind security, ids and counts only, once per new set of findings); the count is in GET /api/admin/orgs.
2.36.2 (#1142): memberships in an organisation's object of people outside it are removed by the nightly run (boundary_repair)."""
import hashlib
import json
import os

from ..core.i18n import N_
from ..core.db import gset, gsetting, iso, local_now, now_utc
from ..accounts.orgs import PRIVATE_FOLDER_RE, has_workspaces, instance_mode, main_org

# when the check runs: once a day at this local hour or later; KALMIDO_TENANT_CHECK=always = at every watchdog tick (tests)
TENANT_CHECK_HOUR = int(os.environ.get("KALMIDO_TENANT_CHECK_HOUR", "3") or 3)
TENANT_CHECK_ENV = os.environ.get("KALMIDO_TENANT_CHECK", "").strip().lower()
TENANT_SAMPLE = 20

# kind -> (what it counts, SQL returning (object id, user id)). Every row is one membership across the boundary.
# Persons: an organisation's object (org_id set) for somebody who is not in org_members of that organisation. Agents: the
# agent's workspace (agents.org_id, NULL = private) differs from the object's. Rows that only come from a group share
# (list_members.grole set, no own role) are counted as "group".
_PERSON = "u.kind!='agent' AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id={o}.org_id AND om.user_id={m}.user_id)"
CHECKS = {
    "list_person": ("SELECT m.list_id, m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id JOIN users u ON u.id=m.user_id "
                    "WHERE l.org_id IS NOT NULL AND NOT (m.grole IS NOT NULL AND m.own_role IS NULL) AND " + _PERSON.format(o="l", m="m")),
    "group": ("SELECT m.list_id, m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id JOIN users u ON u.id=m.user_id "
              "WHERE l.org_id IS NOT NULL AND m.grole IS NOT NULL AND m.own_role IS NULL AND " + _PERSON.format(o="l", m="m")
              + " AND EXISTS (SELECT 1 FROM group_members gm WHERE gm.user_id=m.user_id)"),
    "list_agent": ("SELECT m.list_id, m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id JOIN agents a ON a.user_id=m.user_id "
                   "WHERE COALESCE(a.org_id,0)!=COALESCE(l.org_id,0)"),
    "list_owner": ("SELECT l.id, l.owner_id FROM lists l JOIN users u ON u.id=l.owner_id WHERE l.org_id IS NOT NULL AND u.kind!='agent' "
                   "AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=l.org_id AND om.user_id=l.owner_id)"),
    "cal_person": ("SELECT m.cal_id, m.user_id FROM ev_cal_members m JOIN ev_cals k ON k.id=m.cal_id JOIN users u ON u.id=m.user_id "
                   "WHERE k.org_id IS NOT NULL AND " + _PERSON.format(o="k", m="m")),
    "cal_agent": ("SELECT m.cal_id, m.user_id FROM ev_cal_members m JOIN ev_cals k ON k.id=m.cal_id JOIN agents a ON a.user_id=m.user_id "
                  "WHERE COALESCE(a.org_id,0)!=COALESCE(k.org_id,0)"),
    "cal_owner": ("SELECT k.id, k.owner_id FROM ev_cals k JOIN users u ON u.id=k.owner_id WHERE k.org_id IS NOT NULL AND u.kind!='agent' "
                  "AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=k.org_id AND om.user_id=k.owner_id)"),
    "book_person": ("SELECT m.book_id, m.user_id FROM book_members m JOIN books b ON b.id=m.book_id JOIN users u ON u.id=m.user_id "
                    "WHERE b.org_id IS NOT NULL AND " + _PERSON.format(o="b", m="m")),
    "book_agent": ("SELECT m.book_id, m.user_id FROM book_members m JOIN books b ON b.id=m.book_id JOIN agents a ON a.user_id=m.user_id "
                   "WHERE COALESCE(a.org_id,0)!=COALESCE(b.org_id,0)"),
    "book_owner": ("SELECT b.id, b.owner_id FROM books b JOIN users u ON u.id=b.owner_id WHERE b.org_id IS NOT NULL AND u.kind!='agent' "
                   "AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=b.org_id AND om.user_id=b.owner_id)"),
    # an agent of an organisation that is gone, or a personal agent working in an organisation its owner is not in
    "agent": ("SELECT a.user_id, a.owner_id FROM agents a WHERE a.org_id IS NOT NULL AND (NOT EXISTS (SELECT 1 FROM orgs o WHERE o.id=a.org_id) "
              "OR (a.owner_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM org_members om WHERE om.org_id=a.org_id AND om.user_id=a.owner_id)))"),
}
TENANT_ALERT = N_("Workspace boundary check: {0} memberships cross the boundary between organisations / private ({1}). Settings > Administration > Organisations")


def boundary_check(c):
    """{n, kinds: {kind: count}, sample: {kind: [[object id, user id], ...]}} over the whole server (0 without workspaces)."""
    out = {"n": 0, "kinds": {}, "sample": {}}
    if not has_workspaces(c):
        return out
    for k, sql in CHECKS.items():
        rows = c.execute(sql + " ORDER BY 1, 2").fetchall()
        if rows:
            out["kinds"][k] = len(rows)
            out["sample"][k] = [[r[0], r[1]] for r in rows[:TENANT_SAMPLE]]
            out["n"] += len(rows)
    return out


# 2.36.2 (#1142): memberships of PEOPLE in an organisation's object who are not members of that organisation are taken out
# (like org_leave) instead of only counted -- the same rule the read layer applies (core/access.py acx_org_ok).
# kind -> (member table, object column). Agents of another workspace stay counted only: the read layer already hides the
# object from them, and moving the agent to the right workspace brings its access back. Owners outside their organisation
# and agents whose owner left stay counted as before.
REPAIR = {"list_person": ("list_members", "list_id"), "group": ("list_members", "list_id"),
          "cal_person": ("ev_cal_members", "cal_id"), "book_person": ("book_members", "book_id")}
TENANT_REPAIRED = N_("Workspace boundary check: {0} memberships across the boundary between organisations were removed ({1}). Settings > Administration > Organisations")


def boundary_repair(c):
    """Takes out every membership in an organisation's list / calendar / address book of a person who is not a member of
    that organisation. {kind: [[object id, user id], ...]} of what was removed; the
    caller commits."""
    out = {}
    if not has_workspaces(c):
        return out
    for k, (table, col) in REPAIR.items():
        rows = c.execute(CHECKS[k] + " ORDER BY 1, 2").fetchall()
        done = []
        for oid_, uid in rows:
            c.execute(f"DELETE FROM {table} WHERE {col}=? AND user_id=?", (oid_, uid))
            if table == "list_members":
                c.execute("UPDATE tasks SET assignee_id=NULL WHERE list_id=? AND assignee_id=?", (oid_, uid))
                c.execute("DELETE FROM task_people WHERE user_id=? AND task_id IN (SELECT id FROM tasks WHERE list_id=?)", (uid, oid_))
            done.append([oid_, uid])
        if done:
            out[k] = done
    return out


def boundary_last(c):
    try:
        d = json.loads(gsetting(c, "tenant_check") or "{}")
    except ValueError:
        d = {}
    return d if isinstance(d, dict) else {}


def boundary_tick(c):
    """Watchdog: the boundary check once a night (KALMIDO_TENANT_CHECK_HOUR, default 3:00 local time; =always: every tick).
    Stores the result (setting tenant_check) and raises an admin alert when there are findings that were not reported
    before (the same findings are not repeated every night; the count stays visible in the administration)."""
    from ..notify.alerts import aa_now
    now = local_now()
    last = boundary_last(c)
    if TENANT_CHECK_ENV != "always":
        if TENANT_CHECK_ENV in ("0", "off", "no") or now.hour < TENANT_CHECK_HOUR or last.get("day") == now.date().isoformat():
            return
    fixed = boundary_repair(c)  # 2.36.2 (#1142): repaired, not only counted
    if fixed:
        n = sum(len(v) for v in fixed.values())
        aa_now("security", "tenantfix|" + hashlib.sha256(json.dumps(fixed, sort_keys=True).encode()).hexdigest()[:16], TENANT_REPAIRED,
               [n, ", ".join(f"{k} {len(v)}" for k, v in sorted(fixed.items()))])
        print(f"boundary check (#1142): {n} memberships across the workspace boundary removed "
              f"{json.dumps({k: v[:TENANT_SAMPLE] for k, v in fixed.items()})}", flush=True)
        c.commit()
    res = boundary_check(c)
    sig = hashlib.sha256(json.dumps(res["sample"], sort_keys=True).encode()).hexdigest()[:16] if res["n"] else ""
    rec = {"day": now.date().isoformat(), "at": iso(now_utc()), "n": res["n"], "kinds": res["kinds"], "sig": sig,
           "alerted": last.get("alerted", "")}
    if res["n"] and sig != last.get("alerted"):
        aa_now("security", "tenant|" + sig, TENANT_ALERT, [res["n"], ", ".join(f"{k} {v}" for k, v in sorted(res["kinds"].items()))])
        rec["alerted"] = sig
        print(f"boundary check (#1036): {res['n']} memberships across the workspace boundary {json.dumps(res['kinds'])}", flush=True)
    elif not res["n"]:
        rec["alerted"] = ""
    gset(c, "tenant_check", json.dumps(rec, separators=(",", ":")))
    c.commit()


def boundary_summary(c):
    """For GET /api/admin/orgs: the live count + when the nightly check ran last."""
    res = boundary_check(c)
    last = boundary_last(c)
    return {"violations": res["n"], "kinds": res["kinds"], "sample": res["sample"], "checked_at": last.get("at") or None}


# ---------------------------------------------------------------- the workspace of calendars and address books, once
def _obj_ws(c, members_sql, obj_id, cand):
    """The workspace an existing calendar / address book gets: cand (the owner's organisation) when every member fits it,
    else private when every member fits that, else None + mismatch (private, flagged by the boundary check)."""
    rows = c.execute(members_sql, (obj_id,)).fetchall()
    def fits(oid):
        for r in rows:
            if r["kind"] == "agent":
                if (r["a_org"] or None) != (oid or None):
                    return False
            elif oid and not c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, r["user_id"])).fetchone():
                return False
        return True
    if cand and fits(cand):
        return cand, False
    return None, not fits(None)


def ws_migrate_objs(c):
    """2.30.0 (#1036), once (like ws_migrate for lists): every calendar and address book gets its workspace. Up to 2.29 every
    object of a server with an organisation was the organisation's, so it goes into its owner's (first) organisation -- unless
    it is clearly private (named like "Private" / "Family" / "Home", an address book mirrored from an outside account) or a
    member does not fit (an agent of another workspace, a person outside the organisation): then it stays private. Nobody
    loses access: shares stay as they are; an agent that fits neither is kept and counted by the boundary check. The caller
    commits."""
    if gsetting(c, "migr_ws2300") == "1":
        return
    if not has_workspaces(c):
        return  # no flag yet: a server that gets organisations later (mode switch) still migrates then
    gset(c, "migr_ws2300", "1")
    org_of = {r["user_id"]: r["oid"] for r in c.execute("SELECT user_id, MIN(org_id) AS oid FROM org_members GROUP BY user_id")}
    if instance_mode(c) == "organisation":
        mo = main_org(c)
        for (uid,) in c.execute("SELECT id FROM users"):
            org_of.setdefault(uid, mo)
    for (u, o) in c.execute("SELECT user_id, org_id FROM agents WHERE org_id IS NOT NULL").fetchall():
        org_of[u] = o  # an agent's calendar / address book: its own workspace
    for u in [r[0] for r in c.execute("SELECT user_id FROM agents WHERE org_id IS NULL")]:
        org_of.pop(u, None)
    cnt = {"cal": [0, 0, 0], "book": [0, 0, 0]}  # org, private, mismatch
    mem = "SELECT m.user_id, u.kind, a.org_id AS a_org FROM {t} m JOIN users u ON u.id=m.user_id LEFT JOIN agents a ON a.user_id=m.user_id WHERE m.{k}=?"
    for kind, table, mt, key, extra in (("cal", "ev_cals", "ev_cal_members", "cal_id", ""), ("book", "books", "book_members", "book_id", ", src_id")):
        for r in c.execute(f"SELECT id, owner_id, name{extra} FROM {table} WHERE org_id IS NULL").fetchall():
            cand = org_of.get(r["owner_id"])
            if PRIVATE_FOLDER_RE.match((r["name"] or "").strip()) or (kind == "book" and r["src_id"]):
                cand = None
            oid, bad = _obj_ws(c, mem.format(t=mt, k=key), r["id"], cand)
            if oid:
                c.execute(f"UPDATE {table} SET org_id=? WHERE id=?", (oid, r["id"]))
                cnt[kind][0] += 1
            else:
                cnt[kind][1] += 1
                cnt[kind][2] += 1 if bad else 0
    print("workspaces (#1036): calendars {} in their organisation, {} private ({} with a member of another workspace, kept); "
          "address books {} / {} ({})".format(*cnt["cal"], *cnt["book"]), flush=True)
