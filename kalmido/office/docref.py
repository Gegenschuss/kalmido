"""2.199.0 B (#2742): quotations and invoices (office_docs) filed in folders -- the reference kind 'office_doc' of the folder
system (files/fsref.py). Nothing moves: the PDFs stay where they are (OFFICE_DIR), an office document gets a reference node
only once somebody files it into a folder of its office's file tree (the organisation's tree, a personal office: its owner's
private tree); no node for the documents that exist.

Rights (decision 3 of #2742): the folder gives the higher one of the office groups' level in the area "offers" (base_role)
and the folder's role -- for the DOCUMENT only: open it, read its PDF, change a draft. The special rights (release / send,
payments, lock, export, deleting an invoice) stay with the office groups: there is no route for them here, the office's
own routes keep their checks (office_org / ofr_gate). A finalised document stays unchangeable for everybody
(ofx_need_editable). Agents: only through a share with exactly them (fsref), and then only read (the document, its PDF).

Routes outside /api/office/ (the office gate rules the office routes by the person's groups; a folder is the other way in):
    GET   /api/fsref/office_doc/<did>         the document (as the office route shows it to a non-admin) + role
    GET   /api/fsref/office_doc/<did>/pdf     its PDF (?inline=1), the stored file of a finalised document
    PATCH /api/fsref/office_doc/<did>         change a draft (the office route's body), needs 'edit' through the folder
    PUT   /api/fsref/office_doc/<did>/items   the positions of a draft, needs 'edit'
They run the office's own handlers with the document's office area (office_ctx override, g.ofref_ctx) as "system" for
the rows (a share of a personal office's folder reaches a person outside that office) -- only after fs_ref_role said yes.
"""
from flask import g, jsonify

from ..core.config import app
from ..core.ctx import me
from ..core.db import db
from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_read_file
from ..core.pg import system_ctx
from ..files.fsref import fs_protect_hook, fs_ref_drop, fs_ref_node, fs_ref_register, fs_ref_rename, fs_ref_role
from ..accounts.orgroles import office_allowed
from ..accounts.orgs import org_role
from .docs import doc_public, doc_row, odoc_items_put, odoc_update
from .ledger import ofx_locked, ofx_log
from .model import pb_owner
from .pdfweb import _render, _stored_or_missing, epdf_name, opdf_doc_pdf
from .rights import _is_agent, office_can

OFD_KIND = "office_doc"
OFD_LABEL = {"offer": N_("Quotation"), "invoice": N_("Invoice"), "credit": N_("Credit note"), "reminder": N_("Reminder"),
             "delivery": N_("Delivery note")}
OFD_PROTECT = N_("Finalised invoice")
OFD_PROTECT_DOC = N_("Finalised document")
OFD_RECEIPT_KEPT = N_("Receipt within its retention period")


def _row(c, did):
    with system_ctx(c):  # the folder side asks across offices (a share of a personal office's folder); nothing is handed out
        return c.execute("SELECT id, org_id, kind, number, status, locked_at, trial FROM office_docs WHERE id=?", (int(did),)).fetchone()


def ofd_space(c, did):
    """(org_id | None, owner_id) of the file tree the document belongs to: an organisation's tree; a personal office (a hidden
    organisation row) files into its owner's private tree."""
    r = _row(c, did)
    if not r:
        return None
    owner = pb_owner(c, r["org_id"])
    return (None, owner) if owner is not None else (r["org_id"], None)


def ofd_base_role(c, uid, did):
    """uid's role on the document from the office alone: the level in the area "offers" (office groups; admins and the owner
    of a personal office edit), capped by the organisation role (guests nothing, read-only / accounting read)."""
    r = _row(c, did)
    if not r:
        return None
    oid = r["org_id"]
    if pb_owner(c, oid) is None:
        if org_role(c, uid, oid) is None and not _is_agent(c, uid):
            return None  # not in this organisation (an agent's groups are asked by office_can)
    if not office_can(c, uid, oid, "offers", "view"):
        return None
    if office_allowed(c, uid, oid, write=False):
        return None  # a guest
    if office_allowed(c, uid, oid, write=True) or not office_can(c, uid, oid, "offers", "edit"):
        return "view"
    return "edit"


def ofd_protect(c, did):
    """A finalised document (locked) or an invoice / credit note with a number may not go into the trash with a folder."""
    r = _row(c, did)
    if not r:
        return None
    if r["kind"] in ("invoice", "credit") and (ofx_locked(r) or r["number"]):
        return tr(OFD_PROTECT)
    return tr(OFD_PROTECT_DOC) if ofx_locked(r) else None


