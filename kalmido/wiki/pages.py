"""2.49.0 (#1199): knowledge pages -- a small wiki per organisation.

A page = Markdown with a path as its name ("Processes/Shoot day/Checklist"; the folders come from the paths). It lives in
a space: an organisation (org_id; every member reads and writes it, like the organisation's lists) or the private space
of one person (org_id NULL, owner_id; nobody else sees it). [[Path]] links another page of the same space, #123 a task
(the app shows it only to whoever may see the task: the server never answers a task's title from here). The frontmatter
(a leading "---" block of "key: value" lines) is kept in the text and cached as attrs. Pages under "Templates/" are the
templates of "New page". Export / import: a ZIP of .md files in folders (compatible with SilverBullet); 2.99.0 A (#2182):
with the pages' PDFs and pictures (wikiatt.py).
Nothing here is tied to the wiki view: a page is found by its id and space alone (a file tree can show it later).
Agents have no access yet (no v1 routes): the session routes are for people only (session.py refuses agents).
"""
import json
import re
import unicodedata

from flask import jsonify, request

from ..core.config import app
from ..core.pg import IntegrityError, insert_id
from ..core.i18n import tr
from ..core.db import body, bump, db, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied, task_visible
from ..collab.comments import user_names
from ..personal.timetrack import BadInput

WIKI_PATH_MAX, WIKI_BODY_MAX, WIKI_DEPTH = 200, 500_000, 12
WIKI_ZIP_FILES, WIKI_ZIP_FILE_MAX, WIKI_ZIP_TOTAL = 2000, 1_000_000, 30_000_000
WIKI_TEMPLATES = ("templates/", "vorlagen/")  # lower case; "Templates/…" (SilverBullet) and the German folder name
WIKI_LINK_RE = re.compile(r"\[\[([^\[\]|#\n]{1,250})(?:#[^\[\]|\n]*)?(?:\|[^\[\]\n]*)?\]\]")
WIKI_TASK_RE = re.compile(r"(?<![\w&/#])#(\d{1,12})\b")
WIKI_BAD_CHARS = re.compile(r"[\x00-\x1f\x7f\[\]|#^\\]")


def wiki_clean_path(v):
    """The cleaned path of a page (folders by "/"), or BadInput. No "." / ".." parts, no empty parts, no link characters."""
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "path"))
    v = unicodedata.normalize("NFC", v).strip()
    if v.lower().endswith(".md"):
        v = v[:-3]
    parts = [re.sub(r"\s+", " ", WIKI_BAD_CHARS.sub("", p)).strip() for p in v.replace("\\", "/").split("/")]
    parts = [p for p in parts if p]
    if not parts or any(p in (".", "..") or p.startswith(".") for p in parts):
        raise BadInput(tr("Please give the page a name"))
    if len(parts) > WIKI_DEPTH:
        raise BadInput(tr("Too many folder levels (at most {0})", WIKI_DEPTH))
    out = "/".join(parts)
    if out.lower().startswith("e2e1:"):  # 2.64.3 (#1817, review M1): the prefix of browser ciphertexts is never a plain name
        raise BadInput(tr("Invalid value: {0}", "path"))
    if len(out) > WIKI_PATH_MAX:
        raise BadInput(tr("The name is too long (at most {0} characters)", WIKI_PATH_MAX))
    return out


def wiki_frontmatter(text):
    """{key: value} of a leading "---" block (simple YAML: scalars and [a, b] lists; anything else stays text)."""
    m = re.match(r"\A---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)", text or "", re.S)
    out = {}
    if not m:
        return out
    for ln in m.group(1).splitlines()[:50]:
        mm = re.match(r"^([A-Za-z0-9_][\w .-]{0,40}):\s*(.*)$", ln)
        if not mm:
            continue
        k, v = mm.group(1).strip(), mm.group(2).strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
            v = v[1:-1]
        elif v.startswith("[") and v.endswith("]"):
            v = [x.strip().strip("\"'") for x in v[1:-1].split(",") if x.strip()][:30]
        out[k] = v if isinstance(v, list) else v[:300]
    return out


