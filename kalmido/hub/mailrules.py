"""2.581.0 (#4804): documents from the own mailbox of a workspace (hub/mailbox.py) -- mail rules like Paperless' mail rules.

A rule of a mailbox (hub_mailbox_rules) names its conditions: an IMAP folder (empty = the mailbox's folder), the sender and
the subject (a part of them, any case), "has an attachment" and the age (received in the last max_age days); and its action:
the attachments become documents (the documents input of the document address, docs/ingest.py _docs_mail_into: ZIP /
winmail unpacked, e-invoices, invoice links, the same file never twice), optionally the mail itself as .eml (no PDF of a
mail exists on the server), a target folder of the workspace's documents, tags and the mail's sender as the document's
sender. Afterwards the mail is marked seen, flagged, moved into a folder or left as it is; it is deleted only when the rule's
own switch says so (default off). The first rule that fits takes a mail; each mail once per mailbox (hub_mailbox_docs: a hash
of its Message-ID, else of its head).

Who may: who may set up the mailbox (hub/mailbox.py _ws: the organisation's admins, a person for the own private space); the
documents land in the mailbox's workspace only, filed as the mailbox's holder (mbx_holder), so the organisation boundary and
the target folder's rights are the file store's (fs_put). The rules run in the mailbox round (mbx_loop) on the open
connection after the e-mail filing, at most every MBR_EVERY seconds, and at once with "Fetch now". Errors are codes
(MBX_ERR), never a server's words; the passwords stay in hub/mailbox.py (sealed, never in an answer or a log line).
Source of the documents: doc_meta.source = 'mailbox'. Agents and kid accounts get nothing (people only, like the mailbox)."""
import email
import email.policy
import email.utils
import hashlib
import json
import re
from datetime import timedelta

from flask import jsonify, request

from ..core.config import app
from ..core.db import body, connect, db, err, iso, now_utc
from ..core.db import now_iso as _now
from ..core.pg import system_ctx, write_lock
from ..core.access import Denied
from ..core.conflict import ccf_check
from ..core.i18n import N_, lang, tr
from ..accounts.session import GATE, me
from ..api.common import hit_limit
from ..files.store import fs_role, fs_roles_many
from ..docs import store as DS
from ..docs.ingest import docs_kick, docs_mailbox_import, _mail_parts, _mail_toks
from ..docs.maillink import ml_collect, ml_links
from . import mailbox as MB

MBR_EVERY = 600         # s between two runs of the rules of one mailbox (the round itself is KALMIDO_IMAP_INTERVAL)
MBR_RULES_MAX = 30      # rules of one mailbox
MBR_MAILS = 200         # mails of one folder looked at per run (the newest)
MBR_TAKE = 50           # mails of one mailbox taken in per run (the rest follows in the next run)
MBR_AGE_MAX = 365
MBR_AFTER = ("seen", "flag", "move", "none")
MBR_HOUR = {"links": 30, "eml": 60}  # per mailbox and hour: invoice link downloads / mails filed without a file (as a document address)
MBR_NO_HOLDER = N_("Nobody can receive documents for this mailbox (no admin of the workspace)")
_CTRL = re.compile(r"[\x00-\x1f\x7f]")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_BUDGET = {}            # (box id, kind) -> [hour, used]: this process (the mailbox round runs in one process)


def _gate():
    MB._gate()


def _ws_of(c, raw):
    """(org or None, ws) with the right to manage the mailbox of that workspace; its mailbox row (404 without IMAP)."""
    org, ws = MB._ws(c, raw)
    box = MB.mbx_row(c, ws)
    if not box or not box["imap_host"]:
        raise Denied(404, tr("No mailbox is set up"))
    return org, ws, box


def _rule_ws(c, rid):
    """A rule by id -> (org, ws, box, rule) for a manager of its workspace (another workspace: 404)."""
    _gate()
    if isinstance(rid, bool) or not isinstance(rid, int):
        raise Denied(404)
    r = c.execute("SELECT * FROM hub_mailbox_rules WHERE id=?", (rid,)).fetchone()
    if not r:
        raise Denied(404)
    oid = DS.ws_org(r["ws"])
    org, ws = MB._ws(c, f"org:{oid}" if oid else "private")
    if ws != r["ws"]:
        raise Denied(404)
    box = MB.mbx_row(c, ws)
    if not box or box["id"] != r["box_id"]:
        raise Denied(404)
    return org, ws, box, r


