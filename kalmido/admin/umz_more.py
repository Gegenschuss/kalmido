"""2.363.4 (#3127): the account import takes over the rest of the person's own rows (admin/acctimport.py umz_private calls it).

Through the areas of the organisation import (acctimport.umz_private_oi): filed mails with their files, video sign-offs, notepads
and playbooks of the projects of the file. Written here directly, each checked like an entry made by hand and recorded for the
undo (run.created["more"], umz_more_undo): bookmarks (the preview is fetched again), finished focus sessions, whom I stay in
touch with, saved arrangements of views and project pages, and the bells / follows of the tasks that came along.
Never an id of the old server: what points at something that did not come along is left out."""
import json

from flask import g

from ..core.config import app
from ..core.db import db_log_err, iso, now_utc
from ..core.errors import BadInput
from ..core.access import Denied
from ..core.i18n import N_
from ..accounts.layouts import clean_layout
from ..accounts.layoutsets import lyv_key_ok, lyv_save
from ..accounts.discover import _push as conn_push  # 2.574.0 (#4556): a request asked again is told like one asked by hand
from ..accounts.discover import disc_findable  # 2.574.0 (#4556, review B1)
from ..collab.comments import send_pushes
from ..life.bookmarks import BM_DESC_MAX, BM_MAX, BM_NOTE_MAX, BM_SITE_MAX, BM_STATES, BM_TITLE_MAX, bm_key, bm_norm_url, bm_site, bm_tags
from ..notify.taskbell import TBL_LEVELS
from ..integrations.importers import imp_undo_after  # 2.506.0 (#4299)
from .acctimport import _iso_ts, _oid, _txt, tr, umz_cols, umz_find, umz_insert, umz_row, umz_seen
from ..life.budget import bud_import  # 2.584.0 (#3965)
from ..lists.lists import clean_folder  # 2.584.0 (#3965)
from ..lists.playbook import PB_KEEP, PB_SOURCES, pb_text  # 2.584.0 (#3965)

# the parts written here (each also in acctimport.UMZ_READ)
UMZ_MORE = ("bookmarks", "pomos", "contact_care", "view_layouts", "list_layouts", "task_bell", "task_watchers",
            "kid_parents", "conn_links",  # 2.531.0 (#4317 F12)
            "budgets")  # 2.584.0 (#3965); + a folder's playbooks (rows of "playbooks" without a project, umz_more_has)
UMZ_NAMES_MAX = 20  # 2.531.0 (#4317 F12): names in one warning, the rest as a number
UMZ_CONN_MAX = 50  # 2.574.0 (#4556): connection requests one import asks again at most (the rest is named, not asked)


def umz_more_has(data):
    return any(data.get(p) for p in UMZ_MORE) or bool(_folder_rows(data))


def _folder_rows(data):
    """2.584.0 (#3965): the playbook versions of my folders in the file (list_id empty)."""
    return [r for r in data.get("playbooks") or [] if isinstance(r, dict) and r.get("list_id") is None]


def umz_more_space(run, oi):
    """A filed mail or a video sign-off goes into my private space: its project / task only while that stayed private too (a
    project that went into the organisation would show a private row to its members)."""
    for entry in ("hub/mails.json", "videos/reviews.json"):
        for r in oi.get(entry) or []:
            lid, tid = run.m("lists", r.get("list_id")), run.m("tasks", r.get("task_id"))
            if (lid and run.list_org.get(lid)) or (tid and run.list_org.get(run.task_list.get(tid))):
                r["list_id"] = r["task_id"] = None


def _more(run, table, key):
    run.created.setdefault("more", []).append([table, key])
    run.count(table)


