"""2.48.0 (#1111): the routes of the documents area ("Dokumente", static/js/docs.js).

Rights are the file store's (kalmido/files/store.py): a document is visible when its file node is (fs_visible_sql), it
may be changed with 'edit' on it. Settings, rules, labels and the mail address of an organisation's workspace: its
admins; of a person's own workspace: that person. Agents use the API v1 (docs/v1.py), not these routes."""
import os
import re

from flask import g, jsonify, request

from ..core.config import app, ATT_DIR
from ..core.db import body, bump, db, err, iso, now_utc
from ..core.i18n import tr
from ..core.access import Denied, acx_of
from ..core.orgcrypt import OrgCryptError
from ..accounts.session import me
from ..files.store import fs_log_add, fs_role, fs_visible_ids, fs_visible_sql, fs_version_row, need_node
from . import store as S
from .ingest import docs_ingest, docs_kick
from .ocr import ocr_available

PAGE_MAX = 200
FEATURE_NAMES = ("sender", "type", "tags", "folder")
LEVEL_FEATURES = S.RU.FEATURES


def _now():
    return iso(now_utc())


def _no_agent():
    from ..agents.core import is_agent
    if is_agent(g.user):
        raise Denied(403)


def ws_param(c, raw, uid, manage=False):
    """'private' | 'org:<id>' (also a bare org id) -> (org_id or None, ws). An organisation needs membership (manage:
    admin)."""
    raw = str(raw or "private").strip()
    m = re.fullmatch(r"(?:org:)?(\d+)", raw)
    if not m:
        return None, S.doc_ws(None, uid)
    oid = int(m.group(1))
    if oid not in acx_of(c, uid).org_ids:
        raise Denied(404)
    if manage:
        from ..accounts.orgs import is_org_admin
        if not is_org_admin(c, uid, oid):
            raise Denied(403, tr("Only admins of the organisation can change this"))
    return oid, S.doc_ws(oid, uid)


def _ws_manage(c, ws, uid):
    oid = S.ws_org(ws)
    if oid:
        ws_param(c, oid, uid, manage=True)
    elif ws != S.doc_ws(None, uid):
        raise Denied(404)


# ---- serializing ------------------------------------------------------------------------------------------------------
def doc_json(c, m, node, full=False, role=None):
    ws = m["ws"]
    auto = S.meta_json(c, m, "auto", {})
    sug = S.meta_json(c, m, "suggest", {})
    sug.pop("_given", None)
    out_sug = {}
    for f, s in sug.items():
        if f == "tags":
            names = [S.label_name(c, ws, "tag", t) for t in s.get("value") or []]
            out_sug[f] = {"value": s.get("value"), "label": ", ".join(n for n in names if n), "by": s.get("by")}
        elif f == "folder":
            r = c.execute("SELECT name FROM fs_nodes WHERE id=?", (int(s["value"]),)).fetchone() if str(s.get("value", "")).isdigit() else None
            if r:
                out_sug[f] = {"value": s["value"], "label": r[0], "conf": s.get("conf"), "by": s.get("by")}
        else:
            name = S.label_name(c, ws, f, s.get("value"))
            if name:
                out_sug[f] = {"value": s["value"], "label": name, "conf": s.get("conf"), "by": s.get("by")}
    fl = S.folder_label(c, node)
    folder = None
    if fl:
        r = c.execute("SELECT id, name FROM fs_nodes WHERE id=?", (int(fl),)).fetchone()
        folder = {"id": r["id"], "name": r["name"]} if r else None
    err_key = m["error"] or ""
    d = {"id": m["node_id"], "name": node["name"], "mime": node["mime"], "size": node["size"], "org_id": node["org_id"], "ws": ws,
         "state": m["state"], "error": err_key, "error_text": tr(S.ERRORS[err_key]) if err_key in S.ERRORS else "",
         "method": m["method"], "pages": m["pages"], "date": m["doc_date"], "due": m["due_date"],
         "taken_at": m["taken_at"] or None,  # 2.61.0 B (#1819): the capture date of a photo (EXIF)
         "amount": S.doc_open(c, ws, "doc_meta.amount", m["amount"]) or None, "currency": m["currency"] or None,
         "sender": {"id": m["sender_id"], "name": S.label_name(c, ws, "sender", m["sender_id"])} if m["sender_id"] else None,
         "type": {"id": m["type_id"], "name": S.label_name(c, ws, "type", m["type_id"])} if m["type_id"] else None,
         "tags": S.node_tags(c, m["node_id"]), "folder": folder, "auto": auto, "suggest": out_sug, "review": bool(m["review"]),
         "thumb": bool(m["thumb"]), "task_id": m["task_id"], "asn": m["asn"], "source": m["source"], "created_at": node["created_at"],
         "updated_at": m["updated_at"], "parent_id": node["parent_id"]}
    if role:
        d["role"] = role
    if full:
        d["text"] = S.meta_text(c, m)
        from ..receipts.extracted import rx_doc_view
        d["extracted"] = rx_doc_view(c, m)  # 2.121.0 A (#2092): what the recognition read off a receipt (a suggestion)
    return d


