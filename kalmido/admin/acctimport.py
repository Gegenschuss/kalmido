"""2.73.0 B (#1473): account import -- takes over a file of the account export (admin/acctexport.py) on this server.

Flow (Settings > Data, people only):
    POST   /api/account/import                 {size, name} -> {id, chunk}: a new upload (quota + disk space checked first)
    PUT    /api/account/import/<id>?offset=n   the next piece (raw body, `chunk` bytes, the last one shorter); the file is
                                               sealed at rest like the export (0600, own folder of the person)
    GET    /api/account/import/<id>            state: upload | checking | preview (+ preview) | invalid (+ error) |
                                               running (+ progress) | done | stopped (+ result) | failed
    POST   /api/account/import/<id>/run        {target: "private" | org id, people: {key: {share, invite, email?}}} -> running
    DELETE /api/account/import/<id>            cancel: the upload is removed at once
Undo: POST /api/imports/<import id>/undo (integrations/importers.py imp_undo hands source "Kalmido" to umz_undo).

The check before the preview (umz_open): a ZIP without encryption, safe names (no absolute paths, no "..", no
backslashes, no duplicates), limits for entries, sizes and the compression ratio, the manifest (format, version) with the
SHA-256 of checksum.sha256, and every file of the manifest with its size and SHA-256; the JSON parts must be arrays of
objects. Nothing of the file is trusted as an id: every row is created anew, ids are mapped, owner / org / author
columns are set to the importing person and the chosen target, only columns this server has are taken, any other
column pointing at a row (*_id, *_by, foreign keys) is dropped unless it is mapped here. Sharing with a person found by
e-mail happens only for the people ticked in the preview; inviting a missing person needs an instance admin."""
import base64
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import struct
import threading
import time
import uuid
import zipfile
from datetime import datetime, timedelta

from flask import g, jsonify, request

from ..core.config import app, ATT_DIR, MAX_FILE_MB
from ..core.db import body, bump, connect, db, err, iso, now_utc, usettings, uset
from ..core.pg import insert_id, system_ctx
from ..core.i18n import lang, LANGS, N_, tr as _tr_base
from ..core.access import Denied, ROLES
from ..accounts.session import me
from ..lists.lists import LIST_COLOR_RE
from ..tasks.validation import (DATE_MAX_Y, DATE_MIN_Y, DURATION_MAX, PRIORITIES, REM_COUNT, REM_MAX, REM_MIN, rr_feasible, rr_norm,
                                rr_problem, valid_date, valid_hm, valid_plan_start)
from .orgexport import EXPORT_DIR, OX_SECRET_COLS
from .acctexport import (UMZ_BLOCK, UMZ_FORMAT, UMZ_HEAD, UMZ_V, UmzReader, UmzWriter, umz_key, umz_person, umz_space_ok,
                         umz_user_conn, umz_write_state)

UMZ_IN_DIR = os.path.join(EXPORT_DIR, "account-import")
UMZ_SOURCE = "Kalmido"  # imports.source of an account import (the list of recent imports shows it as it is)
UMZ_KEEP_H = 24  # an upload that is not used is removed after this


def _env_mb(name, dflt):
    try:
        v = int(os.environ.get(name, "").strip() or dflt)
    except ValueError:
        v = dflt
    return max(1, v)