def _bookmarks(c, run, uid, data, ts):
    have = {r[0] for r in c.execute("SELECT url_key FROM bookmarks WHERE user_id=? AND org_id IS NULL AND deleted_at IS NULL", (uid,))}
    n = c.execute("SELECT COUNT(*) FROM bookmarks WHERE user_id=? AND deleted_at IS NULL", (uid,)).fetchone()[0]
    for r in data.get("bookmarks") or []:
        run.step()
        url = bm_norm_url(_txt(r.get("url"), 2000)) if isinstance(r, dict) else ""
        if not url:
            continue
        key = bm_key(url)
        if key in have:  # the same link saved here already stays as it is
            continue
        if n >= BM_MAX:
            run.warning(N_("A row could not be imported: {0}"), tr(N_("Bookmarks")))
            continue
        try:
            tags = bm_tags(json.loads(r["tags"]) if isinstance(r.get("tags"), str) and r["tags"].startswith("[") else r.get("tags"))
        except (BadInput, ValueError):
            tags = []
        st = r.get("state") if r.get("state") in BM_STATES else "unread"
        at = r.get("created_at") if _iso_ts(r.get("created_at")) else ts
        d = {"user_id": uid, "org_id": None, "url": url, "url_key": key, "title": _txt(r.get("title"), BM_TITLE_MAX),
             "description": _txt(r.get("description"), BM_DESC_MAX), "site": bm_site(url)[:BM_SITE_MAX],
             "tags": json.dumps(tags, ensure_ascii=False), "note": _txt(r.get("note"), BM_NOTE_MAX), "state": st, "preview": "pending",
             "created_at": at, "updated_at": ts}
        nid = umz_insert(c, "bookmarks", d)  # review: in a savepoint like every other row
        if not nid:
            continue
        have.add(key)
        n += 1
        _more(run, "bookmarks", nid)


def _pomos(c, run, uid, data, ts):
    """Finished focus sessions only (a running one would start a timer here)."""
    for r in data.get("pomos") or []:
        run.step()
        if not isinstance(r, dict) or not _iso_ts(r.get("start")) or not _iso_ts(r.get("end")):
            continue
        d = umz_row(c, "pomos", r, {"user_id": uid, "task_id": run.m("tasks", r.get("task_id")), "done": 1, "notified": 1,
                                    "paused_at": None}, ts)
        nid = umz_insert(c, "pomos", d) if d else None
        if nid:
            _more(run, "pomos", nid)


def _care(c, run, uid, data, ts):
    for r in data.get("contact_care") or []:
        run.step()
        cid = run.m("contacts", r.get("contact_id")) if isinstance(r, dict) else None
        if not cid or run.old("contacts", cid):  # 2.531.0 (#4317) F16: came along with an earlier import of the contact
            continue
        d = umz_row(c, "contact_care", r, {"user_id": uid, "contact_id": cid, "updated_at": ts}, ts)
        if d and umz_insert(c, "contact_care", d, rid=False):
            _more(run, "contact_care", {"contact_id": cid})


def _layouts(c, run, uid, data, ts):
    """Saved arrangements (a project page under its new id) through lyv_save, the current arrangement of my projects' pages."""
    for r in data.get("view_layouts") or []:
        run.step()
        key = r.get("view_key") if isinstance(r, dict) and isinstance(r.get("view_key"), str) else ""
        if key.startswith("list:"):
            lid = run.m("lists", key[5:])
            key = f"list:{lid}" if lid else ""
        if not lyv_key_ok(key):
            continue
        try:
            with c.savepoint():
                nid = lyv_save(c, uid, key, _txt(r.get("name"), 60) or "Import", r.get("layout") or "")
        except (BadInput, Denied):  # a layout that does not fit, or LYV_MAX arrangements of that view here already
            run.warning(N_("A row could not be imported: {0}"), tr(N_("Saved arrangements")))
            continue
        _more(run, "view_layouts", nid)
    for r in data.get("list_layouts") or []:
        run.step()
        lid = run.m("lists", r.get("list_id")) if isinstance(r, dict) else None
        if not lid or run.old("lists", lid) or c.execute("SELECT 1 FROM list_layouts WHERE list_id=? AND user_id=?", (lid, uid)).fetchone():
            continue  # 2.531.0 (#4317) F16: came along with an earlier import (the inbox: an arrangement of its own here)
        try:
            lay = clean_layout(r.get("layout") if isinstance(r.get("layout"), str) else None)
        except BadInput:
            continue
        if not lay:  # review: an empty own arrangement would only hide the project's standard
            continue
        if umz_insert(c, "list_layouts", {"list_id": lid, "user_id": uid, "layout": lay, "updated_at": ts}, rid=False):
            _more(run, "list_layouts", {"list_id": lid})


