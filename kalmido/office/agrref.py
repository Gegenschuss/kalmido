"""2.351.0 B (#2749): contracts in folders -- the reference kinds 'contract_file' (a PDF of a framework contract,
office_contract_files, office/contractfiles.py) and 'office_agreement' (a contract / insurance of Office > Contracts &
insurance, office_agreements, office/agreements.py) of the folder system (files/fsref.py).

Nothing moves: the PDFs stay where they are (OFFICE_DIR, sealed), the rows stay as they are; a PDF / contract gets a
reference node only once somebody files it into a folder of its office's file tree (an organisation's tree; a personal
office: its owner's private tree) -- then it shows in the file store (Ablage) and can be shared there like any document.
An older version reading a database with these nodes ignores them (unknown kinds: fsref.fs_ref_json no_access).

Rights: the folder gives the higher one of the office's own role (base_role) and the folder's role -- for READING the
document only: a framework contract's PDF (its content), a contract / insurance as a short text (its fields). Every change,
deleting, the deadline task and the cash flow stay with the office's own routes and their rights (office/rights.py: the
office groups, the admins): cap = 'view' for everybody who is not an admin of the area, so a folder never gives more.
Filing needs 'edit' from the office itself (framework contracts: the admins of the area "contracts"; contracts &
insurance: the admins, a personal office: its person). Agents: only through a share with exactly them, and only with the
office's agent switches for the area (like office/docref.py); a token without the scope office never.
A deleted PDF / contract (in its trash) gives nothing through its node; a folder going into the trash deletes nothing."""
import os

from flask import g, has_request_context

from ..core.access import Denied
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_read_file
from ..core.pg import system_ctx
from ..files.fsref import fs_ref_all_sql, fs_ref_register, fs_ref_token_lacks
from ..files.scan import sc_guard
from ..accounts.orgroles import office_allowed
from ..accounts.orgs import org_role
from .agentdocs import ofa_agent_ok
from .agreements import AGR_DELETED, bk_public
from .contractfiles import dma_path
from .model import OFFICE_OFF, office_on, pb_owner
from .rights import _is_agent, office_can, ofr_admin_or

AGR_KIND = "office_agreement"
DMA_KIND = "contract_file"
AGR_AREA = {AGR_KIND: "agreements", DMA_KIND: "contracts"}


def _agr(c, aid):
    with system_ctx(c):  # structure only (which office, deleted?): the folder side asks across offices
        return c.execute("SELECT id, org_id, name, provider, archived FROM office_agreements WHERE id=?", (int(aid),)).fetchone()


def _dma(c, fid):
    with system_ctx(c):
        return c.execute("SELECT f.id, f.org_id, f.contract_id, f.name, f.file, f.deleted_at, k.name AS cname FROM office_contract_files f "
                         "LEFT JOIN office_contracts k ON k.id=f.contract_id WHERE f.id=?", (int(fid),)).fetchone()


def _row(c, kind, rid):
    return _agr(c, rid) if kind == AGR_KIND else _dma(c, rid)


def _gone(kind, r):
    return r is None or (r["archived"] == AGR_DELETED if kind == AGR_KIND else bool(r["deleted_at"]))


def _space(kind):
    def f(c, rid):
        r = _row(c, kind, rid)
        if _gone(kind, r):
            return None
        owner = pb_owner(c, r["org_id"])
        return (None, owner) if owner is not None else (r["org_id"], None)
    return f


def _admin(c, uid, oid, area):
    """Does uid manage area of office oid (the office's admins, a personal office's person, the group level 'manage')?"""
    owner = pb_owner(c, oid)
    if owner is not None:
        return owner == uid
    if org_role(c, uid, oid) is None or office_allowed(c, uid, oid, write=True):
        return False  # not in the organisation; guests, read-only and accounting manage nothing
    return bool(ofr_admin_or(c, uid, oid, area, "edit"))


def _base(kind):
    def f(c, uid, rid):
        r = _row(c, kind, rid)
        if _gone(kind, r) or _is_agent(c, uid):
            return None  # agents: only through a share (fsref)
        oid = r["org_id"]
        if _admin(c, uid, oid, AGR_AREA[kind]):
            return "edit"
        if kind == AGR_KIND or pb_owner(c, oid) is not None:
            return None  # contracts & insurance: admins only; a personal office: its person only
        if org_role(c, uid, oid) is None or office_allowed(c, uid, oid, write=False):
            return None  # framework contracts: read by who works in the office area, not guests
        return "view" if office_can(c, uid, oid, "contracts", "view") else None
    return f


def _cap(kind):
    def f(c, uid, rid):
        """The most a folder share gives: reading (changes stay with the office's routes); a guest of the organisation nothing."""
        r = _row(c, kind, rid)
        if r is None or office_allowed(c, uid, r["org_id"], write=False):
            return None
        return "view"
    return f


def _agent_reads(c, uid, kind, oid):
    if fs_ref_token_lacks(uid, "office"):
        return False
    with system_ctx(c):  # the area's switches (yes / no), whichever workspace the agent's row-level security reaches
        return bool(ofa_agent_ok(c, uid, oid, AGR_AREA[kind], "view"))