def _doc(c, nid, write=False):
    """(meta, node) of a document the signed-in account may see (write: change); 404 when it is no document."""
    n = need_node(c, nid, write=write)
    m = S.meta_row(c, nid)
    if not m:
        raise Denied(404)
    return m, n


# ---- list + search ------------------------------------------------------------------------------------------------------
def doc_query(c, uid, args):
    """The documents account uid sees, filtered by args (ws, q, sender, type, tag, from, to, review, state) -> (rows, total,
    review count). Rows: doc_meta + node columns, newest document date first."""
    where, params = [f"n.id IN {fs_visible_sql(uid, c)}", "n.kind='file'"], []
    ws = str(args.get("ws") or "all")
    if ws == "private":
        where.append("n.org_id IS NULL")
    elif re.fullmatch(r"org:\d+", ws):
        where.append("n.org_id = ?")
        params.append(int(ws[4:]))
    base_where, base_params = list(where), list(params)
    for key, col in (("sender", "d.sender_id"), ("type", "d.type_id")):
        ids = [int(x) for x in str(args.get(key) or "").split(",") if x.strip().isdigit()][:50]
        if ids:
            where.append(f"{col} IN ({','.join('?' * len(ids))})")
            params += ids
    tags = [int(x) for x in str(args.get("tag") or "").split(",") if x.strip().isdigit()][:50]
    if tags:
        where.append(f"d.node_id IN (SELECT node_id FROM doc_node_tags WHERE tag_id IN ({','.join('?' * len(tags))}))")
        params += tags
    for key, op in (("from", ">="), ("to", "<=")):
        v = str(args.get(key) or "")[:10]
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
            where.append(f"COALESCE(d.doc_date, substr(n.created_at, 1, 10)) {op} ?")
            params.append(v)
    if str(args.get("review") or "") in ("1", "true"):
        where.append("d.review = 1")
    st = str(args.get("state") or "")
    if st in S.STATES:
        where.append("d.state = ?")
        params.append(st)
    sql = f"FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE {' AND '.join(where)}"
    q = str(args.get("q") or "").strip()[:200]
    if q:
        by_ws = {}
        for r in c.execute(f"SELECT d.node_id, d.ws {sql}", params):
            by_ws.setdefault(r[1], []).append(r[0])
        hit = S.search_ids(c, by_ws, q)
        for ws_, ids_ in by_ws.items():  # an archive serial number ("ASN00042", "42"): its document as well
            pre = re.escape(S.cfg_get(c, ws_)["asn_prefix"])
            n = re.fullmatch(rf"\s*(?:{pre})?\s*[:#-]?\s*0*(\d{{1,9}})\s*", q, re.I)
            if n:
                r_ = c.execute("SELECT node_id FROM doc_meta WHERE ws=? AND asn=?", (ws_, int(n.group(1)))).fetchone()
                if r_ and r_[0] in ids_:
                    hit = (hit or set()) | {r_[0]}
        if hit is not None:
            ids = sorted(hit)[:5000]
            sql += f" AND d.node_id IN ({','.join('?' * len(ids))})" if ids else " AND FALSE"
            params += ids
    total = c.execute(f"SELECT COUNT(*) {sql}", params).fetchone()[0]
    review = c.execute(f"SELECT COUNT(*) FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE {' AND '.join(base_where)} AND d.review=1",
                       base_params).fetchone()[0]
    try:
        limit = max(1, min(PAGE_MAX, int(args.get("limit") or 50)))
        offset = max(0, int(args.get("offset") or 0))
    except ValueError:
        limit, offset = 50, 0
    rows = c.execute(f"""SELECT d.*, n.id AS nid {sql} ORDER BY COALESCE(d.doc_date, substr(n.created_at, 1, 10)) DESC, n.id DESC
                         LIMIT {limit} OFFSET {offset}""", params).fetchall()
    return rows, total, review


