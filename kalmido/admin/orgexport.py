"""2.42.0 (#833): organisation export, stage 1 -- one organisation as an encrypted archive.

An admin of the organisation (Settings > Organisation, people only: agents and tokens never) starts it; a background thread
collects the organisation's data into a ZIP and encrypts it on the fly (the plain ZIP never touches the disk), the file waits
OX_KEEP_H hours below the data folder (exports/<org id>/, not in the backups) and is removed by the watchdog after that.

What belongs to the organisation: its lists (lists.org_id, never inboxes) with sections, members, fields, tags, status
updates, links, milestones, history, project notes, project files, forms, playbooks and customer reports (2.81.0); every
task of those lists (subtasks, field values, dependencies, people, history, the trash too), their comments and
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

from ..core.config import app, APP_VERSION, ATT_DIR, DB, OFFICE_DIR
from ..core.db import connect, db, err, iso, now_utc
from ..core.pg import system_ctx
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..accounts.session import me
from ..core.orgcrypt import _org_admin, oc_dec, oc_dec_row, oc_enabled, oc_read_file, oc_status  # 2.149.0 G (#2517): pulled up from functions

EXPORT_DIR = os.environ.get("TASKS_EXPORT_DIR", os.path.join(os.path.dirname(DB), "exports"))
OX_KEEP_H = 24  # a finished archive waits this long, then the watchdog removes it
PART_STALE_S = 6 * 3600  # 2.148.1 C (#2482): an unfinished export file older than this is left over (runs end long before)
OX_MAGIC = b"KALMIDO-ORGX\n"
OX_FORMAT = 1
OX_BLOCK = 1 << 20  # 1 MiB of plaintext per block
OX_FK_AAD = b"kalmido-orgx-fk|1|"
OX_SUFFIX = ".kalmido-export"
OX_PAGE = 1000  # rows per query of the big tables (keyset paging)
OX_NO_KEY = N_("The organisation export needs the server key KALMIDO_SECRET_KEY (the archive is encrypted with the organisation’s key), see SELF-HOSTING.md.")
# never in an archive, whatever table they are in (credentials, secrets, hashes of them, push keys, 2FA)
OX_SECRET_COLS = frozenset((
    "password_hash", "password", "pw_hash", "pw_rev", "token", "token_hash", "secret", "hook_secret", "totp_secret", "totp_step",
    "drop_token", "ical_token", "drop_token_hash", "ical_token_hash", "p256dh",  # 2.138.0 C (#1907): the hashes too
    "auth", "code_hash", "webauthn_handle", "oidc_subject", "proxy_login", "endpoint",
    "etags", "api_key", "access_token", "refresh_token",
    "hint"))  # 2.55.0 (#1455): the last characters of a newsletter connection's access data (nl_conns)

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
    if table == "portal_tickets":  # 2.81.0 (#1866): sealed with the server key -> plain inside the encrypted archive; the
        from ..accounts.login import unseal  # keyed hash only works on this server (token / token_hash: OX_SECRET_COLS)
        try:
            row["email"] = unseal(c, "portal-email", row["email"]) if row.get("email") else ""
        except Exception:  # noqa: BLE001  (sealed under an older server key: leave the address out, not the export)
            row["email"] = ""
        row.pop("email_hash", None)
    return row


def _clean(c, oid, table, r):
    row = {k: v for k, v in dict(r).items() if k not in OX_SECRET_COLS}
    return _ox_dec_row(c, oid, table, row)


def _table_cols(c, table):
    return {r[0] for r in c.execute("SELECT column_name FROM information_schema.columns WHERE table_schema=current_schema() AND table_name=?", (table,))}


def _rows(c, oid, table, where, args, paged=True):
    """Every row of table matching where (keyset pages on id when the table has one: big tables never sit in memory whole)."""
    if paged and "id" in _table_cols(c, table):
        last = None
        while True:
            q = f"SELECT * FROM {table} WHERE ({where})" + (" AND id>?" if last is not None else "") + f" ORDER BY id LIMIT {OX_PAGE}"
            rs = c.execute(q, (*args, last) if last is not None else tuple(args)).fetchall()
            for r in rs:
                yield _clean(c, oid, table, r)
            if len(rs) < OX_PAGE:
                return
            last = rs[-1]["id"]
    else:
        for r in c.execute(f"SELECT * FROM {table} WHERE ({where})", tuple(args)).fetchall():
            yield _clean(c, oid, table, r)


LSQ = "SELECT id FROM lists WHERE org_id=? AND is_inbox=0 AND deleted_at IS NULL"  # 2.102.0 A (#1988): not the list trash
TSQ = f"SELECT id FROM tasks WHERE list_id IN ({LSQ})"
DSQ = "SELECT id FROM office_docs WHERE org_id=?"
# (archive name, table, where; every "?" is the organisation id) -- the order of the archive
OX_AREAS = (
    ("lists.json", "lists", "org_id=? AND is_inbox=0"),
    ("lists/sections.json", "sections", f"list_id IN ({LSQ})"),
    ("lists/members.json", "list_members", f"list_id IN ({LSQ})"),
    ("lists/fields.json", "list_fields", f"list_id IN ({LSQ})"),
    ("lists/tags.json", "list_tags", f"list_id IN ({LSQ})"),
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
    ("lists/playbooks.json", "playbooks", f"list_id IN ({LSQ})"),
    ("lists/sprints.json", "sprints", f"list_id IN ({LSQ})"),  # 2.137.0 C (#2344): sprints of the lists (tasks.sprint_id)
    # 2.81.0 (#1866): customer reports of those lists (team/portal.py): the address in plain text, never the status link
    ("portal/tickets.json", "portal_tickets", f"list_id IN ({LSQ})"),
    ("lists/admin_log.json", "org_list_log", "org_id=?"),
    ("tasks.json", "tasks", f"list_id IN ({LSQ})"),
    ("tasks/dependencies.json", "task_deps", f"task_id IN ({TSQ})"),
    ("tasks/field_values.json", "task_field_values", f"task_id IN ({TSQ})"),
    ("tasks/tags.json", "task_list_tags", f"task_id IN ({TSQ})"),
    ("tasks/people.json", "task_people", f"task_id IN ({TSQ})"),
    ("tasks/links.json", "task_links", f"task_id IN ({TSQ})"),  # 2.137.0 C (#2344): a task placed in a further list
    ("tasks/history.json", "activity", f"task_id IN ({TSQ})"),
    ("tasks/encrypted_notes.json", "task_enc_notes", f"task_id IN ({TSQ})"),  # 2.42.0 (#828, agent A): browser-encrypted, as stored
    ("tasks/locked_notes.json", "task_note_locks", f"task_id IN ({TSQ})"),  # 2.48.0 (#1642): locked notes, browser-encrypted, as stored
    ("time_entries.json", "time_entries", f"list_id IN ({LSQ})"),
    ("time_sheets.json", "time_sheets", "org_id=?"),  # 2.137.0 C (#2344): monthly timesheets (note decrypted like the others)
    ("comments.json", "comments", f"task_id IN ({TSQ})"),
    ("comments/reactions.json", "comment_reactions", f"comment_id IN (SELECT id FROM comments WHERE task_id IN ({TSQ}))"),
    ("attachments.json", "attachments", f"task_id IN ({TSQ})"),
    # 2.48.0 (#1207): the organisation's file store (folders, files, versions, shares, history; the trash too)
    ("store/nodes.json", "fs_nodes", "org_id=?"),
    ("store/versions.json", "fs_versions", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)"),
    ("store/shares.json", "fs_shares", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)"),
    ("store/history.json", "fs_log", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)"),
    ("chat/channels.json", "tchat_rooms", f"kind='list' AND list_id IN ({LSQ})"),
    ("chat/messages.json", "tchat_msgs", f"room_id IN (SELECT id FROM tchat_rooms WHERE kind='list' AND list_id IN ({LSQ}))"),
    ("chat/reactions.json", "tchat_rx", f"message_id IN (SELECT m.id FROM tchat_msgs m JOIN tchat_rooms r ON r.id=m.room_id WHERE r.kind='list' AND r.list_id IN ({LSQ}))"),  # 2.137.0 C (#2344)
    ("calendars.json", "ev_cals", "org_id=?"),
    ("calendars/members.json", "ev_cal_members", "cal_id IN (SELECT id FROM ev_cals WHERE org_id=?)"),
    ("events.json", "events", "cal_id IN (SELECT id FROM ev_cals WHERE org_id=?)"),
    ("events/attendees.json", "event_attendees", "event_id IN (SELECT id FROM events WHERE cal_id IN (SELECT id FROM ev_cals WHERE org_id=?))"),
    ("books.json", "books", "org_id=?"),
    ("books/members.json", "book_members", "book_id IN (SELECT id FROM books WHERE org_id=?)"),
    ("books/contacts.json", "contacts", "book_id IN (SELECT id FROM books WHERE org_id=?)"),
    # 2.55.0 (#1455): the newsletter connection (its column "secret" never: see the list above), segments, members, log
    ("newsletter/connection.json", "nl_conns", "org_id=?"),
    ("newsletter/segments.json", "nl_segments", "org_id=?"),
    ("newsletter/members.json", "nl_members", "org_id=?"),
    ("newsletter/runs.json", "nl_runs", "org_id=?"),
    ("clients.json", "clients", "org_id=?"),
    ("office/company.json", "office_company", "org_id=?"),
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
    ("office/procdocs.json", "office_procdocs", "org_id=?"),  # 2.148.0 C (#2472): versions of the procedure documentation
    ("office/suppliers.json", "office_suppliers", "org_id=?"),  # 2.148.0 D (#2458): creditors of the DATEV import
    ("office/opening_balances.json", "office_opening_balances", "org_id=?"),  # 2.148.0 D (#2458)
    ("office/datev_guids.json", "office_datev_guids", "org_id=?"),  # 2.188.0 A (#2498): kept GUIDs of the DATEV receipt images
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
    ("office/doc_templates.json", "office_doc_templates", "org_id=?"),
    ("office/gen_docs.json", "office_gen_docs", "org_id=?"),
    ("office/privacy_sheets.json", "office_privacy_sheets", "org_id=?"),  # 2.154.0 C (#2192): data protection sheets of a client
    ("office/vehicles.json", "office_vehicles", "org_id=?"),
    ("office/drives.json", "office_drives", "org_id=?"),
    ("office/drive_log.json", "office_drive_log", "org_id=?"),
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
    ("wiki/versions.json", "wiki_versions", "org_id=?"),  # 2.137.0 B (#2344): the history of the pages (texts decrypted)
    ("sheets/sheets.json", "sheets", "org_id=?"),  # 2.89.0 (#1916): tables with their columns, rows and cells
    ("sheets/columns.json", "sheet_columns", "sheet_id IN (SELECT id FROM sheets WHERE org_id=?)"),
    ("sheets/rows.json", "sheet_rows", "sheet_id IN (SELECT id FROM sheets WHERE org_id=?)"),
    ("sheets/cells.json", "sheet_cells", "sheet_id IN (SELECT id FROM sheets WHERE org_id=?)"),
    ("sheets/links.json", "sheet_links", "sheet_id IN (SELECT id FROM sheets WHERE org_id=?)"),  # 2.89.0 (#1916, D): carried over by button
    ("sheets/shares.json", "sheet_shares", "org_id=?"),  # 2.124.0 C (#2113): single tables shared with people / agents
    ("sheets/files.json", "sheet_files", "org_id=?"),  # 2.124.0 B (#2110): files of file cells (the rows; names, sizes)
    ("sheets/history.json", "sheet_hist", "sheet_id IN (SELECT id FROM sheets WHERE org_id=?)"),  # 2.124.0 B (#2112): cell history
    ("videos/reviews.json", "video_reviews", "org_id=?"),  # 2.99.1 A (#1959): video sign-offs (links only), versions, comments
    ("videos/versions.json", "video_versions", "org_id=?"),
    ("videos/comments.json", "video_comments", "org_id=?"),
    # 2.48.0 (#1111): documents (recognised text, amounts, sender names and rules decrypted); not the learnt models, not the
    # keyed word index (both are rebuilt from the documents), not the forwarding addresses (their token is a secret)
    ("documents/meta.json", "doc_meta", "org_id=?"),
    ("documents/senders.json", "doc_senders", "org_id=?"),
    ("documents/types.json", "doc_types", "org_id=?"),
    ("documents/tags.json", "doc_tags", "org_id=?"),
    ("documents/document_tags.json", "doc_node_tags", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)"),  # 2.122.0 B (#2099): + files / folders
    ("documents/fields.json", "doc_fields", "org_id=?"),  # 2.153.0 (#2179): custom fields + their values (decrypted)
    ("documents/field_values.json", "doc_field_values", "org_id=?"),
    ("documents/rules.json", "doc_rules", "org_id=?"),
    ("documents/settings.json", "doc_cfg", "org_id=?"),
    ("documents/receipts.json", "rc_receipts", "org_id=?"),  # 2.137.0 B (#2344): project and category of receipts (set by people)
    ("hub/absences.json", "hub_absences", "org_id=?"),  # 2.50.0 (#1195): absences (kind + note decrypted like the others)
    ("hub/bookings.json", "hub_bookings", "org_id=?"),  # 2.50.0 (#1194): bookings of the disposition
    ("hub/leave_quota.json", "hub_leave_quota", "org_id=?"),  # 2.125.0 A (#2117): vacation accounts
    ("hub/mails.json", "hub_mails", "org_id=?"),  # 2.84.0 A (#1198): filed e-mails (texts decrypted; not the addresses, not the word index)
    ("hub/mailbox.json", "hub_mailboxes", "org_id=?"),  # 2.144.5 B (#2410): the workspace mailbox (servers, user names, sender; never "secret")
)
OX_NOT_INCLUDED = (
    "private lists and private sharing of the members (lists without the organisation), other organisations",
    "passwords, sessions, API tokens, app passwords, two-factor data, push subscriptions, webhooks and their secrets",
    "connections with credentials (Git, Paperless, calendar and address book subscriptions, mail-in addresses, public links)",
    "personal data of the members: settings, own tags, filters, templates, habits, News, direct messages, agent chats",
)


def _safe_part(s, n=80):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", s).strip("-.")[:n]
    return s or "file"


def ox_file_name(org_name, oid, when):
    slug = _safe_part(org_name, 40).lower()
    return f"{slug if slug != 'file' else 'org' + str(int(oid))}-{when.strftime('%Y-%m-%d')}{OX_SUFFIX}"


class _Man:
    """The manifest: rows and SHA-256 per archive entry."""

    def __init__(self):
        self.files, self.counts, self.client_enc = {}, {}, {"attachments": [], "task_notes": 0}


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
        if str(o.get("icon") or "").startswith("u:"):  # 2.87.9 (#1913): the picture file is not in the ZIP -> no dead link
            o["icon"] = ""
        _put_json(zf, man, "organisation.json", [o])
        members = c.execute("""SELECT u.id, u.username, u.display_name, u.email, COALESCE(u.kind,'user') AS kind, u.disabled, u.color, m.role
                               FROM org_members m JOIN users u ON u.id=m.user_id WHERE m.org_id=? ORDER BY u.id""", (oid,)).fetchall()
        from ..accounts.orgs import org_role
        _put_json(zf, man, "members.json", ({**dict(r), "role": org_role(c, r["id"], oid) or r["role"]} for r in members))
        for name, table, where in OX_AREAS:
            if table not in have:
                continue
            _put_json(zf, man, name, _rows(c, oid, table, where, (oid,) * where.count("?")))
        # the files: attachments of the tasks, project files of the lists, everything below OFFICE_DIR/<org id>
        enc = "enc" in _table_cols(c, "attachments")
        for r in _rows(c, oid, "attachments", f"task_id IN ({TSQ})", (oid,)):
            full = _under(ATT_DIR, r.get("path"))
            if not full:
                continue
            name = f"files/attachments/{int(r['id'])}-{_safe_part(r.get('name'))}"
            _put_bytes(zf, man, name, _read(c, full))
            if enc and r.get("enc"):
                man.client_enc["attachments"].append(name)
        for r in _rows(c, oid, "list_files", f"list_id IN ({LSQ})", (oid,)):
            full = _under(ATT_DIR, r.get("path"))
            if full:
                _put_bytes(zf, man, f"files/list_files/{int(r['id'])}-{_safe_part(r.get('name'))}", _read(c, full))
        if "fs_versions" in have:  # 2.48.0 (#1207): every version of the file store's files (decrypted like the attachments)
            for r in _rows(c, oid, "fs_versions", "node_id IN (SELECT id FROM fs_nodes WHERE org_id=?)", (oid,)):
                full = _under(ATT_DIR, r.get("path"))
                nm = c.execute("SELECT name FROM fs_nodes WHERE id=?", (r["node_id"],)).fetchone()
                if full and nm:
                    _put_bytes(zf, man, f"files/store/{int(r['node_id'])}-v{int(r['no'])}-{_safe_part(nm[0])}", _read(c, full))
        if "wiki_files" in have:  # 2.99.0 A (#2182): the files of the knowledge pages (decrypted like the attachments)
            for r in _rows(c, oid, "wiki_files", "org_id=?", (oid,)):
                full = _under(ATT_DIR, r.get("path"))
                if full:
                    _put_bytes(zf, man, f"files/wiki/{int(r['id'])}-{_safe_part(r.get('name'))}", _read(c, full))
        if "sheet_files" in have:  # 2.124.0 B (#2110): the files of table cells (decrypted like the attachments)
            for r in _rows(c, oid, "sheet_files", "org_id=?", (oid,)):
                full = _under(ATT_DIR, r.get("path"))
                if full:
                    _put_bytes(zf, man, f"files/sheets/{int(r['id'])}-{_safe_part(r.get('name'))}", _read(c, full))
        odir = os.path.join(OFFICE_DIR, str(int(oid)))
        if os.path.isdir(odir):
            for root, dirs, files in os.walk(odir):
                dirs.sort()
                for fn in sorted(files):
                    full = os.path.join(root, fn)
                    if os.path.islink(full) or not os.path.isfile(full):
                        continue
                    rel = os.path.relpath(full, odir).replace(os.sep, "/")
                    _put_bytes(zf, man, "files/office/" + "/".join(_safe_part(p) for p in rel.split("/")), _read(c, full))
        if "enc" in _table_cols(c, "tchat_msgs"):  # 2.42.0 (#909, agent A): browser-encrypted chat messages stay ciphertext
            man.client_enc["chat_messages"] = c.execute(f"""SELECT COUNT(*) FROM tchat_msgs WHERE COALESCE(enc,'')!='' AND room_id IN
                (SELECT id FROM tchat_rooms WHERE kind='list' AND list_id IN ({LSQ}))""", (oid,)).fetchone()[0]
        if "tasks/encrypted_notes.json" in man.counts:
            man.client_enc["task_notes"] = man.counts["tasks/encrypted_notes.json"]
        if "tasks/locked_notes.json" in man.counts:
            man.client_enc["locked_notes"] = man.counts["tasks/locked_notes.json"]
        if "e2e" in _table_cols(c, "lists"):  # 2.64.1 B (#1817): lists with the lock: texts are browser ciphertexts ("e2e1:...")
            lk = [r[0] for r in c.execute(f"SELECT id FROM lists WHERE e2e IS NOT NULL AND id IN ({LSQ})", (oid,))]
            if lk:
                q = ",".join("?" * len(lk))
                man.client_enc["locked_lists"] = len(lk)
                man.client_enc["locked_list_tasks"] = c.execute(f"SELECT COUNT(*) FROM tasks WHERE list_id IN ({q})", lk).fetchone()[0]
                man.client_enc["locked_list_note"] = ("Texts of lists encrypted in the browser (values starting with e2e1:) can only be "
                                                      "read in Kalmido with a member's own passphrase; no offline tool opens them.")
        if c.execute("SELECT 1 FROM wiki_spaces WHERE org_id=? AND e2e IS NOT NULL", (oid,)).fetchone():  # 2.64.3 A (#1817)
            man.client_enc["locked_wiki_pages"] = c.execute("SELECT COUNT(*) FROM wiki_pages WHERE org_id=?", (oid,)).fetchone()[0]
            man.client_enc["locked_wiki_note"] = ("Name and text of the knowledge pages of a space encrypted in the browser (values starting "
                                                  "with e2e1:) can only be read in Kalmido with a member's own passphrase; export them "
                                                  "decrypted from the knowledge pages in the app.")
        manifest = {
            "format": "kalmido-org-export", "format_version": OX_FORMAT, "kalmido_version": APP_VERSION,
            "org": {"id": int(oid), "name": org["name"]}, "created_at": iso(now_utc()), "created_by": by,
            "counts": man.counts, "files": man.files,
            "client_encrypted": {**man.client_enc, "note": "Encrypted in the browser by their author: stored here as ciphertext, only the author can open them."},
            "decrypted": "Fields and files the server encrypts with the organisation key are in plain text here; the archive itself is encrypted.",
            "not_included": list(OX_NOT_INCLUDED),
        }
        _put_bytes(zf, man, "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1, default=_jdef).encode())
    return manifest


# 2.137.0 A (#2344): the export of a personal office (office/model.py pb_personal) by its owner: only the office and the
# owner's private clients with their contact persons (org_id NULL, created by the owner: model.py pb_cl_sql) -- no lists,
# no other areas of the private space, nobody else. The import takes it into an organisation or into a personal office.
OX_PB_CLIENTS = {"clients": "org_id IS NULL AND created_by=?",
                 "office_client_contacts": "org_id IS NULL AND client_id IN (SELECT id FROM clients WHERE org_id IS NULL AND created_by=?)"}


def ox_build_personal(c, oid, out, org, have, by=None):
    man = _Man()
    owner = int(org["personal_of"])
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        o = _clean(c, oid, "orgs", org)
        o["icon"] = ""
        _put_json(zf, man, "organisation.json", [o])
        _put_json(zf, man, "members.json", [])
        for name, table, where in OX_AREAS:
            if table not in have or not (name.startswith("office/") or name == "clients.json"):
                continue
            if table in OX_PB_CLIENTS:
                _put_json(zf, man, name, _rows(c, oid, table, OX_PB_CLIENTS[table], (owner,)))
            else:
                _put_json(zf, man, name, _rows(c, oid, table, where, (oid,) * where.count("?")))
        odir = os.path.join(OFFICE_DIR, str(int(oid)))
        if os.path.isdir(odir):
            for fn in sorted(os.listdir(odir)):  # the office keeps its files in one folder (no sub folders)
                full = os.path.join(odir, fn)
                if os.path.islink(full) or not os.path.isfile(full):
                    continue
                _put_bytes(zf, man, "files/office/" + _safe_part(fn), _read(c, full))
        manifest = {
            "format": "kalmido-org-export", "format_version": OX_FORMAT, "kalmido_version": APP_VERSION,
            "org": {"id": int(oid), "name": org["name"]}, "created_at": iso(now_utc()), "created_by": by, "personal_office": 1,
            "counts": man.counts, "files": man.files, "client_encrypted": {"note": "none"},
            "decrypted": "Fields and files the server encrypts with the office key are in plain text here; the archive itself is encrypted.",
            "not_included": ["everything of the private space but the office and its clients", *OX_NOT_INCLUDED[1:2]],
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


def _running(oid):
    t = _OX.get(int(oid))
    return bool(t and t.is_alive())


def ox_run(oid, uid):
    """The thread: archive of organisation oid, started by uid."""
    c = connect()
    part = None
    try:
        with system_ctx(c):  # the organisation's rows only (every query names it); the starter is its admin
            from ..core.orgcrypt import oc_key
            org = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()
            okey = oc_key(c, oid, create=True)
            if not org or not okey:
                raise RuntimeError("no organisation key")
            u = c.execute("SELECT id, display_name, username FROM users WHERE id=?", (uid,)).fetchone()
            when = now_utc()
            from ..core.orgcrypt import rck_wrapped
            if c.execute("SELECT 1 FROM org_keys WHERE org_id=? AND rot_started_at IS NOT NULL", (oid,)).fetchone():
                raise RuntimeError("key renewal running")  # 2.138.0 C (#1972, review F2)
            rw = rck_wrapped(c, oid)  # 2.138.0 C (#1972): the recovery key opens the archive (made when there is none yet)
            c.commit()
            head, fk, prefix = ox_header(oid, org["name"], okey, iso(when), rw)
            name = ox_file_name(org["name"], oid, when)
            part = os.path.join(_odir(oid), secrets.token_hex(8) + ".part")
            fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(head)
                w = OxWriter(f, fk, prefix, hashlib.sha256(head).digest())
                man = ox_build(c, oid, w, by={"id": uid, "name": (u["display_name"] or u["username"]) if u else ""})
                w.finish()
                f.flush()
                os.fsync(f.fileno())
            for old in os.listdir(_odir(oid)):  # one archive per organisation: the new one replaces the last
                if old.endswith(OX_SUFFIX):
                    os.remove(os.path.join(_odir(oid), old))
            os.replace(part, os.path.join(_odir(oid), name))
            part = None
            size = os.path.getsize(os.path.join(_odir(oid), name))
            done = now_utc()
            _state_set(oid, {"state": "done", "by": uid, "started_at": _state(oid).get("started_at") if _state(oid) else iso(when),
                             "done_at": iso(done), "expires_at": iso(done + timedelta(hours=OX_KEEP_H)), "file": name, "bytes": size,
                             "files": sum(1 for k in man["files"] if k.startswith("files/")), "rows": sum(man["counts"].values())})
            c.execute("INSERT INTO office_doc_log(org_id, doc_id, user_id, at, action, target, detail) VALUES(?,?,?,?,?,?,?)",
                      (oid, None, uid, iso(done), "export", "org", json.dumps({"bytes": size, "file": name})))
            c.commit()
    except Exception as e:  # noqa: BLE001 -- the state says it failed; never a key or content in the message
        try:
            c.rollback()
        except Exception:  # noqa: BLE001
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
        st = {**st, "state": "failed", "error": "interrupted"}
    if st.get("state") == "done":
        p = os.path.join(_odir(oid), st.get("file") or "")
        if not st.get("file") or not os.path.isfile(p) or st.get("expires_at", "") <= iso(now_utc()):
            st = {"state": "none"}
    out = {k: st.get(k) for k in ("state", "started_at", "done_at", "expires_at", "file", "bytes", "files") if st.get(k) is not None}
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
                        fn.endswith(OX_SUFFIX) and (fn != st.get("file") or st.get("expires_at", "") <= now or old)):
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
    from ..accounts.orgs import _need_org_admin
    from ..accounts.orgretain import odl_admin_export
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


@app.get("/api/orgs/<int:oid>/export")
def ox_get(oid):
    """The state of the organisation's export: none | running | done (file, bytes, expires_at) | failed (error)."""
    c = db()
    oid, own = _ox_area(c, oid)
    on = _need(c, oid, own)
    return jsonify(enabled=on, keep_hours=OX_KEEP_H, **ox_status(oid))


