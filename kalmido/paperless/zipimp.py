"""2.69.0 A (#1846): the import of a Paperless-ngx export (document_exporter, as a ZIP) uploaded into a workspace -- for a
Paperless-ngx that Kalmido cannot reach (Tailnet, VPN, a login in front of it). Hosted and self-hosted servers alike; no
network connection and no token. The same preview with the mapping and the same filing of every document as the import
over the API (ngx.plh_store), the same queue (ngx.pl_claim: one import per server at a time).

- Upload: in parts of PLH_CHUNK bytes (POST /api/paperless/zip announces the size, PUT .../part/<n> sends them in order; the
  last part may be sent again). At most PLH_ZIP_MAX bytes; a full storage refuses the upload. One upload per workspace; it
  belongs to that workspace and the person who uploads it (only they see its preview and start it; the managers of the
  workspace may stop or discard it).
- Storage: every part is sealed on its own (the workspace's key: an organisation's key when its encryption is on, for a
  person's own space the key derived from the server key) in PLH_DIR/<id>/, folders 0700, files 0600, outside the attachments
  (not in the backups). The parts go right after the run (done, stopped, failed, cut off) or when the upload is discarded; an
  upload without a run for PLH_ORPHAN_H hours and folders without their row are cleared by the worker.
- The ZIP is never unpacked onto the disk: zipfile reads the members straight from the sealed parts, only manifest.json /
  <name>-manifest.json (--split-manifest) and the files the manifest names. Limits: entries, manifest bytes, the size of every
  file (MAX_FILE_MB), the compression ratio (zip bombs), JSON depth; encrypted ZIPs are refused, a ZIP inside is only a file.
- Never twice: src = PLH_SRC (one key for every export) + the Paperless id, skipped only when the file is the same (sha256);
  the checksum within the workspace catches the rest (another instance's document with the same id is still imported).
"""
import hashlib
import io
import json
import os
import re
import shutil
import time
import zipfile
from datetime import datetime, timedelta

from flask import jsonify, request

from ..core.config import app, DB, MAX_FILE_MB, TZ
from ..core.db import body, db, err, iso, now_utc
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..accounts.session import me
from ..docs import store as S
from . import ngx as P


def _env_mb(name, default):
    try:
        return max(1, int(os.environ.get(name, "") or default))
    except ValueError:
        return default


PLH_DIR = os.environ.get("KALMIDO_PAPERLESS_ZIP_DIR", os.path.join(os.path.dirname(DB), "paperless-zip"))
PLH_ZIP_MAX = _env_mb("KALMIDO_PAPERLESS_ZIP_MAX_MB", 4096) * 1024 * 1024  # bytes of one uploaded ZIP
PLH_CHUNK = max(64 * 1024, min(_env_mb("KALMIDO_PAPERLESS_ZIP_CHUNK_KB", 8192) * 1024,  # bytes per part (tests: small parts)
                                MAX_FILE_MB * 4 * 1024 * 1024 - 256 * 1024))  # below MAX_CONTENT_LENGTH
PLH_MANIFEST_MAX = 64 * 1024 * 1024  # bytes of all manifests together
PLH_ENTRIES_MAX = 500_000            # members of the ZIP
PLH_DOCS_MAX = 200_000               # documents in the manifest
PLH_RATIO = 200                      # uncompressed / compressed of a member above 1 MB: more = a zip bomb
PLH_ORPHAN_H = 24                    # hours an upload without a run stays
PLH_DISK_MARGIN = 1024 * 1024 * 1024  # bytes that stay free on the disk of PLH_DIR besides an upload
PLH_SRC = P.pl_src("paperless-export")  # pl_imported.src of every ZIP import (not an address: no clash with pl_src(url))
_CTX = b"pl_uploads.part|"
_SWEPT = [0.0]
_MIME_RE = re.compile(r"[a-z0-9][a-z0-9.+-]{0,60}/[a-z0-9][a-z0-9.+-]{0,60}")

