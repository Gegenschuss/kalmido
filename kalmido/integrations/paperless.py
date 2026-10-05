"""Paperless-ngx: linking documents, sending attachments, personal and server connections, polling."""
import hashlib
import http.client
import io
import json
import os
import re
import uuid
import time
import urllib.error
import urllib.parse
import urllib.request
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from flask import g, has_request_context, jsonify, request, Response

from ..core.config import app, ATT_DIR, PL_API, PL_PUBLIC, PL_TOKEN, safe_urlopen, SECRET_KEY, SECRET_KEY_PROBLEM
from ..core.i18n import lang, N_, tr
from ..core.db import body, bump, db, default_uid, err, iso, now_utc, parse_iso, usettings
from ..accounts.session import me
from ..core.access import Denied, need_task
from ..core.serializers import unlink_files
from ..tasks.validation import as_int, log_act
from ..tasks.tasks import one_task
from ..tasks.attachments import need_attachment


# ---------------------------------------------------------------- paperless
# 2.1.0 (#180): several connections.
#  - Connection 0 = the legacy one from the environment (PAPERLESS_TOKEN / PAPERLESS_API / PAPERLESS_PUBLIC_URL, named
#    "Paperless"): the archive of the token owner, for users an admin gave "Paperless access" (as before). Its token
#    stays in the environment. Links from before 2.1.0 belong to it (paperless_links.conn_id NULL).
#  - Server connections (pl_conns.kind 'server'), set up by an admin: name + URL, NO shared token. Every user the admin
#    allows enters their OWN Paperless API token, so Paperless' permissions and groups apply per person.
#  - Personal connections (kind 'personal'): name + URL + token of one user. Only that user sees and uses them; admins can
#    neither see nor grant them (not in the admin UI, not in any API answer for someone else).
# Tokens are write-only (no API answer or page ever contains one: "set" / "not set" only) and encrypted at rest
# (AES-GCM, key KALMIDO_SECRET_KEY from the environment, never in the DB / data dir; associated data = connection + user).
# Without the key no token can be stored (the legacy connection keeps working). Requests to personal connections go
# through the SSRF guard of the calendar subscriptions (public addresses only, internal hosts only where an admin
# allowed them), and no connection follows redirects, so a token only ever goes to the host of its connection.
PL_CONN_MAX = 10          # personal connections per user
PL_SERVER_MAX = 20        # server connections
PL_NAME_MAX, PL_TOKEN_MAX = 60, 400
PL_MAX_BYTES = 25 * 1024 * 1024


class PaperlessError(Exception):
    pass


def pl_key_error():
    return tr("Set KALMIDO_SECRET_KEY on the server to store Paperless tokens (32 random bytes, base64)")


def pl_seal(cid, uid, token):
    from ..personal.timetrack import BadInput
    from ..notify.push import _b64u
    if not SECRET_KEY:
        raise BadInput(pl_key_error())
    n = os.urandom(12)
    return "v1." + _b64u(n + AESGCM(SECRET_KEY).encrypt(n, token.encode(), f"kalmido-pl:{cid}:{uid}".encode()))


def pl_unseal(cid, uid, s):
    """The token or '' (no key, another key, damaged): then it counts as not set."""
    from ..notify.push import _b64u_dec
    if not SECRET_KEY or not s or not s.startswith("v1."):
        return ""
    try:
        raw = _b64u_dec(s[3:])
        return AESGCM(SECRET_KEY).decrypt(raw[:12], raw[12:], f"kalmido-pl:{cid}:{uid}".encode()).decode()
    except (InvalidTag, ValueError, TypeError):
        return ""


def pl_norm_url(u):
    """The base URL of a Paperless server (http(s), no credentials / query / fragment; a trailing /api is dropped)."""
    from ..calendars.subscriptions import cal_norm_url
    u = cal_norm_url(u)
    if not u or not u.lower().startswith(("http://", "https://")):
        return None
    p = urllib.parse.urlsplit(u)
    if p.query or p.fragment:
        return None
    u = u.rstrip("/")
    if u.lower().endswith("/api"):
        u = u[:-4]
    return u


