"""2.49.0 (#1199): knowledge pages -- a small wiki per organisation.

A page = Markdown with a path as its name ("Processes/Shoot day/Checklist"; the folders come from the paths). It lives in
a space: an organisation (org_id; every member reads and writes it, like the organisation's lists) or the private space
of one person (org_id NULL, owner_id; nobody else sees it). [[Path]] links another page of the same space, #123 a task
(the app shows it only to whoever may see the task: the server never answers a task's title from here). The frontmatter
(a leading "---" block of "key: value" lines) is kept in the text and cached as attrs. Pages under "Templates/" are the
templates of "New page". Export / import: a ZIP of .md files in folders (compatible with SilverBullet); 2.99.0 A (#2182):
with the pages' PDFs and pictures (wikiatt.py).
Nothing here is tied to the wiki view: a page is found by its id and space alone (a file tree can show it later).
The session routes are for people only (session.py refuses agents); agents and tokens reach pages through the API v1 (wkv1.py).
"""
import json
import re
import time
import unicodedata
from datetime import timedelta

from flask import jsonify, request

from ..core.config import app
from ..core.pg import IntegrityError, insert_id, system_ctx, write_lock
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, iso_ms, now_utc
from ..core.retention import ret_on, ret_report  # 2.272.0 A (#3026)
from ..accounts.session import me
from ..core.access import Denied, task_visible
from ..collab.comments import user_names
from ..core.errors import BadInput
from ..core.serializers import unlink_files  # 2.149.0 G (#2517): pulled up from functions

WIKI_PATH_MAX, WIKI_BODY_MAX, WIKI_DEPTH = 200, 500_000, 12
WIKI_ZIP_FILES, WIKI_ZIP_FILE_MAX, WIKI_ZIP_TOTAL = 2000, 1_000_000, 30_000_000
WIKI_TEMPLATES = ("templates/", "vorlagen/")  # lower case; "Templates/…" (SilverBullet) and the German folder name
# 2.123.0 C (#2107): [[datei:…]] / [[tabelle:…]] link the file store / a table (wkembed.py), not a page
WIKI_LINK_RE = re.compile(r"\[\[(?!\s*(?i:datei|tabelle)\s*:)([^\[\]|#\n]{1,250})(?:#[^\[\]|\n]*)?(?:\|[^\[\]\n]*)?\]\]")
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
    from ..accounts.orgroles import need_org_area
    need_org_area(c, uid, oid, write=bool(write))  # 2.143.0 A (#2151): guests / accounting 404, read-only only reads
    return oid


def wiki_space_key(oid):
    return f"org:{oid}" if oid else "private"


def wiki_may_read(c, uid, r):
    from .wkfolder import wkf_role  # 2.200.0 A (#2747): the space's role or a share of the page's folders
    return wkf_role(c, uid, r) is not None  # 2.143.0 A (#2151): not guests / accounting


def wiki_need(c, pid, write=False, deleted=False):
    """The page row for the signed-in person: 404 without a role; write: 'edit' on the page (2.200.0 A, #2747: the space's
    right or an edit share of its folders; read-only people get the organisation's 403)."""
    r = c.execute("SELECT * FROM wiki_pages WHERE id=?", (pid,)).fetchone()
    if not r or (bool(r["deleted_at"]) != deleted):
        raise Denied(404)
    from .wkfolder import wkf_role
    uid = me()
    role = wkf_role(c, uid, r)
    if role is None:
        raise Denied(404)
    if write and role != "edit":
        if r["org_id"]:
            from ..accounts.orgroles import need_org_write
            need_org_write(c, uid, r["org_id"])
        raise Denied(403)
    return r


def wiki_need_space(c, uid, r):
    """2.200.0 B (#2747): Denied(403) unless uid edits page row r through its space (wkf_base) -- deleting / restoring /
    moving it elsewhere stay the space's; an edit share of its folders changes only the text and the page's own name (like
    fs_ref_may_file in the file store)."""
    from .wkfolder import wkf_base
    if wkf_base(c, uid, r) != "edit":
        raise Denied(403)


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
        from .wkhist import wkh_body  # 2.123.0 A (#2105): the text is sealed at rest
        d["body"] = wkh_body(db(), r)
    if names is not None:
        d["updated_by_name"] = names.get(r["updated_by"], "")
    return d


