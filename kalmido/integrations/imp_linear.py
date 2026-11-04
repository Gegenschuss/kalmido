"""2.394.0 A (#3377): import from Linear -- with the person's own API key (GraphQL, read only) or from Linear's CSV export.

Both ways end in the neutral plan of integrations/importers.py (preview = dry run, undo 24 h, limits, rate limit there).
The key: sent only to Linear's fixed address, only for the one request it came with (the preview asks again), never
stored, logged, written into the import record or repeated in an error text. KALMIDO_LINEAR_API may point the fetch at a
fake Linear on this machine for tests (http://127.0.0.1 / localhost only; anything else is ignored -- no request to an
address someone chose). Teams become projects (like Jira's projects), issues tasks: title, description, status (completed
= done, canceled = cancelled, a started state as a note), priority, estimate (story points), labels (tags; Bug /
Feature / Improvement also set the ticket type), cycle (a sprint, see imp_sprint), assignee, due date, parent issue,
comments (a notes block, as the other importers keep comments)."""
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from ..core.config import APP_NAME, APP_VERSION
from ..core.i18n import N_, tr
from ..core.db import iso, now_utc
from ..lists.lists import LIST_NAME_MAX
from ..calendars.subscriptions import _cal_opener, CalError
from .importers import (
    imp_addnote, imp_anydate, imp_csv, imp_decode, imp_done, imp_fail, imp_iso, imp_line, imp_list, imp_points, imp_prio_any,
    imp_stem, imp_tags, imp_task, imp_textblock, imp_ts, imp_ttype, imp_warn, IMPORT_FETCHERS, IMPORT_MAX_TASKS, IMPORT_PARSERS,
)

LINEAR_API = "https://api.linear.app/graphql"
LIN_PAGE = 50                 # issues per request (each with up to LIN_COMMENTS comments and LIN_LABELS labels)
LIN_COMMENTS = 30
LIN_LABELS = 25
LIN_TIMEOUT = 25              # seconds per request
LIN_DEADLINE = 150            # seconds for the whole fetch (a bigger workspace: Linear's CSV export)
LIN_MAX_BYTES = 8 * 1048576   # one answer at most
LIN_KEY_MAX = 300
# Linear's priority: 0 none, 1 urgent, 2 high, 3 medium, 4 low -> the levels here (the two top ones are high, as imp_prio_any)
LIN_PRIO = {0: 0, 1: 5, 2: 5, 3: 3, 4: 1}
LIN_QUERY = """query KalmidoImport($after: String) {
  issues(first: %d, after: $after) {
    nodes {
      identifier title description priority estimate dueDate createdAt completedAt canceledAt url
      state { name type }
      team { name key }
      project { name }
      labels(first: %d) { nodes { name } }
      assignee { name displayName email }
      cycle { name number }
      parent { identifier }
      comments(first: %d) { nodes { body createdAt user { name displayName } } }
    }
    pageInfo { hasNextPage endCursor }
  }
}""" % (LIN_PAGE, LIN_LABELS, LIN_COMMENTS)


def lin_api():
    """-> (address, hosts allowed besides public ones). Only a local test address may replace Linear's."""
    u = os.environ.get("KALMIDO_LINEAR_API", "").strip()
    if u:
        p = urllib.parse.urlsplit(u)
        if p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost") and not p.username and not p.password:
            return u, frozenset({(p.hostname, None)})
    return LINEAR_API, frozenset()


def lin_errcode(raw):
    """The extension codes of a GraphQL error answer (never its message: that is Linear's text)."""
    try:
        j = json.loads(raw)
    except (ValueError, RecursionError, UnicodeDecodeError):
        return set()
    errs = j.get("errors") if isinstance(j, dict) else None
    out = set()
    for e in errs if isinstance(errs, list) else []:
        ext = e.get("extensions") if isinstance(e, dict) else None
        if isinstance(ext, dict):
            out.add(str(ext.get("code") or "").upper())
            out.add(str(ext.get("type") or "").upper())
    return out


def lin_refused(codes, status=None):
    if status == 429 or "RATELIMITED" in codes:
        imp_fail(N_("Linear is limiting requests right now, please try again in a few minutes"))
    if status in (401, 403) or codes & {"AUTHENTICATION_ERROR", "AUTHENTICATION ERROR", "FORBIDDEN", "UNAUTHENTICATED"}:
        imp_fail(N_("Linear did not accept the API key (check that it is complete and not revoked)"))


