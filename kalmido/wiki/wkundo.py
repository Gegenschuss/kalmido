"""2.778.0 (#5253): undo across devices, stage 5 -- a person's save of a knowledge page as a pointer step (core/undodiff.py,
mode "ref").

A save of the page's text (PATCH /api/wiki/pages/<id> with body, a version restored) points to the page's own history
(wiki/wkhist.py wiki_versions): {b: the version before the save, a: the version it left}. No second copy. The saves of the
same person within WKH_MERGE share one version, so they share one step too (a save that leaves the same pair adds nothing).
Taking it back = the text of version b saved as a new version (as the version list's "Restore" does), forward again = the
text of version a the same way. Conflict = the version number: the page's newest version must still be the one the step
(or its undo) left and hold the page's text; a save of someone else since = 409 naming who, the text stays. The rights are
the ones of now (wiki_need write). Spaces with the lock keep no history and record no step; a page without an earlier
version (its first save) records none either (nothing to point back to; the browser's "Created" step stays)."""
import json

from ..collab.comments import user_names
from ..core.access import Denied
from ..core.i18n import tr
from ..core.pg import write_lock
from ..core.undodiff import ug_diff_add, undo_diff_reg, undo_person
from ..core.undogroups import UG_LABEL, UG_TRACKED
from ..core.undoweb import UG_GONE
from ..core.writes import UNDO_NOTHING
from .pages import wiki_need
from .wkhist import WikiUnreadable, _locked, _vbody, wkh_body, wkh_put_text

WKU_KIND = "wiki"  # the page's kind in the core's history (wkhist.py WKH_KIND)
WKU_AREA = "wiki"
WKU_CHANGED = "Changed in the meantime by {0}"  # an existing text (wkhist.py wkh_restore)


def _two(c, pid):
    return [r[0] for r in c.execute("SELECT id FROM wiki_versions WHERE page_id=? ORDER BY id DESC LIMIT 2", (int(pid),)).fetchall()]


def wku_pre(c, pid):
    """The page's newest version id before a save (None without one): wku_note tells a merged save from a new version."""
    vs = _two(c, pid)
    return vs[0] if vs else None


def wku_note(c, r, before_text, uid, pre):
    """After a person's save of page row r (wkh_note ran; pre = wku_pre before it): one pointer part {b, a} unless nothing
    changed, the space is locked or there is no earlier version. A save merged into the newest version (WKH_MERGE) belongs
    to the step that made that version: nothing new -- unless an undo made it (its text = the step's version b), then the
    new step points back to that b."""
    if undo_person(c) != uid or _locked(r):
        return
    vs = _two(c, r["id"])
    if len(vs) < 2:
        return
    cur = c.execute("SELECT * FROM wiki_pages WHERE id=?", (r["id"],)).fetchone()
    if cur is None or _locked(cur) or wkh_body(c, cur) == before_text:
        return
    data = {"b": vs[1], "a": vs[0]}
    if pre is not None and vs[0] == pre:  # merged into the version there was
        last = c.execute("SELECT snap, state FROM obj_undo WHERE user_id=? AND kind=? AND ref_id=? AND mode='ref' "
                         "AND group_id IS NOT NULL ORDER BY id DESC LIMIT 1", (int(uid), WKU_KIND, int(r["id"]))).fetchone()
        try:
            prev = json.loads(last["snap"]) if last else {}
        except ValueError:
            prev = {}
        if last is not None and last["state"] == "done" and prev.get("a") == vs[0]:
            return  # the same merged version: that step takes this save back too
        if prev.get("u") == vs[0] and prev.get("b"):
            data["b"] = prev["b"]  # the version an undo made: its text is the one of the step's b
    name = str(cur["path"] or "").rsplit("/", 1)[-1]
    ug_diff_add(c, uid, WKU_KIND, r["id"], r["org_id"] or None, WKU_AREA, (UG_LABEL, [name]), data, mode="ref")


def wku_run(c, uid, pid, data, redo):
    """core/undodiff.py run: the page back to version b (redo: to version a), saved as a new version."""
    write_lock(c, f"wiki-{int(pid)}")  # the lock of the page's saves (pages.py wiki_update), before reading it
    r = wiki_need(c, int(pid), write=True)
    if _locked(r):
        raise Denied(403)
    want = data.get("u") if redo else data.get("a")
    to = data.get("a") if redo else data.get("b")
    vs = _two(c, pid)
    try:
        cur = wkh_body(c, r)
        v = c.execute("SELECT * FROM wiki_versions WHERE id=? AND page_id=?", (want, int(pid))).fetchone() if want else None
        same = v is not None and _vbody(c, v) == cur
    except WikiUnreadable:
        raise Denied(404, tr(UG_GONE)) from None
    if not want or not vs or vs[0] != want or not same:  # saved elsewhere since (another version, or the text moved on)
        who = user_names(c, [r["updated_by"]]).get(r["updated_by"]) or "?"
        raise Denied(409, tr(WKU_CHANGED, who))
    t = c.execute("SELECT * FROM wiki_versions WHERE id=? AND page_id=?", (to, int(pid))).fetchone() if to else None
    if t is None:
        raise Denied(404, tr(UG_GONE))  # the version went (at most WKH_KEEP per page)
    try:
        text = _vbody(c, t)
    except WikiUnreadable:
        raise Denied(404, tr(UG_GONE)) from None
    if text == cur:
        raise Denied(409, tr(UNDO_NOTHING))
    wkh_put_text(c, r, text, uid)
    now = _two(c, pid)[0]
    return ({**data, "a": now} if redo else {**data, "u": now}), []


undo_diff_reg(WKU_KIND, wku_run, WKU_AREA)
UG_TRACKED.setdefault(WKU_KIND, "wiki_pages")  # the watchdog drops the steps of a page deleted for good (ug_drop_orphans)
