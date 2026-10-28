"""2.401.0 (#2924): a project into another workspace -- the dry run of the list dialog's workspace field, and what goes along.

POST /api/lists/<id>/move-space {to, dry: 1} -- the rules of accounts/spacemove.py (agents never, the target an organisation the
person is a member of and may write in) and of accounts/orgs.py list_org_set (the owner only). The answer {notes, block} is the
one of every other move-space route (static/js/spacemove.js shows it): block = what list_org_set would refuse (the basket,
Home & life, a member or agent who does not fit; out of an organisation without its admin = 403 with out_request); notes =
what the move ends and Undo brings back (tasks/movememo.py lmm_*: the client of the old workspace, "also in" links across the
boundary, the opening to the organisation), what goes along (customer reports) and what stays in the old workspace (attached
tables, video reviews, office documents and deals, approval links, receipts: each has its own move). The move itself stays
PATCH /api/lists/<id> {org_id}.

lmv_follow runs inside every workspace change of a list (list_org_set, folder_apply): the customer reports (portal_tickets,
pt_find reads them only in the space of their task's list) and the task bells (task_bell, ignored in another workspace) of
its tasks go along; a report's client of another workspace is unbound (lmm keeps it for the way back).
"""
from flask import jsonify

from ..core.config import app
from ..core.access import Denied, need_list
from ..core.db import body, db
from ..core.i18n import tr, trn
from ..accounts.session import me
from ..accounts.spacemove import smv_answer, smv_refuse_agent, smv_same, smv_target


