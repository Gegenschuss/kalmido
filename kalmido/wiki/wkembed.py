"""2.123.0 C (#2103, #2107): files of the file store ("Ablage") and tables in knowledge pages -- by reference, never a copy.

A page shows a file of the Ablage as ![label](/api/files/nodes/<id>/content) (a picture) or [label](/api/files/nodes/<id>/content)
(a file to open) and links a file or a table as [[datei:<path or id>]] / [[tabelle:<name or id>]] (an optional |label). The
content always comes through the Ablage's own routes (files/web.py: its rights, the virus lock, sealed at rest); this module
only says, for one viewer, which of the referenced objects they may see -- POST /api/wiki/pages/<id>/refs answers names and
types of the visible ones only, the rest stays a placeholder ("File not available") or plain text without any name.
Same space only: a page of an organisation references that organisation's Ablage / tables, a private page the owner's own
private ones (a file shared with the owner by someone else is not offered). After a move to another workspace (wkmove.py) the
references into the old space stay as text and show as unavailable.
wiki_links keeps the resolved references (to_file / to_sheet, rebuilt on every save by pages.wiki_set_links) for the
backlinks: GET /api/wiki/refs?file=<id> | sheet=<id> = the pages one may read that reference it. A space with the lock keeps no
links on the server (the browser asks /refs with the ids it finds in the decrypted text).
wem_visible(c, uid, node_id) is the one check for a viewer (uid None = not signed in, e.g. a guest link: never).
"""
import re

from flask import jsonify, request

from ..core.config import app
from ..core.db import body, db
from ..core.i18n import tr
from ..core.access import Denied
from ..accounts.session import me
from ..personal.timetrack import BadInput

WEM_EMBED_RE = re.compile(r"/api/files/nodes/(\d{1,15})/content\b")
WEM_LINK_RE = re.compile(r"\[\[\s*(datei|tabelle)\s*:\s*([^\[\]|#\n]{1,250}?)\s*(?:\|[^\[\]\n]*)?\]\]", re.I)
WEM_MAX = 200  # references per page / per question


def wem_refs_of(text):
    """(node ids embedded, [(kind 'datei' | 'tabelle', the reference as written)]) of a page text."""
    t = text or ""
    ids = sorted({int(m.group(1)) for m in WEM_EMBED_RE.finditer(t) if int(m.group(1)) < 2 ** 62})
    links, seen = [], set()
    for m in WEM_LINK_RE.finditer(t):
        k = (m.group(1).lower(), m.group(2).strip())
        if k[1] and k not in seen:
            seen.add(k)
            links.append(k)
    return ids[:WEM_MAX], links[:WEM_MAX]


def wem_same_space(row, page):
    """Does an Ablage node / a table row lie in the space of the page (organisation, or the page owner's private one)?"""
    if page["org_id"]:
        return row["org_id"] == page["org_id"]
    return row["org_id"] is None and row["owner_id"] == page["owner_id"]


def wem_visible(c, uid, node_id, page=None):
    """May account uid see the Ablage file node_id (a file, not in the trash, its Ablage rights)? page: also in the page's space.
    uid None (a guest / public link, nobody signed in) -> False."""
    from ..files.store import fs_chain, fs_deleted, fs_role
    if not uid or not isinstance(node_id, int) or not 0 < node_id < 2 ** 62:
        return False
    chain = fs_chain(c, node_id)
    if not chain or fs_deleted(chain) or chain[0]["kind"] != "file":
        return False
    if page is not None and not wem_same_space(chain[0], page):
        return False
    return bool(fs_role(c, node_id, uid, chain=chain))


def wem_sheet_ok(c, uid, sid, page):
    from ..sheets.core import sh_may
    if not uid or not isinstance(sid, int) or not 0 < sid < 2 ** 62:
        return None
    from ..sheets.shbook import shb_deleted
    r = c.execute("SELECT * FROM sheets WHERE id=? AND deleted_at IS NULL", (sid,)).fetchone()
    if r and shb_deleted(c, r):  # 2.124.0 (#2116): a further sheet of a table in the trash
        return None
    return r if r and wem_same_space(r, page) and sh_may(c, uid, r) else None


