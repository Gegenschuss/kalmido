"""2.48.0 (#1111): documents -- the data side (no routes): workspaces, sealing, labels, the word index, the recognition run
and the training of the learning classifier.

A document is a file of the file store (kalmido/files/store.py, fs_nodes) plus its doc_meta row. Its workspace (ws) is the
one of its node: 'o<org id>' for an organisation's tree, 'u<owner id>' for a person's own tree. Senders, types, tags, rules,
models and the word index belong to exactly one workspace; nothing here ever moves a document into another workspace.

Encryption at rest: documents are the most sensitive data. The recognised text, the amount, sender names, rules, models and
suggestions are sealed (AES-256-GCM, "kenc1:") with the workspace key: the organisation's key (core/orgcrypt.py) or, for a
person's own documents, a key derived from the server key per person (the text of a private document is sealed like
the text cache of attachments; 2.64.0 (#1864): its file itself with the owner's account key, core/orgcrypt.py). Without
a server key / with org_encrypt=0 the values stay plain, as everywhere. The full-text search uses no plain index: doc_words holds HMAC-SHA256 hashes (keyed per workspace)
of the folded words plus prefix hashes of 4, 6 and 8 characters; a query word is looked up by its hash (or by its longest
stored prefix and then checked against the opened text)."""
import hashlib
import hmac
import json
import re

from ..core.config import SECRET_KEY
from ..core.db import insert_id, iso, now_utc
from ..core.i18n import N_
from ..core.orgcrypt import OrgCryptError, PREFIX, oc_active, oc_dec_k, oc_enc_k, oc_key
from . import classify as CL
from . import extract as EX
from . import rules as RU

STATES = ("wait", "run", "done", "failed")
LABEL_KINDS = {"sender": "doc_senders", "type": "doc_types", "tag": "doc_tags"}
ROOT = "Dokumente"          # the documents folder at the root of a workspace's file tree
INBOX = "Eingang"           # its inbox folder: files put there are recognised and sorted
PREFIXES = (4, 6, 8)        # prefix lengths kept in the word index
WORDS_MAX = 4000            # distinct words of one document in the index
NAME_MAX = 120
ASN_PREFIX_RE = r"[A-Za-z][A-Za-z0-9-]{0,9}"  # the prefix of archive serial numbers (letters first, at most 10)
THUMB_DIR = "docthumbs"   # below ATT_DIR: the preview images (sealed like the file)
ERRORS = {
    "no_ocr": N_("Text recognition is not available on this server."),
    "encrypted": N_("The PDF is password-protected and cannot be read."),
    "unreadable": N_("The file is damaged or cannot be read."),
    "too_complex": N_("The file took too long or too much memory to read."),
    "missing": N_("The file is missing on the server."),
    "failed": N_("The recognition failed."),
}


def _now():
    return iso(now_utc())


# ---- workspaces and keys --------------------------------------------------------------------------------------------
def doc_ws(org_id, owner_id):
    return f"o{int(org_id)}" if org_id else f"u{int(owner_id)}"


def ws_org(ws):
    return int(ws[1:]) if ws and ws[0] == "o" else None


_PKEYS = {}


def _ws_key(c, ws, create=True):
    """The key that seals values of workspace ws (None without a server key)."""
    if not SECRET_KEY:
        return None
    oid = ws_org(ws)
    if oid:
        return oc_key(c, oid, create=create)
    k = _PKEYS.get(ws)
    if k is None:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        k = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kalmido-docs-v1|" + ws.encode()).derive(SECRET_KEY)
        _PKEYS[ws] = k
    return k


def doc_seal(c, ws, ctx, value):
    """value sealed with the workspace key (unchanged: empty, encryption off, no server key)."""
    if value is None or value == "" or not oc_active(c):
        return value
    key = _ws_key(c, ws)
    return oc_enc_k(key, ws_org(ws) or 0, f"{ctx}|{ws}", value) if key else value


