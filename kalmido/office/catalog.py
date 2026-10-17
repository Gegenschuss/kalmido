"""2.76.0 (#1023): the pack catalogue -- country packs (kind country, office/packs.py) and industry packs (kind industry,
office/sheet.py) from a catalogue the operator sets up (env KALMIDO_PACKS_CATALOG = https://.../index.json), installed per
office area (office_org: an organisation or a person's own office). Empty variable = only the packs shipped with the app,
no network at all.

Security model:
 - the only network call: the index and the pack files, through the SSRF guard of the calendar subscriptions (cal_http:
   every resolved address checked, redirects by hand, never https -> http, size limit, timeout). https only; http and
   internal addresses only for hosts in KALMIDO_PACKS_ALLOW_HOSTS (an internal mirror)
 - the index is checked strictly; texts are cleaned (control characters, tags); invalid entries are skipped one by one
 - a pack file must match its catalogue entry (SHA-256 of the raw bytes, size, code, kind, version, min_app) and pass the
   validator of the built-in packs (data only, no markup); it is stored as data in office_pack_installs (org_id = the
   office area, row-level security) and never runs
 - resolution: office_settings(c, oid) binds the area (pkc_bind); office_pack / dk_pack then see the active installations
   of exactly that area first, then the built-in files. Without a binding only the built-in packs exist
 - finalised documents keep their own snapshot (ledger.ofx_finalize: + pack_sha256, pack_source); an update or an
   uninstall never changes them
 - routes: session only (office_gate refuses agent tokens and kids), read = any member of the area, write = its admin."""
import hashlib
import json
import os
import re
import time
import urllib.parse
from contextvars import ContextVar

from flask import g, has_request_context, jsonify, request

from ..core.config import APP_VERSION, app
from ..core.db import body, db, err, iso, now_utc
from ..core.i18n import N_, lg_base, tr
from ..core.pg import insert_id, write_lock
from ..core.access import Denied
from ..calendars.subscriptions import CalError, cal_allow_parse, cal_host_allowed, cal_http, cal_norm_url
from .packs import PACK_DIR, office_pack, office_pack_validate
from .model import office_gate, office_org, office_role, office_settings
from .sheet import IND_DIR, dk_pack, dk_pack_validate

PKC_URL = os.environ.get("KALMIDO_PACKS_CATALOG", "").strip()
PKC_ALLOW_ENV = os.environ.get("KALMIDO_PACKS_ALLOW_HOSTS", "")
PKC_INDEX_MAX = 1024 * 1024       # bytes of the index
PKC_ENTRIES_MAX = 500             # packs in the index
PKC_VERSIONS_MAX = 20             # versions per pack
PKC_PACK_MAX = 512 * 1024         # bytes of a pack file
PKC_TIMEOUT = 10                  # s per fetch
PKC_TTL = 3600                    # s the index stays in the process cache
PKC_ERR_TTL = 60                  # s a failed fetch is not repeated (the refresh button always fetches)
PKC_KINDS = ("country", "industry")
PKC_LEN = {"name": 80, "description": 1000, "changes": 500, "author": 120, "license": 120}

PKC_E_OFF = N_("No catalogue is set up")
PKC_E_NET = N_("The catalogue is not reachable right now")
PKC_E_BAD = N_("The catalogue could not be read")
PKC_E_CHECK = N_("The pack failed the check")
PKC_E_COMMUNITY = N_("Community packs need your confirmation")
PKC_E_UNKNOWN = N_("This pack is not in the catalogue")
PKC_E_NOT_INST = N_("This pack is not installed")
PKC_E_BUILTIN = N_("Built-in packs cannot be removed")
PKC_E_OTHER = N_("Another version of this pack is installed")
PKC_E_USE_COUNTRY = N_("This pack is the country pack of this office. Choose another one first.")
PKC_E_USE_RULES = N_("This pack is switched on in the calculation rules. Switch it off first.")
PKC_E_USE_OFFERS = N_("{0} open quotations use this pack.")

