"""Contacts: several at once (2.46.1, #1554). One request deletes or moves a selection of contacts (the web client's
selection mode, /api/v1 + the MCP tool bulk_contacts). Every contact is checked before anything changes (one unknown or
foreign id -> 404, one in a read-only address book -> 403: nothing is touched); the work then runs in blocks that are
committed one by one, so 1,400 contacts neither hold the version row nor time out. The birthday / anniversary tasks of
the contacts follow (bk_occ_drop), CardDAV clients see the change through the address books' ctag + sync state."""
import json
import re

from flask import jsonify

from ..core.config import app
from ..core.i18n import N_, tr
from ..core.db import body, bump, db, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied, list_role, need_feat, WRITE_ROLES
from ..tasks.validation import as_int
from ..personal.timetrack import BadInput, UnknownFields
from ..api.v1 import v1_args, v1_json, v1_view
from ..contacts.model import book_touch, contacts_on, my_book_ids, need_book, occ_sync, search_text, CONTACTS_PER_BOOK, FIELD_MAX, ITEMS_MAX, NOTE_MAX

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


def bk_gate(c, title, n):
    """2.46.1 review: an agent's bulk change of APPROVAL_BATCH_MIN or more contacts waits for a person (202), like task batches."""
    from ..api.scopes import APPROVAL_BATCH_MIN, need_approval
    if n >= APPROVAL_BATCH_MIN:
        need_approval(c, title, (n,))


# 2.47.3 (#1731): action set changes properties of many contacts at once (groups added / removed, company, department,
# kind, a note appended); action restore puts the values back that set answered with (the client's one undo step).
# Contacts in read-only or imported (mirrored) address books are skipped and counted, not a 403 like delete / move.
MS_SET_KEYS = ("groups_add", "groups_remove", "org", "dept", "kind", "note_append")
MS_RESTORE_COLS = ("groups", "org", "dept", "kind", "note")


def ms_groups(v, k):
    if v is None:
        return []
    if not isinstance(v, list) or len(v) > ITEMS_MAX or any(not isinstance(x, str) for x in v):
        raise BadInput(tr("Invalid value: {0}", k))
    return list(dict.fromkeys(re.sub(r"[\x00-\x1f\x7f,]", " ", x).strip()[:100] for x in v if x.strip()))


def ms_text(v, k, n):
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", k))
    return re.sub(r"[\x00-\x1f\x7f]", " ", v).strip()[:n]


def ms_set_spec(b):
    """The validated change of action set: {groups_add, groups_remove, org?, dept?, kind?, note_append?}."""
    f = {"groups_add": ms_groups(b.get("groups_add"), "groups_add"), "groups_remove": ms_groups(b.get("groups_remove"), "groups_remove")}
    for k in ("org", "dept"):
        if b.get(k) is not None:
            f[k] = ms_text(b[k], k, FIELD_MAX)
    if b.get("kind") is not None:
        if b["kind"] not in ("individual", "org"):
            raise BadInput(tr("Invalid value: {0}", "kind"))
        f["kind"] = b["kind"]
    if b.get("note_append") is not None:
        if not isinstance(b["note_append"], str):
            raise BadInput(tr("Invalid value: {0}", "note_append"))
        v = b["note_append"].replace("\x00", "").strip()
        if v:
            f["note_append"] = v[:NOTE_MAX]
    if not (f["groups_add"] or f["groups_remove"] or len(f) > 2):
        raise BadInput(tr("Nothing to change"))
    return f


def ms_apply(r, f):
    """The new columns of contact row r under change f (only those that differ) and the old values of them (for the undo)."""
    new = {}
    if f["groups_add"] or f["groups_remove"]:
        try:
            g = json.loads(r["groups"] or "[]")
        except ValueError:
            g = []
        drop = {x.casefold() for x in f["groups_remove"]}
        g2 = [x for x in g if x.casefold() not in drop]
        have = {x.casefold() for x in g2}
        g2 += [x for x in f["groups_add"] if x.casefold() not in have]
        if g2 != g:
            new["groups"] = json.dumps(g2[:ITEMS_MAX], ensure_ascii=False)
    for k in ("org", "dept", "kind"):
        if k in f and r[k] != f[k]:
            new[k] = f[k]
    if "note_append" in f:
        new["note"] = ((r["note"].rstrip() + "\n\n" if r["note"].strip() else "") + f["note_append"])[:NOTE_MAX]
    return new, {k: (json.loads(r[k] or "[]") if k == "groups" else r[k]) for k in new}