def _folder_ok(v):
    return isinstance(v, str) and len(v) <= 200 and not _CTRL.search(v) and '"' not in v and "\\" not in v


def _target_ok(c, ws, tid):
    """The target folder: a folder of this workspace (not in the trash) I may file into."""
    n = c.execute("SELECT id, kind, org_id, owner_id, deleted_at FROM fs_nodes WHERE id=?", (tid,)).fetchone()
    if not n or n["kind"] != "folder" or n["deleted_at"] or DS.doc_ws(n["org_id"], n["owner_id"]) != ws:
        return False
    return fs_role(c, tid, me()) in ("owner", "edit")


def _vals(c, d, cur, ws):
    """The checked columns of a rule from body d (cur = the stored rule or the defaults); a string = what is wrong."""
    v = {}
    for k, n in (("name", 80), ("from_has", 200), ("subject_has", 200)):
        x = d.get(k, cur[k])
        x = "" if x is None else x
        if not isinstance(x, str) or len(x.strip()) > n or _CTRL.search(x):
            return tr("Invalid value: {0}", k)
        v[k] = x.strip()
    for k in ("folder", "after_folder"):
        x = d.get(k, cur[k])
        x = "" if x is None else x
        if not _folder_ok(x):
            return tr("Invalid value: {0}", k)
        v[k] = x.strip()
    for k in ("active", "need_att", "take_files", "take_mail", "sender_from_mail", "delete_mail"):
        x = d.get(k, bool(cur[k]))
        if not isinstance(x, bool):
            return tr("Invalid value: {0}", k)
        v[k] = 1 if x else 0
    age = d.get("max_age", cur["max_age"])
    if isinstance(age, bool) or not isinstance(age, int) or not 1 <= age <= MBR_AGE_MAX:
        return tr("Invalid value: {0}", "max_age")
    v["max_age"] = age
    v["after"] = d.get("after", cur["after"])
    if v["after"] not in MBR_AFTER:
        return tr("Invalid value: {0}", "after")
    if v["after"] == "move" and not v["after_folder"]:
        return tr("Please name the folder the e-mails are moved to")
    if not v["take_files"] and not v["take_mail"]:
        return tr("Please choose what becomes a document")
    tags = d.get("tags", json.loads(cur["tags"] or "[]"))
    if not isinstance(tags, list) or len(tags) > 10 or any(not isinstance(t, str) or not t.strip() or len(t.strip()) > 60 or _CTRL.search(t) for t in tags):
        return tr("Invalid value: {0}", "tags")
    v["tags"] = json.dumps(list(dict.fromkeys(t.strip() for t in tags)))
    tid = d.get("target_id", cur["target_id"])
    if tid in (None, 0, ""):
        tid = None
    elif isinstance(tid, bool) or not isinstance(tid, int):
        return tr("Invalid value: {0}", "target_id")
    elif tid != cur["target_id"] and not _target_ok(c, ws, tid):  # a stored one stays when it is not changed
        return tr("This folder cannot be chosen")
    v["target_id"] = tid
    pos = d.get("pos", cur["pos"])
    if isinstance(pos, bool) or not isinstance(pos, int) or not 0 <= pos <= 10000:
        return tr("Invalid value: {0}", "pos")
    v["pos"] = pos
    return v


COLS = ("name", "pos", "active", "folder", "from_has", "subject_has", "need_att", "max_age", "take_files", "take_mail", "target_id",
        "tags", "sender_from_mail", "after", "after_folder", "delete_mail")
DEFAULT = {"name": "", "pos": 0, "active": 1, "folder": "", "from_has": "", "subject_has": "", "need_att": 1, "max_age": 30, "take_files": 1,
           "take_mail": 0, "target_id": None, "tags": "[]", "sender_from_mail": 1, "after": "seen", "after_folder": "", "delete_mail": 0}
KNOWN = {"ws", "expect_updated_at", *COLS}


