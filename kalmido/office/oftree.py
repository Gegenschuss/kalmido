"""2.351.0 A (#3312): the office's document areas as trees in the panel -- Quotes & invoices (with order confirmations,
credit notes, reminders, delivery notes), Documents (generated), Correspondence (letters), Receipts. Each area opens like a
list / a folder: its folders (with subfolders), the 20 newest documents in no folder and "More…" (the area's full list).

Which folders belong to an area (the simplest form that keeps everything in view):
- the folders below the area's root folder of the office's workspace (files/fsroots.py, area 'of_<area>', e.g. "Quotes &
  invoices" at the top of the organisation's tree / a personal office: its owner's private tree), made on the first folder
  ("New folder…" at the area) -- like the tables' folders (sheets/shfolder.py): a folder made at the top is its maker's
  (nobody else sees it until it is shared through the file store's one share dialog), rights inherit from the folder;
- plus every other folder of the workspace that holds a document of the area the person sees (filed there before 2.351, by
  the file store's "Move to…", or a folder of the file store a document was dragged onto): shown with its path ("outside"),
  only with the area's documents in it -- nothing that lies in a folder today drops out of sight. Nothing moves, no data
  changes: a document lies in a folder through its reference node (files/fsref.py: office_doc, office/oftref.py: office_gendoc,
  office_letter, office_receipt); filing / moving it is POST /api/files/refs, sorting the file store's order route.

Rights stay as they are: the routes are the area's office routes (/api/office/<area's segment>/tree, office/rights.py: the
area's level), the folders listed are the ones the person sees (fs_role), a document of a folder only when it is one of the
office's documents of that area (the office's own read). Customers get no folders (#2742: no office route for them).

    GET  /api/office/docs/tree | gen-docs/tree | letters/tree | receipts/tree
         -> {area, space ('org:<id>' | 'private'), root (null: none yet), can_add, folders: [{id, parent_id, name, sort_no,
            role, shared, outside, path}], docs: [{id, title, sub, folder_id, fnode, fsort, kind, open}] (in shown folders +
            the 20 newest in none), more (more documents in no folder than shown), kind (the reference kind)}
    POST /api/office/<segment>/tree/folders {name, parent_id?} -> {folder}, 201: a folder below parent_id, else at the top
         of the area (below its root, made on the first one)
"""
from flask import jsonify

from ..core.config import app
from ..core.db import body, bump, insert_id
from ..core.errors import BadInput, Denied
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_dec_fields
from ..accounts.orgroles import org_writes
from ..files.fsref import fs_ref_role
from ..files.fsroots import fs_area_folder_name, fs_area_root
from ..files.store import _now, _place, fs_chain, fs_deleted, fs_log_add, fs_role, fs_visible_sql, safe_fs_name
from .model import office_ctx, pb_owner
from .oftref import _gd, _lt
from .rights import AREA_LEGACY

OFT_NEWEST = 20
OFT_FILED_MAX = 2000
# area -> (route segment, reference kind, the root folder's name)
OFT_AREAS = {
    "offers": ("docs", "office_doc", N_("Quotes & invoices")),
    "gendocs": ("gen-docs", "office_gendoc", N_("Documents")),
    "letters": ("letters", "office_letter", N_("Correspondence")),
    "receipts": ("receipts", "office_receipt", N_("Receipts")),
}
OFD_KIND_NAME = {"offer": N_("Quotation"), "invoice": N_("Invoice"), "credit": N_("Credit note"), "reminder": N_("Reminder"),
                 "delivery": N_("Delivery note")}


def oft_space(c, oid):
    """(org_id | None, owner_id | None) of office oid's file tree: an organisation's; a personal office its owner's private tree."""
    owner = pb_owner(c, oid)
    return (None, owner) if owner is not None else (oid, None)


def oft_root(c, uid, oid, area, create=False):
    org, _owner = oft_space(c, oid)
    return fs_area_root(c, uid, org, "of_" + area, tr(OFT_AREAS[area][2]), create=create)


def _below(c, root):
    """The folders below root (not in the trash), parents first (sheets/shfolder.py _below)."""
    return c.execute("""WITH RECURSIVE t(id, depth) AS (SELECT id, 0 FROM fs_nodes WHERE id=?
                          UNION ALL SELECT n.id, t.depth + 1 FROM fs_nodes n JOIN t ON n.parent_id=t.id
                          WHERE n.kind='folder' AND n.deleted_at IS NULL AND t.depth < 32)
                        SELECT n.* FROM fs_nodes n JOIN t ON t.id=n.id WHERE n.id<>? ORDER BY t.depth, n.id LIMIT 2000""",
                     (int(root), int(root))).fetchall()


def _ids(xs):
    return ",".join(str(int(i)) for i in xs) or "0"


def _in(col, ids, neg):
    """The SQL condition "col (NOT) IN (ids)" (ids inlined as integers)."""
    return f"{col} {'NOT IN' if neg else 'IN'} ({_ids(ids)})"