def ms_restore_items(b):
    items = b.get("items")
    if not isinstance(items, list) or not items:
        raise BadInput(tr("Choose at least one contact"))
    if len(items) > BULK_MAX:
        raise BadInput(tr("At most {0} contacts at once", BULK_MAX))
    out = {}
    for it in items:
        if not isinstance(it, dict) or any(k not in ("id", *MS_RESTORE_COLS) for k in it):
            raise BadInput(tr("Invalid value: {0}", "items"))
        v = {}
        for k in MS_RESTORE_COLS:
            if k not in it:
                continue
            if k == "groups":
                v[k] = json.dumps(ms_groups(json.loads(it[k]) if isinstance(it[k], str) else it[k], k), ensure_ascii=False)
            elif k == "kind":
                if it[k] not in ("individual", "org", "group"):
                    raise BadInput(tr("Invalid value: {0}", k))
                v[k] = it[k]
            elif k == "note":
                if not isinstance(it[k], str):
                    raise BadInput(tr("Invalid value: {0}", k))
                v[k] = it[k].replace("\x00", "")[:NOTE_MAX]
            else:
                v[k] = ms_text(it[k], k, FIELD_MAX)
        out[as_int(it.get("id"), "id", 1)] = v
    return out


def ms_write(c, rows, todo):
    """Writes {id: columns} in committed blocks (search text, the books' ctag, the version)."""
    ids = list(todo)
    ts = iso_ms(now_utc())
    for blk in bk_blocks(ids):
        for i in blk:
            f = {**todo[i], "updated_at": ts}
            m = {**dict(rows[i]), **f}
            f["search"] = search_text({**m, **{k: json.loads(m[k] or "[]") for k in ("emails", "phones", "addresses", "groups")}})
            c.execute(f"UPDATE contacts SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), i])
        for bid in sorted({rows[i]["book_id"] for i in blk}):
            book_touch(c, bid)
        bump(c)
        c.commit()


def ms_set(c, uid, b, action):
    """{ids, action: set, groups_add?, groups_remove?, org?, dept?, kind?, note_append?} -> {action, changed, unchanged,
    skipped, undo: [{id, <old values>}]}; {items: [{id, groups?, org?, dept?, kind?, note?}], action: restore} -> {action,
    changed, skipped}."""
    if action == "set":
        f = ms_set_spec(b)
        ids = bk_ids(b)
    else:
        items = ms_restore_items(b)
        ids = list(items)
    if not contacts_on(c, uid):
        raise Denied(404)
    books = my_book_ids(c, uid)
    rows = {}
    for blk in bk_blocks(ids, 1000):
        for r in c.execute(f"SELECT * FROM contacts WHERE id IN ({bk_in(blk)})", blk).fetchall():
            rows[r["id"]] = r
    if any(i not in rows or rows[i]["book_id"] not in books for i in ids):
        raise Denied(404)
    mirrored = {r[0] for r in c.execute(f"SELECT id FROM books WHERE src_id IS NOT NULL AND id IN ({bk_in(list(books))})", list(books)).fetchall()}
    ok = [i for i in ids if books[rows[i]["book_id"]] in ("owner", "edit") and rows[i]["book_id"] not in mirrored]
    bk_gate(c, N_("Change {0} contacts at once"), len(ok))
    todo, undo = {}, []
    for i in ok:
        if action == "set":
            new, old = ms_apply(rows[i], f)
            if new:
                todo[i] = new
                undo.append({"id": i, **old})
        else:
            new = {k: v for k, v in items[i].items() if rows[i][k] != v}
            if new:
                todo[i] = new
    ms_write(c, rows, todo)
    out = {"action": action, "changed": len(todo), "skipped": len(ids) - len(ok)}
    if action == "set":
        out.update(unchanged=len(ok) - len(todo), undo=undo)
    return out


def op_contacts_bulk(c, uid, b):
    """{ids: [...], action: delete | move | set | restore, book_id (move)} -> {action, deleted} | {action, moved, unchanged,
    conflicts: [ids]} | ms_set."""
    bad = sorted(k for k in b if k not in ("ids", "action", "book_id", "items", *MS_SET_KEYS))
    if bad:
        raise UnknownFields(bad)
    action = b.get("action")
    if action not in ("delete", "move", "set", "restore"):
        raise BadInput(tr("Invalid value: {0}", "action"))
    if action in ("set", "restore"):
        return ms_set(c, uid, b, action)
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
        bk_gate(c, N_("Delete {0} contacts at once"), len(ids))
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
    bk_gate(c, N_("Move {0} contacts at once"), len(ids))
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