def wiki_links_of(text):
    """(paths in lower case, task ids) the text links to."""
    paths = {wiki_link_key(m.group(1)) for m in WIKI_LINK_RE.finditer(text or "")}
    tasks = {int(m.group(1)) for m in WIKI_TASK_RE.finditer(text or "") if int(m.group(1)) < 2 ** 62}
    return sorted(p for p in paths if p), sorted(tasks)


def wiki_link_key(p):
    try:
        return wiki_clean_path(p).lower()
    except BadInput:
        return ""


def wiki_space(c, uid, v, write=False):
    """org id (None = private) of a space value "private" | "org:<id>" | <id>; 404 for an organisation the person is not in."""
    from ..accounts.orgs import user_orgs
    if v in (None, "", "private", 0, "0"):
        return None
    if isinstance(v, str) and v.startswith("org:"):
        v = v[4:]
    try:
        oid = int(v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "space"))
    if oid not in user_orgs(c, uid):
        raise Denied(404)
    return oid  # every member writes (org roles: member | admin); a read-only role would be checked here (write)


def wiki_space_key(oid):
    return f"org:{oid}" if oid else "private"


def wiki_may_read(c, uid, r):
    if r["org_id"] is None:
        return r["owner_id"] == uid
    from ..accounts.orgs import user_orgs
    return r["org_id"] in user_orgs(c, uid)


def wiki_need(c, pid, write=False, deleted=False):
    r = c.execute("SELECT * FROM wiki_pages WHERE id=?", (pid,)).fetchone()
    if not r or (bool(r["deleted_at"]) != deleted) or not wiki_may_read(c, me(), r):
        raise Denied(404)
    return r


def wiki_space_sql(oid, uid):
    return ("org_id=?", [oid]) if oid else ("org_id IS NULL AND owner_id=?", [uid])


def wiki_dict(r, full=True, names=None):
    try:
        attrs = json.loads(r["attrs"] or "{}")
    except ValueError:
        attrs = {}
    d = {"id": r["id"], "space": wiki_space_key(r["org_id"]), "org_id": r["org_id"], "path": r["path"], "attrs": attrs,
         "created_by": r["created_by"], "updated_by": r["updated_by"], "created_at": r["created_at"], "updated_at": r["updated_at"],
         "template": r["path"].lower().startswith(WIKI_TEMPLATES)}
    if r["path"].startswith("e2e1:"):  # 2.64.3 A (#1817): a page of a locked space -- the browser reads both from the plain text
        d["attrs"], d["template"] = {}, False
    if full:
        d["body"] = r["body"]
    if names is not None:
        d["updated_by_name"] = names.get(r["updated_by"], "")
    return d


def wiki_set_links(c, pid, text):
    paths, tasks = wiki_links_of(text)
    c.execute("DELETE FROM wiki_links WHERE from_id=?", (pid,))
    if (text or "").startswith("e2e1:"):  # 2.64.3 A (#1817): a locked space keeps no links on the server
        return
    for p in paths[:500]:
        c.execute("INSERT INTO wiki_links(from_id,to_path) VALUES(?,?)", (pid, p))
    for t in tasks[:500]:
        c.execute("INSERT INTO wiki_links(from_id,to_task) VALUES(?,?)", (pid, t))


def wiki_body(b):
    v = b.get("body", "")
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "body"))
    if len(v) > WIKI_BODY_MAX:
        raise BadInput(tr("The page is too long (at most {0} characters)", WIKI_BODY_MAX))
    return v


def wiki_insert(c, oid, uid, path, text, ts):
    """A new page; None when the path is taken in that space."""
    try:
        with c.savepoint():
            pid = insert_id(c, "INSERT INTO wiki_pages(org_id,owner_id,path,body,attrs,created_by,updated_by,created_at,updated_at) "
                               "VALUES(?,?,?,?,?,?,?,?,?)",
                            (oid, None if oid else uid, path, text, json.dumps(wiki_frontmatter(text), ensure_ascii=False), uid, uid, ts, ts))
    except IntegrityError:
        return None
    wiki_set_links(c, pid, text)
    return pid