UMZ_IMPORT_MAX_MB = _env_mb("KALMIDO_ACCOUNT_IMPORT_MAX_MB", 4096)
# one piece per request: 8 MB, never above the request limit, a whole number of sealed blocks
UMZ_CHUNK = max(UMZ_BLOCK, min(8 * UMZ_BLOCK, ((app.config.get("MAX_CONTENT_LENGTH") or 8 * UMZ_BLOCK) - 65536) // UMZ_BLOCK * UMZ_BLOCK))
UMZ_MAX_ENTRIES = 200_000
# review M2: the parsed rows take 5-10 times the text in memory -- a real export of 50 000 tasks stays far below these
UMZ_JSON_MAX = 32 * 1024 * 1024  # one data/<table>.json
UMZ_JSON_TOTAL = 96 * 1024 * 1024  # all data/*.json together (they are held in memory during the check and the run)
UMZ_MAX_ROWS = _env_mb("KALMIDO_ACCOUNT_IMPORT_MAX_ROWS", 500_000)  # rows of one table after parsing
UMZ_MANIFEST_MAX = 32 * 1024 * 1024
UMZ_RATIO = 200  # uncompressed / compressed of one entry above 1 MB
UMZ_TEXT_MAX = 1_000_000  # characters of one text value
UMZ_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._\-/]{0,250}")
UMZ_EID_RE = re.compile(r"[0-9a-f]{8,64}")
UMZ_UID_RE = re.compile(r"[A-Za-z0-9@._-]{1,200}")  # review N7: a contact uid taken from the file
# settings that move along (nothing about security, sign-in, push or connections)
UMZ_SETTINGS = ("lang", "allday_time", "default_reminder", "work_start", "work_end", "show_done_views", "show_done_new",
                "show_done_default", "group_order", "comment_order", "time_rounding", "time_currency", "capacity_h",
                "list_emoji", "side_icons", "prio_bg", "celebrate", "progress_subtasks", "hide_progress", "folders")
# columns never taken from a file, in addition to ids, *_id / *_by columns, foreign keys and OX_SECRET_COLS
UMZ_DROP = {
    "lists": {"is_inbox", "family", "agent_tidy", "agent_listen", "agent_members", "agent_peers", "agent_followup", "tidy_agent",
              "org_visibility", "org_edit", "git_folder_off", "icon"},
    "tasks": {"rotation", "approval", "fam", "tt_id", "nag_at", "wait_fired"},
    "comments": {"mentions", "suggestion", "choices", "choice", "ext_name"},
    "attachments": {"path", "enc_by"},
    "list_files": {"path"},
    "events": {"href"},
    "contacts": {"href"},
}

_UMI = {}  # user id -> running check / import thread
_UMI_LOCK = threading.Lock()
_PIECE_LOCK = threading.Lock()  # one piece at a time: two requests at the same offset must not both append
_L = threading.local()  # the language of the person a background thread works for


def tr(key, *a, lg=None):
    """core.i18n.tr in the language of the person a background thread works for (in a request: as usual)."""
    return _tr_base(key, *a, lg=lg or getattr(_L, "lg", None))


class UmzBad(Exception):
    """The file cannot be imported; the text (translatable) goes to the person."""

    def __init__(self, text, *a):
        super().__init__(text)
        self.text, self.args_ = text, a


class UmzStop(Exception):
    pass


# ---------------------------------------------------------------- the folder of an upload
def _base(uid):
    return os.path.join(UMZ_IN_DIR, str(int(uid)))


def _dir(uid, iid):
    if not re.fullmatch(r"[0-9a-f]{24}", str(iid or "")):
        raise Denied(404)
    return os.path.join(_base(uid), iid)


def _st(uid, iid):
    try:
        with open(os.path.join(_dir(uid, iid), "state.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _set(uid, iid, **kw):
    st = _st(uid, iid) or {}
    st.update(kw)
    umz_write_state(_dir(uid, iid), st)
    return st


def _busy(uid):
    t = _UMI.get(int(uid))
    return bool(t and t.is_alive())


def _need(uid, iid):
    st = _st(uid, iid)
    if not st:
        raise Denied(404)  # another person's upload is not even there for me (own folder per person)
    return st


def _drop(uid, iid):
    shutil.rmtree(_dir(uid, iid), ignore_errors=True)


def umz_import_cleanup():
    """Watchdog part (acctexport.umz_cleanup): uploads older than UMZ_KEEP_H hours, finished or cancelled ones."""
    n = 0
    if not os.path.isdir(UMZ_IN_DIR):
        return 0
    for d in os.listdir(UMZ_IN_DIR):
        p = os.path.join(UMZ_IN_DIR, d)
        if not d.isdigit() or not os.path.isdir(p) or _busy(int(d)):
            continue
        for iid in os.listdir(p):
            q = os.path.join(p, iid)
            try:
                old = time.time() - os.path.getmtime(os.path.join(q, "state.json")) > UMZ_KEEP_H * 3600
                with open(os.path.join(q, "state.json"), encoding="utf-8") as f:
                    st = json.load(f)
            except (OSError, ValueError):
                old, st = True, {}
            if old or st.get("state") in ("done", "stopped", "failed", "invalid"):
                shutil.rmtree(q, ignore_errors=True)
                n += 1
        if not os.listdir(p):
            os.rmdir(p)
    return n


# ---------------------------------------------------------------- reading + checking the file
def _safe_entry(name):
    return bool(UMZ_NAME_RE.fullmatch(name)) and ".." not in name.split("/") and "//" not in name and not name.endswith("/")


def _read_entry(zf, zi, limit, sha=None):
    if zi.file_size > limit:
        raise UmzBad(N_("The file contains a part that is too large: {0}"), zi.filename)
    h, out = hashlib.sha256(), bytearray()
    with zf.open(zi) as f:
        while True:
            b = f.read(1 << 20)
            if not b:
                break
            out += b
            h.update(b)
            if len(out) > limit:
                raise UmzBad(N_("The file contains a part that is too large: {0}"), zi.filename)
    if sha is not None and h.hexdigest() != sha:
        raise UmzBad(N_("Checksum wrong: {0}. The file is damaged or was changed."), zi.filename)
    return bytes(out)


def _json(raw, what):
    try:
        return json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise UmzBad(N_("The file contains a broken part: {0}"), what) from None


def umz_open(path, key, size, full=True):
    """-> (zipfile, manifest, files {path: entry}, data {table: rows}). UmzBad when anything is off. full: check every
    file's SHA-256 too (the preview; the run checks each file again while it reads it)."""
    try:
        r = UmzReader(path, key, size)
        zf = zipfile.ZipFile(r)
    except (zipfile.BadZipFile, ValueError, OSError, EOFError):
        raise UmzBad(N_("This is not a Kalmido export (no ZIP file).")) from None
    except Exception:  # noqa: BLE001 -- a sealed block that does not open (InvalidTag): the upload is damaged
        raise UmzBad(N_("The upload is damaged. Please upload the file again.")) from None
    try:
        infos = zf.infolist()
        if len(infos) > UMZ_MAX_ENTRIES:
            raise UmzBad(N_("The file has too many parts."))
        names, total = {}, 0
        for zi in infos:
            if zi.is_dir():
                continue
            if not _safe_entry(zi.filename):
                raise UmzBad(N_("The file contains a part with a forbidden name: {0}"), zi.filename[:120])
            if zi.filename in names:
                raise UmzBad(N_("The file contains a part twice: {0}"), zi.filename)
            if zi.flag_bits & 0x1:
                raise UmzBad(N_("The file is password protected. Use the export file as it came from Kalmido."))
            if zi.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
                raise UmzBad(N_("This is not a Kalmido export (no ZIP file)."))
            if zi.file_size > 1 << 20 and zi.file_size > UMZ_RATIO * max(1, zi.compress_size):
                raise UmzBad(N_("The file contains a part that is too large: {0}"), zi.filename)
            total += zi.file_size
            names[zi.filename] = zi
        if total > 2 * UMZ_IMPORT_MAX_MB * 1024 * 1024:
            raise UmzBad(N_("The file is too large (at most {0} MB)"), UMZ_IMPORT_MAX_MB)
        if "manifest.json" not in names:
            raise UmzBad(N_("This is not a Kalmido export (manifest.json is missing)."))
        mraw = _read_entry(zf, names["manifest.json"], UMZ_MANIFEST_MAX)
        if "checksum.sha256" not in names and b'"kalmido-org-export"' in mraw[:4096]:
            # an organisation export, opened with its recovery key (umz_unlock): its blocks were authenticated, every
            # entry carries its SHA-256 in the manifest
            man = _json(mraw, "manifest.json")
            if isinstance(man, dict) and man.get("format") == "kalmido-org-export":
                return (zf, *umz_org_open(zf, names, man, mraw, full))
        if "checksum.sha256" not in names:
            raise UmzBad(N_("This is not a Kalmido export (manifest.json is missing)."))
        sums = {}
        for line in _read_entry(zf, names["checksum.sha256"], UMZ_MANIFEST_MAX).decode("utf-8", "replace").splitlines():
            m = re.fullmatch(r"([0-9a-f]{64})\s+\*?(.+)", line.strip())
            if m:
                sums[m.group(2)] = m.group(1)
        if sums.get("manifest.json") != hashlib.sha256(mraw).hexdigest():
            raise UmzBad(N_("Checksum wrong: {0}. The file is damaged or was changed."), "manifest.json")
        man = _json(mraw, "manifest.json")
        if not isinstance(man, dict) or man.get("format") != UMZ_FORMAT:
            raise UmzBad(N_("This is not a Kalmido account export. An organisation export is imported by the organisation's admin."))
        if not isinstance(man.get("v"), int) or man["v"] > UMZ_V or man["v"] < 1:
            raise UmzBad(N_("This export comes from a newer Kalmido version. Update this server first."))
        if not isinstance(man.get("files"), list) or not isinstance(man.get("user"), dict):
            raise UmzBad(N_("The file contains a broken part: {0}"), "manifest.json")
        files = {}
        for f in man["files"]:
            if not isinstance(f, dict) or not isinstance(f.get("path"), str) or not isinstance(f.get("sha256"), str) \
                    or not isinstance(f.get("size"), int):
                raise UmzBad(N_("The file contains a broken part: {0}"), "manifest.json")
            p = f["path"]
            if p in files:
                raise UmzBad(N_("The file contains a part twice: {0}"), p[:120])
            zi = names.get(p)
            if zi is None:
                raise UmzBad(N_("A part of the file is missing: {0}"), p[:120])
            if zi.file_size != f["size"] or sums.get(p) not in (None, f["sha256"]):
                raise UmzBad(N_("Checksum wrong: {0}. The file is damaged or was changed."), p[:120])
            files[p] = (zi, f["sha256"])
        data = {}
        if sum(zi.file_size for p, (zi, _s) in files.items() if p.startswith("data/")) > UMZ_JSON_TOTAL:
            raise UmzBad(N_("The file contains a part that is too large: {0}"), "data/")
        for p, (zi, sha) in files.items():
            if p.startswith("data/") and p.endswith(".json") and "/" not in p[5:]:
                rows = _json(_read_entry(zf, zi, UMZ_JSON_MAX, sha), p)
                if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
                    raise UmzBad(N_("The file contains a broken part: {0}"), p)
                if len(rows) > UMZ_MAX_ROWS:
                    raise UmzBad(N_("The file contains a part that is too large: {0}"), p)
                data[p[5:-5]] = rows
            elif full:
                _read_entry(zf, zi, MAX_FILE_MB * 1024 * 1024 * 4, sha)
        return zf, man, files, data
    except UmzBad:
        zf.close()
        raise
    except (zipfile.BadZipFile, OSError, EOFError, ValueError, NotImplementedError, RuntimeError):
        zf.close()
        raise UmzBad(N_("The file contains a broken part: {0}"), "ZIP") from None


# 2.73.0 B (#1473, part 4): the parts of an organisation export (admin/orgexport.py OX_AREAS) that move along, under the
# table names of the account export; everything else of the archive is named in the preview as not taken over
UMZ_ORG_MAP = {
    "lists.json": "lists", "lists/sections.json": "sections", "lists/members.json": "list_members", "lists/fields.json": "list_fields",
    "lists/tags.json": "list_tags", "lists/status.json": "list_status", "lists/links.json": "list_links",
    "lists/milestones.json": "list_milestones", "lists/files.json": "list_files", "tasks.json": "tasks",
    "tasks/dependencies.json": "task_deps", "tasks/field_values.json": "task_field_values", "tasks/tags.json": "task_list_tags",
    "comments.json": "comments", "attachments.json": "attachments", "calendars.json": "event_calendars", "events.json": "events",
    "events/attendees.json": "event_attendees", "books.json": "address_books", "books/contacts.json": "contacts",
    "members.json": "members",
}
UMZ_ORG_SKIP = (  # archive prefix -> what the preview names as not taken over
    ("office/", N_("Office")), ("store/", N_("File store")), ("chat/", N_("Team chat")), ("wiki/", N_("Knowledge pages")),
    ("documents/", N_("Documents")), ("newsletter/", N_("Newsletter")), ("clients.json", N_("Clients")), ("hub/", N_("Absences and bookings")),
    ("lists/forms.json", N_("Forms")), ("lists/playbooks.json", N_("Playbooks")), ("lists/notes.json", N_("Project notes")),
    ("lists/notepads.json", N_("Notepads")), ("time_entries.json", N_("Time entries")),
    ("tasks/encrypted_notes.json", N_("Encrypted notes")), ("tasks/locked_notes.json", N_("Encrypted notes")),
)


def umz_org_open(zf, names, man, mraw, full):
    """-> (manifest, files, data) of an opened organisation export, in the shape of an account export."""
    from .orgexport import _safe_part
    fl = man.get("files")
    if man.get("format_version") != 1 or not isinstance(fl, dict) or not isinstance(man.get("org"), dict):
        raise UmzBad(N_("This export comes from a newer Kalmido version. Update this server first."))
    listed = set(fl) - {"manifest.json"}
    if set(names) - {"manifest.json"} != listed:
        raise UmzBad(N_("A part of the file is missing: {0}"), ", ".join(sorted(listed ^ (set(names) - {"manifest.json"})))[:120])
    files, data, skipped = {}, {}, {}
    total = sum(names[p].file_size for p in listed if p.endswith(".json"))
    if total > UMZ_JSON_TOTAL:
        raise UmzBad(N_("The file contains a part that is too large: {0}"), "*.json")
    for p in sorted(listed):
        f = fl[p]
        if not isinstance(f, dict) or not isinstance(f.get("sha256"), str):
            raise UmzBad(N_("The file contains a broken part: {0}"), "manifest.json")
        zi = names[p]
        files[p] = (zi, f["sha256"])
        if p in UMZ_ORG_MAP:
            rows = _json(_read_entry(zf, zi, UMZ_JSON_MAX, f["sha256"]), p)
            if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
                raise UmzBad(N_("The file contains a broken part: {0}"), p)
            if len(rows) > UMZ_MAX_ROWS:  # review M2: the same limits as the account import
                raise UmzBad(N_("The file contains a part that is too large: {0}"), p)
            data[UMZ_ORG_MAP[p]] = rows
        elif full or p.endswith(".json"):
            raw = _read_entry(zf, zi, UMZ_JSON_MAX if p.endswith(".json") else MAX_FILE_MB * 1024 * 1024 * 4, f["sha256"])
            what = next((w for pre, w in UMZ_ORG_SKIP if p.startswith(pre)), None)
            if what and p.endswith(".json"):
                try:
                    n = len(json.loads(raw.decode("utf-8")))
                except (ValueError, UnicodeDecodeError, RecursionError, TypeError):
                    n = 0
                if n:
                    skipped[what] = skipped.get(what, 0) + n
    for kind, table in (("attachments", "attachments"), ("list_files", "list_files")):
        for r in data.get(table, []):
            path = f"files/{kind}/{_oid(r.get('id')) or 0}-{_safe_part(r.get('name'))}"
            if path in files:
                r["file"] = path
    lists = {}
    for m in data.pop("list_members", []):
        lists.setdefault(_oid(m.get("user_id")), {})[str(_oid(m.get("list_id")))] = m.get("role")
    data["people"] = [{"user_id": _oid(m.get("id")), "name": _txt(m.get("display_name"), 100) or _txt(m.get("username"), 100),
                       "email": "" if m.get("kind") == "agent" else _txt(m.get("email"), 200), "lists": lists.get(_oid(m.get("id")), {}),
                       **({"agent": True} if m.get("kind") == "agent" else {})} for m in data.pop("members", [])]
    org = man["org"]
    m2 = {"format": "kalmido-org-export", "kind": "org", "v": 1, "kalmido_version": _txt(man.get("kalmido_version"), 40),
          "created_at": _txt(man.get("created_at"), 40), "source": {"url": "", "hosted": False},
          "user": {"id": None, "name": _txt(org.get("name"), 100), "email": ""}, "export_id": hashlib.sha256(mraw).hexdigest()[:32],
          "client_encrypted": {}, "org_skipped": skipped}
    return m2, files, data


def _oid(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int) and 0 < v < 1 << 62:
        return v
    if isinstance(v, str) and v.isdigit() and len(v) < 19:
        return int(v)
    return None


def _txt(v, n=200):
    return v[:n] if isinstance(v, str) else ""


def _email(v):
    v = _txt(v, 200).strip().lower()
    return v if "@" in v and " " not in v else ""


def umz_phash(p):
    """Review M1: the key of a person of the file -- email_hash (account export since the review), or the hash of the
    plain address (older files, the organisation export)."""
    from .acctexport import umz_email_hash
    h = p.get("email_hash") if isinstance(p, dict) else None
    if isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h):
        return h
    return umz_email_hash(_email(p.get("email"))) if isinstance(p, dict) else ""


def umz_pkey(v):
    """A key of the run's choice: the hash, or (older clients) a plain address."""
    from .acctexport import umz_email_hash
    if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v):
        return v
    return umz_email_hash(_email(v))


def umz_disk_size(received, sealed):
    """The bytes on disk of an upload with `received` confirmed plaintext bytes (sealed: head + whole blocks with tag)."""
    return UMZ_HEAD + (received // UMZ_BLOCK) * (UMZ_BLOCK + 16) if sealed else received


def umz_targets(c, uid):
    """Where the import may go: the private space and every organisation the person administers."""
    from ..accounts.orgs import org_role, user_orgs
    out = [{"id": "private", "name": tr("Private|workspace")}]
    for oid in user_orgs(c, uid):
        if org_role(c, uid, oid) == "admin":
            with system_ctx(c):  # the names of the person's own organisations (structure)
                r = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()
            if r:
                out.append({"id": int(oid), "name": r["name"]})
    return out


def umz_seen(c, uid):
    """Review M1: {email hash: account} of the accounts the person may see on this server (never others: the preview must
    not reveal accounts the person could not find in the app either)."""
    from ..accounts.orgs import visible_people
    from .acctexport import umz_email_hash
    vis = visible_people(c, uid)
    out = {}
    for r in c.execute("SELECT id, display_name, username, email FROM users WHERE disabled=0 AND COALESCE(kind,'user')!='agent' "
                       "AND email IS NOT NULL AND email!='' AND id!=?", (uid,)):
        if vis is None or r["id"] in vis:
            out.setdefault(umz_email_hash(r["email"]), r)
    return out


def umz_find(c, uid, h, seen=None):
    """The account behind this hash that the person may see, else None."""
    if not h:
        return None
    return (umz_seen(c, uid) if seen is None else seen).get(h)


def umz_preview(c, uid, man, data, can_invite):
    tables = {k: len(v) for k, v in data.items()}
    lists = [{"name": _txt(L.get("name"), 200), "folder": _txt(L.get("folder"), 300), "inbox": bool(L.get("is_inbox")),
              "tasks": sum(1 for t in data.get("tasks", []) if t.get("list_id") == L.get("id") and not t.get("deleted_at"))}
             for L in data.get("lists", [])]
    people = []
    from .acctexport import umz_email_hash
    mine = umz_email_hash((c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone() or [""])[0])
    seen = umz_seen(c, uid)
    for p in data.get("people", []):
        h = umz_phash(p)
        if not h or p.get("agent") or h == mine:
            continue
        hit = umz_find(c, uid, h, seen)
        # review M1: never an address in the preview; key = hash, the admin types the address for an invitation
        people.append({"key": h, "name": _txt(p.get("name"), 100), "lists": len(p.get("lists") or {}) if isinstance(p.get("lists"), dict) else 0,
                       "found": bool(hit), "found_name": (hit["display_name"] or hit["username"]) if hit else "",
                       "need_address": not _email(p.get("email"))})
    eid = man.get("export_id") if isinstance(man.get("export_id"), str) and UMZ_EID_RE.fullmatch(man.get("export_id")) else ""
    again = bool(eid) and bool(c.execute("SELECT 1 FROM imports WHERE user_id=? AND source=? AND undone_at IS NULL AND report ILIKE ?",
                                         (uid, UMZ_SOURCE, f'%"export_id": "{eid}"%')).fetchone())
    ce = man.get("client_encrypted") if isinstance(man.get("client_encrypted"), dict) else {}
    src = man.get("source") if isinstance(man.get("source"), dict) else {}
    u = man.get("user") or {}
    skipped = []
    org_kind = man.get("kind") == "org"
    for what, n in (man.get("org_skipped") or {}).items():  # an organisation export: the areas that do not move
        skipped.append({"what": tr(what), "count": n})
    for t, text in (("api_tokens", N_("API tokens")), ("webhooks", N_("Webhooks")), ("calendar_subscriptions", N_("Calendar subscriptions")),
                    ("karakeep", N_("Karakeep connection")), ("newsletter_connection", N_("Newsletter connection")),
                    ("agent_schedules", N_("Planned agent jobs")), ("public_links", N_("Public links"))):
        if tables.get(t):
            skipped.append({"what": tr(text), "count": tables[t]})
    return {
        "format": man.get("format"), "v": man.get("v"), "kalmido_version": _txt(man.get("kalmido_version"), 40),
        "created_at": _txt(man.get("created_at"), 40), "source": {"url": _txt(src.get("url"), 300), "hosted": bool(src.get("hosted"))},
        "user": {"name": _txt(u.get("name"), 100), "email": _email(u.get("email"))},  # the own address (plain in the file)
        "counts": {k: tables.get(k, 0) for k in ("lists", "sections", "tasks", "comments", "attachments", "list_files", "habits",
                                                  "filters", "templates", "time_entries", "event_calendars", "events", "address_books",
                                                  "contacts", "journal")},
        "lists": lists[:500], "people": people[:500], "can_invite": bool(can_invite),
        "server_links": [_txt(x.get("name"), 100) or _txt(x.get("base_url"), 200) for x in data.get("server_links", [])][:20],
        "encrypted": {"attachments": len(ce.get("attachments") or []) if isinstance(ce.get("attachments"), list) else 0,
                      "locked_notes": ce.get("locked_notes") if isinstance(ce.get("locked_notes"), int) else 0},
        "not_taken": skipped, "again": again, "export_id": eid, "kind": "org" if org_kind else "account",
        "targets": [t for t in umz_targets(c, uid) if not org_kind or t["id"] != "private"],
    }


# ---------------------------------------------------------------- writing rows
_COLS = {}


def umz_cols(c, table):
    """{column: (type, nullable, has default)} and the columns with a foreign key, cached per process."""
    if table not in _COLS:
        cols = {r[0]: (r[1], r[2] == "YES", r[3] is not None) for r in c.execute(
            """SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns
               WHERE table_schema=current_schema() AND table_name=?""", (table,))}
        fks = {r[0] for r in c.execute(
            """SELECT k.column_name FROM information_schema.table_constraints t JOIN information_schema.key_column_usage k
               ON k.constraint_name=t.constraint_name AND k.table_schema=t.table_schema
               WHERE t.constraint_type='FOREIGN KEY' AND t.table_schema=current_schema() AND t.table_name=?""", (table,))}
        _COLS[table] = (cols, fks)
    return _COLS[table]


_BAD = object()


def _coerce(v, typ):
    if v is None:
        return None
    if typ in ("bigint", "integer", "smallint"):
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int):
            return v if abs(v) < 1 << 62 else _BAD
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, str) and re.fullmatch(r"-?\d{1,18}", v.strip()):
            return int(v)
        return _BAD
    if typ in ("double precision", "real", "numeric"):
        if isinstance(v, bool):
            return _BAD
        try:
            f = float(v)
        except (TypeError, ValueError):
            return _BAD
        return f if f == f and abs(f) < 1e15 else _BAD
    if typ == "text":
        if isinstance(v, (dict, list)):
            v = json.dumps(v, ensure_ascii=False)
        elif not isinstance(v, str):
            v = str(v)
        return v[:UMZ_TEXT_MAX].replace("\x00", "")
    return _BAD  # json, binary, time stamps: not taken over


