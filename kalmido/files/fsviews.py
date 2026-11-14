"""2.429.0 (#3580): the file store ("Ablage") shows only its own folders. One view is uniform (one list, one folder panel, one
share dialog), not the storage behind it: the root folders of the other areas (files/fsroots.py -- knowledge, tables, the
office's areas, projects, address book) with their folders and reference nodes stay where they are (no data moves, the
areas' panels list them as before), but the file store's listings leave them out:
  - the top of a space (private / org:<id>) and "Shared with me" (a folder of an area shared with the person),
  - the search over names and recognised text (a knowledge page's reference node, a table's folder),
  - the folder list of "Move to…" when the file store asks for it (?ablage=1; the office's own "Move to folder" still
    lists its folders).
Opening an area's folder by its address (files_list ?parent=, the areas' share dialogs, links) still works.

What hangs on an area's objects is shown read-only as a collection "From <area>" at the top of the space, grouped by its
object (only listed when it has something the person may read):
  wiki      the files of knowledge pages (wiki_files), per page; deleted only on the page itself
  lists     the project files (list_files), per project; deleted only in the project
  sheets    the files of the tables' file cells (sheet_files), per table; deleted only in the table
  every key (also the ones above) the files (kind 'file') that lie in the area's folders (put there by an older version):
            per folder -- nothing that lay there drops out of sight
Knowledge pages themselves are found through the global search (palette), not in the file store.
2.1148.0 (#4895): last, "Receipts" (key receipts, parts rcoffice / rcmeals / rcbudget, files/fsreceipts.py): references to the
receipts of the office, the entertainment receipts and the household budget -- items without a file address, `open` = the
app address of the receipt's area (they stay there); the collection entry carries subs [{key, name}] = its parts with something.

Only a person in the web app gets the collections (fslock.fsl_person_ok: no agent, no API token); the files open through their
own routes (/api/wiki/files/<id>, /api/list-files/<id>, /api/sheets/<id>/files/<id>, /api/files/nodes/<id>/content), which check the rights again.

    GET /api/files/collections/<key>?space=private | org:<id>
        -> {key, name, space, groups: [{title, open (the object's route in the app | null), items: [{id, kind (wiki |
           list | sheet | fs), name, mime, size, created_at, url, dl}]}], more (cut at FSV_MAX)}
"""
from flask import jsonify, request

from ..core.access import acx_of, vis_sql
from ..core.config import app
from ..core.db import db, usettings
from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.pg import system_ctx
from ..accounts.session import me
from ..accounts.wsareas import wsa_org_check, wsa_org_off
from ..lists.projects import need_overview
from ..sheets.core import sh_need
from ..wiki.pages import wiki_may_read, wiki_space_sql
from ..wiki.wikiatt import wka_locked, wka_url
from .fsroots import fs_area_ws
from .store import fs_role

FSV_MAX = 500  # files per collection
# collection key -> its name; an area belongs to a key by fsv_key
FSV_KEYS = {"wiki": N_("From Knowledge"), "sheets": N_("From Tables"), "office": N_("From Office"),
            "lists": N_("From Projects"), "contacts": N_("From Address book")}
FSV_ORDER = ("wiki", "sheets", "office", "lists", "contacts")


def fsv_key(area):
    """The collection key of an area of fs_area_roots (None: an area the file store shows as its own folders)."""
    a = area or ""
    if a.startswith("of_"):
        return "office"
    return a if a in FSV_KEYS else None


def fsv_hidden(c, ids):
    """The nodes among ids whose tree's top is the root folder of another area (itself included). An area's root lies at the
    top of its workspace (fsroots._alive), so any marked node above is that top. Structure only (ids), all workspaces."""
    ids = sorted({int(i) for i in ids if i})
    out = set()
    with system_ctx(c):  # the folders above a shared node may be another person's / organisation's: ids only, nothing handed out
        for k in range(0, len(ids), 500):
            q = ",".join(str(x) for x in ids[k:k + 500])
            for s, a in c.execute(f"""WITH RECURSIVE up(start, cur, depth) AS (
                                        SELECT id, id, 0 FROM fs_nodes WHERE id IN ({q})
                                        UNION ALL SELECT up.start, n.parent_id, up.depth + 1 FROM up JOIN fs_nodes n ON n.id=up.cur
                                        WHERE n.parent_id IS NOT NULL AND up.depth < 64)
                                      SELECT up.start, r.area FROM up JOIN fs_area_roots r ON r.node_id=up.cur"""):
                if fsv_key(a):
                    out.add(s)
    return out


