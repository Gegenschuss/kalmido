"""2.137.0 B (#2344): organisation import -- file store, documents, knowledge pages, tables and video sign-offs (admin/orgimport.py OiT).

File store: the tree (parents set late), every version written sealed again for the target (quota, virus scan, undo), links
to task / project files only when their file came along, shares only with people ticked in the preview (agents never), the
history with the people ticked (else without a name). Documents: senders, types and tags found by name in the target's
workspace or made there, texts / amounts / rules sealed with the target's workspace key (docs/store.py doc_seal); the word
index, the models and the previews are made again (FINISH), suggestions start empty, the project / category of receipts
comes along (agents' open suggestions do not). Knowledge pages: the text sealed for
the target (wiki/wkhist.py); pages of a space with the lock (browser ciphertexts) stay out -- the space key is not in the
export, nobody could open them -- and nothing goes into a target space with the lock; the page history comes along, the
public read links of pages do not (their token belongs to the old server, like the upload links of folders). Tables: formulas, file and person cells
and the chart are rewritten to the new ids (FINISH); a reference that did not come along points at nothing (shows "ref").
Video sign-offs: links, versions and comments (the approval links themselves are not in the export).
2.353.0 C (#2829): the areas' trees (knowledge folders, the tables' folders) come with the store: an area's root goes into the
target's own root of that area (store/area_roots.json; a knowledge folder of the same name below it is used), else it is made
and marked; page / table reference nodes point at the new rows. An archive without the marks rebuilds the knowledge tree from
the pages' paths as before; a target whose knowledge pages have the lock gets no knowledge tree.
Into the private space (#1941) every part goes into the person's own space (org_id NULL, owner = the person): the app has a
private file store, private documents, private pages, tables and sign-offs."""
import json
import os
import re
import secrets

from ..core.i18n import N_
from .orgimport import OiT, _txt  # 2.362.0 (#3131): + _txt
from .oilock import oil_key, oil_lock  # #4300
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions
from ..core.config import ATT_DIR  # 2.149.0 G (#2517): pulled up from functions
from ..files.fsroots import fs_area_root, fs_area_ws  # 2.353.0 C (#2829)
from ..core.db import iso, now_utc  # 2.362.0 (#3131)
from ..files.store import FS_DIR, fs_read  # 2.369.5 (#2517): pulled up from functions
from .orgexport import _safe_part  # 2.369.5 (#2517): pulled up from functions
from ..videos.review import vdr_parse  # 2.369.5 (#2517): pulled up from functions
from .acctimport import umz_cols  # 2.369.5 (#2517): pulled up from functions
from ..wiki.wkhist import wkh_seal, WKH_KIND, WKH_VCTX  # 2.369.5 (#2517): pulled up from functions; 2.958.0 (#5281): + WKH_KIND
from ..wiki.pages import wiki_set_links  # 2.369.5 (#2517): pulled up from functions
from ..wiki.wksearch import wks_index  # 2.369.5 (#2517): pulled up from functions
from ..tasks.attachtext import file_kind  # 2.369.5 (#2517): pulled up from functions
from ..sheets.shshare import shs_core_of, shs_put  # 2.647.0 (#5047); 2.937.0 (#5244)
from ..core.access import Denied  # 2.937.0 (#5244)
from ..core.pg import system_ctx  # 2.937.0 (#5244)
from ..files.fsref import fs_ref_node  # 2.937.0 (#5244)
from ..docs.store import doc_seal as _doc_seal  # 2.635.0 (#4807 d)

_LOCKED = "e2e1:"
_FILE_CELL = re.compile(r"file:(\d{1,15})")
_SH_REF = re.compile(r"\{(c|col|p|l|k|t|x):(\d{1,18})\}")
_SH_KIND = {"c": "sheet_cells", "x": "sheet_cells", "col": "sheet_columns", "p": "lists", "l": "lists", "k": "clients", "t": "tasks"}
_WK_NODE = re.compile(r"/api/files/nodes/(\d{1,15})/content\b")
_WK_FILE = re.compile(r"/api/wiki/files/(\d{1,15})\b")
_WK_REF = re.compile(r"(\[\[\s*(datei|tabelle)\s*:\s*)(\d{1,15})(\s*[\]|])", re.I)
_WK_TASK = re.compile(r"(?<![\w&/#])#(\d{1,12})\b")
_CF_KEY = re.compile(r"cf\d{1,18}")


def _st(run):
    """Per-run scratch of this area (names of the archive's nodes, the documents and pages made)."""
    st = getattr(run, "oi_store", None)
    if st is None:
        st = run.oi_store = {"docs": [], "pages": [], "names": None}
    return st


def _owner(ctx):
    """owner_id of a page / table / sign-off / file: the person in their private space, none in an organisation."""
    return None if ctx.space else ctx.uid


def _ws(ctx):
    from ..docs.store import doc_ws
    return doc_ws(ctx.space, ctx.uid)


def _same_bytes(src, d, size):
    return src.get("sha256") if isinstance(src.get("sha256"), str) and size == src.get("size") else ""


def _not_agent(c, uid):
    r = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r) and (r[0] or "user") != "agent"


# ---- file store --------------------------------------------------------------------------------------------------------
# 2.353.0 C (#2829): reference nodes of the areas' trees that come along (their ref_id is set in _finish_store, once the
# pages / tables are in; a node whose page / table did not come along goes again)
_REF_KINDS = {"wiki": "wiki_pages", "sheet": "sheets"}
# 2.566.0 (#4712): the core's calendars / address books carry their shares (fs_shares) on their reference node, which lies at
# the top of the workspace's tree or in any folder (no area): it comes along with its shares and history and points at the
# imported calendar / book in _finish_refs (one that did not come along goes again, like a page's node)
_CORE_REF_KINDS = {"evcal": "ev_cals", "address_book": "books"}
# 2.581.0 (#4811): reference nodes of the shared core (#4709) outside the areas' trees. Calendars and address books (#4712) are
# in when the store comes (base import): their node points at the new row at once (the shares of the archive land on it;
# 2.924.0, #5069: an older archive's calendars/members.json -> admin/oi_team.py _core_member). The team chat's channels (#4719) come later (oi_team): their node
# is set in _finish_refs like a page's. A project's node (#4739) is made by the base import itself (lists/lffolder.py lf_place):
# the archive's node maps onto it, so its own member shares and its history follow (its "create" line is the target's).
_CORE_NOW = {"evcal": "ev_cals", "address_book": "books"}
_CORE_LATE = {"tchat_room": "tchat_rooms"}
_LIST_REF = "list"


