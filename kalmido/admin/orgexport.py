"""2.42.0 (#833): organisation export, stage 1 -- one organisation as an encrypted archive.

An admin of the organisation (Settings > Organisation, people only: agents and tokens never) starts it; a background thread
collects the organisation's data into a ZIP and encrypts it on the fly (the plain ZIP never touches the disk), the file waits
OX_KEEP_H hours below the data folder (exports/<org id>/, not in the backups) and is removed by the watchdog after that.

What belongs to the organisation: its lists (lists.org_id, never inboxes) with sections, members, fields, tags, status
updates, links, milestones, history, project notes, project files, forms, playbooks and customer reports (2.81.0); every
task of those lists (subtasks, field values, dependencies, people, history; not the trash), their comments and
attachments, the time entries on those lists, the team chat channels of those lists, its calendars (ev_cals.org_id) with
their events, its address books (books.org_id) with their contacts, its clients and the whole office (master data,
documents with positions, payments, the office log, the archive and every file below OFFICE_DIR/<org id>) and its members
with their roles. Never: private lists (org_id NULL) and other organisations, passwords, sessions, tokens, two-factor
data, push subscriptions, webhook secrets, connection credentials (OX_SECRET_COLS is dropped from every row as a second
floor), people's own tags and settings.

Fields and files that the server encrypts with the organisation's key (core/orgcrypt.py) are decrypted into the archive;
browser-encrypted content (attachments.enc, task_enc_notes) stays ciphertext -- only its author can open it -- and is listed
in the manifest under client_encrypted.

File format (tools/kalmido_export_decrypt.py reads it):
    OX_MAGIC | header length (4 bytes, big endian) | header (JSON, UTF-8) | blocks
    header = {format, v, org_id, org, created_at, kalmido_version, alg: "AES-256-GCM", block, nonce_prefix, wrapped_fk}
    wrapped_fk = base64(nonce 12 | AES-GCM(org key, file key 32 bytes, aad = OX_FK_AAD + org id))
    block i = AES-GCM(file key, nonce = nonce_prefix (8 bytes) | i (4 bytes BE), plaintext <= block bytes,
                      aad = SHA-256(magic | length | header) | i (8 bytes BE) | last (1 byte))
Every block but the last holds exactly `block` bytes; the last one (maybe empty) carries the marker, so cutting, dropping or
reordering blocks fails the authentication. The organisation's recovery key (Settings > Organisation > Encryption) opens the
archive on any machine: 2.138.0 C (#1972) the header carries recovery_wrapped (the org key wrapped with the recovery key
valid at the time of the export, core/orgcrypt.py rck_wrap); a recovery key of the earlier format is the org key itself."""
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import struct
import threading
import time
import unicodedata
import zipfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from flask import g, jsonify, send_file

from .exportleft import left_lines  # 2.362.4 (#3107)
from .oilock import oil_export_keys  # #4300
from ..core.config import app, APP_VERSION, ATT_DIR, DB, OFFICE_DIR
from ..core.db import connect, db, err, iso, now_utc
from ..core.pg import qi, system_ctx, table_names
from ..core.objcomments import ocm_note_cols, ocm_old_cols, ocm_video_cols  # 2.972.0 (#5272); 2.981.0 (#5273): + video / note
from ..docs.store import doc_open as _doc_open  # 2.981.0 (#5273): the notes on documents (obj_comments kind doc_note)
from ..core.i18n import N_, lang, tr
from ..core.access import Denied, live_sql, otr_live
from ..accounts.pictures import list_icon_path, org_icon_path, org_icon_tok  # 2.363.2 (#3106)
from ..accounts.session import me
from ..lists.listhead import o3c_head_rel  # 2.363.2 (#3106)
from ..core.orgcrypt import OrgCryptError, _org_admin, oc_dec, oc_dec_row, oc_enabled, oc_read_file, oc_status  # 2.149.0 G (#2517): pulled up from functions
from ..files.scan import sc_locked_all  # 2.209.0 D (#1856)
from .offsite import stepup_download  # 2.223.2 C (#2871): the step-up before a download
from ..accounts.orgretain import odl_ids  # 2.278.0 A (#3093)
from ..hub.hubmail import hbm_can  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgs import _need_org_admin, org_role  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgretain import odl_admin_export  # 2.369.5 (#2517): pulled up from functions
from ..office.ledger import ofx_log  # 2.369.5 (#2517): pulled up from functions
from ..accounts.bgjobs import bgj_add, bgj_busy, bgj_drop, bgj_fn  # 2.370.3 (#2760)

EXPORT_DIR = os.environ.get("TASKS_EXPORT_DIR", os.path.join(os.path.dirname(DB), "exports"))
OX_KEEP_H = 24  # a finished archive waits this long, then the watchdog removes it
PART_STALE_S = 6 * 3600  # 2.148.1 C (#2482): an unfinished export file older than this is left over (runs end long before)
OX_MAGIC = b"KALMIDO-ORGX\n"
OX_FORMAT = 1
OX_BLOCK = 1 << 20  # 1 MiB of plaintext per block
OX_FK_AAD = b"kalmido-orgx-fk|1|"
OX_SUFFIX = ".kalmido-export"
OX_PAGE = 1000  # rows per query of the big tables (keyset paging)
# 2.362.2 (#3099): without a server key nothing here is encrypted, so the archive is a plain ZIP (mode 0600) with a warning, not a 409
OX_PLAIN_SUFFIX = ".zip"
OX_FILES = (OX_SUFFIX, OX_PLAIN_SUFFIX)
# never in an archive, whatever table they are in (credentials, secrets, hashes of them, push keys, 2FA)
OX_SECRET_COLS = frozenset((
    "password_hash", "password", "pw_hash", "pw_rev", "token", "token_hash", "secret", "hook_secret", "totp_secret", "totp_step",
    "drop_token", "ical_token", "drop_token_hash", "ical_token_hash", "p256dh",  # 2.138.0 C (#1907): the hashes too
    "auth", "code_hash", "webauthn_handle", "oidc_subject", "proxy_login", "endpoint",
    "etags", "api_key", "access_token", "refresh_token",
    "hint",  # 2.55.0 (#1455): the last characters of a newsletter connection's access data (nl_conns)
    "email_seal", "email_key",  # 2.360.2 M (#2561): sealed with this server's key (sheet_shares)
    "confirm_hash", "cancel_hash"))  # 2.362.0 (#3096): the links of a booking (appt_bookings)

_OX = {}  # org id -> the running thread
_OX_LOCK = threading.Lock()


# ---------------------------------------------------------------- the encrypted stream
class OxWriter:
    """A write-only stream (zipfile writes into it): AES-256-GCM in OX_BLOCK blocks into the file f. No tell()/seek(), so
    zipfile streams with data descriptors and nothing is held back. finish() writes the last block (with its marker)."""

    def __init__(self, f, key, prefix, hhash):
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        self.f, self.aes, self.prefix, self.hhash = f, AESGCM(key), prefix, hhash
        self.buf, self.n, self.size = bytearray(), 0, 0

    def write(self, b):
        self.buf += b
        while len(self.buf) > OX_BLOCK:  # strictly more: the last block always gets the rest (also exactly OX_BLOCK)
            self._emit(bytes(self.buf[:OX_BLOCK]), False)
            del self.buf[:OX_BLOCK]
        return len(b)

    def flush(self):
        pass

    def finish(self):
        self._emit(bytes(self.buf), True)
        self.buf = bytearray()

    def _emit(self, chunk, last):
        if self.n >= 1 << 32:
            raise ValueError("archive too large")
        nonce = self.prefix + struct.pack(">I", self.n)
        ct = self.aes.encrypt(nonce, chunk, self.hhash + struct.pack(">QB", self.n, 1 if last else 0))
        self.f.write(ct)
        self.n += 1
        self.size += len(ct)


