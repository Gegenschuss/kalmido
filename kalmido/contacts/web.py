"""Contacts: the web API (address books, sharing, contacts, search, vCard import / export, links to tasks)."""
import json

from flask import jsonify, request, Response

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err
from ..accounts.session import me
from ..core.access import Denied, list_role, need_feat, WRITE_ROLES
from ..tasks.validation import as_int
from ..personal.timetrack import BadInput, UnknownFields
from ..contacts.model import (
    book_create, book_fields, book_member_set, book_public, book_touch, books_for, contact_brief, contact_dict, contact_fields,
    contact_store, contacts_query, CT_KEYS, default_book, import_vcards, link_remove, link_set, my_book_ids, need_book, need_contact,
    occ_sync, render_vcard,
)

VCF_MAX = 20 * 1024 * 1024


def _unknown(b, allowed):
    bad = sorted(k for k in b if k not in allowed)
    if bad:
        raise UnknownFields(bad)


# ---- operations shared with /api/v1
def op_books(c, uid):
    return books_for(c, uid)


def op_book_new(c, uid, b):
    _unknown(b, ("name", "color"))
    bid = book_create(c, uid, b)
    bump(c)
    c.commit()
    return book_public(c, c.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone(), uid)


def op_book_edit(c, uid, bid, b):
    _unknown(b, ("name", "color", "birthdays_list_id"))
    bk, role = need_book(c, bid, manage=True)
    f = book_fields({k: b[k] for k in ("name", "color") if k in b})
    if "birthdays_list_id" in b:  # birthdays + anniversaries of this book's contacts become tasks of this list ('' / null = off)
        lid = b["birthdays_list_id"]
        if lid in (None, ""):
            f["occ_list_id"] = None
        else:
            lid = as_int(lid, "birthdays_list_id", 1)
            if list_role(c, lid, uid) not in WRITE_ROLES:
                raise Denied(404)
            if bk["src_id"]:
                raise BadInput(tr("The birthdays of an imported address book come from its source"))
            f["occ_list_id"] = lid
    if f:
        c.execute(f"UPDATE books SET {','.join(k + '=?' for k in f)} WHERE id=?", [*f.values(), bid])
        book_touch(c, bid)
        if f.get("occ_list_id"):
            for (cid,) in c.execute("SELECT id FROM contacts WHERE book_id=? AND (bday!='' OR anniversary!='')", (bid,)).fetchall():
                occ_sync(c, cid)
    bump(c)
    c.commit()
    return book_public(c, c.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone(), uid)


def op_book_delete(c, uid, bid):
    need_book(c, bid, manage=True)
    c.execute("DELETE FROM books WHERE id=?", (bid,))
    bump(c)
    c.commit()


def op_book_member(c, uid, bid, b):
    _unknown(b, ("user_id", "role"))
    need_book(c, bid, manage=True)
    book_member_set(c, bid, as_int(b.get("user_id"), "user_id", 1), b.get("role") or "view")
    bump(c)
    c.commit()
    return book_public(c, c.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone(), uid)


def op_book_member_rm(c, uid, bid, who):
    bk, role = need_book(c, bid)
    if who != uid and role != "owner":
        raise Denied(403, tr("Only the owner of the address book can do this"))
    if not c.execute("DELETE FROM book_members WHERE book_id=? AND user_id=?", (bid, who)).rowcount:
        raise Denied(404)
    book_touch(c, bid)
    bump(c)
    c.commit()


def op_contacts(c, uid, a):
    book = as_int(a["book_id"], "book_id", 1) if a.get("book_id") not in (None, "") else None
    if book is not None:
        need_book(c, book)
    limit = as_int(a.get("limit", 500), "limit", 1, 2000)
    offset = as_int(a.get("offset", 0), "offset", 0)
    rows, n = contacts_query(c, uid, a.get("q") or "", book, a.get("group") or None, limit, offset)
    ids = my_book_ids(c, uid)
    groups = set()
    if ids:
        q = ",".join("?" * len(ids))
        for (g,) in c.execute(f"SELECT DISTINCT groups FROM contacts WHERE book_id IN ({q}) AND groups!='[]'", list(ids)):
            try:
                groups |= set(json.loads(g))
            except ValueError:
                pass
    return {"items": [contact_brief(r) for r in rows], "total": n, "groups": sorted(groups, key=str.lower)}


def op_contact(c, uid, cid):
    r, role = need_contact(c, cid)
    return {**contact_dict(c, r, uid), "role": role}


def op_contact_new(c, uid, b):
    _unknown(b, CT_KEYS)
    bid = as_int(b["book_id"], "book_id", 1) if b.get("book_id") not in (None, "") else default_book(c, uid)
    need_book(c, bid, write=True)
    f = contact_fields(b)
    cid = contact_store(c, uid, bid, f)
    c.commit()
    return op_contact(c, uid, cid)


