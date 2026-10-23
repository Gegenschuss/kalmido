"""2.48.0 (#1152): the Paperless-ngx connection of a workspace and the import of its documents into the Kalmido documents.

2.69.0 A (#1846): also on a hosted server (KALMIDO_HOSTED=1): there only public HTTPS addresses (the admin's list of allowed
internal hosts does not apply), the storage quota is checked before and during the import, and one import runs per server at
a time (the others wait in a queue, URL and ZIP runs alike; zipimp.py = the import of an uploaded document_exporter ZIP).
One connection per workspace: an
organisation's admins set it up for the organisation, a person for their own space (a freelancer without an organisation
is their own admin, #1348). The documents go into the documents area of exactly that workspace (docs_ingest), never into
another one. Only Paperless-ngx -> Kalmido: Kalmido only reads (GET), it never writes or deletes anything in Paperless-ngx.

- The API token is sealed with the workspace's key (docs/store.py doc_seal) and never sent back to the app (only "set").
  It only goes to the host it was entered for: the SSRF guard of the calendar subscriptions (public addresses; an internal
  host only when an admin allowed it), no redirects, timeouts, MAX_FILE_MB per file.
- Preview: number of documents, the tags / correspondents / document types with their counts and how they map (a tag ->
  a tag | a folder of the documents | skipped; correspondent -> sender, document type -> type; names can be changed).
- Import: in the background (one thread per server process, the state in pl_sources.run_*), stoppable, with progress.
  What comes along: the original file, Paperless' text (no new recognition), the date, tags, correspondent, type, custom
  fields + notes + archive serial number as text below the document's text. Nothing twice: pl_imported (Paperless id per
  connection address) and the checksum of the file within the workspace.
- Following (optional): every every_min minutes the newest documents come in (newest first, until a page holds nothing new).
"""
import hashlib
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import timedelta

from ..core.config import app, MAX_FILE_MB, SECRET_KEY
from ..core.db import connect, iso, now_utc, parse_iso
from ..accounts.session import bg_here
from ..core.i18n import N_, tr
from ..core.pg import system_ctx, write_lock
from ..docs import store as S
from ..core.orgcrypt import oc_enc_k  # 2.149.0 G (#2517): pulled up from functions
from ..core.access import Denied  # 2.149.0 G (#2517): pulled up from functions

PL_TIMEOUT = 20               # s per request
PL_API_VERSIONS = (10, 9, 5)  # 2.56.4 (#1859): Accept: application/json; version=N, the first one the server takes. Paperless-ngx
                              # 3.x only allows 9 / 10 (406 on anything else), 2.x up to 9, 1.x up to 5 (custom fields, notes as a list)
PL_PAGE = 50                  # documents per page of the import
PL_LABEL_PAGES = 20           # pages of 100 tags / correspondents / types at most
PL_JSON_MAX = 8 * 1024 * 1024
PL_TOKEN_MAX = 400
PL_EVERY = (15, 30, 60, 240, 1440)  # minutes between two looks for new documents
PL_IDLE = 5                   # s the worker sleeps when there is nothing to do
PL_STALE = 10                 # min without a heartbeat: a run that was cut off (restart) is taken up again
PL_TEXT_MAX = 200_000
_VER = {}                     # address -> the API version that server took last (per process; a 406 asks again)
_W = {"thread": None}
_WAKE = threading.Event()
_LOCK = threading.Lock()

PL_ERR = {"key": N_("The API token is not set (or the server key changed): enter it again"),
          "auth": N_("Paperless-ngx refused the API token"),
          "network": N_("Paperless-ngx could not be reached"),
          "redirect": N_("Paperless-ngx answered with a redirect: check the address"),
          "answer": N_("Paperless-ngx sent an answer Kalmido does not understand: check the address"),
          "version": N_("This Paperless-ngx version speaks no API version Kalmido understands (5, 9 or 10)"),
          "too_large": N_("The file is larger than {0} MB"),
          "owner": N_("The person who set up the connection can no longer import here"),
          "quota": N_("The storage space is full: the import stopped"),
          "public_https": N_("In hosted operation only public HTTPS addresses work"),  # 2.69.0 A (#1846)
          "failed": N_("The import stopped because of an error")}


class PlError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, str(detail)[:20]

    def stored(self):
        return self.code + (":" + self.detail if self.detail else "")


def pl_err_text(stored):
    """The readable text of a stored error code ('' stays '')."""
    if not stored:
        return ""
    code = str(stored).partition(":")[0]
    if code in PL_ERR:
        return tr(PL_ERR[code], MAX_FILE_MB) if code == "too_large" else tr(PL_ERR[code])
    from ..calendars.subscriptions import cal_err_text
    return cal_err_text(stored)


