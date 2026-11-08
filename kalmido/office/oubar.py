"""2.747.0 (#5252): undo across devices, stage 4 -- the office's steps in the core's step groups (core/undogroups.py).

Labels: a write of an office row (office/owrite.py ow_write, the editors' office/undo.py oun_pre) opens its group with a
label that names the object -- a document by its kind and number (a draft without number: its object number), a client by
its name, a master data row by its name; a column the organisation's key seals at rest is never put into a label (only the
object number then: the label is stored in plain text and shown on every device). ow_kind(label=...) hands these to
core/writes.py obj_track(undo_label=), obj_undo_pre takes them when the route set no label of its own (undo_label).

Barriers: finalising, sending (a document, a letter), a payment (recorded or reversed), the DATEV copy / export and the
period lock write a barrier row of the person (core/undogroups.py undo_barrier, area "office"): the list shows them, "bis
hierher" stops there (core/undoweb.py undo_group_to), and they end the way forward like any new step. The editors' session
undo keeps its own guard (office/undo.py _ctx: 409 OUN_FINAL for a finalised / sent document, the fingerprint for the rest).
Only core imports here: ledger / invoices / letters / periodlock / datev call it without an import cycle.

Interface:
  oub_doc_name(r) -> stored text   "Invoice 2026-031" (kind + number, else "#<id>")
  oub_label_doc(r) / oub_label_client(r) / oub_label_letter(r) / oub_label_md(col)(r) -> (key, [values])
  oub_barrier(c, uid, oid, key, *args) -> id | None   a barrier row of uid in office area oid"""
from flask import g, has_request_context

from ..core.i18n import N_
from ..core.undogroups import UG_LABEL, undo_barrier

OUB_KIND = {"offer": N_("Quotation"), "invoice": N_("Invoice"), "credit": N_("Credit note"), "reminder": N_("Reminder"),
            "delivery": N_("Delivery note")}
OUB_PAIR = "{0} {1}"  # a pattern only (same in every language, like core/i18n.py stored_join)
OUB_FINAL = N_("Finalised: {0}")
OUB_SENT = N_("Sent: {0}")
OUB_PAID = N_("Payment recorded: {0}")
OUB_PAY_BACK = N_("Payment reversed: {0}")
OUB_DATEV = N_("Sent to DATEV: {0}")
OUB_DATEV_EXP = N_("DATEV export: {0} to {1}")
OUB_PERIOD = N_("Months locked up to {0}")
OUB_LETTER = N_("Letter")
SEALED = "kenc"  # core/orgcrypt.py PREFIX "kenc1:" (and later versions): a sealed value never goes into a label


def _plain(v):
    v = v if isinstance(v, str) else ("" if v is None else str(v))
    v = v.strip()
    return "" if not v or v.startswith(SEALED) else v[:80]


def _rid(r):
    return f"#{int(r['id'])}" if r and r.get("id") is not None else "#"


def oub_doc_name(r):
    """The stored name of document row r: [pattern, [kind], number or #id] (translated for the reader)."""
    r = dict(r) if r is not None else {}
    kind = OUB_KIND.get(r.get("kind") or "", N_("Document"))
    return [OUB_PAIR, [kind], _plain(r.get("number")) or _rid(r)]


def oub_label_doc(r):
    return UG_LABEL, [oub_doc_name(r)]


def oub_label_client(r):
    return UG_LABEL, [_plain(r.get("name")) or _rid(r)]


def oub_label_letter(r):
    """A letter's subject and recipient are sealed (core/orgcrypt.py FIELDS office_letters): its object number only."""
    return UG_LABEL, [[OUB_PAIR, [OUB_LETTER], _rid(r)]]


def oub_label_md(col):
    """The label of a master data row (office/model.py MD[kind]["label"] names its column)."""
    return lambda r: (UG_LABEL, [_plain(r.get(col)) or _rid(r)])


def oub_barrier(c, uid, oid, key, *args):
    """A barrier of uid (None: the signed-in person of the request) in office area oid (module docstring); nothing for an
    agent, a background write (a series, the payment provider's hook) or outside a request. One request that books many
    of a kind at once (the bank reconciliation's payments) writes ONE barrier of that kind, unless a step came in between."""
    if not has_request_context():
        return None
    if not uid and getattr(g, "user", None) is not None:
        uid = g.user["id"]
    if not uid:
        return None
    seen = g.setdefault("oub_seen", {})
    k = (key, oid)
    if k in seen and not g.get("undo_group"):
        return seen[k]
    seen[k] = undo_barrier(c, uid, "office", key, args, org_id=oid)
    return seen[k]
