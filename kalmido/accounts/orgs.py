"""Organisations (#752) and workspaces (2.28.0, #935): people in 1..n organisations, whom a person may see, which
workspace (private / an organisation) a list and an agent belong to, the organisation's own admins."""
import os
import re

from flask import g, has_request_context, jsonify, request

from ..core.config import app, OFFICE_DIR
from ..core.pg import insert_id, like_escape, system_ctx
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, err, gset, gsetting, iso, now_utc
from ..core.db import usettings, uset  # 2.356.0 B (#2932)
from ..accounts.session import me
from ..core.access import Denied, acx_drop, acx_warm_register, acx_lists_sql, joined_lists_sql, dlg_gone, plists, pvis, qn_private, token_lists
from ..accounts.login import login_log_who  # 2.239.0 B (#2888)
from ..core.orgcrypt import oc_send_file, oc_write_file, rck_admin_gone, rck_org_admins  # 2.149.0 G (#2517): pulled up from functions; 2.539.0 (#4373): rck_*
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions
from .navmenus import nav_clean_org, nav_org_off  # 2.418.0 (#3560)
from .orgretain import Nn_, odl_former  # 2.186.0 A (#2599); 2.414.0 (#3502): Nn_ marks the plural pair below
from .pictures import org_icon_tok, org_icon_url, AVATAR_MAX_MB, LIST_ICON_DIR, list_icon_process, org_icon_drop_file, org_icon_path  # 2.369.5 (#2517): pulled up from functions
from ..core.i18n import trn  # 2.369.5 (#2517): pulled up from functions
from ..core.serializers import unlink_files  # 2.369.5 (#2517): pulled up from functions
from ..core.retention import ret_need_unheld  # 2.545.0 (#4595)


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
ORG_ROLES = ("member", "admin", "guest", "readonly", "accounting")  # 2.143.0 A (#2151): see accounts/orgroles.py
# folder names (the top folder of a list's owner) that mark a list as private when the workspaces arrive (ws_migrate)
PRIVATE_FOLDER_RE = re.compile(r"^(privat|private|pers[öo]nlich|personal|familie|family|zuhause|zu hause|home|haushalt|household|privé|prive|privado|personale|privato|thuis)$", re.I)
WS_MSG_PERSON = N_("{0} is not a member of the organisation {1}: share this project privately instead, or let an organisation admin add the person")
WS_MSG_AGENT = N_("{0} works in another workspace ({1}): an agent joins only projects of its own workspace")
WS_MSG_OWNER = N_("You are not a member of this organisation")
# 2.30.0 (#1036): calendars and address books follow the same rule
WS_MSG_PERSON_OBJ = N_("{0} is not a member of the organisation {1}: only its members can be in its calendars and address books")
WS_MSG_AGENT_OBJ = N_("{0} works in another workspace ({1}): an agent joins only calendars and address books of its own workspace")
WS_MSG_PRIVATE_ONLY = N_("Family, household and Home & life projects except trips are private: they cannot belong to an organisation")  # 2.173.0 A (#2680)


def instance_mode(c=None):
    """2.46.0 (#1592): shared when set so explicitly, else workspaces (no automatic mode by the number of organisations)."""
    return "shared" if INSTANCE_ENV == "shared" else "workspaces"


def main_org(c):
    with system_ctx(c):  # 2.37.0 (#1150): instance structure (the first organisation's id)
        # 2.422.0 (#2937 review): a company a person created herself is never the server's organisation
        r = c.execute("SELECT id FROM orgs WHERE personal_of IS NULL AND retired_at IS NULL AND self_made=0 ORDER BY id LIMIT 1").fetchone()  # 2.152.0 A
    return r[0] if r else None


def _rq(name):
    """2.369.6 (#3139): the request cache of a read (GET / HEAD only, like user_orgs; core/access.py acx_drop forgets it),
    else None. Structure read as "system" is asked once per request, so a GET does not switch its context per call.
    A GET that changes memberships / shares / connections must call acx_drop() afterwards (as every membership write does)."""
    if has_request_context() and request.method in ("GET", "HEAD"):
        return g.setdefault("org_rq", {}).setdefault(name, {})
    return None


def has_workspaces(c):
    """2.28.0 (#935): the instance knows organisations (any mode but shared) -> lists and agents have a workspace."""
    if instance_mode(c) == "shared":
        return False
    rq = _rq("hw")
    if rq is not None and "v" in rq:
        return rq["v"]
    with system_ctx(c):  # 2.37.0 (#1150): instance structure
        v = bool(c.execute("SELECT 1 FROM orgs WHERE personal_of IS NULL AND retired_at IS NULL LIMIT 1").fetchone())  # 2.152.0 A
    if rq is not None:
        rq["v"] = v
    return v


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
        if c.execute("SELECT 1 FROM orgs WHERE personal_of IS NULL AND retired_at IS NULL LIMIT 1").fetchone():  # 2.152.0 A
            return None
        oid = insert_id(c, "INSERT INTO orgs(name,icon,created_at) VALUES(?,?,?)", (nm, "", iso(now_utc())))
        org_member_add(c, oid, uid, "admin", keep_office=False)
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
    if has_request_context() and request.method in ("GET", "HEAD"):  # 2.280.0 B (#3116): a read asks once per person, not per call
        from .orgroles import org_roles_of
        return sorted(org_roles_of(c, uid))  # the same org ids (request cache, forgotten by acx_drop)
    with system_ctx(c):  # 2.37.0 (#1150): memberships are structure the access rules need (also of other people)
        # 2.223.2 A (#2859): a retired organisation grants no access (a membership row left from before is ignored)
        return [r[0] for r in c.execute("SELECT m.org_id FROM org_members m JOIN orgs o ON o.id=m.org_id WHERE m.user_id=? "
                                        "AND o.retired_at IS NULL ORDER BY m.org_id", (uid,))]


def org_member_add(c, oid, uid, role="member", keep_office=True):
    """2.36.2 (#1142): add uid to organisation oid (nothing when already in) and refresh the request's access contexts.
    keep_office=False (2.356.0, review N3): the person creates the organisation herself -- she goes on in it."""
    n = c.execute("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,?) ON CONFLICT (org_id, user_id) DO NOTHING", (oid, uid, role)).rowcount
    acx_drop()
    if n == 1 and keep_office:  # 2.356.0 B (#2932): a person with an own office keeps working in it (every way of joining comes here)
        _office_keep_on_join(c, uid)
    if n == 1:  # 2.363.3 (#3133): back within a day: their assignments and "coming along" return (every way of joining comes here)
        from .orgleave import olv_rejoin
        olv_rejoin(c, oid, uid)


def _office_keep_on_join(c, uid):
    """2.356.0 B (#2932): uid just joined an organisation. While the setting "workspace" is still unset ("all") and uid
    has a personal office (office/model.py pb_personal) with data (documents, master data, receipts, bank, cash book or
    private clients), it becomes "private": the office stays the person's own instead of switching silently to the
    organisation's (office_where: "all" + one organisation = its office, its numbers). Without such data nothing changes."""
    with system_ctx(c):  # the person's own setting and area (also when an admin adds the person)
        if (usettings(c, uid).get("workspace") or "all").strip() not in ("", "all"):
            return False
        pid = c.execute("SELECT id FROM orgs WHERE personal_of=?", (uid,)).fetchone()
        if not pid:
            return False
        used = c.execute("SELECT 1 FROM office_docs WHERE org_id=? UNION ALL SELECT 1 FROM office_services WHERE org_id=? "
                         "UNION ALL SELECT 1 FROM office_purchases WHERE org_id=? UNION ALL SELECT 1 FROM office_bank_tx WHERE org_id=? "
                         "UNION ALL SELECT 1 FROM office_cash_entries WHERE org_id=? "
                         "UNION ALL SELECT 1 FROM clients WHERE org_id IS NULL AND created_by=? LIMIT 1", (pid[0],) * 5 + (uid,)).fetchone()
        if used:
            uset(c, uid, "workspace", "private")
    return bool(used)


def org_names(c, uid):
    rq = _rq("on")  # 2.369.6 (#3139)
    if rq is not None and uid in rq:
        return list(rq[uid])
    oids = user_orgs(c, uid)
    if not oids:
        return []  # 2.369.6 (#3139): no organisation, no statement
    with system_ctx(c):  # 2.37.0 (#1150): the names of uid's own organisations (also before a login: mails, the login page)
        v = [r[0] for r in c.execute(f"SELECT name FROM orgs WHERE id IN ({','.join(str(int(x)) for x in oids)}) ORDER BY id")]
    if rq is not None:
        rq[uid] = tuple(v)
    return v


