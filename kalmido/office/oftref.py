"""2.351.0 A (#2823, #3312): generated documents, letters and receipts filed in folders -- the reference kinds
'office_gendoc' (office_gen_docs), 'office_letter' (office_letters) and 'office_receipt' (rc_receipts, ref_id = the
receipt's file node) of the folder system (files/fsref.py), like office/docref.py for quotations / invoices ('office_doc').
Nothing moves: an object gets a reference node only once somebody files it into a folder of its office's file tree (the
organisation's tree, a personal office: its owner's private tree); the PDFs / the receipt's file stay where they are.

Rights: the folder gives the higher one of the area's own role (base_role: the office groups' level in the area "gendocs"
/ "letters"; a receipt: the role on its file, which keeps the receipts lock of the office groups, files/store.py) and the
folder's role -- for reading the DOCUMENT only (its PDF / the receipt's file through the file store's content routes).
Finalising, signature links, sending, booking stay with the office's own routes. Agents only through a share with exactly
them and the office's agent switches (hidden, like docref.ofd_hidden); a token without the scope office nothing.
- hidden: receipts keep the receipts lock of the office groups for people too (level receipts below "view": none; "own":
  only the receipts they uploaded) -- the reference node must not open what the receipt's own file does not.
- protect: a finalised / signed document, a sent letter, a receipt within its retention period move one level up when their
  folder goes into the trash.
- title: a letter's subject and recipient are encrypted at rest -- its node is named "Letter <date>" (never the subject in
  the file store's plain names); the office's tree (office/oftree.py) shows the subject decrypted.
"""
from flask import g, has_request_context

from ..core.access import Denied
from ..core.orgcrypt import oc_dec_fields
from ..core.i18n import N_, tr
from ..core.pg import system_ctx
from ..files.fsref import fs_ref_all_sql, fs_ref_drop, fs_ref_node, fs_ref_register, fs_ref_rename, fs_ref_token_lacks
from ..files.store import fs_read, fs_role
from ..accounts.orgroles import office_allowed
from ..accounts.orgs import org_role
from .model import OFFICE_OFF, office_on, pb_owner, pb_personal
from .rights import LV, _is_agent, office_can, ofr_rights

GD_KIND = "office_gendoc"
LT_KIND = "office_letter"
RC_KIND = "office_receipt"
OFT_FINAL = N_("Finalised document")
OFT_SENT = N_("Sent letter")
OFT_KEPT = N_("Receipt within its retention period")


# ---------------------------------------------------------------- the rows (as "system": the folder side asks across offices)
def _gd(c, rid):
    with system_ctx(c):
        return c.execute("SELECT id, org_id, title, status, node_id FROM office_gen_docs WHERE id=?", (int(rid),)).fetchone()


def _lt(c, rid):
    with system_ctx(c):
        return c.execute("SELECT id, org_id, status, letter_date, node_id FROM office_letters WHERE id=?", (int(rid),)).fetchone()


def _rc(c, rid):
    with system_ctx(c):
        return c.execute("""SELECT r.node_id, r.org_id, r.ws, n.name, n.mime, n.owner_id, n.created_by FROM rc_receipts r
                            JOIN fs_nodes n ON n.id=r.node_id WHERE r.node_id=? AND n.kind='file'""", (int(rid),)).fetchone()


def _ws_space(ws):
    """(org_id | None, owner_id) of a documents space 'o<org>' | 'u<person>' (docs/store.py doc_ws), None when unknown."""
    ws = str(ws or "")
    if ws[:1] in ("o", "u") and ws[1:].isdigit():
        return (int(ws[1:]), None) if ws[0] == "o" else (None, int(ws[1:]))
    return None


def _rc_oid(c, r):
    """The office area of receipt row r: the organisation, a private receipt its owner's personal office (None: none yet)."""
    sp = _ws_space(r["ws"])
    if not sp:
        return None
    return sp[0] if sp[0] else pb_personal(c, sp[1], create=False)


def _space(row):
    def space(c, rid):
        r = row(c, rid)
        if not r:
            return None
        owner = pb_owner(c, r["org_id"])
        return (None, owner) if owner is not None else (r["org_id"], None)
    return space


def rc_space(c, rid):
    r = _rc(c, rid)
    return _ws_space(r["ws"]) if r else None


# ---------------------------------------------------------------- roles
def oft_base(c, uid, oid, area):
    """uid's role on a document of office oid's area from the office alone (as docref.ofd_base_role for "offers"): the
    level of the office groups, capped by the organisation role (guests nothing, read-only / accounting read)."""
    if not oid:
        return None
    if pb_owner(c, oid) is None and org_role(c, uid, oid) is None and not _is_agent(c, uid):
        return None
    if not office_can(c, uid, oid, area, "view") or office_allowed(c, uid, oid, write=False):
        return None
    if office_allowed(c, uid, oid, write=True) or not office_can(c, uid, oid, area, "edit"):
        return "view"
    return "edit"


