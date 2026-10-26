"""2.351.0 B (#2749): address books and contacts in folders -- the reference kinds 'address_book' and 'contact' of the folder
system (files/fsref.py) and the folder tree of the address book.

An address book or a single contact can lie in ONE folder of its workspace's file store tree (a reference node). The address
book's folders live below the area root "Address book" of the workspace (files/fsroots.py, area 'contacts'), made on the first
folder; a book / contact gets its node only when somebody files it (none for the existing ones). Nothing moves: the books,
their contacts and book_members stay as they are -- an older version reading a database with these nodes simply ignores them
(the folders are ordinary folders of the file store, the nodes unknown kinds: fsref.fs_ref_json no_access).

Rights: book_role / need_contact (contacts/model.py) = the address book's own role (owner, book_members, the organisation's
role) OR the role a folder gives (fs_ref_node_role: shares with people / groups, agents only through a share with exactly
them; never organisation access nor the folder's ownership); the higher one counts, a folder never gives 'owner' and never
narrows a share. A book in a folder gives its role on all its contacts (also the ones added later); a contact in a folder
only that contact. Filing needs the right to manage the address book (its owner, an organisation book's admins; fsref.fs_ref_may_file: neither a
folder share nor a book share with edit is enough -- they cannot share the book either).
A book through a folder works like a share of the book (book_members): its contacts are read / changed / deleted as the role
says; the book's settings, sharing and deleting stay with its owner. A contact through its own folder only: reading and
changing its fields -- deleting it or moving it into another address book stay with who has a role on the book.
- hidden: a token without the scope "contacts" (a person's or an agent's) never reaches a book / contact through a folder.
- content: a contact as its vCard, an address book as the vCards of its contacts (the file store's content routes).
- cap: the module "contacts" off for the person, or collaboration off on the server: nothing through a share.
- A folder going into the trash never deletes a book or contact (they stay where they are, only out of the folder);
  deleting a book / contact for good removes its node (fs_ref_drop), a book in the trash gives nothing through its node.

Routes: GET / POST /api/contacts/folders (the tree of the panel; filing: POST /api/files/refs, sharing: the file store's)."""
from flask import g, jsonify

from ..core.config import app
from ..core.access import collab_all, need_feat
from ..core.db import body, bump, db, insert_id
from ..core.errors import BadInput, Denied
from ..core.i18n import N_, tr
from ..core.pg import system_ctx
from ..accounts.orgroles import org_writes, user_orgs_full
from ..accounts.orgs import user_orgs
from ..accounts.session import me
from ..files.fsref import (fs_ref_all_sql, fs_ref_drop, fs_ref_node, fs_ref_node_role, fs_ref_may_file, fs_ref_register,
                           fs_ref_rename, fs_ref_role, fs_ref_token_lacks)
from ..files.fsroots import fs_area_folder_name, fs_area_root
from ..files.store import _now, _place, fs_log_add, fs_role, fs_visible_sql, safe_fs_name
from .model import book_role, contacts_on, render_vcard

CTF_BOOK = "address_book"
CTF_CONTACT = "contact"
CTF_AREA = "contacts"


def _book(c, bid):
    with system_ctx(c):  # structure only (which workspace, deleted?): nothing is handed out here
        return c.execute("SELECT * FROM books WHERE id=?", (int(bid),)).fetchone()


def _contact(c, cid):
    return c.execute("SELECT * FROM contacts WHERE id=?", (int(cid),)).fetchone()


def _book_space(c, b):
    if b is None or b["deleted_at"]:
        return None
    if b["owner_org_id"] and b["org_id"] != b["owner_org_id"]:
        return None  # never across the boundary (model._book_role)
    if not b["owner_org_id"]:
        u = c.execute("SELECT disabled FROM users WHERE id=?", (b["owner_id"],)).fetchone()
        if not u or u[0]:
            return None  # a disabled owner's address books are gone for everybody
    return (b["org_id"], b["owner_id"])


def _own_role(c, uid, b):
    """The book's own role (no folder) as the folder system's base role: only who manages the book (its owner, an
    organisation book's admins) has 'edit' -- filing it and sharing its folder pass it on, which a book share does not allow
    (a member who may change it shares it as little as before); a member's role counts as 'view' here (their own access to
    the contacts stays book_role's)."""
    r = book_role(c, uid, b, fold=False)
    return "edit" if r == "owner" else ("view" if r in ("edit", "view") else None)


def _book_base(c, uid, bid):
    b = _book(c, bid)
    return _own_role(c, uid, b) if b is not None else None


def _contact_base(c, uid, cid):
    r = _contact(c, cid)
    if r is None or r["deleted_at"] or not contacts_on(c, uid):
        return None
    b = _book(c, r["book_id"])
    return _own_role(c, uid, b) if b is not None else None


def _contact_space(c, cid):
    r = _contact(c, cid)
    if r is None or r["deleted_at"] or r["kind"] == "group":
        return None
    return _book_space(c, _book(c, r["book_id"]))