def wiki_set_links(c, pid, text):
    paths, tasks = wiki_links_of(text)
    c.execute("DELETE FROM wiki_links WHERE from_id=?", (pid,))
    from .wkembed import wem_set_links
    wem_set_links(c, pid, text)  # 2.123.0 C (#2103, #2107): the files of the file store and the tables it shows / links
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
    from .wkhist import wkh_seal  # 2.123.0 A (#2105, #2106): the text sealed at rest, the word index
    from .wksearch import wks_index
    try:
        with c.savepoint():
            pid = insert_id(c, "INSERT INTO wiki_pages(org_id,owner_id,path,body,attrs,created_by,updated_by,created_at,updated_at) "
                               "VALUES(?,?,?,?,?,?,?,?,?)",
                            (oid, None if oid else uid, path, wkh_seal(c, oid, None if oid else uid, text),  # 2.123.0 A (#2105)
                             json.dumps(wiki_frontmatter(text), ensure_ascii=False), uid, uid, ts, ts))
    except IntegrityError:
        return None
    wiki_set_links(c, pid, text)
    wks_index(c, pid, oid, None if oid else uid, text, ts)  # 2.123.0 A (#2106)
    return pid


def wiki_taken():
    return jsonify(error=tr("A page with this name already exists")), 409


WIKI_INDEX_MAX = 5000  # pages of one space in the index (and the browser's offline copy); more = the rest stays online-only


@app.get("/api/wiki")
def wiki_index():
    """?space=private|org:<id> -- every page of the space without its text (the tree, link suggestions, templates)."""
    c = db()
    uid = me()
    oid = wiki_space(c, uid, request.args.get("space"))
    w, a = wiki_space_sql(oid, uid)
    rows = c.execute(f"SELECT id, org_id, owner_id, path, attrs, created_by, updated_by, created_at, updated_at FROM wiki_pages "
                     f"WHERE deleted_at IS NULL AND {w} ORDER BY lower(path) LIMIT {WIKI_INDEX_MAX + 1}", a).fetchall()
    more = len(rows) > WIKI_INDEX_MAX  # 2.169.1 (#2672): the index says so instead of ending silently
    rows = rows[:WIKI_INDEX_MAX]
    names = user_names(c, {r["updated_by"] for r in rows})
    from .wikie2e import wke_index_info  # 2.64.3 A (#1817): the lock of the space; bodies=1 = the ciphertexts for the local search
    e2e = wke_index_info(c, oid, uid)
    from .wkhist import wsb_body_or
    pages = [wiki_dict(r, full=False, names=names) for r in rows]
    # 2.169.0 (#2671): offline=1 = the browser keeps a copy of the space: the texts of every space (not only a locked one),
    # with since=<updated_at> only those of pages changed at or after it (the others it has; deleted ones are missing here)
    off = request.args.get("offline") == "1"
    since = str(request.args.get("since") or "")[:40] if off else ""
    if (e2e or off) and request.args.get("bodies") == "1":
        ws, wa = (f"{w} AND updated_at>=?", [*a, since]) if since else (w, a)
        bodies = {r["id"]: wsb_body_or(c, r)  # 2.123.0 A (#2105): a page not converted yet may still be sealed at rest; 2.139.0 C (#2386): unreadable = ""
                  for r in c.execute(f"SELECT id, org_id, owner_id, body FROM wiki_pages WHERE deleted_at IS NULL AND {ws} "
                                    f"ORDER BY lower(path) LIMIT {WIKI_INDEX_MAX}", wa)}  # 2.169.1 (#2672): not more texts than pages listed
        for d in pages:
            if not since or d["id"] in bodies:
                d["body"] = bodies.get(d["id"], "")
    from .wkshare import wsh_mark  # 2.123.0 B (#2104): pages a share covers get their mark
    wsh_mark(c, oid, uid, pages)
    from .wkfolder import wkf_sync, wkf_tree  # 2.200.0 A (#2747): the folders of the tree (the path <-> tree check first)
    tree = wkf_tree(c, uid, oid, wkf_sync(c, uid, oid), pages)
    c.commit()
    from ..accounts.orgroles import org_writes
    return jsonify(space=wiki_space_key(oid), may_write=org_writes(c, uid, oid), pages=pages, e2e=e2e, more=more,
                   root=tree["root"], folders=tree["folders"])  # 2.143.0 A (#2151); 2.169.1 (#2672): more


