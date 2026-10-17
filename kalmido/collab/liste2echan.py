"""Kalmido: the list channel (team chat room kind 'list') of a list with the lock (2.64.2, #1817, stage 2).

Messages carry tchat_msgs.enc = {"v":1,"g":<gen>,"iv","ct"} (body ''), AES-256-GCM with the list key of generation g,
AAD "kalmido-chan:v1:<room_id>:<gen>:<sender_id>", padded like the list texts. Post / edit guards, conversion when the lock
goes on / off / after a key change, neutral push and agent events live here (part C). No plain copy of a channel message
exists outside tchat_msgs: agent events and webhook deliveries of the list go with le2b_scrub (they carry the list id),
search skips the channels of locked lists (msgsearch), a saved message (chatsave) is refused for a ciphertext."""
import json

from ..core.db import err
from ..core.i18n import tr
from .e2e import E2E_MSG_MAX, E2E_B64, e2e_msg_parse
from .liste2e import le2a_gen, le2a_reenc_again, le2e_writer_ok


def le2c_blob(v, gen):
    """A channel ciphertext {v: 1, g, iv, ct} (dict or its JSON) of a generation 1..gen -> the JSON text to store, else None.
    Only the shape is checked."""
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except ValueError:
            return None
    if not isinstance(v, dict) or set(v) != {"v", "g", "iv", "ct"} or v.get("v") != 1:
        return None
    g = v.get("g")
    if isinstance(g, bool) or not isinstance(g, int) or not 1 <= g <= gen:
        return None
    for k, lo, hi in (("iv", 12, 24), ("ct", 16, E2E_MSG_MAX)):
        x = v.get(k)
        if not isinstance(x, str) or not lo <= len(x) <= hi or not E2E_B64.match(x):
            return None
    return json.dumps({"v": 1, "g": g, "iv": v["iv"], "ct": v["ct"]}, separators=(",", ":"))


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
    return err(tr("This list is encrypted in the browser. Texts can only be changed in the app."), 409)


def le2c_check(c, r, b):
    """tchat_post of a list channel: the ciphertext to store (JSON text), None for a plain message, or an error response.
    A channel of a list with the lock takes only a ciphertext of the list key from the web app; an open channel refuses one."""
    mode, gen = le2c_mode(c, r)
    if not mode:
        return err(tr("This conversation is not encrypted"), 409) if b.get("enc") is not None else None
    if mode != "on":
        return err(tr("This list is being encrypted. Try again in a moment."), 409)
    if not le2e_writer_ok() or (isinstance(b.get("body"), str) and b["body"].strip()):
        return _le2c_refuse()
    enc = le2c_blob(b.get("enc"), gen)
    if enc and json.loads(enc)["g"] < gen:  # 2.64.2 review (M2): an older generation after a key change: re-encrypt again
        le2a_reenc_again(c, r["list_id"])
    return enc or err(tr("Invalid value: {0}", "enc"))


def le2c_mentions(c, r, b):
    """@mentions of an encrypted channel message: the browser names them (ids), only members of the room count."""
    from .teamchat import tchat_room_members
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
        return None, err(tr("This list is being encrypted. Try again in a moment."), 409)
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
    from .teamchat import TCHAT_MAX
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