def _iso_ts(v):
    """A time stamp as the app writes it (ISO 8601, date or date + time, optionally with zone)."""
    if not isinstance(v, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:?\d{2})?)?", v):
        return False
    try:
        datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return False
    return DATE_MIN_Y <= int(v[:4]) <= DATE_MAX_Y


def _umz_rem(v):
    """'0,15' (minutes before due, as the app writes them) -> normalized, else _BAD."""
    if v == "":
        return v
    items = [x.strip() for x in v.split(",")] if isinstance(v, str) else []
    if not items or len(items) > REM_COUNT or not all(re.fullmatch(r"-?\d{1,6}", x) and REM_MIN <= int(x) <= REM_MAX for x in items):
        return _BAD
    return ",".join(dict.fromkeys(str(int(x)) for x in items))


# review N6: the format of known columns (the forms the app writes itself); a value that does not fit is left out, so the
# column's default applies (or the row is dropped when the column is required)
UMZ_CHECK = {
    ("tasks", "due"): valid_date, ("tasks", "start"): valid_date, ("tasks", "due_time"): valid_hm,
    ("tasks", "plan_start"): valid_plan_start, ("tasks", "priority"): lambda v: v in PRIORITIES,
    ("tasks", "duration"): lambda v: isinstance(v, int) and 1 <= v <= DURATION_MAX,
    ("tasks", "repeat_from"): lambda v: v in ("due", "done"), ("tasks", "reminders"): _umz_rem,
    ("habits", "remind_at"): lambda v: v == "" or valid_hm(v), ("habits", "days"): lambda v: bool(re.fullmatch(r"[1-7]{1,7}", v or "")),
    ("habits", "goal"): lambda v: isinstance(v, int) and 1 <= v <= 1000, ("habits", "per_week"): lambda v: isinstance(v, int) and 0 <= v <= 7,
    ("habit_logs", "day"): valid_date, ("events", "start"): _iso_ts, ("events", "end"): _iso_ts,
    ("time_entries", "start"): _iso_ts, ("time_entries", "end"): _iso_ts,
}


