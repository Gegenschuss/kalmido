"""Organisations (#752) and workspaces (2.28.0, #935): people in 1..n organisations, whom a person may see, which
workspace (private / an organisation) a list and an agent belong to, the organisation's own admins."""
import os
import re

from flask import g, jsonify

from ..core.config import app
from ..core.pg import insert_id, like_escape, system_ctx
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, gset, gsetting, iso, now_utc
from ..accounts.session import me
from ..core.access import Denied


# ---------------------------------------------------------------- 2.22.0 (#752): organisations
# Built the way a hosted service uses them later: an organisation is its own thing (name, an emoji), people belong to
# one or more. The instance setting "people_visibility" says whom a person sees in the share dialog, the user list, as
# an attendee or a new owner:
#   all       everyone (as before 2.22)
#   org       only people of their own organisations (the default once there is one; one company per instance)
#   contacts  only people they are connected with: a list in common, a group in common, a child / its parents (a shared
#             instance of many households and companies: no directory; one shares by e-mail address and learns
#             nothing about whether an address has an account)
# Admins always see everyone (not in the mode "workspaces", see below). Filtered on the server (GET /api/users, sharing,
# attendees, owners), never only in the app.
VIS_MODES = ("all", "org", "contacts")
ORG_NAME_MAX = 60

# 2.23.0 (#799): the kind of instance is set when it is set up, not in the app (later by the operator console):
#   KALMIDO_INSTANCE_MODE=organisation  exactly one organisation (KALMIDO_ORG_NAME, else the name the first-run setup asked
#                                       for / the instance's domain); every account is a member; admins see its name only
#                                       (renaming = the configuration); people see the people of the organisation
#   KALMIDO_INSTANCE_MODE=shared        a shared (Basic) instance of many households: no organisations, people see only their
#                                       own contacts (fixed)
#   KALMIDO_INSTANCE_MODE=workspaces    2.28.0 (#935): one account, several workspaces. Organisations are workspaces on a
#                                       shared server: a person sees the members of their own organisations and the people
#                                       they are connected with (a list / group in common, their kids, their agents) --
#                                       nobody else, instance admins included. Organisations are created by the instance
#                                       admin (the operator); each has its own admins (org_members.role = admin) who manage
#                                       its members, name and e-mail domains. Private sharing stays invisible to the
#                                       organisation. The login page names no organisation.
#   not set                             workspaces
# 2.46.0 (#1592): the modes "organisation" and "multi" are gone: every instance is "workspaces" (organisations + everyone's
# private space) unless KALMIDO_INSTANCE_MODE=shared is set. Whom a person sees: the members of their organisations + their
# connections (a person outside every organisation: only their connections; sharing by e-mail address / user name reaches
# others without telling whether the account exists). An instance without any organisation (a household): everyone sees
# everyone, as before. KALMIDO_INSTANCE_MODE=organisation is ignored (a hint at
# start-up); nobody is put into an organisation automatically any more, memberships and roles stay as they are.
# KALMIDO_ORG_NAME only names the organisation the first-run setup creates. The admin API creates or deletes organisations
# in the mode "workspaces" (403 in shared).
#
# WORKSPACES (2.28.0, #935), in every mode with organisations (organisation, multi, workspaces): every list belongs to a
# workspace -- its owner's private space (lists.org_id NULL) or one of the owner's organisations (lists.org_id). An
# organisation's list is shared only with the organisation's members and the agents of that organisation; a private list
# with anyone the owner may see, but never with an organisation's agents (agents.org_id: the one workspace an agent works
# in; NULL = private). "Used for" (family / household) and Home & life lists are private only. The owner changes a list's
# workspace in the list dialog (refused while people or agents in it do not fit the new one). The app shows one workspace
# at a time (the sidebar's switch, setting "workspace"): the lists, tasks, News, agents and team chats of that workspace.
INSTANCE_MODES = ("shared", "workspaces")  # 2.46.0 (#1592): "organisation" is ignored
INSTANCE_ENV = os.environ.get("KALMIDO_INSTANCE_MODE", "").strip().lower()
ORG_NAME_ENV = re.sub(r"\s+", " ", os.environ.get("KALMIDO_ORG_NAME", "")).strip()[:ORG_NAME_MAX]
ORG_ROLES = ("member", "admin")
# folder names (the top folder of a list's owner) that mark a list as private when the workspaces arrive (ws_migrate)
PRIVATE_FOLDER_RE = re.compile(r"^(privat|private|pers[öo]nlich|personal|familie|family|zuhause|zu hause|home|haushalt|household|privé|prive|privado|personale|privato|thuis)$", re.I)
WS_MSG_PERSON = N_("{0} is not a member of the organisation {1}: share this list privately instead, or let an organisation admin add the person")
WS_MSG_AGENT = N_("{0} works in another workspace ({1}): an agent joins only lists of its own workspace")
WS_MSG_OWNER = N_("You are not a member of this organisation")
# 2.30.0 (#1036): calendars and address books follow the same rule
WS_MSG_PERSON_OBJ = N_("{0} is not a member of the organisation {1}: only its members can be in its calendars and address books")
WS_MSG_AGENT_OBJ = N_("{0} works in another workspace ({1}): an agent joins only calendars and address books of its own workspace")
WS_MSG_PRIVATE_ONLY = N_("Family, household and Home & life lists are private: they cannot belong to an organisation")


def instance_mode(c=None):
    """2.46.0 (#1592): shared when set so explicitly, else workspaces (no automatic mode by the number of organisations)."""
    return "shared" if INSTANCE_ENV == "shared" else "workspaces"


def main_org(c):
    with system_ctx(c):  # 2.37.0 (#1150): instance structure (the first organisation's id)
        r = c.execute("SELECT id FROM orgs WHERE personal_of IS NULL ORDER BY id LIMIT 1").fetchone()
    return r[0] if r else None


def has_workspaces(c):
    """2.28.0 (#935): the instance knows organisations (any mode but shared) -> lists and agents have a workspace."""
    if instance_mode(c) == "shared":
        return False
    with system_ctx(c):  # 2.37.0 (#1150): instance structure
        return bool(c.execute("SELECT 1 FROM orgs WHERE personal_of IS NULL LIMIT 1").fetchone())


