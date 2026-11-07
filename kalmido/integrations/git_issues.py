"""2.394.0 B (#3377): the issues of a repository connection (GitHub, GitLab) -- fetching + one import into its project.

A small provider layer the two-way sync (part C) builds on: gis_fetch_issues / gis_fetch_comments only READ (no database, no
side effects besides the rate-limit state in k, see git_http) and hand back neutral dicts (gis_norm_issue / gis_norm_comment).
Only github and gitlab have issues here (GIS_PROVIDERS); Gitea / Bitbucket get a friendly "not for this provider yet".

POST /api/repos/<id>/issues/import {dry_run?, completed?: import | skip}: the project's owner / admins (people, never agents),
only a project's own repository (not a folder's). It builds an import plan (importers.imp_plan) and lets imp_run write it, so
the preview (dry run), the import record, the import history and the undo within 24 hours are those of every other import
(source "github" / "gitlab", names in importers.IMPORT_SOURCES_CONN). Per issue: title, text as the notes, closed = done
(closed_at), labels = tags, the first assignee an exact member of the project (imp_user_match: login = user name or display
name) else its login as text, the comments as comments of the importing person with an author line ("@login on <date>:"),
the issue's web address as the task's link, and one git_issue_links row. An issue linked already (by anyone) is not taken
again ("already" in the report). The access token comes from the connection, never into an answer or a log."""
import json
import time
import urllib.parse
from datetime import datetime, timezone
from flask import g, jsonify

from ..core.config import app
from ..core.i18n import lang, N_, tr
from ..core.db import body, db, err, iso, now_utc
from ..core.pg import insert_id, write_lock
from ..core.errors import BadInput
from ..core.errors import reject_unknown
from ..core.access import Denied
from ..accounts.session import me
from ..api.common import hit_limit
from ..calendars.subscriptions import CalError
from ..collab.liste2e import le2a_gen_refuse
from ..collab.reactions import clean_ltag_name, set_ltags
from .git import git_ctx, git_err_text, git_http, git_need_conn, GitRate, GIT_ERR
from .gitfolder import gf_row
from .importers import (imp_line, imp_list, imp_plan, imp_run, imp_task, imp_addnote, imp_textblock, imp_warn, IMPORT_RATE,
                        IMPORT_SOURCES_CONN)

GIS_PROVIDERS = ("github", "gitlab")
GIS_MAX = 1000          # issues per import (the newest ones)
GIS_PAGE = 100          # items per request (both providers' maximum)
GIS_COMMENTS_MAX = 100  # comments per issue (one page)
GIS_PAGES_MAX = 30      # pages per listing: GitHub mixes pull requests into its issue list
GIS_IN = ("dry_run", "completed")
GIS_DEADLINE = 150      # 2.394.0 C (#3377 review of B): seconds for all requests of one import (monotonic)
GIS_COMMENT_ISSUES = 200  # issues whose comments one import reads (the rest: a warning)


def _gis_ts(v):
    """A provider's time stamp -> the app's iso() text (UTC, whole seconds); None if missing / unreadable."""
    s = str(v or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return iso(dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc))


def _gis_s(v, n=300):
    return str(v if v is not None else "")[:n]


def gis_api(k, what, no=None, page=1, since=None):
    """The API path of one request: what = issues (the list, newest first; since = updated since, then by update) | comments
    (of issue no, oldest first). k = git_ctx(...)."""
    p, gh = k["path"], k["provider"] == "github"
    if what == "comments":
        return (f"{p}/issues/{int(no)}/comments?per_page={GIS_PAGE}&page={int(page)}" if gh else
                f"{p}/issues/{int(no)}/notes?sort=asc&order_by=created_at&per_page={GIS_PAGE}&page={int(page)}")
    if gh:
        q = f"state=all&per_page={GIS_PAGE}&page={int(page)}&direction=desc&sort=" + ("updated&since=" + urllib.parse.quote(since, safe="") if since else "created")
        return f"{p}/issues?{q}"
    q = f"scope=all&per_page={GIS_PAGE}&page={int(page)}&sort=desc&order_by=" + ("updated_at&updated_after=" + urllib.parse.quote(since, safe="") if since else "created_at")
    return f"{p}/issues?{q}"


def _gis_get(k, path):
    """One page (a JSON list). GitRate when the provider's limit runs low (GIT_RATE_FLOOR, like the poller)."""
    if k.get("low"):
        raise GitRate(k["low"])
    _, _, j = git_http(k, path)
    if not isinstance(j, list):
        raise CalError("parse")
    return j