def umz_fmt(table, k, v):
    """The value to store, or _BAD (left out)."""
    f = UMZ_CHECK.get((table, k))
    if f is None:
        if v is None:
            return v
        if k == "color":
            return v if v == "" or (isinstance(v, str) and LIST_COLOR_RE.fullmatch(v)) else _BAD
        if k.endswith("_at") and isinstance(v, str):
            return v if v == "" or _iso_ts(v) else _BAD
        return v
    if v is None:
        return v
    r = f(v)
    return r if f is _umz_rem else v if r else _BAD


def umz_row(c, table, src, fixed, ts):
    """The row to insert: the file's values of the columns this server has (coerced to their type), never ids or columns
    that point at rows, plus the fixed values. None when a required column has no value."""
    cols, fks = umz_cols(c, table)
    drop = UMZ_DROP.get(table, ())
    d = {}
    for k, v in src.items():
        if not isinstance(k, str) or k not in cols or k in fixed or k == "id" or k in OX_SECRET_COLS or k in fks or k in drop \
                or k.endswith("_id") or k.endswith("_by") or k in ("org_id", "reply_to"):
            continue
        v = _coerce(v, cols[k][0])
        if v is not _BAD:
            v = umz_fmt(table, k, v)
        if v is _BAD or (v is None and not cols[k][1]):
            continue
        d[k] = v
    if table == "tasks":  # review N6: without a valid due date no time / reminders; a rule that never fits is dropped
        if not d.get("due"):
            for k in ("due_time", "reminders"):
                d.pop(k, None)
        if d.get("repeat"):
            rule = rr_norm(d["repeat"])
            if rr_problem(rule) or (d.get("due") and not rr_feasible(rule, d["due"])):
                d.pop("repeat")
            else:
                d["repeat"] = rule
    d.update({k: v for k, v in fixed.items() if k in cols})
    for k, (typ, nullable, dflt) in cols.items():
        if k in d or nullable or dflt or k == "id":
            continue
        if typ == "text" and k.endswith("_at"):
            d[k] = ts
        else:
            return None
    return d


def umz_insert(c, table, d, rid=True):
    names = list(d)
    sql = f"INSERT INTO {table}({','.join(chr(34) + n + chr(34) for n in names)}) VALUES({','.join('?' * len(names))})"
    args = [d[n] for n in names]
    from ..core.db import DataError, IntegrityError
    try:
        with c.savepoint():
            if rid:
                return insert_id(c, sql, args)
            c.execute(sql, args)
            return True
    except (IntegrityError, DataError):  # a duplicate or a value the column refuses: this row is skipped
        return None


class _Run:
    def __init__(self, uid, iid, eid, org, total):
        self.uid, self.iid, self.eid, self.org = uid, iid, eid, org
        self.maps = {}
        self.created = {"lists": [], "sections": [], "tasks": [], "habits": [], "filters": [], "templates": [], "ev_cals": [],
                        "books": [], "time_entries": [], "journal": [], "settings": {}, "files": []}
        self.stats = {}
        self.warn = {}
        self.done, self.total, self.tick = 0, max(1, total), 0
        self.task_list, self.field_list, self.list_org = {}, {}, {}
        self.written = []  # full paths of files written (removed again when the run fails)
        self.stopped = None
        self.kind = "account"  # or "org": an organisation export (part 4)

    def m(self, kind, old):
        o = _oid(old)
        return self.maps.get(kind, {}).get(o) if o else None

    def put(self, kind, old, new):
        o = _oid(old)
        if o and new:
            self.maps.setdefault(kind, {})[o] = new

    def count(self, k, n=1):
        self.stats[k] = self.stats.get(k, 0) + n

    def warning(self, text, *a):
        k = (text, *a)
        self.warn[k] = self.warn.get(k, 0) + 1

    def step(self):
        self.done += 1
        self.tick += 1
        if self.tick >= 200:
            self.tick = 0
            _set(self.uid, self.iid, progress={"done": self.done, "total": self.total})


def _file_bytes(zf, files, path):
    if not isinstance(path, str) or path not in files:
        return None
    zi, sha = files[path]
    return _read_entry(zf, zi, MAX_FILE_MB * 1024 * 1024 * 4, sha)


