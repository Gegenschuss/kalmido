"""2.40.0 (#1380): several contact persons per client (office_client_contacts), one of them the default.

clients.contact stays the default's name (the API field "contact" keeps working, 2.39.1 runs on with the same database:
every change of the default writes it back). A client's contacts are changed with the client (PATCH /api/clients/<id>
{contacts: [...]}, the whole list) and read in its answer ("contacts"). Documents pick one (office_docs.contact_id, the
default when none is chosen): the "attn." line of the recipient and the buyer contact of the e-invoice (BT-56) follow it;
a finalised document keeps its snapshot. The legacy import adds contacts to an existing client (import_run_id; the undo
removes them again). 2.59.0 (#1735): a contact person may be linked to an address book contact (contact_id, see ckl_*)."""
import re

from flask import jsonify

from ..core.config import app
from ..core.db import iso, now_utc
from ..core.i18n import tr
from ..core.pg import insert_id
from ..personal.timetrack import BadInput

FK_MAX = {"name": 120, "role": 120, "email": 200, "phone": 60}
FK_LIMIT = 50  # contact persons per client


def _line(v, k):
    if v is not None and not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", k))
    v = re.sub(r"[\x00-\x1f\x7f]", " ", v or "")
    return re.sub(r"\s+", " ", v).strip()[:FK_MAX[k]]


def fk_contacts(c, cid):
    """The contact persons of client cid, the default first, then in their order."""
    return [{"id": r["id"], "name": r["name"], "role": r["role"], "email": r["email"], "phone": r["phone"], "is_default": bool(r["is_default"]),
             "contact_id": r["contact_id"]}  # 2.59.0 (#1735): the linked address book contact (None = not linked)
            for r in c.execute("SELECT * FROM office_client_contacts WHERE client_id=? ORDER BY is_default DESC, sort, id", (cid,))]


def fk_contact(c, cid, kid=None):
    """Contact kid of client cid (None / unknown: the default, else None)."""
    if kid:
        r = c.execute("SELECT * FROM office_client_contacts WHERE id=? AND client_id=?", (kid, cid)).fetchone()
        if r:
            return dict(r)
    r = c.execute("SELECT * FROM office_client_contacts WHERE client_id=? ORDER BY is_default DESC, sort, id LIMIT 1", (cid,)).fetchone()
    return dict(r) if r else None


def fk_sync(c, cid):
    """Exactly one default while there are contacts; clients.contact = its name (2.39.1 and the API field "contact")."""
    rows = c.execute("SELECT id, name, is_default FROM office_client_contacts WHERE client_id=? ORDER BY is_default DESC, sort, id", (cid,)).fetchall()
    name = ""
    if rows:
        d = rows[0]
        c.execute("UPDATE office_client_contacts SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END WHERE client_id=? AND is_default != CASE WHEN id=? THEN 1 ELSE 0 END",
                  (d["id"], cid, d["id"]))
        name = d["name"]
    c.execute("UPDATE clients SET contact=? WHERE id=? AND contact != ?", (name[:120], cid, name[:120]))