P.PL_ERR.update({
    "zip_bad": N_("This is not a ZIP file or it is damaged"),
    "zip_encrypted": N_("Encrypted ZIP files cannot be imported"),
    "zip_manifest": N_("No Paperless-ngx export found in the ZIP (manifest.json is missing or cannot be read)"),
    "zip_large": N_("The ZIP holds too many entries or a too large manifest"),
    "zip_bomb": N_("The ZIP holds a file that unpacks to far more than its size"),
    "zip_gone": N_("The uploaded file is no longer there: upload it again"),
})


class PlhError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _now():
    return iso(now_utc())


# ---- storage of the parts ---------------------------------------------------------------------------------------------
def _key(c, ws):
    """The key the parts of ws are sealed with (None: stored plain, like an organisation's files with the encryption off)."""
    from ..core.orgcrypt import oc_active
    if S.ws_org(ws) and not oc_active(c):
        return None
    return S._ws_key(c, ws)


def _dir(uid_):
    return os.path.join(PLH_DIR, str(int(uid_)))


def _part_path(rid, n):
    return os.path.join(_dir(rid), f"part-{int(n):06d}")


def _write_part(c, r, n, data):
    from ..core.orgcrypt import oc_seal_k
    os.makedirs(PLH_DIR, mode=0o700, exist_ok=True)
    os.makedirs(_dir(r["id"]), mode=0o700, exist_ok=True)
    key = _key(c, r["ws"])
    blob = oc_seal_k(key, S.ws_org(r["ws"]) or 0, data, _CTX + r["ws"].encode()) if key else bytes(data)
    path = _part_path(r["id"], n)
    tmp = f"{path}.tmp-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def plh_drop_files(rid):
    shutil.rmtree(_dir(rid), ignore_errors=True)


class _Parts(io.RawIOBase):
    """The uploaded ZIP as one seekable file over its sealed parts (one part opened at a time)."""

    def __init__(self, c, r):
        super().__init__()
        self._rid, self._ws, self._size, self._chunk = r["id"], r["ws"], int(r["got"]), int(r["chunk"]) or PLH_CHUNK
        self._key = _key(c, r["ws"])
        self._pos, self._cur = 0, (-1, b"")

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, off, whence=0):
        self._pos = max(0, off if whence == 0 else self._pos + off if whence == 1 else self._size + off)
        return self._pos

    def _part(self, i):
        if self._cur[0] != i:
            from ..core.orgcrypt import MAGIC, OrgCryptError, oc_open_k
            try:
                with open(_part_path(self._rid, i), "rb") as f:
                    raw = f.read()
                if raw[:len(MAGIC)] == MAGIC:
                    if self._key is None:
                        raise PlhError("zip_gone")
                    raw = oc_open_k(self._key, raw, _CTX + self._ws.encode())
            except (OSError, OrgCryptError):
                raise PlhError("zip_gone") from None
            self._cur = (i, raw)
        return self._cur[1]

    def readinto(self, b):
        if self._pos >= self._size:
            return 0
        i = self._pos // self._chunk
        data = self._part(i)
        o = self._pos - i * self._chunk
        n = min(len(b), len(data) - o, self._size - self._pos)
        if n <= 0:
            raise PlhError("zip_gone")
        b[:n] = data[o:o + n]
        self._pos += n
        return n


def _open_zip(c, r):
    try:
        return zipfile.ZipFile(io.BufferedReader(_Parts(c, r), 1024 * 1024))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, EOFError, OSError):
        raise PlhError("zip_bad") from None


def _read(zf, info, limit, code="too_large"):
    """The bytes of one member: never more than limit, never a member with a suspicious ratio or encrypted."""
    if info.flag_bits & 0x1:
        raise PlhError("zip_encrypted")
    if info.file_size > limit:
        raise PlhError(code)
    if info.file_size > 1024 * 1024 and info.file_size > PLH_RATIO * max(1, info.compress_size):
        raise PlhError("zip_bomb")
    try:
        with zf.open(info) as f:
            data = f.read(limit + 1)
    except (zipfile.BadZipFile, NotImplementedError, RuntimeError, ValueError, EOFError, OSError, zipfile.LargeZipFile):
        raise PlhError("zip_bad") from None
    if len(data) > limit:
        raise PlhError(code)
    return data