def _areas(run, ctx):
    """2.353.0 C (#2829): {archive node id: area} of the nodes in an area's tree (store/area_roots.json; an older archive
    has none), {archive root id: area}."""
    st = _st(run)
    if "area_of" not in st:
        oi = ctx.data.get("oi") or {}
        roots = {_oidi(r.get("node_id")): str(r.get("area") or "") for r in oi.get("store/area_roots.json") or []
                 if _oidi(r.get("node_id")) and re.fullmatch(r"[a-z][a-z0-9_]{0,19}", str(r.get("area") or ""))}
        par = {_oidi(r.get("id")): _oidi(r.get("parent_id")) for r in oi.get("store/nodes.json") or []}
        out = {}
        for nid in par:
            chain, x = [], nid
            while x and x not in out and x not in roots and x not in chain and len(chain) < 200:
                chain.append(x)
                x = par.get(x)
            a = out.get(x) or roots.get(x)
            for y in chain:
                out[y] = a
        out.update(roots)
        st.update(area_of=out, roots=roots, merged=set(), new_roots={}, refs=[])
    return st


def _node(c, run, src, d, ctx):
    if d.get("kind") not in ("folder", "file", "link", "page", "ref"):
        return None
    st = _areas(run, ctx)
    sid = _oidi(src.get("id"))
    area = st["area_of"].get(sid)
    if area == "wiki" and _wiki_locked(c, ctx):
        if d.get("kind") == "file" and not st.get("lockwarn"):  # 2.353.0 (#2829, review): files of the tree do not drop silently
            st["lockwarn"] = True
            run.warning(N_("The target's knowledge has the lock: files of the knowledge tree were left out."))
        return False  # the target's knowledge pages have the lock: their pages stay out (_page), so does the tree
    if sid in st["roots"]:  # an area's root: the target's own root of that area when it has one (never a second root)
        have = fs_area_root(c, ctx.uid, ctx.space, area, "", create=False)
        if have:
            run.put("fs_nodes", sid, have)
            st["merged"].add(have)
            return False
        st["new_roots"][sid] = area
        d["parent_id"] = None
        if area == "wiki" and ctx.space:
            d["org_access"] = "edit"  # 2.353.0 (#2829, review): like wkf_root, not the archive's value
    elif area == "wiki" and d["kind"] == "folder" and run.m("fs_nodes", src.get("parent_id")) in st["merged"]:
        have = c.execute("SELECT id FROM fs_nodes WHERE parent_id=? AND kind='folder' AND name=? AND deleted_at IS NULL",
                         (run.m("fs_nodes", src.get("parent_id")), d.get("name"))).fetchone()
        if have:  # names are exact (wiki/wkfolder.py, the index's path check): the target's folder of that name takes it
            run.put("fs_nodes", sid, have[0])
            st["merged"].add(have[0])
            return False
    if d["kind"] == "ref" and src.get("ref_kind") in (*_CORE_NOW, *_CORE_LATE, _LIST_REF):
        return _core_node(c, run, src, d, ctx, st, sid)
    if d["kind"] == "ref":
        # 2.937.0 (#5244): + a table's node at the top of the tree (shshare.py shs_node: a table in no folder; it carries the shares)
        top_sheet = src.get("ref_kind") == "sheet" and not src.get("parent_id")
        if not (src.get("ref_kind") in _REF_KINDS and (area or top_sheet) or src.get("ref_kind") in _CORE_REF_KINDS):
            return None
        d["ref_id"] = None
        st["refs"].append((sid, src["ref_kind"], src.get("ref_id")))
    if not ctx.space:
        d["owner_id"], d["org_access"] = ctx.uid, ""
    if d["kind"] == "link":  # a task / project file shown in the store: only when that file came along
        kind = {"att": "attachments", "list_file": "list_files"}.get(src.get("ref_kind"))
        ref = run.m(kind, src.get("ref_id")) if kind else None
        if not ref:
            return None
        d["ref_id"] = ref
    elif d["kind"] != "ref":
        d["ref_kind"] = None
    return d


def _core_node(c, run, src, d, ctx, st, sid):
    """2.581.0 (#4811): the reference node of a core object (_CORE_NOW / _CORE_LATE / a project). Only an object THIS import
    made in the target counts (run.m): a node whose object did not come along goes (False: silently, the object warned)."""
    kind = src["ref_kind"]
    if kind == _LIST_REF:  # the base import placed the project's node in the target's tree: the archive's node is that one
        lid = run.m("lists", src.get("ref_id"))
        n = c.execute("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=? AND org_id IS NOT DISTINCT FROM ?",
                      (_LIST_REF, lid, ctx.space or None)).fetchone() if lid else None
        if n:
            run.put("fs_nodes", sid, n[0])
            st.setdefault("own_create", set()).add(sid)
        return False
    if kind in _CORE_NOW:
        new = run.m(_CORE_NOW[kind], src.get("ref_id"))
        if not new:
            return False
        have = c.execute("SELECT id FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND ref_id=?", (kind, new)).fetchone()
        if have:  # never a second node of one object
            run.put("fs_nodes", sid, have[0])
            st.setdefault("own_create", set()).add(sid)
            return False
        d["ref_id"] = new
    else:
        d["ref_id"] = None  # the channel comes with oi_team: _finish_refs sets it (or the node goes)
        st["refs"].append((sid, kind, src.get("ref_id")))
    if not ctx.space:
        d["owner_id"], d["org_access"] = ctx.uid, ""
    return d


def _share_id(run, v):
    n = run.m("fs_shares", v)
    return str(n) if n else ""


def _history(c, run, src, d, ctx):
    """2.581.0 (#4811): a node's history line. A node mapped onto one the target made itself keeps the target's "create" line;
    ids inside the detail point at the target (a person not ticked, a group or an agent: the line goes; a share id that did
    not come along: no id)."""
    sid = _oidi(src.get("node_id"))
    act, det = str(src.get("action") or ""), str(src.get("detail") or "")
    if act == "create" and sid in (_st(run).get("own_create") or ()):
        return False
    m = re.fullmatch(r"(user|group|agent):(-?\d+):(.*)", det) if act == "share" else None
    if m:
        new = ctx.who(int(m.group(2))) if m.group(1) == "user" else None
        if not new or not _not_agent(c, new):
            return False
        d["detail"] = f"user:{int(new)}:{m.group(3)}"
        if sid in (_st(run).get("own_create") or ()) and _own_share_line(run, ctx, src):
            return False
    elif act == "share" and det.startswith("merged:"):
        d["detail"] = "merged:" + _share_id(run, det[7:])
    elif act == "unshare" and det:
        d["detail"] = _share_id(run, det)
    elif act == "share_change" and ":" in det:
        d["detail"] = _share_id(run, det.split(":", 1)[0]) + ":" + det.split(":", 1)[1]
    elif act == "move":  # 2.636.0 (#4854): the parent folder's id -> the target's folder (one that did not come along: none)
        if det.isdigit():  # a word ("lock", files/fslock.py) is no id and stays as it is
            new = run.m("fs_nodes", det)
            d["detail"] = str(new) if new else ""
    elif act == "moved_space":  # 2.636.0 (#4854): "org:<source org>->..." names the source server's workspaces: no ids
        d["detail"] = ""
    return d