def gis_norm_issue(prov, j):
    """A provider's issue -> {no, title, body, state open | closed, labels[], assignees[], author, url, created_at, updated_at,
    closed_at, comments (count), pr (GitHub: a pull request in the issue list)}; None for what is not an issue."""
    if not isinstance(j, dict):
        return None
    gh = prov == "github"
    no = j.get("number") if gh else j.get("iid")
    if not isinstance(no, int) or isinstance(no, bool) or no <= 0:
        return None
    labels = [_gis_s(x.get("name") if isinstance(x, dict) else x, 100) for x in (j.get("labels") or []) if x]
    who = j.get("assignees") or ([j["assignee"]] if isinstance(j.get("assignee"), dict) else [])
    login = (lambda u: _gis_s(u.get("login") if gh else u.get("username"), 100) if isinstance(u, dict) else "")
    st, cnt = str(j.get("state") or "").lower(), j.get("comments") if gh else j.get("user_notes_count")
    return {"no": no, "title": _gis_s(j.get("title"), 1000), "body": _gis_s(j.get("body") if gh else j.get("description"), 200000),
            "state": "closed" if st == "closed" else "open", "labels": [x for x in labels if x],
            "assignees": [x for x in (login(u) for u in who) if x], "author": login(j.get("user") if gh else j.get("author")),
            "url": _gis_s(j.get("html_url") if gh else j.get("web_url"), 500), "created_at": _gis_ts(j.get("created_at")),
            "updated_at": _gis_ts(j.get("updated_at")), "closed_at": _gis_ts(j.get("closed_at")),
            "comments": cnt if isinstance(cnt, int) and not isinstance(cnt, bool) and cnt > 0 else 0,
            "pr": bool(gh and j.get("pull_request"))}


def gis_norm_comment(prov, j):
    """A provider's comment (GitLab: note) -> {id, author, body, created_at, updated_at}; None for GitLab's system notes."""
    if not isinstance(j, dict) or (prov == "gitlab" and j.get("system")):
        return None
    u = j.get("user") if prov == "github" else j.get("author")
    return {"id": j.get("id"), "author": _gis_s((u or {}).get("login" if prov == "github" else "username"), 100) if isinstance(u, dict) else "",
            "body": _gis_s(j.get("body"), 100000), "created_at": _gis_ts(j.get("created_at")), "updated_at": _gis_ts(j.get("updated_at"))}


def gis_fetch_issues(k, since=None, cap=GIS_MAX, deadline=None):
    """The newest `cap` issues of the repository (pull requests skipped) -> (issues, prs skipped, more there). Read only.
    2.394.0 C (#3377 review of B): past the deadline (time.monotonic) or at the rate limit after the first page it stops with
    what it has (more = True); before the first page GitRate / CalError pass through."""
    out, prs, more = [], 0, False
    for page in range(1, GIS_PAGES_MAX + 1):
        if page > 1 and deadline is not None and time.monotonic() > deadline:
            more = True
            break
        try:
            rows = _gis_get(k, gis_api(k, "issues", page=page, since=since))
        except GitRate:
            if page == 1:
                raise
            more = True
            break
        for x in rows:
            n = gis_norm_issue(k["provider"], x)
            if not n:
                continue
            if n["pr"]:
                prs += 1
            elif len(out) < cap:
                out.append(n)
            else:
                more = True
        if len(rows) < GIS_PAGE or more:
            break
    else:
        more = True
    return out, prs, more


def gis_fetch_comments(k, no):
    """The comments of issue no, oldest first (at most GIS_COMMENTS_MAX) -> (comments, more there). Read only."""
    rows = _gis_get(k, gis_api(k, "comments", no=no))
    out = [n for n in (gis_norm_comment(k["provider"], x) for x in rows) if n]
    return out[:GIS_COMMENTS_MAX], len(rows) >= GIS_PAGE


def gis_linked(c, cid):
    """Issue numbers of connection cid that are a task already."""
    return {r[0] for r in c.execute("SELECT issue_no FROM git_issue_links WHERE conn_id=?", (cid,))}


def _gis_day(ts, lg):
    if not ts:
        return ""
    d = datetime.fromisoformat(ts).date()
    return d.strftime("%d.%m.%Y") if lg == "de" else d.isoformat()


def gis_snap(n, tail, nc):
    """2.394.0 C (#3377): the synced state of a linked issue (git_issue_links.snap, read by integrations/git_sync.py)."""
    return json.dumps({"title": (n["title"] or "").strip(), "body": imp_textblock(n["body"]), "state": n["state"],
                       "labels": sorted(dict.fromkeys(n["labels"]), key=str.casefold), "tail": tail, "nc": nc}, ensure_ascii=False)