def doc_open(c, ws, ctx, value, default=""):
    """The plain value; default when a sealed value cannot be opened (another server key, a lost organisation key)."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        return oc_dec_k(_ws_key(c, ws, create=False), ws_org(ws) or 0, f"{ctx}|{ws}", value)
    except OrgCryptError:
        return default


def _jopen(c, ws, ctx, value, default):
    try:
        v = json.loads(doc_open(c, ws, ctx, value) or "null")
    except ValueError:
        v = None
    return v if isinstance(v, type(default)) else default


def _jseal(c, ws, ctx, value):
    return doc_seal(c, ws, ctx, json.dumps(value, ensure_ascii=False, separators=(",", ":")))


# ---- the word index ---------------------------------------------------------------------------------------------------
_IKEYS = {}


def _index_key(c, ws):
    k = _IKEYS.get(ws)
    if k is None:
        base = _ws_key(c, ws) or hashlib.sha256(b"kalmido-docs-index-without-server-key").digest()
        k = hmac.new(base, b"kalmido-docs-index-v1|" + ws.encode(), hashlib.sha256).digest()
        _IKEYS[ws] = k
    return k


def index_words(text):
    """The distinct folded words of a text for the index (letters and digits, 2+ characters)."""
    out, seen = [], set()
    for w in re.findall(r"\w+", RU.fold(text)):
        if len(w) < 2 or len(w) > 40 or w in seen:
            continue
        seen.add(w)
        out.append(w)
        if len(out) >= WORDS_MAX:
            break
    return out


def _h(key, s):
    return hmac.new(key, s.encode(), hashlib.sha256).hexdigest()[:20]


def word_hashes(c, ws, words):
    key = _index_key(c, ws)
    hs = set()
    for w in words:
        hs.add(_h(key, "w:" + w))
        for n in PREFIXES:
            if len(w) >= n:
                hs.add(_h(key, f"p{n}:" + w[:n]))
    return hs


def query_hashes(c, ws, word):
    """(hash, exact) for one query word: the whole word (exact), else the longest stored prefix (to be checked)."""
    key = _index_key(c, ws)
    if len(word) < PREFIXES[0]:
        return _h(key, "w:" + word), True
    n = max(p for p in PREFIXES if p <= len(word))
    return _h(key, f"p{n}:" + word[:n]), n == len(word)


def doc_index(c, nid, ws, text):
    c.execute("DELETE FROM doc_words WHERE node_id=?", (nid,))
    hs = sorted(word_hashes(c, ws, index_words(text)))
    for i in range(0, len(hs), 500):
        part = hs[i:i + 500]
        c.execute("INSERT INTO doc_words(node_id, h) VALUES " + ",".join(["(?,?)"] * len(part)) + " ON CONFLICT DO NOTHING",
                  [x for h in part for x in (nid, h)])


def search_ids(c, ws_nodes, query):
    """The node ids of ws_nodes ({ws: [node ids]}) whose indexed text has every word of query (a prefix for words of 4+
    characters). Returns a set."""
    words = index_words(query)[:8]
    if not words:
        return None
    hits = set()
    for ws, ids in ws_nodes.items():
        if not ids:
            continue
        cand = set(ids)
        check = []
        for w in words:
            h, exact = query_hashes(c, ws, w)
            ids_ = sorted(cand)
            cand = set()
            for i in range(0, len(ids_), 5000):  # the database takes a limited number of parameters per statement
                part = ids_[i:i + 5000]
                cand |= {r[0] for r in c.execute(f"SELECT node_id FROM doc_words WHERE h=? AND node_id IN ({','.join('?' * len(part))})",
                                                 (h, *part))}
            if not exact:
                check.append(w)
            if not cand:
                break
        if cand and check:
            ok = set()
            for r in c.execute(f"SELECT node_id, text FROM doc_meta WHERE node_id IN ({','.join('?' * len(cand))})", tuple(cand)):
                have = set(index_words(doc_open(c, ws, "doc_meta.text", r["text"])))
                name = c.execute("SELECT name FROM fs_nodes WHERE id=?", (r["node_id"],)).fetchone()
                have |= set(index_words(name[0] if name else ""))
                if all(any(x.startswith(w) for x in have) for w in check):
                    ok.add(r["node_id"])
            cand = ok
        hits |= cand
    return hits


# ---- labels (senders, types, tags) ------------------------------------------------------------------------------------
def labels(c, ws, kind):
    """[{id, name}] of one kind in workspace ws, sorted by name."""
    rows = c.execute(f"SELECT id, name FROM {LABEL_KINDS[kind]} WHERE ws=?", (ws,)).fetchall()
    out = [{"id": r["id"], "name": doc_open(c, ws, "doc_senders.name", r["name"]) if kind == "sender" else r["name"]} for r in rows]
    return sorted(out, key=lambda x: (x["name"] or "").lower())


def label_name(c, ws, kind, lid):
    """The name of a label (None when it is not one of ws). Within a request the names of a workspace are read once."""
    if not lid:
        return None
    from flask import g, has_request_context
    if has_request_context():
        cache = g.setdefault("doc_labels", {})
        if (ws, kind) not in cache:
            cache[(ws, kind)] = {x["id"]: x["name"] for x in labels(c, ws, kind)}
        return cache[(ws, kind)].get(int(lid))
    r = c.execute(f"SELECT name FROM {LABEL_KINDS[kind]} WHERE id=? AND ws=?", (int(lid), ws)).fetchone()
    if not r:
        return None
    return doc_open(c, ws, "doc_senders.name", r[0]) if kind == "sender" else r[0]


def label_id(c, ws, kind, name, create=True):
    """The id of the label `name` (case-insensitive) in ws; created when missing (create=True). None for an empty name."""
    name = re.sub(r"\s+", " ", str(name or "")).strip()[:NAME_MAX]
    if not name:
        return None
    low = name.lower()
    for x in labels(c, ws, kind):
        if (x["name"] or "").lower() == low:
            return x["id"]
    if not create:
        return None
    val = doc_seal(c, ws, "doc_senders.name", name) if kind == "sender" else name
    from ..core.db import insert_id
    from flask import g, has_request_context
    if has_request_context():
        g.setdefault("doc_labels", {}).pop((ws, kind), None)
    return insert_id(c, f"INSERT INTO {LABEL_KINDS[kind]}(org_id, ws, name, created_at) VALUES(?,?,?,?)", (ws_org(ws), ws, val, _now()))


def label_ok(c, ws, kind, lid):
    return bool(lid) and c.execute(f"SELECT 1 FROM {LABEL_KINDS[kind]} WHERE id=? AND ws=?", (int(lid), ws)).fetchone() is not None


def node_tags(c, nid):
    return [{"id": r[0], "name": r[1], "auto": r[2] or ""} for r in c.execute(
        "SELECT t.id, t.name, nt.auto FROM doc_node_tags nt JOIN doc_tags t ON t.id=nt.tag_id WHERE nt.node_id=? ORDER BY lower(t.name)", (nid,))]


def set_tags(c, nid, tag_ids, auto=""):
    """Replace the tags of a document (ids of its workspace; the caller checked them)."""
    c.execute("DELETE FROM doc_node_tags WHERE node_id=?", (nid,))
    for t in dict.fromkeys(tag_ids):
        c.execute("INSERT INTO doc_node_tags(node_id, tag_id, auto) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                  (nid, int(t), auto if isinstance(auto, str) else (auto.get(t) or "")))


# ---- settings, rules, models -----------------------------------------------------------------------------------------
def cfg_get(c, ws):
    r = c.execute("SELECT data FROM doc_cfg WHERE ws=?", (ws,)).fetchone()
    try:
        d = json.loads(r[0]) if r else {}
    except ValueError:
        d = {}
    pre = str(d.get("asn_prefix") or "ASN")
    return {"levels": RU.levels(d.get("levels")), "inbox": d.get("inbox", True) is not False,
            "asn_prefix": pre if re.fullmatch(ASN_PREFIX_RE, pre) else "ASN"}


def cfg_set(c, ws, data):
    cur = cfg_get(c, ws)
    if isinstance(data.get("levels"), dict):
        cur["levels"] = RU.levels({**cur["levels"], **data["levels"]})
    if "inbox" in data:
        cur["inbox"] = bool(data["inbox"])
    if "asn_prefix" in data:
        pre = str(data["asn_prefix"] or "").strip()
        if not re.fullmatch(ASN_PREFIX_RE, pre):
            raise ValueError("asn_prefix")
        cur["asn_prefix"] = pre
    rid = root_id(c, ws)  # 2.48.0 review: the mark of the documents folder stays
    if rid:
        cur["root_id"] = rid
    c.execute("""INSERT INTO doc_cfg(ws, org_id, data, updated_at) VALUES(?,?,?,?)
                 ON CONFLICT(ws) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
              (ws, ws_org(ws), json.dumps(cur), _now()))
    return cur