# ---- the export's manifest ----------------------------------------------------------------------------------------------
_VALUE = {"string": "value_text", "url": "value_url", "date": "value_date", "boolean": "value_bool", "integer": "value_int",
          "float": "value_float", "monetary": "value_monetary", "documentlink": "value_document_ids", "select": "value_select",
          "longtext": "value_long_text"}


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _created(v):
    """The day of a document: Paperless-ngx before 2.16 exports created as a UTC time -> the day in the server's time zone."""
    v = str(v or "")[:40]
    if "T" in v:
        try:
            t = datetime.fromisoformat(v.replace("Z", "+00:00"))
            if t.tzinfo:
                return t.astimezone(TZ).date().isoformat()
        except ValueError:
            pass
    return v[:10]


def _label(rec, f):
    """A tag / correspondent / document type in the shape of ngx.pl_labels (+ Paperless' matching for learn.py: part B's
    pl_label_match when it is there)."""
    lm = getattr(P, "pl_label_match", None)  # 2.69.0: comes with part B
    if lm:
        return {"id": rec["pk"], "name": str(f.get("name") or "")[:S.NAME_MAX], "count": 0, **lm(f)}
    algo = _int(f.get("matching_algorithm"))
    return {"id": rec["pk"], "name": str(f.get("name") or "")[:S.NAME_MAX], "count": 0, "match": str(f.get("match") or "")[:1000],
            "algo": algo if algo is not None else 0, "insens": bool(f.get("is_insensitive"))}


def plh_scan(zf):
    """Reads the manifest(s) of the export: {labels: {tags, correspondents, document_types: [label]}, fields: {id: {name, type,
    options}}, docs: {pk: doc in the API's shape + member, mime}}. Raises PlhError."""
    infos = zf.infolist()
    if len(infos) > PLH_ENTRIES_MAX:
        raise PlhError("zip_large")
    if any(i.flag_bits & 0x1 for i in infos):
        raise PlhError("zip_encrypted")
    names = {i.filename: i for i in infos if not i.is_dir()}
    mans = sorted((n for n in names if n.rsplit("/", 1)[-1] == "manifest.json"), key=lambda n: (n.count("/"), n))
    if not mans:
        raise PlhError("zip_manifest")
    prefix = mans[0][:-len("manifest.json")]
    parts = [mans[0]] + sorted(n for n in names if n.startswith(prefix) and n.endswith("-manifest.json"))  # --split-manifest
    if sum(names[n].file_size for n in parts) > PLH_MANIFEST_MAX:
        raise PlhError("zip_large")
    recs = []
    for n in parts:
        try:
            j = json.loads(_read(zf, names[n], PLH_MANIFEST_MAX, "zip_large"))
        except (ValueError, RecursionError):
            raise PlhError("zip_manifest") from None
        if not isinstance(j, list):
            raise PlhError("zip_manifest")
        recs.extend(x for x in j if isinstance(x, dict) and isinstance(x.get("fields"), dict) and _int(x.get("pk")) is not None)
    labels = {"tags": {}, "correspondents": {}, "document_types": {}}
    kinds = {"documents.tag": "tags", "documents.correspondent": "correspondents", "documents.documenttype": "document_types"}
    fields, docs, notes, values = {}, {}, {}, {}
    for x in recs:
        m, f = str(x.get("model") or ""), x["fields"]
        if m in kinds:
            labels[kinds[m]][x["pk"]] = _label(x, f)
        elif m == "documents.customfield":
            ed = f.get("extra_data") if isinstance(f.get("extra_data"), dict) else {}
            opts = ed.get("select_options") if isinstance(ed.get("select_options"), list) else []
            fields[x["pk"]] = {"name": str(f.get("name") or "")[:S.NAME_MAX], "type": str(f.get("data_type") or ""), "options": opts}
        elif m == "documents.note" and _int(f.get("document")) is not None and not f.get("deleted_at"):
            t = str(f.get("note") or "").strip()
            if t:
                notes.setdefault(f["document"], []).append(t)
        elif m == "documents.customfieldinstance" and _int(f.get("document")) is not None and _int(f.get("field")) is not None:
            values.setdefault(f["document"], []).append(f)
        elif m == "documents.document" and not f.get("deleted_at"):
            if len(docs) >= PLH_DOCS_MAX:
                raise PlhError("zip_large")
            fn = x.get("__exported_file_name__")
            member = prefix + fn if isinstance(fn, str) and fn and prefix + fn in names else None
            mime = str(f.get("mime_type") or "").lower()
            docs[x["pk"]] = {"id": x["pk"], "title": str(f.get("title") or "")[:500], "content": str(f.get("content") or "")[:P.PL_TEXT_MAX],
                             "created": _created(f.get("created")), "correspondent": _int(f.get("correspondent")),
                             "document_type": _int(f.get("document_type")),
                             "tags": [t for t in (f.get("tags") or []) if _int(t) is not None][:500] if isinstance(f.get("tags"), list) else [],
                             "archive_serial_number": _int(f.get("archive_serial_number")),
                             "original_file_name": str(f.get("original_filename") or (fn if isinstance(fn, str) else "") or "")[-200:].rsplit("/", 1)[-1],
                             "member": member, "mime": mime if _MIME_RE.fullmatch(mime) else "",
                             "size": names[member].file_size if member else 0}
    for pk, d in docs.items():
        d["notes"] = notes.get(pk, [])[:200]
        cf = []
        for f in values.get(pk, []):
            col = _VALUE.get((fields.get(f["field"]) or {}).get("type"))
            v = f.get(col) if col else None
            if v is None:
                v = next((f[k] for k in _VALUE.values() if f.get(k) is not None), None)
            cf.append({"field": f["field"], "value": v})
        d["custom_fields"] = cf
        for key, field in (("correspondents", "correspondent"), ("document_types", "document_type")):
            if d[field] in labels[key]:
                labels[key][d[field]]["count"] += 1
        for t in d["tags"]:
            if t in labels["tags"]:
                labels["tags"][t]["count"] += 1
    return {"labels": {k: sorted(v.values(), key=lambda x: (x["name"].lower(), x["id"])) for k, v in labels.items()},
            "fields": fields, "docs": docs}