_CODE = {"country": re.compile(r"^[A-Z]{2}$"), "industry": re.compile(r"^[a-z][a-z0-9_]{1,30}$")}
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_VER_RE = re.compile(r"^\d{1,4}(?:\.\d{1,4}){0,3}$")
_TAG_RE = re.compile(r"<[^>]*>")
_CTRL_LINE = re.compile(r"[\x00-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")
_CTRL_TEXT = re.compile(r"[\x00-\x09\x0b-\x1f\x7f-\x9f​-‏‪-‮⁦-⁩]")  # keeps line breaks
_IDX = {}          # url -> {"at", "entries", "skipped", "fetched_at", "error"}
_PARSED = {}       # (org_id, sha256) -> the pack dict of an installation (data of that area only)
_BUILTIN_SHA = {}  # path -> sha256 of a built-in pack file
_BOUND = ContextVar("pkc_bound", default=None)  # outside requests (background work): (oid, {(kind, code): inst})


# ---------------------------------------------------------------- helpers
def pkc_allow():
    """Hosts that may be internal and may use http:// (KALMIDO_PACKS_ALLOW_HOSTS, format of the calendar allow list)."""
    return frozenset(cal_allow_parse(PKC_ALLOW_ENV)[0])


def pkc_code(kind, code):
    """A normalised pack code of kind, or None."""
    if kind not in PKC_KINDS or not isinstance(code, str):
        return None
    code = code.strip().upper() if kind == "country" else code.strip().lower()
    return code if _CODE[kind].match(code) else None


def pkc_ver(s):
    """'2.76.0' -> (2, 76, 0), or None."""
    s = str(s or "").strip()
    return tuple(int(x) for x in s.split(".")) if _VER_RE.match(s) else None


def pkc_url_ok(u, allow=None):
    """A pack / index address we may fetch: https, or http for a host on the allow list. -> the url or None."""
    u = cal_norm_url(u) if isinstance(u, str) and not u.lower().startswith("webcal") else None
    if not u:
        return None
    p = urllib.parse.urlsplit(u)
    if p.scheme == "https":
        return u
    allow = pkc_allow() if allow is None else allow
    return u if p.scheme == "http" and cal_host_allowed(allow, p.hostname, p.port or 80) else None


def pkc_host(u):
    p = urllib.parse.urlsplit(u or "")
    return (p.hostname or "")[:120]


def _line(v, n):
    if not isinstance(v, str):
        return ""
    return re.sub(r"\s+", " ", _CTRL_LINE.sub(" ", _TAG_RE.sub("", v))).strip()[:n]


def _para(v, n):
    if not isinstance(v, str):
        return ""
    s = _CTRL_TEXT.sub("", _TAG_RE.sub("", v.replace("\r\n", "\n").replace("\r", "\n")))
    return re.sub(r"\n{3,}", "\n\n", s).strip()[:n]


def _i18n(v, n, para=False):
    """A text of the index: "text" or {de, en} -> {de, en} cleaned (missing language = the other one)."""
    f = _para if para else _line
    if isinstance(v, str):
        t = f(v, n)
        return {"de": t, "en": t}
    if not isinstance(v, dict):
        return {"de": "", "en": ""}
    de, en = f(v.get("de"), n), f(v.get("en"), n)
    return {"de": de or en, "en": en or de}


def _lang():
    return "de" if lg_base() == "de" else "en"


def _pick(d, lg=None):
    d = d or {}
    return d.get(lg or _lang()) or d.get("en") or d.get("de") or ""


def _clean_pack_texts(d):
    """Control characters out of every text of a pack (in place; line breaks stay). Markup is refused by the validators."""
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, str):
                d[k] = _CTRL_TEXT.sub("", v)
            else:
                _clean_pack_texts(v)
    elif isinstance(d, list):
        for i, v in enumerate(d):
            if isinstance(v, str):
                d[i] = _CTRL_TEXT.sub("", v)
            else:
                _clean_pack_texts(v)
    return d