def _base(row, area):
    def base(c, uid, rid):
        r = row(c, rid)
        return oft_base(c, uid, r["org_id"], area) if r else None
    return base


def rc_base(c, uid, rid):
    """A receipt: the role on its file (the file store's rules with the receipts lock of the office groups)."""
    if not _rc(c, rid):
        return None
    role = fs_role(c, int(rid), uid)
    return "edit" if role in ("owner", "edit") else "view" if role == "view" else None


def _cap_oid(c, oid, uid):
    if office_allowed(c, uid, oid, write=False):
        return None
    return "view" if office_allowed(c, uid, oid, write=True) else "edit"


def _cap(row):
    def cap(c, uid, rid):
        r = row(c, rid)
        return _cap_oid(c, r["org_id"], uid) if r else None
    return cap


def rc_cap(c, uid, rid):
    r = _rc(c, rid)
    if not r:
        return None
    sp = _ws_space(r["ws"])
    return _cap_oid(c, sp[0], uid) if sp and sp[0] else "edit"


def _agent_reads(c, uid, oid, area):
    """Agent uid may read the area's documents of office oid like through the office's agent routes (docref._agent_reads)."""
    from .agentdocs import ofa_agent_ok
    if not oid or fs_ref_token_lacks(uid, "office"):
        return False
    with system_ctx(c):
        return bool(ofa_agent_ok(c, uid, oid, area, "view"))


def _gate(row_oid, area):
    """The office's locks on the file store's content routes (like docref.ofd_gate): a token needs the scope office, an agent
    the office's agent switches, a kid's account nothing, the office turned off 403."""
    def gate(c, uid, rid):
        ok, oid = row_oid(c, rid)
        if not ok:
            raise Denied(404)
        if _is_agent(c, uid):
            if not _agent_reads(c, uid, oid, area):
                raise Denied(403)
            return
        if fs_ref_token_lacks(uid, "office"):
            raise Denied(403, tr("This token lacks the permission “{0}”", "office"))
        u = g.get("user") if has_request_context() else None
        if u is not None and u["id"] == uid and "kid" in u.keys() and u["kid"]:
            raise Denied(403)
        if not office_on(c, uid):
            raise Denied(403, tr(OFFICE_OFF))
    return gate


def _receipt_locked(c, uid, org, created_by):
    """The receipts lock of the office groups (files/store.py _fs_receipt_hidden) for an organisation's receipt."""
    r = ofr_rights(c, uid, org)
    if r is None:
        return False
    lv = r["levels"].get("receipts", "none")
    return not (LV[lv] >= LV["view"] or (lv == "own" and created_by == uid))


def _hidden(kind, area):
    """What a folder never opens to uid: a token without the scope office every filed object of kind; an agent the objects
    of every office it may not read; receipts: also the receipts lock of the office groups (people and agents)."""
    def hidden(c, uid):
        if fs_ref_token_lacks(uid, "office"):
            return fs_ref_all_sql(kind)
        agent = _is_agent(c, uid)
        if not agent and kind != RC_KIND:
            return ""
        key = ("oft_hidden", kind, int(uid))
        if has_request_context() and key in g.setdefault("oft_cache", {}):
            return g.oft_cache[key]
        with system_ctx(c):  # the offices of the filed objects (structure: ids only)
            if kind == RC_KIND:
                rows = [(x[0], x[1], x[2]) for x in c.execute(
                    "SELECT n.ref_id, r.ws, COALESCE(f.created_by, f.owner_id) FROM fs_nodes n JOIN rc_receipts r ON r.node_id=n.ref_id "
                    "JOIN fs_nodes f ON f.id=r.node_id WHERE n.kind='ref' AND n.ref_kind=?", (kind,)).fetchall()]
            else:
                tbl = "office_gen_docs" if kind == GD_KIND else "office_letters"
                rows = [(x[0], x[1], None) for x in c.execute(
                    f"SELECT n.ref_id, d.org_id FROM fs_nodes n JOIN {tbl} d ON d.id=n.ref_id WHERE n.kind='ref' AND n.ref_kind=?",
                    (kind,)).fetchall()]
        ok, bad = {}, []
        for rid, where, by in rows:
            if kind == RC_KIND:
                sp = _ws_space(where)
                org = sp[0] if sp else None
                if org and _receipt_locked(c, uid, org, by):
                    bad.append(int(rid))
                    continue
                if not agent:
                    continue
                oid = org or (pb_personal(c, sp[1], create=False) if sp else None)
            else:
                oid = where
            if oid not in ok:
                ok[oid] = _agent_reads(c, uid, oid, area)
            if not ok[oid]:
                bad.append(int(rid))
        out = f"({','.join(str(i) for i in bad)})" if bad else ""
        if has_request_context():
            g.oft_cache[key] = out
        return out
    return hidden