@app.get("/api/wiki/pages/<int:pid>")
def wiki_get(pid):
    """A page with its text and its backlinks (pages of the same space that link to it)."""
    c = db()
    r = wiki_need(c, pid)
    uid = me()
    from .wkfolder import wkf_base, wkf_shared, wkf_shown_path
    base = wkf_base(c, uid, r)  # 2.200.0 B (#2747): None = the page is read through a share only
    w, a = wiki_space_sql(r["org_id"], r["owner_id"] or uid)  # 2.200.0 B (#2747): the page's own space (also another person's)
    back = c.execute(f"SELECT DISTINCT p.id, p.path FROM wiki_links k JOIN wiki_pages p ON p.id=k.from_id WHERE k.to_path=? "
                     f"AND p.deleted_at IS NULL AND p.id!=? AND p.{w.replace(' AND ', ' AND p.')} ORDER BY p.path LIMIT 200",
                     [r["path"].lower(), pid, *a]).fetchall()
    d = wiki_dict(r, names=user_names(c, [r["updated_by"]]))
    from .wikie2e import wke_page_mode  # 2.64.3 A (#1817): a locked space finds its backlinks in the browser
    if base is None:  # 2.200.0 B (#2747): only pages this person may read too (never names of the others)
        info = wkf_shared(c, uid)
        back = [{"id": x["id"], "path": wkf_shown_path(c, uid, x, info)} for x in back if x["id"] in info]
        d["path"] = wkf_shown_path(c, uid, r, info)  # 2.200.0 F (#2747, review B3): nothing above the share
    d["backlinks"] = [] if wke_page_mode(c, r) else [{"id": x["id"], "path": x["path"]} for x in back]
    from .wkmove import wkm_last  # 2.96.0 B (#1941): the last move between workspaces (both sides see it)
    d["moved"] = wkm_last(c, pid) if base else None  # 2.200.0 B (#2747): not through a share
    from .wikiatt import wka_list
    d["files"] = wka_list(c, r)  # 2.99.0 A (#2182): the page's PDFs and pictures
    from .wkshare import wsh_count
    d["shares"] = wsh_count(c, r) if base else 0  # 2.123.0 B (#2104): live shares that cover the page; 2.200.0 F (B3): not through a share
    from .wkfolder import wkf_node_of, wkf_role
    n = wkf_node_of(c, pid)  # 2.200.0 A (#2747): its node in the tree, the asker's role on it
    d["node_id"], d["role"] = (n["id"] if n is not None else None), wkf_role(c, uid, r)
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
        from .wkhist import wkh_body
        t = wiki_need(c, int(b["template_id"]))
        text = wkh_body(c, t)  # 2.123.0 A (#2105)
        if text.startswith("e2e1:"):  # 2.64.3 (#1817, review M1): a template of an encrypted space opens only in the browser
            raise BadInput(tr("Invalid value: {0}", "template_id"))
    pid = wiki_insert(c, oid, uid, path, text, iso_ms(now_utc()))
    if pid is None:
        return wiki_taken()
    from .wkfolder import wkf_sync
    wkf_sync(c, uid, oid)  # 2.200.0 A (#2747): its node (and folders) in the tree
    bump(c)
    c.commit()
    return jsonify(wiki_dict(wiki_need(c, pid))), 201


def wiki_relink(c, r, old, new, uid, ts, only_edit=False):
    """[[old]] -> [[new]] in the other pages of the space (also [[old|label]] and [[old#part]]); the number of pages changed.
    only_edit (2.200.0 F, #2747 review B7: a rename through a share): only pages uid may edit, the others stay untouched."""
    from .wkhist import WikiUnreadable, wkh_open, wkh_seal  # 2.123.0 A (#2105)
    w, a = wiki_space_sql(r["org_id"], r["owner_id"] or uid)  # 2.200.0 B (#2747): the page's space (an edit share: another person's)
    rx = re.compile(r"\[\[\s*" + re.escape(old) + r"\s*(?=[\]|#])", re.I)
    n = 0
    for p in c.execute(f"SELECT DISTINCT p.id, p.org_id, p.owner_id, p.body FROM wiki_links k JOIN wiki_pages p ON p.id=k.from_id WHERE k.to_path=? "
                       f"AND p.deleted_at IS NULL AND p.{w.replace(' AND ', ' AND p.')}", [old.lower(), *a]).fetchall():
        try:
            ob = wkh_open(c, p["org_id"], p["owner_id"], p["body"])  # 2.123.0 A (#2105)
        except WikiUnreadable:  # 2.126.2 B (#2358): an unreadable page keeps its text (and its old link)
            continue
        nb = rx.sub(lambda m: "[[" + new, ob)
        if nb != ob and only_edit:
            from .wkfolder import wkf_role
            if wkf_role(c, uid, c.execute("SELECT * FROM wiki_pages WHERE id=?", (p["id"],)).fetchone()) != "edit":
                continue
        if nb != ob:
            c.execute("UPDATE wiki_pages SET body=?, updated_by=?, updated_at=? WHERE id=?",
                      (wkh_seal(c, p["org_id"], p["owner_id"], nb), uid, ts, p["id"]))
            wiki_set_links(c, p["id"], nb)
            n += 1
    return n


