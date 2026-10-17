"""2.42.0 (#828, #909): end-to-end encryption in the browser -- the key base, encrypted task notes and files, encrypted DMs.

Key model (the browser does all cryptography with WebCrypto; this server never sees a passphrase, a recovery code, a private
key or a content key):
- Per person an ECDH P-256 key pair and a random 256-bit content key (AES-GCM). Both together are the "bundle"; the browser
  wraps it twice: with PBKDF2-SHA256(passphrase, 16-byte salt, 600 000 rounds) and with a recovery code (160 random bits,
  HKDF-SHA256). AES-256-GCM, the AAD binds the user id and the version. Stored here: the public key (JWK) and the two
  wrapped bundles (e2e_keys). Passphrase and code lost = the encrypted content is lost.
- Task note (task_enc_notes): AES-GCM with the content key, AAD "kalmido-note:v1:<task_id>:<user_id>". Only its author
  reads / changes / deletes it; everybody else (people, agents, API, CalDAV, search, mail, push) gets at most
  encrypted_note: true.
- Task file (attachments.enc=1): the file is encrypted with the content key in the browser (name + type inside the
  encrypted header) and uploaded as an opaque blob: no text extraction, no preview, no inline answer, never for agents,
  downloaded only by its uploader.
- DM (tchat_rooms.e2e=1): ECDH(own private, other public) -> HKDF-SHA256(salt = room id, info "kalmido-dm:v1") ->
  AES-256-GCM, AAD "kalmido-dm:v1:<room_id>:<sender_id>". tchat_msgs.enc holds {v, iv, ct}, body stays empty; a plain
  message into such a room is refused. No forward secrecy.

The limit of a web app: this protects against the server operator, a reader of the database and the backups -- not
against a changed script delivered by the server itself.

Endpoints only for the signed-in person (agent accounts: 403). Another person's public key only where a DM is allowed."""
import json
import re

from flask import g, jsonify

from ..core.config import app
from ..core.i18n import tr
from ..core.db import body, bump, db, err, iso, iso_ms, now_utc
from ..accounts.session import me
from ..core.access import Denied, need_task, task_visible
from ..agents.core import is_agent
from ..tasks.validation import log_act

E2E_V = 1
E2E_B64 = re.compile(r"^[A-Za-z0-9+/=_-]*$")
E2E_NOTE_MAX = 400_000      # characters of the encrypted note (base64): ~300 KB of text
E2E_MSG_MAX = 16_000        # characters of an encrypted message (8000 characters of text, base64 + tag)
E2E_KDFS = ("pbkdf2-sha256", "hkdf-sha256")
E2E_SYS = ("on", "off")     # tchat_msgs.enc {"sys": ...}: a notice "encryption switched on / off" in the conversation


def e2e_person(c=None):
    """The signed-in person (agents: 403)."""
    if not g.get("user") or is_agent(g.user):
        raise Denied(403)
    return me()


def e2e_reauth(c, uid, b):
    """2.42.0 (#828): replacing or removing existing keys asks for the account password (like other security steps);
    accounts without a password (single sign-on / proxy) rely on their session. An error response or None."""
    from ..accounts.login import _reauth
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    return _reauth(u, b) if u and u["password_hash"] else None


def _b64(v, lo, hi):
    return isinstance(v, str) and lo <= len(v) <= hi and E2E_B64.match(v) is not None


def e2e_blob(v, max_ct):
    """A ciphertext {v: 1, iv, ct} (dict or its JSON) -> the JSON text to store, else None. Only the shape is checked:
    the server cannot (and must not) read it."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return None
    if not isinstance(v, dict) or set(v) != {"v", "iv", "ct"} or v.get("v") != E2E_V:
        return None
    if not _b64(v["iv"], 12, 24) or not _b64(v["ct"], 16, max_ct):
        return None
    return json.dumps({"v": E2E_V, "iv": v["iv"], "ct": v["ct"]}, separators=(",", ":"))


def _bundle(v):
    """A wrapped key bundle {v, kdf, iter?, salt, iv, ct} -> its JSON, else None."""
    if not isinstance(v, dict) or v.get("v") != E2E_V or v.get("kdf") not in E2E_KDFS:
        return None
    keys = {"v", "kdf", "salt", "iv", "ct"} | ({"iter"} if v["kdf"] == "pbkdf2-sha256" else set())
    if set(v) != keys:
        return None
    if "iter" in keys and (isinstance(v["iter"], bool) or not isinstance(v["iter"], int) or not 600_000 <= v["iter"] <= 10_000_000):
        return None
    if not _b64(v["salt"], 16, 64) or not _b64(v["iv"], 12, 24) or not _b64(v["ct"], 32, 8000):
        return None
    return json.dumps({k: v[k] for k in sorted(keys)}, separators=(",", ":"))


def _pub(v):
    """A public ECDH P-256 key as JWK {kty: EC, crv: P-256, x, y} -> its JSON, else None (no private part accepted)."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return None
    if not isinstance(v, dict) or v.get("kty") != "EC" or v.get("crv") != "P-256" or "d" in v:
        return None
    if not _b64(v.get("x"), 43, 44) or not _b64(v.get("y"), 43, 44):
        return None
    return json.dumps({"crv": "P-256", "kty": "EC", "x": v["x"], "y": v["y"]}, separators=(",", ":"))


