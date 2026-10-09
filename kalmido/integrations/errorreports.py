"""Error reports (Sentry, GlitchTip ...) -> tickets."""
import hashlib
import hmac
import json
import re
import secrets
import threading
import time
from datetime import timedelta
from flask import g, jsonify, request

from ..core.config import app, PUBLIC_URL
from ..core.i18n import lang, tr
from ..core.db import body, bump, db, err, iso, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import is_project, list_people, MANAGE_ROLES, need_list, task_visible
from ..core.pages import valid_url
from ..tasks.validation import CONTENT_MAX, log_act, ticket_template
from ..collab.comments import collab_user, lang_of
from ..collab.news import news_add, notif_ok
from ..personal.timetrack import UnknownFields
from ..notify.push import push_prio, push_reachable
from ..notify.alerts import _env_int
from ..api.v1 import v1_args, v1_call, v1_json, v1_view
from ..agents.core import agent_ids, agent_tidy_events, is_agent
from ..integrations.git import _gd, git_need_manage, GIT_PROVIDERS, git_public


# ---------------------------------------------------------------- 2.18.0 (#408 "Software 2" F): error reports -> tickets
# A project list can take error reports (list dialog > Repository > "Error reports"; owner / list admins, never agents):
# POST /api/hooks/issues/<list id>/<token>. The token is shown once (on / rotate), stored only as its SHA-256; off deletes it.
# Body: a Sentry webhook (issue alert data.issue, event alert data.event, or the legacy plugin's flat payload) or generic
# JSON {title, body?, url?, fingerprint?, level?}. A report creates a bug ticket (ttype bug when the list has ticket types,
# the bug note template below the report details) in the list's first section, created by nobody (like Git activity).
# The same error again (fingerprint: the Sentry issue id, the given fingerprint, else a hash of title + culprit) while its
# ticket is still OPEN only counts: an activity line "happened again (N x)" (one line, updated) instead of a duplicate.
# At most ERR_NEW_PER_HOUR new tickets per list and hour (after that reports are only counted), ERR_REQ_PER_MIN requests
# per list and minute, ERR_MAX_BYTES per body. Report text is never trusted: plain text, Markdown-escaped, the body in a
# code block, links only http(s). New tickets go through the usual paths (outgoing webhooks, the tidy agent's event).
# Tasks by e-mail (2.17.0, #443) are the other inbound way for tickets.
ERR_MAX_BYTES = 256 * 1024
ERR_NEW_PER_HOUR = _env_int("KALMIDO_ERROR_REPORTS_PER_HOUR", 30)
ERR_REQ_PER_MIN = 120
ERR_BODY_MAX = 8000
ERR_LEVELS = ("fatal", "critical", "error", "warning", "warn", "info", "debug")
_ERR_RATE, _ERR_LOCK = {}, threading.Lock()


def err_md(s):
    """One line of report text as Markdown that shows exactly that text (no links, emphasis, HTML)."""
    s = re.sub(r"[\x00-\x1f\x7f]+", " ", str(s or "")).strip()
    # 2.18.0 review (R6): only what Markdown interprets in the middle of a line (the line starts with "**Error:**"), so
    # the text stays readable in the editor too ("\(reading ...\)" was noise); "http://" gets "\:" so it is no link
    s = re.sub(r"([\\`*_\[\]<>~&])", r"\\\1", s)
    return re.sub(r"(?i)\b(https?|mailto):", r"\1\\:", s)


def err_block(s):
    """A longer text (stack trace, message) as a fenced code block: never rendered as Markdown / HTML."""
    s = str(s or "").replace("\r\n", "\n").replace("\x00", "")[:ERR_BODY_MAX].strip("\n")
    if not s.strip():
        return ""
    fence = "`" * max(3, max((len(x) for x in re.findall(r"`+", s)), default=0) + 1)
    return f"{fence}text\n{s}\n{fence}"


def _es(v, n=300):
    return re.sub(r"\s+", " ", str(v)).strip()[:n] if isinstance(v, (str, int, float)) and not isinstance(v, bool) else ""


