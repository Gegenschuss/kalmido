"""2.777.0 (#5254): undo across devices, stage 6 -- contacts in the core's step groups (core/undoareas.py).

A contact (table contacts) is the tracked kind "contact" (core/writes.py obj_track): a change (PATCH /api/contacts/<id>, also
moving it into another address book), putting it into the trash and taking it out record a snap step of the person under
the contact's lock (write_lock contact-<id>, as its saves), labelled with its name. Its identity for devices (uid, href) and
the import marks stay as they are on undo. Taking back (core/undoweb.py): write on the contact NOW (need_contact, also
through its own folder) and on the address book the copy puts it back into; coming out of the trash runs the book's own
restore (contacts/bulk.py ctt_restore: links, birthday tasks; 409 when the book has the same contact again), going into it
the book's own trash (ctt_trash, only with the address book's own right like the forward delete). The address books
themselves (name, colour) are a core kind: obj_write records their steps already (stage 1).
2.985.0 (#5394, stage 6 rest): a change / delete through CardDAV (contacts/carddav.py PUT / DELETE, also a card that comes
back out of the trash by a PUT) records its step the same way (API v1 shares the web's op_contact_*); a whole address book
into the trash and out of it (contacts/web.py op_book_delete / op_book_restore) is a trash step of the core kind
"address_book" taken back the book's way (core/undoweb.py undo_trash_reg): back = bk_restore (manage, the books' limit, the
contacts' links and birthday tasks), forward = bk_trash (newsletter blocks kept, links and birthday tasks off)."""
from ..core.db import bump
from ..core.access import live_sql  # 2.985.0 (#5394)
from ..core.errors import Denied
from ..core.i18n import tr  # 2.985.0 (#5394)
from ..core.pg import write_lock  # 2.985.0 (#5394, review F10)
from ..core.undoareas import ua_plain, ua_trash_fix
from ..core.undogroups import UG_LABEL, undo_label  # 2.985.0 (#5394): undo_label
from ..core.undoweb import undo_need_reg, undo_trash_reg  # 2.985.0 (#5394): undo_trash_reg
from ..core.writes import UG_RESTORED, UG_TRASHED, UNDO_CONFLICT, obj_restore, obj_track, obj_trash, obj_trash_step  # 2.985.0 (#5394): an address book's trash steps
from .bulk import bk_occ_drop, ctt_relink, ctt_restore, ctt_trash, ctt_unlink  # 2.985.0 (#5394): + bk_occ_drop, ctt_relink, ctt_unlink
from .model import bk_max_check, book_touch, need_book, need_contact, occ_sync  # 2.985.0 (#5394): + bk_max_check

CTU_KIND = "contact"
CTU_BOOK = "address_book"  # 2.985.0 (#5394): = contacts/ctfolder.py CTF_BOOK (that module loads later; this one with contacts/web.py)


def ctu_name(r):
    r = dict(r) if r is not None else {}
    nm = r.get("fn") or " ".join(x for x in (r.get("given"), r.get("family")) if x) or r.get("org")
    return ua_plain(nm, r.get("id"))


def ctu_label(r):
    return UG_LABEL, [ctu_name(r)]


obj_track(CTU_KIND, "contacts", area="other", undo_keep={"contacts": {"uid", "href", "imp_at", "imp_rev", "src_digest", "created_by"}},
          undo_nofp={"contacts": {"imp_at", "imp_rev", "src_digest"}}, undo_label=ctu_label, undo_free=("deleted_at",))


def ctu_need(c, uid, rid, oid):
    """Who may take a contact's step back now (module docstring)."""
    r = c.execute("SELECT * FROM contacts WHERE id=?", (int(rid),)).fetchone()
    if r is None:
        raise Denied(404)
    need_contact(c, rid, write=True, uid=uid, trash=bool(r["deleted_at"]))
    old_book = r["book_id"]

    def back(c, x):
        ctt_restore(c, uid, [x])

    def away(c, x):
        need_contact(c, x["id"], write=True, uid=uid, own=True)  # never through the contact's own folder alone (as the delete)
        ctt_trash(c, uid, [x["id"]])
        bump(c)
    trash = ua_trash_fix("contacts", rid, r["deleted_at"], back, away)

    def fix(c):
        n = c.execute("SELECT * FROM contacts WHERE id=?", (int(rid),)).fetchone()
        if n["book_id"] != old_book:
            need_contact(c, rid, write=True, uid=uid, own=True, trash=bool(n["deleted_at"]))
            if need_book(c, n["book_id"], write=True, uid=uid)[0]["src_id"]:
                raise Denied(409)  # an imported book is updated from its source (as the forward move)
            book_touch(c, old_book)
        trash(c)
        n = c.execute("SELECT * FROM contacts WHERE id=?", (int(rid),)).fetchone()
        if not n["deleted_at"]:
            occ_sync(c, int(rid))  # birthday / anniversary tasks as the contact is now
        book_touch(c, n["book_id"])
    return {"fix": fix, "lock": f"contact-{int(rid)}"}