def _own_share_line(run, ctx, src):
    """2.581.0 (#4811): a project's node is the target's own (lf_place); its member shares are made again by the sharing with
    the ticked people after the areas (acctimport.py umz_share -> lists.py _folder_member_add -> lmc_share), which writes their
    share lines itself. The archive's last share line of each person on a project's node is that one: it goes (each share
    once in the history, like the node's "create" line); earlier lines of a share made, taken and made again stay."""
    st = _st(run)
    if "last_share" not in st:
        oi = ctx.data.get("oi") or {}
        lists = {_oidi(r.get("id")) for r in oi.get("store/nodes.json") or [] if r.get("kind") == "ref" and r.get("ref_kind") == _LIST_REF}
        now = {(_oidi(r.get("node_id")), _oidi(r.get("user_id"))) for r in oi.get("store/shares.json") or [] if r.get("user_id")}
        last = {}
        for r in oi.get("store/history.json") or []:
            m = re.fullmatch(r"user:(-?\d+):.*", str(r.get("detail") or "")) if r.get("action") == "share" else None
            nid, rid = _oidi(r.get("node_id")), _oidi(r.get("id"))
            k = (nid, int(m.group(1))) if m else None
            if k and nid in lists and rid and k in now:  # a share the archive still has (a person taken off keeps the line)
                last[k] = max(last.get(k, 0), rid)
        st["last_share"] = set(last.values())
    return _oidi(src.get("id")) in st["last_share"]


def _area_root(c, run, src, d, ctx):
    """2.353.0 C (#2829): the mark of an area's root made by this import (a root put into the target's own one: nothing)."""
    st = _areas(run, ctx)
    sid = _oidi(src.get("node_id"))
    nid = run.m("fs_nodes", sid)
    if sid not in st["new_roots"] or not nid:
        return False
    ws = fs_area_ws(ctx.space, ctx.uid)
    d.update(ws=ws, area=st["new_roots"][sid], org_id=ctx.space or None, owner_id=None if ctx.space else ctx.uid, node_id=nid)
    if c.execute("SELECT 1 FROM fs_area_roots WHERE ws=? AND area=?", (ws, d["area"])).fetchone():  # a mark whose folder is gone
        c.execute("UPDATE fs_area_roots SET node_id=?, updated_at=? WHERE ws=? AND area=?", (nid, d["updated_at"], ws, d["area"]))
        return False
    return d


def _version(c, run, src, d, ctx):
    st = _st(run)
    if st["names"] is None:
        st["names"] = {r.get("id"): r.get("name") for r in (ctx.data.get("oi") or {}).get("store/nodes.json") or []}
    name = st["names"].get(src.get("node_id"))
    cipher = isinstance(name, str) and name.startswith("e2e1:")  # #4300: a file of a locked folder: its cipher name names no stored file
    try:
        path = f"files/store/{int(src['node_id'])}-v{int(src['no'])}-{_safe_part(name)}"
    except (TypeError, ValueError, KeyError):
        return None
    got = ctx.file(path, os.path.join(FS_DIR, str(d["node_id"])), "encrypted.kenc" if cipher else name or "file", mime=str(src.get("mime") or ""))
    if not got:
        return None
    d["path"], d["size"] = got
    d["sha256"] = _same_bytes(src, d, got[1])
    return d


def _lock(c, run, src, d, ctx):
    """#4300: admin/oilock.py. A folder that went into a root of the target (a crafted file: areas are never locked) gets no lock."""
    return False if _lock_area(run, src, d, ctx) else oil_lock(run, src, d, ctx.uid)


def _lock_area(run, src, d, ctx):
    st = _areas(run, ctx)
    return d["node_id"] in st["merged"] or st["area_of"].get(_oidi(src.get("node_id")))


def _lock_key(c, run, src, d, ctx):
    return False if _lock_area(run, src, d, ctx) else oil_key(c, run, src, d, ctx.uid)  # #4300


def _share(c, run, src, d, ctx):
    if not (d.get("user_id") and _not_agent(c, d["user_id"])):
        return None  # people only (groups and agents stay out)
    # 2.937.0 (#5244): a share of a table's node is the table's share (no card any more): noted for _finish_sheet_shares, which
    # puts it on the imported table's node when the node of the archive did not stay (a table already placed, _finish_refs)
    sn = _sheet_nodes(run, ctx).get(_oidi(src.get("node_id")))
    if sn:
        _sheet_share_note(run, sn, None, d["user_id"], {"view": "read", "edit": "write"}.get(src.get("role")), src.get("expires_at"))
    return d


def _sheet_nodes(run, ctx):
    """2.937.0 (#5244): {archive node id: archive table id} of the tables' reference nodes in store/nodes.json."""
    st = _st(run)
    if "sheet_nodes" not in st:
        oi = ctx.data.get("oi") or {}
        st["sheet_nodes"] = {_oidi(r.get("id")): _oidi(r.get("ref_id")) for r in oi.get("store/nodes.json") or []
                             if r.get("kind") == "ref" and r.get("ref_kind") == "sheet" and _oidi(r.get("ref_id"))}
    return st["sheet_nodes"]


def _sheet_share_note(run, src_sid, sid, who, role, expires_at=None):
    if not hasattr(run, "oi_sheet_shares"):
        run.oi_sheet_shares = []
    run.oi_sheet_shares.append((src_sid, sid, who, role, expires_at))


# ---- documents ---------------------------------------------------------------------------------------------------------
def _label(kind):
    def prep(c, run, src, d, ctx):
        from ..docs import store as S
        ws = _ws(ctx)
        name = re.sub(r"\s+", " ", str(src.get("name") or "")).strip()[:S.NAME_MAX]
        if not name:
            return None
        have = S.label_id(c, ws, kind, name, create=False)
        if have:  # the target knows it already: the documents use that one
            run.put(S.LABEL_KINDS[kind], src.get("id"), have)
            return None
        d["ws"], d["name"] = ws, S.doc_seal(c, ws, "doc_senders.name", name) if kind == "sender" else name
        return d
    return prep


