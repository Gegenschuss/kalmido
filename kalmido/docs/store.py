"""2.48.0 (#1111): documents -- the data side (no routes): workspaces, sealing, labels, the word index, the recognition run
and the training of the learning classifier.

A document is a file of the file store (kalmido/files/store.py, fs_nodes) plus its doc_meta row. Its workspace (ws) is the
one of its node: 'o<org id>' for an organisation's tree, 'u<owner id>' for a person's own tree. Senders, types, tags, rules,
models and the word index belong to exactly one workspace; nothing here moves a document into another workspace -- 2.96.0 A
(#1941): files/fsmove.py does (its labels are found / made by name in the target, its values sealed again).

Encryption at rest: documents are the most sensitive data. The recognised text, the amount, sender names, rules, models and
suggestions are sealed (AES-256-GCM, "kenc1:") with the workspace key: the organisation's key (core/orgcrypt.py) or, for a
person's own documents, a key derived from the server key per person (the text of a private document is sealed like
the text cache of attachments; 2.64.0 (#1864): its file itself with the owner's account key, core/orgcrypt.py). Without
a server key / with org_encrypt=0 the values stay plain, as everywhere. The full-text search uses no plain index: the shared word index obj_search_words (core/objwords.py, kind 'doc'; 2.1002.0
#5279, was doc_words) holds HMAC-SHA256 prefix hashes of the folded words (keyed per workspace, _index_key); a query word is
looked up by its prefix hash (or by its longest stored prefix and then checked against the opened text, doc_opened)."""
import hashlib
import hmac
import json
import re
from datetime import timedelta

from ..core.config import SECRET_KEY, ATT_DIR
from ..core.db import insert_id, iso, now_utc
from ..core.i18n import LANGS, N_, lang, tr
from ..core.orgcrypt import OrgCryptError, PREFIX, oc_active, oc_dec_k, oc_enc_k, oc_key, oc_private_on  # 2.662.0 (#4939): + oc_private_on
from . import classify as CL
from . import extract as EX
from . import rules as RU
from ..core.pg import system_ctx, write_lock  # 2.149.0 G (#2517): pulled up from functions
from ..core.access import acx_of, Denied, live_sql  # 2.149.0 G (#2517): pulled up from functions; 2.981.0 (#5273): live_sql
from ..core.orgcrypt import oc_file_org, oc_open_k, oc_read_file, oc_seal_k, oc_write_file  # 2.149.0 G (#2517): pulled up from functions
from ..files.scan import sc_locked as _sc_locked  # 2.360.0 B (#2496)
from ..core.objwords import OSW_KEY, osw_put, osw_register  # 2.1002.0 (#5279): the shared word index
from ..files.store import fs_chain as _fs_chain, fs_deleted as _fs_deleted, fs_role as _fs_role  # 2.199.0 B (#2742); 2.351.0 A (#2823): fs_role
from ..files.fslock import fl_is_locked, fsl_of_chain  # 2.353.0 F (#2758)
from ..files.store import fs_visible_sql_c as _fs_visible_sql  # 2.360.0 B (#2496)
from ..files.store import fs_folder, _free_name, fs_chain, safe_fs_name, fs_role, DEPTH_MAX, fs_read  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgroles import org_role_key  # 2.369.5 (#2517): pulled up from functions
from ..core.errors import BadInput  # 2.369.5 (#2517): pulled up from functions
from .ocr import thumb_bytes, doc_text, qr_codes, OCR_PAGES, QR_DOC_S, THUMB_WL  # 2.369.5 (#2517): pulled up from functions; 2.583.0 (#4812): THUMB_WL
from .ocr import OCR_LANG_MAX, ocr_choices  # 2.635.0 (#4807 b)
from .scanmark import scan_of  # 2.836.0 (#5390): the scan mark
from .pagesize import PgBusy, pg_of  # 2.905.0 (#5393): the first page's size; 2.990.0 (#5571): PgBusy
from ..office.einvoice_in import ei_of_file, ei_text, ei_amount, ei_details, ei_compact, ei_receipt  # 2.369.5 (#2517): pulled up from functions
from ..tasks.attachtext import file_kind  # 2.369.5 (#2517): pulled up from functions

STATES = ("wait", "run", "done", "failed")
LABEL_KINDS = {"sender": "doc_senders", "type": "doc_types", "tag": "doc_tags"}
ROOT = "Dokumente"          # the documents folder at the root of a workspace's file tree (its name before 2.368)
INBOX = "Eingang"           # its inbox folder: files put there are recognised and sorted (its name before 2.368)
# 2.368.0 (#2987): a new documents folder is named in its owner's language; every language's name (and the German one of
# before) is still recognised, so existing folders keep working and no second one is made
ROOT_KEY = N_("Documents|folder")
INBOX_KEY = N_("Inbox|folder")


def folder_names(key, old):
    """Every name of a built-in folder, lower case: the German name of before 2.368 + the name in each app language."""
    return sorted({old.lower(), tr(key, lg="en").lower(), *(tr(key, lg=lg).lower() for lg in LANGS)})


def is_inbox(name):
    return str(name or "").lower() in folder_names(INBOX_KEY, INBOX)


def folder_in_sql(col, names):
    """SQL "lower(col) IN (?, ...)" for folder_names() (the arguments are the names)."""
    return f"lower({col}) IN ({', '.join('?' * len(names))})"
NAME_MAX = 120
TITLE_MAX = 200  # 2.750.0 (#4876): a document's own title (doc_meta.title)
# 2.750.0 (#4876): the endings a title leaves off when it comes from the file name ("Brief.pdf" -> "Brief")
_TITLE_EXT = re.compile(r"\.(pdf|jpe?g|png|heic|heif|tiff?|webp|gif|bmp|txt|md|csv|xml|json|eml|msg|html?|rtf|odt|ods|odp|docx?|xlsx?|pptx?|zip)$", re.I)


def doc_title(name, title=None):
    """2.750.0 (#4876): what a document is called: its own title, else its file name without the ending of a known type."""
    t = (title or "").strip()
    if t:
        return t
    name = name or ""
    base = _TITLE_EXT.sub("", name).strip()
    return base or name


# 2.783.0 (#4882): the title pattern of an area (doc_cfg title_pattern / title_auto). Placeholders in German or English, any
# case; an unknown {x} stays as text. The date as DD.MM.YYYY. An empty part goes with the separator in front of it.
TITLE_PATTERN = "{Absender} {Typ} {Datum}"
TITLE_PATTERN_MAX = 120
_TP_KEYS = {"absender": "sender", "sender": "sender", "typ": "type", "type": "type", "datum": "date", "date": "date"}
_TP_RE = re.compile(r"\{([^{}]{1,20})\}")


def title_fill(pattern, sender="", typ="", date=""):
    """The title the pattern gives for these values ("" when every placeholder is empty and no text is left)."""
    d = str(date or "")[:10]
    vals = {"sender": str(sender or "").strip(), "type": str(typ or "").strip(),
            "date": f"{d[8:10]}.{d[5:7]}.{d[:4]}" if re.fullmatch(r"\d{4}-\d{2}-\d{2}", d) else ""}
    lits, keys, at = [""], [], 0
    for mt in _TP_RE.finditer(str(pattern or "")):
        k = _TP_KEYS.get(mt.group(1).strip().lower())
        lits[-1] += pattern[at:mt.start()] + ("" if k else mt.group(0))
        at = mt.end()
        if k:
            keys.append(k)
            lits.append("")
    lits[-1] += str(pattern or "")[at:]
    out, first = lits[0], True
    for i, k in enumerate(keys):
        if not vals[k]:
            continue
        out += ("" if first else lits[i]) + vals[k]
        first = False
    out += lits[-1]
    return re.sub(r"\s+", " ", out).strip(" -–—,;:/|")[:TITLE_MAX].strip()


def title_is_manual(m):
    """Set by hand (never replaced by the pattern): title_manual 1, or a row from before #4882 (NULL) that has a title."""
    keys = m.keys() if hasattr(m, "keys") else ()
    v = m["title_manual"] if "title_manual" in keys else None
    return bool(v) if v is not None else bool(((m["title"] if "title" in keys else "") or "").strip())


def title_of(c, m, pattern=None):
    """The pattern's title for document row m (its area's pattern unless given)."""
    ws = m["ws"]
    return title_fill(pattern or cfg_get(c, ws)["title_pattern"], label_name(c, ws, "sender", m["sender_id"]) or "",
                      label_name(c, ws, "type", m["type_id"]) or "", m["doc_date"] or "")


