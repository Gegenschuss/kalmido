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
from .orgimport import OiT
from .acctimport import tr  # 2.184.0 A (#2579)
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions
from ..core.config import ATT_DIR  # 2.149.0 G (#2517): pulled up from functions

_LOCKED = "e2e1:"
_FILE_CELL = re.compile(r"file:(\d{1,15})")
_SH_REF = re.compile(r"\{(c|col|p|l|k|t|x):(\d{1,18})\}")
_SH_KIND = {"c": "sheet_cells", "x": "sheet_cells", "col": "sheet_columns", "p": "lists", "l": "lists", "k": "clients", "t": "tasks"}
_WK_NODE = re.compile(r"/api/files/nodes/(\d{1,15})/content\b")
_WK_FILE = re.compile(r"/api/wiki/files/(\d{1,15})\b")
_WK_REF = re.compile(r"(\[\[\s*(datei|tabelle)\s*:\s*)(\d{1,15})(\s*[\]|])", re.I)
_WK_TASK = re.compile(r"(?<![\w&/#])#(\d{1,12})\b")


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
        return False  # the target's knowledge pages have the lock: their pages stay out (_page), so does the tree
    if sid in st["roots"]:  # an area's root: the target's own root of that area when it has one (never a second root)
        from ..files.fsroots import fs_area_root
        have = fs_area_root(c, ctx.uid, ctx.space, area, "", create=False)
        if have:
            run.put("fs_nodes", sid, have)
            st["merged"].add(have)
            return False
        st["new_roots"][sid] = area
        d["parent_id"] = None
    elif area == "wiki" and d["kind"] == "folder" and run.m("fs_nodes", src.get("parent_id")) in st["merged"]:
        have = c.execute("SELECT id FROM fs_nodes WHERE parent_id=? AND kind='folder' AND name=? AND deleted_at IS NULL",
                         (run.m("fs_nodes", src.get("parent_id")), d.get("name"))).fetchone()
        if have:  # a knowledge folder's names are exact (wiki/wkfolder.py): the target's folder of that name takes it
            run.put("fs_nodes", sid, have[0])
            st["merged"].add(have[0])
            return False
    if d["kind"] == "ref":
        if src.get("ref_kind") not in _REF_KINDS or not area:
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


def _area_root(c, run, src, d, ctx):
    """2.353.0 C (#2829): the mark of an area's root made by this import (a root put into the target's own one: nothing)."""
    from ..files.fsroots import fs_area_ws
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
    from ..files.store import FS_DIR
    from .orgexport import _safe_part
    st = _st(run)
    if st["names"] is None:
        st["names"] = {r.get("id"): r.get("name") for r in (ctx.data.get("oi") or {}).get("store/nodes.json") or []}
    name = st["names"].get(src.get("node_id"))
    try:
        path = f"files/store/{int(src['node_id'])}-v{int(src['no'])}-{_safe_part(name)}"
    except (TypeError, ValueError, KeyError):
        return None
    got = ctx.file(path, os.path.join(FS_DIR, str(d["node_id"])), name or "file", mime=str(src.get("mime") or ""))
    if not got:
        return None
    d["path"], d["size"] = got
    d["sha256"] = _same_bytes(src, d, got[1])
    return d


def _share(c, run, src, d, ctx):
    return d if d.get("user_id") and _not_agent(c, d["user_id"]) else None  # people only (groups and agents stay out)


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
    """A field / value not taken over: named like a row of the documents (no label on the specs: the preview counts documents)."""
    run.warning(N_("A row could not be taken over: {0}"), tr(N_("Documents")))
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


def _field_value(c, run, src, d, ctx):
    """2.184.0 A (#2579): the value of a custom field, sealed with the target's workspace key (a select value -> its option)."""
    from ..docs import store as S
    f = c.execute("SELECT ws, type, options FROM doc_fields WHERE id=?", (d["field_id"],)).fetchone()
    v = src.get("value")
    if not f or not isinstance(v, str) or v.startswith("kenc1:"):
        return _df_skip(run)  # a value that did not open in the export
    if f["type"] == "select":
        omap = _st(run).get("opts", {}).get(d["field_id"])
        v = omap.get(v) if omap is not None else v
        if v not in {o["id"] for o in _df_opts(f["options"])}:
            return _df_skip(run)
    d["ws"], d["value"] = f["ws"], S.doc_seal(c, f["ws"], "doc_field_values.value", v)
    return d


# ---- knowledge pages -----------------------------------------------------------------------------------------------------
def _wiki_locked(c, ctx):
    return c.execute("SELECT 1 FROM wiki_spaces WHERE COALESCE(org_id,0)=? AND COALESCE(owner_id,0)=? AND e2e IS NOT NULL",
                     (ctx.space or 0, 0 if ctx.space else ctx.uid)).fetchone() is not None


def _video_version(c, run, src, d, ctx):
    """2.137.0 review M1: the link is checked like a pasted one (videos/review.py vdr_parse); provider and embed id come from it."""
    from ..videos.review import vdr_parse
    from .acctimport import tr, umz_cols
    try:
        v = vdr_parse(src.get("url"))
    except BadInput:
        run.warning(N_("A row could not be taken over: {0}"), tr(N_("Video sign-offs")))
        return False
    for k in ("url", "provider", "embed_id"):
        if k in d or k in umz_cols(c, "video_versions")[0]:
            d[k] = v[k]
    return d


_W_LOCKED = N_("Knowledge pages encrypted in the browser were not taken over: export them as Markdown from the unlocked space and import that file into the knowledge pages.")


