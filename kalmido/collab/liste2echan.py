"""Kalmido: the list channel (team chat room kind 'list') of a list with the lock (2.64.2, #1817, stage 2).

Messages carry tchat_msgs.enc = {"v":1|2,"g":<gen>,"iv","ct"} (body ''), AES-256-GCM with the list key of generation g,
AAD "kalmido-chan:v1:<room_id>:<gen>:<sender_id>" (v 1) or, since 2.640.0 (#3388), "kalmido-chan:v2:<room_id>:<gen>:<sender_id>:
<message id>" (v 2: a ciphertext opens only as its own message), padded like the list texts. A new v2 message is stored under
the id the browser reserved before encrypting (POST /api/team/rooms/<rid>/msgid, collab/e2eresv.py). 2.652.0 (#5044): a NEW
message takes v 2 only (v 1: 400 code e2e_v1_new, le2c_take); editing a message, the re-encryption and reading still take v 1
(messages from before 2.640 keep opening). Post / edit guards, conversion when the lock
goes on / off / after a key change, neutral push and agent events live here (part C). No plain copy of a channel message
exists outside tchat_msgs: agent events and webhook deliveries of the list go with le2b_scrub (they carry the list id),
search skips the channels of locked lists (msgsearch), a saved message (chatsave) is refused for a ciphertext."""
import json

from flask import jsonify

from ..core.config import app
from ..core.db import db, err, write_lock
from ..core.i18n import tr
from .e2e import E2E_MSG_MAX, E2E_B64, e2e_msg_parse
from .liste2e import le2a_gen, le2a_reenc_again, le2e_writer_ok
from .teamchat import tchat_room_members, TCHAT_MAX  # 2.369.5 (#2517): pulled up from functions
from .teamchat import need_room, tchat_need_say, need_tchat  # 2.640.0 (#3388)
from .e2eresv import e2r_new, e2r_ok  # 2.640.0 (#3388)
from ..accounts.session import me