@app.patch("/api/wiki/pages/<int:pid>")
def wiki_update(pid):
    """{path?, body?, expect_updated_at? (409 with the current page when someone else saved in between), relink? (default
    true: a new name changes the [[links]] to it in the space)}"""
    c = db()
    write_lock(c, f"wiki-{int(pid)}")  # 2.269.0 B (#3034): the expect check and the write see no other save in between
    r = wiki_need(c, pid, write=True)  # 2.200.0 A (#2747): edit on the page (was: the space's write right)
    uid = me()
    b = body()
    exp = b.get("expect_updated_at")
    from .wkfolder import wkf_base, wkf_shared, wkf_shown_path
    by_share = wkf_base(c, uid, r) != "edit"  # 2.200.0 B (#2747): edit through a share of its folders only

    def conflict(r):
        cur = wiki_dict(r, names=user_names(c, [r["updated_by"]]))
        cur["path"] = wkf_shown_path(c, uid, r)  # 2.200.0 F (#2747, review B3)
        return jsonify(error=tr("Changed in the meantime by {0}", cur.get("updated_by_name") or "?"), page=cur), 409
    if exp and exp != r["updated_at"] and ("body" in b or "path" in b):
        return conflict(r)
    f, ts, n = {}, iso_ms(now_utc()), 0
    from .wkhist import wkh_body, wkh_note, wkh_prev, wkh_seal  # 2.123.0 A (#2105, #2102, #2106)
    from .wksearch import wks_index
    from .wikie2e import wke_guard  # 2.64.3 A (#1817): a locked space takes ciphertexts only, its links stay in the browser
    locked = wke_guard(c, r["org_id"], r["owner_id"], b.get("path"), b.get("body"), "update")
    if "body" in b:
        f["body"] = b["body"] if locked else wiki_body(b)
        f["attrs"] = "{}" if locked else json.dumps(wiki_frontmatter(f["body"]), ensure_ascii=False)
    plain = f.get("body")
    if "path" in b:
        path = b["path"] if locked else wiki_clean_path(b["path"])
        if by_share and not locked:  # 2.200.0 F (#2747, review B3): the client knows the path from the share down
            shown = wkf_shown_path(c, uid, r)
            if path.rsplit("/", 1)[0:-1] == shown.rsplit("/", 1)[0:-1]:
                path = "/".join([*r["path"].rsplit("/", 1)[0:-1], path.rsplit("/", 1)[-1]])
        if path != r["path"]:
            if by_share and path.rsplit("/", 1)[0:-1] != r["path"].rsplit("/", 1)[0:-1]:
                raise Denied(403, tr("Through a share only the page's own name can change, not its folder"))
            if by_share and not (wkf_shared(c, uid).get(r["id"]) or {}).get("folder"):  # 2.200.0 (#2747, review): a page
                raise Denied(403, tr("Through a share only the page's own name can change, not its folder"))  # shared alone: no name oracle
            f["path"] = path
    if f:
        f["updated_by"], f["updated_at"] = uid, ts
        if plain is not None:
            f["body"] = wkh_seal(c, r["org_id"], r["owner_id"], plain)  # 2.123.0 A (#2105): sealed at rest
        prev = wkh_prev(c, r)
        guard = " AND updated_at=?" if exp else ""  # 2.200.0 F (#1781, review 5): the conflict check in the same statement
        try:
            with c.savepoint():
                hit = c.execute(f"UPDATE wiki_pages SET {','.join(k + '=?' for k in f)} WHERE id=?{guard}",
                                [*f.values(), pid, *([exp] if exp else [])]).rowcount
        except IntegrityError:
            return wiki_taken()
        if not hit:  # someone saved between the read above and this write
            return conflict(wiki_need(c, pid))
        if "body" in f:
            wiki_set_links(c, pid, plain)
        if not locked:  # 2.123.0 A (#2102, #2106): the history and the word index
            wkh_note(c, pid, uid, ts, prev=prev)
            wks_index(c, pid, r["org_id"], r["owner_id"], plain if plain is not None else wkh_body(c, r), ts)
        if "path" in f and b.get("relink", True) is not False and not locked:
            n = wiki_relink(c, r, r["path"], f["path"], uid, ts, only_edit=by_share)  # 2.200.0 F (B7): a share: its pages only
        if "path" in f and not locked:
            from .wkshare import wsh_repath  # 2.123.0 B (#2104): the page's shares follow the new name
            wsh_repath(c, r["org_id"], r["owner_id"], r["path"], f["path"], False)
            from .wkfolder import wkf_sync
            wkf_sync(c, r["owner_id"] or uid, r["org_id"])  # 2.200.0 A (#2747): its node follows the new path
            if by_share:  # 2.200.0 B (#2747): the sync is the space's (it skips a guest): the node's name follows here
                from ..files.store import _now
                c.execute("UPDATE fs_nodes SET name=?, updated_at=? WHERE kind='ref' AND ref_kind='wiki' AND ref_id=?",
                          (f["path"].rsplit("/", 1)[-1], _now(), pid))
        bump(c)
        c.commit()
    r = wiki_need(c, pid)
    d = wiki_dict(r, names=user_names(c, [uid]))
    d["relinked"] = 0 if by_share else n  # 2.200.0 F (#2747, review B3/B7): nothing about pages outside the share
    d["path"] = wkf_shown_path(c, uid, r)
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
    from .wkshare import wsh_repath  # 2.123.0 B (#2104): the shares of the folder and of its pages follow
    wsh_repath(c, oid, None if oid else uid, src, dst, True)
    from .wkfolder import wkf_folder_move, wkf_sync
    wkf_folder_move(c, uid, oid, src, dst)  # 2.200.0 A (#2747): the folder node (with its shares) follows, then the pages
    wkf_sync(c, uid, oid)
    bump(c)
    c.commit()
    return jsonify(ok=True, moved=[{"id": r["id"], "from": r["path"], "to": new} for r, new in moves], relinked=n)


