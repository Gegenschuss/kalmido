"""2.425.0 C (#3453): receipt fetchers -- a helper program on the person's own computer that fetches invoices from web portals
(Amazon & co.) and hands them straight to Kalmido.

A fetcher is connected with a setup code like a scan inbox (docs/scankeys.py), but its key is a kind of its own: table
doc_fetchers (only its hash, "kbh_" + 43 characters), never an api_tokens row, so no other route of the API knows it (401);
api/v1.py asks this module for every key with the prefix (V1_KEY_KINDS) and lets it reach FX_ROUTES only (403 otherwise).
It can do two things: upload a PDF into the documents of its place (the person's own or an organisation's, checked with the
person's rights at every upload, sk_resolve) and report the state of its portals (doc_fetch_portals: name, last run, number
of new receipts, an error such as "please sign in again"). A new error tells the person once (News + push of the event
"fetcher", switchable in the notification settings). The person switches a portal on / off in Kalmido; the helper reads
that in the answer of its next report. Kalmido never stores passwords, cookies or logins: there are no fields for them and
the routes refuse every field they do not know (400). Only for people with the office (feature "office"), also the own one.
The setup code: "kalmido-fetch:1:" + base64url (no padding) of {"url", "key", "name"}."""
import base64
import json
import os
import re
import secrets

from flask import g, jsonify, request

from ..core.config import MAX_FILE_MB, PUBLIC_URL, PUBLIC_URL_SET, app
from ..core.db import body, bump, db, err, iso, iso_ms, now_utc, parse_iso
from ..core.errors import BadInput, Denied, UnknownFields
from ..core.i18n import N_, lang, tr
from ..core.pg import insert_id, system_ctx
from ..accounts.session import _rate_blocked, _rate_fail, _token_hash, FAIL_WINDOW, me
from ..api.common import hit_limit, v1_err, v1_json, v1_view, V1_KEY_KINDS
from ..collab.comments import collab_user
from ..collab.news import notif_ok
from ..files.store import fs_log_add
from ..files.upsafe import h6d_read
from ..notify.push import push_prio
from ..office.model import office_on
from . import store as S
from .ingest import docs_ingest, docs_kick
from .scankeys import _sk_org_ok, _v1, sk_resolve
from .web import _no_agent, ws_param

FX_PREFIX = "kbh_"
FX_KEY_RE = re.compile(r"kbh_[A-Za-z0-9_-]{20,100}")
FX_CODE_PREFIX = "kalmido-fetch:1:"
FX_MAX = 10              # fetchers per person
FX_PORTALS_MAX = 50      # portals per fetcher
FX_RATE = 120            # requests of one fetcher per minute
FX_USED_EVERY = 60       # s between two last_seen_at updates
FX_NAME_MAX, FX_ERR_MAX, FX_ORDER_MAX = 60, 300, 100
FX_KEY_PORTAL = re.compile(r"[a-z0-9][a-z0-9_.-]{0,39}")
FX_PORTAL_FIELDS = ("key", "name", "last_run", "new", "error")
# the only routes a fetcher key reaches (method, rule)
FX_ROUTES = {("GET", "/api/v1/fetcher"), ("PUT", "/api/v1/fetcher/status"), ("POST", "/api/v1/fetcher/documents")}
OFF_MSG = N_("Receipt fetchers need the office")
GONE = N_("This receipt fetcher is no longer connected")


# ---- the key (called by api/v1.py api_authenticate for every bearer key with FX_PREFIX)
def fx_authenticate(c, tok, bad):
    """g.user = the fetcher's person (auth_via "token", no scopes), g.fetcher = its row; a refusal as the API's error."""
    row = None
    if FX_KEY_RE.fullmatch(tok):
        with system_ctx(c):  # the key's row by its hash across organisations (its place is checked with the person's rights later)
            row = c.execute("SELECT * FROM doc_fetchers WHERE token_hash=?", (_token_hash(tok),)).fetchone()
    u = c.execute("SELECT * FROM users WHERE id=?", (row["user_id"],)).fetchone() if row else None
    if not u or u["disabled"] or u["kid"] or (u["kind"] if "kind" in u.keys() else "user") == "agent":
        if _rate_blocked(bad):
            return v1_err(429, tr("Too many invalid tokens, please wait a few minutes"), {"Retry-After": str(FAIL_WINDOW)})
        _rate_fail(bad)
        return v1_err(401, tr("Missing or invalid API token"), {"WWW-Authenticate": 'Bearer realm="kalmido"'})
    if (request.method, request.url_rule.rule if request.url_rule else "") not in FX_ROUTES:
        return v1_err(403, tr("This key may only upload receipts and report the state of its portals"))
    if hit_limit(f"fx:{row['id']}", FX_RATE):
        return v1_err(429, tr("Too many requests, please slow down"), {"Retry-After": "60"})
    g.user, g.auth_via, g.token, g.scopes, g.fetcher = u, "token", None, frozenset(), row
    last = row["last_seen_at"]
    if not last or (now_utc() - parse_iso(last)).total_seconds() >= FX_USED_EVERY:
        with system_ctx(c):  # the fetcher's own row (its place may be an organisation)
            c.execute("UPDATE doc_fetchers SET last_seen_at=? WHERE id=?", (iso(now_utc()), row["id"]))
        c.commit()
    return None