# ---------------------------------------------------------------- the documents of an area (one query each, ids inlined)
def _docs_offers(c, uid, oid, ids, neg, limit):
    rows = c.execute(f"SELECT id, kind, number, status, date, project_title, trial, locked_at FROM office_docs WHERE org_id=? AND {_in('id', ids, neg)} "
                     f"ORDER BY id DESC LIMIT {int(limit)}", (oid,)).fetchall()
    return [{"id": r["id"], "kind": r["kind"], "title": f"{tr(OFD_KIND_NAME.get(r['kind'], OFD_KIND_NAME['offer']))} {r['number'] or tr('Draft')}",
             "sub": r["project_title"] or "", "date": r["date"] or "", "locked": bool(r["locked_at"]), "open": f"office/offers/{r['id']}"} for r in rows]


def _docs_gendocs(c, uid, oid, ids, neg, limit):
    rows = c.execute(f"SELECT id, title, status, created_at FROM office_gen_docs WHERE org_id=? AND archived=0 AND {_in('id', ids, neg)} "
                     f"ORDER BY id DESC LIMIT {int(limit)}", (oid,)).fetchall()
    return [{"id": r["id"], "kind": "gendoc", "title": r["title"] or tr("Document"), "sub": "", "date": (r["created_at"] or "")[:10],
             "locked": r["status"] != "draft", "open": f"office/gendocs/{r['id']}"} for r in rows]


def _docs_letters(c, uid, oid, ids, neg, limit):
    rows = c.execute(f"SELECT id, subject, letter_date, status FROM office_letters WHERE org_id=? AND archived=0 AND {_in('id', ids, neg)} "
                     f"ORDER BY letter_date DESC, id DESC LIMIT {int(limit)}", (oid,)).fetchall()
    out = []
    for r in rows:
        d = oc_dec_fields(c, oid, "office_letters", r)
        out.append({"id": r["id"], "kind": "letter", "title": d.get("subject") or tr("Letter"), "sub": "", "date": r["letter_date"] or "",
                    "locked": r["status"] != "draft", "open": f"office/letters/{r['id']}"})
    return out


def _docs_receipts(c, uid, oid, ids, neg, limit):
    from .books import bk_ws
    rows = c.execute(f"SELECT r.node_id, n.name, n.created_at FROM rc_receipts r JOIN fs_nodes n ON n.id=r.node_id WHERE r.ws=? "
                     f"AND n.kind='file' AND n.deleted_at IS NULL AND n.id IN {fs_visible_sql(uid, c)} AND {_in('r.node_id', ids, neg)} "
                     f"ORDER BY r.node_id DESC LIMIT {int(limit)}", (bk_ws(c, oid),)).fetchall()
    return [{"id": r["node_id"], "kind": "receipt", "title": r["name"], "sub": "", "date": (r["created_at"] or "")[:10], "locked": False,
             "open": f"docs/{r['node_id']}"} for r in rows if not fs_deleted(fs_chain(c, r["node_id"]))]


OFT_DOCS = {"offers": _docs_offers, "gendocs": _docs_gendocs, "letters": _docs_letters, "receipts": _docs_receipts}


def oft_tree(c, uid, oid, area):
    """The tree of one area (module docstring)."""
    kind = OFT_AREAS[area][1]
    org, owner = oft_space(c, oid)
    root = oft_root(c, uid, oid, area)
    folders, seen = [], set()
    if root:
        rows = _below(c, root)
        shared = {x[0] for x in c.execute(f"SELECT DISTINCT node_id FROM fs_shares WHERE node_id IN ({_ids(r['id'] for r in rows)})")} if rows else set()
        for r in rows:
            role = fs_role(c, r["id"], uid)
            if not role:
                continue
            seen.add(r["id"])
            folders.append({"id": r["id"], "parent_id": r["parent_id"], "name": r["name"], "sort_no": r["sort_no"], "role": role,
                            "shared": r["id"] in shared, "outside": False, "path": ""})
    # the area's documents filed in a folder uid sees (also outside the root: filed before 2.351 / in the file store)
    sp = f"n.org_id = {int(org)}" if org else f"n.org_id IS NULL AND n.owner_id = {int(owner)}"
    nodes = c.execute(f"SELECT n.id, n.parent_id, n.ref_id, n.sort_no FROM fs_nodes n WHERE n.kind='ref' AND n.ref_kind=? AND n.deleted_at IS NULL "
                      f"AND {sp} AND n.id IN {fs_visible_sql(uid, c)} ORDER BY n.id LIMIT {OFT_FILED_MAX}", (kind,)).fetchall()
    out_par = {}
    for n in nodes:
        p = n["parent_id"]
        if p in seen or p in out_par:
            continue
        chain = fs_chain(c, p)
        role = fs_role(c, p, uid, chain=chain) if chain else None
        if not role or fs_deleted(chain):
            out_par[p] = None
            continue
        out_par[p] = {"id": p, "parent_id": None, "name": chain[0]["name"], "sort_no": None, "role": role, "shared": False, "outside": True,
                      "path": " / ".join(x["name"] for x in reversed(chain))}
    folders += [x for x in out_par.values() if x]
    shown = seen | {k for k, v in out_par.items() if v}
    filed = {n["ref_id"]: n for n in nodes if n["parent_id"] in shown}
    docs = []
    if filed:  # the office's own documents of the area among them (another office's / area's: never)
        for d in OFT_DOCS[area](c, uid, oid, filed, False, OFT_FILED_MAX):
            n = filed[d["id"]]
            docs.append({**d, "folder_id": n["parent_id"], "fnode": n["id"], "fsort": n["sort_no"]})
    loose = OFT_DOCS[area](c, uid, oid, filed, True, OFT_NEWEST + 1)
    docs += [{**d, "folder_id": None, "fnode": None, "fsort": None} for d in loose[:OFT_NEWEST]]
    return {"area": area, "kind": kind, "space": f"org:{int(org)}" if org else "private", "root": root,
            "can_add": bool(org_writes(c, uid, org)), "folders": folders, "docs": docs, "more": len(loose) > OFT_NEWEST,
            "shared": oft_shared(c, uid, oid, area) if area in ("gendocs", "letters") else []}