def pkc_validate(kind, d):
    """The validator of the built-in packs of kind -> list of problems."""
    return office_pack_validate(d) if kind == "country" else dk_pack_validate(d)


# ---------------------------------------------------------------- the index
def pkc_index_parse(d, allow=None):
    """A downloaded index -> (entries, skipped). Strict: every entry is checked on its own; a bad one is skipped."""
    if not isinstance(d, dict) or d.get("format") != 1 or not isinstance(d.get("packs"), list):
        raise ValueError("format")
    allow = pkc_allow() if allow is None else allow
    out, seen, skipped = [], set(), 0
    for e in d["packs"]:
        if len(out) >= PKC_ENTRIES_MAX:
            skipped += 1
            continue
        x = _entry(e, allow)
        if not x or (x["kind"], x["code"]) in seen:
            skipped += 1
            continue
        seen.add((x["kind"], x["code"]))
        out.append(x)
    return out, skipped


def _entry(e, allow):
    if not isinstance(e, dict):
        return None
    kind = e.get("kind")
    code = pkc_code(kind, e.get("code")) if isinstance(e.get("code"), str) and e.get("code") == e.get("code").strip() else None
    if not code or code != e.get("code"):
        return None
    name = _i18n(e.get("name"), PKC_LEN["name"])
    if not name["en"]:
        return None
    hp = e.get("homepage")
    hp = hp if isinstance(hp, str) and urllib.parse.urlsplit(hp.strip()).scheme == "https" and cal_norm_url(hp.strip()) else ""
    vs = []
    for v in e.get("versions") if isinstance(e.get("versions"), list) else []:
        if len(vs) >= PKC_VERSIONS_MAX:
            break
        if not isinstance(v, dict):
            continue
        n, url, sha, size = v.get("version"), v.get("url"), v.get("sha256"), v.get("size")
        if not isinstance(n, int) or isinstance(n, bool) or n < 1 or n > 10 ** 6:
            continue
        if not isinstance(url, str) or not pkc_url_ok(url, allow):
            continue
        if not isinstance(sha, str) or not _SHA_RE.match(sha.lower()):
            continue
        if size is not None and (not isinstance(size, int) or isinstance(size, bool) or size < 1 or size > PKC_PACK_MAX):
            continue
        ma = v.get("min_app")
        if ma not in (None, "") and not pkc_ver(ma):
            continue
        rel = v.get("released") if isinstance(v.get("released"), str) and _DATE_RE.match(v.get("released")) else ""
        if any(o["version"] == n for o in vs):
            continue
        vs.append({"version": n, "url": url.strip(), "sha256": sha.lower(), "size": size or 0, "released": rel,
                   "min_app": str(ma or ""), "changes": _i18n(v.get("changes"), PKC_LEN["changes"], para=True)})
    if not vs:
        return None
    vs.sort(key=lambda v: -v["version"])
    return {"kind": kind, "code": code, "name": name, "description": _i18n(e.get("description"), PKC_LEN["description"], para=True),
            "author": _line(e.get("author"), PKC_LEN["author"]), "license": _line(e.get("license"), PKC_LEN["license"]),
            "verified": e.get("verified") is True, "homepage": hp.strip(), "versions": vs}


def _fetch(url, max_bytes):
    """GET through the SSRF guard -> raw bytes. CalError on any failure."""
    allow = pkc_allow()
    if not pkc_url_ok(url, allow):
        raise CalError("config")
    st, _, data, _final = cal_http(url, headers={"Accept": "application/json"}, allow=allow, cross_redirects=True,
                                   max_bytes=max_bytes, timeout=PKC_TIMEOUT, deadline=PKC_TIMEOUT)
    if st != 200:
        raise CalError("http", st)
    return data