V1_KEY_KINDS[FX_PREFIX] = fx_authenticate


def _fx_row():
    """The fetcher of this request, its person still with the office, its place still open (403 / 409 otherwise)."""
    fx = g.get("fetcher")
    if fx is None:
        raise Denied(403, tr("This key may only upload receipts and report the state of its portals"))
    c, uid = db(), me()
    if not office_on(c, uid):
        raise Denied(403, tr(OFF_MSG))
    oid, _pid, place = sk_resolve(c, uid, {"org": fx["org_id"], "parent_id": None})
    return c, uid, fx, oid, place


def _portals(c, fid):
    return c.execute("SELECT * FROM doc_fetch_portals WHERE fetcher_id=? ORDER BY lower(name), key", (fid,)).fetchall()


def _portal_out(p, full=False):
    d = {"key": p["key"], "name": p["name"], "enabled": bool(p["enabled"])}
    if full:
        d.update(last_run=p["last_run"], new=p["new_count"], error=p["error"], error_at=p["error_at"], updated_at=p["updated_at"])
    return d


@app.get("/api/v1/fetcher")
@v1_view
def v1_fetcher_get():
    """The fetcher's own view: its name, the place its receipts go, the largest file and which portals are switched on."""
    c, _uid, fx, _oid, place = _fx_row()
    return jsonify(name=fx["name"], target=place, max_mb=MAX_FILE_MB, portals=[_portal_out(p) for p in _portals(c, fx["id"])])


def _clean_portal(x):
    if not isinstance(x, dict):
        raise BadInput(tr("Invalid value: {0}", "portals"))
    extra = sorted(k for k in x if k not in FX_PORTAL_FIELDS)
    if extra:  # never stored: no password, cookie or login field exists
        raise UnknownFields(extra)
    key = x.get("key")
    if not isinstance(key, str) or not FX_KEY_PORTAL.fullmatch(key):
        raise BadInput(tr("Invalid value: {0}", "key"))
    name = x.get("name", key)
    if not isinstance(name, str) or not name.strip():
        raise BadInput(tr("Invalid value: {0}", "name"))
    last = x.get("last_run")
    if last not in (None, ""):
        if not isinstance(last, str) or len(last) > 40:
            raise BadInput(tr("Invalid value: {0}", "last_run"))
        try:
            last = iso(parse_iso(last))
        except (TypeError, ValueError):
            raise BadInput(tr("Invalid value: {0}", "last_run")) from None
    n = x.get("new", 0)
    if n is None:
        n = 0
    if not isinstance(n, int) or isinstance(n, bool) or not 0 <= n <= 100000:
        raise BadInput(tr("Invalid value: {0}", "new"))
    e = x.get("error") or ""
    if not isinstance(e, str):
        raise BadInput(tr("Invalid value: {0}", "error"))
    return key, re.sub(r"\s+", " ", name).strip()[:FX_NAME_MAX], last or None, n, re.sub(r"\s+", " ", e).strip()[:FX_ERR_MAX]