from ..core.db import now_iso as _now  # noqa: E402  2.149.0 G (#2517): was an own copy


def pl_src(url):
    """A short key of a Paperless-ngx address: the same document id of another instance is another document."""
    return hashlib.sha256(str(url).lower().encode()).hexdigest()[:12]


def pl_norm_url(u):
    """https?://host[:port][/path] without /api at the end, or None."""
    from ..calendars.subscriptions import cal_norm_url
    if not isinstance(u, str):  # 2.48.0 review (L6): null / a number -> 400, not 500
        return None
    try:
        from ..admin.hosting import hosted
        u = cal_norm_url(u)
        if not u or not u.lower().startswith(("https://",) if hosted() else ("http://", "https://")):  # 2.69.0 A (#1846): hosted = HTTPS only
            return None
        p = urllib.parse.urlsplit(u)
        p.port  # noqa: B018 -- raises ValueError on a bad port
    except ValueError:
        return None
    if p.query or p.fragment or p.username or p.password or not p.hostname:
        return None
    u = u.rstrip("/")
    if u.lower().endswith("/api"):
        u = u[:-4]
    return u


def pl_row(c, ws):
    return c.execute("SELECT * FROM pl_sources WHERE ws=?", (ws,)).fetchone()


_TKEYS = {}


def _token_key(ws):
    """2.48.0 review (S2): the token is always sealed, also with the organisation's encryption off -- a key derived from the
    server key per workspace (like docs/store.py _ws_key for private spaces). None without a server key."""
    if not SECRET_KEY:
        return None
    k = _TKEYS.get(ws)
    if k is None:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.kdf.hkdf import HKDF
        k = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"kalmido-paperless-token-v1|" + ws.encode()).derive(SECRET_KEY)
        _TKEYS[ws] = k
    return k


def pl_seal_token(ws, tok):
    """The sealed token; None without a server key (then it is not stored at all)."""
    key = _token_key(ws)
    return oc_enc_k(key, S.ws_org(ws) or 0, f"pl_sources.token.v2|{ws}", tok) if key and tok else None


def pl_token(c, r):
    """The plain token. A plain value from before 2.48.0's review (or sealed with the organisation's key) is sealed with the
    server key right away (the caller's commit keeps it)."""
    v = r["token"]
    if not v:
        return ""
    if isinstance(v, str) and v.startswith(S.PREFIX):
        key = _token_key(r["ws"])
        if key:
            from ..core.orgcrypt import OrgCryptError, oc_dec_k
            try:
                return oc_dec_k(key, S.ws_org(r["ws"]) or 0, f"pl_sources.token.v2|{r['ws']}", v)
            except OrgCryptError:
                pass
        v = S.doc_open(c, r["ws"], "pl_sources.token", v)
        if not v or v.startswith(S.PREFIX):
            return ""
    sealed = pl_seal_token(r["ws"], v)
    if sealed:
        c.execute("UPDATE pl_sources SET token=? WHERE id=?", (sealed, r["id"]))
    return v


def pl_token_lost(c, r):
    """2.138.4 C (#2382): True when a token is stored but opens with neither the current server key nor the workspace's
    key (the server key changed): it has to be entered again. Reads only."""
    v = r["token"]
    if not v or not (isinstance(v, str) and v.startswith(S.PREFIX)):
        return False
    key = _token_key(r["ws"])
    if key:
        from ..core.orgcrypt import OrgCryptError, oc_dec_k
        try:
            oc_dec_k(key, S.ws_org(r["ws"]) or 0, f"pl_sources.token.v2|{r['ws']}", v)
            return False
        except OrgCryptError:
            pass
    w = S.doc_open(c, r["ws"], "pl_sources.token", v)
    return not w or w.startswith(S.PREFIX)


def pl_mapping(c, r):
    if isinstance(r, dict) and "_map" in r:  # 2.87.9 (#1940): a run into another space keeps the mapping of its source
        return r["_map"]
    m = S._jopen(c, r["ws"], "pl_sources.mapping", r["mapping"], {}) if r and r["mapping"] else {}
    out = {k: (m.get(k) if isinstance(m.get(k), dict) else {}) for k in ("tags", "senders", "types")}
    out["rules"] = m.get("rules", True) is not False  # 2.69.0 B (#1847): take over Paperless' matching rules
    return out