def _bells(c, run, uid, me_old, data, ts):
    """My bell level of a task that came along (set by me; one somebody else set for me stays behind) and the tasks I follow."""
    for r in data.get("task_bell") or []:
        run.step()
        tid = run.m("tasks", r.get("task_id")) if isinstance(r, dict) else None
        if not tid or run.old("tasks", tid) or r.get("level") not in TBL_LEVELS or (_oid(r.get("set_by")) and _oid(r.get("set_by")) != me_old):
            continue
        d = {"task_id": tid, "user_id": uid, "org_id": run.list_org.get(run.task_list.get(tid)), "level": r["level"],
             "until": r.get("until") if _iso_ts(r.get("until")) else None, "set_by": uid if r.get("set_by") else None,
             "created_at": r.get("created_at") if _iso_ts(r.get("created_at")) else ts, "updated_at": ts}
        if umz_insert(c, "task_bell", d, rid=False):
            _more(run, "task_bell", {"task_id": tid})
    for r in data.get("task_watchers") or []:
        run.step()
        tid = run.m("tasks", r.get("task_id")) if isinstance(r, dict) else None
        if tid and not run.old("tasks", tid) and umz_insert(c, "task_watchers", {"task_id": tid, "user_id": uid,
                                                     "created_at": r.get("created_at") if _iso_ts(r.get("created_at")) else ts}, rid=False):
            _more(run, "task_watchers", {"task_id": tid})


def _names(rows):
    names = sorted({_txt(r.get("name"), 100) or tr("Unknown") for r in rows})
    more = len(names) - UMZ_NAMES_MAX
    return ", ".join(names[:UMZ_NAMES_MAX]) + (f" (+{more})" if more > 0 else "")