def facets(c, uid, ws_filter):
    """Senders, types and tags of the documents uid can see (in the workspace filter), merged by name: [{name, ids}] each.
    Only labels used on visible documents: names from documents one cannot open never show up in the filters."""
    where, params = [f"n.id IN {fs_visible_sql(uid, c)}"], []
    if ws_filter == "private":
        where.append("n.org_id IS NULL")
    elif re.fullmatch(r"org:\d+", str(ws_filter or "")):
        where.append("n.org_id = ?")
        params.append(int(ws_filter[4:]))
    vis = f"SELECT d.node_id FROM doc_meta d JOIN fs_nodes n ON n.id=d.node_id WHERE {' AND '.join(where)}"
    used = {
        "sender": c.execute(f"SELECT DISTINCT sender_id, ws FROM doc_meta WHERE sender_id IS NOT NULL AND node_id IN ({vis})", params).fetchall(),
        "type": c.execute(f"SELECT DISTINCT type_id, ws FROM doc_meta WHERE type_id IS NOT NULL AND node_id IN ({vis})", params).fetchall(),
        "tag": c.execute(f"SELECT DISTINCT t.id, t.ws FROM doc_node_tags nt JOIN doc_tags t ON t.id=nt.tag_id WHERE nt.node_id IN ({vis})",
                         params).fetchall()}
    out = {}
    for kind, key in (("sender", "senders"), ("type", "types"), ("tag", "tags")):
        merged = {}
        for lid, ws in used[kind]:
            name = S.label_name(c, ws, kind, lid)
            if name:
                merged.setdefault(name.lower(), {"name": name, "ids": []})["ids"].append(lid)
        out[key] = sorted(merged.values(), key=lambda v: (v["name"] or "").lower())
    return out


@app.get("/api/docs")
def docs_list():
    """Documents I can see: ?ws=all|private|org:<id>&q=&sender=&type=&tag=&from=&to=&review=1&state=&limit=&offset=."""
    c = db()
    uid = me()
    rows, total, review = doc_query(c, uid, request.args)
    out = []
    for r in rows:
        node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (r["node_id"],)).fetchone()
        out.append(doc_json(c, r, node))
    waiting = c.execute(f"SELECT COUNT(*) FROM doc_meta d WHERE d.state IN ('wait','run') AND d.node_id IN {fs_visible_sql(uid, c)}").fetchone()[0]
    res = {"docs": out, "total": total, "review": review, "waiting": waiting}
    if request.args.get("facets") != "0":
        res["facets"] = facets(c, uid, request.args.get("ws"))
    return jsonify(res)


@app.post("/api/docs")
def docs_upload():
    """Multipart files (field "files", several) -> documents in the workspace ws (form field: private | org:<id>)."""
    from ..admin.hosting import QuotaExceeded
    c = db()
    uid = me()
    _no_agent()
    org, _ws = ws_param(c, request.form.get("ws"), uid)
    files = request.files.getlist("files") or request.files.getlist("file")
    if not files:
        return err(tr("No file"))
    ids, errors = [], []
    from ..files.upsafe import h6d_read
    for f in files[:50]:
        data = h6d_read(f)  # 2.86.0 (N22): at most MAX_FILE_MB + 1 bytes in memory (refused in fs_put)
        try:
            with c.savepoint():
                nid = docs_ingest(c, uid, org, f.filename or "document", data, f.mimetype, "share" if request.form.get("source") == "share" else "upload")
                fs_log_add(c, nid, "upload")
            ids.append(nid)
        except QuotaExceeded:
            errors.append(tr("{0}: no space left in your storage", f.filename or ""))
        except ValueError as e:
            errors.append(str(e))
    bump(c)
    c.commit()
    docs_kick()
    return jsonify(ids=ids, errors=errors), 201 if ids else 400


@app.get("/api/docs/<int:nid>")
def docs_get(nid):
    c = db()
    m, n = _doc(c, nid)
    fs_log_add(c, nid, "meta")
    return jsonify(doc_json(c, m, n, full=True, role=n["role"]))


