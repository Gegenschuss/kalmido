"""2.394.0 C (#3377): the two-way sync of GitHub / GitLab issues with the tasks of a repository connection's project.

Per connection two switches (git_conns.issue_sync / issue_create, off by default; PATCH /api/repos/<id> {issue_sync,
issue_create}, the project's owner / admins, people only -- git_update / git_need_manage). Switching the sync on checks
whether the token may write issues (GitHub: permissions push / maintain / admin of the repository answer -- triage cannot edit
others' issues, 2.394.0 D; GitLab: an
access level of Reporter or more): without it the sync only reads (repository -> Kalmido, issue_rw 0, shown in the settings).
Never for a project with end-to-end encryption, a list whose data never leaves the server (health, budget, an organisation's
trip, read later: like webhooks.wh_note), a folder's repository or another provider (409 with the reason).

Synced: title, text (the task's notes; a note tail the import or the sync added, e.g. "owner/repo#12 - opened by @x", stays
in Kalmido only), open / closed, labels <-> the project tags (list tags; personal tags never), comments -- both ways.
Comments are only added, never changed or deleted: an issue comment becomes a comment with an author line (like the import),
a Kalmido comment goes out as "<name> (Kalmido):" + its text (mentions as plain names); both are remembered in
git_issue_comments, so nothing comes back as an echo or twice. Never sent: a locked (private) note, attachments, custom
fields, personal tags, portal answers, agents' suggestion / answer cards.

PULL (git_poll -> gsy_pull, inside the poll's rate-limit handling): the issues updated since the last round (GitHub since=,
GitLab updated_after=, oldest first, one page per round), comments of at most GSY_COMMENT_ISSUES issues per round. A linked
issue is merged field by field (gsy_merge); an issue opened after the sync was switched on that no task has becomes a task
in the section "Backlog" (else the list's first section, else none) with its link; deleted / moved-away tasks are never made
again (git_issue_gone).
PUSH: a change of a linked task (log_act / a new comment -> gsy_note, collected per request and queued only after a
successful answer, like wh_note) marks the changed fields with their time and sets push_due to now + GSY_PUSH_S; the git loop
(gsy_push, once per tick) sends what is due: it reads the issue first (one request: the same field merge, so a change in
the repository since the last poll is never overwritten unseen), then one PATCH (GitLab PUT) with the fields that differ and
the comments still to be sent. A new top-level task goes out as a new issue only with issue_create on (the first such
repository of the project). A change the sync itself makes runs without a request: it is never noted, so never echoed.
CONFLICT (both sides changed a field since the last sync, snap = that state): the newer one wins (the field's own time in the
repository where it is cheap -- 2.394.0 D: GitHub issue events, GitLab state / label events, one extra request per issue
and only on a conflict -- else the issue's updated_at, against the time of the change here); the lost version goes into
the task's history (activity "git_sync_lost" with field, value, side and both times), never silently overwritten.
2.394.0 D (#3377 review): every successful write to the repository is stored and committed at once (a new issue is marked
"being created" before its POST, so a later error never creates a second one; each sent comment at once), a change noted
while a send runs is never lost (dirty is merged with the row under its lock), a title goes out cut to GSY_TITLE_MAX, and
after GSY_FAIL_MAX equal errors in a row a link is given up (history "git_sync_fail") until the task changes again.
A deleted task or one moved to another project: its link goes (git_issue_gone), nothing is deleted in the repository."""
import json
import time
import urllib.parse
from datetime import timedelta
from flask import g, has_request_context

from ..core.config import app
from ..core.i18n import lang, N_, tr
from ..core.db import bump, db, err, iso, iso_ms, now_utc, parse_iso
from ..core.pg import insert_id, write_lock
from ..core.access import reading_sql
from ..notify.alerts import _env_int, aa_count
from ..calendars.subscriptions import CalError
from ..collab.liste2e import le2e_mode
from ..collab.reactions import clean_ltag_name, ltag_names, set_ltags
from ..collab.comments import MENTION_RE, user_names
from ..core.errors import BadInput
from ..tasks.validation import ACT_NOTES, log_act
from .git import GIT_SYNC, GitRate, git_ctx, git_err_text, git_http
from .gitfolder import gf_row
from .git_issues import _gis_day, GIS_PAGE, GIS_PROVIDERS, gis_norm_comment, gis_norm_issue, gis_snap
from .importers import imp_line, imp_textblock

GSY_PUSH_S = _env_int("KALMIDO_GIT_SYNC_PUSH", 30)   # s a task's changes are collected before they go out (at most every 30 s)
GSY_PUSH_PER_TICK = 10                               # linked tasks sent per loop tick
GSY_COMMENT_ISSUES = 10                              # issues whose comments are read per round
GSY_COMMENT_PAGES = 5                                # pages of comments per issue (100 each)
GSY_ROUND_S = 60                                     # s for one round's requests (monotonic), the rest waits for the next
GSY_CREATE_PER_REQUEST = 20                          # new issues one request may queue (a bulk action never floods a repository)
GSY_FIELDS = ("title", "body", "state", "labels")
GSY_TITLE_MAX = 255                                  # 2.394.0 D: GitHub takes 256 characters, GitLab 255 (Kalmido 2000)
GSY_FAIL_MAX = 5                                     # 2.394.0 D: equal send errors of one link in a row before it is given up
GSY_RETRY_S = 300                                    # s before a failed send is tried again
# 2.394.0 D (#3377 review 3): GitHub issue events that date a field (GitLab: resource_state_events / resource_label_events)
GSY_GH_EVENTS = {"renamed": "title", "closed": "state", "reopened": "state", "labeled": "labels", "unlabeled": "labels"}
# what a history entry means for the sync: a field, "-" = the link may go (deleted / moved), "+" = a new task
GSY_KINDS = {"title": "title", "content": "body", "complete": "state", "reopen": "state", "wont": "state", "ltags": "labels",
             "delete": "-", "list": "-", "created": "+"}
GSY_ERR = {"e2e": N_("The project is end-to-end encrypted: its tasks cannot be synced"),
           "private": N_("The data of this project never leaves the server: no sync"),
           "provider": N_("The issue sync is available for GitHub and GitLab only"),
           "folder": N_("The issue sync works with a project's own repository, not the one of its folder"),
           "write": N_("The token cannot write issues: the sync only reads (GitHub: Issues read and write, GitLab: api)"),
           "issues": N_("No issues found: are issues switched on in this repository?")}