def gis_plan(r, issues, more, lg, fetched=None):
    """The import plan of issues (gis_norm_issue dicts) of connection r into its list (one plan list, the target decides).
    fetched = how many issues were read (the warning names that number, 2.394.0 C review of B)."""
    prov, full = r["provider"], f"{r['owner']}/{r['repo']}"
    plan = imp_plan(prov)
    L = imp_list(plan, full)
    if more:
        imp_warn(plan, N_("Only the newest {0} issues were imported"), None, fetched if fetched is not None else len(issues))
    for n in sorted(issues, key=lambda x: x["no"]):
        t = imp_task(L, f"{r['id']}:{n['no']}", n["title"] or f"{full}#{n['no']}", status=2 if n["state"] == "closed" else 0,
                     completed_at=n["closed_at"], created_at=n["created_at"], url=n["url"] or None, tags=[],
                     assignee={"username": n["assignees"][0], "name": n["assignees"][0]} if n["assignees"] else None)
        imp_addnote(t, n["body"])
        for x in n["assignees"][1:]:
            imp_addnote(t, tr("Assignee ({0}): {1}", IMPORT_SOURCES_CONN[prov], x, lg=lg))
        imp_addnote(t, f"{full}#{n['no']}" + (" · " + tr("opened by @{0}", n["author"], lg=lg) if n["author"] else ""))
        t["_gis"] = n
    return plan


def gis_ltags(c, tid, labels):
    """2.394.0 C (#3377): the labels as the task's project tags (shared in the project, synced with the issue's labels);
    names a project tag cannot have are left out; at the project's tag limit nothing is set."""
    names = []
    for x in labels[:50]:
        try:
            names.append(clean_ltag_name(x))
        except BadInput:
            continue
    try:
        set_ltags(c, tid, names, log=False)
    except BadInput:
        pass


def gis_before(cid, stats):
    """imp_run's first step in its transaction (2.394.0 C, #3377 review of B): one import per connection at a time (two
    admins at once: the second waits), and issues linked meanwhile are left out ("already")."""
    def run(c, plan):
        write_lock(c, f"gis:{cid}")
        have = gis_linked(c, cid)
        for L in plan["lists"]:
            keep = [t for t in L["tasks"] if (t.get("_gis") or {}).get("no") not in have]
            stats["already"] += len(L["tasks"]) - len(keep)
            L["tasks"] = keep
    return run


def gis_after(r, uid, lg, stats):
    """imp_run's hook (same transaction): per new task its link (+ the synced state for the two-way sync, 2.394.0 C), its
    labels as project tags and its comments (fetched before, gis_import: no request while the transaction is open; each
    remembered in git_issue_comments, so the sync never takes it twice); the dry run only counts them."""
    def run(c, rows, rep, dry):
        ts, ncom = iso(now_utc()), 0
        for t, tid, _lid in rows:
            n = t.get("_gis") or {}
            if dry:
                ncom += n.get("comments") or 0
                continue
            row = c.execute("SELECT content, created_at FROM tasks WHERE id=?", (tid,)).fetchone()
            body, notes = imp_textblock(n.get("body")), row["content"] or ""
            tail = notes[len(body):] if body and notes.startswith(body) else ("\n\n" + notes if not body and notes else "")
            # nc -1: the comments were not read (cap / time): the sync reads them once
            nc = (n.get("comments") or 0) if n.get("_cms") is not None or not n.get("comments") else -1
            c.execute("""INSERT INTO git_issue_links(conn_id,issue_no,task_id,remote_updated_at,local_updated_at,created_at,snap)
                         VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""",
                      (r["id"], n["no"], tid, n.get("updated_at"), ts, ts, gis_snap(n, tail, nc)))
            if n.get("labels"):
                gis_ltags(c, tid, n["labels"])
            if not n.get("comments"):
                continue
            cms, cut = n.get("_cms") or [], n.get("_cut")
            if cut:
                imp_warn_rep(rep, tr("Only the first {0} comments of an issue were imported", GIS_COMMENTS_MAX, lg=lg), t["title"])
            for x in cms:
                # 2.394.0 C (#3377 review of B): control / bidi characters out; without a date the task's (the import's) time
                head = tr("@{0} on {1}:", imp_line(x["author"], 100) or "?", _gis_day(x["created_at"], lg), lg=lg)
                cid = insert_id(c, "INSERT INTO comments(task_id,user_id,body,mentions,created_at) VALUES(?,?,?,'',?)",
                                (tid, uid, (head + "\n\n" + imp_textblock(x["body"], 100000))[:100000], x["created_at"] or row["created_at"] or ts))
                if isinstance(x.get("id"), int) and not isinstance(x.get("id"), bool):
                    c.execute("""INSERT INTO git_issue_comments(conn_id,issue_no,remote_id,comment_id,created_at) VALUES(?,?,?,?,?)
                                 ON CONFLICT DO NOTHING""", (r["id"], n["no"], x["id"], cid, ts))
                ncom += 1
        rep["comments"] = ncom
        rep.update(stats)
    return run