@app.put("/api/v1/fetcher/status")
@v1_view
def v1_fetcher_status():
    """{portals: [{key, name, last_run, new, error}]} -> the stored state; answers which portals are switched on. A portal
    that is new here starts switched on; an error that was not there before tells the person once."""
    c, uid, fx, _oid, _place = _fx_row()
    b = v1_json()
    extra = sorted(k for k in b if k != "portals")
    if extra:
        raise UnknownFields(extra)
    ps = b.get("portals")
    if not isinstance(ps, list) or len(ps) > FX_PORTALS_MAX:
        raise BadInput(tr("Invalid value: {0}", "portals"))
    rows = [_clean_portal(x) for x in ps]
    if len({r[0] for r in rows}) != len(rows):
        raise BadInput(tr("Invalid value: {0}", "key"))
    have = {p["key"]: p for p in _portals(c, fx["id"])}
    if len(set(have) | {r[0] for r in rows}) > FX_PORTALS_MAX:
        raise BadInput(tr("At most {0} portals", FX_PORTALS_MAX))
    ts = iso(now_utc())
    for key, name, last, n, e in rows:
        p = have.get(key)
        if p is None:
            c.execute("INSERT INTO doc_fetch_portals(fetcher_id,org_id,key,name,enabled,last_run,new_count,error,error_at,updated_at) "
                      "VALUES(?,?,?,?,1,?,?,?,?,?)", (fx["id"], fx["org_id"], key, name, last, n, e, ts if e else None, ts))
        else:
            c.execute("UPDATE doc_fetch_portals SET name=?, last_run=?, new_count=?, error=?, error_at=?, updated_at=? WHERE fetcher_id=? AND key=?",
                      (name, last or p["last_run"], n, e, (p["error_at"] if e == p["error"] else ts) if e else None, ts, fx["id"], key))
        if e and (p is None or e != p["error"]) and (p is None or p["enabled"]):
            _fx_tell(c, uid, fx, name, e)
    c.commit()
    return jsonify(portals=[_portal_out(p) for p in _portals(c, fx["id"])])


def _fx_tell(c, uid, fx, portal, error):
    """A new error of a portal: one News item + push for the person (event "fetcher" of the notification settings)."""
    s = collab_user(c, uid, None)
    if not s:
        return
    data = {"fetcher": fx["id"], "name": fx["name"], "portal": portal, "error": error}
    if notif_ok(c, uid, s, "fetcher", "news"):
        c.execute("INSERT INTO notifications(user_id,kind,task_id,list_id,actor_id,comment_id,data,created_at) VALUES(?,?,?,?,?,?,?,?)",
                  (uid, "fetcherr", None, None, None, None, json.dumps(data, ensure_ascii=False), iso_ms(now_utc())))
    if notif_ok(c, uid, s, "fetcher", "push"):
        lg = lang(c, uid)
        g.setdefault("pushes", []).append((uid, tr("Receipt fetcher: {0}", portal, lg=lg), error, f"{PUBLIC_URL}/#settings/fetcher", push_prio(s)))


