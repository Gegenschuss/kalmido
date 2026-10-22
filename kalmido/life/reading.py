"""2.172.0 B (#2679): Reading -- the view "Read later" of one space (private or an organisation), the place "Read later"
of a feed, the share sheet and the view save to. Built by part B."""
import re
import urllib.parse

from flask import g, has_request_context, jsonify, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, iso, now_utc
from ..core.pg import insert_id
from ..core.access import Denied, my_max_sort, vis_sql, wr_sql
from ..core.errors import BadInput
from ..accounts.session import me
from ..lists.lists import LIST_NAME_MAX, list_created
from ..tasks.validation import as_int, TITLE_MAX
from ..life.model import _insert, life_list_create, need_life
from ..life.rss import rss_space, rss_space_key, rss_text, rss_url


# ---------------------------------------------------------------- 2.172.0 B (#2679): read later per space
# Read later stays what it was: tasks (title + link) of a project. Private = the person's "Read later" projects outside
# every organisation (lists.life 'reading', as before: Karakeep, the share sheet and old entries keep working). An
# organisation's = ONE project of the organisation open to every member ("Everyone in the organisation", members may
# tick and add; never an agent's: agents do not see such projects unless shared with them), made on first use and
# remembered in reading_orgs. Each view shows only its own space. People only: no agent, no API token (no v1 route).
RL_PAGE = 60
RL_SUMMARY = 300


def rl_need(c, uid):
    """The person's own module "reading"; never an agent, never an API token (an agent's account has kind 'agent')."""
    u = getattr(g, "user", None) if has_request_context() else None
    if has_request_context() and ((u is not None and "kind" in u.keys() and u["kind"] == "agent") or g.get("auth_via") == "token"):
        raise Denied(403, tr("Read later is only available in the app"))
    need_life(c, uid, "reading")


def _rl_org_list(c, oid):
    """The live project registered for organisation oid, or None."""
    r = c.execute("""SELECT l.id FROM reading_orgs r JOIN lists l ON l.id=r.list_id WHERE r.org_id=? AND l.org_id=?
                     AND l.deleted_at IS NULL AND l.archived=0""", (oid, oid)).fetchone()
    return r[0] if r else None