@app.delete("/api/wiki/pages/<int:pid>")
def wiki_delete(pid):
    """To the trash (the app's Undo brings it back: POST /api/wiki/restore)."""
    c = db()
    r = wiki_need(c, pid, write=True)  # 2.200.0 A (#2747): edit on the page
    wiki_need_space(c, me(), r)  # 2.200.0 B (#2747): deleting is the space's, not an edit share's
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
            wiki_need_space(c, uid, wiki_need(c, pid, write=True, deleted=not trash))  # 2.200.0 A/B (#2747): edit from the space
        except Denied:
            skipped.append(pid)
            continue
        try:
            with c.savepoint():
                c.execute("UPDATE wiki_pages SET deleted_at=? WHERE id=?", (ts if trash else None, pid))
                if not trash and r["deleted_at"]:  # 2.272.0 A (#3026): its files trashed with it (or later) come back too;
                    # a file deleted on its own before the page stays in the trash
                    c.execute("UPDATE wiki_files SET deleted_at=NULL WHERE page_id=? AND deleted_at>=?", (pid, r["deleted_at"]))
            done.append(pid)
        except IntegrityError:
            skipped.append(pid)
    if not trash:
        fdone, fskip = wka_bulk(c, uid, fids, False)
    if done or fdone:
        bump(c)
        c.commit()
    return jsonify(ok=True, ids=done, skipped=skipped, files=fdone, files_skipped=fskip)


# ---- 2.143.0 B (#2211): the trash of pages -- listed, deleted for good by hand ("Delete for good", "Empty trash") and after
# the trash period of tasks (tasktrash.ttp_days, KALMIDO_TRASH_DAYS) by the watchdog. Final = the row and what cascades from it
# (links, files, history, word index), the files' scan / text marks and move records; the stored files after the commit.
WKT_TICK = {"at": 0.0}
WKT_BATCH = 200  # pages per run; the rest follows in the next hour


