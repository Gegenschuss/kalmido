"""2.747.0 (#5249): who may take an office step back from the core's step groups (core/undoweb.py undo_need_reg).

The office's rows are tracked kinds (office/owrite.py ow_kind, office/undo.py OUN_KINDS), not registered core kinds: the core
asks the office whether the person may change the row NOW. For this first stage only the cases the editors' own undo
(office/undo.py _ctx) allows without the office groups: an admin of that office area (the personal office: its owner); a
document only while not finalised / sent, a letter only as a draft; a client by its own check (need_client, the invoicing
fields stay for who may not change them). Every other office kind is never written back from the list (core: noaccess) until
#5252 maps the office groups. Its own module (after office.docs / office.letters / office.undo): docs imports office.undo."""
from ..core.errors import Denied
from ..core.i18n import tr
from ..core.undoweb import undo_need_reg
from ..team.clients import CLIENT_BILL_GATED, _gate, cl_bill_ok, need_client
from .docs import doc_row, recalc
from .ledger import ofx_locked
from .letters import lt_row
from .model import MD, office_role
from .undo import OUN_FINAL

UGO_LETTER_SENT = "A sent letter cannot be changed any more. Edit a copy instead."  # the key office/letters.py uses


def _admin(c, uid, oid):
    if not oid or office_role(c, uid, oid) != "admin":
        raise Denied(403)


def ugo_doc(c, uid, ref, oid):
    _admin(c, uid, oid)
    r = doc_row(c, oid, ref)
    if ofx_locked(r) or r["status"] == "sent":
        raise Denied(409, tr(OUN_FINAL))
    return {"fix": lambda c: recalc(c, oid, ref)}  # the sums and the parts' title page lines, as office/undo.py oun_restore


def ugo_client(c, uid, ref, oid):
    _gate(c)
    row = need_client(c, ref, uid)
    return {"keep": None if cl_bill_ok(c, uid, row["org_id"], "edit") else {"clients": set(CLIENT_BILL_GATED)},
            "lock": f"clients-{int(ref)}"}  # the lock of its saves (team/clients.py ow_write lock=)


def ugo_letter(c, uid, ref, oid):
    _admin(c, uid, oid)
    if lt_row(c, oid, ref)["status"] != "draft":
        raise Denied(409, tr(UGO_LETTER_SENT))
    return {}


def ugo_md(c, uid, ref, oid):
    _admin(c, uid, oid)
    return {}


undo_need_reg("office_doc", ugo_doc)
undo_need_reg("client", ugo_client)
undo_need_reg("office_letter", ugo_letter)
for _k in MD:
    undo_need_reg(f"office_md_{_k}", ugo_md)