# ---- HTTP ---------------------------------------------------------------------------------------------------------------
def pl_get(c, url, token, path, raw=False, limit=PL_JSON_MAX):
    """GET url + path from Paperless-ngx with the token. JSON (raw: (bytes, content type, file name)). Raises PlError.
    2.56.4 (#1859): the API version is negotiated -- the one this server took last first, then PL_API_VERSIONS in order; a 406
    (version not allowed) tries the next one, none left = PlError('version')."""
    if not token:
        raise PlError("key")
    if raw:
        return _pl_get1(c, url, token, path, None, True, limit)
    last = _VER.get(url)
    for v in ([last] if last else []) + [x for x in PL_API_VERSIONS if x != last]:
        try:
            j = _pl_get1(c, url, token, path, v, False, limit)
        except PlError as e:
            if e.code == "http" and e.detail == "406":
                continue
            raise
        if last != v:
            if len(_VER) > 1000:
                _VER.clear()
            _VER[url] = v
        return j
    _VER.pop(url, None)
    raise PlError("version")


def _pl_get1(c, url, token, path, ver, raw, limit):
    from ..calendars.subscriptions import _cal_opener, CalError
    allow = plh_allow(c, url)
    if allow is None:  # 2.69.0 A (#1846): a stored http:// address on a server that is hosted now
        raise PlError("public_https")
    hdr = {"Authorization": f"Token {token}", "Accept": "*/*" if raw else f"application/json; version={ver}"}
    req = urllib.request.Request(url + path, headers=hdr, method="GET")
    try:
        with _cal_opener(allow).open(req, timeout=PL_TIMEOUT) as resp:
            if not raw and resp.headers.get("Content-Length", "").isdigit() and int(resp.headers["Content-Length"]) > limit:
                raise PlError("answer")
            data = resp.read(limit + 1)
            if len(data) > limit:
                raise PlError("too_large" if raw else "answer")
            if raw:
                cd = resp.headers.get("Content-Disposition") or ""
                m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
                name = urllib.parse.unquote(m.group(1)) if m else ""
                return data, (resp.headers.get("Content-Type") or "").split(";")[0].strip(), name
            try:
                return json.loads(data or b"null")
            except ValueError:
                raise PlError("answer") from None
    except urllib.error.HTTPError as e:
        e.close()
        raise PlError("auth" if e.code in (401, 403) else "redirect" if 300 <= e.code < 400 else "http", e.code) from None
    except urllib.error.URLError as e:
        raise PlError(plh_code(e.reason.code) if isinstance(e.reason, CalError) else "network") from None
    except CalError as e:
        raise PlError(plh_code(e.code)) from None
    except PlError:
        raise
    except (OSError, ValueError):
        raise PlError("network") from None


def plh_allow(c, url=None):
    """2.69.0 A (#1846): the internal hosts Paperless-ngx may be on: the admin's list on a self-hosted server, none on a hosted
    one (public addresses only, like the integrations of #905). None = this address may not be used at all (hosted + http)."""
    from ..admin.hosting import hosted
    from ..calendars.subscriptions import cal_allow
    if not hosted():
        return cal_allow(c)
    return frozenset() if url is None or str(url).lower().startswith("https://") else None


def plh_code(code):
    """A blocked (internal) address on a hosted server: the hint names public HTTPS, not the admin's list (which does not apply)."""
    from ..admin.hosting import hosted
    return "public_https" if code == "blocked" and hosted() else code


def pl_check(c, url, token):
    """A quick look whether address + token work (raises PlError)."""
    j = pl_get(c, url, token, "/api/documents/?page_size=1")
    if not isinstance(j, dict) or "count" not in j:
        raise PlError("answer")
    return int(j.get("count") or 0)


def pl_labels(c, url, token, kind):
    """All tags / correspondents / document_types: [{id, name, count, match, algo, insens}] (2.69.0 B (#1847): + the matching:
    pattern, matching_algorithm, is_insensitive -- see learn.py)."""
    out, page = [], 1
    while page <= PL_LABEL_PAGES:
        j = pl_get(c, url, token, f"/api/{kind}/?page_size=100&page={page}")
        if not isinstance(j, dict) or not isinstance(j.get("results"), list):
            raise PlError("answer")
        for x in j["results"]:
            if isinstance(x, dict) and isinstance(x.get("id"), int):
                out.append({"id": x["id"], "name": str(x.get("name") or "")[:S.NAME_MAX],
                            "count": int(x.get("document_count") or 0) if str(x.get("document_count") or "0").isdigit() else 0,
                            **pl_label_match(x)})
        if not j.get("next"):
            break
        page += 1
    return out


def pl_label_match(x):
    """2.69.0 B (#1847): {match, algo, insens} of a Paperless-ngx label (API answer or export record)."""
    algo = x.get("matching_algorithm")
    return {"match": str(x.get("match") or "")[:1000], "algo": algo if isinstance(algo, int) and not isinstance(algo, bool) else 0,
            "insens": x.get("is_insensitive") is not False}