GSY_BOOL = (True, False, 0, 1)


# ---- values
def _norm_body(v):
    return imp_textblock(v)


def _eq(f, a, b):
    if a is None or b is None:
        return a is b
    if f == "labels":
        return sorted({x.casefold() for x in a}) == sorted({x.casefold() for x in b})
    if f == "body":
        return _norm_body(a) == _norm_body(b)
    if f == "title":  # 2.394.0 D: a title goes out cut (GSY_TITLE_MAX), the cut one in the repository is the same
        return str(a).strip()[:GSY_TITLE_MAX] == str(b).strip()[:GSY_TITLE_MAX]
    return str(a).strip() == str(b).strip()


def _remote(n, f):
    return {"title": (n["title"] or "").strip(), "body": _norm_body(n["body"]), "state": n["state"],
            "labels": sorted(dict.fromkeys(n["labels"]), key=str.casefold)}[f]


def _tail_cut(content, tail):
    s = content or ""
    if tail and s == tail.lstrip("\n"):  # notes that are only the tail (an issue without text)
        return ""
    return s[:-len(tail)] if tail and s.endswith(tail) else s


def _with_tail(v, tail):
    return (v + tail) if v else tail.lstrip("\n")


def _locked_note(c, tid):
    return bool(c.execute("SELECT 1 FROM task_note_locks WHERE task_id=?", (tid,)).fetchone())


def gsy_local(c, t, tail):
    """The synced fields of task row t as the repository would see them."""
    return {"title": (t["title"] or "").strip(), "body": _norm_body(_tail_cut(t["content"], tail)),
            "state": "open" if t["status"] == 0 else "closed", "labels": ltag_names(c, t["id"])}


def gsy_snap(n, tail, nc=None):
    """The synced state of a just-linked issue (git_issue_links.snap, the same as the import's)."""
    return gis_snap(n, tail, n["comments"] if nc is None else nc)


def _ref(r, no):
    return f"{r['owner']}/{r['repo']}#{no}"


def _shown(f, v):
    """A field's value for the history (lists joined, long texts cut)."""
    return ", ".join(v) if f == "labels" else str(v or "")[:20000]


# ---- the state for the settings, the switches
def gsy_block(c, r):
    """Why the sync cannot run on connection r (a GSY_ERR code) or None."""
    if r["provider"] not in GIS_PROVIDERS:
        return "provider"
    if gf_row(c, r["id"]):
        return "folder"
    if le2e_mode(c, r["list_id"]):
        return "e2e"
    if c.execute(f"""SELECT 1 FROM lists l WHERE l.id=? AND (l.life IN ('health', 'budget') OR (l.life='travel' AND l.org_id IS NOT NULL)
                     OR {reading_sql()})""", (r["list_id"],)).fetchone():
        return "private"
    return None


def gsy_err_text(code):
    code = code or ""
    return tr(GSY_ERR[code]) if code in GSY_ERR else git_err_text(code) if code else ""


def gsy_public(c, r):
    """git_public's issue_state (managers only): available, block (code + text), rw write | read | null (not checked yet),
    synced_at, error."""
    keys = r.keys() if hasattr(r, "keys") else ()
    if "issue_rw" not in keys:
        return None
    b = gsy_block(c, r)
    rw = r["issue_rw"]
    return {"available": b is None, "block": b, "block_text": gsy_err_text(b) if b else "",
            "rw": "write" if rw == 1 else "read" if rw == 0 else None, "synced_at": r["issue_synced_at"] or None,
            "error": gsy_err_text(r["issue_error"]) if r["issue_error"] else ""}


def gsy_rw_of(prov, j, token):
    """1 if the repository answer j says the token may write issues, else 0."""
    if not token or not isinstance(j, dict):
        return 0
    p = j.get("permissions") if isinstance(j.get("permissions"), dict) else {}
    if prov == "github":
        return 1 if any(p.get(x) is True for x in ("push", "maintain", "admin")) else 0  # 2.394.0 D: not triage
    lv = [(p.get(x) or {}).get("access_level") for x in ("project_access", "group_access") if isinstance(p.get(x), dict)]
    return 1 if any(isinstance(v, int) and v >= 20 for v in lv) else 0


def gsy_check_rw(c, r, k):
    """Reads the repository with the connection's token and stores issue_rw. CalError / GitRate pass through."""
    _, _, j = git_http(k, k["path"])
    rw = gsy_rw_of(r["provider"], j, k["token"])
    c.execute("UPDATE git_conns SET issue_rw=?, issue_error=? WHERE id=?", (rw, "" if rw else "write", r["id"]))
    return rw


def gsy_update(c, r, b):
    """git_update's part for {issue_sync?, issue_create?}: an error response or None (the caller commits)."""
    for key in ("issue_sync", "issue_create"):
        if key in b and (b[key] not in GSY_BOOL or isinstance(b[key], float)):
            return err(tr("Invalid value: {0}", key))
    on = bool(b["issue_sync"]) if "issue_sync" in b else bool(r["issue_sync"])
    if on and not r["issue_sync"]:
        blk = gsy_block(c, r)
        if blk:
            return err(gsy_err_text(blk), 409)
        k, rw = git_ctx(c, r), -1
        try:
            rw = gsy_check_rw(c, r, k)
        except GitRate:
            pass  # checked again with the first round
        except CalError as e:
            return err(git_err_text(e.stored()), 409 if e.code in ("auth", "not_found") else 502)
        ts = iso(now_utc())
        c.execute("UPDATE git_conns SET issue_sync=1, issue_on_at=?, issue_since=?, issue_rw=?, issue_error=?, next_at=0 WHERE id=?",
                  (ts, ts, rw, "write" if rw == 0 else "", r["id"]))
    elif not on and r["issue_sync"]:
        c.execute("UPDATE git_conns SET issue_sync=0, issue_error='' WHERE id=?", (r["id"],))
        c.execute("UPDATE git_issue_links SET push_due=0 WHERE conn_id=?", (r["id"],))
    if "issue_create" in b:
        c.execute("UPDATE git_conns SET issue_create=? WHERE id=?", (1 if b["issue_create"] else 0, r["id"]))
    return None


# ---- requests
def _issue_path(k, no=None, what=""):
    p = f"{k['path']}/issues" + (f"/{int(no)}" if no is not None else "")
    return p + ("/" + ("comments" if k["provider"] == "github" else "notes") if what == "comments" else "")


