"""2.52.0 C (#1438): address books an organisation owns (books.owner_org_id). A person's address book of an organisation's
workspace goes to the organisation on request ("Hand over to the organisation", its admins only, nothing moves by itself);
an organisation admin can make it personal again (their own book). The rights follow the organisation's roles (contacts/
model.py book_role): admins manage, members read or change as the book's org_role says, shares add to that. owner_id stays
filled (the manager: whose lists the birthdays go to) and is handed on when that person leaves the organisation or their
account is deleted, so the book, its contacts, its birthday list and the links to tasks stay."""
from flask import g, jsonify

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import body, bump, db
from ..core.pg import system_ctx
from ..accounts.session import me
from ..core.access import Denied, list_role, need_feat, WRITE_ROLES
from ..personal.timetrack import BadInput
from ..contacts.model import book_public, book_touch, need_book, obk_can_take

OBK_ROLES = ("view", "edit", "none")


def obk_heir(c, oid, uid):
    """Who manages organisation oid's address books after uid: an admin of it, else another member (people only, no kid
    accounts, no agents, not disabled), or None."""
    with system_ctx(c):  # the members of the organisation (an instance admin deletes accounts of organisations they are not in)
        r = c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.user_id!=?
                         AND COALESCE(u.kind, 'user')!='agent' AND u.kid=0 AND u.disabled=0
                         AND NOT EXISTS (SELECT 1 FROM agents a WHERE a.user_id=m.user_id)
                         ORDER BY (m.role='admin') DESC, m.user_id LIMIT 1""", (oid, uid)).fetchone()
    return r[0] if r else None


def obk_hand_on(c, bid, heir):
    c.execute("DELETE FROM book_members WHERE book_id=? AND user_id=?", (bid, heir))  # the manager needs no share of its own
    c.execute("UPDATE books SET owner_id=? WHERE id=?", (heir, bid))
    # 2.52.0 review: a birthday list the new manager cannot write (e.g. the old manager's private list) is unset, so the
    # book shows "no birthday list" and an admin picks one, instead of occ_sync skipping silently
    r = c.execute("SELECT occ_list_id FROM books WHERE id=?", (bid,)).fetchone()
    if r and r[0] and list_role(c, r[0], heir) not in WRITE_ROLES:
        c.execute("UPDATE books SET occ_list_id=NULL WHERE id=?", (bid,))


def obk_leave(c, oid, uid, heir):
    """uid leaves organisation oid (accounts/orgs.py org_leave, before its own hand-over): the organisation's address books
    uid manages get another manager (heir when it is a person of the organisation, else obk_heir). Nobody left: the book
    becomes uid's own again (it then leaves the organisation like before 2.52.0). The caller commits."""
    with system_ctx(c):  # the instance admin takes people out of organisations they need not be in (orgs.py _set_members)
        for (bid,) in c.execute("SELECT id FROM books WHERE owner_id=? AND owner_org_id=?", (uid, oid)).fetchall():
            h = heir if heir and heir != uid and _person_in(c, oid, heir) else obk_heir(c, oid, uid)
            if h:
                obk_hand_on(c, bid, h)
            else:
                c.execute("UPDATE books SET owner_org_id=NULL WHERE id=?", (bid,))


def obk_user_purge(c, uid):
    """Account uid is deleted (accounts/users.py user_purge): the organisations' address books it manages get another
    manager, so they do not go with the account (ON DELETE CASCADE). Without anybody left they go as before."""
    with system_ctx(c):  # every organisation (the instance admin deletes the account)
        rows = c.execute("SELECT id, owner_org_id FROM books WHERE owner_id=? AND owner_org_id IS NOT NULL", (uid,)).fetchall()
        for bid, oid in rows:
            h = obk_heir(c, oid, uid)
            if h:
                obk_hand_on(c, bid, h)


def _person_in(c, oid, uid):
    with system_ctx(c):  # membership structure of the organisation (the heir need not be visible to the caller)
        return bool(c.execute("""SELECT 1 FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? AND m.user_id=?
                                 AND COALESCE(u.kind, 'user')!='agent' AND u.kid=0""", (oid, uid)).fetchone())


def _need_person():
    from ..agents.core import is_agent
    need_feat("contacts")
    if is_agent(g.user):
        raise Denied(403, tr("Agents cannot use this endpoint"))


def _org_role(b, cur="view"):
    v = b.get("org_role", cur)
    if v not in OBK_ROLES:
        raise BadInput(tr("Invalid value: {0}", "org_role"))
    return v


def _answer(c, bid, uid):
    return jsonify(book_public(c, c.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone(), uid))


@app.post("/api/books/<int:bid>/org")
def obk_take(bid):
    """{org_role?: view | edit | none} -- the owner of a person's address book in an organisation's workspace, an admin of
    that organisation, hands it over to the organisation (a mirrored book of an outside account never). Without org_role
    the book keeps the one it had (the undo of "make personal again")."""
    _need_person()
    c, b, uid = db(), body(), me()
    bk, role = need_book(c, bid, manage=True)
    if bk["owner_org_id"]:
        raise Denied(409, tr("This address book already belongs to the organisation"))
    if bk["src_id"] or not bk["org_id"]:
        raise Denied(409, tr("Only an address book of an organisation's workspace can be handed over to it"))
    if not obk_can_take(c, uid, bk["org_id"]):
        raise Denied(403, tr("Only an admin of this organisation can do this"))
    c.execute("UPDATE books SET owner_org_id=?, org_role=? WHERE id=?", (bk["org_id"], _org_role(b, bk["org_role"] or "view"), bid))
    book_touch(c, bid)
    bump(c)
    c.commit()
    print("address book", bid, "handed over to organisation", bk["org_id"], "by", uid, flush=True)
    return _answer(c, bid, uid)


@app.patch("/api/books/<int:bid>/org")
def obk_edit(bid):
    """{org_role: view | edit | none} -- an admin of the organisation sets what its members may in its address book."""
    _need_person()
    c, b, uid = db(), body(), me()
    bk, role = need_book(c, bid, manage=True)
    if not bk["owner_org_id"]:
        raise Denied(409, tr("This address book does not belong to an organisation"))
    if "org_role" not in b:
        raise BadInput(tr("Invalid value: {0}", "org_role"))
    c.execute("UPDATE books SET org_role=? WHERE id=?", (_org_role(b), bid))
    book_touch(c, bid)
    bump(c)
    c.commit()
    return _answer(c, bid, uid)


OBK_STAYS = N_("The address book stays with the organisation. Export or copy the contacts instead.")


@app.delete("/api/books/<int:bid>/org")
def obk_drop(bid):
    """An admin of the organisation makes its address book a person's book again: their own (it stays in the organisation's
    workspace; the members keep only what is shared with them). The way back of the hand-over."""
    _need_person()
    c, uid = db(), me()
    bk, role = need_book(c, bid, manage=True)
    if not bk["owner_org_id"]:
        raise Denied(409, tr("This address book does not belong to an organisation"))
    if bk["owner_id"] != uid:  # 2.148.1 B (#2491): only the undo of one's own hand-over; nobody takes the organisation's book
        raise Denied(403, tr(OBK_STAYS))
    c.execute("DELETE FROM book_members WHERE book_id=? AND user_id=?", (bid, uid))
    c.execute("UPDATE books SET owner_org_id=NULL, owner_id=? WHERE id=?", (uid, bid))
    book_touch(c, bid)
    bump(c)
    c.commit()
    print("address book", bid, "of organisation", bk["owner_org_id"], "made personal by", uid, flush=True)
    return _answer(c, bid, uid)
