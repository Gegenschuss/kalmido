"""Contacts: the web API (address books, sharing, contacts, search, vCard import / export, links to tasks)."""
import json
import secrets
import threading
import time
from datetime import datetime, timezone

from flask import jsonify, request, Response
from werkzeug.exceptions import RequestEntityTooLarge

from ..core.config import app
from ..core.i18n import N_, tr, trn
from ..core.db import body, bump, connect, db, err, iso
from ..accounts.session import me
from ..core.access import Denied, list_role, need_feat, WRITE_ROLES
from ..tasks.validation import as_int
from ..core.errors import BadInput, UnknownFields
from ..contacts.model import (
    book_create, book_fields, book_member_set, book_public, book_touch, books_for, contact_brief, contact_dict, contact_fields,
    contact_copy, contact_store, contacts_query, CT_KEYS, default_book, import_vcards, link_remove, link_set, my_book_ids, need_book, need_contact,
    occ_sync, render_vcard, split_vcards, CONTACTS_PER_BOOK, IMPORT_BATCH,
)
from ..core.zipread import base_name, is_zip, zip_read, ZipLimit  # 2.149.0 G (#2517): pulled up from functions

# 2.41.0 (#1437): never above the request limit (MAX_CONTENT_LENGTH answers 413 before the route), whole MB for the message
VCF_MAX = min(20, (app.config.get("MAX_CONTENT_LENGTH") or 0) // (1024 * 1024) or 20) * 1024 * 1024


@app.errorhandler(RequestEntityTooLarge)
def ct_too_large(e):
    """413 from the request limit on a vCard import: JSON with the reason (the app showed "Import failed: " without one)."""
    p = request.path
    if not (p.startswith(("/api/books/", "/api/v1/address-books/")) and p.endswith("/import")):
        # 2.86.0 (N22): this handler replaces core/pages.py too_large (same key: 413); the JSON answer stays for every other route
        from ..core.pages import too_large
        return too_large(e)
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
    b, _ = need_book(c, bid, manage=True)
    from ..api.scopes import need_approval  # 2.148.1 D (#2495): an agent deleting a whole address book waits for a person
    need_approval(c, N_("Delete the address book “{0}” with all its contacts"), ((b["name"] or "")[:80],))
    c.execute("DELETE FROM books WHERE id=?", (bid,))
    # 2.66.0 (#1835): the undo data of merges into this book goes with it (the history line stays)
    c.execute("UPDATE merge_runs SET snapshot='{}' WHERE kind='contact' AND book_id=?", (bid,))
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
    d = {**contact_dict(c, r, uid), "role": role}
    if role in ("owner", "edit"):  # 2.66.0 A (#1835): the merges into this contact (history + undo), only for who may change it
        from ..contacts.merge import ctm_history
        m = ctm_history(c, cid)
        if m:
            from ..collab.comments import user_names
            nm = user_names(c, [x["by"] for x in m])
            d["merges"] = [{**x, "by_name": nm.get(x["by"], "")} for x in m]
    return d


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
        if need_book(c, nb, write=True)[0]["src_id"]:  # 2.58.0 (#1656): as the bulk move
            raise Denied(409, tr("An imported address book is updated from its source; contacts cannot be moved into it"))
        if c.execute("SELECT 1 FROM contacts WHERE book_id=? AND (uid=? OR href=?)", (nb, r["uid"], r["href"])).fetchone():
            raise Denied(409, tr("The address book has this contact already"))
        from ..accounts.orgout import org_out  # 2.148.1 B (#2483): as the bulk move (only an admin takes it out of an organisation)
        so, to = (c.execute("SELECT org_id FROM books WHERE id=?", (x,)).fetchone()[0] for x in (r["book_id"], nb))
        org_out(c, so, to, "contacts", trn("{0} contact", "{0} contacts", 1))
        if c.execute("SELECT src_id FROM books WHERE id=?", (r["book_id"],)).fetchone()[0]:  # 2.138.4 C (#2378): out of a mirror = a copy
            ncid = contact_copy(c, uid, cid, nb)
            contact_store(c, uid, nb, contact_fields({k: v for k, v in b.items() if k != "book_id"}, r), cid=ncid)
            book_touch(c, nb)
            c.commit()
            return {**op_contact(c, uid, ncid), "copied": True}
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
    from ..newsletter.sync import nls_keep  # 2.152.0 D (#2170): an unsubscription outlives the contact
    nls_keep(c, [cid])
    c.execute("DELETE FROM contacts WHERE id=?", (cid,))
    book_touch(c, r["book_id"])
    bump(c)
    c.commit()


def op_import(c, uid, bid, raw, bg=False, csv_ok=False, mapping=None, preview=False, name=""):
    need_book(c, bid, write=True)
    if len(raw) > VCF_MAX:
        raise BadInput(tr("The file is too large (at most {0} MB)", VCF_MAX // (1024 * 1024)))
    from ..contacts.ctxlist import ctx_cards, ctx_import_dupes, ctx_is_csv, ctx_max_id, ctx_preview
    if csv_ok and ctx_is_csv(raw, name):  # 2.119.1 A (#2080): the app's CSV: preview = columns + suggested fields; else rows as vCards
        if preview:
            return ctx_preview(raw)
        cards = ctx_cards(raw, mapping)
    else:
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
        if "BEGIN:VCARD" not in text.upper():
            raise BadInput(tr("This is not a contacts file (vCard or CSV)") if csv_ok else tr("This is not a contacts file (vCard)"))
        if preview:
            return {"format": "vcard"}
        cards = split_vcards(text)
    since = ctx_max_id(c, bid)  # 2.119.1 A (#2084): the contacts after it are the new ones (likely duplicates in the answer)
    if bg and len(cards) > IMPORT_SYNC_MAX:
        return lv_import_start(c, uid, bid, cards, since)
    res = import_vcards(c, uid, bid, None, batch=IMPORT_BATCH, cards=cards, photos=15)  # 2.41.0 (#1437): commits per batch; 2.47.3: 15 s photo budget
    c.commit()
    if csv_ok:
        res.update(ctx_import_dupes(c, uid, bid, since))
    return res


# 2.41.0 (#1437): a large vCard file is imported in the background: the request answers at once with an import id, a thread
# of this process stores the cards in batches (each committed) and GET /api/books/imports/<id> tells the progress. Only the
# person who started it sees it; the state lives in memory for an hour (one process, like the backup's state).
IMPORT_SYNC_MAX = 100
_IMP, _IMP_LOCK = {}, threading.Lock()


def lv_import_public(st):
    d = {k: st[k] for k in ("import_id", "book_id", "state", "total", "done", "created", "updated", "unchanged", "errors", "error")}
    d.update({k: st[k] for k in ("dupes", "dupe_groups") if k in st})  # 2.119.1 A (#2084)
    for k in ("started_at", "ended_at"):
        d[k] = iso(datetime.fromtimestamp(st[k], timezone.utc)) if st[k] else None
    return d


IMP_RUNNING_MAX = 4  # 2.126.0 C (#1986): background imports at once in this process


def lv_import_start(c, uid, bid, cards, since=None):
    iid = secrets.token_urlsafe(12)
    st = {"import_id": iid, "user_id": uid, "book_id": bid, "state": "running", "total": min(len(cards), CONTACTS_PER_BOOK), "done": 0,
          "created": 0, "updated": 0, "unchanged": 0, "errors": 0, "error": "", "started_at": time.time(), "ended_at": None}
    now = time.time()
    with _IMP_LOCK:
        for k in [k for k, v in _IMP.items() if v["ended_at"] and now - v["ended_at"] > 3600]:
            _IMP.pop(k, None)
        running = [v for v in _IMP.values() if not v["ended_at"]]  # 2.126.0 C (#1986): one per person, a few per process
        if any(v["user_id"] == uid for v in running):
            raise Denied(409, tr("An import is already running"))
        if len(running) >= IMP_RUNNING_MAX:
            raise Denied(429, tr("Too many imports, please wait a few minutes"))
        _IMP[iid] = st
    ctx = c.ctx  # the starter's row-level-security context goes with the thread
    threading.Thread(target=lv_import_run, args=(st, ctx, uid, bid, cards, since), daemon=True).start()
    with _IMP_LOCK:
        return lv_import_public(st)


def lv_import_run(st, ctx, uid, bid, cards, since=None):
    # 2.138.4 C (#2377): a pool connection per batch (taken, given back after the batch's commit) instead of one for the
    # whole run, each with the starter's row-level-security context; the photo budget and the counts run across the batches.
    cards = cards[:CONTACTS_PER_BOOK]
    res = {"created": 0, "updated": 0, "unchanged": 0, "errors": 0}
    t_end = time.monotonic() + 900
    c = None
    try:
        for i in range(0, len(cards), IMPORT_BATCH):
            c = connect()
            c.set_ctx(*ctx)
            # batch: a block that hits the book's limit keeps what it stored; photos > 0: a used-up budget keeps old pictures
            part = import_vcards(c, uid, bid, None, batch=IMPORT_BATCH, cards=cards[i:i + IMPORT_BATCH],
                                 photos=max(1e-3, t_end - time.monotonic()))
            c.commit()
            c.close()
            c = None
            for k in res:
                res[k] += part[k]
            with _IMP_LOCK:
                st.update(done=min(i + IMPORT_BATCH, len(cards)), **res)
        if since is not None:  # 2.119.1 A (#2084): the new contacts that look like one already there
            from ..contacts.ctxlist import ctx_import_dupes
            c = connect()
            c.set_ctx(*ctx)
            res.update(ctx_import_dupes(c, uid, bid, since))
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


# 2.146.0 E (#2457): several vCard files in one request (Outlook writes one .vcf per contact) or a ZIP of them (Google
# Takeout): multipart field "files" (several) or one "file" that is a ZIP. The vCards go through the one import of a single
# file (duplicates by UID / the likely-duplicates check as before); each file and all together at most VCF_MAX.
CT_VCF_EXTS = (".vcf", ".vcard")


def _vcf_text(data):
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", "replace")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def ct_gather(ups):
    """The uploads -> (vCard bytes of all readable files, info {files, errors [{file, error}], skipped [names]}); None when
    it is one plain file (the single import reads it as before, CSV included)."""
    if len(ups) == 1 and not is_zip(ups[0][0], ups[0][1]):
        return None
    parts, errors, skipped, total = [], [], [], 0

    def take(name, data):
        nonlocal total
        text = _vcf_text(data)
        if "BEGIN:VCARD" not in text.upper():
            errors.append({"file": name, "error": tr("This is not a contacts file (vCard)")})
            return
        total += len(data)
        if total > VCF_MAX:
            raise BadInput(tr("The files are too large together (at most {0} MB)", VCF_MAX // (1024 * 1024)))
        parts.append(text.strip())

    for name, data in ups:
        name = base_name(name) or tr("File")
        if is_zip(name, data):
            try:
                z = zip_read(data, CT_VCF_EXTS, VCF_MAX, total_max=VCF_MAX)
            except ZipLimit as e:
                raise BadInput(str(e)) from None
            errors += [{"file": f"{name}: {x['file']}" if x["file"] else name, "error": x["error"]} for x in z.errors]
            skipped += z.skipped
            for n, d in z.files:
                take(n, d)
        else:
            take(name, data)
    if not parts:
        raise BadInput(errors[0]["error"] if len(errors) == 1 else tr("No contacts file found (vCard)"))
    return "\r\n".join(parts).encode("utf-8") + b"\r\n", {"files": len(parts), "errors": errors[:50], "skipped": skipped[:50]}


def _ct_uploads():
    """The uploaded files [(name, bytes)]: field "files" (several, 2.146.0 E #2457) and / or "file"; the whole request at most VCF_MAX."""
    if (request.content_length or 0) > VCF_MAX + 1024 * 1024:  # before the form is parsed
        raise BadInput(tr("The file is too large (at most {0} MB)", VCF_MAX // (1024 * 1024)))
    out, total = [], 0
    for f in [x for x in request.files.getlist("files") if x] + [x for x in request.files.getlist("file") if x]:
        data = f.stream.read(VCF_MAX + 1 - total)
        total += len(data)
        if total > VCF_MAX:
            raise BadInput(tr("The file is too large (at most {0} MB)", VCF_MAX // (1024 * 1024)))
        out.append((f.filename or "", data))
    return out


@app.post("/api/books/<int:bid>/import")
def books_import(bid):
    need_feat("contacts")
    bg = request.args.get("background") in ("1", "true")  # 2.41.0 (#1437): ?background=1 (the app): a large file answers 202 {import_id, ...} at once
    preview = request.args.get("preview") in ("1", "true")
    if len(request.files.getlist("files")) + len(request.files.getlist("file")) > 1 or request.files.get("files"):
        ups = _ct_uploads()
        if not ups:
            return err(tr("No file"))
        got = ct_gather(ups)  # 2.146.0 E (#2457): several files
        name, raw = ("contacts.vcf", got[0]) if got else ups[0]
    else:
        f = request.files.get("file")
        raw = f.read(VCF_MAX + 1) if f else request.get_data(cache=False)[:VCF_MAX + 1]
        name = (f.filename or "") if f else ""
        got = ct_gather([(name, raw)]) if raw else None  # 2.146.0 E (#2457): one ZIP of vCards
        if got:
            name, raw = "contacts.vcf", got[0]
    if not raw:
        return err(tr("No file"))
    # 2.119.1 A (#2080): a CSV file too; ?preview=1 answers its columns, the form field mapping = a field per column
    r = op_import(db(), me(), bid, raw, bg=bg, csv_ok=True, mapping=None if got else request.form.get("mapping"), preview=preview, name=name)
    if got:
        r["files"] = got[1]
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
