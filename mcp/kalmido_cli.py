#!/usr/bin/env python3
"""2.630.0 (#4520): `kalmido`, a small command line for the Kalmido REST API (/api/v1) -- the common task commands from a
script or a terminal, the way you would use gh. Python 3 standard library only; it uses the HTTP client of kalmido_mcp.py
(next to this file: retries on 429 / 503, the rate limit headers, one Idempotency-Key per write), so it needs no package.

Configuration (environment, the same as the MCP server):
  KALMIDO_URL     base address of the instance, e.g. https://tasks.example.com
  KALMIDO_TOKEN   an API token (abk_...): Settings > Access; scopes read, tasks:write (add, done), comments (comment)

Commands (a task is its id 42 or its ticket key APP-12):
  kalmido_cli.py list [--project ID] [--status open|done|wont_do|all] [--assignee me|none|ID] [--search TEXT] [--limit N]
  kalmido_cli.py show TASK                     the task with its notes and comments
  kalmido_cli.py add TITLE [--project ID] [--notes TEXT|-] [--due YYYY-MM-DD] [--priority none|low|medium|high|urgent]
                                               (without --project: your inbox)
  kalmido_cli.py comment TASK TEXT|-           "-" reads the text from stdin
  kalmido_cli.py done TASK
  kalmido_cli.py docs WORDS... | --read KEY | --overview   the help of the server (2.1067.0, #5819): search, one section, overview
Every command takes --json: the API answer as JSON instead of the readable text.
Exit codes: 0 done, 1 the API refused or cannot be reached (the message on stderr), 2 wrong use / no configuration.
Tip: alias kalmido='python3 /path/to/kalmido_cli.py'. See mcp/README.md and docs/AGENTS.md."""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from kalmido_mcp import ApiError, Kalmido  # noqa: E402 -- the module only defines things on import

KEY_RX = re.compile(r"[A-Za-z][A-Za-z0-9]{1,5}-\d{1,9}")
PAGE = 100
PRIOS = ("none", "low", "medium", "high", "urgent")


class Usage(Exception):
    pass


def task_id(api, ref):
    """42, #42 or APP-12 -> the task id (a key is looked up: GET /tasks/APP-12)."""
    s = str(ref).strip().lstrip("#")
    if s.isdigit() and int(s) > 0:
        return int(s)
    if KEY_RX.fullmatch(s):
        return int(api.call("GET", f"/tasks/{s}")["id"])
    raise Usage(f"not a task id or ticket key: {ref!r} (e.g. 42 or APP-12)")


def _text(v):
    if v == "-":
        return sys.stdin.read().rstrip("\n")
    return v


def _label(t):
    return t.get("key") or f"#{t.get('id')}"


def _line(t):
    bits = [f"{_label(t):>9}", f"{t.get('status') or '':<7}"]
    if t.get("priority") and t["priority"] != "none":
        bits.append(f"[{t['priority']}]")
    if t.get("due"):
        bits.append(t["due"] + (" " + t["due_time"] if t.get("due_time") else ""))
    bits.append(t.get("title") or "")
    return "  ".join(bits)


def cmd_list(api, a):
    q = {"list_id": a.project, "status": a.status, "assignee": a.assignee, "q": a.search}
    out, cur = [], None
    while len(out) < a.limit:
        r = api.call("GET", "/tasks", {**q, "limit": min(PAGE, a.limit - len(out)), "cursor": cur})
        out += r.get("data") or []
        cur = r.get("next_cursor")
        if not cur:
            break
    if a.json:
        return {"data": out, "more": bool(cur)}
    if not out:
        return "no tasks"
    return "\n".join(_line(t) for t in out) + ("\n(more: raise --limit)" if cur else "")


def cmd_show(api, a):
    tid = task_id(api, a.task)
    t = api.call("GET", f"/tasks/{tid}")
    try:
        cm = api.call("GET", f"/tasks/{tid}/comments").get("data") or []
    except ApiError as e:  # comments off in that project: the task alone still helps
        cm, t["comments_error"] = [], e.message
    if a.json:
        return {**t, "comments": cm}
    rows = [f"{_label(t)}  {t.get('title') or ''}", f"  id {t.get('id')}  project {t.get('list_id')}  status {t.get('status')}"
            f"  priority {t.get('priority') or 'none'}"]
    if t.get("due"):
        rows.append(f"  due {t['due']}" + (f" {t['due_time']}" if t.get("due_time") else ""))
    if t.get("tags"):
        rows.append("  tags " + ", ".join("#" + x for x in t["tags"]))
    if (t.get("notes") or "").strip():
        rows += ["", t["notes"].rstrip()]
    if cm:
        rows += ["", f"Comments ({len(cm)}):"]
        for c in cm:
            who = (c.get("author") or {}).get("name") or "?"
            rows.append(f"- {who}, {(c.get('created_at') or '')[:16].replace('T', ' ')}: {c.get('text') or c.get('body') or ''}")
    elif t.get("comments_error"):
        rows += ["", f"(comments: {t['comments_error']})"]
    return "\n".join(rows)


def cmd_add(api, a):
    if not a.title.strip():
        raise Usage("the title is empty")
    b = {"title": a.title}
    if a.project:
        b["list_id"] = a.project
    if a.notes is not None:
        b["notes"] = _text(a.notes)
    if a.due:
        b["due"] = a.due
    if a.priority:
        b["priority"] = a.priority
    t = api.call("POST", "/tasks", body=b)
    return t if a.json else f"created {_label(t)}  {t.get('title') or ''}  (id {t.get('id')}, project {t.get('list_id')})"