def wiki_trash_days():
    from ..tasks.tasktrash import ttp_days
    return ttp_days()


def wiki_purge(c, ids):
    """Deletes these pages for good when they are (still) in the trash -> (ids deleted, stored file paths to unlink after the
    commit). The caller checked the rights."""
    ids = sorted({int(x) for x in ids})
    if not ids:
        return [], []
    q = ",".join("?" * len(ids))
    ids = [r[0] for r in c.execute(f"SELECT id FROM wiki_pages WHERE id IN ({q}) AND deleted_at IS NOT NULL ORDER BY id FOR UPDATE", ids)]
    if not ids:
        return [], []
    q = ",".join("?" * len(ids))
    from .wikiatt import wka_page_files
    files = wka_page_files(c, ids)
    fids = [r[0] for r in c.execute(f"SELECT id FROM wiki_files WHERE page_id IN ({q})", ids)]
    if fids:
        f = ",".join("?" * len(fids))
        c.execute(f"DELETE FROM upload_scan WHERE kind='wiki' AND ref_id IN ({f})", fids)
        c.execute(f"DELETE FROM file_text WHERE kind='wiki' AND ref_id IN ({f})", fids)
    c.execute(f"DELETE FROM space_moves WHERE kind='wiki' AND obj_id IN ({q})", ids)
    # a share of exactly this page ends with it (a later page of the same name is not shared by the old link); folder shares stay
    c.execute("UPDATE wiki_shares s SET revoked_at=? FROM wiki_pages p WHERE p.id IN (" + q + ") AND s.is_folder=0 AND s.revoked_at IS NULL "
              "AND COALESCE(s.org_id,0)=COALESCE(p.org_id,0) AND COALESCE(s.owner_id,0)=COALESCE(p.owner_id,0) AND lower(s.path)=lower(p.path) "
              "AND NOT EXISTS (SELECT 1 FROM wiki_pages x WHERE x.deleted_at IS NULL AND COALESCE(x.org_id,0)=COALESCE(p.org_id,0) "
              "AND COALESCE(x.owner_id,0)=COALESCE(p.owner_id,0) AND lower(x.path)=lower(p.path))", [iso(now_utc()), *ids])
    c.execute(f"DELETE FROM wiki_pages WHERE id IN ({q})", ids)  # links, files, versions, word index: ON DELETE CASCADE
    from .wkfolder import wkf_drop
    wkf_drop(c, ids)  # 2.200.0 A (#2747): their nodes in the tree
    if files:  # a stored file another row still names stays on disk
        f = ",".join("?" * len(files))
        used = {r[0] for r in c.execute(f"SELECT path FROM wiki_files WHERE path IN ({f})", files)}
        files = [p for p in files if p not in used]
    return ids, files


def wiki_trash_tick(c, force=False):
    """The watchdog (at most hourly): pages longer in the trash than the period go for good, with their files. -> counts."""
    if not force and time.time() - WKT_TICK["at"] < 3600:
        return {}
    WKT_TICK["at"] = time.time()
    cut = iso_ms(now_utc() - timedelta(days=wiki_trash_days()))
    purge, files = ret_on("trash"), []  # 2.272.0 A (#3026): like every retention run, off = count only
    with system_ctx(c):  # housekeeping over every space: rows are only deleted, nothing is handed to a person
        if purge:
            due = [r[0] for r in c.execute("SELECT id FROM wiki_pages WHERE deleted_at IS NOT NULL AND deleted_at<? "
                                           "ORDER BY deleted_at, id LIMIT ?", (cut, WKT_BATCH))]
            ids, files = wiki_purge(c, due) if due else ([], [])
            counts = {"pages": len(ids), "files": len(files)}
            if ids:
                bump(c)
        else:
            counts = {"pages": c.execute("SELECT COUNT(*) FROM wiki_pages WHERE deleted_at IS NOT NULL AND deleted_at<?", (cut,)).fetchone()[0],
                      "files": c.execute("SELECT COUNT(*) FROM wiki_files f JOIN wiki_pages p ON p.id=f.page_id "
                                         "WHERE p.deleted_at IS NOT NULL AND p.deleted_at<?", (cut,)).fetchone()[0]}
        ret_report(c, "trash", counts, purge, run="wiki")
    c.commit()
    unlink_files(files)  # after the commit: a failed commit keeps the rows and their files
    return counts