def wem_find_file(c, page, ref):
    """The node id a [[datei:…]] reference names in the page's space: an id, or a path of folder names from the top (case
    does not matter); None when there is none. No rights check (the caller checks the viewer)."""
    ref = ref.strip().strip("/")
    if ref.isdigit():
        r = c.execute("SELECT id, org_id, owner_id FROM fs_nodes WHERE id=?", (int(ref),)).fetchone() if len(ref) < 16 else None
        return r["id"] if r and wem_same_space(r, page) else None
    parts = [p.strip() for p in ref.split("/") if p.strip()]
    if not parts or len(parts) > 32:
        return None
    if page["org_id"]:
        w, a = "parent_id IS NULL AND org_id=?", [page["org_id"]]
    else:
        w, a = "parent_id IS NULL AND org_id IS NULL AND owner_id=?", [page["owner_id"]]
    nid = None
    for i, p in enumerate(parts):
        kind = "file" if i == len(parts) - 1 else "folder"
        r = c.execute(f"SELECT id FROM fs_nodes WHERE {w} AND deleted_at IS NULL AND lower(name)=? AND kind=? ORDER BY id LIMIT 1",
                      [*a, p.lower(), kind]).fetchone()
        if not r:
            return None
        nid = r["id"]
        w, a = "parent_id=?", [nid]
    return nid


def wem_find_sheet(c, page, ref):
    """The table id a [[tabelle:…]] reference names in the page's space (an id or the title, case does not matter)."""
    ref = ref.strip()
    w, a = ("org_id=?", [page["org_id"]]) if page["org_id"] else ("org_id IS NULL AND owner_id=?", [page["owner_id"]])
    if ref.isdigit() and len(ref) < 16:
        r = c.execute(f"SELECT id FROM sheets WHERE id=? AND deleted_at IS NULL AND {w}", [int(ref), *a]).fetchone()
    else:
        r = c.execute(f"SELECT id FROM sheets WHERE lower(title)=? AND deleted_at IS NULL AND book_id IS NULL AND {w} ORDER BY id LIMIT 1", [ref.lower(), *a]).fetchone()
    return r["id"] if r else None