def rl_list(c, uid, oid, create=True):
    """The read-later project of a space for a new entry: private = the person's first writable "Read later" project
    outside every organisation (made when missing); an organisation's = its registered project (made on first use)."""
    if not oid:
        r = c.execute(f"""SELECT id FROM lists WHERE life='reading' AND archived=0 AND e2e IS NULL AND org_id IS NULL AND id IN {wr_sql()}
                          ORDER BY owner_id!=?, id LIMIT 1""", (uid, uid, uid)).fetchone()
        if r:
            return r[0]
        return life_list_create(c, uid, "reading") if create else None
    lid = _rl_org_list(c, oid)
    if lid or not create:
        return lid
    lid = insert_id(c, """INSERT INTO lists(name,color,folder,sort,view,created_at,owner_id,checklist,kind,org_id,org_visibility,org_edit)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (tr("Read later")[:LIST_NAME_MAX], "#8b5cf6", "", my_max_sort(c, uid) + 1, "list", iso(now_utc()), uid, 0, "list",
                     oid, "org", 1))
    list_created(c, uid, lid, agents=False)
    c.execute("""INSERT INTO reading_orgs(org_id,list_id,created_at) VALUES(?,?,?)
                 ON CONFLICT (org_id) DO UPDATE SET list_id=excluded.list_id, created_at=excluded.created_at""", (oid, lid, iso(now_utc())))
    return lid


def rl_need_write(c, uid, lid):
    """403 unless uid may add to project lid (an organisation's project its owner / admins closed again, a read-only role)."""
    if not c.execute(f"SELECT 1 FROM lists WHERE id=? AND id IN {wr_sql()}", (lid, uid, uid)).fetchone():
        raise Denied(403, tr("You cannot add to this project"))


def rl_lists(c, uid, oid):
    """The read-later projects of a space uid sees (the view): private ones / the organisation's own (+ "Read later"
    projects moved into the organisation that uid sees)."""
    if not oid:
        q, a = "l.life='reading' AND l.org_id IS NULL", []
    else:
        own = _rl_org_list(c, oid)
        q, a = "l.org_id=? AND (l.life='reading' OR l.id=?)", [oid, own or 0]
    return [r[0] for r in c.execute(f"""SELECT l.id FROM lists l WHERE {q} AND l.archived=0 AND l.e2e IS NULL AND l.deleted_at IS NULL
                                        AND l.id IN {vis_sql()} ORDER BY l.id""", (*a, uid, uid)).fetchall()]


def rl_site(u):
    h = (urllib.parse.urlsplit(u or "").hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def rl_item_out(r, writable):
    return {"id": r["id"], "list_id": r["list_id"], "title": r["title"], "url": rss_url(r["url"] or ""), "site": rl_site(r["url"]),
            "summary": rss_text(r["content"] or "", RL_SUMMARY), "created_at": r["created_at"], "done": r["status"] != 0,
            "completed_at": r["completed_at"], "can_edit": writable}


def rl_view(c, uid, a):
    """?space=private|org:<id> &done=1 (the ticked ones) &q= &offset= -> {items, more, count, done_count, space, list_id}."""
    rl_need(c, uid)
    oid = rss_space(c, uid, a.get("space"))
    lids = rl_lists(c, uid, oid)
    target = rl_list(c, uid, oid, create=False)
    out = {"items": [], "more": False, "count": 0, "done_count": 0, "space": rss_space_key(oid), "list_id": target,
           "lists": lids}
    if not lids:
        return out
    ph = ",".join("?" * len(lids))
    wr = {r[0] for r in c.execute(f"SELECT id FROM lists WHERE id IN ({ph}) AND id IN {wr_sql()}", (*lids, uid, uid)).fetchall()}
    done = a.get("done") in ("1", "true")
    w, args = f"t.list_id IN ({ph}) AND t.deleted_at IS NULL AND t.parent_id IS NULL", list(lids)
    q = (a.get("q") or "").strip()[:200]
    if q:
        for word in q.split()[:8]:
            lk = "%" + word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            w += " AND (t.title ILIKE ? ESCAPE '\\' OR COALESCE(t.url, '') ILIKE ? ESCAPE '\\' OR t.content ILIKE ? ESCAPE '\\')"
            args += [lk] * 3
    off = as_int(a.get("offset") or 0, "offset", 0, 1_000_000)
    n_open, n_done = c.execute(f"SELECT COUNT(*) FILTER (WHERE t.status=0), COUNT(*) FILTER (WHERE t.status<>0) FROM tasks t WHERE {w}",
                               args).fetchone()
    rows = c.execute(f"""SELECT t.id, t.list_id, t.title, t.url, t.content, t.status, t.created_at, t.completed_at FROM tasks t
                         WHERE {w} AND {'t.status<>0' if done else 't.status=0'}
                         ORDER BY {'t.completed_at DESC' if done else 't.created_at DESC'}, t.id DESC LIMIT ? OFFSET ?""",
                     (*args, RL_PAGE + 1, off)).fetchall()
    out.update(items=[rl_item_out(r, r["list_id"] in wr) for r in rows[:RL_PAGE]], more=len(rows) > RL_PAGE, count=n_open, done_count=n_done)
    return out


def rl_save(c, uid, b):
    """{url, title?, note?, space?}: a link as a task of the space's read-later project (the same open link there comes
    back) -> {task_id, list_id, created, space}."""
    rl_need(c, uid)
    unknown = sorted(set(b) - {"url", "title", "note", "space"})
    if unknown:
        raise BadInput(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    oid = rss_space(c, uid, b.get("space"), write=True)
    raw = b.get("url")
    u = str(raw or "").strip() if isinstance(raw, str) else ""
    if u and not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", u) and re.match(r"^[\w-]+(\.[\w-]+)+([/:?#]|$)", u):
        u = "https://" + u
    url = rss_url(u)
    if not url:
        raise BadInput(tr("Please enter a link (http or https)"))
    for k in ("title", "note"):
        if b.get(k) is not None and not isinstance(b.get(k), str):
            raise BadInput(tr("Invalid value: {0}", k))
    title = re.sub(r"\s+", " ", b.get("title") or "").strip()[:TITLE_MAX] or (rl_site(url) + urllib.parse.urlsplit(url).path.rstrip("/"))[:TITLE_MAX] or url[:TITLE_MAX]
    lid = rl_list(c, uid, oid)
    rl_need_write(c, uid, lid)
    old = c.execute("SELECT id FROM tasks WHERE list_id=? AND url=? AND status=0 AND deleted_at IS NULL AND parent_id IS NULL ORDER BY id LIMIT 1",
                    (lid, url)).fetchone()
    if old:
        return {"task_id": old[0], "list_id": lid, "created": False, "space": rss_space_key(oid)}
    tid = _insert(c, uid, lid, title, url=url, content=(b.get("note") or "").strip()[:5000])
    return {"task_id": tid, "list_id": lid, "created": True, "space": rss_space_key(oid)}


@app.get("/api/reading")
def reading_get():
    """The read-later entries of one space -> {items, more, count, done_count, space, list_id, lists}."""
    c, uid = db(), me()
    return jsonify(rl_view(c, uid, request.args))


@app.post("/api/reading")
def reading_post():
    """{url, title?, note?, space?}: save a link to read later in a space -> {task_id, list_id, created, space}."""
    c, uid = db(), me()
    out = rl_save(c, uid, body())
    if out["created"]:
        bump(c)
    c.commit()
    return jsonify(out), 201 if out["created"] else 200