def _hidden(kind):
    def f(c, uid):
        return fs_ref_all_sql(kind) if fs_ref_token_lacks(uid, "contacts") else ""
    return f


def _gate(c, uid, rid):
    if fs_ref_token_lacks(uid, "contacts"):
        raise Denied(403, tr("This token lacks the permission “{0}”", "contacts"))
    if not contacts_on(c, uid):
        raise Denied(403)


def _cap(c, uid, rid):
    """The most a folder share gives: nothing with the module off or collaboration off (like book_members)."""
    if not collab_all() or not contacts_on(c, uid):
        return None
    return "edit"


def _book_title(c, bid):
    b = _book(c, bid)
    return b["name"] if b is not None else ""


def _contact_title(c, cid):
    r = _contact(c, cid)
    return (r["fn"] or r["org"] or "?") if r is not None else ""


def _book_content(c, uid, bid):
    b = _book(c, bid)
    if b is None or b["deleted_at"]:
        return None
    text = "".join(render_vcard(r) for r in c.execute("SELECT * FROM contacts WHERE book_id=? AND deleted_at IS NULL ORDER BY id", (b["id"],)))
    return text.encode("utf-8"), f"{b['name'] or 'contacts'}.vcf", "text/vcard"


def _contact_content(c, uid, cid):
    r = _contact(c, cid)
    if r is None or r["deleted_at"]:
        return None
    return render_vcard(r).encode("utf-8"), f"{r['fn'] or r['org'] or 'contact'}.vcf", "text/vcard"


fs_ref_register(CTF_BOOK, label=N_("Address book"), open_url=lambda bid: f"contacts/b/{int(bid)}", base_role=_book_base,
                space=lambda c, bid: _book_space(c, _book(c, bid)), hidden=_hidden(CTF_BOOK), title=_book_title,
                content=_book_content, content_gate=_gate, cap=_cap)
fs_ref_register(CTF_CONTACT, label=N_("Contact"), open_url=lambda cid: f"contacts/{int(cid)}", base_role=_contact_base,
                space=_contact_space, hidden=_hidden(CTF_CONTACT), title=_contact_title, content=_contact_content,
                content_gate=_gate, cap=_cap)


# ---------------------------------------------------------------- the hooks of contacts/model.py
def _any(c, kind):
    key = ("ctf_any", kind)
    cache = g.setdefault("ctf_cache", {}) if _req() else {}
    if key not in cache:
        cache[key] = c.execute("SELECT 1 FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND deleted_at IS NULL LIMIT 1", (kind,)).fetchone() is not None
    return cache[key]


def _req():
    from flask import has_request_context
    return has_request_context()


def ctf_node_role(c, uid, kind, rid):
    """The role the folder of book / contact rid gives uid (None: in no folder, in the trash, no share)."""
    if not uid or not _any(c, kind):
        return None
    n = fs_ref_node(c, kind, rid)
    if n is None or n["deleted_at"]:
        return None
    return fs_ref_node_role(c, uid, n)


def ctf_reached(c, uid, kind):
    """{ref_id: role} of the books / contacts whose node lies in a folder that gives uid a role."""
    if not uid or not _any(c, kind):
        return {}
    out = {}
    for n in c.execute(f"SELECT * FROM fs_nodes WHERE kind='ref' AND ref_kind=? AND deleted_at IS NULL AND id IN {fs_visible_sql(uid, c)}",
                       (kind,)).fetchall():
        r = fs_ref_node_role(c, uid, n)
        if r:
            out[n["ref_id"]] = r
    return out


def ctf_renamed(c, kind, rid, name):
    """The book's / contact's new name on its node."""
    if name:
        fs_ref_rename(c, kind, rid, name)


def ctf_dropped(c, kind, rid):
    """The book / contact is gone for good: its node goes."""
    fs_ref_drop(c, kind, rid)


# ---------------------------------------------------------------- the tree of the address book
def ctf_root(c, uid, org_id, create=False):
    return fs_area_root(c, uid, org_id, CTF_AREA, tr("Address book"), create=create)


def _spaces(c, uid):
    full = user_orgs_full(c, uid)
    return [(None, "private")] + [(o, f"org:{int(o)}") for o in user_orgs(c, uid) if o in full]


def _below(c, root):
    """The folders and reference nodes below root (not in the trash), parents first."""
    return c.execute("""WITH RECURSIVE t(id, depth) AS (SELECT id, 0 FROM fs_nodes WHERE id=?
                          UNION ALL SELECT n.id, t.depth + 1 FROM fs_nodes n JOIN t ON n.parent_id=t.id
                          WHERE n.kind IN ('folder', 'ref') AND n.deleted_at IS NULL AND t.depth < 32)
                        SELECT n.* FROM fs_nodes n JOIN t ON t.id=n.id WHERE n.id<>? ORDER BY t.depth, n.id LIMIT 5000""",
                     (int(root), int(root))).fetchall()