def pl_fields(c, url, token):
    """The custom fields: {id: {name, type, options}}; options = the select options (API 7+: [{id, label}], before: [label])."""
    out, page = {}, 1
    while page <= PL_LABEL_PAGES:
        j = pl_get(c, url, token, f"/api/custom_fields/?page_size=100&page={page}")
        if not isinstance(j, dict) or not isinstance(j.get("results"), list):
            raise PlError("answer")
        for x in j["results"]:
            if isinstance(x, dict) and isinstance(x.get("id"), int):
                ed = x.get("extra_data") if isinstance(x.get("extra_data"), dict) else {}
                opts = ed.get("select_options") if isinstance(ed.get("select_options"), list) else []
                out[x["id"]] = {"name": str(x.get("name") or "")[:S.NAME_MAX], "type": str(x.get("data_type") or ""), "options": opts}
        if not j.get("next"):
            break
        page += 1
    return out


def _field_text(fd, v):
    """A custom field's value as text: a select option's label (API 7+: the option's id, before: its index), Yes / No,
    an amount 'EUR12.50' as '12.50 EUR', document links as 'Paperless #12'."""
    t = fd.get("type") if isinstance(fd, dict) else ""
    if isinstance(v, bool) or t == "boolean":
        return tr("Yes") if v else tr("No")
    if t == "select":
        for i, o in enumerate(fd.get("options") or []):
            if isinstance(o, dict) and o.get("id") == v and o.get("label") is not None:
                return str(o["label"])
            if isinstance(o, str) and isinstance(v, int) and i == v:
                return o
        return str(v)
    if t == "monetary":
        m = re.fullmatch(r"([A-Za-z]{3})?(-?\d+(?:\.\d+)?)", str(v))
        if m:
            return f"{m.group(2)} {(m.group(1) or '').upper()}".strip()
    if isinstance(v, list):
        return ", ".join(f"Paperless #{x}" if isinstance(x, int) else str(x) for x in v)
    return str(v)


def _map_default(kind, lid, name):
    return {"to": "tag", "name": name} if kind == "tags" else name


def pl_preview(c, r):
    """What an import would bring: count, already imported, the labels with their mapping."""
    url, tok = r["url"], pl_token(c, r)
    count = pl_check(c, url, tok)
    mp = pl_mapping(c, r)
    out = {"count": count, "already": c.execute("SELECT COUNT(*) FROM pl_imported WHERE ws=? AND src=?", (r["ws"], pl_src(url))).fetchone()[0]}
    for kind, key in (("tags", "tags"), ("correspondents", "senders"), ("document_types", "types")):
        rows = []
        for x in pl_labels(c, url, tok, kind):
            m = mp[key].get(str(x["id"]))
            if key == "tags":
                m = m if isinstance(m, dict) and m.get("to") in ("tag", "folder", "skip") else {"to": "tag", "name": x["name"]}
                rows.append({**x, "to": m["to"], "target": str(m.get("name") or x["name"])[:S.NAME_MAX]})
            else:
                rows.append({**x, "to": "skip" if m == "" else "keep", "target": (m if isinstance(m, str) and m else x["name"])[:S.NAME_MAX]})
        out[key] = rows
    from .learn import pll_rules_preview  # 2.69.0 B (#1847): which matching rules come along
    out["rules"] = pll_rules_preview({k: out[key] for k, key in (("tags", "tags"), ("correspondents", "senders"), ("document_types", "types"))},
                                     mp, c, r["ws"], pl_src(url))
    return out


def pl_clean_mapping(d):
    """{tags: {id: {to, name}}, senders: {id: name|''}, types: {id: name|''}} from the app (unknown parts dropped)."""
    out = {"tags": {}, "senders": {}, "types": {}, "rules": True}
    if not isinstance(d, dict):
        return out
    out["rules"] = d.get("rules") is not False  # 2.69.0 B (#1847)
    for k, v in (d.get("tags") or {}).items() if isinstance(d.get("tags"), dict) else ():
        if str(k).isdigit() and isinstance(v, dict) and v.get("to") in ("tag", "folder", "skip"):
            out["tags"][str(k)] = {"to": v["to"], "name": str(v.get("name") or "").strip()[:S.NAME_MAX]}
    for key in ("senders", "types"):
        for k, v in (d.get(key) or {}).items() if isinstance(d.get(key), dict) else ():
            if str(k).isdigit() and isinstance(v, str):
                out[key][str(k)] = v.strip()[:S.NAME_MAX]
    return out


# ---- one document -------------------------------------------------------------------------------------------------------
def monetary_value(doc, fields):
    """2.98.0 D (#2178): (amount '12.50', currency 'EUR' | None) of the first custom field of type monetary ('EUR12.50'), else None
    -- the only amount an import takes over (no guessing from the text)."""
    for f in doc.get("custom_fields") or []:
        fd = (fields or {}).get(f.get("field")) if isinstance(f, dict) else None
        if isinstance(fd, dict) and fd.get("type") == "monetary":
            m = re.fullmatch(r"([A-Za-z]{3})?\s*(\d+(?:\.\d+)?)", str(f.get("value") or "").strip())
            if m and float(m.group(2)) > 0:
                return f"{float(m.group(2)):.2f}", (m.group(1) or "").upper() or None
    return None


