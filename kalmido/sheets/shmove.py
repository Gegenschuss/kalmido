"""2.96.0 B (#1941): a table to the other workspace (private <-> organisation).

POST /api/sheets/<id>/move-space {to, dry, undo?} -- the rules of accounts/spacemove.py: agents never (403), the target an
organisation the person is a member of (409), the right to write the table (sheets/core.py sh_need) and, out of an
organisation, its creator or that organisation's admin (403); a private table only its owner. What does not fit the target
ends in the same transaction and is named by the dry run: the attachment to a list of the old workspace (the table would
open to the whole target space otherwise -- it is taken off), carried-over rows linked to tasks of the old workspace (the
nightly boundary check counts them: accounts/tenancy.py sheet_link; they get undone_at like an undone carry-over).
Formulas naming lists / projects / clients / tasks of the old workspace stay and show "No access" there (named). Table
cells are no orgcrypt fields (core/orgcrypt.py FIELDS): nothing to re-seal. undo = the id of the space_moves row of the move
being taken back (the same person, the way back): the list attachment and the carry-overs that fit again come back.
"""
import json
import re

from flask import jsonify

from ..core.config import app
from ..core.access import Denied, WRITE_ROLES, list_role, need_feat
from ..core.db import body, db, iso_ms, now_utc
from ..core.i18n import N_, tr, trn
from ..accounts.session import me
from ..accounts.orgs import is_org_admin
from ..accounts.spacemove import smv_answer, smv_refuse_agent, smv_same, smv_target
from .core import sh_dict, sh_need, sh_reload, sh_space_key, sh_touch

SHM_REF_RE = re.compile(r"\{(p|l|k|t):(\d{1,18})\}")
SHM_ONLY = N_("Only who created this table or an admin of the organisation can move it out of it")