def pl_legacy():
    return {"id": 0, "kind": "legacy", "name": "Paperless", "url": PL_PUBLIC, "api": PL_API, "token": PL_TOKEN,
            "guard": False, "allow": frozenset()}


def pl_token_row(c, cid, uid):
    return c.execute("SELECT token FROM pl_tokens WHERE conn_id=? AND user_id=?", (cid, uid)).fetchone()


def pl_may(c, r, uid):
    """May uid use connection row r at all (token aside)?"""
    if r["kind"] == "personal":
        return r["owner_id"] == uid
    return bool(c.execute("SELECT 1 FROM pl_conn_users WHERE conn_id=? AND user_id=?", (r["id"], uid)).fetchone())


def pl_conn(c, cid, uid):
    """Connection cid as uid may use it right now (their token set) -> dict with token, else None."""
    from ..calendars.subscriptions import cal_allow
    from ..agents.core import is_agent
    cid = int(cid or 0)
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not u or is_agent(u):
        return None
    if not cid:
        return pl_legacy() if PL_TOKEN and u["paperless_access"] else None
    r = c.execute("SELECT * FROM pl_conns WHERE id=?", (cid,)).fetchone()
    if not r or not pl_may(c, r, uid):
        return None
    tk = pl_token_row(c, cid, uid)
    token = pl_unseal(cid, uid, tk["token"]) if tk else ""
    if not token:
        return None
    guard = r["kind"] == "personal"
    return {"id": r["id"], "kind": r["kind"], "name": r["name"], "url": r["url"], "api": r["url"], "token": token,
            "guard": guard, "allow": cal_allow(c) if guard else frozenset()}


def pl_conns_for(c, uid):
    """The connections uid sees (Settings, the link dialog): never a token, only whether theirs is set."""
    from ..agents.core import is_agent
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or is_agent(u):
        return []
    out = []
    if PL_TOKEN and u["paperless_access"]:
        out.append({"id": 0, "kind": "legacy", "name": "Paperless", "url": PL_PUBLIC, "token_set": True, "usable": True})
    for r in c.execute("""SELECT p.* FROM pl_conns p WHERE (p.kind='personal' AND p.owner_id=?) OR (p.kind='server' AND p.id IN
                          (SELECT conn_id FROM pl_conn_users WHERE user_id=?)) ORDER BY p.kind DESC, p.name COLLATE NOCASE, p.id""",
                          (uid, uid)):
        tk = pl_token_row(c, r["id"], uid)
        ok = bool(tk) and bool(pl_unseal(r["id"], uid, tk["token"]))
        out.append({"id": r["id"], "kind": r["kind"], "name": r["name"], "url": r["url"], "token_set": bool(tk),
                    "token_ok": ok, "usable": ok})
    return out


def pl_state(c, u):
    """/api/state: enabled = at least one usable connection; configured = the legacy env connection exists (admin UI);
    conns = what I see (no tokens); key = tokens can be stored; url = the first usable connection (old clients)."""
    from ..agents.core import is_agent
    conns = pl_conns_for(c, u["id"])
    use = [x for x in conns if x["usable"]]
    return {"enabled": bool(use), "configured": bool(PL_TOKEN), "url": use[0]["url"] if use else "", "conns": conns,
            "key": bool(SECRET_KEY), "personal": not is_agent(u)}


def pl_usable_ids(c, uid):
    """Ids of the connections uid can use now (0 = legacy): link titles / thumbnails are only shown for these."""
    if not uid:
        return set()
    return {x["id"] for x in pl_conns_for(c, uid) if x["usable"]}


def pl_forget_user(c, uid):
    """A user is deleted / becomes an agent: their personal connections, tokens and grants go (list bells too)."""
    c.execute("DELETE FROM pl_tokens WHERE conn_id IN (SELECT id FROM pl_conns WHERE kind='personal' AND owner_id=?)", (uid,))
    c.execute("DELETE FROM pl_conns WHERE kind='personal' AND owner_id=?", (uid,))
    c.execute("DELETE FROM pl_tokens WHERE user_id=?", (uid,))
    c.execute("DELETE FROM pl_conn_users WHERE user_id=?", (uid,))
    c.execute("DELETE FROM list_bell WHERE user_id=?", (uid,))