def _since_path(k, since):
    """The issues updated since `since` (one second earlier: GitHub's since is inclusive, GitLab's updated_after not), oldest first."""
    try:
        s = iso(parse_iso(since) - timedelta(seconds=1))
    except (ValueError, TypeError):
        s = since
    q = urllib.parse.quote(s, safe="")
    if k["provider"] == "github":
        return f"{k['path']}/issues?state=all&sort=updated&direction=asc&per_page={GIS_PAGE}&since={q}"
    return f"{k['path']}/issues?scope=all&order_by=updated_at&sort=asc&per_page={GIS_PAGE}&updated_after={q}"


def _send(k, method, path, data):
    if k.get("low"):
        raise GitRate(k["low"])
    _, _, j = git_http(k, path, method=method, data=data)
    return j


def _fetch_comments(k, no, deadline):
    out = []
    for page in range(1, GSY_COMMENT_PAGES + 1):
        if time.monotonic() > deadline:
            break
        if k.get("low"):
            raise GitRate(k["low"])
        sep = "&" if k["provider"] == "gitlab" else "?"
        path = _issue_path(k, no, "comments") + ("?sort=asc&order_by=created_at" if k["provider"] == "gitlab" else "")
        _, _, j = git_http(k, f"{path}{sep}per_page={GIS_PAGE}&page={page}")
        if not isinstance(j, list):
            raise CalError("parse")
        out += [x for x in (gis_norm_comment(k["provider"], y) for y in j) if x]
        if len(j) < GIS_PAGE:
            break
    return out


def _field_time(k, n, f, ev):
    """2.394.0 D (#3377 review 3): when field f of issue n was last changed in the repository, or None (unknown: the issue's
    updated_at counts). GitHub: the issue's events (renamed / closed / reopened / labeled / unlabeled), GitLab: its state or
    label events (a title / text has none). One request per issue at most (ev keeps it); a full page = unknown (older ones
    first, the newest may be missing); a field without events was never changed since the issue was opened."""
    gh = k is not None and k["provider"] == "github"
    if k is None or f == "body" or (not gh and f == "title"):
        return None
    if "got" not in ev:
        ev["got"] = None
        if k.get("low"):
            raise GitRate(k["low"])
        what = "events" if gh else "resource_state_events" if f == "state" else "resource_label_events"
        try:
            _, _, j = git_http(k, f"{_issue_path(k, n['no'])}/{what}?per_page={GIS_PAGE}")
        except CalError:
            return None
        if isinstance(j, list) and len(j) < GIS_PAGE:
            times = {}
            for x in j:
                fx = (GSY_GH_EVENTS.get(x.get("event")) if gh else f) if isinstance(x, dict) else None
                if fx and isinstance(x.get("created_at"), str) and x["created_at"] > times.get(fx, ""):
                    times[fx] = x["created_at"]
            ev["got"] = {"fields": set(GSY_GH_EVENTS.values()) if gh else {f}, "times": times}
    got = ev["got"]
    if not got or f not in got["fields"]:
        return None
    return got["times"].get(f) or n.get("created_at") or None


def _newer(a, b):
    """True if time a is at least as new as time b (an unreadable time: a counts as newer, like before)."""
    try:
        return bool(a) and (not b or parse_iso(a) >= parse_iso(b))
    except (ValueError, TypeError):
        return True


# ---- merging one issue into its task
def _apply(c, r, t, f, v, tail, ref):
    """Writes the repository's value v of field f into task t (no request: never noted for sending back)."""
    tid, ts = t["id"], iso_ms(now_utc())
    if f == "title":
        c.execute("UPDATE tasks SET title=?, updated_at=? WHERE id=?", ((v or "?")[:500], ts, tid))
        log_act(c, tid, "title", {"to": (v or "")[:200], "gsy": ref}, uid=None)
    elif f == "body":
        prev = t["content"] or ""
        c.execute("UPDATE tasks SET content=?, updated_at=? WHERE id=?", (_with_tail(v or "", tail), ts, tid))
        log_act(c, tid, "content", {"prev": prev[:20000], "gsy": ref} if prev.strip() else {"gsy": ref}, uid=None)
    elif f == "state":
        if t["locked"]:  # 2.542.0 (#4609): a locked task keeps its status (the repository's state is not taken over)
            return
        if v == "closed":
            c.execute("UPDATE tasks SET status=2, completed_at=?, updated_at=? WHERE id=? AND status=0", (ts, ts, tid))
            log_act(c, tid, "complete", {"gsy": ref}, uid=None)
        else:
            c.execute("UPDATE tasks SET status=0, completed_at=NULL, updated_at=? WHERE id=? AND status<>0", (ts, tid))
            log_act(c, tid, "reopen", {"gsy": ref}, uid=None)
    elif f == "labels":
        names = []
        for x in v or []:
            try:
                names.append(clean_ltag_name(x))
            except BadInput:
                continue
        try:
            set_ltags(c, tid, names[:50], log=False)
        except BadInput:  # the project's tag limit: the ones it has
            set_ltags(c, tid, [x for x in names if x.casefold() in {y.casefold() for y in ltag_names(c, tid)}], log=False)
        log_act(c, tid, "ltags", {"tags": ltag_names(c, tid), "gsy": ref}, uid=None)
        c.execute("UPDATE tasks SET updated_at=? WHERE id=?", (ts, tid))