# ---------------------------------------------------------------- protect / title / content
def gd_protect(c, rid):
    r = _gd(c, rid)
    return tr(OFT_FINAL) if r and r["status"] in ("final", "signed") else None


def lt_protect(c, rid):
    r = _lt(c, rid)
    return tr(OFT_SENT) if r and r["status"] != "draft" else None


def rc_protect(c, rid):
    from ..receipts.suggest import olk_fs_locked
    if not _rc(c, rid):
        return None
    with system_ctx(c):
        kept = olk_fs_locked(c, int(rid))
    return tr(OFT_KEPT) if kept else None


def gd_title(c, rid):
    r = _gd(c, rid)
    return (r["title"] or tr("Document")) if r else ""


def lt_title(c, rid):
    r = _lt(c, rid)
    return f"{tr('Letter')} {r['letter_date'] or ''}".strip() if r else ""


def rc_title(c, rid):
    r = _rc(c, rid)
    return r["name"] if r else ""


def _stored(c, nid):
    """The bytes of a filed PDF (node nid) or None (missing / in the trash)."""
    if not nid:
        return None
    n = c.execute("SELECT deleted_at FROM fs_nodes WHERE id=?", (int(nid),)).fetchone()
    if not n or n["deleted_at"]:
        return None
    try:
        return fs_read(c, int(nid))
    except Denied:
        return None


def _pdf_name(t):
    t = "".join(ch for ch in str(t or "") if ch not in '\\/:*?"<>|\r\n\t').strip()[:120]
    return (t or "document") + ".pdf"


def gd_content(c, uid, rid):
    """(bytes, name, mime) of a generated document: the filed PDF of a finished one, else written (a draft as a preview)."""
    from .doctpl import dt_pdf
    r = _gd(c, rid)
    if not r:
        return None
    oid = r["org_id"]
    with system_ctx(c):
        d = dict(oc_dec_fields(c, oid, "office_gen_docs", c.execute("SELECT * FROM office_gen_docs WHERE id=?", (int(rid),)).fetchone()))
        data = _stored(c, d["node_id"]) if d["status"] != "draft" else None
        data = data if data is not None else dt_pdf(c, oid, d)
    return data, _pdf_name(d["title"]), "application/pdf"


def lt_content(c, uid, rid):
    """(bytes, name, mime) of a letter: the filed PDF of a sent one, else written (a draft says DRAFT)."""
    from .letters import lt_pdf, lt_row
    r = _lt(c, rid)
    if not r:
        return None
    oid = r["org_id"]
    with system_ctx(c):
        d = lt_row(c, oid, int(rid))
        data = _stored(c, d.get("node_id")) if d["status"] != "draft" else None
        data = data if data is not None else lt_pdf(c, oid, d)
    return data, _pdf_name(lt_title(c, rid)), "application/pdf"


def rc_content(c, uid, rid):
    r = _rc(c, rid)
    if not r:
        return None
    with system_ctx(c):
        data = fs_read(c, int(rid))
    return data, r["name"], r["mime"] or "application/octet-stream"


def _row_oid(row):
    def f(c, rid):
        r = row(c, rid)
        return (True, r["org_id"]) if r else (False, None)
    return f


def _rc_row_oid(c, rid):
    r = _rc(c, rid)
    return (True, _rc_oid(c, r)) if r else (False, None)


fs_ref_register(GD_KIND, label=N_("Document"), open_url=lambda rid: f"office/gendocs/{int(rid)}", base_role=_base(_gd, "gendocs"),
                space=_space(_gd), protect=gd_protect, title=gd_title, content=gd_content, content_gate=_gate(_row_oid(_gd), "gendocs"),
                hidden=_hidden(GD_KIND, "gendocs"), cap=_cap(_gd))
fs_ref_register(LT_KIND, label=N_("Letter"), open_url=lambda rid: f"office/letters/{int(rid)}", base_role=_base(_lt, "letters"),
                space=_space(_lt), protect=lt_protect, title=lt_title, content=lt_content, content_gate=_gate(_row_oid(_lt), "letters"),
                hidden=_hidden(LT_KIND, "letters"), cap=_cap(_lt))
fs_ref_register(RC_KIND, label=N_("Receipt"), open_url=lambda rid: f"docs/{int(rid)}", base_role=rc_base, space=rc_space,
                protect=rc_protect, title=rc_title, content=rc_content, content_gate=_gate(_rc_row_oid, "receipts"),
                hidden=_hidden(RC_KIND, "receipts"), cap=rc_cap)


def oft_renamed(c, kind, rid, title):
    """The object's title changed: its node (if filed) takes the new one."""
    if fs_ref_node(c, kind, rid) is not None:
        fs_ref_rename(c, kind, rid, title)


def oft_dropped(c, kind, rid):
    """The object was deleted for good (as "system": the node may lie in a folder the deleting person does not see)."""
    with system_ctx(c):
        fs_ref_drop(c, kind, rid)
