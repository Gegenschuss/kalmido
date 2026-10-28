"""2.390.0 (#3353): readable ticket keys "APP-123" for projects.

A project gets a key (lists.ticket_key: 2-6 capitals or digits, a letter first, unique per workspace = the organisation,
else the owner's private one) in the project dialog (owner / project admins). Its tasks get a running number
(tasks.ticket_no): a new task and a task moved in get the next one (database trigger TICKET_NO_TRIGGER, core/schema.py, so
every way a task is made or moved counts), the tasks that were there before the key was set get theirs in the order they
were made. A task that leaves the project and a project whose key changes keep the old keys as aliases (task_keys): old
commits, links and texts still find the task. "#123" (the instance-wide id) stays valid everywhere.

Used by: the list dialog (PATCH /api/lists/<id> {ticket_key}), the Git matching (integrations/git.py: "APP-123" in
commits, pull requests, branch names "app-123-..."), the agent API (field "key", GET /api/v1/tasks/APP-123) and the search.
"""
import re

from flask import g, has_app_context

from ..core.db import iso, now_utc
from ..core.errors import BadInput
from ..core.i18n import tr

TK_RE = re.compile(r"[A-Z][A-Z0-9]{1,5}")
TK_FULL_RE = re.compile(r"([A-Za-z][A-Za-z0-9]{1,5})-(\d{1,9})")
_TK_UML = str.maketrans({"Ä": "A", "Ö": "O", "Ü": "U", "ä": "A", "ö": "O", "ü": "U", "ß": "S", "É": "E", "é": "E", "È": "E",
                         "è": "E", "À": "A", "à": "A", "Ç": "C", "ç": "C", "Ñ": "N", "ñ": "N"})


def tk_norm(v):
    """The key as stored (upper case, no spaces) or None for '' / None; BadInput for anything else."""
    if v is None:
        return None
    if not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", "ticket_key"))
    v = v.strip().upper()
    if not v:
        return None
    if not TK_RE.fullmatch(v):
        raise BadInput(tr("A project key has 2 to 6 capital letters or digits and starts with a letter (e.g. APP)"))
    return v


def tk_suggest(name):
    """A key for a project name: the initials of up to four words, else the first three letters ("Website relaunch" -> WR,
    "Kalmido" -> KAL). Always valid (falls back to PRJ)."""
    words = re.findall(r"[A-Za-z0-9]+", str(name or "").translate(_TK_UML))
    words = [w for w in words if w[0].isalpha()] or words
    k = "".join(w[0] for w in words[:4]).upper() if len(words) > 1 else (words[0][:3].upper() if words else "")
    if len(k) < 2 and words:
        k = words[0][:3].upper()
    return k if TK_RE.fullmatch(k) else "PRJ"


def _ws_where(org_id, owner_id):
    return ("org_id=?", org_id) if org_id else ("org_id IS NULL AND owner_id=?", owner_id)


def tk_taken(c, lid, key):
    """The other project of the same workspace that uses key (its name), else None."""
    r = c.execute("SELECT org_id, owner_id FROM lists WHERE id=?", (lid,)).fetchone()
    if not r:
        return None
    w, v = _ws_where(r["org_id"], r["owner_id"])
    x = c.execute(f"SELECT name FROM lists WHERE ticket_key=? AND id<>? AND {w}", (key, lid, v)).fetchone()
    return x["name"] if x else None


def tk_set(c, lid, key):
    """Sets / changes / removes (None) the key of list lid. The rights are the caller's job (owner / project admins).
    Old keys stay as aliases; tasks without a number get theirs in the order they were made. Returns the stored key."""
    key = tk_norm(key)
    old = c.execute("SELECT ticket_key FROM lists WHERE id=?", (lid,)).fetchone()
    if not old:
        return None
    old = old["ticket_key"]
    if key == old:
        return key
    if key and tk_taken(c, lid, key):
        raise BadInput(tr("The key {0} is already used by another project of this workspace", key))
    # the counter row first, locked until the commit: a task made meanwhile (trigger) waits and counts on from our end
    seq = c.execute("""INSERT INTO list_ticket_seq(list_id, seq) VALUES(?, 0) ON CONFLICT (list_id) DO UPDATE
                       SET seq=list_ticket_seq.seq RETURNING seq""", (lid,)).fetchone()[0]
    if old:  # the old keys keep finding their tasks
        c.execute("""INSERT INTO task_keys(prefix, no, task_id, list_id, created_at) SELECT ?, ticket_no, id, list_id, ? FROM tasks
                     WHERE list_id=? AND ticket_no IS NOT NULL ON CONFLICT DO NOTHING""", (old, iso(now_utc()), lid))
    c.execute("UPDATE lists SET ticket_key=? WHERE id=?", (key, lid))
    if key:
        seq = max(seq, c.execute("SELECT COALESCE(MAX(ticket_no), 0) FROM tasks WHERE list_id=?", (lid,)).fetchone()[0])
        n = c.execute("""UPDATE tasks t SET ticket_no=? + s.rn FROM (SELECT id, row_number() OVER (ORDER BY created_at, id) AS rn
                         FROM tasks WHERE list_id=? AND ticket_no IS NULL) s WHERE t.id=s.id""", (seq, lid)).rowcount
        c.execute("UPDATE list_ticket_seq SET seq=GREATEST(seq, ?) WHERE list_id=?", (seq + max(n, 0), lid))
    _tk_cache().pop(lid, None)
    return key