def _check(c, r):
    """After the last part: is it an export? Keeps what the preview needs (sealed); state ready | bad."""
    try:
        with _open_zip(c, r) as zf:
            x = plh_scan(zf)
        info = {"labels": x["labels"], "docs": [[pk, d["size"], bool(d["member"])] for pk, d in sorted(x["docs"].items())]}
        c.execute("UPDATE pl_uploads SET state='ready', info=?, error='', updated_at=? WHERE id=?",
                  (S._jseal(c, r["ws"], "pl_uploads.info", info), _now(), r["id"]))
    except PlhError as e:
        plh_drop_files(r["id"])
        c.execute("UPDATE pl_uploads SET state='bad', error=?, updated_at=? WHERE id=?", (e.code, _now(), r["id"]))


def _info(c, r):
    return S._jopen(c, r["ws"], "pl_uploads.info", r["info"], {}) if r["info"] else {}


# ---- the size and the storage quota -----------------------------------------------------------------------------------
def plh_space(c, uid, need, exact):
    """{need, exact, free (None = no limit), fits: yes | maybe | no} -- maybe = an estimate above the free space (a warning,
    the import may start), no = full, or an exact size above the free space."""
    from ..admin.hosting import quota_info
    q = quota_info(c, uid) or {}
    free = max(0, q["limit"] - q["used"]) if q.get("limit") else None
    fits = "yes"
    if free is not None:
        if free <= 0:
            fits = "no"
        elif need is not None and need > free:
            fits = "no" if exact else "maybe"
    return {"need": need, "exact": bool(exact), "free": free, "fits": fits}


def plh_size_url(c, r, tok, left):
    """About how many bytes `left` documents of a connection need: the mean original_size of up to 10 of the newest
    documents (/api/documents/<id>/metadata/) times left. None when Paperless-ngx tells no size."""
    if left <= 0:
        return 0
    try:
        j = P.pl_get(c, r["url"], tok, "/api/documents/?ordering=-id&page_size=10")
        sizes = []
        for d in (j.get("results") if isinstance(j, dict) and isinstance(j.get("results"), list) else [])[:10]:
            if isinstance(d, dict) and _int(d.get("id")) is not None:
                m = P.pl_get(c, r["url"], tok, f"/api/documents/{d['id']}/metadata/")
                if isinstance(m, dict) and _int(m.get("original_size")) is not None and m["original_size"] >= 0:
                    sizes.append(m["original_size"])
    except P.PlError:
        return None
    return int(sum(sizes) / len(sizes) * left) if sizes else None