def _family(c, run, uid, data, ts, salt):
    """2.531.0 (#4317 F12): the family links and connections of the file, the other person found by the address hash among the
    accounts the person may see (like the people of the preview). A family link hands a parent the care of a child account: only an
    admin sets it (Users), so the import never makes one and names who it was with. A connection is asked again: an open request
    the other person confirms (never a connection without them); one that cannot be asked is named.
    2.574.0 (#4556): an open request is told to the other person the way discover.conn_request tells one (News + push, row
    "share" of their notification settings); a hidden one (they blocked the person) stays silent. At most UMZ_CONN_MAX new
    requests per run, the rest is not asked and named in its own warning. Review B1: only someone the person could ask by hand
    (findable, or a request row between them, discover.disc_findable); the others are named (ask by hand). Review B2: a request the
    undo withdrew (wd_<state>) gets its state back without a new message, like asking again by hand."""
    fam = [r for r in data.get("kid_parents") or [] if isinstance(r, dict)]
    if fam:
        run.warning(N_("Family links do not move along, an admin of this server sets them up again: {0}"), _names(fam))
    links = [r for r in data.get("conn_links") or [] if isinstance(r, dict)]
    if not links:
        return
    me_ = c.execute("SELECT kid, COALESCE(kind,'user') AS kind, display_name, username FROM users WHERE id=?", (uid,)).fetchone()
    seen = umz_seen(c, uid, salt) if me_ and not me_["kid"] and me_["kind"] == "user" else {}
    asked, gone, over, tell, hidden_ = [], [], [], [], []
    for r in links:
        run.step()
        hit = umz_find(c, uid, r.get("email_hash") if isinstance(r.get("email_hash"), str) else "", seen)
        o = c.execute("SELECT id FROM users WHERE id=? AND disabled=0 AND kind='user' AND kid=0", (hit["id"],)).fetchone() if hit else None
        if not o:
            gone.append(r)
            continue
        a, b = sorted((uid, o["id"]))
        old = c.execute("SELECT id, status FROM conn_requests WHERE from_id=? AND to_id=?", (uid, o["id"])).fetchone()
        if c.execute("SELECT 1 FROM conn_links WHERE a_id=? AND b_id=? AND deleted_at IS NULL", (a, b)).fetchone() or \
                (old and not old["status"].startswith("wd_")) or \
                c.execute("SELECT 1 FROM conn_requests WHERE from_id=? AND to_id=? AND status='open'", (o["id"], uid)).fetchone():
            continue  # connected or asked already (a request of mine keeps its state, as when asking again by hand)
        if not old and not disc_findable(c, uid, o["id"]):  # review B1: not findable for a request by hand either
            hidden_.append(r)
            continue
        if len(asked) >= UMZ_CONN_MAX:  # 2.574.0 (#4556): a hidden one counts too (the limit tells nothing about a block)
            over.append(r)
            continue
        blocked = c.execute("SELECT 1 FROM conn_blocks WHERE user_id=? AND blocked_id=?", (o["id"], uid)).fetchone()
        if old:  # review B2: withdrawn by an undo -> the old state back, no new message (discover.conn_request, 2.49.0 S1)
            st0 = old["status"][3:]
            c.execute("UPDATE conn_requests SET status=? WHERE id=?", ("hidden" if blocked and st0 == "open" else st0, old["id"]))
            _more(run, "conn_requests", old["id"])
            asked.append(r)
            continue
        rid = umz_insert(c, "conn_requests", {"from_id": uid, "to_id": o["id"], "status": "hidden" if blocked else "open", "created_at": ts})
        if rid:
            _more(run, "conn_requests", rid)
            asked.append(r)
            if not blocked:  # told once the run is committed (_conn_tell)
                tell.append(o["id"])
        else:
            gone.append(r)
    if tell:
        run.after.append(lambda c2: _conn_tell(c2, uid, tell))
    if asked:
        run.warning(N_("Connections asked again, they count once the other person confirms: {0}"), _names(asked))
    if gone:
        run.warning(N_("Connections that do not move along (no account here you may see): {0}"), _names(gone))
    if over:
        run.warning(N_("Connections not asked again, more than {0} in one import (ask them by hand): {1}"), UMZ_CONN_MAX, _names(over), must=True)
    if hidden_:  # review B1
        run.warning(N_("Connections not asked again, the other person cannot be found in the connection search (ask them by hand): {0}"),
                    _names(hidden_))


def _conn_tell(c, uid, to_ids):
    """2.574.0 (#4556): after the run's commit (acctimport umz_run, run.after): the open requests the import asked again are told
    to the other person like discover.conn_request tells one (News + push, row "share" of their notification settings). The import
    runs without a request (a queue row): in one of its own, as the importing person (me() = the sender, as when asking by hand);
    the pushes leave after the News are committed. A failure here costs only the News, never the committed import."""
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u:
        return
    with app.test_request_context("/api/account/import"):
        g.pushes, g.user, g.auth_via = [], u, None  # not g.db: the context's end would close the run's connection
        try:
            for o in to_ids:
                conn_push(c, o, "connreq", u["display_name"] or u["username"])
            c.commit()
        except Exception as e:  # noqa: BLE001 -- the import is committed already; only the News are lost
            c.heal() or c.rollback()
            print(f"account import of user {uid}: telling the connection requests failed: {db_log_err(e)}", flush=True)
            return
        send_pushes(g.pop("pushes", None))


def _budgets(c, run, uid, data):
    """2.584.0 (#3965): the household budgets (life/budget.py bud_export) into their budget list that came along with this run
    (one of an earlier import of the file keeps what it has); nothing goes into a list of somebody else (bud_import checks it)."""
    for b in data.get("budgets") or []:
        run.step()
        lid = run.m("lists", b.get("list_id")) if isinstance(b, dict) else None
        if not lid or run.old("lists", lid):
            if isinstance(b, dict) and not lid:
                run.warning(N_("A row could not be taken over: {0}"), tr(N_("Household budget")))
            continue
        try:
            made, bad = bud_import(c, uid, lid, b, lambda t: run.m("tasks", t))
        except Denied:  # not a budget list of mine (the file's list is no budget, or it did not come along as mine)
            run.warning(N_("A row could not be taken over: {0}"), tr(N_("Household budget")))
            continue
        for table, nid in made:
            _more(run, table, nid)
        for _ in range(bad):
            run.warning(N_("A row could not be taken over: {0}"), tr(N_("Household budget")))