def rules_get(c, ws):
    out = []
    for r in c.execute("SELECT id, pos, data FROM doc_rules WHERE ws=? ORDER BY pos, id", (ws,)):
        d = _jopen(c, ws, "doc_rules.data", r["data"], {})
        if d:
            out.append({"id": r["id"], **d})
    return out


def model_get(c, ws, feature):
    r = c.execute("SELECT data FROM doc_models WHERE ws=? AND feature=?", (ws, feature)).fetchone()
    m = _jopen(c, ws, "doc_models.data", r[0], {}) if r else {}
    if feature == "tags":
        return m
    return m if m.get("classes") is not None else CL.new_model()


def model_put(c, ws, feature, m):
    c.execute("""INSERT INTO doc_models(org_id, ws, feature, data, updated_at) VALUES(?,?,?,?,?)
                 ON CONFLICT(ws, feature) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
              (ws_org(ws), ws, feature, _jseal(c, ws, "doc_models.data", m), _now()))


# ---- one document -----------------------------------------------------------------------------------------------------
def asn_next(c, ws):
    """The next free archive serial number of a workspace (the highest + 1)."""
    return int(c.execute("SELECT COALESCE(MAX(asn), 0) FROM doc_meta WHERE ws=?", (ws,)).fetchone()[0] or 0) + 1


def asn_taken(c, ws, n, nid=None):
    return c.execute("SELECT 1 FROM doc_meta WHERE ws=? AND asn=? AND node_id<>?", (ws, int(n), int(nid or 0))).fetchone() is not None


def index_text(c, m, name, text):
    """What the word index of a document holds: name, sender, archive number and the recognised text."""
    sender = label_name(c, m["ws"], "sender", m["sender_id"]) or ""
    asn = f"{cfg_get(c, m['ws'])['asn_prefix']}{m['asn']} {m['asn']}" if m.get("asn") else ""
    return f"{name}\n{sender}\n{asn}\n{text}"


def meta_row(c, nid):
    return c.execute("SELECT * FROM doc_meta WHERE node_id=?", (nid,)).fetchone()


def meta_text(c, m):
    return doc_open(c, m["ws"], "doc_meta.text", m["text"]) or ""


def meta_json(c, m, col, default):
    if col == "auto":
        try:
            v = json.loads(m["auto"] or "{}")
        except ValueError:
            v = {}
        return v if isinstance(v, dict) else default
    return _jopen(c, m["ws"], f"doc_meta.{col}", m[col], default)


def meta_set_json(c, nid, ws, col, value):
    v = json.dumps(value) if col == "auto" else (_jseal(c, ws, f"doc_meta.{col}", value) if value else "")
    c.execute(f"UPDATE doc_meta SET {col}=?, updated_at=? WHERE node_id=?", (v, _now(), nid))


def root_id(c, ws):
    """The documents folder of workspace ws: the one marked in doc_cfg (root_id; renaming keeps it), else (made before the
    mark) the oldest folder "Dokumente" at the top of the workspace, or None."""
    org = ws_org(ws)
    r = c.execute("SELECT data FROM doc_cfg WHERE ws=?", (ws,)).fetchone()
    try:
        rid = int(json.loads(r[0]).get("root_id") or 0) if r else 0
    except (ValueError, TypeError, AttributeError):
        rid = 0
    if rid:
        n = c.execute("SELECT parent_id, kind, org_id, owner_id, deleted_at FROM fs_nodes WHERE id=?", (rid,)).fetchone()
        if (n and n["parent_id"] is None and n["kind"] == "folder" and not n["deleted_at"]
                and doc_ws(n["org_id"], n["owner_id"]) == ws):
            return rid
        return None if n and not n["deleted_at"] else _root_by_name(c, ws, org)
    return _root_by_name(c, ws, org)


def _root_by_name(c, ws, org):
    if org:
        r = c.execute("SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id=? AND kind='folder' AND lower(name)=lower(?) "
                      "AND deleted_at IS NULL AND agent_id IS NULL ORDER BY id LIMIT 1", (org, ROOT)).fetchone()
    else:
        r = c.execute("SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id IS NULL AND owner_id=? AND kind='folder' "
                      "AND lower(name)=lower(?) AND deleted_at IS NULL AND agent_id IS NULL ORDER BY id LIMIT 1",
                      (int(ws[1:]), ROOT)).fetchone()
    return r[0] if r else None


def root_mark(c, ws, nid):
    """Mark nid as the documents folder of ws (doc_cfg.data root_id, the settings stay)."""
    r = c.execute("SELECT data FROM doc_cfg WHERE ws=?", (ws,)).fetchone()
    try:
        d = json.loads(r[0]) if r else {}
    except ValueError:
        d = {}
    d = d if isinstance(d, dict) else {}
    d["root_id"] = int(nid)
    c.execute("""INSERT INTO doc_cfg(ws, org_id, data, updated_at) VALUES(?,?,?,?)
                 ON CONFLICT(ws) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
              (ws, ws_org(ws), json.dumps(d), _now()))