def _tk_cache():
    if not has_app_context():
        return {}
    if "tk_keys" not in g:
        g.tk_keys = {}
    return g.tk_keys


def tk_list_key(c, lid):
    """The key of list lid (None = none), cached for the request."""
    if not lid:
        return None
    cache = _tk_cache()
    if lid not in cache:
        r = c.execute("SELECT ticket_key FROM lists WHERE id=?", (lid,)).fetchone()
        cache[lid] = r["ticket_key"] if r else None
    return cache[lid]


def tk_key(c, r):
    """The key "APP-12" of a task row / dict (None without a key)."""
    no = r["ticket_no"] if "ticket_no" in r.keys() else None
    if not no:
        return None
    k = tk_list_key(c, r["list_id"])
    return f"{k}-{no}" if k else None


def tk_parse(text):
    """("APP", 12) of a whole key "APP-12" / "app-12" (upper-cased), else None."""
    m = TK_FULL_RE.fullmatch(str(text or "").strip())
    return (m.group(1).upper(), int(m.group(2))) if m else None


def tk_find(c, pairs, lids=None):
    """The ids of live tasks with one of the keys pairs [(prefix, no)] -- their current key or an old one (alias); only
    in the lists lids when given. The caller checks what the reader may see."""
    pairs = sorted(set(pairs))[:200]
    if not pairs:
        return set()
    lw, la = "", ()
    if lids is not None:
        lids = sorted({lids} if isinstance(lids, int) else set(lids))
        if not lids:
            return set()
        lw, la = f" AND t.list_id IN ({','.join('?' * len(lids))})", tuple(lids)
    out = set()
    for p, n in pairs:
        out |= {r[0] for r in c.execute(f"""SELECT t.id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE l.ticket_key=? AND t.ticket_no=?
                                            AND t.deleted_at IS NULL{lw}""", (p, n, *la))}
        out |= {r[0] for r in c.execute(f"""SELECT t.id FROM task_keys k JOIN tasks t ON t.id=k.task_id WHERE k.prefix=? AND k.no=?
                                            AND t.deleted_at IS NULL{lw}""", (p, n, *la))}
    return out


def tk_ids_ordered(c, pair):
    """The live tasks with key pair (prefix, no): the ones that have it now first, then the ones that had it, each by id."""
    p, n = pair
    now = [r[0] for r in c.execute("""SELECT t.id FROM tasks t JOIN lists l ON l.id=t.list_id WHERE l.ticket_key=? AND t.ticket_no=?
                                      AND t.deleted_at IS NULL ORDER BY t.id""", (p, n))]
    old = [r[0] for r in c.execute("""SELECT t.id FROM task_keys k JOIN tasks t ON t.id=k.task_id WHERE k.prefix=? AND k.no=?
                                      AND t.deleted_at IS NULL ORDER BY t.id""", (p, n))]
    return now + [i for i in old if i not in now]


def tk_prefixes(c, lids):
    """The keys (current and old) of the tasks of the lists lids: what the Git matching looks for."""
    lids = sorted({lids} if isinstance(lids, int) else set(lids or ()))
    if not lids:
        return set()
    q = ",".join("?" * len(lids))
    out = {r[0] for r in c.execute(f"SELECT ticket_key FROM lists WHERE id IN ({q}) AND ticket_key IS NOT NULL", lids)}
    out |= {r[0] for r in c.execute(f"""SELECT DISTINCT k.prefix FROM task_keys k JOIN tasks t ON t.id=k.task_id
                                        WHERE t.list_id IN ({q})""", lids)}
    return out


def tk_has_key(c, lids):
    """True when one of the lists lids has a key of its own (then "#123" counts only with the repository's switch)."""
    lids = sorted({lids} if isinstance(lids, int) else set(lids or ()))
    return bool(lids) and bool(c.execute(f"SELECT 1 FROM lists WHERE id IN ({','.join('?' * len(lids))}) AND ticket_key IS NOT NULL LIMIT 1",
                                         lids).fetchone())


def tk_text_re(prefixes, branch=False):
    """A pattern for the keys of prefixes in a text: "APP-12" (also "app-12" in a branch name, where Git tools write lower
    case). None without prefixes."""
    if not prefixes:
        return None
    alt = "|".join(sorted((re.escape(p) for p in prefixes), key=len, reverse=True))
    return re.compile(rf"(?<![\w-])({alt})-(\d{{1,9}})\b", re.I if branch else 0)


def tk_text_pairs(text, rx, branch=False):
    if rx is None:
        return set()
    return {(p.upper(), int(n)) for p, n in rx.findall(text or "")} if branch else {(p, int(n)) for p, n in rx.findall(text or "")}