def fk_add(c, cid, oid, x, run_id=None, default=False):
    """Adds one contact person {name, role?, email?, phone?} to client cid -> its id."""
    f = {k: _line(x.get(k), k) for k in FK_MAX}
    if not f["name"]:
        raise BadInput(tr("Name missing"))
    if f["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f["email"]):
        raise BadInput(tr("Invalid value: {0}", "email"))
    n = c.execute("SELECT COUNT(*), COALESCE(MAX(sort), 0) FROM office_client_contacts WHERE client_id=?", (cid,)).fetchone()
    if n[0] >= FK_LIMIT:
        raise BadInput(tr("Invalid value: {0}", "contacts"))
    ts = iso(now_utc())
    if default:
        c.execute("UPDATE office_client_contacts SET is_default=0 WHERE client_id=?", (cid,))
    kid = insert_id(c, "INSERT INTO office_client_contacts(org_id, client_id, name, role, email, phone, is_default, sort, import_run_id, created_at, updated_at) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (oid, cid, f["name"], f["role"], f["email"], f["phone"], 1 if default or not n[0] else 0, int(n[1]) + 1, run_id, ts, ts))
    return kid


def fk_put(c, cid, oid, items):
    """The whole list of client cid from the client dialog: [{id?, name, role, email, phone, is_default, contact_id?}] -- rows
    with an id are changed, without one added, missing ones deleted. 2.59.0 (#1735): contact_id links an address book
    contact (missing = unchanged, null = unlinked; a new link is checked: ckl_want)."""
    if not isinstance(items, list) or len(items) > FK_LIMIT or not all(isinstance(x, dict) for x in items):
        raise BadInput(tr("Invalid value: {0}", "contacts"))
    links = {r["id"]: r["contact_id"] for r in c.execute("SELECT id, contact_id FROM office_client_contacts WHERE client_id=?", (cid,))}
    have = set(links)
    cl = c.execute("SELECT id, org_id, created_by FROM clients WHERE id=?", (cid,)).fetchone()
    keep, want_default = set(), None
    ts = iso(now_utc())
    for i, x in enumerate(items):
        f = {k: _line(x.get(k), k) for k in FK_MAX}
        if not f["name"]:
            raise BadInput(tr("Name missing"))
        if f["email"] and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", f["email"]):
            raise BadInput(tr("Invalid value: {0}", "email"))
        kid = x.get("id")
        if kid is not None and (not isinstance(kid, int) or isinstance(kid, bool) or kid not in have):
            raise BadInput(tr("Invalid value: {0}", "contacts"))
        link = ckl_want(c, cl, x, links.get(kid))
        if kid:
            c.execute("UPDATE office_client_contacts SET name=?, role=?, email=?, phone=?, sort=?, contact_id=?, updated_at=? WHERE id=? AND client_id=?",
                      (f["name"], f["role"], f["email"], f["phone"], i + 1, link, ts, kid, cid))
        else:
            kid = insert_id(c, "INSERT INTO office_client_contacts(org_id, client_id, name, role, email, phone, is_default, sort, contact_id, created_at, updated_at) "
                               "VALUES(?,?,?,?,?,?,0,?,?,?,?)", (oid, cid, f["name"], f["role"], f["email"], f["phone"], i + 1, link, ts, ts))
        keep.add(kid)
        if x.get("is_default") and want_default is None:
            want_default = kid
    for kid in have - keep:
        c.execute("DELETE FROM office_client_contacts WHERE id=? AND client_id=?", (kid, cid))
    if want_default is not None:
        c.execute("UPDATE office_client_contacts SET is_default=CASE WHEN id=? THEN 1 ELSE 0 END WHERE client_id=?", (want_default, cid))
    fk_sync(c, cid)


def fk_contact_field(c, cid, oid, name):
    """The old single field "contact" was written (API): it renames the default (or adds one); empty removes the default
    (the next one takes its place)."""
    name = _line(name, "name")
    if not name:
        c.execute("DELETE FROM office_client_contacts WHERE client_id=? AND is_default=1", (cid,))
        fk_sync(c, cid)
        return
    d = c.execute("SELECT id FROM office_client_contacts WHERE client_id=? AND is_default=1 LIMIT 1", (cid,)).fetchone()
    if d:
        c.execute("UPDATE office_client_contacts SET name=?, updated_at=? WHERE id=?", (name, iso(now_utc()), d["id"]))
    else:
        fk_add(c, cid, oid, {"name": name}, default=True)
    fk_sync(c, cid)


def fk_has_name(c, cid, name):
    n = re.sub(r"\s+", " ", (name or "")).strip().lower()
    return bool(n) and any(re.sub(r"\s+", " ", r["name"]).strip().lower() == n
                           for r in c.execute("SELECT name FROM office_client_contacts WHERE client_id=?", (cid,)))


def fk_migrate(c):
    """Start-up (idempotent): every client with a contact name and no contact persons gets it as its default; a client
    whose contact field was changed by an older version (2.39.1 on the same database) has its default renamed."""
    ts = iso(now_utc())
    c.execute("INSERT INTO office_client_contacts(org_id, client_id, name, is_default, sort, created_at, updated_at) "
              "SELECT cl.org_id, cl.id, cl.contact, 1, 1, ?, ? FROM clients cl WHERE cl.contact != '' "
              "AND NOT EXISTS (SELECT 1 FROM office_client_contacts k WHERE k.client_id=cl.id)", (ts, ts))
    c.execute("UPDATE office_client_contacts k SET name=cl.contact, updated_at=? FROM clients cl WHERE k.client_id=cl.id AND k.is_default=1 "
              "AND cl.contact != '' AND k.name != cl.contact", (ts,))


# ---------------------------------------------------------------- 2.59.0 (#1735): the link to the address book
# A contact person may point to a contact of an address book (contact_id; ON DELETE SET NULL: deleting the contact or its
# book, also through CardDAV, only drops the link). Allowed books: those the client's organisation owns (books.owner_org_id
# = clients.org_id, inside its workspace); a client without an organisation (a freelancer's) takes its creator's own books
# (no organisation, private workspace). Never a private book for an organisation's client, never across organisations.
# Name, e-mail, phone and role stay a copy on the contact person (documents read the copy); nothing follows later edits.
def ckl_book_fits(cl, b):
    """Is address book b (org_id, owner_org_id, owner_id) one the contact persons of client cl may link to?"""
    if cl["org_id"]:
        return b["owner_org_id"] == cl["org_id"] and b["org_id"] == cl["org_id"]
    # 2.126.0 C (#1992 K10): a private client like an organisation's: any private book the person reads (shared ones too)
    return not b["owner_org_id"] and not b["org_id"]


def ckl_contact_ok(c, uid, cl, kid):
    """Contact kid when person uid sees it (contacts module on, its book readable) and its book fits client cl, else None."""
    from ..contacts.model import contact_visible
    r = contact_visible(c, kid, uid)
    if not r or r["kind"] == "group":
        return None
    b = c.execute("SELECT org_id, owner_org_id, owner_id FROM books WHERE id=?", (r["book_id"],)).fetchone()
    return r if b and ckl_book_fits(cl, b) else None


class CklGone(BadInput):
    """2.81.0 (#1852): the linked contact is gone / not allowed; the dialog unlinks that entry and saves again."""


@app.errorhandler(CklGone)
def ckl_gone(e):
    return jsonify(error=e.args[0], code="contact_gone", contact_id=e.args[1]), 400  # only the id the caller sent, no foreign data


def ckl_want(c, cl, x, old):
    """The contact_id entry x of the client dialog asks for: missing = unchanged (old), null / 0 = not linked, an id = linked
    after the check (a colleague without access to the book keeps an existing link by sending it back unchanged)."""
    if "contact_id" not in x:
        return old
    v = x["contact_id"]
    if v is None or v == 0:
        return None
    if not isinstance(v, int) or isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", "contact_id"))
    if v == old:
        return old
    from flask import g
    from ..api.scopes import need_scope
    need_scope("contacts")  # a token links a contact only with the permission to read contacts
    u = g.get("user")
    if not u or not cl or not ckl_contact_ok(c, u["id"], cl, v):
        raise CklGone(tr("Invalid value: {0}", "contact_id"), v)
    return v


def ckl_unlink_client(c, cid):
    """Client cid moves into another workspace: its links go (no address book belongs to two of them)."""
    c.execute("UPDATE office_client_contacts SET contact_id=NULL WHERE client_id=? AND contact_id IS NOT NULL", (cid,))


def ckl_contact_clients(c, kid, uid):
    """The contact card: [{client_id, name, icon, role, contact_person_id}] of the clients contact kid is a contact person of,
    only clients person uid may open (people with the module clients who see the client, as GET /api/clients/<id>) and only
    links whose book still fits the client. [] for everybody else."""
    from ..team.clients import client_rows, clients_on
    u = c.execute("SELECT kind, kid FROM users WHERE id=?", (uid,)).fetchone()
    if not u or u["kid"] or (u["kind"] or "user") == "agent" or not clients_on(c, uid):
        return []
    rows = c.execute("SELECT k.id, k.client_id, k.role, b.org_id, b.owner_org_id, b.owner_id FROM office_client_contacts k "
                     "JOIN contacts ct ON ct.id=k.contact_id JOIN books b ON b.id=ct.book_id WHERE k.contact_id=? ORDER BY k.client_id, k.id",
                     (kid,)).fetchall()
    if not rows:
        return []
    mine = {r["id"]: r for r in client_rows(c, uid)}
    return [{"client_id": r["client_id"], "name": mine[r["client_id"]]["name"], "icon": mine[r["client_id"]]["icon"], "role": r["role"],
             "contact_person_id": r["id"]}
            for r in rows if r["client_id"] in mine and ckl_book_fits(mine[r["client_id"]], r)]


def ckl_candidates(c, uid, cl, q="", limit=20):
    """The contacts person uid may link to the contact persons of client cl: [{id, fn, org, title, email, phone, book}],
    matching q (name, company, e-mail, phone), at most limit."""
    from ..contacts.model import contact_brief, contacts_on, my_book_ids
    if not contacts_on(c, uid):
        return []
    ids = list(my_book_ids(c, uid))
    if not ids:
        return []
    books = {b["id"]: b for b in c.execute(f"SELECT id, name, org_id, owner_org_id, owner_id FROM books WHERE id IN ({','.join('?' * len(ids))})", ids)
             if ckl_book_fits(cl, b)}
    if not books:
        return []
    from ..core.pg import like_escape
    sql = f"SELECT * FROM contacts WHERE book_id IN ({','.join('?' * len(books))}) AND kind != 'group'"
    args = list(books)
    q = re.sub(r"\s+", " ", q or "").strip()[:100]
    if q:
        sql += " AND search ILIKE ? ESCAPE '\\'"
        args.append("%" + like_escape(q.lower()) + "%")
    out = []
    for r in c.execute(sql + " ORDER BY lower(fn), id LIMIT ?", (*args, max(1, min(int(limit), 50)))):
        d = contact_brief(r)
        out.append({"id": d["id"], "fn": d["fn"], "org": d["org"], "title": r["title"], "email": d["email"], "phone": d["phone"],
                    "book": books[r["book_id"]]["name"]})
    return out
