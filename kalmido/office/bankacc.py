"""2.470.0 (#3596, part A): the bank accounts of an office as master data (table office_bank_accounts): several per office, exactly
one of them the default. IBAN, BIC and bank name are sealed like the company's (core/orgcrypt.py).

The default account feeds everything that printed or read the company's bank fields: ledger.ofx_company lays it over those
fields, so the printed lines, the payment data of a document, the e-invoice and the GiroCode follow without a change of their
own, and the sender snapshot of a finished document stays frozen. Order: the default account, else the company fields, else the
free bank lines of the settings. The company fields stay stored; the first look of somebody with the right makes the default
account from them (bka_seed, once per office, nothing is deleted), and a later write to them goes on to the default account
(bka_mirror: an older client, the settings API) so there is one truth.

DATEV: the ledger account of the bank is a plain number without a link to the IBAN, so each account may carry its own
(datev_account); empty = the account of the DATEV settings as before (bka_datev).

Rights: whoever gets the company's bank fields today (bka_sees: the admin, or a group that manages the settings), nobody else --
members and the role accounting get a 403 here as they get empty fields in GET /api/office/settings. No agents (office_gate)."""
import re

from flask import jsonify, request

from ..core.access import Denied
from ..core.config import app
from ..core.db import body, err, iso, now_utc
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import insert_id, write_lock
from .ledger import ofx_company_clean, ofx_log
from .model import OFFICE_ADMIN_ONLY, office_ctx_admin as _ctx, office_role, office_settings
from .rights import office_can, ofr_mine

BKA_TABLE = "office_bank_accounts"
BKA_BANK = ("iban", "bic", "bank_name")
BKA_MAX = 30  # accounts of an office, archived ones included
BKA_LABEL_MAX = 80
BKA_LAST = N_("This is the only bank account. Add another one first.")
BKA_FULL = N_("At most {0} bank accounts per office")
BKA_ARCHIVED = N_("This bank account is archived")


def bka_sees(c, uid, oid):
    """Whether uid may see the bank data of office oid (2.86.0 N15, 2.187.0 #2476: was inline in GET /api/office/settings)."""
    if office_role(c, uid, oid) == "admin":
        return True
    return not ofr_mine(c, uid, oid)["legacy"] and office_can(c, uid, oid, "settings", "manage")


def _ctx_bank():
    c, uid, oid = _ctx()
    if not bka_sees(c, uid, oid):
        raise Denied(403, tr(OFFICE_ADMIN_ONLY))
    return c, uid, oid


def _lock(c, oid):
    write_lock(c, f"{BKA_TABLE}_{int(oid)}")


def bka_default(c, oid):
    """The default account of office oid, decrypted (None: no account yet)."""
    r = c.execute(f"SELECT * FROM {BKA_TABLE} WHERE org_id=? AND is_default=1 AND archived=0", (oid,)).fetchone()
    return oc_dec_fields(c, oid, BKA_TABLE, r) if r else None


def bka_rows(c, oid, archived=False):
    """The accounts of office oid, decrypted: the default first; archived: only the archived ones."""
    rows = c.execute(f"SELECT * FROM {BKA_TABLE} WHERE org_id=? AND archived=? ORDER BY is_default DESC, sort, id", (oid, 1 if archived else 0)).fetchall()
    return [oc_dec_fields(c, oid, BKA_TABLE, r) for r in rows]


def bka_count(c, oid):
    return c.execute(f"SELECT COUNT(*) FROM {BKA_TABLE} WHERE org_id=? AND archived=0", (oid,)).fetchone()[0]


def bka_public(r):
    return {"id": r["id"], "label": r["label"], "iban": r["iban"], "bic": r["bic"], "bank_name": r["bank_name"], "datev_account": r["datev_account"],
            "is_default": bool(r["is_default"]), "archived": bool(r["archived"])}


def _brief(d):
    """What the office log keeps of an account: never the whole IBAN (the log has more readers than the bank data)."""
    iban = d.get("iban") or ""
    return {"label": d.get("label") or "", "iban": "… " + iban[-4:] if iban else "", "datev_account": d.get("datev_account") or ""}