def _folder_pbs(c, run, uid, me_old, data):
    """2.584.0 (#3965): the playbooks of my folders (owner + folder path, every version in its order). A folder that has a
    playbook here already keeps it (named); the author is me or nobody, never an id of the old server."""
    by = {}
    for r in _folder_rows(data):
        run.step()
        try:
            folder = clean_folder(_txt(r.get("folder"), 1000), strict=False)
            text = pb_text(r.get("body"))
        except Exception:  # noqa: BLE001 -- a broken folder path / text: left out like a row that does not fit
            folder, text = "", ""
        v = r.get("version")
        if not folder or not text or not isinstance(v, int) or isinstance(v, bool) or v < 1:
            run.warning(N_("A row could not be taken over: {0}"), tr(N_("Playbooks")))
            continue
        by.setdefault(folder, {})[v] = (r, text)
    here = []
    for folder, vers in sorted(by.items()):
        if c.execute("SELECT 1 FROM playbooks WHERE list_id IS NULL AND owner_id=? AND folder=? LIMIT 1", (uid, folder)).fetchone():
            here.append(folder)
            continue
        for v in sorted(vers)[-PB_KEEP:]:
            r, text = vers[v]
            src = r.get("source") if r.get("source") in PB_SOURCES else "import"
            d = {"list_id": None, "owner_id": uid, "folder": folder, "version": v, "body": text, "source": src,
                 "author_id": uid if _oid(r.get("author_id")) == me_old else None,
                 "created_at": r.get("created_at") if _iso_ts(r.get("created_at")) else iso(now_utc())}
            nid = umz_insert(c, "playbooks", d)
            if nid:
                _more(run, "playbooks", nid)
    if here:
        run.warning(N_("Folders that have a playbook here already keep it: {0}"), ", ".join(here[:UMZ_NAMES_MAX]))


def umz_more_write(c, run, uid, me_old, data, salt=None):
    """Inside the run's transaction (the caller commits). salt: the export's people_salt (2.531.0 #4317)."""
    ts = iso(now_utc())
    _budgets(c, run, uid, data)  # 2.584.0 (#3965)
    _folder_pbs(c, run, uid, me_old, data)
    _bookmarks(c, run, uid, data, ts)
    _pomos(c, run, uid, data, ts)
    _care(c, run, uid, data, ts)
    _layouts(c, run, uid, data, ts)
    _bells(c, run, uid, me_old, data, ts)
    _family(c, run, uid, data, ts, salt)


# what the undo removes: always only the importing person's row
_UNDO = {"bookmarks": "id", "pomos": "id", "view_layouts": "id", "contact_care": "contact_id", "list_layouts": "list_id",
         "task_bell": "task_id", "task_watchers": "task_id", "conn_requests": "id",
         "budget_cats": "id", "budget_recurring": "id", "budget_entries": "id", "playbooks": "id"}  # 2.584.0 (#3965)
# 2.584.0 (#3965): rows without a person column -> the condition that they are still the importing person's
_UNDO_MINE = {"budget_cats": "list_id IN (SELECT id FROM lists WHERE owner_id=?)", "budget_recurring": "list_id IN (SELECT id FROM lists WHERE owner_id=?)",
              "budget_entries": "list_id IN (SELECT id FROM lists WHERE owner_id=?)", "playbooks": "list_id IS NULL AND owner_id=?"}


