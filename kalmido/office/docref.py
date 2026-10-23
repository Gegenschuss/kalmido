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
    GET   /api/fsref/office_doc/<did>         the document (cut down to the document itself, ofd_view) + role
    GET   /api/fsref/office_doc/<did>/pdf     its PDF (?inline=1), the stored file of a finalised document
    PATCH /api/fsref/office_doc/<did>         change a draft (the office route's body without links into the master data), 'edit'
    PUT   /api/fsref/office_doc/<did>/items   the positions of a draft (no new catalogue service), needs 'edit'
They run the office's own handlers with the document's office area (office_ctx override, g.ofref_ctx) as "system" for
the rows (a share of a personal office's folder reaches a person outside that office) -- only after fs_ref_role said yes.
"""
import json

from flask import g, jsonify

from ..core.config import app
from ..core.ctx import me
from ..core.db import body, db
from ..core.errors import Denied
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_read_file
from ..core.pg import system_ctx
from ..files.fsref import fs_protect_hook, fs_ref_drop, fs_ref_node, fs_ref_register, fs_ref_rename, fs_ref_role
from ..accounts.orgroles import office_allowed
from ..accounts.orgs import org_role
from .docs import doc_public, doc_row, odoc_items_put, odoc_update
from .ledger import ofx_locked, ofx_log
from .model import OFFICE_OFF, office_on, pb_owner
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
    """The document was deleted for good: its node goes (2.199.0 G: as "system" -- the node may lie in a folder the deleting
    person does not see, it must not stay behind pointing at nothing)."""
    with system_ctx(c):
        fs_ref_drop(c, OFD_KIND, did)


# ---------------------------------------------------------------- the way in through a folder
def _agent(c, uid):
    return _is_agent(c, uid)


def _need(c, did, write):
    """(c, uid, oid, role) after the folder check: 404 without a role, 403 for a change without 'edit' (agents read only).
    2.199.0 G (#2742): a person meets the office gate's locks here as well (model.office_gate): a kid's account nothing,
    the office turned off in the settings 403 -- agents keep their read through their own share."""
    uid = me()
    role = fs_ref_role(c, uid, OFD_KIND, did)
    if not role:
        raise Denied(404)
    u = g.user
    if u is not None and not _agent(c, uid):
        if "kid" in u.keys() and u["kid"]:
            raise Denied(403)
        if not office_on(c, uid):
            raise Denied(403, tr(OFFICE_OFF))
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


# 2.199.0 G (#2742 review): the folder way hands out the DOCUMENT -- head, its recipient, positions, totals, status -- never
# the office's master data or its business: no payments, credit notes, billed time, the client's contact list, the framework
# contract with its rates, the catalogue ids of positions, the cash flow chain, who finalised it, Peppol sends.
OFD_VIEW = frozenset((
    "id", "kind", "number", "status", "state", "status_text", "statuses", "lang", "currency", "vat_mode", "recipient",
    "recipient_missing", "project_title", "project_ref", "intro", "closing", "order_ref", "date", "valid_until", "service_from",
    "service_to", "due_date", "payment_days", "vat_note", "delivery_title", "reminder_level", "reminder_fee",
    "reminder_deadline_days", "skonto_pct", "skonto_days", "inv_type", "raw_mode", "raw_factor", "producing_on", "producing_mode",
    "producing_rate", "prod_quotient", "discount_pct", "handling_pct", "markup_pct", "handling_label", "markup_label",
    "share_label", "markup_stacked", "fields", "totals", "net_text", "gross_text", "items", "parts", "accept_print", "locked",
    "can_edit", "trial", "created_at", "updated_at", "lang_notes"))
OFD_ITEM = frozenset(("id", "sort", "kind", "title", "detail", "qty", "unit", "rate", "tax", "tax_pct", "net", "tax_amount",
                      "raw_fee", "producing", "in_handling", "in_markup", "intext", "discountable", "part_id", "ref_part_id"))
OFD_PART = frozenset(("id", "kind", "title", "print", "sort", "settings", "totals", "used", "items"))


def _ofd_items(its):
    return [{k: v for k, v in it.items() if k in OFD_ITEM} for it in its or [] if isinstance(it, dict)]


def ofd_view(d):
    """The office's document (doc_public, non-admin) cut down to what the folder way may show (OFD_VIEW)."""
    out = {k: v for k, v in d.items() if k in OFD_VIEW}
    if "items" in out:
        out["items"] = _ofd_items(out["items"])
    if "parts" in out:
        out["parts"] = [{**{k: v for k, v in p.items() if k in OFD_PART}, **({"items": _ofd_items(p["items"])} if "items" in p else {})}
                        for p in out["parts"] or [] if isinstance(p, dict)]
    rt = d.get("rights")
    if isinstance(rt, dict):  # the texts as they stand in the document, not the catalogue's ids
        out["rights"] = {k: ({"id": None, "text": (v or {}).get("text") or ""} if k in ("time", "territory", "media") else v)
                         for k, v in rt.items()}
    return out


def _ofd_out(resp):
    """An office handler's answer (a flask response) for the folder way: the document cut down, errors as they are."""
    if getattr(resp, "status_code", 200) != 200 or not getattr(resp, "is_json", False):
        return resp
    return jsonify(ofd_view(resp.get_json()))


# 2.199.0 G (#2742 review): a change through a folder touches the document's own fields only. Every field that links into the
# office's master data (a client and its contacts, a framework contract with its rates, a catalogue service or text) would
# let the person read that data from the answer by trying ids: a new link is refused (403), the same link as now is fine.
OFD_HEAD = frozenset((
    "lang", "currency", "fx_rate", "vat_mode", "recipient", "project_title", "project_ref", "intro", "closing", "order_ref",
    "date", "valid_until", "service_from", "service_to", "due_date", "payment_days", "vat_note", "einvoice_format",
    "delivery_title", "skonto_pct", "skonto_days", "inv_type", "reminder_level", "reminder_fee", "reminder_deadline_days",
    "raw_mode", "producing_on", "accept_on", "raw_factor", "prod_quotient", "producing_rate", "discount_pct", "handling_pct",
    "markup_pct", "handling_label", "markup_label", "markup_stacked", "rights", "fields"))
OFD_LINKS = ("client_id", "contact_id", "contract_id")
OFD_NO_LINK = N_("Through a folder only the document itself can be changed, not its client, contact person, framework contract or catalogue entries")


def _same_id(a, b):
    try:
        return (int(a) if a not in (None, "", 0, "0") else None) == (int(b) if b not in (None, "", 0) else None)
    except (TypeError, ValueError):
        return False


def ofd_head_body(c, did, b):
    """The PATCH body for the folder way: OFD_HEAD fields; client / contact / contract only unchanged (dropped); a rights
    text taken from the catalogue by its id only as the id it has now."""
    if not isinstance(b, dict):
        return b
    with system_ctx(c):
        cur = c.execute("SELECT client_id, contact_id, contract_id, rights FROM office_docs WHERE id=?", (int(did),)).fetchone()
    for k in OFD_LINKS:
        if k in b and not _same_id(b.get(k), cur[k] if cur else None):
            raise Denied(403, tr(OFD_NO_LINK))
    out = {k: v for k, v in b.items() if k in OFD_HEAD}
    rt = out.get("rights")
    if isinstance(rt, dict):
        try:
            now = json.loads(cur["rights"] or "{}") if cur else {}
        except (TypeError, ValueError):
            now = {}
        for dim in ("time", "territory", "media"):
            x = rt.get(dim)
            if isinstance(x, dict) and x.get("id") not in (None, "") and not _same_id(x.get("id"), ((now or {}).get(dim) or {}).get("id")):
                raise Denied(403, tr(OFD_NO_LINK))
    return out


def ofd_items_body(c, oid, did, b):
    """The PUT items body for the folder way: a position keeps the catalogue service it has (by its id), never takes a new
    one; an empty title / rate of such a position stays as it is (no lookup in the catalogue)."""
    items = b.get("items") if isinstance(b, dict) else b
    if not isinstance(items, list):
        return b
    with system_ctx(c):
        old = {r["id"]: r for r in c.execute("SELECT id, service_id, title, rate FROM office_doc_items WHERE doc_id=? AND org_id=?",
                                              (int(did), oid))}
    out = []
    for it in items:
        if isinstance(it, dict) and it.get("service_id") not in (None, "", 0):
            try:
                prev = old.get(int(it.get("id") or 0))
            except (TypeError, ValueError):
                prev = None
            if not prev or not _same_id(it.get("service_id"), prev["service_id"]):
                raise Denied(403, tr(OFD_NO_LINK))
            it = {**it, "title": it.get("title") or prev["title"], "rate": str(prev["rate"]) if it.get("rate") in (None, "") else it["rate"]}
        if isinstance(it, dict):
            it = {k: v for k, v in it.items() if k != "cost"}
        out.append(it)
    return {**b, "items": out} if isinstance(b, dict) else out


def _with_body(b, fn, *a):
    """Run fn with b as the request body (core.db.body reads g.body first)."""
    had = g.get("body")
    g.body = b
    try:
        return fn(*a)
    finally:
        g.body = had


@app.get("/api/fsref/office_doc/<int:did>")
def ofd_get(did):
    """The document as the office shows it to a non-admin, with the role a folder / the office gives ("view" | "edit")."""
    c = db()
    uid, oid, role = _need(c, did, False)

    def go():
        r = doc_row(c, oid, did)
        ofx_log(c, oid, "open", doc_id=did, dedupe_min=10)
        return doc_public(c, oid, r, False)
    out = ofd_view(_run(c, uid, oid, go))
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
    """Change a draft through a folder ('edit'): the body of PATCH /api/office/docs/<id>, only the fields without a link
    into the office's master data (ofd_head_body)."""
    c = db()
    uid, oid, _role = _need(c, did, True)
    return _ofd_out(_with_body(ofd_head_body(c, did, body()), _run, c, uid, oid, odoc_update, did))


@app.put("/api/fsref/office_doc/<int:did>/items")
def ofd_items(did):
    """The positions of a draft through a folder ('edit'): the body of PUT /api/office/docs/<id>/items, free positions
    (no new catalogue service, ofd_items_body)."""
    c = db()
    uid, oid, _role = _need(c, did, True)
    return _ofd_out(_with_body(ofd_items_body(c, oid, did, body()), _run, c, uid, oid, odoc_items_put, did))