def _doc_text(doc, notes, fields):
    """Paperless' text + notes + archive serial number (labelled, below the text). 2.153.0 (#2179): the custom fields are
    no longer lines here -- plh_store makes them fields of the document (docs/fields.py df_from_paperless)."""
    parts = [str(doc.get("content") or "").strip()]
    extra = []
    if doc.get("archive_serial_number") not in (None, ""):
        extra.append(f"{tr('Archive serial number')}: {doc['archive_serial_number']}")
    if extra:
        parts.append("\n".join(extra))
    if notes:
        parts.append(tr("Notes") + ":\n" + "\n".join(f"- {n}" for n in notes))
    return "\n\n".join(p for p in parts if p)[:PL_TEXT_MAX]


def _notes(c, r, tok, doc):
    n = doc.get("notes")
    if isinstance(n, list):
        return [str(x.get("note") or "").strip() for x in n if isinstance(x, dict) and str(x.get("note") or "").strip()][:200]
    if isinstance(n, int) and n > 0:
        j = pl_get(c, r["url"], tok, f"/api/documents/{int(doc['id'])}/notes/")
        j = j.get("results") if isinstance(j, dict) else j
        return [str(x.get("note") or "").strip() for x in (j or []) if isinstance(x, dict) and str(x.get("note") or "").strip()][:200]
    return []


def _day(v):
    v = str(v or "")[:10]
    return v if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) else None


def pl_import_doc(c, r, uid, tok, doc, labels, fields):
    """One Paperless document into the documents of r's workspace. Returns 'new' | 'skip' | 'dup'. Raises PlError."""
    ws, src, pid = r["ws"], pl_src(r["url"]), int(doc["id"])
    if c.execute("SELECT 1 FROM pl_imported WHERE ws=? AND src=? AND pl_id=?", (ws, src, pid)).fetchone():
        return "skip"
    data, mime, fname = pl_get(c, r["url"], tok, f"/api/documents/{pid}/download/?original=true", raw=True,
                               limit=MAX_FILE_MB * 1024 * 1024)
    return plh_store(c, r, uid, src, doc, data, mime, fname, labels, lambda: _doc_text(doc, _notes(c, r, tok, doc), fields), fields)


def plh_store(c, r, uid, src, doc, data, mime, fname, labels, text, fields=None):
    """2.69.0 A (#1846): file the bytes of one Paperless document (fetched over the API or read from an export ZIP) into r's
    workspace: the same file already there = 'dup', else the mapping of r (tags / folder / sender / type) and docs_ingest =
    'new'; either way one pl_imported row (ws, src, pl_id). text() = the document's text (only asked for a new one)."""
    from ..docs.ingest import docs_ingest
    ws, pid = r["ws"], int(doc["id"])
    sha = hashlib.sha256(data).hexdigest()
    asn = doc.get("archive_serial_number") if isinstance(doc.get("archive_serial_number"), int) else None
    same = c.execute("SELECT node_id FROM pl_imported WHERE ws=? AND sha256=? AND node_id IS NOT NULL LIMIT 1", (ws, sha)).fetchone() or \
        c.execute("""SELECT n.id FROM fs_versions v JOIN fs_nodes n ON n.id=v.node_id AND n.cur_version=v.no AND n.deleted_at IS NULL
                     JOIN doc_meta d ON d.node_id=n.id AND d.ws=? WHERE v.sha256=? LIMIT 1""", (ws, sha)).fetchone()
    if same:
        c.execute("INSERT INTO pl_imported(ws,src,pl_id,org_id,node_id,sha256,asn,dup,created_at) VALUES(?,?,?,?,?,?,?,1,?) "
                  "ON CONFLICT DO NOTHING", (ws, src, pid, r["org_id"], same[0], sha, asn, _now()))
        return "dup"
    mp = pl_mapping(c, r)
    tags, folder = [], None
    for t in doc.get("tags") or []:
        m = mp["tags"].get(str(t)) or {"to": "tag", "name": labels["tags"].get(t, "")}
        name = (m.get("name") or labels["tags"].get(t, "")).strip()
        if not name or m.get("to") == "skip":
            continue
        if m.get("to") == "folder":
            folder = folder or name
        elif name not in tags:
            tags.append(name)
    meta = {"ext_id": f"pl:{src}:{pid}", "date": _day(doc.get("created") or doc.get("created_date")), "tags": tags, "text": text()}
    money = monetary_value(doc, fields)
    if money:                                # 2.98.0 D (#2178): amount only from a monetary field, due date stays empty
        meta["amount"], meta["currency"] = money[0], money[1] or ""
    for key, kind, field in (("senders", "correspondents", "correspondent"), ("types", "document_types", "document_type")):
        lid = doc.get(field)
        if isinstance(lid, int):
            m = mp[key].get(str(lid))
            name = labels[kind].get(lid, "") if m is None else m
            if name:
                meta["sender" if key == "senders" else "type"] = name
    title = str(doc.get("title") or "").strip()
    orig = str(doc.get("original_file_name") or fname or "").strip()
    ext = ("." + orig.rsplit(".", 1)[1][:8]) if "." in orig else (".pdf" if mime == "application/pdf" else "")
    name = (title + ext if title and not title.lower().endswith(ext.lower()) else title) or orig or f"paperless-{pid}{ext}"
    nid = docs_ingest(c, uid, r["org_id"], name[:200], data, mime or None, "paperless", meta)
    if doc.get("custom_fields"):  # 2.153.0 (#2179): Paperless' custom fields as fields of the document
        from ..docs.fields import df_from_paperless
        df_from_paperless(c, ws, nid, doc, fields, uid)
    if folder:
        node = c.execute("SELECT * FROM fs_nodes WHERE id=?", (nid,)).fetchone()
        fid = S.folder_by_name(c, node, uid, folder)
        if fid:
            S.move_to_folder(c, node, fid)
    c.execute("INSERT INTO pl_imported(ws,src,pl_id,org_id,node_id,sha256,asn,dup,created_at) VALUES(?,?,?,?,?,?,?,0,?) "
              "ON CONFLICT DO NOTHING", (ws, src, pid, r["org_id"], nid, sha, asn, _now()))
    return "new"