def le2c_blob(v, gen):
    """A channel ciphertext {v: 1|2, g, iv, ct} (dict or its JSON) of a generation 1..gen -> the JSON text to store, else None.
    Only the shape is checked (2.640.0, #3388: v 2 = the message id is in the AAD)."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return None
    if not isinstance(v, dict) or set(v) != {"v", "g", "iv", "ct"} or v.get("v") not in (1, 2) or isinstance(v.get("v"), bool):
        return None
    g = v.get("g")
    if isinstance(g, bool) or not isinstance(g, int) or not 1 <= g <= gen:
        return None
    for k, lo, hi in (("iv", 12, 24), ("ct", 16, E2E_MSG_MAX)):
        x = v.get(k)
        if not isinstance(x, str) or not lo <= len(x) <= hi or not E2E_B64.match(x):
            return None
    return json.dumps({"v": v["v"], "g": g, "iv": v["iv"], "ct": v["ct"]}, separators=(",", ":"))


def le2c_gen_of(enc):
    """The generation of a stored channel ciphertext (0 = none / a notice / a DM blob)."""
    d = e2e_msg_parse(enc) or {}
    g = d.get("g")
    return g if isinstance(g, int) and not isinstance(g, bool) else 0


def le2c_mode(c, r):
    """(mode, gen) of a room: a list channel of a list with the lock -> its state, else (None, 0)."""
    if not r or r["kind"] != "list":
        return None, 0
    return le2a_gen(c, r["list_id"])


def _le2c_refuse():
    return err(tr("This project is encrypted in the browser. Texts can only be changed in the app."), 409)


def le2c_check(c, r, b):
    """tchat_post of a list channel: the ciphertext to store (JSON text), None for a plain message, or an error response.
    A channel of a list with the lock takes only a ciphertext of the list key from the web app; an open channel refuses one."""
    mode, gen = le2c_mode(c, r)
    if not mode:
        return err(tr("This conversation is not encrypted"), 409) if b.get("enc") is not None else None
    if mode != "on":
        return err(tr("This project is being encrypted. Try again in a moment."), 409)
    if not le2e_writer_ok() or (isinstance(b.get("body"), str) and b["body"].strip()):
        return _le2c_refuse()
    enc = le2c_blob(b.get("enc"), gen)
    if enc and json.loads(enc)["g"] < gen:  # 2.64.2 review (M2): an older generation after a key change: re-encrypt again
        le2a_reenc_again(c, r["list_id"])
    return enc or err(tr("Invalid value: {0}", "enc"))


def le2c_take(c, r, b, enc, uid):
    """2.640.0 (#3388): the id a new v2 message is stored under (the one reserved for uid in this room, it is in the AAD), or an
    error response. 409 chan_resv_stale when another message of the room came in after the reservation: the browser encrypts
    once more with a new id, so the ids keep the order of the room (read marks and "unread" count by id). 2.652.0 (#5044): a
    v1 message (an app tab from before 2.640, two versions later) is refused with 400 code e2e_v1_new -- only a new message:
    editing one and the re-encryption still take v1."""
    if json.loads(enc)["v"] != 2:
        return jsonify(error=tr("Please reload the app."), code="e2e_v1_new"), 400
    mid = b.get("msg_id")
    if not e2r_ok(c, "chan", r["id"], uid, mid, b.get("resv")):
        return err(tr("Invalid value: {0}", "msg_id"))
    write_lock(c, f"le2c-room-{r['id']}")
    newest = c.execute("SELECT MAX(id) FROM tchat_msgs WHERE room_id=?", (r["id"],)).fetchone()[0]
    if newest and newest > mid:
        return jsonify(error=tr("Another message arrived at the same moment. Please send again."), code="chan_resv_stale"), 409
    return mid


@app.post("/api/team/rooms/<int:rid>/msgid")
def le2c_msgid(rid):
    """2.640.0 (#3388): {id, resv} -- the id of the next message I write in the channel of a list with the lock (web app only)."""
    c = db()
    need_tchat(c)
    r = need_room(c, rid)
    tchat_need_say(c, r)  # 2.981.0 (#5274): the core's say rule
    mode, _gen = le2c_mode(c, r)
    if not mode:
        return err(tr("This conversation is not encrypted"), 409)
    if mode != "on":
        return err(tr("This project is being encrypted. Try again in a moment."), 409)
    if not le2e_writer_ok():
        return _le2c_refuse()
    out = e2r_new(c, "chan", r["id"], me())
    c.commit()
    return jsonify(out)


def le2c_mentions(c, r, b):
    """@mentions of an encrypted channel message: the browser names them (ids), only members of the room count."""
    ids = b.get("mentions")
    if not isinstance(ids, list):
        return []
    mem = tchat_room_members(c, r)
    return list(dict.fromkeys(u for u in ids if isinstance(u, int) and not isinstance(u, bool) and u in mem))[:50]


def le2c_edit(c, r, m, b):
    """tchat_edit in a list channel of a list with the lock: (ciphertext to store, None) or (None, error response); (None, None)
    for an open channel (the plain way goes on)."""
    mode, gen = le2c_mode(c, r)
    if not mode:
        if b.get("enc") is not None:
            return None, err(tr("This conversation is not encrypted"), 409)
        return None, None
    if mode != "on":
        return None, err(tr("This project is being encrypted. Try again in a moment."), 409)
    if (e2e_msg_parse(m["enc"]) or {}).get("sys") or not le2e_writer_ok() or (isinstance(b.get("body"), str) and b["body"].strip()):
        return None, _le2c_refuse()
    enc = le2c_blob(b.get("enc"), gen)
    if enc and json.loads(enc)["g"] < gen:  # 2.64.2 review (M2)
        le2a_reenc_again(c, r["list_id"])
    return (enc, None) if enc else (None, err(tr("Invalid value: {0}", "enc")))


def le2c_room(c, r):
    """What the room answer adds for a list channel with the lock: {list_e2e: mode, gen}."""
    mode, gen = le2c_mode(c, r)
    return {"list_e2e": mode, "gen": gen} if mode else {}


def le2c_out(c, r, msgs):
    """Messages of a channel with the lock for an agent / an API token (no web app): no ciphertext, no text, encrypted: true."""
    mode, _gen = le2c_mode(c, r)
    if not mode or le2e_writer_ok():
        return msgs
    out = []
    for d in msgs:
        d = {**d, "body": "", "enc": None, "encrypted": True}
        if d.get("reply"):
            d["reply"] = {**d["reply"], "text": "", "body": ""} if isinstance(d["reply"], dict) else None
        out.append(d)
    return out


# ---- conversion: switching on / off and the re-encryption after a key change (part A's todo / bulk call these)
def _le2c_rooms(c, lid):
    return [x[0] for x in c.execute("SELECT id FROM tchat_rooms WHERE kind='list' AND list_id=?", (lid,))]


def _le2c_todo(row, mode, gen):
    if row["deleted_at"]:
        return False
    if mode == "encrypting":
        return not row["enc"] and (row["body"] or "") != ""
    g = le2c_gen_of(row["enc"])
    if mode == "decrypting":
        return g > 0
    return (not row["enc"] and (row["body"] or "") != "") or 0 < g < gen  # on: re-encryption to gen (and leftovers)


def le2c_left(c, lid, mode, gen, limit=None):
    """The channel messages of list lid not yet in the target format: ([{id, room_id, user_id, body, enc}], count).
    mode encrypting = plain messages; on = ciphertexts of an older generation than gen (and plain leftovers);
    decrypting = every ciphertext of the list key. gen = lists.e2e_gen (the target generation).
    2.64.2 review (M4): chosen and counted in SQL (a long channel is not read into Python on every call)."""
    rooms = _le2c_rooms(c, lid)
    if not rooms:
        return [], 0
    q = ",".join("?" * len(rooms))
    plain = "(enc IS NULL AND body<>'')"
    g = "(enc::jsonb->>'g')::bigint"  # NULL for a notice {sys} (enc is always JSON written by the server)
    cond, args = {"encrypting": (plain, []), "decrypting": (f"(enc IS NOT NULL AND {g} IS NOT NULL)", []),
                  "on": (f"({plain} OR (enc IS NOT NULL AND {g} < ?))", [gen])}[mode]
    base = f"FROM tchat_msgs WHERE room_id IN ({q}) AND deleted_at IS NULL AND {cond}"
    n = c.execute(f"SELECT COUNT(*) {base}", (*rooms, *args)).fetchone()[0]
    if not limit or not n:
        return [], n
    rows = c.execute(f"SELECT id, room_id, user_id, body, enc {base} ORDER BY id LIMIT ?", (*rooms, *args, limit)).fetchall()
    return [{"id": r["id"], "room_id": r["room_id"], "user_id": r["user_id"], "body": r["body"] if not r["enc"] else "",
             "enc": e2e_msg_parse(r["enc"]) if r["enc"] else None} for r in rows], n


def le2c_bulk(c, lid, mode, gen, rows):
    """Writes converted channel messages of list lid: [{id, enc}] (encrypting / on: a ciphertext of generation gen) or
    [{id, body}] (decrypting). Only messages that are still to do; no edit mark, no push. -> number written, or raises ValueError."""
    if not rows:
        return 0
    if not isinstance(rows, list):
        raise ValueError("msgs")
    rooms = set(_le2c_rooms(c, lid))
    n = 0
    for x in rows:
        if not isinstance(x, dict) or isinstance(x.get("id"), bool) or not isinstance(x.get("id"), int):
            raise ValueError("msgs")
        m = c.execute("SELECT id, room_id, user_id, body, enc, deleted_at FROM tchat_msgs WHERE id=?", (x["id"],)).fetchone()
        if not m or m["room_id"] not in rooms:
            raise ValueError("msgs")
        if not _le2c_todo(m, mode, gen):
            continue  # done meanwhile (another tab): idempotent
        if mode == "decrypting":
            text = x.get("body")
            if not isinstance(text, str) or len(text) > TCHAT_MAX or text.startswith("e2e1:"):
                raise ValueError("msgs")
            c.execute("UPDATE tchat_msgs SET body=?, enc=NULL WHERE id=?", (text, m["id"]))
        else:
            enc = le2c_blob(x.get("enc"), gen)
            if not enc or json.loads(enc)["g"] != gen:
                raise ValueError("msgs")
            c.execute("UPDATE tchat_msgs SET body='', enc=? WHERE id=?", (enc, m["id"]))
        n += 1
    return n