def pl_req(cn, path, method="GET", body=None, ctype=None, raw=False, timeout=20):
    """One request to connection cn (pl_conn): the token only goes to that connection's own host (no redirects)."""
    from ..notify.alerts import aa_err, aa_fail, aa_ok
    from ..calendars.subscriptions import _cal_opener, CalError
    if not cn or not cn.get("token"):
        raise PaperlessError(tr("Paperless is not set up"))
    legacy = cn["id"] == 0
    hdr = {"Authorization": f"Token {cn['token']}", "Accept": "application/json"}
    if ctype:
        hdr["Content-Type"] = ctype
    req = urllib.request.Request(cn["api"] + path, data=body, headers=hdr, method=method)
    try:
        opener = _cal_opener(cn["allow"]) if cn.get("guard") else None
        with (opener.open(req, timeout=timeout) if opener else safe_urlopen(req, timeout=timeout)) as r:
            data = r.read(PL_MAX_BYTES + 1)
            if len(data) > PL_MAX_BYTES:
                raise PaperlessError(tr("Paperless: the answer is too large"))
            if legacy:
                aa_ok("paperless")
            return (data, r.headers.get("Content-Type", "")) if raw else json.loads(data or b"null")
    except urllib.error.HTTPError as e:
        if legacy and (e.code in (401, 403) or e.code >= 500):  # admin alert after aa_integ_min minutes of this
            aa_fail("paperless", {401: "HTTP 401 unauthorised", 403: "HTTP 403 forbidden"}.get(e.code, f"HTTP {e.code}"))
        elif legacy:
            aa_ok("paperless")
        if 300 <= e.code < 400:
            raise PaperlessError(tr("Paperless: the server redirects to another address, which is not followed")) from e
        msg = {401: N_("invalid token"), 403: N_("no permission"), 404: N_("document not found")}.get(e.code)
        raise PaperlessError(f"Paperless: {tr(msg)}" if msg else
                             f"Paperless: HTTP {e.code} {e.read()[:200].decode('utf-8', 'replace')}") from e
    except PaperlessError:
        raise
    except (urllib.error.URLError, TimeoutError, OSError, CalError, http.client.HTTPException, ValueError) as e:
        rs = getattr(e, "reason", None)
        if isinstance(e, CalError) or isinstance(rs, CalError):
            ce = e if isinstance(e, CalError) else rs
            if getattr(ce, "code", "") == "blocked":
                raise PaperlessError(tr("Paperless: this address is in an internal network; an admin can allow the host")) from e
        if legacy:
            aa_fail("paperless", aa_err(e))
        raise PaperlessError(tr("Paperless not reachable ({0})", type(e).__name__ if not legacy else e)) from e


_corr = {}


def pl_correspondents(cn):
    key = (cn["id"], hashlib.sha256(cn["token"].encode()).hexdigest()[:16])
    hit = _corr.get(key)
    if not hit or time.time() - hit[0] > 600:
        j = pl_req(cn, "/api/correspondents/?page_size=1000&fields=id,name")
        if len(_corr) > 200:
            _corr.clear()
        hit = _corr[key] = (time.time(), {r["id"]: r["name"] for r in j.get("results", [])})
    return hit[1]


def pl_doc(cn, doc_id):
    d = pl_req(cn, f"/api/documents/{int(doc_id)}/?fields=id,title,created,correspondent")
    return {"doc_id": d["id"], "title": d.get("title") or tr("Document {0}", d['id']),
            "correspondent": pl_correspondents(cn).get(d.get("correspondent"), "") if d.get("correspondent") else "",
            "created": (d.get("created") or "")[:10]}


@app.errorhandler(PaperlessError)
def paperless_error(e):
    return err(str(e), 502)


def pl_access(u=None):
    """The legacy connection (environment token) is the whole archive of the token owner: only users an admin granted access."""
    u = u if u is not None else (g.user if has_request_context() and getattr(g, "user", None) else None)
    return bool(PL_TOKEN) and bool(u) and bool(u["paperless_access"])


def pl_conn_arg(v):
    from ..personal.timetrack import BadInput
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        raise BadInput(tr("Invalid value: {0}", "conn")) from None