def _space_of(c, uid, v):
    if v in (None, "", "private"):
        return None
    try:
        oid = int(str(v)[4:] if str(v).startswith("org:") else v)
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "space")) from None
    if oid not in user_orgs(c, uid):
        raise Denied(404)
    return oid


@app.get("/api/contacts/folders")
def contacts_folders():
    """The address book's folders per workspace: {spaces: [{space, root, can_add}], folders: [{id, parent_id, name, sort_no,
    role (owner | edit | view), shared, space}], items: [{node, parent_id, sort_no, kind (book | contact), id, name, role, may_file (move / share it)}]} --
    only the folders uid sees and the books / contacts uid may open (a book or contact in no folder is not listed)."""
    need_feat("contacts")
    c = db()
    uid = me()
    spaces, folders, items = [], [], []
    for oid, key in _spaces(c, uid):
        root = ctf_root(c, uid, oid)
        spaces.append({"space": key, "root": root, "can_add": oid is None or bool(org_writes(c, uid, oid))})
        if not root:
            continue
        rows = _below(c, root)
        fids = [r["id"] for r in rows if r["kind"] == "folder"]
        shared = set()
        if fids:
            shared = {x[0] for x in c.execute(f"SELECT DISTINCT node_id FROM fs_shares WHERE node_id IN ({','.join(str(int(i)) for i in fids)})")}
        seen = {root}
        for r in rows:
            if r["parent_id"] not in seen:
                continue  # below a folder uid does not see
            if r["kind"] == "folder":
                role = fs_role(c, r["id"], uid)
                if not role:
                    continue
                seen.add(r["id"])
                folders.append({"id": r["id"], "parent_id": r["parent_id"], "name": r["name"], "sort_no": r["sort_no"], "role": role,
                                "shared": r["id"] in shared, "space": key})
            elif r["ref_kind"] in (CTF_BOOK, CTF_CONTACT):
                role = fs_ref_role(c, uid, r["ref_kind"], r["ref_id"])
                if role:
                    items.append({"node": r["id"], "parent_id": r["parent_id"], "sort_no": r["sort_no"], "role": role,
                                  "kind": "book" if r["ref_kind"] == CTF_BOOK else "contact", "id": r["ref_id"], "name": r["name"],
                                  "space": key, "may_file": fs_ref_may_file(c, uid, r["ref_kind"], r["ref_id"])})
    return jsonify(spaces=spaces, folders=folders, items=items)


@app.post("/api/contacts/folders")
def contacts_folder_new():
    """{space, parent_id?, name} -> {folder}: a folder of the address book -- below parent_id, else at the top of the
    workspace's address book (its root folder is made on the first one). Needs the right to add there (like the file store)."""
    need_feat("contacts")
    c = db()
    uid = me()
    b = body()
    raw = str(b.get("name") or "").strip()
    if not raw:
        raise BadInput(tr("Name missing"))
    pid = b.get("parent_id")
    if pid is not None:
        if isinstance(pid, bool) or not isinstance(pid, int):
            raise BadInput(tr("Invalid value: {0}", "parent_id"))
        owner, org = _place(c, uid, pid, None)
    else:  # at the top: below the root, but the person's own (like a folder at the top of the file store)
        oid = _space_of(c, uid, b.get("space"))
        owner, org = _place(c, uid, None, oid)
        pid = ctf_root(c, uid, oid, create=True)
    ts = _now()
    nid = insert_id(c, "INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (pid, "folder", fs_area_folder_name(c, pid, owner, org, safe_fs_name(raw)), owner, org, uid, ts, ts))
    fs_log_add(c, nid, "create")
    bump(c)
    c.commit()
    r = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    return jsonify(folder={"id": nid, "parent_id": pid, "name": r["name"], "sort_no": None, "role": fs_role(c, nid, uid),
                           "shared": False, "space": f"org:{int(org)}" if org else "private"}), 201


def ctf_folder_ids(c, uid, fid):
    """(book ids, contact ids) filed in folder fid or its subfolders that uid may open -- the list's folder filter."""
    chain_role = fs_role(c, int(fid), uid)
    if not chain_role:
        raise Denied(404)
    books, contacts = [], []
    rows = c.execute("""WITH RECURSIVE t(id, depth) AS (SELECT id, 0 FROM fs_nodes WHERE id=?
                          UNION ALL SELECT n.id, t.depth + 1 FROM fs_nodes n JOIN t ON n.parent_id=t.id
                          WHERE n.kind IN ('folder', 'ref') AND n.deleted_at IS NULL AND t.depth < 32)
                        SELECT n.* FROM fs_nodes n JOIN t ON t.id=n.id WHERE n.kind='ref' LIMIT 20000""", (int(fid),)).fetchall()
    for r in rows:
        if r["ref_kind"] in (CTF_BOOK, CTF_CONTACT) and fs_ref_role(c, uid, r["ref_kind"], r["ref_id"]):
            (books if r["ref_kind"] == CTF_BOOK else contacts).append(r["ref_id"])
    return books, contacts