def root_folder(c, uid, org_id):
    """Find or make (and mark) the documents folder of workspace org_id (None: uid's own space) for an upload by uid.
    An organisation's folder belongs to one of its admins, whoever adds the first document: members file their documents
    into it as their own (fs_add_hooks, root_add_ok) and see only those and what is shared with them; admins see all."""
    from ..files.store import fs_folder, _free_name
    from ..core.access import Denied, acx_of
    ws = doc_ws(org_id, uid)
    rid = root_id(c, ws)
    if rid:
        if not doc_root_marked(c, ws, rid):
            root_mark(c, ws, rid)
        return rid
    ctx = acx_of(c, uid)
    if not org_id or ctx.role == "agent":
        rid = fs_folder(c, uid, org_id, [ROOT])
    else:
        if int(org_id) not in ctx.org_ids:
            raise Denied(404)
        from ..core.pg import system_ctx
        with system_ctx(c):  # the organisation's admins (members list; uid is a member, checked above)
            a = c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=?
                             AND COALESCE(u.kind, '')!='agent' ORDER BY (m.role='admin') DESC, (m.user_id=?) DESC, m.user_id
                             LIMIT 1""", (int(org_id), uid)).fetchone()
        owner = a[0] if a else uid
        ts = _now()
        rid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at)
                              VALUES(NULL,'folder',?,?,?,?,?,?)""",
                        (_free_name(c, None, owner, int(org_id), ROOT), owner, int(org_id), uid, ts, ts))
    root_mark(c, doc_ws(org_id, uid), rid)
    return rid