def gsy_merge(c, r, L, t, n, k=None):
    """Merges issue n (gis_norm_issue) into task row t of link L field by field -> (snap dict, dirty dict, changed here).
    Only the repository changed a field: taken. Only here: left for the push. Both: the newer one wins, the other goes into
    the history (git_sync_lost); a lost remote value counts as seen (snap = it), so the push sends the local one.
    2.394.0 D: with k the field's own time in the repository is asked for (_field_time, only on a conflict)."""
    snap, dirty = json.loads(L["snap"] or "{}"), json.loads(L["dirty"] or "{}")
    tail, ref = snap.get("tail") or "", _ref(r, n["no"])
    loc, locked, changed = gsy_local(c, t, tail), _locked_note(c, t["id"]), False
    rts, ev = n.get("updated_at"), {}
    # 2.665.0 (#5113): the field times of a conflict are asked for before the first write (_apply), the same request the
    # loop below would make: with commit_first (git_http) no half-merged task is committed by that request
    for f in GSY_FIELDS:
        if "got" in ev:
            break
        if not (f == "body" and locked) and _gsy_conflict(f, _remote(n, f), loc[f], snap.get(f)):
            _field_time(k, n, f, ev)
    for f in GSY_FIELDS:
        if f == "body" and locked:  # a private (locked) note: never compared, never sent
            continue
        R, V, S = _remote(n, f), loc[f], snap.get(f)
        if _eq(f, R, V):
            snap[f] = R
            dirty.pop(f, None)
            continue
        if S is not None and _eq(f, R, S):
            continue  # changed here only: the push sends it
        if S is not None and _eq(f, V, S):
            _apply(c, r, t, f, R, tail, ref)
            snap[f], changed = R, True
            dirty.pop(f, None)
            continue
        lts = dirty.get(f) or t["updated_at"]
        fts = _field_time(k, n, f, ev)
        rt = fts or rts
        # 2.394.0 D: both times in the history (the repository's: of the field, else of the whole issue)
        when = {"at_here": lts or "", "at_repo": rt or "", "repo_by": "field" if fts else "issue"}
        if _newer(rt, lts):
            _apply(c, r, t, f, R, tail, ref)
            log_act(c, t["id"], "git_sync_lost", {"field": f, "value": _shown(f, V), "side": "here", "gsy": ref, **when}, uid=None)
            dirty.pop(f, None)
            changed = True
        else:
            log_act(c, t["id"], "git_sync_lost", {"field": f, "value": _shown(f, R), "side": "repo", "gsy": ref, **when}, uid=None)
            dirty.setdefault(f, lts)
            changed = True
        snap[f] = R
    return snap, dirty, changed


def _gsy_conflict(f, R, V, S):
    """2.665.0 (#5113): both sides changed field f since the last sync (gsy_merge's case that asks for the field's time)."""
    return not _eq(f, R, V) and not (S is not None and (_eq(f, R, S) or _eq(f, V, S)))