# ---- the run ------------------------------------------------------------------------------------------------------------
def _zset(c, rid, **kw):
    kw["run_beat"] = _now()
    c.execute("UPDATE pl_uploads SET " + ", ".join(f"{k}=?" for k in kw) + " WHERE id=?", (*kw.values(), rid))


def _zstopped(c, rid):
    r = c.execute("SELECT run_state FROM pl_uploads WHERE id=?", (rid,)).fetchone()
    return not r or r[0] == "stop"


def _learn(c, r, uid, since, labels):
    """learn.py of part B: rules + training from what came in (an empty dict without it)."""
    try:
        from .learn import pll_finish  # 2.69.0: learn.py comes with part B
    except ImportError:
        pll_finish = None
    if not pll_finish:
        return {}
    try:
        return pll_finish(c, r["ws"], r["org_id"], uid, PLH_SRC, since, labels, P.pl_mapping(c, r)) or {}
    except Exception as e:  # noqa: BLE001 -- learning never fails the import
        print("paperless: zip learn", r["id"], type(e).__name__, flush=True)
        return {}


def plh_zip_run(c, rid):
    """The run of upload rid (claimed: run_state 'busy'): every document of the export, oldest first; commits after every
    document; at the end (also stopped / full / failed) the parts go. Never raises."""
    from ..admin.hosting import QuotaExceeded
    from ..docs.ingest import docs_kick as kick
    r = c.execute("SELECT * FROM pl_uploads WHERE id=?", (rid,)).fetchone()
    if not r:
        return
    uid, since = r["run_by"], _now()
    counts = {"new": 0, "skip": 0, "dup": 0, "fail": 0, "done": 0}
    error, scan = "", None
    try:
        if not P.pl_may_import(c, uid, r["org_id"]):
            raise PlhError("owner")
        with _open_zip(c, r) as zf:
            scan = plh_scan(zf)
            labels = {k: {x["id"]: x["name"] for x in v} for k, v in scan["labels"].items()}
            docs = [scan["docs"][k] for k in sorted(scan["docs"])]
            _zset(c, rid, run_total=len(docs))
            c.commit()
            for d in docs:
                if _zstopped(c, rid):
                    break
                res = "fail"
                try:
                    if d["member"]:
                        data = _read(zf, zf.getinfo(d["member"]), MAX_FILE_MB * 1024 * 1024)
                        sha = hashlib.sha256(data).hexdigest()
                        if c.execute("SELECT 1 FROM pl_imported WHERE ws=? AND src=? AND pl_id=? AND sha256=?",
                                     (r["ws"], PLH_SRC, d["id"], sha)).fetchone():
                            res = "skip"
                        else:
                            with c.savepoint():
                                res = P.plh_store(c, r, uid, PLH_SRC, d, data, d["mime"] or None, d["original_file_name"], labels,
                                                  lambda d=d: P._doc_text(d, d["notes"], scan["fields"]))
                except PlhError as e:
                    if e.code == "zip_gone":  # the parts are gone: nothing more can come; a damaged member only fails its document
                        raise
                except QuotaExceeded:
                    raise PlhError("quota") from None
                except (Denied, ValueError) as e:
                    print("paperless: zip document refused", d["id"], type(e).__name__, flush=True)
                counts[res if res in counts else "fail"] += 1
                counts["done"] += 1
                _zset(c, rid, run_done=counts["done"], run_new=counts["new"], run_skip=counts["skip"] + counts["dup"], run_fail=counts["fail"])
                c.commit()
                if res == "new":
                    kick()
    except PlhError as e:
        c.rollback()
        error = e.code
    except Exception as e:  # noqa: BLE001 -- the worker never dies on one run
        c.rollback()
        print("paperless: zip run", rid, type(e).__name__, e, flush=True)
        error = "failed"
    learn = _learn(c, r, uid, since, scan["labels"]) if scan else {}
    plh_drop_files(rid)
    _zset(c, rid, run_state="", state="done", run_error=error, run_learn=json.dumps(learn, ensure_ascii=False)[:100_000] if learn else "",
          updated_at=_now())
    c.commit()


