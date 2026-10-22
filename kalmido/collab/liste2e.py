"""2.64.1 (#1817): the lock per list -- texts of a list encrypted in the browser (stage 1 of the browser encryption).

Built on the person's key base of 2.42 (collab/e2e.py: ECDH P-256 key pair + content key, passphrase, recovery code); nothing
of it is replaced. The browser does all cryptography (static/js/liste2e.js); this server never sees a list key or a plain text
of a locked list.

Key model:
- Per list and generation a random 256-bit list key (AES-GCM). The browser wraps it for every member: ECDH(private key of the
  wrapper, public key of the member) -> HKDF-SHA256(salt "<list_id>:<gen>", info "kalmido-listkey:v1") -> AES-256-GCM, AAD
  "kalmido-listkey:v1:<list_id>:<gen>:<recipient>:<wrapper>". Stored: list_keys (wrapped {v, iv, ct}, wrapped_by, wrapper_pub).
- Texts: AES-256-GCM with the list key of generation g, AAD "kalmido-list:v1:<list_id>:<gen>:<field>" (no task id, so the
  server may copy a ciphertext within the list -- repeating tasks; it may therefore also swap two ciphertexts of the same
  list and field: an integrity, not a confidentiality loss, finding M1). The plain text is padded to steps of 64 bytes
  (finding L1). The value stored in the existing text column is "e2e1:" + JSON {"v": 1, "g": gen, "iv", "ct"}.
- Encrypted fields (field name in the AAD): tasks.title "title", tasks.content "content", tasks.url "url", tasks.snippets
  "snippets", comments.body "comment", notes.title "note_title", notes.body "note_body", sections.name "section", text values
  of custom fields task_field_values.value "field" (only fields of type text; select / number / date stay readable, decision E2).
- Readable stay: dates, status, priority, order, section ids, assignees, list name, tags, timestamps, lengths (finding L1: padded).

lists.e2e: NULL (open) | 'encrypting' (switching on: the browser re-writes every text, others may not write texts) | 'on' |
'decrypting' (the way back). Members without a key of the current generation wait in list_key_pending (trigger
list_e2e_members, core/schema.py). A member who leaves sets e2e_rotate (rotation pending; the rotation itself is 2.64b).

The limit of a web app: this protects against a reader of the database, the backups and the operator -- not against a changed
script delivered by the server itself, and not against members who saw the texts.

This module: the helpers every other module uses (no routes here; the routes are added below by part A)."""
import json
import re

from ..core.i18n import N_, tr
from ..core.errors import BadInput  # 2.149.0 G (#2517): pulled up from functions
from ..core.access import collab_all, ov_open  # 2.149.0 G (#2517): pulled up from functions

LE2E_PREFIX = "e2e1:"
LE2E_MODES = ("encrypting", "on", "decrypting")
LE2E_FIELDS = ("title", "content", "url", "snippets", "comment", "note_title", "note_body", "section", "field")
LE2E_B64 = re.compile(r"^[A-Za-z0-9+/=_-]*$")
LE2E_CT_MAX = 600_000  # characters of one ciphertext (base64): ~400 KB of text (CONTENT_MAX is 200 000 characters)
LE2E_NEUTRAL = N_("🔒 Task")  # decision E6: what server texts (push, mail, CalDAV, time entries) show instead of a locked title


def le2e_is_cipher(v):
    """Does the stored text look like a ciphertext of a locked list ("e2e1:...")?"""
    return isinstance(v, str) and v.startswith(LE2E_PREFIX)


def le2e_parse(v, max_ct=LE2E_CT_MAX):
    """A ciphertext "e2e1:{v, g, iv, ct}" -> the dict, else None. Only the shape is checked: the server cannot (and must not)
    read it."""
    if not le2e_is_cipher(v):
        return None
    try:
        d = json.loads(v[len(LE2E_PREFIX):])
    except ValueError:
        return None
    if not isinstance(d, dict) or set(d) != {"v", "g", "iv", "ct"} or d.get("v") != 1:
        return None
    g = d.get("g")
    if isinstance(g, bool) or not isinstance(g, int) or g < 1:
        return None
    for k, lo, hi in (("iv", 12, 24), ("ct", 16, max_ct)):
        x = d.get(k)
        if not isinstance(x, str) or not lo <= len(x) <= hi or not LE2E_B64.match(x):
            return None
    return d


def le2e_mode(c, lid):
    """The lock state of list lid: None (open) | 'encrypting' | 'on' | 'decrypting'."""
    if not lid:
        return None
    r = c.execute("SELECT e2e FROM lists WHERE id=?", (lid,)).fetchone()
    return (r[0] or None) if r else None


def le2e_modes(c, lids):
    """{list_id: mode} of the lists in lids that are not open."""
    out, lids = {}, [x for x in set(lids or []) if x]
    for i in range(0, len(lids), 5000):
        part = lids[i:i + 5000]
        for r in c.execute(f"SELECT id, e2e FROM lists WHERE e2e IS NOT NULL AND id IN ({','.join('?' * len(part))})", part):
            out[r[0]] = r[1]
    return out