def pkc_index(force=False):
    """The catalogue (cached 1 h per process): {configured, source, fetched_at, error, skipped, entries}. Never raises."""
    if not PKC_URL:
        return {"configured": False, "source": "", "fetched_at": None, "error": None, "skipped": 0, "entries": []}
    cur = _IDX.get(PKC_URL)
    age = time.monotonic() - cur["at"] if cur else None
    if force or not cur or age > (PKC_ERR_TTL if cur["error"] else PKC_TTL):
        new = {"at": time.monotonic(), "entries": [], "skipped": 0, "fetched_at": None, "error": None}
        try:
            raw = _fetch(PKC_URL, PKC_INDEX_MAX)
            new["entries"], new["skipped"] = pkc_index_parse(json.loads(raw.decode("utf-8")))
            new["fetched_at"] = iso(now_utc())
        except CalError:
            new["error"] = PKC_E_NET
        except (ValueError, UnicodeDecodeError, RecursionError):
            new["error"] = PKC_E_BAD
        if new["error"] and cur and not cur["error"]:  # keep the last good list, show the failure
            new.update(entries=cur["entries"], skipped=cur["skipped"], fetched_at=cur["fetched_at"])
        _IDX[PKC_URL] = cur = new
    return {"configured": True, "source": pkc_host(PKC_URL), "fetched_at": cur["fetched_at"],
            "error": tr(cur["error"]) if cur["error"] else None, "skipped": cur["skipped"], "entries": cur["entries"]}


def _entry_of(idx, kind, code):
    return next((e for e in idx["entries"] if e["kind"] == kind and e["code"] == code), None)


def _latest(e):
    """The highest version this app may install (min_app <= the running version), or None."""
    app_v = pkc_ver(APP_VERSION) or (0,)
    return next((v for v in (e or {}).get("versions") or [] if not v["min_app"] or pkc_ver(v["min_app"]) <= app_v), None)


# ---------------------------------------------------------------- binding: the installations of one office area
def _parsed(oid, sha, kind, data):
    k = (int(oid), sha)
    if k not in _PARSED:
        try:
            d = json.loads(data)
        except (TypeError, ValueError):
            d = None
        _PARSED[k] = d if d is not None and not pkc_validate(kind, d) else None
    return _PARSED[k]


def pkc_rows(c, oid):
    return c.execute("SELECT * FROM office_pack_installs WHERE org_id=? AND removed_at IS NULL ORDER BY id", (oid,)).fetchall()


def pkc_bind(c, oid):
    """Binds office area oid: office_pack / dk_pack see its active installations from now on (this request; outside a
    request this context until pkc_unbind). Called by office_settings, so every caller that reads the settings of an
    area resolves that area's packs and never the ones of another area."""
    cache = g.setdefault("pkc_cache", {}) if has_request_context() else {}
    if oid not in cache:
        m = {}
        if oid:
            for r in pkc_rows(c, oid):
                d = _parsed(oid, r["sha256"], r["kind"], r["data"])
                if d:
                    m[(r["kind"], r["code"])] = {"pack": d, "sha256": r["sha256"], "source": r["source"], "badge": r["badge"],
                                                 "version": r["version"], "row": r}
        cache[oid] = m
    val = (oid, cache[oid])
    if has_request_context():
        g.pkc_bound = val
    else:
        _BOUND.set(val)
    return cache[oid]


def pkc_unbind():
    """Drops the binding (background work after one area)."""
    if has_request_context():
        g.pop("pkc_bound", None)
    _BOUND.set(None)


def _forget(oid):
    if has_request_context():
        g.setdefault("pkc_cache", {}).pop(oid, None)
        if (g.get("pkc_bound") or (None,))[0] == oid:
            g.pop("pkc_bound", None)


def _bound():
    v = g.get("pkc_bound") if has_request_context() else _BOUND.get()
    return (v or (None, {}))[1]