def _page(c, run, src, d, ctx):
    from ..wiki.wkhist import wkh_seal
    st = _st(run)
    if str(src.get("path") or "").startswith(_LOCKED) or str(src.get("body") or "").startswith(_LOCKED):
        if not st.get("w_src"):  # named once; the row itself counts under "A row could not be taken over"
            st["w_src"] = run.warning(_W_LOCKED) or 1
        return None
    if _wiki_locked(c, ctx):
        if not st.get("w_dst"):
            st["w_dst"] = run.warning(N_("The knowledge pages of this space are encrypted in the browser")) or 1
        return None
    d["owner_id"] = _owner(ctx)
    d["body"] = wkh_seal(c, ctx.space, d["owner_id"], d.get("body") or "")  # ids inside are put right in _finish
    return d


def _wiki_version(c, run, src, d, ctx):
    from ..wiki.wkhist import WKH_VCTX, wkh_seal
    if str(src.get("path") or "").startswith(_LOCKED) or str(src.get("body") or "").startswith(_LOCKED):
        return None
    pg = c.execute("SELECT org_id, owner_id FROM wiki_pages WHERE id=?", (d["page_id"],)).fetchone()
    if not pg:
        return None
    d["owner_id"] = pg["owner_id"]
    d["body"] = wkh_seal(c, pg["org_id"], pg["owner_id"], d.get("body") or "", ctx=WKH_VCTX)
    return d


def _receipt(c, run, src, d, ctx):
    d["ws"] = _ws(ctx)
    if (src.get("billed_doc_id") or src.get("billed_at")) and not d.get("billed_doc_id"):  # 2.278.0 B (#3094): never silently open
        d["billed_at"] = None
        run.warning(N_("Billed receipts whose invoice did not come along are open again: check them before billing"))
    return d


def _wiki_file(c, run, src, d, ctx):
    from .orgexport import _safe_part
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
    from .orgexport import _safe_part
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
    return d if _not_agent(c, d["user_id"]) else None


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


def _body(run, text):
    text = _WK_NODE.sub(lambda m: f"/api/files/nodes/{run.m('fs_nodes', m.group(1)) or 0}/content", text)
    text = _WK_FILE.sub(lambda m: f"/api/wiki/files/{run.m('wiki_files', m.group(1)) or 0}", text)
    text = _WK_REF.sub(lambda m: f"{m.group(1)}{run.m('fs_nodes' if m.group(2).lower() == 'datei' else 'sheets', m.group(3)) or 0}{m.group(4)}",
                       text)
    return _WK_TASK.sub(lambda m: f"#{run.m('tasks', m.group(1))}" if run.m("tasks", m.group(1)) else m.group(0), text)


def _finish_wiki(c, run, oi):
    from ..wiki.pages import wiki_set_links
    from ..wiki.wkhist import wkh_seal
    from ..wiki.wksearch import wks_index
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
    locked page, the trash) goes again."""
    for sid, kind, ref in _st(run).get("refs") or []:
        nid, new = run.m("fs_nodes", sid), run.m(_REF_KINDS[kind], ref)
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
    from ..files.store import fs_read
    from ..tasks.attachtext import file_kind
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
                t = c.execute("SELECT thumb FROM doc_meta WHERE node_id=?", (nid,)).fetchone()
                if t and t[0]:
                    full = os.path.join(ATT_DIR, t[0])
                    run.written.append(full)
                    run.created.setdefault("oi_files", []).append(full)
        except Exception as e:  # noqa: BLE001 -- no preview: the documents view shows the placeholder
            print("orgimport: document preview", nid, type(e).__name__, flush=True)


def _finish(c, run, uid, data, who):
    oi = data.get("oi") or {}
    _finish_store(c, run, oi)
    _finish_docs(c, run)
    _finish_sheets(c, run, oi, who)
    _finish_wiki(c, run, oi)


_P = {"created_by": "null"}
SPECS = [
    # file store: nodes (parents late), versions, shares, history
    OiT("store/nodes.json", "fs_nodes", people={"owner_id": "me", "created_by": "null", "deleted_by": "null"}, late={"parent_id": "fs_nodes"},
        label=N_("File store"), prep=_node),
    OiT("store/area_roots.json", "fs_area_roots", rid=False, key=("ws", "area"), prep=_area_root),  # 2.353.0 C (#2829)
    OiT("store/versions.json", "fs_versions", refs={"node_id": "fs_nodes"}, need=("node_id",), people=_P, space=(), prep=_version),
    OiT("store/shares.json", "fs_shares", refs={"node_id": "fs_nodes"}, need=("node_id",), people={"user_id": "member", **_P}, space=(),
        prep=_share),
    OiT("store/history.json", "fs_log", refs={"node_id": "fs_nodes"}, need=("node_id",), people={"user_id": "null"}, space=()),
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
    OiT("office/letter_links.json", "office_letter_links", refs={"letter_id": "office_letters", "node_id": "fs_nodes"},
        need=("letter_id", "node_id"), people={**_P, "agent_id": "null"}, private="office", label=N_("Letters")),
    # knowledge pages (text sealed in prep: enc off) and their files
    OiT("wiki/pages.json", "wiki_pages", people={"created_by": "null", "updated_by": "null"}, label=N_("Knowledge pages"), prep=_page,
        enc=False),
    OiT("wiki/files.json", "wiki_files", refs={"page_id": "wiki_pages"}, need=("page_id",), people=_P, prep=_wiki_file),
    OiT("wiki/versions.json", "wiki_versions", refs={"page_id": "wiki_pages"}, need=("page_id",), people=_P, prep=_wiki_version,
        enc=False),
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
    OiT("videos/comments.json", "video_comments", refs={"review_id": "video_reviews", "version_id": "video_versions"}, need=("review_id",),
        late={"parent_id": "video_comments"}, people={"author_id": "null"}),
]
FIXES = []
FINISH = [_finish]