# ---- the run ------------------------------------------------------------------------------------------------------------
def pl_target(c, r):
    """2.87.9 (#1940): the row the documents of r's current run are filed with: r itself, or -- run_ws = the starter's own
    private space ("Rather into private" from an organisation's connection / export) -- a copy with that workspace (no
    organisation) and r's mapping opened with r's key. None when run_ws is anything else (never someone else's space)."""
    tw = r["run_ws"] or ""
    if not tw or tw == r["ws"]:
        return r
    if not r["run_by"] or tw != S.doc_ws(None, r["run_by"]):
        return None
    t = dict(r)
    t.update(ws=tw, org_id=None, _map=pl_mapping(c, r))
    return t


def pl_run_target(c, uid, org, ws, raw):
    """2.87.9 (#1940): the run_ws an import start asks for: '' (the workspace itself) or, from an organisation, the starter's
    own private space (target 'private'). Anything else is refused: an import only ever goes into the workspace it belongs
    to or into the starter's own space."""
    if raw in (None, "", "same") or raw == ws:
        return ""
    if raw == "private" and org:
        return S.doc_ws(None, uid)
    if raw == "private":
        return ""
    raise Denied(400, tr("Invalid value: {0}", "target"))


def pl_may_import(c, uid, org_id):
    """May uid (still) import into this workspace: an organisation's admin / the person themself."""
    u = c.execute("SELECT disabled FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    if not u or u["disabled"]:
        return False
    from ..agents.core import is_agent
    if is_agent(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()):
        return False
    if org_id:
        from ..accounts.orgs import is_org_admin
        return bool(is_org_admin(c, uid, org_id))
    return True


def _set(c, sid, **kw):
    kw["run_beat"] = _now()
    c.execute("UPDATE pl_sources SET " + ", ".join(f"{k}=?" for k in kw) + " WHERE id=?", (*kw.values(), sid))


class PlLost(Exception):
    """2.81.0 (#1875): the run lost its claim (no heartbeat for PL_STALE minutes: queued again, maybe taken by another process,
    or discarded) -- it ends at once and writes nothing more."""


def pl_beat(c, table, rid, own, **kw):
    """2.81.0 (#1875): the heartbeat of a run (+ kw) only while it still holds its claim: the row is busy / stop with the beat
    this run wrote last (own[0], the claim's at first); else PlLost. A long document no longer lets a second run in parallel.
    The caller commits right after it (a rollback would bring back an older beat than own[0])."""
    b = _now()
    n = c.execute(f"UPDATE {table} SET " + "".join(f"{k}=?, " for k in kw) + "run_beat=? WHERE id=? AND run_state IN ('busy','stop') "
                  "AND run_beat=?", (*kw.values(), b, rid, own[0])).rowcount
    if not n:
        raise PlLost()
    own[0] = b


def _stopped(c, sid):
    r = c.execute("SELECT run_state FROM pl_sources WHERE id=?", (sid,)).fetchone()
    return not r or r[0] == "stop"


def pl_run(c, sid):
    """One import run of connection sid (claimed: run_state 'busy'). kind 'all' = every document (oldest first), 'new' =
    newest first until a page holds nothing new. Commits after every document."""
    from ..admin.hosting import QuotaExceeded
    from ..docs.ingest import docs_kick as kick
    r = c.execute("SELECT * FROM pl_sources WHERE id=?", (sid,)).fetchone()
    uid = r["run_by"]
    if not pl_may_import(c, uid, r["org_id"]):
        _set(c, sid, run_state="", run_error="owner", follow=0, error="owner")
        c.commit()
        return
    tok = pl_token(c, r)
    t = pl_target(c, r)  # 2.87.9 (#1940): where the documents go (the connection's workspace or the starter's private space)
    if t is None:
        _set(c, sid, run_state="", run_error="owner", run_ws="")
        c.commit()
        return
    own = [r["run_beat"]]  # 2.81.0 (#1875): the claim's beat; every later write checks it is still this run's
    counts = {"new": 0, "skip": 0, "dup": 0, "fail": 0, "done": 0}
    since, full = _now(), None  # 2.69.0 B (#1847): learn.py takes the documents of this run at its end
    try:
        full = {k: pl_labels(c, r["url"], tok, k) for k in ("tags", "correspondents", "document_types")}
        labels = {k: {x["id"]: x["name"] for x in full[k]} for k in full}
        fields = pl_fields(c, r["url"], tok)
        order = "id" if r["run_kind"] == "all" else "-id"
        page, stop = 1, False
        while not stop:
            j = pl_get(c, r["url"], tok, f"/api/documents/?ordering={order}&page_size={PL_PAGE}&page={page}")
            if not isinstance(j, dict) or not isinstance(j.get("results"), list):
                raise PlError("answer")
            if page == 1 and r["run_kind"] == "all":
                pl_beat(c, "pl_sources", sid, own, run_total=int(j.get("count") or 0))
                c.commit()
            fresh = 0
            for doc in j["results"]:
                if not isinstance(doc, dict) or not isinstance(doc.get("id"), int):
                    continue
                if _stopped(c, sid):
                    stop = True
                    break
                pl_beat(c, "pl_sources", sid, own)  # 2.81.0 (#1875): before the document; the beat after it guards its filing
                c.commit()
                try:
                    with c.savepoint():
                        res = pl_import_doc(c, t, uid, tok, doc, labels, fields)
                except PlError as e:
                    if e.code in ("auth", "network", "key", "blocked", "version"):
                        raise
                    res = "fail"
                except (Denied, ValueError, QuotaExceeded) as e:
                    print("paperless: document refused", doc.get("id"), type(e).__name__, flush=True)
                    res = "fail"
                    if isinstance(e, QuotaExceeded):
                        counts["fail"] += 1
                        raise PlError("quota") from None
                counts[res if res in counts else "fail"] += 1
                counts["done"] += 1
                fresh += res == "new"
                pl_beat(c, "pl_sources", sid, own, run_done=counts["done"], run_new=counts["new"], run_skip=counts["skip"] + counts["dup"],
                        run_fail=counts["fail"])
                c.commit()
                if res == "new":
                    kick()
            if not j.get("next") or (r["run_kind"] != "all" and not fresh):
                break
            page += 1
        pl_beat(c, "pl_sources", sid, own, run_state="", synced_at=_now(), error="", run_error="")
    except PlLost:  # 2.81.0 (#1875): another run has it now (or nobody): nothing more from this one
        c.rollback()
        print("paperless: run lost its claim", sid, flush=True)
        return
    except PlError as e:
        c.rollback()
        try:
            pl_beat(c, "pl_sources", sid, own, run_state="", run_error=e.stored(), error=e.stored(), synced_at=_now())
        except PlLost:
            c.rollback()
            return
    if full is not None:  # 2.69.0 B (#1847): rules + learning once per run, also after a stop / a full storage
        from .learn import pll_finish
        res = pll_finish(c, t["ws"], t["org_id"], uid, pl_src(r["url"]), since, full, pl_mapping(c, t))
        if r["run_kind"] == "all":  # the app shows the summary of a full import; a follow-up run keeps it
            from .learn import pll_stored
            _set(c, sid, run_learn=pll_stored(res))
    c.commit()


def pl_claim(c):
    """The run this process takes now (queued, a run cut off, a follow that is due): ('url', pl_sources.id) | ('zip',
    pl_uploads.id), or None. 2.69.0 A (#1846): one import per server at a time -- across all processes (the advisory lock
    serializes the claim, a fresh busy / stop run of either table blocks it); the others wait in the order they were queued
    (run_beat), a run cut off (no heartbeat for PL_STALE minutes) goes back to the queue and never blocks it for good."""
    from .zipimp import plh_sweep
    stale = iso(now_utc() - timedelta(minutes=PL_STALE))
    c.execute("UPDATE pl_sources SET run_state='queued' WHERE run_state='busy' AND (run_beat IS NULL OR run_beat < ?)", (stale,))
    c.execute("UPDATE pl_sources SET run_state='' WHERE run_state='stop' AND (run_beat IS NULL OR run_beat < ?)", (stale,))
    for r in c.execute("SELECT id, every_min, synced_at, created_by FROM pl_sources WHERE follow=1 AND run_state='' AND token<>''").fetchall():
        last = parse_iso(r["synced_at"]) if r["synced_at"] else None
        if not last or now_utc() - last >= timedelta(minutes=int(r["every_min"] or 15)):
            c.execute("UPDATE pl_sources SET run_state='queued', run_kind='new', run_by=?, run_total=0, run_done=0, run_new=0, run_skip=0, "
                      "run_fail=0, run_error='', run_ws='', run_beat=? WHERE id=? AND run_state=''", (r["created_by"], _now(), r["id"]))
    plh_sweep(c, stale)
    c.commit()
    write_lock(c, "paperless-queue")
    if c.execute("SELECT 1 FROM pl_sources WHERE run_state IN ('busy','stop') UNION ALL "
                 "SELECT 1 FROM pl_uploads WHERE run_state IN ('busy','stop') LIMIT 1").fetchone():
        c.commit()
        return None
    x = c.execute("""SELECT 'url' AS k, id, run_beat FROM pl_sources WHERE run_state='queued' UNION ALL
                     SELECT 'zip' AS k, id, run_beat FROM pl_uploads WHERE run_state='queued' ORDER BY run_beat, k, id LIMIT 1""").fetchone()
    if x:
        c.execute(f"UPDATE {'pl_sources' if x['k'] == 'url' else 'pl_uploads'} SET run_state='busy', run_beat=? WHERE id=?", (_now(), x["id"]))
    c.commit()
    return (x["k"], x["id"]) if x else None


def plh_queue_place(c, table, rid):
    """2.69.0 A (#1846): the place of a waiting run in the server's queue (1 = next), None when it does not wait."""
    r = c.execute(f"SELECT run_state, run_beat FROM {table} WHERE id=?", (rid,)).fetchone()
    if not r or r["run_state"] != "queued":
        return None
    with system_ctx(c):  # the queue spans every workspace of the server: only a count of the runs ahead, nothing of them
        b = r["run_beat"] or ""
        ahead = sum(c.execute(f"SELECT COUNT(*) FROM {t} WHERE run_state='queued' AND COALESCE(run_beat,'') < ?", (b,)).fetchone()[0]
                    for t in ("pl_sources", "pl_uploads"))
        ahead += c.execute(f"SELECT COUNT(*) FROM {table} WHERE run_state='queued' AND COALESCE(run_beat,'') = ? AND id < ?", (b, rid)).fetchone()[0]
    return int(ahead or 0) + 1


def pl_run_once():
    c = connect()
    try:
        with system_ctx(c):  # paperless worker: the import of every workspace's connection; the right of run_by is checked in pl_run
            from .zipimp import plh_check_one
            if plh_check_one(c):  # 2.81.0 (#1874): an uploaded export left unchecked (a restart) is checked before the claim
                return 1
            x = pl_claim(c)
            if not x:
                return 0
            kind, sid = x
            if kind == "zip":  # 2.69.0 A (#1846): an uploaded export (it never raises)
                from .zipimp import plh_zip_run
                plh_zip_run(c, sid)
                return 1
            try:
                pl_run(c, sid)
            except Exception as e:  # noqa: BLE001 -- the worker never dies on one run
                c.rollback()
                print("paperless: run", sid, type(e).__name__, e, flush=True)
                _set(c, sid, run_state="", run_error="failed", error="failed")
                c.commit()
        return 1
    finally:
        c.close()


def _loop():
    from ..accounts.session import GATE
    time.sleep(1)
    while True:
        n = 0
        try:
            with GATE.bg():
                n = pl_run_once()
        except Exception as e:  # noqa: BLE001 -- the worker never dies
            print("paperless: worker", type(e).__name__, e, flush=True)
        if not n:
            _WAKE.wait(PL_IDLE)
            _WAKE.clear()


def pl_kick():
    """Wake the worker (start it when it does not run yet)."""
    if not bg_here():  # 2.193.0 D (#2220): role web -- the worker runs the queue from its table
        return
    with _LOCK:
        if _W["thread"] is None or not _W["thread"].is_alive():
            _W["thread"] = threading.Thread(target=_loop, daemon=True, name="paperless")
            _W["thread"].start()
    _WAKE.set()


@app.before_request
def _pl_start():
    if _W["thread"] is None:  # 2.69.0 A (#1846): also on a hosted server
        pl_kick()