def e2e_keys_of(c, uid):
    return c.execute("SELECT * FROM e2e_keys WHERE user_id=?", (uid,)).fetchone()


def e2e_has_keys(c, uid):
    return c.execute("SELECT 1 FROM e2e_keys WHERE user_id=?", (uid,)).fetchone() is not None


# ---------------------------------------------------------------- the person's keys
@app.get("/api/e2e/keys")
def e2e_keys_get():
    """{set, pub, bundle_pass, bundle_rec, created_at, updated_at} -- my own wrapped keys (the browser unwraps them)."""
    c = db()
    uid = e2e_person()
    r = e2e_keys_of(c, uid)
    u = c.execute("SELECT password_hash FROM users WHERE id=?", (uid,)).fetchone()
    pw = bool(u and u["password_hash"])  # password: changing / removing the keys asks for it
    if not r:
        return jsonify(set=False, password=pw)
    return jsonify(set=True, pub=json.loads(r["pub"]), bundle_pass=json.loads(r["bundle_pass"]), bundle_rec=json.loads(r["bundle_rec"]),
                   created_at=r["created_at"], updated_at=r["updated_at"], password=pw)


@app.put("/api/e2e/keys")
def e2e_keys_put():
    """{pub, bundle_pass, bundle_rec[, password]} -- set up (no keys yet) or re-wrap (new passphrase, reset with the recovery code: the
    public key stays the same). A different public key while keys exist = 409 (remove them first)."""
    c = db()
    uid = e2e_person()
    b = body()
    pub, bp, br = _pub(b.get("pub")), _bundle(b.get("bundle_pass")), _bundle(b.get("bundle_rec"))
    if not pub or not bp or not br or json.loads(bp)["kdf"] != "pbkdf2-sha256" or json.loads(br)["kdf"] != "hkdf-sha256":
        return err(tr("Invalid value: {0}", "keys"))
    ts = iso(now_utc())
    old = e2e_keys_of(c, uid)
    # repair: true (2.42.0, #909) = the browser found that the stored public key is not the one of its unlocked bundle and
    # stores the bundle's key again (with the password like every change of existing keys)
    if old and old["pub"] != pub and b.get("repair") is not True:
        return err(tr("Encryption is already set up. Remove the keys first."), 409)
    if old:
        e = e2e_reauth(c, uid, b)
        if e is not None:
            return e
    if old:
        c.execute("UPDATE e2e_keys SET pub=?, bundle_pass=?, bundle_rec=?, updated_at=? WHERE user_id=?", (pub, bp, br, ts, uid))
    else:
        c.execute("INSERT INTO e2e_keys(user_id,pub,bundle_pass,bundle_rec,created_at,updated_at) VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(user_id) DO NOTHING", (uid, pub, bp, br, ts, ts))
    c.commit()
    return jsonify(ok=True, set=True, created=not old)


@app.delete("/api/e2e/keys")
def e2e_keys_delete():
    """Removes my keys for good: my encrypted notes go with them, my encrypted DMs are switched off (their old messages
    stay unreadable), my encrypted files stay as unreadable files (I may delete them)."""
    c = db()
    uid = e2e_person()
    if not e2e_has_keys(c, uid):
        return jsonify(ok=True, removed=False)
    e = e2e_reauth(c, uid, body())
    if e is not None:
        return e
    tids = [r[0] for r in c.execute("SELECT task_id FROM task_enc_notes WHERE user_id=?", (uid,))]
    c.execute("DELETE FROM task_enc_notes WHERE user_id=?", (uid,))
    for r in c.execute("SELECT * FROM tchat_rooms WHERE kind='dm' AND e2e=1 AND (a=? OR b=?)", (uid, uid)).fetchall():
        e2e_room_set(c, r, False, uid)
    c.execute("DELETE FROM e2e_keys WHERE user_id=?", (uid,))
    if tids:
        bump(c)
    c.commit()
    return jsonify(ok=True, removed=True)