def wiki_taken():
    return jsonify(error=tr("A page with this name already exists")), 409


@app.get("/api/wiki")
def wiki_index():
    """?space=private|org:<id> -- every page of the space without its text (the tree, link suggestions, templates)."""
    c = db()
    uid = me()
    oid = wiki_space(c, uid, request.args.get("space"))
    w, a = wiki_space_sql(oid, uid)
    rows = c.execute(f"SELECT id, org_id, owner_id, path, attrs, created_by, updated_by, created_at, updated_at FROM wiki_pages "
                     f"WHERE deleted_at IS NULL AND {w} ORDER BY lower(path) LIMIT 5000", a).fetchall()
    names = user_names(c, {r["updated_by"] for r in rows})
    from .wikie2e import wke_index_info  # 2.64.3 A (#1817): the lock of the space; bodies=1 = the ciphertexts for the local search
    e2e = wke_index_info(c, oid, uid)
    pages = [wiki_dict(r, full=False, names=names) for r in rows]
    if e2e and request.args.get("bodies") == "1":
        bodies = {r["id"]: r["body"] for r in c.execute(f"SELECT id, body FROM wiki_pages WHERE deleted_at IS NULL AND {w}", a)}
        for d in pages:
            d["body"] = bodies.get(d["id"], "")
    return jsonify(space=wiki_space_key(oid), may_write=True, pages=pages, e2e=e2e)


@app.get("/api/wiki/pages/<int:pid>")
def wiki_get(pid):
    """A page with its text and its backlinks (pages of the same space that link to it)."""
    c = db()
    r = wiki_need(c, pid)
    uid = me()
    w, a = wiki_space_sql(r["org_id"], uid)
    back = c.execute(f"SELECT DISTINCT p.id, p.path FROM wiki_links k JOIN wiki_pages p ON p.id=k.from_id WHERE k.to_path=? "
                     f"AND p.deleted_at IS NULL AND p.id!=? AND p.{w.replace(' AND ', ' AND p.')} ORDER BY p.path LIMIT 200",
                     [r["path"].lower(), pid, *a]).fetchall()
    d = wiki_dict(r, names=user_names(c, [r["updated_by"]]))
    from .wikie2e import wke_page_mode  # 2.64.3 A (#1817): a locked space finds its backlinks in the browser
    d["backlinks"] = [] if wke_page_mode(c, r) else [{"id": x["id"], "path": x["path"]} for x in back]
    from .wkmove import wkm_last  # 2.96.0 B (#1941): the last move between workspaces (both sides see it)
    d["moved"] = wkm_last(c, pid)
    from .wikiatt import wka_list
    d["files"] = wka_list(c, r)  # 2.99.0 A (#2182): the page's PDFs and pictures
    return jsonify(d)


@app.post("/api/wiki/pages")
def wiki_create():
    """{space, path, body?, template_id? (a page whose text the new one starts with)} -- 409 when the name is taken."""
    c = db()
    uid = me()
    b = body()
    oid = wiki_space(c, uid, b.get("space"), write=True)
    from .wikie2e import wke_guard  # 2.64.3 A (#1817): a locked space takes ciphertexts only (no template copy on the server)
    if wke_guard(c, oid, uid, b.get("path"), b.get("body", ""), "create", template=bool(b.get("template_id"))):
        path, text = b.get("path"), b.get("body", "")
    else:
        path = wiki_clean_path(b.get("path"))
        text = wiki_body(b)
    if b.get("template_id") and not text:
        t = wiki_need(c, int(b["template_id"]))
        text = t["body"]
        if text.startswith("e2e1:"):  # 2.64.3 (#1817, review M1): a template of an encrypted space opens only in the browser
            raise BadInput(tr("Invalid value: {0}", "template_id"))
    pid = wiki_insert(c, oid, uid, path, text, iso_ms(now_utc()))
    if pid is None:
        return wiki_taken()
    bump(c)
    c.commit()
    return jsonify(wiki_dict(wiki_need(c, pid))), 201