def ox_header(oid, org_name, okey, created_at, recovery_wrapped=None):
    """(header bytes incl. magic + length, file key, nonce prefix). 2.138.0 C (#1972): + recovery_wrapped when given."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    fk, prefix, n = os.urandom(32), os.urandom(8), os.urandom(12)
    wrapped = n + AESGCM(okey).encrypt(n, fk, OX_FK_AAD + str(int(oid)).encode())
    head = json.dumps({"format": "kalmido-org-export", "v": OX_FORMAT, "org_id": int(oid), "org": org_name, "created_at": created_at,
                       "kalmido_version": APP_VERSION, "alg": "AES-256-GCM", "block": OX_BLOCK,
                       "nonce_prefix": base64.b64encode(prefix).decode(), "wrapped_fk": base64.b64encode(wrapped).decode(),
                       **({"recovery_wrapped": recovery_wrapped} if recovery_wrapped else {})},
                      ensure_ascii=False, sort_keys=True).encode()
    return OX_MAGIC + struct.pack(">I", len(head)) + head, fk, prefix


# ---------------------------------------------------------------- what goes into the archive
def _jdef(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(v)).decode()
    return str(v)


# 2.455.0 (#3469): what makes a feed's address a secret (a private feed): a query parameter or a path of the known forms; rss_url refuses user:password@ already
OX_FEED_KEY_RE = re.compile(r"[?&;](?:[\w.-]*(?:token|key|secret|auth|pass|password|pwd|sig|signature|session|hash|code)[\w.-]*)="
                            r"|/(?:private-|secret:)|/[0-9a-f]{32,}(?:[/?.]|$)", re.I)


def _ox_dec_row(c, oid, table, row):
    """The row with every field the server encrypted with the organisation key in plain text (core/orgcrypt.py)."""
    if table.startswith("doc_") and row.get("ws"):  # 2.48.0 (#1111): documents seal with the workspace in the context (docs/store.py)
        from ..docs.store import doc_open
        for k, v in list(row.items()):
            if isinstance(v, str) and v.startswith("kenc1:"):
                row[k] = doc_open(c, row["ws"], f"{table}.{k}", v, default=None)
    row = oc_dec_row(c, oid, table, row)  # the protected columns (core/orgcrypt.py FIELDS; office_doc_items: cost from cost_enc)
    for k, v in list(row.items()):  # a second floor: any other value with the field prefix
        if isinstance(v, str) and v.startswith("kenc1:"):
            row[k] = oc_dec(c, oid, f"{table}.{k}", v)
    row.pop("cost_enc", None)
    if table == "sched_poll_votes":  # 2.380 (#2398 review): a voter's edit key hash and address hash never leave (kept empty: required columns)
        row.update(edit_hash="", ip_hash="")
    if table == "office_privacy_sheets":  # 2.363.2 (#3106): the mail code of a sheet is a key (sealed, its hash): the target makes a new one
        row.update(code="", code_hash="")
    if table == "appt_bookings":  # 2.362.0 (#3096): the booking customer's address on the network is no business record
        row.pop("ip", None)
    if table == "portal_tickets":  # 2.81.0 (#1866): sealed with the server key -> plain inside the encrypted archive; the
        from ..accounts.login import unseal  # keyed hash only works on this server (token / token_hash: OX_SECRET_COLS)
        try:
            row["email"] = unseal(c, "portal-email", row["email"]) if row.get("email") else ""
        except Exception:  # noqa: BLE001  (sealed under an older server key: leave the address out, not the export)
            row["email"] = ""
        row.pop("email_hash", None)
    if table == "doc_rules":  # 2.581.0 (#4803 review): a flow's webhook secret (and its address, a key itself for many services, like the
        # webhooks table) never leave; the import takes no webhook / notify anyway (docs/rules.py clean_rule without extra)
        try:
            fl = json.loads(row["data"]) if isinstance(row.get("data"), str) else row.get("data")
        except ValueError:
            fl = None
        if isinstance(fl, dict):
            for k in ("hook_secret", "webhook"):
                fl.pop(k, None)
            row["data"] = json.dumps(fl, ensure_ascii=False)
        elif row.get("data") is not None:
            row["data"] = None  # not readable as a flow: nothing of it goes out
    if table in OX_PART_COLS:  # 2.959.0 (#4031): the plain parts (the organisation's field schema)
        row = {k: row.get(k) for k in OX_PART_COLS[table]}
    if table == "templates":  # 2.905.0 (#5288): what a template keeps on this server only (people, sealed file copies; lists/tplextra.py)
        row["extra"] = "{}"
    if table == "rss_feeds":  # 2.455.0 (#3469): the feed stays visible by its title, never its key; the import takes none without address
        if OX_FEED_KEY_RE.search(row.get("url") or ""):
            row["url"] = ""
        for k in ("etag", "last_modified", "last_fetch", "last_ok", "last_error", "fails"):
            row.pop(k, None)
    return row


# 2.959.0 (#4031): the columns of the plain parts -- what the part is, never the table's internals (organisation, owner, times):
# the import (admin/oi_team.py) reads them so, whatever table holds them later
OX_PART_COLS = {"org_fields": ("id", "key", "name", "type", "options", "sort")}


# 2.763.0 (#5269): the column a reaction's target had in the archive before the core's table (the import reads it so, old archives too)
OX_RX_COL = {"comment": "comment_id", "tchat": "message_id"}


def _clean(c, oid, table, r):
    row = {k: v for k, v in dict(r).items() if k not in OX_SECRET_COLS}
    if table == "obj_reactions":
        row[OX_RX_COL[row.pop("target_kind")]] = row.pop("target_id")
    if table == "obj_tags":  # 2.947.0 (#5275): the columns of list_tags / the labels' file
        k, v = row.pop("scope_kind"), row.pop("scope_id")
        row.pop("created_by", None)
        if k == "list":
            row["list_id"] = int(v)
            row.pop("org_id", None)
    if table == "obj_versions":  # 2.958.0 (#5281) / 2.977.0 (#5282): the old table's columns (an older archive reads the same)
        return ox_objv_row(c, oid, row)
    if table == "obj_tag_links":  # 2.947.0 (#5275): the columns of task_list_tags (+ when and how it was set)
        row["task_id"] = row.pop("obj_id")
        row.pop("kind", None)
        row.pop("created_by", None)
    if table == "obj_comments" and "ws" in row:  # 2.981.0 (#5273): a document's note, sealed with its workspace (as doc_notes was)
        row["text"] = _doc_open(c, row["ws"], "doc_notes.text", row["text"], default=None) if row.get("text") else row.get("text")
    if table == "obj_follow":  # 2.972.0 (#5285): tasks/watchers.json as before (task_id, user_id, created_at)
        row = {"task_id": row["ref_id"], "user_id": row["user_id"], "created_at": row["created_at"]}
    row.pop("legacy_aad", None)  # 2.278.0 C (#3091): a person's own move detail (old AAD), not the organisation's
    return _ox_dec_row(c, oid, table, row)


def ox_objv_row(c, oid, row):
    """2.977.0 (#5282): a row of the core's versions (obj_versions) as the archive file of its kind has it since before the core:
    wiki/versions.json the columns of wiki_versions (2.958.0, #5281), lists/playbooks.json those of playbooks (list_id, owner_id,
    folder, version, body, source, author_id = 0 for an author who is gone, created_at), office/procdocs.json those of office_procdocs (org_id, version, data
    = the JSON text, created_by, created_at). The sealed text opened first (its context is obj_versions.body)."""
    row = _ox_dec_row(c, oid, "obj_versions", row)
    kind = row.get("kind")
    if kind == "playbook":
        h = c.execute("SELECT list_id, owner_id, folder FROM playbooks WHERE id=?", (row["ref_id"],)).fetchone()
        return {"id": row["id"], "list_id": h["list_id"] if h else None, "owner_id": h["owner_id"] if h else None,
                "folder": h["folder"] if h else None, "version": row["no"], "body": row["body"], "source": row.get("source") or "edit",
                # Fable review F1: an author who is gone (NULL, foreign) is 0 in the file -- NULL there means the owner's own text
                "author_id": row["created_by"] if row["created_by"] is not None else 0, "created_at": row["created_at"]}
    if kind == "procdoc":
        return {"id": row["id"], "org_id": row["org_id"], "version": row["no"], "data": row["body"] or "{}",
                "created_by": row["created_by"], "created_at": row["created_at"]}
    row["page_id"], row["path"] = row.pop("ref_id"), row.pop("title")
    for k in ("kind", "no", "held_at", "source"):
        row.pop(k, None)
    return row


def _table_cols(c, table):
    return {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?", (table,))}


# 2.972.0 (#5272): tables whose file keeps the columns of the table before the core's (comments.json: task_id, reply_to,
# mentions as csv, suggestion / choices / choice / portal / rule_name), so older and newer archives read alike
OX_COLS = {"obj_comments": ocm_old_cols()}
# 2.981.0 (#5273): the other kinds of obj_comments keep the files and columns of their old tables (videos/comments.json:
# video_comments, documents/notes.json: doc_notes) -- chosen by the kind the where of the entry starts with
OX_KIND_COLS = {"kind='video'": ocm_video_cols("obj_comments"), "kind='doc_note'": ocm_note_cols("obj_comments")}


def _ox_cols(table, where):
    """2.981.0 (#5273): the column list of an archive entry (OX_COLS, OX_KIND_COLS), '*' for every other table."""
    if table == "obj_comments":
        k = next((x for x in OX_KIND_COLS if where.lstrip("(").startswith(x)), None)
        if k:
            return OX_KIND_COLS[k]
    return OX_COLS.get(table, "*")


def _rows(c, oid, table, where, args, paged=True):
    """Every row of table matching where (keyset pages on id when the table has one: big tables never sit in memory whole)."""
    cols, names = _ox_cols(table, where), table_names(c)  # 2.972.0 (#5272): a touched place takes qi() (#5296); 2.981.0: _ox_cols
    if paged and "id" in _table_cols(c, table):
        last = None
        while True:
            q = f"SELECT {cols} FROM {qi(table, names)} WHERE ({where})" + (" AND id>?" if last is not None else "") + f" ORDER BY id LIMIT {OX_PAGE}"
            rs = c.execute(q, (*args, last) if last is not None else tuple(args)).fetchall()
            for r in rs:
                yield _clean(c, oid, table, r)
            if len(rs) < OX_PAGE:
                return
            last = rs[-1]["id"]
    else:
        for r in c.execute(f"SELECT {cols} FROM {qi(table, names)} WHERE ({where})", tuple(args)).fetchall():
            yield _clean(c, oid, table, r)


LSQ = f"SELECT id FROM lists WHERE org_id=? AND is_inbox=0 AND {otr_live('')}"  # 2.102.0 A (#1988): not the list trash
TSQ = f"SELECT id FROM tasks WHERE list_id IN ({LSQ}) AND deleted_at IS NULL"  # 2.223.3 B (#2879): not the task trash
DSQ = "SELECT id FROM office_docs WHERE org_id=?"
# 2.362.0 (#3092): the organisation's channels (kind 'channel') the exporting admin reads in the app: the open ones (ox_csq: + the
# ones they are a member of); RSQ = every team chat room of the archive (+ the channels of the lists of LSQ)
CSQ = "SELECT id FROM tchat_rooms WHERE kind='channel' AND org_id=? AND is_open=1 AND archived_at IS NULL"
RSQ = f"SELECT id FROM tchat_rooms WHERE (kind='list' AND list_id IN ({LSQ})) OR id IN ({CSQ})"
# 2.362.0 (#3096): the booking pages billed by the organisation's office (a business record); ox_apq: + the exporting admin's
# own page on a calendar of the organisation (another member's bookings only their owner reads in the app: calendars/apptbook.py)
APQ = "SELECT user_id FROM appt_pages WHERE office_org_id=?"
# (archive name, table, where; every "?" is the organisation id) -- the order of the archive
OX_AREAS = (
    ("lists.json", "lists", f"id IN ({LSQ})"),  # 2.223.3 B (#2879, #2880): the lists of LSQ (ox_lsq), not the trash
    ("lists/sections.json", "sections", f"list_id IN ({LSQ})"),
    ("lists/views.json", "filters", f"list_id IN ({LSQ})"),  # 2.577.0 (#3356): the shared views of a project (a private filter has no list_id)
    ("lists/members.json", "list_members", f"list_id IN ({LSQ})"),
    ("lists/fields.json", "list_fields", f"list_id IN ({LSQ})"),
    # 2.947.0 (#5275): the project tags are rows of the core (obj_tags scope list); the file keeps list_id (_clean)
    ("lists/tags.json", "obj_tags", f"scope_kind='list' AND scope_id IN (SELECT CAST(x.id AS TEXT) FROM ({LSQ}) x)"),
    ("org/labels.json", "obj_tags", "scope_kind='org' AND org_id=?"),  # 2.947.0 (#5275): the labels of the organisation (was #4031)
    ("lists/status.json", "list_status", f"list_id IN ({LSQ})"),
    ("lists/links.json", "list_links", f"list_id IN ({LSQ})"),
    ("lists/notepads.json", "list_notepads", f"list_id IN ({LSQ})"),  # 2.43.0 (#1346): notepads on the project page
    ("lists/milestones.json", "list_milestones", f"list_id IN ({LSQ})"),
    ("lists/rules.json", "list_rules", f"list_id IN ({LSQ})"),  # 2.71.0 A (#1457)
    ("lists/history.json", "list_activity", f"list_id IN ({LSQ})"),
    ("lists/notes.json", "notes", f"list_id IN ({LSQ})"),
    ("lists/files.json", "list_files", f"list_id IN ({LSQ})"),
    ("lists/forms.json", "forms", f"list_id IN ({LSQ})"),
    ("lists/form_entries.json", "form_entries", f"form_id IN (SELECT id FROM forms WHERE list_id IN ({LSQ}))"),  # 2.137.0 C (#2344): answers of form entries
    # 2.977.0 (#5282): the versions are rows of the core's obj_versions on the Playbook's head; the file keeps its columns (_clean)
    ("lists/playbooks.json", "obj_versions", f"kind='playbook' AND ref_id IN (SELECT id FROM playbooks WHERE list_id IN ({LSQ}))"),
    ("lists/sprints.json", "sprints", f"list_id IN ({LSQ})"),  # 2.137.0 C (#2344): sprints of the lists (tasks.sprint_id)
    # 2.905.0 (#5288, rest of #4031): the organisation's templates -- task, project and section templates, one kind of the core
    # (was lists/section_templates.json, 2.362.0 #3096; an older archive's file is still read by the import), not the trash
    ("lists/templates.json", "templates", f"org_id=? AND {live_sql()}"),
    ("lists/ticket_types.json", "ticket_types", "org_id=?"),  # 2.609.0 (#3372): the organisation's own ticket types
    # 2.959.0 (#4031): the organisation's field schema (lists/orgfields.py; list_fields.org_field_id names a row of it), a plain
    # part (OX_PART_COLS: no table internals)
    ("lists/org_fields.json", "org_fields", "org_id=?"),
    # 2.81.0 (#1866): customer reports of those lists (team/portal.py): the address in plain text, never the status link
    ("portal/tickets.json", "portal_tickets", f"list_id IN ({LSQ})"),
    ("lists/admin_log.json", "org_list_log", "org_id=?"),
    ("tasks.json", "tasks", f"list_id IN ({LSQ})"),
    ("tasks/dependencies.json", "task_deps", f"task_id IN ({TSQ})"),
    ("tasks/relations.json", "task_relations", f"task_id IN ({TSQ}) AND other_id IN ({TSQ})"),  # 2.576.0 (#3371): both tasks of the organisation
    ("tasks/field_values.json", "task_field_values", f"task_id IN ({TSQ})"),
    # 2.947.0 (#5275): the tags of the tasks (a project tag or a label, tag_id = its id in lists/tags.json / org/labels.json); the
    # file keeps task_id (_clean); a link to a tag of another project (the task moved since) stays out, as the app shows none
    ("tasks/tags.json", "obj_tag_links", f"""kind='task' AND obj_id IN ({TSQ}) AND tag_id IN (SELECT id FROM obj_tags WHERE (scope_kind='list'
     AND scope_id IN (SELECT CAST(x.id AS TEXT) FROM ({LSQ}) x)) OR (scope_kind='org' AND org_id=?))"""),
    ("tasks/people.json", "task_people", f"task_id IN ({TSQ})"),
    # 2.473.0 (#3357); 2.972.0 (#5285): rows of the core's obj_follow (mode watch), the file keeps its columns (_clean)
    ("tasks/watchers.json", "obj_follow", f"kind='task' AND mode='watch' AND ref_id IN ({TSQ})"),
    ("tasks/links.json", "task_links", f"task_id IN ({TSQ})"),  # 2.137.0 C (#2344): a task placed in a further list
    ("tasks/decisions.json", "task_decisions", f"task_id IN ({TSQ})"),  # 2.392.0 C (#3370)
    # 2.654.0 (#4585): where a task came from in a quotation (office/offertasks.py); the import maps task, list, quotation and the
    # position key (admin/oi_office.py _p_offer_link), so the moved positions stay linked and are not offered as new again
    ("tasks/offer_links.json", "task_offer_links", f"task_id IN ({TSQ})"),
    ("tasks/history.json", "activity", f"task_id IN ({TSQ})"),
    ("tasks/encrypted_notes.json", "task_enc_notes", f"task_id IN ({TSQ})"),  # 2.42.0 (#828, agent A): browser-encrypted, as stored
    ("tasks/locked_notes.json", "task_note_locks", f"task_id IN ({TSQ})"),  # 2.48.0 (#1642): locked notes, browser-encrypted, as stored
    ("time_entries.json", "time_entries", f"list_id IN ({LSQ})"),
    ("time_sheets.json", "time_sheets", "org_id=?"),  # 2.137.0 C (#2344): monthly timesheets (note decrypted like the others)
    ("comments.json", "obj_comments", f"kind='task' AND ref_id IN ({TSQ})"),  # 2.972.0 (#5272): the core's rows, the old columns (OX_COLS)
    # 2.763.0 (#5269): the reactions are rows of the core (obj_reactions); the file keeps its columns (_clean: comment_id), a
    # comment in the trash leaves its reactions out (as OX_GONE_WITH did)
    ("comments/reactions.json", "obj_reactions",
     f"target_kind='comment' AND target_id IN (SELECT id FROM obj_comments WHERE kind='task' AND ref_id IN ({TSQ}) AND {live_sql()})"),
    ("attachments.json", "attachments", f"task_id IN ({TSQ})"),
    # 2.48.0 (#1207): the organisation's file store (folders, files, versions, shares, history)
    # 2.223.3 B (#2879): without the trash (ox_live, ox_dead_nodes)
    # 2.353.0 C (#2829): with the knowledge tree (root, empty folders, order, folder shares, page nodes, files put there
    # under 2.199) and the marks of the areas' roots (store/area_roots.json): the import puts a root into the target's own
    # root of that area (admin/oi_store.py), never a second one; an older archive without them still rebuilds from the paths
    ("store/nodes.json", "fs_nodes", "org_id=?"),
    ("store/area_roots.json", "fs_area_roots", "org_id=? AND node_id IS NOT NULL"),
    ("store/versions.json", "fs_versions", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)"),
    ("store/locks.json", "fs_locks", "org_id=? AND e2e IS NOT NULL"),  # #4300 (the exporting person's own key: store/lock_keys.json, ox_build)
    ("store/shares.json", "fs_shares", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)"),
    ("store/history.json", "fs_log", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)"),
    # 2.362.0 (#3092): + the organisation's channels (CSQ), their members and the files of the messages (bytes under files/tchat/)
    # 2.924.0 (#5069): the members are the shares of the channel's node (store/nodes.json + store/shares.json; tchat_members is
    # gone, chat/members.json only comes from older archives: admin/oi_team.py _room_member)
    ("chat/channels.json", "tchat_rooms", f"id IN ({RSQ})"),
    ("chat/messages.json", "tchat_msgs", f"room_id IN ({RSQ})"),
    ("chat/reactions.json", "obj_reactions",  # 2.137.0 C (#2344); 2.763.0 (#5269): rows of the core, the file keeps message_id
     f"target_kind='tchat' AND target_id IN (SELECT id FROM tchat_msgs WHERE room_id IN ({RSQ}) AND {live_sql()})"),
    ("chat/files.json", "tchat_files", f"room_id IN ({RSQ})"),
    ("calendars.json", "ev_cals", "org_id=?"),
    # 2.924.0 (#5069): calendars/members.json and books/members.json are no more: the members of a calendar / an address book
    # are the shares of its reference node (store/nodes.json + store/shares.json); an older archive with them still imports
    ("events.json", "events", "cal_id IN (SELECT id FROM ev_cals WHERE org_id=?)"),
    ("events/attendees.json", "event_attendees", "event_id IN (SELECT id FROM events WHERE cal_id IN (SELECT id FROM ev_cals WHERE org_id=?))"),
    ("books.json", "books", "org_id=?"),
    ("books/contacts.json", "contacts", "book_id IN (SELECT id FROM books WHERE org_id=?)"),
    # 2.362.0 (#3096): contacts on tasks of the lists (waiting for / responsible / about)
    ("books/contact_tasks.json", "contact_tasks", f"contact_id IN (SELECT id FROM contacts WHERE book_id IN (SELECT id FROM books WHERE org_id=?)) AND task_id IN ({TSQ})"),
    # 2.362.0 (#3096): the booking pages on a calendar of the organisation (or billed by its office), their kinds of appointment
    # and bookings (the customers' data; never the confirm / cancel links); the booked appointments are events of the calendar
    ("bookings/pages.json", "appt_pages", f"user_id IN ({APQ})"),
    ("bookings/types.json", "appt_types", f"user_id IN ({APQ})"),
    ("bookings/bookings.json", "appt_bookings", f"user_id IN ({APQ})"),
    # 2.55.0 (#1455): the newsletter connection (its column "secret" never: see the list above), segments, members, log
    ("newsletter/connection.json", "nl_conns", "org_id=?"),
    ("newsletter/segments.json", "nl_segments", "org_id=?"),
    ("newsletter/members.json", "nl_members", "org_id=?"),
    ("newsletter/runs.json", "nl_runs", "org_id=?"),
    # 2.362.0 (#3096): the suppression list and the consent log (hashes of the addresses): an unsubscription survives the move
    ("newsletter/suppressed.json", "nl_suppress", "org_id=?"),
    ("newsletter/consent_log.json", "nl_consent_log", "org_id=?"),
    ("clients.json", "clients", "org_id=?"),
    ("office/company.json", "office_company", "org_id=?"),
    ("office/bank_accounts.json", "office_bank_accounts", "org_id=?"),  # 2.470.0 (#3596)
    ("office/settings.json", "office_settings", "org_id=?"),
    ("office/services.json", "office_services", "org_id=?"),
    ("office/roles.json", "office_roles", "org_id=?"),  # 2.47.0 (#1649): Freelancer-Rollen + Drehpersonal (costs decrypted like the others)
    ("office/equipment.json", "office_equipment", "org_id=?"),
    ("office/packages.json", "office_sets", "org_id=?"),
    ("office/texts.json", "office_texts", "org_id=?"),
    ("office/contracts.json", "office_contracts", "org_id=?"),
    ("office/contract_files.json", "office_contract_files", "org_id=?"),  # 2.117.0 B (#2285): the files themselves come with OFFICE_DIR
    ("office/client_contacts.json", "office_client_contacts", "org_id=?"),
    ("office/numbers.json", "office_numbers", "org_id=?"),
    ("office/documents.json", "office_docs", "org_id=?"),
    ("office/document_items.json", "office_doc_items", f"doc_id IN ({DSQ})"),
    ("office/document_parts.json", "office_doc_parts", "org_id=?"),  # 2.47.0 (#1215): the parts of quotations
    ("office/purchases.json", "office_purchases", "org_id=?"),  # 2.47.0 (#1649): purchase of accepted quotations (amount decrypted)
    ("office/invoice_series.json", "office_inv_series", "org_id=?"),  # 2.91.0 A (#1923): invoice series (template, interval, next period)
    ("office/payments.json", "office_payments", "org_id=?"),
    ("office/pay-props.json", "office_pay_props", "org_id=?"),  # 2.51.0 (#1350): agents' payment match proposals
    ("office/signoffs.json", "office_signoffs", "org_id=?"),  # 2.50.0 (#1200): approval links + protocol (the token never)
    ("office/trips.json", "office_trips", "org_id=?"),  # 2.47.3 (#1022): travel expenses (decrypted like the others)
    ("office/trip_items.json", "office_trip_items", "org_id=?"),
    ("office/trip_purposes.json", "office_trip_purposes", "org_id=?"),  # 2.117.0 A (#2292): own purposes of trips
    ("office/cashbooks.json", "office_cashbooks", "org_id=?"),  # 2.121.0 B (#2095): the cash book (boxes, entries, closings, log)
    ("office/cash_entries.json", "office_cash_entries", "org_id=?"),
    ("office/cash_closings.json", "office_cash_closings", "org_id=?"),
    ("office/cash_log.json", "office_cash_log", "org_id=?"),
    ("office/period_locks.json", "office_period_locks", "org_id=?"),  # 2.148.0 A (#2471): locked accounting periods
    # 2.148.0 C (#2472): versions of the procedure documentation; 2.977.0 (#5282): rows of the core's obj_versions, the file keeps its
    # columns (_clean)
    ("office/procdocs.json", "obj_versions", "kind='procdoc' AND org_id=?"),
    ("office/suppliers.json", "office_suppliers", "org_id=?"),  # 2.148.0 D (#2458): creditors of the DATEV import
    ("office/opening_balances.json", "office_opening_balances", "org_id=?"),  # 2.148.0 D (#2458)
    ("office/ledger_entries.json", "office_ledger_entries", "org_id=?"),  # 2.666.0 (#3461): adjusting / opening entries of the balance sheet
    # 2.414.0 (#3502): the booking archive (the files bka-* come with OFFICE_DIR)
    ("office/bookarch_files.json", "office_bookarch_files", "org_id=?"),
    ("office/bookarch.json", "office_bookarch", "org_id=?"),
    ("office/bookarch_accts.json", "office_bookarch_accts", "org_id=?"),
    ("office/bookarch_docs.json", "office_bookarch_docs", "org_id=?"),
    ("office/datev_guids.json", "office_datev_guids", "org_id=?"),  # 2.188.0 A (#2498): kept GUIDs of the DATEV receipt images
    ("office/rights_groups.json", "office_rgroups", "org_id=?"),  # 2.187.0 C (#2476): office rights: own groups, memberships, log
    ("office/rights_members.json", "office_rgroup_members", "org_id=?"),
    ("office/rights_log.json", "office_rights_log", "org_id=?"),
    ("office/meals.json", "office_meals", "org_id=?"),  # 2.119.0 A (#2288): entertainment receipts (the bills come with OFFICE_DIR)
    ("office/meal_files.json", "office_meal_files", "org_id=?"),
    ("office/meal_choices.json", "office_meal_choices", "org_id=?"),
    ("office/meal_log.json", "office_meal_log", "org_id=?"),
    ("office/fixed_costs.json", "office_fixed_costs", "org_id=?"),  # 2.47.3 (#1652): fixed costs of the cash flow
    ("office/cashflow_start.json", "office_cf_start", "org_id=?"),  # 2.123.0 D (#2341): start balance, corrections, real balances
    ("office/cashflow_adjust.json", "office_cf_adjust", "org_id=?"),
    ("office/cashflow_actual.json", "office_cf_actual", "org_id=?"),
    ("office/bank_balances.json", "office_bank_balances", "org_id=?"),  # 2.124.0 D (#2342): balances of the imported statements
    # 2.137.0 A (#2344): the rest of the office (the statement imports the balances hang on, their bookings, document
    # templates and documents made from them, the logbook)
    ("office/bank_imports.json", "office_bank_imports", "org_id=?"),
    ("office/bank_tx.json", "office_bank_tx", "org_id=?"),
    ("office/bank_rules.json", "office_bank_rules", "org_id=?"),  # 2.299.0 B (#3191): bank rules, declined rule suggestions
    ("office/bank_rule_nos.json", "office_bank_rule_nos", "org_id=?"),
    ("office/bank_vendors.json", "office_bank_vendors", "org_id=?"),  # 2.425.0 B (#3451): recurring providers of the bank bookings
    ("office/cc_cards.json", "office_cc_cards", "org_id=?"),  # 2.444.0 (#3447): credit card statements
    ("office/cc_statements.json", "office_cc_statements", "org_id=?"),
    ("office/cc_lines.json", "office_cc_lines", "org_id=?"),
    ("office/doc_templates.json", "office_doc_templates", "org_id=?"),
    ("office/gen_docs.json", "office_gen_docs", "org_id=?"),
    ("office/privacy_sheets.json", "office_privacy_sheets", "org_id=?"),  # 2.154.0 C (#2192): data protection sheets of a client
    # 2.184.0 A (#2579): the correspondence (letters decrypted; their filed PDFs come with the documents space, store/)
    ("office/letters.json", "office_letters", "org_id=?"),
    ("office/letter_links.json", "office_letter_links", "org_id=?"),
    ("office/letter_blocks.json", "office_letter_blocks", "org_id=?"),
    ("office/letter_profiles.json", "office_letter_profiles", "org_id=?"),
    ("office/vehicles.json", "office_vehicles", "org_id=?"),
    ("office/drives.json", "office_drives", "org_id=?"),
    ("office/drive_log.json", "office_drive_log", "org_id=?"),
    ("office/drive_closed.json", "office_drive_closed", "org_id=?"),  # 2.362.0 (#3096): the closed months of the logbook (GoBD)
    ("office/sub_reminders.json", "office_sub_reminders", "org_id=?"),  # 2.91.0 B (#1924): reminder tasks before a subscription renews
    ("office/dunning_marks.json", "office_dunning_marks", "org_id=?"),  # 2.147.1 B (#2054): invoices + levels with a suggested reminder
    ("office/peppol_sends.json", "office_peppol_sends", "org_id=?"),  # 2.154.0 B (#1960): sends over Peppol (the connection + key stay)
    ("office/agreements.json", "office_agreements", "org_id=?"),  # 2.92.0 A (#1925): business contracts and insurances
    ("office/deals.json", "office_deals", "org_id=?"),  # 2.50.0 (#1196): the sales pipeline
    ("office/archive.json", "office_archive", "org_id=?"),
    ("office/archive-log.json", "office_archive_log", "org_id=?"),  # 2.81.0 B (#1834): the history of the archived documents
    ("office/pack-installs.json", "office_pack_installs", "org_id=?"),  # 2.76.0 review (N2): installed catalogue packs (data only)
    ("office/import_runs.json", "office_import_runs", "org_id=?"),
    ("office/log.json", "office_doc_log", "org_id=?"),
    ("wiki/pages.json", "wiki_pages", "org_id=?"),  # 2.49.0 (#1199): knowledge pages
    ("wiki/files.json", "wiki_files", "org_id=?"),  # 2.99.0 A (#2182): their PDFs and pictures (the bytes under files/wiki/)
    # 2.137.0 B (#2344): the history of the pages (texts decrypted); 2.958.0 (#5281): rows of the core's versions, the file keeps
    # its columns (_clean: page_id, path)
    # 2.977.0 (#5282): the versions of a page in the trash stay out with it (was OX_GONE_WITH, now three kinds share the table)
    ("wiki/versions.json", "obj_versions", "kind='wiki' AND org_id=? AND ref_id NOT IN (SELECT id FROM wiki_pages WHERE deleted_at IS NOT NULL)"),
    ("sheets/sheets.json", "sheets", "org_id=?"),  # 2.89.0 (#1916): tables with their columns, rows and cells
    ("sheets/columns.json", "sheet_columns", "sheet_id IN (SELECT id FROM sheets WHERE org_id=?)"),
    ("sheets/rows.json", "sheet_rows", "sheet_id IN (SELECT id FROM sheets WHERE org_id=?)"),
    ("sheets/cells.json", "sheet_cells", "sheet_id IN (SELECT id FROM sheets WHERE org_id=?)"),
    ("sheets/links.json", "sheet_links", "sheet_id IN (SELECT id FROM sheets WHERE org_id=?)"),  # 2.89.0 (#1916, D): carried over by button
    ("sheets/shares.json", "sheet_shares", "org_id=? AND email_key=''"),  # 2.124.0 C (#2113): single tables shared with people / agents; 2.360.2 M (#2561): not by address (a sealed address, the account behind it stays unnamed); 2.937.0 (#5244): empty since stage 7c (the shares travel as store/shares.json), read for older archives
    ("sheets/files.json", "sheet_files", "org_id=?"),  # 2.124.0 B (#2110): files of file cells (the rows; names, sizes)
    ("sheets/history.json", "sheet_hist", "sheet_id IN (SELECT id FROM sheets WHERE org_id=?)"),  # 2.124.0 B (#2112): cell history
    ("videos/reviews.json", "video_reviews", "org_id=?"),  # 2.99.1 A (#1959): video sign-offs (links only), versions, comments
    ("videos/versions.json", "video_versions", "org_id=?"),
    # 2.981.0 (#5273): the comments are rows of obj_comments (kind video), the file keeps its columns (OX_KIND_COLS); not those of
    # a review in the trash (was OX_GONE_WITH)
    ("videos/comments.json", "obj_comments", f"kind='video' AND org_id=? AND {live_sql()} AND ref_id NOT IN (SELECT id FROM video_reviews WHERE deleted_at IS NOT NULL)"),
    # 2.48.0 (#1111): documents (recognised text, amounts, sender names and rules decrypted); not the learnt models, not the
    # keyed word index (both are rebuilt from the documents), not the forwarding addresses (their token is a secret)
    ("documents/meta.json", "doc_meta", "org_id=?"),
    ("documents/senders.json", "doc_senders", "org_id=?"),
    ("documents/types.json", "doc_types", "org_id=?"),
    ("documents/tags.json", "doc_tags", "org_id=?"),
    ("documents/document_tags.json", "doc_node_tags", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)"),  # 2.122.0 B (#2099): + files / folders
    ("documents/fields.json", "doc_fields", "org_id=?"),  # 2.153.0 (#2179): custom fields + their values (decrypted)
    ("documents/field_values.json", "doc_field_values", "org_id=?"),
    ("documents/notes.json", "obj_comments", f"kind='doc_note' AND org_id=? AND {live_sql()}"),  # review 2.981 (Fable F6): not the notes in the trash; 2.635.0 (#4807 d): notes on documents (decrypted); 2.981.0 (#5273): obj_comments
    ("documents/rules.json", "doc_rules", "org_id=?"),
    ("documents/settings.json", "doc_cfg", "org_id=?"),
    ("documents/receipts.json", "rc_receipts", "org_id=?"),  # 2.137.0 B (#2344): project and category of receipts (set by people)
    ("hub/absences.json", "hub_absences", "org_id=?"),  # 2.50.0 (#1195): absences (kind + note decrypted like the others)
    ("hub/bookings.json", "hub_bookings", "org_id=?"),  # 2.50.0 (#1194): bookings of the disposition
    ("hub/callsheets.json", "hub_callsheets", "org_id=?"),  # 2.855.0 (#1956): call sheets of the shoot days (decrypted)
    ("hub/leave_quota.json", "hub_leave_quota", "org_id=?"),  # 2.125.0 A (#2117): vacation accounts
    ("hub/mails.json", "hub_mails", "org_id=?"),  # 2.84.0 A (#1198): filed e-mails (texts decrypted; not the addresses, not the word index)
    ("hub/mail_links.json", "hub_mail_links", "org_id=?"),  # 2.362.0 (#3096): the tasks / events made from a filed e-mail
    ("hub/mailbox.json", "hub_mailboxes", "org_id=?"),  # 2.144.5 B (#2410): the workspace mailbox (servers, user names, sender; never "secret")
    # 2.380 H (#2398): the organisation's scheduling polls (options, votes; never the link: the import makes a new one) and
    # bookmarks (their pictures under files/bookmarks/); a person's own ones (no organisation) go with the account export
    ("polls.json", "sched_polls", "org_id=?"),
    ("polls/options.json", "sched_poll_options", "poll_id IN (SELECT id FROM sched_polls WHERE org_id=? AND deleted_at IS NULL)"),
    ("polls/votes.json", "sched_poll_votes", "poll_id IN (SELECT id FROM sched_polls WHERE org_id=? AND deleted_at IS NULL)"),
    ("bookmarks.json", "bookmarks", "org_id=?"),
    # 2.455.0 (#3469): the organisation's feeds (the articles are fetched again; an address with an access key stays out: _ox_dec_row)
    # and its read-later project (the feeds of a project the admin does not see stay out with the project)
    ("feeds/feeds.json", "rss_feeds", "org_id=?"),
    ("feeds/reading.json", "reading_orgs", f"org_id=? AND list_id IN ({LSQ})"),
    # 2.575.0 (#3778): the module cards of the organisation and the members they are assigned to
    ("settings/module_cards.json", "module_cards", "org_id=?"),
    ("settings/module_card_people.json", "module_card_people", "card_id IN (SELECT id FROM module_cards WHERE org_id=?)"),
)
OX_NOT_INCLUDED = (
    N_("private lists and private sharing of the members (lists without the organisation), other organisations"),
    # 2.223.3 B (#2880): the same rule as in the app (accounts/orglists.py ol_shared)
    N_("lists of the organisation a member shares with nobody (each member exports them with the own account export)"),
    N_("deleted rows and files (the trash, undone entries)"),  # 2.223.3 B (#2879)
    N_("passwords, sessions, API tokens, app passwords, two-factor data, push subscriptions, webhooks and their secrets"),
    N_("connections with credentials (Git, Paperless, calendar and address book subscriptions, mail-in addresses, public links)"),
    # 2.380 H (#2398): the polls come along, their links do not
    N_("the links of the scheduling polls (the import makes new ones; the old links stop working)"),
    N_("personal data of the members: settings, own tags, filters, templates, habits, News, direct messages, agent chats"),
    # 2.362.0 (#3092): group conversations belong to their people like direct messages; channels like in the app (teamchan.py tcx_room_ok)
    N_("group conversations of the team chat (like direct messages they belong to their people, not to the organisation)"),
    N_("channels of the organisation that are not open and that the exporting admin is not a member of"),
    # 2.362.0 (#3096): what else stays out on purpose (OX_LEFT names every table with an organisation column that does)
    N_("notification channels (their targets are secrets), invitations and join requests, synchronisation data of calendar and task apps (CalDAV), groups of people and their shares"),
    N_("the articles of feeds (fetched again on the target) and feed addresses that carry an access key"),  # 2.455.0 (#3469)
    N_("booking pages of other members that the office does not bill (only their owner reads the bookings), archived channels"),
    # 2.190.0 D (#2561): the same rule as in the app (hub/hubmail.py hbm_can)
    N_("filed e-mails (and their files) the exporting admin cannot open in the app: other members' inboxes, projects without them"),
)

# 2.362.0 (#3096): every table with an organisation or a list column that is NOT in OX_AREAS, with the reason (the static guard
# tests/export_coverage_test.py fails on a new such table until it is in OX_AREAS or here -- so nothing goes missing silently)
_SECRET = "credentials or link secrets (not_included)"
_PERSONAL = "a person's own data (their account export)"
_DERIVED = "derived or working data, rebuilt on the target"
_SERVER = "state of this server (keys, jobs, scanner, queues)"
_AGENT = "agents and their logs (never in the organisation export)"
_ONLINEPAY = "the online provider's working data (the payments themselves are in the export)"
_LATER2 = "not yet in the export"  # follow-up task #3642: the 2.390 / 2.352 tables
OX_LEFT = {
    # organisation column
    "agents": _AGENT, "bg_jobs": _SERVER, "doc_mail": _SECRET, "doc_models": _DERIVED, "doc_flow_runs": _DERIVED, "file_text": _DERIVED,
    "doc_fetchers": "a person's receipt fetcher and its token (set up again on the target)", "doc_fetch_portals": _DERIVED,
    "fs_ext_links": _SECRET, "fs_upload_requests": _SECRET, "hub_tokens": _SECRET, "life_trip_costs": _PERSONAL,
    "merge_runs": _PERSONAL, "notify_channels": _SECRET, "support_grants": _SERVER, "office_peppol": _SECRET,
    "office_payonline": _SECRET, "office_pay_links": _SECRET, "office_pay_sessions": _ONLINEPAY, "office_pay_events": _ONLINEPAY, "office_pay_payouts": _ONLINEPAY,
    "office_trash": "the trash (not_included)",
    "org_invites": "invitations (not_included)", "org_joins": "join requests (not_included)",
    "org_keys": _SERVER, "org_members": "members.json (with the role)", "org_out_requests": "requests of one person, short-lived",
    "pl_imported": _SECRET, "pl_rules": _SECRET, "pl_sources": _SECRET, "pl_uploads": _SECRET, "portal_logins": _SECRET,
    "rc_suggest": _DERIVED, "time_wipes": _DERIVED,  # 2.530.0 B (#4315): the Undo copy of "Delete all times"
    "list_part_trash": _DERIVED,  # 2.567.0 A (#4707): the copies of deleted sections / sprints until the trash period ends; 2.783.0 (#5368): + deleted fields, "Delete all times"
    "obj_history": _DERIVED, "obj_undo": "undo steps of 30 days", "obj_revoked": "shares removed (not_included)",  # 2.558.0 (#4709): the core's working data; 2.747.0 (#5249): 30 days
    "undo_groups": "undo steps of 30 days",  # 2.747.0 (#5249): their heads per person
    "doc_views": "saved views of the documents search (their filters name label and folder ids of this server)",  # 2.579.0 (#4802)
    "field_trash": _DERIVED, "member_memos": _DERIVED,  # 2.550.0 (#4528): deleted fields / a removed member's ways back (trash period)
    "task_vectors": _DERIVED, "upload_scan": _SERVER, "webhooks": _SECRET, "wiki_shares": _SECRET,
    "wiki_spaces": "the lock of a space (client_encrypted names it)",
    # 2.977.0 (#5282): the heads; their versions are office/procdocs.json and lists/playbooks.json (obj_versions)
    "office_procdocs": "the head of the procedure documentation (its versions: office/procdocs.json)",
    "playbooks": "the head of a project's Playbook (its versions: lists/playbooks.json)",
    # list column
    "agent_audit": _AGENT, "agent_burst_held": _SERVER, "agent_decisions": _AGENT, "agent_jobs": _AGENT, "agent_list_access": _AGENT, "agent_schedules": _AGENT, "agent_usage": _AGENT,
    "assistant_access": _PERSONAL, "assistant_log": _PERSONAL, "budget_cats": _PERSONAL, "budget_entries": _PERSONAL,
    "budget_files": _PERSONAL, "budget_meta": _PERSONAL, "budget_recurring": _PERSONAL, "contact_srcs": _SECRET, "ctr_notices": _PERSONAL, "dav_sync": _DERIVED,
    "dl_changes": _DERIVED, "env_deploys": _SECRET, "git_conns": _SECRET,
    "hook_in": _SECRET, "issue_hooks": _SECRET,
    "issue_reports": "fingerprints of error reports: a counter and limit of this server, the reports themselves are tasks",  # 2.455.0 (#3469)
    "kk_conns": _SECRET, "list_envs": _SECRET, "list_key_pending": "list keys (client_encrypted)",
    "list_keys": "list keys (client_encrypted)", "list_layouts": _PERSONAL, "list_mine_hide": _PERSONAL,
    "list_paperless": _SECRET, "mail_tokens": _SECRET, "notifications": _PERSONAL, "playbook_proposals": _AGENT, "public_links": _SECRET,
    "agent_schedules": _AGENT, "budget_meta": _PERSONAL, "issue_hooks": _SECRET, "issue_reports": "not yet in the export",  # 2.362.4 (#3107)
    "shop_memory": _PERSONAL, "list_ticket_seq": _DERIVED, "task_keys": _LATER2, "list_folder_skip": _LATER2,
}

# 2.223.3 B (#2879): soft-deleted rows (the trash, undone entries) stay out of the organisation and the retention export, and
# the rows of a deleted parent with them. office_drives keeps them: a removed drive stays for the change log (tax office).
OX_KEEP_DELETED = ("office_drives",)
OX_GONE_WITH = {  # table -> (parent table, column) pairs: a row goes when its parent row is deleted
    "tchat_files": (("tchat_msgs", "message_id"),),  # 2.362.0 (#3092)
    "hub_mail_links": (("hub_mails", "mail_id"),),  # 2.362.0 (#3096)
    "event_attendees": (("events", "event_id"),),
    "contacts": (("books", "book_id"),),
    "office_client_contacts": (("clients", "client_id"),),
    "office_meal_files": (("office_meals", "meal_id"),),
    "office_sub_reminders": (("office_fixed_costs", "fixed_id"),),  # 2.905.0 (#5414): the reminders of a subscription in the trash
    # 2.1005.0 (#5415): what hangs on a document draft in the core's trash (ON DELETE CASCADE) stays out with it; the log stays
    # (no foreign key: history, as after a delete), the SET NULL references were emptied by the trash (office/docs.py odoc_trash)
    "office_doc_items": (("office_docs", "doc_id"),), "office_doc_parts": (("office_docs", "doc_id"),),
    "office_purchases": (("office_docs", "doc_id"),), "office_payments": (("office_docs", "doc_id"),),
    "office_pay_props": (("office_docs", "doc_id"),), "office_signoffs": (("office_docs", "doc_id"),),
    "office_peppol_sends": (("office_docs", "doc_id"),), "office_dunning_marks": (("office_docs", "doc_id"),),
    "office_datev_guids": (("office_docs", "doc_id"),),
    "sheet_columns": (("sheets", "sheet_id"),),
    "sheet_rows": (("sheets", "sheet_id"),),
    "sheet_cells": (("sheets", "sheet_id"), ("sheet_rows", "row_id"), ("sheet_columns", "col_id")),
    "sheet_links": (("sheets", "sheet_id"),),
    "sheet_shares": (("sheets", "sheet_id"),),
    "sheet_files": (("sheets", "sheet_id"),),
    "sheet_hist": (("sheets", "sheet_id"),),
    "video_versions": (("video_reviews", "review_id"),),
    "wiki_files": (("wiki_pages", "page_id"),),
}


def ox_live(c, table, where):
    """2.223.3 B (#2879): where without the soft-deleted rows of table and the rows of a deleted parent (OX_GONE_WITH)."""
    if table not in OX_KEEP_DELETED and "deleted_at" in _table_cols(c, table):
        where = f"({where}) AND deleted_at IS NULL"
    if "wkx_held_at" in _table_cols(c, table):  # 2.528.0 D (#4306): files held at a lock stay out (only who read them then)
        where = f"({where}) AND wkx_held_at IS NULL"
    if table == "obj_versions":  # 2.958.0 (#5281): the versions' hold is held_at now
        where = f"({where}) AND held_at IS NULL"
    for parent, col in OX_GONE_WITH.get(table, ()):
        if "deleted_at" in _table_cols(c, parent):
            # 2.1005.0 (#5415): a row without a parent (a nullable column: a sign-off of a list) stays -- NULL NOT IN (..) is no true
            q = qi(col, _table_cols(c, table))
            where = f"({where}) AND ({q} IS NULL OR {q} NOT IN (SELECT id FROM {qi(parent, table_names(c))} WHERE deleted_at IS NOT NULL))"
    return where


def ox_dead_nodes(c, oid):
    """2.223.3 B (#2879): ids of the organisation's file store nodes in the trash and everything below them."""
    if "deleted_at" not in _table_cols(c, "fs_nodes"):
        return set()
    return {r[0] for r in c.execute("""WITH RECURSIVE t(id) AS (SELECT id FROM fs_nodes WHERE org_id=? AND deleted_at IS NOT NULL
                                         UNION SELECT n.id FROM fs_nodes n JOIN t ON n.parent_id=t.id) SELECT id FROM t""", (oid,)).fetchall()}


def ox_dead_office_files(c, oid, have):
    """2.223.3 B (#2879): names of the office folder's files that only deleted contract / meal file rows hold."""
    dead, live = set(), set()
    for t in ("office_contract_files", "office_meal_files"):
        if t in have and "deleted_at" in _table_cols(c, t):
            gone = ("deleted_at IS NOT NULL OR meal_id IN (SELECT id FROM office_meals WHERE deleted_at IS NOT NULL)"
                    if t == "office_meal_files" else "deleted_at IS NOT NULL")
            for r in c.execute(f"SELECT file, CASE WHEN {gone} THEN 1 ELSE 0 END FROM {t} WHERE org_id=?", (oid,)):
                (dead if r[1] else live).add(os.path.basename(r[0] or ""))
    return dead - live - {""}


def ox_lsq(by_id):
    """2.223.3 B (#2880): LSQ narrowed to the lists the exporting admin sees in the app: shared with at least one more person
    or open to the organisation (the rule of accounts/orglists.py ol_shared), the admin's own lists and those shared with them."""
    u = int(by_id or 0)
    own = f" OR l.owner_id={u} OR l.id IN (SELECT list_id FROM list_members WHERE user_id={u})" if u else ""
    return (f"SELECT l.id FROM lists l WHERE l.org_id=? AND l.is_inbox=0 AND {otr_live('l')} AND ("
            "(l.org_visibility='org' AND COALESCE(l.life,'')='' AND COALESCE(l.family,'')='') "
            "OR EXISTS (SELECT 1 FROM list_members m JOIN users u ON u.id=m.user_id WHERE m.list_id=l.id AND m.user_id!=l.owner_id "
            f"AND COALESCE(u.kind,'user')!='agent'){own})")


def ox_apq(by_id):
    """2.362.0 (#3096, review): APQ for the exporting admin (their own booking page on a calendar of the organisation too)."""
    u = int(by_id or 0)
    return APQ + (f" OR (user_id={u} AND cal_id IN (SELECT id FROM ev_cals WHERE org_id=?))" if u else "")


def ox_csq(by_id):
    """2.362.0 (#3092): CSQ for the exporting admin: the open channels of the organisation and the ones they are a member of
    (the rule of collab/teamchan.py tcx_room_ok: an admin manages a closed channel but does not read it)."""
    u = int(by_id or 0)
    return ("SELECT id FROM tchat_rooms WHERE kind='channel' AND org_id=? AND ((is_open=1 AND archived_at IS NULL)"
            + (f" OR id IN ({_tcx_rooms(u)})" if u else "") + ")")


def _tcx_rooms(u):
    """2.924.0 (#5069): the rooms u is a member of through the core alone (a person's / agent's share, a group's)."""
    from ..collab.tcxcore import tcx_core_rooms_sql
    return tcx_core_rooms_sql(u)


# 2.190.0 R (#2561): rows of the file store that belong to one node (left out with a hidden filed mail's nodes)
OX_NODE_TABLES = ("fs_versions", "fs_shares", "fs_log", "doc_meta", "doc_node_tags", "doc_field_values", "rc_receipts",
                  "fs_area_roots", "fs_locks")  # 2.353.0 C (#2829), #4300; 2.981.0 (#5273): the notes by their file (OX_NODE_FILES)
OX_NODE_FILES = ("documents/notes.json",)  # 2.635.0 (#4807 d): the notes on documents (rows of obj_comments since 2.981.0, #5273)


def ox_hidden_nodes(c, oid, hidden):
    """2.190.0 R (#2561): ids of the file store nodes of the hidden filed mails (marked with hub_mail_id) and everything below them."""
    if not hidden:
        return set()
    q = ",".join(str(int(x)) for x in hidden)
    return {r[0] for r in c.execute(f"""WITH RECURSIVE t(id) AS (SELECT id FROM fs_nodes WHERE org_id=? AND hub_mail_id IN ({q})
                                         UNION SELECT n.id FROM fs_nodes n JOIN t ON n.parent_id=t.id) SELECT id FROM t""", (oid,)).fetchall()}


def ox_hidden_mails(c, oid, uid):
    """2.190.0 D (#2561): ids of the organisation's filed mails uid may not read in the app (none hidden without uid)."""
    if not uid:
        return set()
    return {r["id"] for r in c.execute("SELECT id, list_id, client_id, owner_id, org_id FROM hub_mails WHERE org_id=?", (oid,)).fetchall()
            if not hbm_can(c, uid, r)}


def _safe_part(s, n=80):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-.")[:n]
    return s or "file"


def ox_lang(c, by):
    return lang(c, by["id"]) if by else "en"


def ox_not_included(c, by, texts):
    """2.449.0 (#3768): what the export leaves out, in the language of the person who runs it (without one: English)."""
    return [tr(x, lg=ox_lang(c, by)) for x in texts]


def ox_file_name(org_name, oid, when, suffix=OX_SUFFIX):
    slug = _safe_part(org_name, 40).lower()
    return f"{slug if slug != 'file' else 'org' + str(int(oid))}-{when.strftime('%Y-%m-%d')}{suffix}"


def ox_decrypted_note(what):
    """The manifest's word on what is readable (2.362.2 #3099: a server without key has no encryption at all)."""
    if not oc_enabled():
        return "This server has no server key: nothing is encrypted, neither the fields nor this archive."
    return f"Fields and files the server encrypts with the {what} key are in plain text here; the archive itself is encrypted."


class _Man:
    """The manifest: rows and SHA-256 per archive entry."""

    def __init__(self):
        self.files, self.counts, self.client_enc = {}, {}, {"attachments": [], "task_notes": 0}
        self.locked = []  # 2.209.0 D (#1856): files left out because the virus scanner locked them
        self.missing = []  # 2.363.2 (#3106): files that are gone or cannot be opened (manifest "missing")


def _ox_locked(c, oid, man):
    """2.209.0 D (#1856): lk(kind, row | id, name, ver=0) -> True for a file the virus scanner locked (it is then listed in
    man.locked: area, id, name, signature, nothing else of it goes into the export); lk.office = the locked office files."""
    inf = sc_locked_all(c, oid)
    office = inf.pop("office", {})

    def lk(kind, r, name, ver=0):
        rid = int(r["id"] if isinstance(r, dict) else r)
        sig = office[name][2] if kind in ("ocf", "omf", "oar") and name in office else inf.get((kind, rid, int(ver or 0)))
        if sig is None:
            return False
        man.locked.append({"area": kind, "id": rid, "ver": int(ver or 0), "name": name or "", "signature": sig})
        return True
    lk.office = office
    return lk


def _put_json(zf, man, name, rows):
    h, size, n = hashlib.sha256(), 0, 0
    with zf.open(zipfile.ZipInfo(name, date_time=time.localtime()[:6]), "w", force_zip64=True) as w:
        def put(s):
            nonlocal size
            b = s.encode()
            h.update(b)
            size += len(b)
            w.write(b)
        put("[")
        for r in rows:
            put(("," if n else "") + "\n" + json.dumps(r, ensure_ascii=False, default=_jdef, sort_keys=True))
            n += 1
        put("\n]\n")
    man.files[name] = {"sha256": h.hexdigest(), "bytes": size}
    man.counts[name] = n


def _put_bytes(zf, man, name, data):
    zi = zipfile.ZipInfo(name, date_time=time.localtime()[:6])
    zi.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(zi, data)
    man.files[name] = {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def _read(c, full):
    return oc_read_file(c, full)


def ox_read_listed(c, missing, name, full):
    """2.363.2 (#3106): the plain bytes of a stored file, or None with an entry {file, reason} in missing: one file that is
    gone or cannot be decrypted is named in the manifest, the rest of the export goes on (the retention export does the same)."""
    if not full:
        missing.append({"file": name, "reason": "not_found"})
        return None
    try:
        return _read(c, full)
    except (OrgCryptError, OSError):
        missing.append({"file": name, "reason": "unreadable"})
        return None


def _put_file(c, zf, man, name, full):
    """A stored file into the archive -> False when it is listed in man.missing instead."""
    data = ox_read_listed(c, man.missing, name, full)
    if data is None:
        return False
    _put_bytes(zf, man, name, data)
    return True


def _under(base, rel):
    full = os.path.realpath(os.path.join(base, rel or ""))
    return full if full.startswith(os.path.realpath(base) + os.sep) and os.path.isfile(full) else None


def ox_build(c, oid, out, by=None):
    """Writes the ZIP of organisation oid into the stream out; returns the manifest dict (also inside the ZIP)."""
    man = _Man()
    have = {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema()")}
    org = c.execute("SELECT * FROM orgs WHERE id=?", (oid,)).fetchone()
    if org and "personal_of" in org.keys() and org["personal_of"]:  # 2.137.0 A (#2344): a person's own office
        return ox_build_personal(c, oid, out, org, have, by)
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        o = _clean(c, oid, "orgs", org)
        if str(o.get("icon") or "").startswith("u:"):  # 2.87.9 (#1913): a token of this server -> no dead link (2.459.0, #3849: the picture is files/pictures/organisation.png)
            o["icon"] = ""
        _put_json(zf, man, "organisation.json", [o])
        members = c.execute("""SELECT u.id, u.username, u.display_name, u.email, COALESCE(u.kind,'user') AS kind, u.disabled, u.color, m.role
                               FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? ORDER BY u.id""", (oid,)).fetchall()
        _put_json(zf, man, "members.json", ({**dict(r), "role": org_role(c, r["id"], oid) or r["role"]} for r in members))
        hidden = ox_hidden_mails(c, oid, (by or {}).get("id")) if "hub_mails" in have else set()
        if "hub_mails" in have and "deleted_at" in _table_cols(c, "hub_mails"):  # 2.223.3 B (#2879): a deleted filed mail's files follow it out
            hidden |= {r[0] for r in c.execute("SELECT id FROM hub_mails WHERE org_id=? AND deleted_at IS NOT NULL", (oid,))}
        hnodes = ox_hidden_nodes(c, oid, hidden) if hidden and "fs_nodes" in have else set()
        if "fs_nodes" in have:
            hnodes |= ox_dead_nodes(c, oid)  # 2.223.3 B (#2879): the trash of the file store and its rows
        lsq = ox_lsq((by or {}).get("id"))  # 2.223.3 B (#2880): only the lists the admin sees in the app

        csq = ox_csq((by or {}).get("id"))  # 2.362.0 (#3092): the channels the admin reads in the app

        apq = ox_apq((by or {}).get("id"))  # 2.362.0 (#3096, review): only booking pages the admin reads in the app

        def vis(where):
            return where.replace(CSQ, csq).replace(APQ, apq).replace(LSQ, lsq)
        for name, table, where in OX_AREAS:
            if table not in have:
                continue
            where = ox_live(c, table, vis(where))
            rows = _rows(c, oid, table, where, (oid,) * where.count("?"))
            if table == "hub_mails" and hidden:
                rows = (r for r in rows if r.get("id") not in hidden)
            elif table == "hub_mail_links" and hidden:  # 2.362.0 (#3096): a hidden mail's links stay out with it
                rows = (r for r in rows if r.get("mail_id") not in hidden)
            elif hnodes and table == "fs_nodes":  # 2.190.0 R (#2561): the filed mail's folder, its files and their rows go too
                rows = (r for r in rows if r.get("id") not in hnodes)
            elif hnodes and (table in OX_NODE_TABLES or name in OX_NODE_FILES):
                rows = (r for r in rows if r.get("node_id") not in hnodes)
            _put_json(zf, man, name, rows)
        if "fs_locks" in have and (by or {}).get("id"):  # #4300: only the exporting person's own copy of a folder key (it opens only with their keys)
            _put_json(zf, man, "store/lock_keys.json", [r for r in oil_export_keys(c, "l.org_id=? AND k.user_id=?", (oid, by["id"])) if r["node_id"] not in hnodes])
        # the files: attachments of the tasks, project files of the lists, everything below OFFICE_DIR/<org id>
        enc = "enc" in _table_cols(c, "attachments")
        lk = _ox_locked(c, oid, man)  # 2.209.0 D (#1856): files the virus scanner locked stay out, listed in the manifest
        for r in _rows(c, oid, "attachments", ox_live(c, "attachments", vis(f"task_id IN ({TSQ})")), (oid,)):
            full = _under(ATT_DIR, r.get("path"))
            if lk("att", r, r.get("name")):
                continue
            name = f"files/attachments/{int(r['id'])}-{_safe_part(r.get('name'))}"
            if _put_file(c, zf, man, name, full) and enc and r.get("enc"):
                man.client_enc["attachments"].append(name)
        for r in _rows(c, oid, "list_files", ox_live(c, "list_files", vis(f"list_id IN ({LSQ})")), (oid,)):
            full = _under(ATT_DIR, r.get("path"))
            if not lk("list", r, r.get("name")):
                _put_file(c, zf, man, f"files/list_files/{int(r['id'])}-{_safe_part(r.get('name'))}", full)
        if "fs_versions" in have:  # 2.48.0 (#1207): every version of the file store's files (decrypted like the attachments)
            for r in _rows(c, oid, "fs_versions", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)", (oid,)):
                full = _under(ATT_DIR, r.get("path"))
                nm = c.execute("SELECT name, hub_mail_id FROM fs_nodes WHERE id=?", (r["node_id"],)).fetchone()
                if r["node_id"] in hnodes or (nm and hidden and nm["hub_mail_id"] in hidden):
                    continue  # 2.190.0 D (#2561): a filed mail's file follows the mail (2.223.3 B (#2879): the trash too)
                if nm and not lk("fs", {"id": r["node_id"]}, nm[0], r["no"]):
                    _put_file(c, zf, man, f"files/store/{int(r['node_id'])}-v{int(r['no'])}-{_safe_part(nm[0])}", full)
        if "wiki_files" in have:  # 2.99.0 A (#2182): the files of the knowledge pages (decrypted like the attachments)
            for r in _rows(c, oid, "wiki_files", ox_live(c, "wiki_files", "org_id=?"), (oid,)):
                full = _under(ATT_DIR, r.get("path"))
                if not lk("wiki", r, r.get("name")):
                    _put_file(c, zf, man, f"files/wiki/{int(r['id'])}-{_safe_part(r.get('name'))}", full)
        if "sheet_files" in have:  # 2.124.0 B (#2110): the files of table cells (decrypted like the attachments)
            for r in _rows(c, oid, "sheet_files", ox_live(c, "sheet_files", "org_id=?"), (oid,)):
                full = _under(ATT_DIR, r.get("path"))
                if not lk("sheet", r, r.get("name")):
                    _put_file(c, zf, man, f"files/sheets/{int(r['id'])}-{_safe_part(r.get('name'))}", full)
        if "bookmarks" in have:  # 2.380 H (#2398): the pictures of the organisation's bookmarks (decrypted like the attachments)
            for r in _rows(c, oid, "bookmarks", ox_live(c, "bookmarks", "org_id=? AND image<>''"), (oid,)):
                full = _under(ATT_DIR, r.get("image"))
                _put_file(c, zf, man, f"files/bookmarks/{int(r['id'])}-{_safe_part(os.path.basename(r['image']))}", full)
        if "tchat_files" in have:  # 2.362.0 (#3092): the files and voice messages of the team chat (decrypted like the attachments)
            tw = ox_live(c, "tchat_files", vis(f"room_id IN ({RSQ})"))
            for r in _rows(c, oid, "tchat_files", tw, (oid,) * tw.count("?")):
                full = _under(ATT_DIR, r.get("path"))
                if not lk("tchat", r, r.get("name")):
                    _put_file(c, zf, man, f"files/tchat/{int(r['id'])}-{_safe_part(r.get('name'))}", full)
        # 2.363.2 (#3106): the pictures of the organisation and of the lists the admin sees, as files
        tok = org_icon_tok(org["icon"])
        if tok:
            _put_file(c, zf, man, "files/pictures/organisation.png", _under(ATT_DIR, os.path.relpath(org_icon_path(oid, tok), ATT_DIR)))
        for r in c.execute(vis(f"SELECT id, icon, header_file FROM lists WHERE id IN ({LSQ})"), (oid,)).fetchall():
            if str(r["icon"] or "").startswith("u:"):
                _put_file(c, zf, man, f"files/pictures/list-{int(r['id'])}-icon.png",
                          _under(ATT_DIR, os.path.relpath(list_icon_path(r["id"], r["icon"][2:]), ATT_DIR)))
            if r["header_file"]:
                _put_file(c, zf, man, f"files/pictures/list-{int(r['id'])}-header.jpg", _under(ATT_DIR, o3c_head_rel(r["id"], r["header_file"])))
        odir = os.path.join(OFFICE_DIR, str(int(oid)))
        dead = ox_dead_office_files(c, oid, have)  # 2.223.3 B (#2879)
        if os.path.isdir(odir):
            for root, dirs, files in os.walk(odir):
                dirs.sort()
                for fn in sorted(files):
                    full = os.path.join(root, fn)
                    if os.path.islink(full) or not os.path.isfile(full):
                        continue
                    if root == odir and fn in lk.office:  # 2.209.0 D (#1856)
                        lk(*lk.office[fn][:2], fn)
                        continue
                    if root == odir and fn in dead:
                        continue
                    rel = os.path.relpath(full, odir).replace(os.sep, "/")
                    _put_file(c, zf, man, "files/office/" + "/".join(_safe_part(p) for p in rel.split("/")), full)
        if "enc" in _table_cols(c, "tchat_msgs"):  # 2.42.0 (#909, agent A): browser-encrypted chat messages stay ciphertext
            man.client_enc["chat_messages"] = c.execute(vis(f"""SELECT COUNT(*) FROM tchat_msgs WHERE COALESCE(enc,'')!='' AND room_id IN
                ({RSQ})"""), (oid,) * RSQ.count("?")).fetchone()[0]  # 2.362.0 (#3092): + the channels
        if "tasks/encrypted_notes.json" in man.counts:
            man.client_enc["task_notes"] = man.counts["tasks/encrypted_notes.json"]
        if "tasks/locked_notes.json" in man.counts:
            man.client_enc["locked_notes"] = man.counts["tasks/locked_notes.json"]
        # 2.278.0 C (#3091): the key bundles are personal: never in this archive (each person moves them with the account export)
        man.client_enc["keys_note"] = ("Personal encryption keys are not in the organisation export: browser-encrypted notes and "
                                       "files of a person open after a move only via that person's own account export.")
        if "e2e" in _table_cols(c, "lists"):  # 2.64.1 B (#1817): lists with the lock: texts are browser ciphertexts ("e2e1:...")
            lk = [r[0] for r in c.execute(vis(f"SELECT id FROM lists WHERE e2e IS NOT NULL AND id IN ({LSQ})"), (oid,))]
            if lk:
                q = ",".join("?" * len(lk))
                man.client_enc["locked_lists"] = len(lk)
                man.client_enc["locked_list_tasks"] = c.execute(f"SELECT COUNT(*) FROM tasks WHERE list_id IN ({q}) AND deleted_at IS NULL", lk).fetchone()[0]
                man.client_enc["locked_list_note"] = ("Texts of lists encrypted in the browser (values starting with e2e1:) can only be "
                                                      "read in Kalmido with a member's own passphrase; no offline tool opens them.")
                man.client_enc["locked_list_import"] = "The import does not take these lists over (no list keys move along)."  # 2.278.0 C (#3091)
        if "fs_locks" in have and c.execute("SELECT 1 FROM fs_locks WHERE org_id=? AND e2e IS NOT NULL", (oid,)).fetchone():  # 2.353.0 A (#2758)
            man.client_enc["locked_folders"] = c.execute("SELECT COUNT(*) FROM fs_locks WHERE org_id=? AND e2e IS NOT NULL", (oid,)).fetchone()[0]
            man.client_enc["locked_folder_note"] = ("Names and files below a locked folder of the file store (names starting with e2e1:, "
                                                    "files starting with KENC) are exported as stored, encrypted in the browser; only the "
                                                    "people holding the folder key can read them, in Kalmido. The exporting person's own "
                                                    "copy of each folder key comes along (store/lock_keys.json): an import opens the "
                                                    "folder when that person has the same keys on the target (their account export moves "
                                                    "them, before this import) and hands it on to the others from there; a folder without "
                                                    "such a key stays out of the import: unlock it before the export.")
        if c.execute("SELECT 1 FROM wiki_spaces WHERE org_id=? AND e2e IS NOT NULL", (oid,)).fetchone():  # 2.64.3 A (#1817)
            man.client_enc["locked_wiki_pages"] = c.execute("SELECT COUNT(*) FROM wiki_pages WHERE org_id=? AND deleted_at IS NULL", (oid,)).fetchone()[0]
            man.client_enc["locked_wiki_note"] = ("Name and text of the knowledge pages of a space encrypted in the browser (values starting "
                                                  "with e2e1:) can only be read in Kalmido with a member's own passphrase; export them "
                                                  "decrypted from the knowledge pages in the app.")
        manifest = {
            "format": "kalmido-org-export", "format_version": OX_FORMAT, "kalmido_version": APP_VERSION,
            "org": {"id": int(oid), "name": org["name"]}, "created_at": iso(now_utc()), "created_by": by,
            "counts": man.counts, "files": man.files,
            "client_encrypted": {**man.client_enc, "note": "Encrypted in the browser by their author: stored here as ciphertext, only the author can open them."},
            "decrypted": ox_decrypted_note("organisation"),
            "not_included": [*ox_not_included(c, by, OX_NOT_INCLUDED), *left_lines(OX_LEFT, ox_lang(c, by))],  # 2.449.0 (#3768), 2.362.4 (#3107), 2.464.0 (#3841)
            "locked_files": man.locked,  # 2.209.0 D (#1856)
            "missing": man.missing,  # 2.363.2 (#3106)
        }
        _put_bytes(zf, man, "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1, default=_jdef).encode())
    return manifest


# 2.137.0 A (#2344): the export of a personal office (office/model.py pb_personal) by its owner: only the office and the
# owner's private clients with their contact persons (org_id NULL, created by the owner: model.py pb_cl_sql) -- no lists,
# no other areas of the private space, nobody else. The import takes it into an organisation or into a personal office.
OX_PB_CLIENTS = {"clients": "org_id IS NULL AND created_by=?",
                 "office_client_contacts": "org_id IS NULL AND client_id IN (SELECT id FROM clients WHERE org_id IS NULL AND created_by=?)"}
OX_PB_LEFT = N_("everything of the private workspace but the office, its clients and the documents the office stands on (receipts, filed letters, contract and equipment documents, cash book receipts); files below a browser-locked folder stay out")


def ox_pb_nodes(c, oid, owner, have):
    """2.362.2 (#3099): the files of the owner's private documents space the personal office stands on: everything an office
    table points at (receipts of cash entries, filed letters, contracts, equipment, statements ...) and the receipts of the
    space -> (file ids, those + their folders). Only the owner's own nodes, nothing of the trash, nothing below a browser-locked
    folder (only its key holders read it)."""
    from ..docs.store import doc_ws
    refs = {r[0] for r in c.execute("SELECT node_id FROM rc_receipts WHERE ws=?", (doc_ws(None, owner),))}
    for t, col in c.execute("""SELECT table_name, column_name FROM information_schema.columns WHERE table_schema=current_schema()
                               AND table_name ILIKE 'office%' AND column_name ILIKE '%node_id'""").fetchall():
        if "org_id" in _table_cols(c, t):
            refs |= {r[0] for r in c.execute(f"SELECT {col} FROM {t} WHERE org_id=? AND {col} IS NOT NULL", (oid,))}
    nodes, todo = {}, set(refs)
    while todo:  # upwards: the folders above the files (each id once)
        q = ",".join(str(int(x)) for x in todo)
        rs = c.execute(f"SELECT id, parent_id, kind, deleted_at FROM fs_nodes WHERE id IN ({q}) AND owner_id=? AND org_id IS NULL", (owner,)).fetchall()
        nodes.update((r["id"], r) for r in rs)
        todo = {r["parent_id"] for r in rs if r["parent_id"]} - set(nodes)
    locked = {r[0] for r in c.execute("SELECT node_id FROM fs_locks WHERE org_id IS NULL AND e2e IS NOT NULL")} if "fs_locks" in have else set()

    def chain(nid):
        out = []
        while nid in nodes and nid not in out:
            out.append(nid)
            nid = nodes[nid]["parent_id"]
        return out
    files, tree = set(), set()
    for nid in refs & set(nodes):
        ups = chain(nid)
        if nodes[nid]["kind"] == "file" and not any(nodes[x]["deleted_at"] or x in locked for x in ups):
            files.add(nid)
            tree.update(ups)
    return files, tree


def ox_pb_read(c, man, area, rid, name, full):
    """2.362.2 (#3099, review): one file that does not open (a lost key, a damaged file) is named in the manifest and never
    stops the copy of a person's data. -> its bytes or None."""
    try:
        return _read(c, full)
    except (OSError, OrgCryptError) as e:
        print(f"personal office export: {area} file not readable: {type(e).__name__}", flush=True)
        man.locked.append({"area": area, "id": int(rid), "name": name or "", "signature": "", "unreadable": True})
        return None


def ox_pb_store(c, zf, man, lk, oid, owner, have, pre=""):
    """2.362.2 (#3099): the entries of the file store and the documents for those files, in the shape of an organisation's
    (the import takes them over the same way and sets the office's references to them, admin/oi_store.py)."""
    from ..docs.store import doc_ws
    files, tree = ox_pb_nodes(c, oid, owner, have)
    if not files:
        return
    ws, k, t = doc_ws(None, owner), ",".join(str(int(x)) for x in sorted(files)), ",".join(str(int(x)) for x in sorted(tree))
    for name, table, where, args in (
            ("store/nodes.json", "fs_nodes", f"id IN ({t})", ()),
            ("store/area_roots.json", "fs_area_roots", f"ws=? AND node_id IN ({t})", (ws,)),
            ("store/versions.json", "fs_versions", f"node_id IN ({k})", ()),
            ("documents/senders.json", "doc_senders", "ws=?", (ws,)),
            ("documents/types.json", "doc_types", "ws=?", (ws,)),
            ("documents/tags.json", "doc_tags", "ws=?", (ws,)),
            ("documents/document_tags.json", "doc_node_tags", f"node_id IN ({k})", ()),
            ("documents/fields.json", "doc_fields", "ws=?", (ws,)),
            ("documents/field_values.json", "doc_field_values", f"node_id IN ({k})", ()),
            ("documents/notes.json", "obj_comments", f"kind='doc_note' AND ref_id IN ({k}) AND {live_sql()}", ()),  # 2.635.0 (#4807 d); 2.981.0 (#5273)
            ("documents/meta.json", "doc_meta", f"node_id IN ({k})", ()),
            ("documents/receipts.json", "rc_receipts", f"node_id IN ({k})", ())):
        if table in have:
            _put_json(zf, man, pre + name, _rows(c, oid, table, where, args))
    names = {r[0]: r[1] for r in c.execute(f"SELECT id, name FROM fs_nodes WHERE id IN ({k})")}
    for r in _rows(c, oid, "fs_versions", f"node_id IN ({k})", ()):
        full, nm = _under(ATT_DIR, r.get("path")), names.get(r["node_id"])
        if full and not lk("fs", {"id": r["node_id"]}, nm, r["no"]):
            data = ox_pb_read(c, man, "fs", r["node_id"], nm, full)
            if data is not None:
                _put_bytes(zf, man, f"{pre}files/store/{int(r['node_id'])}-v{int(r['no'])}-{_safe_part(nm)}", data)


def ox_pb_parts(c, zf, man, oid, owner, have, pre=""):
    """The parts of a personal office into the open ZIP zf, below pre (2.362.2 #3099: the account export carries them too)."""
    for name, table, where in OX_AREAS:
        if table not in have or not (name.startswith("office/") or name == "clients.json"):
            continue
        if table in OX_PB_CLIENTS:
            _put_json(zf, man, pre + name, _rows(c, oid, table, ox_live(c, table, OX_PB_CLIENTS[table]), (owner,)))  # 2.223.3 B (#2879)
        else:
            where = ox_live(c, table, where)  # 2.223.3 B (#2879): without the trash
            _put_json(zf, man, pre + name, _rows(c, oid, table, where, (oid,) * where.count("?")))
    odir = os.path.join(OFFICE_DIR, str(int(oid)))
    lk = _ox_locked(c, oid, man)
    dead = ox_dead_office_files(c, oid, have)  # 2.223.3 B (#2879)
    if os.path.isdir(odir):
        for fn in sorted(os.listdir(odir)):  # the office keeps its files in one folder (no sub folders)
            full = os.path.join(odir, fn)
            if os.path.islink(full) or not os.path.isfile(full) or fn in dead:
                continue
            if fn in lk.office:  # 2.209.0 D (#1856): a file the virus scanner locked stays out, listed in the manifest
                lk(*lk.office[fn][:2], fn)
                continue
            data = ox_pb_read(c, man, "office", 0, fn, full)
            if data is not None:
                _put_bytes(zf, man, f"{pre}files/office/" + _safe_part(fn), data)
    ox_pb_store(c, zf, man, lk, oid, owner, have, pre)


def ox_build_personal(c, oid, out, org, have, by=None):
    man = _Man()
    owner = int(org["personal_of"])
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        o = _clean(c, oid, "orgs", org)
        o["icon"] = ""
        _put_json(zf, man, "organisation.json", [o])
        _put_json(zf, man, "members.json", [])
        ox_pb_parts(c, zf, man, oid, owner, have)
        manifest = {
            "format": "kalmido-org-export", "format_version": OX_FORMAT, "kalmido_version": APP_VERSION,
            "org": {"id": int(oid), "name": org["name"]}, "created_at": iso(now_utc()), "created_by": by, "personal_office": 1,
            "counts": man.counts, "files": man.files, "client_encrypted": {"note": "none"},
            "decrypted": ox_decrypted_note("office"),
            "not_included": ox_not_included(c, by, [OX_PB_LEFT, *OX_NOT_INCLUDED[1:2]]),  # 2.449.0 (#3768)
            "locked_files": man.locked,  # 2.209.0 D (#1856)
            "missing": man.missing,  # 2.363.2 (#3106)
        }
        _put_bytes(zf, man, "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1, default=_jdef).encode())
    return manifest


# ---------------------------------------------------------------- state, thread, clean-up
def _odir(oid):
    return os.path.join(EXPORT_DIR, str(int(oid)))


def _state(oid):
    try:
        with open(os.path.join(_odir(oid), "state.json"), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _state_set(oid, d):
    os.makedirs(EXPORT_DIR, mode=0o700, exist_ok=True)
    os.makedirs(_odir(oid), mode=0o700, exist_ok=True)
    p = os.path.join(_odir(oid), "state.json")
    tmp = p + ".tmp"
    with os.fdopen(os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as f:
        json.dump(d, f)
    os.replace(tmp, p)


def _running(oid, c=None):
    """2.370.3 (#2760): the export runs or waits for the worker: its queue row (any process), or a thread of this process
    (the queue's fallback without a database)."""
    t = _OX.get(int(oid))
    if t and t.is_alive():
        return True
    try:
        return bgj_busy("ox:export", org_id=int(oid), c=c)
    except Exception:  # noqa: BLE001 -- 2.551.0 (#4643): no answer from the database counts as busy (as _busy of the imports, #4295)
        return True


@bgj_fn("ox:export", long=True)
def ox_export_row(oid, uid):
    """2.370.3 (#2760): the queue row of an organisation's export (run again after a lost run: it only writes its file)."""
    with _OX_LOCK:
        t = _OX.get(int(oid))
        if t and t.is_alive():  # review 2: a run taken again while the first still writes here: never two at once
            raise RuntimeError("export still running in this process")
        _OX[int(oid)] = threading.current_thread()
    ox_run(oid, uid)


def ox_run(oid, uid):
    """The thread: archive of organisation oid, started by uid."""
    c = connect()
    part = None
    try:
        with system_ctx(c):  # the organisation's rows only (every query names it); the starter is its admin
            from ..core.orgcrypt import oc_key
            org = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()
            plain = not oc_enabled()  # 2.362.2 (#3099)
            okey = None if plain else oc_key(c, oid, create=True)
            if not org or not (okey or plain):
                raise RuntimeError("no organisation key")
            u = c.execute("SELECT id, display_name, username FROM users WHERE id=?", (uid,)).fetchone()
            when = now_utc()
            if not plain:
                from ..core.orgcrypt import rck_wrapped
                if c.execute("SELECT 1 FROM org_keys WHERE org_id=? AND rot_started_at IS NOT NULL", (oid,)).fetchone():
                    raise RuntimeError("key renewal running")  # 2.138.0 C (#1972, review F2)
                rw = rck_wrapped(c, oid)  # 2.138.0 C (#1972): the recovery key opens the archive (made when there is none yet)
                c.commit()
                head, fk, prefix = ox_header(oid, org["name"], okey, iso(when), rw)
            name = ox_file_name(org["name"], oid, when, OX_PLAIN_SUFFIX if plain else OX_SUFFIX)
            by = {"id": uid, "name": (u["display_name"] or u["username"]) if u else ""}
            part = os.path.join(_odir(oid), secrets.token_hex(8) + ".part")
            fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                if plain:
                    man = ox_build(c, oid, f, by=by)
                else:
                    f.write(head)
                    w = OxWriter(f, fk, prefix, hashlib.sha256(head).digest())
                    man = ox_build(c, oid, w, by=by)
                    w.finish()
                f.flush()
                os.fsync(f.fileno())
            for old in os.listdir(_odir(oid)):  # one archive per organisation: the new one replaces the last
                if old.endswith(OX_FILES):
                    os.remove(os.path.join(_odir(oid), old))
            os.replace(part, os.path.join(_odir(oid), name))
            part = None
            size = os.path.getsize(os.path.join(_odir(oid), name))
            done = now_utc()
            _state_set(oid, {"state": "done", "by": uid, "started_at": _state(oid).get("started_at") if _state(oid) else iso(when),
                             "done_at": iso(done), "expires_at": iso(done + timedelta(hours=OX_KEEP_H)), "file": name, "bytes": size, "plain": plain,
                             "files": sum(1 for k in man["files"] if k.startswith("files/")), "rows": sum(man["counts"].values()),
                             "missing": len(man["missing"])})
            c.execute("INSERT INTO office_doc_log(org_id, doc_id, user_id, at, action, target, detail) VALUES(?,?,?,?,?,?,?)",
                      (oid, None, uid, iso(done), "export", "org", json.dumps({"bytes": size, "file": name})))
            c.commit()
    except Exception as e:  # noqa: BLE001 -- the state says it failed; never a key or content in the message
        try:
            c.rollback()
        except Exception:  # noqa: BLE001 -- rollback after an error: the failed state counts
            pass
        print(f"org export {oid} failed: {type(e).__name__}", flush=True)
        st = _state(oid) or {}
        _state_set(oid, {**{k: st.get(k) for k in ("by", "started_at")}, "state": "failed", "error": type(e).__name__, "done_at": iso(now_utc())})
    finally:
        if part and os.path.exists(part):
            os.remove(part)
        c.close()
        with _OX_LOCK:
            _OX.pop(int(oid), None)


def ox_status(oid):
    st = _state(oid) or {"state": "none"}
    if st.get("state") == "running" and not _running(oid):
        st = _state(oid) or {"state": "none"}  # #3506: the run may have written its end and finished after st was read
        if st.get("state") == "running":
            st = {**st, "state": "failed", "error": "interrupted"}
    if st.get("state") == "done":
        p = os.path.join(_odir(oid), st.get("file") or "")
        if not st.get("file") or not os.path.isfile(p) or st.get("expires_at", "") <= iso(now_utc()):
            st = {"state": "none"}
    out = {k: st.get(k) for k in ("state", "started_at", "done_at", "expires_at", "file", "bytes", "files", "plain", "missing") if st.get(k) is not None}
    if st.get("state") == "failed":
        out["error"] = tr("The export was interrupted. Please start it again.") if st.get("error") == "interrupted" else tr("The export failed. Please try again later or ask the server admin (server log).")
    return out


OX_CLEAN = {"at": 0.0}


def ox_cleanup(c=None, force=False):
    """Watchdog, at most every 10 minutes: removes archives after OX_KEEP_H hours, leftovers of interrupted runs and the
    folders of organisations that no longer exist. Returns the number of removed files."""
    if not force and time.time() - OX_CLEAN["at"] < 600:
        return 0
    OX_CLEAN["at"] = time.time()
    if not os.path.isdir(EXPORT_DIR):
        return 0
    own = c is None
    c = c or connect()
    n = 0
    try:
        with system_ctx(c):  # clean-up: which organisations still exist (ids only, no content)
            orgs = {r[0] for r in c.execute("SELECT id FROM orgs")}
        now = iso(now_utc())
        for d in os.listdir(EXPORT_DIR):
            p = os.path.join(EXPORT_DIR, d)
            if not os.path.isdir(p) or not d.isdigit():
                continue
            oid = int(d)
            if _running(oid):
                continue
            st = _state(oid) or {}
            if oid not in orgs:
                n += len(os.listdir(p))
                shutil.rmtree(p, ignore_errors=True)
                continue
            for fn in os.listdir(p):
                fp = os.path.join(p, fn)
                old = time.time() - os.path.getmtime(fp) > OX_KEEP_H * 3600
                # 2.148.1 C (#2482): a .part only when stale (a run of another process writes it right now)
                if (fn.endswith(".part") and time.time() - os.path.getmtime(fp) > PART_STALE_S) or (
                        fn.endswith(OX_FILES) and (fn != st.get("file") or st.get("expires_at", "") <= now or old)):
                    os.remove(fp)
                    n += 1
            if st.get("state") == "done" and not os.path.isfile(os.path.join(p, st.get("file") or "-")):
                os.remove(os.path.join(p, "state.json"))
    finally:
        if own:
            c.close()
    return n


# ---------------------------------------------------------------- routes (people only: /api/orgs is APP_ONLY, agents 403)
def _need(c, oid, own=False):
    from ..agents.core import is_agent
    # 2.137.0 A (#2344): own = the person's own personal office, reached as organisation 0 (_ox_area)
    # 2.152.0 A (#2167): a retired one: the instance admins (review A4: not the personal office of a deleted person)
    # 2.186.0 A (#2599): its former admins only (orgretain.odl_admin_export)
    # review N1: that way only in a session of the person, never an API token (like retexport.rx_may_export)
    if not own and not (not is_agent(g.user) and getattr(g, "auth_via", None) in ("session", "proxy") and odl_admin_export(c, oid)):
        _need_org_admin(c, oid)
    return oc_enabled()


def _ox_area(c, oid):
    """2.137.0 A (#2344): (area id, own). Organisation 0 = the signed-in person's own personal office (2.138.0 #1972: its
    hidden id is never used from outside); never for agents or API tokens."""
    if oid != 0:
        return oid, False
    from flask import g
    if getattr(g, "auth_via", None) == "token":
        raise Denied(403)
    return _org_admin(c, 0), True


def ox_foreign(c, oid, own, st):
    """2.278.0 A (#3093): the archive is filtered by its starter's rights (#2561, ox_hidden_mails), so only the starter loads
    or deletes it. -> None (mine, none, own office) or (starter's name, holds): holds = the starter still administers the
    organisation (a former admin of a retired one counts); when not (left, disabled, deleted), a current admin may replace it."""
    by = st.get("by")
    if own or not by or by == me() or st.get("state") not in ("running", "done"):
        return None
    with system_ctx(c):  # another person's account and role in this organisation (structure, no content)
        u = c.execute("SELECT display_name, username, disabled FROM users WHERE id=?", (by,)).fetchone()
        o = c.execute("SELECT retired_at, retired_admins FROM orgs WHERE id=?", (oid,)).fetchone()
    if not u or u["disabled"]:
        return (u and (u["display_name"] or u["username"])) or tr("a former admin"), False
    holds = by in odl_ids(o["retired_admins"]) if o and o["retired_at"] else org_role(c, by, oid) == "admin"
    return u["display_name"] or u["username"], holds


def _ox_foreign_msg(st, name):
    """2.278.0 A (#3093): the hint for the other admins."""
    if st.get("state") == "running":
        return tr("The export of {0} is running. Only {0} can download or delete it (it is filtered by their rights).", name)
    return tr("The export of {0} is available. Only {0} can download or delete it (it is filtered by their rights).", name)


@app.get("/api/orgs/<int:oid>/export")
def ox_get(oid):
    """The state of the organisation's export: none | running | done (file, bytes, expires_at) | failed (error)."""
    c = db()
    oid, own = _ox_area(c, oid)
    on = _need(c, oid, own)
    out = ox_status(oid)
    fx = ox_foreign(c, oid, own, {**(_state(oid) or {}), "state": out.get("state")})
    if fx:  # 2.278.0 A (#3093): another admin's archive: only that it exists, by whom, no file name / download
        out = {k: out[k] for k in ("state", "started_at", "done_at", "expires_at") if k in out}
        out.update(foreign=True, by_name=fx[0], may_replace=not fx[1], hint=_ox_foreign_msg(out, fx[0]))
    return jsonify(enabled=on, keep_hours=OX_KEEP_H, **out)


@app.post("/api/orgs/<int:oid>/export")
def ox_start(oid):
    """Starts the export in the background (one at a time per organisation; 409 while one runs). 2.362.2 (#3099): without
    the server key a plain ZIP (the state says plain, the app warns), never a dead end: Art. 20 holds on every server."""
    c = db()
    oid, own = _ox_area(c, oid)
    _need(c, oid, own)
    if oc_status(c, oid).get("rotating"):  # 2.138.0 C (#1972, review F2): the archive's recovery header needs the finished key
        return err(tr("The organisation’s key is being renewed on the server. Try again when that is finished."), 409)
    uid = me()

    def guard(qc):  # 2.370.3 (#2760): under the queue's lock of the organisation: one export at a time in every process
        if _running(oid, qc):
            raise Denied(409, tr("An export of this organisation is already running"))
        st = _state(oid) or {}
        fx = ox_foreign(c, oid, own, {**st, "state": ox_status(oid).get("state")})
        if fx and fx[1]:  # 2.278.0 A (#3093): never replace the archive of another admin who still holds the organisation
            raise Denied(403, _ox_foreign_msg(st, fx[0]))
        _state_set(oid, {"state": "running", "by": uid, "started_at": iso(now_utc())})
    with _OX_LOCK:
        try:
            bgj_add("ox:export", int(oid), uid, org_id=int(oid), user_id=uid, lock=f"ox:export:{int(oid)}", guard=guard)
        except Denied as e:
            return err(e.text(), e.code)
    return jsonify(ox_status(oid)), 202


@app.get("/api/orgs/<int:oid>/export/file")
@app.post("/api/orgs/<int:oid>/export/file")  # 2.223.2 C (#2871): POST = the step-up (own office)
def ox_download(oid):
    c = db()
    oid, own = _ox_area(c, oid)
    _need(c, oid, own)
    st = ox_status(oid)
    if st.get("state") != "done":
        raise Denied(404)
    fx = ox_foreign(c, oid, own, {**(_state(oid) or {}), "state": "done"})
    if fx:  # 2.278.0 A (#3093): only the starter (the archive is filtered by their rights)
        raise Denied(403, _ox_foreign_msg(st, fx[0]))
    # 2.223.2 C (#2871): the own office (0): POST with the step-up -> a ticket, GET with it -> the archive. 2.360.0 A (#2496):
    # an organisation's archive too (a login-proxy admin relies on the session there)
    e = stepup_download(c, proxy_ok=not own)
    if e is not None:
        return e
    with system_ctx(c):  # 2.152.0 (#2167, review A4): an instance admin of a retired organisation is no member of it
        ofx_log(c, oid, "export", target="org_download", detail={"file": st["file"]}, dedupe_min=10)
    c.commit()
    return send_file(os.path.join(_odir(oid), st["file"]), as_attachment=True, download_name=st["file"],
                     mimetype="application/zip" if st["file"].endswith(OX_PLAIN_SUFFIX) else "application/octet-stream", conditional=False, max_age=0)


@app.delete("/api/orgs/<int:oid>/export")
def ox_delete(oid):
    """Removes the finished archive now (instead of waiting OX_KEEP_H hours)."""
    c = db()
    oid, own = _ox_area(c, oid)
    _need(c, oid, own)
    bgj_drop("ox:export", org_id=oid)  # 2.370.3 (review 6): an export still waiting for the worker can be removed
    if _running(oid):
        return err(tr("An export of this organisation is already running"), 409)
    st = ox_status(oid)
    fx = ox_foreign(c, oid, own, {**(_state(oid) or {}), "state": st.get("state")})
    if fx and fx[1]:  # 2.278.0 A (#3093): only the starter (a current admin clears the archive of one who left)
        raise Denied(403, _ox_foreign_msg(st, fx[0]))
    shutil.rmtree(_odir(oid), ignore_errors=True)
    return jsonify(ok=True)