def umz_write(c, run, uid, man, zf, files, data, people):
    """Creates everything in the open transaction (the caller commits). people: {old user id: new user id} for authors
    and assignees (only people ticked for sharing)."""
    from ..admin.hosting import QuotaExceeded, quota_guard
    from ..core.access import my_inbox, my_max_sort
    from ..core.orgcrypt import oc_write_file
    from ..lists.lists import clean_folder, list_created, LIST_NAME_MAX
    from ..lists.projects import LIST_FILES_SUB
    from ..tasks.attachments import safe_name
    from ..core.schema import MAX_DEPTH
    from ..tasks.validation import CONTENT_MAX, TITLE_MAX
    ts = iso(now_utc())
    me_old = _oid((man.get("user") or {}).get("id"))
    org = run.org
    eid = run.eid

    def who(old):
        o = _oid(old)
        if o and o == me_old:
            return uid
        return people.get(o) if o else None

    # lists (the inbox of the file goes into my inbox)
    inbox = my_inbox(c, uid)
    sort = my_max_sort(c, uid)
    for L in data.get("lists", []):
        run.step()
        if L.get("is_inbox"):
            run.put("lists", L.get("id"), inbox)
            continue
        sort += 1
        try:
            folder = clean_folder(_txt(L.get("folder"), 1000), strict=False)
        except Exception:  # noqa: BLE001 -- a broken folder path: no folder
            folder = ""
        lorg = org
        if org and man.get("kind") != "org" and _txt(L.get("life"), 20):  # Home & life lists (health, contracts ...) stay private
            lorg = None
            run.warning(N_("Personal list kept in your private space: {0}"), _txt(L.get("name"), 80))
        d = umz_row(c, "lists", L, {"owner_id": uid, "org_id": lorg, "is_inbox": 0, "sort": sort, "folder": folder,
                                     "name": _txt(L.get("name"), LIST_NAME_MAX).strip() or tr("Import")}, ts)
        lid = umz_insert(c, "lists", d) if d else None
        if not lid:
            run.warning(N_("A list could not be taken over: {0}"), _txt(L.get("name"), 80))
            continue
        list_created(c, uid, lid, agents=False)  # 2.25.0 (#931); agents only when the person shares later
        run.list_org[lid] = lorg
        run.put("lists", L.get("id"), lid)
        run.created["lists"].append(lid)
        run.count("lists")
    # what hangs on a list
    for table, kind, fixed in (("sections", "sections", {}), ("list_fields", "list_fields", {}), ("list_tags", "list_tags", {}),
                               ("list_status", None, {"user_id": uid}), ("list_links", None, {"created_by": uid}),
                               ("list_milestones", "list_milestones", {"created_by": uid})):
        for r in data.get(table, []):
            run.step()
            lid = run.m("lists", r.get("list_id"))
            if not lid or lid == inbox:
                continue
            d = umz_row(c, table, r, {"list_id": lid, **fixed}, ts)
            nid = umz_insert(c, table, d) if d else None
            if nid and kind:
                run.put(kind, r.get("id"), nid)
                if kind == "list_fields":
                    run.field_list[nid] = lid
            if nid and table == "sections":
                run.created["sections"].append(nid)
            if nid:
                run.count(table)
    # tasks (the trash stays behind), then their parents
    rows = []
    for t in data.get("tasks", []):
        run.step()
        lid = run.m("lists", t.get("list_id"))
        if not lid or t.get("deleted_at"):
            continue
        sid = run.m("sections", t.get("section_id"))
        status = _coerce(t.get("status"), "bigint")
        status = status if status in (0, 2, -1) else 0
        aid = who(t.get("assignee_id"))
        if t.get("assignee_id") and not aid:
            run.warning(N_("Assignment not taken over (the person is not on this server or was not chosen)"))
        d = umz_row(c, "tasks", t, {
            "list_id": lid, "section_id": sid, "title": _txt(t.get("title"), TITLE_MAX) or "…",
            "content": _txt(t.get("content"), CONTENT_MAX), "status": status, "milestone_id": run.m("list_milestones", t.get("milestone_id")),
            "created_by": uid, "completed_by": uid if status else None, "assignee_id": aid, "assigned_by": uid if aid else None,
            "tt_id": f"kalmido:{eid[:16]}:{_oid(t.get('id')) or 0}", "parent_id": None, "updated_at": ts}, ts)
        tid = umz_insert(c, "tasks", d) if d else None
        if not tid:
            run.warning(N_("A task could not be taken over: {0}"), _txt(t.get("title"), 80))
            continue
        run.put("tasks", t.get("id"), tid)
        run.task_list[tid] = lid
        run.created["tasks"].append(tid)
        rows.append((t, tid, lid))
        run.count("tasks")
    old_parent = {_oid(t.get("id")): _oid(t.get("parent_id")) for t, _, _ in rows}
    for t, tid, lid in rows:
        p = run.m("tasks", t.get("parent_id"))
        if not p:
            continue
        chain, cur = 0, _oid(t.get("parent_id"))
        seen = {_oid(t.get("id"))}
        while cur and cur not in seen and chain <= MAX_DEPTH:
            seen.add(cur)
            chain += 1
            cur = old_parent.get(cur)
        if run.task_list.get(p) != lid or chain >= MAX_DEPTH or (cur and cur in seen):
            run.warning(N_("Subtask in another list or in a cycle, imported as a main task"), _txt(t.get("title"), 80))
            continue
        c.execute("UPDATE tasks SET parent_id=? WHERE id=?", (p, tid))
        run.count("subtasks")
    # what hangs on a task
    for r in data.get("task_deps", []):
        a, b = run.m("tasks", r.get("task_id")), run.m("tasks", r.get("blocker_id"))
        if a and b and a != b and umz_insert(c, "task_deps", {"task_id": a, "blocker_id": b, "created_by": uid, "created_at": ts}, rid=False):
            run.count("task_deps")
    for r in data.get("task_field_values", []):
        tid, fid = run.m("tasks", r.get("task_id")), run.m("list_fields", r.get("field_id"))
        if tid and fid and run.field_list.get(fid) == run.task_list.get(tid):
            umz_insert(c, "task_field_values", {"task_id": tid, "field_id": fid, "value": _coerce(r.get("value"), "text") or ""}, rid=False)
    for r in data.get("task_tags", []):
        tid = run.m("tasks", r.get("task_id"))
        tag = _txt(r.get("tag"), 100).strip()
        if tid and tag and _oid(r.get("user_id")) == me_old:
            umz_insert(c, "task_tags", {"task_id": tid, "user_id": uid, "tag": tag}, rid=False)
    for r in data.get("task_list_tags", []):
        tid, gid = run.m("tasks", r.get("task_id")), run.m("list_tags", r.get("tag_id"))
        if tid and gid:
            umz_insert(c, "task_list_tags", {"task_id": tid, "tag_id": gid}, rid=False)
    for r in data.get("task_note_locks", []):  # browser-encrypted with my note password: only my own
        tid = run.m("tasks", r.get("task_id"))
        if tid and _oid(r.get("user_id")) == me_old:
            d = umz_row(c, "task_note_locks", r, {"task_id": tid, "user_id": uid}, ts)
            if d:
                umz_insert(c, "task_note_locks", d, rid=False)
    names = {_oid(p.get("user_id")): _txt(p.get("name"), 100) for p in data.get("people", [])}
    for r in sorted(data.get("comments", []), key=lambda x: _oid(x.get("id")) or 0):
        run.step()
        tid = run.m("tasks", r.get("task_id"))
        if not tid:
            continue
        au = who(r.get("user_id"))
        ext = None if au else (names.get(_oid(r.get("user_id"))) or _txt(r.get("ext_name"), 100) or tr("Unknown"))
        d = umz_row(c, "comments", r, {"task_id": tid, "user_id": au, "ext_name": ext, "reply_to": run.m("comments", r.get("reply_to")),
                                        "mentions": ""}, ts)
        nid = umz_insert(c, "comments", d) if d else None
        if nid:
            run.put("comments", r.get("id"), nid)
            run.count("comments")
    # files: attachments + project files, sealed like an upload (orgcrypt) and counted against the quota
    for table, kind in (("attachments", "tasks"), ("list_files", "lists")):
        for r in data.get(table, []):
            run.step()
            parent = run.m(kind, r.get("task_id" if kind == "tasks" else "list_id"))
            if not parent:
                continue
            enc = _coerce(r.get("enc"), "bigint") if table == "attachments" else 0
            if enc and _oid(r.get("enc_by")) != me_old:
                run.warning(N_("Encrypted file of another person not taken over: {0}"), _txt(r.get("name"), 80))
                continue
            raw = _file_bytes(zf, files, r.get("file"))
            if raw is None:
                run.warning(N_("A file is missing in the export: {0}"), _txt(r.get("name"), 80))
                continue
            if not raw or len(raw) > MAX_FILE_MB * 1024 * 1024:
                run.warning(N_("A file is empty or too large and was skipped: {0}"), _txt(r.get("name"), 80))
                continue
            try:
                quota_guard(c, uid, len(raw))
            except QuotaExceeded:
                run.stopped = "quota"
                raise UmzStop() from None
            name = safe_name(_txt(r.get("name"), 150))
            sub = os.path.join(str(parent)) if kind == "tasks" else os.path.join(LIST_FILES_SUB, str(parent))
            os.makedirs(os.path.join(ATT_DIR, sub), exist_ok=True)
            rel = os.path.join(sub, f"{uuid.uuid4().hex[:12]}-{name}")
            full = os.path.join(ATT_DIR, rel)
            run.written.append(full)
            lorg = run.list_org.get(run.task_list.get(parent) if kind == "tasks" else parent)
            oc_write_file(c, lorg, full, raw)  # 2.42.0 (#828): sealed with the key of the list's organisation (none: private)
            fixed = {"name": name, "size": len(raw), "path": rel, "user_id": uid, "created_at": _txt(r.get("created_at"), 40) or ts}
            if kind == "tasks":
                fixed.update({"task_id": parent, "comment_id": run.m("comments", r.get("comment_id")), "enc": 1 if enc else 0,
                              "enc_by": uid if enc else None})
            else:
                fixed["list_id"] = parent
            d = umz_row(c, table, r, fixed, ts)
            if not d or not umz_insert(c, table, d):
                run.warning(N_("A file could not be taken over: {0}"), name)
                continue
            if kind == "tasks":
                run.created["files"].append(rel)
            run.count(table)
    # personal parts
    for r in data.get("time_entries", []):
        run.step()
        d = umz_row(c, "time_entries", r, {"user_id": uid, "task_id": run.m("tasks", r.get("task_id")),
                                            "list_id": run.m("lists", r.get("list_id"))}, ts)
        nid = umz_insert(c, "time_entries", d) if d else None
        if nid:
            run.created["time_entries"].append(nid)
            run.count("time_entries")
    org_kind = man.get("kind") == "org"
    for src, table, kind, fixed in (("habits", "habits", "habits", {"user_id": uid}), ("filters", "filters", None, {"user_id": uid}),
                                    ("templates", "templates", None, {"user_id": uid}),
                                    ("address_books", "books", "books", {"owner_id": uid, "org_id": org if org_kind else None, "owner_org_id": None}),
                                    ("event_calendars", "ev_cals", "ev_cals", {"owner_id": uid, "org_id": org if org_kind else None})):
        for r in data.get(src, []):
            run.step()
            if table == "books" and org_kind and _oid(r.get("owner_org_id")):
                fixed = {**fixed, "owner_org_id": org}  # an address book of the organisation itself (2.52.0 C, #1438)
            d = umz_row(c, table, r, {**fixed, "updated_at": ts, "changed_at": ts}, ts)
            nid = umz_insert(c, table, d) if d else None
            if not nid:
                continue
            if kind:
                run.put(kind, r.get("id"), nid)
            run.created[table if table in run.created else src].append(nid)
            run.count(src)
    for r in data.get("habit_logs", []):
        hid = run.m("habits", r.get("habit_id"))
        if hid:
            d = umz_row(c, "habit_logs", r, {"habit_id": hid}, ts)
            if d:
                umz_insert(c, "habit_logs", d, rid=False)
    for r in data.get("contacts", []):
        run.step()
        bid = run.m("books", r.get("book_id"))
        if not bid:
            continue
        cuid = r.get("uid") if isinstance(r.get("uid"), str) and UMZ_UID_RE.fullmatch(r["uid"]) else uuid.uuid4().hex
        # review N7: the CardDAV path never comes from the file (a uid with / or spaces made it unreachable)
        d = umz_row(c, "contacts", r, {"book_id": bid, "uid": cuid, "href": f"{uuid.uuid4().hex}.vcf", "updated_at": ts, "changed_at": ts}, ts)
        nid = umz_insert(c, "contacts", d) if d else None
        if nid:
            run.put("contacts", r.get("id"), nid)
            run.count("contacts")
    for r in data.get("events", []):
        run.step()
        cid = run.m("ev_cals", r.get("cal_id"))
        if not cid:
            continue
        euid = _txt(r.get("uid"), 300) or uuid.uuid4().hex
        d = umz_row(c, "events", r, {"cal_id": cid, "uid": euid, "href": f"{uuid.uuid4().hex}.ics", "task_id": run.m("tasks", r.get("task_id")),
                                      "created_by": uid, "updated_at": ts}, ts)
        nid = umz_insert(c, "events", d) if d else None
        if nid:
            run.put("events", r.get("id"), nid)
            run.count("events")
    for r in data.get("event_attendees", []):
        eid2 = run.m("events", r.get("event_id"))
        if eid2:
            d = umz_row(c, "event_attendees", r, {"event_id": eid2, "user_id": uid if _oid(r.get("user_id")) == me_old else None,
                                                   "contact_id": run.m("contacts", r.get("contact_id"))}, ts)
            if d:
                umz_insert(c, "event_attendees", d)
    for r in data.get("journal", []):
        day = _txt(r.get("day"), 10)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) and not c.execute("SELECT 1 FROM journal WHERE user_id=? AND day=?", (uid, day)).fetchone():
            d = umz_row(c, "journal", r, {"user_id": uid, "day": day, "updated_at": ts}, ts)
            if d and umz_insert(c, "journal", d, rid=False):
                run.created["journal"].append(day)
                run.count("journal")
    cur = usettings(c, uid)
    for r in data.get("settings", []):
        k, v = r.get("key"), r.get("value")
        if k not in UMZ_SETTINGS or not isinstance(v, str) or len(v) > 20000:
            continue
        if (k == "lang" and v not in LANGS) or (k not in ("lang", "folders") and not re.fullmatch(r"[A-Za-z0-9:,._ -]{0,64}", v)):
            continue  # only plain values (the app checks the others when they are set by hand)
        if k == "folders":  # my folders stay; the file's are added behind them
            try:
                mine, theirs = json.loads(cur.get("folders") or "[]"), json.loads(v)
            except ValueError:
                continue
            if not isinstance(theirs, list):
                continue
            v = json.dumps(mine + [f for f in theirs if isinstance(f, str) and f not in mine][:500], ensure_ascii=False)
        if v != (cur.get(k) or ""):
            run.created["settings"][k] = {"old": cur.get(k), "new": v}
            uset(c, uid, k, v)