def org_role(c, uid, oid):
    """2.28.0 (#935): member | admin | None -- the person's role in organisation oid. 2.143.0 A (#2151): also guest | readonly |
    accounting (what each may do: accounts/orgroles.py; is_org_admin and == "admin" checks stay as they are)."""
    if not oid or oid not in user_orgs(c, uid):
        return None
    if _rq("or") is not None:  # 2.369.6 (#3139): a read takes the role from the request cache user_orgs read (same rows)
        from .orgroles import org_roles_of
        return org_roles_of(c, uid).get(oid)
    with system_ctx(c):  # 2.37.0 (#1150): membership structure (also asked for other people)
        r = c.execute("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
    if not r:
        return None
    from .orgroles import role_known
    return role_known(r["role"], oid, uid)  # 2.143.0 A (#2151, review): unknown -> guest


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
    rq = _rq("vp")  # 2.369.6 (#3139): once per request and person (a copy: callers may change the set)
    if rq is not None and uid in rq:
        v = rq[uid]
        return None if v is None else set(v)
    with system_ctx(c):
        v = _visible_people(c, uid)
    if rq is not None:
        rq[uid] = None if v is None else frozenset(v)
    return v


def token_people(c, uid):
    """2.473.0 (#3907): None = no limit; a token limited to some projects (a person's or an agent's): the set of the people
    of those projects, oneself and an agent's owner -- the people of the account's other projects stay out. Ids only."""
    lids = token_lists()
    if lids is None:
        return None
    q = ",".join("?" * len(lids)) or "NULL"
    with system_ctx(c):
        keep = {uid, *(r[0] for r in c.execute("SELECT owner_id FROM agents WHERE user_id=?", (uid,)))}
        keep |= {r[0] for r in c.execute(f"SELECT owner_id FROM lists WHERE id IN ({q})", [*lids])}
        keep |= {r[0] for r in c.execute(f"SELECT user_id FROM list_members WHERE list_id IN ({q})", [*lids])}
    return keep


def _agent_visible_people(c, uid):
    """2.223.7 A (#2917): the people an agent account may see -- itself, its owner (a personal / freelancer agent) or the
    admins of its organisation (a team agent), and the owners / members of the projects shared with it. Never the whole
    organisation (agents are org_members) and never "everyone" (an instance without organisations, #2941)."""
    a = c.execute("SELECT owner_id, org_id FROM agents WHERE user_id=?", (uid,)).fetchone()
    ids = {uid}
    if a and a["owner_id"] is not None:
        ids.add(a["owner_id"])
    elif a and a["org_id"] is not None:
        ids |= {r[0] for r in c.execute("SELECT user_id FROM org_members WHERE org_id=? AND role='admin'", (a["org_id"],))}
    lq = acx_lists_sql(req=False, ov=False)
    pl = set(plists(c, uid))  # 2.223.7 (#2918): as a participant only the owner + (with a task of its own) the full members, like h6r_shared_people
    ids |= {r[0] for r in c.execute(f"SELECT owner_id FROM lists WHERE id IN {lq}", (uid, uid))}
    mine = {}
    for lid, p, role in c.execute(f"SELECT list_id, user_id, role FROM list_members WHERE list_id IN {lq}", (uid, uid)).fetchall():
        if lid in pl and lid not in mine:
            mine[lid] = bool(pvis(c, uid, lid)[1])
        if lid not in pl or (role != "participant" and mine[lid]):
            ids.add(p)
    return ids


def _visible_people(c, uid):
    u = c.execute("SELECT is_admin, kind FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return None
    if (u["kind"] or "user") == "agent":
        return _agent_visible_people(c, uid)  # 2.223.7 A (#2917, #2941)
    m = instance_mode(c)
    if m == "workspaces":  # 2.28.0 (#935): the members of my organisations + my connections; admins are no exception
        orgs = user_orgs(c, uid)
        ids = set()
        if orgs:
            # 2.143.0 A (#2151): in an organisation where uid is a guest / accounting only its admins (+ connections below)
            from .orgroles import user_orgs_full
            full = [o for o in user_orgs_full(c, uid) if o in orgs]
            q = ",".join("?" * len(orgs))
            ids = {r[0] for r in c.execute(f"SELECT user_id FROM org_members WHERE org_id IN ({q}) AND (role='admin' OR org_id IN ({','.join(str(int(o)) for o in full) or 'NULL'}))", orgs)}
        elif not c.execute("SELECT 1 FROM orgs WHERE personal_of IS NULL AND retired_at IS NULL AND self_made=0 LIMIT 1").fetchone():  # 2.152.0 A; 2.422.0 (#2937 review): like om_has_orgs
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
        raise Denied(404, tr("unknown person"))


def org_icon_fields(r, member=True):
    """2.87.9 (#1913): {icon: the emoji ('' with an own picture), icon_url: the own picture ('' without; only for members)}."""
    v = r["icon"] or ""
    return {"icon": "" if org_icon_tok(v) else v, "icon_url": org_icon_url(r["id"], v) if member else ""}


def org_public(c, r, roles=True):
    d = {"id": r["id"], "name": r["name"], "domains": r["domains"],  # 2.23.0 (#711): e-mail domains
         "members": [x[0] for x in c.execute("SELECT user_id FROM org_members WHERE org_id=? ORDER BY user_id", (r["id"],))]}
    d.update(org_icon_fields(r, member=g.get("user") is not None and g.user["id"] in d["members"]))  # 2.87.9 (#1913)
    # 2.147.1 C (#2420): the people count of the card leaves agent accounts out (like the members dialog)
    d["people"] = c.execute("SELECT COUNT(*) FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND COALESCE(u.kind,'user')!='agent'", (r["id"],)).fetchone()[0]
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
    # 2.409.0 (#3490): + areas_off (the areas its admins switched off for the members, accounts/wsareas.py)
    return [{"id": r["id"], "name": r["name"], **org_icon_fields(r), "color": r["color"] or "", "role": org_role(c, uid, r["id"]) or "member",
             "areas_off": [x for x in (r["areas_off"] or "").split(",") if x],
             "nav_off": nav_org_off(r)}  # 2.418.0 (#3560): menu points its admins switched off
            for r in c.execute(f"SELECT id, name, icon, color, areas_off, nav_off FROM orgs WHERE id IN ({q}) ORDER BY id", oids)]


def org_peers(c, uid):
    """2.364.0 D (#3036): does uid work with someone in an organisation (another member or an agent of one of its
    organisations)? Part of the app's mark "has collaborators" (with the shared projects, the client)."""
    oids = user_orgs(c, uid)
    if not oids:
        return False
    rq = _rq("op")  # 2.369.6 (#3139)
    if rq is not None and uid in rq:
        return rq[uid]
    q = ",".join("?" * len(oids))
    with system_ctx(c):  # memberships are structure (ids only), as user_orgs
        v = bool(c.execute(f"SELECT 1 FROM org_members WHERE org_id IN ({q}) AND user_id<>? LIMIT 1", (*oids, uid)).fetchone()
                    or c.execute(f"SELECT 1 FROM agents WHERE org_id IN ({q}) LIMIT 1", oids).fetchone())
    if rq is not None:
        rq[uid] = v
    return v


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
    from ..collab.liste2eguard import le2b_agent_problem
    p = le2b_agent_problem(c, lid, uid)  # 2.64.1 B (#1817): an agent never joins a list with the lock (every share path)
    if p:
        return p
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


def ws_check_owner(c, oid, uid):
    """2.538.0 (#4371): Denied(409) when uid may not own a project of organisation oid -- the rule of list_owner_set for every
    way a project changes hands (handover by an organisation admin, a folder, an heir when someone leaves): only a member or
    an admin (org_writes); a guest / read-only / accounting person never becomes the owner (the role cap #2151)."""
    from .orgroles import org_writes
    if oid and not org_writes(c, uid, oid):
        raise Denied(409, tr("Only a member or admin of the organisation can own its projects"))


def _orgs_w(c, uid):
    """2.143.0 A (#2151): uid's organisations in which they may add content (member / admin)."""
    from .orgroles import user_orgs_full
    mine = set(user_orgs(c, uid))
    return [o for o in user_orgs_full(c, uid, write=True) if o in mine]


def ws_obj_default(c, uid):
    """2.30.0 (#1036): the workspace of a new calendar / address book when the client names none: an agent's own workspace,
    else the chosen / only organisation (ws_chosen_org, 2.148.1 H #2480: as a new list), else private."""
    if not has_workspaces(c):
        return None
    u = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
    if u and (u["kind"] or "user") == "agent":
        return agent_org(c, uid)
    return _ws_sga(c, ws_chosen_org(c, uid))  # 2.148.1 H (#2480): the chosen / only organisation, else private (was the first one)


def _ws_sga(c, oid):
    """2.538.0 (#4365): a support session's new object lands privately, never by default in an organisation without support access."""
    from .supportgrant import sga_org_foreign
    return None if sga_org_foreign(c, oid) else oid


def ws_chosen_org(c, uid):
    """2.148.1 A (#2480): the organisation a person chose in the workspace switch (setting workspace = org:<id>) while they
    may add content there; else their only organisation (one they may add content to); with several, None (private) --
    never simply the first one. An agent: its own workspace."""
    u = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
    if u and (u["kind"] or "user") == "agent":
        return agent_org(c, uid)
    mine = _orgs_w(c, uid)  # 2.143.0 A (#2151): never where uid only reads / is a guest
    ws = str(usettings(c, uid).get("workspace") or "")
    m = re.fullmatch(r"org:(\d{1,9})", ws)
    oid = int(m.group(1)) if m else None
    if oid and oid in mine:
        return oid
    if ws == "private":  # 2.148.1 H (#2480): the switch on "Private" means private
        return None
    return mine[0] if len(mine) == 1 else None


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
    if table == "ev_cals" and oid:  # 2.87.0 (#1983): people invited to its events must fit the organisation too
        for (uid,) in c.execute("SELECT DISTINCT a.user_id FROM event_attendees a JOIN events e ON e.id=a.event_id WHERE e.cal_id=? "
                                "AND e.deleted_at IS NULL AND a.user_id IS NOT NULL ORDER BY a.user_id", (obj_id,)).fetchall():
            p = ws_fit_problem(c, oid, uid, kind)
            if p:
                raise Denied(409, p)
    from .orgout import org_out  # 2.148.1 H (#2483): out of an organisation only through its admin (logged)
    org_out(c, r["org_id"], oid, "book" if table == "books" else "calendar",
            c.execute(f"SELECT name FROM {table} WHERE id=?", (obj_id,)).fetchone()[0])
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
    from .supportgrant import sga_scope_check
    sga_scope_check(c, oid)  # 2.538.0 (#4365): a support session puts nothing into an organisation without support access
    from .orgroles import need_org_write
    need_org_write(c, uid, oid)  # 2.143.0 A (#2151): guests / read-only / accounting add nothing to the organisation
    return oid


def list_org_set(c, lid, v):
    """The owner moves list lid into workspace v (clean_org_id). Refused (409) for the inbox, for family / household / Home &
    life lists going into an organisation, and while a member or agent of the list does not fit the new workspace (named)."""
    lr = c.execute("SELECT owner_id, is_inbox, family, life, org_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not lr or lr["owner_id"] != me():
        raise Denied(403, tr("Only the owner can change the workspace of a project"))
    if (None if v in (None, "", 0, "0", "private") else v) == lr["org_id"]:
        return False  # unchanged (the list dialog sends it with every save)
    oid = clean_org_id(c, v, me())
    if lr["is_inbox"] and oid:
        raise Denied(409, tr("The basket is always private"))
    if oid:
        qn_private(c, lid)  # 2.477.0 (#3881)
    if oid and (lr["family"] or (lr["life"] and lr["life"] != "travel")):  # 2.173.0 A (#2680): a trip may belong to an organisation
        raise Denied(409, tr(WS_MSG_PRIVATE_ONLY))
    if (oid or None) == (list_org(c, lid) or None):
        return False
    from .orgout import org_out  # 2.148.1 B (#2483): out of an organisation only through its admin (logged, admins told)
    org_out(c, lr["org_id"], oid, "list", c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0], list_id=lid, obj=lid)  # 2.361.2 (#2923): obj
    # 2.352.0 F (#2748, review N4): a row only through the old workspace's folders ends with the move (grp_sync below)
    for (uid,) in c.execute("""SELECT user_id FROM list_members WHERE list_id=? AND NOT (frole IS NOT NULL AND own_role IS NULL
                               AND grole IS NULL) ORDER BY user_id""", (lid,)).fetchall():
        ws_check_member(c, lid, uid, org_id=oid or 0)
    c.execute("UPDATE lists SET org_id=? WHERE id=?", (oid, lid))
    # 2.361.0 (#2922): who brought it in from the private space (it goes back there when that person leaves, org_leave)
    c.execute("UPDATE lists SET brought_by=? WHERE id=?", (me() if oid and not lr["org_id"] else None, lid))
    from ..lists.groups import grp_sync
    grp_sync(c, [lid])  # 2.352.0 A (#2748): its node into the new workspace's projects tree, the old folders' roles end
    boundary = ol_client_fit(c, lid, oid)  # 2.86.0 (N11): a client of another workspace does not travel along (as list_client_set refuses it)
    list_space_follow(c, lid, lr["org_id"], boundary)  # 2.401.0 (#2924): its customer reports and bells go along
    from ..admin.orgcrypt_cli import oc_settle_kick
    # 2.42.0 (#828): the list's files get the organisation's key now; 2.64.0 (#1864): out of it the owner's account key
    # (only this list's files, after the request)
    oc_settle_kick([lid])
    return True


def list_space_follow(c, lid, old_org, boundary):
    """2.401.0 (#2924): list lid just changed its workspace (from old_org): its tasks' customer reports and bells that lived in
    the old space go along (lists/lmove.py); boundary = team/clients.py _org_boundary: a report's client of another workspace
    is unbound then. Returns the number of reports moved. The caller commits."""
    l = c.execute("SELECT org_id, owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not l or (l["org_id"] or None) == (old_org or None):
        return 0
    oid, owner = l["org_id"] or None, None if l["org_id"] else l["owner_id"]
    n = c.execute("""UPDATE portal_tickets SET org_id=?, owner_id=? WHERE task_id IN (SELECT id FROM tasks WHERE list_id=?)
                     AND org_id IS NOT DISTINCT FROM ?""", (oid, owner, lid, old_org or None)).rowcount
    if n and boundary:  # a client of another workspace is no client of the report there (tenancy portal_client)
        c.execute("""UPDATE portal_tickets SET client_id=NULL WHERE task_id IN (SELECT id FROM tasks WHERE list_id=?)
                     AND client_id IS NOT NULL AND client_id NOT IN (SELECT id FROM clients WHERE org_id IS NOT DISTINCT FROM ?)""",
                  (lid, oid))
    c.execute("""UPDATE task_bell SET org_id=? WHERE task_id IN (SELECT id FROM tasks WHERE list_id=?)
                 AND org_id IS NOT DISTINCT FROM ?""", (oid, lid, old_org or None))
    return n


def ws_default_org(c, uid, folder=""):
    """The workspace a new list of uid gets when the client names none: the workspace of the other lists of that folder (all
    of them in one), else the organisation chosen in the workspace switch or the only one (2.148.1 A, #2480: with several
    no longer simply the first), else private."""
    if not has_workspaces(c):
        return None
    if folder:
        rows = c.execute("SELECT DISTINCT org_id FROM lists WHERE owner_id=? AND is_inbox=0 AND (folder=? OR folder ILIKE ? ESCAPE '\\')",
                         (uid, folder, like_escape(folder.split("/", 1)[0]) + "/%")).fetchall()
        oids = {r[0] for r in rows}
        if len(oids) == 1 and (None in oids or oids <= set(_orgs_w(c, uid))):  # 2.143.0 A (#2151)
            return _ws_sga(c, oids.pop())  # 2.538.0 (#4365)
    return _ws_sga(c, ws_chosen_org(c, uid))  # 2.148.1 A (#2480): the chosen / only organisation, else private (was the first one)


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
        raise Denied(409, tr("{0} works in another workspace ({1}): an agent joins only projects of its own workspace", ag["display_name"] or ag["username"], _org_name(c, oid)))
    from .orgout import org_out  # 2.148.1 H (#2483): out of an organisation only through its admin (logged)
    org_out(c, oid, None, "list", c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()[0], list_id=lid, obj=lid)  # 2.361.2 (#2923): obj
    c.execute("UPDATE lists SET org_id=NULL WHERE id=?", (lid,))
    c.execute("DELETE FROM reading_orgs WHERE list_id=?", (lid,))  # 2.172.1 (#2689): no longer the organisation's read-later project
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
            for (lo,) in c.execute(f"SELECT l.org_id FROM lists l WHERE l.is_inbox=0 AND l.id IN {joined_lists_sql()}",
                                  (a["user_id"], a["user_id"])):
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
    if v.startswith("u:"):  # 2.87.9 (#1913): an own picture is set only by its upload (POST /api/orgs/{id}/icon)
        return ""
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
        if u in roles:
            org_member_add(c, oid, u, roles[u])
        else:
            org_join_or_add(c, oid, u)  # 2.306.0 D1 (#2875): hosted: an invitation
    # 2.36.2 (#1142): the people taken out leave the organisation the same way as with an organisation admin (org_leave):
    # they leave its lists, calendars and address books; their lists of this workspace go to an admin who stays
    _members_gone(c, oid, sorted(set(roles) - set(ids)), {u for u, r in roles.items() if r == "admin"})  # 2.539.0 (#4373): admins


def _ids_arg(b, k):
    """2.270.0 A (#3019): an id list of the request (members_add …), 400 on anything else."""
    v = b.get(k, [])
    if not isinstance(v, list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in v):
        raise Denied(400, tr("Invalid value: {0}", k))
    return v


def _member_ops(c, oid, b):
    """2.270.0 A (#3019): {members_add?, members_remove?, admins_add?, admins_remove?} change only these people (the old
    {members, admins} replaced the whole set: who joined meanwhile was taken out, a new admin demoted). {members, admins}
    with `_prev: {members?, admins?}` (the sets the dialog showed) becomes the same operations. Returns True when used."""
    prev = b.get("_prev") if isinstance(b.get("_prev"), dict) else {}
    ops = {k: _ids_arg(b, k) for k in ("members_add", "members_remove", "admins_add", "admins_remove") if k in b}
    for k in ("members", "admins"):
        if k in b and k in prev:
            new, old = set(_ids_arg(b, k)), set(_ids_arg(prev, k))
            ops[k + "_add"] = sorted(set(ops.get(k + "_add", [])) | (new - old))
            ops[k + "_remove"] = sorted(set(ops.get(k + "_remove", [])) | (old - new))
    if not ops:
        return False
    have = {r[0]: r[1] or "user" for r in c.execute("SELECT id, kind FROM users")}
    had = org_own_admin(c, oid)
    for u in ops.get("members_add", []):
        if u in have and not c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, u)).fetchone():
            # 2.306.0 D1 (#2875): hosted: an invitation; Fix-1 (#2875 review): with the admin role when also in admins_add
            org_join_or_add(c, oid, u, "admin" if have[u] != "agent" and u in ops.get("admins_add", []) else "member")
    # 2.306.0 D1 (#2875): the new admins first, so the people taken out leave their lists to them (not to the operator)
    for u in ops.get("admins_add", []):
        if c.execute("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=? AND role!='admin' AND user_id IN (SELECT id FROM users WHERE kind!='agent')", (oid, u)).rowcount:
            org_role_news(c, oid, u, "admin")  # 2.367.4 (#2974)
    for u in ops.get("admins_remove", []):  # only an admin becomes a member; guest / read-only / accounting keep their role (#2151)
        if c.execute("UPDATE org_members SET role='member' WHERE org_id=? AND user_id=? AND role='admin'", (oid, u)).rowcount:
            org_role_news(c, oid, u, "member")
            rck_admin_gone(c, oid, u)  # 2.539.0 (#4373)
    gone = [u for u in ops.get("members_remove", []) if c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, u)).fetchone()]
    was = set(rck_org_admins(c, oid)) if gone else set()  # 2.539.0 (#4373)
    for u in gone:
        c.execute("DELETE FROM org_members WHERE org_id=? AND user_id=?", (oid, u))
    _members_gone(c, oid, gone, was)
    keep_own_admin(c, oid, had)  # 2.306.0 Fix-1 (#2875 review): hosted: demoting the last admin is refused too
    acx_drop()
    return True