def cmd_comment(api, a):
    tid = task_id(api, a.task)
    body = _text(a.text)
    if not body.strip():
        raise Usage("the comment is empty")
    c = api.call("POST", f"/tasks/{tid}/comments", body={"body": body})
    return c if a.json else f"comment {c.get('id')} added to #{tid}"


def cmd_done(api, a):
    tid = task_id(api, a.task)
    t = api.call("POST", f"/tasks/{tid}/complete")
    if a.json:
        return t
    if t.get("next_due"):
        return f"done {_label(t)}  {t.get('title') or ''}  (repeats: next on {t['next_due']})"
    return f"done {_label(t)}  {t.get('title') or ''}"


def cmd_docs(api, a):
    """2.1067.0 (#5819): the help of the server -- search (words), one section (--read KEY) or the overview."""
    if a.overview:
        r = api.call("GET", "/help")
        if a.json:
            return r
        rows = [f"Kalmido {r.get('version') or ''} - features per area:"]
        for ar in r.get("features") or []:
            rows += [f"{ar['area']}  ({ar['key']})"] + [f"  - {x}" for x in ar.get("items") or []]
        rows += ["", "Help files (read a section: docs --read KEY):"]
        for f in r.get("files") or []:
            rows.append(f"{f['key']:<16} {f['title']}")
        return "\n".join(rows)
    if a.read:
        r = api.call("GET", "/help/section", {"key": a.read})
        if a.json:
            return r
        more = ["", "(truncated; parts: " + ", ".join(p["key"] for p in r["parts"]) + ")"] if r.get("truncated") else []
        return "\n".join([" > ".join(r.get("path") or []), "", r.get("text") or ""] + more)
    q = " ".join(a.words).strip()
    if not q:
        raise Usage("give words to search for, --read KEY or --overview")
    r = api.call("GET", "/search", {"kind": "help", "q": q, "limit": a.limit})
    if a.json:
        return r
    hits = r.get("data") or []
    if not hits:
        return "nothing in the help"
    return "\n".join(f"{h['key']}\n  {' > '.join(h.get('path') or [])}\n  {h.get('snippet') or ''}" for h in hits)


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="print the API answer as JSON")
    ap = argparse.ArgumentParser(prog="kalmido", parents=[common],
                                 description="Kalmido from the command line. Needs KALMIDO_URL and KALMIDO_TOKEN in the environment.")
    ap.add_argument("--url", default=None, help="instead of KALMIDO_URL")
    sub = ap.add_subparsers(dest="cmd", metavar="COMMAND")
    sub.required = True
    p = sub.add_parser("list", parents=[common], help="list tasks")
    p.add_argument("--project", type=int, help="only this project (its id)")
    p.add_argument("--status", choices=("open", "done", "wont_do", "all"), help="default open")
    p.add_argument("--assignee", help="me, none or a user id")
    p.add_argument("--search", help="words in the title or notes")
    p.add_argument("--limit", type=int, default=50, help="at most this many tasks (default 50)")
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("show", parents=[common], help="one task with its comments")
    p.add_argument("task", help="id or ticket key (APP-12)")
    p.set_defaults(fn=cmd_show)
    p = sub.add_parser("add", parents=[common], help="create a task (default: your inbox)")
    p.add_argument("title")
    p.add_argument("--project", type=int, help="the project id (default: your inbox)")
    p.add_argument("--notes", help="Markdown; - = from stdin")
    p.add_argument("--due", help="YYYY-MM-DD")
    p.add_argument("--priority", choices=PRIOS)
    p.set_defaults(fn=cmd_add)
    p = sub.add_parser("comment", parents=[common], help="comment on a task")
    p.add_argument("task", help="id or ticket key (APP-12)")
    p.add_argument("text", help="Markdown; - = from stdin")
    p.set_defaults(fn=cmd_comment)
    p = sub.add_parser("done", parents=[common], help="complete a task")
    p.add_argument("task", help="id or ticket key (APP-12)")
    p.set_defaults(fn=cmd_done)
    p = sub.add_parser("docs", parents=[common], help="search or read the help of the server (2.1067.0)")
    p.add_argument("words", nargs="*", help="words to search for (English works best)")
    p.add_argument("--read", metavar="KEY", help="one section by its key (from a search hit)")
    p.add_argument("--overview", action="store_true", help="the feature list per area and the help files")
    p.add_argument("--limit", type=int, default=8, help="at most this many hits (1-20, default 8)")
    p.set_defaults(fn=cmd_docs)
    return ap


def main(argv=None, out=None, err=None):
    out, err = out or sys.stdout, err or sys.stderr
    a = parser().parse_args(argv)
    a.json = getattr(a, "json", False)
    if getattr(a, "limit", 1) < 1:
        print("kalmido: --limit must be at least 1", file=err)
        return 2
    url, token = a.url or os.environ.get("KALMIDO_URL", ""), os.environ.get("KALMIDO_TOKEN", "")
    if not url or not token:
        print("kalmido: KALMIDO_URL and KALMIDO_TOKEN must be set (an API token: Settings > Access)", file=err)
        return 2
    api = Kalmido(url, token)
    try:
        r = a.fn(api, a)
    except Usage as e:
        print(f"kalmido: {e}", file=err)
        return 2
    except ApiError as e:
        hint = " (check KALMIDO_TOKEN: missing, revoked or expired)" if e.status == 401 else \
            " (the token lacks the scope for this, or no access)" if e.status == 403 else ""
        print(f"kalmido: {e.message}{hint}", file=err)
        return 1
    print(json.dumps(r, ensure_ascii=False, indent=2) if a.json else r, file=out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
