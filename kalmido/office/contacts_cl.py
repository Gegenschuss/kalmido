"""2.40.0 (#1380): several contact persons per client (office_client_contacts), one of them the default.

clients.contact stays the default's name (the API field "contact" keeps working, 2.39.1 runs on with the same database:
every change of the default writes it back). A client's contacts are changed with the client (PATCH /api/clients/<id>
{contacts: [...]}, the whole list) and read in its answer ("contacts"). Documents pick one (office_docs.contact_id, the
default when none is chosen): the "attn." line of the recipient and the buyer contact of the e-invoice (BT-56) follow it;
a finalised document keeps its snapshot. The legacy import adds contacts to an existing client (import_run_id; the undo
removes them again). Not linked to the address book (not decided yet; a later column can add the link)."""
import re

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
    return [{"id": r["id"], "name": r["name"], "role": r["role"], "email": r["email"], "phone": r["phone"], "is_default": bool(r["is_default"])}
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
    """The whole list of client cid from the client dialog: [{id?, name, role, email, phone, is_default}] -- rows with an id
    are changed, without one added, missing ones deleted."""
    if not isinstance(items, list) or len(items) > FK_LIMIT or not all(isinstance(x, dict) for x in items):
        raise BadInput(tr("Invalid value: {0}", "contacts"))
    have = {r["id"] for r in c.execute("SELECT id FROM office_client_contacts WHERE client_id=?", (cid,))}
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
        if kid:
            c.execute("UPDATE office_client_contacts SET name=?, role=?, email=?, phone=?, sort=?, updated_at=? WHERE id=? AND client_id=?",
                      (f["name"], f["role"], f["email"], f["phone"], i + 1, ts, kid, cid))
        else:
            kid = insert_id(c, "INSERT INTO office_client_contacts(org_id, client_id, name, role, email, phone, is_default, sort, created_at, updated_at) "
                               "VALUES(?,?,?,?,?,?,0,?,?,?)", (oid, cid, f["name"], f["role"], f["email"], f["phone"], i + 1, ts, ts))
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