def _rule(c, run, src, d, ctx):
    from ..docs import store as S
    ws = _ws(ctx)
    raw = src.get("data")
    try:
        r = json.loads(raw) if isinstance(raw, str) else raw
        r = S.RU.clean_rule(r) if isinstance(r, dict) else None
    except (ValueError, S.RU.RuleError):
        r = None
    if not r:
        return None
    to = (r.get("task") or {}).get("to")
    if to:  # 2.581.0 (#4803 review): the person of a flow's task is an id of the source server -> the person chosen here, else the author
        new = ctx.who(int(to))
        if new and _not_agent(c, new):
            r["task"]["to"] = int(new)
        else:
            r["task"].pop("to", None)
    d["ws"], d["data"] = ws, S._jseal(c, ws, "doc_rules.data", r)
    return d


def _cfg(c, run, src, d, ctx):
    ws = _ws(ctx)
    if c.execute("SELECT 1 FROM doc_cfg WHERE ws=?", (ws,)).fetchone():
        return None  # the target's own settings stay
    try:
        data = json.loads(src.get("data") or "{}")
    except (ValueError, TypeError):
        data = {}
    data = data if isinstance(data, dict) else {}
    root = run.m("fs_nodes", data.pop("root_id", None))
    if root:
        data["root_id"] = root
    d["ws"], d["data"] = ws, json.dumps(data)
    return d


def _meta(c, run, src, d, ctx):
    from ..docs import store as S
    ws = _ws(ctx)
    d["ws"] = ws
    for k in ("text", "amount", "extracted"):
        if isinstance(d.get(k), str) and d[k]:
            d[k] = S.doc_seal(c, ws, f"doc_meta.{k}", d[k])
    d.update({"suggest": "", "trained": "", "review": 0, "thumb": None})  # suggestions name the source's labels; made again
    if "thumb_l" in d:
        d["thumb_l"] = None  # 2.583.0 (#4812): the sharp preview is made again too (thumb_store below)
    if d.get("state") == "run":
        d["state"] = "wait"
    if d.get("asn") and S.asn_taken(c, ws, d["asn"]):
        d["asn"] = None
    _st(run)["docs"].append((d["node_id"], ws))
    return d


def _df_opts(raw):
    try:
        o = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        o = None
    raw = o.get("options") if isinstance(o, dict) else None
    out, seen = [], set()
    for x in (raw if isinstance(raw, list) else []):  # review: only well-formed options (ids / names like df_clean_def), at most 50
        oid, nm = (x.get("id"), x.get("name")) if isinstance(x, dict) else (None, None)
        if not isinstance(oid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,16}", oid) or oid in seen or not isinstance(nm, str):
            continue
        nm = re.sub(r"\s+", " ", nm).strip()[:60]  # DF_NAME_MAX
        if nm:
            seen.add(oid)
            out.append({"id": oid, "name": nm})
    return out[:50]


def _df_skip(run):
    """A field / value not taken over. 2.369.0 (#2734): one warning of the run, the report counts it ("... (12×)")."""
    run.warning(N_("Field values not imported"))
    return False


def _field(c, run, src, d, ctx):
    """2.184.0 A (#2579): a custom field of the documents: the target's field of the same name and type is used (a select field
    gains the options it lacks, by name), else it is made; the option ids of the archive -> the target's (_st()["opts"])."""
    from ..docs.fields import DF_MAX, DF_NAME_MAX, DF_TYPES
    ws = _ws(ctx)
    name = re.sub(r"\s+", " ", str(src.get("name") or "")).strip()[:DF_NAME_MAX]
    if not name or src.get("type") not in DF_TYPES:
        return _df_skip(run)
    opts = _df_opts(src.get("options")) if src.get("type") == "select" else []
    have = c.execute("SELECT id, type, options FROM doc_fields WHERE ws=? AND lower(name)=lower(?)", (ws, name)).fetchone()
    if have and have["type"] == src["type"]:
        mine = _df_opts(have["options"])
        known = len(mine)
        by_name = {o["name"].lower(): o["id"] for o in mine}
        omap = {}
        for o in opts:
            if o["name"].lower() not in by_name and len(mine) < 50:
                mine.append({"id": secrets.token_hex(4), "name": o["name"]})
                by_name[o["name"].lower()] = mine[-1]["id"]
            if o["name"].lower() in by_name:
                omap[o["id"]] = by_name[o["name"].lower()]
        if src["type"] == "select":
            c.execute("UPDATE doc_fields SET options=? WHERE id=?", (json.dumps({"options": mine}, ensure_ascii=False), have["id"]))
            if mine[known:]:  # 2.369.0 (#2734): four items, oi_undo takes them out again (an option made since stays)
                run.created.setdefault("oi", []).append(["doc_fields", have["id"], ws, [o["id"] for o in mine[known:]]])
        run.put("doc_fields", src.get("id"), have["id"])
        _st(run).setdefault("opts", {})[have["id"]] = omap
        return False
    if have:  # another type has the name in the target
        name = f"{name[:DF_NAME_MAX - 5]} (2)"
    if c.execute("SELECT COUNT(*) FROM doc_fields WHERE ws=?", (ws,)).fetchone()[0] >= DF_MAX:
        return _df_skip(run)  # the target's workspace is full
    d["ws"], d["name"] = ws, name
    d["options"] = json.dumps({"options": opts} if src["type"] == "select" else {}, ensure_ascii=False)
    return d


def _df_links(run, v):
    """2.657.0 (#5018): a link field's value ("12,34") with each document id of the archive put onto the document this run
    made from it (the documents come before the values); a Paperless id ("pl:7", the source's Paperless) or an id that did not
    come along drops out and counts as a warning of the report. Never a raw id of the source. "" = nothing left."""
    from ..docs.fields import DF_LINKS_MAX
    out = []
    for x in str(v).split(","):
        x = x.strip()
        new = run.m("fs_nodes", x) if re.fullmatch(r"[1-9]\d{0,17}", x) else None
        if not new:
            if x:
                run.warning(N_("Links to documents that did not come along were left out"))
            continue
        if str(new) not in out and len(out) < DF_LINKS_MAX:
            out.append(str(new))
    return ",".join(out)