def umz_share(c, run, uid, data, picks, can_invite):
    """After the import: lists shared with the people ticked in the preview (found by their e-mail hash), missing people
    invited (instance admins only, the address typed by the admin must match the hash). Returns the people's results for
    the report."""
    from ..lists.lists import _folder_member_add
    from .acctexport import umz_email_hash
    out = []
    seen = umz_seen(c, uid)
    for p in data.get("people", []):
        h = umz_phash(p)
        pick = picks.get(h) or {}
        if not h or p.get("agent") or not (pick.get("share") or pick.get("invite")):
            continue
        lists = p.get("lists") if isinstance(p.get("lists"), dict) else {}
        hit = umz_find(c, uid, h, seen)
        em = pick.get("email") or _email(p.get("email"))  # typed by the admin, or the plain address of an older file
        target, state = None, "skipped"
        if hit and pick.get("share"):
            target, state = hit["id"], "shared"
            if run.org and run.kind == "org":  # an organisation export: the ticked member joins the target organisation
                from ..accounts.orgs import org_member_add, org_role
                if not org_role(c, hit["id"], run.org):
                    with system_ctx(c):  # the organisation's admin adds the person they ticked (structure)
                        org_member_add(c, run.org, hit["id"], "member")
        elif not hit and pick.get("invite") and can_invite:
            if not em or umz_email_hash(em) != h:
                state = "mismatch"  # review M1: the typed address is not the one of the file -- nobody is invited
            else:
                target = umz_invite(c, run, uid, em, _txt(p.get("name"), 60))
                state = "invited" if target else "failed"
        n = 0
        if target:
            for old, role in lists.items():
                lid = run.m("lists", old)
                if lid and lid in run.created["lists"] and _folder_member_add(c, lid, target, role if role in ROLES else "edit", uid):
                    n += 1
        out.append({"key": h, "name": _txt(p.get("name"), 100), "state": state, "lists": n})
    return out


def umz_fix_people(c, run, uid, names):
    """After the sharing: an assignment or a comment author that points at a person who did not become a member of the
    list (sharing refused, not ticked, the run stopped) is undone -- the name stays as text, nobody gets attributed or
    assigned in a list they cannot see."""
    ids = run.created["tasks"]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        nm = f"""user_id!=? AND NOT EXISTS (SELECT 1 FROM list_members m JOIN tasks t ON t.list_id=m.list_id
                 WHERE t.id=comments.task_id AND m.user_id=comments.user_id)"""
        for r in c.execute(f"SELECT id, user_id FROM comments WHERE task_id IN ({q}) AND user_id IS NOT NULL AND {nm}", part + [uid]).fetchall():
            c.execute("UPDATE comments SET user_id=NULL, ext_name=? WHERE id=?", (names.get(r["user_id"]) or tr("Unknown"), r["id"]))
        n = c.execute(f"""UPDATE tasks SET assignee_id=NULL, assigned_by=NULL WHERE id IN ({q}) AND assignee_id IS NOT NULL AND assignee_id!=?
                          AND NOT EXISTS (SELECT 1 FROM list_members m WHERE m.list_id=tasks.list_id AND m.user_id=tasks.assignee_id)""",
                      part + [uid]).rowcount
        if n:
            run.warning(N_("Assignment not taken over (the person is not on this server or was not chosen)"))


def umz_invite(c, run, uid, email, name):
    """A new account for a missing person (instance admin) and the invitation link by e-mail (#697)."""
    from ..accounts.invite import invite_new
    from ..core.db import create_user
    if c.execute("SELECT 1 FROM users WHERE lower(email)=?", (email,)).fetchone():
        return None  # the address exists but the admin does not see it: never a second account
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower())[:24] or "user"
    if not re.match(r"[a-z0-9]", base):
        base = "u" + base
    login, i = base, 1
    while c.execute("SELECT 1 FROM users WHERE username=?", (login,)).fetchone():
        i += 1
        login = f"{base}{i}"[:32]
    nid = create_user(c, login, name or login, None, None, False, onboard=True)
    c.execute("UPDATE users SET email=? WHERE id=?", (email, nid))
    uset(c, nid, "lang", usettings(c, uid).get("lang") or "en")
    if run.org:
        from ..accounts.orgs import org_member_add
        with system_ctx(c):  # the organisation's admin places the invited person in it (structure)
            org_member_add(c, run.org, nid, "member")
    try:
        invite_new(c, nid, uid, send=True)
    except Denied:
        return None
    return nid


def umz_run(uid, iid, opts):
    """The thread: check the file again, write everything, share / invite, record the import (undo)."""
    c = connect()
    run = None
    try:
        umz_user_conn(c, uid)
        _L.lg = lang(c, uid)
        st = _st(uid, iid) or {}
        key = umz_key(uid, "upload") if st.get("sealed") else None
        zf, man, files, data = umz_open(os.path.join(_dir(uid, iid), "upload.bin"), key, st["size"], full=False)
        try:
            people = {}
            seen = umz_seen(c, uid)
            for p in data.get("people", []):
                h = umz_phash(p)
                if h and (opts["people"].get(h) or {}).get("share"):
                    hit = umz_find(c, uid, h, seen)
                    if hit and _oid(p.get("user_id")):
                        people[_oid(p.get("user_id"))] = hit["id"]
            if man.get("kind") == "org":  # an organisation export: my own account there has my e-mail address
                from .acctexport import umz_email_hash
                mine = umz_email_hash((c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone() or [""])[0])
                hit = [p for p in data.get("people", []) if mine and umz_phash(p) == mine]
                man["user"]["id"] = _oid(hit[0].get("user_id")) if hit else None
                if hit and _oid(hit[0].get("user_id")) in people:
                    people.pop(_oid(hit[0].get("user_id")), None)
            total = sum(len(v) for v in data.values())
            eid = st.get("export_id") or secrets.token_hex(8)
            run = _Run(uid, iid, eid, opts["org"], total)
            run.kind = man.get("kind") or "account"
            c.commit()
            try:
                umz_write(c, run, uid, man, zf, files, data, people)
            except UmzStop:
                pass
            report = {**run.stats, "export_id": eid, "tasks": run.stats.get("tasks", 0)}
            iid_db = None
            if any(run.created[k] for k in run.created):  # recorded with the rows: whatever happens next, undo works
                from ..integrations.importers import IMPORT_KEEP
                iid_db = insert_id(c, "INSERT INTO imports(user_id,source,file_name,created,report,created_at) VALUES(?,?,?,?,?,?)",
                                   (uid, UMZ_SOURCE, _txt(st.get("name"), 200), json.dumps(run.created), json.dumps(report), iso(now_utc())))
                c.execute("""DELETE FROM imports WHERE user_id=? AND id NOT IN
                             (SELECT id FROM imports WHERE user_id=? ORDER BY id DESC LIMIT ?)""", (uid, uid, IMPORT_KEEP))
            c.commit()
            run.written = []  # committed: the files belong to their rows now
            shared = []
            if not run.stopped:
                try:
                    shared = umz_share(c, run, uid, data, opts["people"], opts["can_invite"])
                except Exception as e:  # noqa: BLE001 -- the import stays (and can be undone); the sharing is reported
                    c.heal() or c.rollback()
                    print(f"account import of user {uid}: sharing failed: {type(e).__name__}", flush=True)
                    run.warning(N_("Sharing with the chosen people failed. Share the lists by hand."))
            names = {}
            for p in data.get("people", []):  # the new account ids of the mapped people -> their names from the file
                o = _oid(p.get("user_id"))
                if o in people:
                    names[people[o]] = _txt(p.get("name"), 100)
            umz_fix_people(c, run, uid, names)
            bump(c)
            c.commit()
        finally:
            zf.close()
        from ..integrations.importers import IMPORT_UNDO_HOURS
        result = {"created": run.stats, "people": shared, "import_id": iid_db,
                  "undo_until": iso(now_utc() + timedelta(hours=IMPORT_UNDO_HOURS)) if iid_db else None,
                  "warnings": [{"text": tr(k[0], *k[1:]), "count": n} for k, n in list(run.warn.items())[:50]]}
        if run.stopped == "quota":
            result["stopped"] = tr("Your storage is full: the import stopped. What came over so far can be undone.")
        _set(uid, iid, state="stopped" if run.stopped else "done", result=result, progress=None)
        print(f"account import of user {uid}: {run.stats.get('tasks', 0)} tasks", flush=True)
    except UmzBad as e:
        c.rollback()
        _set(uid, iid, state="invalid", error=tr(e.text, *e.args_))
    except Exception as e:  # noqa: BLE001 -- the state says it failed; never content in the message
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
            pass
        for p in run.written if run else ():  # files of rows that were never committed
            try:
                os.remove(p)
            except OSError:
                pass
        print(f"account import of user {uid} failed: {type(e).__name__}", flush=True)
        _set(uid, iid, state="failed", error=tr("The import failed. Nothing was taken over. Please try again later or ask the server admin (server log)."))
    finally:
        try:
            p = os.path.join(_dir(uid, iid), "upload.bin")
            if (_st(uid, iid) or {}).get("state") in ("done", "stopped", "failed") and os.path.exists(p):
                os.remove(p)  # the upload is gone as soon as the run is over
        except OSError:
            pass
        c.close()
        with _UMI_LOCK:
            _UMI.pop(int(uid), None)