def _feature_value(c, ws, node, f, v, uid):
    """A value from the client -> the stored form (label id / folder id text / tag ids). Names make new labels."""
    if f in ("sender", "type"):
        if v in (None, ""):
            return None
        if isinstance(v, int) and not isinstance(v, bool):
            if not S.label_ok(c, ws, f, v):
                raise Denied(404)
            return v
        return S.label_id(c, ws, f, str(v))
    if f == "tags":
        out = []
        for t in (v or [])[:30]:
            if isinstance(t, int) and not isinstance(t, bool):
                if S.label_ok(c, ws, "tag", t):
                    out.append(t)
            elif str(t).strip():
                out.append(S.label_id(c, ws, "tag", str(t)))
        return [t for t in out if t]
    if f == "folder":
        if v in (None, ""):
            return ""
        if isinstance(v, int) and not isinstance(v, bool):
            # 2.48.0 review: only a folder the person sees (a member of an organisation: shared folders)
            return str(v) if S.folder_ok(c, node, v) and fs_role(c, v, uid) else None
        root = S.docs_root(c, node)
        fid = S.folder_by_name(c, node, uid, str(v), create=bool(root) and fs_role(c, root, uid) in ("owner", "edit"))
        fid = fid if fid and fs_role(c, fid, uid) else None
        return str(fid) if fid else None
    return None


def doc_update(c, nid, d, uid, by=None):
    """Apply a change {name, date, due, amount, currency, sender, type, tags, folder} to document nid (rights checked by the
    caller). by=None: a person -- the changed features lose "automatic" and the models learn them; by="agent": the
    features are marked "agent" (or land as suggestions when the workspace has the feature on level agent)."""
    m = S.meta_row(c, nid)
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    ws = m["ws"]
    sets = {}
    for k, col in (("date", "doc_date"), ("due", "due_date")):
        if k in d:
            v = str(d[k] or "")[:10]
            if v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v):
                return err(tr("Invalid value: {0}", k))
            sets[col] = v or None
    if "amount" in d:
        v = str(d["amount"] or "").strip().replace(",", ".")[:20]
        if v and not re.fullmatch(r"-?\d{1,12}(\.\d{1,2})?", v):
            return err(tr("Invalid value: {0}", "amount"))
        sets["amount"] = S.doc_seal(c, ws, "doc_meta.amount", v)
    if "asn" in d and by is None:
        v = d["asn"]
        if v == "next":
            v = S.asn_next(c, ws)
        if v in (None, ""):
            sets["asn"] = None
        elif isinstance(v, int) and not isinstance(v, bool) and 0 < v < 10**9:
            if S.asn_taken(c, ws, v, nid):
                return err(tr("This archive number is already used"), 409)
            sets["asn"] = v
        else:
            return err(tr("Invalid value: {0}", "asn"))
    if "currency" in d:
        sets["currency"] = re.sub(r"[^A-Za-z€$£]", "", str(d["currency"] or ""))[:8].upper()
    if "text" in d and by == "agent" and not S.meta_text(c, m).strip():
        sets["text"] = S.doc_seal(c, ws, "doc_meta.text", str(d["text"] or "")[:200_000])
    if "name" in d and by is None:
        name = str(d["name"] or "").strip()
        if name:
            from ..files.store import _free_name, safe_fs_name
            c.execute("UPDATE fs_nodes SET name=?, updated_at=? WHERE id=?",
                      (_free_name(c, node["parent_id"], node["owner_id"], node["org_id"], safe_fs_name(name), skip=nid), _now(), nid))
    if sets:
        c.execute(f"UPDATE doc_meta SET {', '.join(k + '=?' for k in sets)}, updated_at=? WHERE node_id=?", (*sets.values(), _now(), nid))
        if "asn" in sets:
            auto = S.meta_json(c, m, "auto", {})
            auto.pop("asn", None)
            S.meta_set_json(c, nid, ws, "auto", auto)
            _reindex(c, nid)
        if "doc_date" in sets and by is None:  # 2.61.0 B (#1819): a date set by hand is no longer "from the photo"
            m = S.meta_row(c, nid)
            auto = S.meta_json(c, m, "auto", {})
            if auto.pop("date", None):
                S.meta_set_json(c, nid, ws, "auto", auto)
        m = S.meta_row(c, nid)  # the feature part below reads auto / suggest as they are now
    changed = [f for f in FEATURE_NAMES if f in d]
    if not changed:
        return None
    lv = S.cfg_get(c, ws)["levels"]
    vals = {}
    for f in changed:
        v = _feature_value(c, ws, node, f, d[f], uid)
        if v is None and f == "folder":
            return err(tr("Invalid value: {0}", f))
        vals[f] = v
    auto = S.meta_json(c, m, "auto", {})
    sug = S.meta_json(c, m, "suggest", {})
    if by == "agent":
        direct = {f: v for f, v in vals.items() if lv.get(f) != "agent"}
        for f, v in vals.items():
            if lv.get(f) == "agent":
                sug[f] = {"value": v, "by": "agent"}
        S.apply_values(c, m, node, direct, {f: ({t: "agent" for t in v} if f == "tags" else "agent") for f, v in direct.items()}, "agent")
        auto.update({f: "agent" for f in direct})
        S.meta_set_json(c, nid, ws, "suggest", sug)
        S.meta_set_json(c, nid, ws, "auto", auto)
        if any(lv.get(f) == "agent" for f in vals):
            c.execute("UPDATE doc_meta SET review=1 WHERE node_id=?", (nid,))
        return None
    S.apply_values(c, m, node, vals, {})
    for f in changed:
        auto.pop(f, None)
        sug.pop(f, None)
    S.meta_set_json(c, nid, ws, "auto", auto)
    S.meta_set_json(c, nid, ws, "suggest", sug)
    S.train(c, nid, changed)
    _reindex(c, nid)
    return None