def fsv_drop(c, rows, key="id"):
    """rows without the nodes of other areas (rows: sqlite rows / dicts with key)."""
    hide = fsv_hidden(c, [r[key] for r in rows])
    return [r for r in rows if r[key] not in hide] if hide else list(rows)


def _person():
    from .fslock import fsl_person_ok
    return fsl_person_ok()


def _space(c, uid, v):
    """(org id | None) of ?space= -- private or an organisation of uid; else Denied."""
    v = (v or "private").strip()
    if v == "private":
        return None
    if v.startswith("org:") and v[4:].isdigit():
        oid = int(v[4:])
        if oid in acx_of(c, uid).org_ids:
            return oid
        raise Denied(404)
    raise Denied(400, tr("Invalid value: {0}", "space"))


def _cap(limit):
    """Rows read for limit files: some may be refused (a page / project / table the person may not read)."""
    return int(min(FSV_MAX * 4, max(200, limit * 4)))


def _item(kind, i, name, mime, size, created_at, url, dl):
    return {"id": i, "kind": kind, "name": name, "mime": mime or "", "size": size or 0, "created_at": created_at, "url": url, "dl": dl}


def _wiki(c, uid, oid, limit):
    """[(title, open, items)] -- the files of the knowledge pages of the space uid may read, per page (no locked space)."""
    w, a = wiki_space_sql(oid, uid)
    rows = c.execute(f"""SELECT id, page_id, name, mime, size, created_at FROM wiki_files WHERE deleted_at IS NULL AND {w}
                         ORDER BY page_id, name, id LIMIT {_cap(limit)}""", a).fetchall()
    pids = sorted({r["page_id"] for r in rows})
    pages = {}
    if pids:
        q = ",".join("?" * len(pids))
        for p in c.execute(f"SELECT * FROM wiki_pages WHERE id IN ({q}) AND deleted_at IS NULL", pids):
            pages[p["id"]] = p
    ok, out, n = {}, {}, 0
    for r in rows:
        p = pages.get(r["page_id"])
        if p is None:
            continue
        if p["id"] not in ok:
            ok[p["id"]] = not wka_locked(c, p) and wiki_may_read(c, uid, p)
        if not ok[p["id"]]:
            continue
        url = wka_url(r["id"], r["name"])
        g = out.setdefault(p["id"], (p["path"].rsplit("/", 1)[-1] or p["path"], f"wiki/{p['id']}", []))
        g[2].append(_item("wiki", r["id"], r["name"], r["mime"], r["size"], r["created_at"], url, url + "?dl=1"))
        n += 1
        if n >= limit:
            break
    return sorted(out.values(), key=lambda g: g[0].lower())


def _lists(c, uid, oid, limit):
    """[(title, open, items)] -- the project files of the space's projects uid may open (the project's full roles), per project."""
    sp, a = ("l.org_id=?", [oid]) if oid else ("l.org_id IS NULL", [])
    rows = c.execute(f"""SELECT f.id, f.list_id, f.name, f.mime, f.size, f.created_at, l.name AS list_name FROM list_files f
                         JOIN lists l ON l.id=f.list_id WHERE f.list_id IN {vis_sql()} AND f.deleted_at IS NULL
                         AND l.deleted_at IS NULL AND {sp} ORDER BY l.name, f.name, f.id LIMIT {_cap(limit)}""",
                     (uid, uid, *a)).fetchall()
    ok, out, n = {}, {}, 0
    for r in rows:
        if r["list_id"] not in ok:
            try:
                need_overview(c, r["list_id"], full=True)  # like opening the project file (textscan._list_file_hits)
                ok[r["list_id"]] = True
            except Denied:
                ok[r["list_id"]] = False
        if not ok[r["list_id"]]:
            continue
        url = f"/api/list-files/{int(r['id'])}"
        g = out.setdefault(r["list_id"], (r["list_name"] or "", f"l/{r['list_id']}", []))
        g[2].append(_item("list", r["id"], r["name"], r["mime"], r["size"], r["created_at"], url, url + "?dl=1"))
        n += 1
        if n >= limit:
            break
    return sorted(out.values(), key=lambda g: g[0].lower())