@app.get("/api/e2e/pub/<int:uid>")
def e2e_pub_get(uid):
    """The public key of a person I may write a DM to (or already have one with): {user_id, pub (null = not set up)}."""
    from ..collab.teamchat import tchat_coworkers
    c = db()
    mine = e2e_person()
    a, b = sorted((mine, uid))
    from .liste2e import le2a_shares_list
    if uid != mine and uid not in tchat_coworkers(c, mine) and not c.execute(
            "SELECT 1 FROM tchat_rooms WHERE kind='dm' AND a=? AND b=?", (a, b)).fetchone() \
            and not le2a_shares_list(c, mine, uid):  # 2.64.1 (#1817, H4): also the people I share a list with
        raise Denied(404)
    r = e2e_keys_of(c, uid)
    return jsonify(user_id=uid, pub=json.loads(r["pub"]) if r else None)


# ---------------------------------------------------------------- #828 the encrypted note of a task
def e2e_note_flags(c, ids, uid):
    """{task_id: mine (bool)} of the tasks in ids that carry an encrypted note (anyone's)."""
    out = {}
    if not ids:
        return out
    ids = list(ids)
    for i in range(0, len(ids), 5000):
        part = ids[i:i + 5000]
        for r in c.execute(f"SELECT task_id, user_id FROM task_enc_notes WHERE task_id IN ({','.join('?' * len(part))})", part):
            out[r[0]] = out.get(r[0], False) or r[1] == uid
    return out


def _note_task(c, tid, write):
    uid = e2e_person()
    need_task(c, tid, write=False, full=True)  # who sees the task with its notes may keep an own encrypted note there
    if c.execute("SELECT deleted_at FROM tasks WHERE id=?", (tid,)).fetchone()[0]:
        raise Denied(404)
    return uid


@app.get("/api/tasks/<int:tid>/enc-note")
def e2e_note_get(tid):
    """{body: {v, iv, ct}, updated_at} -- my own encrypted note of the task (404: none)."""
    c = db()
    uid = _note_task(c, tid, False)
    r = c.execute("SELECT body, updated_at FROM task_enc_notes WHERE task_id=? AND user_id=?", (tid, uid)).fetchone()
    if not r:
        raise Denied(404)
    return jsonify(task_id=tid, body=json.loads(r["body"]), updated_at=r["updated_at"])


@app.put("/api/tasks/<int:tid>/enc-note")
def e2e_note_put(tid):
    """{body: {v, iv, ct}} -- write my encrypted note (needs my keys)."""
    c = db()
    uid = _note_task(c, tid, True)
    if not e2e_has_keys(c, uid):
        return err(tr("Set up end-to-end encryption first (Settings > Account)."), 409)
    enc = e2e_blob(body().get("body"), E2E_NOTE_MAX)
    if not enc:
        return err(tr("Invalid value: {0}", "body"))
    ts = iso_ms(now_utc())
    new = c.execute("SELECT 1 FROM task_enc_notes WHERE task_id=? AND user_id=?", (tid, uid)).fetchone() is None
    c.execute("INSERT INTO task_enc_notes(task_id,user_id,body,updated_at) VALUES(?,?,?,?) ON CONFLICT(task_id,user_id) "
              "DO UPDATE SET body=excluded.body, updated_at=excluded.updated_at", (tid, uid, enc, ts))
    if new:
        bump(c)  # the task's flag encrypted_note changes (nothing of the content goes anywhere else)
    c.commit()
    return jsonify(ok=True, task_id=tid, updated_at=ts)


@app.delete("/api/tasks/<int:tid>/enc-note")
def e2e_note_delete(tid):
    c = db()
    uid = _note_task(c, tid, False)
    n = c.execute("DELETE FROM task_enc_notes WHERE task_id=? AND user_id=?", (tid, uid)).rowcount
    if n:
        bump(c)
    c.commit()
    return jsonify(ok=True, removed=bool(n))