def instance_sync(c):
    """At every start (init_db). 2.46.0 (#1592): puts nobody into an organisation and changes no roles or names any more;
    only says that a former mode setting is ignored. Once, on the first start of 2.46: a server that was in the former
    automatic mode "organisation" (one organisation, no mode set) gets the last sync it did at every start (every account
    a member, the instance's admins its admins), so everybody keeps exactly what they saw; nothing after that."""
    if INSTANCE_ENV and INSTANCE_ENV not in ("shared", "workspaces"):
        print(f"KALMIDO_INSTANCE_MODE={INSTANCE_ENV} is deprecated and ignored: organisations + private spaces (workspaces)", flush=True)
    if gsetting(c, "migr_om2460") == "1":
        return
    gset(c, "migr_om2460", "1")
    if INSTANCE_ENV not in ("", "organisation"):
        return
    with system_ctx(c):  # instance structure
        oids = [r[0] for r in c.execute("SELECT id FROM orgs WHERE personal_of IS NULL ORDER BY id LIMIT 2")]
        if len(oids) != 1:
            return
        n = c.execute("INSERT INTO org_members(org_id,user_id) SELECT ?, id FROM users ON CONFLICT DO NOTHING", (oids[0],)).rowcount
        n += c.execute("UPDATE org_members SET role='admin' WHERE org_id=? AND role!='admin' AND user_id IN (SELECT id FROM users WHERE is_admin=1 AND kind!='agent')", (oids[0],)).rowcount
    print(f"organisations (#1592): the former mode organisation synced once ({n} rows)", flush=True)


def om_setup_org(c, uid, name):
    """2.46.0 (#1592): the first-run setup creates the instance's first organisation (name given, else KALMIDO_ORG_NAME)
    with the setting-up admin as its admin; nothing when there is one already, no name or the mode shared. The caller
    commits. Returns the new id or None."""
    nm = re.sub(r"\s+", " ", str(name or "")).strip()[:ORG_NAME_MAX] or ORG_NAME_ENV
    if not nm or instance_mode(c) == "shared":
        return None
    with system_ctx(c):  # instance structure: is there an organisation at all
        if c.execute("SELECT 1 FROM orgs WHERE personal_of IS NULL LIMIT 1").fetchone():
            return None
        oid = insert_id(c, "INSERT INTO orgs(name,icon,created_at) VALUES(?,?,?)", (nm, "", iso(now_utc())))
        org_member_add(c, oid, uid, "admin")
    return oid


def vis_mode(c):
    m = instance_mode(c)
    if m == "shared":
        return "contacts"
    return "org"  # 2.46.0 (#1592): workspaces


def user_orgs(c, uid):
    m = instance_mode(c)
    if m == "shared":
        return []
    with system_ctx(c):  # 2.37.0 (#1150): memberships are structure the access rules need (also of other people)
        return [r[0] for r in c.execute("SELECT org_id FROM org_members WHERE user_id=? ORDER BY org_id", (uid,))]


def org_member_add(c, oid, uid, role="member"):
    """2.36.2 (#1142): add uid to organisation oid (nothing when already in) and refresh the request's access contexts."""
    c.execute("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,?) ON CONFLICT (org_id, user_id) DO NOTHING", (oid, uid, role))
    from ..core.access import acx_drop
    acx_drop()


def org_names(c, uid):
    with system_ctx(c):  # 2.37.0 (#1150): the names of uid's own organisations (also before a login: mails, the login page)
        return [r[0] for r in c.execute(f"SELECT name FROM orgs WHERE id IN ({','.join(str(int(x)) for x in user_orgs(c, uid)) or 'NULL'}) ORDER BY id")]