def wiki_relink(c, r, old, new, uid, ts):
    """[[old]] -> [[new]] in the other pages of the space (also [[old|label]] and [[old#part]]); the number of pages changed."""
    w, a = wiki_space_sql(r["org_id"], uid)
    rx = re.compile(r"\[\[\s*" + re.escape(old) + r"\s*(?=[\]|#])", re.I)
    n = 0
    for p in c.execute(f"SELECT DISTINCT p.id, p.body FROM wiki_links k JOIN wiki_pages p ON p.id=k.from_id WHERE k.to_path=? "
                       f"AND p.deleted_at IS NULL AND p.{w.replace(' AND ', ' AND p.')}", [old.lower(), *a]).fetchall():
        nb = rx.sub(lambda m: "[[" + new, p["body"])
        if nb != p["body"]:
            c.execute("UPDATE wiki_pages SET body=?, updated_by=?, updated_at=? WHERE id=?", (nb, uid, ts, p["id"]))
            wiki_set_links(c, p["id"], nb)
            n += 1
    return n


@app.patch("/api/wiki/pages/<int:pid>")
def wiki_update(pid):
    """{path?, body?, expect_updated_at? (409 with the current page when someone else saved in between), relink? (default
    true: a new name changes the [[links]] to it in the space)}"""
    c = db()
    r = wiki_need(c, pid, write=True)
    uid = me()
    wiki_space(c, uid, r["org_id"], write=True)
    b = body()
    exp = b.get("expect_updated_at")
    if exp and exp != r["updated_at"] and ("body" in b or "path" in b):
        cur = wiki_dict(r, names=user_names(c, [r["updated_by"]]))
        return jsonify(error=tr("Changed in the meantime by {0}", cur.get("updated_by_name") or "?"), page=cur), 409
    f, ts, n = {}, iso_ms(now_utc()), 0
    from .wikie2e import wke_guard  # 2.64.3 A (#1817): a locked space takes ciphertexts only, its links stay in the browser
    locked = wke_guard(c, r["org_id"], r["owner_id"], b.get("path"), b.get("body"), "update")
    if "body" in b:
        f["body"] = b["body"] if locked else wiki_body(b)
        f["attrs"] = "{}" if locked else json.dumps(wiki_frontmatter(f["body"]), ensure_ascii=False)
    if "path" in b:
        path = b["path"] if locked else wiki_clean_path(b["path"])
        if path != r["path"]:
            f["path"] = path
    if f:
        f["updated_by"], f["updated_at"] = uid, ts
        try:
            with c.savepoint():
                c.execute(f"UPDATE wiki_pages SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), pid])
        except IntegrityError:
            return wiki_taken()
        if "body" in f:
            wiki_set_links(c, pid, f["body"])
        if "path" in f and b.get("relink", True) is not False and not locked:
            n = wiki_relink(c, r, r["path"], f["path"], uid, ts)
        bump(c)
        c.commit()
    d = wiki_dict(wiki_need(c, pid), names=user_names(c, [uid]))
    d["relinked"] = n
    return jsonify(d)


@app.post("/api/wiki/move")
def wiki_move():
    """{space, from, to} -- renames a folder: every page at or under "from" moves under "to" (the links to them follow).
    409 with the names that are taken; one transaction."""
    c = db()
    uid = me()
    b = body()
    oid = wiki_space(c, uid, b.get("space"), write=True)
    from .wikie2e import wke_guard  # 2.64.3 A (#1817): in a locked space the browser renames page by page
    wke_guard(c, oid, uid, kind="move")
    src, dst = wiki_clean_path(b.get("from")), wiki_clean_path(b.get("to"))
    if dst.lower() == src.lower() or dst.lower().startswith(src.lower() + "/"):
        raise BadInput(tr("Invalid value: {0}", "to"))
    w, a = wiki_space_sql(oid, uid)
    rows = c.execute(f"SELECT * FROM wiki_pages WHERE deleted_at IS NULL AND {w} AND (lower(path)=? OR lower(path) ILIKE ? ESCAPE '\\')",
                     [*a, src.lower(), src.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "/%"]).fetchall()
    if not rows:
        raise Denied(404)
    moves = [(r, wiki_clean_path(dst + r["path"][len(src):])) for r in rows]
    mine = {r["id"] for r in rows}
    taken = [n for _, n in moves if (x := c.execute(f"SELECT id FROM wiki_pages WHERE deleted_at IS NULL AND {w} AND lower(path)=?", [*a, n.lower()]).fetchone()) and x["id"] not in mine]
    if taken:
        return jsonify(error=tr("A page with this name already exists"), taken=taken[:20]), 409
    ts, n = iso_ms(now_utc()), 0
    for r, new in moves:  # first to a free name, then to the target (pages of the folder may swap names among themselves)
        c.execute("UPDATE wiki_pages SET path=? WHERE id=?", (f".moving/{r['id']}", r["id"]))
    for r, new in moves:
        c.execute("UPDATE wiki_pages SET path=?, updated_by=?, updated_at=? WHERE id=?", (new, uid, ts, r["id"]))
    for r, new in moves:
        n += wiki_relink(c, r, r["path"], new, uid, ts)
    bump(c)
    c.commit()
    return jsonify(ok=True, moved=[{"id": r["id"], "from": r["path"], "to": new} for r, new in moves], relinked=n)


@app.delete("/api/wiki/pages/<int:pid>")
def wiki_delete(pid):
    """To the trash (the app's Undo brings it back: POST /api/wiki/restore)."""
    c = db()
    r = wiki_need(c, pid, write=True)
    wiki_space(c, me(), r["org_id"], write=True)
    c.execute("UPDATE wiki_pages SET deleted_at=? WHERE id=?", (iso_ms(now_utc()), pid))
    bump(c)
    c.commit()
    return jsonify(ok=True, page=wiki_dict(r, full=False))


@app.post("/api/wiki/trash")
def wiki_trash_many():
    """{ids, files?} -- several pages (and page files, 2.99.0 A #2182) to the trash (Undo of an import); what one may not
    change is left out."""
    return wiki_bulk(True)


@app.post("/api/wiki/restore")
def wiki_restore_many():
    """{ids, files?} -- back from the trash; a page whose name was taken in the meantime stays there (skipped)."""
    return wiki_bulk(False)


def wiki_bulk(trash):
    c = db()
    uid = me()
    b = body()
    ids, fids = b.get("ids"), b.get("files", [])
    if not isinstance(ids, list) or len(ids) > WIKI_ZIP_FILES or any(isinstance(x, bool) or not isinstance(x, int) for x in ids):
        raise BadInput(tr("Invalid value: {0}", "ids"))
    if not isinstance(fids, list) or len(fids) > WIKI_ZIP_FILES or any(isinstance(x, bool) or not isinstance(x, int) for x in fids):
        raise BadInput(tr("Invalid value: {0}", "files"))
    done, skipped, ts = [], [], iso_ms(now_utc())
    from .wikiatt import wka_bulk  # 2.99.0 A (#2182): files to the trash before their pages, back after them
    fdone, fskip = wka_bulk(c, uid, fids, True) if trash else ([], [])
    for pid in ids:
        try:
            r = wiki_need(c, pid, write=True, deleted=not trash)
            wiki_space(c, uid, r["org_id"], write=True)
        except Denied:
            skipped.append(pid)
            continue
        try:
            with c.savepoint():
                c.execute("UPDATE wiki_pages SET deleted_at=? WHERE id=?", (ts if trash else None, pid))
            done.append(pid)
        except IntegrityError:
            skipped.append(pid)
    if not trash:
        fdone, fskip = wka_bulk(c, uid, fids, False)
    if done or fdone:
        bump(c)
        c.commit()
    return jsonify(ok=True, ids=done, skipped=skipped, files=fdone, files_skipped=fskip)


@app.get("/api/wiki/search")
def wiki_search():
    """?q=words -- pages of every space one may read whose name (or text) has all words; without their text."""
    from ..accounts.orgs import user_orgs
    c = db()
    uid = me()
    q = (request.args.get("q") or "").strip()[:200]
    orgs = user_orgs(c, uid)
    w = "deleted_at IS NULL AND ((org_id IS NULL AND owner_id=?)" + (f" OR org_id IN ({','.join(str(int(x)) for x in orgs)})" if orgs else "") + ")"
    from .wikie2e import wke_open_sql  # 2.64.3 A (#1817): locked spaces are searched in the browser
    w += " AND " + wke_open_sql("wiki_pages")
    a = [uid]
    for word in q.split()[:6]:
        like = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        w += " AND (path ILIKE ? ESCAPE '\\' OR body ILIKE ? ESCAPE '\\')"
        a += [like, like]
    rows = c.execute(f"SELECT id, org_id, owner_id, path, attrs, created_by, updated_by, created_at, updated_at FROM wiki_pages "
                     f"WHERE {w} ORDER BY updated_at DESC LIMIT 30", a).fetchall()
    return jsonify(pages=[wiki_dict(r, full=False) for r in rows])


@app.get("/api/wiki/mentions")
def wiki_mentions():
    """?task=<id> -- the pages one may read that mention task #id (404 when one may not see the task)."""
    from ..accounts.orgs import user_orgs
    c = db()
    uid = me()
    try:
        tid = int(request.args.get("task") or 0)
    except ValueError:
        tid = 0
    if not tid or not task_visible(c, tid, uid):
        raise Denied(404)
    orgs = user_orgs(c, uid)
    from .wikie2e import wke_open_sql  # 2.64.3 A (#1817): mentions in a locked space are found in the browser
    rows = c.execute("SELECT DISTINCT p.id, p.org_id, p.path FROM wiki_links k JOIN wiki_pages p ON p.id=k.from_id WHERE k.to_task=? "
                     f"AND {wke_open_sql('p')} AND p.deleted_at IS NULL AND ((p.org_id IS NULL AND p.owner_id=?)"
                     + (f" OR p.org_id IN ({','.join(str(int(x)) for x in orgs)})" if orgs else "") + ") ORDER BY p.path LIMIT 50",
                     (tid, uid)).fetchall()
    return jsonify(pages=[{"id": r["id"], "path": r["path"], "space": wiki_space_key(r["org_id"])} for r in rows])


@app.get("/api/wiki/export")
def wiki_export():
    """?space= -- every page of the space as a ZIP of .md files in folders (the path = folders + file name); 2.99.0 A (#2182):
    with the pages' files under _attachments/<page>/ (wikiatt.wka_export_zip)."""
    c = db()
    uid = me()
    oid = wiki_space(c, uid, request.args.get("space"))
    from .wikie2e import wke_guard  # 2.64.3 A (#1817): a locked space exports in the browser (decrypted ZIP)
    wke_guard(c, oid, uid, kind="export")
    from .wikiatt import wka_export_zip
    return wka_export_zip(c, oid, uid)


@app.post("/api/wiki/import")
def wiki_import():
    """multipart file = a ZIP of .md files (?space=, ?replace=1 overwrites pages of the same name); 2.99.0 A (#2182): with
    PDFs and pictures (wikiatt: checked by their content, attached to the page that links them, the links rewritten; the
    others on a page "Imported files" of their folder). At most WIKI_ZIP_FILES files, 1 MB per page, 25 MB per file, 500 MB
    in all; paths cleaned ("../" and absolute paths lose their dangerous parts). Answers the new page ids (Undo moves them
    to the trash), the new file ids, the skipped names (skipped) and the reasons (skipped_detail: [{name, reason}])."""
    from .wikiatt import WKA_ZIP_TOTAL, wka_import_zip
    request.max_content_length = WKA_ZIP_TOTAL + 1024 * 1024  # this route only (the app's limit is lower); + form framing
    c = db()
    uid = me()
    oid = wiki_space(c, uid, request.args.get("space"), write=True)
    from .wikie2e import wke_guard  # 2.64.3 A (#1817): a locked space imports in the browser
    wke_guard(c, oid, uid, kind="import")
    return jsonify(wka_import_zip(c, uid, oid, request.args.get("replace") == "1"))
