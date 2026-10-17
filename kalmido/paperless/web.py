"""2.48.0 (#1152): the routes of the Paperless-ngx connection (documents settings, static/js/paperless.js).

Self-hosted servers only: on a hosted server every route answers 404. ?ws / {ws} = 'private' | 'org:<id>' like the
documents settings; setting up, importing and stopping need the right to manage that workspace (an organisation's admin,
the person themself for their own space). Agents have no connection."""
import json

from flask import jsonify, request

from ..core.config import app
from ..core.db import body, db, err
from ..core.i18n import tr
from ..core.access import Denied
from ..accounts.session import me
from ..docs import store as S
from ..docs.web import _no_agent, ws_param
from . import ngx as P


def _gate():
    from ..admin.hosting import hosted
    if hosted():
        raise Denied(404)
    _no_agent()


def _ws(c, raw, manage=True):
    uid = me()
    org, ws = ws_param(c, raw, uid, manage=manage)
    return uid, org, ws


def _public(c, ws, uid, org):
    from ..accounts.orgs import is_org_admin
    r = P.pl_row(c, ws)
    can = bool(is_org_admin(c, uid, org)) if org else True
    out = {"available": True, "can_manage": can, "ws": f"org:{org}" if org else "private", "every_choices": list(P.PL_EVERY)}
    if not r:
        out["conn"] = None
        return out
    run = {"state": r["run_state"] or "idle", "kind": r["run_kind"], "total": r["run_total"], "done": r["run_done"], "new": r["run_new"],
           "skipped": r["run_skip"], "failed": r["run_fail"], "error": r["run_error"], "error_text": P.pl_err_text(r["run_error"])}
    try:  # 2.69.0 B (#1847): what the last run learnt (rules taken over, documents trained)
        run["learn"] = json.loads(r["run_learn"]) if r["run_learn"] else None
    except ValueError:
        run["learn"] = None
    out["conn"] = {"url": r["url"], "token_set": bool(r["token"]), "follow": bool(r["follow"]), "every_min": r["every_min"],
                   "synced_at": r["synced_at"], "error": r["error"], "error_text": P.pl_err_text(r["error"]), "run": run}
    return out


@app.get("/api/paperless")
def pl_get_conn():
    """?ws= -- the connection of the workspace (never the token: only token_set) and the state of the import."""
    _gate()
    c = db()
    uid, org, ws = _ws(c, request.args.get("ws"), manage=False)
    return jsonify(_public(c, ws, uid, org))


@app.put("/api/paperless")
def pl_put_conn():
    """{ws, url?, token?, follow?: bool, every_min?} -- sets up / changes the connection; a new address or token is tried
    at once (400 with the reason when Paperless-ngx does not answer)."""
    _gate()
    c = db()
    d = body()
    uid, org, ws = _ws(c, d.get("ws"))
    unknown = sorted(set(d) - {"ws", "url", "token", "follow", "every_min"})
    if unknown:
        return err(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    r = P.pl_row(c, ws)
    url = P.pl_norm_url(d["url"]) if "url" in d else (r["url"] if r else None)
    if not url:
        return err(tr("Invalid value: {0}", tr("Address")))
    tok = P.pl_token(c, r) if r and url == r["url"] else ""
    if "token" in d:
        t = d["token"]
        if not isinstance(t, str) or not t.strip() or len(t.strip()) > P.PL_TOKEN_MAX or any(ord(ch) < 33 for ch in t.strip()):
            return err(tr("Invalid value: {0}", tr("API token")))
        tok = t.strip()
    if not tok:
        return err(tr("Please enter the API token"))
    if not P._token_key(ws):  # 2.48.0 review (S2): the token is only ever stored sealed
        return err(tr("The server key is missing: the API token cannot be stored safely"), 409)
    follow = r["follow"] if r else 0
    if "follow" in d:
        if not isinstance(d["follow"], bool):
            return err(tr("Invalid value: {0}", "follow"))
        follow = 1 if d["follow"] else 0
    every = r["every_min"] if r else P.PL_EVERY[0]
    if "every_min" in d:
        if d["every_min"] not in P.PL_EVERY:
            return err(tr("Invalid value: {0}", "every_min"))
        every = d["every_min"]
    if not r or "url" in d or "token" in d:
        try:
            P.pl_check(c, url, tok)
        except P.PlError as e:
            return err(P.pl_err_text(e.stored()))
    sealed = P.pl_seal_token(ws, tok)  # 2.48.0 review (S2): always sealed, never plain in the database
    ts = P._now()
    if r:
        c.execute("UPDATE pl_sources SET url=?, token=?, follow=?, every_min=?, error='', created_by=?, updated_at=? WHERE id=?",
                  (url, sealed, follow, every, uid, ts, r["id"]))
    else:
        c.execute("INSERT INTO pl_sources(org_id, ws, url, token, follow, every_min, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                  (org, ws, url, sealed, follow, every, uid, ts, ts))
    c.commit()
    if follow:
        P.pl_kick()
    return jsonify(_public(c, ws, uid, org))


@app.delete("/api/paperless")
def pl_del_conn():
    """?ws= -- removes the connection (the token goes; imported documents stay, and they never come in twice)."""
    _gate()
    c = db()
    uid, org, ws = _ws(c, request.args.get("ws"))
    c.execute("DELETE FROM pl_sources WHERE ws=?", (ws,))
    c.commit()
    return jsonify(_public(c, ws, uid, org))


def _need_conn(c, ws):
    r = P.pl_row(c, ws)
    if not r:
        raise Denied(404, tr("No Paperless-ngx connection"))
    return r


@app.get("/api/paperless/preview")
def pl_preview_get():
    """?ws= -- before the import: number of documents, already imported, tags / correspondents / types with their mapping."""
    _gate()
    c = db()
    _uid, _org, ws = _ws(c, request.args.get("ws"))
    r = _need_conn(c, ws)
    try:
        return jsonify(P.pl_preview(c, r))
    except P.PlError as e:
        return err(P.pl_err_text(e.stored()), 502)


@app.post("/api/paperless/import")
def pl_import_start():
    """{ws, mapping?} -- saves the mapping and starts the import of all documents in the background (409 while one runs)."""
    _gate()
    c = db()
    d = body()
    uid, _org, ws = _ws(c, d.get("ws"))
    r = _need_conn(c, ws)
    if r["run_state"] in ("queued", "busy", "stop"):
        return err(tr("An import is already running"), 409)
    if "mapping" in d:
        c.execute("UPDATE pl_sources SET mapping=? WHERE id=?", (S._jseal(c, ws, "pl_sources.mapping", P.pl_clean_mapping(d["mapping"])), r["id"]))
    c.execute("UPDATE pl_sources SET run_state='queued', run_kind='all', run_by=?, run_total=0, run_done=0, run_new=0, run_skip=0, "
              "run_fail=0, run_error='', run_beat=? WHERE id=?", (uid, P._now(), r["id"]))
    c.commit()
    P.pl_kick()
    return jsonify(_public(c, ws, uid, _org))


@app.post("/api/paperless/stop")
def pl_import_stop():
    """{ws} -- stops a running import after the current document (what came in stays)."""
    _gate()
    c = db()
    d = body()
    uid, org, ws = _ws(c, d.get("ws"))
    r = _need_conn(c, ws)
    if r["run_state"] == "queued":
        c.execute("UPDATE pl_sources SET run_state='' WHERE id=?", (r["id"],))
    elif r["run_state"] == "busy":
        c.execute("UPDATE pl_sources SET run_state='stop' WHERE id=?", (r["id"],))
    c.commit()
    return jsonify(_public(c, ws, uid, org))
