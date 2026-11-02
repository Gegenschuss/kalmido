"""2.363.4 (#3127): the account import takes over the rest of the person's own rows (admin/acctimport.py umz_private calls it).

Through the areas of the organisation import (acctimport.umz_private_oi): filed mails with their files, video sign-offs, notepads
and playbooks of the projects of the file. Written here directly, each checked like an entry made by hand and recorded for the
undo (run.created["more"], umz_more_undo): bookmarks (the preview is fetched again), finished focus sessions, whom I stay in
touch with, saved arrangements of views and project pages, and the bells / follows of the tasks that came along.
Never an id of the old server: what points at something that did not come along is left out."""
import json

from ..core.db import iso, now_utc
from ..core.errors import BadInput
from ..core.access import Denied
from ..core.i18n import N_
from ..accounts.layouts import clean_layout
from ..accounts.layoutsets import lyv_key_ok, lyv_save
from ..life.bookmarks import BM_DESC_MAX, BM_MAX, BM_NOTE_MAX, BM_SITE_MAX, BM_STATES, BM_TITLE_MAX, bm_key, bm_norm_url, bm_site, bm_tags
from ..notify.taskbell import TBL_LEVELS
from .acctimport import _iso_ts, _oid, _txt, tr, umz_insert, umz_row

# the parts written here (each also in acctimport.UMZ_READ)
UMZ_MORE = ("bookmarks", "pomos", "contact_care", "view_layouts", "list_layouts", "task_bell", "task_watchers")


def umz_more_has(data):
    return any(data.get(p) for p in UMZ_MORE)


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
            run.warning(N_("A row could not be taken over: {0}"), tr(N_("Bookmarks")))
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
        if not cid:
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
            run.warning(N_("A row could not be taken over: {0}"), tr(N_("Saved arrangements")))
            continue
        _more(run, "view_layouts", nid)
    for r in data.get("list_layouts") or []:
        run.step()
        lid = run.m("lists", r.get("list_id")) if isinstance(r, dict) else None
        if not lid:
            continue
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
        if not tid or r.get("level") not in TBL_LEVELS or (_oid(r.get("set_by")) and _oid(r.get("set_by")) != me_old):
            continue
        d = {"task_id": tid, "user_id": uid, "org_id": run.list_org.get(run.task_list.get(tid)), "level": r["level"],
             "until": r.get("until") if _iso_ts(r.get("until")) else None, "set_by": uid if r.get("set_by") else None,
             "created_at": r.get("created_at") if _iso_ts(r.get("created_at")) else ts, "updated_at": ts}
        if umz_insert(c, "task_bell", d, rid=False):
            _more(run, "task_bell", {"task_id": tid})
    for r in data.get("task_watchers") or []:
        run.step()
        tid = run.m("tasks", r.get("task_id")) if isinstance(r, dict) else None
        if tid and umz_insert(c, "task_watchers", {"task_id": tid, "user_id": uid,
                                                     "created_at": r.get("created_at") if _iso_ts(r.get("created_at")) else ts}, rid=False):
            _more(run, "task_watchers", {"task_id": tid})


def umz_more_write(c, run, uid, me_old, data):
    """Inside the run's transaction (the caller commits)."""
    ts = iso(now_utc())
    run.created["more_at"] = ts  # review: a bookmark changed after the import stays with the undo
    _bookmarks(c, run, uid, data, ts)
    _pomos(c, run, uid, data, ts)
    _care(c, run, uid, data, ts)
    _layouts(c, run, uid, data, ts)
    _bells(c, run, uid, me_old, data, ts)


# what the undo removes: always only the importing person's row
_UNDO = {"bookmarks": "id", "pomos": "id", "view_layouts": "id", "contact_care": "contact_id", "list_layouts": "list_id",
         "task_bell": "task_id", "task_watchers": "task_id"}


def umz_more_undo(c, uid, cr):
    """The rows umz_more_write recorded (an arrangement or bookmark changed since stays: it is the person's own work now)."""
    n = 0
    for item in reversed(cr.get("more") or []):
        if not (isinstance(item, list) and len(item) == 2 and item[0] in _UNDO):
            continue
        table, key = item
        col = _UNDO[table]
        v = key.get(col) if isinstance(key, dict) else key
        if not isinstance(v, int):
            continue
        extra = " AND updated_at<=?" if table == "bookmarks" else " AND updated_at<=created_at" if table == "view_layouts" else ""
        n += c.execute(f"DELETE FROM {table} WHERE {col}=? AND user_id=?{extra}", (v, uid, *((cr.get("more_at") or "9999",) if table == "bookmarks" else ()))).rowcount
    return n