undo_need_reg(CTU_KIND, ctu_need)


def bk_trash(c, uid, bid, step=False):
    """2.985.0 (#5394): op_book_delete (contacts/web.py) without its approval and commit (also the undo of a book's
    restore step) -> the number of its contacts. step = a trash step of the person's list "Recent steps"."""
    write_lock(c, f"obj-address_book-{int(bid)}")  # review F10: the book's lock (op_book_edit) -- the app and an undo one after the other
    b, _ = need_book(c, bid, manage=True, uid=uid)
    from ..newsletter.sync import NWL_BLOCKED, nls_keep  # 2.186.0 C (#2602): the unsubscriptions outlive the address book
    nls_keep(c, [r["id"] for r in c.execute(f"SELECT id FROM contacts WHERE book_id=? AND nl_status IN ({','.join('?' * len(NWL_BLOCKED))})",
                                             (bid, *NWL_BLOCKED))])
    # 2.272.0 E1 (#3038): its birthday tasks go to the trash (made again on restore)
    live = [r[0] for r in c.execute(f"SELECT id FROM contacts WHERE book_id=? AND {live_sql()}", (bid,)).fetchall()]
    bk_occ_drop(c, uid, live)
    ctt_unlink(c, live)  # clients' contact persons: unlinked as before
    n = c.execute(f"SELECT COUNT(*) FROM contacts WHERE book_id=? AND kind!='group' AND {live_sql()}", (bid,)).fetchone()[0]
    if step:  # 2.985.0 (#5394): taken back through the book's own restore (contacts/ctundo.py, core/undoweb.py undo_trash_reg)
        undo_label(c, UG_TRASHED, ua_plain(b["name"], bid))
        obj_trash_step(c, uid, CTU_BOOK, bid, b["org_id"] or None, "trash")
    obj_trash(c, uid, CTU_BOOK, bid, step=False)  # 2.947.0 (#5367): the core's trash, its node with it (the step is the one above)
    return n


def bk_restore(c, uid, bid, step=False):
    """2.985.0 (#5394): op_book_restore (contacts/web.py) without its commit (also the undo of a book's trash step); 409
    when it is not in the trash. step = a restore step of the person's list "Recent steps"."""
    write_lock(c, f"obj-address_book-{int(bid)}")  # review F10: see bk_trash
    b, _ = need_book(c, bid, manage=True, trash=True, uid=uid)
    if not b["deleted_at"]:
        raise Denied(409, tr(UNDO_CONFLICT))
    if not b["owner_org_id"]:  # 2.370.4 (#3089, review N4): the trash does not count against BOOKS_MAX, a restore does
        bk_max_check(c, b["owner_id"])
    if step:
        undo_label(c, UG_RESTORED, ua_plain(b["name"], bid))
        obj_trash_step(c, uid, CTU_BOOK, bid, b["org_id"] or None, "restore")
    obj_restore(c, uid, CTU_BOOK, bid, step=False)  # 2.947.0 (#5367): the core's way, its node with it
    ctt_relink(c, [r[0] for r in c.execute(f"SELECT id FROM contacts WHERE book_id=? AND {live_sql()}", (bid,)).fetchall()])  # 2.272.0 F (M8)
    for (cid,) in c.execute(f"SELECT id FROM contacts WHERE book_id=? AND {live_sql()} AND (bday!='' OR anniversary!='')",
                            (bid,)).fetchall():
        occ_sync(c, cid)
    book_touch(c, bid)


def ctu_book_back(c, uid, bid):
    """2.985.0 (#5394): an address book's trash step taken back = its restore (bk_restore, no step of its own)."""
    bk_restore(c, uid, bid)
    bump(c)


def ctu_book_away(c, uid, bid):
    """An address book's restore step taken back / its trash step forward again = into the trash (bk_trash)."""
    bk_trash(c, uid, bid)
    bump(c)


undo_trash_reg(CTU_BOOK, ctu_book_back, ctu_book_away)