def title_auto(c, nid):
    """After a recognition / a rule / "Apply what was learned": the title from the area's pattern, when "Title automatically"
    is on and the title was never set by hand. Only once a sender or a type is known (a date alone says less than the file
    name; "Suggest title" gives it all the same). An empty result leaves the title as it is. -> True when it changed."""
    m = meta_row(c, nid)
    if not m or title_is_manual(m) or not (m["sender_id"] or m["type_id"]):
        return False
    cfg = cfg_get(c, m["ws"])
    if not cfg["title_auto"]:
        return False
    t = title_of(c, m, cfg["title_pattern"])
    if not t or t == (m["title"] or ""):
        return False
    c.execute("UPDATE doc_meta SET title=?, title_manual=0 WHERE node_id=?", (t, nid))
    return True
ASN_PREFIX_RE = r"[A-Za-z][A-Za-z0-9-]{0,9}"  # the prefix of archive serial numbers (letters first, at most 10)
THUMB_DIR = "docthumbs"   # below ATT_DIR: the preview images (sealed like the file)
ERRORS = {
    "no_ocr": N_("Text recognition is not available on this server."),
    "encrypted": N_("The PDF is password-protected and cannot be read."),
    "unreadable": N_("The file is damaged or cannot be read."),
    "too_complex": N_("The file took too long or too much memory to read."),
    "missing": N_("The file is missing on the server."),
    "failed": N_("The recognition failed."),
    "no_heif": N_("This server cannot read HEIC photos at the moment. Please send the photo as JPEG."),  # 2.146.0 B (#2454); #4168: no HEIC reader in the image for now
}


from ..core.db import now_iso as _now  # noqa: E402  2.149.0 G (#2517): was an own copy


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


# 2.126.0 A (#1970): the values of a person's own documents are sealed with the person's account key (core/orgcrypt.py
# user_keys, space -<id>), so a new server key keeps them (rewrap-accounts) like the organisations' values. Values of the
# older form (the key derived from the server key above, space 0) stay readable; the start-up pass moves them
# (admin/orgcrypt_cli.py docs_settle), "docs-to-server-key" moves them back before running an older version.
def ws_user(ws):
    return int(ws[1:]) if ws and ws[0] == "u" and ws[1:].isdigit() else None


def docs_ukey_on(c):
    """The instance setting docs_account_key (default on; docs-to-server-key sets "0")."""
    with system_ctx(c):  # orgcrypt: an instance setting, no content
        r = c.execute("SELECT value FROM settings WHERE key='docs_account_key'").fetchone()
    return (r[0] if r else "1") != "0"


def _acct_key(c, ws, create):
    uid = ws_user(ws)
    if not uid or not SECRET_KEY:
        return None
    try:
        return oc_key(c, -uid, create=create)
    except OrgCryptError:  # an account key of another server key: the older form (never lost)
        return None


def doc_seal_as(c, ws, ctx, value, account):
    """value sealed for ws in the given form (account: a person's account key, else the workspace key); unchanged without
    a key. Used by doc_seal and the passes of admin/orgcrypt_cli.py."""
    if account and ws_user(ws):
        key = _acct_key(c, ws, True)
        if key:
            return oc_enc_k(key, -ws_user(ws), f"{ctx}|{ws}", value)
    key = _ws_key(c, ws)
    return oc_enc_k(key, ws_org(ws) or 0, f"{ctx}|{ws}", value) if key else value