def lin_post(url, allow, key, after, deadline):
    """One page of issues -> the decoded answer. Every failure is one of our own texts (no answer text, no key)."""
    left = deadline - time.monotonic()
    if left < 1:
        imp_fail(N_("Linear took too long to answer; for a big workspace use Linear's CSV export instead"))
    req = urllib.request.Request(url, data=json.dumps({"query": LIN_QUERY, "variables": {"after": after}}).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Accept": "application/json", "Authorization": key,
                                          "User-Agent": f"{APP_NAME}/{APP_VERSION} (Linear import)"})
    try:
        r = _cal_opener(allow).open(req, timeout=min(LIN_TIMEOUT, left))
    except urllib.error.HTTPError as e:
        code = e.code
        try:
            raw = e.read(65536)
        except (OSError, http.client.HTTPException):
            raw = b""
        e.close()
        lin_refused(lin_errcode(raw), code)
        imp_fail(N_("Linear could not be read (error {0})"), code)
    except (CalError, OSError, ValueError, http.client.HTTPException):
        imp_fail(N_("Linear could not be reached, please try again later"))
    try:
        with r:
            raw = r.read(LIN_MAX_BYTES + 1)
    except (OSError, http.client.HTTPException):
        imp_fail(N_("Linear could not be reached, please try again later"))
    if len(raw) > LIN_MAX_BYTES:
        imp_fail(N_("Linear sent more data than an import takes"))
    lin_refused(lin_errcode(raw))
    try:
        j = json.loads(raw)
    except (ValueError, RecursionError, UnicodeDecodeError):
        j = None
    data = j.get("data") if isinstance(j, dict) else None
    iss = data.get("issues") if isinstance(data, dict) else None
    if not isinstance(iss, dict) or not isinstance(iss.get("nodes"), list):
        imp_fail(N_("Linear sent an answer that could not be read"))
    return iss