def imp_warn_rep(rep, text, title):
    """A warning that comes up only while writing (the plan's warnings are already in the report)."""
    w = next((x for x in rep["warnings"] if x["text"] == text), None)
    if not w:
        w = {"text": text, "count": 0, "examples": []}
        rep["warnings"].append(w)
    w["count"] += 1
    if len(w["examples"]) < 3:
        w["examples"].append(imp_line(title, 80))


@app.post("/api/repos/<int:cid>/issues/import")
def gis_import(cid):
    """{dry_run?: bool, completed?: import | skip} -> the import report (+ issues, already, pull_requests, comments)."""
    if (g.user["kind"] or "user") == "agent":  # also with a folder repository or a list it cannot see
        raise Denied(403, tr("Agents cannot import issues"))
    c, uid = db(), me()
    b = body()
    reject_unknown(b, GIS_IN)
    dry = b.get("dry_run", False)
    comp = b.get("completed", "import")
    if dry not in (True, False) or comp not in ("import", "skip"):
        return err(tr("Invalid value: {0}", "dry_run" if dry not in (True, False) else "completed"))
    r = git_need_conn(c, cid)
    if gf_row(c, cid):
        return err(tr("Issues are imported into a project's own repository, not the one of its folder"), 409)
    if r["provider"] not in GIS_PROVIDERS:
        return err(tr("Importing issues is not available for this provider yet (GitHub and GitLab only)"), 409)
    le2a_gen_refuse(c, r["list_id"])
    if hit_limit(f"import:{uid}", IMPORT_RATE, 600):
        raise Denied(429, tr("Too many imports, please wait a few minutes"))
    k, lg = git_ctx(c, r), lang(c, uid)
    deadline = time.monotonic() + GIS_DEADLINE  # 2.394.0 C (#3377 review of B): one limit for all requests of the import
    try:
        issues, prs, more = gis_fetch_issues(k, deadline=deadline)
    except GitRate:
        return err(tr(GIT_ERR["rate"]), 409)
    except CalError as e:
        if e.code == "auth":
            return err(tr("Access denied: the token needs read access to the issues (GitHub: Issues read, GitLab: read_api)"), 409)
        if e.code == "not_found":
            return err(tr("No issues found: are issues switched on in this repository?"), 409)
        return err(git_err_text(e.stored()), 502)
    have = gis_linked(c, cid)
    new = [n for n in issues if n["no"] not in have]
    stats = {"issues": len(issues), "already": len(issues) - len(new), "pull_requests": prs}
    if not new:
        return jsonify({"source": r["provider"], "source_name": IMPORT_SOURCES_CONN[r["provider"]], "dry_run": dry,
                        "created": {"tasks": 0, "done": 0, "skipped": 0, "assigned": 0}, "skipped": 0, "lists": [], "import_id": None,
                        "undo_until": None, "samples": [], "warnings": [], "comments": 0, "tasks": 0, "new_lists": 0, **stats})
    left = 0  # 2.394.0 C (#3377 review of B): issues whose comments are not read (cap, time, rate limit): a warning
    if not dry:  # the comments before the transaction (the dry run counts them from the issues)
        want = [n for n in new if n["comments"] and not (comp == "skip" and n["state"] == "closed")]
        for i, n in enumerate(want):
            if i >= GIS_COMMENT_ISSUES or time.monotonic() > deadline:
                left = len(want) - i
                break
            try:
                n["_cms"], n["_cut"] = gis_fetch_comments(k, n["no"])
            except GitRate:
                left = len(want) - i
                break
            except CalError as e:
                return err(git_err_text(e.stored()), 502)
    plan = gis_plan(r, new, more, lg, fetched=len(issues))
    if left:
        imp_warn(plan, N_("The comments of {0} issues were not imported (too many or the Git server was too slow)"), None, left)
    opts = {"target": r["list_id"], "completed": comp, "_fname": f"{r['owner']}/{r['repo']}"[:200],
            "_before": gis_before(cid, stats), "_after": gis_after(r, uid, lg, stats)}
    return jsonify(imp_run(c, uid, plan, opts, dry))