def wem_set_links(c, pid, text):
    """The to_file / to_sheet rows of a page (called by pages.wiki_set_links after it removed the old rows)."""
    if (text or "").startswith("e2e1:"):  # a locked space keeps no links on the server
        return
    ids, links = wem_refs_of(text)
    if not ids and not links:
        return
    page = c.execute("SELECT id, org_id, owner_id FROM wiki_pages WHERE id=?", (pid,)).fetchone()
    if not page:
        return
    files, sheets = set(), set()
    for nid in ids:
        r = c.execute("SELECT id, org_id, owner_id FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        if r and wem_same_space(r, page):
            files.add(nid)
    for kind, ref in links:
        x = wem_find_file(c, page, ref) if kind == "datei" else wem_find_sheet(c, page, ref)
        if x:
            (files if kind == "datei" else sheets).add(x)
    for f in sorted(files):
        c.execute("INSERT INTO wiki_links(from_id,to_file) VALUES(?,?)", (pid, f))
    for s in sorted(sheets):
        c.execute("INSERT INTO wiki_links(from_id,to_sheet) VALUES(?,?)", (pid, s))


def wem_file_dict(c, nid):
    r = c.execute("SELECT id, name, mime, size FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    return {"kind": "file", "id": r["id"], "name": r["name"], "mime": r["mime"] or "", "size": r["size"],
            "image": (r["mime"] or "").startswith("image/"), "url": f"/api/files/nodes/{r['id']}/content"}


def wem_list(v, what, item):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > WEM_MAX or not all(item(x) for x in v):
        raise BadInput(tr("Invalid value: {0}", what))
    return v


@app.post("/api/wiki/pages/<int:pid>/refs")
def wem_refs(pid):
    """{files: [node id …], links: ["datei:<path or id>" | "tabelle:<name or id>" …]} -- what of it the signed-in person may
    see from this page (they need to read the page): {files: {id: {name, mime, size, image, url}}, links: {"<kind>:<ref in
    lower case>": {kind file | sheet, id, name, url, image?}}}. Not visible / not there / another space = left out (no name).
    Read-only; POST only because the browser sends what it found in the text (a locked space: the decrypted text)."""
    from .pages import wiki_need
    c = db()
    page = wiki_need(c, pid)
    uid = me()
    b = body()
    ids = wem_list(b.get("files"), "files", lambda x: isinstance(x, int) and not isinstance(x, bool))
    links = wem_list(b.get("links"), "links", lambda x: isinstance(x, str) and 0 < len(x) <= 260)
    files, out = {}, {}
    for nid in ids:
        if wem_visible(c, uid, nid, page):
            files[str(nid)] = wem_file_dict(c, nid)
    for s in links:
        kind, _, ref = s.partition(":")
        kind = kind.strip().lower()
        if kind not in ("datei", "tabelle") or not ref.strip():
            continue
        key = f"{kind}:{ref.strip().lower()}"
        if kind == "datei":
            nid = wem_find_file(c, page, ref)
            if nid and wem_visible(c, uid, nid, page):
                out[key] = wem_file_dict(c, nid)
        else:
            sid = wem_find_sheet(c, page, ref)
            r = wem_sheet_ok(c, uid, sid, page) if sid else None
            if r:
                out[key] = {"kind": "sheet", "id": r["id"], "name": r["title"] or tr("Untitled table"), "url": f"#sheets/{r['id']}"}
    return jsonify(files=files, links=out)


@app.get("/api/wiki/refs")
def wem_backlinks():
    """?file=<node id> | ?sheet=<table id> -- the knowledge pages one may read (spaces without the lock) that show or link it;
    404 when one may not see the file / table itself."""
    from ..accounts.orgs import user_orgs
    from .wikie2e import wke_open_sql
    c = db()
    uid = me()
    fid, sid = request.args.get("file", type=int), request.args.get("sheet", type=int)
    if fid:
        if not wem_visible(c, uid, fid):
            raise Denied(404)
        col, oid = "to_file", fid
    elif sid:
        from ..sheets.core import sh_need
        sh_need(c, sid)
        col, oid = "to_sheet", sid
    else:
        raise BadInput(tr("Invalid value: {0}", "file"))
    from ..accounts.orgroles import user_orgs_full
    orgs = [o for o in user_orgs(c, uid) if o in user_orgs_full(c, uid)]  # 2.143.0 A (#2151)
    rows = c.execute(f"SELECT DISTINCT p.id, p.org_id, p.path FROM wiki_links k JOIN wiki_pages p ON p.id=k.from_id WHERE k.{col}=? "
                     f"AND {wke_open_sql('p')} AND p.deleted_at IS NULL AND ((p.org_id IS NULL AND p.owner_id=?)"
                     + (f" OR p.org_id IN ({','.join(str(int(x)) for x in orgs)})" if orgs else "") + ") ORDER BY p.path LIMIT 50",
                     (oid, uid)).fetchall()
    from .pages import wiki_space_key
    return jsonify(pages=[{"id": r["id"], "path": r["path"], "space": wiki_space_key(r["org_id"])} for r in rows])


def wem_purged(c, nid):
    """A file removed for good (files/store.fs_purge): its backlink rows go with it."""
    c.execute("DELETE FROM wiki_links WHERE to_file=?", (nid,))


def _wem_hook():
    from ..files.store import fs_on_delete
    if wem_purged not in fs_on_delete:
        fs_on_delete.append(wem_purged)


_wem_hook()