@app.get("/api/wiki/trash")
def wiki_trash_list():
    """?space= -- the pages of the space in the trash (newest first) with their files' count / size and the trash period."""
    c = db()
    uid = me()
    oid = wiki_space(c, uid, request.args.get("space"))
    w, a = wiki_space_sql(oid, uid)
    rows = c.execute(f"SELECT p.id, p.path, p.deleted_at, COUNT(f.id) AS n, COALESCE(SUM(f.size), 0) AS size FROM wiki_pages p "
                     f"LEFT JOIN wiki_files f ON f.page_id=p.id WHERE p.deleted_at IS NOT NULL AND p.{w.replace(' AND ', ' AND p.')} "
                     "GROUP BY p.id, p.path, p.deleted_at ORDER BY p.deleted_at DESC, p.id DESC LIMIT 2000", a).fetchall()
    return jsonify(space=wiki_space_key(oid), days=wiki_trash_days(),
                   pages=[{"id": r["id"], "path": r["path"], "deleted_at": r["deleted_at"], "files": r["n"], "size": int(r["size"])}
                          for r in rows])


@app.post("/api/wiki/purge")
def wiki_purge_many():
    """{space, ids} -- these pages of the trash for good; {space, all: true} -- empty the space's trash. Rights as deleting a
    page (wiki_space write). -> {ids, skipped}"""
    c = db()
    uid = me()
    b = body()
    oid = wiki_space(c, uid, b.get("space"), write=True)
    w, a = wiki_space_sql(oid, uid)
    ids = b.get("ids")
    if b.get("all") is True:
        ids = [r[0] for r in c.execute(f"SELECT id FROM wiki_pages WHERE deleted_at IS NOT NULL AND {w}", a)]
    elif not isinstance(ids, list) or len(ids) > WIKI_ZIP_FILES or any(isinstance(x, bool) or not isinstance(x, int) for x in ids):
        raise BadInput(tr("Invalid value: {0}", "ids"))
    mine = set()
    if ids:
        q = ",".join("?" * len(ids))
        mine = {r[0] for r in c.execute(f"SELECT id FROM wiki_pages WHERE id IN ({q}) AND deleted_at IS NOT NULL AND {w}", [*ids, *a])}
    done, files = wiki_purge(c, mine)
    if done:
        bump(c)
    c.commit()
    unlink_files(files)  # after the commit
    return jsonify(ok=True, ids=done, skipped=[x for x in ids if x not in set(done)])


@app.get("/api/wiki/search")
def wiki_search():
    """?q=words -- pages of every space one may read whose name (or text) has all words; without their text. 2.123.0 A
    (#2106): over the word index (wksearch.py), ranked (words in the name, then in the text, then the newest); ?space=
    only that space, ?limit= (default 30, at most 100) &offset= the next ones -> {pages, total, more, offset}."""
    from ..accounts.orgs import user_orgs
    from .wksearch import WKS_LIMIT, WKS_LIMIT_MAX, wks_search
    c = db()
    uid = me()
    q = (request.args.get("q") or "").strip()[:200]
    try:
        limit = max(1, min(WKS_LIMIT_MAX, int(request.args.get("limit") or WKS_LIMIT)))
        offset = max(0, min(100_000, int(request.args.get("offset") or 0)))
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "limit"))
    if request.args.get("space") not in (None, ""):
        spaces = [wiki_space(c, uid, request.args.get("space"))]
    else:
        from ..accounts.orgroles import user_orgs_full
        spaces = [None, *[o for o in user_orgs(c, uid) if o in user_orgs_full(c, uid)]]  # 2.143.0 A (#2151)
    rows, total = wks_search(c, uid, spaces, q, limit, offset)
    return jsonify(pages=[wiki_dict(r, full=False) for r in rows], total=total, offset=offset, more=offset + len(rows) < total)


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
    from ..accounts.orgroles import user_orgs_full
    orgs = [o for o in user_orgs(c, uid) if o in user_orgs_full(c, uid)]  # 2.143.0 A (#2151)
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
    others on a page "Imported files" of their folder). At most WIKI_ZIP_FILES files, 1 MB per page, 100 MB per file, 500 MB
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