def pkc_installed(kind, code):
    """The pack dict of an active installation in the bound area, or None (used by office_pack / dk_pack)."""
    inst = _bound().get((kind, code))
    return inst["pack"] if inst else None


def pkc_codes(kind):
    """The codes installed in the bound area."""
    return {k[1] for k in _bound() if k[0] == kind}


def _builtin_path(kind, code):
    return os.path.join(PACK_DIR, code.lower() + ".json") if kind == "country" else os.path.join(IND_DIR, code + ".json")


def _builtin(kind, code):
    return office_pack(code, builtin=True) if kind == "country" else dk_pack(code, builtin=True)


def _builtin_codes(kind):
    d = PACK_DIR if kind == "country" else IND_DIR
    if not os.path.isdir(d):
        return []
    out = []
    for f in sorted(os.listdir(d)):
        code = pkc_code(kind, f[:-5]) if f.endswith(".json") else None
        if code and _builtin(kind, code):
            out.append(code)
    return out


def pkc_origin(kind, code):
    """(sha256, source) of the pack office_pack / dk_pack resolves for code right now: an installation of the bound area
    (its SHA-256, the catalogue host) or the built-in file (the SHA-256 of its bytes, "builtin")."""
    code = pkc_code(kind, code) or ""
    inst = _bound().get((kind, code))
    if inst:
        return inst["sha256"], inst["source"] or "catalogue"
    p = _builtin_path(kind, code) if code else ""
    if p and os.path.isfile(p):
        if p not in _BUILTIN_SHA:
            with open(p, "rb") as f:
                _BUILTIN_SHA[p] = hashlib.sha256(f.read()).hexdigest()
        return _BUILTIN_SHA[p], "builtin"
    return "", "builtin"


# ---------------------------------------------------------------- what the client sees
def _uname(c, uid):
    if not uid:
        return ""
    r = c.execute("SELECT display_name, username FROM users WHERE id=?", (uid,)).fetchone()
    return (r["display_name"] or r["username"]) if r else ""


def _inst_public(c, r):
    return {"version": r["version"], "badge": r["badge"], "installed_at": r["installed_at"],
            "installed_by_name": _uname(c, r["installed_by"]), "source": r["source"]}


def pkc_in_use(c, oid, kind, code):
    """Why the installation of code may not be removed right now ("" = free). Only when no built-in pack takes over."""
    if _builtin(kind, code):
        return ""
    s = office_settings(c, oid)
    if kind == "country":
        return tr(PKC_E_USE_COUNTRY) if s.get("pack") == code else ""
    if code in (s.get("industry_packs") or []):
        return tr(PKC_E_USE_RULES)
    from ..core.orgcrypt import oc_dec_fields
    docs = set()
    for r in c.execute("SELECT p.* FROM office_doc_parts p JOIN office_docs d ON d.id=p.doc_id WHERE p.org_id=? AND d.org_id=? "
                       "AND p.kind='shoot' AND d.kind='offer' AND d.locked_at IS NULL", (oid, oid)).fetchall():
        try:
            sh = json.loads(oc_dec_fields(c, oid, "office_doc_parts", r).get("sheet") or "{}")
        except (TypeError, ValueError):
            sh = {}
        if isinstance(sh, dict) and (sh.get("pack") or "film") == code:
            docs.add(r["doc_id"])
    return tr(PKC_E_USE_OFFERS, len(docs)) if docs else ""


def _builtin_item(kind, code):
    p = _builtin(kind, code)
    if kind == "country":
        return {"name": {"de": p["name"], "en": p.get("name_en") or p["name"]}, "version": p["version"]}
    return {"name": {"de": p["name"]["de"], "en": p["name"]["en"]}, "version": p["version"]}