def umz_check(uid, iid, can_invite):
    """The thread after the last piece: check the file, build the preview."""
    c = connect()
    try:
        umz_user_conn(c, uid)
        _L.lg = lang(c, uid)
        st = _st(uid, iid) or {}
        key = umz_key(uid, "upload") if st.get("sealed") else None
        head = umz_org_head(os.path.join(_dir(uid, iid), "upload.bin"), key, st["size"])
        if head is not None:  # an encrypted organisation export: the recovery key opens it (umz_unlock)
            c.rollback()
            _set(uid, iid, state="key", preview={"kind": "org", "org": _txt(head.get("org"), 100), "created_at": _txt(head.get("created_at"), 40),
                                                  "kalmido_version": _txt(head.get("kalmido_version"), 40)})
            return
        zf, man, files, data = umz_open(os.path.join(_dir(uid, iid), "upload.bin"), key, st["size"])
        zf.close()
        pv = umz_preview(c, uid, man, data, can_invite)
        c.rollback()
        _set(uid, iid, state="preview", preview=pv, export_id=pv["export_id"])
    except UmzBad as e:
        _set(uid, iid, state="invalid", error=tr(e.text, *e.args_))
        try:
            os.remove(os.path.join(_dir(uid, iid), "upload.bin"))
        except OSError:
            pass
    except Exception as e:  # noqa: BLE001
        print(f"account import check of user {uid} failed: {type(e).__name__}", flush=True)
        _set(uid, iid, state="invalid", error=tr("The file could not be read."))
    finally:
        c.close()
        with _UMI_LOCK:
            _UMI.pop(int(uid), None)


def _buffered(path, key, size):
    return io.BufferedReader(UmzReader(path, key, size), UMZ_BLOCK)


