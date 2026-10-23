"""2.207.0 A (#2763): scan inboxes for the folder watcher.

A scan inbox is an API key with the one scope "docs:upload", bound to one place (a person's own documents or an
organisation's, optionally one folder of it; api_tokens.upload_target). It reaches only POST /api/v1/documents (multipart
field file, nothing else; the answer is {id, name}) and GET /api/v1/documents/upload-target (api/v1.py UPLOAD_ROUTES); every
upload is checked with the person's rights at that moment. Its hash is stored as "u:" + hash, so a version before 2.207
never finds it. The setup code the settings show once: "kalmido-scan:1:" + base64url (no padding) of
{"url", "key", "name"}. The programs (folder watcher, built in the image) are served from KALMIDO_FOLDERWATCH_DIR."""
import base64
import json
import os
import secrets

from flask import g, jsonify, request, send_file

from ..core.access import acx_of
from ..core.config import MAX_FILE_MB, PUBLIC_URL, PUBLIC_URL_SET, app
from ..core.db import body, bump, db, err, iso, now_utc, uset, usettings
from ..core.errors import BadInput, Denied, UnknownFields
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_active_for, oc_user_space
from ..core.pg import insert_id
from ..accounts.orgroles import org_role_key, org_writes
from ..accounts.session import _token_hash, me
from ..api.common import v1_args, v1_view
from ..files.store import fs_log_add, need_node
from ..files.upsafe import h6d_read
from .ingest import docs_ingest, docs_kick
from .web import _no_agent, ws_param

SK_NAME_MAX = 60
SK_CODE_PREFIX = "kalmido-scan:1:"
FW_DIR = os.environ.get("KALMIDO_FOLDERWATCH_DIR", "/app/folderwatch")
# id, file name, label (common contract with the folder watcher build in the Dockerfile)
FW_FILES = (("mac-arm64", "kalmido-folder-watcher-mac-arm64.zip", N_("Mac (Apple chip)")),
            ("mac-amd64", "kalmido-folder-watcher-mac-amd64.zip", N_("Mac (Intel)")),
            ("windows", "kalmido-folder-watcher-windows.exe", N_("Windows")),
            ("linux-amd64", "kalmido-folder-watcher-linux-amd64", N_("Linux (x86-64)")),
            ("linux-arm64", "kalmido-folder-watcher-linux-arm64", N_("Linux (ARM)")),
            ("sums", "SHA256SUMS", N_("Checksums (SHA-256)")))
GONE_MSG = N_("The place of this scan inbox is no longer open to you")
FOLDER_GONE_MSG = N_("The folder of this scan inbox no longer exists; create a new inbox")


def sk_target(row):
    """The bound place of a token row: {"org": id|None, "parent_id": id|None}, or None (an ordinary token)."""
    try:
        t = json.loads(row["upload_target"] or "null") if row is not None and "upload_target" in row.keys() else None
    except ValueError:
        return None
    if not isinstance(t, dict):
        return None
    ints = {k: t.get(k) if isinstance(t.get(k), int) and not isinstance(t.get(k), bool) else None for k in ("org", "parent_id")}
    return ints


def _sk_org_ok(c, uid, oid):
    """True while uid is a member of organisation oid who may add documents there (no guest, no read-only role)."""
    return oid in acx_of(c, uid).org_ids and org_role_key(c, uid, oid) != "guest" and org_writes(c, uid, oid)


def sk_resolve(c, uid, t):
    """(org id | None, folder id | None, readable place) of target t with uid's rights now; Denied 403 (no longer
    allowed) / 409 (the folder is gone)."""
    if not t:
        raise Denied(403, tr(GONE_MSG))
    oid, pid = t.get("org"), t.get("parent_id")
    if oid and not _sk_org_ok(c, uid, oid):
        raise Denied(403, tr(GONE_MSG))
    place = _sk_ws_name(c, oid)
    if pid:
        n = c.execute("SELECT id, kind, name, org_id, owner_id, deleted_at FROM fs_nodes WHERE id=?", (pid,)).fetchone()
        if not n or n["kind"] != "folder" or n["deleted_at"] or n["org_id"] != oid or (not oid and n["owner_id"] != uid):
            raise Denied(409, tr(FOLDER_GONE_MSG))
        try:
            need_node(c, pid, write=True)
        except Denied as e:
            raise Denied(409 if e.code == 404 else 403, tr(FOLDER_GONE_MSG if e.code == 404 else GONE_MSG)) from None
        place += " / " + n["name"]
    return oid, pid, place