def _reindex(c, nid):
    m = S.meta_row(c, nid)
    node = c.execute("SELECT name FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    S.doc_index(c, nid, m["ws"], S.index_text(c, dict(m), node["name"], S.meta_text(c, m)))


@app.patch("/api/docs/<int:nid>")
def docs_patch(nid):
    """{name?, date?, due?, amount?, currency?, sender? (name | id | null), type?, tags? [names | ids], folder? (name | id | "")}"""
    c = db()
    _no_agent()
    _doc(c, nid, write=True)
    d = body()
    e = doc_update(c, nid, d, me())
    if e:
        return e
    fs_log_add(c, nid, "edit")
    bump(c)
    c.commit()
    m, n = _doc(c, nid)
    return jsonify(doc_json(c, m, n, full=True, role=n["role"]))


@app.post("/api/docs/<int:nid>/accept")
def docs_accept(nid):
    """{features?: [..]} -- take the suggestions (all or these), they count as a confirmation (the models learn them)."""
    c = db()
    _no_agent()
    m, n = _doc(c, nid, write=True)
    sug = S.meta_json(c, m, "suggest", {})
    sug.pop("_given", None)
    want = body().get("features") or list(sug)
    vals = {f: sug[f]["value"] for f in want if f in sug and f in FEATURE_NAMES}
    if "tags" in vals:
        vals["tags"] = sorted(set([t["id"] for t in S.node_tags(c, nid)] + list(vals["tags"])))
    e = doc_update(c, nid, vals, me()) if vals else None
    if e:
        return e
    m = S.meta_row(c, nid)
    left = {k: v for k, v in S.meta_json(c, m, "suggest", {}).items() if k != "_given"}
    if not left:
        c.execute("UPDATE doc_meta SET review=0 WHERE node_id=?", (nid,))
    bump(c)
    c.commit()
    m, n = _doc(c, nid)
    return jsonify(doc_json(c, m, n, full=True, role=n["role"]))


@app.post("/api/docs/<int:nid>/review")
def docs_review(nid):
    """{done: true} -- checked: out of "To review"; the current values count as confirmed (the models learn them),
    the open suggestions are dropped. {done: false}: back into "To review" (the undo)."""
    c = db()
    _no_agent()
    m, n = _doc(c, nid, write=True)
    done = body().get("done", True) is not False
    if done:
        S.meta_set_json(c, nid, m["ws"], "suggest", {})
        c.execute("UPDATE doc_meta SET review=0, updated_at=? WHERE node_id=?", (_now(), nid))
        S.train(c, nid)
    else:
        c.execute("UPDATE doc_meta SET review=1, updated_at=? WHERE node_id=?", (_now(), nid))
    bump(c)
    c.commit()
    m, n = _doc(c, nid)
    return jsonify(doc_json(c, m, n, role=n["role"]))


@app.post("/api/docs/<int:nid>/redo")
def docs_redo(nid):
    """Recognise again (text, date, amount; the sorting keeps what is set)."""
    c = db()
    _no_agent()
    _doc(c, nid, write=True)
    c.execute("UPDATE doc_meta SET state='wait', tries=0, error='', updated_at=? WHERE node_id=?", (_now(), nid))
    c.commit()
    docs_kick()
    m, n = _doc(c, nid)
    return jsonify(doc_json(c, m, n, role=n["role"]))


@app.get("/api/docs/<int:nid>/thumb")
def docs_thumb(nid):
    from flask import Response
    c = db()
    m, _n = _doc(c, nid)
    if not m["thumb"]:
        raise Denied(404)
    try:
        data = S.thumb_read(c, m["ws"], os.path.join(ATT_DIR, m["thumb"]))  # 2.48.0 review (L3): private ones sealed
    except (OSError, OrgCryptError):
        raise Denied(404) from None
    r = Response(data, mimetype="image/jpeg")
    r.headers["Cache-Control"] = "private, max-age=86400" if request.args.get("v") else "private, no-cache"
    return r


@app.get("/api/docs/<int:nid>/file")
def docs_file(nid):
    """The document's file (inline for images / PDF / text, ?dl=1: download)."""
    from ..tasks.attachments import send_stored
    c = db()
    _m, n = _doc(c, nid)
    v = fs_version_row(c, nid)
    if not v:
        raise Denied(404)
    from ..files.scan import sc_guard
    sc_guard(c, "fs", nid, v["no"])  # 2.61.0 (#1818): a version found infected later is locked
    fs_log_add(c, nid, "download" if request.args.get("dl") == "1" else "read")
    c.commit()
    return send_stored({"id": nid, "path": v["path"], "name": n["name"], "mime": v["mime"] or n["mime"], "size": v["size"]})


@app.post("/api/docs/<int:nid>/task")
def docs_task(nid):
    """A task in my inbox for the due date: title from type / sender, due = the due date, the document linked in the notes."""
    from ..core.pages import new_inbox_task
    c = db()
    _no_agent()
    m, n = _doc(c, nid, write=True)
    uid = me()
    sender = S.label_name(c, m["ws"], "sender", m["sender_id"])
    typ = S.label_name(c, m["ws"], "type", m["type_id"])
    title = " ".join(x for x in (typ or "", sender or "") if x).strip() or n["name"]
    title = tr("Pay: {0}", title) if m["amount"] else title
    amount = S.doc_open(c, m["ws"], "doc_meta.amount", m["amount"])
    lines = [f"[{n['name']}](#docs/{nid})"]
    if amount:
        lines.append(f"{tr('Amount')}: {amount} {m['currency'] or ''}".strip())
    tid = new_inbox_task(c, uid, title[:300], "\n".join(lines), None, None)
    if m["due_date"]:
        c.execute("UPDATE tasks SET due=? WHERE id=?", (m["due_date"], tid))
    c.execute("UPDATE doc_meta SET task_id=?, updated_at=? WHERE node_id=?", (tid, _now(), nid))
    bump(c)
    c.commit()
    return jsonify(task_id=tid, title=title), 201


@app.delete("/api/docs/<int:nid>/task")
def docs_task_unlink(nid):
    """The undo of "Create task": forget the link (the client deletes the task itself)."""
    c = db()
    _no_agent()
    _doc(c, nid, write=True)
    c.execute("UPDATE doc_meta SET task_id=NULL WHERE node_id=?", (nid,))
    c.commit()
    return jsonify(ok=True)


# ---- settings of a workspace: levels, rules, labels, mail address ------------------------------------------------------
def _settings_labels(c, ws, uid, can):
    """The senders / types / tags for the fields' suggestions: all of the workspace for who manages it, else only those
    on documents the person can see."""
    if can:
        return {"senders": S.labels(c, ws, "sender"), "types": S.labels(c, ws, "type"), "tags": S.labels(c, ws, "tag")}
    f = facets(c, uid, f"org:{S.ws_org(ws)}" if S.ws_org(ws) else "private")
    return {k: [{"id": x["ids"][0], "name": x["name"]} for x in f[k]] for k in ("senders", "types", "tags")}


def _settings_json(c, ws, uid):
    from ..integrations.mail import MAIL_IN_ON, mail_addr
    oid = S.ws_org(ws)
    can = True
    if oid:
        from ..accounts.orgs import is_org_admin
        can = is_org_admin(c, uid, oid)
    tok = c.execute("SELECT token FROM doc_mail WHERE user_id=? AND org_id IS NOT DISTINCT FROM ?", (uid, oid)).fetchone()
    root = S.root_id(c, ws)  # 2.48.0 review: the marked documents folder; only the folders uid can see (L4)
    vis = fs_visible_ids(c, uid) if root else set()
    folders = [{"id": x[0], "name": x[1]} for x in c.execute(
        "SELECT id, name FROM fs_nodes WHERE parent_id=? AND kind='folder' AND deleted_at IS NULL ORDER BY lower(name)", (root,))
        if x[0] in vis] if root else []
    cfg = S.cfg_get(c, ws)
    return {"ws": f"org:{oid}" if oid else "private", "can_manage": can, "levels": cfg["levels"], "inbox": cfg["inbox"],
            "rules": S.rules_get(c, ws) if can else [], **_settings_labels(c, ws, uid, can), "folders": [f for f in folders if f["name"].lower() != S.INBOX.lower()],
            "root_id": root, "ocr": ocr_available(), "asn_prefix": cfg["asn_prefix"], "asn_next": S.asn_next(c, ws), "mail": {"enabled": MAIL_IN_ON, "address": mail_addr(tok[0]) if (tok and MAIL_IN_ON) else ""}}


@app.get("/api/docs/settings")
def docs_settings():
    """?ws=private|org:<id> -- levels per feature, rules, senders / types / tags, folders, the mail address."""
    c = db()
    _no_agent()
    uid = me()
    _org, ws = ws_param(c, request.args.get("ws"), uid)
    return jsonify(_settings_json(c, ws, uid))


@app.put("/api/docs/settings")
def docs_settings_put():
    """{ws, levels?: {sender|type|tags|folder: rules|learn|agent|off}, inbox?: bool}"""
    c = db()
    _no_agent()
    uid = me()
    d = body()
    _org, ws = ws_param(c, d.get("ws"), uid, manage=True)
    try:
        S.cfg_set(c, ws, d)
    except ValueError:
        return err(tr("The prefix takes letters, digits and dashes (at most 10, a letter first)"))
    c.commit()
    return jsonify(_settings_json(c, ws, uid))


def _rule_save(c, ws, d, rid=None):
    try:
        r = S.RU.clean_rule(d)
    except S.RU.RuleError as e:
        why = str(e)
        msg = {"nested": tr("This pattern could take very long (nested repetition); please simplify it"),
               "backref": tr("Back references are not allowed in patterns"), "long": tr("The pattern is too long"),
               "invalid": tr("The pattern is not a valid regular expression"), "empty": tr("The condition is empty"),
               "nothing": tr("The rule does not set anything")}.get(why, tr("Invalid value: {0}", "rule"))
        return None, err(msg)
    data = S._jseal(c, ws, "doc_rules.data", r)
    if rid:
        c.execute("UPDATE doc_rules SET data=? WHERE id=? AND ws=?", (data, rid, ws))
        return rid, None
    from ..core.db import insert_id
    pos = (c.execute("SELECT COALESCE(MAX(pos), 0) FROM doc_rules WHERE ws=?", (ws,)).fetchone()[0] or 0) + 1
    return insert_id(c, "INSERT INTO doc_rules(org_id, ws, pos, data, created_by, created_at) VALUES(?,?,?,?,?,?)",
                     (S.ws_org(ws), ws, pos, data, me(), _now())), None


@app.post("/api/docs/rules")
def docs_rule_add():
    """{ws, kind: any|all|exact|regex|fuzzy, match, sender?, type?, tags?, folder?}"""
    c = db()
    _no_agent()
    uid = me()
    d = body()
    _org, ws = ws_param(c, d.get("ws"), uid, manage=True)
    rid, e = _rule_save(c, ws, d)
    if e:
        return e
    c.commit()
    return jsonify(id=rid, rules=S.rules_get(c, ws)), 201


def _rule_ws(c, rid):
    r = c.execute("SELECT ws FROM doc_rules WHERE id=?", (rid,)).fetchone()
    if not r:
        raise Denied(404)
    _ws_manage(c, r[0], me())
    return r[0]


@app.patch("/api/docs/rules/<int:rid>")
def docs_rule_edit(rid):
    c = db()
    _no_agent()
    ws = _rule_ws(c, rid)
    d = body()
    if "pos" in d and isinstance(d["pos"], (int, float)) and not isinstance(d["pos"], bool):
        c.execute("UPDATE doc_rules SET pos=? WHERE id=?", (int(d["pos"]), rid))
    if "match" in d:
        _rid, e = _rule_save(c, ws, d, rid)
        if e:
            return e
    c.commit()
    return jsonify(rules=S.rules_get(c, ws))


@app.delete("/api/docs/rules/<int:rid>")
def docs_rule_del(rid):
    c = db()
    _no_agent()
    ws = _rule_ws(c, rid)
    c.execute("DELETE FROM doc_rules WHERE id=?", (rid,))
    c.commit()
    return jsonify(rules=S.rules_get(c, ws))


@app.patch("/api/docs/labels/<kind>/<int:lid>")
def docs_label_rename(kind, lid):
    """{name} -- rename a sender / type / tag of a workspace."""
    c = db()
    _no_agent()
    if kind not in S.LABEL_KINDS:
        raise Denied(404)
    r = c.execute(f"SELECT ws FROM {S.LABEL_KINDS[kind]} WHERE id=?", (lid,)).fetchone()
    if not r:
        raise Denied(404)
    _ws_manage(c, r[0], me())
    name = re.sub(r"\s+", " ", str(body().get("name") or "")).strip()[:S.NAME_MAX]
    if not name:
        return err(tr("Name missing"))
    c.execute(f"UPDATE {S.LABEL_KINDS[kind]} SET name=? WHERE id=?", (S.doc_seal(c, r[0], "doc_senders.name", name) if kind == "sender" else name, lid))
    bump(c)
    c.commit()
    return jsonify(id=lid, name=name)


@app.delete("/api/docs/labels/<kind>/<int:lid>")
def docs_label_del(kind, lid):
    """Delete a sender / type / tag (documents keep everything else)."""
    c = db()
    _no_agent()
    if kind not in S.LABEL_KINDS:
        raise Denied(404)
    r = c.execute(f"SELECT ws FROM {S.LABEL_KINDS[kind]} WHERE id=?", (lid,)).fetchone()
    if not r:
        raise Denied(404)
    _ws_manage(c, r[0], me())
    name = S.label_name(c, r[0], kind, lid)
    if kind != "tag":
        ids = [x[0] for x in c.execute(f"SELECT node_id FROM doc_meta WHERE {kind}_id=? AND ws=?", (lid, r[0]))]
        c.execute(f"UPDATE doc_meta SET {kind}_id=NULL WHERE {kind}_id=? AND ws=?", (lid, r[0]))
    else:
        ids = [x[0] for x in c.execute("SELECT node_id FROM doc_node_tags WHERE tag_id=?", (lid,))]
    c.execute(f"DELETE FROM {S.LABEL_KINDS[kind]} WHERE id=?", (lid,))
    bump(c)
    c.commit()
    return jsonify(ok=True, name=name, ids=ids)  # the undo sends both back (POST /api/docs/labels/<kind>)


@app.post("/api/docs/labels/<kind>")
def docs_label_restore(kind):
    """{ws, name, ids} -- the undo of deleting a sender / type / tag: the label again, on the documents (ids) of the workspace
    that have no other value meanwhile (not a correction: the models are left as they are)."""
    c = db()
    _no_agent()
    if kind not in S.LABEL_KINDS:
        raise Denied(404)
    d = body()
    _org, ws = ws_param(c, d.get("ws"), me(), manage=True)
    lid = S.label_id(c, ws, kind, d.get("name"))
    if not lid:
        return err(tr("Name missing"))
    ids = [int(x) for x in (d.get("ids") or [])[:5000] if isinstance(x, int) and not isinstance(x, bool)]
    for i in range(0, len(ids), 1000):
        part = ids[i:i + 1000]
        q = ",".join("?" * len(part))
        if kind == "tag":
            for (nid,) in c.execute(f"SELECT node_id FROM doc_meta WHERE ws=? AND node_id IN ({q})", (ws, *part)).fetchall():
                c.execute("INSERT INTO doc_node_tags(node_id, tag_id) VALUES(?,?) ON CONFLICT DO NOTHING", (nid, lid))
        else:
            c.execute(f"UPDATE doc_meta SET {kind}_id=? WHERE ws=? AND {kind}_id IS NULL AND node_id IN ({q})", (lid, ws, *part))
    bump(c)
    c.commit()
    return jsonify(id=lid, name=d.get("name")), 201


@app.post("/api/docs/mail")
def docs_mail_new():
    """{ws} -- a new forwarding address for documents (the old one stops working)."""
    import secrets
    from ..integrations.mail import MAIL_IN_ON, mail_addr
    c = db()
    _no_agent()
    uid = me()
    if not MAIL_IN_ON:
        return err(tr("E-mail to tasks is not set up on this server"), 409)
    org, _ws = ws_param(c, body().get("ws"), uid)
    tok = "d" + secrets.token_urlsafe(14).replace("-", "x").replace("_", "y")
    c.execute("DELETE FROM doc_mail WHERE user_id=? AND org_id IS NOT DISTINCT FROM ?", (uid, org))
    c.execute("INSERT INTO doc_mail(token, user_id, org_id, created_at) VALUES(?,?,?,?)", (tok, uid, org, _now()))
    c.commit()
    return jsonify(address=mail_addr(tok))


@app.delete("/api/docs/mail")
def docs_mail_del():
    """?ws= -- the forwarding address stops working."""
    c = db()
    _no_agent()
    uid = me()
    org, _ws = ws_param(c, request.args.get("ws"), uid)
    c.execute("DELETE FROM doc_mail WHERE user_id=? AND org_id IS NOT DISTINCT FROM ?", (uid, org))
    c.commit()
    return jsonify(ok=True)