def shm_ref_org(c, typ, oid, cache):
    """The workspace (org id | None) of a formula source, or False when it is gone."""
    k = (typ, oid)
    if k not in cache:
        if typ in ("p", "l"):
            r = c.execute("SELECT org_id FROM lists WHERE id=?", (oid,)).fetchone()
        elif typ == "k":
            r = c.execute("SELECT org_id FROM clients WHERE id=?", (oid,)).fetchone()
        else:
            r = c.execute("SELECT l.org_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (oid,)).fetchone()
        cache[k] = (r["org_id"] or None) if r else False
    return cache[k]


def shm_foreign_formulas(c, sid, to):
    """Cells whose formula names a source outside workspace to (a private table may use whatever its viewer sees: 0)."""
    if not to:
        return 0
    n, cache = 0, {}
    for r in c.execute("SELECT raw FROM sheet_cells WHERE sheet_id=? AND raw ILIKE '%{%:%}%'", (sid,)).fetchall():
        if any(shm_ref_org(c, m.group(1), int(m.group(2)), cache) not in (False, to) for m in SHM_REF_RE.finditer(r["raw"] or "")):
            n += 1
    return n


def shm_links_out(c, sid, to):
    """Ids of the live carry-overs (task / row) whose task lies in another workspace than to."""
    return [x[0] for x in c.execute("SELECT k.id FROM sheet_links k JOIN tasks t ON t.id=k.target_id JOIN lists l ON l.id=t.list_id "
                                    "WHERE k.sheet_id=? AND k.kind IN ('task', 'row') AND k.undone_at IS NULL "
                                    "AND l.org_id IS DISTINCT FROM ?", (sid, to)).fetchall()]


@app.post("/api/sheets/<int:sid>/move-space")
def sheets_move_space(sid):
    smv_refuse_agent()
    need_feat("sheets")
    c = db()
    uid = me()
    r = sh_need(c, sid, write=True)
    from .shbook import shb_bid, shb_member_ids, shb_move
    if shb_bid(r) != sid:  # 2.124.0 E (#2116): a further sheet moves with its table (its first sheet)
        sid = shb_bid(r)
        r = sh_need(c, sid, write=True)
    tabs = shb_member_ids(c, sid)
    b = body()
    to = smv_target(c, uid, b.get("to"))
    smv_same(r["org_id"], to)
    if r["org_id"] is None and r["owner_id"] != uid:
        raise Denied(403, tr(SHM_ONLY))
    if r["org_id"] and r["created_by"] != uid and not is_org_admin(c, uid, r["org_id"]):
        raise Denied(403, tr(SHM_ONLY))
    from ..accounts.orgout import OO_ADMIN_ONLY, org_out, org_out_ok
    if not org_out_ok(c, r["org_id"], to):  # 2.148.1 B (#2483): out of an organisation only by its admin
        raise Denied(403, tr(OO_ADMIN_ONLY))
    l = c.execute("SELECT id, name, org_id, e2e FROM lists WHERE id=?", (r["list_id"],)).fetchone() if r["list_id"] else None
    unbind = bool(l) and (l["org_id"] or None) != (to or None)
    links = [x for t in tabs for x in shm_links_out(c, t, to)]  # 2.124.0 E (#2116): every sheet of the table
    offers = sum(c.execute("SELECT COUNT(*) FROM sheet_links WHERE sheet_id=? AND kind='offer' AND undone_at IS NULL", (t,)).fetchone()[0]
                 for t in tabs)
    formulas = sum(shm_foreign_formulas(c, t, to) for t in tabs)
    shares = c.execute("SELECT COUNT(*) FROM sheet_shares WHERE sheet_id=? AND revoked_at IS NULL", (sid,)).fetchone()[0]  # 2.124.0 C (#2113)
    notes = [tr("The table is no longer attached to its list") if unbind else "",
             tr("Every member of the organisation can then open the table") if unbind and to else "",  # review 2.96 (L4)
             trn("{0} row carried over to a task of the old workspace loses its link", "{0} rows carried over to tasks of the old workspace lose their link",
                 len(links)) if links else "",
             trn("{0} quotation made from this table stays in the old workspace", "{0} quotations made from this table stay in the old workspace",
                 offers) if offers else "",
             trn("{0} formula uses lists or clients of the old workspace: it shows “No access” there",
                 "{0} formulas use lists or clients of the old workspace: they show “No access” there", formulas) if formulas else "",
             trn("{0} share with a person or agent ends", "{0} shares with people or agents end", shares) if shares else ""]  # 2.124.0 C (#2113)
    if b.get("dry"):
        return jsonify(smv_answer(notes, None, count=1))
    ts = iso_ms(now_utc())
    back, revived = None, []
    if b.get("undo") not in (None, "", 0):
        u = b.get("undo")
        if isinstance(u, bool) or not isinstance(u, int):
            raise Denied(400, tr("Invalid value: {0}", "undo"))
        x = c.execute("SELECT * FROM space_moves WHERE id=? AND kind='sheet' AND obj_id=? AND by_id=?", (u, sid, uid)).fetchone()
        if x and (x["from_org"] or None) == (to or None) and (x["to_org"] or None) == (r["org_id"] or None):
            try:
                back = json.loads(x["detail"] or "{}")
            except ValueError:
                back = {}
    list_id = None if unbind else r["list_id"]
    if back and back.get("list_id") and not r["list_id"]:
        k = c.execute("SELECT org_id, e2e FROM lists WHERE id=?", (back["list_id"],)).fetchone()
        # review 2.96 (L2): only a list the person may still write in (like re-binding by hand, sh_may_rebind)
        if k and (k["org_id"] or None) == (to or None) and k["e2e"] is None and list_role(c, back["list_id"], uid) in WRITE_ROLES:
            list_id = back["list_id"]
    org_out(c, r["org_id"], to, "sheet", r["title"])  # 2.148.1 B (#2483): logged, the organisation's other admins told
    c.execute("UPDATE sheets SET org_id=?, owner_id=?, list_id=? WHERE id=?", (to, None if to else uid, list_id, sid))
    if shares:  # 2.124.0 C (#2113): every share ends (the people / agents belong to the old workspace; share again there)
        from .shshare import shs_end
        shs_end(c, sid)
    from .shkinds import shk_move_files
    shk_move_files(c, sid, to, uid)  # 2.124.0 B (#2110): the files of file cells go along, sealed with the target's key
    shb_move(c, sid, to, uid)  # 2.124.0 E (#2116): the further sheets follow (space, list, their files)
    if links:
        c.execute(f"UPDATE sheet_links SET undone_at=? WHERE id IN ({','.join('?' * len(links))})", [ts, *links])
    if back and back.get("links"):
        ids = [i for i in back["links"] if isinstance(i, int)][:2000]
        if ids:
            c.execute(f"UPDATE sheet_links SET undone_at=NULL WHERE sheet_id IN ({','.join('?' * len(tabs))}) AND id IN ({','.join('?' * len(ids))}) "
                      f"AND undone_at=?", [*tabs, *ids, back.get("at") or ""])  # 2.124.0 E (#2116): + the further sheets
            still = {x for t in tabs for x in shm_links_out(c, t, to)}
            revived = [i for i in ids if i not in still]
            out = [i for i in ids if i not in revived]
            if out:  # a task moved on in between: its link stays ended
                c.execute(f"UPDATE sheet_links SET undone_at=? WHERE id IN ({','.join('?' * len(out))})", [ts, *out])
    detail = {"list_id": r["list_id"] if unbind else None, "links": links, "at": ts}
    from ..core.pg import insert_id
    mid = insert_id(c, "INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES('sheet',?,?,?,?,?,?)",
                    (sid, r["org_id"], to, uid, ts, json.dumps(detail)))
    sh_touch(c, sid, uid)
    c.commit()
    d = sh_dict(c, sh_reload(c, sid))
    return jsonify(smv_answer(notes, None, ok=True, move_id=mid, from_space=sh_space_key(r["org_id"]), space=sh_space_key(to),
                              sheet=d, revived=len(revived)))


def shm_last(c, sid):
    """The last move of table sid between workspaces (its history line), or None. The caller checked the table is visible."""
    r = c.execute("SELECT from_org, to_org, by_id, at FROM space_moves WHERE kind='sheet' AND obj_id=? ORDER BY id DESC LIMIT 1",
                  (sid,)).fetchone()
    if not r:
        return None
    from ..collab.comments import user_names
    from ..wiki.wkmove import wkr_line  # 2.97.0 D (#2051): workspaces by name, only those of the viewer
    return wkr_line(c, r, user_names(c, [r["by_id"]]).get(r["by_id"], ""))
