"""2.579.0 (#4802): saved views of the documents search -- any combination of the documents search (the search field with its
syntax, the filters, the sort; docs/dsearch.py, docs/web.py doc_query) under a name. The sidebar shows them under "Files"
next to "Documents" and "To review" with their number of hits, a star pins one to the favourites (lists/favorites.py,
kind docview), a switch shows it as a block on Today (the first five hits + the number; the user setting dv_today).

A view is an object of the shared core (docs/dev/kern.md, kind 'docview', table doc_views of migrations.d/4802_a.py): no share
table, no check and no save path of its own. Private per person (org_id NULL: only its owner sees it); in an organisation's
workspace an admin shares it with everyone of the organisation (core/writes.py obj_space_set: org_id = the organisation, the
members read it, org_access "view"; org_join "admin": no member brings one there; 2.657.0, #4828: a view is always created private, also by an admin) and takes it back.
Agents see a view only through an explicit share (the core's default role gives agents nothing), on the core's agent routes.

The hits are ALWAYS worked out with the rights of whoever looks (doc_query runs as the signed-in person): a view an admin
shared names the same filters for everyone, every member sees only the documents they may see anyway.

Routes (people; the rest -- create, change with its version, trash / restore / undo / history, shares -- are the core's
generic routes /api/obj/docview/...):
  GET  /api/docs/views?ws=all|private|org:<id>   the views one sees for that workspace with their number of hits
  GET  /api/docs/views/<id>/hits?limit=5          the first hits (Today's block) and their number
  POST /api/docs/views/<id>/share {all: bool}     an admin shares the view with everyone of its organisation / takes it back"""
import re
from urllib.parse import parse_qsl, urlencode

from flask import jsonify, request
from werkzeug.datastructures import MultiDict

from ..core.access import Denied, acx_of
from ..core.config import app
from ..core.db import body, db
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.objects import f_text, obj_need, obj_public, obj_register, obj_role, obj_rows
from ..core.writes import obj_space_set
from ..accounts.session import me
from ..core.schema import USER_DEFAULTS
from .web import _no_agent, doc_json, doc_prefetch, doc_query, doc_visible

DV_KIND = "docview"
# the parameters of the documents search a view keeps (docs/web.py docs_list, docs/dsearch.py dsr_filters, doc_sort);
# ws is a field of its own, paging / facets are never kept
DV_KEYS = ("q", "sender", "type", "tag", "not_tag", "tag_mode", "from", "to", "added_from", "added_to", "review", "state",
           "no_tag", "no_sender", "no_type", "folder", "under", "ftype", "sort", "dir", "area", "unbooked")
DV_QUERY_MAX = 4000
DV_PAIRS_MAX = 200
DV_LIST_MAX = 100   # views listed with their counts
DV_HITS_MAX = 20
DV_WS = re.compile(r"all|private|org:[1-9][0-9]{0,11}")
DV_SHARED_WS = N_("A view shared with the organisation searches its documents")
USER_DEFAULTS.setdefault("dv_today", "")  # the views shown on Today (personal, also for a view an admin shared; accounts/settings.py)


def dv_query_clean(c, v, row=None):
    """The kept search as a query string: only the keys of DV_KEYS, each value at most 500 characters."""
    if v is None:
        return ""
    if not isinstance(v, str) or len(v) > DV_QUERY_MAX:
        raise BadInput(tr("Invalid value: {0}", "query"))
    pairs = [(k, x[:500]) for k, x in parse_qsl(v.lstrip("?"), keep_blank_values=False) if k in DV_KEYS and x.strip()]
    if len(pairs) > DV_PAIRS_MAX:
        raise BadInput(tr("Invalid value: {0}", "query"))
    return urlencode(pairs)


def dv_ws_clean(c, v, row=None):
    """The workspace the search runs in; a view shared with an organisation keeps that organisation's."""
    if v is None:
        v = "all"
    if not isinstance(v, str) or not DV_WS.fullmatch(v):
        raise BadInput(tr("Invalid value: {0}", "ws"))
    if row is not None and row["org_id"] and v != f"org:{int(row['org_id'])}":
        raise BadInput(tr(DV_SHARED_WS))
    return v