def err_parse(j):
    """A report body -> {source, title, culprit, url, level, fid, body} or None (nothing we understand)."""
    if not isinstance(j, dict):
        return None
    d = j.get("data") if isinstance(j.get("data"), dict) else {}
    if isinstance(d.get("issue"), dict):  # Sentry issue alert / issue webhook
        x = d["issue"]
        out = {"source": "sentry", "title": _es(x.get("title")), "culprit": _es(x.get("culprit")),
               "url": _es(x.get("permalink") or x.get("web_url"), 2000), "level": _es(x.get("level"), 20), "fid": _es(x.get("id"), 100),
               "body": "\n".join(v for v in (_es(_gd(x, "metadata", "type"), 200), _es(_gd(x, "metadata", "value"), 2000)) if v)}
    elif isinstance(d.get("event"), dict):  # Sentry event alert
        x = d["event"]
        out = {"source": "sentry", "title": _es(x.get("title") or x.get("message")), "culprit": _es(x.get("culprit")),
               "url": _es(x.get("web_url"), 2000), "level": _es(x.get("level"), 20), "fid": _es(x.get("issue_id"), 100),
               "body": str(x.get("message") or "") if isinstance(x.get("message"), str) else ""}
    elif "project_name" in j or ("culprit" in j and "level" in j and "url" in j):  # Sentry's legacy webhook plugin
        out = {"source": "sentry", "title": _es(j.get("message") or _gd(j, "event", "title")), "culprit": _es(j.get("culprit")),
               "url": _es(j.get("url"), 2000), "level": _es(j.get("level"), 20), "fid": _es(j.get("id"), 100),
               "body": str(j.get("message") or "") if isinstance(j.get("message"), str) else ""}
    elif isinstance(j.get("title"), str) and j["title"].strip():  # generic
        out = {"source": "generic", "title": _es(j["title"]), "culprit": _es(j.get("culprit")), "url": _es(j.get("url"), 2000),
               "level": _es(j.get("level"), 20), "fid": _es(j.get("fingerprint"), 200),
               "body": j.get("body") if isinstance(j.get("body"), str) else ""}
    else:
        return None
    if not out["title"]:
        return None
    out["level"] = out["level"].lower() if out["level"].lower() in ERR_LEVELS else ""
    out["url"] = out["url"] if valid_url(out["url"]) else ""
    out["fp"] = (("sentry:" if out["source"] == "sentry" else "fp:") + out["fid"]) if out["fid"] else \
        "h:" + hashlib.sha256((out["title"] + "\n" + out["culprit"]).encode()).hexdigest()[:32]
    return out


def err_content(c, lid, rep, lg):
    lines = [f"**{err_md(tr('Error report', lg=lg))}** · {'Sentry' if rep['source'] == 'sentry' else err_md(tr('webhook', lg=lg))}"
             + (f" · {rep['level']}" if rep["level"] else ""), "",
             f"**{err_md(tr('Error', lg=lg))}:** {err_md(rep['title'])}"]
    if rep["culprit"]:
        lines.append(f"**{err_md(tr('Where', lg=lg))}:** {err_md(rep['culprit'])}")
    if rep["url"]:
        lines.append(f"**{err_md(tr('Link', lg=lg))}:** {rep['url']}")
    blk = err_block(rep["body"])
    tpl = ticket_template(c, lid, "bug")
    return "\n".join(lines) + (f"\n\n{blk}" if blk else "") + (f"\n\n{tpl}" if tpl else "")


def err_rate_ok(lid):
    now = time.time()
    with _ERR_LOCK:
        lst = [t for t in _ERR_RATE.get(lid, []) if t > now - 60]
        if len(lst) >= ERR_REQ_PER_MIN:
            _ERR_RATE[lid] = lst
            return False
        lst.append(now)
        _ERR_RATE[lid] = lst
        if len(_ERR_RATE) > 5000:
            _ERR_RATE.clear()
    return True


