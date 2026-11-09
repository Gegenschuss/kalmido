"""2.769.0 (#5352): "Recently edited" over the areas Knowledge, Files and Reading -- ONE route for the overview "All
workspaces" of these areas and the start page's block "Recently edited" (static/js/recent.js). Read only: it makes nothing,
stores nothing and changes no area.

    GET /api/recent?space=all | private | org:<id>&limit=20&areas=wiki,files,reading
        -> {space, items: [{area (wiki | files | reading), id, space (private | org:<id> | shared), title, place, by, by_name,
            at, url (reading: the link)}]}, newest first; limit 1..50 (default 20); space all (default) = every workspace plus
            what others shared with the person, private / org:<id> = only that workspace (an organisation the person is not
            in = 404)

Rights: every area answers with its OWN check, there is no check of this module (the shared core, 2.558.0):
  wiki     the spaces through wiki/pages.py wiki_space (member, need_org_area: guests / accounting nothing), every page then
           through wiki_may_read (wkfolder.wkf_role: closed folders); pages shared with the person from spaces she is not in
           through wkshare.wsh_reach (the list "Shared with me"); a page of a space with a lock (ciphertext names) is left out
  files    the file store's own visibility (files/store.py fs_visible_sql_c: owner, organisation, shares, mail, receipts,
           references), fs_mail_rows like a folder's listing and fsviews.fsv_drop (the folders of other areas, as the file
           store's own views); files of a locked folder (fslock: names are ciphertexts) are left out
  reading  the spaces through life/rss.py rss_space, the projects through reading.rl_lists (vis_sql) -- the view "Read later"
An area the organisation's admins switched off (accounts/wsareas.py wsa_org_off) gives nothing of that organisation, a module
the person switched off (features) nothing at all. People only: an agent or an API token gets 403 (like Read later and the
favourites), so the agent API has no such route (docs/AGENTS.md unchanged)."""
from flask import g, has_request_context, jsonify, request

from ..core.access import Denied
from ..core.config import app
from ..core.db import db
from ..core.errors import BadInput
from ..core.i18n import tr
from ..accounts.session import me
from ..accounts.orgs import user_orgs
from ..accounts.wsareas import WSA_KEY_RE, wsa_org_off
from ..collab.comments import user_names
from ..life.model import feat_on
from ..life.reading import rl_lists, rl_site
from ..life.rss import rss_space
from ..files.fslock import fsl_map
from ..files.fsviews import fsv_drop
from ..files.store import fs_mail_rows, fs_visible_sql_c
from ..wiki.pages import wiki_may_read, wiki_space
from ..wiki.wkfolder import wkf_locked
from ..wiki.wkshare import wsh_reach

RCN_LIMIT, RCN_MAX = 20, 50
RCN_AREAS = ("wiki", "files", "reading")
RCN_FEAT = {"wiki": "wiki", "files": "files", "reading": "reading"}  # the module switch of the person (features)
RCN_WSA = {"wiki": "wiki", "files": "ablage", "reading": "reading"}  # the area id an organisation's admins switch off


def rcn_person():
    """403 for an agent or an API token (the same rule as Read later, life/reading.py rl_need)."""
    u = getattr(g, "user", None) if has_request_context() else None
    if (u is not None and "kind" in u.keys() and u["kind"] == "agent") or (has_request_context() and g.get("auth_via") == "token"):
        raise Denied(403, tr("Recently edited is only available in the app"))


def rcn_space_arg(c, uid, v):
    """?space= -> (key, org id | None): 'all' | 'private' | 'org:<id>' (an organisation uid is not in: 404)."""
    v = (v or "all").strip()
    if v == "all":
        return "all", None
    if not WSA_KEY_RE.fullmatch(v):
        raise BadInput(tr("Invalid value: {0}", "space"))
    if v == "private":
        return "private", None
    oid = int(v[4:])
    if oid not in user_orgs(c, uid):
        raise Denied(404)
    return v, oid


def _sp_key(c, uid, org_id, owner_id):
    """The workspace an item opens in for uid; 'shared' = shared with uid from a workspace that is not uid's own."""
    if org_id:
        return "org:%d" % org_id if org_id in user_orgs(c, uid) else "shared"
    return "private" if owner_id == uid else "shared"


def _spaces(c, uid, key, oid):
    """The workspaces asked for: [None (private), org ids ...]."""
    if key == "all":
        return [None, *user_orgs(c, uid)]
    return [oid]


def _off(c, oid, area):
    return bool(oid) and RCN_WSA[area] in wsa_org_off(c, oid)


def _want(key, sp):
    """Is an item of workspace sp ('private' | 'org:<id>' | 'shared') asked for?"""
    return key == "all" or sp == key