def _field_value(c, run, src, d, ctx):
    """2.184.0 A (#2579): the value of a custom field, sealed with the target's workspace key (a select value -> its option)."""
    from ..docs import store as S
    f = c.execute("SELECT ws, type, options FROM doc_fields WHERE id=?", (d["field_id"],)).fetchone()
    v = src.get("value")
    if not f or not isinstance(v, str) or v.startswith("kenc1:"):
        return _df_skip(run)  # a value that did not open in the export
    if f["type"] == "documentlink":  # 2.657.0 (#5018): the source's document ids -> the ones this run made (run.m only)
        v = _df_links(run, v)
        if not v:
            return _df_skip(run)
    if f["type"] == "select":
        omap = _st(run).get("opts", {}).get(d["field_id"])
        v = omap.get(v) if omap is not None else v
        if v not in {o["id"] for o in _df_opts(f["options"])}:
            return _df_skip(run)
    d["ws"], d["value"] = f["ws"], S.doc_seal(c, f["ws"], "doc_field_values.value", v)
    return d


def _doc_note(c, run, src, d, ctx):
    """2.635.0 (#4807 d): a note on a document, sealed with the target document's workspace key (a text that did not open in
    the export is left out); its author maps like every person column (else NULL: the note keeps its text and time).
    2.981.0 (#5273): a row of obj_comments (kind doc_note, ref_id = the document): the name it came with -> ext_name, its
    source -> extra (the archive keeps the columns of doc_notes)."""
    v = src.get("text")
    m = c.execute("SELECT ws FROM doc_meta WHERE node_id=?", (d["ref_id"],)).fetchone()
    if not m or not isinstance(v, str) or not v.strip() or v.startswith("kenc1:"):
        return False
    d["body"] = _doc_seal(c, m[0], "doc_notes.text", v)
    d["ext_name"] = str(src.get("author") or "")[:200] or None
    d["extra"] = json.dumps({"source": src["source"]} if isinstance(src.get("source"), str) and src["source"] else {})
    return d


def _video_comment(c, run, src, d, ctx):
    """2.981.0 (#5273): a comment of the archive's videos/comments.json (the columns of video_comments) becomes a row of
    obj_comments (kind video): its version (mapped) and place -> anchor, done -> state, author_id -> user_id (the importing
    person or nobody, like every author column; nobody keeps the name: ext_name)."""
    num = (int, float)
    an = {"version_id": run.m("video_versions", src.get("version_id")) if src.get("version_id") is not None else None}
    for k, col in (("t", "at_sec"), ("page", "page"), ("x", "pos_x"), ("y", "pos_y")):
        v = src.get(col)
        an[k] = v if isinstance(v, num) and not isinstance(v, bool) else None
    an = {k: v for k, v in an.items() if v is not None}
    d["anchor"] = json.dumps(an) if an else None
    d["state"] = "done" if src.get("done") in (1, True) else None
    au = src.get("author_id")
    new = ctx.who(au) if au is not None else None
    d["user_id"] = new if new is not None and new == ctx.uid else None
    if d["user_id"] is None and au is not None and not d.get("ext_name"):
        d["ext_name"] = next((str(p.get("name") or "")[:100] for p in ctx.data.get("people") or []
                              if isinstance(p, dict) and str(p.get("user_id")) == str(au)), None) or None
    return d


# ---- knowledge pages -----------------------------------------------------------------------------------------------------
def _wiki_locked(c, ctx):
    return c.execute("SELECT 1 FROM wiki_spaces WHERE COALESCE(org_id,0)=? AND COALESCE(owner_id,0)=? AND e2e IS NOT NULL",
                     (ctx.space or 0, 0 if ctx.space else ctx.uid)).fetchone() is not None


def _video_version(c, run, src, d, ctx):
    """2.137.0 review M1: the link is checked like a pasted one (videos/review.py vdr_parse); provider and embed id come from it."""
    try:
        v = vdr_parse(src.get("url"))
    except BadInput:
        run.warning(N_("A row could not be imported: {0}"), (N_("Video sign-offs"),))
        return False
    for k in ("url", "provider", "embed_id"):
        if k in d or k in umz_cols(c, "video_versions")[0]:
            d[k] = v[k]
    return d


_W_LOCKED = N_("Knowledge pages encrypted in the browser were not imported: export them as Markdown from the unlocked workspace and import that file into the knowledge pages.")


def _page(c, run, src, d, ctx):
    st = _st(run)
    if str(src.get("path") or "").startswith(_LOCKED) or str(src.get("body") or "").startswith(_LOCKED):
        if not st.get("w_src"):  # named once; the row itself counts under "A row could not be taken over"
            st["w_src"] = run.warning(_W_LOCKED) or 1
        return None
    if _wiki_locked(c, ctx):
        if not st.get("w_dst"):
            st["w_dst"] = run.warning(N_("The knowledge pages of this workspace are encrypted in the browser")) or 1
        return None
    d["owner_id"] = _owner(ctx)
    d["body"] = wkh_seal(c, ctx.space, d["owner_id"], d.get("body") or "")  # ids inside are put right in _finish
    return d


def _wiki_version(c, run, src, d, ctx):
    """2.958.0 (#5281): a version of the archive's wiki/versions.json (page_id, path, body ... as before) becomes a row of the
    core's versions (obj_versions kind "wiki": ref_id = the page, title = its name then, the next number of the page)."""
    if str(src.get("path") or "").startswith(_LOCKED) or str(src.get("body") or "").startswith(_LOCKED):
        return None
    pg = c.execute("SELECT org_id, owner_id FROM wiki_pages WHERE id=?", (d["ref_id"],)).fetchone()
    if not pg:
        return None
    d["owner_id"] = pg["owner_id"]
    d["title"] = str(src.get("path") or "")
    d["body"] = wkh_seal(c, pg["org_id"], pg["owner_id"], d.get("body") or "", ctx=WKH_VCTX)
    d["no"] = c.execute("SELECT COALESCE(MAX(no), 0) + 1 FROM obj_versions WHERE kind=? AND ref_id=?", (WKH_KIND, d["ref_id"])).fetchone()[0]
    d["held_at"] = None
    return d


def _receipt(c, run, src, d, ctx):
    d["ws"] = _ws(ctx)
    if (src.get("billed_doc_id") or src.get("billed_at")) and not d.get("billed_doc_id"):  # 2.278.0 B (#3094): never silently open
        # 2.362.0 (#3131): it stays billed ("billed, invoice missing": billed_at without a document, office/outlays.py au_billed),
        # never open again (it would be billed twice); unbill frees it on purpose
        d["billed_at"] = _txt(src.get("billed_at"), 40) or iso(now_utc())
        d["billed_doc_id"], d["billed_item_id"] = None, None
        run.warning(N_("Billed receipts whose invoice did not come along stay billed (invoice missing): free them under Bookkeeping only if they were never billed"))
    return d


