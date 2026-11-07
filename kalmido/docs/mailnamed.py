"""2.577.0 C (#4466): the settings routes of the named document addresses (docs/mailaddr.py): list, make, change (name,
target folder, tags, on / off; expect_updated_at -> 409 with the current state, core/conflict.py), renew (the old address
is invalid at once), delete. Web session only, never an agent (like the scan inboxes); the general address keeps its
routes (docs/web.py /api/docs/mail). Integrations layer (kalmido/__init__.py LAYER_OF): it reads the mail input's switch."""
import json
import secrets

from flask import jsonify, request

from ..core.config import app
from ..core.conflict import ccf_check
from ..core.db import body, db, err, now_iso
from ..core.errors import Denied
from ..core.i18n import tr
from ..core.pg import write_lock
from ..accounts.session import me
from ..integrations.mail import MAIL_IN_ON, mail_addr
from .mailaddr import DMN_MAX, DMN_NAME_MAX, GENERAL, OFF_MSG, dmn_row_tags, dmn_folder, dmn_tags, dmn_token
from .web import _no_agent, ws_param


def _dmn_out(c, r, uid):
    general = not r["aid"]
    note, ok, path = "", True, ""
    if not general and r["target_folder"]:
        try:
            _pid, path = dmn_folder(c, uid, r["org_id"], r["target_folder"])
        except Denied as e:
            note, ok = e.text(), False
    if not r["active"]:
        note = tr(OFF_MSG)
    return {"id": r["aid"] or "general", "general": general, "name": tr(GENERAL) if general else r["name"],
            "address": mail_addr(r["token"]) if MAIL_IN_ON else "", "active": bool(r["active"]),
            "target_folder": None if general else r["target_folder"], "target": path, "ok": ok, "note": note,
            "tags": dmn_row_tags(r), "created_at": r["created_at"], "updated_at": r["updated_at"] or r["created_at"]}


def _dmn_rows(c, uid, oid):
    return c.execute("SELECT * FROM doc_mail WHERE user_id=? AND org_id IS NOT DISTINCT FROM ? ORDER BY aid<>'', name, created_at",
                     (uid, oid)).fetchall()


def _dmn_get(c, aid):
    """The named address aid of the signed-in person (with the membership check of its space now) -> (row, uid); 404."""
    _no_agent()
    uid = me()
    r = c.execute("SELECT * FROM doc_mail WHERE aid=? AND aid<>'' AND user_id=?", (str(aid)[:40], uid)).fetchone()
    if not r:
        raise Denied(404)
    ws_param(c, f"org:{r['org_id']}" if r["org_id"] else "private", uid)  # a member who may write there now
    return r, uid


def _dmn_mail_on():
    return MAIL_IN_ON


def _dmn_body_fields(c, uid, oid, b, cur=None):
    """name / target_folder / tags / active of a body -> the values to store; ValueError(field) / Denied(409 folder)."""
    out = {}
    if "name" in b or cur is None:
        name = " ".join(str(b.get("name") or "").split())[:DMN_NAME_MAX]
        if not name:
            raise ValueError("name")
        out["name"] = name
    if "target_folder" in b:
        pid = b.get("target_folder")
        if pid in (None, "", 0):
            pid = None
        elif not isinstance(pid, int) or isinstance(pid, bool):
            raise ValueError("target_folder")
        out["target_folder"] = dmn_folder(c, uid, oid, pid)[0]
    if "tags" in b:
        out["tags"] = json.dumps(dmn_tags(b.get("tags")), ensure_ascii=False)
    if "active" in b:
        if not isinstance(b["active"], bool):
            raise ValueError("active")
        out["active"] = b["active"]
    return out


@app.get("/api/docs/mail-addresses")
def docs_mail_addresses():
    """?ws= -> {enabled, max, addresses: [the general one (if made) first, then the named ones]} of my documents space."""
    _no_agent()
    c, uid = db(), me()
    oid, _ws = ws_param(c, request.args.get("ws"), uid)
    return jsonify(enabled=_dmn_mail_on(), max=DMN_MAX, addresses=[_dmn_out(c, r, uid) for r in _dmn_rows(c, uid, oid)])


