"""2.365.1 (#3395): leaving an organisation (or being removed) takes along what the person brought in from their private space.

Projects do since 2.361.0 (lists.brought_by, accounts/orgs.py ol_private). Tables, files and folders, knowledge pages, video
reviews, polls and bookmarks follow the same way: their move-space routes note the person in brought_by on the way private ->
organisation and clear it on every way out; org_leave calls olb_home. Each area's own helper (shm_home, fsm_home_plans +
fsm_apply, wkm_home, vdr_home, tpo_home, bm_home) has the same consequences as its route, without a dialog: shares end, a
project of the organisation lets go, files are sealed with the account key, a name taken gets " (2)". Things in the trash stay.

What stays although it was brought in (olb_preview counts it as kept): pages of a space with a lock (the server cannot encrypt
them again), locked folders, receipts in the books, a link already saved privately -- the request of accounts/orgoutreq.py
is their way back. Office clients and drafts never go by themselves: they hang at the organisation's documents.
Without a mark nothing goes: a thing made in the organisation, or brought in before the mark and without a row in space_moves
(files: fsmove writes that row only when something ends), is the organisation's. No guessing from created_by.
"""
from flask import after_this_request, has_request_context

from ..core.pg import system_ctx
from ..core.orgcrypt import OrgCryptError
from ..core.access import Denied
from ..core.serializers import unlink_files

OLB_FILL = (("sheets", "sheet"), ("wiki_pages", "wiki"), ("video_reviews", "video"), ("sched_polls", "poll"), ("bookmarks", "bookmark"))


def olb_backfill(c):
    """Once at the start: the mark of what came in before it existed, from the last move of each thing (space_moves): private ->
    today's organisation = by_id brought it in."""
    n = 0
    with system_ctx(c):
        for table, kind in OLB_FILL:
            n += c.execute(f"""UPDATE {table} t SET brought_by=m.by_id FROM
                               (SELECT DISTINCT ON (obj_id) obj_id, from_org, to_org, by_id FROM space_moves WHERE kind=? ORDER BY obj_id, id DESC) m
                               WHERE m.obj_id=t.id AND m.from_org IS NULL AND m.to_org=t.org_id AND m.by_id IS NOT NULL AND t.brought_by IS NULL""",
                           (kind,)).rowcount
    return n


def olb_plan(c, oid, uid):
    """What of uid goes back from organisation oid: {area: rows}, files = plans of files/fsmove.py; kept = how many stay."""
    from ..files.fsmove import fsm_home_plans
    from ..life.bookmarks import bm_home_rows
    from ..wiki.wkmove import wkm_home_rows
    files, kept = fsm_home_plans(c, oid, uid)
    wiki, k2 = wkm_home_rows(c, oid, uid)
    marks, k3 = bm_home_rows(c, oid, uid)
    q = "WHERE org_id=? AND brought_by=? AND deleted_at IS NULL ORDER BY id"
    return {"sheet": c.execute(f"SELECT * FROM sheets {q}", (oid, uid)).fetchall(), "file": files, "wiki": wiki,
            "video": c.execute(f"SELECT * FROM video_reviews {q}", (oid, uid)).fetchall(),
            "poll": c.execute(f"SELECT * FROM sched_polls {q}", (oid, uid)).fetchall(), "bookmark": marks, "kept": kept + k2 + k3}


def olb_preview(c, oid, uid):
    """The numbers of leave-info: ({key of OLV_STAYS + folders: n}, {key: ids that go}, how many stay although brought in)."""
    from ..sheets.shbook import shb_member_ids
    with system_ctx(c):
        p = olb_plan(c, oid, uid)
        moved = [r for f in p["file"] for r, _ in f["moved"]]
        files = [r["id"] for r in moved if r["kind"] == "file"]
        gone = {"files": files, "wiki_pages": [r["id"] for r in p["wiki"]], "tables": [i for r in p["sheet"] for i in shb_member_ids(c, r["id"])],
                "bookmarks": [r["id"] for r in p["bookmark"]], "polls": [r["id"] for r in p["poll"]], "videos": [r["id"] for r in p["video"]]}
    counts = {"files": len(files), "folders": len(moved) - len(files), "wiki_pages": len(gone["wiki_pages"]), "tables": len(p["sheet"]),
              "bookmarks": len(gone["bookmarks"]), "polls": len(gone["polls"]), "videos": len(gone["videos"])}
    return {k: v for k, v in counts.items() if v}, gone, p["kept"]


def olb_home(c, oid, uid, back=None):
    """Everything uid brought into organisation oid (and may go by itself) goes back into their private space: [kind, id] appended
    to back; one log row + News per area for the organisation's admins. The caller commits; the old stored files go after it.
    What fails (a text or file that cannot be opened ...) stays in the organisation and never stops the leaving."""
    from ..calendars.polls import tpo_home
    from ..files.fsmove import fsm_apply
    from ..life.bookmarks import bm_home
    from ..sheets.shmove import shm_home
    from ..videos.review import vdr_home
    from ..wiki.wkmove import wkm_home
    back = [] if back is None else back
    names, old, made = {}, [], []

    def one(kind, rows, go):
        """go(new stored files, old stored files) in a savepoint for the thing(s) rows: [(id, name)]."""
        new, mine = [], []
        try:
            with c.savepoint():
                if go(new, mine) is False:
                    return
        except (Denied, OrgCryptError, OSError) as e:
            print("leaving: stays in the organisation:", kind, type(e).__name__, flush=True)
            unlink_files(new)
            return
        old.extend(mine)
        made.extend(new)
        back.extend([kind, i] for i, _ in rows)
        names.setdefault(kind, []).extend(str(n or "") for _, n in rows)
    with system_ctx(c):  # the rows of a person who may be somebody else than the signed-in admin
        p = olb_plan(c, oid, uid)
        for r in p["sheet"]:
            one("sheet", [(r["id"], r["title"])], lambda new, mine, r=r: shm_home(c, r, uid, new, mine))
        for f in p["file"]:
            n = f["roots"][0][0]
            one("file", [(n["id"], n["name"])], lambda new, mine, f=f: fsm_apply(c, uid, f, None, new, mine))
        if p["wiki"]:
            one("wiki", [(r["id"], r["path"]) for r in p["wiki"]], lambda new, mine: wkm_home(c, oid, uid, p["wiki"], new, mine))
        for r in p["video"]:
            one("video", [(r["id"], r["title"])], lambda new, mine, r=r: vdr_home(c, r, uid))
        for r in p["poll"]:
            one("poll", [(r["id"], r["title"])], lambda new, mine, r=r: tpo_home(c, r, uid))
        for r in p["bookmark"]:
            one("bookmark", [(r["id"], r["title"] or r["url"])], lambda new, mine, r=r: bm_home(c, r, uid, mine))
        real = (c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone() or [""])[0] if names else ""
    from .orgout import oo_note
    for kind, ns in names.items():
        oo_note(c, oid, real, kind, ", ".join(ns)[:200], back=True)
    if (old or made) and has_request_context():
        @after_this_request
        def _clean(resp):
            unlink_files(old if resp.status_code < 400 else made)  # committed: the old files go; rolled back: the new ones
            return resp
    return back