def _out(r):
    d = {k: r[k] for k in ("id", "name", "pos", "folder", "from_has", "subject_has", "max_age", "target_id", "after", "after_folder",
                           "hits", "last_hit_at", "updated_at")}
    d.update({k: bool(r[k]) for k in ("active", "need_att", "take_files", "take_mail", "sender_from_mail", "delete_mail")})
    d["tags"] = json.loads(r["tags"] or "[]")
    return d


def _status(c, box):
    lg = lang(c, me())
    code = box["docs_error"] or ""
    return {"polled_at": box["docs_polled_at"], "error": code, "error_text": tr(MBR_NO_HOLDER, lg=lg) if code == "holder" else MB.mbx_err_text(code, lg),
            "count": int(box["docs_count"] or 0), "due": bool(box["docs_due"]), "folder": box["imap_folder"] or "INBOX"}


def _folders(c, ws):
    """The folders of the workspace's documents (the target picker): [{id, path}] I may file into, at most 300."""
    rid = DS.root_id(c, ws)
    if not rid:
        return []
    out, todo, seen = [], [(rid, "")], set()
    while todo and len(out) < 300:
        pid, path = todo.pop(0)
        if pid in seen:
            continue
        seen.add(pid)
        kids = c.execute("SELECT id, name FROM fs_nodes WHERE parent_id=? AND kind='folder' AND deleted_at IS NULL ORDER BY lower(name), id", (pid,)).fetchall()
        roles = fs_roles_many(c, [k["id"] for k in kids], me()) if kids else {}
        for k in kids:
            gone, role = roles.get(k["id"], (False, None))
            if gone or not role:
                continue
            p = f"{path}/{k['name']}" if path else k["name"]
            if role in ("owner", "edit"):
                out.append({"id": k["id"], "path": p})
            todo.append((k["id"], p))
    return out


def _list(c, ws, box):
    rows = c.execute("SELECT * FROM hub_mailbox_rules WHERE box_id=? ORDER BY pos, id", (box["id"],)).fetchall()
    return {"rules": [_out(r) for r in rows], "status": _status(c, box), "folders": _folders(c, ws)}


@app.get("/api/hubmail/mailbox/rules")
def mbr_list():
    """?ws= -- the document rules of a workspace's mailbox, the state of the last run and the folders a rule can file into."""
    c = db()
    _org, ws, box = _ws_of(c, request.args.get("ws"))
    return jsonify(_list(c, ws, box))