def need_paperless(c=None, cid=0):
    """The connection cid for the current user, or 403 / 502."""
    c = c or db()
    cn = pl_conn(c, cid, me())
    if cn:
        return cn
    if not cid and not PL_TOKEN:
        raise PaperlessError(tr("Paperless is not set up"))
    if not cid:
        raise Denied(403, tr("No access to Paperless (an admin can allow it)"))
    raise Denied(403, tr("No access to this Paperless connection (or your token is not set)"))


PL_THUMB_TYPES = {"image/webp", "image/png", "image/jpeg", "image/gif", "image/avif"}


@app.get("/api/paperless/search")
def paperless_search():
    cn = need_paperless(db(), pl_conn_arg(request.args.get("conn")))
    q = (request.args.get("q") or "").strip()
    fields = "id,title,created,correspondent,page_count,mime_type"
    base = f"/api/documents/?page_size=20&fields={fields}"
    if q:
        j = pl_req(cn, base + "&query=" + urllib.parse.quote(q))
        if not j.get("count") and re.fullmatch(r"[\w\s.-]+", q):  # word fragments: prefix search ("stadtw*")
            j = pl_req(cn, base + "&query=" + urllib.parse.quote(" ".join(w + "*" for w in q.split())))
        if not j.get("count"):  # last resort: plain title match
            j = pl_req(cn, base + "&ordering=-created&title__icontains=" + urllib.parse.quote(q))
    else:
        j = pl_req(cn, base + "&ordering=-added")
    corr = pl_correspondents(cn)
    items = []
    for d in j.get("results", []):
        hit = (d.get("__search_hit__") or {}).get("highlights") or ""
        items.append({"id": d["id"], "title": d.get("title") or "", "created": (d.get("created") or "")[:10],
                      "correspondent": corr.get(d.get("correspondent"), "") if d.get("correspondent") else "",
                      "pages": d.get("page_count"),
                      "snippet": re.sub(r"\s+", " ", re.sub(r"</?b>", "", hit)).strip()[:160]})
    return jsonify(items=items, count=j.get("count", 0), url=cn["url"], conn=cn["id"])


@app.get("/api/paperless/thumb/<int:doc_id>")
def paperless_thumb(doc_id):
    cn = need_paperless(db(), pl_conn_arg(request.args.get("conn")))
    data, ctype = pl_req(cn, f"/api/documents/{doc_id}/thumb/", raw=True)
    ctype = (ctype or "").split(";")[0].strip().lower()
    if ctype not in PL_THUMB_TYPES:  # never serve upstream html/svg/... from our origin
        return err(tr("Paperless: unexpected thumbnail type"), 502)
    resp = Response(data, mimetype=ctype)
    resp.headers["Cache-Control"] = "private, max-age=86400"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; sandbox"
    return resp


@app.post("/api/tasks/<int:tid>/paperless")
def paperless_link(tid):
    c = db()
    need_task(c, tid)
    b = body()
    cid = pl_conn_arg(b.get("conn"))
    cn = need_paperless(c, cid)
    try:
        doc_id = int(b.get("doc_id") or 0)
    except (TypeError, ValueError):
        return err(tr("unknown"))
    if not c.execute("SELECT 1 FROM paperless_links WHERE task_id=? AND doc_id=? AND COALESCE(conn_id,0)=?",
                     (tid, doc_id, cid)).fetchone():
        d = pl_doc(cn, doc_id)
        c.execute("""INSERT INTO paperless_links(task_id,doc_id,title,correspondent,created,status,added_at,conn_id,added_by)
                     VALUES(?,?,?,?,?,'ok',?,?,?)""", (tid, d["doc_id"], d["title"], d["correspondent"], d["created"],
                                                      iso(now_utc()), cid or None, me()))
        log_act(c, tid, "paperless", {"title": d["title"], "conn": cid})
        bump(c)
        c.commit()
    return jsonify(one_task(c, tid))