def plh_sweep(c, stale):
    """The worker's tidying (system context, before the claim): a ZIP run cut off goes back to the queue, a stop cut off ends;
    uploads without a run for PLH_ORPHAN_H hours go; folders without their row go (at most every 10 minutes)."""
    c.execute("UPDATE pl_uploads SET run_state='queued' WHERE run_state='busy' AND (run_beat IS NULL OR run_beat < ?)", (stale,))
    old = iso(now_utc() - timedelta(hours=PLH_ORPHAN_H))
    gone = [x[0] for x in c.execute("""SELECT id FROM pl_uploads WHERE (run_state='stop' AND (run_beat IS NULL OR run_beat < ?))
                                       OR (run_state='' AND state IN ('upload','ready','bad') AND updated_at < ?)""", (stale, old))]
    for rid in gone:
        plh_drop_files(rid)
        c.execute("UPDATE pl_uploads SET run_state='', state='done', updated_at=? WHERE id=? AND run_state IN ('', 'stop')", (_now(), rid))
    if time.time() - _SWEPT[0] > 600 and os.path.isdir(PLH_DIR):
        _SWEPT[0] = time.time()
        keep = {str(x[0]) for x in c.execute("SELECT id FROM pl_uploads WHERE state IN ('upload','ready') OR run_state<>''")}
        for n in os.listdir(PLH_DIR):
            if n not in keep:
                p = os.path.join(PLH_DIR, n)
                try:
                    if time.time() - os.path.getmtime(p) > 600:
                        shutil.rmtree(p, ignore_errors=True)
                except OSError:
                    pass


# ---- routes -------------------------------------------------------------------------------------------------------------
def _row(c, ws):
    return c.execute("SELECT * FROM pl_uploads WHERE ws=? ORDER BY id DESC LIMIT 1", (ws,)).fetchone()


def plh_public(c, ws, uid):
    """The upload of the workspace for the app (None: none). Only the uploader may continue / preview / start it."""
    r = _row(c, ws)
    if not r:
        return None
    from .web import _run_public
    run = _run_public(c, "pl_uploads", r, "all")
    return {"id": r["id"], "state": r["state"], "name": r["name"], "size": r["size"], "got": r["got"], "chunk": r["chunk"] or PLH_CHUNK,
            "next": r["parts"], "mine": r["created_by"] == uid, "error": r["error"], "error_text": P.pl_err_text(r["error"]), "run": run}


def _mine(c, raw, need_state=None):
    from .web import _gate, _ws
    _gate()
    uid, org, ws = _ws(c, raw)
    r = _row(c, ws)
    if not r or r["created_by"] != uid:
        raise Denied(404, tr("No uploaded Paperless-ngx export"))
    if need_state and r["state"] != need_state:
        raise Denied(409, tr("The upload is not ready for this"))
    return uid, org, ws, r


def _running(r):
    return r is not None and r["run_state"] in ("queued", "busy", "stop")


def _answer(c, ws, uid, org):
    from .web import _public
    return jsonify(_public(c, ws, uid, org))