def _sheets(c, uid, oid, limit):
    """[(title, open, items)] -- the files of the file cells of the space's tables uid may read (sheets/core.sh_need), per table."""
    sp, a = ("s.org_id=?", [oid]) if oid else ("s.org_id IS NULL AND s.owner_id=?", [uid])
    rows = c.execute(f"""SELECT f.id, f.sheet_id, f.name, f.mime, f.size, f.created_at, s.title FROM sheet_files f
                         JOIN sheets s ON s.id=f.sheet_id WHERE f.deleted_at IS NULL AND s.deleted_at IS NULL AND {sp}
                         ORDER BY s.title, f.name, f.id LIMIT {_cap(limit)}""", a).fetchall()
    ok, out, n = {}, {}, 0
    for r in rows:
        if r["sheet_id"] not in ok:
            try:
                sh_need(c, r["sheet_id"])  # like opening the file (shkinds.shk_file_get)
                ok[r["sheet_id"]] = True
            except Denied:
                ok[r["sheet_id"]] = False
        if not ok[r["sheet_id"]]:
            continue
        url = f"/api/sheets/{int(r['sheet_id'])}/files/{int(r['id'])}"
        g = out.setdefault(r["sheet_id"], (r["title"] or tr("Untitled table"), f"sheets/{r['sheet_id']}", []))
        g[2].append(_item("sheet", r["id"], r["name"], r["mime"], r["size"], r["created_at"], url, url + "?dl=1"))
        n += 1
        if n >= limit:
            break
    return sorted(out.values(), key=lambda g: g[0].lower())


def _fs(c, uid, oid, key, limit):
    """[(title, None, items)] -- the files lying in the folders of the space's roots of key that uid may see, per folder."""
    ws = fs_area_ws(oid, uid)
    with system_ctx(c):  # the area roots of the space (the server's own table; reading the ids grants nothing)
        roots = [r[0] for r in c.execute("SELECT node_id, area FROM fs_area_roots WHERE ws=? AND node_id IS NOT NULL", (ws,))
                 if fsv_key(r[1]) == key]
    if not roots:
        return []
    q = ",".join(str(int(x)) for x in roots)
    tree = c.execute(f"""WITH RECURSIVE t(id, depth) AS (SELECT id, 0 FROM fs_nodes WHERE id IN ({q}) AND deleted_at IS NULL
                           UNION ALL SELECT n.id, t.depth + 1 FROM fs_nodes n JOIN t ON n.parent_id=t.id
                           WHERE n.deleted_at IS NULL AND t.depth < 32)
                         SELECT n.* FROM fs_nodes n JOIN t ON t.id=n.id WHERE n.kind IN ('folder', 'file') ORDER BY t.depth, n.id
                         LIMIT 5000""").fetchall()
    folders = {r["id"]: r for r in tree if r["kind"] == "folder"}

    def path(fid):
        out, guard = [], 0
        while fid in folders and guard < 64:
            out.insert(0, folders[fid]["name"])
            fid, guard = folders[fid]["parent_id"], guard + 1
        return " / ".join(out)
    out, n = {}, 0
    for r in tree:
        if r["kind"] != "file" or not fs_role(c, r["id"], uid):
            continue
        url = f"/api/files/nodes/{int(r['id'])}/content"
        g = out.setdefault(r["parent_id"], (path(r["parent_id"]), None, []))
        g[2].append(_item("fs", r["id"], r["name"], r["mime"], r["size"], r["created_at"], url, url + "?dl=1"))
        n += 1
        if n >= limit:
            break
    return sorted(out.values(), key=lambda g: g[0].lower())


