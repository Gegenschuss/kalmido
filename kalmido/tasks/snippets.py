"""2.35.0 (#1095): code snippets of a task -- plain code (no Markdown) with a language, an optional file path + line.

Stored as a JSON list in tasks.snippets ('' = none; a new column, older versions ignore it). Each snippet:
{id, lang, path, line, code, by, updated_at}. lang '' = the client recognises the language itself. The web client and
the API replace the whole list (PATCH ... {snippets: [...]}: a snippet sent with its id stays that snippet, its author and
time stay when nothing in it changed); POST /api/v1/tasks/<id>/snippets appends one (an agent stores a diff / a proposal).
Task events carry a shortened copy (snip_event), the full code comes with get_task."""
import json
import re
import secrets

from flask import jsonify

from ..core.config import app
from ..core.db import db, iso, now_utc
from ..core.i18n import tr
from ..accounts.session import me
from ..api.v1 import _v1_live, v1_args, v1_call, v1_json, v1_one, v1_view

SNIP_MAX_N = 20            # snippets per task
SNIP_CODE_MAX = 20_000     # characters per snippet (the client highlights up to this length, HL_MAX)
SNIP_PATH_MAX = 300
SNIP_LINE_MAX = 10_000_000
SNIP_EVENT_N, SNIP_EVENT_CODE = 10, 4000   # in task events: at most this many snippets, code cut to this many characters
SNIP_LANG_RE = re.compile(r"^[a-z0-9+#.-]{0,20}$")
SNIP_ID_RE = re.compile(r"^[A-Za-z0-9]{1,16}$")


def snip_parse(raw):
    """The stored column -> a list (broken / empty -> [])."""
    if not raw:
        return []
    try:
        v = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return [s for s in v if isinstance(s, dict) and isinstance(s.get("code"), str)] if isinstance(v, list) else []


def snip_clean(v):
    """Client / API value -> the JSON to store ('' for none); raises BadInput. New snippets get an id, every snippet
    the writer as author and now as time (snip_keep restores both for unchanged ones)."""
    from ..personal.timetrack import BadInput
    if v in (None, "", []):
        return ""
    bad = lambda what: BadInput(tr("Invalid value: {0}", what))  # noqa: E731
    if not isinstance(v, list):
        raise bad("snippets")
    if len(v) > SNIP_MAX_N:
        raise BadInput(tr("At most {0} code snippets per task", SNIP_MAX_N))
    out, ids, ts = [], set(), iso(now_utc())
    for s in v:
        if not isinstance(s, dict) or not isinstance(s.get("code"), str):
            raise bad("snippets")
        unknown = set(s) - {"id", "lang", "path", "line", "code", "by", "updated_at", "truncated"}
        if unknown:
            raise bad("snippets." + sorted(unknown)[0])
        code = s["code"].replace("\r\n", "\n")
        if len(code) > SNIP_CODE_MAX:
            raise BadInput(tr("A code snippet can have at most {0} characters", SNIP_CODE_MAX))
        if s.get("truncated"):  # a shortened copy from an event must not overwrite the full code
            raise bad("snippets.truncated")
        lang = str(s.get("lang") or "").strip().lower()
        if not SNIP_LANG_RE.match(lang):
            raise bad("snippets.lang")
        path = s.get("path")
        if path is not None and not isinstance(path, str):
            raise bad("snippets.path")
        path = (path or "").strip()
        if len(path) > SNIP_PATH_MAX or any(ch in path for ch in "\n\r\t\0"):
            raise bad("snippets.path")
        line = s.get("line")
        if line in ("", None):
            line = None
        elif isinstance(line, bool) or not isinstance(line, (int, str)) or not str(line).isdigit() \
                or not 1 <= int(line) <= SNIP_LINE_MAX:
            raise bad("snippets.line")
        else:
            line = int(line)
        sid = s.get("id")
        if not (isinstance(sid, str) and SNIP_ID_RE.match(sid)) or sid in ids:
            sid = secrets.token_hex(4)
        ids.add(sid)
        if not code.strip() and not path:
            continue  # an empty new snippet is not kept
        out.append({"id": sid, "lang": lang, "path": path or None, "line": line, "code": code, "by": me(), "updated_at": ts})
    return json.dumps(out, ensure_ascii=False, separators=(",", ":")) if out else ""


def snip_keep(new_raw, old_raw):
    """Unchanged snippets (same id, language, path, line and code) keep their author and time."""
    if not new_raw or not old_raw:
        return new_raw
    old = {s.get("id"): s for s in snip_parse(old_raw)}
    out = []
    for s in snip_parse(new_raw):
        o = old.get(s["id"])
        if o and all(o.get(k) == s.get(k) for k in ("lang", "path", "line", "code")):
            s = {**s, "by": o.get("by"), "updated_at": o.get("updated_at")}
        out.append(s)
    return json.dumps(out, ensure_ascii=False, separators=(",", ":"))


def snip_out(raw):
    return [{k: s.get(k) for k in ("id", "lang", "path", "line", "code", "by", "updated_at")} for s in snip_parse(raw)]


def snip_event(raw):
    """The shortened copy for task events: at most SNIP_EVENT_N snippets, code cut to SNIP_EVENT_CODE characters."""
    out = []
    for s in snip_out(raw)[:SNIP_EVENT_N]:
        if len(s["code"]) > SNIP_EVENT_CODE:
            s = {**s, "code": s["code"][:SNIP_EVENT_CODE], "truncated": True}
        out.append(s)
    return out


@app.post("/api/v1/tasks/<int:tid>/snippets")
@v1_view
def v1_snippet_add(tid):
    """2.35.0 (#1095): appends one snippet {code, lang?, path?, line?} (scope write; whoever may change the task)."""
    from ..personal.timetrack import BadInput
    from ..tasks.tasks import task_update
    v1_args(())
    c = db()
    _v1_live(c, tid)
    b = v1_json()
    if set(b) - {"code", "lang", "path", "line"}:
        raise BadInput(tr("Invalid value: {0}", sorted(set(b) - {"code", "lang", "path", "line"})[0]))
    if not isinstance(b.get("code"), str) or not b["code"].strip():
        raise BadInput(tr("Invalid value: {0}", "code"))
    have = snip_out(c.execute("SELECT snippets FROM tasks WHERE id=?", (tid,)).fetchone()[0])
    if len(have) >= SNIP_MAX_N:
        raise BadInput(tr("At most {0} code snippets per task", SNIP_MAX_N))
    sid = secrets.token_hex(4)
    v1_call(task_update, tid, body={"snippets": have + [{**b, "id": sid}]})
    t = v1_one(c, tid)
    r = jsonify(snippet=next((s for s in t.get("snippets") or [] if s["id"] == sid), None), task=t)
    r.status_code = 201
    return r


def snip_tpl(v):
    """Templates (2.35.0): the snippets of a template node as {lang, path, line, code} (invalid ones: none)."""
    try:
        raw = snip_clean(v if isinstance(v, list) else snip_parse(v) if isinstance(v, str) else None)
    except Exception:  # noqa: BLE001 -- a broken template node simply has no snippets
        return []
    return [{k: s[k] for k in ("lang", "path", "line", "code")} for s in snip_parse(raw)]


def snip_sig(v):
    """2.35.0: what a snippet list says (for the conflict check of undo / offline replays); None, '' and [] are the same."""
    lst = snip_parse(v) if isinstance(v, str) or v is None else [s for s in v if isinstance(s, dict)] if isinstance(v, list) else []
    return json.dumps([[s.get("id"), s.get("lang") or "", s.get("path") or None, s.get("line"), s.get("code")] for s in lst])