def doc_open_as(c, ws, ctx, value):
    """(plain value, True when it was sealed with the account key); OrgCryptError when no key opens it."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value, False
    uid = ws_user(ws)
    if uid:
        key = _acct_key(c, ws, False)
        if key:
            try:
                return oc_dec_k(key, -uid, f"{ctx}|{ws}", value), True
            except OrgCryptError:
                pass
    return oc_dec_k(_ws_key(c, ws, create=False), ws_org(ws) or 0, f"{ctx}|{ws}", value), False


def doc_seal(c, ws, ctx, value):
    """value sealed with the workspace key (unchanged: empty, encryption off, no server key)."""
    if value is None or value == "" or not oc_active(c):
        return value
    return doc_seal_as(c, ws, ctx, value, bool(ws_user(ws)) and docs_ukey_on(c))  # 2.126.0 A (#1970)


def doc_opener(c, ws, ctx, default=""):
    """2.546.0 (#4186): doc_open for many values of one space ws and field ctx (the receipt lists): the same two forms and the
    same default, the keys looked up once instead of per value (oc_key reads its key row on every call)."""
    keys = {}

    def key(kind):
        if kind not in keys:
            try:
                keys[kind] = _acct_key(c, ws, False) if kind == "acct" else _ws_key(c, ws, create=False)
            except OrgCryptError as e:
                keys[kind] = e
        return keys[kind]

    def open_(value):
        if not isinstance(value, str) or not value.startswith(PREFIX):
            return value
        uid = ws_user(ws)
        if uid:
            k = key("acct")
            if k and not isinstance(k, OrgCryptError):
                try:
                    return oc_dec_k(k, -uid, f"{ctx}|{ws}", value)
                except OrgCryptError:
                    pass
        k = key("ws")
        if isinstance(k, OrgCryptError):
            return default
        try:
            return oc_dec_k(k, ws_org(ws) or 0, f"{ctx}|{ws}", value)
        except OrgCryptError:
            return default
    return open_


def doc_open(c, ws, ctx, value, default=""):
    """The plain value; default when a sealed value cannot be opened (another server key, a lost organisation key)."""
    if not isinstance(value, str) or not value.startswith(PREFIX):
        return value
    try:
        return doc_open_as(c, ws, ctx, value)[0]  # 2.126.0 A (#1970): both forms of a person's values
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
    base = _ws_key(c, ws) or hashlib.sha256(b"kalmido-docs-index-without-server-key").digest()
    k = _IKEYS.get((ws, base))  # 2.138.0 C (#1972): per key too - a renewed org key (orgcrypt_cli rotate) indexes with the new one at once
    if k is None:
        for x in [x for x in _IKEYS if x[0] == ws]:
            _IKEYS.pop(x, None)
        k = hmac.new(base, b"kalmido-docs-index-v1|" + ws.encode(), hashlib.sha256).digest()
        _IKEYS[(ws, base)] = k
    return k


def doc_index(c, nid, ws, text):
    """2.1002.0 (#5279): the words of document nid in the shared word index (core/objwords.py, kind 'doc'; was doc_words)."""
    # 2.360.0 B (#2496): a locked file stays out of the search (no words, only the mark: not indexed again)
    osw_put(c, "doc", nid, ws, None if _sc_locked(c, "fs", nid) else text)


def doc_opened(c, ws, ids):
    """2.1002.0 (#5279): {node id: everything the index holds of the document} (name, text, sender, archive number, custom
    field values, notes; 2.153.0 #2179, 2.184.0 B #2580, 2.635.0 #4807 d) for the word index's check of a longer word,
    in portions of 5000 (the database takes a limited number of parameters per statement)."""
    from .fields import df_index_texts
    out = {}
    ids = sorted(int(i) for i in ids)
    for i in range(0, len(ids), 5000):
        part = ids[i:i + 5000]
        qm = ",".join("?" * len(part))
        names = {x[0]: x[1] for x in c.execute(f"SELECT id, name FROM fs_nodes WHERE id IN ({qm})", tuple(part))}
        cfs = df_index_texts(c, ws, part)
        nts = notes_texts(c, ws, part)
        for r in c.execute(f"SELECT * FROM doc_meta WHERE node_id IN ({qm})", tuple(part)).fetchall():
            out[r["node_id"]] = index_text(c, dict(r), names.get(r["node_id"]) or "", doc_open(c, ws, "doc_meta.text", r["text"]),
                                           cf=cfs.get(r["node_id"], ""), notes=nts.get(r["node_id"], ""))
    return out


def doc_reindex(c, ids):
    """2.1002.0 (#5279): documents indexed again by this version's rules (core/objwords.py osw_tick)."""
    for nid in ids:
        m = meta_row(c, nid)
        node = c.execute("SELECT name FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        if m and node:
            doc_index(c, nid, m["ws"], index_text(c, dict(m), node["name"], meta_text(c, m)))
        else:
            osw_put(c, "doc", nid)  # nothing to index: the mark only (never asked again)


osw_register("doc", "doc_meta", "node_id", "TRUE", doc_reindex)
OSW_KEY.append(_index_key)  # 2.1002.0 (#5279): the shared word index hashes with the workspace's key  # 2.1002.0 (#5279): the watchdog's catch-up (core/objwords.py)


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
    ol = d.get("ocr_langs")  # 2.635.0 (#4807 b): the area's text recognition languages ([] = the default, deu+eng)
    return {"levels": RU.levels(d.get("levels")), "inbox": d.get("inbox", True) is not False,
            "asn_prefix": pre if re.fullmatch(ASN_PREFIX_RE, pre) else "ASN",
            "ocr_langs": [str(x) for x in ol][:OCR_LANG_MAX] if isinstance(ol, list) else [],
            # 2.783.0 (#4882): the title pattern and "Title automatically" (on unless switched off)
            "title_pattern": str(d.get("title_pattern") or "").strip()[:TITLE_PATTERN_MAX] or TITLE_PATTERN,
            "title_auto": d.get("title_auto", True) is not False,
            "pdf_opt_auto": d.get("pdf_opt_auto") is True}  # 2.892.0 (#4873): optimise new scans automatically (off by default)


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
    if "ocr_langs" in data:  # 2.635.0 (#4807 b): only installed languages within KALMIDO_OCR_LANGS, at most OCR_LANG_MAX
        ol = data["ocr_langs"] or []
        if not isinstance(ol, list) or len(ol) > OCR_LANG_MAX or not set(map(str, ol)) <= set(ocr_choices()):
            raise ValueError("ocr_langs")
        cur["ocr_langs"] = list(dict.fromkeys(str(x) for x in ol))
    if "title_pattern" in data:  # 2.783.0 (#4882): empty = the default; at least one placeholder
        tp = re.sub(r"\s+", " ", str(data["title_pattern"] or "")).strip() or TITLE_PATTERN
        if len(tp) > TITLE_PATTERN_MAX or not any(mt.group(1).strip().lower() in _TP_KEYS for mt in _TP_RE.finditer(tp)):
            raise ValueError("title_pattern")
        cur["title_pattern"] = tp
    if "title_auto" in data:
        cur["title_auto"] = bool(data["title_auto"])
    if "pdf_opt_auto" in data:  # 2.892.0 (#4873)
        cur["pdf_opt_auto"] = bool(data["pdf_opt_auto"])
    rid = root_id(c, ws)  # 2.48.0 review: the mark of the documents folder stays
    if rid:
        cur["root_id"] = rid
    c.execute("""INSERT INTO doc_cfg(ws, org_id, data, updated_at) VALUES(?,?,?,?)
                 ON CONFLICT(ws) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at""",
              (ws, ws_org(ws), json.dumps(cur), _now()))
    return cur


def rules_get(c, ws, secret=False):
    """The rules (flows, 2.581.0 #4803) of ws in their order. A flow's webhook secret only with secret=True (docs/flows.py)."""
    out = []
    for r in c.execute("SELECT id, pos, data FROM doc_rules WHERE ws=? ORDER BY pos, id", (ws,)):
        d = _jopen(c, ws, "doc_rules.data", r["data"], {})
        if d:
            if not secret:
                d.pop("hook_secret", None)
            out.append({"id": r["id"], **d})
    return out


def flow_facts(c, m, node):
    """2.581.0 (#4803): what the filters of a flow look at (docs/rules.py flow_pass): source, file name, tag / type / sender names."""
    return {"source": m["source"], "name": node["name"],
            "tags": {RU.fold(t["name"]) for t in node_tags(c, m["node_id"])},
            "type": RU.fold(label_name(c, m["ws"], "type", m["type_id"]) or ""),
            "sender": RU.fold(label_name(c, m["ws"], "sender", m["sender_id"]) or "")}


def rules_received(c, m, node):
    """2.581.0 (#4803): the flows with the trigger "received" whose filters (besides the words) hold for the document --
    every old rule (no trigger, no filters) as before."""
    facts = None
    out = []
    for r in rules_get(c, m["ws"]):
        if RU.trigger_of(r) != "received":
            continue
        facts = facts or flow_facts(c, m, node)
        if RU.flow_pass(r, facts):
            out.append(r)
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


def asn_holder(c, ws, n, nid=None):
    """2.591.0 B (#4863): the document of ws (other than nid) that has archive number n, also one in the trash -- or None."""
    r = c.execute("SELECT node_id FROM doc_meta WHERE ws=? AND asn=? AND node_id<>? ORDER BY node_id LIMIT 1", (ws, int(n), int(nid or 0))).fetchone()
    return r[0] if r else None


def asn_lock(c, ws, nid):
    """2.273.0 C (#3047): hand out / check an archive number of a workspace under a lock until the transaction ends (two saves
    with "next" got the same number: unique violation, the save's other fields were lost). The document's row first, then the
    workspace lock -- the same order in every caller (no deadlock with a recognition run of the same document)."""
    c.execute("SELECT 1 FROM doc_meta WHERE node_id=? FOR UPDATE", (nid,))
    write_lock(c, f"doc-asn:{ws}")


# 2.273.0 C (#3047): the values a person set by hand, listed in doc_meta.auto["_hand"]; a recognition run ("Recognise again",
# a new file version) keeps them. Older versions ignore the key.
HAND_FIELDS = {"date": "doc_date", "due": "due_date", "amount": "amount", "currency": "currency"}


def hand_fields(auto):
    h = auto.get("_hand") if isinstance(auto, dict) else None
    return [f for f in h if f in HAND_FIELDS] if isinstance(h, list) else []


def was_digest(nid, f, v):
    """2.273.0 (#3047): the recognised value behind a hand value is kept only as a keyed digest (auto is not sealed; the
    amount must never sit there in plain text) - enough to see that a value was set back."""
    return hmac.new(SECRET_KEY or b"kalmido-doc-was", f"{nid}|{f}|{v}".encode(), hashlib.sha256).hexdigest()[:32]


def index_text(c, m, name, text, cf=None, notes=None):
    """What the word index of a document holds: name, sender, archive number, the custom field values (2.153.0) and the
    recognised text. cf: the custom field values read already (2.184.0 B, #2580: fields.py df_index_texts). 2.635.0 (#4807 d):
    + its notes (notes: read already, notes_texts)."""
    from .fields import df_index_text
    sender = label_name(c, m["ws"], "sender", m["sender_id"]) or ""
    asn = f"{cfg_get(c, m['ws'])['asn_prefix']}{m['asn']} {m['asn']}" if m.get("asn") else ""
    nt = notes_texts(c, m["ws"], [m["node_id"]]).get(int(m["node_id"]), "") if notes is None else notes
    title = (m.get("title") or "").strip() if hasattr(m, "get") else ""  # 2.750.0 (#4876): the own title as well (the file name stays findable)
    return f"{name}{chr(10) + title if title else ''}\n{sender}\n{asn}\n{df_index_text(c, m['node_id'], m['ws']) if cf is None else cf}\n{text}\n{nt}"


def notes_texts(c, ws, nids):
    """2.635.0 (#4807 d): the opened texts of the notes of the documents nids of ws ({node id: text}; docs/notes.py writes them)."""
    out = {int(n): [] for n in nids}
    if not out:
        return {}
    op = doc_opener(c, ws, "doc_notes.text")
    # 2.981.0 (#5273): the notes are rows of obj_comments (kind doc_note; the live ones); every node has one workspace (doc_meta.ws)
    for r in c.execute(f"SELECT ref_id AS node_id, body AS text FROM obj_comments WHERE kind='doc_note' AND ref_id IN ({','.join('?' * len(out))}) "
                       f"AND {live_sql()} ORDER BY id", tuple(out)).fetchall():
        out[r["node_id"]].append(op(r["text"]) or "")
    return {n: "\n".join(x) for n, x in out.items()}


def meta_row(c, nid):
    return c.execute("SELECT * FROM doc_meta WHERE node_id=?", (nid,)).fetchone()


def meta_text(c, m):
    return doc_open(c, m["ws"], "doc_meta.text", m["text"]) or ""


def meta_text_shown(c, m):
    """2.360.0 B (#2496): the recognised text for people / agents / the search: none while the file is locked (malware
    found later). meta_text stays the stored value (re-sealing, the models)."""
    return "" if _sc_locked(c, "fs", m["node_id"]) else meta_text(c, m)


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
    nl = " AND id NOT IN (SELECT node_id FROM fs_locks WHERE e2e IS NOT NULL)"  # 2.353.0 F (#2758, review M2): a locked folder renamed so is none
    nm = folder_names(ROOT_KEY, ROOT)  # 2.368.0 (#2987): its name in any language
    if org:
        r = c.execute("SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id=? AND kind='folder' AND " + folder_in_sql("name", nm) +
                      " AND deleted_at IS NULL AND agent_id IS NULL" + nl + " ORDER BY id LIMIT 1", (org, *nm)).fetchone()
    else:
        r = c.execute("SELECT id FROM fs_nodes WHERE parent_id IS NULL AND org_id IS NULL AND owner_id=? AND kind='folder' "
                      "AND " + folder_in_sql("name", nm) + " AND deleted_at IS NULL AND agent_id IS NULL" + nl + " ORDER BY id LIMIT 1",
                      (int(ws[1:]), *nm)).fetchone()
    return r[0] if r else None


def inbox_path(c, root, uid):
    """2.368.0 (#2987): "<documents folder>/<inbox>" as the settings name it: the existing folders' names, else the names a new
    one gets in uid's language."""
    lg = lang(c, uid)
    r = c.execute("SELECT name FROM fs_nodes WHERE id=?", (root,)).fetchone() if root else None
    i = None
    if root:
        ni = folder_names(INBOX_KEY, INBOX)
        i = c.execute("SELECT name FROM fs_nodes WHERE parent_id=? AND kind='folder' AND " + folder_in_sql("name", ni) +
                      " AND deleted_at IS NULL ORDER BY id LIMIT 1", (root, *ni)).fetchone()
    return f"{r[0] if r else tr(ROOT_KEY, lg=lg)}/{i[0] if i else tr(INBOX_KEY, lg=lg)}"


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
    ws = doc_ws(org_id, uid)
    rid = root_id(c, ws)
    if rid:
        if not doc_root_marked(c, ws, rid):
            root_mark(c, ws, rid)
        return rid
    ctx = acx_of(c, uid)
    if not org_id or ctx.role == "agent":
        rid = fs_folder(c, uid, org_id, [tr(ROOT_KEY, lg=lang(c, uid))])  # 2.368.0 (#2987): in the owner's language
    else:
        if int(org_id) not in ctx.org_ids:
            raise Denied(404)
        with system_ctx(c):  # the organisation's admins (members list; uid is a member, checked above)
            a = c.execute("""SELECT m.user_id FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=?
                             AND COALESCE(u.kind, '')!='agent' ORDER BY (m.role='admin') DESC, (m.user_id=?) DESC, m.user_id
                             LIMIT 1""", (int(org_id), uid)).fetchone()
        owner = a[0] if a else uid
        ts = _now()
        rid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at)
                              VALUES(NULL,'folder',?,?,?,?,?,?)""",
                        (_free_name(c, None, owner, int(org_id), tr(ROOT_KEY, lg=lang(c, owner))), owner, int(org_id), uid, ts, ts))
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
    top = chain[0]
    if len(chain) != 1 or top["kind"] != "folder" or not top["org_id"]:
        return False
    ctx = acx_of(c, uid)
    if ctx.role == "agent" or top["org_id"] not in ctx.org_ids:
        return False
    if org_role_key(c, uid, top["org_id"]) in ("guest", "readonly"):  # 2.143.0 A (#2151, review): accounting uploads receipts
        return False
    return root_id(c, doc_ws(top["org_id"], None)) == top["id"]


def docs_root(c, node):
    """The id of the documents folder (the marked folder at the root of the workspace, root_id) a node sits in, or None."""
    chain = fs_chain(c, node["id"])
    top = chain[-1] if chain else None
    if top and top["kind"] == "folder" and top["parent_id"] is None and top["id"] != node["id"] \
            and root_id(c, doc_ws(top["org_id"], top["owner_id"])) == top["id"]:
        return top["id"]
    return None


def folder_label(c, node):
    """The folder feature of a document: the id of the folder it lies in below the documents folder, at any depth (2.199.0 B
    (#2742); "" = in the documents folder itself / the inbox / outside)."""
    if not node["parent_id"]:
        return ""  # 2.525.0 (#4195): at the root nothing to look up (was the chain of every such row)
    root = docs_root(c, node)
    if not root or node["parent_id"] == root:
        return ""
    return str(node["parent_id"]) if _in_docs_tree(c, root, node["parent_id"]) else ""


def _in_docs_tree(c, root, fid):
    """2.199.0 B (#2742): is fid a folder (not in the trash) below the documents folder root, outside the inbox?"""
    chain = _fs_chain(c, int(fid))
    if not chain or chain[0]["kind"] != "folder" or _fs_deleted(chain):
        return False
    ids = [x["id"] for x in chain]
    if root not in ids or ids[0] == root:
        return False
    below = chain[:ids.index(root)]  # the folders between root and fid (fid first)
    if is_inbox(below[-1]["name"]):
        return False
    return fsl_of_chain(c, chain) is None  # 2.353.0 F (#2758, review M2): no document (plain, recognised) into a locked folder


def folder_ok(c, node, fid):
    """Is fid a folder (not in the trash) below the documents folder of node's own workspace (any depth since 2.199.0 B
    (#2742), never in the inbox)?"""
    root = docs_root(c, node)
    if not root or not str(fid or "").isdigit():
        return False
    r = c.execute("SELECT org_id FROM fs_nodes WHERE id=?", (int(fid),)).fetchone()
    return bool(r) and r["org_id"] == node["org_id"] and _in_docs_tree(c, root, int(fid))


def folder_tree(c, root, vis=None):
    """2.199.0 B (#2742): the folders below the documents folder root (not the inbox, not in the trash), depth first in the
    order of the file store (sort_no, then name): [{id, name, parent_id, depth, path}] -- path = "Kunde A / 2026".
    vis: the ids the asker may see (None = all); a hidden folder hides its subtree."""
    out, kids = [], {}
    rows = c.execute("""WITH RECURSIVE t(id) AS (SELECT id FROM fs_nodes WHERE parent_id=? AND kind='folder' AND deleted_at IS NULL
                        UNION ALL SELECT n.id FROM fs_nodes n JOIN t ON n.parent_id=t.id WHERE n.kind='folder' AND n.deleted_at IS NULL)
                        SELECT n.id, n.name, n.parent_id, n.sort_no FROM fs_nodes n WHERE n.id IN (SELECT id FROM t) LIMIT 5000""",
                     (root,)).fetchall()
    for r in rows:
        kids.setdefault(r["parent_id"], []).append(r)

    def walk(pid, path, depth):
        for r in sorted(kids.get(pid, []), key=lambda x: (x["sort_no"] is None, x["sort_no"] or 0, x["name"].lower())):
            if (depth == 0 and is_inbox(r["name"])) or (vis is not None and r["id"] not in vis):
                continue
            p = path + [r["name"]]
            out.append({"id": r["id"], "name": r["name"], "parent_id": r["parent_id"], "depth": depth, "path": " / ".join(p)})
            if depth < 30:
                walk(r["id"], p, depth + 1)
    walk(root, [], 0)
    return out


def folder_path(c, node):
    """2.199.0 B (#2742): "Kunde A / 2026" -- the path of the folder a document lies in below its documents folder, or ""."""
    fl = folder_label(c, node)
    if not fl:
        return ""
    root = docs_root(c, node)
    names = []
    for x in _fs_chain(c, int(fl)):
        if x["id"] == root:
            break
        names.append(x["name"])
    return " / ".join(reversed(names))


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


def folder_by_name(c, node, uid, name, create=True, path=False, check=False, also=None):
    """The folder `name` below the documents folder of node's workspace (made when missing and create), or None.
    2.199.0 B (#2742): path=True reads "Kunde A / 2026" as a path and walks (and makes) the subfolders (a customer's name
    with a slash stays one folder: path False). A new folder belongs to the owner of the
    documents folder (2.48.0 review: never a second "Dokumente" elsewhere).
    2.199.0 G (#2742 review): check=True (a person's request) walks only through folders uid sees (fs_role, also the hub
    mail rule) and makes a folder only where uid edits -- otherwise None and nothing made (no hidden folder, no hint).
    2.607.0 (#4872, review): also = a second person who asks along ("Apply what was learned" by someone else than the
    uploader): the walk and a new folder need both of them -- nobody has a folder made where they may not edit themselves."""
    who = {uid, also or uid}
    root = docs_root(c, node)
    parts = [safe_fs_name(x[:NAME_MAX]).strip() for x in (str(name or "").split("/") if path else [str(name or "")])]
    parts = [x for x in parts if x][:DEPTH_MAX - 2]
    if not root or not parts or is_inbox(parts[0]):
        return None
    p = c.execute("SELECT owner_id, org_id FROM fs_nodes WHERE id=?", (root,)).fetchone()
    pid = root
    for nm in parts:
        r = c.execute("SELECT id FROM fs_nodes WHERE parent_id=? AND kind='folder' AND lower(name)=lower(?) AND deleted_at IS NULL "
                      "ORDER BY id LIMIT 1", (pid, nm)).fetchone()
        if r:
            if check and not all(fs_role(c, r[0], u) for u in who):
                return None
            if fl_is_locked(c, r[0]):
                return None  # 2.353.0 F (#2758, review M2): a locked folder takes no document (none is made next to it either)
            pid = r[0]
            continue
        if not create or (check and any(fs_role(c, pid, u) not in ("owner", "edit") for u in who)):
            return None
        ts = _now()
        pid = insert_id(c, """INSERT INTO fs_nodes(parent_id,kind,name,owner_id,org_id,created_by,created_at,updated_at)
                              VALUES(?,'folder',?,?,?,?,?,?)""",
                        (pid, _free_name(c, pid, p["owner_id"], p["org_id"], nm), p["owner_id"], p["org_id"], also or uid, ts, ts))
    return pid


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


def _learn_seen(c, m, uid, f, lid):
    """2.360.0 B (#2496): the models of an organisation's documents folder learn from every member's documents; for a
    member who does not manage it a learned sender / type / tag counts only when it is on another document they see."""
    oid = ws_org(m["ws"])
    if not oid or not uid:
        return True
    with system_ctx(c):
        r = c.execute("SELECT role FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone()
    if r and r[0] == "admin":
        return True
    q = ("SELECT 1 FROM doc_node_tags WHERE tag_id=? AND node_id<>?" if f == "tag" else
         f"SELECT 1 FROM doc_meta WHERE {'sender_id' if f == 'sender' else 'type_id'}=? AND node_id<>?")
    return bool(c.execute(f"{q} AND node_id IN {_fs_visible_sql(c, uid)} LIMIT 1", (int(lid), m["node_id"])).fetchone())


def classify(c, m, node, text, given=None, seer=None):
    """(set, suggest, auto): what the levels of the workspace decide for one document.
    set = {feature: value} applied now, suggest = {feature: {value, conf, by}} offered for review, auto = {feature: how}.
    Values: sender / type = label ids, folder = folder id text, tags = [tag ids]. given = features fixed by the caller.
    seer = 2.607.0 (#4872): the person who asks for the sorting ("Apply what was learned") when not the uploader: a folder
    only one they may edit as well, a learned sender / type / tag only one they see elsewhere as well (_learn_seen)."""
    uid = m["created_by"] or node["owner_id"]
    can = lambda fid: all(_fs_role(c, fid, u) in ("owner", "edit") for u in {uid, seer or uid})  # noqa: E731
    seen = lambda f, lid: all(_learn_seen(c, m, u, f, lid) for u in {uid, seer or uid})  # noqa: E731
    ws = m["ws"]
    lv = cfg_get(c, ws)["levels"]
    given = given or {}
    out, sug, auto = {}, {}, {}
    rr = RU.apply_rules(rules_received(c, m, node), f"{node['name']}\n{text}") if any(lv[f] in ("rules", "learn") for f in lv) else {"tags": []}  # 2.581.0 (#4803)
    toks = CL.tokens(f"{node['name']}\n{text}")
    for f in ("sender", "type", "folder"):
        if f in given or lv[f] in ("agent", "off"):
            continue
        if rr.get(f):
            if f == "folder":
                fid = folder_by_name(c, node, uid, rr[f], path=True, check=True, also=seer)  # 2.199.0 B (#2742): "A / B" = a subfolder
                # 2.351.0 A (#2823): a rule files only into a folder the uploading person may edit (walks and makes folders
                # only where they see / edit); otherwise the file stays where it lands without the rule
                if fid and not can(fid):
                    fid = None
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
            # 2.360.0 B (#2496); 2.373.0 (#3336): a learned folder only one the uploading person may edit (like a rule),
            # neither filed nor suggested otherwise -- the file stays where it lands
            if not can(int(label)):
                continue
        elif not label_ok(c, ws, f, label) or not seen(f, label):
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
                if not str(tid).isdigit() or not label_ok(c, ws, "tag", tid) or int(tid) in tags or not seen("tag", tid):
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


# 2.607.0 (#4872): a new sorting (a recognition run, "Recognise again", "Apply what was learned") may replace what the rules or
# the learned models set before; a value set by hand, an import's, an e-invoice's or an agent's stays. Tags are never replaced:
# the tags a sorting finds are added to the ones there (their marks stay, a tag set by hand has none).
LEARN_AUTO = ("rule", "learn")


def learn_fixed(cur, auto_all, keep=()):
    """The features a sorting leaves alone (classify given): sender / type / folder with a value whose auto mark is not
    LEARN_AUTO (no mark = set by hand), and keep (the features an import gave)."""
    return {f for f in ("sender", "type", "folder") if cur[f] and auto_all.get(f) not in LEARN_AUTO} | set(keep)


def learn_merge(c, nid, newv, auto, sug):
    """2.607.0 (#4872): a classify result made additive for the tags: newv["tags"] = the tags there + the new ones (auto["tags"]
    the marks of all, the old ones keep theirs), dropped when nothing is new; a suggested tag the document has already goes.
    -> the ids of the tags added (newv / auto / sug are changed in place)."""
    have = {t["id"]: t["auto"] for t in node_tags(c, nid)}
    if isinstance(sug.get("tags"), dict):
        sug["tags"]["value"] = [t for t in sug["tags"].get("value") or [] if t not in have]
        if not sug["tags"]["value"]:
            sug.pop("tags")
    add = [t for t in newv.get("tags") or [] if t not in have]
    if not add:
        newv.pop("tags", None)
        auto.pop("tags", None)
        return []
    marks = auto.get("tags") if isinstance(auto.get("tags"), dict) else {}
    newv["tags"] = [*have, *add]
    auto["tags"] = {**have, **{t: marks.get(t, "learn") for t in add}}
    return add


# 2.363.3 (#3134): "Recognise again" can be taken back for 24 h: the row's recognised values as stored (sealed ones stay sealed)
# and the tags are kept in doc_meta.redo_prev until the undo or the queue's clean-up (redo_purge). A folder the run filed the
# document into stays: the document may be used there already.
REDO_COLS = ("state", "error", "method", "pages", "text", "doc_date", "due_date", "amount", "currency", "sender_id", "type_id",
             "auto", "suggest", "review", "version", "done_at", "extracted", "asn")
REDO_HOURS = 24


def redo_save(c, m, nid):
    """Keeps what the new run replaces. Only from a finished state: a second press while it waits keeps the first copy."""
    if m["state"] not in ("done", "failed"):
        return
    prev = {k: m[k] for k in REDO_COLS}
    prev["ws"], prev["tags"] = m["ws"], [t["id"] for t in node_tags(c, nid)]
    prev["title"], prev["title_manual"] = m["title"] or "", m["title_manual"]  # 2.783.0 (#4882): the run may set the pattern's title
    c.execute("UPDATE doc_meta SET redo_prev=?, redo_at=? WHERE node_id=?", (json.dumps(prev, separators=(",", ":")), _now(), nid))


def redo_back(c, nid):
    """Puts the kept values back; values set by hand since then stay. Raises BadInput when it is too late or still running.
    The caller holds no lock: the row is locked here, so the queue cannot take it up meanwhile."""
    m = c.execute("SELECT * FROM doc_meta WHERE node_id=? FOR UPDATE", (nid,)).fetchone()
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if m["state"] == "run":
        raise BadInput(tr("The recognition is still running. Please try again in a moment."))
    try:
        prev = json.loads(m["redo_prev"] or "{}")
    except ValueError:
        prev = {}
    fresh = m["redo_at"] and m["redo_at"] > iso(now_utc() - timedelta(hours=REDO_HOURS))
    # a new version of the file since then: the old text would not belong to it
    stale = prev.get("state") == "done" and int(prev.get("version") or 0) != int(node["cur_version"] or 0)
    if not prev or not fresh or stale or prev.get("ws") != m["ws"]:
        raise BadInput(tr("This recognition can no longer be undone"))
    try:  # 2.363.3 (#3134, review): a key rotation since then: the kept copy is sealed with a key that is gone
        doc_open_as(c, m["ws"], "doc_meta.text", prev["text"])
    except OrgCryptError:
        raise BadInput(tr("This recognition can no longer be undone")) from None
    auto, hand = json.loads(prev["auto"] or "{}"), hand_fields(meta_json(c, m, "auto", {}))
    auto.pop("_hand", None)
    auto.pop("_was", None)
    now_auto = meta_json(c, m, "auto", {})
    auto.update({k: now_auto[k] for k in ("_hand", "_was", "_scan", "_pg") if k in now_auto})  # 2.836.0 (#5390, review): the scan mark stays; 2.905.0 (#5393): the page size of the file now
    vals = {k: prev[k] for k in REDO_COLS if k != "auto"}
    for f in hand:
        vals[HAND_FIELDS[f]] = m[HAND_FIELDS[f]]
    if vals["asn"] and vals["asn"] != m["asn"]:  # 2.363.3 (#3134, review): the old number may belong to another document by now
        write_lock(c, f"doc-asn:{m['ws']}")  # the row is locked already: same order as asn_lock
        if asn_taken(c, m["ws"], vals["asn"], nid):
            vals["asn"] = m["asn"]
    if "title" in prev and not title_is_manual(m):  # 2.783.0 (#4882): the title from before; one set by hand since then stays
        vals["title"], vals["title_manual"] = prev["title"], prev.get("title_manual")
    sets = ", ".join(f"{k}=?" for k in vals)
    c.execute(f"UPDATE doc_meta SET {sets}, auto=?, redo_prev='', redo_at='', updated_at=? WHERE node_id=?",
              (*vals.values(), json.dumps(auto, separators=(",", ":")), _now(), nid))
    set_tags(c, nid, prev["tags"], {t: "" for t in prev["tags"]})
    m = meta_row(c, nid)
    doc_index(c, nid, m["ws"], index_text(c, dict(m), node["name"], doc_open(c, m["ws"], "doc_meta.text", m["text"]) or ""))


def redo_purge(c):
    """The queue's clean-up: what can no longer be taken back goes (the old texts stay no longer than needed)."""
    c.execute("UPDATE doc_meta SET redo_prev='', redo_at='' WHERE redo_at<>'' AND redo_at<?", (iso(now_utc() - timedelta(hours=REDO_HOURS)),))
    c.execute("UPDATE doc_meta SET learn_prev='', learn_at='' WHERE learn_at<>'' AND learn_at<?", (iso(now_utc() - timedelta(hours=REDO_HOURS)),))  # 2.607.0 (#4872)


# 2.607.0 (#4872): "Apply what was learned" -- only the sorting (rules + the learned models, classify) with the stored text of a
# document: no new recognition, no archive number, date and amount stay. Empty sender / type / folder are filled, automatic ones
# may be found anew (LEARN_AUTO), the tags found are added; values and tags set by hand stay. One step back for 24 h:
# doc_meta.learn_prev (learn_back), a value changed since then stays as it is.
def learn_apply(c, nid, uid, run):
    """Sorts document nid again for person uid (write access checked by the caller). -> "set" (a value set), "suggest" (new
    suggestions only), "both", "" (nothing new) or None (skipped: the recognition waits / runs, a stack waiting to be split)."""
    from .split import sp_view
    write_lock(c, f"doc_meta-{nid}")  # like a save (web.py docs_patch); the recognition locks the row (same order: lock, row)
    m = c.execute("SELECT * FROM doc_meta WHERE node_id=? FOR UPDATE", (nid,)).fetchone()
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    if not m or not node or m["state"] not in ("done", "failed") or (sp_view(m) or {}).get("stack"):
        return None
    ws = m["ws"]
    text = meta_text(c, m)
    auto_all = meta_json(c, m, "auto", {})
    cur = current(c, m, node)
    fixed = learn_fixed(cur, auto_all)
    newv, sug, auto = classify(c, m, node, text, given=fixed, seer=uid)
    for f in ("sender", "type", "folder"):  # the same value again is nothing new
        if f in newv and str(newv[f] or "") == str(cur[f] or ""):
            newv.pop(f)
            auto.pop(f, None)
    added = learn_merge(c, nid, newv, auto, sug)
    old_sug = meta_json(c, m, "suggest", {})
    keep = {k: v for k, v in old_sug.items() if k == "_given" or k in fixed or (isinstance(v, dict) and v.get("by") == "agent")}
    new_sug = {**{k: v for k, v in sug.items() if k not in newv}, **keep}
    for f in newv:
        if f != "tags" and (new_sug.get(f) or {}).get("by") != "agent":
            new_sug.pop(f, None)
    fresh = [k for k, v in sug.items() if k in new_sug and (old_sug.get(k) or {}).get("value") != v.get("value")]
    if not newv and new_sug == old_sug:
        return ""
    stamp = _now()
    prev = {"run": run, "ws": ws, "sender_id": m["sender_id"], "type_id": m["type_id"], "parent_id": node["parent_id"],
            "owner_id": node["owner_id"], "auto": m["auto"] or "", "suggest": m["suggest"] or "", "review": m["review"], "stamp": stamp,
            "title": m["title"] or "", "title_manual": m["title_manual"],  # 2.783.0 (#4882)
            "after": {**{f: str(v) for f, v in newv.items() if f != "tags"}, "tags": added}}
    apply_values(c, m, node, newv, auto)
    auto_all.update({f: (a[added[0]] if f == "tags" else a) for f, a in auto.items()})
    review = 1 if any(k != "_given" for k in new_sug) else m["review"]
    c.execute("UPDATE doc_meta SET auto=?, suggest=?, review=?, learn_prev=?, learn_at=?, updated_at=? WHERE node_id=?",
              (json.dumps(auto_all, separators=(",", ":")), _jseal(c, ws, "doc_meta.suggest", new_sug) if new_sug else "", review,
               json.dumps(prev, separators=(",", ":")), stamp, stamp, nid))
    t_new = title_auto(c, nid) if newv else False  # 2.783.0 (#4882): a new sender / type -> the pattern's title (never a hand one)
    if "sender" in newv or t_new:  # the word index holds the sender's name (and the title)
        doc_index(c, nid, ws, index_text(c, dict(meta_row(c, nid)), node["name"], text))
    return ("both" if fresh else "set") if newv else ("suggest" if fresh else "")


def learn_back(c, nid, run):
    """Takes "Apply what was learned" of run back on document nid: a sender / type / folder / tag it set comes off when it is
    still there, the marks come back; the suggestions and "To review" only when nothing was saved since. -> done (bool)."""
    write_lock(c, f"doc_meta-{nid}")
    m = c.execute("SELECT * FROM doc_meta WHERE node_id=? FOR UPDATE", (nid,)).fetchone()
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    try:
        prev = json.loads(m["learn_prev"] or "{}") if m else {}
    except ValueError:
        prev = {}
    fresh = m and m["learn_at"] and m["learn_at"] > iso(now_utc() - timedelta(hours=REDO_HOURS))
    if not prev or not fresh or not run or prev.get("run") != run or prev.get("ws") != m["ws"] or not node:
        return False
    af = prev.get("after") or {}
    try:
        p_auto = json.loads(prev.get("auto") or "{}")
    except ValueError:
        p_auto = {}
    auto = meta_json(c, m, "auto", {})
    back = []
    for f, col in (("sender", "sender_id"), ("type", "type_id")):
        if f in af and str(m[col] or "") == af[f]:
            c.execute(f"UPDATE doc_meta SET {col}=? WHERE node_id=?", (prev.get(col), nid))
            back.append(f)
    if "folder" in af and str(node["parent_id"] or "") == af["folder"] and prev.get("parent_id"):
        chain = _fs_chain(c, int(prev["parent_id"]))  # the folder it came from: still a folder of the same space
        # 2.607.0 (#4872, review): ... and not locked meanwhile (no plain, recognised document into a locked folder, _in_docs_tree)
        if chain and chain[0]["kind"] == "folder" and not _fs_deleted(chain) and chain[0]["org_id"] == node["org_id"] \
                and fsl_of_chain(c, chain) is None:
            c.execute("UPDATE fs_nodes SET parent_id=?, owner_id=?, updated_at=? WHERE id=?",
                      (int(prev["parent_id"]), prev.get("owner_id") or node["owner_id"], _now(), nid))
            back.append("folder")
    gone = [t for t in af.get("tags") or []
            if c.execute("DELETE FROM doc_node_tags WHERE node_id=? AND tag_id=? AND auto IN ('rule', 'learn')", (nid, int(t))).rowcount]
    if gone and len(gone) == len(af.get("tags") or []):
        back.append("tags")
    for f in back:
        if p_auto.get(f):
            auto[f] = p_auto[f]
        else:
            auto.pop(f, None)
    sets, args = "auto=?", [json.dumps(auto, separators=(",", ":"))]
    if "title" in prev and not title_is_manual(m) and (m["title"] or "") != prev["title"]:  # 2.783.0 (#4882): the pattern's title back
        sets, args = sets + ", title=?, title_manual=?", [*args, prev["title"], prev.get("title_manual")]
    if m["updated_at"] == prev.get("stamp"):  # nothing saved since: the suggestions and "To review" as they were
        sets, args = sets + ", suggest=?, review=?", [*args, prev.get("suggest") or "", int(prev.get("review") or 0)]
    c.execute(f"UPDATE doc_meta SET {sets}, learn_prev='', learn_at='', updated_at=? WHERE node_id=?", (*args, _now(), nid))
    m = meta_row(c, nid)
    doc_index(c, nid, m["ws"], index_text(c, dict(m), node["name"], meta_text(c, m)))
    return True


def thumb_store(c, m, node, data, kind):
    """Make the preview image of a document (sealed like its file) and note its path in doc_meta.thumb.
    2.583.0 (#4812): and the sharper one of big cards (THUMB_WL, doc_meta.thumb_l), sealed the same way (pictures / PDFs only)."""
    if kind not in ("pdf", "image", "docx", "xlsx", "odt", "ods"):  # 2.635.0 (#4807): + Office files (from their preview model)
        return
    rel = _thumb_write(c, m, node, thumb_bytes(data, kind), "")
    if not rel:
        return
    thumb_drop(m["thumb"])
    c.execute("UPDATE doc_meta SET thumb=? WHERE node_id=?", (rel, node["id"]))
    if not thumb_store_l(c, m, node, data, kind) and thumb_l_of(m):  # no sharp one of the new content: the old one never stays
        thumb_drop(thumb_l_of(m))
        c.execute("UPDATE doc_meta SET thumb_l=NULL WHERE node_id=?", (node["id"],))


def thumb_store_l(c, m, node, data, kind):
    """2.583.0 (#4812): only the sharper preview (THUMB_WL wide) into doc_meta.thumb_l -- the catch-up of documents from before
    (docs/thumbfill.py). Nothing made (no tools, a damaged file): the column stays as it was, the card keeps the small one."""
    if kind not in ("pdf", "image"):
        return False
    rel = _thumb_write(c, m, node, thumb_bytes(data, kind, THUMB_WL), "l")
    if not rel:
        return False
    thumb_drop(thumb_l_of(m))
    c.execute("UPDATE doc_meta SET thumb_l=? WHERE node_id=?", (rel, node["id"]))
    return True


def thumb_l_of(m):
    """2.583.0 (#4812): the path of the sharper preview of doc_meta row m ('' when none, or the row was read without it)."""
    return (m["thumb_l"] if "thumb_l" in m.keys() else "") or ""


def _thumb_write(c, m, node, jpg, tag):
    """A preview JPEG written below ATT_DIR/THUMB_DIR, sealed like the document (an organisation's key; a private one with the
    space's derived key, 2.48.0 review L3) -> its relative path, None when there is nothing to write or the disk refused."""
    import os
    import uuid
    if not jpg:
        return None
    rel = os.path.join(THUMB_DIR, f"{int(node['id'])}-{uuid.uuid4().hex[:10]}{'-' + tag if tag else ''}.jpg")
    try:
        os.makedirs(os.path.join(ATT_DIR, THUMB_DIR), exist_ok=True)
        if node["org_id"]:
            oc_write_file(c, node["org_id"], os.path.join(ATT_DIR, rel), jpg)
        else:  # 2.48.0 review (L3): a private document's preview is sealed like its text (the derived key of the space)
            from ..core.orgcrypt import _write_atomic
            _write_atomic(os.path.join(ATT_DIR, rel), thumb_seal(c, m["ws"], jpg))
    except OSError:
        return None
    return rel


def _thumb_ctx(ws):
    return b"kalmido-docs-thumb-v1|" + ws.encode()


def thumb_seal(c, ws, data):
    """The preview of a private document sealed with the space's derived key (unchanged: encryption off, no server key).
    2.662.0 (#4939): also unchanged while private_encrypt is off (after decrypt-private no new preview is sealed again)."""
    if ws_org(ws) or not oc_active(c) or not oc_private_on(c):
        return data
    key = _ws_key(c, ws)
    return oc_seal_k(key, 0, data, _thumb_ctx(ws)) if key else data


def thumb_read(c, ws, path):
    """The plain preview image: a private one with the space's key (header org 0), else like any stored file."""
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
    if rel and rel.startswith(THUMB_DIR + os.sep) and ".." not in rel:
        try:
            os.remove(os.path.join(ATT_DIR, rel))
        except OSError:
            pass


RECEIPT_TYPE = re.compile(r"rechnung|beleg|quittung|kassenbon|bon\b|invoice|receipt|bill\b", re.I)

RECEIPT_TEXT = re.compile(r"rechnung|invoice|quittung|kassenbon|receipt", re.I)


def doc_guesses(c, m, ws, type_id, text=""):
    """2.98.0 D (#2178): amount and due date are guessed only for a receipt photo (an amount typed in before the first run) or a
    document of type invoice / receipt (the type label, or the word in the first lines of the text); an import (paperless) never gets a guess."""
    if m["source"] == "paperless":
        return False
    if m["amount"] and not m["method"]:
        return True
    name = label_name(c, ws, "type", type_id) if type_id else None
    return bool(name and RECEIPT_TYPE.search(name)) or bool(RECEIPT_TEXT.search(text[:3000]))


def process(c, nid):
    """The recognition run of one document: text (text layer / OCR), preview, date / due date / amount, sorting, index.
    Returns the new state. Runs in the background queue (docs/ingest.py) -- never inside a request."""
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
    ei = None
    if not given.get("text"):
        ei = ei_of_file(node["name"], node["mime"], data, m["created_by"])  # 2.146.0 A (#2451): an e-invoice (XML / in a PDF)
    if given.get("text"):
        res = {"text": str(given["text"])[:200_000], "method": "import", "kind": file_kind(node["name"], node["mime"], data[:2048])}
    elif ei and ei["source"] == "xml":       # 2.146.0 A (#2451): the readable text of the invoice, not the XML
        res = {"text": ei_text(ei), "method": "e-invoice", "kind": "einvoice"}
    else:
        try:
            from ..core.i18n import lang as _lang
            ulang = _lang(c, uid=m["created_by"])  # 2.122.0 (#2101): the person's app language picks the OCR language
        except Exception:  # noqa: BLE001 -- the language is a hint only
            ulang = None
        res = doc_text(node["name"], node["mime"], data, lang=ulang, langs=cfg_get(c, ws)["ocr_langs"] or None)  # 2.635.0 (#4807 b)
    if res.get("error") == "busy":
        return "wait"
    if ei and not res.get("error"):
        res["method"] = "e-invoice"
    # 2.781.0 (#5390): read before the row is locked (a PDF is read in a child process); 2.836.0 (review): before thumb_store's UPDATE
    scan = scan_of(node["name"], node["mime"], data, res.get("kind"), m["source"], einvoice=bool(ei))
    try:                                     # 2.905.0 (#5393): the first page's size (a PDF in a child process), before the row lock
        page1, pg_busy = pg_of(data, res.get("kind"), strict=True), False
    except PgBusy:                           # 2.990.0 (#5571): no free PDF slot now -- the stored size stays (the catch-up is done)
        page1, pg_busy = None, True
    thumb_store(c, m, node, data, res.get("kind"))
    text = res.get("text") or ""
    asn_found = None
    if not m["asn"]:
        # 2.273.0 F2 (#3047): only found here; written under the workspace lock just before the final write (the lock is not
        # held over classifying / recognising, a save with "next" does not wait for them)
        # 2.591.0 B (#4863): the codes of every page (up to ocr.QR_PAGES, a finer second try), kept apart from the text
        pre = cfg_get(c, ws)["asn_prefix"]
        # review: at most as many pages as the text recognition (ocr.OCR_PAGES) and ocr.QR_DOC_S seconds in all
        codes = qr_codes(data, res.get("kind"), pages=min(int(res.get("pages") or 1), OCR_PAGES), budget=QR_DOC_S, want=lambda cs: EX.find_asn(pre, (), codes=cs) is not None)
        asn_found = EX.find_asn(pre, [text[:20000]], codes=codes)
    ex = EX.extract(text, guess=False)
    if m["source"] == "paperless":           # an import keeps due date and amount empty (only a monetary field fills them)
        ex["due"] = ex["amount"] = ex["currency"] = None
    #     # 2.98.0 D (#2178): the amount / due date are guessed below, once the type is known
    vals = {"doc_date": given.get("date") or ex["date"], "due_date": given.get("due") or ex["due"],
            "amount": str(given.get("amount") or ex["amount"] or ""), "currency": str(given.get("currency") or ex["currency"] or "")[:8]}
    auto_all = meta_json(c, m, "auto", {})
    if ei:                                   # 2.146.0 A (#2451): the e-invoice's values replace the recognition's
        ei_det = ei_details(ei)
        ei_old = meta_json(c, m, "extracted", {}) if m["extracted"] else {}
        ei_first = not ei_old.get("_einv")  # 2.153.0 (#2055): read as an e-invoice for the first time
        ei_rc = bool(ei_old.get("_eirc"))   # 2.185.0 A (#2583): it was made a receipt once (a person may have taken it out)
        # 2.153.0 (#2055): a credit note's amount negative (ei_amount)
        for k, v in (("doc_date", ei["date"]), ("due_date", ei["due"]), ("amount", ei_amount(ei)), ("currency", ei["currency"])):
            if v and not given.get({"doc_date": "date", "due_date": "due"}.get(k, k)):
                vals[k] = str(v)[:8] if k == "currency" else v
                auto_all[{"doc_date": "date", "due_date": "due"}.get(k, k)] = "e-invoice"
    if m["doc_date"]:
        vals["doc_date"] = m["doc_date"]     # set by hand while it waited
    if m["amount"] and not m["method"]:      # 2.90.0 A (#1921): an amount typed in before the first run (receipt photo) stays
        vals["amount"] = doc_open(c, ws, "doc_meta.amount", m["amount"]) or vals["amount"]
    if not vals["doc_date"] and m["taken_at"]:  # 2.61.0 B (#1819): no date in the text -> the day the photo was taken
        vals["doc_date"] = str(m["taken_at"])[:10]
        auto_all["date"] = "photo"
    imported = {}                            # features the caller gave (an import): set as they are
    for f in ("sender", "type"):
        if given.get(f):
            imported[f] = label_id(c, ws, f, given[f])
    if given.get("tags"):
        imported["tags"] = [t for t in (label_id(c, ws, "tag", x) for x in given["tags"]) if t]
    how, agent_sug = "import", {}
    if imported and given.get("_by") == "agent":  # 2.122.0 (#2098): an agent's values follow the levels like PATCH (level agent = suggestion)
        lv_a = cfg_get(c, ws)["levels"]
        agent_sug = {f: {"value": v, "by": "agent"} for f, v in imported.items() if lv_a.get(f) == "agent"}
        imported, how = {f: v for f, v in imported.items() if f not in agent_sug}, "agent"
    if imported:
        apply_values(c, m, node, imported, {f: ({t: how for t in v} if f == "tags" else how) for f, v in imported.items()} if how == "agent" else {}, how)
        auto_all.update({f: how for f in imported})
    if ei and not given.get("sender") and not m["sender_id"] and (ei_det["supplier"] or ei_det["vat_id"]):
        from ..receipts.extracted import rx_sender_find  # 2.146.0 A (#2451): the seller of the e-invoice is the sender
        sid, sname = rx_sender_find(c, ws, ei_det, nid)
        sid = sid or (label_id(c, ws, "sender", sname[:120]) if sname else None)
        if sid:
            apply_values(c, m, node, {"sender": sid}, {})
            imported["sender"] = sid         # fixed: the classifier does not override it
            auto_all["sender"] = "e-invoice"
    cur = current(c, m, node)
    # 2.607.0 (#4872): a value set by hand / imported stays, an automatic one may be found anew; the tags found are added
    # (was: every feature with a value fixed, the tags as a whole as soon as there was one)
    fixed = learn_fixed(cur, auto_all, imported)
    if given.get("folder"):  # 2.577.0 C (#4466): a named mail address's target folder stays (docs/mailaddr.py)
        fixed.add("folder")
    newv, sug, auto = classify(c, m, node, text, given=fixed)
    new_tags = learn_merge(c, nid, newv, auto, sug)  # auto["tags"] only when tags were added (the marks of all)
    sug = {**sug, **agent_sug}
    apply_values(c, m, node, newv, auto)
    auto_all.update({f: (a[new_tags[0]] if f == "tags" else a) for f, a in auto.items()})
    if not given.get("text") and not ei and doc_guesses(c, m, ws, newv.get("type") or cur["type"], text):  # 2.98.0 D (#2178)
        ex = EX.extract(text, details=True)  # 2.121.0 A (#2092): + supplier, VAT, net / gross, invoice number (a suggestion)
        vals["due_date"] = given.get("due") or ex["due"]
        vals["amount"] = str(given.get("amount") or ex["amount"] or vals["amount"] or "")
        vals["currency"] = str(given.get("currency") or ex["currency"] or vals["currency"] or "")[:8]
    node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    # 2.273.0 C (#3047): the row locked from here on (a save waits); the values a person set by hand stay
    m2 = c.execute("SELECT * FROM doc_meta WHERE node_id=? FOR UPDATE", (nid,)).fetchone()
    if not m2:  # #3090: deleted along while the run went (users.user_delete / orgs.org_delete lock its row first)
        return None
    auto_all.pop("_asn_taken", None)         # 2.591.0 B (#4863): a fresh run, a fresh hint
    if page1:                                # 2.905.0 (#5393): the document view's preview takes it before the file is loaded
        auto_all["_pg"] = page1
    elif not pg_busy:                        # no size of this content (another kind, unreadable): never the old version's
        auto_all.pop("_pg", None)
    if scan is not None:                     # 2.781.0 (#5390): a scan (archive number field); unknown = the old mark stays
        auto_all["_scan"] = scan
    if asn_found and not m2["asn"]:
        asn_lock(c, ws, nid)                 # 2.273.0 C (#3047); F2: only around the write
        holder = asn_holder(c, ws, asn_found, nid)
        if holder is None:
            c.execute("UPDATE doc_meta SET asn=? WHERE node_id=?", (asn_found, nid))
            auto_all["asn"] = "code"
        else:  # 2.591.0 B (#4863): not silently skipped - the document says which one has the number (doc_json asn_taken)
            auto_all["_asn_taken"] = {"n": int(asn_found), "by": int(holder)}
    hand = hand_fields(meta_json(c, m2, "auto", {}))
    was = meta_json(c, m2, "auto", {}).get("_was")
    was = {f: w for f, w in was.items() if f in hand} if isinstance(was, dict) else {}
    for f in hand:
        col = HAND_FIELDS[f]
        if isinstance(was.get(f), dict):    # 2.273.0 F2 (#3047): this run's value is the recognised one behind the hand value
            was[f]["v"], was[f]["a"] = was_digest(nid, f, str(vals[col] or "")), auto_all.get(f)
        vals[col] = (doc_open(c, ws, "doc_meta.amount", m2["amount"]) or "") if col == "amount" else (m2[col] or ("" if col == "currency" else None))
        auto_all.pop(f, None)
    auto_all.pop("_hand", None)
    auto_all.pop("_was", None)
    if hand:
        auto_all["_hand"] = hand
    if was:
        auto_all["_was"] = was
    review = 1 if sug or not (m2["sender_id"] or m2["type_id"]) else 0
    state = "failed" if res.get("error") else "done"
    # 2.90.0 A (#1921): a date / an amount typed in while the run was busy wins (the columns' values at the time of the
    # write, not those read at the start of the run: the receipt sheet saves while the recognition still runs)
    c.execute("""UPDATE doc_meta SET state=?, error=?, method=?, pages=?, text=?,
                 doc_date=CASE WHEN doc_date IS NOT NULL AND doc_date<>'' THEN doc_date ELSE ? END, due_date=?,
                 amount=CASE WHEN amount<>'' AND method='' THEN amount ELSE ? END, currency=?,
                 auto=?, suggest=?, review=?, version=?, done_at=?, updated_at=? WHERE node_id=?""",
              (state, res.get("error") or "", res.get("method") or "", int(res.get("pages") or 0), doc_seal(c, ws, "doc_meta.text", text),
               vals["doc_date"], vals["due_date"], doc_seal(c, ws, "doc_meta.amount", vals["amount"]), vals["currency"],
               json.dumps(auto_all, separators=(",", ":")), _jseal(c, ws, "doc_meta.suggest", sug) if sug else "", review, node["cur_version"],
               _now(), _now(), nid))
    from ..receipts.extracted import rx_compact
    if ei:                                   # 2.146.0 A (#2451): the e-invoice's values + the invoice for its readable view
        # 2.153.0 (#2055): in an office's documents space it becomes a receipt (not an own invoice); 2.185.0 A (#2583): a
        # later run makes up a missing one (read before 2.153, moved into the office) unless it was a receipt once
        if (ei_first or not ei_rc) and ei_receipt(c, node, ws, ei, ei_det["vat_pct"], late=not ei_first):
            ei_rc = True
        meta_set_json(c, nid, ws, "extracted", {**rx_compact(ei_det), "_einv": ei_compact(ei), **({"_eirc": 1} if ei_rc else {})})
    else:
        meta_set_json(c, nid, ws, "extracted", rx_compact(ex.get("details")))  # 2.121.0 A (#2092): a fresh run, a fresh suggestion
    from .split import sp_detect, sp_view
    sp_detect(c, nid, data, res)             # 2.154.0 A (#1111): a stack scan with several archive number codes
    if not (sp_view(meta_row(c, nid)) or {}).get("stack"):
        title_auto(c, nid)                   # 2.783.0 (#4882): the title from the area's pattern (never one set by hand)
    doc_index(c, nid, ws, index_text(c, dict(meta_row(c, nid)), node["name"], text))
    return state