def _wiki_file(c, run, src, d, ctx):
    pg = c.execute("SELECT owner_id FROM wiki_pages WHERE id=?", (d["page_id"],)).fetchone()
    name = str(src.get("name") or "file")
    got = ctx.file(f"files/wiki/{_oidi(src.get('id'))}-{_safe_part(src.get('name'))}", os.path.join("wiki", str(d["page_id"])), name,
                   mime=str(src.get("mime") or ""))
    if not got or not pg:
        return None
    d["owner_id"], (d["path"], d["size"]) = pg[0], got
    d["sha256"] = _same_bytes(src, d, got[1])
    return d


def _oidi(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


# ---- tables ------------------------------------------------------------------------------------------------------------
def _sheet(c, run, src, d, ctx):
    d["owner_id"], d["agent_batch"] = _owner(ctx), None
    return d


def _cell(c, run, src, d, ctx):
    d["agent_batch"] = None
    return d


def _sheet_file(c, run, src, d, ctx):
    name = str(src.get("name") or "file")
    got = ctx.file(f"files/sheets/{_oidi(src.get('id'))}-{_safe_part(src.get('name'))}", os.path.join("sheets", str(d["sheet_id"])),
                   name, mime=str(src.get("mime") or ""))
    if not got:
        return None
    d["owner_id"], (d["path"], d["size"]) = _owner(ctx), got
    return d


def _sheet_link(c, run, src, d, ctx):
    kind = {"task": "tasks", "row": "tasks", "offer": "office_docs"}.get(src.get("kind"))
    target = run.m(kind, src.get("target_id")) if kind else None
    if not target:
        return None  # its task / quotation did not come along
    d["target_id"] = target
    return d


def _sheet_share(c, run, src, d, ctx):
    """2.937.0 (#5244): a row of sheets/shares.json (a person's / agent's share of an archive before stage 7c; addresses were
    never exported, 2.360.2 M #2561) is no row of its own any more: _finish_sheet_shares makes it the core share of the
    imported table's node unless the archive's file store brought that node (its store/shares.json is the truth then). Always
    False."""
    if d.get("user_id") is not None and d.get("sheet_id") and _not_agent(c, d["user_id"]):
        _sheet_share_note(run, _oidi(src.get("sheet_id")), d["sheet_id"], d["user_id"], d.get("role"))
    return False


# ---- video sign-offs -------------------------------------------------------------------------------------------------------
def _video(c, run, src, d, ctx):
    d["owner_id"] = _owner(ctx)
    return d


# ---- after every area: ids inside texts, indexes, models, previews -----------------------------------------------------------
def _raw(run, who, raw, kind):
    """A cell input with the ids of the target (a reference that did not come along -> 0: the cell shows "ref")."""
    if not isinstance(raw, str) or not raw:
        return raw
    if kind == "person" and raw.strip().isdigit():  # an account: the person ticked in the preview, else empty
        o = who(raw.strip())
        return str(o) if o else ""
    m = _FILE_CELL.fullmatch(raw.strip())
    if m:
        f = run.m("sheet_files", m.group(1))
        return f"file:{f}" if f else ""
    return _SH_REF.sub(lambda x: "{%s:%d}" % (x.group(1), run.m(_SH_KIND[x.group(1)], x.group(2)) or 0), raw)


def _finish_sheets(c, run, oi, who):
    kinds = {r.get("id"): r.get("kind") for r in oi.get("sheets/columns.json") or []}
    for r in oi.get("sheets/cells.json") or []:
        nid = run.m("sheet_cells", r.get("id"))
        if nid:
            new = _raw(run, who, r.get("raw"), kinds.get(r.get("col_id")))
            if new != r.get("raw"):
                c.execute("UPDATE sheet_cells SET raw=? WHERE id=?", (new or "", nid))
    for r in oi.get("sheets/history.json") or []:
        nid = run.m("sheet_hist", r.get("id"))
        if nid:
            k = kinds.get(r.get("col_id"))
            c.execute("UPDATE sheet_hist SET old_raw=?, new_raw=? WHERE id=?",
                      (_raw(run, who, r.get("old_raw"), k), _raw(run, who, r.get("new_raw"), k), nid))
    for r in oi.get("sheets/sheets.json") or []:
        nid = run.m("sheets", r.get("id"))
        if not nid or not r.get("chart"):
            continue
        try:
            ch = json.loads(r["chart"])
        except (ValueError, TypeError):
            ch = None
        if isinstance(ch, dict):  # {type, x: column, y: [columns]}: a column that did not come along drops out
            ch["x"] = run.m("sheet_columns", ch.get("x")) if ch.get("x") is not None else None
            ys = ch.get("y") if isinstance(ch.get("y"), list) else []
            ch["y"] = [y for y in (run.m("sheet_columns", v) for v in ys if not isinstance(v, (list, dict))) if y]
        c.execute("UPDATE sheets SET chart=? WHERE id=?", (json.dumps(ch) if isinstance(ch, dict) and ch["y"] else "", nid))


def _finish_sheet_shares(c, run, oi, uid):
    """2.647.0 (#5047): one right per share, never a card beside a core share. 2.937.0 (#5244): the shares of an imported table
    are the core shares of its node -- each share of the archive's table node (store/shares.json, _share) and each row of an
    older archive's sheets/shares.json is a share of the imported table's node (shshare.py shs_put) unless the account has one
    there already (the archive's node stayed with its shares: role and end date as they came)."""
    for src_sid, sid, who, role, expires_at in getattr(run, "oi_sheet_shares", None) or []:
        sid = sid or run.m("sheets", src_sid)
        r = c.execute("SELECT * FROM sheets WHERE id=?", (sid,)).fetchone() if sid else None
        if r is None or r["book_id"]:
            continue
        with system_ctx(c):  # the node of the table this import just made (in the target's tree)
            made = fs_ref_node(c, "sheet", sid) is None
            try:
                with c.savepoint():
                    if shs_core_of(c, sid, who) is None:
                        shs_put(c, uid, r, who, role if role in ("read", "write") else "read", expires_at or None)
            except Denied:  # the node is full: the share stays out
                continue
            n = fs_ref_node(c, "sheet", sid)
            if made and n is not None:  # made here: recorded for the undo (like a calendar's node, oi_team._core_member)
                run.created["oi"].append(["fs_nodes", n["id"], n["org_id"]])


def _body(run, text):
    text = _WK_NODE.sub(lambda m: f"/api/files/nodes/{run.m('fs_nodes', m.group(1)) or 0}/content", text)
    text = _WK_FILE.sub(lambda m: f"/api/wiki/files/{run.m('wiki_files', m.group(1)) or 0}", text)
    text = _WK_REF.sub(lambda m: f"{m.group(1)}{run.m('fs_nodes' if m.group(2).lower() == 'datei' else 'sheets', m.group(3)) or 0}{m.group(4)}",
                       text)
    return _WK_TASK.sub(lambda m: f"#{run.m('tasks', m.group(1))}" if run.m("tasks", m.group(1)) else m.group(0), text)


def _finish_wiki(c, run, oi):
    for r in oi.get("wiki/pages.json") or []:
        nid = run.m("wiki_pages", r.get("id"))
        if not nid:
            continue
        p = c.execute("SELECT org_id, owner_id, updated_at FROM wiki_pages WHERE id=?", (nid,)).fetchone()
        text = _body(run, str(r.get("body") or ""))
        c.execute("UPDATE wiki_pages SET body=? WHERE id=?", (wkh_seal(c, p["org_id"], p["owner_id"], text), nid))
        wiki_set_links(c, nid, text)
        wks_index(c, nid, p["org_id"], p["owner_id"], text, p["updated_at"])


def _finish_refs(c, run):
    """2.353.0 C (#2829): the reference nodes point at the new page / table; one whose page / table did not come along (a
    locked page, the trash) goes again. 2.581.0 (#4811): the same for a team chat channel's node."""
    for sid, kind, ref in _st(run).get("refs") or []:
        nid, new = run.m("fs_nodes", sid), run.m({**_REF_KINDS, **_CORE_REF_KINDS, **_CORE_LATE}[kind], ref)
        if nid and new and not c.execute("SELECT 1 FROM fs_nodes WHERE ref_kind=? AND ref_id=? AND kind='ref'", (kind, new)).fetchone():
            c.execute("UPDATE fs_nodes SET ref_id=? WHERE id=?", (new, nid))
        elif nid:
            c.execute("DELETE FROM fs_nodes WHERE id=? AND kind='ref' AND ref_id IS NULL", (nid,))


def _finish_store(c, run, oi):
    _finish_refs(c, run)
    for r in oi.get("store/nodes.json") or []:  # a version that could not be taken over: the newest one that came along counts
        nid = run.m("fs_nodes", r.get("id"))
        if not nid or r.get("kind") != "file":
            continue
        v = c.execute("SELECT no, size, mime FROM fs_versions WHERE node_id=? ORDER BY (no=?) DESC, no DESC LIMIT 1",
                      (nid, _oidi(r.get("cur_version")))).fetchone()
        if v:
            c.execute("UPDATE fs_nodes SET cur_version=?, size=? WHERE id=?", (v["no"], v["size"], nid))
            if not c.execute("SELECT 1 FROM doc_meta WHERE node_id=?", (nid,)).fetchone():  # its text for the search, like an upload
                from ..files.textscan import ts_after_store
                ts_after_store(c, "fs", nid, None, None)


def _finish_docs(c, run):
    from ..docs import store as S
    for nid, ws in _st(run)["docs"]:
        node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        m = S.meta_row(c, nid)
        if not node or not m:
            continue
        try:
            with c.savepoint():  # the word index and the models of the target learn the document
                S.doc_index(c, nid, ws, S.index_text(c, dict(m), node["name"], S.meta_text(c, m)))
                S.train(c, nid)
        except Exception as e:  # noqa: BLE001 -- a value that does not open: the document stays, without index
            print("orgimport: document index", nid, type(e).__name__, flush=True)
        if m["state"] != "done" or node["kind"] != "file":
            continue
        try:
            with c.savepoint():  # the preview, sealed like the file (docs/thumbfill.py makes the same)
                data = fs_read(c, nid)
                S.thumb_store(c, m, node, data, file_kind(node["name"], node["mime"], data[:2048]))
                t = c.execute("SELECT thumb, thumb_l FROM doc_meta WHERE node_id=?", (nid,)).fetchone()  # 2.583.0 (#4812): + thumb_l
                for rel in (t or ()):
                    if not rel:
                        continue
                    full = os.path.join(ATT_DIR, rel)
                    run.written.append(full)
                    run.created.setdefault("oi_files", []).append(full)
        except Exception as e:  # noqa: BLE001 -- no preview: the documents view shows the placeholder
            print("orgimport: document preview", nid, type(e).__name__, flush=True)


def _finish_auto(c, run):
    """2.369.0 (#2734): the mark "automatic" of a field value (doc_meta.auto, key cf<id>) -> the target's field."""
    for nid, _ in _st(run)["docs"]:
        r = c.execute("SELECT auto FROM doc_meta WHERE node_id=?", (nid,)).fetchone()
        try:
            auto = json.loads(r["auto"] or "{}") if r else None
        except (ValueError, TypeError):
            auto = None
        if not isinstance(auto, dict) or not any(_CF_KEY.fullmatch(k) for k in auto):
            continue
        out = {k: v for k, v in auto.items() if not _CF_KEY.fullmatch(k)}
        for k, v in auto.items():
            new = run.m("doc_fields", k[2:]) if _CF_KEY.fullmatch(k) else None
            if new:
                out[f"cf{new}"] = v
        c.execute("UPDATE doc_meta SET auto=? WHERE node_id=?", (json.dumps(out), nid))


def _finish(c, run, uid, data, who):
    oi = data.get("oi") or {}
    _finish_store(c, run, oi)
    _finish_docs(c, run)
    _finish_auto(c, run)
    _finish_sheets(c, run, oi, who)
    _finish_sheet_shares(c, run, oi, uid)  # 2.647.0 (#5047)
    _finish_wiki(c, run, oi)


_P = {"created_by": "null"}
SPECS = [
    # file store: nodes (parents late), versions, shares, history
    OiT("store/nodes.json", "fs_nodes", people={"owner_id": "me", "created_by": "null", "deleted_by": "null"}, late={"parent_id": "fs_nodes", "hub_mail_id": "hub_mails"},  # 2.363.2 (#3106): the mark of a filed mail's nodes (the mail's reading rule)
        label=N_("File store"), prep=_node),
    OiT("store/area_roots.json", "fs_area_roots", rid=False, key=("ws", "area"), prep=_area_root),  # 2.353.0 C (#2829)
    OiT("store/versions.json", "fs_versions", refs={"node_id": "fs_nodes"}, need=("node_id",), people=_P, space=(), prep=_version),
    OiT("store/locks.json", "fs_locks", refs={"node_id": "fs_nodes"}, need=("node_id",), rid=False, prep=_lock),  # #4300: go with the node (undo)
    OiT("store/lock_keys.json", "fs_lock_keys", refs={"node_id": "fs_nodes"}, need=("node_id",), people={"user_id": "me"}, space=(), rid=False, prep=_lock_key),
    OiT("store/shares.json", "fs_shares", refs={"node_id": "fs_nodes"}, need=("node_id",), people={"user_id": "member", **_P}, space=(),
        prep=_share),
    OiT("store/history.json", "fs_log", refs={"node_id": "fs_nodes"}, need=("node_id",), people={"user_id": "null"}, space=(),
        prep=_history),  # 2.581.0 (#4811)
    # documents: labels first (found by name in the target), then the links of the tags, rules, settings, the documents
    OiT("documents/senders.json", "doc_senders", prep=_label("sender")),
    OiT("documents/types.json", "doc_types", prep=_label("type")),
    OiT("documents/tags.json", "doc_tags", prep=_label("tag")),
    OiT("documents/document_tags.json", "doc_node_tags", refs={"node_id": "fs_nodes", "tag_id": "doc_tags"}, need=("node_id", "tag_id"),
        space=(), rid=False),
    OiT("documents/rules.json", "doc_rules", people=_P, prep=_rule),
    OiT("documents/settings.json", "doc_cfg", rid=False, key=("ws",), prep=_cfg),  # 2.137.1 (#2399): undone by its workspace
    # 2.278.0 B (#3094): dup_of (an older document's node) mapped, never the old id
    OiT("documents/meta.json", "doc_meta", refs={"node_id": "fs_nodes", "sender_id": "doc_senders", "type_id": "doc_types", "task_id": "tasks",
                                                 "dup_of": "fs_nodes"},
        need=("node_id",), people=_P, rid=False, label=N_("Documents"), prep=_meta),
    # 2.278.0 B (#3094): billed_doc_id -> the new invoice (office_docs come first), like the trip items
    OiT("documents/receipts.json", "rc_receipts", refs={"node_id": "fs_nodes", "list_id": "lists", "billed_doc_id": "office_docs"}, need=("node_id",),
        people={"set_by": "null"}, rid=False, prep=_receipt),
    # 2.184.0 A (#2579): custom fields + their values (undone with the run like every created row), the letters' documents
    OiT("documents/fields.json", "doc_fields", people=_P, prep=_field),
    OiT("documents/field_values.json", "doc_field_values", refs={"node_id": "fs_nodes", "field_id": "doc_fields"},
        need=("node_id", "field_id"), prep=_field_value),
    # 2.635.0 (#4807 d): after the documents (doc_meta: their workspace); 2.981.0 (#5273): into obj_comments (kind doc_note)
    OiT("documents/notes.json", "obj_comments", kind="obj_comments_doc_note", refs={"ref_id": "fs_nodes"}, src={"ref_id": "node_id"},
        need=("ref_id",), people={"user_id": "null"}, prep=_doc_note, fixed={"kind": "doc_note"}),
    OiT("office/letter_links.json", "office_letter_links", refs={"letter_id": "office_letters", "node_id": "fs_nodes"},
        need=("letter_id", "node_id"), people={**_P, "agent_id": "null"}, private="office", label=N_("Letters")),
    # knowledge pages (text sealed in prep: enc off) and their files
    OiT("wiki/pages.json", "wiki_pages", people={"created_by": "null", "updated_by": "null"}, label=N_("Knowledge pages"), prep=_page,
        enc=False),
    OiT("wiki/files.json", "wiki_files", refs={"page_id": "wiki_pages"}, need=("page_id",), people=_P, prep=_wiki_file),
    # 2.958.0 (#5281): into the core's versions; the archive (also an older one) names the page page_id and its name path
    OiT("wiki/versions.json", "obj_versions", kind="obj_versions_wiki", refs={"ref_id": "wiki_pages"}, src={"ref_id": "page_id"},
        need=("ref_id",), people=_P, prep=_wiki_version, enc=False, fixed={"kind": WKH_KIND, "no": 0}),
    # tables
    OiT("sheets/sheets.json", "sheets", refs={"list_id": "lists"}, late={"book_id": "sheets"},
        people={"created_by": "null", "updated_by": "null"}, label=N_("Tables"), prep=_sheet),
    OiT("sheets/columns.json", "sheet_columns", refs={"sheet_id": "sheets"}, need=("sheet_id",), space=()),
    OiT("sheets/rows.json", "sheet_rows", refs={"sheet_id": "sheets"}, need=("sheet_id",), space=()),
    OiT("sheets/cells.json", "sheet_cells", refs={"sheet_id": "sheets", "row_id": "sheet_rows", "col_id": "sheet_columns"},
        need=("sheet_id", "row_id", "col_id"), people={"updated_by": "null"}, space=(), prep=_cell),
    OiT("sheets/files.json", "sheet_files", refs={"sheet_id": "sheets"}, need=("sheet_id",), people=_P, prep=_sheet_file),
    OiT("sheets/links.json", "sheet_links", refs={"sheet_id": "sheets", "row_id": "sheet_rows", "list_id": "lists"}, need=("sheet_id",),
        people=_P, space=(), prep=_sheet_link),
    OiT("sheets/shares.json", "sheet_shares", refs={"sheet_id": "sheets"}, need=("sheet_id",), people={"user_id": "member", **_P},
        prep=_sheet_share),
    OiT("sheets/history.json", "sheet_hist", refs={"sheet_id": "sheets", "cell_id": "sheet_cells", "row_id": "sheet_rows",
                                                  "col_id": "sheet_columns"}, need=("sheet_id",), people={"user_id": "null"}, space=()),
    # video sign-offs
    OiT("videos/reviews.json", "video_reviews", refs={"task_id": "tasks", "list_id": "lists", "client_id": "clients"}, people=_P,
        label=N_("Video sign-offs"), prep=_video),
    OiT("videos/versions.json", "video_versions", refs={"review_id": "video_reviews"}, need=("review_id",), people=_P, prep=_video_version),
    # 2.981.0 (#5273): into obj_comments (kind video; the archive keeps the columns of video_comments, _video_comment)
    OiT("videos/comments.json", "obj_comments", kind="obj_comments_video", refs={"ref_id": "video_reviews"}, src={"ref_id": "review_id"},
        need=("ref_id",), late={"parent_id": "obj_comments_video"}, prep=_video_comment, fixed={"kind": "video"}),
]
FIXES = []
FINISH = [_finish]