def op_contact_edit(c, uid, cid, b):
    _unknown(b, CT_KEYS + ("expect",))
    r, role = need_contact(c, cid, write=True)
    if b.get("expect") and b["expect"] != r["updated_at"]:
        raise Denied(409, tr("The contact was changed meanwhile"))
    b = {k: v for k, v in b.items() if k != "expect"}
    if "book_id" in b and b["book_id"] not in (None, "") and as_int(b["book_id"], "book_id", 1) != r["book_id"]:
        nb = as_int(b["book_id"], "book_id", 1)
        need_book(c, nb, write=True)
        if c.execute("SELECT 1 FROM contacts WHERE book_id=? AND (uid=? OR href=?)", (nb, r["uid"], r["href"])).fetchone():
            raise Denied(409, tr("The address book has this contact already"))
        c.execute("UPDATE contacts SET book_id=? WHERE id=?", (nb, cid))
        book_touch(c, r["book_id"])
        r = c.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    f = contact_fields({k: v for k, v in b.items() if k != "book_id"}, r)
    contact_store(c, uid, r["book_id"], f, cid=cid)
    c.commit()
    return op_contact(c, uid, cid)


def op_contact_delete(c, uid, cid):
    r, role = need_contact(c, cid, write=True)
    c.execute("DELETE FROM contacts WHERE id=?", (cid,))
    book_touch(c, r["book_id"])
    bump(c)
    c.commit()


def op_import(c, uid, bid, raw):
    need_book(c, bid, write=True)
    if len(raw) > VCF_MAX:
        raise BadInput(tr("The file is too large (at most {0} MB)", VCF_MAX // (1024 * 1024)))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if "BEGIN:VCARD" not in text.upper():
        raise BadInput(tr("This is not a contacts file (vCard)"))
    res = import_vcards(c, uid, bid, text)
    bump(c)
    c.commit()
    return res


def op_export(c, uid, bid):
    need_book(c, bid)
    return "".join(render_vcard(r) for r in c.execute("SELECT * FROM contacts WHERE book_id=? ORDER BY id", (bid,)))


def op_link(c, uid, tid, b):
    _unknown(b, ("contact_id", "kind"))
    link_set(c, uid, as_int(b.get("contact_id"), "contact_id", 1), tid, b.get("kind") or "about")
    c.commit()
    from ..contacts.model import task_contacts
    return {"items": task_contacts(c, uid, {tid}).get(tid, [])}


def op_unlink(c, uid, tid, cid):
    link_remove(c, uid, cid, tid)
    c.commit()


# ---- web routes
@app.get("/api/books")
def books_get():
    return jsonify(items=op_books(db(), me()))


@app.post("/api/books")
def books_new():
    need_feat("contacts")
    return jsonify(op_book_new(db(), me(), body())), 201


@app.patch("/api/books/<int:bid>")
def books_edit(bid):
    need_feat("contacts")
    return jsonify(op_book_edit(db(), me(), bid, body()))


@app.delete("/api/books/<int:bid>")
def books_delete(bid):
    need_feat("contacts")
    op_book_delete(db(), me(), bid)
    return jsonify(ok=True)


@app.put("/api/books/<int:bid>/members")
def books_member(bid):
    need_feat("contacts")
    return jsonify(op_book_member(db(), me(), bid, body()))


@app.delete("/api/books/<int:bid>/members/<int:uid>")
def books_member_rm(bid, uid):
    need_feat("contacts")
    op_book_member_rm(db(), me(), bid, uid)
    return jsonify(ok=True)


@app.post("/api/books/<int:bid>/import")
def books_import(bid):
    need_feat("contacts")
    f = request.files.get("file")
    raw = f.read(VCF_MAX + 1) if f else request.get_data(cache=False)[:VCF_MAX + 1]
    if not raw:
        return err(tr("No file"))
    return jsonify(op_import(db(), me(), bid, raw))


@app.get("/api/books/<int:bid>/export.vcf")
def books_export(bid):
    need_feat("contacts")
    r = Response(op_export(db(), me(), bid), 200, content_type="text/vcard; charset=utf-8")
    r.headers["Content-Disposition"] = 'attachment; filename="contacts-%d.vcf"' % bid
    return r


@app.get("/api/contacts")
def contacts_get():
    need_feat("contacts")
    return jsonify(op_contacts(db(), me(), request.args))


@app.get("/api/contacts/<int:cid>")
def contact_get(cid):
    need_feat("contacts")
    return jsonify(op_contact(db(), me(), cid))


@app.post("/api/contacts")
def contact_new():
    need_feat("contacts")
    return jsonify(op_contact_new(db(), me(), body())), 201


@app.patch("/api/contacts/<int:cid>")
def contact_edit(cid):
    need_feat("contacts")
    return jsonify(op_contact_edit(db(), me(), cid, body()))


@app.delete("/api/contacts/<int:cid>")
def contact_delete(cid):
    need_feat("contacts")
    op_contact_delete(db(), me(), cid)
    return jsonify(ok=True)


@app.post("/api/tasks/<int:tid>/contacts")
def task_contact_link(tid):
    need_feat("contacts")
    return jsonify(op_link(db(), me(), tid, body()))


@app.delete("/api/tasks/<int:tid>/contacts/<int:cid>")
def task_contact_unlink(tid, cid):
    need_feat("contacts")
    op_unlink(db(), me(), tid, cid)
    return jsonify(ok=True)