def doc_root_marked(c, ws, rid):
    r = c.execute("SELECT data FROM doc_cfg WHERE ws=?", (ws,)).fetchone()
    try:
        return bool(r) and int(json.loads(r[0]).get("root_id") or 0) == int(rid)
    except (ValueError, TypeError, AttributeError):
        return False


def root_add_ok(c, uid, chain):
    """fs_add_hooks: a person who is a member of the organisation may add their own file directly into its documents folder."""
    from ..core.access import acx_of
    top = chain[0]
    if len(chain) != 1 or top["kind"] != "folder" or not top["org_id"]:
        return False
    ctx = acx_of(c, uid)
    return ctx.role != "agent" and top["org_id"] in ctx.org_ids and root_id(c, doc_ws(top["org_id"], None)) == top["id"]


def docs_root(c, node):
    """The id of the documents folder (the marked folder at the root of the workspace, root_id) a node sits in, or None."""
    from ..files.store import fs_chain
    chain = fs_chain(c, node["id"])
    top = chain[-1] if chain else None
    if top and top["kind"] == "folder" and top["parent_id"] is None and top["id"] != node["id"] \
            and root_id(c, doc_ws(top["org_id"], top["owner_id"])) == top["id"]:
        return top["id"]
    return None


def folder_label(c, node):
    """The folder feature of a document: the id of its folder directly below the documents folder ("" = in the documents
    folder itself / the inbox / outside)."""
    root = docs_root(c, node)
    if not root or not node["parent_id"] or node["parent_id"] == root:
        return ""
    p = c.execute("SELECT id, parent_id, name, kind FROM fs_nodes WHERE id=?", (node["parent_id"],)).fetchone()
    if not p or p["parent_id"] != root or p["name"].lower() == INBOX.lower():
        return ""
    return str(p["id"])


def folder_ok(c, node, fid):
    """Is fid a folder (not in the trash) directly below the documents folder of node's own workspace?"""
    root = docs_root(c, node)
    if not root or not str(fid or "").isdigit():
        return False
    r = c.execute("SELECT parent_id, kind, org_id, deleted_at FROM fs_nodes WHERE id=?", (int(fid),)).fetchone()
    return bool(r) and r["parent_id"] == root and r["kind"] == "folder" and not r["deleted_at"] and r["org_id"] == node["org_id"]


def move_to_folder(c, node, fid):
    """Move a document into folder fid of the same workspace (never across: checked by folder_ok)."""
    if not folder_ok(c, node, fid):
        return False
    if node["org_id"]:  # 2.48.0 review: a member's document stays theirs in the organisation's documents folder
        c.execute("UPDATE fs_nodes SET parent_id=?, updated_at=? WHERE id=?", (int(fid), _now(), node["id"]))
        return True
    p = c.execute("SELECT owner_id FROM fs_nodes WHERE id=?", (int(fid),)).fetchone()
    c.execute("UPDATE fs_nodes SET parent_id=?, owner_id=?, updated_at=? WHERE id=?", (int(fid), p["owner_id"], _now(), node["id"]))
    return True