def pkc_item(c, oid, kind, code, idx, rows=None):
    """One element of GET /api/office/catalog (see docs/PACKS.md)."""
    lg = _lang()
    e = _entry_of(idx, kind, code)
    rows = pkc_rows(c, oid) if rows is None else rows
    r = next((x for x in rows if x["kind"] == kind and x["code"] == code), None)
    meta = {}
    if r:
        try:
            meta = json.loads(r["meta"] or "{}")
        except ValueError:
            meta = {}
    b = _builtin_item(kind, code) if _builtin(kind, code) else None
    name = (e or {}).get("name") or meta.get("name") or (b or {}).get("name") or {}
    lt = _latest(e)
    if r:
        badge, cur = r["badge"], r["version"]
    else:
        badge, cur = "verified" if b or (e and e["verified"]) else "community", (b or {}).get("version")
    in_use = pkc_in_use(c, oid, kind, code) if r else ""
    return {"kind": kind, "code": code, "name": _pick(name, lg) or code,
            "description": _pick((e or meta).get("description"), lg), "author": (e or meta).get("author") or "",
            "license": (e or meta).get("license") or "", "homepage": (e or meta).get("homepage") or "",
            "badge": badge, "builtin": bool(b),
            "latest": {"version": lt["version"], "size": lt["size"], "released": lt["released"], "changes": _pick(lt["changes"], lg)} if lt else None,
            "installed": _inst_public(c, r) if r else None,
            "update": bool(lt and cur is not None and lt["version"] > cur),
            "in_use": bool(in_use), "in_use_text": in_use}


def pkc_catalog(c, uid, oid, q="", kind="", force=False):
    idx = pkc_index(force=force)
    rows = pkc_rows(c, oid)
    keys = []
    for k in PKC_KINDS:
        if kind and kind != k:
            continue
        keys += [(k, x) for x in _builtin_codes(k)]
        keys += [(r["kind"], r["code"]) for r in rows if r["kind"] == k]
        keys += [(e["kind"], e["code"]) for e in idx["entries"] if e["kind"] == k]
    items, seen = [], set()
    q = (q or "").strip().lower()[:100]
    for k in keys:
        if k in seen:
            continue
        seen.add(k)
        it = pkc_item(c, oid, k[0], k[1], idx, rows)
        if q and not any(q in str(it.get(f) or "").lower() for f in ("code", "name", "description", "author")):
            continue
        items.append(it)
    items.sort(key=lambda it: (0 if it["installed"] or it["builtin"] else 1, it["name"].lower(), it["kind"], it["code"]))
    return {"configured": idx["configured"], "source": idx["source"], "fetched_at": idx["fetched_at"], "error": idx["error"],
            "skipped": idx["skipped"], "can_manage": office_role(c, uid, oid) == "admin", "items": items}


def pkc_packs_extra(c, oid):
    """GET /api/office/packs: (source, badge) per country code + the industry list (built-in + installed of the area)."""
    pkc_bind(c, oid)
    b = _bound()
    country = {code: ("installed", b[("country", code)]["badge"]) if ("country", code) in b else ("builtin", "verified")
               for code in set(_builtin_codes("country")) | pkc_codes("country")}
    ind = []
    for code in sorted(set(_builtin_codes("industry")) | pkc_codes("industry")):
        p = dk_pack(code)
        if p:
            inst = b.get(("industry", code))
            ind.append({"code": code, "name": p["name"]["de"], "name_en": p["name"]["en"], "version": p["version"],
                        "badge": inst["badge"] if inst else "verified", "source": "installed" if inst else "builtin"})
    return country, ind


# ---------------------------------------------------------------- routes
def _ctx(admin=False):
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=admin)
    return c, uid, oid


@app.get("/api/office/catalog")
def pkc_catalog_get():
    """?q=&kind=country|industry -> the catalogue merged with the built-in and installed packs of my office area."""
    c, uid, oid = _ctx()
    kind = request.args.get("kind") or ""
    return jsonify(pkc_catalog(c, uid, oid, request.args.get("q") or "", kind if kind in PKC_KINDS else ""))