@app.post("/api/hooks/issues/<int:lid>/<token>")
def errhook_in(lid, token):
    """Inbound error report (Sentry or generic JSON) -> a bug ticket, or a count on the open one of the same error."""
    c = db()
    r = c.execute("SELECT h.*, l.owner_id, l.tickets, l.archived FROM issue_hooks h JOIN lists l ON l.id=h.list_id WHERE h.list_id=?",
                  (lid,)).fetchone()
    if not r or len(token) > 200 or not hmac.compare_digest(r["token_hash"], hashlib.sha256(token.encode()).hexdigest()):
        return err(tr("unknown"), 404)
    if (request.content_length or 0) > ERR_MAX_BYTES:
        return err(tr("The report is too large (at most {0} KB)", ERR_MAX_BYTES // 1024), 413)
    raw = request.get_data(cache=False) or b""
    if len(raw) > ERR_MAX_BYTES:
        return err(tr("The report is too large (at most {0} KB)", ERR_MAX_BYTES // 1024), 413)
    if not err_rate_ok(lid):
        return err(tr("Too many attempts, please wait a few minutes"), 429)
    try:
        rep = err_parse(json.loads(raw.decode("utf-8") or "null"))
    except (ValueError, UnicodeDecodeError):
        rep = None
    if not rep:
        return err(tr("Invalid value: {0}", "body"))
    now = iso(now_utc())
    c.execute("UPDATE issue_hooks SET last_at=?, received=received+1 WHERE list_id=?", (now, lid))
    old = c.execute("SELECT * FROM issue_reports WHERE list_id=? AND fp=?", (lid, rep["fp"])).fetchone()
    t = c.execute("SELECT id, status, deleted_at, list_id FROM tasks WHERE id=?", (old["task_id"],)).fetchone() \
        if old and old["task_id"] else None
    if t and t["status"] == 0 and not t["deleted_at"] and t["list_id"] == lid:  # the same error, its ticket still open
        n = old["count"] + 1
        c.execute("UPDATE issue_reports SET count=?, last_at=? WHERE list_id=? AND fp=?", (n, now, lid, rep["fp"]))
        data = json.dumps({"n": n, "level": rep["level"], "url": rep["url"]}, ensure_ascii=False)
        last = c.execute("SELECT id, kind FROM activity WHERE task_id=? ORDER BY id DESC LIMIT 1", (t["id"],)).fetchone()
        if last and last["kind"] == "err_again":  # one line that counts up, never a flood of lines
            c.execute("UPDATE activity SET data=?, created_at=? WHERE id=?", (data, iso_ms(now_utc()), last["id"]))
        else:
            c.execute("INSERT INTO activity(task_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
                      (t["id"], None, "err_again", data, iso_ms(now_utc())))
        c.execute("UPDATE tasks SET updated_at=? WHERE id=?", (now, t["id"]))
        bump(c)
        c.commit()
        return jsonify(ok=True, task_id=t["id"], duplicate=True, count=n)
    hour = iso(now_utc() - timedelta(hours=1))
    # tickets made from reports in the last hour (a fingerprint can have made several, one after the other was closed)
    made = c.execute("""SELECT COUNT(*) FROM tasks t WHERE t.list_id=? AND t.created_at>? AND t.created_by IS NULL AND EXISTS
                        (SELECT 1 FROM activity a WHERE a.task_id=t.id AND a.kind='created' AND a.data LIKE '%"report":%')""",
                     (lid, hour)).fetchone()[0]
    if made >= ERR_NEW_PER_HOUR or r["archived"]:  # only counted
        c.execute("""INSERT INTO issue_reports(list_id,fp,task_id,count,first_at,last_at) VALUES(?,?,NULL,1,?,?)
                     ON CONFLICT(list_id,fp) DO UPDATE SET count=count+1, last_at=excluded.last_at""", (lid, rep["fp"], now, now))
        c.commit()
        return jsonify(ok=True, limited=True), 202
    lg = lang(c, r["owner_id"])
    sec = c.execute("SELECT id FROM sections WHERE list_id=? ORDER BY sort, id LIMIT 1", (lid,)).fetchone()
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    content = err_content(c, lid, rep, lg)[:CONTENT_MAX]
    tid = c.execute("""INSERT INTO tasks(list_id,section_id,title,content,sort,created_at,updated_at,created_by,url,ttype)
                       VALUES(?,?,?,?,?,?,?,NULL,?,?)""",
                    (lid, sec[0] if sec else None, rep["title"][:300], content, srt, now, now, rep["url"] or None,
                     "bug" if r["tickets"] else "")).lastrowid
    c.execute("""INSERT INTO issue_reports(list_id,fp,task_id,count,first_at,last_at) VALUES(?,?,?,1,?,?)
                 ON CONFLICT(list_id,fp) DO UPDATE SET task_id=excluded.task_id, count=1, first_at=excluded.first_at,
                 last_at=excluded.last_at""", (lid, rep["fp"], tid, now, now))
    g.user = {"id": None, "kind": "user", "username": "", "display_name": ""}  # nobody (system), like Git activity
    try:
        log_act(c, tid, "created", {"report": rep["source"]}, uid=None)
        agent_tidy_events(c, tid)
        from ..agents.core import agent_added_events
        agent_added_events(c, tid, source="errors")  # 2.23.0 (#795)
        if not old:  # 2.18.0 (owner decision): a NEW error -> exactly one News item + push; repeats, re-opened errors, counts stay quiet
            errreport_events(c, tid, lid, rep)
    finally:
        g.user = None
    bump(c)
    c.commit()
    return jsonify(ok=True, task_id=tid, created=True), 201


def errreport_events(c, tid, lid, rep):
    """2.18.0: a new error (first ticket of its fingerprint) -> event "errreport" for everyone who sees the whole list
    (people only): one News item and one push per the notification settings (row errreport, on by default; a muted list
    bell stops it). Reports after the hourly limit never get here (only counted), so they never push."""
    lst = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()
    ag = agent_ids(c)
    for uid in sorted(list_people(c, lid)):
        if uid in ag:
            continue
        s = collab_user(c, uid, lid)
        if not s or not task_visible(c, tid, uid, full=True):
            continue
        news_add(c, uid, "errreport", task_id=tid, data={"title": rep["title"][:200], "level": rep["level"]}, actor=None, s=s)
        if not notif_ok(c, uid, s, "errreport", "push", lid) or not push_reachable(c, uid, s):
            continue
        lg = lang_of(s)
        g.pushes.append((uid, tr("New error: {0}", rep["title"][:120], lg=lg), lst["name"] if lst else "", f"{PUBLIC_URL}/#t/{tid}",
                         push_prio(s)))


def errhook_public(c, lid, manage):
    r = c.execute("SELECT * FROM issue_hooks WHERE list_id=?", (lid,)).fetchone()
    d = {"on": bool(r), "last_at": r["last_at"] if r else None, "received": r["received"] if r else 0,
         "open": c.execute("""SELECT COUNT(*) FROM issue_reports e JOIN tasks t ON t.id=e.task_id WHERE e.list_id=?
                              AND t.status=0 AND t.deleted_at IS NULL""", (lid,)).fetchone()[0] if r else 0,
         "may": bool(manage), "per_hour": ERR_NEW_PER_HOUR}
    if r and manage:
        d["created_at"] = r["created_at"]
    return d


@app.get("/api/lists/<int:lid>/error-hook")
def errhook_get(lid):
    """Is the error-report webhook of a list on (never its URL: that is shown once)? Everyone who sees the list."""
    c = db()
    role = need_list(c, lid, write=False)
    return jsonify(errhook_public(c, lid, role in MANAGE_ROLES and not is_agent(g.user)))


@app.patch("/api/lists/<int:lid>/error-hook")
def errhook_set(lid):
    """{state: on | rotate | off} -- the list owner / a list admin (never an agent). on / rotate answer the URL once."""
    c = db()
    git_need_manage(c, lid)
    b = body()
    unknown = sorted(k for k in b if k != "state")
    if unknown:
        raise UnknownFields(unknown)
    st = b.get("state")
    if st not in ("on", "rotate", "off"):
        return err(tr("Invalid value: {0}", "state"))
    out = {}
    if st == "off":
        c.execute("DELETE FROM issue_hooks WHERE list_id=?", (lid,))
    else:
        if not is_project(c, lid):
            return err(tr("Make this list a project to connect a repository"), 409)
        tok = secrets.token_urlsafe(32)
        c.execute("""INSERT INTO issue_hooks(list_id,token_hash,created_by,created_at) VALUES(?,?,?,?)
                     ON CONFLICT(list_id) DO UPDATE SET token_hash=excluded.token_hash, created_by=excluded.created_by,
                     created_at=excluded.created_at""", (lid, hashlib.sha256(tok.encode()).hexdigest(), me(), iso(now_utc())))
        out["url"] = f"{PUBLIC_URL.rstrip('/')}/api/hooks/issues/{lid}/{tok}"  # the only time it is shown
    bump(c)
    c.commit()
    return jsonify({**errhook_public(c, lid, True), **out})


@app.get("/api/v1/lists/<int:lid>/error-hook")
@v1_view
def v1_errhook_get(lid):
    v1_args(())
    return jsonify(v1_call(errhook_get, lid))


@app.patch("/api/v1/lists/<int:lid>/error-hook")
@v1_view
def v1_errhook_set(lid):
    v1_args(())
    return jsonify(v1_call(errhook_set, lid, body=v1_json()))


def git_spec(paths, schemas, op, ok, errs, ref, pid, nul, page):
    """2.2.0 (#271 / #339) additions to the OpenAPI document."""
    repo = {"type": "object", "properties": {"id": {"type": "integer"}, "list_id": {"type": "integer"},
                                             "provider": {"type": "string", "enum": list(GIT_PROVIDERS)}, "base_url": {"type": "string"},
                                             "web_url": {"type": "string"}, "owner": {"type": "string"}, "repo": {"type": "string"},
                                             "full_name": {"type": "string"}, "default_branch": nul("string"),
                                             "status": {"type": "string", "enum": ["new", "ok", "error"]}, "error": {"type": "string"},
                                             "polled_at": nul("string"),
                                             "folder": nul("string", description="2.33.0 (#934): a repository of the list's folder "
                                                           "(it serves every project list in it): \"\" for agents and everyone but the folder's owner, who sees "
                                                           "the folder's path; null = the list's own")}}
    code = {"type": "object", "description": "Linked pull requests (state open / merged / closed, ci success / failure / pending / null) "
                                             "and commits (2.2.0)",
            "properties": {"prs": {"type": "array", "items": {"type": "object"}}, "commits": {"type": "array", "items": {"type": "object"}}}}
    schemas.update({"Repo": repo, "RepoPage": page("Repo"), "Code": code,
                    "MergeRequestInput": {"type": "object", "required": ["kind", "pr_url"], "additionalProperties": False, "properties": {
                        "kind": {"type": "string", "enum": ["merge_request"]}, "pr_url": {"type": "string"}, "summary": {"type": "string"}}}})
    schemas["Task"]["properties"]["code"] = ref("Code")
    schemas["Task"]["properties"]["repo"] = {"type": "object", "description": "GET /tasks/{id} in a list with a repository: provider, "
                                             "web_url, owner, repo, default_branch, a suggested branch, the linked code (2.2.0)"}
    schemas["List"]["properties"]["repos"] = {"type": "array", "items": {"type": "object"}}
    schemas["CommentInput"]["properties"]["suggestion"] = {"oneOf": [ref("TidyInput"), ref("MergeRequestInput")]}
    paths["/lists/{id}/repos"] = {"get": op("Repositories connected to a list (never a token); 2.33.0: without own ones the list's folder's "
                                            "repositories it uses (folder = the folder's path)", "Lists", ok(ref("RepoPage")) | errs("404"),
                                            [pid("id", "List id")])}
    # 2.18.0 (#408): the error-report webhook of a list (people with the owner / list admin role change it, never agents)
    hook = {"type": "object", "properties": {
        "on": {"type": "boolean"}, "last_at": nul("string"), "received": {"type": "integer"},
        "open": {"type": "integer", "description": "Open tickets created from reports"}, "may": {"type": "boolean"},
        "per_hour": {"type": "integer", "description": "New tickets per hour at most; later reports are only counted"},
        "url": {"type": "string", "description": "Only in the answer of state on / rotate: POST Sentry webhooks or "
                                                 "{title, body?, url?, fingerprint?, level?} to it"}}}
    schemas["ErrorHook"] = hook
    paths["/lists/{id}/error-hook"] = {
        "get": op("Is the error-report webhook of a list on (never its URL)", "Lists", ok(ref("ErrorHook")) | errs("404"), [pid("id", "List id")]),
        "patch": op("Turn the error-report webhook on, rotate its URL or turn it off (list owner / list admin, not agents)", "Lists",
                    ok(ref("ErrorHook")) | errs("400", "403", "404", "409"), [pid("id", "List id")], scope="write",
                    body={"type": "object", "required": ["state"], "additionalProperties": False,
                          "properties": {"state": {"type": "string", "enum": ["on", "rotate", "off"]}}})}


# ---- REST API
@app.get("/api/v1/lists/<int:lid>/repos")
@v1_view
def v1_git_list(lid):
    v1_args(())
    c = db()
    need_list(c, lid, write=False)
    from ..integrations.git import git_conns_of_list
    rows = git_conns_of_list(c, lid)  # 2.33.0 (#934): its own repositories, else the folder's (folder = its path)
    return jsonify(data=[git_public(c, r) for r in rows])