def ofd_title(c, did):
    r = _row(c, did)
    if not r:
        return ""
    return f"{tr(OFD_LABEL.get(r['kind'], N_('Quotation')))} {r['number'] or tr('Draft')}".strip()


def ofd_content(c, uid, did):
    """(bytes, file name, mime) of the document's PDF -- the content of its reference node for whoever the folder lets read
    it (an agent through the file API, files/fsref.py; the caller checked fs_ref_role): a finalised document's stored file,
    a draft rendered."""
    r = _row(c, did)
    if not r:
        return None
    oid = r["org_id"]
    with system_ctx(c):
        d = doc_row(c, oid, did)
        p = _stored_or_missing(c, oid, d, "pdf")
        data = oc_read_file(c, p) if p else _render(c, oid, d)[0]
    return data, epdf_name(d) + ".pdf", "application/pdf"


fs_ref_register(OFD_KIND, label=N_("Quotation or invoice"), open_url=lambda did: f"office/offers/{int(did)}",
                base_role=ofd_base_role, space=ofd_space, protect=ofd_protect, title=ofd_title, content=ofd_content)


@fs_protect_hook
def ofd_receipt_kept(c, n):
    """A receipt (a file of the store with an rc_receipts row) inside its legal retention period (receipts/suggest.py
    olk_fs_locked: booked, billed on a finalised document, in the cash book / equipment list) does not go into the trash
    with its folder: it moves one level up (fsref.fs_trash_prepare). Yes / no only, read as "system" (the person deleting
    the folder may not see the receipt: then it stays where it is, out of their sight)."""
    if n["kind"] != "file":
        return None
    from ..receipts.suggest import olk_fs_locked
    with system_ctx(c):
        if not c.execute("SELECT 1 FROM rc_receipts WHERE node_id=?", (n["id"],)).fetchone():
            return None
        kept = olk_fs_locked(c, n["id"])
    return tr(OFD_RECEIPT_KEPT) if kept else None


def ofd_renamed(c, did):
    """The document's number / kind changed: its node (if filed) takes the new title."""
    if fs_ref_node(c, OFD_KIND, did) is not None:
        fs_ref_rename(c, OFD_KIND, did, ofd_title(c, did))


def ofd_deleted(c, did):
    """The document was deleted for good: its node goes."""
    fs_ref_drop(c, OFD_KIND, did)


# ---------------------------------------------------------------- the way in through a folder
def _agent(c, uid):
    return _is_agent(c, uid)


def _need(c, did, write):
    """(c, uid, oid, role) after the folder check: 404 without a role, 403 for a change without 'edit' (agents read only)."""
    uid = me()
    role = fs_ref_role(c, uid, OFD_KIND, did)
    if not role:
        raise Denied(404)
    if write and (role != "edit" or _agent(c, uid)):
        raise Denied(403)
    r = _row(c, did)
    if not r:
        raise Denied(404)
    return uid, r["org_id"], role


def _run(c, uid, oid, fn, *a):
    """Run an office handler for this document with its office area (office_ctx override) as "system"."""
    g.ofref_ctx = (c, uid, oid)
    try:
        with system_ctx(c):
            return fn(*a)
    finally:
        g.ofref_ctx = None


@app.get("/api/fsref/office_doc/<int:did>")
def ofd_get(did):
    """The document as the office shows it to a non-admin, with the role a folder / the office gives ("view" | "edit")."""
    c = db()
    uid, oid, role = _need(c, did, False)

    def go():
        r = doc_row(c, oid, did)
        ofx_log(c, oid, "open", doc_id=did, dedupe_min=10)
        return doc_public(c, oid, r, False)
    out = _run(c, uid, oid, go)
    c.commit()
    out["folder_role"] = role
    return jsonify(out)


@app.get("/api/fsref/office_doc/<int:did>/pdf")
def ofd_pdf(did):
    """The document's PDF (?inline=1): the stored file of a finalised document, a draft rendered."""
    c = db()
    uid, oid, _role = _need(c, did, False)
    return _run(c, uid, oid, opdf_doc_pdf, did)


@app.patch("/api/fsref/office_doc/<int:did>")
def ofd_patch(did):
    """Change a draft through a folder ('edit'): the body of PATCH /api/office/docs/<id>."""
    c = db()
    uid, oid, _role = _need(c, did, True)
    return _run(c, uid, oid, odoc_update, did)


@app.put("/api/fsref/office_doc/<int:did>/items")
def ofd_items(did):
    """The positions of a draft through a folder ('edit'): the body of PUT /api/office/docs/<id>/items."""
    c = db()
    uid, oid, _role = _need(c, did, True)
    return _run(c, uid, oid, odoc_items_put, did)

