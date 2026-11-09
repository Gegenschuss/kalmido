"""2.777.0 (#5254): undo across devices, stage 6 -- contacts in the core's step groups (core/undoareas.py).

A contact (table contacts) is the tracked kind "contact" (core/writes.py obj_track): a change (PATCH /api/contacts/<id>, also
moving it into another address book), putting it into the trash and taking it out record a snap step of the person under
the contact's lock (write_lock contact-<id>, as its saves), labelled with its name. Its identity for devices (uid, href) and
the import marks stay as they are on undo. Taking back (core/undoweb.py): write on the contact NOW (need_contact, also
through its own folder) and on the address book the copy puts it back into; coming out of the trash runs the book's own
restore (contacts/bulk.py ctt_restore: links, birthday tasks; 409 when the book has the same contact again), going into it
the book's own trash (ctt_trash, only with the address book's own right like the forward delete). The address books
themselves (name, colour) are a core kind: obj_write records their steps already (stage 1)."""
from ..core.db import bump
from ..core.errors import Denied
from ..core.undoareas import ua_plain, ua_trash_fix
from ..core.undogroups import UG_LABEL
from ..core.undoweb import undo_need_reg
from ..core.writes import obj_track
from .bulk import ctt_restore, ctt_trash
from .model import book_touch, need_book, need_contact, occ_sync

CTU_KIND = "contact"


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