def _unlink(c, conn_id, no):
    c.execute("DELETE FROM git_issue_links WHERE conn_id=? AND issue_no=?", (conn_id, no))
    if no > 0:
        c.execute("INSERT INTO git_issue_gone(conn_id,issue_no,created_at) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                  (conn_id, no, iso(now_utc())))


def _task(c, tid):
    return c.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone()


def _gone_task(t, r):
    return not t or t["deleted_at"] or t["list_id"] != r["list_id"]


def _author(c, r):
    """Who the sync's comments belong to: the person who connected the repository, else the project's owner."""
    if r["created_by"] and c.execute("SELECT 1 FROM users WHERE id=?", (r["created_by"],)).fetchone():
        return r["created_by"]
    return c.execute("SELECT owner_id FROM lists WHERE id=?", (r["list_id"],)).fetchone()[0]


def gsy_take_comments(c, r, tid, no, cms, lg):
    """The issue comments cms not seen yet -> comments of task tid (author line, their own date). -> how many."""
    have = {x[0] for x in c.execute("SELECT remote_id FROM git_issue_comments WHERE conn_id=? AND remote_id IS NOT NULL", (r["id"],))}
    uid, n, ts = _author(c, r), 0, iso_ms(now_utc())
    for x in cms:
        rid = x.get("id")
        if not isinstance(rid, int) or isinstance(rid, bool) or rid in have:
            continue
        head = tr("@{0} on {1}:", imp_line(x["author"], 100) or "?", _gis_day(x["created_at"], lg), lg=lg)
        cid = insert_id(c, "INSERT INTO comments(task_id,user_id,body,mentions,created_at) VALUES(?,?,?,'',?)",
                        (tid, uid, (head + "\n\n" + imp_textblock(x["body"], 100000))[:100000], x["created_at"] or ts))
        c.execute("INSERT INTO git_issue_comments(conn_id,issue_no,remote_id,comment_id,created_at) VALUES(?,?,?,?,?) ON CONFLICT DO NOTHING",
                  (r["id"], no, rid, cid, ts))
        n += 1
    return n


def _section(c, lid):
    s = c.execute("SELECT id FROM sections WHERE list_id=? AND lower(name)='backlog' ORDER BY sort, id LIMIT 1", (lid,)).fetchone() or \
        c.execute("SELECT id FROM sections WHERE list_id=? ORDER BY sort, id LIMIT 1", (lid,)).fetchone()
    return s[0] if s else None


def gsy_new_task(c, r, n, lg):
    """A new issue -> a new task of the connection's project with its link (+ its comments with the next comment read)."""
    ts, lid, ref = iso_ms(now_utc()), r["list_id"], _ref(r, n["no"])
    tail = "\n\n" + ref + (" · " + tr("opened by @{0}", imp_line(n["author"], 100), lg=lg) if n["author"] else "")
    body = _norm_body(n["body"])
    srt = c.execute("SELECT COALESCE(MIN(sort),0)-1 FROM tasks WHERE list_id=? AND parent_id IS NULL", (lid,)).fetchone()[0]
    closed = n["state"] == "closed"
    tid = insert_id(c, """INSERT INTO tasks(list_id,section_id,title,content,status,sort,created_at,updated_at,completed_at,created_by,url)
                       VALUES(?,?,?,?,?,?,?,?,?,NULL,?)""",
                    (lid, _section(c, lid), (n["title"] or ref)[:500], _with_tail(body, tail), 2 if closed else 0, srt,
                     n["created_at"] or ts, ts, (n["closed_at"] or ts) if closed else None, n["url"] or None))
    log_act(c, tid, "created", {"gsy": ref}, uid=None)
    if n["labels"]:
        _apply(c, r, _task(c, tid), "labels", _remote(n, "labels"), tail, ref)
    snap = json.loads(gsy_snap(n, tail, nc=0))
    c.execute("""INSERT INTO git_issue_links(conn_id,issue_no,task_id,remote_updated_at,local_updated_at,created_at,snap)
                 VALUES(?,?,?,?,?,?,?) ON CONFLICT DO NOTHING""", (r["id"], n["no"], tid, n["updated_at"], ts, ts, json.dumps(snap, ensure_ascii=False)))
    return tid


def gsy_pull(c, r, k, get):
    """git_poll's part: one page of issues updated since the last round -> merged / new tasks. -> changed. GitRate passes
    through (the poll pauses); other errors only stop the sync's round (issue_error), never the poll."""
    if gsy_block(c, r):
        c.execute("UPDATE git_conns SET issue_error=? WHERE id=?", (gsy_block(c, r), r["id"]))
        return False
    deadline, changed, lg = time.monotonic() + GSY_ROUND_S, False, lang(c, _author(c, r))
    complete = False  # 2.394.0 D (#3377 review 5): a round that stopped early keeps no ETag (else the same page answers 304)
    try:
        if r["issue_rw"] == -1:
            gsy_check_rw(c, r, k)
        since = r["issue_since"] or r["issue_on_at"] or iso(now_utc())
        j = get("issues:sync", _since_path(k, since))
        if j is None:  # unchanged (304)
            complete = True
            c.execute("UPDATE git_conns SET issue_synced_at=? WHERE id=?", (iso(now_utc()), r["id"]))
            return False
        if not isinstance(j, list):
            raise CalError("parse")
        issues = [x for x in (gis_norm_issue(r["provider"], y) for y in j) if x and not x["pr"]]
        write_lock(c, f"gis:{r['id']}")  # never at the same time as an issue import of this connection (git_issues.gis_before)
        links = {x["issue_no"]: x for x in c.execute("SELECT * FROM git_issue_links WHERE conn_id=?", (r["id"],))}
        gone = {x[0] for x in c.execute("SELECT issue_no FROM git_issue_gone WHERE conn_id=?", (r["id"],))}
        on_at, last, reads = r["issue_on_at"] or since, since, 0
        for n in issues:
            L = links.get(n["no"])
            snap = json.loads(L["snap"] or "{}") if L else {}
            want = n["comments"] and (not L or n["comments"] != snap.get("nc"))
            if want and (reads >= GSY_COMMENT_ISSUES or time.monotonic() > deadline):
                break  # the rest with the next round (issue_since stays before it)
            if L:
                t = _task(c, L["task_id"])
                if _gone_task(t, r):
                    _unlink(c, r["id"], n["no"])
                else:
                    snap, dirty, ch = gsy_merge(c, r, L, t, n, k)
                    changed |= ch
                    # 2.394.0 D (#3377 review 2 + 5): stored before the comments are read (a rate limit there keeps the merge,
                    # its conflict is never logged twice), merged with a change noted meanwhile
                    d, due = _fresh_dirty(c, r["id"], n["no"], json.loads(L["dirty"] or "{}"), dirty)
                    c.execute("UPDATE git_issue_links SET snap=?, dirty=?, remote_updated_at=?, push_due=? WHERE conn_id=? AND issue_no=?",
                              (json.dumps(snap, ensure_ascii=False), json.dumps(d) if d else "", n["updated_at"],
                               (due or time.time() + GSY_PUSH_S) if d and r["issue_rw"] != 0 else due, r["id"], n["no"]))
                    if want:
                        reads += 1
                        changed |= bool(gsy_take_comments(c, r, t["id"], n["no"], _fetch_comments(k, n["no"], deadline), lg))
                        snap["nc"] = n["comments"]
                        c.execute("UPDATE git_issue_links SET snap=? WHERE conn_id=? AND issue_no=?",
                                  (json.dumps(snap, ensure_ascii=False), r["id"], n["no"]))
            elif n["no"] not in gone and n["created_at"] and n["created_at"] >= on_at:
                tid = gsy_new_task(c, r, n, lg)
                changed = True
                if want:
                    reads += 1
                    gsy_take_comments(c, r, tid, n["no"], _fetch_comments(k, n["no"], deadline), lg)
                    snap = json.loads(c.execute("SELECT snap FROM git_issue_links WHERE conn_id=? AND issue_no=?", (r["id"], n["no"])).fetchone()[0])
                    c.execute("UPDATE git_issue_links SET snap=? WHERE conn_id=? AND issue_no=?",
                              (json.dumps({**snap, "nc": n["comments"]}, ensure_ascii=False), r["id"], n["no"]))
            if n["updated_at"] and n["updated_at"] > last:
                last = n["updated_at"]
        else:
            complete = True
        c.execute("UPDATE git_conns SET issue_since=?, issue_synced_at=?, issue_error=CASE WHEN issue_rw=0 THEN 'write' ELSE '' END WHERE id=?",
                  (last, iso(now_utc()), r["id"]))
    except CalError as e:
        c.execute("UPDATE git_conns SET issue_error=? WHERE id=?", ("issues" if e.code == "not_found" else e.stored(), r["id"]))
    finally:
        if not complete and hasattr(get, "forget"):
            get.forget("issues:sync")
    return changed


# ---- sending
def _out_fields(k, vals):
    """The provider's body of an issue write from {field: value}."""
    gh, d = k["provider"] == "github", {}
    for f, v in vals.items():
        if f == "title":
            d["title"] = (v or "?")[:GSY_TITLE_MAX]  # 2.394.0 D: longer ones are refused (422) by both providers
        elif f == "body":
            d["body" if gh else "description"] = v
        elif f == "state":
            if gh:
                d["state"] = v
            else:
                d["state_event"] = "close" if v == "closed" else "reopen"
        elif f == "labels":
            d["labels"] = list(v) if gh else ",".join(v)
    return d


def _comment_text(c, row):
    u = c.execute("SELECT display_name, username FROM users WHERE id=?", (row["user_id"],)).fetchone() if row["user_id"] else None
    name = (u["display_name"] or u["username"]) if u else "?"
    text = row["body"] or ""
    names = user_names(c, [int(x) for x in MENTION_RE.findall(text)])
    return f"{name} (Kalmido):\n\n" + MENTION_RE.sub(lambda m: "@" + names.get(int(m.group(1)), "?"), text)


def _fresh_dirty(c, cid, no, seen, mine):
    """2.394.0 D (#3377 review 2): the link's row locked (FOR UPDATE; gsy_queue changes dirty in one statement on the row)
    -> (dirty to write, its push_due): mine (what this round leaves) plus every field noted meanwhile (another time than the
    one read before the requests, seen). ({}, 0) if the link is gone."""
    row = c.execute("SELECT dirty, push_due FROM git_issue_links WHERE conn_id=? AND issue_no=? FOR UPDATE", (cid, no)).fetchone()
    if not row:
        return {}, 0
    d = dict(mine)
    d.update({f: ts for f, ts in json.loads(row["dirty"] or "{}").items() if ts != seen.get(f)})
    return d, row["push_due"] or 0


def _settle(c, cid, no):
    """2.394.0 D (#3377 review 2): after a successful send: push_due 0 only if nothing unsent is left (a field or a comment
    noted while it ran is collected anew: due in GSY_PUSH_S), the error count goes. Commits."""
    d, _ = _fresh_dirty(c, cid, no, {}, {})
    left = d or c.execute("SELECT 1 FROM git_issue_comments WHERE conn_id=? AND issue_no=? AND remote_id IS NULL LIMIT 1", (cid, no)).fetchone()
    c.execute("UPDATE git_issue_links SET push_due=?, push_err='', push_fails=0 WHERE conn_id=? AND issue_no=?",
              (time.time() + GSY_PUSH_S if left else 0, cid, no))
    c.commit()


def _created_before(r, k, mark, title):
    """2.394.0 D (#3377 review 1): an earlier try was marked before its POST and did not get to store the answer: the issue
    with this title opened since the mark (adopted, never a second one), None = there is none (that POST created nothing).
    More than a page of issues since then: unsure (CalError), nothing is created."""
    if k.get("low"):
        raise GitRate(k["low"])
    try:
        since = iso(parse_iso(mark) - timedelta(seconds=120))  # the repository's clock may differ a little
    except (ValueError, TypeError):
        since = mark
    _, _, j = git_http(k, _since_path(k, since))
    if not isinstance(j, list):
        raise CalError("parse")
    for n in (gis_norm_issue(r["provider"], y) for y in j):
        if n and not n["pr"] and n["created_at"] and _eq("title", (n["title"] or "").strip(), title) and _newer(n["created_at"], since):
            return n
    if len(j) >= GIS_PAGE:
        raise CalError("error")
    return None


def gsy_create_issue(c, r, k, L):
    """A pending new task (issue_no = -task id) -> a new issue; the link gets its number, the task its address + tail.
    2.394.0 D (#3377 review 1): the link is marked "being created" (committed) before the POST and gets the issue's number
    (committed) right after it; a closed task / its comments then go out like any change (gsy_push_one): an error after the
    POST never creates a second issue."""
    t = _task(c, L["task_id"])
    if _gone_task(t, r):
        _unlink(c, r["id"], L["issue_no"])
        return False
    vals = {"title": (t["title"] or "?").strip(), "labels": ltag_names(c, t["id"])}
    if not _locked_note(c, t["id"]):
        vals["body"] = _norm_body(t["content"])
    mark = json.loads(L["snap"] or "{}").get("creating")
    n = _created_before(r, k, mark, vals["title"]) if mark else None
    adopted = n is not None
    if not adopted:
        c.execute("UPDATE git_issue_links SET snap=? WHERE conn_id=? AND issue_no=?",
                  (json.dumps({"creating": iso(now_utc())}), r["id"], L["issue_no"]))
        c.commit()
        n = gis_norm_issue(r["provider"], _send(k, "POST", _issue_path(k), _out_fields(k, vals)))
        if not n:
            raise CalError("parse")
    ref, ts = _ref(r, n["no"]), iso_ms(now_utc())
    tail = "\n\n" + ref
    c.execute("UPDATE tasks SET content=?, url=COALESCE(NULLIF(url, ''), ?) WHERE id=?", (_with_tail(t["content"] or "", tail), n["url"] or None, t["id"]))
    # what the issue has: what was sent (an adopted one: what it says, the rest goes out with the next step)
    snap = {**json.loads(gsy_snap(n, tail, nc=0)), **({} if adopted else vals)}
    c.execute("UPDATE git_issue_links SET issue_no=?, snap=?, remote_updated_at=?, local_updated_at=? WHERE conn_id=? AND issue_no=?",
              (n["no"], json.dumps(snap, ensure_ascii=False), n["updated_at"], ts, r["id"], L["issue_no"]))
    c.execute("UPDATE git_issue_comments SET issue_no=? WHERE conn_id=? AND issue_no=?", (n["no"], r["id"], L["issue_no"]))
    c.commit()
    L2 = c.execute("SELECT * FROM git_issue_links WHERE conn_id=? AND issue_no=?", (r["id"], n["no"])).fetchone()
    if L2 and (adopted or t["status"] != 0 or
               c.execute("SELECT 1 FROM git_issue_comments WHERE conn_id=? AND issue_no=? AND remote_id IS NULL LIMIT 1", (r["id"], n["no"])).fetchone()):
        gsy_push_one(c, r, k, L2)  # the state (issues are created open), what changed meanwhile, the comments
    elif L2:
        _settle(c, r["id"], n["no"])
    return True


def _sent_before(c, r, k, no, row, text, got):
    """2.665.0 (#5113): an earlier try of comment row was marked (send_at) before its POST and did not get to store the
    answer: the issue comment with the same text written since the mark that no row has yet (adopted, never sent twice), else
    None. The issue's comments are read once per push (got); all pages read without it: unsure (CalError), nothing is sent."""
    if "list" not in got:
        got["list"] = _fetch_comments(k, no, time.monotonic() + GSY_ROUND_S)
        got["full"] = len(got["list"]) >= GSY_COMMENT_PAGES * GIS_PAGE
    try:
        since = iso(parse_iso(row["send_at"]) - timedelta(seconds=120))  # the repository's clock may differ a little
    except (ValueError, TypeError):
        since = row["send_at"]
    have = {x[0] for x in c.execute("SELECT remote_id FROM git_issue_comments WHERE conn_id=? AND remote_id IS NOT NULL", (r["id"],))}
    for x in got["list"]:
        if isinstance(x.get("id"), int) and x["id"] not in have and (x["body"] or "").strip() == text.strip() and \
                _newer(x["created_at"], since):
            return x["id"]
    if got["full"]:
        raise CalError("error")
    return None


def _push_comments(c, r, k, no):
    """The comments still to be sent to issue no; each one is stored (committed) as soon as the repository took it
    (2.394.0 D, #3377 review 1: an error with the next one never sends it twice).
    2.665.0 (#5113): each one is marked (send_at, committed) before its POST; a marked one whose answer was not stored (the
    store broke off after the POST) is looked for among the issue's comments first (_sent_before): at most one more POST,
    only when the repository has no such comment."""
    got = {}
    for row in c.execute("""SELECT x.id, x.send_at, m.body, m.user_id, m.deleted_at FROM git_issue_comments x JOIN comments m ON m.id=x.comment_id
                            WHERE x.conn_id=? AND x.issue_no=? AND x.remote_id IS NULL ORDER BY x.id""", (r["id"], no)).fetchall():
        if row["deleted_at"] or not (row["body"] or "").strip():
            c.execute("DELETE FROM git_issue_comments WHERE id=?", (row["id"],))
            c.commit()
            continue
        text = _comment_text(c, row)
        rid = _sent_before(c, r, k, no, row, text, got) if row["send_at"] else None
        if rid is not None:
            c.execute("UPDATE git_issue_comments SET remote_id=? WHERE id=?", (rid, row["id"]))
            c.commit()
            continue
        c.execute("UPDATE git_issue_comments SET send_at=? WHERE id=?", (iso(now_utc()), row["id"]))
        c.commit()
        j = _send(k, "POST", _issue_path(k, no, "comments"), {"body": text})
        rid = j.get("id") if isinstance(j, dict) else None
        if isinstance(rid, int):
            c.execute("UPDATE git_issue_comments SET remote_id=? WHERE id=?", (rid, row["id"]))
        else:
            c.execute("DELETE FROM git_issue_comments WHERE id=?", (row["id"],))
        c.commit()


def gsy_push_one(c, r, k, L):
    """Sends the collected changes of one linked task (reads the issue first and merges it). -> changed here.
    2.394.0 D (#3377 review 1 + 2): the fields are stored (committed) right after the PATCH, each comment after its POST;
    push_due goes to 0 only if nothing was noted meanwhile."""
    if L["issue_no"] < 0:
        return gsy_create_issue(c, r, k, L)
    t = _task(c, L["task_id"])
    if _gone_task(t, r):
        _unlink(c, r["id"], L["issue_no"])
        return False
    if k.get("low"):
        raise GitRate(k["low"])
    _, _, j = git_http(k, _issue_path(k, L["issue_no"]))
    n = gis_norm_issue(r["provider"], j)
    if not n:
        raise CalError("parse")
    seen = json.loads(L["dirty"] or "{}")
    snap, _, changed = gsy_merge(c, r, L, t, n, k)
    t = _task(c, L["task_id"])
    loc = gsy_local(c, t, snap.get("tail") or "")
    locked = _locked_note(c, t["id"])
    out = {f: loc[f] for f in GSY_FIELDS if not (f == "body" and locked) and not _eq(f, loc[f], snap.get(f))}
    rts = n["updated_at"]
    # 2.665.0 (#5113): what the merge did is stored in its own short transaction before anything is sent (the snap of what
    # the issue has now; dirty stays as the row has it): a failed send no longer needs a rollback of the merge, and the
    # next try neither applies nor logs a conflict a second time
    c.execute("UPDATE git_issue_links SET snap=?, remote_updated_at=? WHERE conn_id=? AND issue_no=?",
              (json.dumps(snap, ensure_ascii=False), rts, r["id"], n["no"]))
    c.commit()
    if out:
        m = gis_norm_issue(r["provider"], _send(k, "PATCH" if k["provider"] == "github" else "PUT", _issue_path(k, n["no"]), _out_fields(k, out)))
        snap.update(out)
        rts = (m or {}).get("updated_at") or rts
    d, _ = _fresh_dirty(c, r["id"], n["no"], seen, {})  # everything read is sent or settled; only what came meanwhile stays
    c.execute("""UPDATE git_issue_links SET snap=?, dirty=?, remote_updated_at=?, local_updated_at=? WHERE conn_id=? AND issue_no=?""",
              (json.dumps(snap, ensure_ascii=False), json.dumps(d) if d else "", rts, iso_ms(now_utc()), r["id"], n["no"]))
    c.commit()
    _push_comments(c, r, k, n["no"])
    _settle(c, r["id"], n["no"])
    return changed


def _failed(c, r, L, code, again):
    """2.394.0 D (#3377 review 4): a send of link L failed (not a rate limit, not a refused token): tried again at `again`;
    after GSY_FAIL_MAX equal errors in a row it is given up (push_due 0, history "git_sync_fail" on the task) until the
    task changes again (gsy_queue sets push_due anew)."""
    row = c.execute("SELECT issue_no, push_err, push_fails FROM git_issue_links WHERE conn_id=? AND task_id=?", (r["id"], L["task_id"])).fetchone()
    if not row:
        return
    n = (row["push_fails"] or 0) + 1 if row["push_err"] == code else 1
    if n >= GSY_FAIL_MAX:
        c.execute("UPDATE git_issue_links SET push_due=0, push_err='', push_fails=0 WHERE conn_id=? AND task_id=?", (r["id"], L["task_id"]))
        ref = _ref(r, row["issue_no"]) if row["issue_no"] > 0 else f"{r['owner']}/{r['repo']}"
        log_act(c, L["task_id"], "git_sync_fail", {"gsy": ref, "error": code, "n": n}, uid=None)
    else:
        c.execute("UPDATE git_issue_links SET push_due=?, push_err=?, push_fails=? WHERE conn_id=? AND task_id=?",
                  (again, code, n, r["id"], L["task_id"]))


def gsy_push(c):
    """The git loop's part: the linked tasks whose collected changes are due (GSY_PUSH_PER_TICK). Per connection: read only
    or locked = nothing goes out; a rate limit pauses it; an error is shown and retried later.
    2.665.0 (#5113): like the poll (git_poll, 2.658.0) every request first commits (commit_first in git_http): no row lock
    and no snapshot stays open while the provider answers. Every answer is stored and committed at once (gsy_create_issue,
    gsy_push_one, _push_comments), so an error rolls back only what came after the last request; the error itself is stored
    as the link's state (push_err / push_fails / push_due, git_conns.issue_error)."""
    now = time.time()
    rows = c.execute("""SELECT l.* FROM git_issue_links l JOIN git_conns k ON k.id=l.conn_id
                        WHERE l.push_due>0 AND l.push_due<=? AND k.issue_sync=1 ORDER BY l.push_due LIMIT ?""", (now, GSY_PUSH_PER_TICK)).fetchall()
    c.commit()
    conns, stop, changed = {}, set(), False
    for L in rows:
        if L["conn_id"] in stop:
            continue
        r = conns.get(L["conn_id"]) or conns.setdefault(L["conn_id"], c.execute("SELECT * FROM git_conns WHERE id=?", (L["conn_id"],)).fetchone())
        if not r:  # 2.394.0 D (#3377 review 7): the connection was deleted meanwhile (its links went with it)
            continue
        k = conns.get(("k", r["id"])) or conns.setdefault(("k", r["id"]), git_ctx(c, r))
        k["commit_first"] = c  # 2.665.0 (#5113): see above
        try:
            if gsy_block(c, r):
                c.execute("UPDATE git_issue_links SET push_due=0 WHERE conn_id=?", (r["id"],))
                c.execute("UPDATE git_conns SET issue_error=? WHERE id=?", (gsy_block(c, r), r["id"]))
                stop.add(r["id"])
            elif (r["issue_rw"] if r["issue_rw"] != -1 else gsy_check_rw(c, r, k)) != 1:
                c.execute("UPDATE git_issue_links SET push_due=0 WHERE conn_id=?", (r["id"],))
                stop.add(r["id"])
            else:
                changed |= gsy_push_one(c, r, k, L)
                c.execute("UPDATE git_conns SET issue_synced_at=? WHERE id=?", (iso(now_utc()), r["id"]))
            c.commit()
        except GitRate as e:
            c.rollback()
            c.execute("UPDATE git_issue_links SET push_due=? WHERE conn_id=? AND push_due>0", (max(e.until + 5, now + 30), r["id"]))
            c.commit()
            stop.add(r["id"])
        except CalError as e:
            c.rollback()
            if e.code == "auth":  # the token may read but not write
                c.execute("UPDATE git_conns SET issue_rw=0, issue_error='write' WHERE id=?", (r["id"],))
                c.execute("UPDATE git_issue_links SET push_due=0 WHERE conn_id=?", (r["id"],))
                stop.add(r["id"])
            else:
                c.execute("UPDATE git_conns SET issue_error=? WHERE id=?", (e.stored(), r["id"]))
                _failed(c, r, L, e.stored(), now + GSY_RETRY_S)
            c.commit()
        except Exception as e:  # noqa: BLE001  (one bad task never stops the others)
            c.rollback()
            _failed(c, r, L, type(e).__name__, now + 900)
            c.commit()
            aa_count("watchdog", f"git|sync|{type(e).__name__}", "git")
    if changed:
        bump(c)
        c.commit()


# ---- noting local changes (per request, queued after a successful answer)
def gsy_note(c, tid, kind, cid=None, data=None):
    """ACT_NOTES: a change of task tid that may go to its issue (log_act / a new comment)."""
    if not has_request_context() or (kind not in GSY_KINDS and kind != "comment"):
        return
    if kind == "created" and isinstance(data, dict) and (data.get("from") or data.get("gsy")):
        return  # an import never floods the repository with new issues
    n = g.setdefault("gsy", {})
    e = n.setdefault(tid, {"f": {}, "cids": [], "x": set()})
    ts = iso_ms(now_utc())
    if kind == "comment":
        if cid:
            e["cids"].append(cid)
    elif GSY_KINDS[kind] in ("-", "+"):
        e["x"].add(GSY_KINDS[kind])
    else:
        e["f"][GSY_KINDS[kind]] = ts


def gsy_queue(c, n):
    """Marks the noted changes of linked tasks for sending (push_due), unlinks deleted / moved ones, queues new issues."""
    if not c.execute("SELECT 1 FROM git_conns WHERE issue_sync=1 LIMIT 1").fetchone():
        return
    ids = sorted(n)
    q = ",".join("?" * len(ids))
    now = time.time()
    links = c.execute(f"""SELECT l.*, k.list_id, k.issue_rw FROM git_issue_links l JOIN git_conns k ON k.id=l.conn_id
                          WHERE k.issue_sync=1 AND l.task_id IN ({q})""", ids).fetchall()
    linked = {x["task_id"] for x in c.execute(f"SELECT task_id FROM git_issue_links WHERE task_id IN ({q})", ids)}
    for L in links:
        e, t = n[L["task_id"]], _task(c, L["task_id"])
        if "-" in e["x"] and _gone_task(t, L):
            _unlink(c, L["conn_id"], L["issue_no"])
            continue
        if L["issue_rw"] == 0 or _gone_task(t, L):
            continue
        if not (e["f"] or e["cids"]):
            continue
        # 2.394.0 D (#3377 review 2): merged into the row in one statement (a send running now keeps what it did not read,
        # gsy_push_one / _fresh_dirty), by task: a new issue may just have got its number
        row = c.execute("""UPDATE git_issue_links SET dirty=(COALESCE(NULLIF(dirty, ''), '{}')::jsonb || ?::jsonb)::text,
                              push_due=CASE WHEN push_due>0 THEN push_due ELSE ? END WHERE conn_id=? AND task_id=? RETURNING issue_no""",
                        (json.dumps(e["f"]), now + GSY_PUSH_S, L["conn_id"], L["task_id"])).fetchone()
        for cid in e["cids"] if row else ():
            c.execute("INSERT INTO git_issue_comments(conn_id,issue_no,remote_id,comment_id,created_at) VALUES(?,?,NULL,?,?) ON CONFLICT DO NOTHING",
                      (L["conn_id"], row[0], cid, iso(now_utc())))
    made = 0
    for tid in ids:
        if "+" not in n[tid]["x"] or tid in linked or made >= GSY_CREATE_PER_REQUEST:
            continue
        t = _task(c, tid)
        if not t or t["deleted_at"] or t["parent_id"]:
            continue
        r = c.execute("""SELECT k.* FROM git_conns k WHERE k.list_id=? AND k.issue_sync=1 AND k.issue_create=1 AND k.issue_rw<>0
                         AND k.provider IN ('github', 'gitlab') AND NOT EXISTS (SELECT 1 FROM git_folders f WHERE f.conn_id=k.id)
                         ORDER BY k.id LIMIT 1""", (t["list_id"],)).fetchone()
        if r and not gsy_block(c, r):
            c.execute("""INSERT INTO git_issue_links(conn_id,issue_no,task_id,local_updated_at,created_at,push_due)
                         VALUES(?,?,?,?,?,?) ON CONFLICT DO NOTHING""", (r["id"], -tid, tid, iso_ms(now_utc()), iso(now_utc()), now + GSY_PUSH_S))
            made += 1
    c.commit()


@app.after_request
def gsy_flush(resp):
    n = g.pop("gsy", None) if has_request_context() else None
    if n and resp.status_code < 400:
        try:
            gsy_queue(db(), n)
        except Exception as e:  # noqa: BLE001  (never fail the request that already succeeded)
            try:
                db().heal()
            except Exception:  # noqa: BLE001
                pass
            aa_count("watchdog", f"git|syncq|{type(e).__name__}", "queue")
    return resp


ACT_NOTES.append(gsy_note)
GIT_SYNC.update(pull=gsy_pull, push=gsy_push, update=gsy_update, public=gsy_public)