obj_register(DV_KIND, "doc_views", label=N_("Saved view"), area="other", org_access="view", org_join="admin", listed=False,
             fields={"title": f_text(120, required=True), "query": dv_query_clean, "ws": dv_ws_clean},
             open_url=lambda rid: f"docs/v/{int(rid)}")


def dv_args(row, extra=None):
    """The request arguments of the documents search the view stands for (MultiDict, as request.args)."""
    md = MultiDict(parse_qsl(row["query"] or ""))
    md["ws"] = row["ws"] or "all"
    for k, v in (extra or {}).items():
        md[k] = v
    return md


def dv_count(c, uid, row, vis):
    """The number of hits of the view for uid (its rights: doc_query runs as uid). The sort is left out (a count needs none)."""
    a = dv_args(row, {"limit": "1"})
    a.pop("sort", None)
    a.pop("dir", None)
    _, total, _ = doc_query(c, uid, a, vis)
    return total


def _in_ws(row, ws):
    """Is the view one of workspace ws ('all' = every one)? A view of 'all' shows in every workspace."""
    return ws == "all" or (row["ws"] or "all") in (ws, "all")


@app.get("/api/docs/views")
def dv_list():
    """The saved views the person sees in the workspace ?ws= (default all), each with `count` (?counts=0: without)."""
    _no_agent()
    c, uid = db(), me()
    ws = str(request.args.get("ws") or "all")
    if not DV_WS.fullmatch(ws):
        raise BadInput(tr("Invalid value: {0}", "ws"))
    rows = [(r, role) for r, role in obj_rows(c, uid, DV_KIND, limit=DV_LIST_MAX) if _in_ws(r, ws)]
    rows.sort(key=lambda x: ((x[0]["title"] or "").casefold(), x[0]["id"]))
    vis = doc_visible(c, uid) if rows and request.args.get("counts") != "0" else None
    out = []
    for r, role in rows:
        o = obj_public(c, uid, DV_KIND, r, role)
        o["shared_all"] = bool(r["org_id"])
        if vis is not None:
            o["count"] = dv_count(c, uid, r, vis)
        out.append(o)
    return jsonify(items=out)


@app.get("/api/docs/views/<int:vid>/hits")
def dv_hits(vid):
    """The first ?limit= (default 5) documents of the view, in its sort, and their number -- with the viewer's rights."""
    _no_agent()
    c, uid = db(), me()
    row, role = obj_need(c, uid, DV_KIND, vid, "view")
    try:
        n = max(1, min(DV_HITS_MAX, int(request.args.get("limit") or 5)))
    except ValueError:
        n = 5
    vis = doc_visible(c, uid)
    rows, total, _ = doc_query(c, uid, dv_args(row, {"limit": str(n), "offset": "0"}), vis)
    pre = doc_prefetch(c, [r["node_id"] for r in rows])
    docs = [doc_json(c, r, pre["nodes"][r["node_id"]], pre=pre) for r in rows if r["node_id"] in pre["nodes"]]
    return jsonify(view=obj_public(c, uid, DV_KIND, row, role), total=total, docs=docs)


@app.post("/api/docs/views/<int:vid>/share")
def dv_share(vid):
    """{all: true}: an admin of the organisation the view searches shares it with everyone of it; {all: false}: back to its
    owner alone. The core decides (obj_space_set: 'manage', only admins bring it in or take it out, logged)."""
    _no_agent()
    c, uid = db(), me()
    b = body()
    b = b if isinstance(b, dict) else {}
    if not isinstance(b.get("all"), bool):
        raise BadInput(tr("Expected {0}", "all: true | false"))
    row, _ = obj_need(c, uid, DV_KIND, vid, "manage")
    org = None
    if b["all"]:
        m = re.fullmatch(r"org:(\d+)", row["ws"] or "")
        if not m or int(m.group(1)) not in acx_of(c, uid).org_ids:
            raise Denied(409, tr("Only a view of an organisation's workspace can be shared with everyone of it"))
        org = int(m.group(1))
    row, moved = obj_space_set(c, uid, DV_KIND, vid, org)
    c.commit()
    out = obj_public(c, uid, DV_KIND, row, obj_role(c, uid, DV_KIND, vid, row=row))  # None: an admin took back another admin's view
    out["shared_all"] = bool(row["org_id"])
    return jsonify({**out, "moved": moved})