def _insert(c, oid, d, default):
    ts = iso(now_utc())
    enc = oc_enc_fields(c, oid, BKA_TABLE, {k: d.get(k) or "" for k in BKA_BANK})
    sort = c.execute(f"SELECT COALESCE(MAX(sort), 0) + 1 FROM {BKA_TABLE} WHERE org_id=?", (oid,)).fetchone()[0]
    return insert_id(c, f"INSERT INTO {BKA_TABLE}(org_id, label, iban, bic, bank_name, datev_account, is_default, sort, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                     (oid, d.get("label") or "", enc["iban"], enc["bic"], enc["bank_name"], d.get("datev_account") or "", 1 if default else 0, sort, ts, ts))


def _set_bank(c, oid, rid, d):
    enc = oc_enc_fields(c, oid, BKA_TABLE, {k: d.get(k) or "" for k in BKA_BANK})
    c.execute(f"UPDATE {BKA_TABLE} SET iban=?, bic=?, bank_name=?, updated_at=? WHERE id=? AND org_id=?", (enc["iban"], enc["bic"], enc["bank_name"], iso(now_utc()), rid, oid))


def _set_default(c, oid, rid):
    c.execute(f"UPDATE {BKA_TABLE} SET is_default=0 WHERE org_id=? AND is_default=1", (oid,))  # first: the unique index allows one
    if rid is not None:
        c.execute(f"UPDATE {BKA_TABLE} SET is_default=1, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), rid, oid))


def bka_seed(c, oid):
    """The default account made from the company's bank fields, once per office and only while it has no account at all (so an
    office whose accounts were all taken care of never gets one back). True when it wrote; the caller commits."""
    sql = f"SELECT 1 FROM {BKA_TABLE} WHERE org_id=? LIMIT 1"
    if c.execute(sql, (oid,)).fetchone():
        return False
    r = c.execute("SELECT iban, bic, bank_name FROM office_company WHERE org_id=?", (oid,)).fetchone()
    co = oc_dec_fields(c, oid, "office_company", r) if r else {}
    if not any(co.get(k) for k in BKA_BANK):
        return False
    _lock(c, oid)
    if c.execute(sql, (oid,)).fetchone():  # (somebody else was first)
        return False
    d = {**{k: co.get(k) or "" for k in BKA_BANK}, "label": co.get("bank_name") or tr("Main account")}
    rid = _insert(c, oid, d, True)
    ofx_log(c, oid, "create", target="bank_account", detail={"id": rid, "after": _brief(d), "from": "company"})
    return True


def bka_mirror(c, oid, fields):
    """A write to the company's bank fields reaches the default account (ledger.ofx_company_save)."""
    r = bka_default(c, oid)
    if r and any((fields.get(k) or "") != (r.get(k) or "") for k in BKA_BANK):
        _set_bank(c, oid, r["id"], fields)


def bka_datev(c, oid, st):
    """The DATEV settings st with the bank account of the default account, when it has one that fits the ledger length."""
    r = bka_default(c, oid)
    v = (r or {}).get("datev_account") or ""
    return {**st, "bank": v} if v and len(v) <= int(st["acct_len"]) else st


def _clean(c, oid, b, cur=None):
    """A body -> the full values (BadInput on a wrong value). The IBAN is the point of an account; only a row that came without
    one (made from a company with just a bank name) may stay so."""
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    base = cur or {"label": "", "iban": "", "bic": "", "bank_name": "", "datev_account": ""}
    out = {**ofx_company_clean({k: b[k] for k in BKA_BANK if k in b}, base)}  # the rules of the company's fields (IBAN check digits)
    if not out["iban"] and (cur is None or cur.get("iban")):
        raise BadInput(tr("Invalid value: {0}", "IBAN"))
    if "label" in b:
        if not isinstance(b["label"], (str, type(None))):
            raise BadInput(tr("Invalid value: {0}", "label"))
        out["label"] = re.sub(r"[\x00-\x1f]+", " ", b["label"] or "").strip()[:BKA_LABEL_MAX]
    if not out["label"]:
        out["label"] = out["bank_name"][:BKA_LABEL_MAX] or "… " + out["iban"][-4:]
    if "datev_account" in b:
        from .datev import _digits, dx_settings
        out["datev_account"] = _digits(b["datev_account"], "datev_account", 1, int(dx_settings(office_settings(c, oid))["acct_len"]))
    return out


def _row(c, oid, rid):
    r = c.execute(f"SELECT * FROM {BKA_TABLE} WHERE id=? AND org_id=?", (rid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return oc_dec_fields(c, oid, BKA_TABLE, r)


def _answer(c, oid, rid, **more):
    return jsonify(account=bka_public(_row(c, oid, rid)), count=bka_count(c, oid), **more)


@app.get("/api/office/settings/bank-accounts")
def bka_list():
    """?archived=1: only the archived ones. {items, count = the active accounts}."""
    c, uid, oid = _ctx_bank()
    if bka_seed(c, oid):
        c.commit()
    return jsonify(items=[bka_public(r) for r in bka_rows(c, oid, request.args.get("archived") == "1")], count=bka_count(c, oid))


@app.post("/api/office/settings/bank-accounts")
def bka_new():
    """{label, iban, bic, bank_name, datev_account, default}: the first account of an office is the default by itself."""
    c, uid, oid = _ctx_bank()
    b = body()
    _lock(c, oid)
    bka_seed(c, oid)  # the company's account comes first, so a new account never pushes it out unseen
    d = _clean(c, oid, b)
    if c.execute(f"SELECT COUNT(*) FROM {BKA_TABLE} WHERE org_id=?", (oid,)).fetchone()[0] >= BKA_MAX:
        return err(tr(BKA_FULL, BKA_MAX), 409)
    first = bka_default(c, oid) is None
    rid = _insert(c, oid, d, False)
    if first or b.get("default") is True:
        _set_default(c, oid, rid)
    ofx_log(c, oid, "create", target="bank_account", detail={"id": rid, "after": _brief(d)})
    c.commit()
    return _answer(c, oid, rid), 201


@app.put("/api/office/settings/bank-accounts/<int:rid>")
def bka_edit(rid):
    """Partial body: label, iban, bic, bank_name, datev_account."""
    c, uid, oid = _ctx_bank()
    b = body()
    _lock(c, oid)
    cur = _row(c, oid, rid)
    d = _clean(c, oid, b, cur)
    _set_bank(c, oid, rid, d)
    c.execute(f"UPDATE {BKA_TABLE} SET label=?, datev_account=? WHERE id=? AND org_id=?", (d["label"], d["datev_account"], rid, oid))
    ofx_log(c, oid, "update", target="bank_account", detail={"id": rid, "before": _brief(cur), "after": _brief(d)})
    c.commit()
    return _answer(c, oid, rid)


@app.post("/api/office/settings/bank-accounts/<int:rid>/default")
def bka_make_default(rid):
    c, uid, oid = _ctx_bank()
    _lock(c, oid)
    r = _row(c, oid, rid)
    if r["archived"]:
        return err(tr(BKA_ARCHIVED), 409)
    if not r["is_default"]:
        _set_default(c, oid, rid)
        ofx_log(c, oid, "update", target="bank_account", detail={"id": rid, "default": True, "after": _brief(r)})
        c.commit()
    return _answer(c, oid, rid)


@app.post("/api/office/settings/bank-accounts/<int:rid>/archive")
def bka_archive(rid):
    """The default goes on to the next active account, so there always stays exactly one: the last active account cannot go
    (else the documents would quietly fall back to old company data). {default_id, was_default}: what an undo needs."""
    c, uid, oid = _ctx_bank()
    _lock(c, oid)
    r = _row(c, oid, rid)
    was = bool(r["is_default"])
    if not r["archived"]:
        rest = [x["id"] for x in c.execute(f"SELECT id FROM {BKA_TABLE} WHERE org_id=? AND archived=0 AND id<>? ORDER BY sort, id", (oid, rid)).fetchall()]
        if not rest:
            return err(tr(BKA_LAST), 409)
        if was:
            _set_default(c, oid, rest[0])
        c.execute(f"UPDATE {BKA_TABLE} SET archived=1, is_default=0, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), rid, oid))
        ofx_log(c, oid, "archive", target="bank_account", detail={"id": rid, "before": _brief(r)})
        c.commit()
    d = bka_default(c, oid)
    return _answer(c, oid, rid, default_id=d["id"] if d else None, was_default=was)


@app.post("/api/office/settings/bank-accounts/<int:rid>/restore")
def bka_restore(rid):
    c, uid, oid = _ctx_bank()
    _lock(c, oid)
    r = _row(c, oid, rid)
    if r["archived"]:
        c.execute(f"UPDATE {BKA_TABLE} SET archived=0, updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), rid, oid))
        if bka_default(c, oid) is None:
            _set_default(c, oid, rid)
        ofx_log(c, oid, "restore", target="bank_account", detail={"id": rid, "after": _brief(r)})
        c.commit()
    return _answer(c, oid, rid)