@app.delete("/api/paperless-links/<int:lid>")
def paperless_unlink(lid):
    c = db()
    r = c.execute("SELECT task_id, title, conn_id FROM paperless_links WHERE id=?", (lid,)).fetchone()
    if not r:
        return err(tr("unknown"), 404)
    need_task(c, r["task_id"])
    need_paperless(c, r["conn_id"] or 0)
    c.execute("DELETE FROM paperless_links WHERE id=?", (lid,))
    log_act(c, r["task_id"], "paperless_rm", {"title": r["title"], "conn": r["conn_id"] or 0})
    bump(c)
    c.commit()
    return jsonify(one_task(c, r["task_id"]))


# ---- 2.1.0 (#180): the connections of the current user (Settings > Integrations > My connections)
def pl_clean_name(v):
    from ..personal.timetrack import BadInput
    n = str(v or "").strip()[:PL_NAME_MAX]
    if not n:
        raise BadInput(tr("Name missing"))
    return n


def pl_clean_token(v):
    from ..personal.timetrack import BadInput
    t = str(v or "").strip()
    if not t or len(t) > PL_TOKEN_MAX or any(ch.isspace() or ord(ch) < 33 for ch in t):
        raise BadInput(tr("Invalid value: {0}", tr("API token")))
    return t


def pl_set_token(c, cid, uid, token):
    c.execute("INSERT INTO pl_tokens(conn_id,user_id,token,updated_at) VALUES(?,?,?,?) ON CONFLICT(conn_id,user_id) "
              "DO UPDATE SET token=excluded.token, updated_at=excluded.updated_at", (cid, uid, pl_seal(cid, uid, token), iso(now_utc())))


def need_pl_user():
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403, tr("An agent is never an admin and has no Paperless access"))


@app.get("/api/paperless/conns")
def pl_conns_get():
    need_pl_user()
    return jsonify(conns=pl_conns_for(db(), me()), key=bool(SECRET_KEY))


@app.post("/api/paperless/conns")
def pl_conn_create():
    """{name, url, token}: a personal connection (only I see and use it)."""
    need_pl_user()
    c, b = db(), body()
    if not SECRET_KEY:
        return err(pl_key_error(), 409)
    name, url, token = pl_clean_name(b.get("name")), pl_norm_url(b.get("url")), pl_clean_token(b.get("token"))
    if not url:
        return err(tr("Invalid value: {0}", "URL"))
    if c.execute("SELECT COUNT(*) FROM pl_conns WHERE kind='personal' AND owner_id=?", (me(),)).fetchone()[0] >= PL_CONN_MAX:
        return err(tr("At most {0} connections", PL_CONN_MAX), 409)
    cid = c.execute("INSERT INTO pl_conns(kind,owner_id,name,url,created_at) VALUES('personal',?,?,?,?)",
                    (me(), name, url, iso(now_utc()))).lastrowid
    pl_set_token(c, cid, me(), token)
    bump(c)
    c.commit()
    return jsonify(next(x for x in pl_conns_for(c, me()) if x["id"] == cid)), 201


def need_pl_conn_row(c, cid):
    """A connection row the current user may use (personal: own; server: granted), else 404 (no hint that it exists)."""
    from ..agents.core import is_agent
    r = c.execute("SELECT * FROM pl_conns WHERE id=?", (cid,)).fetchone()
    if not r or is_agent(g.user) or not pl_may(c, r, me()):
        raise Denied(404)
    return r


