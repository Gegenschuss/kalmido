"""2.55.0 E (#1455): the routes of the newsletter connection (contacts settings, static/js/newsletter.js).

?ws / {ws} = 'private' | 'org:<id>' like the documents settings. Everything about the connection (reading included: the
log shows numbers of the organisation's contacts) needs the right to manage that workspace -- an organisation's admin, the
person themself for their own space. The consent of a contact: whoever may change the contact. Agents have no routes here
(they read the consent with the contact through the API v1 when they may read the contact anyway)."""
import csv
import io
import json
import re
from datetime import date, datetime, timezone

from flask import jsonify, request

from ..core.config import app
from ..core.db import body, db, err, iso, local_now
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..accounts.session import me
from ..docs.web import _no_agent, ws_param
from . import sync as N
from .adapters import NWL_DEFAULT_URL, NWL_KINDS, NWL_PREVIEW, NwlError

NWL_SECRET_MAX = 400
NWL_NAME_MAX = 120


def _ws(c, raw):
    _no_agent()
    uid = me()
    org, ws = ws_param(c, raw, uid, manage=True)
    return uid, org, ws


def _seg_json(c, conn, s, rows):
    try:
        rule = json.loads(s["rule"] or "{}")
    except ValueError:
        rule = {}
    n = N.nwl_seg_counts(c, conn, rule, rows)
    n["on_list"] = c.execute("SELECT COUNT(*) FROM nl_members WHERE seg_id=?", (s["id"],)).fetchone()[0]
    return {"id": s["id"], "name": s["name"], "rule": rule, "list_id": s["remote_id"], "list_name": s["remote_name"], "counts": n}


def _public(c, ws, org):
    r = N.nwl_conn(c, ws)
    out = {"ws": f"org:{org}" if org else "private", "kinds": [{"kind": k, "preview": k in NWL_PREVIEW, "default_url": NWL_DEFAULT_URL.get(k, "")}
                                                               for k in NWL_KINDS],
           "modes": list(N.NWL_MODES), "key_ok": N.nwl_key_ok(ws)}
    if not r:
        out["conn"] = None
        return out
    N.nwl_stale(c, r["id"])
    rows = N.nwl_contacts(c, ws)
    secret_set = bool(r["secret"])
    out["conn"] = {"kind": r["kind"], "preview": r["kind"] in NWL_PREVIEW, "url": r["url"], "secret_set": secret_set,
                   "hint": r["hint"] if secret_set else "", "mode": r["mode"], "auto": bool(r["auto"]), "synced_at": r["synced_at"],
                   "error": r["error"], "error_text": N.nwl_err_text(r["error"]), "busy": N.nwl_busy(r["id"]),
                   "user": "set" if secret_set and r["kind"] in ("listmonk", "cleverreach") else ""}
    out["segments"] = [_seg_json(c, r, s, rows) for s in c.execute("SELECT * FROM nl_segments WHERE conn_id=? ORDER BY lower(name), id",
                                                                    (r["id"],)).fetchall()]
    out["runs"] = [N.nwl_run_json(x) for x in c.execute("SELECT * FROM nl_runs WHERE conn_id=? ORDER BY id DESC LIMIT 20", (r["id"],))]
    out["facets"] = N.nwl_facets(c, ws)
    out["contacts"] = {"total": len(rows), "email": sum(1 for x in rows if N.nwl_email(x)),
                       "yes": sum(1 for x in rows if x["nl_status"] == "yes"), "pending": sum(1 for x in rows if x["nl_status"] == "pending"),
                       "blocked": sum(1 for x in rows if x["nl_status"] in N.NWL_BLOCKED)}
    return out


def _need_conn(c, ws):
    r = N.nwl_conn(c, ws)
    if not r:
        raise Denied(404, tr("No newsletter connection"))
    return r


def _svc_err(e, code=400):
    return err(N.nwl_err_text(e.stored()), code)


@app.get("/api/newsletter")
def nwl_get_conn():
    """?ws= -- the connection (never the access data: only secret_set + the last four characters), segments, log."""
    c = db()
    _uid, org, ws = _ws(c, request.args.get("ws"))
    return jsonify(_public(c, ws, org))


def _str(d, k, n):
    v = d.get(k)
    if not isinstance(v, str) or not v.strip() or len(v.strip()) > n or any(ord(ch) < 32 for ch in v):
        return None
    return v.strip()