def _operator_apart():
    """2.306.0 D1 (#2875, #2687): on a hosted instance the operator stays out of its customers' organisations: it never becomes
    their admin when the last one goes (409 instead) and puts no existing account into one without the person's consent
    (an invitation, org_join_or_add). A self-hosted server keeps both as before."""
    from ..admin.hosting import hosted
    return hosted()


# 2.399.0 (#2687): on a hosted instance the operator (an instance admin) runs the server, not its customers' organisations: every
# instance-admin way into an organisation it does not administer itself (members, roles, creating one for somebody else) and into
# an account of a customer (password, sign-in link, e-mail, organisations, its agents) answers 403. Locking, deleting and quotas stay.
OP_APART_MSG = N_("On a hosted instance the operator does not reach into the organisations and accounts of its clients")


def op_apart_deny():
    raise Denied(403, tr(OP_APART_MSG))


def op_foreign_org(c, oid, note=True, grant=True):
    """2.399.0 (#2687): hosted and the current person is no admin of organisation oid (a self-hosted server: False).
    2.485.0 (#3939): not while the organisation granted support access (accounts/supportgrant.py; note: log the use;
    grant=False: as if there were none)."""
    if not _operator_apart() or org_role(c, me(), oid) == "admin":
        return False
    if not grant:
        return True
    from .supportgrant import sga_open
    return not sga_open(c, oid=oid, note=note)


# 2.485.0 (#3939, review F1/F3): what support access never hands to the operator -- credentials and new people: they would
# outlive the client's consent
OP_SUPPORT_MSG = N_("Support access does not hand out sign-in data or add people: the client does that")


def op_support_only(c, uid=None, oid=None):
    """2.485.0 (#3939): hosted and the current person reaches account uid / organisation oid only through the client's support
    access (without it: foreign). Then no credentials, no new people (op_support_deny)."""
    if oid is not None:
        return op_foreign_org(c, oid, grant=False) and not op_foreign_org(c, oid, note=False)
    return op_foreign_account(c, uid, grant=False) and not op_foreign_account(c, uid, note=False)


def op_support_deny():
    raise Denied(403, tr(OP_SUPPORT_MSG))