@app.post("/api/paperless/zip")
def plh_zip_new():
    """{ws, size, name?} -- announces the upload of an export ZIP of `size` bytes (replaces an earlier upload of the same
    person in the workspace that does not run). 413 when it is larger than allowed or the storage is full."""
    from ..admin.hosting import QuotaExceeded, quota_info
    from .web import _gate, _ws
    _gate()
    c = db()
    d = body()
    uid, org, ws = _ws(c, d.get("ws"))
    size = d.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 22:
        return err(tr("Invalid value: {0}", "size"))
    if size > PLH_ZIP_MAX:
        return err(tr("The file is larger than {0} MB", PLH_ZIP_MAX // (1024 * 1024)), 413)
    q = quota_info(c, uid)
    if q and q["limit"] and q["used"] >= q["limit"]:
        raise QuotaExceeded(q)
    try:  # the parts lie on the server's disk until the run: keep a margin for everything else
        if shutil.disk_usage(os.path.dirname(PLH_DIR.rstrip(os.sep)) or "/").free < size + PLH_DISK_MARGIN:
            return err(tr("There is not enough space on the server for this upload right now"), 507)
    except OSError:
        pass
    name = d.get("name") if isinstance(d.get("name"), str) else ""
    name = re.sub(r"[\x00-\x1f\x7f/\\\\]", "", name).strip()[-120:]
    from ..core.pg import insert_id, write_lock
    write_lock(c, f"pl_uploads:{ws}")
    r = _row(c, ws)
    if r and (_running(r) or (r["created_by"] != uid and r["state"] in ("upload", "ready") and r["updated_at"] > iso(now_utc() - timedelta(hours=PLH_ORPHAN_H)))):
        return err(tr("Another import is under way in this area"), 409)
    for x in c.execute("SELECT id FROM pl_uploads WHERE ws=?", (ws,)).fetchall():
        plh_drop_files(x[0])
    c.execute("DELETE FROM pl_uploads WHERE ws=?", (ws,))
    ts = _now()
    rid = insert_id(c, "INSERT INTO pl_uploads(org_id, ws, created_by, state, name, size, chunk, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (org, ws, uid, "upload", name, size, PLH_CHUNK, ts, ts))
    c.commit()
    plh_drop_files(rid)  # a folder left over from an id of before (a restored database)
    return _answer(c, ws, uid, org)


@app.post("/api/paperless/zip/part")
def plh_zip_part():
    """multipart: ws, n (the part's number: the next one, or the last one again), part (the bytes: PLH_CHUNK, the last one
    less). After the last part the ZIP is checked (state ready | bad)."""
    from ..core.pg import write_lock
    c = db()
    uid, org, ws, r = _mine(c, request.form.get("ws"), "upload")
    write_lock(c, f"pl_uploads:{ws}")  # two sends of one part at once: one after the other
    r = c.execute("SELECT * FROM pl_uploads WHERE id=?", (r["id"],)).fetchone()
    if not r or r["state"] != "upload":
        raise Denied(409, tr("The upload is not ready for this"))
    try:
        n = int(request.form.get("n", ""))
    except ValueError:
        return err(tr("Invalid value: {0}", "n"))
    f = request.files.get("part")
    if f is None:
        return err(tr("Invalid value: {0}", "part"))
    data = f.read(int(r["chunk"]) + 1)
    chunk, got, parts = int(r["chunk"]), int(r["got"]), int(r["parts"])
    if n == parts - 1 and n >= 0:  # the last part once more (its answer was lost)
        got -= min(chunk, got - n * chunk)
        parts -= 1
    elif n != parts:
        return err(tr("Invalid value: {0}", "n"), 409)
    last = got + len(data) >= int(r["size"])
    if not data or len(data) > chunk or got + len(data) > int(r["size"]) or (not last and len(data) != chunk):
        return err(tr("Invalid value: {0}", "part"))
    try:
        _write_part(c, r, n, data)
    except OSError:
        return err(tr("The file could not be stored"), 507)
    c.execute("UPDATE pl_uploads SET got=?, parts=?, updated_at=? WHERE id=?", (got + len(data), n + 1, _now(), r["id"]))
    if last:
        _check(c, c.execute("SELECT * FROM pl_uploads WHERE id=?", (r["id"],)).fetchone())
    c.commit()
    return _answer(c, ws, uid, org)


def _rows(mp, labels):
    """The mapping rows of the preview (the same as ngx.pl_preview)."""
    out = {}
    for kind, key in (("tags", "tags"), ("correspondents", "senders"), ("document_types", "types")):
        rows = []
        for x in labels.get(kind) or []:
            m = mp[key].get(str(x["id"]))
            if key == "tags":
                m = m if isinstance(m, dict) and m.get("to") in ("tag", "folder", "skip") else {"to": "tag", "name": x["name"]}
                rows.append({**x, "to": m["to"], "target": str(m.get("name") or x["name"])[:S.NAME_MAX]})
            else:
                rows.append({**x, "to": "skip" if m == "" else "keep", "target": (m if isinstance(m, str) and m else x["name"])[:S.NAME_MAX]})
        out[key] = rows
    return out


def _left(c, r, info):
    """(documents, already imported, bytes of the rest) of an upload."""
    docs = info.get("docs") or []
    done = {x[0] for x in c.execute("SELECT pl_id FROM pl_imported WHERE ws=? AND src=?", (r["ws"], PLH_SRC))}
    already = sum(1 for d in docs if d[0] in done)
    return len(docs), already, sum(int(d[1]) for d in docs if d[0] not in done and d[2])


@app.get("/api/paperless/zip/preview")
def plh_zip_preview():
    """?ws= -- like /api/paperless/preview for the uploaded export, plus the exact size and the free storage."""
    c = db()
    uid, _org, ws, r = _mine(c, request.args.get("ws"), "ready")
    info = _info(c, r)
    count, already, need = _left(c, r, info)
    mp = P.pl_mapping(c, r)
    out = {"count": count, "already": already, "zip": True, **_rows(mp, info.get("labels") or {}), "size": plh_space(c, uid, need, True)}
    try:
        from .learn import pll_rules_preview  # 2.69.0: learn.py comes with part B
    except ImportError:
        pll_rules_preview = None
    if pll_rules_preview:
        try:
            out["rules"] = pll_rules_preview(info.get("labels") or {}, mp, c=c, ws=ws, src=PLH_SRC)
        except Exception as e:  # noqa: BLE001 -- the preview never fails on the rules
            print("paperless: zip rules preview", type(e).__name__, flush=True)
    return jsonify(out)


@app.post("/api/paperless/zip/import")
def plh_zip_start():
    """{ws, mapping?} -- saves the mapping and queues the import of the uploaded export (413 when it does not fit)."""
    from ..admin.hosting import fmt_bytes
    c = db()
    d = body()
    uid, org, ws, r = _mine(c, d.get("ws"), "ready")
    if _running(r):
        return err(tr("An import is already running"), 409)
    _count, _already, need = _left(c, r, _info(c, r))
    sp = plh_space(c, uid, need, True)
    if sp["fits"] == "no":
        return err(tr("The documents need {0}, but only {1} of storage is free", fmt_bytes(need), fmt_bytes(sp["free"] or 0)), 413)
    if "mapping" in d:
        # sealed in the context ngx.pl_mapping opens (the mapping has the same shape for both ways)
        c.execute("UPDATE pl_uploads SET mapping=? WHERE id=?", (S._jseal(c, ws, "pl_sources.mapping", P.pl_clean_mapping(d["mapping"])), r["id"]))
    c.execute("UPDATE pl_uploads SET run_state='queued', run_by=?, run_total=0, run_done=0, run_new=0, run_skip=0, run_fail=0, "
              "run_error='', run_learn='', run_beat=?, updated_at=? WHERE id=?", (uid, _now(), _now(), r["id"]))
    c.commit()
    P.pl_kick()
    return _answer(c, ws, uid, org)


@app.post("/api/paperless/zip/stop")
def plh_zip_stop():
    """{ws} -- a waiting run ends at once and its upload goes; a running one stops after the current document (what came
    in stays, the upload goes then)."""
    from .web import _gate, _ws
    _gate()
    c = db()
    uid, org, ws = _ws(c, body().get("ws"))
    r = _row(c, ws)
    if not r:
        raise Denied(404, tr("No uploaded Paperless-ngx export"))
    if r["run_state"] == "queued":
        plh_drop_files(r["id"])
        c.execute("DELETE FROM pl_uploads WHERE id=? AND run_state='queued'", (r["id"],))
    elif r["run_state"] == "busy":
        c.execute("UPDATE pl_uploads SET run_state='stop' WHERE id=? AND run_state='busy'", (r["id"],))
    c.commit()
    return _answer(c, ws, uid, org)


@app.delete("/api/paperless/zip")
def plh_zip_drop():
    """?ws= -- discards the upload of the workspace (not while its run waits or runs: stop it first)."""
    from .web import _gate, _ws
    _gate()
    c = db()
    uid, org, ws = _ws(c, request.args.get("ws"))
    r = _row(c, ws)
    if r:
        if _running(r):
            return err(tr("An import is already running"), 409)
        plh_drop_files(r["id"])
        c.execute("DELETE FROM pl_uploads WHERE id=?", (r["id"],))
        c.commit()
    return _answer(c, ws, uid, org)