def _sk_ws_name(c, oid):
    if not oid:
        return tr("Your own documents")
    r = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()
    return r["name"] if r else "?"


def sk_upload():
    """POST /api/v1/documents with a docs:upload key (called from docs/v1.py): the field file only, into the bound place."""
    from ..admin.hosting import QuotaExceeded
    if not request.files:
        raise BadInput(tr("Expected {0}", "file"))
    extra = sorted(set(request.form) | (set(request.files) - {"file"}))
    if extra:
        raise UnknownFields(extra)
    files = request.files.getlist("file")
    if len(files) != 1:
        raise BadInput(tr("Expected {0}", "file"))
    c, uid = db(), me()
    oid, pid, _place = sk_resolve(c, uid, sk_target(g.token))
    f = files[0]
    data, name, mime = h6d_read(f), os.path.basename(f.filename or "") or "scan.pdf", f.mimetype
    try:
        with c.savepoint():
            nid = docs_ingest(c, uid, oid, name, data, mime, "scan", {}, parent_id=pid)
            fs_log_add(c, nid, "upload")
    except QuotaExceeded:
        raise Denied(413, tr("{0}: no space left in your storage", name)) from None
    except ValueError as e:
        raise BadInput(str(e)) from None
    n = c.execute("SELECT name FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    bump(c)
    c.commit()
    docs_kick()
    print("scan inbox", g.token["id"], "of user", uid, "uploaded document", nid, flush=True)
    return jsonify(id=nid, name=n["name"] if n else name), 201


@app.get("/api/v1/documents/upload-target")
@v1_view
def v1_doc_upload_target():
    """Where a docs:upload key uploads to (to check a setup; the folder watcher's status page)."""
    v1_args(())
    _oid, _pid, place = sk_resolve(db(), me(), sk_target(g.token))
    return jsonify(name=g.token["name"], target=place, max_mb=MAX_FILE_MB)


# ---- the settings (web session only, never an agent)
def _v1():
    """The API module (a higher layer: its switch, the token limit, the upload key's hash prefix)."""
    from ..api import v1
    return v1


def _sk_web(ws_raw, write=False):
    _no_agent()
    c, uid = db(), me()
    oid, _ws = ws_param(c, ws_raw, uid)
    if write and oid and not _sk_org_ok(c, uid, oid):
        raise Denied(403)
    return c, uid, oid


def _sk_rows(c, uid, oid):
    out = []
    for r in c.execute("SELECT * FROM api_tokens WHERE user_id=? AND token_hash ILIKE ? ORDER BY id DESC", (uid, _v1().UPLOAD_HASH_PREFIX + "%")).fetchall():
        t = sk_target(r)
        if not t or t["org"] != oid:
            continue
        try:
            _o, _p, place = sk_resolve(c, uid, t)
            ok = True
        except Denied as e:
            place, ok = e.text(), False
        out.append({"id": r["id"], "name": r["name"], "prefix": r["prefix"], "target": place, "parent_id": t["parent_id"], "ok": ok,
                    "created_at": r["created_at"], "last_used_at": r["last_used_at"]})
    return out


def fw_downloads():
    """The folder watcher programs this server has: [{id, label, file, size}]."""
    out = []
    for k, fn, label in FW_FILES:
        p = os.path.join(FW_DIR, fn)
        if os.path.isfile(p):
            out.append({"id": k, "label": tr(label), "file": fn, "size": os.path.getsize(p)})
    return out


def sk_settings(c, uid, oid):
    """The part "Scans from your computer" of the document settings."""
    api_on = _v1().API_ON
    return {"api": api_on, "downloads": fw_downloads(), "keys": _sk_rows(c, uid, oid) if api_on else [],
            "encrypted": oc_active_for(c, oid or oc_user_space(uid)), "mail_notice": usettings(c, uid).get("doc_mail_notice") == "1"}


@app.get("/api/docs/scan-keys")
def docs_scan_keys():
    """?ws= -- my scan inboxes of this workspace, the downloads and whether the API is on."""
    c, uid, oid = _sk_web(request.args.get("ws"))
    return jsonify(sk_settings(c, uid, oid))


@app.post("/api/docs/scan-keys")
def docs_scan_key_new():
    """{ws, name, parent_id?} -> 201 {id, name, target, code}: a new scan inbox; the setup code is shown only in this answer."""
    V = _v1()
    V.need_api()
    b = body()
    unknown = sorted(k for k in b if k not in ("ws", "name", "parent_id"))
    if unknown:
        return err(tr("Invalid value: {0}", ", ".join(unknown)))
    c, uid, oid = _sk_web(b.get("ws"), write=True)
    name = str(b.get("name") or "").strip()[:SK_NAME_MAX]
    if not name:
        return err(tr("Name missing"))
    pid = b.get("parent_id")
    if pid in (None, "", 0):
        pid = None
    elif not isinstance(pid, int) or isinstance(pid, bool):
        return err(tr("Invalid value: {0}", "parent_id"))
    t = {"org": oid, "parent_id": pid}
    try:
        _o, _p, place = sk_resolve(c, uid, t)
    except Denied as e:
        return err(tr("Choose a folder of these documents you may add to") if pid else e.text(), 400 if pid else e.code)
    if c.execute("SELECT COUNT(*) FROM api_tokens WHERE user_id=?", (uid,)).fetchone()[0] >= V.API_TOKEN_MAX:
        return err(tr("At most {0} tokens", V.API_TOKEN_MAX), 409)
    tok = "abk_" + secrets.token_urlsafe(32)
    kid = insert_id(c, "INSERT INTO api_tokens(user_id,name,token_hash,prefix,scopes,expires_at,created_at,allowed_ips,list_ids,upload_target) "
                       "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (uid, name, V.UPLOAD_HASH_PREFIX + _token_hash(tok), tok[:12], "docs:upload", None, iso(now_utc()), "", "", json.dumps(t)))
    c.commit()
    print("scan inbox", kid, "created for user", uid, "org", oid, flush=True)
    url = (PUBLIC_URL if PUBLIC_URL_SET else request.host_url).rstrip("/")
    raw = json.dumps({"url": url, "key": tok, "name": name}, ensure_ascii=False, separators=(",", ":")).encode()
    code = SK_CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return jsonify(id=kid, name=name, target=place, code=code), 201


@app.delete("/api/docs/scan-keys/<int:kid>")
def docs_scan_key_del(kid):
    """Revoke one of my scan inboxes (the folder watcher stops at once)."""
    _no_agent()
    c = db()
    if not c.execute("DELETE FROM api_tokens WHERE id=? AND user_id=? AND token_hash ILIKE ?", (kid, me(), _v1().UPLOAD_HASH_PREFIX + "%")).rowcount:
        raise Denied(404)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/docs/mail-notice")
def docs_mail_notice():
    """The person has read the note that mail is not end-to-end encrypted (shown big only once)."""
    _no_agent()
    c = db()
    uset(c, me(), "doc_mail_notice", "1")
    c.commit()
    return jsonify(ok=True)


@app.get("/api/docs/folder-watcher/<name>")
def docs_folder_watcher(name):
    """A folder watcher program (fixed names only) as a download; 404 when this server has none (no image build)."""
    me()
    fn = next((x[1] for x in FW_FILES if x[1] == name), None)
    p = os.path.join(FW_DIR, fn) if fn else ""
    if not fn or not os.path.isfile(p):
        raise Denied(404, tr("Not available on this server - the image builds the programs (Dockerfile)"))
    return send_file(p, as_attachment=True, download_name=fn,
                     mimetype="text/plain" if fn == "SHA256SUMS" else "application/octet-stream", max_age=0)