def op_foreign_account(c, uid, note=True, grant=True):
    """2.399.0 (#2687): hosted and account uid belongs to a customer: not the current person, no account of an organisation the
    current person administers, 2.480.0 (#3944, F8): no account the current person made that never signed in (users.op_made_by). An agent follows its owner (a personal one: only one's own) or its organisation; a server agent
    without both belongs to the operator. 2.485.0 (#3939): not while the account (an agent: its owner) granted support access
    (accounts/supportgrant.py; note: log the use)."""
    if not _operator_apart() or uid == me():
        return False
    from .supportgrant import sga_open
    with system_ctx(c):  # membership structure, no content
        a = c.execute("SELECT owner_id, org_id FROM agents WHERE user_id=?", (uid,)).fetchone()
        if a:
            if a["owner_id"]:
                return a["owner_id"] != me() and not (grant and sga_open(c, uid=a["owner_id"], note=note))
            return bool(a["org_id"]) and op_foreign_org(c, a["org_id"], note=note, grant=grant)
        if c.execute("SELECT 1 FROM users WHERE id=? AND op_made_by=?", (uid, me())).fetchone():
            return False  # 2.480.0 (#3944, F8): an account the operator made itself that never signed in (family, a kid)
        apart = not c.execute("SELECT 1 FROM org_members a JOIN org_members b ON b.org_id=a.org_id JOIN orgs o ON o.id=a.org_id "
                              "WHERE a.user_id=? AND a.role='admin' AND b.user_id=? AND o.retired_at IS NULL LIMIT 1",
                              (me(), uid)).fetchone()  # review F7: a retired organisation grants nothing
    return apart and not (grant and sga_open(c, uid=uid, note=note))


def org_own_admin(c, oid, but=0):
    """2.306.0 Fix-1 (#2875 review): an active admin of organisation oid who is a person (not `but`), or None."""
    r = c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role='admin' "
                  "AND u.disabled=0 AND COALESCE(u.kind,'user')!='agent' AND m.user_id!=? ORDER BY m.user_id LIMIT 1", (oid, but)).fetchone()
    return r[0] if r else None


def keep_own_admin(c, oid, had):
    """2.306.0 Fix-1 (#2875 review): hosted: a change by the operator that leaves an organisation which had an admin of its own
    without one is refused (409, rolled back), like the last admin leaving (_members_gone)."""
    if had and _operator_apart() and org_own_admin(c, oid) is None:
        c.rollback()
        raise Denied(409, tr("The last admin of an organisation cannot leave it: make somebody else an admin first"))


def org_join_or_add(c, oid, uid, role="member"):
    """2.306.0 D1 (#2875): the instance admin places an existing account into organisation oid: directly, or on a hosted
    instance as an invitation the person accepts (accounts/orginvite.py, like an organisation admin's). An agent is placed
    directly (it accepts nothing). Returns True when only invited."""
    if _operator_apart() and c.execute("SELECT 1 FROM users WHERE id=? AND COALESCE(kind,'user')!='agent'", (uid,)).fetchone():
        if uid == me():  # 2.306.0 Fix-1 (#2875 review): the operator does not invite itself into a customer's organisation
            c.rollback()
            raise Denied(409, tr("On a hosted instance the operator does not join the organisations of its clients"))
        from .orginvite import ojn_invite
        ojn_invite(c, oid, uid, role)
        return True
    org_member_add(c, oid, uid, role)
    return False


def org_heir_lift(c, oid, heir):
    """2.538.0 (#4371): the heir of a leaving person is only ever an admin or member (ws_check_owner): an instance admin who
    takes over while in organisation oid as guest / read-only / accounting becomes its admin first, like org_member_remove
    (review 2646 finding 8: before, org_leave refused with 409 halfway through). Not a member: unchanged. The caller commits."""
    if c.execute("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=? AND role NOT IN ('admin','member')",
                 (oid, heir)).rowcount:
        acx_drop()


def _members_gone(c, oid, gone, admins=()):
    """The people taken out of organisation oid leave it (org_leave); no admin left: the operator takes over. 2.539.0 (#4373):
    admins = who of them was an admin before their membership rows went (rck_admin_gone)."""
    if gone:
        own = c.execute("SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role='admin' "
                        "AND u.disabled=0 AND u.kind!='agent' ORDER BY m.user_id LIMIT 1", (oid,)).fetchone()
        if not own and _operator_apart():  # 2.306.0 D1 (#2875): hosted: the organisation keeps an admin of its own
            c.rollback()
            raise Denied(409, tr("The last admin of an organisation cannot leave it: make somebody else an admin first"))
        heir = (own
                or c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0 AND kind!='agent' ORDER BY id LIMIT 1").fetchone() or [None])[0]
        if heir and not c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, heir)).fetchone():
            org_member_add(c, oid, heir, "admin")  # no admin stays: the operator takes over (like org_member_remove)
        elif heir:
            org_heir_lift(c, oid, heir)  # 2.538.0 (#4371): an operator in it as guest / read-only takes over as admin
        for u in gone:
            org_leave(c, oid, u, heir)
            if u in admins:
                rck_admin_gone(c, oid, u)  # 2.539.0 (#4373)


def op_org_public(c, r):
    """2.399.0 (#2687): an organisation for the instance admin's list -- hosted, one it does not administer comes without its
    people and domains (name, symbol, the number of people) and marked apart (no edit button)."""
    d = org_public(c, r)
    if op_foreign_org(c, r["id"]):
        d.update(members=[], admins=[], domains="", apart=True)
    return d


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
        # 2.152.0 A (#2167): + retired_at / retain_until / retired_personal (a retired one: kept by law, export only)
        return jsonify(orgs=[{**op_org_public(c, r), "retired_at": r["retired_at"], "retain_until": r["retain_until"] or "",
                              "retired_personal": bool(r["retired_personal"])} for r in rows],
                       visibility=vis_mode(c), mode=m, editable=m == "workspaces",
                       creatable=m == "workspaces", name_env=bool(ORG_NAME_ENV),
                       boundary=boundary_summary(c, g.user["id"]))  # 2.122.4 A (#1724): names only inside own orgs; 2.30.0 (#1036): memberships across the workspace boundary (0 = clean)


@app.post("/api/admin/orgs/boundary/repair")
def oa_boundary_repair():
    """2.46.0 (#1563): the button "Clean up" of the boundary check: takes out the memberships of people (not agents) in an
    organisation's lists / calendars / address books that are not members of the organisation (tenancy.boundary_repair)."""
    _need_admin()
    from ..accounts.tenancy import boundary_repair, boundary_summary, rp_foreign
    c = db()
    with system_ctx(c):  # 2.480.0 (#3944, F5): hosted: only the operator's own organisations, a client's rows are only counted
        done = boundary_repair(c, keep=(lambda k, a, b: rp_foreign(c, k, a, b)) if _operator_apart() else None)
        kept = done.pop("_kept", {})
        if done:
            bump(c)
    c.commit()
    n = sum(len(v) for v in done.values())
    if n:
        print(f"boundary check (#1563): {n} memberships across the workspace boundary removed by an admin", flush=True)
    return jsonify(removed=n, kinds={k: len(v) for k, v in done.items()}, kept=sum(kept.values()),
                   boundary=boundary_summary(c, g.user["id"]))  # 2.122.4 A (#1724)


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
        # 2.540.0 (#4383): a retired organisation's name is free again
        if c.execute("SELECT 1 FROM orgs WHERE lower(name)=lower(?) AND personal_of IS NULL AND retired_at IS NULL", (name,)).fetchone():
            return err(tr("An organisation with this name exists"), 409)
        oid = insert_id(c, "INSERT INTO orgs(name,icon,domains,created_at) VALUES(?,?,?,?)",
                        (name, _clean_icon(b.get("icon")), _clean_domains(b.get("domains") or ""), iso(now_utc())))
        adm = b.get("admin_id", me())
        if not isinstance(adm, int) or isinstance(adm, bool) or not c.execute("SELECT 1 FROM users WHERE id=? AND kind!='agent' AND disabled=0", (adm,)).fetchone():
            c.rollback()
            return err(tr("Invalid value: {0}", "admin_id"))
        if adm != me() and _operator_apart():  # 2.399.0 (#2687): hosted: a customer creates its organisation itself (POST /api/orgs)
            c.rollback()
            op_apart_deny()
        org_member_add(c, oid, adm, "admin", keep_office=adm != me())
        bump(c)
        c.commit()
        print("organisation", oid, "created by", login_log_who(g.user), flush=True)
        return jsonify(org_public(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone())), 201


# 2.422.0 (#2937): a self-employed person creates a company of her own (work apart from her private
# things) without the server's admin: mode workspaces, a person (no agent, no kid account), she becomes its admin. At most
# ORG_SELF_MAX such companies per person. Marked self_made: only a server admin sets its e-mail domains (nobody joins it by
# the domain of their address), and it does not count as the server's organisation for open registration (signup.py), its
# main organisation (main_org) or the household rule "everyone sees everyone" (_visible_people). self_made holds the id of
# the person who created it (0 = the server's admin), so leaving one never frees a place.
ORG_SELF_MAX = 3


def org_heir_to(c, oid, uid, raw):
    """2.512.0 (#4076, was in org_member_remove): the ?to= of removing uid from organisation oid as a user id, when that
    is the removing admin or another active person of the organisation; None for anybody else, so that neither the removal
    nor its preview (leave-info) ever takes or names an account from outside."""
    try:
        to = int(raw)
    except ValueError:
        return None
    if not 0 < to < 2 ** 63:
        return None
    if to == me() or c.execute("""SELECT 1 FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.user_id=?
                                  AND m.user_id!=? AND u.disabled=0 AND COALESCE(u.kind,'user')!='agent'""", (oid, to, uid)).fetchone():
        ws_check_owner(c, oid, to)  # 2.538.0 (#4371): only to a member / admin (409); asked by an organisation admin, who sees the roles
        return to
    return None


def org_self_name_taken(c, uid, name):
    """2.512.0 (#4077): uid already created a company of this name. Only uid's own: an answer about the names of the whole
    server would tell anybody which companies its other customers are called (the server admin's route stays server-wide)."""
    return bool(c.execute("SELECT 1 FROM orgs WHERE self_made=? AND lower(name)=lower(?) AND personal_of IS NULL AND retired_at IS NULL",
                          (uid, name)).fetchone())


def org_self_made_n(c, uid):
    """The companies uid created herself (2.422.0, #2937; review: also the ones she left or handed over)."""
    return c.execute("SELECT COUNT(*) FROM orgs WHERE self_made=? AND personal_of IS NULL AND retired_at IS NULL", (uid,)).fetchone()[0]


@app.post("/api/orgs")
def org_self_create():
    """2.422.0 (#2937): {name, icon?} -- the signed-in person creates a company and becomes its admin (201, like
    POST /api/admin/orgs). 403 for agents and kid accounts, 403 outside the mode workspaces, 409 when she already has a
    company of this name (#4077: only her own count) or ORG_SELF_MAX companies of her own."""
    if (g.user["kind"] or "user") == "agent" or g.user["kid"]:
        raise Denied(403, tr("Only a person can create a company"))
    c, b, uid = db(), body(), me()
    with system_ctx(c):  # creating an organisation (instance structure) with the caller as its only member
        if instance_mode(c) != "workspaces":
            raise Denied(403, tr("Only an admin of this server can create an organisation"))
        name = _clean_name(b.get("name"))
        if org_self_name_taken(c, uid, name):
            return err(tr("You already have a company with this name"), 409)
        if org_self_made_n(c, uid) >= ORG_SELF_MAX:
            return err(tr("You already have {0} companies of your own", ORG_SELF_MAX), 409)
        oid = insert_id(c, "INSERT INTO orgs(name,icon,domains,created_at,self_made) VALUES(?,?,?,?,?)",
                        (name, _clean_icon(b.get("icon")), "", iso(now_utc()), uid))
        org_member_add(c, oid, uid, "admin", keep_office=False)
        bump(c)
        c.commit()
        print("organisation", oid, "created by its own admin", login_log_who(g.user), flush=True)
        return jsonify(org_public(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone())), 201