@app.post("/api/hubmail/mailbox/rules")
def mbr_add():
    """{ws, name?, folder?, from_has?, subject_has?, need_att?, max_age?, take_files?, take_mail?, target_id?, tags?,
    sender_from_mail?, after?, after_folder?, delete_mail?, active?, pos?} -- a new rule (201)."""
    c = db()
    d = body() if isinstance(body(), dict) else {}
    _org, ws, box = _ws_of(c, d.get("ws"))
    unknown = sorted(set(d) - KNOWN)
    if unknown:
        return err(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    n = c.execute("SELECT count(*) FROM hub_mailbox_rules WHERE box_id=?", (box["id"],)).fetchone()[0]
    if n >= MBR_RULES_MAX:
        return err(tr("At most {0} rules", MBR_RULES_MAX))
    v = _vals(c, d, {**DEFAULT, "pos": n}, ws)
    if isinstance(v, str):
        return err(v)
    ts = _now()
    rid = c.execute(f"INSERT INTO hub_mailbox_rules(box_id, ws, {', '.join(COLS)}, created_by, created_at, updated_at) "
                    f"VALUES(?,?,{','.join('?' * len(COLS))},?,?,?) RETURNING id", (box["id"], ws, *[v[k] for k in COLS], me(), ts, ts)).fetchone()[0]
    r = c.execute("SELECT * FROM hub_mailbox_rules WHERE id=?", (rid,)).fetchone()
    c.commit()
    return jsonify(rule=_out(r)), 201


@app.put("/api/hubmail/mailbox/rules/<int:rid>")
def mbr_put(rid):
    """{expect_updated_at?, ...the fields of POST} -- changes a rule; a stale expect_updated_at -> 409 with the current rule."""
    c = db()
    d = body() if isinstance(body(), dict) else {}
    _org, ws, _box, r = _rule_ws(c, rid)
    unknown = sorted(set(d) - KNOWN)
    if unknown:
        return err(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    write_lock(c, f"hub_mailbox_rules-{rid}")
    r = c.execute("SELECT * FROM hub_mailbox_rules WHERE id=?", (rid,)).fetchone()
    if not r:
        raise Denied(404)
    ccf_check(d, r["updated_at"], "rule", lambda: _out(r))
    v = _vals(c, d, dict(r), ws)
    if isinstance(v, str):
        return err(v)
    c.execute(f"UPDATE hub_mailbox_rules SET {', '.join(k + '=?' for k in COLS)}, updated_at=? WHERE id=?", (*[v[k] for k in COLS], _now(), rid))
    r = c.execute("SELECT * FROM hub_mailbox_rules WHERE id=?", (rid,)).fetchone()
    c.commit()
    return jsonify(rule=_out(r))


@app.delete("/api/hubmail/mailbox/rules/<int:rid>")
def mbr_del(rid):
    """The rule goes; its documents stay (the mails it took are not taken again)."""
    c = db()
    _rule_ws(c, rid)
    c.execute("DELETE FROM hub_mailbox_rules WHERE id=?", (rid,))
    c.commit()
    return jsonify(ok=True)


@app.post("/api/hubmail/mailbox/rules/fetch")
def mbr_fetch_now():
    """{ws} -- run the document rules of this mailbox now (in the next moment of the mailbox round)."""
    c = db()
    d = body() if isinstance(body(), dict) else {}
    _org, ws, box = _ws_of(c, d.get("ws"))
    if hit_limit(f"mbrfetch:{me()}", 20, 600):
        return err(tr("Too many tests, please wait a few minutes"), 429)
    c.execute("UPDATE hub_mailboxes SET docs_due=1 WHERE id=?", (box["id"],))
    c.commit()
    MB._DUE.add(ws)
    MB.MBX_WAKE.set()
    return jsonify(ok=True)


# ---- the run (in the mailbox round, hub/mailbox.py mbx_poll_one -> MBX_AFTER_POLL) ---------------------------------------
def _bg(fn):
    with GATE.bg():
        c = connect()
        try:
            with system_ctx(c):  # the background round: the mailbox and its holder were checked when the rule was saved / here
                out = fn(c)
            c.commit()
            return out
        finally:
            c.close()


def _budget(box_id):
    def take(kind, n=1):
        hour = _now()[:13]
        cell = _BUDGET.setdefault((box_id, kind), [hour, 0])
        if cell[0] != hour:
            cell[:] = [hour, 0]
        k = max(0, min(n, MBR_HOUR[kind] - cell[1]))
        cell[1] += k
        if k < n:
            print("mailbox docs: budget spent", kind, n - k, flush=True)
        return k
    return take


def _mid_key(head):
    m = email.message_from_bytes(head, policy=email.policy.default)
    mid = str(m.get("Message-ID", "") or "").strip()
    return hashlib.sha256(mid.encode() if mid else b"head:" + head).hexdigest(), m


def _has(hay, needle):
    return not needle or needle.casefold() in str(hay or "").casefold()


def _young(m, days):
    try:
        dt = email.utils.parsedate_to_datetime(str(m.get("Date", "") or ""))
    except (TypeError, ValueError, IndexError):
        return True  # no date: the server's SINCE decided
    if dt is None:
        return True
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=now_utc().tzinfo)
    return dt >= now_utc() - timedelta(days=days)


def _head_fits(rule, m):
    return _has(m.get("From"), rule["from_has"]) and _has(m.get("Subject"), rule["subject_has"]) and _young(m, rule["max_age"])


def _fetch_heads(M, uids):
    """{uid: (size, head bytes)} of uids (one FETCH of the size and the header lines a rule looks at, never \\Seen)."""
    out = {}
    for i in range(0, len(uids), 100):
        typ, data = M.uid("FETCH", b",".join(uids[i:i + 100]).decode(), "(RFC822.SIZE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE)])")
        if typ != "OK":
            continue
        for x in data or []:
            if isinstance(x, tuple) and len(x) > 1:
                u, sz = re.search(rb"UID (\d+)", x[0]), re.search(rb"RFC822\.SIZE (\d+)", x[0])
                if u:
                    out[u.group(1)] = (int(sz.group(1)) if sz else None, x[1] or b"")  # review: no size = like too big (as mail_fetch), never a stall
    return out


def _after(M, rule, u):
    """What happens to a taken mail; '' or an error code. Delete only with the rule's own switch (UID EXPUNGE: exactly this mail;
    a server without UIDPLUS keeps it marked deleted, nothing else of the folder goes)."""
    caps = getattr(M, "capabilities", ()) or ()
    us = u.decode()
    if rule["delete_mail"]:
        M.uid("STORE", us, "+FLAGS", "(\\Deleted)")
        if "UIDPLUS" in caps:
            M.xatom("UID", "EXPUNGE", us)
        return ""
    if rule["after"] == "seen":
        M.uid("STORE", us, "+FLAGS", "(\\Seen)")
    elif rule["after"] == "flag":
        M.uid("STORE", us, "+FLAGS", "(\\Flagged)")
    elif rule["after"] == "move":
        dest = MB._folder_arg(rule["after_folder"])
        if "MOVE" in caps:
            typ, _ = M.xatom("UID", "MOVE", us, dest)
            return "" if typ == "OK" else "folder"
        typ, _ = M.uid("COPY", us, dest)
        if typ != "OK":
            return "folder"
        if "UIDPLUS" in caps:  # COPY + delete exactly this one = a move; without UIDPLUS it stays (seen) where it was
            M.uid("STORE", us, "+FLAGS", "(\\Seen \\Deleted)")
            M.xatom("UID", "EXPUNGE", us)
        else:
            M.uid("STORE", us, "+FLAGS", "(\\Seen)")
    return ""


def _take(box, holder, rule, key, raw):
    """One mail -> documents of the box's workspace (as its holder); the claim of the mail (key = _mid_key of its header lines,
    the same as the look before) in the same transaction. -> (handled, documents); handled None = another process had it."""
    msg = email.message_from_bytes(raw, policy=email.policy.default)
    budget = _budget(box["id"])
    pre = None
    if rule["take_files"]:
        _t, mail_text, ei_is = _mail_toks(msg)
        links = ml_links(msg)
        if links and not _mail_parts(mail_text(msg, att_images=True)[1], ei_is, ""):
            k = budget("links", len(links))
            pre = ml_collect(msg, limit=k, links=links) if k else ([], [])
    meta = {}
    if json.loads(rule["tags"] or "[]"):
        meta["tags"] = json.loads(rule["tags"])
    if rule["sender_from_mail"]:
        name, addr = email.utils.parseaddr(str(msg.get("From", "") or ""))
        if (name or addr).strip():
            meta["sender"] = (name or addr).strip()[:120]

    def run(c):
        if c.execute("INSERT INTO hub_mailbox_docs(box_id, mid, rule_id, at) VALUES(?,?,?,?) ON CONFLICT DO NOTHING RETURNING box_id",
                     (box["id"], key, rule["id"], _now())).fetchone() is None:
            return None, 0
        first, made = docs_mailbox_import(c, holder, box["org_id"] or None, msg, raw, meta=meta, parent_id=rule["target_id"],
                                          take_files=bool(rule["take_files"]), take_mail=bool(rule["take_mail"]), budget=budget, pre=pre)
        c.execute("UPDATE hub_mailbox_docs SET node_id=? WHERE box_id=? AND mid=?", (first or None, box["id"], key))
        if made:
            c.execute("UPDATE hub_mailbox_rules SET hits=hits+1, last_hit_at=? WHERE id=?", (_now(), rule["id"]))
        return bool(made), len(made)
    return _bg(run)


def _skip(box, key):
    """A mail no rule takes after it was fetched whole (too large, no attachment, failed): remembered, never fetched again."""
    _bg(lambda c: c.execute("INSERT INTO hub_mailbox_docs(box_id, mid, at) VALUES(?,?,?) ON CONFLICT DO NOTHING", (box["id"], key, _now())))


def mbr_due(box):
    """The rules of box run now: "Fetch now" (docs_due) or MBR_EVERY seconds after the last run."""
    return bool(box.get("docs_due")) or not box.get("docs_polled_at") or str(box["docs_polled_at"]) <= iso(now_utc() - timedelta(seconds=MBR_EVERY))


def mbr_run(M, box):
    """The document rules of mailbox box (a row as dict) on the logged-in connection M; stores the state. -> documents taken."""
    if not mbr_due(box):
        return 0
    rules = _bg(lambda c: [dict(x) for x in c.execute("SELECT * FROM hub_mailbox_rules WHERE box_id=? AND active=1 ORDER BY pos, id",
                                                       (box["id"],)).fetchall()])
    if not rules:
        if box["docs_due"]:
            _bg(lambda c: c.execute("UPDATE hub_mailboxes SET docs_due=0 WHERE id=?", (box["id"],)))
        return 0
    holder = _bg(lambda c: MB.mbx_holder(c, box))
    n, code, taken = 0, "", 0
    if not holder:
        code = "holder"
    folders = {}
    for r in rules:
        folders.setdefault(r["folder"] or box["imap_folder"] or "INBOX", []).append(r)
    for folder, frs in ([] if code else folders.items()):
        if taken >= MBR_TAKE:
            break
        try:
            typ, _ = M.select(MB._folder_arg(folder))
            if typ != "OK":
                code = code or "folder"
                continue
            day = now_utc() - timedelta(days=max(r["max_age"] for r in frs) + 1)
            since = f"{day.day:02d}-{_MONTHS[day.month - 1]}-{day.year}"  # IMAP's date (English month names, any locale)
            typ, data = M.uid("SEARCH", None, "UNDELETED", "SINCE", since)
            uids = (data[0] or b"").split()[-MBR_MAILS:] if typ == "OK" and data else []
            heads = _fetch_heads(M, uids)
            keys = {u: _mid_key(h) for u, (_sz, h) in heads.items()}
            known = set()
            if keys:
                ks = [k for k, _m in keys.values()]
                known = _bg(lambda c: {x[0] for x in c.execute(f"SELECT mid FROM hub_mailbox_docs WHERE box_id=? AND mid IN ({','.join('?' * len(ks))})",
                                                               (box["id"], *ks)).fetchall()})
            for u in uids:
                if taken >= MBR_TAKE:
                    break
                if u not in keys or keys[u][0] in known:
                    continue
                key, head = keys[u]
                fit = [r for r in frs if _head_fits(r, head)]
                if not fit:
                    continue  # its header lines fit no rule: looked at again next time (a new rule may take it)
                known.add(key)
                if heads[u][0] is None or heads[u][0] > MB.MBX_MAIL_MAX:
                    _skip(box, key)
                    continue
                typ, parts = M.uid("FETCH", u.decode(), "(BODY.PEEK[])")
                raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and len(p) > 1), None)
                if typ != "OK" or not raw:
                    continue
                msg = email.message_from_bytes(raw, policy=email.policy.default)
                files = None
                rule = None
                for r in fit:
                    if r["need_att"]:
                        if files is None:
                            _t, mail_text, _ei = _mail_toks(msg)
                            files = mail_text(msg, att_images=True)[1]
                        if not files:
                            continue
                    rule = r
                    break
                if rule is None:
                    _skip(box, key)
                    continue
                try:
                    handled, got = _take(box, holder, rule, key, raw)
                except Exception as e:  # noqa: BLE001 -- one mail never stops the others; it is not taken again
                    print("mailbox docs: one mail failed:", type(e).__name__, flush=True)
                    _skip(box, key)
                    continue
                if handled is None:
                    continue
                taken += 1
                n += got
                if handled:
                    code = _after(M, rule, u) or code
        except Exception as e:  # noqa: BLE001 -- the next folder goes on; the code is kept (never the server's words)
            code = code or MB._err_code(e)
            print("mailbox docs: ws", box["ws"], type(e).__name__, flush=True)
    if n:
        docs_kick()
    _bg(lambda c: c.execute("UPDATE hub_mailboxes SET docs_polled_at=?, docs_error=?, docs_due=0, docs_count=docs_count+? WHERE id=?",
                            (_now(), code, n, box["id"])))
    return n


MB.MBX_AFTER_POLL.append(mbr_run)