def org_role(c, uid, oid):
    """2.28.0 (#935): member | admin | None -- the person's role in organisation oid."""
    if not oid or oid not in user_orgs(c, uid):
        return None
    with system_ctx(c):  # 2.37.0 (#1150): membership structure (also asked for other people)
        r = c.execute("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
    return (r["role"] if r["role"] in ORG_ROLES else "member") if r else None


def is_org_admin(c, uid, oid):
    return org_role(c, uid, oid) == "admin"


def _connections(c, uid):
    """The people uid is connected with: a list / group in common, their kids / parents, their own agents, their chats, an
    accepted connection request (2.49.0, #1106, accounts/discover.py)."""
    rows = c.execute("""SELECT m2.user_id FROM list_members m1 JOIN list_members m2 ON m2.list_id=m1.list_id WHERE m1.user_id=?
                        UNION SELECT l.owner_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE m.user_id=?
                        UNION SELECT m.user_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE l.owner_id=?
                        UNION SELECT g2.user_id FROM group_members g1 JOIN group_members g2 ON g2.group_id=g1.group_id WHERE g1.user_id=?
                        UNION SELECT parent_id FROM kid_parents WHERE kid_id=? UNION SELECT kid_id FROM kid_parents WHERE parent_id=?
                        UNION SELECT user_id FROM agents WHERE owner_id=?
                        UNION SELECT b_id FROM conn_links WHERE a_id=? AND deleted_at IS NULL
                        UNION SELECT a_id FROM conn_links WHERE b_id=? AND deleted_at IS NULL""", (uid,) * 9).fetchall()  # 2.49.0 (#1106): accepted requests
    return {r[0] for r in rows}


def visible_people(c, uid):
    """None = everyone; else the set of user ids uid may see (uid included). 2.37.0 (#1150): computed over the memberships
    as "system" (ids only), so the rule is the same whoever asks -- row-level security does not narrow it."""
    with system_ctx(c):
        return _visible_people(c, uid)


def _visible_people(c, uid):
    u = c.execute("SELECT is_admin FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return None
    m = instance_mode(c)
    if m == "workspaces":  # 2.28.0 (#935): the members of my organisations + my connections; admins are no exception
        orgs = user_orgs(c, uid)
        ids = set()
        if orgs:
            q = ",".join("?" * len(orgs))
            ids = {r[0] for r in c.execute(f"SELECT user_id FROM org_members WHERE org_id IN ({q})", orgs)}
        elif not c.execute("SELECT 1 FROM orgs WHERE personal_of IS NULL LIMIT 1").fetchone():
            return None  # 2.46.0 (#1592): an instance without any organisation (a household): everyone, as before
        return ids | _connections(c, uid) | {uid}
    if u[0]:
        return None  # shared: admins see everyone
    return _connections(c, uid) | {uid}  # shared: contacts


def may_see(c, uid, other):
    v = visible_people(c, uid)
    return v is None or other in v


def need_visible(c, other):
    """404 (as for an unknown user) when the current person must not see `other`."""
    if not may_see(c, me(), other):
        raise Denied(404, tr("unknown user"))


def org_public(c, r, roles=True):
    d = {"id": r["id"], "name": r["name"], "icon": r["icon"], "domains": r["domains"],  # 2.23.0 (#711): e-mail domains
         "members": [x[0] for x in c.execute("SELECT user_id FROM org_members WHERE org_id=? ORDER BY user_id", (r["id"],))]}
    if roles:  # 2.28.0 (#935): the organisation's admins
        d["admins"] = [x[0] for x in c.execute("SELECT user_id FROM org_members WHERE org_id=? AND role='admin' ORDER BY user_id", (r["id"],))]
    return d


def org_label(c, uid=None):
    """The organisation name to show next to the app name. 2.46.0 (#1592): none -- workspaces show the switch instead, and
    the login page names no organisation (#1552)."""
    return ""


# ---------------------------------------------------------------- 2.28.0 (#935): workspaces of lists and agents
def workspaces_for(c, uid):
    """[{id, name, icon, role}] -- the organisations uid belongs to, with the person's role (the app's switch)."""
    oids = user_orgs(c, uid)
    if not oids:
        return []
    q = ",".join("?" * len(oids))
    # 2.53.0 B (#1474): + color (the organisation's colour, '' = the default tone of its id)
    return [{"id": r["id"], "name": r["name"], "icon": r["icon"], "color": r["color"] or "", "role": org_role(c, uid, r["id"]) or "member"}
            for r in c.execute(f"SELECT id, name, icon, color FROM orgs WHERE id IN ({q}) ORDER BY id", oids)]


def list_org(c, lid):
    r = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()
    return r["org_id"] if r else None


def agent_org(c, aid):
    with system_ctx(c):  # 2.37.0 (#1150): an agent's workspace is structure the boundary rules need (also for foreign agents)
        r = c.execute("SELECT org_id FROM agents WHERE user_id=?", (aid,)).fetchone()
    return r["org_id"] if r else None


def _org_name(c, oid):
    r = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone() if oid else None
    return r[0] if r else tr("Private|workspace")


def ws_member_problem(c, lid, uid, org_id=None):
    """2.28.0 (#935): the reason (translated) why uid cannot be in list lid, or None. org_id: check against this workspace
    instead of the list's current one. A person: an organisation's list only for its members. An agent: only lists of its
    own workspace (agents.org_id == lists.org_id)."""
    if not has_workspaces(c):
        return None
    return ws_fit_problem(c, list_org(c, lid) if org_id is None else (org_id or None), uid)


def ws_fit_problem(c, oid, uid, kind="list"):
    """2.30.0 (#1036): THE workspace rule for every shared object (lists, calendars, address books): the reason (translated)
    why uid cannot be in an object of workspace oid (None = private), or None. A person: an organisation's object only for
    its members. An agent: only objects of its own workspace (agents.org_id == the object's org_id; so a private object
    never reaches an organisation's agent). kind: list | cal | book (the wording of the answer)."""
    if not has_workspaces(c):
        return None
    oid = oid or None
    u = c.execute("SELECT kind, display_name, username FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return None
    name = u["display_name"] or u["username"]
    if (u["kind"] or "user") == "agent":
        a_oid = agent_org(c, uid)
        if (a_oid or None) != (oid or None):
            return tr(WS_MSG_AGENT if kind == "list" else WS_MSG_AGENT_OBJ, name, _org_name(c, a_oid))
        return None
    if oid and oid not in user_orgs(c, uid):
        return tr(WS_MSG_PERSON if kind == "list" else WS_MSG_PERSON_OBJ, name, _org_name(c, oid))
    return None


def ws_check_member(c, lid, uid, org_id=None):
    """Denied(409) when uid does not fit the list's workspace (see ws_member_problem)."""
    p = ws_member_problem(c, lid, uid, org_id)
    if p:
        raise Denied(409, p)


def ws_obj_default(c, uid):
    """2.30.0 (#1036): the workspace of a new calendar / address book when the client names none: an agent's own workspace,
    else the person's first organisation (as for a new list), else private."""
    if not has_workspaces(c):
        return None
    u = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
    if u and (u["kind"] or "user") == "agent":
        return agent_org(c, uid)
    mine = user_orgs(c, uid)
    return mine[0] if mine else None


def obj_org_set(c, table, oid_col, members, obj_id, v, kind):
    """2.30.0 (#1036): the owner moves calendar / address book obj_id (table ev_cals | books, its member table + key column)
    into workspace v (clean_org_id). Refused (409) while a member (person or agent) does not fit the new workspace (named).
    Returns True when it changed. The caller commits."""
    r = c.execute(f"SELECT owner_id, org_id FROM {table} WHERE id=?", (obj_id,)).fetchone()
    if not r or r["owner_id"] != me():
        raise Denied(403, tr("Only the owner can change the workspace"))
    if (None if v in (None, "", 0, "0", "private") else v) == r["org_id"]:
        return False
    oid = clean_org_id(c, v, me())
    if (oid or None) == (r["org_id"] or None):
        return False
    for (uid,) in c.execute(f"SELECT user_id FROM {members} WHERE {oid_col}=? ORDER BY user_id", (obj_id,)).fetchall():
        p = ws_fit_problem(c, oid, uid, kind)
        if p:
            raise Denied(409, p)
    c.execute(f"UPDATE {table} SET org_id=? WHERE id=?", (oid, obj_id))
    return True


def clean_org_id(c, v, uid):
    """The org_id a client sent for a list: None / 0 / '' = private; else an organisation uid belongs to (409 otherwise)."""
    if v in (None, "", 0, "0", "private"):
        return None
    try:
        oid = int(v)
    except (TypeError, ValueError):
        raise Denied(400, tr("Invalid value: {0}", "org_id")) from None
    if oid not in user_orgs(c, uid):
        raise Denied(409, tr(WS_MSG_OWNER))
    return oid


def list_org_set(c, lid, v):
    """The owner moves list lid into workspace v (clean_org_id). Refused (409) for the inbox, for family / household / Home &
    life lists going into an organisation, and while a member or agent of the list does not fit the new workspace (named)."""
    lr = c.execute("SELECT owner_id, is_inbox, family, life, org_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not lr or lr["owner_id"] != me():
        raise Denied(403, tr("Only the owner can change the workspace of a list"))
    if (None if v in (None, "", 0, "0", "private") else v) == lr["org_id"]:
        return False  # unchanged (the list dialog sends it with every save)
    oid = clean_org_id(c, v, me())
    if lr["is_inbox"] and oid:
        raise Denied(409, tr("The basket is always private"))
    if oid and (lr["family"] or lr["life"]):
        raise Denied(409, tr(WS_MSG_PRIVATE_ONLY))
    if (oid or None) == (list_org(c, lid) or None):
        return False
    for (uid,) in c.execute("SELECT user_id FROM list_members WHERE list_id=? ORDER BY user_id", (lid,)).fetchall():
        ws_check_member(c, lid, uid, org_id=oid or 0)
    c.execute("UPDATE lists SET org_id=? WHERE id=?", (oid, lid))
    from ..admin.orgcrypt_cli import oc_settle_kick
    # 2.42.0 (#828): the list's files get the organisation's key now; 2.64.0 (#1864): out of it the owner's account key
    # (only this list's files, after the request)
    oc_settle_kick([lid])
    return True


def ws_default_org(c, uid, folder=""):
    """The workspace a new list of uid gets when the client names none: the workspace of the other lists of that folder (all
    of them in one), else the person's first organisation (a server with an organisation worked like that up to 2.27: every
    list was the organisation's), else private."""
    if not has_workspaces(c):
        return None
    if folder:
        rows = c.execute("SELECT DISTINCT org_id FROM lists WHERE owner_id=? AND is_inbox=0 AND (folder=? OR folder ILIKE ? ESCAPE '\\')",
                         (uid, folder, like_escape(folder.split("/", 1)[0]) + "/%")).fetchall()
        oids = {r[0] for r in rows}
        if len(oids) == 1:
            return oids.pop()
    mine = user_orgs(c, uid)
    return mine[0] if mine else None


def ws_apply_default(c, uid, lid, folder=""):
    """A list just created by code (a proposal, an import, the sample project): the default workspace of a new list."""
    oid = ws_default_org(c, uid, folder)
    if oid:
        c.execute("UPDATE lists SET org_id=? WHERE id=? AND org_id IS NULL", (oid, lid))


def ws_private_for(c, lid):
    """2.28.0 (#935): "Used for" / Home & life make a list private. Denied(409) while an agent of the organisation is in it."""
    oid = list_org(c, lid)
    if not oid:
        return
    ag = c.execute("""SELECT u.display_name, u.username FROM list_members m JOIN users u ON u.id=m.user_id JOIN agents a ON a.user_id=u.id
                      WHERE m.list_id=? AND a.org_id IS NOT NULL ORDER BY m.user_id LIMIT 1""", (lid,)).fetchone()
    if ag:
        raise Denied(409, tr("{0} works in another workspace ({1}): an agent joins only lists of its own workspace", ag["display_name"] or ag["username"], _org_name(c, oid)))
    c.execute("UPDATE lists SET org_id=NULL WHERE id=?", (lid,))
    from ..admin.orgcrypt_cli import oc_settle_kick
    oc_settle_kick([lid])  # 2.64.0 (#1864): its files get the owner's account key


def ws_migrate(c):
    """2.28.0 (#935), once: every list and agent gets its workspace. On a server with organisations everything was the
    organisation's up to 2.27 (one company per server), so lists stay in their owner's (first) organisation -- except the
    ones that are clearly private: family / household (Used for), Home & life lists, lists in a top folder named like
    "Private" / "Family" / "Home", and everyone's inbox. Agents: team agents work in their organisation, a personal agent in
    the workspace most of its lists are in (ties: private). An agent that already sits in a list of another workspace stays
    there (nothing is removed on an update); the list dialog points it out and the owner decides. Idempotent, the caller
    commits."""
    if gsetting(c, "migr_ws2280") == "1":
        return
    gset(c, "migr_ws2280", "1")
    if not has_workspaces(c):
        return
    org_of = {}
    for r in c.execute("SELECT user_id, MIN(org_id) AS oid FROM org_members GROUP BY user_id"):  # pg-ok: alias, not the system column
        org_of[r["user_id"]] = r["oid"]
    n_org = n_priv = 0
    for r in c.execute("SELECT id, owner_id, folder, family, life, is_inbox FROM lists WHERE org_id IS NULL").fetchall():
        oid = org_of.get(r["owner_id"])
        top = (r["folder"] or "").split("/", 1)[0].strip()
        if not oid or r["is_inbox"] or r["family"] or r["life"] or PRIVATE_FOLDER_RE.match(top):
            n_priv += 1
            continue
        c.execute("UPDATE lists SET org_id=? WHERE id=?", (oid, r["id"]))
        n_org += 1
    for a in c.execute("SELECT a.user_id, a.owner_id FROM agents a JOIN users u ON u.id=a.user_id WHERE u.kind='agent' AND a.org_id IS NULL").fetchall():
        if a["owner_id"] is None:  # a team agent: its organisation (the organisation mode: the one)
            oid = org_of.get(a["user_id"])
        else:  # the workspace most of its lists are in
            cnt = {}
            for (lo,) in c.execute("""SELECT l.org_id FROM lists l WHERE l.is_inbox=0 AND (l.owner_id=? OR l.id IN
                                      (SELECT list_id FROM list_members WHERE user_id=?))""", (a["user_id"], a["user_id"])):
                cnt[lo] = cnt.get(lo, 0) + 1
            oid = max(cnt, key=lambda k: (cnt[k], 0 if k is None else 1)) if cnt else None
            if oid is not None and oid not in user_orgs(c, a["owner_id"]):
                oid = None
        if oid:
            c.execute("UPDATE agents SET org_id=? WHERE user_id=?", (oid, a["user_id"]))
    # the instance's admins administer the organisations they are in
    c.execute("UPDATE org_members SET role='admin' WHERE user_id IN (SELECT id FROM users WHERE is_admin=1 AND kind!='agent')")
    mism = c.execute("""SELECT COUNT(*) FROM list_members m JOIN agents a ON a.user_id=m.user_id JOIN lists l ON l.id=m.list_id
                        WHERE COALESCE(a.org_id,0)!=COALESCE(l.org_id,0)""").fetchone()[0]
    print(f"workspaces (#935): {n_org} lists in their organisation, {n_priv} private, {mism} agent memberships across workspaces (kept)", flush=True)


def ws_mismatches(c, uid):
    """{list id: [agent ids]} -- agents of another workspace in lists uid owns (from before the workspaces; the dialog says so)."""
    out = {}
    if not has_workspaces(c):
        return out
    for r in c.execute("""SELECT m.list_id, m.user_id FROM list_members m JOIN agents a ON a.user_id=m.user_id JOIN lists l ON l.id=m.list_id
                          WHERE l.owner_id=? AND COALESCE(a.org_id,0)!=COALESCE(l.org_id,0) ORDER BY m.list_id, m.user_id""", (uid,)):
        out.setdefault(r["list_id"], []).append(r["user_id"])
    return out


def _clean_name(v):
    if not isinstance(v, str) or not v.strip():
        raise Denied(400, tr("Name missing"))
    return re.sub(r"\s+", " ", v).strip()[:ORG_NAME_MAX]


def _clean_icon(v):
    v = str(v or "").strip()
    return v[:8]


def _clean_domains(v):
    """2.23.0 (#711): "acme.example, @Other.example" -> "acme.example, other.example" (registrations join by these)."""
    if not isinstance(v, str):
        raise Denied(400, tr("Invalid value: {0}", "domains"))
    out = []
    for d in re.split(r"[,\s;]+", v.lower()):
        d = d.strip().lstrip("@")
        if d and "." in d and re.fullmatch(r"[a-z0-9.-]{1,100}", d) and d not in out:
            out.append(d)
    return ", ".join(out[:50])


def _need_admin():
    if not g.user["is_admin"]:
        raise Denied(403)


def _set_members(c, oid, ids):
    if not isinstance(ids, list) or not all(isinstance(x, int) for x in ids):
        raise Denied(400, tr("Invalid value: {0}", "members"))
    have = {r[0] for r in c.execute("SELECT id FROM users")}
    roles = {r[0]: r[1] for r in c.execute("SELECT user_id, role FROM org_members WHERE org_id=?", (oid,))}
    c.execute("DELETE FROM org_members WHERE org_id=?", (oid,))
    for u in sorted(set(ids) & have):
        org_member_add(c, oid, u, roles.get(u, "member"))
    # 2.36.2 (#1142): the people taken out leave the organisation the same way as with an organisation admin (org_leave):
    # they leave its lists, calendars and address books; their lists of this workspace go to an admin who stays
    gone = sorted(set(roles) - set(ids))
    if gone:
        heir = (c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role='admin' "
                          "AND u.disabled=0 AND u.kind!='agent' ORDER BY m.user_id LIMIT 1", (oid,)).fetchone()
                or c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0 AND kind!='agent' ORDER BY id LIMIT 1").fetchone() or [None])[0]
        if heir and not c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, heir)).fetchone():
            org_member_add(c, oid, heir, "admin")  # no admin stays: the operator takes over (like org_member_remove)
        for u in gone:
            org_leave(c, oid, u, heir)


@app.get("/api/admin/orgs")
def orgs_get():
    """2.23.0 (#799): + mode (organisation | shared | multi | workspaces) and whether names / members can be changed here
    (multi and workspaces)."""
    _need_admin()
    c = db()
    with system_ctx(c):  # 2.37.0 (#1150): instance admin: organisation structure (names, members, counts) of every organisation, no content
        m = instance_mode(c)
        rows = [] if m == "shared" else c.execute("SELECT * FROM orgs WHERE personal_of IS NULL ORDER BY lower(name), id").fetchall()  # 2.47.3 (#1360): never the personal offices
        from ..accounts.tenancy import boundary_summary
        return jsonify(orgs=[org_public(c, r) for r in rows], visibility=vis_mode(c), mode=m, editable=m == "workspaces",
                       creatable=m == "workspaces", name_env=bool(ORG_NAME_ENV),
                       boundary=boundary_summary(c))  # 2.30.0 (#1036): memberships across the workspace boundary (0 = clean)


@app.post("/api/admin/orgs/boundary/repair")
def oa_boundary_repair():
    """2.46.0 (#1563): the button "Clean up" of the boundary check: takes out the memberships of people (not agents) in an
    organisation's lists / calendars / address books that are not members of the organisation (tenancy.boundary_repair)."""
    _need_admin()
    from ..accounts.tenancy import boundary_repair, boundary_summary
    c = db()
    with system_ctx(c):
        done = boundary_repair(c)
        if done:
            bump(c)
    c.commit()
    n = sum(len(v) for v in done.values())
    if n:
        print(f"boundary check (#1563): {n} memberships across the workspace boundary removed by an admin", flush=True)
    return jsonify(removed=n, kinds={k: len(v) for k, v in done.items()}, boundary=boundary_summary(c))


def _no_change():
    raise Denied(403, tr("Organisations are set by the server's configuration (KALMIDO_INSTANCE_MODE, KALMIDO_ORG_NAME)"))


@app.post("/api/admin/orgs")
def org_create():
    """2.28.0 (#935): {name, icon?, domains?, admin_id?} -- the instance admin creates an organisation (mode workspaces only;
    2.23.0: 403 elsewhere). admin_id (default: the creating admin) becomes its first member and organisation admin."""
    _need_admin()
    c, b = db(), body()
    with system_ctx(c):  # 2.37.0 (#1150): instance admin manages the organisations themselves (also ones he is not in)
        if instance_mode(c) != "workspaces":
            _no_change()
        name = _clean_name(b.get("name"))
        if c.execute("SELECT 1 FROM orgs WHERE lower(name)=lower(?) AND personal_of IS NULL", (name,)).fetchone():
            return err(tr("An organisation with this name exists"), 409)
        oid = insert_id(c, "INSERT INTO orgs(name,icon,domains,created_at) VALUES(?,?,?,?)",
                        (name, _clean_icon(b.get("icon")), _clean_domains(b.get("domains") or ""), iso(now_utc())))
        adm = b.get("admin_id", me())
        if not isinstance(adm, int) or isinstance(adm, bool) or not c.execute("SELECT 1 FROM users WHERE id=? AND kind!='agent' AND disabled=0", (adm,)).fetchone():
            c.rollback()
            return err(tr("Invalid value: {0}", "admin_id"))
        org_member_add(c, oid, adm, "admin")
        bump(c)
        c.commit()
        print("organisation", name, "(id", oid, ") created by", g.user["username"], flush=True)
        return jsonify(org_public(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone())), 201


@app.patch("/api/admin/orgs/<int:oid>")
def org_update(oid):
    """{name?, icon?, members?: [user ids] (replaces them), domains?} -- only on an instance that kept several organisations
    from 2.22 ("multi") or in the mode workspaces; else 403 (#799)."""
    _need_admin()
    c, b = db(), body()
    with system_ctx(c):  # 2.37.0 (#1150): instance admin manages the organisations themselves (also ones he is not in)
        if instance_mode(c) != "workspaces":
            _no_change()
        if not c.execute("SELECT 1 FROM orgs WHERE id=? AND personal_of IS NULL", (oid,)).fetchone():  # 2.47.3 (#1360)
            return err(tr("Not found"), 404)
        _org_patch(c, oid, b)
        if "members" in b:
            _set_members(c, oid, b["members"])
        if "admins" in b:  # 2.28.0 (#935): the organisation's admins (a subset of its members)
            if not isinstance(b["admins"], list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in b["admins"]):
                c.rollback()
                return err(tr("Invalid value: {0}", "admins"))
            c.execute("UPDATE org_members SET role='member' WHERE org_id=?", (oid,))
            for x in b["admins"]:
                c.execute("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=? AND user_id IN (SELECT id FROM users WHERE kind!='agent')", (oid, x))
        bump(c)
        c.commit()
        return jsonify(org_public(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone()))


def wsc_clean_color(v):
    """2.53.0 B (#1474): an organisation's colour: '' or #rrggbb (the app offers its own palette and shows the nearest tone)."""
    from ..lists.lists import LIST_COLOR_RE
    v = v.strip() if isinstance(v, str) else v
    if v in ("", None):
        return ""
    if not isinstance(v, str) or not LIST_COLOR_RE.fullmatch(v):
        raise Denied(400, tr("Invalid value: {0}", tr("Color")))
    return v


def _org_patch(c, oid, b):
    if "name" in b:
        c.execute("UPDATE orgs SET name=? WHERE id=?", (_clean_name(b["name"]), oid))
    if "icon" in b:
        c.execute("UPDATE orgs SET icon=? WHERE id=?", (_clean_icon(b["icon"]), oid))
    if "domains" in b:
        c.execute("UPDATE orgs SET domains=? WHERE id=?", (_clean_domains(b["domains"]), oid))


@app.delete("/api/admin/orgs/<int:oid>")
def org_delete(oid):
    """2.28.0 (#935): the instance admin deletes an organisation (mode workspaces) -- only one without lists (409 otherwise:
    its owners move or delete them first). 2.23.0: 403 in the other modes."""
    _need_admin()
    c = db()
    with system_ctx(c):  # 2.37.0 (#1150): instance admin manages the organisations themselves (also ones he is not in)
        if instance_mode(c) != "workspaces":
            _no_change()
        if not c.execute("SELECT 1 FROM orgs WHERE id=? AND personal_of IS NULL", (oid,)).fetchone():  # 2.47.3 (#1360)
            return err(tr("Not found"), 404)
        n = c.execute("SELECT COUNT(*) FROM lists WHERE org_id=?", (oid,)).fetchone()[0]
        if n:
            return err(tr("This organisation still has {0} lists: their owners move or delete them first", n), 409)
        from ..files.store import fs_org_live, fs_org_purge
        n = fs_org_live(c, oid)  # 2.48.0 (#1207): nothing of the file store disappears with it (the trash does)
        if n:
            return err(tr("This organisation still has {0} folders and files in its file store: delete them first", n), 409)
        fs_files = fs_org_purge(c, oid)
        c.execute("UPDATE agents SET org_id=NULL WHERE org_id=?", (oid,))
        c.execute("UPDATE ev_cals SET org_id=NULL WHERE org_id=?", (oid,))  # 2.30.0 (#1036): they stay with their owners, private
        c.execute("UPDATE books SET org_id=NULL, owner_org_id=NULL WHERE org_id=?", (oid,))  # 2.52.0 C (#1438): its own books -> the managers'
        # 2.42.0 (#828): files of lists that left the organisation are sealed with their new organisation's key (or plain),
        # then the organisation's key is destroyed (what is left encrypted with it can no longer be read) and its office
        # folder (stored invoices, archive) removed
        from ..admin.orgcrypt_cli import before_org_delete
        from ..core.orgcrypt import oc_drop_key
        if before_org_delete(c, oid)[1]:  # 2.64.0 (#1864): a file that lives on could not be resealed: keep the key
            raise Denied(409, tr("Some files could not be encrypted again for their new place. Nothing was deleted; see the server log."))
        oc_drop_key(c, oid)
        c.execute("DELETE FROM orgs WHERE id=?", (oid,))
        bump(c)
        c.commit()
        oc_drop_office_dir(oid)
        from ..core.serializers import unlink_files
        unlink_files(fs_files)
        return jsonify(ok=True)


def oc_drop_office_dir(oid):
    """2.42.0 (#828): remove the office folder of a deleted organisation (stored documents, archive PDFs, logos)."""
    import shutil
    from ..core.config import OFFICE_DIR
    d = os.path.join(OFFICE_DIR, str(int(oid)))
    if os.path.isdir(d) and not os.path.islink(d):
        shutil.rmtree(d, ignore_errors=True)


@app.put("/api/admin/orgs/visibility")
def org_visibility():
    """{mode: all | org | contacts}: whom people see. 2.46.0 (#1592): fixed (the members of one's organisations +
    connections; shared: own contacts) -- always 403, like the former modes organisation / workspaces."""
    _need_admin()
    _no_change()


# ---------------------------------------------------------------- 2.28.0 (#935): my organisations, their admins
def _need_org_admin(c, oid):
    """The current person administers organisation oid (404 when not even a member)."""
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot use this endpoint"))
    role = org_role(c, me(), oid)
    if not role:
        raise Denied(404)
    if role != "admin":
        raise Denied(403, tr("Only an admin of this organisation can do this"))


def org_mine_dict(c, r, uid):
    from ..collab.comments import user_names
    mem = c.execute("SELECT m.user_id, m.role, u.kind, u.disabled FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? ORDER BY lower(u.display_name), u.id", (r["id"],)).fetchall()
    names = user_names(c, [m["user_id"] for m in mem])
    return {"id": r["id"], "name": r["name"], "icon": r["icon"], "color": r["color"] or "", "domains": r["domains"], "role": org_role(c, uid, r["id"]) or "member",
            "members": [{"id": m["user_id"], "name": names.get(m["user_id"], ""), "role": m["role"] if m["role"] in ORG_ROLES else "member",
                         "agent": (m["kind"] or "user") == "agent", "disabled": bool(m["disabled"])} for m in mem],
            "lists": c.execute("SELECT COUNT(*) FROM lists WHERE org_id=?", (r["id"],)).fetchone()[0]}


@app.get("/api/orgs")
def orgs_mine():
    """2.28.0 (#935): the organisations I belong to (my workspaces), their members and my role; mode + whether an
    organisation admin may manage members here (modes multi / workspaces; in the mode organisation the instance admin does)."""
    from ..agents.core import is_agent
    c = db()
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot use this endpoint"))
    uid = me()
    oids = user_orgs(c, uid)
    rows = c.execute(f"SELECT * FROM orgs WHERE id IN ({','.join('?' * len(oids)) or 'NULL'}) ORDER BY id", oids).fetchall()
    m = instance_mode(c)
    return jsonify(orgs=[org_mine_dict(c, r, uid) for r in rows], mode=m, manage=m == "workspaces", workspaces=has_workspaces(c),
                   mismatches={str(k): v for k, v in ws_mismatches(c, uid).items()})


@app.patch("/api/orgs/<int:oid>")
def org_mine_update(oid):
    """2.28.0 (#935): {name?, icon?, domains?} -- an organisation admin renames it / sets its e-mail domains (modes multi /
    workspaces; in the mode organisation the name comes from the configuration or the instance admin).
    2.53.0 B (#1474): {color?} -- its colour for every member ('' = the default tone); only here (an admin of this
    organisation), not in the instance admin's routes."""
    c, b = db(), body()
    _need_org_admin(c, oid)
    if instance_mode(c) != "workspaces":
        _no_change()
    if "color" in b:
        c.execute("UPDATE orgs SET color=? WHERE id=?", (wsc_clean_color(b["color"]), oid))
    _org_patch(c, oid, b)
    bump(c)
    c.commit()
    return jsonify(org_mine_dict(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone(), me()))


@app.put("/api/orgs/<int:oid>/members")
def org_member_put(oid):
    """2.28.0 (#935): {user_id | email, role?: member | admin} -- an organisation admin adds a person (one they may see, or by
    e-mail address: the answer never says whether the address has an account) or changes a member's role."""
    c, b = db(), body()
    _need_org_admin(c, oid)
    if instance_mode(c) != "workspaces":
        _no_change()
    role = b.get("role", "member")
    if role not in ORG_ROLES:
        return err(tr("Invalid value: {0}", "role"))
    uid, by_mail = b.get("user_id"), False
    if "email" in b and uid is not None:
        return err(tr("Invalid value: {0}", "user_id"))
    if b.get("email"):
        em = str(b["email"]).strip().lower()[:200]
        r = c.execute("SELECT id FROM users WHERE lower(email)=? AND disabled=0 AND COALESCE(kind,'user')!='agent'", (em,)).fetchone()
        if not r:
            return jsonify(ok=True, by_email=True)
        uid, by_mail = r[0], True
    if not isinstance(uid, int) or isinstance(uid, bool):
        return err(tr("Invalid value: {0}", "user_id"))
    u = c.execute("SELECT id, kind FROM users WHERE id=? AND disabled=0", (uid,)).fetchone()
    if not u or (u["kind"] or "user") == "agent" or (uid != me() and not by_mail and not may_see(c, me(), uid)):
        return err(tr("unknown user"), 404)
    cur = c.execute("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
    if cur and uid == me() and role != "admin" and _admins(c, oid) <= 1:
        return err(tr("The last admin of an organisation cannot step down: make somebody else an admin first"), 409)
    if cur:
        c.execute("UPDATE org_members SET role=? WHERE org_id=? AND user_id=?", (role, oid, uid))
    else:
        org_member_add(c, oid, uid, role)
        from ..collab.news import news_add
        news_add(c, uid, "share", list_id=None, data={"org": True, "name": c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()[0], "role": role})
    bump(c)
    c.commit()
    return jsonify(ok=True, by_email=bool(b.get("email")), **({} if b.get("email") else {"org": org_mine_dict(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone(), me())}))


def _admins(c, oid):
    return c.execute("SELECT COUNT(*) FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role='admin' AND u.disabled=0", (oid,)).fetchone()[0]


def org_leave(c, oid, uid, heir):
    """uid leaves organisation oid: their lists of that workspace go to heir (an organisation admin), uid leaves every list
    of the organisation (members and the agents it owns there stay with the lists), their personal agents of that workspace
    become private. The caller commits. Returns the number of lists transferred."""
    from ..lists.ownership import owner_transfer
    n = 0
    for lr in c.execute("SELECT * FROM lists WHERE owner_id=? AND org_id=? AND is_inbox=0", (uid, oid)).fetchall():
        if heir and heir != uid:
            owner_transfer(c, lr, heir)
            c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (lr["id"], uid))
            n += 1
        else:
            c.execute("UPDATE lists SET org_id=NULL WHERE id=?", (lr["id"],))
            from ..admin.orgcrypt_cli import oc_settle_kick
            oc_settle_kick([lr["id"]])  # 2.64.0 (#1864): its files get the owner's account key
    for (lid,) in c.execute("SELECT m.list_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE m.user_id=? AND l.org_id=?", (uid, oid)).fetchall():
        c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (lid, uid))
        c.execute("UPDATE tasks SET assignee_id=NULL WHERE list_id=? AND assignee_id=?", (lid, uid))
        c.execute("DELETE FROM task_people WHERE user_id=? AND task_id IN (SELECT id FROM tasks WHERE list_id=?)", (uid, lid))
    from ..contacts.orgbooks import obk_leave
    obk_leave(c, oid, uid, heir)  # 2.52.0 C (#1438): the organisation's own address books stay with it (another manager)
    # 2.30.0 (#1036): the organisation's calendars and address books follow the same way: the leaver's go to heir (else
    # they become private), the leaver leaves the ones of others
    for table, mt, key in (("ev_cals", "ev_cal_members", "cal_id"), ("books", "book_members", "book_id")):
        for (xid,) in c.execute(f"SELECT id FROM {table} WHERE owner_id=? AND org_id=?", (uid, oid)).fetchall():
            if heir and heir != uid:
                c.execute(f"DELETE FROM {mt} WHERE {key}=? AND user_id=?", (xid, heir))
                c.execute(f"UPDATE {table} SET owner_id=? WHERE id=?", (heir, xid))
            else:
                c.execute(f"UPDATE {table} SET org_id=NULL WHERE id=?", (xid,))
        c.execute(f"DELETE FROM {mt} WHERE user_id=? AND {key} IN (SELECT id FROM {table} WHERE org_id=?)", (uid, oid))
    # 2.46.0 (#1592, review fix): the leaver's personal agents leave the organisation with them -- its lists, calendars,
    # address books and the membership (an agent of an organisation is one of its members)
    ags = [r[0] for r in c.execute("SELECT user_id FROM agents WHERE owner_id=?", (uid,)).fetchall()]
    for aid in ags:
        c.execute("DELETE FROM list_members WHERE user_id=? AND list_id IN (SELECT id FROM lists WHERE org_id=?)", (aid, oid))
        for table, mt, key in (("ev_cals", "ev_cal_members", "cal_id"), ("books", "book_members", "book_id")):
            c.execute(f"DELETE FROM {mt} WHERE user_id=? AND {key} IN (SELECT id FROM {table} WHERE org_id=?)", (aid, oid))
        c.execute("DELETE FROM org_members WHERE org_id=? AND user_id=?", (oid, aid))
    c.execute("UPDATE agents SET org_id=NULL WHERE owner_id=? AND org_id=?", (uid, oid))
    c.execute("DELETE FROM org_members WHERE org_id=? AND user_id=?", (oid, uid))
    # 2.53.0 (#1424, review): the leaver's task bells in the organisation go too (else the nightly boundary check alarms)
    c.execute("DELETE FROM task_bell WHERE org_id=? AND user_id IN (%s)" % ",".join("?" * (len(ags) + 1)), (oid, uid, *ags))
    from ..core.access import acx_drop
    acx_drop()  # 2.36.2 (#1142): the request's access contexts follow the new memberships
    return n


@app.delete("/api/orgs/<int:oid>/members/<int:uid>")
def org_member_remove(oid, uid):
    """2.28.0 (#935): an organisation admin removes a member (or a member leaves: uid = self). The person's lists of this
    workspace go to the admin who removes them (leaving: to the organisation's first other admin), the person leaves every
    list of the organisation. The last admin cannot leave."""
    c = db()
    if uid != me():
        _need_org_admin(c, oid)
    elif not org_role(c, me(), oid):
        raise Denied(404)
    if instance_mode(c) != "workspaces":
        _no_change()
    if not c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone():
        return err(tr("unknown"), 404)
    if uid != me() and org_role(c, uid, oid) == "admin" and _admins(c, oid) <= 1:
        return err(tr("The last admin of an organisation cannot leave it: make somebody else an admin first"), 409)
    heir = me() if uid != me() else (c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role='admin' AND u.disabled=0 AND m.user_id!=? ORDER BY m.user_id LIMIT 1", (oid, uid)).fetchone() or [None])[0]
    operator = None
    if heir is None:  # the only admin leaves: the operator (an instance admin) takes the organisation over and is told
        operator = (c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0 AND kind!='agent' AND id!=? ORDER BY id LIMIT 1", (uid,)).fetchone() or [None])[0]
        if operator is None:
            return err(tr("The last admin of an organisation cannot leave it: make somebody else an admin first"), 409)
        c.execute("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT(org_id,user_id) DO UPDATE SET role='admin'", (oid, operator))
        from ..core.access import acx_drop
        acx_drop()
        heir = operator
    oname = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()[0]  # 2.37.0 (#1150): before leaving it (then invisible)
    n = org_leave(c, oid, uid, heir)
    if operator:
        from ..collab.news import news_add
        news_add(c, operator, "share", list_id=None, data={"org": True, "name": oname, "role": "admin", "handover": n}, actor=uid)
        print("organisation", oid, "last admin", uid, "left: operator", operator, "took it over,", n, "lists", flush=True)
    if uid != me():
        from ..collab.news import news_add
        news_add(c, uid, "unshare", list_id=None, data={"org": True, "name": oname})
    bump(c)
    c.commit()
    print("organisation", oid, "member", uid, "removed by" if uid != me() else "left,", g.user["username"], "lists transferred:", n, flush=True)
    return jsonify(ok=True, transferred=n)