@app.patch("/api/admin/orgs/<int:oid>")
def org_update(oid):
    """{name?, icon?, members?: [user ids] (replaces them), domains?} -- only on an instance that kept several organisations
    from 2.22 ("multi") or in the mode workspaces; else 403 (#799). 2.270.0 A (#3019): members_add / members_remove /
    admins_add / admins_remove (or members / admins with _prev: {members, admins}) change only those people."""
    _need_admin()
    c, b = db(), body()
    if op_foreign_org(c, oid):  # 2.399.0 (#2687): hosted: name, members and roles of a customer's organisation are its admins' own
        op_apart_deny()
    if isinstance(b, dict) and op_support_only(c, oid=oid):  # 2.485.0 (#3939, review F3): support access adds nobody
        with system_ctx(c):
            have = {r[0] for r in c.execute("SELECT user_id FROM org_members WHERE org_id=?", (oid,))}
        new = set()
        for k in ("members_add", "admins_add", "members", "admins"):
            v = b.get(k)
            if isinstance(v, list):
                new |= {x for x in v if isinstance(x, int) and not isinstance(x, bool)} - have
        if new:
            op_support_deny()
    with system_ctx(c):  # 2.37.0 (#1150): instance admin manages the organisations themselves (also ones he is not in)
        if instance_mode(c) != "workspaces":
            _no_change()
        if not c.execute("SELECT 1 FROM orgs WHERE id=? AND personal_of IS NULL", (oid,)).fetchone():  # 2.47.3 (#1360)
            return err(tr("Not found"), 404)
        if c.execute("SELECT 1 FROM orgs WHERE id=? AND retired_at IS NOT NULL", (oid,)).fetchone():  # 2.152.0 A (#2167): read only
            return err(tr("This organisation is retired: its data is kept by law and can only be exported"), 409)
        _org_patch(c, oid, b)
        _member_ops(c, oid, b)  # 2.270.0 A (#3019): add / remove (or the sets with _prev) change only those people
        pv = b.get("_prev") if isinstance(b.get("_prev"), dict) else {}
        if "members" in b and "members" not in pv:  # the old whole-set format, per set (a mixed body keeps both)
            _set_members(c, oid, b["members"])
        if "admins" in b and "admins" not in pv:  # 2.28.0 (#935): the organisation's admins (a subset of its members)
            if not isinstance(b["admins"], list) or not all(isinstance(x, int) and not isinstance(x, bool) for x in b["admins"]):
                c.rollback()
                return err(tr("Invalid value: {0}", "admins"))
            # 2.143.0 A (#2151): only former admins become members; guest / read-only / accounting keep their role
            had = org_own_admin(c, oid)
            was = set(rck_org_admins(c, oid))  # 2.539.0 (#4373)
            c.execute("UPDATE org_members SET role='member' WHERE org_id=? AND role='admin'", (oid,))
            for x in b["admins"]:
                c.execute("UPDATE org_members SET role='admin' WHERE org_id=? AND user_id=? AND user_id IN (SELECT id FROM users WHERE kind!='agent')", (oid, x))
            for x in sorted(was - set(rck_org_admins(c, oid))):  # 2.539.0 (#4373): demoted by the whole set
                rck_admin_gone(c, oid, x)
            keep_own_admin(c, oid, had)  # 2.306.0 Fix-1 (#2875 review): hosted: the organisation keeps an admin of its own
            acx_drop()  # 2.143.0 A (#2151, review): the request's cached roles follow
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
        raise Denied(400, tr("Invalid value: {0}", tr("Colour")))
    return v