def oft_shared(c, uid, oid, area):
    """2.351.0 A (#2823): the documents / letters of ANOTHER office uid reaches only through a folder shared with them (e.g. a
    freelancer's folder): [{id, node, title}] -- the lists of the area show them (read: the PDF through the file store)."""
    kind, row = OFT_AREAS[area][1], (_gd if area == "gendocs" else _lt)
    out = []
    for n in c.execute(f"SELECT id, ref_id, name FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND deleted_at IS NULL "
                       f"AND id IN {fs_visible_sql(uid, c)} ORDER BY id DESC LIMIT 200", (kind,)).fetchall():
        r = row(c, n["ref_id"])
        if r and r["org_id"] != oid and fs_ref_role(c, uid, kind, n["ref_id"]):
            out.append({"id": n["ref_id"], "node": n["id"], "title": n["name"]})
    return out


def _folder_new(c, uid, oid, area):
    b = body()
    raw = str(b.get("name") or "").strip()
    if not raw:
        raise BadInput(tr("Name missing"))
    pid = b.get("parent_id")
    if pid is not None:
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise BadInput(tr("Invalid value: {0}", "parent_id"))
        owner, org = _place(c, uid, pid, None)
    else:  # at the top of the area: below its root, but the person's own (like a folder at the top of the tables)
        sorg, _o = oft_space(c, oid)
        owner, org = _place(c, uid, None, sorg)
        pid = oft_root(c, uid, oid, area, create=True)
    if (org or None) != (oft_space(c, oid)[0] or None):
        raise Denied(409, tr("Files can only be moved within the same space"))
    ts = _now()
    nid = insert_id(c, "INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (pid, "folder", fs_area_folder_name(c, pid, owner, org, safe_fs_name(raw)), owner, org, uid, ts, ts))
    fs_log_add(c, nid, "create")
    bump(c)
    c.commit()
    r = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    return jsonify(folder={"id": nid, "parent_id": pid, "name": r["name"], "sort_no": None, "role": fs_role(c, nid, uid),
                           "shared": False, "outside": False, "path": ""}), 201


def _ctx(area):
    """The area's office context: gen-docs / letters / receipts are admin routes like the area's own (office_ctx_admin)."""
    return office_ctx(AREA_LEGACY[area] == "admin")


def _get(area):
    c, uid, oid = _ctx(area)
    return jsonify(oft_tree(c, uid, oid, area))


def _post(area):
    c, uid, oid = _ctx(area)
    return _folder_new(c, uid, oid, area)


# literal routes (the route guards read them from the source, tests/routes_ast.py)
@app.get("/api/office/docs/tree")
def oft_tree_offers():
    return _get("offers")


@app.post("/api/office/docs/tree/folders")
def oft_folder_offers():
    return _post("offers")


@app.get("/api/office/gen-docs/tree")
def oft_tree_gendocs():
    return _get("gendocs")


@app.post("/api/office/gen-docs/tree/folders")
def oft_folder_gendocs():
    return _post("gendocs")


@app.get("/api/office/letters/tree")
def oft_tree_letters():
    return _get("letters")


@app.post("/api/office/letters/tree/folders")
def oft_folder_letters():
    return _post("letters")


@app.get("/api/office/receipts/tree")
def oft_tree_receipts():
    return _get("receipts")


@app.post("/api/office/receipts/tree/folders")
def oft_folder_receipts():
    return _post("receipts")