def lmv_follow(c, lid, old_org):
    """List lid just changed its workspace (from old_org): its tasks' customer reports and bells that lived in the old space
    go along. Returns the number of reports moved. The caller commits."""
    l = c.execute("SELECT org_id, owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not l or (l["org_id"] or None) == (old_org or None):
        return 0
    oid, owner = l["org_id"] or None, None if l["org_id"] else l["owner_id"]
    n = c.execute("""UPDATE portal_tickets SET org_id=?, owner_id=? WHERE task_id IN (SELECT id FROM tasks WHERE list_id=?)
                     AND org_id IS NOT DISTINCT FROM ?""", (oid, owner, lid, old_org or None)).rowcount
    from ..team.clients import _org_boundary
    if n and _org_boundary(c):  # a client of another workspace is no client of the report there (tenancy portal_client)
        c.execute("""UPDATE portal_tickets SET client_id=NULL WHERE task_id IN (SELECT id FROM tasks WHERE list_id=?)
                     AND client_id IS NOT NULL AND client_id NOT IN (SELECT id FROM clients WHERE org_id IS NOT DISTINCT FROM ?)""",
                  (lid, oid))
    c.execute("""UPDATE task_bell SET org_id=? WHERE task_id IN (SELECT id FROM tasks WHERE list_id=?)
                 AND org_id IS NOT DISTINCT FROM ?""", (oid, lid, old_org or None))
    return n


def _fits_sql(alias, to, owner):
    """SQL + args: an office row (alias.org_id) belongs to workspace to (None = the owner's personal office)."""
    if to:
        return f"{alias}.org_id=?", [to]
    return f"{alias}.org_id IN (SELECT id FROM orgs WHERE personal_of=?)", [owner]


def lmv_notes(c, lid, lr, to):
    """The notes of the dry run of list lid (row lr) going to workspace to."""
    from ..team.clients import _org_boundary
    from ..accounts.orgout import oo_into_note
    notes = []
    if lr["client_id"] and _org_boundary(c) and not c.execute(
            "SELECT 1 FROM clients WHERE id=? AND org_id IS NOT DISTINCT FROM ?", (lr["client_id"], to)).fetchone():
        notes.append(tr("The client of the project is taken off (Undo brings it back)"))
    links = c.execute("""SELECT COUNT(*) FROM task_links k JOIN tasks t ON t.id=k.task_id JOIN lists o ON o.id=t.list_id
                         JOIN lists x ON x.id=k.list_id WHERE (k.list_id=? OR t.list_id=?)
                         AND (CASE WHEN k.list_id=? THEN o.org_id ELSE x.org_id END) IS DISTINCT FROM ?""",
                      (lid, lid, lid, to)).fetchone()[0]
    if links:
        notes.append(trn("{0} link to another project ends (Undo brings it back)", "{0} links to other projects end (Undo brings them back)", links))
    if lr["org_visibility"]:
        notes.append(tr("It is no longer open to everyone in the organisation (Undo brings it back)"))
    tickets = c.execute("""SELECT COUNT(*) FROM portal_tickets WHERE task_id IN (SELECT id FROM tasks WHERE list_id=? AND deleted_at IS NULL)
                           AND org_id IS NOT DISTINCT FROM ?""", (lid, lr["org_id"])).fetchone()[0]
    if tickets:
        notes.append(trn("{0} customer report moves along", "{0} customer reports move along", tickets))
    stay = []
    n = c.execute("SELECT COUNT(*) FROM sheets WHERE list_id=? AND deleted_at IS NULL AND org_id IS DISTINCT FROM ?", (lid, to)).fetchone()[0]
    if n:
        stay.append(trn("{0} table", "{0} tables", n))
    n = c.execute("SELECT COUNT(*) FROM video_reviews WHERE list_id=? AND deleted_at IS NULL AND org_id IS DISTINCT FROM ?", (lid, to)).fetchone()[0]
    if n:
        stay.append(trn("{0} video review", "{0} video reviews", n))
    w, a = _fits_sql("d", to, lr["owner_id"])
    n = c.execute(f"SELECT COUNT(*) FROM office_docs d WHERE d.list_id=? AND NOT ({w})", (lid, *a)).fetchone()[0]
    if n:
        stay.append(trn("{0} office document", "{0} office documents", n))
    n = c.execute(f"SELECT COUNT(*) FROM office_deals d WHERE d.list_id=? AND d.deleted_at IS NULL AND NOT ({w})", (lid, *a)).fetchone()[0]
    if n:
        stay.append(trn("{0} deal", "{0} deals", n))
    n = c.execute(f"SELECT COUNT(*) FROM office_signoffs d WHERE d.list_id=? AND d.revoked_at IS NULL AND NOT ({w})", (lid, *a)).fetchone()[0]
    if n:
        stay.append(trn("{0} approval link", "{0} approval links", n))
    n = c.execute("SELECT COUNT(*) FROM rc_receipts WHERE list_id=? AND org_id IS DISTINCT FROM ?", (lid, to)).fetchone()[0]
    if n:
        stay.append(trn("{0} receipt", "{0} receipts", n))
    if stay:
        notes.append(tr("Stays in the old workspace and is no longer linked to the project: {0}. Move it on its own if needed.", ", ".join(stay)))
    notes.append(oo_into_note(c, lr["org_id"], to))
    return notes


@app.post("/api/lists/<int:lid>/move-space")
def list_move_space(lid):
    """{to, dry: 1} -> {notes, block, count} (see the module text). Only the dry run: the move is PATCH /api/lists/<id> {org_id}."""
    smv_refuse_agent()
    c = db()
    uid = me()
    b = body()
    if not b.get("dry"):
        raise Denied(400, tr("Invalid value: {0}", "dry"))
    need_list(c, lid, write=False)
    lr = c.execute("SELECT owner_id, is_inbox, family, life, org_id, client_id, org_visibility FROM lists WHERE id=?", (lid,)).fetchone()
    if lr["owner_id"] != uid:
        raise Denied(403, tr("Only the owner can change the workspace of a project"))
    to = smv_target(c, uid, b.get("to"))
    smv_same(lr["org_id"], to)
    from ..accounts.orgs import WS_MSG_PRIVATE_ONLY, ws_member_problem
    from ..accounts.orgout import oo_denied, org_out_ok
    if lr["is_inbox"] and to:
        return jsonify(smv_answer([], tr("The basket is always private"), count=1))
    if to and (lr["family"] or (lr["life"] and lr["life"] != "travel")):
        return jsonify(smv_answer([], tr(WS_MSG_PRIVATE_ONLY), count=1))
    if not org_out_ok(c, lr["org_id"], to, "list", lid):  # 2.148.1 B (#2483): out of an organisation only by its admin
        raise oo_denied(c, lr["org_id"], to, "list", lid)
    for (m,) in c.execute("SELECT user_id FROM list_members WHERE list_id=? ORDER BY user_id", (lid,)).fetchall():
        p = ws_member_problem(c, lid, m, org_id=to or 0)
        if p:
            return jsonify(smv_answer([], p, count=1))
    return jsonify(smv_answer(lmv_notes(c, lid, lr, to), None, count=1))