def lin_fetch(key, opts, plan):  # noqa: ARG001 (the fetcher signature of IMPORT_FETCHERS)
    """IMPORT_FETCHERS["linear"]: every issue the key can read, page by page, into the plan."""
    if len(key) > LIN_KEY_MAX or any(ord(ch) < 33 or ord(ch) > 126 for ch in key):
        imp_fail(N_("This is not a Linear API key"))
    url, allow = lin_api()
    deadline, after, lists, out = time.monotonic() + LIN_DEADLINE, None, {}, []
    for _ in range(IMPORT_MAX_TASKS // LIN_PAGE + 2):
        page = lin_post(url, allow, key, after, deadline)
        for it in page["nodes"]:
            if isinstance(it, dict):
                lin_api_issue(plan, lists, out, it)
        info = page.get("pageInfo") if isinstance(page.get("pageInfo"), dict) else {}
        after = info.get("endCursor")
        if not info.get("hasNextPage") or not isinstance(after, str) or not after:
            break
    lin_parents(plan, out)


def _d(v):
    return v if isinstance(v, dict) else {}


def _nodes(v):
    n = _d(v).get("nodes")
    return [x for x in n if isinstance(x, dict)] if isinstance(n, list) else []


def lin_api_issue(plan, lists, out, it):
    st = _d(it.get("state"))
    a = _d(it.get("assignee"))
    cy = _d(it.get("cycle"))
    cycle = imp_line(cy.get("name"), 100) or (tr("Cycle {0}", cy["number"]) if isinstance(cy.get("number"), (int, float)) else "")
    comments = []
    for x in sorted(_nodes(it.get("comments")), key=lambda x: str(x.get("createdAt") or "")):
        u = _d(x.get("user"))
        comments.append((imp_line(u.get("displayName") or u.get("name") or "", 100), imp_ts(x.get("createdAt")), x.get("body")))
    lin_task(plan, lists, out, {
        "ident": it.get("identifier"), "title": it.get("title"), "desc": it.get("description"), "state": st.get("name"),
        "type": str(st.get("type") or "").lower(), "prio": LIN_PRIO.get(it.get("priority"), 0) if type(it.get("priority")) in (int, float) else 0,
        "estimate": it.get("estimate"), "labels": [x.get("name") for x in _nodes(it.get("labels"))], "cycle": cycle,
        "assignee": {"name": imp_line(a.get("name") or a.get("displayName"), 200), "email": imp_line(a.get("email"), 200)} if a else None,
        "due": imp_iso(it.get("dueDate"))[0], "parent": _d(it.get("parent")).get("identifier"), "created": imp_ts(it.get("createdAt")),
        "done_at": imp_ts(it.get("completedAt") or it.get("canceledAt")), "url": it.get("url"), "team": _d(it.get("team")).get("name")
        or _d(it.get("team")).get("key"), "project": _d(it.get("project")).get("name"), "comments": comments})


def lin_task(plan, lists, out, d):
    """One issue (API or CSV, the same fields) -> a task of its team's project."""
    title, ident = imp_line(d["title"]), imp_line(d["ident"], 100)
    if not title or not ident:
        return
    ln = imp_line(d["team"], LIST_NAME_MAX) or "Linear"
    L = lists.get(ln) or lists.setdefault(ln, imp_list(plan, ln))
    status = {"completed": 2, "canceled": -1, "cancelled": -1}.get(d["type"], 0)
    labels = [imp_line(x, 100) for x in d["labels"] if imp_line(x, 100)]
    url = imp_line(d["url"], 2000)
    t = imp_task(L, ident, title, due=d["due"], tags=list(dict.fromkeys(labels))[:50], priority=d["prio"] or 0, status=status,
                 created_at=d["created"], completed_at=(d["done_at"] or iso(now_utc())) if status else None,
                 url=url if url.startswith("https://") else None, assignee=d["assignee"] if d["assignee"] and any(d["assignee"].values()) else None)
    t["ttype"] = next((imp_ttype(x) for x in labels if imp_ttype(x) in ("bug", "feature")), "")
    imp_addnote(t, "Linear: " + ident)
    imp_addnote(t, d["desc"])
    lines = []
    if not status and d["type"] not in ("", "unstarted", "backlog", "triage") and imp_line(d["state"], 100):
        lines.append(tr("Status ({0}): {1}", "Linear", imp_line(d["state"], 100)))
    if imp_line(d.get("prio_text"), 100):
        lines.append(f"{tr('Priority')}: {imp_line(d['prio_text'], 100)}")
    if imp_line(d["project"], 200):
        lines.append(f"{tr('Project')}: {imp_line(d['project'], 200)}")
    if lines:
        imp_addnote(t, "\n".join(lines))
    imp_points(t, d["estimate"], tr("Estimate"))
    t["sprint"] = imp_line(d["cycle"], 100) or None
    cm = []
    for who, at, body in d["comments"]:
        text, head = imp_textblock(body, 20000), " · ".join(x for x in (who, (at or "")[:10]) if x)
        if text:
            cm.append(f"**{head}**\n{text}" if head else text)
    if cm:
        imp_addnote(t, tr("Comments ({0}):", "Linear") + "\n" + "\n\n".join(cm))
    out.append((t, imp_line(d["parent"], 100)))


def lin_parents(plan, out):
    known = {t["ext"] for t, _p in out}
    for t, p in out:
        if p:
            if p in known and p != t["ext"]:
                t["parent"] = p
            else:
                imp_warn(plan, N_("Parent task not found, imported as a main task"), t["title"])


# ---- Linear's CSV export (Settings > Workspace > Import / export > Export CSV)
LIN_CSV_KEYS = {"team", "cycle name", "cycle number", "parent issue", "estimate"}


def parse_linear(data, fname, opts, plan):  # noqa: ARG001
    keys, rows, _head = imp_csv(imp_decode(data, plan), plan)  # 2.533.0 (#4318) F8
    if not {"id", "title", "status"} <= set(keys) or not LIN_CSV_KEYS & set(keys):
        imp_fail(N_("This is not a Linear CSV export (columns ID, Title, Status and Team missing)"))
    lists, out = {}, []
    for r in rows:
        done_at, cancel_at = (r.get("completed") or "").strip(), (r.get("canceled") or "").strip()
        typ = "completed" if done_at else "canceled" if cancel_at else {2: "completed", -1: "canceled"}.get(imp_done(r.get("status")), "")
        if not typ and imp_line(r.get("status"), 100).lower() not in ("", "todo", "to do", "backlog", "triage", "open"):
            typ = "started"
        d, _tm = imp_anydate(r.get("due date"))
        pr = imp_prio_any(r.get("priority"))
        cyc = imp_line(r.get("cycle name"), 100) or (tr("Cycle {0}", imp_line(r.get("cycle number"), 20)) if imp_line(r.get("cycle number"), 20) else "")
        who = imp_line(r.get("assignee"), 200)
        lin_task(plan, lists, out, {
            "ident": r.get("id"), "title": r.get("title"), "desc": r.get("description"), "state": r.get("status"), "type": typ,
            "prio": pr or 0, "prio_text": "" if pr is not None else r.get("priority"), "estimate": r.get("estimate"), "labels": imp_tags(r.get("labels") or "", r","), "cycle": cyc,
            "assignee": ({"email": who} if "@" in who else {"name": who}) if who else None, "due": d,
            "parent": r.get("parent issue"), "created": imp_ts(r.get("created")), "done_at": imp_ts(done_at or cancel_at),
            "url": None, "team": r.get("team") or imp_stem(fname), "project": r.get("project"), "comments": []})
    lin_parents(plan, out)


IMPORT_PARSERS["linear"] = parse_linear
IMPORT_FETCHERS["linear"] = lin_fetch