def umz_org_head(path, key, size):
    """The header of an encrypted organisation export (orgexport.py ox_header), None for anything else."""
    from .orgexport import OX_MAGIC
    with _buffered(path, key, size) as r:
        if r.read(len(OX_MAGIC)) != OX_MAGIC:
            return None
        raw = r.read(4)
        n = struct.unpack(">I", raw)[0] if len(raw) == 4 else 0
        if not 0 < n <= 1 << 16:
            raise UmzBad(N_("The file contains a broken part: {0}"), "header")
        head = r.read(n)
    try:
        h = json.loads(head.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise UmzBad(N_("The file contains a broken part: {0}"), "header") from None
    if not isinstance(h, dict) or h.get("format") != "kalmido-org-export" or h.get("alg") != "AES-256-GCM":
        raise UmzBad(N_("The file contains a broken part: {0}"), "header")
    if h.get("v") != 1:
        raise UmzBad(N_("This export comes from a newer Kalmido version. Update this server first."))
    return {**h, "_raw": raw, "_head": head}


class UmzWrongKey(Exception):
    pass


def umz_org_decrypt(path, key, size, okey, out):
    """Writes the plain ZIP of the organisation export in path into out (an UmzWriter), block by block as
    tools/kalmido_export_decrypt.py does: a wrong key -> UmzWrongKey, a damaged / cut / reordered file -> UmzBad."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from .orgexport import OX_FK_AAD, OX_MAGIC
    h = umz_org_head(path, key, size)
    hh = hashlib.sha256(OX_MAGIC + h["_raw"] + h["_head"]).digest()
    try:
        w = base64.b64decode(h["wrapped_fk"])
        prefix = base64.b64decode(h["nonce_prefix"])
        block = int(h["block"])
        fk = AESGCM(okey).decrypt(w[:12], w[12:], OX_FK_AAD + str(int(h["org_id"])).encode())
    except InvalidTag:
        raise UmzWrongKey() from None
    except (KeyError, ValueError, TypeError):
        raise UmzBad(N_("The file contains a broken part: {0}"), "header") from None
    if len(prefix) != 8 or not 0 < block <= 1 << 26:
        raise UmzBad(N_("The file contains a broken part: {0}"), "header")
    aes, i = AESGCM(fk), 0
    with _buffered(path, key, size) as r:
        r.read(len(OX_MAGIC) + 4 + len(h["_head"]))
        cur = r.read(block + 16)
        while True:
            if len(cur) < 16:
                raise UmzBad(N_("The upload is damaged. Please upload the file again."))
            nxt = r.read(block + 16) if len(cur) == block + 16 else b""
            last = not nxt
            try:
                out.write(aes.decrypt(prefix + struct.pack(">I", i), cur, hh + struct.pack(">QB", i, 1 if last else 0)))
            except InvalidTag:
                raise UmzBad(N_("The upload is damaged. Please upload the file again.")) from None
            if last:
                return
            cur, i = nxt, i + 1


UMZ_KEY_TRIES = 10  # wrong recovery keys per upload; then the upload is removed


def umz_unlock(uid, iid, okey, can_invite):
    """The thread: open the organisation export with the recovery key, then check it like any other file."""
    try:
        _L.lg = lang(uid=uid)
        st = _st(uid, iid) or {}
        key = umz_key(uid, "upload") if st.get("sealed") else None
        src = os.path.join(_dir(uid, iid), "upload.bin")
        dst = os.path.join(_dir(uid, iid), "plain.part")
        try:
            with os.fdopen(os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as f:
                w = UmzWriter(f, key)
                umz_org_decrypt(src, key, st["size"], okey, w)
                w.finish()
        except UmzWrongKey:
            os.remove(dst)
            tries = int(st.get("tries") or 0) + 1
            if tries >= UMZ_KEY_TRIES:
                _drop(uid, iid)
                return
            _set(uid, iid, state="key", tries=tries, key_error=True)
            return
        except Exception:
            if os.path.exists(dst):
                os.remove(dst)
            raise
        os.replace(dst, src)
        _set(uid, iid, state="checking", size=w.size, key_error=False)
        umz_check(uid, iid, can_invite)  # the opened ZIP is checked like any other file (same thread)
    except UmzBad as e:
        _set(uid, iid, state="invalid", error=tr(e.text, *e.args_))
        return
    except Exception as e:  # noqa: BLE001
        print(f"account import unlock of user {uid} failed: {type(e).__name__}", flush=True)
        _set(uid, iid, state="invalid", error=tr("The file could not be read."))
        return
    finally:
        with _UMI_LOCK:
            _UMI.pop(int(uid), None)


def _thread(uid, fn, *args):
    with _UMI_LOCK:
        if _busy(uid):
            raise Denied(409, tr("An import is already running"))
        t = threading.Thread(target=fn, args=(uid, *args), daemon=True)
        _UMI[int(uid)] = t
        t.start()


def umz_undo(c, uid, r):
    """Undo of an account import (called by importers.imp_undo after its own checks): everything the run created."""
    from ..core.access import list_role, WRITE_ROLES
    from ..core.serializers import unlink_files
    from ..lists.projects import list_purge_files, list_row_purge
    cr = json.loads(r["created"] or "{}")
    own_lists = set(cr.get("lists") or [])
    files = [p for p in cr.get("files") or [] if isinstance(p, str)]
    n_tasks = 0
    ids = [int(x) for x in cr.get("tasks") or []]
    for i in range(0, len(ids), 500):  # tasks in lists that were there before (my inbox): only still writable ones
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        for t in c.execute(f"SELECT id, list_id FROM tasks WHERE id IN ({q}) AND created_by=? AND tt_id ILIKE 'kalmido:%'", part + [uid]).fetchall():
            if t["list_id"] not in own_lists and list_role(c, t["list_id"], uid) in WRITE_ROLES:
                c.execute("UPDATE tasks SET parent_id=NULL WHERE parent_id=?", (t["id"],))
                n_tasks += c.execute("DELETE FROM tasks WHERE id=?", (t["id"],)).rowcount
    gone, n_lists = [], 0
    for lid in own_lists:
        if c.execute("SELECT 1 FROM lists WHERE id=? AND owner_id=?", (lid, uid)).fetchone():
            n_tasks += c.execute("SELECT COUNT(*) FROM tasks WHERE list_id=?", (lid,)).fetchone()[0]
            n_lists += list_row_purge(c, lid, gone)
    for table, col in (("habits", "user_id"), ("filters", "user_id"), ("templates", "user_id"), ("ev_cals", "owner_id"),
                       ("books", "owner_id"), ("time_entries", "user_id")):
        part = [int(x) for x in cr.get(table) or []]
        for i in range(0, len(part), 500):
            p = part[i:i + 500]
            c.execute(f"DELETE FROM {table} WHERE id IN ({','.join('?' * len(p))}) AND {col}=?", p + [uid])
    for day in cr.get("journal") or []:
        c.execute("DELETE FROM journal WHERE user_id=? AND day=?", (uid, day))
    cur = usettings(c, uid)
    for k, v in (cr.get("settings") or {}).items():
        if k in UMZ_SETTINGS and isinstance(v, dict) and cur.get(k) == v.get("new"):
            uset(c, uid, k, v.get("old") if v.get("old") is not None else "")
    c.execute("UPDATE imports SET undone_at=? WHERE id=?", (iso(now_utc()), r["id"]))
    bump(c)
    c.commit()
    unlink_files(files)
    list_purge_files(gone)
    print("account import undo", r["id"], "user", uid, "tasks", n_tasks, flush=True)
    return {"tasks": n_tasks, "lists": n_lists, "sections": 0, "kept_lists": 0, "kept_tasks": 0}


# ---------------------------------------------------------------- routes (people only)
def _view(uid, iid, st):
    out = {"id": iid, "state": st.get("state"), "size": st.get("size"), "received": st.get("received"), "name": st.get("name", "")}
    if st.get("state") in ("checking", "running") and not _busy(uid):
        out["state"] = "failed"
        out["error"] = tr("The import was interrupted. Please start it again.")
    if st.get("state") == "key" and st.get("key_error"):
        out["error"] = tr("The recovery key does not open this export. Attempts left: {0}", UMZ_KEY_TRIES - int(st.get("tries") or 0))
    for k in ("preview", "error", "progress", "result"):
        if st.get(k) is not None and k not in out:
            out[k] = st[k]
    return out


@app.post("/api/account/import")
def umz_new():
    """{size, name}: a new upload. 413 above KALMIDO_ACCOUNT_IMPORT_MAX_MB, 413 quota_exceeded, 507 without disk space."""
    umz_person()
    uid = me()
    b = body()
    size = b.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size < 22:
        return err(tr("Invalid value: {0}", "size"))
    if size > UMZ_IMPORT_MAX_MB * 1024 * 1024:
        return err(tr("The file is too large (at most {0} MB)", UMZ_IMPORT_MAX_MB), 413)
    c = db()
    from ..admin.hosting import quota_guard
    quota_guard(c, uid, size)  # the files in it will count against my storage (checked again per file in the run)
    if not umz_space_ok(UMZ_IN_DIR, size * 2):
        return err(tr("There is not enough space on the server for the import. Please ask the server admin."), 507)
    if _busy(uid):
        return err(tr("An import is already running"), 409)
    if os.path.isdir(_base(uid)):  # one upload per person: an older one goes
        shutil.rmtree(_base(uid), ignore_errors=True)
    iid = secrets.token_hex(12)
    os.makedirs(_dir(uid, iid), mode=0o700, exist_ok=True)
    key = umz_key(uid, "upload")
    with os.fdopen(os.open(os.path.join(_dir(uid, iid), "upload.bin"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
        UmzWriter(f, key).finish()
    umz_write_state(_dir(uid, iid), {"state": "upload", "size": size, "received": 0, "sealed": bool(key),
                                     "name": _txt(b.get("name"), 200), "created_at": iso(now_utc())})
    c.rollback()
    return jsonify(id=iid, chunk=UMZ_CHUNK, max_mb=UMZ_IMPORT_MAX_MB)


@app.put("/api/account/import/<iid>")
def umz_piece(iid):
    """The next piece of the upload (raw body) at ?offset= (= the bytes received so far)."""
    umz_person()
    uid = me()
    st = _need(uid, iid)
    if st.get("state") != "upload":
        return err(tr("This upload is complete already"), 409)
    try:
        off = int(request.args.get("offset", ""))
    except ValueError:
        return err(tr("Invalid value: {0}", "offset"))
    if off != st["received"]:
        return jsonify(error=tr("Invalid value: {0}", "offset"), received=st["received"]), 409
    n = request.content_length or 0
    last = off + n == st["size"]
    if n <= 0 or n > UMZ_CHUNK or off + n > st["size"] or (not last and n % UMZ_BLOCK):
        return err(tr("Invalid value: {0}", "chunk"))
    data = request.get_data(cache=False)
    if len(data) != n:
        return err(tr("Invalid value: {0}", "chunk"))
    path = os.path.join(_dir(uid, iid), "upload.bin")
    key = umz_key(uid, "upload") if st.get("sealed") else None
    with _PIECE_LOCK:
        if (_st(uid, iid) or {}).get("received") != off:  # another request at the same offset was faster
            return jsonify(error=tr("Invalid value: {0}", "offset"), received=(_st(uid, iid) or {}).get("received")), 409
        with open(path, "ab") as f:
            # review N4: a piece that broke off half-written left bytes behind the confirmed state -- cut them, so the next
            # try neither appends to a broken file nor seals a block number (nonce) twice
            f.truncate(umz_disk_size(off, bool(key)))
            w = UmzWriter.resume(f, path, key, off)
            w.write(data)
            w.finish()
        st = _set(uid, iid, received=off + n)
    if last:
        _set(uid, iid, state="checking")
        try:
            _thread(uid, umz_check, iid, bool(g.user["is_admin"]))
        except Denied:
            _set(uid, iid, state="upload", received=off)
            raise
    return jsonify(_view(uid, iid, _st(uid, iid)))


@app.get("/api/account/import/<iid>")
def umz_state(iid):
    umz_person()
    uid = me()
    return jsonify(_view(uid, iid, _need(uid, iid)))


@app.get("/api/account/import")
def umz_current():
    """My current upload / import (the newest), if any -- the app picks it up again after a reload."""
    umz_person()
    uid = me()
    best = None
    if os.path.isdir(_base(uid)):
        for iid in os.listdir(_base(uid)):
            st = _st(uid, iid) if re.fullmatch(r"[0-9a-f]{24}", iid) else None
            if st and (best is None or st.get("created_at", "") > best[1].get("created_at", "")):
                best = (iid, st)
    return jsonify(current=_view(uid, *best) if best else None, chunk=UMZ_CHUNK, max_mb=UMZ_IMPORT_MAX_MB)


@app.post("/api/account/import/<iid>/run")
def umz_go(iid):
    """{target: "private" | org id (I am its admin), people: {key: {share: bool, invite: bool, email?: str}}} -> the run starts.
    key = the preview's hash (review M1; a plain address of an older client works too); email = the address an instance
    admin typed for an invitation (checked against the hash in the run)."""
    umz_person()
    uid = me()
    st = _need(uid, iid)
    if st.get("state") != "preview":
        return err(tr("The file is not ready for the import"), 409)
    b = body()
    c = db()
    tg = b.get("target", "private")
    org = None
    if tg == "private" and (st.get("preview") or {}).get("kind") == "org":
        return err(tr("An organisation export goes into an organisation: choose one you administer."))
    if tg != "private":
        if not isinstance(tg, int) or isinstance(tg, bool):
            return err(tr("Invalid value: {0}", "target"))
        from ..accounts.orgs import _need_org_admin
        _need_org_admin(c, tg)  # 404 not a member, 403 not its admin: never into somebody else's organisation
        org = tg
    picks = {}
    for em, v in (b.get("people") or {}).items() if isinstance(b.get("people"), dict) else ():
        e = umz_pkey(em)
        if e and isinstance(v, dict):
            picks[e] = {"share": v.get("share") is True, "invite": v.get("invite") is True, "email": _email(v.get("email"))
                        or (_email(em) if "@" in str(em) else "")}
    c.rollback()
    _set(uid, iid, state="running", progress={"done": 0, "total": 1}, target=org)
    try:
        _thread(uid, umz_run, iid, {"org": org, "people": picks, "can_invite": bool(g.user["is_admin"])})
    except Denied:
        _set(uid, iid, state="preview")
        raise
    return jsonify(_view(uid, iid, _st(uid, iid))), 202


@app.post("/api/account/import/<iid>/key")
def umz_key_route(iid):
    """{recovery_key}: opens an uploaded organisation export (Settings > Organisation > Encryption of the source server).
    Wrong keys answer later in the state (key_error); after UMZ_KEY_TRIES the upload is removed."""
    umz_person()
    uid = me()
    st = _need(uid, iid)
    if st.get("state") != "key":
        return err(tr("The file is not ready for the import"), 409)
    from ..core.orgcrypt import oc_parse_recovery
    try:
        okey = oc_parse_recovery(body().get("recovery_key"))
    except ValueError:
        return err(tr("This is not a recovery key (52 characters A-Z and 2-7, in groups of 4)."))
    _set(uid, iid, state="checking")
    try:
        _thread(uid, umz_unlock, iid, okey, bool(g.user["is_admin"]))
    except Denied:
        _set(uid, iid, state="key")
        raise
    return jsonify(_view(uid, iid, _st(uid, iid))), 202


@app.delete("/api/account/import/<iid>")
def umz_cancel(iid):
    """Cancels the upload / preview: the file is removed at once (not while the run is writing)."""
    umz_person()
    uid = me()
    st = _need(uid, iid)
    if st.get("state") in ("checking", "running") and _busy(uid):
        return err(tr("An import is already running"), 409)
    _drop(uid, iid)
    return jsonify(ok=True)