@app.post("/api/office/catalog/refresh")
def pkc_catalog_refresh():
    """Office admin: fetch the index again (the answer as GET)."""
    c, uid, oid = _ctx(admin=True)
    b = body()
    b = b if isinstance(b, dict) else {}
    kind = b.get("kind") or ""
    return jsonify(pkc_catalog(c, uid, oid, str(b.get("q") or ""), kind if kind in PKC_KINDS else "", force=True))


def _fail(problems):
    return jsonify(error=tr(PKC_E_CHECK), problems=problems[:20]), 422


@app.post("/api/office/packs/install")
def pkc_install():
    """Office admin: {kind, code, version, accept_community} -> installs (or updates to) that version of a catalogue pack in
    my office area. 400 input, 404 not in the catalogue / no catalogue, 409 community without confirmation, 422 the check
    failed (checksum, size, schema, markup, code / kind / version, min_app), 502 the catalogue is not reachable."""
    c, uid, oid = _ctx(admin=True)
    b = body()
    if not isinstance(b, dict):
        return err(tr("Invalid data"))
    kind = b.get("kind")
    code = pkc_code(kind, b.get("code"))
    ver = b.get("version")
    if not code or not isinstance(ver, int) or isinstance(ver, bool) or ver < 1:
        return err(tr("Invalid data"))
    if not PKC_URL:
        return err(tr(PKC_E_OFF), 404)
    idx = pkc_index()
    e = _entry_of(idx, kind, code)
    v = next((x for x in (e or {}).get("versions") or [] if x["version"] == ver), None)
    if not v and not idx["error"]:  # a pack published since the last fetch
        idx = pkc_index(force=True)
        e = _entry_of(idx, kind, code)
        v = next((x for x in (e or {}).get("versions") or [] if x["version"] == ver), None)
    if not v:
        return err(idx["error"], 502) if idx["error"] and not idx["entries"] else err(tr(PKC_E_UNKNOWN), 404)
    try:
        raw = _fetch(v["url"], PKC_PACK_MAX)
    except CalError as ex:
        if ex.code == "too_large":
            return _fail([f"size: more than {PKC_PACK_MAX} bytes"])
        return err(tr(PKC_E_NET), 502)
    problems = []
    sha = hashlib.sha256(raw).hexdigest()
    if sha != v["sha256"]:
        problems.append("sha256: does not match the catalogue")
    if v["size"] and len(raw) != v["size"]:
        problems.append("size: does not match the catalogue")
    if problems:
        return _fail(problems)
    try:
        d = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        return _fail(["pack: not JSON"])
    if not isinstance(d, dict):
        return _fail(["pack must be an object"])
    _clean_pack_texts(d)
    problems = pkc_validate(kind, d)
    if d.get("code") != code:
        problems.append("code: does not match the catalogue")
    if kind == "industry" and d.get("kind") != "industry" or kind == "country" and d.get("kind") not in (None, "country"):
        problems.append("kind: does not match the catalogue")
    if d.get("version") != ver:
        problems.append("version: does not match the catalogue")
    if v["min_app"] and pkc_ver(v["min_app"]) > (pkc_ver(APP_VERSION) or (0,)):
        problems.append(f"min_app: needs Kalmido {v['min_app']}")
    if problems:
        return _fail(problems)
    badge = "verified" if e["verified"] and d.get("community") is not True else "community"
    if badge == "community" and b.get("accept_community") is not True:
        return jsonify(error=tr(PKC_E_COMMUNITY), badge=badge), 409
    meta = {"name": e["name"], "description": e["description"], "author": e["author"], "license": e["license"],
            "homepage": e["homepage"], "changes": v["changes"], "released": v["released"]}
    source = pkc_host(PKC_URL)
    write_lock(c, f"office_packs_{int(oid)}")
    ts = iso(now_utc())
    c.execute("UPDATE office_pack_installs SET removed_at=? WHERE org_id=? AND kind=? AND code=? AND removed_at IS NULL", (ts, oid, kind, code))
    insert_id(c, "INSERT INTO office_pack_installs(org_id, kind, code, version, sha256, data, meta, badge, source, installed_at, installed_by) "
                 "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
              (oid, kind, code, ver, sha, json.dumps(d, ensure_ascii=False), json.dumps(meta, ensure_ascii=False), badge, source, ts, uid))
    from .ledger import ofx_log
    ofx_log(c, oid, "pack_install", target="pack", detail={"kind": kind, "code": code, "version": ver, "sha256": sha, "badge": badge, "source": source})
    c.commit()
    _forget(oid)
    rows = pkc_rows(c, oid)
    r = next(x for x in rows if x["kind"] == kind and x["code"] == code)
    return jsonify(ok=True, installed=_inst_public(c, r), item=pkc_item(c, oid, kind, code, idx, rows))