@app.patch("/api/paperless/conns/<int:cid>")
def pl_conn_update(cid):
    """Personal: {name?, url?, token?}; a server connection: only {token} (my own)."""
    c, b = db(), body()
    r = need_pl_conn_row(c, cid)
    unknown = sorted(k for k in b if k not in (("name", "url", "token") if r["kind"] == "personal" else ("token",)))
    if unknown:
        return err(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    if "name" in b:
        c.execute("UPDATE pl_conns SET name=? WHERE id=?", (pl_clean_name(b["name"]), cid))
    if "url" in b:
        url = pl_norm_url(b["url"])
        if not url:
            return err(tr("Invalid value: {0}", "URL"))
        c.execute("UPDATE pl_conns SET url=? WHERE id=?", (url, cid))
    if "token" in b:
        if not SECRET_KEY:
            c.rollback()
            return err(pl_key_error(), 409)
        pl_set_token(c, cid, me(), pl_clean_token(b["token"]))
    bump(c)
    c.commit()
    return jsonify(next(x for x in pl_conns_for(c, me()) if x["id"] == cid))


@app.delete("/api/paperless/conns/<int:cid>/token")
def pl_conn_token_delete(cid):
    c = db()
    need_pl_conn_row(c, cid)
    c.execute("DELETE FROM pl_tokens WHERE conn_id=? AND user_id=?", (cid, me()))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.delete("/api/paperless/conns/<int:cid>")
def pl_conn_delete(cid):
    """Only personal connections (server ones belong to the admin). Links made with it stay, as hidden documents."""
    c = db()
    r = need_pl_conn_row(c, cid)
    if r["kind"] != "personal":
        return err(tr("Only an admin can remove a server connection"), 403)
    c.execute("DELETE FROM pl_tokens WHERE conn_id=?", (cid,))
    c.execute("DELETE FROM pl_conns WHERE id=?", (cid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


@app.post("/api/paperless/conns/<int:cid>/test")
def pl_conn_test(cid):
    """Checks my token on that connection (one small request)."""
    c = db()
    if cid:
        need_pl_conn_row(c, cid)
    cn = need_paperless(c, cid)
    try:
        pl_req(cn, "/api/correspondents/?page_size=1&fields=id", timeout=10)
    except PaperlessError as e:
        return jsonify(ok=False, error=str(e))
    return jsonify(ok=True)


# ---- 2.1.0 (#180): server connections (admin). Never a token, never a personal connection.
def pl_server_dict(c, r):
    return {"id": r["id"], "name": r["name"], "url": r["url"],
            "users": [x[0] for x in c.execute("SELECT user_id FROM pl_conn_users WHERE conn_id=? ORDER BY user_id", (r["id"],))],
            "tokens": c.execute("SELECT COUNT(*) FROM pl_tokens WHERE conn_id=?", (r["id"],)).fetchone()[0]}


def pl_admin_state(c):
    return {"key": bool(SECRET_KEY), "key_problem": SECRET_KEY_PROBLEM,
            "legacy": {"configured": bool(PL_TOKEN), "url": PL_PUBLIC if PL_TOKEN else ""},
            "servers": [pl_server_dict(c, r) for r in c.execute("SELECT * FROM pl_conns WHERE kind='server' ORDER BY name COLLATE NOCASE, id")]}


@app.get("/api/admin/paperless")
def pl_admin_get():
    from ..accounts.users import need_admin
    need_admin()
    return jsonify(pl_admin_state(db()))


def pl_grant_users(c, cid, users):
    from ..personal.timetrack import BadInput
    from ..agents.core import is_agent
    if not isinstance(users, list) or len(users) > 5000:
        raise BadInput(tr("Invalid value: {0}", "users"))
    want = set()
    for x in users:
        u = c.execute("SELECT * FROM users WHERE id=?", (as_int(x, "users", 1),)).fetchone()
        if not u or is_agent(u):
            raise BadInput(tr("Invalid value: {0}", "users"))
        want.add(u["id"])
    have = {r[0] for r in c.execute("SELECT user_id FROM pl_conn_users WHERE conn_id=?", (cid,))}
    for uid in have - want:  # access taken away: their token goes too
        c.execute("DELETE FROM pl_conn_users WHERE conn_id=? AND user_id=?", (cid, uid))
        c.execute("DELETE FROM pl_tokens WHERE conn_id=? AND user_id=?", (cid, uid))
    for uid in want - have:
        c.execute("INSERT INTO pl_conn_users(conn_id,user_id) VALUES(?,?)", (cid, uid))


@app.post("/api/admin/paperless")
def pl_admin_create():
    """{name, url, users?: [ids]}: a server connection; each allowed user enters their own token."""
    from ..accounts.users import need_admin
    need_admin()
    c, b = db(), body()
    name, url = pl_clean_name(b.get("name")), pl_norm_url(b.get("url"))
    if not url:
        return err(tr("Invalid value: {0}", "URL"))
    if c.execute("SELECT COUNT(*) FROM pl_conns WHERE kind='server'").fetchone()[0] >= PL_SERVER_MAX:
        return err(tr("At most {0} connections", PL_SERVER_MAX), 409)
    cid = c.execute("INSERT INTO pl_conns(kind,owner_id,name,url,created_at) VALUES('server',NULL,?,?,?)",
                    (name, url, iso(now_utc()))).lastrowid
    pl_grant_users(c, cid, b.get("users") or [])
    bump(c)
    c.commit()
    return jsonify(pl_server_dict(c, c.execute("SELECT * FROM pl_conns WHERE id=?", (cid,)).fetchone())), 201


def need_pl_server(c, cid):
    r = c.execute("SELECT * FROM pl_conns WHERE id=? AND kind='server'", (cid,)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.patch("/api/admin/paperless/<int:cid>")
def pl_admin_update(cid):
    """{name?, url?, users?}. A new URL drops every stored token of it (they were meant for the old server)."""
    from ..accounts.users import need_admin
    need_admin()
    c, b = db(), body()
    r = need_pl_server(c, cid)
    if "name" in b:
        c.execute("UPDATE pl_conns SET name=? WHERE id=?", (pl_clean_name(b["name"]), cid))
    if "url" in b:
        url = pl_norm_url(b["url"])
        if not url:
            return err(tr("Invalid value: {0}", "URL"))
        if url != r["url"]:
            c.execute("UPDATE pl_conns SET url=? WHERE id=?", (url, cid))
            c.execute("DELETE FROM pl_tokens WHERE conn_id=?", (cid,))
    if "users" in b:
        pl_grant_users(c, cid, b["users"])
    bump(c)
    c.commit()
    return jsonify(pl_server_dict(c, need_pl_server(c, cid)))


@app.delete("/api/admin/paperless/<int:cid>")
def pl_admin_delete(cid):
    from ..accounts.users import need_admin
    need_admin()
    c = db()
    need_pl_server(c, cid)
    c.execute("DELETE FROM pl_tokens WHERE conn_id=?", (cid,))
    c.execute("DELETE FROM pl_conn_users WHERE conn_id=?", (cid,))
    c.execute("DELETE FROM pl_conns WHERE id=?", (cid,))
    bump(c)
    c.commit()
    return jsonify(ok=True)


def multipart(fields, files):
    """fields: {name: value}; files: [(field, filename, mime, bytes)] -> (body, content-type)."""
    b = uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields.items():
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    for field, name, mime, data in files:
        fn = urllib.parse.quote(name)
        out.write(f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{fn}"; filename*=UTF-8\'\'{fn}\r\n'
                  f'Content-Type: {mime}\r\n\r\n'.encode())
        out.write(data)
        out.write(b"\r\n")
    out.write(f"--{b}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={b}"


@app.post("/api/attachments/<int:aid>/to-paperless")
def attachment_to_paperless(aid):
    """Upload an attachment into Paperless. The link is 'pending' until Paperless has consumed it;
    the watchdog then swaps it for the real document and removes the local copy."""
    c = db()
    a = need_attachment(c, aid, True)
    if a["comment_id"] is not None:
        return err(tr("Files in comments cannot be sent to Paperless"))
    cid = pl_conn_arg(body().get("conn", request.args.get("conn")))
    cn = need_paperless(c, cid)
    if c.execute("SELECT 1 FROM paperless_links WHERE att_id=? AND status='pending'", (aid,)).fetchone():
        return err(tr("Already being sent to Paperless"))
    with open(os.path.join(ATT_DIR, a["path"]), "rb") as f:
        data = f.read()
    title = os.path.splitext(a["name"])[0]
    payload, ctype = multipart({"title": title}, [("document", a["name"], a["mime"], data)])
    ptask = pl_req(cn, "/api/documents/post_document/", "POST", payload, ctype, timeout=120)
    if isinstance(ptask, dict):
        ptask = ptask.get("task_id") or ptask.get("id") or json.dumps(ptask)
    c.execute("""INSERT INTO paperless_links(task_id,title,status,message,ptask,att_id,added_at,conn_id,added_by)
                 VALUES(?,?,'pending','Paperless verarbeitet das Dokument…',?,?,?,?,?)""",
              (a["task_id"], title, str(ptask), aid, iso(now_utc()), cid or None, me()))
    log_act(c, a["task_id"], "paperless_send", {"name": a["name"]})
    bump(c)
    c.commit()
    return jsonify(one_task(c, a["task_id"]))


def task_owner(c, tid):
    """Owner of the list a task is in (settings for server-side work on the task)."""
    r = c.execute("SELECT l.owner_id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    return r[0] if r else default_uid(c)


def paperless_poll(c):
    """Watchdog: resolve pending uploads (success -> link doc + drop the local attachment). 2.1.0: each with its
    connection (the legacy one with the environment token, the others with the token of whoever sent it)."""
    from ..notify.push import _wd_fail
    rows = c.execute("SELECT * FROM paperless_links WHERE status='pending'").fetchall()
    down = set()  # connections that failed in this tick
    for p in rows:
        cid = p["conn_id"] or 0
        if cid in down:
            continue
        cn = (pl_legacy() if PL_TOKEN else None) if not cid else pl_conn(c, cid, p["added_by"])
        if not cn:
            continue  # no token (any more): stays pending, the 30 min rule does not apply without an answer
        try:
            if _pl_poll_one(c, p, cn) == "stop":
                down.add(cid)
        except Exception as e:  # noqa: BLE001
            _wd_fail(c, "paperless link", p["id"], e)


def _pl_poll_one(c, p, cn):
    try:
        j = pl_req(cn, "/api/tasks/?task_id=" + urllib.parse.quote(p["ptask"] or ""))
    except PaperlessError as e:
        print("paperless poll:", e, flush=True)
        return "stop"
    owner = task_owner(c, p["task_id"])
    lst = j if isinstance(j, list) else j.get("results", [])
    t = next((x for x in lst if x.get("task_id") == p["ptask"]), None)
    age = (now_utc() - parse_iso(p["added_at"])).total_seconds()
    if not t:
        if age > 1800:
            c.execute("UPDATE paperless_links SET status='error', message=? WHERE id=?",
                      (tr("Paperless did not confirm the upload", lg=lang(c, owner)), p["id"]))
            bump(c)
            c.commit()
        return
    status = (t.get("status") or "").lower()
    res = t.get("result_data") if "result_data" in t else t.get("result")
    if isinstance(res, dict):  # paperless 3.x: {"error_type", "error_message", "traceback"} on failure
        res_txt = res.get("error_message") or res.get("message") or json.dumps(res, ensure_ascii=False)
    else:
        res_txt = res or ""
    doc_id = None
    if status == "success":
        ids = t.get("related_document_ids") or ([t["related_document"]] if t.get("related_document") else [])
        doc_id = ids[0] if ids else None
        if not doc_id:
            m = re.search(r"(?:id|#)\s*(\d+)", res_txt or "")
            doc_id = int(m.group(1)) if m else None
    elif status == "failure":
        m = re.search(r"duplicate.*?#(\d+)", res_txt or "", re.I | re.S)
        if m:  # already in Paperless: link the existing document
            doc_id = int(m.group(1))
        else:
            c.execute("UPDATE paperless_links SET status='error', message=? WHERE id=?",
                      ((res_txt or tr("Paperless could not consume the document", lg=lang(c, owner)))[:300], p["id"]))
            bump(c)
            c.commit()
            return
    else:
        return  # pending / started
    if not doc_id:
        return
    try:
        d = pl_doc(cn, doc_id)
    except PaperlessError:
        d = {"doc_id": doc_id, "title": p["title"], "correspondent": "", "created": ""}
    dup = status == "failure"
    c.execute("""UPDATE paperless_links SET doc_id=?, title=?, correspondent=?, created=?, status='ok',
                 message=?, att_id=NULL WHERE id=?""",
              (d["doc_id"], d["title"], d["correspondent"], d["created"],
               "war schon in Paperless" if dup else "", p["id"]))
    files = []
    keep = usettings(c, owner).get("paperless_keep") == "1"
    if p["att_id"] and not keep:
        a = c.execute("SELECT path FROM attachments WHERE id=?", (p["att_id"],)).fetchone()
        if a:
            files.append(a["path"])
            c.execute("DELETE FROM attachments WHERE id=?", (p["att_id"],))
    bump(c)
    c.commit()
    unlink_files(files)