@app.post("/api/docs/mail-addresses")
def docs_mail_address_new():
    """{ws, name, target_folder?, tags?} -> 201 the new named address (active)."""
    _no_agent()
    if not _dmn_mail_on():
        return err(tr("E-mail to tasks is not set up on this server"), 409)
    c, uid = db(), me()
    b = body()
    unknown = sorted(k for k in b if k not in ("ws", "name", "target_folder", "tags"))
    if unknown:
        return err(tr("Invalid value: {0}", ", ".join(unknown)))
    oid, _ws = ws_param(c, b.get("ws"), uid)
    try:
        v = _dmn_body_fields(c, uid, oid, b)
    except ValueError as e:
        return err(tr("Name missing") if str(e) == "name" else tr("Invalid value: {0}", str(e)))
    except Denied as e:
        return err(tr("Select a folder of these documents you may add to"), 400) if e.code == 409 else err(e.text(), e.code)
    write_lock(c, f"doc_mail-{uid}-{oid or 0}")
    if c.execute("SELECT COUNT(*) FROM doc_mail WHERE user_id=? AND org_id IS NOT DISTINCT FROM ? AND aid<>''", (uid, oid)).fetchone()[0] >= DMN_MAX:
        return err(tr("At most {0} addresses", DMN_MAX), 409)
    aid, ts = "a" + secrets.token_hex(8), now_iso()
    c.execute("INSERT INTO doc_mail(token, user_id, org_id, created_at, aid, name, target_folder, tags, active, updated_at) "
              "VALUES(?,?,?,?,?,?,?,?,?,?)", (dmn_token(), uid, oid, ts, aid, v["name"], v.get("target_folder"), v.get("tags", "[]"), True, ts))
    r = c.execute("SELECT * FROM doc_mail WHERE aid=?", (aid,)).fetchone()
    c.commit()
    print("docs: named mail address", aid, "made for user", uid, "org", oid, flush=True)
    return jsonify(_dmn_out(c, r, uid)), 201


@app.patch("/api/docs/mail-addresses/<aid>")
def docs_mail_address_set(aid):
    """{name?, target_folder?, tags?, active?, expect_updated_at?} -> the address; 409 {address} when it changed meanwhile."""
    c = db()
    r, uid = _dmn_get(c, aid)
    b = body()
    unknown = sorted(k for k in b if k not in ("name", "target_folder", "tags", "active", "expect_updated_at"))
    if unknown:
        return err(tr("Invalid value: {0}", ", ".join(unknown)))
    write_lock(c, f"doc_mail-{r['aid']}")
    r = c.execute("SELECT * FROM doc_mail WHERE aid=?", (r["aid"],)).fetchone()
    ccf_check(b, r["updated_at"] or r["created_at"], "address", lambda: _dmn_out(c, r, uid))
    try:
        v = _dmn_body_fields(c, uid, r["org_id"], b, cur=r)
    except ValueError as e:
        return err(tr("Name missing") if str(e) == "name" else tr("Invalid value: {0}", str(e)))
    except Denied as e:
        return err(tr("Select a folder of these documents you may add to"), 400) if e.code == 409 else err(e.text(), e.code)
    if v:
        v["updated_at"] = now_iso()
        cols = ", ".join(f"{k}=?" for k in v)
        c.execute(f"UPDATE doc_mail SET {cols} WHERE aid=? AND user_id=?", (*v.values(), r["aid"], uid))  # noqa: S608 -- fixed names
    r = c.execute("SELECT * FROM doc_mail WHERE aid=?", (r["aid"],)).fetchone()
    c.commit()
    return jsonify(_dmn_out(c, r, uid))


@app.post("/api/docs/mail-addresses/<aid>/renew")
def docs_mail_address_renew(aid):
    """A new address for the named address aid: the old one is invalid at once (name, folder, tags stay; the hourly
    budget goes with it)."""
    c = db()
    r, uid = _dmn_get(c, aid)
    if not _dmn_mail_on():
        return err(tr("E-mail to tasks is not set up on this server"), 409)
    write_lock(c, f"doc_mail-{r['aid']}")
    c.execute("UPDATE doc_mail SET token=?, updated_at=? WHERE aid=? AND user_id=?", (dmn_token(), now_iso(), r["aid"], uid))
    r = c.execute("SELECT * FROM doc_mail WHERE aid=?", (r["aid"],)).fetchone()
    c.commit()
    return jsonify(_dmn_out(c, r, uid))


@app.delete("/api/docs/mail-addresses/<aid>")
def docs_mail_address_del(aid):
    """The named address aid is gone (mails to it are not taken any more)."""
    c = db()
    r, uid = _dmn_get(c, aid)
    c.execute("DELETE FROM doc_mail WHERE aid=? AND user_id=?", (r["aid"], uid))
    c.commit()
    return jsonify(ok=True)