@app.post("/api/v1/fetcher/documents")
@v1_view
def v1_fetcher_upload():
    """multipart: file (a PDF), portal (its key), order (the order number, optional) -> 201 {id, name, duplicate}. The same
    file or the same order of the same portal again returns the document that is there (duplicate true, 200)."""
    c, uid, fx, oid, _place = _fx_row()
    extra = sorted((set(request.form) - {"portal", "order"}) | (set(request.files) - {"file"}))
    if extra:
        raise UnknownFields(extra)
    files = request.files.getlist("file")
    if len(files) != 1:
        raise BadInput(tr("Expected {0}", "file"))
    key, order = request.form.get("portal") or "", (request.form.get("order") or "").strip()
    if not FX_KEY_PORTAL.fullmatch(key):
        raise BadInput(tr("Invalid value: {0}", "portal"))
    if len(order) > FX_ORDER_MAX or any(ord(ch) < 32 for ch in order):
        raise BadInput(tr("Invalid value: {0}", "order"))
    p = c.execute("SELECT * FROM doc_fetch_portals WHERE fetcher_id=? AND key=?", (fx["id"], key)).fetchone()
    if p is None:
        raise BadInput(tr("Report the portal first (PUT /fetcher/status)"))
    if not p["enabled"]:
        raise Denied(409, tr("The portal {0} is switched off in Kalmido", p["name"]))
    f = files[0]
    data = h6d_read(f)
    if len(data) > MAX_FILE_MB * 1024 * 1024:  # 2.425.0 (#3453 review): 413 as docs/API.md says (fs_put's ValueError would be 400)
        raise Denied(413, tr("The file is too large (at most {0} MB)", MAX_FILE_MB))
    if not data.startswith(b"%PDF-"):
        raise BadInput(tr("Only PDF files"))
    name = os.path.basename(f.filename or "") or f"{p['name']}-{order or 'receipt'}.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    ext = f"abholer:{key}:{order}" if order else None  # the portal + order number, also the second way to find a repeat
    meta, info = ({"ext_id": ext} if ext else {}), {}
    known = c.execute("SELECT node_id FROM doc_meta WHERE ws=? AND ext_id=?", (S.doc_ws(oid, uid), ext)).fetchone() if ext else None
    try:
        with c.savepoint():
            nid = docs_ingest(c, uid, oid, name, data, "application/pdf", "abholer", meta, dedup=True, info=info)
            dup = bool(known) or bool(info.get("dup"))
            if not dup:
                fs_log_add(c, nid, "upload")
    except ValueError as e:
        raise BadInput(str(e)) from None
    n = c.execute("SELECT name FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not dup:
        c.execute("UPDATE doc_fetch_portals SET uploaded=uploaded+1, uploaded_at=? WHERE fetcher_id=? AND key=?", (iso(now_utc()), fx["id"], key))
        bump(c)
    c.commit()
    if not dup:
        docs_kick()
    print("receipt fetcher", fx["id"], "of user", uid, "document", nid, "duplicate" if dup else "new", flush=True)
    return jsonify(id=nid, name=n["name"] if n else name, duplicate=dup), 200 if dup else 201


# ---- the settings (web session only, never an agent)
def _fx_web(ws_raw, write=False):
    _no_agent()
    c, uid = db(), me()
    if not office_on(c, uid):
        raise Denied(403, tr(OFF_MSG))
    oid, _ws = ws_param(c, ws_raw, uid)
    if write and oid and not _sk_org_ok(c, uid, oid):
        raise Denied(403)
    return c, uid, oid


def fx_list(c, uid, oid):
    out = []
    for r in c.execute("SELECT * FROM doc_fetchers WHERE user_id=? ORDER BY id DESC", (uid,)).fetchall():
        if r["org_id"] != oid:
            continue
        try:
            _o, _p, place = sk_resolve(c, uid, {"org": r["org_id"], "parent_id": None})
            ok = True
        except Denied as e:
            place, ok = e.text(), False
        out.append({"id": r["id"], "name": r["name"], "prefix": r["prefix"], "target": place, "ok": ok, "created_at": r["created_at"],
                    "last_seen_at": r["last_seen_at"], "portals": [_portal_out(p, True) for p in _portals(c, r["id"])]})
    return out


@app.get("/api/docs/fetchers")
def docs_fetchers():
    """?ws= -- my receipt fetchers of this workspace with the state of their portals; whether the API is on."""
    c, uid, oid = _fx_web(request.args.get("ws"))
    api_on = _v1().API_ON
    return jsonify(api=api_on, fetchers=fx_list(c, uid, oid) if api_on else [])


@app.post("/api/docs/fetchers")
def docs_fetcher_new():
    """{ws, name} -> 201 {id, name, target, code}: a new receipt fetcher; the setup code is shown only in this answer."""
    _v1().need_api()
    b = body()
    unknown = sorted(k for k in b if k not in ("ws", "name"))
    if unknown:
        return err(tr("Invalid value: {0}", ", ".join(unknown)))
    c, uid, oid = _fx_web(b.get("ws"), write=True)
    name = re.sub(r"\s+", " ", str(b.get("name") or "")).strip()[:FX_NAME_MAX]
    if not name:
        return err(tr("Name missing"))
    try:
        _o, _p, place = sk_resolve(c, uid, {"org": oid, "parent_id": None})
    except Denied as e:
        return err(e.text(), e.code)
    if c.execute("SELECT COUNT(*) FROM doc_fetchers WHERE user_id=?", (uid,)).fetchone()[0] >= FX_MAX:
        return err(tr("At most {0} receipt fetchers", FX_MAX), 409)
    tok = FX_PREFIX + secrets.token_urlsafe(32)
    fid = insert_id(c, "INSERT INTO doc_fetchers(user_id,org_id,name,token_hash,prefix,created_at) VALUES(?,?,?,?,?,?)",
                    (uid, oid, name, _token_hash(tok), tok[:12], iso(now_utc())))
    c.commit()
    print("receipt fetcher", fid, "created for user", uid, "org", oid, flush=True)
    url = (PUBLIC_URL if PUBLIC_URL_SET else request.host_url).rstrip("/")
    raw = json.dumps({"url": url, "key": tok, "name": name}, ensure_ascii=False, separators=(",", ":")).encode()
    return jsonify(id=fid, name=name, target=place, code=FX_CODE_PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")), 201


@app.delete("/api/docs/fetchers/<int:fid>")
def docs_fetcher_del(fid):
    """Disconnect one of my receipt fetchers (its key stops at once; the documents it brought stay)."""
    _no_agent()
    c = db()
    if not c.execute("DELETE FROM doc_fetchers WHERE id=? AND user_id=?", (fid, me())).rowcount:
        raise Denied(404, tr(GONE))
    c.commit()
    return jsonify(ok=True)


@app.patch("/api/docs/fetchers/<int:fid>/portals/<key>")
def docs_fetcher_portal(fid, key):
    """{enabled: bool}: switch a portal of my receipt fetcher on / off (the helper reads it with its next report)."""
    _no_agent()
    c, uid = db(), me()
    if not office_on(c, uid):
        raise Denied(403, tr(OFF_MSG))
    b = body()
    if sorted(b) != ["enabled"] or not isinstance(b["enabled"], bool):
        return err(tr("Invalid value: {0}", "enabled"))
    if not c.execute("SELECT 1 FROM doc_fetchers WHERE id=? AND user_id=?", (fid, uid)).fetchone():
        raise Denied(404, tr(GONE))
    if not c.execute("UPDATE doc_fetch_portals SET enabled=?, updated_at=? WHERE fetcher_id=? AND key=?",
                     (1 if b["enabled"] else 0, iso(now_utc()), fid, key)).rowcount:
        raise Denied(404)
    c.commit()
    return jsonify(ok=True, enabled=b["enabled"])


def fx_spec(paths, op, ok, errs, T):
    """OpenAPI of the three routes of a receipt fetcher key (called from docs/v1.py docs_spec). Documented with the scope
    docs:upload: no ordinary token reaches them (403), a fetcher key reaches nothing else."""
    pt = {"type": "object", "properties": {"key": {"type": "string"}, "name": {"type": "string"}, "enabled": {"type": "boolean"}}}
    why = ("Only for receipt fetcher keys (kbh_..., made with a setup code in Settings > Integrations > Receipt fetcher): such a key "
           "reaches only GET /fetcher, PUT /fetcher/status and POST /fetcher/documents; every other route answers 401 / 403. ")
    paths["/fetcher"] = {"get": op(
        "The receipt fetcher of this key (2.425.0)", T,
        ok({"type": "object", "properties": {"name": {"type": "string"}, "target": {"type": "string"}, "max_mb": {"type": "integer"},
                                              "portals": {"type": "array", "items": pt}}}) | errs("403", "409"),
        [], scope="docs:upload", desc=why + "portals[].enabled is the person's switch: fetch only from portals that are on.")}
    paths["/fetcher/status"] = {"put": op(
        "Report the state of the portals (2.425.0)", T, ok({"type": "object", "properties": {"portals": {"type": "array", "items": pt}}}) | errs("400", "403"),
        [], scope="docs:upload",
        body={"type": "object", "required": ["portals"], "properties": {"portals": {"type": "array", "maxItems": FX_PORTALS_MAX, "items": {
            "type": "object", "required": ["key"], "additionalProperties": False, "properties": {
                "key": {"type": "string", "description": "a-z 0-9 _ . - (up to 40), e.g. amazon"}, "name": {"type": "string"},
                "last_run": {"type": "string", "description": "ISO time of the last run"},
                "new": {"type": "integer", "description": "New receipts of the last run"},
                "error": {"type": "string", "description": "Empty = fine; a new error tells the person once"}}}}}},
        desc=why + "Unknown fields are refused (400): Kalmido stores no passwords, cookies or logins. The answer names the switched-on portals.")}
    paths["/fetcher/documents"] = {"post": op(
        "Upload a fetched receipt (2.425.0)", T,
        ok({"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}, "duplicate": {"type": "boolean"}}}, "Created", "201")
        | errs("400", "403", "409", "413"), [], scope="docs:upload",
        desc=why + "multipart/form-data: file (a PDF), portal (a reported key), order (order number, optional). The document is "
                   "recognised like an upload; the same file or order again answers 200 with duplicate true.")}
    paths["/fetcher/documents"]["post"]["requestBody"] = {"required": True, "content": {"multipart/form-data": {"schema": {
        "type": "object", "required": ["file", "portal"], "properties": {"file": {"type": "string", "format": "binary"},
                                                                         "portal": {"type": "string"}, "order": {"type": "string"}}}}}}