# ---------------------------------------------------------------- knowledge pages
def rcn_wiki(c, uid, key, oid, limit):
    orgs, own = [], False
    for o in _spaces(c, uid, key, oid):
        if _off(c, o, "wiki"):
            continue
        try:
            got = wiki_space(c, uid, "org:%d" % o if o else "private")  # the area's own check of a space (404 / 403)
        except (Denied, BadInput):
            continue
        if got:
            orgs.append(int(got))
        else:
            own = True
    conds, args = [], []
    if own:
        conds.append("(org_id IS NULL AND owner_id=?)")
        args.append(uid)
    if orgs:
        conds.append(f"org_id IN ({','.join(str(o) for o in orgs)})")
    rows = []
    if conds:
        rows = c.execute(f"SELECT * FROM wiki_pages WHERE deleted_at IS NULL AND ({' OR '.join(conds)}) "
                         f"ORDER BY updated_at DESC, id DESC LIMIT ?", (*args, limit * 4)).fetchall()
    if key == "all":  # pages others shared with uid from spaces uid does not read anyway (the list "Shared with me")
        shared, _info = wsh_reach(c, uid)
        rows = list(rows) + [r for r in shared if not _off(c, r["org_id"], "wiki")]
    out, seen = [], set()
    for r in sorted(rows, key=lambda x: (rcn_at_key(x["updated_at"]), x["id"]), reverse=True):
        if r["id"] in seen or wkf_locked(c, r) or not wiki_may_read(c, uid, r):
            continue
        seen.add(r["id"])
        parts = str(r["path"]).split("/")
        out.append({"area": "wiki", "id": r["id"], "space": _sp_key(c, uid, r["org_id"], r["owner_id"]), "title": parts[-1],
                    "place": "/".join(parts[:-1]), "by": r["updated_by"], "at": r["updated_at"]})
        if len(out) >= limit:
            break
    return out


# ---------------------------------------------------------------- files of the file store
def rcn_files(c, uid, key, oid, limit):
    if key == "private":
        w, a = "org_id IS NULL AND owner_id=?", [uid]
    elif key == "all":
        w, a = "TRUE", []
    else:
        w, a = "org_id=?", [oid]
    rows = c.execute(f"SELECT * FROM fs_nodes WHERE kind='file' AND deleted_at IS NULL AND {w} AND id IN {fs_visible_sql_c(c, uid)} "
                     f"ORDER BY updated_at DESC, id DESC LIMIT ?", (*a, limit * 4)).fetchall()
    rows = fsv_drop(c, fs_mail_rows(c, uid, rows))  # like a folder's listing; no file of another area's folders
    lk = fsl_map(c, [r["id"] for r in rows])
    rows = [r for r in rows if r["id"] not in lk and not _off(c, r["org_id"], "files")][:limit]
    by = {}
    if rows:
        q = ",".join(str(int(r["id"])) for r in rows)
        by = {n: u for n, u in c.execute(f"SELECT v.node_id, v.created_by FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id "
                                         f"AND v.no=n.cur_version WHERE v.node_id IN ({q})")}
    return [{"area": "files", "id": r["id"], "space": _sp_key(c, uid, r["org_id"], r["owner_id"]), "title": r["name"], "place": "",
             "by": by.get(r["id"]) or r["created_by"] or r["owner_id"], "at": r["updated_at"]} for r in rows]


# ---------------------------------------------------------------- read later
def rcn_reading(c, uid, key, oid, limit):
    lsp = {}
    for o in _spaces(c, uid, key, oid):
        if _off(c, o, "reading"):
            continue
        try:
            got = rss_space(c, uid, "org:%d" % o if o else "private")  # the area's own check of a space
        except (Denied, BadInput):
            continue
        for lid in rl_lists(c, uid, got):
            lsp[lid] = "org:%d" % got if got else "private"
    if not lsp:
        return []
    ph = ",".join("?" * len(lsp))
    rows = c.execute(f"SELECT id, list_id, title, url, created_at, created_by FROM tasks WHERE list_id IN ({ph}) AND deleted_at IS NULL "
                     f"AND parent_id IS NULL AND status=0 ORDER BY created_at DESC, id DESC LIMIT ?", (*lsp, limit)).fetchall()
    return [{"area": "reading", "id": r["id"], "space": lsp[r["list_id"]], "title": r["title"], "place": rl_site(r["url"]),
             "url": r["url"] or "", "by": r["created_by"], "at": r["created_at"]} for r in rows]


RCN_GET = {"wiki": rcn_wiki, "files": rcn_files, "reading": rcn_reading}


def rcn_at_key(v):
    """A sortable form of a stored UTC time: the areas write seconds (files, tasks) or milliseconds (pages)."""
    v = str(v or "")
    return v[:19] + (v[19:23] if v[19:20] == "." else ".000")


def rcn_items(c, uid, space="all", limit=RCN_LIMIT, areas=RCN_AREAS):
    """The newest items of the areas over the workspaces asked for (module docstring) -> (space key, [item])."""
    key, oid = rcn_space_arg(c, uid, space)
    out = []
    for a in areas:
        if feat_on(c, uid, RCN_FEAT[a]):
            out += [x for x in RCN_GET[a](c, uid, key, oid, limit) if _want(key, x["space"])]
    out.sort(key=lambda x: (rcn_at_key(x["at"]), x["area"], x["id"]), reverse=True)
    out = out[:limit]
    names = user_names(c, {x["by"] for x in out})
    for x in out:
        x["by_name"] = names.get(x["by"], "")
    return key, out


@app.get("/api/recent")
def recent_get():
    """?space=all|private|org:<id> &limit=1..50 &areas=wiki,files,reading -> {space, items} (module docstring)."""
    rcn_person()
    c, uid = db(), me()
    try:
        limit = int(request.args.get("limit") or RCN_LIMIT)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "limit")) from None
    if not 1 <= limit <= RCN_MAX:
        raise BadInput(tr("Invalid value: {0}", "limit"))
    areas = [x for x in (request.args.get("areas") or ",".join(RCN_AREAS)).split(",") if x]
    if not areas or any(x not in RCN_AREAS for x in areas):
        raise BadInput(tr("Invalid value: {0}", "areas"))
    key, items = rcn_items(c, uid, request.args.get("space"), limit, tuple(dict.fromkeys(areas)))
    return jsonify(space=key, items=items)