def _gate(kind):
    def f(c, uid, rid):
        """The office's locks on the file store's content routes (like office/docref.py ofd_gate)."""
        r = _row(c, kind, rid)
        if r is None:
            raise Denied(404)
        if _is_agent(c, uid):
            if not _agent_reads(c, uid, kind, r["org_id"]):
                raise Denied(403)
            return
        if fs_ref_token_lacks(uid, "office"):
            raise Denied(403, tr("This token lacks the permission “{0}”", "office"))
        u = g.get("user") if has_request_context() else None
        if u is not None and u["id"] == uid and "kid" in u.keys() and u["kid"]:
            raise Denied(403)
        if not office_on(c, uid):
            raise Denied(403, tr(OFFICE_OFF))
    return f


def _hidden(kind):
    table = "office_agreements" if kind == AGR_KIND else "office_contract_files"

    def f(c, uid):
        """A token without the scope office: every filed one; an agent: those of the offices it may not read."""
        if fs_ref_token_lacks(uid, "office"):
            return fs_ref_all_sql(kind)
        if not _is_agent(c, uid):
            return ""
        key = (kind, int(uid))
        if has_request_context() and key in g.setdefault("agrref_cache", {}):
            return g.agrref_cache[key]
        with system_ctx(c):  # the offices of the filed rows (structure: ids only)
            rows = c.execute(f"SELECT n.ref_id, t.org_id FROM fs_nodes n JOIN {table} t ON t.id=n.ref_id "
                             "WHERE n.kind='ref' AND n.ref_kind=?", (kind,)).fetchall()
        ok = {}
        for x in rows:
            if x[1] not in ok:
                ok[x[1]] = _agent_reads(c, uid, kind, x[1])
        bad = [int(x[0]) for x in rows if not ok[x[1]]]
        out = f"({','.join(str(i) for i in bad)})" if bad else ""
        if has_request_context():
            g.agrref_cache[key] = out
        return out
    return f


def _dma_title(c, fid):
    r = _dma(c, fid)
    return (r["name"] or "contract.pdf") if r is not None else ""


def _dma_content(c, uid, fid):
    """The PDF (decrypted), for whoever the folder lets read it (the caller checked fs_ref_role and the gate)."""
    r = _dma(c, fid)
    if _gone(DMA_KIND, r):
        return None
    p = dma_path(r["org_id"], r["file"])
    if not p or not os.path.isfile(p):
        return None
    sc_guard(c, "ocf", r["id"])  # found infected (strict: not checked yet) = locked, like the office's own route
    with system_ctx(c):  # the office area's key (a personal office's folder shared with a person outside it)
        data = oc_read_file(c, p)
    return data, r["name"] or "contract.pdf", "application/pdf"


def _agr_title(c, aid):
    r = _agr(c, aid)
    return (r["name"] or tr("Contract")) if r is not None else ""


def _agr_content(c, uid, aid):
    """The contract / insurance as a short text: kind, provider, number, contribution, term, notice, note (the office keeps
    the rest; its document has its own node in the documents)."""
    r = _agr(c, aid)
    if _gone(AGR_KIND, r):
        return None
    with system_ctx(c):  # the row and the office area's key (decrypting the number, cost and note)
        row = c.execute("SELECT * FROM office_agreements WHERE id=?", (r["id"],)).fetchone()
        d = bk_public(c, r["org_id"], uid, row)
    per = {"month": tr("per month"), "quarter": tr("per quarter"), "year": tr("per year")}.get(d.get("per") or "", d.get("per") or "")
    unit = {"d": tr("days"), "w": tr("weeks"), "m": tr("months")}.get(d.get("notice_unit") or "", "")
    lines = [d.get("name") or "",
             f"{tr('Provider')}: {d['provider']}" if d.get("provider") else "",
             f"{tr('Policy or contract number')}: {d['number']}" if d.get("number") else "",
             f"{tr('Contribution')}: {d['cost']} {per}".strip() if d.get("cost") not in (None, "") else "",
             f"{tr('Start')}: {d['start']}" if d.get("start") else "",
             f"{tr('End of the current term')}: {d['ends']}" if d.get("ends") else "",
             f"{tr('Notice period')}: {d['notice']} {unit}".strip() if d.get("notice") else "",
             f"{tr('Cancel by {0}', d['deadline']['cancel_by'])}" if d.get("deadline") and d["deadline"].get("cancel_by") else "",
             "", d.get("note") or ""]
    name = "".join(ch if ch.isalnum() or ch in " -_." else "_" for ch in (d.get("name") or "contract"))[:80].strip() or "contract"
    return ("\n".join(x for x in lines if x is not None).strip() + "\n").encode("utf-8"), f"{name}.txt", "text/plain"


fs_ref_register(DMA_KIND, label=N_("Framework contract"), open_url=lambda fid: "office/contracts", base_role=_base(DMA_KIND),
                space=_space(DMA_KIND), title=_dma_title, content=_dma_content, content_gate=_gate(DMA_KIND),
                hidden=_hidden(DMA_KIND), cap=_cap(DMA_KIND))
fs_ref_register(AGR_KIND, label=N_("Contract or insurance"), open_url=lambda aid: "office/agreements", base_role=_base(AGR_KIND),
                space=_space(AGR_KIND), title=_agr_title, content=_agr_content, content_gate=_gate(AGR_KIND),
                hidden=_hidden(AGR_KIND), cap=_cap(AGR_KIND))