def _kc(kind, code):
    code = pkc_code(kind, code)
    if not code:
        raise Denied(404)
    return kind, code


@app.delete("/api/office/packs/installed/<kind>/<code>")
def pkc_uninstall(kind, code):
    """Office admin: removes the installation (removed_at; restore = the undo). 409 while something depends on it."""
    c, uid, oid = _ctx(admin=True)
    kind, code = _kc(kind, code)
    write_lock(c, f"office_packs_{int(oid)}")
    r = c.execute("SELECT * FROM office_pack_installs WHERE org_id=? AND kind=? AND code=? AND removed_at IS NULL", (oid, kind, code)).fetchone()
    if not r:
        if _builtin(kind, code):
            return err(tr(PKC_E_BUILTIN), 400)
        return err(tr(PKC_E_NOT_INST), 404)
    why = pkc_in_use(c, oid, kind, code)
    if why:
        return err(why, 409)
    c.execute("UPDATE office_pack_installs SET removed_at=? WHERE id=? AND org_id=?", (iso(now_utc()), r["id"], oid))
    from .ledger import ofx_log
    ofx_log(c, oid, "pack_remove", target="pack", detail={"kind": kind, "code": code, "version": r["version"], "sha256": r["sha256"]})
    c.commit()
    _forget(oid)
    return jsonify(ok=True)


@app.post("/api/office/packs/installed/<kind>/<code>/restore")
def pkc_restore(kind, code):
    """Office admin: the undo of an uninstall -- the latest removed installation becomes active again (409 when another
    one is active by now)."""
    c, uid, oid = _ctx(admin=True)
    kind, code = _kc(kind, code)
    write_lock(c, f"office_packs_{int(oid)}")
    if c.execute("SELECT 1 FROM office_pack_installs WHERE org_id=? AND kind=? AND code=? AND removed_at IS NULL", (oid, kind, code)).fetchone():
        return err(tr(PKC_E_OTHER), 409)
    r = c.execute("SELECT * FROM office_pack_installs WHERE org_id=? AND kind=? AND code=? AND removed_at IS NOT NULL "
                  "ORDER BY removed_at DESC, id DESC LIMIT 1", (oid, kind, code)).fetchone()
    if not r:
        return err(tr(PKC_E_NOT_INST), 404)
    c.execute("UPDATE office_pack_installs SET removed_at=NULL WHERE id=? AND org_id=?", (r["id"], oid))
    from .ledger import ofx_log
    ofx_log(c, oid, "pack_install", target="pack", detail={"kind": kind, "code": code, "version": r["version"], "sha256": r["sha256"],
                                                          "badge": r["badge"], "source": r["source"], "restore": True})
    c.commit()
    _forget(oid)
    r = c.execute("SELECT * FROM office_pack_installs WHERE id=?", (r["id"],)).fetchone()
    return jsonify(ok=True, installed=_inst_public(c, r))
