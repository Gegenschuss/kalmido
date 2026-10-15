"""Contacts: several at once (2.46.1, #1554). One request deletes or moves a selection of contacts (the web client's
selection mode, /api/v1 + the MCP tool bulk_contacts). Every contact is checked before anything changes (one unknown or
foreign id -> 404, one in a read-only address book -> 403: nothing is touched); the work then runs in blocks that are
committed one by one, so 1,400 contacts neither hold the version row nor time out. The birthday / anniversary tasks of
the contacts follow (bk_occ_drop), CardDAV clients see the change through the address books' ctag + sync state."""
from flask import jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied, list_role, need_feat, WRITE_ROLES
from ..tasks.validation import as_int
from ..personal.timetrack import BadInput, UnknownFields
from ..api.v1 import v1_args, v1_json, v1_view
from ..contacts.model import book_touch, contacts_on, my_book_ids, need_book, occ_sync, CONTACTS_PER_BOOK

BULK_MAX = 5000      # contacts in one request (an address book holds up to CONTACTS_PER_BOOK; the app sends what it shows)
BULK_BLOCK = 200     # contacts per committed block


def bk_blocks(ids, n=BULK_BLOCK):
    for i in range(0, len(ids), n):
        yield ids[i:i + n]


def bk_in(ids):
    return ",".join("?" * len(ids))


def bk_occ_drop(c, uid, cids):
    """The birthday / anniversary tasks of these contacts go to the trash (when uid may change their list) and the links
    are removed: used before a contact is deleted or moves to an address book with another birthday list (one or many)."""
    from ..tasks.lifecycle import trash_task
    roles = {}
    for blk in bk_blocks(list(cids), 500):
        for r in c.execute(f"SELECT o.task_id, t.list_id FROM contact_occ o JOIN tasks t ON t.id=o.task_id "
                           f"WHERE o.contact_id IN ({bk_in(blk)}) AND t.deleted_at IS NULL", blk).fetchall():
            if r["list_id"] not in roles:
                roles[r["list_id"]] = list_role(c, r["list_id"], uid)
            if roles[r["list_id"]] in WRITE_ROLES:
                trash_task(c, r["task_id"])
        c.execute(f"DELETE FROM contact_occ WHERE contact_id IN ({bk_in(blk)})", blk)


def bk_ids(b):
    ids = b.get("ids")
    if not isinstance(ids, list) or not ids:
        raise BadInput(tr("Choose at least one contact"))
    if len(ids) > BULK_MAX:
        raise BadInput(tr("At most {0} contacts at once", BULK_MAX))
    out = {}
    for x in ids:
        out.setdefault(as_int(x, "ids", 1), None)
    return list(out)


def op_contacts_bulk(c, uid, b):
    """{ids: [...], action: delete | move, book_id (move)} -> {action, deleted} | {action, moved, unchanged, conflicts: [ids]}."""
    bad = sorted(k for k in b if k not in ("ids", "action", "book_id"))
    if bad:
        raise UnknownFields(bad)
    action = b.get("action")
    if action not in ("delete", "move"):
        raise BadInput(tr("Invalid value: {0}", "action"))
    ids = bk_ids(b)
    if not contacts_on(c, uid):
        raise Denied(404)
    books = my_book_ids(c, uid)
    rows = {}
    for blk in bk_blocks(ids, 1000):
        for r in c.execute(f"SELECT id, book_id, uid, href, bday, anniversary FROM contacts WHERE id IN ({bk_in(blk)})", blk).fetchall():
            rows[r["id"]] = r
    if any(i not in rows or rows[i]["book_id"] not in books for i in ids):
        raise Denied(404)
    if any(books[rows[i]["book_id"]] not in ("owner", "edit") for i in ids):
        raise Denied(403, tr("You can only read this address book"))
    if action == "delete":
        for blk in bk_blocks(ids):
            bk_occ_drop(c, uid, blk)
            c.execute(f"DELETE FROM contacts WHERE id IN ({bk_in(blk)})", blk)
            for bid in sorted({rows[i]["book_id"] for i in blk}):
                book_touch(c, bid)
            bump(c)
            c.commit()
        return {"action": "delete", "deleted": len(ids)}
    nb = as_int(b.get("book_id"), "book_id", 1)
    bk, _ = need_book(c, nb, write=True, uid=uid)
    seen = {(r["uid"], "u") for r in c.execute("SELECT uid FROM contacts WHERE book_id=?", (nb,)).fetchall()}
    seen |= {(r["href"], "h") for r in c.execute("SELECT href FROM contacts WHERE book_id=?", (nb,)).fetchall()}
    mv, conflicts, same = [], [], 0
    for i in ids:
        r = rows[i]
        if r["book_id"] == nb:
            same += 1
        elif (r["uid"], "u") in seen or (r["href"], "h") in seen:  # the address book has this contact already (like a single move)
            conflicts.append(i)
        else:
            mv.append(i)
            seen |= {(r["uid"], "u"), (r["href"], "h")}
    have = c.execute("SELECT COUNT(*) FROM contacts WHERE book_id=?", (nb,)).fetchone()[0]
    if mv and have + len(mv) > CONTACTS_PER_BOOK:
        raise Denied(409, tr("At most {0} contacts per address book", CONTACTS_PER_BOOK))
    occ = {r[0]: r[1] for r in c.execute(f"SELECT id, occ_list_id FROM books WHERE id IN ({bk_in(list(books))})", list(books)).fetchall()}
    for blk in bk_blocks(mv):
        # a new birthday list: the old tasks go, the target's list gets new ones (the same list: they stay)
        drop = [i for i in blk if occ.get(rows[i]["book_id"]) != bk["occ_list_id"]]
        if drop:
            bk_occ_drop(c, uid, drop)
        c.execute(f"UPDATE contacts SET book_id=?, updated_at=? WHERE id IN ({bk_in(blk)})", [nb, iso_ms(now_utc()), *blk])
        for i in drop:
            if rows[i]["bday"] or rows[i]["anniversary"]:
                occ_sync(c, i)
        for bid in sorted({rows[i]["book_id"] for i in blk} | {nb}):
            book_touch(c, bid)
        bump(c)
        c.commit()
    return {"action": "move", "moved": len(mv), "unchanged": same, "conflicts": conflicts}


@app.post("/api/contacts/bulk")
def contacts_bulk():
    need_feat("contacts")
    return jsonify(op_contacts_bulk(db(), me(), body()))


@app.post("/api/v1/contacts/bulk")
@v1_view
def v1_contacts_bulk():
    v1_args(())
    need_feat("contacts")
    return jsonify(op_contacts_bulk(db(), me(), v1_json()))