def le2e_task_mode(c, tid):
    """The lock state of the list of task tid (None: open or no such task)."""
    r = c.execute("SELECT l.e2e FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (tid,)).fetchone()
    return (r[0] or None) if r else None


def le2e_open_sql(alias="l"):
    """SQL condition: the list (table alias) has no lock -- for searches, digests, feeds that read texts on the server."""
    return f"{alias}.e2e IS NULL"


def le2e_neutral(lg=None):
    """2.64.2 D (#1817): lg = the recipient's language (background pushes have no request language)."""
    return tr(LE2E_NEUTRAL, lg=lg) if lg else tr(LE2E_NEUTRAL)


def le2e_show(v, lg=None):
    """A text for server output (push, mail, CalDAV, time entries, news): a ciphertext becomes the neutral word."""
    return le2e_neutral(lg) if le2e_is_cipher(v) else v


# ================================================================ part A: write guard, routes, memberships (2.64.1, #1817)
from flask import g, has_request_context, jsonify, request  # noqa: E402

from ..core.config import app  # noqa: E402
from ..core.db import body, bump, db, err, iso, now_utc  # noqa: E402
from ..core.access import Denied, need_list  # noqa: E402
from ..accounts.session import me  # noqa: E402

LE2A_MANAGE = ("owner", "admin")  # finding M9: who may switch the lock and hand out list keys
LE2A_BULK_MAX = 200               # values per bulk call (finding M6)
LE2A_KEYS_MAX = 200               # entries per start / keys call
LE2A_WRAP_MAX = 200               # characters of a wrapped list key (32 bytes + tag in base64)
LE2A_MSG = {
    "list_e2e": N_("This project is encrypted in the browser. Texts can only be changed in the app."),
    "list_e2e_busy": N_("This project is being encrypted. Try again in a moment."),
    "list_e2e_open": N_("Encrypted texts belong only in projects encrypted in the browser."),
    "list_e2e_api": N_("This project is encrypted in the browser: its texts are not available through the API or to agents."),
    "list_e2e_plain": N_("Not available in projects encrypted in the browser: this text would not be encrypted."),
    "list_e2e_move": N_("Tasks and notes move into or out of a project encrypted in the browser only in the app (their texts are encrypted anew)."),
}
LE2A_BLOCKERS = {
    "inbox": N_("The basket cannot be encrypted."),
    "agent": N_("Remove the agent from the project first: agents cannot read encrypted projects."),
    "public_link": N_("Remove the public link of the project first."),
    "org_open": N_("Turn off \"Everyone in the organisation\" for this project first."),
    "participant": N_("Change the role \"Participant\" first: projects encrypted in the browser have no participants."),
    "folder_participant": N_("A folder share with the role \"Participant\" reaches this project: change it first."),
    "note_lock": N_("Unlock the notes locked with a password in this project first."),
    "notepad": N_("Empty the notepads of this project first: they cannot be encrypted yet."),
    "owner_setup": N_("The owner needs to set up encryption first."),  # 2.64.1 review (M2)
    # 2.64.1 review (M3): lists the server itself writes texts into
    "family": N_("Projects of the Family module cannot be encrypted yet."),
    "life": N_("Projects of Home & life cannot be encrypted yet."),
    "generator": N_("Birthdays from an address book land in this project: choose another project for them first."),
}


class LE2EDenied(Denied):
    """A refused write of the lock per list: the answer carries a code for the app ({error, code})."""

    def __init__(self, code, status=409, msg=None, **extra):
        super().__init__(status, msg or tr(LE2A_MSG[code]))
        self.le2e, self.extra = code, extra


@app.errorhandler(LE2EDenied)
def le2a_denied(e):
    return jsonify(error=e.text(), code=e.le2e, **e.extra), e.code


def le2e_writer_ok():
    """May the current request write ciphertexts? Only a person signed in to the web app (no agent, no API token, no
    calendar app, no public link, no background job)."""
    if not has_request_context():
        return False
    u = g.get("user")
    if not u:
        return False
    from ..agents.core import is_agent
    return not is_agent(u) and g.get("auth_via") in ("session", "proxy")


def le2a_gen(c, lid):
    r = c.execute("SELECT e2e, e2e_gen FROM lists WHERE id=?", (lid,)).fetchone()
    return ((r[0] or None), int(r[1] or 0)) if r else (None, 0)


def le2a_value_ok(v, gen):
    """A stored value of a locked list: '' or a ciphertext of a generation up to gen."""
    if v in (None, ""):
        return True
    d = le2e_parse(v)
    return bool(d) and d["g"] <= gen


def le2e_guard(c, lid, values, source="app", cur=None):
    """THE write guard for the texts of list lid. values = {field (LE2E_FIELDS): value} that are about to be stored, cur = the
    stored values (unchanged values pass). Raises LE2EDenied (or returns None):
    - open list: no ciphertext (400, finding M8);
    - 'on': every text a ciphertext of a known generation or '' -- and only from a person in the web app (source "app");
    - 'encrypting' / 'decrypting': texts only through /e2e/bulk (409 busy)."""
    vals = {k: v for k, v in (values or {}).items() if not (cur is not None and k in cur and (cur[k] or "") == (v or ""))}
    if not vals:
        return None
    mode, gen = le2a_gen(c, lid)
    if mode is None:
        if any(le2e_is_cipher(v) for v in vals.values()):
            raise LE2EDenied("list_e2e_open", 400)
        return None
    if all(v in (None, "") for v in vals.values()):
        return None
    if mode != "on":
        raise LE2EDenied("list_e2e_busy")
    if source != "app" or not le2e_writer_ok():
        raise LE2EDenied("list_e2e", 403)
    if not all(le2a_value_ok(v, gen) for v in vals.values()):
        raise LE2EDenied("list_e2e")
    if any((le2e_parse(v) or {}).get("g", gen) < gen for v in vals.values() if v):
        le2a_reenc_again(c, lid)
    return None


def le2a_reenc_again(c, lid):
    """2.64.2 review (M2): a ciphertext of an older generation arrived after a key change (a tab that was not reloaded):
    the re-encryption is due again -- the honest hint comes back and the next owner / list admin's browser cleans it up."""
    c.execute("UPDATE lists SET e2e_reenc=e2e_gen WHERE id=? AND e2e='on' AND e2e_reenc=0 AND e2e_gen>1", (lid,))


def le2a_snip_cipher(raw):
    """tasks.snippets (jsonb text) -> the ciphertext when the column holds one (a JSON string), else None."""
    if isinstance(raw, str) and raw.startswith('"'):
        try:
            v = json.loads(raw)
        except ValueError:
            return None
        return v if le2e_is_cipher(v) else None
    return None


def le2a_task_texts(f):
    """The encrypted fields of a cleaned task change f ({title, content, url, snippets} -> values as the browser sent them)."""
    out = {k: f[k] for k in ("title", "content", "url") if k in f}
    if "snippets" in f:
        out["snippets"] = le2a_snip_cipher(f["snippets"]) or ("" if not f["snippets"] else f["snippets"])
    return out


def le2a_task_cur(row):
    out = {k: row[k] for k in ("title", "content", "url")}
    out["snippets"] = le2a_snip_cipher(row["snippets"]) or (row["snippets"] or "")
    return out


def le2a_task_create(c, lid, f):
    """POST /api/tasks: the texts of a new task in list lid (a ticket template is not added in a locked list)."""
    le2e_guard(c, lid, le2a_task_texts(f))


def le2a_moving(c, src, dst):
    """Does a move from list src to dst need the browser (one of them locked, keys differ)?"""
    if not src or not dst or src == dst:
        return False
    m = le2e_modes(c, [src, dst])
    return bool(m)


def le2a_task_write(c, tid, cur, f, b, lid):
    """apply_update (PATCH, batch, undo): the texts of task tid (row cur) written into list lid. A move into / out of /
    between locked lists needs every text of the moved subtree in the target format (browser, field le2e_move)."""
    if lid != cur["list_id"] and le2a_moving(c, cur["list_id"], lid):
        from .liste2efile import le2f_move_guard  # 2.64.2 B (#1817): list files stay in their list
        le2f_move_guard(c, tid, cur["list_id"], lid)
        return le2a_move(c, tid, cur, f, b.get("le2e_move"), lid)
    le2e_guard(c, lid, le2a_task_texts(f), cur=le2a_task_cur(cur))
    return None


def le2a_subtree(c, tid):
    ids, level = [tid], [tid]
    for _ in range(60):
        q = ",".join("?" * len(level))
        level = [r[0] for r in c.execute(f"SELECT id FROM tasks WHERE parent_id IN ({q})", level) if r[0] not in ids]
        if not level:
            break
        ids += level
    return ids


def le2a_move(c, tid, cur, f, extra, dst):
    """Finding M8: a move of task tid into / out of a locked list. f (the task's own change) must carry its non-empty texts in
    the target format; extra = {tasks: [{id, title, content, url, snippets}], comments: [{id, body}], fields: [{task_id,
    field_id, value}]} the texts of the subtasks, comments and text field values that move along. Writes those (the task's own
    texts are written by the caller) or raises LE2EDenied list_e2e_move with what is missing. Returns the function that writes
    them (called by apply_update right after the move, so a refused change writes nothing)."""
    from ..tasks.tasks import can_move
    if not le2e_writer_ok():
        raise LE2EDenied("list_e2e_move", 403)
    mode, gen = le2a_gen(c, dst)
    if mode not in (None, "on") or le2e_mode(c, cur["list_id"]) not in (None, "on"):
        raise LE2EDenied("list_e2e_busy")
    extra = extra if isinstance(extra, dict) else {}

    def ok(v):
        if v in (None, "", []):
            return True
        if isinstance(v, list):  # plain snippets as a list (open target)
            return mode is None
        return isinstance(v, str) and (le2a_value_ok(v, gen) if mode == "on" else not le2e_is_cipher(v))

    def given(key, idk):
        out = {}
        for x in extra.get(key) or []:
            if isinstance(x, dict):
                k = tuple(x.get(i) for i in idk) if isinstance(idk, tuple) else x.get(idk)
                out[k] = x
        return out
    need = {"tasks": [], "comments": [], "fields": []}
    gt, gc, gf = given("tasks", "id"), given("comments", "id"), given("fields", ("task_id", "field_id"))
    own = le2a_task_texts(f)
    # the task's own texts as fields of the change or (batch: one change for many tasks) in le2e_move.tasks
    mine = {k: v for k, v in (gt.get(tid) or {}).items() if k in ("title", "content", "url", "snippets") and k not in own}
    own = {**own, **mine}
    for k, v in le2a_task_cur(cur).items():
        if v and not (k in own and own[k] not in (None, "", []) and ok(own[k])):
            need["tasks"].append(tid)
            break
    ids = le2a_subtree(c, tid)
    writes, allowed, conv = ([("t", tid, mine)] if mine else []), {}, [tid]
    for r in c.execute(f"SELECT * FROM tasks WHERE id IN ({','.join('?' * len(ids))})", ids).fetchall():
        if r["id"] == tid or not le2a_moving(c, r["list_id"], dst):
            continue
        if r["list_id"] not in allowed:
            allowed[r["list_id"]] = can_move(c, r["list_id"], dst)
        if not allowed[r["list_id"]]:
            raise LE2EDenied("list_e2e_move")  # it would stay behind as a top-level task: not with the lock
        conv.append(r["id"])
        x, curv, upd = gt.get(r["id"]) or {}, le2a_task_cur(r), {}
        for k, v in curv.items():
            if not v:
                continue
            nv = x.get(k)
            if nv in (None, "", []) or not ok(nv):
                need["tasks"].append(r["id"])
                break
            upd[k] = nv
        else:
            if upd:
                writes.append(("t", r["id"], upd))
    ids = conv  # comments and field values of the tasks whose texts change format
    q = ",".join("?" * len(ids))
    for r in c.execute(f"SELECT id, body FROM comments WHERE task_id IN ({q}) AND COALESCE(body, '')<>''", ids).fetchall():
        nv = (gc.get(r["id"]) or {}).get("body")
        if not isinstance(nv, str) or not nv or not ok(nv):
            need["comments"].append(r["id"])
        else:
            writes.append(("c", r["id"], nv))
    for r in c.execute(f"""SELECT v.task_id, v.field_id, v.value FROM task_field_values v JOIN list_fields lf ON lf.id=v.field_id
                           WHERE v.task_id IN ({q}) AND lf.type='text' AND COALESCE(v.value, '')<>''""", ids).fetchall():
        nv = (gf.get((r["task_id"], r["field_id"])) or {}).get("value")
        if not isinstance(nv, str) or not nv or not ok(nv):
            need["fields"].append([r["task_id"], r["field_id"]])
        else:
            writes.append(("f", (r["task_id"], r["field_id"]), nv))
    if any(need.values()):
        raise LE2EDenied("list_e2e_move", need=need)
    if not all(ok(v) for v in own.values()):  # also texts the task did not have before
        raise LE2EDenied("list_e2e_open", 400) if mode is None else LE2EDenied("list_e2e")

    def post():
        for kind, key, v in writes:
            if kind == "t":
                le2a_task_set(c, key, v)
            elif kind == "c":
                c.execute("UPDATE comments SET body=? WHERE id=?", (v, key))
            else:
                c.execute("UPDATE task_field_values SET value=? WHERE task_id=? AND field_id=?", (v, *key))
        if mode == "on":
            # 2.64.1 review (L2): the waiting note is not encrypted (like finish: it goes)
            if ids:
                c.execute(f"UPDATE tasks SET wait_note='' WHERE id IN ({','.join('?' * len(ids))}) AND COALESCE(wait_note, '')<>''", ids)
            le2a_scrub_tasks(c, ids)
    return post


def le2a_scrub_tasks(c, ids):
    """Tasks that came into a locked list: what other tables kept of their plain texts goes (part B, liste2eguard)."""
    from .liste2eguard import le2b_scrub_tasks
    le2b_scrub_tasks(c, ids)


def le2a_task_set(c, tid, vals):
    """Writes encrypted / decrypted task texts as they are (no history, no trimming)."""
    sets, args = [], []
    for k, v in vals.items():
        if k == "snippets":
            v = le2a_snip_store(v)
        sets.append(f"{k}=?")
        args.append(v if k != "url" else (v or None))
    if sets:
        c.execute(f"UPDATE tasks SET {','.join(sets)} WHERE id=?", (*args, tid))


def le2a_snip_store(v):
    """A snippets value for the jsonb column: a ciphertext as a JSON string, a plain list (or its JSON text) as JSON, '' -> NULL."""
    if v in (None, "", []):
        return None
    if le2e_is_cipher(v):
        return json.dumps(v)
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            raise BadInput(tr("Invalid value: {0}", "snippets")) from None
    if not isinstance(v, list) or any(not isinstance(s, dict) or not isinstance(s.get("code"), str) for s in v):
        raise BadInput(tr("Invalid value: {0}", "snippets"))
    return json.dumps(v, ensure_ascii=False, separators=(",", ":")) if v else None


def le2a_comment_in(c, lid, text, tid=None):
    """A comment in a locked list: the body is a ciphertext (guarded); mentions come from the browser (mentions: [ids] or the
    form field "mentions" = "1,2"), only people of the list count."""
    from .comments import task_people
    le2e_guard(c, lid, {"comment": text})
    raw = request.form.get("mentions") if (request.files or request.form) else body().get("mentions")
    if isinstance(raw, str):
        raw = [x for x in raw.split(",") if x.strip()]
    ids = []
    for x in raw if isinstance(raw, list) else []:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    allowed = {p["id"] for p in task_people(c, lid, tid)} if collab_all() else set()  # 2.86.0 (N20 review)
    return text, list(dict.fromkeys(i for i in ids if i in allowed and i != me()))[:50]


def le2a_note_write(c, r, f):
    """PATCH /api/notes/<id>: the cleaned change f of note row r. A move into / out of / between locked lists needs title and
    body in the target format (the browser re-encrypts them), else 409 list_e2e_move."""
    dst = f.get("list_id", r["list_id"])
    vals = {k2: f[k] for k, k2 in (("title", "note_title"), ("body", "note_body")) if k in f}
    if dst != r["list_id"] and le2a_moving(c, r["list_id"], dst):
        if not le2e_writer_ok():
            raise LE2EDenied("list_e2e_move", 403)
        need = [k for k, col in (("note_title", "title"), ("note_body", "body")) if (r[col] or "") and not vals.get(k)]
        if need:
            raise LE2EDenied("list_e2e_move", need={"notes": [r["id"]]})
        le2e_guard(c, dst, vals)
        return
    le2e_guard(c, dst, vals, cur={"note_title": r["title"], "note_body": r["body"]})


def le2a_api_refuse(c, *lids):
    """REST API v1 routes of things in a list with the lock: 403 (agents and tokens cannot read or write its texts)."""
    if le2e_modes(c, [x for x in lids if isinstance(x, int) and not isinstance(x, bool)]):
        raise LE2EDenied("list_e2e_api", 403)


def le2a_field_value(c, f, v, lid):
    """field_value: a value for custom field f (row) in list lid. Text fields of a locked list take ciphertexts only (guarded);
    any other type never takes one (decision E2: select / number / date / url stay readable)."""
    if f["type"] != "text":
        if le2e_is_cipher(v):
            raise BadInput(tr("{0}: invalid value", f["name"]))
        return v
    v = str(v)
    if le2e_is_cipher(v.strip()):
        v = le2a_clean_cipher(v.strip(), f["name"])
    le2e_guard(c, lid, {"field": v})
    return v


def le2a_text_max(v, plain_max):
    """Length limit of a text value: a ciphertext may be longer than the plain limit (finding L3)."""
    return LE2E_CT_MAX + len(LE2E_PREFIX) + 64 if le2e_is_cipher(v) else plain_max


def le2a_clean_cipher(v, what):
    """clean_task & co.: a ciphertext stays as it is (never stripped or cut); a broken one is refused (400)."""
    if not le2e_parse(v):
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def le2a_locked_text(c, lid, *vals, what="list_e2e_plain"):
    """Free-text places that are not encrypted (notepads, waiting notes): refused with text in a locked list."""
    if le2e_mode(c, lid) and any(v not in (None, "") for v in vals):
        raise LE2EDenied(what)


# ---------------------------------------------------------------- memberships
def le2a_member_problem(c, lid, uid, role):
    """A text when uid (with role) cannot join / stay in locked list lid (agent, participant role), else None."""
    if not le2e_mode(c, lid):
        return None
    from ..agents.core import is_agent
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if u and is_agent(u):
        return tr("Agents cannot be members of a project encrypted in the browser.")
    if role == "participant":
        return tr("Projects encrypted in the browser have no participants. Choose another role.")
    return None


def le2a_folder_problem(c, owner, folder, role, uid=None):
    """PUT /api/folders/people / groups: the role participant (or a kid) for a folder that holds locked lists -> a text."""
    from ..lists.lists import _in_folder
    kid = uid and c.execute("SELECT 1 FROM users WHERE id=? AND kid=1", (uid,)).fetchone()
    if role != "participant" and not kid:
        return None
    for r in c.execute("SELECT folder FROM lists WHERE owner_id=? AND e2e IS NOT NULL", (owner,)).fetchall():
        if _in_folder(r["folder"], folder):
            return tr("This folder holds projects encrypted in the browser: they have no participants. Choose another role.")
    return None


def le2a_gen_locked(c, lid):
    """2.64.1 review (M3): server generators (birthdays from contacts / CardDAV, family deadlines, Home & life) skip a list with
    the lock -- they would write plain titles into it. True = skip."""
    return bool(lid) and le2e_mode(c, lid) is not None


def le2a_gen_refuse(c, lid):
    """The same for a list chosen explicitly in a request: 409 instead of a plain text in a locked list."""
    if le2a_gen_locked(c, lid):
        raise LE2EDenied("list_e2e_plain")


def le2a_owner_keep(c, lid, new, force=False):
    """Transfer of ownership: the new owner needs a key of the current generation (409 otherwise; force: a transfer that must
    happen -- someone leaves the organisation -- puts the heir on the waiting list instead). Returns what the members trigger
    would drop when the new owner's member row goes (their keys, the rotation mark), for le2a_owner_restore."""
    mode, gen = le2a_gen(c, lid)
    if not mode:
        return None
    has = c.execute("SELECT 1 FROM list_keys WHERE list_id=? AND user_id=? AND gen=?", (lid, new, gen)).fetchone()
    if not has and not force:
        # 2.64.1 review (L6): named -- a folder / organisation transfer moves many lists at once
        name = c.execute("SELECT name FROM lists WHERE id=?", (lid,)).fetchone()
        raise Denied(409, tr("The new owner needs the key of the project “{0}” first.", name[0] if name else ""))
    keys = [dict(r) for r in c.execute("SELECT * FROM list_keys WHERE list_id=? AND user_id=?", (lid, new))]
    rot = c.execute("SELECT e2e_rotate FROM lists WHERE id=?", (lid,)).fetchone()[0]
    return {"keys": keys, "rotate": rot, "wait": not has}


def le2a_owner_restore(c, lid, keep):
    if not keep:
        return
    for k in keep["keys"]:
        c.execute("INSERT INTO list_keys(list_id,gen,user_id,wrapped,wrapped_by,wrapper_pub,created_at) VALUES(?,?,?,?,?,?,?) "
                  "ON CONFLICT (list_id,gen,user_id) DO NOTHING",
                  (k["list_id"], k["gen"], k["user_id"], k["wrapped"], k["wrapped_by"], k["wrapper_pub"], k["created_at"]))
        c.execute("DELETE FROM list_key_pending WHERE list_id=? AND user_id=?", (lid, k["user_id"]))
    if keep.get("wait"):
        new = c.execute("SELECT owner_id FROM lists WHERE id=?", (lid,)).fetchone()[0]
        c.execute("INSERT INTO list_key_pending(list_id,user_id,since) VALUES(?,?,?) ON CONFLICT DO NOTHING", (lid, new, iso(now_utc())))
    c.execute("UPDATE lists SET e2e_rotate=? WHERE id=?", (keep["rotate"], lid))


def le2a_state(c, rows, uid):
    """/api/state: {list_id: {e2e_pending, e2e_mine}} of the locked lists in rows (the other columns come with the row)."""
    lids = [r["id"] for r in rows if r["e2e"]]
    out = {}
    if not lids:
        return out
    q = ",".join("?" * len(lids))
    pend = dict(c.execute(f"SELECT list_id, COUNT(*) FROM list_key_pending WHERE list_id IN ({q}) GROUP BY list_id", lids).fetchall())
    mine = {r[0] for r in c.execute(f"""SELECT k.list_id FROM list_keys k JOIN lists l ON l.id=k.list_id AND k.gen=l.e2e_gen
                                       WHERE k.user_id=? AND k.list_id IN ({q})""", (uid, *lids))}
    for lid in lids:
        out[lid] = {"e2e_pending": int(pend.get(lid, 0)), "e2e_mine": lid in mine}
    return out


def le2a_shares_list(c, a, b):
    """Do people a and b share a list (owner or member of the same list)? -- /api/e2e/pub (finding H4)."""
    sub = "(SELECT id AS l FROM lists WHERE owner_id=? UNION SELECT list_id FROM list_members WHERE user_id=?)"
    return c.execute(f"SELECT 1 FROM {sub} x JOIN {sub} y ON x.l=y.l LIMIT 1", (a, a, b, b)).fetchone() is not None


# ---------------------------------------------------------------- routes
def _le2a_person():
    """A person in the web app (agents, API tokens, calendar apps, public links: 403)."""
    if not le2e_writer_ok():
        raise Denied(403)
    return me()


def _le2a_list(c, lid):
    role = need_list(c, lid, write=False)
    r = c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone()
    return r, role


def _le2a_names(c, ids):
    from .comments import user_names
    return user_names(c, list(ids))


def le2a_people(c, lr):
    """Owner + members of list row lr: ([{user_id, name, role, kind, has_keys, pub, key_gens}], [{user_id, name}] agents)."""
    from ..agents.core import agent_ids
    lid = lr["id"]
    rows = [(lr["owner_id"], "owner")] + [(r[0], r[1]) for r in c.execute(
        "SELECT user_id, role FROM list_members WHERE list_id=? ORDER BY added_at, user_id", (lid,))]
    ids = [u for u, _ in rows if u]
    names = _le2a_names(c, ids)
    ag = set(agent_ids(c)) | {r[0] for r in c.execute(
        f"SELECT id FROM users WHERE kind='agent' AND id IN ({','.join('?' * len(ids)) or 'NULL'})", ids)}
    pubs = {r[0]: r[1] for r in c.execute(f"SELECT user_id, pub FROM e2e_keys WHERE user_id IN ({','.join('?' * len(ids)) or 'NULL'})", ids)}
    gens = {}
    for r in c.execute("SELECT user_id, gen FROM list_keys WHERE list_id=? ORDER BY gen", (lid,)):
        gens.setdefault(r[0], []).append(r[1])
    people, agents = [], []
    for u, role in rows:
        if not u:
            continue
        if u in ag:
            agents.append({"user_id": u, "name": names.get(u, "")})
            continue
        people.append({"user_id": u, "name": names.get(u, ""), "role": role, "kind": "person", "has_keys": u in pubs,
                       "pub": json.loads(pubs[u]) if u in pubs else None, "key_gens": gens.get(u, [])})
    return people, agents


def le2a_blockers(c, lr, agents):
    """Why the lock cannot be switched on now: [{code, text}]."""
    from ..lists.groups import grp_shares_of_list
    from ..lists.lists import _in_folder
    lid, out = lr["id"], []

    def add(code):
        out.append({"code": code, "text": tr(LE2A_BLOCKERS[code])})
    if lr["is_inbox"]:
        add("inbox")
    # 2.64.1 review (M2): a list admin must not lock the owner out of their own list (waiting list, no way back without a key)
    if not c.execute("SELECT 1 FROM e2e_keys WHERE user_id=?", (lr["owner_id"],)).fetchone():
        add("owner_setup")
    if agents:
        add("agent")
    if c.execute("SELECT 1 FROM public_links WHERE list_id=?", (lid,)).fetchone():
        add("public_link")
    if ov_open(lr):
        add("org_open")
    if c.execute("SELECT 1 FROM list_members WHERE list_id=? AND role='participant' LIMIT 1", (lid,)).fetchone() or \
            any(role == "participant" for _gid, role, _via in grp_shares_of_list(c, lid)):
        add("participant")
    if lr["folder"] and any(_in_folder(lr["folder"], r["folder"]) for r in c.execute(
            "SELECT folder FROM folder_people WHERE owner_id=? AND role='participant'", (lr["owner_id"],)).fetchall()):
        add("folder_participant")
    if c.execute("SELECT 1 FROM task_note_locks n JOIN tasks t ON t.id=n.task_id WHERE t.list_id=? LIMIT 1", (lid,)).fetchone():
        add("note_lock")
    if c.execute("SELECT 1 FROM list_notepads WHERE list_id=? AND (title<>'' OR body<>'') LIMIT 1", (lid,)).fetchone():
        add("notepad")
    if lr["family"]:  # 2.64.1 review (M3)
        add("family")
    if lr["life"]:
        add("life")
    if c.execute("SELECT 1 FROM books WHERE occ_list_id=? UNION ALL SELECT 1 FROM contact_srcs WHERE list_id=? LIMIT 1", (lid, lid)).fetchone():
        add("generator")
    return out


# what /e2e/todo hands out: (key, table, id columns, text column, field name)
_LE2A_PLAIN = "(COALESCE({0}, '')<>'' AND left({0}, 5)<>'e2e1:')"  # the prefix exactly (left(), not LIKE: pg_dialect)
_LE2A_CIPHER = "(left({0}, 5)='e2e1:')"
# 2.64.2 A (#1817): a ciphertext of a generation older than the target of the re-encryption after a key change ("g" of the
# compact JSON; {1} = the target generation)
_LE2A_OLD = "(left({0}, 5)='e2e1:' AND substring({0} from '\"g\"\\s*:\\s*([0-9]+)')::bigint < {1})"  # 2.64.3 (review L2): also with spaces
LE2A_FILES_MAX = 20  # 2.64.2 A (#1817): files per todo call (each one is converted through its own upload, part B)


def _le2a_conds(mode, reenc=0):
    """SQL conditions (template for a text column, snippets) of the values not yet in the target format of mode."""
    if mode == "encrypting":
        return _LE2A_PLAIN, "jsonb_typeof(t.snippets)='array' AND jsonb_array_length(t.snippets)>0"
    if mode == "decrypting":
        return _LE2A_CIPHER, "jsonb_typeof(t.snippets)='string'"
    # 2.64.2 A (#1817): 'on' -- plain texts (there should be none) and, after a key change, ciphertexts older than reenc
    r = int(reenc or 0)
    old = _LE2A_OLD.replace("{1}", str(r))
    t = f"({_LE2A_PLAIN} OR {old})" if r > 0 else _LE2A_PLAIN
    snip = "(jsonb_typeof(t.snippets)='array' AND jsonb_array_length(t.snippets)>0)"
    if r > 0:
        snip = f"({snip} OR (jsonb_typeof(t.snippets)='string' AND {old.replace('{0}', '(t.snippets #>> ARRAY[]::text[])')}))"
    return t, snip


def _le2a_extra(c, lid, mode, gen, uid, limit):
    """2.64.2 A (#1817): the files (part B) and channel messages (part C) of the list still to convert ->
    (files, number of files, msgs, number of msgs); gen = the target generation, always lists.e2e_gen (on: older ones are
    re-encrypted to it), limit 0 = only the numbers."""
    from .liste2echan import le2c_left
    from .liste2efile import le2f_left
    files, nf = le2f_left(c, lid, mode, gen, uid, min(limit, LE2A_FILES_MAX))
    msgs, nm = le2c_left(c, lid, mode, gen, limit)
    return list(files or [])[:LE2A_FILES_MAX] if limit else [], int(nf or 0), list(msgs or [])[:limit] if limit else [], int(nm or 0)


def le2a_left(c, lid, mode, limit=None, uid=None):
    """The values of list lid that are not yet in the target format (mode encrypting: plain texts, decrypting: ciphertexts,
    on [2.64.2 A]: plain texts and ciphertexts older than e2e_gen, i.e. after a key change), deleted tasks (trash) included, plus
    the files and channel messages (2.64.2: parts B / C). -> ({tasks, comments, notes, sections, fields, files, msgs},
    left counts); uid = who converts (files encrypted for one person only count for that person)."""
    lr = c.execute("SELECT e2e_gen FROM lists WHERE id=?", (lid,)).fetchone()
    gen = int(lr[0] or 0) if lr else 0
    # 'on': every ciphertext older than the current generation (normally only during the re-encryption after a key change;
    # a write of an outdated tab afterwards is picked up by the next run), the same target as files / messages
    reenc = gen
    t, snip = _le2a_conds(mode, reenc)
    tc = " OR ".join([t.format("t.title"), t.format("t.content"), t.format("t.url"), f"(t.snippets IS NOT NULL AND {snip})"])
    tasks_sql = f"FROM tasks t WHERE t.list_id=? AND ({tc})"
    com_sql = f"FROM comments cm JOIN tasks t ON t.id=cm.task_id WHERE t.list_id=? AND {t.format('cm.body')}"
    note_sql = f"FROM notes n WHERE n.list_id=? AND ({t.format('n.title')} OR {t.format('n.body')})"
    sec_sql = f"FROM sections s WHERE s.list_id=? AND {t.format('s.name')}"
    fld_sql = (f"FROM task_field_values v JOIN list_fields lf ON lf.id=v.field_id AND lf.type='text' JOIN tasks t ON t.id=v.task_id "
               f"WHERE t.list_id=? AND {t.format('v.value')}")
    left = {k: c.execute(f"SELECT COUNT(*) {s}", (lid,)).fetchone()[0]
            for k, s in (("tasks", tasks_sql), ("comments", com_sql), ("notes", note_sql), ("sections", sec_sql), ("fields", fld_sql))}
    files, left["files"], msgs, left["msgs"] = _le2a_extra(c, lid, mode, gen, uid, limit or 0)
    if limit is None:
        return None, left

    def todo(v):
        if not isinstance(v, str) or v == "":
            return False
        if not le2e_is_cipher(v):
            return mode != "decrypting"
        if mode != "on":
            return mode == "decrypting"
        d = le2e_parse(v)  # 2.64.2 A (#1817): an older generation than the target of the key change
        return bool(d) and d["g"] < reenc
    out, n = {"tasks": [], "comments": [], "notes": [], "sections": [], "fields": [], "files": files, "msgs": []}, 0
    for r in c.execute(f"SELECT t.id, t.title, t.content, t.url, t.snippets {tasks_sql} ORDER BY t.id LIMIT ?", (lid, limit)).fetchall():
        if n >= limit:
            break
        d = {"id": r["id"]}
        for k in ("title", "content", "url"):
            d[k] = r[k] if todo(r[k]) else None
        sc = le2a_snip_cipher(r["snippets"])
        if mode == "decrypting":
            d["snippets"] = sc
        else:  # the whole JSON text of the snippets is one value
            from ..tasks.snippets import snip_parse
            d["snippets"] = r["snippets"] if not sc and snip_parse(r["snippets"]) else (sc if sc and mode == "on" and todo(sc) else None)
        for k in ("title", "content", "url", "snippets"):  # at most limit values (the rest comes with the next call)
            if d[k] is not None:
                if n >= limit:
                    d[k] = None
                else:
                    n += 1
        out["tasks"].append(d)
    for key, sql, cols in (("comments", com_sql, ("cm.id", "cm.body")), ("notes", note_sql, ("n.id", "n.title", "n.body")),
                           ("sections", sec_sql, ("s.id", "s.name"))):
        if n >= limit:
            break
        for r in c.execute(f"SELECT {', '.join(cols)} {sql} ORDER BY 1 LIMIT ?", (lid, limit - n)).fetchall():
            if n >= limit:
                break
            d = {"id": r[0]}
            for i, col in enumerate(cols[1:], 1):
                name = col.split(".")[1]
                d[name] = r[i] if todo(r[i]) and n < limit else None
                n += d[name] is not None
            out[key].append(d)
    if n < limit:
        for r in c.execute(f"SELECT v.task_id, v.field_id, v.value {fld_sql} ORDER BY 1, 2 LIMIT ?", (lid, limit - n)).fetchall():
            out["fields"].append({"task_id": r[0], "field_id": r[1], "value": r[2]})
            n += 1
    if n < limit:  # 2.64.2 A (#1817): channel messages go through bulk too (part C)
        out["msgs"] = msgs[:limit - n]
    return out, left


def le2a_info(c, lr, role, uid):
    """The answer of GET /api/lists/<id>/e2e (also of start and rotate)."""
    lid = lr["id"]
    people, agents = le2a_people(c, lr)
    pnames = {p["user_id"]: p for p in people}
    pend = [{"user_id": r["user_id"], "name": pnames.get(r["user_id"], {}).get("name") or _le2a_names(c, [r["user_id"]]).get(r["user_id"], ""),
             "since": r["since"], "has_keys": bool(pnames.get(r["user_id"], {}).get("has_keys"))}
            for r in c.execute("SELECT user_id, since FROM list_key_pending WHERE list_id=? ORDER BY since, user_id", (lid,))]
    keys = [{"gen": r["gen"], "wrapped": json.loads(r["wrapped"]), "wrapped_by": r["wrapped_by"], "wrapper_pub": json.loads(r["wrapper_pub"])}
            for r in c.execute("SELECT * FROM list_keys WHERE list_id=? AND user_id=? ORDER BY gen", (lid, uid))]
    mode = lr["e2e"] or None
    d = {"list_id": lid, "mode": mode, "gen": int(lr["e2e_gen"] or 0), "rotate": int(lr["e2e_rotate"] or 0), "by": lr["e2e_by"],
         "at": lr["e2e_at"], "can_manage": role in LE2A_MANAGE, "keys": keys, "pending": pend, "members": people, "agents": agents,
         "blockers": le2a_blockers(c, lr, agents) if not mode else [],
         "reenc": int(lr["e2e_reenc"] or 0)}  # 2.64.2 A (#1817): target generation of the re-encryption after a key change
    if mode in ("encrypting", "decrypting") or (mode == "on" and role in LE2A_MANAGE):
        # 2.64.2 A (#1817): in 'on' what the background re-encryption still has to do (only for those who run it)
        d["left"] = le2a_left(c, lid, mode, uid=uid)[1]
    return d


@app.get("/api/lists/<int:lid>/e2e")
def le2a_get(lid):
    """The lock of a list as the browser needs it: mode, generation, my wrapped keys, waiting list, members with their public
    keys, what blocks switching it on, what is left of a running switch (see the protocol in this module's docs)."""
    c = db()
    uid = _le2a_person()
    lr, role = _le2a_list(c, lid)
    return jsonify(le2a_info(c, lr, role, uid))


def _le2a_manage(c, lid):
    uid = _le2a_person()
    lr, role = _le2a_list(c, lid)
    if role not in LE2A_MANAGE:
        raise Denied(403, tr("Only the owner and project admins can change this setting"))
    return uid, lr, role


def _le2a_wrapped(v):
    from .e2e import e2e_blob
    return e2e_blob(v, LE2A_WRAP_MAX)


@app.post("/api/lists/<int:lid>/e2e/start")
def le2a_start(lid):
    """{keys: [{user_id, wrapped}]} -- switch the lock on (owner / list admins with their own keys set up): the browser made a
    list key and wrapped it for everyone with encryption set up; the others wait for it (decision E7). -> 'encrypting'."""
    from .e2e import e2e_keys_of
    c = db()
    uid, lr, role = _le2a_manage(c, lid)
    if lr["e2e"]:
        return err(tr("The project is already encrypted in the browser."), 409)
    mine = e2e_keys_of(c, uid)
    if not mine:
        return err(tr("Set up end-to-end encryption first (Settings > Account)."), 409)
    people, agents = le2a_people(c, lr)
    bl = le2a_blockers(c, lr, agents)
    if bl:
        return jsonify(error=bl[0]["text"], code="list_e2e_blocked", blockers=bl), 409
    keys = body().get("keys")
    if not isinstance(keys, list) or len(keys) > LE2A_KEYS_MAX:
        return err(tr("Invalid value: {0}", "keys"))
    ready = {p["user_id"] for p in people if p["has_keys"]}
    given = {}
    for k in keys:
        w = _le2a_wrapped(k.get("wrapped")) if isinstance(k, dict) else None
        u = k.get("user_id") if isinstance(k, dict) else None
        if not w or isinstance(u, bool) or not isinstance(u, int) or u not in ready or u in given:
            return err(tr("Invalid value: {0}", "keys"))
        given[u] = w
    missing = ready - set(given)
    if lr["owner_id"] not in given:  # 2.64.1 review (M2): the owner always gets the key (the blocker above checks the setup)
        return jsonify(error=tr("The owner needs to set up encryption first."), code="list_e2e_keys",
                       missing=sorted(missing | {lr["owner_id"]})), 409
    if missing or uid not in given:
        names = _le2a_names(c, missing)
        return jsonify(error=tr("A key is missing for: {0}", ", ".join(sorted(names.get(u, "?") for u in missing))),
                       code="list_e2e_keys", missing=sorted(missing)), 409
    gen = int(lr["e2e_gen"] or 0) + 1
    ts = iso(now_utc())
    # 2.64.1 review (M1): the switch itself first and only from the open state -- a second start at the same moment (another
    # admin) gets 409 and never replaces the keys the first browser already encrypts with
    if not c.execute("UPDATE lists SET e2e='encrypting', e2e_gen=?, e2e_rotate=0, e2e_reenc=0, e2e_by=?, e2e_at=? WHERE id=? AND e2e IS NULL AND "
                     "COALESCE(e2e_gen, 0)=?", (gen, uid, ts, lid, gen - 1)).rowcount:
        c.rollback()
        return err(tr("The project is already encrypted in the browser."), 409)
    c.execute("DELETE FROM list_keys WHERE list_id=?", (lid,))
    c.execute("DELETE FROM list_key_pending WHERE list_id=?", (lid,))
    for u, w in given.items():
        c.execute("INSERT INTO list_keys(list_id,gen,user_id,wrapped,wrapped_by,wrapper_pub,created_at) VALUES(?,?,?,?,?,?,?)",
                  (lid, gen, u, w, uid, mine["pub"], ts))
    for p in people:
        if p["user_id"] not in given:
            c.execute("INSERT INTO list_key_pending(list_id,user_id,since) VALUES(?,?,?) ON CONFLICT DO NOTHING", (lid, p["user_id"], ts))
    c.execute("INSERT INTO list_activity(list_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
              (lid, uid, "e2e", json.dumps({"on": True, "gen": gen}), ts))
    bump(c)
    c.commit()
    return jsonify(le2a_info(c, c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone(), role, uid))


def _le2a_switch(c, lid, on_ok=False):
    """todo / bulk / finish: only during a switch, only the owner / list admins (whoever started it was one; a person who lost
    that role meanwhile does not continue). on_ok (2.64.2 A): also in 'on' -- the background re-encryption after a key change
    (and files / channel messages of a list locked before 2.64.2)."""
    uid = _le2a_person()
    lr, role = _le2a_list(c, lid)
    if lr["e2e"] not in (("encrypting", "decrypting", "on") if on_ok else ("encrypting", "decrypting")):
        return uid, lr, role, err(tr("No encryption change is running for this project."), 409)
    if role not in LE2A_MANAGE:
        raise Denied(403, tr("Only the owner and project admins can change this setting"))
    return uid, lr, role, None


@app.get("/api/lists/<int:lid>/e2e/todo")
def le2a_todo(lid):
    """?limit=200 -- the next values the browser converts (only those not in the target format yet; others null). 2.64.2 A:
    also in 'on' (re-encryption after a key change), plus files (converted one by one through /e2e/files/<id>, part B) and
    channel messages (written back through bulk, part C)."""
    c = db()
    uid, lr, _role, e = _le2a_switch(c, lid, on_ok=True)
    if e:
        return e
    try:
        limit = max(1, min(LE2A_BULK_MAX, int(request.args.get("limit") or LE2A_BULK_MAX)))
    except ValueError:
        return err(tr("Invalid value: {0}", "limit"))
    out, left = le2a_left(c, lid, lr["e2e"], limit, uid=uid)
    return jsonify({**out, "left": left, "mode": lr["e2e"], "gen": int(lr["e2e_gen"] or 0), "reenc": int(lr["e2e_reenc"] or 0)})


@app.post("/api/lists/<int:lid>/e2e/bulk")
def le2a_bulk(lid):
    """{tasks: [{id, title?, content?, url?, snippets?}], comments: [{id, body}], notes: [{id, title?, body?}], sections: [{id, name}],
    fields: [{task_id, field_id, value}], msgs: [{id, enc} | {id, body}]} -- converted values (at most 200): encrypting = ciphertexts
    of the current generation (or ''), decrypting = plain texts, on (2.64.2 A: re-encryption after a key change) = ciphertexts of
    the current generation that replace an older ciphertext or a plain text (a value already of the current generation -- someone
    edited it meanwhile -- stays). No history entries, one live update per call; repeating a call is harmless."""
    from ..tasks.validation import CONTENT_MAX, TITLE_MAX
    from .notes import NOTE_BODY_MAX, NOTE_TITLE_MAX
    from .comments import MAX_COMMENT
    c = db()
    _uid, lr, _role, e = _le2a_switch(c, lid, on_ok=True)
    if e:
        return e
    mode, gen = lr["e2e"], int(lr["e2e_gen"] or 0)
    enc, on = mode in ("encrypting", "on"), mode == "on"
    b = body()
    groups = {k: b.get(k) or [] for k in ("tasks", "comments", "notes", "sections", "fields", "msgs")}
    if any(not isinstance(v, list) or any(not isinstance(x, dict) for x in v) for v in groups.values()):
        return err(tr("Invalid data"))
    bad = lambda what: BadInput(tr("Invalid value: {0}", what))  # noqa: E731

    def val(v, what, plain_max):
        if v is None:
            return None
        if not isinstance(v, str):
            raise bad(what)
        if v == "":
            return ""
        if enc:
            d = le2e_parse(v)
            if not d or d["g"] != gen:
                raise bad(what)
        elif le2e_is_cipher(v) or len(v) > plain_max:
            raise bad(what)
        return v

    def stale(cur):
        """2.64.2 A (#1817): 'on' -- may the stored value be replaced? (a plain text or an older generation)"""
        if not on or cur in (None, ""):
            return True
        d = le2e_parse(cur)
        return not le2e_is_cipher(cur) or (bool(d) and d["g"] < gen)

    def iid(x, k="id"):
        v = x.get(k)
        if isinstance(v, bool) or not isinstance(v, int):
            raise bad(k)
        return v
    n = len(groups["msgs"])
    for key, cols in (("tasks", ("title", "content", "url", "snippets")), ("comments", ("body",)), ("notes", ("title", "body")),
                      ("sections", ("name",)), ("fields", ("value",))):
        n += sum(1 for x in groups[key] for k in cols if x.get(k) is not None)
    if n > LE2A_BULK_MAX:
        return err(tr("At most {0} values per call", LE2A_BULK_MAX))
    try:
        for x in groups["tasks"]:
            tid = iid(x)
            row = c.execute("SELECT title, content, url, snippets FROM tasks WHERE id=? AND list_id=?", (tid, lid)).fetchone()
            if not row:
                raise bad("tasks")
            upd = {}
            for k, mx in (("title", TITLE_MAX), ("content", CONTENT_MAX), ("url", 2000)):
                v = val(x.get(k), k, mx)
                if v is not None and stale(row[k]):
                    upd[k] = v
            if x.get("snippets") is not None:
                s = x["snippets"]
                if enc:
                    v = val(s, "snippets", 0)
                    if not on or stale(le2a_snip_cipher(row["snippets"])):
                        upd["snippets"] = v
                else:
                    if isinstance(s, str) and le2e_is_cipher(s):
                        raise bad("snippets")
                    upd["snippets"] = s
            if "title" in upd and upd["title"] == "":
                raise bad("title")
            le2a_task_set(c, tid, upd)
        for x in groups["comments"]:
            v = val(x.get("body"), "body", MAX_COMMENT)
            cid = iid(x)
            row = c.execute("SELECT cm.body FROM comments cm JOIN tasks t ON t.id=cm.task_id WHERE cm.id=? AND t.list_id=?",
                            (cid, lid)).fetchone()
            if v is None or not row:
                raise bad("comments")
            if stale(row[0]):
                c.execute("UPDATE comments SET body=? WHERE id=?", (v, cid))
        for x in groups["notes"]:
            nid = iid(x)
            row = c.execute("SELECT title, body FROM notes WHERE id=? AND list_id=?", (nid, lid)).fetchone()
            if not row:
                raise bad("notes")
            for k, col, mx in (("title", "title", NOTE_TITLE_MAX), ("body", "body", NOTE_BODY_MAX)):
                v = val(x.get(k), k, mx)
                if v is not None:
                    if k == "title" and v == "":
                        raise bad("title")
                    if stale(row[col]):
                        c.execute(f"UPDATE notes SET {col}=? WHERE id=?", (v, nid))
        for x in groups["sections"]:
            v = val(x.get("name"), "name", 200)
            sid = iid(x)
            row = c.execute("SELECT name FROM sections WHERE id=? AND list_id=?", (sid, lid)).fetchone()
            if not v or not row:
                raise bad("sections")
            if stale(row[0]):
                c.execute("UPDATE sections SET name=? WHERE id=?", (v, sid))
        for x in groups["fields"]:
            tid, fid = iid(x, "task_id"), iid(x, "field_id")
            v = val(x.get("value"), "value", 1000)
            row = c.execute("""SELECT v.value FROM task_field_values v JOIN list_fields lf ON lf.id=v.field_id AND lf.type='text'
                               JOIN tasks t ON t.id=v.task_id WHERE v.task_id=? AND v.field_id=? AND t.list_id=?""",
                            (tid, fid, lid)).fetchone()
            if v is None or not row:
                raise bad("fields")
            if not stale(row[0]):
                continue
            if v == "":
                c.execute("DELETE FROM task_field_values WHERE task_id=? AND field_id=?", (tid, fid))
            else:
                c.execute("UPDATE task_field_values SET value=? WHERE task_id=? AND field_id=?", (v, tid, fid))
        if groups["msgs"]:  # 2.64.2 A (#1817): channel messages of the list room (part C checks and writes them)
            from .liste2echan import le2c_bulk
            try:
                le2c_bulk(c, lid, mode, gen, groups["msgs"])
            except ValueError:
                raise bad("msgs") from None
    except BadInput as x:
        c.rollback()
        return err(str(x))
    bump(c)
    c.commit()
    return jsonify(ok=True, left=le2a_left(c, lid, mode, uid=_uid)[1])


@app.post("/api/lists/<int:lid>/e2e/finish")
def le2a_finish(lid):
    """Ends a switch when nothing is left: encrypting -> 'on' (copies of plain texts elsewhere go, part B), decrypting -> open
    (the list keys and the waiting list go). 2.64.2 A: 'on' -> the re-encryption after a key change is done (e2e_reenc 0)."""
    c = db()
    uid, lr, _role, e = _le2a_switch(c, lid, on_ok=True)
    if e:
        return e
    if lr["e2e"] == "on" and not int(lr["e2e_reenc"] or 0):  # no key change to finish (review M1: a second finish = 409)
        return err(tr("No encryption change is running for this project."), 409)
    left = le2a_left(c, lid, lr["e2e"], uid=uid)[1]
    if any(left.values()):
        return jsonify(error=tr("Not all texts are converted yet."), code="list_e2e_left", left=left), 409
    ts = iso(now_utc())
    if lr["e2e"] == "on":  # 2.64.2 A (#1817): only for the generation this call checked (a key change in between: its own run)
        if not c.execute("UPDATE lists SET e2e_reenc=0 WHERE id=? AND e2e='on' AND e2e_gen=? AND e2e_reenc=?",
                         (lid, int(lr["e2e_gen"] or 0), int(lr["e2e_reenc"] or 0))).rowcount:
            c.rollback()
            return err(tr("No encryption change is running for this project."), 409)
        c.execute("INSERT INTO list_activity(list_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
                  (lid, uid, "e2e", json.dumps({"reenc": True, "done": True, "gen": int(lr["e2e_gen"] or 0)}), ts))
        bump(c)
        c.commit()
        return jsonify(ok=True, mode="on")
    # 2.64.1 review (M1): only from the state this call checked (a stop or another finish in between = 409)
    if not c.execute("UPDATE lists SET e2e=?, e2e_at=? WHERE id=? AND e2e=? AND COALESCE(e2e_gen, 0)=?",
                     ("on" if lr["e2e"] == "encrypting" else None, ts, lid, lr["e2e"], int(lr["e2e_gen"] or 0))).rowcount:
        c.rollback()
        return err(tr("No encryption change is running for this project."), 409)
    if lr["e2e"] == "encrypting":
        c.execute("UPDATE tasks SET wait_note='' WHERE list_id=? AND COALESCE(wait_note, '')<>''", (lid,))  # not encrypted: it goes
        from .liste2eguard import le2b_scrub  # H2: copies of the plain texts in other tables (history, time entries, pushes, webhooks, agent events ...)
        le2b_scrub(c, lid)
    else:
        c.execute("UPDATE lists SET e2e_rotate=0, e2e_reenc=0 WHERE id=?", (lid,))
        c.execute("DELETE FROM list_keys WHERE list_id=?", (lid,))
        c.execute("DELETE FROM list_key_pending WHERE list_id=?", (lid,))
    c.execute("INSERT INTO list_activity(list_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
              (lid, uid, "e2e", json.dumps({"on": lr["e2e"] == "encrypting", "done": True, "gen": int(lr["e2e_gen"] or 0)}), ts))
    bump(c)
    c.commit()
    return jsonify(ok=True, mode="on" if lr["e2e"] == "encrypting" else None)


@app.post("/api/lists/<int:lid>/e2e/stop")
def le2a_stop(lid):
    """{password} -- the way back (only the owner, with the account password like removing one's keys): 'on' / 'encrypting'
    -> 'decrypting'; the browser writes the plain texts back through todo / bulk / finish."""
    from .e2e import e2e_reauth
    c = db()
    uid = _le2a_person()
    lr, role = _le2a_list(c, lid)
    if role != "owner":
        raise Denied(403, tr("Only the owner can switch the lock off."))
    if lr["e2e"] not in ("on", "encrypting"):
        return err(tr("The project is not encrypted in the browser."), 409)
    if not c.execute("SELECT 1 FROM list_keys WHERE list_id=? AND user_id=? AND gen=?", (lid, uid, lr["e2e_gen"])).fetchone():
        return err(tr("You have no key for this project yet."), 409)
    e = e2e_reauth(c, uid, body())
    if e is not None:
        return e
    ts = iso(now_utc())
    # 2.64.1 review (M1): conditional, like start and finish
    if not c.execute("UPDATE lists SET e2e='decrypting', e2e_by=?, e2e_at=? WHERE id=? AND e2e IN ('on', 'encrypting')",
                     (uid, ts, lid)).rowcount:
        c.rollback()
        return err(tr("The project is not encrypted in the browser."), 409)
    c.execute("INSERT INTO list_activity(list_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
              (lid, uid, "e2e", json.dumps({"on": False}), ts))
    bump(c)
    c.commit()
    return jsonify(le2a_info(c, c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone(), role, uid))


@app.post("/api/lists/<int:lid>/e2e/keys")
def le2a_keys(lid):
    """{keys: [{user_id, gen, wrapped}]} -- hand the list key to people on the waiting list or again (new keys after a lost
    passphrase): only the owner / list admins holding that generation (finding M9); the recipient must be the owner or a
    member with encryption set up. The server stores the wrapper's public key itself and tells the recipient (News)."""
    from .e2e import e2e_keys_of
    from .news import news_add
    c = db()
    uid, lr, _role = _le2a_manage(c, lid)
    if not lr["e2e"]:
        return err(tr("The project is not encrypted in the browser."), 409)
    mine = e2e_keys_of(c, uid)
    keys = body().get("keys")
    if not mine or not isinstance(keys, list) or not keys or len(keys) > LE2A_KEYS_MAX:
        return err(tr("Invalid value: {0}", "keys"))
    people = {p["user_id"]: p for p in le2a_people(c, lr)[0]}
    have = {r[0] for r in c.execute("SELECT gen FROM list_keys WHERE list_id=? AND user_id=?", (lid, uid))}
    rows = []
    for k in keys:
        if not isinstance(k, dict):
            return err(tr("Invalid value: {0}", "keys"))
        u, gn, w = k.get("user_id"), k.get("gen"), _le2a_wrapped(k.get("wrapped"))
        if isinstance(u, bool) or not isinstance(u, int) or isinstance(gn, bool) or not isinstance(gn, int) or not w:
            return err(tr("Invalid value: {0}", "keys"))
        if u not in people or not people[u]["has_keys"]:
            return err(tr("{0} cannot receive the key (not a member or encryption not set up).",
                          _le2a_names(c, [u]).get(u, "?")), 409)
        if gn not in have or gn > int(lr["e2e_gen"] or 0):
            return err(tr("You have no key for this project yet."), 409)
        rows.append((u, gn, w))
    ts = iso(now_utc())
    got, skipped = set(), set()
    for u, gn, w in rows:
        # 2.64.1 review (L3): an existing copy is replaced only for myself or after the recipient set up new keys (a lost
        # passphrase); otherwise an admin could slip a copy the recipient cannot open under them
        old = c.execute("SELECT created_at FROM list_keys WHERE list_id=? AND gen=? AND user_id=?", (lid, gn, u)).fetchone()
        if old and u != uid:
            ku = c.execute("SELECT updated_at FROM e2e_keys WHERE user_id=?", (u,)).fetchone()
            if not ku or (ku[0] or "") <= (old[0] or ""):
                skipped.add(u)
                continue
        c.execute("INSERT INTO list_keys(list_id,gen,user_id,wrapped,wrapped_by,wrapper_pub,created_at) VALUES(?,?,?,?,?,?,?) "
                  "ON CONFLICT (list_id,gen,user_id) DO UPDATE SET wrapped=excluded.wrapped, wrapped_by=excluded.wrapped_by, "
                  "wrapper_pub=excluded.wrapper_pub, created_at=excluded.created_at", (lid, gn, u, w, uid, mine["pub"], ts))
        if gn == int(lr["e2e_gen"] or 0):
            c.execute("DELETE FROM list_key_pending WHERE list_id=? AND user_id=?", (lid, u))
        got.add(u)
    skipped -= got
    by = _le2a_names(c, [uid]).get(uid, "")
    for u in got:
        if u != uid:
            news_add(c, u, "e2e_key", list_id=lid, data={"list_id": lid, "name": lr["name"], "by": uid, "by_name": by}, row="share")
    bump(c)
    c.commit()
    return jsonify(ok=True, released=sorted(got), skipped=sorted(skipped))


# ---------------------------------------------------------------- 2.64.2 A (#1817): key change (rotation)
@app.post("/api/lists/<int:lid>/e2e/rotate")
def le2a_rotate(lid):
    """{gen, keys: [{user_id, wrapped}]} -- a new generation of the list key (after someone left, or on request): only the
    owner / list admins holding the key of the current generation, only in 'on'. gen must be e2e_gen + 1 (a second rotation at
    the same moment gets 409 code list_e2e_gen and does not rotate again). Everyone who held the previous generation and is not
    in keys (e.g. a changed key not confirmed yet) goes on the waiting list; an entry for someone who is not the owner / a member
    -> 400. The server stores the wrapper's public key itself. Starts the background re-encryption (e2e_reenc = gen); old
    generations stay (members need them for texts not re-encrypted yet and for backups)."""
    from .e2e import e2e_keys_of
    c = db()
    uid, lr, role = _le2a_manage(c, lid)
    if lr["e2e"] != "on":
        return err(tr("The project is not encrypted in the browser."), 409)
    cur = int(lr["e2e_gen"] or 0)
    mine = e2e_keys_of(c, uid)
    if not mine or not c.execute("SELECT 1 FROM list_keys WHERE list_id=? AND user_id=? AND gen=?", (lid, uid, cur)).fetchone():
        return err(tr("You have no key for this project yet."), 409)
    b = body()
    gen, keys = b.get("gen"), b.get("keys")
    if isinstance(gen, bool) or not isinstance(gen, int):
        return err(tr("Invalid value: {0}", "gen"))
    if gen != cur + 1:
        return jsonify(error=tr("The key of this project was changed meanwhile."), code="list_e2e_gen", gen=cur), 409
    if not isinstance(keys, list) or not keys or len(keys) > LE2A_KEYS_MAX:
        return err(tr("Invalid value: {0}", "keys"))
    people = {p["user_id"]: p for p in le2a_people(c, lr)[0]}
    given = {}
    for k in keys:
        w = _le2a_wrapped(k.get("wrapped")) if isinstance(k, dict) else None
        u = k.get("user_id") if isinstance(k, dict) else None
        if not w or isinstance(u, bool) or not isinstance(u, int) or u in given or u not in people or not people[u]["has_keys"]:
            return err(tr("Invalid value: {0}", "keys"))
        given[u] = w
    if uid not in given:
        return err(tr("Invalid value: {0}", "keys"))
    ts = iso(now_utc())
    # atomic: only from the generation this browser wrapped for (another rotation first = 409, nothing written)
    if not c.execute("UPDATE lists SET e2e_gen=?, e2e_rotate=0, e2e_reenc=?, e2e_by=?, e2e_at=? WHERE id=? AND e2e='on' AND e2e_gen=?",
                     (gen, gen, uid, ts, lid, cur)).rowcount:
        c.rollback()
        return jsonify(error=tr("The key of this project was changed meanwhile."), code="list_e2e_gen", gen=cur), 409
    # the list row is locked now: a member who left in the meantime must not get the new key (the browser asks again)
    now = {p["user_id"] for p in le2a_people(c, c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone())[0]}
    if set(given) - now:
        c.rollback()
        return jsonify(error=tr("The members of this project changed meanwhile. Try again."), code="list_e2e_members"), 409
    for u, w in given.items():
        c.execute("INSERT INTO list_keys(list_id,gen,user_id,wrapped,wrapped_by,wrapper_pub,created_at) VALUES(?,?,?,?,?,?,?)",
                  (lid, gen, u, w, uid, mine["pub"], ts))
        c.execute("DELETE FROM list_key_pending WHERE list_id=? AND user_id=?", (lid, u))
    for r in c.execute("SELECT user_id FROM list_keys WHERE list_id=? AND gen=?", (lid, cur)).fetchall():
        if r[0] not in given and r[0] in now:
            c.execute("INSERT INTO list_key_pending(list_id,user_id,since) VALUES(?,?,?) ON CONFLICT DO NOTHING", (lid, r[0], ts))
    c.execute("INSERT INTO list_activity(list_id,user_id,kind,data,created_at) VALUES(?,?,?,?,?)",
              (lid, uid, "e2e", json.dumps({"rotate": True, "gen": gen}), ts))
    bump(c)
    c.commit()
    return jsonify(le2a_info(c, c.execute("SELECT * FROM lists WHERE id=?", (lid,)).fetchone(), role, uid))