FSV_GATE = {"wiki": "wiki", "sheets": "sheets", "office": "office", "contacts": "contacts"}  # key -> module / area switch


def _key_on(c, uid, oid, key):
    """Is the area of key on for uid in space oid: the person's module (settings features) and, in an organisation, not
    switched off by its admins (accounts/wsareas.py) -- an area that is off shows no collection."""
    a = FSV_GATE.get(key)
    if not a:
        return True
    if a not in (usettings(c, uid).get("features") or "").split(","):
        return False
    return a not in wsa_org_off(c, oid)


def _unlocked(c, groups):
    """Review: no file of a locked folder (fslock: names and contents encrypted in the browser) in a collection."""
    from .fslock import fsl_map
    ids = [x["id"] for g in groups for x in g[2] if x["kind"] == "fs"]
    lk = fsl_map(c, ids) if ids else {}
    if not lk:
        return groups
    return [(g[0], g[1], [x for x in g[2] if not (x["kind"] == "fs" and x["id"] in lk)]) for g in groups]


def fsv_groups(c, uid, oid, key, limit=FSV_MAX):
    """The groups of collection key in space oid (None: private) for uid, at most limit files."""
    from .fsreceipts import RCX_KEYS, rcx_groups  # 2.1148.0 (#4895): loaded after the office / budget / documents (ORDER)
    if key in RCX_KEYS:  # "Receipts": references to the receipts of the office, the meals and the budget (files/fsreceipts.py)
        return rcx_groups(c, uid, oid, key, limit)
    groups = []
    if not _key_on(c, uid, oid, key):
        return groups
    if key == "wiki":
        groups += _wiki(c, uid, oid, limit)
    elif key == "lists":
        groups += _lists(c, uid, oid, limit)
    elif key == "sheets":
        groups += _sheets(c, uid, oid, limit)
    left = limit - sum(len(g[2]) for g in groups)
    if left > 0:
        groups += _unlocked(c, _fs(c, uid, oid, key, left))
    for g in groups:
        g[2].sort(key=lambda x: x["name"].lower())
    return groups


def fsv_collections(c, uid, oid):
    """[{key, name}] of the space's collections that hold something for uid (the top of the space lists them; each asks for
    one file only)."""
    if not _person():
        return []
    from .fsreceipts import rcx_collection  # 2.1148.0 (#4895)
    rc = rcx_collection(c, uid, oid)  # "Receipts" last, below the tree: {key, name, subs} (only the parts with something)
    return [{"key": k, "name": tr(FSV_KEYS[k])} for k in FSV_ORDER if fsv_groups(c, uid, oid, k, limit=1)] + ([rc] if rc else [])


@app.get("/api/files/collections/<key>")
def files_collection(key):
    """One collection "From <area>" of a space (module docstring): read-only, grouped by object."""
    from .fsreceipts import RCX_KEYS  # 2.1148.0 (#4895): + "Receipts" and its parts
    if key not in FSV_KEYS and key not in RCX_KEYS:
        raise Denied(404)
    c = db()
    uid = me()
    if not _person():
        raise Denied(404)
    oid = _space(c, uid, request.args.get("space"))
    if oid:
        wsa_org_check(c, oid, "ablage")  # the file store switched off by the organisation's admins (like its other views)
    groups = fsv_groups(c, uid, oid, key, limit=FSV_MAX + 1)
    total, cut = 0, False
    for g in groups:
        if total + len(g[2]) > FSV_MAX:
            del g[2][FSV_MAX - total:]
            cut = True
        total += len(g[2])
    return jsonify(key=key, name=tr(FSV_KEYS.get(key) or RCX_KEYS[key]), space=f"org:{oid}" if oid else "private", more=cut,
                   groups=[{"title": g[0], "open": g[1], "items": g[2]} for g in groups if g[2]])