def folder_by_name(c, node, uid, name, create=True):
    """The folder `name` directly below the documents folder of node's workspace (made when missing and create), or None.
    A new folder belongs to the owner of the documents folder (2.48.0 review: never a second "Dokumente" elsewhere)."""
    from ..files.store import safe_fs_name, _free_name
    root = docs_root(c, node)
    nm = safe_fs_name(str(name or "")[:NAME_MAX]).strip()
    if not root or not nm or nm.lower() == INBOX.lower():
        return None
    r = c.execute("SELECT id FROM fs_nodes WHERE parent_id=? AND kind='folder' AND lower(name)=lower(?) AND deleted_at IS NULL "
                  "ORDER BY id LIMIT 1", (root, nm)).fetchone()
    if r or not create:
        return r[0] if r else None
    p = c.execute("SELECT owner_id, org_id FROM fs_nodes WHERE id=?", (root,)).fetchone()
    ts = _now()
    return insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at)
                           VALUES(?,'folder',?,?,?,?,?,?)""",
                     (root, _free_name(c, root, p["owner_id"], p["org_id"], nm), p["owner_id"], p["org_id"], uid, ts, ts))


def current(c, m, node):
    """The current values of the features: {sender: id|None, type: id|None, folder: id text|"", tags: [ids]}."""
    return {"sender": m["sender_id"], "type": m["type_id"], "folder": folder_label(c, node),
            "tags": [t["id"] for t in node_tags(c, m["node_id"])]}


def _tokens(c, m, node, text=None):
    return CL.tokens(f"{node['name']}\n{text if text is not None else meta_text(c, m)}")


def train(c, nid, features=("sender", "type", "folder", "tags")):
    """Teach the workspace's models the current values of a document (a correction or a confirmation): the value it was
    trained with before is taken out first, so a document counts once per model."""
    m = meta_row(c, nid)
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not m or not node:
        return
    ws = m["ws"]
    lv = cfg_get(c, ws)["levels"]
    toks = _tokens(c, m, node)
    if not toks:
        return
    trained = meta_json(c, m, "trained", {})
    cur = current(c, m, node)
    all_tags = [str(x["id"]) for x in labels(c, ws, "tag")]
    for f in features:
        if lv.get(f) == "off":
            continue
        model = model_get(c, ws, f)
        if f == "tags":
            if "tags" in trained:
                CL.learn_tags(model, toks, trained["tags"], all_tags, -1)
            new = [str(t) for t in cur["tags"]]
            CL.learn_tags(model, toks, new, all_tags)
            trained["tags"] = new
        else:
            if f in trained:
                CL.unlearn(model, toks, trained[f])
            new = str(cur[f] or "")
            CL.learn(model, toks, new)
            trained[f] = new
        model_put(c, ws, f, model)
    meta_set_json(c, nid, ws, "trained", trained)


def untrain(c, nid):
    """Take a document out of the models (it is deleted for good)."""
    m = meta_row(c, nid)
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not m or not node:
        return
    trained = meta_json(c, m, "trained", {})
    if not trained:
        return
    toks = _tokens(c, m, node)
    all_tags = [str(x["id"]) for x in labels(c, m["ws"], "tag")]
    for f, label in trained.items():
        model = model_get(c, m["ws"], f)
        if f == "tags":
            CL.learn_tags(model, toks, label, all_tags, -1)
        else:
            CL.unlearn(model, toks, label)
        model_put(c, m["ws"], f, model)


def classify(c, m, node, text, given=None):
    """(set, suggest, auto): what the levels of the workspace decide for one document.
    set = {feature: value} applied now, suggest = {feature: {value, conf, by}} offered for review, auto = {feature: how}.
    Values: sender / type = label ids, folder = folder id text, tags = [tag ids]. given = features fixed by the caller."""
    ws = m["ws"]
    lv = cfg_get(c, ws)["levels"]
    given = given or {}
    out, sug, auto = {}, {}, {}
    rr = RU.apply_rules(rules_get(c, ws), f"{node['name']}\n{text}") if any(lv[f] in ("rules", "learn") for f in lv) else {"tags": []}
    toks = CL.tokens(f"{node['name']}\n{text}")
    uid = m["created_by"] or node["owner_id"]
    for f in ("sender", "type", "folder"):
        if f in given or lv[f] in ("agent", "off"):
            continue
        if rr.get(f):
            if f == "folder":
                fid = folder_by_name(c, node, uid, rr[f])
                if fid:
                    out[f], auto[f] = str(fid), "rule"
            else:
                out[f], auto[f] = label_id(c, ws, f, rr[f]), "rule"
            continue
        if lv[f] != "learn":
            continue
        label, conf = CL.predict(model_get(c, ws, f), toks)
        if not label:
            continue
        if f == "folder":
            if not folder_ok(c, node, label):
                continue
        elif not label_ok(c, ws, f, label):
            continue
        val = label if f == "folder" else int(label)
        if conf >= CL.SURE:
            out[f], auto[f] = val, "learn"
        elif conf >= CL.MAYBE:
            sug[f] = {"value": val, "conf": round(conf, 2), "by": "learn"}
    if "tags" not in given and lv["tags"] not in ("agent", "off"):
        tags, tag_auto = [], {}
        for name in rr.get("tags") or []:
            tid = label_id(c, ws, "tag", name)
            if tid and tid not in tags:
                tags.append(tid)
                tag_auto[tid] = "rule"
        if lv["tags"] == "learn":
            maybe = []
            for tid, conf in CL.predict_tags(model_get(c, ws, "tags"), toks):
                if not str(tid).isdigit() or not label_ok(c, ws, "tag", tid) or int(tid) in tags:
                    continue
                if conf >= CL.SURE:
                    tags.append(int(tid))
                    tag_auto[int(tid)] = "learn"
                else:
                    maybe.append(int(tid))
            if maybe:
                sug["tags"] = {"value": maybe, "by": "learn"}
        if tags:
            out["tags"], auto["tags"] = tags, tag_auto
    return out, sug, auto


def apply_values(c, m, node, values, auto, how=None):
    """Write feature values to a document (sender / type ids, folder id text, tag ids). auto: {feature: how} recorded."""
    nid = m["node_id"]
    if "sender" in values:
        c.execute("UPDATE doc_meta SET sender_id=? WHERE node_id=?", (values["sender"] or None, nid))
    if "type" in values:
        c.execute("UPDATE doc_meta SET type_id=? WHERE node_id=?", (values["type"] or None, nid))
    if values.get("folder"):
        move_to_folder(c, node, values["folder"])
    if "tags" in values:
        ta = auto.get("tags") if isinstance(auto.get("tags"), dict) else {}
        set_tags(c, nid, values["tags"], {t: ta.get(t, how or "") for t in values["tags"]})


def thumb_store(c, m, node, data, kind):
    """Make the preview image of a document (sealed like its file) and note its path in doc_meta.thumb."""
    import os
    import uuid
    from ..core.config import ATT_DIR
    from ..core.orgcrypt import oc_write_file
    from .ocr import thumb_bytes
    if kind not in ("pdf", "image"):
        return
    jpg = thumb_bytes(data, kind)
    if not jpg:
        return
    rel = os.path.join(THUMB_DIR, f"{int(node['id'])}-{uuid.uuid4().hex[:10]}.jpg")
    try:
        os.makedirs(os.path.join(ATT_DIR, THUMB_DIR), exist_ok=True)
        if node["org_id"]:
            oc_write_file(c, node["org_id"], os.path.join(ATT_DIR, rel), jpg)
        else:  # 2.48.0 review (L3): a private document's preview is sealed like its text (the derived key of the space)
            from ..core.orgcrypt import _write_atomic
            _write_atomic(os.path.join(ATT_DIR, rel), thumb_seal(c, m["ws"], jpg))
    except OSError:
        return
    thumb_drop(m["thumb"])
    c.execute("UPDATE doc_meta SET thumb=? WHERE node_id=?", (rel, node["id"]))


def _thumb_ctx(ws):
    return b"kalmido-docs-thumb-v1|" + ws.encode()


def thumb_seal(c, ws, data):
    """The preview of a private document sealed with the space's derived key (unchanged: encryption off, no server key)."""
    from ..core.orgcrypt import oc_seal_k
    if ws_org(ws) or not oc_active(c):
        return data
    key = _ws_key(c, ws)
    return oc_seal_k(key, 0, data, _thumb_ctx(ws)) if key else data