@app.post("/api/orgs/<int:oid>/export")
def ox_start(oid):
    """Starts the export in the background (one at a time per organisation; 409 while one runs, or without the server key)."""
    c = db()
    oid, own = _ox_area(c, oid)
    if not _need(c, oid, own):
        return err(tr(OX_NO_KEY), 409)
    if oc_status(c, oid).get("rotating"):  # 2.138.0 C (#1972, review F2): the archive's recovery header needs the finished key
        return err(tr("The organisation’s key is being renewed on the server. Try again when that is finished."), 409)
    with _OX_LOCK:
        if _running(oid):
            return err(tr("An export of this organisation is already running"), 409)
        _state_set(oid, {"state": "running", "by": me(), "started_at": iso(now_utc())})
        t = threading.Thread(target=ox_run, args=(int(oid), me()), daemon=True)
        _OX[int(oid)] = t
        t.start()
    return jsonify(ox_status(oid)), 202


@app.get("/api/orgs/<int:oid>/export/file")
def ox_download(oid):
    c = db()
    oid, own = _ox_area(c, oid)
    _need(c, oid, own)
    st = ox_status(oid)
    if st.get("state") != "done":
        raise Denied(404)
    from ..office.ledger import ofx_log
    with system_ctx(c):  # 2.152.0 (#2167, review A4): an instance admin of a retired organisation is no member of it
        ofx_log(c, oid, "export", target="org_download", detail={"file": st["file"]}, dedupe_min=10)
    c.commit()
    return send_file(os.path.join(_odir(oid), st["file"]), as_attachment=True, download_name=st["file"],
                     mimetype="application/octet-stream", conditional=False, max_age=0)


@app.delete("/api/orgs/<int:oid>/export")
def ox_delete(oid):
    """Removes the finished archive now (instead of waiting OX_KEEP_H hours)."""
    c = db()
    oid, own = _ox_area(c, oid)
    _need(c, oid, own)
    if _running(oid):
        return err(tr("An export of this organisation is already running"), 409)
    shutil.rmtree(_odir(oid), ignore_errors=True)
    return jsonify(ok=True)
