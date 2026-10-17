"""Contacts: the web API (address books, sharing, contacts, search, vCard import / export, links to tasks)."""
import json
import secrets
import threading
import time
from datetime import datetime, timezone

from flask import jsonify, request, Response
from werkzeug.exceptions import RequestEntityTooLarge

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, connect, db, err, iso
from ..accounts.session import me
from ..core.access import Denied, list_role, need_feat, WRITE_ROLES
from ..tasks.validation import as_int
from ..personal.timetrack import BadInput, UnknownFields
from ..contacts.model import (
    book_create, book_fields, book_member_set, book_public, book_touch, books_for, contact_brief, contact_dict, contact_fields,
    contact_store, contacts_query, CT_KEYS, default_book, import_vcards, link_remove, link_set, my_book_ids, need_book, need_contact,
    occ_sync, render_vcard, split_vcards, CONTACTS_PER_BOOK, IMPORT_BATCH,
)

# 2.41.0 (#1437): never above the request limit (MAX_CONTENT_LENGTH answers 413 before the route), whole MB for the message
VCF_MAX = min(20, (app.config.get("MAX_CONTENT_LENGTH") or 0) // (1024 * 1024) or 20) * 1024 * 1024


@app.errorhandler(RequestEntityTooLarge)
def ct_too_large(e):
    """413 from the request limit on a vCard import: JSON with the reason (the app showed "Import failed: " without one)."""
    p = request.path
    if not (p.startswith(("/api/books/", "/api/v1/address-books/")) and p.endswith("/import")):
        return e
    return err(tr("The file is too large (at most {0} MB)", VCF_MAX // (1024 * 1024)), 413)


def _unknown(b, allowed):
    bad = sorted(k for k in b if k not in allowed)
    if bad:
        raise UnknownFields(bad)


# ---- operations shared with /api/v1
def op_books(c, uid):
    return books_for(c, uid)


def op_book_new(c, uid, b):
    _unknown(b, ("name", "color", "org_id"))  # 2.30.0 (#1036): org_id = its workspace
    bid = book_create(c, uid, b)
    bump(c)
    c.commit()
    return book_public(c, c.execute("SELECT * FROM books WHERE id=?", (bid,)).fetchone(), uid)


def op_book_edit(c, uid, bid, b):
    _unknown(b, ("name", "color", "birthdays_list_id", "org_id"))
    bk, role = need_book(c, bid, manage=True)
    if "org_id" in b and bk["owner_org_id"] and b["org_id"] != bk["owner_org_id"]:  # 2.52.0 C (#1438)
        raise Denied(409, tr("An address book of an organisation stays in it"))
    if "org_id" in b and not bk["owner_org_id"]:  # 2.30.0 (#1036): the owner moves it into another workspace (409 while a member does not fit)
        from ..accounts.orgs import obj_org_set
        if obj_org_set(c, "books", "book_id", "book_members", bid, b["org_id"], "book"):
            book_touch(c, bid)
    f = book_fields({k: b[k] for k in ("name", "color") if k in b})
    if "birthdays_list_id" in b:  # birthdays + anniversaries of this book's contacts become tasks of this list ('' / null = off)
        lid = b["birthdays_list_id"]
        if lid in (None, ""):
            f["occ_list_id"] = None
        else:
            lid = as_int(lid, "birthdays_list_id", 1)
            if list_role(c, lid, uid) not in WRITE_ROLES:
                raise Denied(404)
            from ..collab.liste2e import le2a_gen_refuse
            le2a_gen_refuse(c, lid)  # 2.64.1 review (M3): birthdays would land in plain text
            if bk["src_id"]:
                raise BadInput(tr("The birthdays of an imported address book come from its source"))
            f["occ_list_id"] = lid
            if bk["owner_org_id"] and bk["owner_id"] != uid:  # 2.52.0 C (#1438): the birthdays go to the admin who chose the list
                f["owner_id"] = uid
                c.execute("DELETE FROM book_members WHERE book_id=? AND user_id=?", (bid, uid))
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
        nbk = c.execute("SELECT occ_list_id FROM books WHERE id=?", (nb,)).fetchone()
        if c.execute("SELECT occ_list_id FROM books WHERE id=?", (r["book_id"],)).fetchone()[0] != nbk[0]:
            from ..contacts.bulk import bk_occ_drop  # 2.46.1 (#1554): another birthday list: the old tasks go, contact_store makes new ones
            bk_occ_drop(c, uid, [cid])
        c.execute("UPDATE contacts SET book_id=? WHERE id=?", (nb, cid))
        book_touch(c, r["book_id"])
        r = c.execute("SELECT * FROM contacts WHERE id=?", (cid,)).fetchone()
    f = contact_fields({k: v for k, v in b.items() if k != "book_id"}, r)
    contact_store(c, uid, r["book_id"], f, cid=cid)
    c.commit()
    return op_contact(c, uid, cid)


def op_contact_delete(c, uid, cid):
    r, role = need_contact(c, cid, write=True)
    from ..contacts.bulk import bk_occ_drop  # 2.46.1 (#1554): its birthday / anniversary tasks go to the trash with it
    bk_occ_drop(c, uid, [cid])
    c.execute("DELETE FROM contacts WHERE id=?", (cid,))
    book_touch(c, r["book_id"])
    bump(c)
    c.commit()


def op_import(c, uid, bid, raw, bg=False):
    need_book(c, bid, write=True)
    if len(raw) > VCF_MAX:
        raise BadInput(tr("The file is too large (at most {0} MB)", VCF_MAX // (1024 * 1024)))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    if "BEGIN:VCARD" not in text.upper():
        raise BadInput(tr("This is not a contacts file (vCard)"))
    cards = split_vcards(text)
    if bg and len(cards) > IMPORT_SYNC_MAX:
        return lv_import_start(c, uid, bid, cards)
    res = import_vcards(c, uid, bid, text, batch=IMPORT_BATCH, cards=cards, photos=15)  # 2.41.0 (#1437): commits per batch; 2.47.3: 15 s photo budget
    c.commit()
    return res


# 2.41.0 (#1437): a large vCard file is imported in the background: the request answers at once with an import id, a thread
# of this process stores the cards in batches (each committed) and GET /api/books/imports/<id> tells the progress. Only the
# person who started it sees it; the state lives in memory for an hour (one process, like the backup's state).
IMPORT_SYNC_MAX = 100
_IMP, _IMP_LOCK = {}, threading.Lock()


def lv_import_public(st):
    d = {k: st[k] for k in ("import_id", "book_id", "state", "total", "done", "created", "updated", "unchanged", "errors", "error")}
    for k in ("started_at", "ended_at"):
        d[k] = iso(datetime.fromtimestamp(st[k], timezone.utc)) if st[k] else None
    return d


def lv_import_start(c, uid, bid, cards):
    iid = secrets.token_urlsafe(12)
    st = {"import_id": iid, "user_id": uid, "book_id": bid, "state": "running", "total": min(len(cards), CONTACTS_PER_BOOK), "done": 0,
          "created": 0, "updated": 0, "unchanged": 0, "errors": 0, "error": "", "started_at": time.time(), "ended_at": None}
    now = time.time()
    with _IMP_LOCK:
        for k in [k for k, v in _IMP.items() if v["ended_at"] and now - v["ended_at"] > 3600]:
            _IMP.pop(k, None)
        _IMP[iid] = st
    ctx = c.ctx  # the starter's row-level-security context goes with the thread
    threading.Thread(target=lv_import_run, args=(st, ctx, uid, bid, cards), daemon=True).start()
    with _IMP_LOCK:
        return lv_import_public(st)


def lv_import_run(st, ctx, uid, bid, cards):
    def prog(done, total, res):
        with _IMP_LOCK:
            st.update(done=done, **res)
    c = None
    try:
        c = connect()
        c.set_ctx(*ctx)
        res = import_vcards(c, uid, bid, None, batch=IMPORT_BATCH, progress=prog, cards=cards, photos=900)
        c.commit()
        with _IMP_LOCK:
            st.update(state="done", done=st["total"], **res)
    except Exception as e:  # noqa: BLE001 -- any failure ends the import with a message; the batches before it stay
        msg = e.text() if isinstance(e, Denied) else str(e) if isinstance(e, BadInput) else ""
        print("contacts import failed:", type(e).__name__, flush=True)
        try:
            if c:
                c.rollback()
        except Exception:  # noqa: BLE001
            pass
        with _IMP_LOCK:
            st.update(state="failed", error=msg)
    finally:
        with _IMP_LOCK:
            st["ended_at"] = time.time()
        if c:
            c.close()


def op_import_state(uid, iid):
    with _IMP_LOCK:
        st = _IMP.get(iid)
        if not st or st["user_id"] != uid:
            raise Denied(404)
        return lv_import_public(st)


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
    # 2.41.0 (#1437): ?background=1 (the app): a large file answers 202 {import_id, state: "running", ...} at once
    bg = request.args.get("background") in ("1", "true")
    r = op_import(db(), me(), bid, raw, bg=bg)
    return (jsonify(r), 202) if "import_id" in r else jsonify(r)


@app.get("/api/books/imports/<iid>")
def books_import_state(iid):
    need_feat("contacts")
    return jsonify(op_import_state(me(), iid))


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