def umz_more_there(c, uid, cr):
    """2.611.0 (#4866): {(table, key)} of the rows umz_more_write recorded that are still there and the undo may delete (its
    preview compares before / after; a connection request is withdrawn, never deleted: not here)."""
    want = {}
    for item in cr.get("more") or []:
        if not (isinstance(item, list) and len(item) == 2 and item[0] in _UNDO) or item[0] == "conn_requests":
            continue
        col = _UNDO[item[0]]
        v = item[1].get(col) if isinstance(item[1], dict) else item[1]
        if isinstance(v, int) and not isinstance(v, bool):
            want.setdefault(item[0], set()).add(v)
    out = set()
    for table, ids in want.items():
        col, ids = _UNDO[table], sorted(ids)
        for i in range(0, len(ids), 500):
            p = ids[i:i + 500]
            out.update((table, r[0]) for r in c.execute(f"SELECT {col} FROM {table} WHERE {col} IN ({','.join('?' * len(p))}) AND user_id=?",
                                                         p + [uid]).fetchall())
    return out


def umz_more_undo(c, uid, cr, since, plan):
    """The rows umz_more_write recorded -> how many stay (2.506.0 #4299): one changed since the import is the person's own work now.
    Bookmarks: the plan judges them (their preview fetch writes the time columns) and counts them. A focus session is finished and
    has no way to change."""
    kept = 0
    pbs = {x[1] for x in cr.get("more") or [] if isinstance(x, list) and len(x) == 2 and x[0] == "playbooks"}  # 2.584.0 (#3965)
    for item in reversed(cr.get("more") or []):
        if not (isinstance(item, list) and len(item) == 2 and item[0] in _UNDO):
            continue
        table, key = item
        col = _UNDO[table]
        v = key.get(col) if isinstance(key, dict) else key
        if not isinstance(v, int):
            continue
        if table == "conn_requests":  # 2.531.0 (#4317 F12): a request still waiting goes, one the other person answered stays
            # 2.574.0 (#4556, review B2): withdrawn (wd_<state>) as by hand, not deleted: a second import brings it back without a new message
            if c.execute("UPDATE conn_requests SET status='wd_' || status WHERE id=? AND from_id=? AND status IN ('open','hidden')",
                         (v, uid)).rowcount == 0:
                kept += 1 if c.execute("SELECT 1 FROM conn_requests WHERE id=? AND from_id=?", (v, uid)).fetchone() else 0
            continue
        if table in _UNDO_MINE:  # 2.584.0 (#3965): a budget row changed since / a folder written on since stays (own work now)
            mine = _UNDO_MINE[table]
            if table == "playbooks":  # a version saved since on that folder (one this import did not make) keeps the folder's history
                r = c.execute(f"SELECT folder FROM playbooks WHERE id=? AND {mine}", (v, uid)).fetchone()
                gone = r is not None and not any(x["id"] not in pbs for x in c.execute(
                    "SELECT id FROM playbooks WHERE list_id IS NULL AND owner_id=? AND folder=?", (uid, r["folder"])))
                kept += r is not None and not gone
            else:  # 2.584.0 (fable F5): a budget row is never deleted on its own - its list goes into the trash with all its rows,
                # or stays whole when anything in it was written since (importers.imp_undo_lists, imp_budget_touched)
                r = c.execute(f"SELECT updated_at FROM {table} WHERE id=? AND {mine}", (v, uid)).fetchone()
                kept += r is not None and imp_undo_after(r["updated_at"], since)
                gone = False
            if gone:
                c.execute(f"DELETE FROM {table} WHERE id=? AND {mine}", (v, uid))
            continue
        if table == "bookmarks":
            if not plan.goes(table, v):
                continue
        elif "updated_at" in umz_cols(c, table)[0]:
            r = c.execute(f"SELECT updated_at, created_at FROM {table} WHERE {col}=? AND user_id=?", (v, uid)).fetchone() if table == "view_layouts" else \
                c.execute(f"SELECT updated_at FROM {table} WHERE {col}=? AND user_id=?", (v, uid)).fetchone()
            if r is None:
                continue
            if imp_undo_after(r["updated_at"], since) or (table == "view_layouts" and r["updated_at"] > r["created_at"]):
                kept += 1
                continue
        c.execute(f"DELETE FROM {table} WHERE {col}=? AND user_id=?", (v, uid))
    return kept