# ---------------------------------------------------------------- #828 encrypted files of a task
@app.post("/api/tasks/<int:tid>/enc-attachments")
def e2e_attachment_upload(tid):
    """multipart "file": one file the browser encrypted (opaque). Stored like a task file (size limit, quota, storage), marked
    enc=1 / enc_by=me, with a neutral name -- the real name and type are inside the encrypted header."""
    from flask import request
    from werkzeug.datastructures import FileStorage
    from ..tasks.attachments import save_attachments
    from ..core.serializers import unlink_files
    from ..tasks.tasks import one_task
    c = db()
    uid = e2e_person()
    need_task(c, tid)
    if not e2e_has_keys(c, uid):
        return err(tr("Set up end-to-end encryption first (Settings > Account)."), 409)
    files = request.files.getlist("file")
    if len(files) != 1:
        return err(tr("File missing"))
    f = files[0]
    head = f.stream.read(5)
    f.stream.seek(0)
    if head != b"KENC\x01":  # the format's magic + version (static/js/e2e.js e2eFileEncrypt)
        return err(tr("Invalid value: {0}", "file"))
    blob = FileStorage(stream=f.stream, filename="encrypted.kenc", content_type="application/octet-stream")
    saved, ids = [], []
    e = save_attachments(c, tid, [blob], saved=saved, uid=uid, ids=ids)
    if e:
        c.rollback()
        unlink_files(saved)
        return err(e)
    aid = ids[0]  # the row save_attachments inserted (not "the newest row": a parallel upload may be newer)
    c.execute("UPDATE attachments SET enc=1, enc_by=?, mime='application/octet-stream' WHERE id=?", (uid, aid))
    log_act(c, tid, "attach", {"names": [tr("Encrypted file")], "n": 1})
    bump(c)
    c.commit()
    return jsonify(one_task(c, tid))


def e2e_att_guard(a):
    """need_attachment(read): an encrypted file only for its uploader (people; agents never)."""
    if "enc" in a.keys() and a["enc"] == 2:  # 2.64.2 B (#1817): a list file: every person with the list key (read right checked by the caller)
        from .liste2efile import le2f_att_guard
        return le2f_att_guard(a)
    if "enc" in a.keys() and a["enc"]:
        if not g.get("user") or is_agent(g.user) or a["enc_by"] != me():
            raise Denied(404)


# ---------------------------------------------------------------- #909 encrypted direct messages
def e2e_room_set(c, r, on, uid):
    """Switch a DM's encryption and leave a notice in the conversation ({"sys": "on" | "off"}, body empty)."""
    c.execute("UPDATE tchat_rooms SET e2e=? WHERE id=?", (int(on), r["id"]))
    ts = iso_ms(now_utc())
    c.execute("INSERT INTO tchat_msgs(room_id,user_id,body,created_at,enc) VALUES(?,?,?,?,?)",
              (r["id"], uid, "", ts, json.dumps({"sys": "on" if on else "off"})))
    c.execute("UPDATE tchat_rooms SET last_at=? WHERE id=?", (ts, r["id"]))


@app.post("/api/team/rooms/<int:rid>/e2e")
def e2e_room_toggle(rid):
    """{on: bool} -- either person of a DM switches its encryption (on: both must have set up their keys)."""
    from ..collab.teamchat import need_room, need_tchat
    from ..collab.comments import user_names
    c = db()
    uid = e2e_person()
    need_tchat(c)
    r = need_room(c, rid)
    if r["kind"] != "dm":
        return err(tr("Only direct messages can be encrypted"))
    on = body().get("on")
    if not isinstance(on, bool):
        return err(tr("Invalid value: {0}", "on"))
    if on:
        other = r["b"] if r["a"] == uid else r["a"]
        if not e2e_has_keys(c, uid):
            return err(tr("Set up end-to-end encryption first (Settings > Account)."), 409)
        if not e2e_has_keys(c, other):
            return err(tr("{0} has not set up encryption yet", user_names(c, [other]).get(other, "?")), 409)
    if bool(r["e2e"]) != on:
        e2e_room_set(c, r, on, uid)
    c.commit()
    return jsonify(ok=True, id=rid, e2e=on)


def e2e_msg_parse(v):
    """tchat_msgs.enc -> the dict for the client: {v, iv, ct} | {sys} | None."""
    if not v:
        return None
    try:
        d = json.loads(v)
    except ValueError:
        return None
    return d if isinstance(d, dict) else None