@app.put("/api/newsletter")
def nwl_put_conn():
    """{ws, kind?, url?, user?, token?, mode?: consented | doi, auto?: bool} -- sets up / changes the connection; new access
    data or a new address are tried at once (400 with the reason when the service does not answer)."""
    c = db()
    d = body()
    uid, org, ws = _ws(c, d.get("ws"))
    unknown = sorted(set(d) - {"ws", "kind", "url", "user", "token", "mode", "auto"})
    if unknown:
        return err(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    r = N.nwl_conn(c, ws)
    kind = d.get("kind", r["kind"] if r else None)
    if kind not in NWL_KINDS:
        return err(tr("Invalid value: {0}", "kind"))
    url = r["url"] if r and kind == r["kind"] else ""
    if "url" in d:
        if d["url"] in ("", None) and kind != "listmonk":
            url = ""
        else:
            from ..paperless.ngx import pl_norm_url
            url = pl_norm_url(d["url"])
            if not url:
                return err(tr("Invalid value: {0}", tr("Address")))
    if kind == "listmonk" and not url:
        return err(tr("Please enter the address of the newsletter service"))
    # the stored access data only ever go to the address they were entered for: another service or address needs them again
    # (the user name is no secret and stays)
    old = N.nwl_secret(r) if r and kind == r["kind"] else {}
    secret = old if r and url == r["url"] else {"user": old.get("user", "")}
    if "token" in d:
        t = _str(d, "token", NWL_SECRET_MAX)
        if not t or any(ord(ch) < 33 for ch in t):
            return err(tr("Invalid value: {0}", tr("Access data")))
        secret = {"token": t, "user": secret.get("user", "")}
    if "user" in d:
        u = _str(d, "user", NWL_SECRET_MAX)
        if not u:
            return err(tr("Invalid value: {0}", tr("User")))
        secret["user"] = u
    if not secret.get("token") or (kind in ("listmonk", "cleverreach") and not secret.get("user")):
        return err(tr("Please enter the access data"))
    if not N.nwl_key_ok(ws):
        return err(tr("The server key is missing: the access data cannot be stored safely"), 409)
    mode = d.get("mode", r["mode"] if r and kind == "listmonk" else "consented")  # double opt-in through Kalmido: listmonk only
    if mode not in N.NWL_MODES or (mode == "doi" and kind != "listmonk"):
        return err(tr("Invalid value: {0}", "mode"))
    auto = r["auto"] if r else 0
    if "auto" in d:
        if not isinstance(d["auto"], bool):
            return err(tr("Invalid value: {0}", "auto"))
        auto = 1 if d["auto"] else 0
    if not r or {"kind", "url", "user", "token"} & set(d):
        try:
            N.nwl_adapter_for(c, {"kind": kind, "url": url}, secret).check()
        except NwlError as e:
            return _svc_err(e)
    sealed, hint, ts = N.nwl_seal(ws, secret), N.nwl_hint(secret), N._now()
    if r:
        if kind != r["kind"] or url != r["url"]:  # another service / instance: the lists of the old one mean nothing there
            c.execute("UPDATE nl_segments SET remote_id='', remote_name='', updated_at=? WHERE conn_id=?", (ts, r["id"]))
            c.execute("DELETE FROM nl_members WHERE seg_id IN (SELECT id FROM nl_segments WHERE conn_id=?)", (r["id"],))
        c.execute("UPDATE nl_conns SET kind=?, url=?, secret=?, hint=?, mode=?, auto=?, error='', updated_at=? WHERE id=?",
                  (kind, url, sealed, hint, mode, auto, ts, r["id"]))
    else:
        c.execute("INSERT INTO nl_conns(org_id, owner_id, ws, kind, url, secret, hint, mode, auto, created_by, created_at, updated_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (org, None if org else uid, ws, kind, url, sealed, hint, mode, auto, uid, ts, ts))
    c.commit()
    return jsonify(_public(c, ws, org))


@app.delete("/api/newsletter")
def nwl_del_conn():
    """?ws= -- removes the connection with its segments and log (the access data go; the lists at the service and the
    consent of the contacts stay)."""
    c = db()
    _uid, org, ws = _ws(c, request.args.get("ws"))
    c.execute("DELETE FROM nl_conns WHERE ws=?", (ws,))
    c.commit()
    return jsonify(_public(c, ws, org))


@app.get("/api/newsletter/lists")
def nwl_lists():
    """?ws= -- the lists at the service (to pick one for a segment)."""
    c = db()
    _uid, _org, ws = _ws(c, request.args.get("ws"))
    r = _need_conn(c, ws)
    try:
        return jsonify({"lists": N.nwl_adapter_for(c, r).lists()[:1000]})
    except NwlError as e:
        return _svc_err(e, 502)


def _seg_in(c, ws, conn, d, seg=None):
    """Checks + the list at the service ({list_id} = an existing one, {create_list: true} = a new one named like the segment)."""
    unknown = sorted(set(d) - {"ws", "name", "rule", "list_id", "create_list"})
    if unknown:
        raise Denied(400, tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    name = seg["name"] if seg and "name" not in d else _str(d, "name", NWL_NAME_MAX)
    if not name:
        raise Denied(400, tr("Invalid value: {0}", tr("Name")))
    rule = json.loads(seg["rule"] or "{}") if seg and "rule" not in d else N.nwl_clean_rule(c, ws, d.get("rule") or {})
    if rule is None:
        raise Denied(400, tr("Invalid value: {0}", "rule"))
    rid, rname = (seg["remote_id"], seg["remote_name"]) if seg else ("", "")
    if d.get("create_list") is True:
        a = N.nwl_adapter_for(c, conn)
        made = a.create_list(name, conn["mode"] == "doi")
        rid, rname = made["id"], made["name"] or name
    elif "list_id" in d:
        lid = str(d["list_id"] or "")
        if lid:
            hit = next((x for x in N.nwl_adapter_for(c, conn).lists() if x["id"] == lid), None)
            if not hit:
                raise Denied(400, tr("The list of this segment no longer exists at the newsletter service"))
            rid, rname = hit["id"], hit["name"]
        else:
            rid, rname = "", ""
    return name, rule, rid, rname


@app.post("/api/newsletter/segments")
def nwl_seg_new():
    """{ws, name, rule: {tags, companies, books}, list_id? | create_list?: true} -- a new segment."""
    c = db()
    d = body()
    _uid, org, ws = _ws(c, d.get("ws"))
    conn = _need_conn(c, ws)
    if c.execute("SELECT COUNT(*) FROM nl_segments WHERE conn_id=?", (conn["id"],)).fetchone()[0] >= N.NWL_SEG_MAX:
        return err(tr("At most {0} segments", N.NWL_SEG_MAX))
    try:
        name, rule, rid, rname = _seg_in(c, ws, conn, d)
    except NwlError as e:
        return _svc_err(e, 502)
    ts = N._now()
    sid = c.execute("INSERT INTO nl_segments(conn_id, org_id, name, rule, remote_id, remote_name, created_at, updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?) RETURNING id", (conn["id"], conn["org_id"], name, json.dumps(rule), rid, rname, ts, ts)).fetchone()[0]
    c.commit()
    out = _public(c, ws, org)
    out["segment_id"] = sid
    return jsonify(out)


def _need_seg(c, sid, ws):
    conn = _need_conn(c, ws)
    s = c.execute("SELECT * FROM nl_segments WHERE id=? AND conn_id=?", (sid, conn["id"])).fetchone()
    if not s:
        raise Denied(404)
    return conn, s


@app.patch("/api/newsletter/segments/<int:sid>")
def nwl_seg_edit(sid):
    """{ws, name?, rule?, list_id?, create_list?} -- changes a segment (another list: what Kalmido put on the old one stays there)."""
    c = db()
    d = body()
    _uid, org, ws = _ws(c, d.get("ws"))
    conn, s = _need_seg(c, sid, ws)
    try:
        name, rule, rid, rname = _seg_in(c, ws, conn, d, s)
    except NwlError as e:
        return _svc_err(e, 502)
    if rid != s["remote_id"]:
        c.execute("DELETE FROM nl_members WHERE seg_id=?", (sid,))
    c.execute("UPDATE nl_segments SET name=?, rule=?, remote_id=?, remote_name=?, updated_at=? WHERE id=?",
              (name, json.dumps(rule), rid, rname, N._now(), sid))
    c.commit()
    return jsonify(_public(c, ws, org))


@app.delete("/api/newsletter/segments/<int:sid>")
def nwl_seg_del(sid):
    """?ws= -- removes a segment (its list at the service stays as it is)."""
    c = db()
    _uid, org, ws = _ws(c, request.args.get("ws"))
    _need_seg(c, sid, ws)
    c.execute("DELETE FROM nl_segments WHERE id=?", (sid,))
    c.commit()
    return jsonify(_public(c, ws, org))


@app.post("/api/newsletter/sync")
def nwl_sync():
    """{ws} -- "Sync now": starts a run (202; the log shows it). 409 when one runs already."""
    c = db()
    d = body()
    uid, org, ws = _ws(c, d.get("ws"))
    conn = _need_conn(c, ws)
    rid = N.nwl_start(c, conn, kind="manual", by=uid)
    if rid is None:
        return err(tr("A sync is already running"), 409)
    out = _public(c, ws, org)
    out["run_id"] = rid
    return jsonify(out), 202


@app.put("/api/newsletter/consent")
def nwl_consent():
    """{ids: [contact ids], status: '' | yes | pending, source?} -- the newsletter consent of contacts (write right on each).
    unsub / bounce come only from the service, and a contact with one of them stays so (a new subscription goes through
    the service's own form)."""
    _no_agent()
    from ..contacts.model import need_contact
    c = db()
    d = body()
    uid = me()
    unknown = sorted(set(d) - {"ids", "status", "source"})
    if unknown:
        return err(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    ids, st = d.get("ids"), d.get("status")
    if (not isinstance(ids, list) or not ids or len(ids) > 2000
            or not all(isinstance(x, int) and not isinstance(x, bool) for x in ids)):
        return err(tr("Invalid value: {0}", "ids"))
    if st not in ("", "yes", "pending"):
        return err(tr("Invalid value: {0}", "status"))
    src = d.get("source", "")
    if not isinstance(src, str) or len(src) > N.NWL_SOURCE_MAX or any(ord(ch) < 32 for ch in src):
        return err(tr("Invalid value: {0}", "source"))
    if st == "yes" and not src.strip():
        return err(tr("Please note where the consent comes from"))
    done, kept = [], 0
    rows = [need_contact(c, cid, write=True, uid=uid)[0] for cid in dict.fromkeys(ids)]  # every right first, then the writes
    for r in rows:
        cid = r["id"]
        if (r["nl_status"] or "") in N.NWL_BLOCKED:
            kept += 1
            continue
        N.nwl_set_status(c, cid, st, src.strip())
        done.append(cid)
    c.commit()
    return jsonify({"changed": done, "kept": kept})


# 2.141.0 C (#2143): consent import from a CSV (E-mail, Date, Source). Preview first (apply false), then apply true. Careful
# variant: only contacts already in the workspace's address books are touched, none is created; a consent that is already
# "yes" and an unsubscribe / bounce stay as they are; "" / "pending" become "yes" with the date and source of the file.
NWL_IMP_BYTES = 2 * 1024 * 1024
NWL_IMP_ROWS = 5000
NWL_IMP_SHOW = 100  # error lines in the answer
_IMP_HEAD = {"email": ("email", "e-mail", "e mail", "mail", "e-mail-adresse", "emailadresse", "email address"),
             "date": ("date", "datum", "consent date", "einwilligung", "zeitpunkt"),
             "source": ("source", "quelle", "herkunft", "origin")}
_IMP_REASON = {"email": N_("No valid e-mail address"), "date": N_("Date missing or invalid"), "future": N_("Date is in the future"),
               "dup": N_("Duplicate address in the file")}


def _imp_date(v):
    v = (v or "").strip()
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[T ].*)?", v) or None
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.fullmatch(r"(\d{1,2})\.(\d{1,2})\.(\d{4})(?:\s.*)?", v)
        if not m:
            return None
        d, mo, y = int(m[1]), int(m[2]), int(m[3])
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def _imp_rows(text):
    """[(line number, [cells])] without empty lines and the header, plus the column index of email / date / source."""
    first = next((ln for ln in text.splitlines() if ln.strip()), "")
    delim = max(",;\t", key=lambda d: first.count(d))
    rows = [(i, r) for i, r in enumerate(csv.reader(io.StringIO(text), delimiter=delim), 1) if any(x.strip() for x in r)]
    cols = {"email": 0, "date": 1, "source": 2}
    if rows and not any("@" in x for x in rows[0][1]):  # a header line: find the columns by name
        head = [x.strip().lower() for x in rows[0][1]]
        found = {k: next((i for i, h in enumerate(head) if h in names), None) for k, names in _IMP_HEAD.items()}
        if found["email"] is not None:
            cols = {k: v for k, v in found.items() if v is not None}
            rows = rows[1:]
    return rows, cols


@app.post("/api/newsletter/consent/import")
def nwl_consent_import():
    """{ws, csv: text, filename?, apply?} -- the consent import: columns E-mail, Date (YYYY-MM-DD or DD.MM.YYYY), Source (optional),
    header line optional, comma / semicolon / tab. apply false (default): only the preview {rows, valid, errors:[{line, email,
    reason}], errors_count, matched, will_change, kept, unmatched}; apply true stores the valid rows."""
    c = db()
    d = body()
    unknown = sorted(set(d) - {"ws", "csv", "filename", "apply"})
    if unknown:
        return err(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    _uid, _org, ws = _ws(c, d.get("ws"))
    text, fname, apply_ = d.get("csv"), d.get("filename") or "", bool(d.get("apply"))
    if not isinstance(text, str) or not text.strip() or not isinstance(fname, str):
        return err(tr("Invalid value: {0}", "csv"))
    if len(text.encode("utf-8")) > NWL_IMP_BYTES:
        return err(tr("The file is too large (at most {0} MB)", NWL_IMP_BYTES // (1024 * 1024)))
    try:
        rows, cols = _imp_rows(text.lstrip("\ufeff"))
    except csv.Error:  # 2.141.0 C (#2143, review): an oversized field / broken quoting = a clear error, not a 500
        return err(tr("Invalid value: {0}", "csv"))
    if len(rows) > NWL_IMP_ROWS:
        return err(tr("Too many rows (at most {0})", NWL_IMP_ROWS))
    fname = re.sub(r"[\x00-\x1f\x7f]", "", fname).strip()[-80:]
    by_mail = {}
    for r in N.nwl_contacts(c, ws):
        for e in N._jl(r["emails"]):
            v = str((e or {}).get("value") or "").strip().lower() if isinstance(e, dict) else ""
            if N.nwl_email_ok(v):
                by_mail.setdefault(v, []).append(r)
    today, seen = local_now().date(), set()
    errors, valid, will, kept, unmatched, todo = [], 0, 0, 0, 0, []
    from ..contacts.model import need_contact
    for line, cells in rows:
        cell = lambda k: (cells[cols[k]].strip() if k in cols and cols[k] < len(cells) else "")  # noqa: E731
        mail, day = cell("email").lower(), _imp_date(cell("date"))
        bad = ("email" if not N.nwl_email_ok(mail) else "date" if not day else "future" if day > today else "dup" if mail in seen else None)
        if bad:
            errors.append({"line": line, "email": mail[:254], "code": bad, "reason": tr(_IMP_REASON[bad])})
            continue
        seen.add(mail)
        valid += 1
        hits = by_mail.get(mail)
        if not hits:
            unmatched += 1
            continue
        src = (tr("Import: {0}", fname) if fname else tr("Import")) + (" · " + cell("source") if cell("source") else "")
        src = re.sub(r"[\x00-\x1f\x7f]", " ", src)[:N.NWL_SOURCE_MAX]
        at = iso(datetime(day.year, day.month, day.day, 12, 0, tzinfo=timezone.utc))
        for r in hits:
            if (r["nl_status"] or "") not in ("", "pending"):  # consented already, unsubscribed or bounced: untouched
                kept += 1
                continue
            try:
                need_contact(c, r["id"], write=True)
            except Denied:
                kept += 1
                continue
            will += 1
            todo.append((r["id"], src, at))
    if apply_:
        for cid, src, at in todo:
            N.nwl_set_status(c, cid, "yes", src, at)
        c.commit()
    return jsonify({"rows": len(rows), "valid": valid, "errors": errors[:NWL_IMP_SHOW], "errors_count": len(errors), "will_change": will,
                    "kept": kept, "unmatched": unmatched, "applied": len(todo) if apply_ else 0})