def _org_patch(c, oid, b, own_only=None):
    if "name" in b:
        # 2.551.0 (#4635): the same rule as org_create (a retired organisation's name is free, another spelling of its own
        # name is no clash). own_only=uid: an organisation admin sees only the companies uid made himself (see org_self_name_taken)
        nm = _clean_name(b["name"])
        q, a = "SELECT 1 FROM orgs WHERE id<>? AND lower(name)=lower(?) AND personal_of IS NULL AND retired_at IS NULL", [oid, nm]
        if own_only is not None:
            q, a = q + " AND self_made=?", a + [own_only]
        if c.execute(q, a).fetchone():
            c.rollback()
            raise Denied(409, tr("An organisation with this name exists"))
        c.execute("UPDATE orgs SET name=? WHERE id=?", (nm, oid))
    if "icon" in b:
        v = _clean_icon(b["icon"])
        old = (c.execute("SELECT icon FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0] or ""
        if v or not org_icon_tok(old):  # 2.87.9 (#1913): an empty symbol keeps the own picture (removed by DELETE .../icon)
            c.execute("UPDATE orgs SET icon=? WHERE id=?", (v, oid))
            org_icon_drop_file(oid, old)  # an emoji replaces the own picture
    if "domains" in b:
        # 2.422.0 (#2937), 2.467.0 (#3898): only an admin of the server sets e-mail domains, for every organisation: they decide
        # whose registrations land here. What an organisation has stays; its own value sent back unchanged is no change.
        v = _clean_domains(b["domains"])
        if g.user["is_admin"]:
            c.execute("UPDATE orgs SET domains=? WHERE id=?", (v, oid))
        elif v != _clean_domains((c.execute("SELECT domains FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0] or ""):
            raise Denied(403, tr("Only an admin of this server sets the e-mail domains of an organisation"))


@app.delete("/api/admin/orgs/<int:oid>")
def org_delete(oid):
    """2.28.0 (#935): the instance admin deletes an organisation (mode workspaces) -- only one without lists (409 otherwise:
    its owners move or delete them first). 2.23.0: 403 in the other modes. 2.152.0 A (#2167): office data under a legal
    period (orgretain.odl_retention) retires it instead; wiki pages, tables or office data that would go along (and the
    retirement) answer 409 with the numbers until ?confirm=1; a retired one goes only after its period."""
    _need_admin()
    c = db()
    from .orgretain import odl_dismantle, odl_retire, odl_retired
    with system_ctx(c):  # 2.37.0 (#1150): instance admin manages the organisations themselves (also ones he is not in)
        if instance_mode(c) != "workspaces":
            _no_change()
        if not c.execute("SELECT 1 FROM orgs WHERE id=? AND personal_of IS NULL", (oid,)).fetchone():  # 2.47.3 (#1360)
            return err(tr("Not found"), 404)
        n = c.execute("SELECT COUNT(*) FROM lists WHERE org_id=?", (oid,)).fetchone()[0]
        if n:
            return err(tr("This organisation still has {0} projects: their owners move or delete them first", n), 409)
        ret_need_unheld(c, oid)  # 2.545.0 (#4595): not while the switch "Extend the lock" is on
        info = odl_delete_info(c, oid)
        if info["kept_until"] and info["kept_until"] > (odl_retired(c, oid) or ""):  # 2.239.0 C (#2874): the newer period is noted
            c.execute("UPDATE orgs SET retain_until=? WHERE id=?", (info["kept_until"], oid))
            c.commit()
        if info["kept_until"] and info["kept_until"] >= iso(now_utc())[:10]:
            return err(tr("This organisation is kept until {0} by law (invoices, receipts, logbook): it can be deleted after that", info["kept_until"]), 409)
        confirm = request.args.get("confirm") == "1"
        from .orgleave import olv_early, olv_gone_news
        if olv_early(c, oid):  # 2.361.0 (#2920): the members were told a day: it waits until then (or the notice is taken back)
            return err(tr("The members were told that this organisation is deleted on {0}: it can be deleted from that day on", olv_early(c, oid)), 409)
        if info["retain_until"] and not info["kept_until"]:
            if not confirm:
                return jsonify(error=tr("This organisation keeps {0} by law until {1}: it is retired instead of deleted. Export it first, then confirm.",
                                        odl_text(info["kept"]), info["retain_until"]), **info), 409
            olv_gone_news(c, oid, (c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0])  # 2.361.0 (#2920)
            odl_retire(c, oid, info["retain_until"])  # review F6: the acting admin may keep the files
            bump(c)
            c.commit()
            return jsonify(ok=True, retired=True, retain_until=info["retain_until"])
        if info["content"] and not confirm and not info["kept_until"]:
            return jsonify(error=tr("This organisation still has {0}: export it first, then confirm the deletion.", odl_text(info["content"])), **info), 409
        from ..files.store import fs_org_live
        n = fs_org_live(c, oid)  # 2.48.0 (#1207): nothing of the file store disappears with it (the trash does)
        if n and not info["kept_until"]:
            return err(tr("This organisation still has {0} folders and files in its file store: delete them first", n), 409)
        # #3090: its documents locked before the deletion's first write (no deadlock with a recognition run, users.user_delete)
        c.execute("SELECT node_id FROM doc_meta WHERE org_id=? ORDER BY node_id FOR UPDATE", (oid,)).fetchall()
        from ..admin.retexport import rx_alert, rx_gate, rx_subject
        bad, retained = rx_gate(c, rx_subject(c, "org", oid))  # 2.146.0 D (#2468): the retention export (or its waiver) first
        if bad:
            return bad
        oname = (c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0]
        from ..admin.hosting import hosted
        from ..office.olock import OLK_BYPASS
        olv_gone_news(c, oid, oname)  # 2.361.0 (#2920): every member learns it, with what of theirs goes along
        tok = OLK_BYPASS.set(hosted())  # 2.152.0 (#2167, review A2): the hosted instance keeps no booked receipts (rx_gate passed)
        try:
            todo = odl_dismantle(c, oid)  # 2.152.0 A: the steps shared with the account deletion and the retention run
        finally:
            OLK_BYPASS.reset(tok)
        bump(c)
        c.commit()
        unlink_files(todo)
        if retained:
            rx_alert(retained[0], [g.user["username"], oname])
        return jsonify(ok=True)


def odl_delete_info(c, oid):
    """2.152.0 A (#2167): what deleting organisation oid means (the caller is an instance admin, system context): content
    that goes along, office data kept by law (retain_until), kept_until of an organisation retired already, whether the
    caller may export it (an admin of it; its former admins for a retired one, review A4: not a retired personal office;
    2.239.0 C (#2943): can_retention = the retention export of a retired one, for the instance admins when no former admin is left)."""
    from .orgretain import odl_admin_export, odl_content, odl_more, odl_more_text, odl_retention, odl_retired
    kept = odl_retired(c, oid)
    ret = odl_retention(c, oid) if kept is None else {"counts": {}, "until": None}
    if kept is not None:  # 2.239.0 C (#2874): the period anew, as the watchdog does (odl_retired_prune): newer data keeps it longer
        kept = max(kept, odl_retention(c, oid)["until"] or "")
    from ..files.store import fs_org_live
    more = odl_more(c, oid)  # 2.272.0 D (#3029): the rest that goes along (catalogue), for the dialog only
    from .orgleave import olv_members, olv_notice
    return {"members": olv_members(c, oid), "notice": olv_notice(c, oid),  # 2.361.0 (#2920): what is whose, the day the members were told
            "content": odl_content(c, oid), "more": more, "more_text": odl_more_text(more), "kept": ret["counts"], "retain_until": ret["until"], "kept_until": kept or None,
            "retired": kept is not None, "lists": c.execute("SELECT COUNT(*) FROM lists WHERE org_id=?", (oid,)).fetchone()[0],
            "files": fs_org_live(c, oid), "can_export": odl_admin_export(c, oid) or org_role(c, me(), oid) == "admin",
            "can_retention": kept is not None and odl_admin_export(c, oid, retention=True)}  # 2.239.0 C (#2943): the retention export only


ODL_WORDS = {"wiki_pages": ("{0} knowledge page", "{0} knowledge pages"), "tables": ("{0} table", "{0} tables"),
             "office_documents": ("{0} document", "{0} documents"), "documents": ("{0} document", "{0} documents"),
             "office_archive": ("{0} archive entry", "{0} archive entries"), "archive": ("{0} archive entry", "{0} archive entries"),
             "trips": ("{0} trip", "{0} trips"), "drives": ("{0} drive", "{0} drives"), "clients": ("{0} client", "{0} clients"),
             "receipts": ("{0} receipt", "{0} receipts"), "trip_receipts": ("{0} receipt", "{0} receipts"),
             # 2.152.0 (#2167, review A6)
             "cash": ("{0} cash book entry", "{0} cash book entries"), "bank": ("{0} bank transaction", "{0} bank transactions"),
             "meals": ("{0} entertainment receipt", "{0} entertainment receipts"),
             "letters": ("{0} sent letter", "{0} sent letters"),  # 2.184.0 A (#2628)
             # 2.239.0 C (#2874)
             "open_receipts": ("{0} receipt", "{0} receipts"), "einvoices": ("{0} invoice", "{0} invoices"),
             "payments": ("{0} payment", "{0} payments"), "signoffs": ("{0} confirmed sign-off", "{0} confirmed sign-offs"),
             "procdocs": ("{0} version of the procedure documentation", "{0} versions of the procedure documentation"),
             "assets": ("{0} device", "{0} devices"),  # 2.355.0 B (#2845): the asset register
             "bookarch": Nn_("{0} archived booking", "{0} archived bookings")}  # 2.414.0 (#3502): the booking archive


def odl_text(counts):
    """"3 knowledge pages, 2 tables" (translated) of {key: n}."""
    return ", ".join(trn(*ODL_WORDS[k], n) for k, n in counts.items() if n and k in ODL_WORDS)


@app.get("/api/admin/orgs/<int:oid>/delete-info")
def odl_delete_info_get(oid):
    """2.152.0 A (#2167): for the delete dialog of the organisations list -- see odl_delete_info."""
    _need_admin()
    c = db()
    with system_ctx(c):  # instance admin: numbers of an organisation they need not be in, no content
        if not c.execute("SELECT 1 FROM orgs WHERE id=? AND personal_of IS NULL", (oid,)).fetchone():
            return err(tr("Not found"), 404)
        return jsonify(odl_delete_info(c, oid))


def oc_drop_office_dir(oid):
    """2.42.0 (#828): remove the office folder of a deleted organisation (stored documents, archive PDFs, logos)."""
    import shutil
    d = os.path.join(OFFICE_DIR, str(int(oid)))
    if os.path.isdir(d) and not os.path.islink(d):
        shutil.rmtree(d, ignore_errors=True)
        if os.path.exists(d):  # 2.152.0 A (#2167): what could not be removed is logged (count, path below OFFICE_DIR), not swallowed
            n = sum(len(f) for _, _, f in os.walk(d))
            print(f"organisation {int(oid)}: {n} file(s) left in office/{int(oid)} after the deletion", flush=True)


@app.put("/api/admin/orgs/visibility")
def org_visibility():
    """{mode: all | org | contacts}: whom people see. 2.46.0 (#1592): fixed (the members of one's organisations +
    connections; shared: own contacts) -- always 403, like the former modes organisation / workspaces."""
    _need_admin()
    _no_change()


# ---------------------------------------------------------------- 2.28.0 (#935): my organisations, their admins
def _need_org_admin(c, oid):
    """The current person administers organisation oid (404 when not even a member)."""
    if org_need_person(c, oid) != "admin":
        raise Denied(403, tr("Only an admin of this organisation can do this"))


def org_need_person(c, oid):
    """2.361.2 (#2923, was the start of _need_org_admin): the current person (no agent: 403) is in organisation oid (404
    otherwise; a retired one 409) -> their role."""
    from ..agents.core import need_person
    need_person(403, tr("Agents cannot use this endpoint"))
    with system_ctx(c):  # 2.223.2 A (#2859): a membership row left in a retired organisation = read only (409 as org_update)
        if c.execute("SELECT 1 FROM orgs o JOIN org_members m ON m.org_id=o.id AND m.user_id=? WHERE o.id=? AND o.retired_at IS NOT NULL",
                     (me(), oid)).fetchone():
            raise Denied(409, tr("This organisation is retired: its data is kept by law and can only be exported"))
    role = org_role(c, me(), oid)
    if not role:
        raise Denied(404)
    return role


def org_mine_dict(c, r, uid):
    from ..collab.comments import user_names
    mem = c.execute("SELECT m.user_id, m.role, u.kind, u.disabled, u.signup FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? ORDER BY lower(u.display_name), u.id", (r["id"],)).fetchall()
    from .orgroles import org_sees_all, org_writes, roles_public
    full = org_sees_all(c, uid, r["id"])
    if not full:  # 2.143.0 A (#2151): a guest / accounting sees only the people they share something with (and the admins)
        near = _connections(c, uid) | {uid}
        mem = [m for m in mem if m["user_id"] in near or m["role"] == "admin"]
    names = user_names(c, [m["user_id"] for m in mem])
    admin = org_role(c, uid, r["id"]) == "admin"  # 2.464.0 (#3882): they see a waiting registration and decide it
    return {"id": r["id"], "name": r["name"], **org_icon_fields(r), "color": r["color"] or "", "domains": r["domains"],  # 2.87.9 (#1913)
            "photo_meta_strip": bool(r["photo_meta_strip"]),  # 2.61.0 B (#1819)
            "ext_links": bool(r["ext_links"]),  # 2.112.1 B (#2058): external share links of the file store allowed
            "asst_comments": bool(r["asst_comments"]),  # 2.240.0 (#2884): the assistant may read other members' comments
            "chn_content": bool(r["chn_content"]),  # 2.240.0 (#2867): personal channels get the content of the organisation's lists
            "member_agents": bool(r["member_agents"]),  # 2.361.4 (#2928): members may keep their own agents in it
            "areas_off": [x for x in (r["areas_off"] or "").split(",") if x],  # 2.409.0 (#3490): areas its admins switched off
            "nav_off": nav_org_off(r),  # 2.418.0 (#3560): menu points its admins switched off for the members
            "role": org_role(c, uid, r["id"]) or "member",
            "members": [{"id": m["user_id"], "name": names.get(m["user_id"], ""), "role": m["role"] if m["role"] in ORG_ROLES else "guest",
                         "agent": (m["kind"] or "user") == "agent", "disabled": bool(m["disabled"]),
                         **({"pending": True} if admin and m["signup"] == "pending" else {})} for m in mem],  # 2.464.0 (#3882)
            "lists": c.execute("SELECT COUNT(*) FROM lists WHERE org_id=? AND deleted_at IS NULL", (r["id"],)).fetchone()[0] if full else 0,
            "limited": not full or not org_writes(c, uid, r["id"]),  # 2.143.0 A (#2151): guest / read-only / accounting
            "roles": roles_public(c)}  # 2.143.0 A (#2151): the roles an admin hands out, with their explanation


@app.get("/api/orgs")
def orgs_mine():
    """2.28.0 (#935): the organisations I belong to (my workspaces), their members and my role; mode + whether an
    organisation admin may manage members here (modes multi / workspaces; in the mode organisation the instance admin does)."""
    from ..agents.core import need_person
    c = db()
    need_person(403, tr("Agents cannot use this endpoint"))
    uid = me()
    oids = user_orgs(c, uid)
    rows = c.execute(f"SELECT * FROM orgs WHERE id IN ({','.join('?' * len(oids)) or 'NULL'}) ORDER BY id", oids).fetchall()
    m = instance_mode(c)
    from .orginvite import ojn_mine
    return jsonify(orgs=[org_mine_dict(c, r, uid) for r in rows], mode=m, manage=m == "workspaces", workspaces=has_workspaces(c),
                   mismatches={str(k): v for k, v in ws_mismatches(c, uid).items()},
                   joins=ojn_mine(c, uid),  # 2.148.1 A (#2480): invitations waiting for my answer
                   retired=odl_former(c, uid))  # 2.186.0 A (#2599): retired organisations I was an admin of (their export)


@app.patch("/api/orgs/<int:oid>")
def org_mine_update(oid):
    """2.28.0 (#935): {name?, icon?, domains?} -- an organisation admin renames it (modes multi / workspaces; in the mode
    organisation the name comes from the configuration or the instance admin). 2.467.0 (#3898): domains only by a server admin.
    2.53.0 B (#1474): {color?} -- its colour for every member ('' = the default tone); only here (an admin of this
    organisation), not in the instance admin's routes. 2.61.0 B (#1819): {photo_meta_strip?: bool} likewise."""
    c, b = db(), body()
    _need_org_admin(c, oid)
    if instance_mode(c) != "workspaces":
        _no_change()
    if "color" in b:
        c.execute("UPDATE orgs SET color=? WHERE id=?", (wsc_clean_color(b["color"]), oid))
    if "photo_meta_strip" in b:  # 2.61.0 B (#1819): remove the metadata of photos uploaded into the organisation (admins only)
        if not isinstance(b["photo_meta_strip"], bool):
            return err(tr("Invalid value: {0}", "photo_meta_strip"))
        c.execute("UPDATE orgs SET photo_meta_strip=? WHERE id=?", (int(b["photo_meta_strip"]), oid))
    if "ext_links" in b:  # 2.112.1 B (#2058): off = every external link of the organisation's files is dead at once (kept)
        if not isinstance(b["ext_links"], bool):
            return err(tr("Invalid value: {0}", "ext_links"))
        c.execute("UPDATE orgs SET ext_links=? WHERE id=?", (int(b["ext_links"]), oid))
    for k in ("asst_comments", "chn_content", "member_agents"):  # 2.240.0 (#2884, #2867), 2.361.4 (#2928): switches of the organisation (admins only)
        if k in b:
            if not isinstance(b[k], bool):
                return err(tr("Invalid value: {0}", k))
            if k == "asst_comments" and b[k]:  # 2.240.0 A (#2884): the members learn it when it goes on
                from ..assistant.web import asst_comments_notice
                asst_comments_notice(c, oid, me())
            c.execute(f"UPDATE orgs SET {k}=? WHERE id=?", (int(b[k]), oid))
    if "areas_off" in b:  # 2.409.0 (#3490): the areas switched off for every member (admins only); nothing is deleted
        from .wsareas import wsa_clean_org
        c.execute("UPDATE orgs SET areas_off=? WHERE id=?", (wsa_clean_org(b["areas_off"]), oid))
    if "share_defaults" in b:  # 2.470.0 (#3596): what new external links and file requests start with (admins only)
        from .sharedefs import sd_clean
        c.execute("UPDATE orgs SET share_defaults=? WHERE id=?", (sd_clean(b["share_defaults"]), oid))
    if "nav_off" in b:  # 2.418.0 (#3560): menu points switched off for every member (admins only); only the menus change
        c.execute("UPDATE orgs SET nav_off=? WHERE id=?", (nav_clean_org(b["nav_off"]), oid))
    _org_patch(c, oid, b, own_only=me())
    bump(c)
    c.commit()
    return jsonify(org_mine_dict(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone(), me()))


# ---------------------------------------------------------------- 2.87.9 (#1913): an own picture as the organisation's symbol
@app.post("/api/orgs/<int:oid>/icon")
def org_icon_upload(oid):
    """multipart "file": an organisation admin sets an own picture (JPEG / PNG / WebP, up to AVATAR_MAX_MB MB, cropped square
    in the app) as its symbol instead of the emoji. Re-encoded like a list icon (square PNG, no metadata), sealed with the
    organisation's key; the old picture file goes."""
    from flask import request
    import secrets
    c = db()
    _need_org_admin(c, oid)
    if instance_mode(c) != "workspaces":
        _no_change()
    f = request.files.get("file")
    if not f:
        return err(tr("No file"))
    raw = f.read(AVATAR_MAX_MB * 1024 * 1024 + 1)
    if len(raw) > AVATAR_MAX_MB * 1024 * 1024:
        return err(tr("The picture is too large (at most {0} MB)", AVATAR_MAX_MB), 413)
    try:
        png = list_icon_process(raw)
    except BadInput as e:
        return err(str(e))
    tok = secrets.token_urlsafe(12)
    os.makedirs(LIST_ICON_DIR, exist_ok=True)
    oc_write_file(c, oid, org_icon_path(oid, tok), png)
    old = (c.execute("SELECT icon FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0] or ""
    c.execute("UPDATE orgs SET icon=? WHERE id=?", ("u:" + tok, oid))  # as the colour in org_mine_update (its admin, checked above)
    bump(c)
    c.commit()
    org_icon_drop_file(oid, old)
    print("organisation", oid, "symbol picture set by", login_log_who(g.user), flush=True)
    return jsonify(org_mine_dict(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone(), me()))


@app.delete("/api/orgs/<int:oid>/icon")
def org_icon_delete(oid):
    """An organisation admin removes the own picture (the symbol is empty again: the app shows its default)."""
    c = db()
    _need_org_admin(c, oid)
    if instance_mode(c) != "workspaces":
        _no_change()
    old = (c.execute("SELECT icon FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0] or ""
    if org_icon_tok(old):
        c.execute("UPDATE orgs SET icon='' WHERE id=?", (oid,))
        bump(c)
        c.commit()
        org_icon_drop_file(oid, old)
    return jsonify(org_mine_dict(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone(), me()))


@app.get("/api/org-icon/<int:oid>/<tok>.png")
def org_icon_get(oid, tok):
    """An organisation's own picture: only for its members (404 for everybody else, also a wrong / old token)."""
    if g.get("user") is None:
        raise Denied(401)
    c = db()
    r = c.execute("SELECT icon FROM orgs WHERE id=? AND personal_of IS NULL", (oid,)).fetchone()
    if not r or r["icon"] != "u:" + tok or not re.fullmatch(r"[A-Za-z0-9_-]{8,40}", tok) or oid not in user_orgs(c, me()):
        raise Denied(404)
    p = org_icon_path(oid, tok)
    if not os.path.isfile(p):
        raise Denied(404)
    rs = oc_send_file(c, p, mimetype="image/png", max_age=31536000)  # sealed -> decrypted in memory
    rs.headers["Cache-Control"] = "private, max-age=31536000, immutable"
    return rs


@app.put("/api/orgs/<int:oid>/members")
def org_member_put(oid):
    """2.28.0 (#935): {user_id | email, role?: member | admin | guest | readonly | accounting (2.143.0 A, #2151)} -- an organisation admin adds a person (one they may see, or by
    e-mail address: the answer never says whether the address has an account) or changes a member's role. 2.148.1 A (#2480):
    a person who is not a member yet gets an invitation to accept (accounts/orginvite.py ojn_*); only an instance admin adds
    directly."""
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
        return err(tr("unknown person"), 404)
    cur = c.execute("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
    if cur and uid == me() and role != "admin" and _admins(c, oid) <= 1:
        return err(tr("The last admin of an organisation cannot step down: make somebody else an admin first"), 409)
    pending = False
    if cur:
        c.execute("UPDATE org_members SET role=? WHERE org_id=? AND user_id=?", (role, oid, uid))
        acx_drop()  # 2.143.0 A (#2151): the cached roles of this request
        if cur["role"] != role:
            org_role_news(c, oid, uid, role)  # 2.367.4 (#2974)
            if cur["role"] == "admin":
                rck_admin_gone(c, oid, uid)  # 2.539.0 (#4373)
            org_open_chan_off(c, oid, uid, role)  # 2.560.0 (#4698 b)
    elif uid != me() and (not g.user["is_admin"] or _operator_apart()):  # 2.148.1 A (#2480): an existing account joins only by accepting an invitation (2.306.0 D1, #2875: also the operator's)
        from .orginvite import ojn_invite
        ojn_invite(c, oid, uid, role)
        pending = True
    else:
        org_member_add(c, oid, uid, role)
        from ..collab.news import news_add
        news_add(c, uid, "share", list_id=None, data={"org": True, "name": c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()[0], "role": role,
                                                          "org_id": oid})  # 2.540.0 (#4383): news_org_mine compares the number
    bump(c)
    c.commit()
    if b.get("email"):  # 2.148.1 A (#2480): the same answer for every address (account or not, added or invited)
        return jsonify(ok=True, by_email=True)
    return jsonify(ok=True, by_email=False, **({"pending": True} if pending else {}),
                   org=org_mine_dict(c, c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone(), me()))


def org_open_chan_off(c, oid, uid, role):
    """2.560.0 (#4698 b): uid's role in oid became guest / accounting (no full reading): they leave the organisation's OPEN
    channels they had joined, with their personal agents (an open channel is the organisation's room, a member row there
    would keep reading it); closed channels stay (a personal invitation)."""
    from .orgroles import FULL_READ
    if role in FULL_READ:
        return
    with system_ctx(c):  # the person's own rows in the organisation's channels, also when an admin changes the role
        c.execute("DELETE FROM tchat_members WHERE (user_id=? OR user_id IN (SELECT user_id FROM agents WHERE owner_id=?)) AND room_id IN "
                  "(SELECT id FROM tchat_rooms WHERE kind='channel' AND is_open=1 AND org_id=?)", (uid, uid, oid))


def org_role_news(c, oid, uid, role):
    """2.367.4 (#2974): the person's role in the organisation changed: a News item (row "share"), never for one's own change."""
    from ..collab.news import news_add
    name = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()[0]
    news_add(c, uid, "orgrole", row="share", data={"org_id": oid, "name": name, "role": role})


def _admins(c, oid):
    return c.execute("SELECT COUNT(*) FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.role='admin' AND u.disabled=0", (oid,)).fetchone()[0]


def ol_client_fit(c, lid, oid):
    """2.86.0 (N11): list lid now in workspace oid (None = private) loses a client of another workspace. Returns the boundary
    (team/clients.py _org_boundary) for list_space_follow."""
    from ..team.clients import _org_boundary
    boundary = _org_boundary(c)
    if boundary:
        c.execute("UPDATE lists SET client_id=NULL WHERE id=? AND client_id IS NOT NULL AND client_id NOT IN"
                  " (SELECT id FROM clients WHERE org_id IS NOT DISTINCT FROM ?)", (lid, oid))
    return boundary


def ol_private(c, lid, uid):
    """2.361.0 (#2922): list lid of uid leaves its organisation into uid's private space (the caller checked why): its client
    of the organisation stays behind, the organisation's agents leave it (uid's own agents follow uid), its files get the
    owner's account key after the request."""
    old = c.execute("SELECT org_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
    c.execute("UPDATE lists SET org_id=NULL, brought_by=NULL WHERE id=?", (lid,))
    c.execute("DELETE FROM reading_orgs WHERE list_id=?", (lid,))  # 2.172.1 (#2689)
    # 2.86.0 (N11) + 2.401.0 (#2924): as list_org_set, its customer reports and bells go along
    list_space_follow(c, lid, old, ol_client_fit(c, lid, None))
    for (aid,) in c.execute("SELECT m.user_id FROM list_members m JOIN agents a ON a.user_id=m.user_id WHERE m.list_id=? "
                            "AND a.owner_id IS DISTINCT FROM ? AND a.org_id IS NOT NULL", (lid, uid)).fetchall():
        c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (lid, aid))
        c.execute("UPDATE tasks SET assignee_id=NULL WHERE list_id=? AND assignee_id=?", (lid, aid))
        dlg_gone(c, lid, aid)  # 2.473.0 (#3357): delegated tasks and watching of this list end
    from ..admin.orgcrypt_cli import oc_settle_kick
    oc_settle_kick([lid])  # 2.64.0 (#1864): its files get the owner's account key


def ol_back_log(c, oid, lr):
    """2.361.0 (#2922, review): a brought-in list that went back private is in the admins' history (as org_out's moves out)
    and told to the organisation's admins (News orglist moveout)."""
    from .orgout import oo_note
    with system_ctx(c):
        real = (c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0]
    oo_note(c, oid, real, "list", lr["name"], lr["id"], back=True)


def org_leave(c, oid, uid, heir, back=None):
    """uid leaves organisation oid: their lists of that workspace go to heir (an organisation admin), uid leaves every list
    of the organisation (members and the agents it owns there stay with the lists), their personal agents of that workspace
    become private. 2.361.0 (#2922): a list uid brought in from the private space (lists.brought_by) goes back there instead
    (its id appended to back), 2.365.1 (#3395) and so does what else they brought in (accounts/orgback.py, [kind, id] appended).
    The caller commits. Returns the number of lists transferred."""
    from ..lists.ownership import owner_transfer
    from .orgleave import OLV_AREAS, olv_memo, olv_snap
    if heir and heir != uid:
        ws_check_owner(c, oid, heir)  # 2.538.0 (#4371): every caller's heir is a member / admin of the organisation (409)
    snap = olv_snap(c, oid, uid)  # 2.363.3 (#3133): what the end of the membership takes away, for coming back within a day
    was_admin = c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=? AND role='admin'", (oid, uid)).fetchone()  # 2.539.0 (#4373)
    n, priv = 0, []
    for lr in c.execute("SELECT * FROM lists WHERE owner_id=? AND org_id=? AND is_inbox=0", (uid, oid)).fetchall():
        if lr["brought_by"] == uid and not lr["deleted_at"]:
            ol_private(c, lr["id"], uid)
            priv.append(lr["id"])
            ol_back_log(c, oid, lr)
            if back is not None:
                back.append(lr["id"])
        elif heir and heir != uid:
            owner_transfer(c, lr, heir, force=True)  # 2.64.1 (#1817): a list with the lock too (the heir waits for its key)
            c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (lr["id"], uid))
            from .orglists import _ol_log
            _ol_log(c, oid, lr, "owner", to_id=heir)  # 2.148.1 A (#2480): the handover is in the admins' history
            n += 1
        elif lr["deleted_at"]:  # 2.102.0 A (#1988): a list in the trash stays the organisation's (never the leaver's private one)
            continue
        else:
            ol_private(c, lr["id"], uid)
            priv.append(lr["id"])
    for (lid,) in c.execute("SELECT m.list_id FROM list_members m JOIN lists l ON l.id=m.list_id WHERE m.user_id=? AND l.org_id=?", (uid, oid)).fetchall():
        c.execute("DELETE FROM list_members WHERE list_id=? AND user_id=?", (lid, uid))
        c.execute("UPDATE tasks SET assignee_id=NULL WHERE list_id=? AND assignee_id=?", (lid, uid))
        dlg_gone(c, lid, uid)  # 2.473.0 (#3357): delegated tasks and watching of this list end
        c.execute("DELETE FROM task_people WHERE user_id=? AND task_id IN (SELECT id FROM tasks WHERE list_id=?)", (uid, lid))
    if priv:  # 2.352.0 F (#2748, review N3): the lists now private leave the organisation's tree, its folders' roles end
        from ..lists.groups import grp_sync
        grp_sync(c, priv)
    OLV_AREAS["home"](c, oid, uid, back)  # 2.365.1 (#3395): after the lists: what hangs at a project that went back stays attached
    # 2.473.0 (#3357): watching without a membership ends the same way (a list open to the organisation)
    c.execute("DELETE FROM task_watchers WHERE user_id=? AND task_id IN (SELECT id FROM tasks WHERE list_id IN (SELECT id FROM lists WHERE org_id=? AND owner_id!=?))", (uid, oid, uid))
    # 2.83.0 (#1725): tasks assigned without joining (a list everyone in the organisation may edit)
    c.execute("UPDATE tasks SET assignee_id=NULL WHERE assignee_id=? AND list_id IN (SELECT id FROM lists WHERE org_id=? AND owner_id!=?)", (uid, oid, uid))
    # 2.363.3 (#3133): coming along without a membership too (brought back by joining again in a list open to the organisation)
    c.execute("DELETE FROM task_people WHERE user_id=? AND task_id IN (SELECT id FROM tasks WHERE list_id IN (SELECT id FROM lists WHERE org_id=? AND owner_id!=?))", (uid, oid, uid))
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
    # 2.87.0 (#1983): the leaver and their agents are no longer invited to the events of the organisation's calendars
    c.execute("DELETE FROM event_attendees WHERE user_id IN (%s) AND event_id IN (SELECT e.id FROM events e JOIN ev_cals k "
              "ON k.id=e.cal_id WHERE k.org_id=?)" % ",".join("?" * (len(ags) + 1)), (uid, *ags, oid))
    c.execute("UPDATE agents SET org_id=NULL WHERE owner_id=? AND org_id=?", (uid, oid))
    with system_ctx(c):  # 2.223.2 B (#2860): their office rights groups go too (coming back = no old groups)
        c.execute("DELETE FROM office_rgroup_members WHERE org_id=? AND user_id IN (%s)" % ",".join("?" * (len(ags) + 1)), (oid, uid, *ags))
        c.execute("DELETE FROM doc_fetchers WHERE org_id=? AND user_id=?", (oid, uid))  # 2.425.0 (#3453 review): their receipt fetchers end (coming back = no old key)
    c.execute("DELETE FROM org_members WHERE org_id=? AND user_id=?", (oid, uid))
    if was_admin:  # 2.539.0 (#4373): an admin who saw the recovery key leaves: the other admins are asked to renew it
        rck_admin_gone(c, oid, uid)
    # 2.351.0 D (#3214): their read marks in the organisation's channels and list conversations go too (tchat_sig_q
    # counts the marks of every room with a mark of mine: the reading in rooms left would stay visible); 2.373.0 (#3337):
    # groups have no organisation and the person stays a member there -- their marks stay
    c.execute("DELETE FROM tchat_reads WHERE user_id IN (%s) AND room_id IN (SELECT id FROM tchat_rooms WHERE org_id=? OR "
              "list_id IN (SELECT id FROM lists WHERE org_id=?))" % ",".join("?" * (len(ags) + 1)), (uid, *ags, oid, oid))
    with system_ctx(c):  # 2.560.0 (#4698 a): their channel memberships and file / knowledge shares in the organisation end
        # (coming back the same day, also as a guest = no old closed channels, no old folder shares)
        c.execute("DELETE FROM tchat_members WHERE user_id IN (%s) AND room_id IN (SELECT id FROM tchat_rooms WHERE org_id=?)"
                  % ",".join("?" * (len(ags) + 1)), (uid, *ags, oid))
        c.execute("DELETE FROM fs_shares WHERE (user_id IN ({0}) OR agent_id IN ({0})) AND node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)"
                  .format(",".join("?" * (len(ags) + 1))), (uid, *ags, uid, *ags, oid))
    # 2.53.0 (#1424, review): the leaver's task bells in the organisation go too (else the nightly boundary check alarms)
    c.execute("DELETE FROM task_bell WHERE org_id=? AND user_id IN (%s)" % ",".join("?" * (len(ags) + 1)), (oid, uid, *ags))
    from ..sheets.shshare import shs_leave
    shs_leave(c, oid, [uid, *ags])  # 2.124.0 C (#2113): their shares of the organisation's tables end
    acx_drop()  # 2.36.2 (#1142): the request's access contexts follow the new memberships
    olv_memo(c, oid, uid, snap)
    return n


@app.delete("/api/orgs/<int:oid>/members/<int:uid>")
def org_member_remove(oid, uid):
    """2.28.0 (#935): an organisation admin removes a member (or a member leaves: uid = self). The person's lists of this
    workspace go to the admin who removes them (leaving: to the organisation's first other admin), the person leaves every
    list of the organisation. The last admin cannot leave. 2.88.0 (#1980): ?to=<id> = another active member gets the lists."""
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
    if uid != me() and request.args.get("to"):  # 2.88.0 (#1980): the admin hands the person's lists to another active member
        heir = org_heir_to(c, oid, uid, request.args["to"])
        if heir is None:
            return err(tr("The projects can only go to another active person of the organisation"), 400)
    operator = None
    if heir is None and _operator_apart():  # 2.306.0 D1 (#2875): a hosted instance's operator never takes a customer's organisation over
        return err(tr("The last admin of an organisation cannot leave it: make somebody else an admin first"), 409)
    if heir is None:  # the only admin leaves: the operator (an instance admin) takes the organisation over and is told
        operator = (c.execute("SELECT id FROM users WHERE is_admin=1 AND disabled=0 AND kind!='agent' AND id!=? ORDER BY id LIMIT 1", (uid,)).fetchone() or [None])[0]
        if operator is None:
            return err(tr("The last admin of an organisation cannot leave it: make somebody else an admin first"), 409)
        c.execute("INSERT INTO org_members(org_id,user_id,role) VALUES(?,?,'admin') ON CONFLICT(org_id,user_id) DO UPDATE SET role='admin'", (oid, operator))
        acx_drop()
        heir = operator
    oname = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()[0]  # 2.37.0 (#1150): before leaving it (then invisible)
    back = []
    n = org_leave(c, oid, uid, heir, back=back)  # 2.361.0 (#2922): what the person brought in goes back to their private space
    from ..collab.news import news_add
    if operator:
        news_add(c, operator, "share", list_id=None, data={"org": True, "name": oname, "role": "admin", "handover": n, "org_id": oid}, actor=uid)  # 2.540.0 (#4383)
        print("organisation", oid, "last admin", uid, "left: operator", operator, "took it over,", n, "lists", flush=True)
    if uid != me():
        from ..collab.comments import user_names
        # 2.148.1 A (#2480): the person learns that their lists of the organisation stayed with it (and with whom)
        news_add(c, uid, "unshare", list_id=None, data={"org": True, "name": oname, "org_id": oid, **({"lists": n, "to": user_names(c, [heir]).get(heir, "")} if n else {}),
                                                        **({"back": len(back)} if back else {})})  # 2.361.0 (#2922)
    bump(c)
    c.commit()
    print("organisation", oid, "member", uid, "removed by" if uid != me() else "left,", login_log_who(g.user), "lists transferred:", n, flush=True)
    return jsonify(ok=True, transferred=n, back=len(back))


def org_warm(c, uid):
    """2.369.6 (#3139): GET /api/state asks this structure of the signed-in person anyway; read it in the context hook's
    "system" phase (core/access.py acx_conn_hook), before the first statement as the person, into the request caches above
    -- so the state does not switch its database context back and forth per helper (22 set_config before)."""
    from .orgroles import org_roles_of
    org_roles_of(c, uid)
    has_workspaces(c)
    visible_people(c, uid)
    org_peers(c, uid)
    if user_orgs(c, uid):
        org_names(c, uid)


acx_warm_register("/api/state", org_warm)