def thumb_read(c, ws, path):
    """The plain preview image: a private one with the space's key (header org 0), else like any stored file."""
    from ..core.orgcrypt import oc_file_org, oc_open_k, oc_read_file
    with open(path, "rb") as f:
        data = f.read()
    if oc_file_org(data) == 0 and not ws_org(ws):
        key = _ws_key(c, ws, create=False)
        if key is None:
            raise OSError("no key")
        try:
            return oc_open_k(key, data, _thumb_ctx(ws))
        except OrgCryptError:
            raise OSError("cannot open") from None
    return oc_read_file(c, path)


def thumb_drop(rel):
    import os
    from ..core.config import ATT_DIR
    if rel and rel.startswith(THUMB_DIR + os.sep) and ".." not in rel:
        try:
            os.remove(os.path.join(ATT_DIR, rel))
        except OSError:
            pass


def process(c, nid):
    """The recognition run of one document: text (text layer / OCR), preview, date / due date / amount, sorting, index.
    Returns the new state. Runs in the background queue (docs/ingest.py) -- never inside a request."""
    from ..files.store import fs_read
    from ..core.access import Denied
    from .ocr import doc_text
    m = meta_row(c, nid)
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not m or not node:
        return None
    ws = m["ws"]
    given = meta_json(c, m, "suggest", {}).get("_given") or {}
    try:
        data = fs_read(c, nid)
    except (Denied, OSError, OrgCryptError):
        c.execute("UPDATE doc_meta SET state='failed', error='missing', updated_at=? WHERE node_id=?", (_now(), nid))
        return "failed"
    if given.get("text"):
        res = {"text": str(given["text"])[:200_000], "method": "import"}
    else:
        res = doc_text(node["name"], node["mime"], data)
    if res.get("error") == "busy":
        return "wait"
    thumb_store(c, m, node, data, res.get("kind"))
    text = res.get("text") or ""
    if not m["asn"]:
        from .ocr import qr_codes
        n = EX.find_asn(cfg_get(c, ws)["asn_prefix"], [*qr_codes(data, res.get("kind")), text[:20000]])
        if n and not asn_taken(c, ws, n, nid):
            c.execute("UPDATE doc_meta SET asn=? WHERE node_id=?", (n, nid))
            given = {**given, "_asn": True}
    ex = EX.extract(text)
    vals = {"doc_date": given.get("date") or ex["date"], "due_date": given.get("due") or ex["due"],
            "amount": str(given.get("amount") or ex["amount"] or ""), "currency": str(given.get("currency") or ex["currency"] or "")[:8]}
    if m["doc_date"]:
        vals["doc_date"] = m["doc_date"]     # set by hand while it waited
    auto_all = meta_json(c, m, "auto", {})
    if not vals["doc_date"] and m["taken_at"]:  # 2.61.0 B (#1819): no date in the text -> the day the photo was taken
        vals["doc_date"] = str(m["taken_at"])[:10]
        auto_all["date"] = "photo"
    if given.get("_asn"):
        auto_all["asn"] = "code"
    imported = {}                            # features the caller gave (an import): set as they are
    for f in ("sender", "type"):
        if given.get(f):
            imported[f] = label_id(c, ws, f, given[f])
    if given.get("tags"):
        imported["tags"] = [t for t in (label_id(c, ws, "tag", x) for x in given["tags"]) if t]
    if imported:
        apply_values(c, m, node, imported, {}, "import")
        auto_all.update({f: "import" for f in imported})
    cur = current(c, m, node)
    fixed = {f for f in ("sender", "type", "tags") if cur[f]} | set(imported)  # a value set by hand / imported stays
    if cur["folder"]:
        fixed.add("folder")
    newv, sug, auto = classify(c, m, node, text, given=fixed)
    apply_values(c, m, node, newv, auto)
    auto_all.update({f: (next(iter(a.values()), "rule") if isinstance(a, dict) else a) for f, a in auto.items()})
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    m2 = meta_row(c, nid)
    review = 1 if sug or not (m2["sender_id"] or m2["type_id"]) else 0
    state = "failed" if res.get("error") else "done"
    c.execute("""UPDATE doc_meta SET state=?, error=?, method=?, pages=?, text=?, doc_date=?, due_date=?, amount=?, currency=?,
                 auto=?, suggest=?, review=?, version=?, done_at=?, updated_at=? WHERE node_id=?""",
              (state, res.get("error") or "", res.get("method") or "", int(res.get("pages") or 0), doc_seal(c, ws, "doc_meta.text", text),
               vals["doc_date"], vals["due_date"], doc_seal(c, ws, "doc_meta.amount", vals["amount"]), vals["currency"],
               json.dumps(auto_all, separators=(",", ":")), _jseal(c, ws, "doc_meta.suggest", sug) if sug else "", review, node["cur_version"],
               _now(), _now(), nid))
    doc_index(c, nid, ws, index_text(c, dict(meta_row(c, nid)), node["name"], text))
    return state
