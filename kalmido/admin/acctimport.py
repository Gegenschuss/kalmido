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
from decimal import Decimal, InvalidOperation  # 2.765.0 (#5315)
from datetime import date, datetime, timedelta

from flask import g, jsonify, request

from ..core.config import app, ATT_DIR, MAX_FILE_MB, PUBLIC_URL
from ..core.config import USERNAME_RE  # 2.278.0 B (#3094)
from ..accounts.orgs import visible_people as umz_visible  # 2.278.0 B (#3094)
from ..core.serializers import unlink_files  # 2.464.0 (#3865)
from ..api.common import hit_limit  # 2.585.0 (#4350, review 2)
from ..core.pg import write_lock  # review 2.611 (#4866)
from ..files.upsafe import up_after_store, up_check, UploadRefused  # 2.464.0 (#3865): pulled up from functions
from ..lists.projects import LIST_FILES_SUB
from ..lists.tplextra import tx_import, tx_keys
from ..tasks.attachments import safe_name
from .hosting import QuotaExceeded, fmt_bytes, quota_guard, quota_info
from ..core.db import body, bump, connect, db, err, iso, iso_ms, now_utc, parse_iso, usettings, uset, create_user, DataError, IntegrityError
from ..core.pg import insert_id, system_ctx, ts_canon  # 2.1095.0 (#5306): ts_canon
from ..core.moneycol import MC_COLS, MC_FITS  # 2.765.0 (#5315): the money columns NUMERIC(14,2) and their rule
from ..core.coltype import CT_JSON  # 2.1111.0 (#5953): the JSON columns that were TEXT (JSONB now)
from ..core.errors import BadInput  # 2.273.0 A (#3030)
from ..accounts.settings import clean_look_pref, clean_setting  # 2.273.0 A (#3030); 2.363.4 (#3127): clean_setting
from ..tasks.snippets import snip_clean  # 2.273.0 A (#3030)
from ..core.i18n import lang, LANGS, N_, short_day, stored_join, tr as _tr_base, tr_stored  # 2.531.0 (#4317): + short_day
from ..core.access import Denied, ROLES, list_role, my_inbox, my_max_sort, WRITE_ROLES
from ..accounts.session import me
from ..accounts.bgjobs import bgj_active, bgj_add, bgj_busy, bgj_drop, bgj_fn  # 2.370.3 (#2760)
from ..lists.listhead import HEAD_STYLES  # 2.459.0 (#3849)
from ..lists.lists import clean_color, LIST_COLOR_RE
from ..core.objtags import otg_add, otg_find, otg_link, otg_user_add  # 2.947.0 (#5275); 2.955.0 (#5276): otg_user_add
from ..core.objexport import oex_org_map, oex_read, oex_umz_left  # 2.1093.0 (#5289): the export register of the core
from ..lists.fields import fx_tpl_fix  # 2.362.4 (#3100)
from ..lists.formula import fx_display  # 2.362.4 (#3100)
from ..lists.templates import tpl_clean  # 2.362.4 (#3100)
from ..tasks.validation import (DATE_MAX_Y, DATE_MIN_Y, DURATION_MAX, PRIORITIES, REM_COUNT, REM_MAX, REM_MIN, rr_feasible, rr_norm,
                                rr_problem, valid_date, valid_hm, valid_plan_start)
from .orgexport import EXPORT_DIR, OX_SECRET_COLS, _safe_part
from .acctexport import (UMZ_BLOCK, UMZ_FORMAT, UMZ_HEAD, UMZ_V, UmzReader, UmzWriter, umz_key, umz_person, umz_space_ok,
                         umz_user_conn, umz_write_state)
from ..core.orgcrypt import OrgCryptError, oc_user_space, oc_write_file, rck_parse, rck_resolve  # 2.149.0 G (#2517); 2.531.0: + OrgCryptError, rck_resolve pulled up (layer budget)
from ..core.schema import MAX_DEPTH  # 2.149.0 G (#2517): pulled up from functions
from ..life.model import JOURNAL_MAX, jr_open, jr_seal  # 2.306.0 A (#2885); 2.531.0 (#4317): + JOURNAL_MAX, jr_open
from ..accounts.orginvite import ojn_drop_later, ojn_invite, ojn_later  # 2.278.0 A (#3095)
from ..collab.e2e import _pub, e2e_has_keys, e2e_import_keys, e2e_same_keys  # 2.278.0 C (#3091)
from .oilock import oil_preview, OIL_NODES, OIL_LOCKS, OIL_KEYS  # #4300: locked folders of the file store
from ..hub.absence import ABS_HALF, ABS_KINDS, ABS_NOTE_MAX, ABS_SPAN_MAX, DATE_RE  # 2.765.0 (#3965)
from .acctexport import umz_email_hash  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgs import org_role, user_orgs, visible_people, _need_org_admin  # 2.369.5 (#2517): pulled up from functions
from ..integrations.importers import ACCOUNT_IMPORT_UNDO_DAYS, IMPORT_RATE, imp_undo_after, imp_undo_lists, imp_undo_split, imp_undo_trash  # 2.369.5 (#2517): pulled up from functions
from ..lists.lists import clean_folder, list_created, LIST_NAME_MAX, _folder_member_add  # 2.369.5 (#2517): pulled up from functions
from ..tasks.validation import CONTENT_MAX, TITLE_MAX  # 2.369.5 (#2517): pulled up from functions
from ..contacts.bulk import bk_occ_drop, ctt_unlink  # 2.370.4 (#3089)
from ..accounts.invite import invite_new  # 2.369.5 (#2517): pulled up from functions
from .orgexport import OX_MAGIC, OX_FK_AAD  # 2.369.5 (#2517): pulled up from functions
from ..hub.mailbox import mbx_take_values  # 2.369.5 (#2517): pulled up from functions

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
# 2.278.0 C (#3091): the AAD a browser ciphertext of the old server carries (collab/e2e.py, notelock.js, e2e.js)
UMZ_AAD_RE = re.compile(r"kalmido-(locknote|note|file):v1:[0-9]{1,19}:[0-9]{1,19}|kalmido-e2e:v1:[0-9]{1,19}")


def umz_legacy_aad(prefix, old, *ids):
    """2.278.0 C (#3091): the old AAD of a ciphertext: the one the file already carries (moved twice), else from the old ids."""
    if isinstance(old, str) and UMZ_AAD_RE.fullmatch(old) and old.startswith(prefix + ":"):
        return old
    ids = [_oid(x) for x in ids]
    return f"{prefix}:" + ":".join(str(x) for x in ids) if all(ids) else None
UMZ_UID_RE = re.compile(r"[A-Za-z0-9@._-]{1,200}")  # review N7: a contact uid taken from the file
# settings that move along (nothing about security, sign-in, push or connections)
UMZ_SETTINGS = ("lang", "allday_time", "default_reminder", "work_start", "work_end", "show_done_views", "show_done_new",
                "show_done_default", "group_order", "comment_order", "time_rounding", "time_currency", "capacity_h",
                "list_emoji", "side_icons", "prio_bg", "celebrate", "progress_subtasks", "hide_progress", "folders",
                "look", "workdays")  # 2.273.0 A (#3030): the appearance (theme) and the working days move along too
# 2.363.4 (#3127): the other settings that move along -- an allow list of preferences without ids of the old server, checked like a
# value set by hand (accounts/settings.py clean_setting); never sign-in, security, push, mail delivery or connections
UMZ_SETTINGS_MORE = ("detail_split", "detail_cm_fold", "detail_fold", "agent_steps_live", "agent_steps_always", "agent_quota_show",
                     "chat_read_receipts", "chat_kbd_agent", "chat_kbd_team", "today_inbox", "pomo_focus", "pomo_short", "pomo_long",
                     "pomo_long_every", "time_autostop_h", "time_focus", "time_target", "time_split_midnight", "tz", "hide_blocked_today",
                     "fav_only", "fav_suggest", "mine_view", "mine_board", "mine_board_by", "date_confirm", "start_page", "person_colors",
                     "list_color_dot", "ws_accent", "side_progress", "row_icons", "row_icons_custom", "side_count", "side_dots", "side_share",
                     "cal_today", "cal_tasks", "cal_holidays", "cal_abs", "cal_abs_team", "holiday_state", "tours_more", "features",
                     "nav_order", "mods_all", "folders_closed", "folder_colors", "photo_meta_strip", "week_start", "time_format",
                     "date_order", "mail_trim_fwd", "mail_trim_eml")
UMZ_SETTINGS_ALL = frozenset(UMZ_SETTINGS + UMZ_SETTINGS_MORE)
def _umz_delivery(t):
    """2.392.2 (#3365, review): the delivery state of an imported task: in progress names a job of the old server (gone here),
    waiting keeps only its note (the task it waited for is an id of the old server); parked stays with its reason."""
    st, note = t.get("delivery") or "", _txt(t.get("delivery_note"), 500)
    if st == "parked" or (st == "waiting" and note):
        return {"delivery": st, "delivery_note": note}
    return {"delivery": "", "delivery_note": "", "delivery_at": None}


# columns never taken from a file, in addition to ids, *_id / *_by columns, foreign keys and OX_SECRET_COLS
UMZ_DROP = {
    "lists": {"is_inbox", "family", "agent_tidy", "agent_listen", "agent_members", "agent_peers", "agent_followup", "tidy_agent",
              "org_visibility", "org_edit", "git_folder_off", "icon", "icon_size", "header_size",  # 2.498.0 (#3884): sizes are measured here
              "header_file",  # 2.459.0 (#3849): a token of the old server (orgimport.oi_pictures makes a new one with the picture)
              # 2.538.0 (#4372, review 2646 finding 3): a locked project never moves along (umz_write); an archive whose e2e is
              # set but empty ("") would bring one in locked, with its plain texts: the lock state never comes from a file
              "e2e", "e2e_gen", "e2e_rotate", "e2e_reenc", "e2e_at"},
    "tasks": {"rotation", "approval", "fam", "tt_id", "nag_at", "wait_fired",
              "irreversible_yes_at", "acceptance_of"},  # 2.392.0 C (#3370): a yes is given here, an environment id means nothing here
    # 2.370.2 (#3088): client_ref like the notes'; 2.972.0 (#5272): the rows go into obj_comments (kind task), extra is set by
    # the caller from the file's portal / rule_name (a proposal or a choice of the old server never comes along)
    "obj_comments": {"mentions", "extra", "ext_name", "client_ref", "kind"},
    "attachments": {"path", "enc_by"},
    "list_files": {"path"},
    "video_versions": {"uploaded"},  # 2.662.0 (#5041): the review's rights stand in for the file only for an upload made here
    "events": {"href"},
    "contacts": {"href"},
    "notes": {"client_ref"},  # 2.362.0 (#3090, review): the offline outbox mark of the old server (unique per person)
    # 2.278.0 B (#3094): time_entries.billed_at is kept (umz_billed): a billed entry never comes open again (billed twice)
}
# 2.273.0 A (#3030): the parts of an account export the import reads (umz_write; people + list_members through the sharing
# step, server_links as a hint of the preview). Every other part of the file is named in the preview and in the result as
# staying on the old server (umz_left): a part the import learns to read = its name here, one line.
# 2.1093.0 (#5289, stage Q11): the parts made of the core's tables (comments, list_tags, task_list_tags, task_tags, org_tags,
# video_comments, task_bell, task_watchers) come from the export register (core/objexport.py read / org part): UMZ_READ_OWN holds
# the old tables' parts, UMZ_READ both
UMZ_READ_OWN = frozenset((
    "lists", "list_members", "sections", "list_fields", "list_status", "list_links", "list_milestones", "tasks",
    "task_deps", "task_field_values", "task_note_locks", "attachments", "list_files",
    "time_entries", "habits", "habit_logs", "filters", "templates", "address_books", "contacts", "event_calendars", "events",
    "event_attendees", "journal", "mailbox", "settings", "people", "server_links",
    "e2e_keys",  # 2.278.0: the browser keys
    "notes", "task_enc_notes",  # 2.362.0 (#3090): project notes, my encrypted task notes
    "sprints", "task_links", "list_rules", "portal_tickets",  # 2.455.0 (#3469)
    "task_decisions",  # 2.392.0 C (#3370)
    "task_relations",  # 2.576.0 (#3371)
    "template_files",  # 2.464.0 (#3865)
    "private_files", "private_versions", "private_area_roots", "wiki_pages", "wiki_files",  # #3470: umz_private (UMZ_PRIVATE)
    "private_locks", "private_lock_keys",  # #4300: admin/oilock.py
    "sheets", "sheet_columns", "sheet_rows", "sheet_cells", "sheet_files", "sheet_hist",
    # 2.363.4 (#3127): filed mails, video sign-offs, notepads and project playbooks through the areas (umz_private), the rest
    # of my own rows directly (admin/umz_more.py)
    "hub_mails", "video_reviews", "video_versions", "list_notepads", "playbooks", "bookmarks", "pomos",
    "contact_care", "view_layouts", "list_layouts",
    "kid_parents", "conn_links",  # 2.531.0 (#4317 F12): admin/umz_more.py _family
    # 2.765.0 (#3965): absences (my personal office) and timesheets through the areas (umz_private), the household budgets
    # (life/budget.py bud_import) and a folder's playbooks directly (admin/umz_more.py)
    "absences", "timesheets", "budgets",
    "ticket_types", "org_fields",  # 2.995.0 (#5602): my own ticket types and field schema through the areas (UMZ_PRIVATE_MORE)
))
UMZ_READ = UMZ_READ_OWN | oex_read()
# #3470: the private file store, knowledge pages and tables of an account export go through the organisation import's areas
# (admin/oi_store.py) into my private space: account part -> archive entry of the organisation export
UMZ_PRIVATE = (
    ("private_files", "store/nodes.json"), ("private_area_roots", "store/area_roots.json"), ("private_versions", "store/versions.json"),
    ("private_locks", "store/locks.json"), ("private_lock_keys", "store/lock_keys.json"),  # #4300
    ("wiki_pages", "wiki/pages.json"), ("wiki_files", "wiki/files.json"),
    ("sheets", "sheets/sheets.json"), ("sheet_columns", "sheets/columns.json"), ("sheet_rows", "sheets/rows.json"),
    ("sheet_cells", "sheets/cells.json"), ("sheet_files", "sheets/files.json"), ("sheet_hist", "sheets/history.json"),
)
# 2.1097.0 (#5949): the parts made of the core's tables name themselves in the export register (core/objexport.py acct / acct_more,
# the third field: shared_comments, list_notif, folder_notif, written_comments, reactions); UMZ_LEFT_OWN holds the old tables'
# parts, UMZ_LEFT both (a register part joins the first entry of its name)
UMZ_LEFT_OWN = (  # (name, parts): the first part counts, the others only when it is empty; a name used twice adds up
    # #3470: tables, knowledge pages and my files come along (UMZ_PRIVATE); 2.363.4 (#3127): mails, video sign-offs, bookmarks,
    # focus sessions, notepads, playbooks, staying in touch, saved arrangements and task bells too (what stays: umz_left counts it)
    # 2.765.0 (#3965): household budgets, absences and timesheets come along too (UMZ_READ)
    (N_("Playbooks"), ("playbook_proposals",)),
    (N_("Saved arrangements"), ("view_layout_offers",)),
    (N_("History"), ("activity",)), (N_("Direct messages"), ("direct_messages",)), (N_("Agent chats"), ("agent_chats",)),
    (N_("Shared with me"), ("shared_lists",)),
    (N_("Environments"), ("list_envs", "env_deploys")), (N_("Devices"), ("device_links",)),
    (N_("Assistant"), ("assistant_access", "assistant_log")),
    (N_("Booking page"), ("appt_pages", "appt_types", "appt_bookings")), (N_("Polls"), ("polls", "poll_options", "poll_votes")),  # 2.360.2 D (#2561)
    (N_("Forms"), ("forms", "form_entries")), (N_("Holiday allowance"), ("leave_quota",)),
    (N_("Module cards"), ("module_cards",)),  # 2.575.0 (#3778): my private module cards (made again on the target)
    (N_("Log"), ("agent_steps",)), (N_("Log"), ("org_list_actions",)), (N_("Log"), ("merge_runs",)),
    (N_("API tokens"), ("api_tokens",)), (N_("Webhooks"), ("webhooks",)), (N_("Calendar subscriptions"), ("calendar_subscriptions",)),
    (N_("Karakeep connection"), ("karakeep",)), (N_("Newsletter connection"), ("newsletter_connection",)),
    (N_("Newsletter"), ("newsletter_segments", "newsletter_runs")), (N_("Planned agent jobs"), ("agent_schedules",)),
    (N_("Public links"), ("public_links",)), (N_("Feeds"), ("feeds",)),  # 2.85.0 B (#1162): moved by OPML export / import
    # 2.360.4 (#3248): what I wrote or got elsewhere; the preview showed the technical names of these parts
    (N_("Channel messages"), ("channel_messages",)),
    (N_("Tasks in other projects"), ("other_tasks",)), (N_("Tasks I take part in"), ("task_people",)),
    (N_("Stars"), ("kid_stars",)), (N_("Received notifications"), ("notifications",)), (N_("Sign-ins"), ("sessions",)),
    (N_("Push devices"), ("push_devices",)), (N_("Agent chat settings"), ("agent_chat_prefs",)),
)
UMZ_LEFT = oex_umz_left(UMZ_LEFT_OWN)
# 2.531.0 (#4317) F5: the parts of UMZ_LEFT are never read: they count against neither size limit (a long history of a person
# made a file that exports but never imports); their checksum is checked when the import runs, their rows counted from the manifest
UMZ_LEFT_PARTS = frozenset(p for _w, ps in UMZ_LEFT for p in ps) - UMZ_READ
# 2.531.0 (#4317) F11: the area a refused row of a table is named under in the result (else its technical name)
UMZ_REFUSED_AREA = {
    "lists": N_("Projects"), "sections": N_("Sections"), "list_fields": N_("Custom fields"), "list_tags": N_("Project tags"), "org_tags": N_("Labels of the organisation"),  # 2.947.0 (#5275)
    "list_milestones": N_("Milestones"), "sprints": N_("Sprints"), "tasks": N_("Tasks"), "task_deps": N_("Dependencies"),
    "task_relations": N_("Relations"),  # 2.576.0 (#3371)
    "task_field_values": N_("Custom fields"), "task_tags": N_("Tags"), "task_list_tags": N_("Project tags"),
    "task_note_locks": N_("Encrypted notes"), "task_enc_notes": N_("Encrypted notes"), "notes": N_("Project notes"),
    "obj_comments": N_("Comments"), "attachments": N_("Attachments"), "list_files": N_("Files"), "time_entries": N_("Time entries"),
    "habits": N_("Habits"), "habit_logs": N_("Habits"), "filters": N_("Saved filters"), "templates": N_("Templates"),
    "template_files": N_("Templates"), "books": N_("Address books"), "contacts": N_("Contacts"), "ev_cals": N_("Calendars"),
    "events": N_("Events"), "event_attendees": N_("Events"), "journal": N_("Journal"), "bookmarks": N_("Bookmarks"),
    "pomos": N_("Focus sessions"), "contact_care": N_("Staying in touch"), "list_rules": N_("Rules"),
}
# 2.531.0 (#4317) F6: the person columns of a task besides the assignee -> the role named when it does not come along
UMZ_TASK_ROLES = (("approver_id", N_("Approver")), ("reviewer_id", N_("Reviewer")), ("review_by", N_("Reviewer")),
                  ("wait_by", N_("Waiting on")), ("delegate_agent_id", N_("Delegated agent")), ("assignee_group_id", N_("Group")))
UMZ_ROLE_LOST = N_("Role on tasks not imported (the person is not on this server or was not selected): {0}")
UMZ_AREAS_LEFT = N_("These areas stay on the old server: {0}")
UMZ_WARN_MAX = 50  # the result names at most this many warnings, the ones a run must always name (run.must) on top and first

_UMI = {}  # user id -> running check / import thread (of this process; 2.370.3 (#2760): the queue row tells it for every process)
_UMI_START = {}  # 2.308.0 (#3261): user id -> steps waiting for that worker's end before they start their own
# 2.148.1 C (#2492, #2485): at most this many checks / imports at once on the whole server (every process). 2.370.3 (#2760):
# a slot is a waiting or running queue row of UMZ_IMPORT_KINDS (counted under the queue lock "umz:import" when one is added),
# no longer an advisory lock a thread of the web process holds
UMZ_PARALLEL = max(1, _env_mb("KALMIDO_ACCOUNT_IMPORT_PARALLEL", 2))
UMZ_KINDS = ("umz:check", "umz:unlock", "umz:import")  # 2.370.3 (#2760): the steps of an account import (queue rows)
UMZ_IMPORT_KINDS = UMZ_KINDS + ("wki:import",)  # the import slots are shared with the knowledge import (admin/wkimport.py)
UMZ_SETTLE_S = 5  # 2.308.0 (#3261): how long a new step waits for the person's previous worker to end
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


def _busy(uid, c=None):
    """2.370.3 (#2760): a step of my import waits or runs: its queue row (any process), or a thread of this process (the
    queue's fallback without a database)."""
    t = _UMI.get(int(uid))
    if t and t.is_alive():
        return True
    try:
        return bgj_busy(UMZ_KINDS, user_id=int(uid), c=c)
    except Exception:  # noqa: BLE001 -- 2.547.0 (#4295): no answer from the database counts as busy (was: not busy; a running import
        return True    # of another process then looked "interrupted", a second start / the clean-up could go next to it)


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


def _sum_entry(zf, zi, sha):
    """2.531.0 (#4317) F5: the checksum of a part that is never read, streamed (no size limit, nothing kept in memory)."""
    h = hashlib.sha256()
    with zf.open(zi) as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    if h.hexdigest() != sha:
        raise UmzBad(N_("Checksum wrong: {0}. The file is damaged or was changed."), zi.filename)


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
        data, unread = {}, {}

        def left(p):  # 2.531.0 (#4317) F5: a part of UMZ_LEFT, never read
            return p.startswith("data/") and p.endswith(".json") and p[5:-5] in UMZ_LEFT_PARTS
        if sum(zi.file_size for p, (zi, _s) in files.items() if p.startswith("data/") and not left(p)) > UMZ_JSON_TOTAL:
            raise UmzBad(N_("The file contains a part that is too large: {0}"), "data/")
        rows_of = man.get("tables") if isinstance(man.get("tables"), dict) else {}
        for p, (zi, sha) in files.items():
            if left(p):
                n = rows_of.get(p[5:-5])
                if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
                    unread[p[5:-5]] = n
                    if full:
                        _sum_entry(zf, zi, sha)
                elif zi.file_size <= UMZ_JSON_MAX:
                    # 2.531.0 (#4317 F5): a file without the row counts (made by hand, an older writer): the part is read only to
                    # count it, never kept, so what stays on the old server is still named
                    rows = _json(_read_entry(zf, zi, UMZ_JSON_MAX, sha), p)
                    unread[p[5:-5]] = len(rows) if isinstance(rows, list) else 0
                else:
                    unread[p[5:-5]] = 0
                    if full:
                        _sum_entry(zf, zi, sha)
            elif p.startswith("data/") and p.endswith(".json") and "/" not in p[5:]:
                rows = _json(_read_entry(zf, zi, UMZ_JSON_MAX, sha), p)
                if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
                    raise UmzBad(N_("The file contains a broken part: {0}"), p)
                if len(rows) > UMZ_MAX_ROWS:
                    raise UmzBad(N_("The file contains a part that is too large: {0}"), p)
                data[p[5:-5]] = rows
            elif full:
                _read_entry(zf, zi, MAX_FILE_MB * 1024 * 1024 * 4, sha)
        man["_unread"] = unread  # 2.531.0 (#4317) F5: {part: rows of the manifest} for umz_left
        return zf, man, files, data
    except UmzBad:
        zf.close()
        raise
    except (zipfile.BadZipFile, OSError, EOFError, ValueError, NotImplementedError, RuntimeError):
        zf.close()
        raise UmzBad(N_("The file contains a broken part: {0}"), "ZIP") from None


# 2.73.0 B (#1473, part 4): the parts of an organisation export (admin/orgexport.py OX_AREAS) that move along, under the
# table names of the account export; everything else of the archive is named in the preview as not taken over
# 2.1093.0 (#5289): + the files of the core's tables with their part (core/objexport.py org: lists/tags.json, org/labels.json,
# tasks/tags.json, comments.json); UMZ_ORG_MAP_OWN holds the old tables' files
UMZ_ORG_MAP_OWN = {
    "lists.json": "lists", "lists/sections.json": "sections", "lists/members.json": "list_members", "lists/fields.json": "list_fields",
    "lists/status.json": "list_status", "lists/links.json": "list_links",
    "lists/milestones.json": "list_milestones", "lists/files.json": "list_files", "tasks.json": "tasks",
    "tasks/dependencies.json": "task_deps", "tasks/field_values.json": "task_field_values",
    "tasks/relations.json": "task_relations",  # 2.576.0 (#3371)
    "tasks/decisions.json": "task_decisions", "attachments.json": "attachments", "calendars.json": "event_calendars", "events.json": "events",
    "events/attendees.json": "event_attendees", "books.json": "address_books", "books/contacts.json": "contacts",
    "members.json": "members",
}
UMZ_ORG_MAP = {**UMZ_ORG_MAP_OWN, **oex_org_map()}
UMZ_ORG_SKIP = (  # archive prefix -> what the preview names as not taken over
    ("office/", N_("Office")), ("store/", N_("File store")), ("chat/", N_("Team chat")), ("wiki/", N_("Knowledge pages")),
    ("documents/", N_("Documents")), ("newsletter/", N_("Newsletter")), ("clients.json", N_("Clients")), ("hub/", N_("Absences and bookings")),
    ("lists/forms.json", N_("Forms")), ("lists/playbooks.json", N_("Playbooks")), ("lists/notes.json", N_("Project notes")),
    ("lists/notepads.json", N_("Notepads")), ("time_entries.json", N_("Time entries")),
    ("tasks/encrypted_notes.json", N_("Encrypted notes")), ("tasks/locked_notes.json", N_("Encrypted notes")),
    ("portal/", N_("Client reports")),  # 2.81.0 (#1866)
    ("sheets/", N_("Tables")), ("videos/", N_("Video sign-offs")),  # 2.137.0 (#2344): named too
    ("lists/sprints.json", N_("Sprints")), ("tasks/people.json", N_("People on tasks")),  # 2.273.0 A (#3030)
    ("lists/views.json", N_("Shared views")),  # 2.577.0 (#3356): in the archive, not taken over (they name columns and people of the old ids)
    ("lists/history.json", N_("History")), ("tasks/history.json", N_("History")),
    ("bookings/", N_("Booking page")),  # 2.362.0 (#3096): in the archive, not taken over (a booking page is one person's)
)


def umz_org_open(zf, names, man, mraw, full):
    """-> (manifest, files, data) of an opened organisation export, in the shape of an account export (2.137.0, #2344: the
    entries of admin/orgimport.py under data["oi"][entry])."""
    from .orgimport import oi_covers
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
        if p in UMZ_ORG_MAP or (p.endswith(".json") and oi_covers(p)):  # 2.137.0 (#2344): + the areas of admin/orgimport.py
            rows = _json(_read_entry(zf, zi, UMZ_JSON_MAX, f["sha256"]), p)
            if not isinstance(rows, list) or not all(isinstance(x, dict) for x in rows):
                raise UmzBad(N_("The file contains a broken part: {0}"), p)
            if len(rows) > UMZ_MAX_ROWS:  # review M2: the same limits as the account import
                raise UmzBad(N_("The file contains a part that is too large: {0}"), p)
            if p in UMZ_ORG_MAP:
                data[UMZ_ORG_MAP[p]] = rows
            else:
                data.setdefault("oi", {})[p] = rows
        elif full or p.endswith(".json"):
            raw = _read_entry(zf, zi, UMZ_JSON_MAX if p.endswith(".json") else MAX_FILE_MB * 1024 * 1024 * 4, f["sha256"])
            what = next((w for pre, w in UMZ_ORG_SKIP if p.startswith(pre)), None)
            if p.endswith(".json"):
                try:
                    x = json.loads(raw.decode("utf-8"))
                    # 2.273.0 A (#3030): a part without a name of its own keeps its technical name (rows only)
                    n = len(x) if what or isinstance(x, list) else 0
                except (ValueError, UnicodeDecodeError, RecursionError, TypeError):
                    n = 0
                what = what or p[:-5]
                if n:
                    skipped[what] = skipped.get(what, 0) + n
    data["pictures"] = [p for p in sorted(files) if p.startswith("files/pictures/")]  # 2.459.0 (#3849): orgimport.oi_pictures
    # 2.278.0 A (#3095): the members' roles of the file (admin / member) -> a suggestion in the preview
    roles = {_oid(m.get("id")): m.get("role") for m in data.get("members", []) if isinstance(m, dict)}
    for kind, table in (("attachments", "attachments"), ("list_files", "list_files")):
        for r in data.get(table, []):
            path = f"files/{kind}/{_oid(r.get('id')) or 0}-{_safe_part(r.get('name'))}"
            if path in files:
                r["file"] = path
    lists = {}
    for m in data.pop("list_members", []):
        lists.setdefault(_oid(m.get("user_id")), {})[str(_oid(m.get("list_id")))] = m.get("role")
    for r in data.get("lists", []):  # 2.456.0 (#3821): the owner is no row of list_members; the project is shared like with a member
        if _oid(r.get("owner_id")):
            lists.setdefault(_oid(r.get("owner_id")), {}).setdefault(str(_oid(r.get("id"))), "edit")
    data["people"] = [{"user_id": _oid(m.get("id")), "name": _txt(m.get("display_name"), 100) or _txt(m.get("username"), 100),
                       "email": "" if m.get("kind") == "agent" else _txt(m.get("email"), 200), "lists": lists.get(_oid(m.get("id")), {}),
                       **({"agent": True} if m.get("kind") == "agent" else {})} for m in data.pop("members", [])]
    org = man["org"]
    m2 = {"format": "kalmido-org-export", "kind": "org", "v": 1, "kalmido_version": _txt(man.get("kalmido_version"), 40),
          "created_at": _txt(man.get("created_at"), 40), "source": {"url": "", "hosted": False},
          "user": {"id": None, "name": _txt(org.get("name"), 100), "email": ""}, "export_id": hashlib.sha256(mraw).hexdigest()[:32],
          "client_encrypted": {}, "org_skipped": skipped}
    for p in data["people"]:
        p["role"] = umz_role(roles.get(p["user_id"]))
    return m2, files, data


def umz_role(v):
    """2.278.0 A (#3095): the only roles an imported person is invited with (anything else = member)."""
    return v if v in ("admin", "member") else "member"


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
    h = p.get("email_hash") if isinstance(p, dict) else None
    if isinstance(h, str) and re.fullmatch(r"[0-9a-f]{64}", h):
        return h
    return umz_email_hash(_email(p.get("email"))) if isinstance(p, dict) else ""


def umz_pkey(v):
    """A key of the run's choice: the hash, or (older clients) a plain address."""
    if isinstance(v, str) and (re.fullmatch(r"[0-9a-f]{64}", v) or re.fullmatch(r"id[1-9]\d{0,17}", v)):  # 2.278.0 B (#3094): id<old id>
        return v
    return umz_email_hash(_email(v))


def umz_disk_size(received, sealed):
    """The bytes on disk of an upload with `received` confirmed plaintext bytes (sealed: head + whole blocks with tag)."""
    return UMZ_HEAD + (received // UMZ_BLOCK) * (UMZ_BLOCK + 16) if sealed else received


def umz_targets(c, uid):
    """Where the import may go: the private space and every organisation the person administers."""
    out = [{"id": "private", "name": tr("Private|workspace")}]
    for oid in user_orgs(c, uid):
        if org_role(c, uid, oid) == "admin":
            with system_ctx(c):  # the names of the person's own organisations (structure)
                r = c.execute("SELECT name FROM orgs WHERE id=?", (oid,)).fetchone()
            if r:
                out.append({"id": int(oid), "name": r["name"]})
    return out


def umz_salt(man):
    """2.239.0 A (#2882): the key of the file's e-mail hashes (people_salt of newer account exports), else None (older form)."""
    v = man.get("people_salt") if isinstance(man, dict) else None
    return v if isinstance(v, str) and re.fullmatch(r"[0-9a-f]{32}", v) else None


def umz_seen(c, uid, salt=None):
    """Review M1: {email hash: account} of the accounts the person may see on this server (never others: the preview must
    not reveal accounts the person could not find in the app either)."""
    vis = visible_people(c, uid)
    out = {}
    for r in c.execute("SELECT id, display_name, username, email FROM users WHERE NOT disabled AND COALESCE(kind,'user')!='agent' "
                       "AND email IS NOT NULL AND email!='' AND id!=?", (uid,)):
        if vis is None or r["id"] in vis:
            out.setdefault(umz_email_hash(r["email"], salt), r)
    return out


def umz_find(c, uid, h, seen=None):
    """The account behind this hash that the person may see, else None."""
    if not h:
        return None
    return (umz_seen(c, uid) if seen is None else seen).get(h)


def umz_pid(p):
    """2.278.0 B (#3094): the key of a person of the file in the preview / run -- the address hash, else (no address in the
    file) "id<old id>"; such a person can only be matched by a user name the admin types."""
    o = _oid(p.get("user_id")) if isinstance(p, dict) else None
    return umz_phash(p) or (f"id{o}" if o else "")


def umz_find_login(c, uid, login):
    """2.278.0 B (#3094): the account with exactly this user name, only when the person may see it (like umz_find: never a
    search, and "not there" / "not visible" give the same None -- no way to list accounts)."""
    login = login.strip().lower() if isinstance(login, str) else ""
    if not login or not USERNAME_RE.fullmatch(login):
        return None
    r = c.execute("SELECT id, display_name, username, email FROM users WHERE NOT disabled AND COALESCE(kind,'user')!='agent' "
                  "AND id!=? AND username=?", (uid, login)).fetchone()
    vis = umz_visible(c, uid) if r else None
    return r if r and (vis is None or r["id"] in vis) else None


def umz_left(data, unread=None):
    """2.273.0 A (#3030): what of an account export stays on the old server -> [{"what": name, "count": n}]: every part of
    the file the import does not read (UMZ_LEFT names them, an unknown part keeps its technical name), the settings that
    do not move and the tasks in the trash. 2.454.0 (#3808): name = the key, translated for who reads it (umz_areas_tr).
    2.531.0 (#4317) F5: unread = {part: rows} of the parts umz_open did not read (man["_unread"])."""
    n = {k: len(v) for k, v in data.items() if isinstance(v, list)}
    n.update({k: v for k, v in (unread or {}).items() if isinstance(v, int)})
    out, known = {}, set(UMZ_READ)
    for what, parts in UMZ_LEFT:
        known.update(parts)
        k = n.get(parts[0]) or sum(n.get(p, 0) for p in parts[1:])
        if k:
            out[what] = out.get(what, 0) + k
    for t in sorted(set(n) - known):
        if n[t]:
            out[t] = n[t]
    mine = {_oid(L.get("id")) for L in data.get("lists", []) if isinstance(L, dict) and not L.get("e2e")}
    # 2.531.0 (#4317 F17): comments and files of a task in the trash stay behind with it (umz_write leaves them out), counted on
    # their own; its time entries come along without the task (list-level entries), so they are not counted here
    trash = {_oid(t.get("id")) for t in data.get("tasks", []) if isinstance(t, dict) and t.get("deleted_at")} - {None}
    on_trash = lambda part: sum(1 for r in data.get(part, []) if isinstance(r, dict) and _oid(r.get("task_id")) in trash)  # noqa: E731
    for what, k in ((N_("Other settings"), sum(1 for r in data.get("settings", []) if r.get("key") not in UMZ_SETTINGS_ALL)),
                    (N_("Tasks in the trash"), sum(1 for t in data.get("tasks", []) if t.get("deleted_at"))),
                    (N_("Comments on tasks in the trash"), on_trash("comments")),
                    (N_("Files of tasks in the trash"), on_trash("attachments")),
                    # 2.363.4 (#3127): what hangs on a project that is not mine (or encrypted); 2.765.0 (#3965): a folder's playbook comes along
                    (N_("Notepads"), sum(1 for r in data.get("list_notepads", []) if _oid(r.get("list_id")) not in mine)),
                    (N_("Playbooks"), sum(1 for r in data.get("playbooks", []) if isinstance(r, dict) and r.get("list_id") is not None
                                          and _oid(r.get("list_id")) not in mine)),
                    # 2.765.0 (#3965, fable F6): the budget's entries come along, their receipts (names only in the file) do not
                    (N_("Receipts in the household budget"), sum(len(b["files"]) for b in data.get("budgets", [])
                                                                 if isinstance(b, dict) and isinstance(b.get("files"), list)))):
        if k:
            out[what] = out.get(what, 0) + k
    return [{"what": w, "count": k} for w, k in out.items()]


def umz_areas_tr(rows):
    """2.454.0 (#3808): [{what: key, count}] of a kept state in the language of who asks; a state written before keeps its text."""
    return [{**x, "what": tr(x["what"])} for x in rows or []]


def umz_preview(c, uid, man, data, can_invite):
    from .orgimport import oi_counts
    tables = {k: len(v) for k, v in data.items()}
    lists = [{"name": _txt(L.get("name"), 200), "folder": _txt(L.get("folder"), 300), "inbox": bool(L.get("is_inbox")),
              "tasks": sum(1 for t in data.get("tasks", []) if t.get("list_id") == L.get("id") and not t.get("deleted_at"))}
             for L in data.get("lists", []) if not L.get("e2e")]  # 2.278.0 C (#3091): encrypted projects stay behind
    people = []
    mine = umz_email_hash((c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone() or [""])[0], umz_salt(man))
    seen = umz_seen(c, uid, umz_salt(man))
    for p in data.get("people", []):
        h = umz_phash(p)
        if not umz_pid(p) or p.get("agent") or (h and h == mine):  # 2.278.0 B (#3094): people without an address too
            continue
        hit = umz_find(c, uid, h, seen)
        # review M1: never an address in the preview; key = hash, the admin types the address for an invitation
        people.append({"key": umz_pid(p), "name": _txt(p.get("name"), 100), "lists": len(p.get("lists") or {}) if isinstance(p.get("lists"), dict) else 0,
                       "found": bool(hit), "found_name": (hit["display_name"] or hit["username"]) if hit else "",
                       "need_address": not _email(p.get("email")), "by_login": not hit})  # by_login: the admin may type a user name
    eid = man.get("export_id") if isinstance(man.get("export_id"), str) and UMZ_EID_RE.fullmatch(man.get("export_id")) else ""
    skey = umz_src(man, eid)
    earlier = umz_again(c, uid, skey, eid)  # 2.362.3 (#3098): the same source, not only the same file
    if man.get("kind") == "org":  # 2.278.0 A (#3095): the role of the file as a suggestion, the admin confirms it
        roles = {umz_pid(p): umz_role(p.get("role")) for p in data.get("people", [])}  # review M2: same key as the preview rows
        for q in people:
            q["role"] = roles.get(q["key"], "member")
    ce = man.get("client_encrypted") if isinstance(man.get("client_encrypted"), dict) else {}
    src = man.get("source") if isinstance(man.get("source"), dict) else {}
    u = man.get("user") or {}
    skipped = []
    org_kind = man.get("kind") == "org"
    for what, n in (man.get("org_skipped") or {}).items():  # an organisation export: the areas that do not move
        skipped.append({"what": what, "count": n})
    if not org_kind:  # 2.273.0 A (#3030): every part of the file the import does not read (was a fixed list)
        skipped += umz_left(data, man.get("_unread"))
        here = umz_sheets_here(c, uid, data)  # 2.765.0 (#3965): a month here already keeps the one here
        if here:
            skipped.append({"what": tr(N_("Timesheets of months you have here already")), "count": len(here)})
    office = man.get("personal_office") if isinstance(man.get("personal_office"), dict) else {}  # 2.362.2 (#3099)
    if not org_kind and isinstance(office.get("rows"), int) and office["rows"]:
        skipped.append({"what": tr(N_("Office")), "count": office["rows"]})
    return {
        "format": man.get("format"), "v": man.get("v"), "kalmido_version": _txt(man.get("kalmido_version"), 40),
        "created_at": _txt(man.get("created_at"), 40), "source": {"url": _txt(src.get("url"), 300), "hosted": bool(src.get("hosted"))},
        "user": {"name": _txt(u.get("name"), 100), "email": _email(u.get("email"))},  # the own address (plain in the file)
        "counts": {k: tables.get(k, 0) for k in ("lists", "sections", "tasks", "comments", "attachments", "list_files", "habits",
                                                  "filters", "templates", "time_entries", "event_calendars", "events", "address_books",
                                                  "contacts", "journal", "notes")},  # 2.362.0 (#3090): + project notes
        "lists": lists[:500], "people": people[:500], "can_invite": bool(can_invite),
        "people_salt": umz_salt(man) or "",  # 2.239.0 A (#2882): the client checks a typed address against the keyed hash
        "server_links": [_txt(x.get("name"), 100) or _txt(x.get("base_url"), 200) for x in data.get("server_links", [])][:20],
        "encrypted": {"attachments": len(ce.get("attachments") or []) if isinstance(ce.get("attachments"), list) else 0,
                      "locked_notes": ce.get("locked_notes") if isinstance(ce.get("locked_notes"), int) else 0,
                      **umz_enc_preview(c, uid, data, org_kind)},  # 2.278.0 C (#3091)
        "not_taken": skipped, "taken_areas": oi_counts(data) if org_kind else [], "again": bool(earlier), "earlier": earlier, "office_copy": bool(not org_kind and office), "export_id": eid, "src": skey, "kind": "org" if org_kind else "account",
        "targets": umz_targets(c, uid),  # 2.96.0 D (#1941): an organisation export may go into the private space too
    }


def umz_enc_preview(c, uid, data, org_kind):
    """2.278.0 C (#3091): locked_lists = projects encrypted in the browser (never taken over: no list keys move along);
    keys = the fate of my key bundle: "take" (no keys here yet), "keep" (own keys here: the file's ciphertexts stay unreadable),
    "none" (the file has none)."""
    keys, k0 = "none", {}
    if not org_kind and data.get("e2e_keys"):
        k0 = data["e2e_keys"][0] if isinstance(data["e2e_keys"], list) and data["e2e_keys"] and isinstance(data["e2e_keys"][0], dict) else {}
        keys = "take" if not e2e_has_keys(c, uid) or e2e_same_keys(c, uid, k0) else "keep"  # review M1: the same pair again = take
    oi = data.get("oi") if isinstance(data.get("oi"), dict) else {}
    parts = (oi.get(OIL_NODES), oi.get(OIL_LOCKS), oi.get(OIL_KEYS)) if org_kind else (data.get("private_files"), data.get("private_locks"), data.get("private_lock_keys"))
    pub = _pub(k0.get("pub")) if keys == "take" else None
    return {"locked_lists": sum(1 for L in data.get("lists", []) if L.get("e2e")), "keys": keys, **oil_preview(c, uid, *parts, pub)}


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
    if typ == "boolean":  # 2.1118.0 (#5952): the yes / no columns; older files hold 0 / 1, newer ones too (core/pg.py reads 0 / 1)
        if isinstance(v, bool):
            return int(v)
        if isinstance(v, int) or (isinstance(v, float) and v.is_integer()):  # review 2.1118 (F5): as cb_migrate, 0 = no, else yes
            return 0 if v == 0 else 1
        if isinstance(v, str) and v.strip().lower() in ("0", "1", "true", "false"):
            return 1 if v.strip().lower() in ("1", "true") else 0
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
    if typ == "timestamp with time zone":  # 2.760.0 (#5311): the core template's columns -- a valid ISO time stamp as text
        return v if _iso_ts(v) else _BAD
    if typ == "date":  # 2.1115.0 (#5951): a day column (DATE) - its day; '' / no day stays out (NULL)
        return v[:10] if isinstance(v, str) and _iso_ts(v) else _BAD
    return _BAD  # json, binary, other time stamps: not taken over


def _umz_json(v):
    """2.1111.0 (#5953): the value of a JSON column that was TEXT before (core/coltype.py CT_JSON, JSONB now) -> its JSON text,
    _BAD for what JSONB refuses (no JSON, a NUL, NaN, too long): the column keeps its default, the row comes (an error in the
    INSERT would drop the whole row). A file of before holds the JSON text, a file of now too (the driver reads JSONB as text)."""
    try:
        j = json.loads(v) if isinstance(v, str) else v
        s = json.dumps(j, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError, RecursionError):
        return _BAD
    return _BAD if len(s) > UMZ_TEXT_MAX or "\\u0000" in s else s


def _umz_snips(v, by):
    """2.273.0 A (#3030): the code snippets of a task from the file -> the stored JSON (the importer is their author)."""
    if isinstance(v, str) and v.startswith("["):  # stored as JSON text (a list's ciphertext "e2e1:..." stays behind)
        try:
            v = json.loads(v)
        except ValueError:
            return _BAD
    if not isinstance(v, list) or not by:
        return _BAD
    try:
        return snip_clean(v, by)
    except BadInput:
        return _BAD


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
    ("habits", "remind_at"): lambda v: v == "" or valid_hm(v),
    ("habits", "remind_times"): lambda v: v == "" or (len(v.split(",")) <= 6 and all(valid_hm(x) for x in v.split(","))),  # 2.140.0 C (#2135)
    ("habits", "days"): lambda v: bool(re.fullmatch(r"[1-7]{1,7}", v or "")),
    ("habits", "goal"): lambda v: isinstance(v, int) and 1 <= v <= 1000, ("habits", "per_week"): lambda v: isinstance(v, int) and 0 <= v <= 7,
    ("habit_logs", "day"): valid_date, ("events", "start"): _iso_ts, ("events", "end"): _iso_ts,
    ("time_entries", "start"): _iso_ts, ("time_entries", "end"): _iso_ts,
    ("sprints", "start"): valid_date, ("sprints", "end_day"): valid_date,  # 2.455.0 (#3469): the app reads them as days
}
UMZ_CHECK[("tasks", "remind_at")] = valid_plan_start  # 2.111.0 C (#2057): local "YYYY-MM-DDTHH:MM", not a UTC time stamp


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


UMZ_MONEY = {(t, col) for t, col, _n in MC_COLS}  # 2.765.0 (#5315)
UMZ_MONEY_TABLES = {t for t, _c in UMZ_MONEY}


def _money_fits(v):
    """2.765.0 (#5315): v fits a NUMERIC(14,2) column without a change -- the rule of the migration (core/moneycol.py MC_FITS:
    a plain number with at most 12 places before the point, no third place after it that is not 0). '' / None: as before (NULL
    or the column's default). Anything else (a text that is no plain number, '1,5', 'NaN', '1e3', true) does not fit either:
    the import would otherwise leave the column out and the default 0 would stand in for it silently (review M1 / N1)."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return True
    if isinstance(v, bool) or not isinstance(v, (str, int, float)):
        return False
    t = v.strip() if isinstance(v, str) else str(v)
    if isinstance(v, str) and not re.fullmatch(MC_FITS, t):
        return False
    try:
        d = Decimal(t)
    except (InvalidOperation, ValueError):
        return False
    return d.is_finite() and abs(d) < Decimal(10) ** 12 and d == d.quantize(Decimal("0.01"))


def umz_money_misfit(c, table, src):
    """2.765.0 (#5315): (column, the value as in the file) of the first money column of the row that NUMERIC(14,2) would have
    to round (1234.567) or cannot hold as it is ('1,5'), else None. The import does not round such a value silently: the row stays out and the report names
    the value, as the start's migration keeps a column with such a value TEXT and names it."""
    if table not in UMZ_MONEY_TABLES or not isinstance(src, dict):
        return None
    cols, _f = umz_cols(c, table)
    for t, col in sorted(UMZ_MONEY):
        if t == table and col in src and (cols.get(col) or ("",))[0] == "numeric" and not _money_fits(src[col]):
            return col, str(src[col])[:40]
    return None


def umz_row(c, table, src, fixed, ts):
    """The row to insert: the file's values of the columns this server has (coerced to their type), never ids or columns
    that point at rows, plus the fixed values. None when a required column has no value."""
    cols, fks = umz_cols(c, table)
    if umz_money_misfit(c, table, src):  # 2.765.0 (#5315): never rounded silently (the caller names the value)
        return None
    drop = UMZ_DROP.get(table, ())
    d = {}
    for k, v in src.items():
        if not isinstance(k, str) or k not in cols or k in fixed or k == "id" or k in OX_SECRET_COLS or k in fks or k in drop \
                or k.endswith("_id") or k.endswith("_by") or k in ("org_id", "reply_to"):
            continue
        if table == "tasks" and k == "snippets":  # 2.273.0 A (#3030): jsonb, checked like new snippets (a list's ciphertext stays behind)
            v = _umz_snips(v, fixed.get("created_by"))
        elif cols[k][0] == "jsonb" and any(x == k for x, _ in CT_JSON.get(table, ())):  # 2.1111.0 (#5953): as when they were TEXT
            v = _umz_json(v)
        else:
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
            if rr_problem(rule, True) or (d.get("due") and not rr_feasible(rule, d["due"])):
                d.pop("repeat")
            else:
                d["repeat"] = rule
    d.update({k: v for k, v in fixed.items() if k in cols})
    for k, (typ, nullable, dflt) in cols.items():
        if k in d or nullable or dflt or k == "id":
            continue
        if typ in ("text", "timestamp with time zone") and k.endswith("_at"):  # 2.760.0 (#5311): + TIMESTAMPTZ
            d[k] = ts
        else:
            return None
    return d


def umz_billed(run, src, d, ts):
    """2.278.0 B (#3094): a billed time entry stays billed -- on its invoice when that came along (d["billed_doc_id"] = the
    new document, mapped by the caller), else marked not billable with its billing date, so nobody bills it a second time."""
    if not (_oid(src.get("billed_doc_id")) or src.get("billed_at")):
        d.pop("billed_at", None)
        d["billed_doc_id"] = None
        return d
    d["billed_at"] = d.get("billed_at") or ts
    if not d.get("billed_doc_id"):
        d["billed_doc_id"] = None
        d["billable"] = 0
        run.warning(N_("Billed time entries without their invoice were imported as not billable"))
    return d


def umz_insert(c, table, d, rid=True, told=False):
    """The row in a savepoint -> new id (rid) / True, None when the database refuses it. 2.531.0 (#4317) F11: a refusal is
    counted per table for the run of this thread (umz_refused); told = the caller names this row in a warning of its own."""
    names = list(d)
    sql = f"INSERT INTO {table}({','.join(chr(34) + n + chr(34) for n in names)}) VALUES({','.join('?' * len(names))})"
    args = [d[n] for n in names]
    try:
        with c.savepoint():
            if rid:
                return insert_id(c, sql, args)
            c.execute(sql, args)
            return True
    except (IntegrityError, DataError):  # a duplicate or a value the column refuses: this row is skipped
        rej = getattr(_L, "rej", None)
        if rej is not None and not told:
            rej[table] = rej.get(table, 0) + 1
        return None


def umz_refused(run):
    """2.531.0 (#4317) F11: the rows the database refused in this run, one warning per area, and the counting ends."""
    rej, _L.rej = getattr(_L, "rej", None) or {}, None
    by = {}
    for table, n in rej.items():
        area = UMZ_REFUSED_AREA.get(table, table)
        by[area] = by.get(area, 0) + n
    for area, n in by.items():
        run.warning(N_("{1} entries in {0} were refused by this server and not imported"),
                    (area,) if area in UMZ_REFUSED_AREA.values() else area, n)


# 2.362.3 (#3098): what a second import of the same source into the same target skips, row by row: kind of _Run.put -> (table, column, kind of the
# parent or None). A row counts as there while it exists outside the trash, it hangs on a parent that counts as there (column =
# the parent), or without a parent it is still the person's (column = the owner); a list also still in the target or private
# (nothing is written into a list that went to somebody else or another organisation). Anything else is taken over anew. Parents first.
def umz_list_tags(c, run, data, inbox, uid):
    """2.947.0 (#5275): the project tags of the archive (lists/tags.json, list_tags rows of any version, a label's copy of
    2.609-2.924 too) become project tags of the core in their imported list; a name the list has already is that tag (60
    characters: agents/core.py LTAG_NAME_MAX, not imported here: tools/check_layers.py). The labels of an organisation export
    (org/labels.json) become labels of the target organisation (a name it has already is that label); into the private space
    they stay names only: umz_task_ltags makes them project tags of the tasks' projects."""
    for r in data.get("org_tags", []) if run.org else ():
        run.step()
        name = re.sub(r"[\x00-\x1f]", "", _txt(r.get("name"), 60)).strip().lstrip("#").strip()
        if not name:
            continue
        have = otg_find(c, "org", run.org, name)
        nid = have["id"] if have else otg_add(c, "org", run.org, name, clean_color(r.get("color") or ""), by=uid)
        run.put("org_tags", r.get("id"), nid)
        if not have:
            run.count("org_tags")
    for r in data.get("list_tags", []):
        run.step()
        lid = run.m("lists", r.get("list_id"))
        if not lid or lid == inbox or run.there("list_tags", r.get("id")):
            continue
        name = re.sub(r"[\x00-\x1f]", "", _txt(r.get("name"), 60)).strip().lstrip("#").strip()
        if not name:
            continue
        have = otg_find(c, "list", lid, name)
        try:
            srt = float(r.get("sort") or 0)
        except (TypeError, ValueError):
            srt = None
        nid = have["id"] if have else otg_add(c, "list", lid, name, clean_color(r.get("color") or ""), by=uid, sort=srt)
        run.put("list_tags", r.get("id"), nid)
        if not have:
            run.count("list_tags")


def umz_task_ltags(c, run, data, uid):
    """2.947.0 (#5275): the tags of the imported tasks (tasks/tags.json: a project tag, or since 2.947 a label of the organisation
    under its id of org/labels.json). A label the target has no organisation for becomes the project tag of that name."""
    labels = {_oid(r.get("id")): r for r in data.get("org_tags", []) if _oid(r.get("id"))}
    for r in data.get("task_list_tags", []):
        tid = run.m("tasks", r.get("task_id"))
        if not tid or run.old("tasks", tid):  # 2.531.0 (#4317) F16
            continue
        gid = run.m("list_tags", r.get("tag_id")) or run.m("org_tags", r.get("tag_id"))
        lab = labels.get(_oid(r.get("tag_id")))
        if not gid and lab:
            name = re.sub(r"[\x00-\x1f]", "", _txt(lab.get("name"), 60)).strip().lstrip("#").strip()
            lid = c.execute("SELECT list_id FROM tasks WHERE id=?", (tid,)).fetchone()
            if name and lid:
                have = otg_find(c, "list", lid[0], name)
                gid = have["id"] if have else otg_add(c, "list", lid[0], name, clean_color(lab.get("color") or ""), by=uid)
        if gid:
            otg_link(c, gid, tid, by=uid)


UMZ_SRC = {  # 2.947.0 (#5275, review F5): list_tags reads a project tag's list only (another scope's id may be 'o:3')
    "lists": ("lists", "owner_id", None), "sections": ("sections", "list_id", "lists"), "list_fields": ("list_fields", "list_id", "lists"),
    "list_tags": ("obj_tags", "CASE WHEN scope_kind='list' THEN CAST(scope_id AS BIGINT) END", "lists"), "list_status": ("list_status", "list_id", "lists"), "list_links": ("list_links", "list_id", "lists"),
    "list_milestones": ("list_milestones", "list_id", "lists"), "tasks": ("tasks", "list_id", "lists"), "notes": ("notes", "list_id", "lists"),
    "comments": ("obj_comments", "ref_id", "tasks"), "attachments": ("attachments", "task_id", "tasks"), "list_files": ("list_files", "list_id", "lists"),
    "time_entries": ("time_entries", "user_id", None), "habits": ("habits", "user_id", None), "filters": ("filters", "user_id", None),
    "templates": ("templates", "owner_id", None), "books": ("books", "owner_id", None), "ev_cals": ("ev_cals", "owner_id", None),
    "contacts": ("contacts", "book_id", "books"), "events": ("events", "cal_id", "ev_cals"), "event_attendees": ("event_attendees", "event_id", "events"),
    "sprints": ("sprints", "list_id", "lists"), "list_rules": ("list_rules", "list_id", "lists"),  # 2.455.0 (#3469)
    "portal_tickets": ("portal_tickets", "list_id", "lists"),
    "template_files": ("template_files", "template_id", "templates"),  # 2.464.0 (#3865)
}


def umz_src(man, eid):
    """2.362.3 (#3098): the key of what a file comes from: server + account of an account export, so a newer export of the same
    account counts as the same source; else (no address of the server, an organisation export: its ids say nothing across
    servers) the file itself."""
    url, oid = _txt((man.get("source") or {}).get("url"), 300).strip().rstrip("/").lower(), _oid((man.get("user") or {}).get("id"))
    if man.get("format") != UMZ_FORMAT or not url or not oid:
        return eid
    return hashlib.sha256(f"kalmido-source|{url}|{oid}".encode()).hexdigest()[:32]


def umz_earlier(c, uid, src, eid=""):
    """2.362.3 (#3098): the imports of this source that are not undone, oldest first (eid: also a file imported before there was
    a source key)."""
    a = [f'%"{k}": "{v}"%' for k, v in (("src", src), ("export_id", eid or src)) if v and UMZ_EID_RE.fullmatch(v)]
    if not a:
        return []
    w = " OR ".join("CAST(report AS text) ILIKE ?" for _ in a)
    return c.execute(f"SELECT id, created, created_at, report FROM imports WHERE user_id=? AND source=? AND undone_at IS NULL AND ({w}) ORDER BY id",
                     (uid, UMZ_SOURCE, *a)).fetchall()


def umz_undo_until(at):
    """2.585.0 (#4350): an account import can be undone for ACCOUNT_IMPORT_UNDO_DAYS (30) days, not the
    24 hours of the task imports (integrations/importers.py imp_undo_until reads the same constant)."""
    return at + timedelta(days=ACCOUNT_IMPORT_UNDO_DAYS)


def umz_again(c, uid, src, eid):
    """2.362.3 (#3098): the preview's facts about the last import of this source, else None."""
    rows = umz_earlier(c, uid, src, eid)
    if not rows:
        return None
    r, until = rows[-1], umz_undo_until(parse_iso(rows[-1]["created_at"]))
    return {"id": r["id"], "at": r["created_at"], "undo_until": iso(until) if until > now_utc() else ""}


def umz_have(c, run, uid, rows, mine=False):
    """2.362.3 (#3098): fills run.have {kind: {old id: new id}} from the earlier imports of this source, with what still counts
    as there (UMZ_SRC), in the person's access context. Only imports into the same target: a copy into another workspace is
    wanted. An earlier run with the areas of an organisation export: run.oi_done. mine = the file is my own export of this
    server: it holds the copies of the earlier imports too, under their ids here."""
    known = {}
    for r in rows:
        if json.loads(r["report"] or "{}").get("target") != run.org:
            continue
        cr = json.loads(r["created"] or "{}")
        run.oi_done = run.oi_done or bool(cr.get("oi_done"))
        for kind, m in (cr.get("src") or {}).items():
            if kind in UMZ_SRC and isinstance(m, dict):
                m = {_oid(k): v for k, v in m.items() if _oid(k) and _oid(v)}
                known.setdefault(kind, {}).update({**({v: v for v in m.values()} if mine else {}), **m})
    for kind, (table, col, parent) in UMZ_SRC.items():
        m, here = known.get(kind) or {}, {}
        ids, ups = sorted(set(m.values())), set(run.have.get(parent, {}).values()) if parent else {uid}
        for i in range(0, len(ids), 500):
            part = ids[i:i + 500]
            extra, live = ", org_id" if kind == "lists" else "", " AND deleted_at IS NULL" if "deleted_at" in umz_cols(c, table)[0] else ""
            for x in c.execute(f"SELECT id, {col} AS up{extra} FROM {table} WHERE id IN ({','.join('?' * len(part))}){live}", part).fetchall():
                if x["up"] in ups and (kind != "lists" or x["org_id"] in (None, run.org)):
                    here[x["id"]] = x
        run.have[kind] = {o: n for o, n in m.items() if n in here}
        if kind == "lists":
            run.list_org.update({n: x["org_id"] for n, x in here.items()})
        elif kind == "tasks":
            run.task_list.update({n: x["up"] for n, x in here.items()})
        elif kind == "list_fields":
            run.field_list.update({n: x["up"] for n, x in here.items()})
        elif kind == "sprints":  # 2.455.0 (#3469)
            run.sprint_list.update({n: x["up"] for n, x in here.items()})


UMZ_MENTION_RE = re.compile(r"<@(\d{1,18})>")  # as in collab/comments.py
UMZ_NO_SPACE = N_("A file was left out because your storage is full")  # 2.362.4 (#3100)


def umz_cmt_extra(r):
    """2.972.0 (#5272): the extras of a comment of the file (old columns portal / rule_name) as obj_comments.extra (JSON text);
    a key only when it has a value."""
    x = {}
    if r.get("portal") in (1, True, "1", "true"):
        x["portal"] = True
    if isinstance(r.get("rule_name"), str) and r["rule_name"].strip():
        x["rule_name"] = r["rule_name"].strip()[:200]
    return json.dumps(x, ensure_ascii=False)


def umz_mentions(text, names, who):
    """2.362.4 (#3100): <@old id> of a text from the file -> <@new id> of a person who came along, else plain @name: an old id
    would name whoever has that number on this server."""
    if not isinstance(text, str) or "<@" not in text:
        return text

    def sub(m):
        n = who(m.group(1))
        return f"<@{n}>" if n else "@" + (names.get(int(m.group(1))) or "?")
    return UMZ_MENTION_RE.sub(sub, text)


def umz_filter_rules(run, v, who):
    """2.362.4 (#3100): the rules of a saved filter (static/js filterMatch) with the ids of this server -> JSON text. An id that
    did not come along goes; None when a category loses all its ids: an empty category means "everything", the filter would
    show something else than it did."""
    try:
        r = json.loads(v) if isinstance(v, str) else v
    except (ValueError, RecursionError):
        return None
    if not isinstance(r, dict):
        return None
    out = dict(r)

    def person(x):
        n = who(x)
        return "me" if n and n == run.uid else n

    for key, fn in (("lists", lambda x: run.m("lists", x)),
                    ("secs", lambda x: x if x == "none" else run.m("sections", x)),
                    ("ms", lambda x: x if x == "none" else run.m("list_milestones", x)),
                    ("who", lambda x: x if x in ("me", "none") else person(x)),
                    ("sprints", lambda x: x if x in ("cur", "none") else None)):  # 2.390.0 B (#3355): never a sprint id
        old = r.get(key)
        if isinstance(old, list) and old:
            out[key] = list(dict.fromkeys(y for y in map(fn, old) if y is not None))
            if not out[key]:
                return None
    if isinstance(r.get("cf"), dict) and r["cf"]:  # {field id: rule}
        out["cf"] = {str(run.m("list_fields", k)): x for k, x in r["cf"].items() if run.m("list_fields", k)}
        if not out["cf"]:
            return None
    if isinstance(r.get("conds"), list):  # 2.521.0 (#4479): the condition rows {f, op, v} of the filter dialog
        conds = [umz_filter_cond(run, x, person) for x in r["conds"] if isinstance(x, dict)]
        if any(x is None for x in conds):
            return None
        out["conds"] = conds
    return json.dumps(out, ensure_ascii=False)


# 2.521.0 (#4479): the values of a condition that are ids of the old server (the other kinds: folder paths, dates, names ...)
UMZ_COND_IDS = {"list": ("lists", ()), "sec": ("sections", ("none",)), "ms": ("list_milestones", ("none",))}


def umz_filter_cond(run, x, person):
    """One condition of a saved filter with the ids of this server; None when it loses all its values (the filter would show
    something else). A custom field condition with its own field id follows that field (its option ids are the field's);
    one by name + type stays as it is."""
    x = dict(x)
    f, v = x.get("f"), x.get("v")
    if f == "cf" and x.get("fid"):  # a falsy fid (0, "") is a field by name + type, as the client reads it (Fable review)
        nf = run.m("list_fields", x["fid"])
        if not nf:
            return None
        x["fid"] = nf
        return x
    if not isinstance(v, list) or not v:
        return x
    if f in UMZ_COND_IDS:
        table, keep = UMZ_COND_IDS[f]
        fn = (lambda y: y if y in keep else run.m(table, y))
    elif f == "who":
        fn = (lambda y: y if y in ("me", "none") else person(y))
    elif f == "sprint":
        fn = (lambda y: y if y in ("cur", "none") else None)
    else:
        return x
    x["v"] = list(dict.fromkeys(y for y in map(fn, v) if y is not None))
    return x if x["v"] else None


def umz_template_data(kind, v):
    """2.362.4 (#3100): the data of a template from the file as a new template stores it: tpl_clean keeps only the known parts
    (names, offsets, node keys), so no id of the old server stays. None = not a template."""
    try:
        return json.dumps(tpl_clean(kind, json.loads(v) if isinstance(v, str) else v), ensure_ascii=False)
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError):
        return None


class _Run:
    def __init__(self, uid, iid, eid, org, total):
        self.uid, self.iid, self.eid, self.org = uid, iid, eid, org
        self.maps = {}
        self.have, self.src, self.oi_done = {}, {}, False  # 2.362.3 (#3098): umz_have; old -> new of this run, for the next one
        self.created = {"lists": [], "sections": [], "tasks": [], "habits": [], "filters": [], "templates": [], "ev_cals": [],
                        "books": [], "time_entries": [], "journal": [], "settings": {}, "files": [], "template_files": []}
        self.stats = {}
        self.warn = {}
        self.must = set()  # 2.531.0 (#4317) F4: the keys of warn the result always names, first and outside UMZ_WARN_MAX
        self.after = []  # 2.574.0 (#4556): steps once the run is committed (fn(c)), e.g. telling the connection requests
        self._old = {}  # 2.531.0 (#4317) F16: kind -> the new ids of the rows of an earlier import (umz_have)
        self.done, self.total, self.tick = 0, max(1, total), 0
        self.task_list, self.field_list, self.list_org = {}, {}, {}
        self.sprint_list = {}  # 2.455.0 (#3469): new sprint id -> its list
        self.field_type, self.names = {}, {}  # 2.362.4 (#3100)
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
            if kind in UMZ_SRC:
                self.src.setdefault(kind, {})[str(o)] = new

    def there(self, kind, old):
        """2.362.3 (#3098): the row of an earlier import of this source when it still counts as there: nothing to create, what
        hangs on it finds it (put), else None."""
        new = self.have.get(kind, {}).get(_oid(old))
        if new:
            self.put(kind, old, new)
            self.count("skipped")
        return new

    def count(self, k, n=1):
        self.stats[k] = self.stats.get(k, 0) + n

    def warning(self, text, *a, must=False):
        k = (text, *a)
        self.warn[k] = self.warn.get(k, 0) + 1
        if must:
            self.must.add(k)

    def warnings(self):
        """2.531.0 (#4317) F4: the warnings of the result: the ones that must be named first, then at most UMZ_WARN_MAX others."""
        first = [k for k in self.warn if k in self.must]
        rest = [k for k in self.warn if k not in self.must][:UMZ_WARN_MAX]
        return [{"text": list(k), "count": self.warn[k]} for k in first + rest]

    def old(self, kind, new):
        """2.531.0 (#4317) F16: new is a row of an earlier import of this source (run.there found it): what hangs on it came
        along with that import, a second run must not add it again."""
        if kind not in self._old:
            self._old[kind] = set(self.have.get(kind, {}).values())
        return bool(new) and new in self._old[kind]

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


def umz_part(run, lid, table, key):
    """2.455.0 (#3469): a row on a list of an earlier import: the undo of this run takes it away (on a list of this run it stays
    with its list, which goes into the trash and can come back)."""
    if lid not in run.created["lists"]:
        run.created.setdefault("parts", []).append([table, key])


def umz_list_parts(c, run, uid, inbox, data, who):
    """2.455.0 (#3469): after the tasks: the close-outs of the sprints, the further placements of tasks, the rules and the customer
    reports of my lists. Every id through the maps of this run; what points at something that did not come along goes, nothing
    here keeps an id of the old server."""
    from .oi_team import rule_fields, rule_ids, sprint_finish, ticket_seal
    ts = iso(now_utc())
    sprint_finish(c, run, [r for r in data.get("sprints", []) if _oid(r.get("id")) not in run.have.get("sprints", {})])
    for r in data.get("task_links", []):
        run.step()
        tid, lid = run.m("tasks", r.get("task_id")), run.m("lists", r.get("list_id"))
        if not tid or not lid or lid == inbox or lid == run.task_list.get(tid) or run.old("tasks", tid):  # 2.531.0 (#4317) F16
            continue
        both = c.execute("SELECT org_id, life FROM lists WHERE id IN (?,?)", (lid, run.task_list.get(tid))).fetchall()  # the app's rule (ml_add)
        if len(both) < 2 or both[0][0] != both[1][0] or any(x[1] in ("health", "budget") for x in both):
            continue
        sid = run.m("sections", r.get("section_id"))
        if sid and not c.execute("SELECT 1 FROM sections WHERE id=? AND list_id=?", (sid, lid)).fetchone():
            sid = None
        d = umz_row(c, "task_links", r, {"task_id": tid, "list_id": lid, "section_id": sid, "org_id": run.list_org.get(lid), "added_by": uid}, ts)
        if d and umz_insert(c, "task_links", d, rid=False):
            umz_part(run, lid, "task_links", [tid, lid])
            run.count("task_links")
    types = rule_fields(data)
    for r in data.get("list_rules", []):
        run.step()
        lid = run.m("lists", r.get("list_id"))
        if not lid or lid == inbox or r.get("deleted_at") or run.there("list_rules", r.get("id")):
            continue
        d = umz_row(c, "list_rules", r, {"list_id": lid, "org_id": run.list_org.get(lid), "created_by": uid, "name": "", "trig": "", "act": "",
                                          "updated_at": ts}, ts)
        d = rule_ids(c, run, who, types, r, d) if d else None
        nid = umz_insert(c, "list_rules", d) if d else None
        if nid:
            run.put("list_rules", r.get("id"), nid)
            umz_part(run, lid, "list_rules", nid)
            run.count("list_rules")
    for r in data.get("portal_tickets", []):
        run.step()
        tid, lid = run.m("tasks", r.get("task_id")), run.m("lists", r.get("list_id"))
        if not tid or not lid or lid == inbox or run.task_list.get(tid) != lid or run.there("portal_tickets", r.get("id")):
            continue
        d = umz_row(c, "portal_tickets", r, {"task_id": tid, "list_id": lid, "token": "", "token_hash": ""}, ts)
        d = ticket_seal(c, run, uid, r, d) if d else None
        nid = umz_insert(c, "portal_tickets", d) if d else None
        if nid:
            run.put("portal_tickets", r.get("id"), nid)
            umz_part(run, lid, "portal_tickets", nid)
            run.count("portal_tickets")


def umz_formulas(c, run, data):
    """2.362.4 (#3100): a formula names the fields of its list by id: rewritten for the new ids through the field names, as a
    template does (fx_tpl_fix: a formula that does not fit stays empty)."""
    rows, lists = data.get("list_fields", []), set()
    for r in rows:
        nid = run.m("list_fields", r.get("id"))
        if not nid or r.get("type") != "formula":
            continue
        try:
            o = json.loads(r.get("options") or "{}")
            o["formula"] = fx_display(o.get("expr"), [{"id": _oid(x.get("id")), "name": _txt(x.get("name"))} for x in rows if x.get("list_id") == r.get("list_id")])
        except (ValueError, TypeError, AttributeError, RecursionError):
            o = {"expr": "", "formula": ""}
        c.execute("UPDATE list_fields SET options=? WHERE id=?", (json.dumps(o, ensure_ascii=False), nid))
        lists.add(run.field_list[nid])
    for lid in lists:
        try:
            with c.savepoint():
                fx_tpl_fix(c, lid)
        except (ValueError, TypeError, AttributeError, RecursionError):  # another field's options from the file are no JSON object
            run.warning(N_("A formula could not be imported"))


def umz_files(c, run, uid, me_old, zf, files, data):
    """Attachments and project files of a run."""
    ts = iso(now_utc())
    # files: attachments + project files, sealed like an upload (orgcrypt) and counted against the quota
    for table, kind in (("attachments", "tasks"), ("list_files", "lists")):
        for r in data.get(table, []):
            run.step()
            parent = run.m(kind, r.get("task_id" if kind == "tasks" else "list_id"))
            if not parent or run.there(table, r.get("id")):
                continue
            enc = _coerce(r.get("enc"), "bigint") if table == "attachments" else 0
            if enc and _oid(r.get("enc_by")) != me_old:
                run.warning(N_("Encrypted file of another person not imported: {0}"), _txt(r.get("name"), 80))
                continue
            if run.stopped:  # 2.362.4 (#3100): the storage is full, the rows without a file still come
                run.warning(UMZ_NO_SPACE)
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
                run.warning(UMZ_NO_SPACE)
                continue
            name = safe_name(_txt(r.get("name"), 150))
            if enc and raw[:5] != b"KENC\x01":  # 2.148.1 C (#2492): only a real browser-encrypted file (collab/e2e.py) skips the checks
                enc = 0
            mime, info = "application/octet-stream", None
            if not enc:  # 2.61.0 (#1818 #1819): a taken-over file is new content for this server: virus scan + photo metadata
                try:
                    raw, mime, info = up_check(c, name, raw, _txt(r.get("mime"), 120) or "application/octet-stream", uid,
                                               run.list_org.get(run.task_list.get(parent) if kind == "tasks" else parent), "att")
                except UploadRefused:
                    run.warning(N_("A file could not be imported: {0}"), name)
                    continue
            sub = os.path.join(str(parent)) if kind == "tasks" else os.path.join(LIST_FILES_SUB, str(parent))
            os.makedirs(os.path.join(ATT_DIR, sub), exist_ok=True)
            rel = os.path.join(sub, f"{uuid.uuid4().hex[:12]}-{name}")
            full = os.path.join(ATT_DIR, rel)
            run.written.append(full)
            lorg = run.list_org.get(run.task_list.get(parent) if kind == "tasks" else parent)
            # 2.42.0 (#828), 2.64.0 (#1864): sealed with the key of the list's space (organisation, else my account: I own the
            # taken-over lists); bytes from outside
            oc_write_file(c, lorg or oc_user_space(uid), full, raw, fresh=True)
            fixed = {"name": name, "size": len(raw), "path": rel, "user_id": uid, "created_at": _txt(r.get("created_at"), 40) or ts,
                     "mime": mime[:120]}  # 2.148.1 C (#2492): the type found in the content, not the one in the file
            if kind == "tasks":
                fixed.update({"task_id": parent, "comment_id": run.m("comments", r.get("comment_id")), "enc": 1 if enc else 0,
                              "enc_by": uid if enc else None,  # 2.278.0 C (#3091): the AAD of the old task + person
                              "legacy_aad": umz_legacy_aad("kalmido-file:v1", r.get("legacy_aad"), r.get("task_id"), me_old) if enc else None})
            else:
                fixed["list_id"] = parent
            d = umz_row(c, table, r, fixed, ts)
            nid = umz_insert(c, table, d) if d else None
            if not nid:
                run.warning(N_("A file could not be imported: {0}"), name)
                continue
            run.put(table, r.get("id"), nid)  # 2.137.0 B (#2344): the links of the file store point at them (oi_store.py)
            up_after_store(c, "att" if kind == "tasks" else "list", nid, lorg or None, info)  # 2.148.1 C (#2492): unchecked = scanned later
            if kind == "tasks":
                run.created["files"].append(rel)
            run.count(table)
    umz_template_files(c, run, uid, zf, files, data)


def umz_template_files(c, run, uid, zf, files, data):
    """2.464.0 (#3865): the file copies of my templates, checked like an attachment, sealed for my account (lists/tplextra.py) and
    counted against the quota. The node key comes along as it is: templates.data keeps its keys (tx_keys)."""
    ts = iso(now_utc())
    keys = {}  # template -> its node keys
    for r in data.get("template_files", []):
        run.step()
        tpl, node = run.m("templates", r.get("template_id")), _txt(r.get("node_key"), 80)
        if not tpl or not node or run.there("template_files", r.get("id")):
            continue
        if tpl not in keys:
            keys[tpl] = tx_keys(json.loads(c.execute("SELECT data FROM templates WHERE id=?", (tpl,)).fetchone()[0] or "{}"))
        if node not in keys[tpl]:  # review: a task the template does not have: the file would never be used, only count
            run.warning(N_("A file could not be imported: {0}"), _txt(r.get("name"), 80))
            continue
        if run.stopped:
            run.warning(UMZ_NO_SPACE)
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
            run.warning(UMZ_NO_SPACE)
            continue
        name = safe_name(_txt(r.get("name"), 150))
        try:
            raw, mime, info = up_check(c, name, raw, _txt(r.get("mime"), 120) or "application/octet-stream", uid, None, "att")
        except UploadRefused:
            run.warning(N_("A file could not be imported: {0}"), name)
            continue
        rel = os.path.join("tplfiles", str(tpl), f"{uuid.uuid4().hex[:12]}-{name}")
        full = os.path.join(ATT_DIR, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        run.written.append(full)
        oc_write_file(c, oc_user_space(uid), full, raw, fresh=True)
        d = umz_row(c, "template_files", r, {"template_id": tpl, "user_id": uid, "node_key": node, "name": name, "mime": mime[:120], "size": len(raw),
                                             "path": rel, "scan": info.get("scan") or "clean", "created_at": _txt(r.get("created_at"), 40) or ts}, ts)
        nid = umz_insert(c, "template_files", d) if d else None
        if not nid:
            run.written.remove(full)  # review: no row, no file (the commit keeps what is in the list)
            os.remove(full)
            run.warning(N_("A file could not be imported: {0}"), name)
            continue
        run.put("template_files", r.get("id"), nid)
        run.created["template_files"].append(nid)
        run.count("template_files")


def umz_undo_templates(c, uid, cr, plan):
    """2.464.0 (#3865): the files that go with the undo: of the run's templates (the rows go with the template) and the ones it put
    on a template of an earlier run. Before the templates go -> the paths to unlink after the commit.
    2.506.0 (#4299): only of what the plan lets go (a template changed since keeps its files, also the ones added since)."""
    tpl = [x for x in (int(y) for y in cr.get("templates") or []) if plan.goes("templates", x)]
    ids = [x for x in (int(y) for y in cr.get("template_files") or []) if plan.goes("template_files", x)]
    paths = []
    for i in range(0, max(len(tpl), len(ids)), 500):
        t, f = tpl[i:i + 500] or [0], ids[i:i + 500] or [0]
        q = f"WHERE user_id=? AND (template_id IN ({','.join('?' * len(t))}) OR id IN ({','.join('?' * len(f))}))"
        paths += [x[0] for x in c.execute(f"SELECT path FROM template_files {q}", [uid, *t, *f]).fetchall()]
        c.execute(f"DELETE FROM template_files {q}", [uid, *t, *f])
    return paths


UMZ_JOURNAL_SEP = "\n\n---\n"


def umz_journal_add(c, run, uid, r, here):
    """2.531.0 (#4317) F7: the file's entry of a journal day that has an entry here already: below the text of here, after a
    line and the date of the file's entry, counted and named in the result. The same text found there already (a second
    import) is skipped. The undo cuts it off again while the day was not written on since (created["journal_add"])."""
    src = _txt(r.get("text"), JOURNAL_MAX).strip()
    if not src:
        return
    cur = jr_open(c, uid, here)
    old = cur.get("text") or ""
    if src in old:
        run.count("skipped")
        return
    at = parse_iso(r["updated_at"]) if _iso_ts(r.get("updated_at")) else None
    when = short_day(at.date() if at else datetime.strptime(here["day"], "%Y-%m-%d").date(), lg=getattr(_L, "lg", None), year=True)
    text = f"{old}{UMZ_JOURNAL_SEP}{tr(N_('From the import (entry of {0})'), when)}\n{src}"
    if len(text) > JOURNAL_MAX:  # the journal keeps at most JOURNAL_MAX characters a day (journal_set): never cut silently
        text = text[:JOURNAL_MAX]
        run.warning(N_("A journal day was too long to add the entry of the file in full: {0}"), here["day"])
    st, sm, se = jr_seal(c, uid, text, cur.get("mood"))
    ts = iso_ms(now_utc())
    if c.execute("UPDATE journal SET text=?, mood=?, mood_enc=?, updated_at=? WHERE user_id=? AND day=? AND updated_at=?",
                 (st, sm, se, ts, uid, here["day"], here["updated_at"])).rowcount:
        run.created.setdefault("journal_add", []).append([here["day"], len(old), here["updated_at"], ts])
        run.count("journal_added")
        run.warning(N_("Journal: the entry of the file was added below a day that already had an entry here"))


def umz_task_roles(c, run, t, who):
    """2.531.0 (#4317) F6: approver, reviewer, who waits and the delegated agent of a task from the file like its assignee:
    the person who came along (an agent only as an agent), else empty with a warning naming the role. A group of the old
    server has no match here: always empty with a warning."""
    out = {}
    for col, role in UMZ_TASK_ROLES:
        if not _oid(t.get(col)):
            continue
        new = None if col == "assignee_group_id" else who(t.get(col))
        if new and col == "delegate_agent_id" and not c.execute(
                "SELECT 1 FROM users WHERE id=? AND COALESCE(kind,'user')='agent'", (new,)).fetchone():
            new = None
        out[col] = new
        if not new:
            run.warning(UMZ_ROLE_LOST, (role,))
    return out


def umz_write(c, run, uid, man, zf, files, data, people):
    """Creates everything in the open transaction (the caller commits). people: {old user id: new user id} for authors
    and assignees (only people ticked for sharing). 2.362.4 (#3100): the files come last: a full storage stops only them."""
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
        if L.get("e2e"):  # 2.278.0 C (#3091): its list keys never move along -- the texts would stay ciphertext for good
            run.warning(N_("An encrypted project was not imported: switch its encryption off before the export or export its content."))
            continue
        if run.there("lists", L.get("id")):  # 2.362.3 (#3098)
            continue
        sort += 1
        try:
            folder = clean_folder(_txt(L.get("folder"), 1000), strict=False)
        except Exception:  # noqa: BLE001 -- a broken folder path: no folder
            folder = ""
        lorg = org
        if org and man.get("kind") != "org" and _txt(L.get("life"), 20):  # Home & life lists (health, contracts ...) stay private
            lorg = None
            run.warning(N_("Personal project kept in your private workspace: {0}"), _txt(L.get("name"), 80))
        hst = L.get("header_style")  # 2.459.0 (#3849): "image" only comes back with its picture (oi_pictures)
        d = umz_row(c, "lists", L, {"owner_id": uid, "org_id": lorg, "is_inbox": 0, "sort": sort, "folder": folder,
                                     "name": _txt(L.get("name"), LIST_NAME_MAX).strip() or tr("Import"),
                                     "header_style": hst if hst in HEAD_STYLES and hst != "image" else ""}, ts)
        lid = umz_insert(c, "lists", d, told=True) if d else None
        if not lid:
            run.warning(N_("A project could not be imported: {0}"), _txt(L.get("name"), 80))
            continue
        list_created(c, uid, lid, agents=False)  # 2.25.0 (#931); agents only when the person shares later
        run.list_org[lid] = lorg
        run.put("lists", L.get("id"), lid)
        run.created["lists"].append(lid)
        run.count("lists")
    # what hangs on a list
    umz_list_tags(c, run, data, inbox, uid)  # 2.947.0 (#5275): the project tags into the core
    for table, kind, fixed in (("sections", "sections", {}), ("list_fields", "list_fields", {}),
                               ("list_status", "list_status", {"user_id": uid}), ("list_links", "list_links", {"created_by": uid}),
                               ("list_milestones", "list_milestones", {"created_by": uid}), ("sprints", "sprints", {"created_by": uid, "review": None, "state": "planned"})):  # 2.455.0 (#3469): both from sprint_finish, a stop before it keeps no old id
        for r in data.get(table, []):
            run.step()
            lid = run.m("lists", r.get("list_id"))
            if not lid or lid == inbox or run.there(kind, r.get("id")):
                continue
            d = umz_row(c, table, r, {"list_id": lid, **fixed}, ts)
            nid = umz_insert(c, table, d) if d else None
            if nid:
                run.put(kind, r.get("id"), nid)
                if kind == "list_fields":
                    run.field_list[nid] = lid
                    run.field_type[nid] = r.get("type")  # 2.362.4 (#3100)
                elif kind == "sprints":  # 2.455.0 (#3469)
                    run.sprint_list[nid] = lid
                    umz_part(run, lid, "sprints", nid)
            if nid and table == "sections":
                run.created["sections"].append(nid)
            if nid:
                run.count(table)
    umz_formulas(c, run, data)
    # tasks (the trash stays behind), then their parents
    rows = []
    for t in data.get("tasks", []):
        run.step()
        lid = run.m("lists", t.get("list_id"))
        if not lid or t.get("deleted_at"):
            if t.get("deleted_at"):  # 2.278.0 B (#3094): left behind on purpose -- what hangs on it goes without a warning (oi_write)
                run.put("tasks_left", t.get("id"), 1)
            continue
        if run.there("tasks", t.get("id")):  # 2.362.3 (#3098)
            continue
        sid = run.m("sections", t.get("section_id"))
        status = _coerce(t.get("status"), "bigint")
        status = status if status in (0, 2, -1) else 0
        aid = who(t.get("assignee_id"))
        if t.get("assignee_id") and not aid:
            run.warning(N_("Assignment not imported (the person is not on this server or was not selected)"))
        spr = run.m("sprints", t.get("sprint_id"))  # 2.455.0 (#3469): of the same list, else the backlog
        spr = spr if run.sprint_list.get(spr) == lid else None
        roles = umz_task_roles(c, run, t, who)  # 2.531.0 (#4317) F6
        d = umz_row(c, "tasks", t, {**roles,
            **({} if spr or man.get("kind") == "org" else {"sprint_at": None}), "sprint_id": spr,  # an organisation export: oi_write
            "list_id": lid, "section_id": sid, "title": _txt(t.get("title"), TITLE_MAX) or "…",
            "content": _txt(t.get("content"), CONTENT_MAX), "status": status, "milestone_id": run.m("list_milestones", t.get("milestone_id")),
            "created_by": uid, "completed_by": uid if status else None, "assignee_id": aid, "assigned_by": uid if aid else None,
            "tt_id": f"kalmido:{eid[:16]}:{_oid(t.get('id')) or 0}", "parent_id": None, "updated_at": ts,
            **_umz_delivery(t)}, ts)
        tid = umz_insert(c, "tasks", d, told=True) if d else None
        if not tid:
            run.warning(N_("A task could not be imported: {0}"), _txt(t.get("title"), 80))
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
            run.warning(N_("Subtask in another project or in a cycle, imported as a main task"), _txt(t.get("title"), 80))
            continue
        c.execute("UPDATE tasks SET parent_id=? WHERE id=?", (p, tid))
        run.count("subtasks")
    # what hangs on a task
    for r in data.get("task_deps", []):
        a, b = run.m("tasks", r.get("task_id")), run.m("tasks", r.get("blocker_id"))
        if run.old("tasks", a) and run.old("tasks", b):  # 2.531.0 (#4317) F16: came along with the earlier import
            continue
        if a and b and a != b and umz_insert(c, "task_deps", {"task_id": a, "blocker_id": b, "created_by": uid, "created_at": ts}, rid=False):
            run.count("task_deps")
    for r in data.get("task_relations", []):  # 2.576.0 (#3371): both tasks came along (else the relation stays behind)
        a, b = run.m("tasks", r.get("task_id")), run.m("tasks", r.get("other_id"))
        kind = r.get("kind") if r.get("kind") in ("relates", "duplicate") else None
        if not (a and b and a != b and kind) or (run.old("tasks", a) and run.old("tasks", b)):
            continue
        a, b = (min(a, b), max(a, b)) if kind == "relates" else (a, b)
        if umz_insert(c, "task_relations", {"task_id": a, "other_id": b, "kind": kind, "created_by": uid, "created_at": ts}, rid=False):
            run.count("task_relations")
    for r in data.get("task_field_values", []):
        tid, fid = run.m("tasks", r.get("task_id")), run.m("list_fields", r.get("field_id"))
        if tid and fid and run.field_list.get(fid) == run.task_list.get(tid) and not run.old("tasks", tid):  # 2.531.0 (#4317) F16
            val = _coerce(r.get("value"), "text") or ""
            if run.field_type.get(fid) in ("person", "task"):  # 2.362.4 (#3100): the value is an id of the old server
                val = who(val) if run.field_type[fid] == "person" else run.m("tasks", val.strip().lstrip("#"))
                if not val:
                    continue
            umz_insert(c, "task_field_values", {"task_id": tid, "field_id": fid, "value": str(val)}, rid=False)
    for r in data.get("task_tags", []):
        tid = run.m("tasks", r.get("task_id"))
        tag = _txt(r.get("tag"), 100).strip()
        if tid and tag and _oid(r.get("user_id")) == me_old and not run.old("tasks", tid):  # 2.531.0 (#4317) F16
            otg_user_add(c, tid, uid, tag, by=uid)  # 2.955.0 (#5276): the core's personal tags (the file keeps task_tags' columns)
    umz_task_ltags(c, run, data, uid)
    for r in data.get("task_note_locks", []):  # browser-encrypted with my note password: only my own
        tid = run.m("tasks", r.get("task_id"))
        if tid and _oid(r.get("user_id")) == me_old and not run.old("tasks", tid):  # 2.531.0 (#4317) F16
            d = umz_row(c, "task_note_locks", r, {"task_id": tid, "user_id": uid, "legacy_aad": umz_legacy_aad(  # 2.278.0 C (#3091)
                "kalmido-locknote:v1", r.get("legacy_aad"), r.get("task_id"), me_old)}, ts)
            if d:
                umz_insert(c, "task_note_locks", d, rid=False)
    for r in data.get("task_enc_notes", []):  # 2.362.0 (#3090): browser-encrypted with my content key: only my own
        tid = run.m("tasks", r.get("task_id"))
        if tid and _oid(r.get("user_id")) == me_old and not run.old("tasks", tid):  # 2.531.0 (#4317) F16
            d = umz_row(c, "task_enc_notes", r, {"task_id": tid, "user_id": uid, "legacy_aad": umz_legacy_aad(
                "kalmido-note:v1", r.get("legacy_aad"), r.get("task_id"), me_old)}, ts)
            if d and umz_insert(c, "task_enc_notes", d, rid=False):
                run.count("task_enc_notes")
    for r in data.get("notes", []):  # 2.362.0 (#3090): the project notes of my lists (the trash stays behind)
        run.step()
        lid = run.m("lists", r.get("list_id"))
        if not lid or lid == inbox or r.get("deleted_at") or run.there("notes", r.get("id")):
            continue
        d = umz_row(c, "notes", r, {"list_id": lid, "created_by": uid, "updated_by": uid}, ts)
        nid = umz_insert(c, "notes", d) if d else None
        if nid:
            run.put("notes", r.get("id"), nid)
            run.count("notes")
    umz_list_parts(c, run, uid, inbox, data, who)  # 2.455.0 (#3469)
    keys = [r for r in data.get("e2e_keys", []) if _oid(r.get("user_id")) == me_old] if run.kind != "org" else []
    if keys:  # 2.278.0 C (#3091): my key bundle -- taken while I have none here, never replacing my own keys
        k = e2e_import_keys(c, uid, keys[0], me_old)
        if k == "kept":
            run.warning(N_("Encrypted content from the export stays unreadable because you already have your own encryption keys here."))
        elif k == "taken":
            run.count("e2e_keys")
            run.warning(N_("Encryption keys imported: open locked notes and encrypted files with your passphrase from before."))
        else:
            run.warning(N_("The encryption keys in the export are broken: encrypted content stays unreadable."))
    names = run.names = {_oid(p.get("user_id")): _txt(p.get("name"), 100) for p in data.get("people", [])}
    for r in sorted(data.get("comments", []), key=lambda x: _oid(x.get("id")) or 0):
        run.step()
        tid = run.m("tasks", r.get("task_id"))
        if not tid:
            if run.m("tasks_left", r.get("task_id")):  # 2.278.0 B (#3094): on a task in the trash
                run.put("comments_left", r.get("id"), 1)
            continue
        if run.there("comments", r.get("id")):  # 2.362.3 (#3098)
            continue
        au = uid if _oid(r.get("user_id")) == me_old else None  # 2.148.1 C (#2492): others' comments by name only, never as an account
        ext = None if au else (names.get(_oid(r.get("user_id"))) or _txt(r.get("ext_name"), 100) or tr("Unknown"))
        # 2.972.0 (#5272): into the core's table (kind task); the file keeps the old columns (portal, rule_name -> extra)
        d = umz_row(c, "obj_comments", r, {"kind": "task", "ref_id": tid, "user_id": au, "ext_name": ext,
                                            "parent_id": run.m("comments", r.get("reply_to")), "extra": umz_cmt_extra(r)}, ts)
        if d and d.get("body"):  # 2.362.4 (#3100)
            d["body"] = umz_mentions(d["body"], names, who)
        nid = umz_insert(c, "obj_comments", d) if d else None
        if nid:
            run.put("comments", r.get("id"), nid)
            run.count("comments")
    # 2.392.0 C (#3370): the decisions of the tasks that came along, oldest first; what replaced what through the new ids
    for r in sorted(data.get("task_decisions", []), key=lambda x: _oid(x.get("id")) or 0):
        run.step()
        tid = run.m("tasks", r.get("task_id"))
        if not tid or run.there("task_decisions", r.get("id")):
            continue
        d = umz_row(c, "task_decisions", r, {"task_id": tid, "by_id": uid if _oid(r.get("by_id")) == me_old else None, "superseded_by": None}, ts)
        nid = umz_insert(c, "task_decisions", d) if d else None
        if nid:
            run.put("task_decisions", r.get("id"), nid)
            run.count("task_decisions")
    for r in data.get("task_decisions", []):
        old, new = run.m("task_decisions", r.get("id")), run.m("task_decisions", r.get("superseded_by"))
        if old and new:
            c.execute("UPDATE task_decisions SET superseded_by=? WHERE id=?", (new, old))
    # personal parts
    for r in data.get("time_entries", []):
        run.step()
        if run.there("time_entries", r.get("id")):  # 2.362.3 (#3098)
            continue
        d = umz_row(c, "time_entries", r, {"user_id": uid, "task_id": run.m("tasks", r.get("task_id")),
                                            "list_id": run.m("lists", r.get("list_id"))}, ts)
        if d:  # 2.278.0 B (#3094): the account export has no invoices: a billed entry stays billed (not billable)
            d = umz_billed(run, r, {**d, "billed_doc_id": run.m("office_docs", r.get("billed_doc_id"))}, ts)
        nid = umz_insert(c, "time_entries", d) if d else None
        if nid:
            run.put("time_entries", r.get("id"), nid)
            run.created["time_entries"].append(nid)
            run.count("time_entries")
    org_kind = man.get("kind") == "org"
    for src, table, kind, fixed in (("habits", "habits", "habits", {"user_id": uid}), ("filters", "filters", "filters", {"user_id": uid}),
                                    ("templates", "templates", "templates", {"owner_id": uid}),  # 2.905.0 (#5288): owner_id (was user_id)
                                    ("address_books", "books", "books", {"owner_id": uid, "org_id": org if org_kind else None, "owner_org_id": None}),
                                    ("event_calendars", "ev_cals", "ev_cals", {"owner_id": uid, "org_id": org if org_kind else None})):
        for r in data.get(src, []):
            run.step()
            if run.there(kind, r.get("id")):  # 2.362.3 (#3098)
                continue
            if table == "books" and org_kind and _oid(r.get("owner_org_id")):
                fixed = {**fixed, "owner_org_id": org}  # an address book of the organisation itself (2.52.0 C, #1438)
                if not org:  # 2.96.0 D (#1941): into the private space it becomes the person's own address book
                    run.warning(N_("An address book of the organisation became your own address book: {0}"), _txt(r.get("name"), 80))
            extra = {}
            if table == "filters":  # 2.362.4 (#3100): their ids are the old server's
                extra["rules"] = umz_filter_rules(run, r.get("rules"), who)
                if extra["rules"] is None:
                    run.warning(N_("A saved filter pointed at projects or people that did not come along and was left out: {0}"), _txt(r.get("name"), 80))
                    continue
                # 2.577.0 (#3356): a shared view only with its project, under its new id; never a list id or a share from the file
                extra["list_id"] = run.m("lists", r["list_id"]) if r.get("list_id") else None
                extra["shared"] = 1 if extra["list_id"] else 0
                if r.get("list_id") and not extra["list_id"]:
                    run.warning(N_("A saved filter pointed at projects or people that did not come along and was left out: {0}"), _txt(r.get("name"), 80))
                    continue
            elif table == "templates":
                extra["data"] = umz_template_data(_txt(r.get("kind"), 10) or "task", r.get("data"))
                if extra["data"] is None:
                    run.warning(N_("A template could not be imported: {0}"), _txt(r.get("name"), 80))
                    continue
                extra["extra"] = tx_import(r.get("extra"), who, tx_keys(json.loads(extra["data"])))  # 2.463.0 (#3860): never the file's text
            d = umz_row(c, table, r, {**fixed, **extra, "updated_at": ts, "changed_at": ts}, ts)
            nid = umz_insert(c, table, d) if d else None
            if not nid:
                continue
            run.put(kind, r.get("id"), nid)
            run.created[table if table in run.created else src].append(nid)
            run.count(src)
    for r in data.get("habit_logs", []):
        hid = run.m("habits", r.get("habit_id"))
        if hid and not run.old("habits", hid):  # 2.531.0 (#4317) F16: the check-ins came along with the earlier import
            d = umz_row(c, "habit_logs", r, {"habit_id": hid}, ts)
            if d:
                umz_insert(c, "habit_logs", d, rid=False)
    for r in data.get("contacts", []):
        run.step()
        bid = run.m("books", r.get("book_id"))
        if not bid or run.there("contacts", r.get("id")):
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
        if not cid or run.there("events", r.get("id")):
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
        if eid2 and not run.there("event_attendees", r.get("id")):
            d = umz_row(c, "event_attendees", r, {"event_id": eid2, "user_id": uid if _oid(r.get("user_id")) == me_old else None,
                                                   "contact_id": run.m("contacts", r.get("contact_id"))}, ts)
            run.put("event_attendees", r.get("id"), umz_insert(c, "event_attendees", d) if d else None)
    for r in data.get("journal", []):
        day = _txt(r.get("day"), 10)
        here = c.execute("SELECT day, text, mood, mood_enc, updated_at FROM journal WHERE user_id=? AND day=?",
                         (uid, day)).fetchone() if re.fullmatch(r"\d{4}-\d{2}-\d{2}", day) else None
        if here:  # 2.531.0 (#4317) F7: a day written here already keeps its text, the file's entry is added below it
            umz_journal_add(c, run, uid, r, here)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            d = umz_row(c, "journal", r, {"user_id": uid, "day": day, "updated_at": ts}, ts)
            if d:  # 2.306.0 A (#2885): sealed for the importing person like a new entry
                d.pop("mood_enc", None)
                d["text"], d["mood"], d["mood_enc"] = jr_seal(c, uid, d.get("text") or "", d.get("mood"))
            if d and umz_insert(c, "journal", d, rid=False):
                run.created["journal"].append(day)
                run.count("journal")
    # 2.144.5 B (#2410): the mailbox of the private space goes into the target workspace (an organisation or the private space)
    # without its passwords, unless that workspace has one
    if data.get("mailbox") and isinstance(data["mailbox"], list):
        from ..docs.store import doc_ws
        mws, v = doc_ws(run.org, uid), mbx_take_values(data["mailbox"][0])
        if v and c.execute("SELECT 1 FROM hub_mailboxes WHERE ws=?", (mws,)).fetchone():
            run.warning(N_("The workspace already has a mailbox: the one of the export was not imported."))
        elif v:
            v.update(org_id=run.org, owner_id=None if run.org else uid, ws=mws, created_by=uid, created_at=ts, updated_at=ts)
            nid = insert_id(c, f"INSERT INTO hub_mailboxes({', '.join(v)}) VALUES({','.join('?' * len(v))})", tuple(v.values()))
            run.created.setdefault("hub_mailboxes", []).append(nid)
            run.count("mailbox")
            run.warning(N_("Mailbox imported without its passwords and switched off: enter them in the settings and switch it on."))
    cur = usettings(c, uid)
    for r in data.get("settings", []):
        k, v = r.get("key"), r.get("value")
        if k not in UMZ_SETTINGS_ALL or not isinstance(v, str) or len(v) > 20000:
            continue
        if k in UMZ_SETTINGS_MORE:  # 2.363.4 (#3127): checked like a value set by hand
            try:
                v = clean_setting(k, v)
            except BadInput:
                continue
            if v is None:
                continue
        elif k == "look":  # 2.273.0 A (#3030): JSON, checked like a value set by hand
            try:
                v = clean_look_pref(v)
            except BadInput:
                continue
        elif (k == "lang" and v not in LANGS) or (k not in ("lang", "folders") and not re.fullmatch(r"[A-Za-z0-9:,._ -]{0,64}", v)):
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
    umz_files(c, run, uid, me_old, zf, files, data)
    if man.get("kind") == "org" and data.get("oi") and run.oi_done:  # 2.362.3 (#3098): these areas came with the same file
        run.warning(N_("Office, file store, chat and the other areas of this export are here already: they were skipped."))
    elif man.get("kind") == "org" and data.get("oi"):  # 2.137.0 (#2344): office, file store, chat ... (admin/orgimport.py)
        from .orgimport import oi_write
        oi_write(c, run, uid, man, zf, files, data, who)
        run.created["oi_done"] = True  # 2.362.3 (#3098, review): a run stopped inside (quota) took only a part of the areas
    if man.get("kind") != "org":  # #3470: my private file store, knowledge pages and tables
        umz_private(c, run, uid, man, zf, files, data, who)
    if man.get("kind") == "org":  # 2.459.0 (#3849): also on a second run: the lists it creates anew
        from .orgimport import oi_pictures
        oi_pictures(c, run, uid, zf, files, data)


# 2.363.4 (#3127): account parts that go through the areas of admin/orgimport.py (archive entry of the organisation export); a
# notepad or playbook only on a project of the file (the others hang on projects of other people, umz_left names them)
UMZ_PRIVATE_MORE = (("video_reviews", "videos/reviews.json"), ("video_versions", "videos/versions.json"),
                    ("video_comments", "videos/comments.json"), ("list_notepads", "lists/notepads.json"), ("playbooks", "lists/playbooks.json"),
                    # 2.995.0 (#5602): my own ticket types and field schema, into my private space as the organisation import does
                    # (admin/oi_team.py _ttype / _ofield; a type or field with the same key here stays and the project fields link to it)
                    ("ticket_types", "lists/ticket_types.json"), ("org_fields", "lists/org_fields.json"))
UMZ_SCHEMA_OI = ("lists/ticket_types.json", "lists/org_fields.json")  # 2.995.0 (#5602): idempotent by key, also on a second run


def umz_mails_oi(data, nodes, me_old):
    """2.363.4 (#3127): my filed mails as rows of hub/mails.json: the file names their .eml and attachments by their place in the
    ZIP (acctexport._mail_files), the area wants the nodes of the file store -> (mail rows, ids of their nodes)."""
    by_file = {r.get("file"): _oid(r.get("id")) for r in nodes if isinstance(r.get("file"), str) and _oid(r.get("id"))}
    rows, used = [], set()
    for r in data.get("hub_mails") or []:
        if not isinstance(r, dict) or not _oid(r.get("id")):
            continue
        d = {k: v for k, v in r.items() if k not in ("eml_file", "attachment_files", "eml_id", "files", "folder_id")}
        att = r.get("attachment_files") if isinstance(r.get("attachment_files"), list) else []
        ids = [by_file[f] for f in att if isinstance(f, str) and by_file.get(f)]
        # the account export names no workspace (oi_team._mail sets it; a required column without a value drops the row)
        d.update(owner_id=me_old, ws="", eml_id=by_file.get(r.get("eml_file")) if isinstance(r.get("eml_file"), str) else None, files=json.dumps(ids))
        used.update(x for x in (d["eml_id"], *ids) if x)
        rows.append(d)
    return rows, used


def umz_private_oi(data, files, me_old=None):
    """#3470: the private areas of an account export as the archive entries of admin/oi_store.py -> {entry: rows}. The bytes
    get the names the areas read (files/store/<node>-v<no>-<name>, files/wiki/..., files/sheets/...) as a second name of the
    file's entry; an export before #3470 has no versions: the current one comes from the node's "file". Files of a filed mail
    follow the mail (it stays on the old server), rows of a table in the trash stay with it."""
    oi = {}
    every = [r for r in data.get("private_files") or [] if isinstance(r, dict)]
    mails, of_mails = umz_mails_oi(data, every, me_old)  # 2.363.4 (#3127): a filed mail comes along with its files
    took = {_oid(m.get("id")) for m in mails}
    nodes = [r for r in every if not r.get("hub_mail_id") or (_oid(r.get("hub_mail_id")) in took and _oid(r.get("id")) in of_mails)]
    names = {_oid(r.get("id")): r.get("name") for r in nodes}
    vers = [v for v in data.get("private_versions") or [] if _oid(v.get("node_id")) in names]
    if not data.get("private_versions"):  # an older export: the current version of each file
        vers = [{"id": r.get("id"), "node_id": r.get("id"), "no": _oid(r.get("cur_version")) or 1, "size": r.get("size"),
                 "mime": r.get("mime"), "created_at": r.get("updated_at"), "file": r.get("file")}
                for r in nodes if r.get("kind") == "file" and r.get("file")]
    kept = []
    for v in vers:
        try:
            path = f"files/store/{int(v['node_id'])}-v{int(v['no'])}-{_safe_part(names.get(_oid(v['node_id'])))}"
        except (TypeError, ValueError, KeyError):
            continue
        if path not in files and v.get("file") in files:
            files[path] = files[v["file"]]
        if path in files:
            kept.append(v)
    # 2.480.0 review (#3470): a version without bytes (a file encrypted in the browser: its bytes are not exported) is no
    # row, and a file without any version is no node (it would point at nothing)
    vers = kept
    has = {_oid(v.get("node_id")) for v in vers}
    nodes = [r for r in nodes if r.get("kind") != "file" or _oid(r.get("id")) in has]
    sheets = {_oid(r.get("id")) for r in data.get("sheets") or []}
    for part, kind in (("wiki_files", "wiki"), ("sheet_files", "sheets")):
        for r in data.get(part) or []:
            path = f"files/{kind}/{_oid(r.get('id')) or 0}-{_safe_part(r.get('name'))}"
            if path not in files and r.get("file") in files:
                files[path] = files[r["file"]]
    for part, entry in UMZ_PRIVATE:
        rows = nodes if part == "private_files" else vers if part == "private_versions" else data.get(part) or []
        if part.startswith("sheet_"):
            rows = [r for r in rows if _oid(r.get("sheet_id")) in sheets and not r.get("deleted_at")]
        if part in ("private_versions", "wiki_files", "sheet_files"):  # the account export names no server path: the area's prep sets it
            rows = [{**r, "path": ""} for r in rows]
        if rows:
            oi[entry] = rows
    if mails:
        oi["hub/mails.json"] = mails
    mine = {_oid(L.get("id")) for L in data.get("lists") or [] if isinstance(L, dict) and not L.get("e2e")}
    for part, entry in UMZ_PRIVATE_MORE:
        rows = [r for r in data.get(part) or [] if isinstance(r, dict)]
        if part in ("list_notepads", "playbooks"):
            rows = [r for r in rows if _oid(r.get("list_id")) in mine]
        if rows:
            oi[entry] = rows
    oi.update(umz_office_oi(data, me_old))  # 2.765.0 (#3965)
    return oi


UMZ_MONTH_RE = re.compile(r"^(19|20|21)\d\d-(0[1-9]|1[0-2])$")  # 2.765.0 (#3965): the month of a timesheet


def umz_office_oi(data, me_old):
    """2.765.0 (#3965): my absences and timesheets as rows of hub/absences.json (into my personal office, oi_prepare) and
    time_sheets.json (my private space). Both always mine: the person columns are set to my old account id whatever the file
    says (the areas map only that one to the importing person), who decided is never taken over. A request still waiting
    (pending) is an entered absence there (my personal office asks nobody); one month comes once (time_sheets: month per person)."""
    if me_old is None:
        return {}
    out = {}
    ab = []
    for r in data.get("absences") or []:
        if not isinstance(r, dict) or not _oid(r.get("id")):
            continue
        a, b = r.get("start_date"), r.get("end_date")
        try:  # checked like an absence entered by hand (hub/absence.py abs_clean): a day, the end not before the start
            span = (date.fromisoformat(b) - date.fromisoformat(a)).days if DATE_RE.match(a) and DATE_RE.match(b) else -1
        except (TypeError, ValueError):
            span = -1
        if not 0 <= span < ABS_SPAN_MAX:
            continue
        st = r.get("status") if r.get("status") in ("approved", "rejected") else "approved"
        ab.append({**r, "user_id": me_old, "created_by": me_old, "decided_by": None, "status": st,
                   "kind": r.get("kind") if r.get("kind") in ABS_KINDS else "other",
                   "half_day": r.get("half_day") if r.get("half_day") in ABS_HALF else "", "note": _txt(r.get("note"), ABS_NOTE_MAX),
                   "decision_note": _txt(r.get("decision_note"), ABS_NOTE_MAX)})
    if ab:
        out["hub/absences.json"] = ab
    ts, seen = [], set()
    for r in data.get("timesheets") or []:
        m = r.get("month") if isinstance(r, dict) else None
        if not _oid(r.get("id") if isinstance(r, dict) else None) or not isinstance(m, str) or not UMZ_MONTH_RE.match(m) or m in seen:
            continue
        seen.add(m)
        # 2.765.0 (#3965, fable F2): only the known fields of a month; the history (log) is never taken from a file (its "by"
        # ids would be shown as names of this server's accounts), the state only one of the app's own
        ts.append({**{k: r[k] for k in UMZ_SHEET_KEEP if isinstance(r.get(k), str)}, "id": r["id"], "month": m,
                   "state": r.get("state") if r.get("state") in UMZ_SHEET_STATES else "open", "log": "[]",
                   "user_id": me_old, "decided_by": None})
    if ts:
        out["time_sheets.json"] = ts
    return out


UMZ_SHEET_STATES = ("open", "closed", "approved")  # 2.765.0 (#3965, fable F2): time_sheets.state (personal/timesheet.py)
UMZ_SHEET_KEEP = ("closed_at", "decided_at", "note", "created_at", "updated_at")


def umz_sheets_here(c, uid, data):
    """2.765.0 (#3965): the months of the file's timesheets I have here already (the one here stays, the preview names them)."""
    want = {r.get("month") for r in data.get("timesheets") or [] if isinstance(r, dict) and isinstance(r.get("month"), str)}
    if not want:
        return set()
    return {r[0] for r in c.execute("SELECT month FROM time_sheets WHERE user_id=?", (uid,)) if r[0] in want}


def umz_private(c, run, uid, man, zf, files, data, who):
    """#3470: my private file store (every version), knowledge pages and tables, restored in my private space -- also when the
    rest goes into an organisation (they are mine alone, like the Home & life projects). Sealed, counted on my storage and
    checked by the virus scanner per file like an upload (orgimport.oi_file); undone with the import (run.created["oi"])."""
    from .umz_more import umz_more_has, umz_more_write, umz_more_space
    me_old = _oid((man.get("user") or {}).get("id")) or -1  # review: a file without its account id: the mails are still mine
    oi = umz_private_oi(data, files, me_old)
    if not oi and not umz_more_has(data):
        return
    again = run.oi_done
    if again:  # 2.362.3 (#3098): an earlier import of this file brought them already
        run.warning(N_("Your files, knowledge pages and tables are here already from an earlier import: they were skipped."))
        # 2.995.0 (#5602, review F1): the own ticket types and field schema still go through (one with the same key here stays,
        # a new one comes), so the projects this run creates find their types and link their fields
        oi = {k: v for k, v in oi.items() if k in UMZ_SCHEMA_OI}
        if not oi:
            return
    here = umz_sheets_here(c, uid, data) if oi.get("time_sheets.json") else set()  # 2.765.0 (review N4): after the oi_done check
    if here:  # 2.765.0 (#3965): a month I have here already keeps the one here
        oi["time_sheets.json"] = [r for r in oi["time_sheets.json"] if r.get("month") not in here]
        run.warning(N_("Timesheets of months you have here already were not taken over: {0}"), ", ".join(sorted(here)))
        if not oi["time_sheets.json"]:
            oi.pop("time_sheets.json")
        if not oi and not umz_more_has(data):
            return
    if run.org and any(oi.get(k) for k in UMZ_SCHEMA_OI):  # 2.995.0 (#5602, review F2): they are mine, the projects the organisation's
        run.warning(N_("Your own ticket types and fields went into your private workspace; projects imported into the organisation do not use them."))
    from .orgimport import oi_write
    umz_more_space(run, oi)  # 2.363.4 (#3127): a mail or sign-off in my private space never points into an organisation
    org = run.org
    run.org = None
    try:
        if oi:
            # 2.995.0 (#5602): + the project fields, so oi_team._schema_links links them to my own field schema again
            oi_write(c, run, uid, man, zf, files, {"oi": oi, "people": data.get("people") or [], "list_fields": data.get("list_fields") or []}, who)
        if not again:
            umz_more_write(c, run, uid, me_old, data, umz_salt(man))  # 2.363.4 (#3127): bookmarks, focus sessions, arrangements, bells ... (2.531.0 #4317: + salt)
    finally:
        run.org = org
    run.created["oi_done"] = True


def umz_share(c, run, uid, data, picks, can_invite, salt=None):
    """After the import: lists shared with the people ticked in the preview (found by their e-mail hash), missing people
    invited (instance admins only, the address typed by the admin must match the hash). Returns the people's results for
    the report."""
    out = []
    # 2.644.0 (#5024): the imported projects locked until the caller commits (id order, like the watchdog's lffolder.lf_own_stale):
    # their own member shares are committed already, the members not yet - the watchdog must not take those shares as stale
    lids = sorted({int(x) for x in run.created.get("lists") or [] if isinstance(x, int)})
    if lids:
        c.execute(f"SELECT id FROM lists WHERE id IN ({','.join('?' * len(lids))}) ORDER BY id FOR UPDATE", tuple(lids)).fetchall()
    seen = umz_seen(c, uid, salt)
    for p in data.get("people", []):
        h = umz_pid(p)  # 2.278.0 B (#3094): the address hash, else "id<old id>" (matched by user name only)
        pick = picks.get(h) or {}
        if not h or p.get("agent") or not (pick.get("share") or pick.get("invite")):
            continue
        lists = p.get("lists") if isinstance(p.get("lists"), dict) else {}
        hit = umz_find(c, uid, umz_phash(p), seen) or umz_find_login(c, uid, pick.get("login"))
        em = pick.get("email") or _email(p.get("email"))  # typed by the admin, or the plain address of an older file
        target, joins, state = None, None, "skipped"
        if hit and pick.get("share"):
            target, state = hit["id"], "shared"
            # 2.278.0 A (#3095): an organisation export: an existing account joins only by accepting an invitation (#2480),
            # with the role the admin confirmed; until then nothing of the organisation is shared with it
            if run.org and run.kind == "org" and not umz_in_org(c, run.org, hit["id"]):
                ojn_invite(c, run.org, hit["id"], umz_role(pick.get("role") or p.get("role")), by=uid)
                run.created.setdefault("org_joins", []).append([run.org, hit["id"]])  # 2.360.2 M (#2561): the undo withdraws it
                joins, target, state = hit["id"], None, "org_invited"
                run.warning(N_("Person invited to the organisation: their content stays with you as the importing admin, the ticked projects are shared when they accept."))
        elif not hit and pick.get("invite") and can_invite:
            if not em or umz_email_hash(em, salt) != h:
                state = "mismatch"  # review M1: the typed address is not the one of the file -- nobody is invited
            else:
                target = umz_invite(c, run, uid, em, _txt(p.get("name"), 60), umz_role(pick.get("role") or p.get("role")))
                state = "invited" if target else "failed"
                if target and run.org:  # 2.360.2 M (#2561): like an existing account: nothing shared before the person accepts
                    joins, target, state = target, None, "org_invited"
                    run.warning(N_("Person invited to the organisation: their content stays with you as the importing admin, the ticked projects are shared when they accept."))
        n = 0
        pairs = [(lid, role if role in ROLES else "edit") for lid, role in ((run.m("lists", old), role) for old, role in lists.items())
                 if lid and lid in run.created["lists"]]
        if target:
            n = sum(1 for lid, role in pairs if _folder_member_add(c, lid, target, role, uid))
        elif joins:  # 2.363.0 (#3132): noted on the invitation, shared when the person accepts
            ojn_later(c, run.org, joins, uid, pairs)
        if os.environ.get("KALMIDO_TEST") == "1" and os.environ.get("KALMIDO_TEST_UMZ_SHARE_DELAY"):  # tests only (2.644.0, #5024)
            time.sleep(float(os.environ["KALMIDO_TEST_UMZ_SHARE_DELAY"]))
        out.append({"key": h, "name": _txt(p.get("name"), 100), "state": state, "lists": n})
    return out


def umz_in_org(c, oid, uid):
    """2.278.0 A (#3095): uid is a member of organisation oid."""
    with system_ctx(c):  # membership structure of another person
        return bool(c.execute("SELECT 1 FROM org_members WHERE org_id=? AND user_id=?", (oid, uid)).fetchone())


def umz_fix_people(c, run, uid, names):
    """After the sharing: an assignment or a comment author that points at a person who did not become a member of the
    list (sharing refused, not ticked, the run stopped) is undone -- the name stays as text, nobody gets attributed or
    assigned in a list they cannot see."""
    ids = run.created["tasks"]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        nm = f"""user_id!=? AND NOT EXISTS (SELECT 1 FROM list_members m JOIN tasks t ON t.list_id=m.list_id
                 WHERE t.id=obj_comments.ref_id AND m.user_id=obj_comments.user_id)"""  # 2.972.0 (#5272): the core's table
        for r in c.execute(f"SELECT id, user_id FROM obj_comments WHERE kind='task' AND ref_id IN ({q}) AND user_id IS NOT NULL AND {nm}", part + [uid]).fetchall():
            c.execute("UPDATE obj_comments SET user_id=NULL, ext_name=? WHERE id=?", (names.get(r["user_id"]) or tr("Unknown"), r["id"]))
        n = c.execute(f"""UPDATE tasks SET assignee_id=NULL, assigned_by=NULL WHERE id IN ({q}) AND assignee_id IS NOT NULL AND assignee_id!=?
                          AND NOT EXISTS (SELECT 1 FROM list_members m WHERE m.list_id=tasks.list_id AND m.user_id=tasks.assignee_id)""",
                      part + [uid]).rowcount
        if n:
            run.warning(N_("Assignment not imported (the person is not on this server or was not selected)"))
        # 2.362.4 (#3100): the same for person fields and mentions
        c.execute(f"""DELETE FROM task_field_values v USING list_fields f, tasks t WHERE f.id=v.field_id AND t.id=v.task_id AND t.id IN ({q})
                      AND f.type='person' AND v.value!=? AND NOT EXISTS (SELECT 1 FROM list_members m WHERE m.list_id=t.list_id AND m.user_id::text=v.value)""",
                  part + [str(uid)])
        for r in c.execute(f"SELECT c.id, c.body, t.list_id FROM obj_comments c JOIN tasks t ON t.id=c.ref_id AND c.kind='task' WHERE t.id IN ({q}) AND c.body ILIKE '%<@%'", part).fetchall():
            mem = {x[0] for x in c.execute("SELECT user_id FROM list_members WHERE list_id=?", (r["list_id"],)).fetchall()} | {uid}
            body = UMZ_MENTION_RE.sub(lambda m: m.group(0) if int(m.group(1)) in mem else "@" + (names.get(int(m.group(1))) or "?"), r["body"])
            if body != r["body"]:
                c.execute("UPDATE obj_comments SET body=? WHERE id=?", (body, r["id"]))


def umz_invite(c, run, uid, email, name, role="member"):
    """A new account for a missing person (instance admin) and the invitation link by e-mail (#697). 2.360.2 M (#2561): into an
    organisation only by accepting an invitation (org_joins, in the admins' list of open invitations), in the confirmed role."""
    if c.execute("SELECT 1 FROM users WHERE lower(email)=?", (email,)).fetchone():
        return None  # the address exists but the admin does not see it: never a second account
    base = re.sub(r"[^a-z0-9._-]", "", email.split("@")[0].lower())[:24] or "user"
    if not re.match(r"[a-z0-9]", base):
        base = "u" + base
    login, i = base, 1
    while c.execute("SELECT 1 FROM users WHERE username=?", (login,)).fetchone():
        i += 1
        login = f"{base}{i}"[:32]
    nid = create_user(c, login, name or login, None, None, False, onboard=True, ask_purpose=uid if run.org else 0)  # 2.364.0 A (#3032)
    c.execute("UPDATE users SET email=? WHERE id=?", (email, nid))
    uset(c, nid, "lang", usettings(c, uid).get("lang") or "en")
    if run.org:
        with system_ctx(c):  # the organisation's admin invites a person who is no member (structure)
            ojn_invite(c, run.org, nid, role, by=uid)
        run.created.setdefault("org_joins", []).append([run.org, nid])
    try:
        invite_new(c, nid, uid, send=True)
    except Denied:
        return None
    return nid


def umz_unwrite(run):
    """Removes the files of rows that were never committed."""
    for p in run.written if run else ():
        try:
            os.remove(p)
        except OSError:
            pass


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
            seen = umz_seen(c, uid, umz_salt(man))
            for p in data.get("people", []):
                h = umz_pid(p)  # 2.278.0 B (#3094): + a user name the admin typed
                if h and (opts["people"].get(h) or {}).get("share"):
                    hit = umz_find(c, uid, umz_phash(p), seen) or umz_find_login(c, uid, opts["people"][h].get("login"))
                    # 2.278.0 A (#3095): into an organisation only its members; an invited account is none until it accepts
                    # (its rows stay with me like those of a person not ticked)
                    if hit and _oid(p.get("user_id")) and not (man.get("kind") == "org" and opts["org"] and not umz_in_org(c, opts["org"], hit["id"])):
                        people[_oid(p.get("user_id"))] = hit["id"]
            if man.get("kind") == "org":  # an organisation export: my own account there has my e-mail address
                from .acctexport import umz_email_hash
                mine = umz_email_hash((c.execute("SELECT email FROM users WHERE id=?", (uid,)).fetchone() or [""])[0], umz_salt(man))
                hit = [p for p in data.get("people", []) if mine and umz_phash(p) == mine]
                man["user"]["id"] = _oid(hit[0].get("user_id")) if hit else None
                if hit and _oid(hit[0].get("user_id")) in people:
                    people.pop(_oid(hit[0].get("user_id")), None)
            total = sum(len(v) for k, v in data.items() if k != "oi") + sum(len(v) for v in (data.get("oi") or {}).values())
            eid = st.get("export_id") or secrets.token_hex(8)
            run = _Run(uid, iid, eid, opts["org"], total)
            run.kind = man.get("kind") or "account"
            src = umz_src(man, st.get("export_id") or "")
            umz_have(c, run, uid, umz_earlier(c, uid, src, st.get("export_id") or ""),  # 2.362.3 (#3098)
                     mine=src == umz_src({"format": UMZ_FORMAT, "source": {"url": PUBLIC_URL}, "user": {"id": uid}}, ""))
            if run.kind == "org" and not run.org:  # 2.96.0 D (#1941): an organisation export into the private space
                run.warning(N_("Imported into your private workspace: nobody joins an organisation, projects are only shared with the people you ticked."))
            c.commit()
            if run.kind == "org":  # 2.137.0 (#2344): the personal office for office parts going into the private space
                from .orgimport import oi_prepare
                oi_prepare(c, run, uid, data)
            elif data.get("absences") and not run.oi_done:  # 2.765.0 (#3965, review N3: not for a second import of the file): my absences go into my personal office (umz_private, also next to an organisation)
                from .orgimport import oi_prepare
                oi_prepare(c, run, uid, {"oi": umz_office_oi(data, _oid((man.get("user") or {}).get("id")) or -1)}, private=True)
            _L.rej = {}  # 2.531.0 (#4317) F11: umz_insert counts the refused rows of the run
            umz_write(c, run, uid, man, zf, files, data, people)
            umz_refused(run)
            # 2.273.0 A (#3030): what stays on the old server, in the result and the import's report too
            left = [{"what": w, "count": n} for w, n in (man.get("org_skipped") or {}).items()] if run.kind == "org" else umz_left(data, man.get("_unread"))
            if left:  # 2.454.0 (#3808): as stored texts, umz_view translates the names too; 2.531.0 (#4317) F4: always named
                run.warning(UMZ_AREAS_LEFT, stored_join(("{0} ({1})", (x["what"],), x["count"]) for x in left), must=True)
            if run.stats.get("skipped"):  # 2.362.3 (#3098)
                run.warning(N_("Already here from an earlier import, skipped: {0} entries"), run.stats["skipped"])
            report = {**run.stats, "export_id": eid, "src": src, "target": run.org, "tasks": run.stats.get("tasks", 0), "not_taken": left}
            iid_db = None
            if any(run.created[k] for k in run.created):  # recorded with the rows (2.137.0, #2344: + "oi"): whatever happens next, undo works
                from ..integrations.importers import imp_prune
                iid_db = insert_id(c, "INSERT INTO imports(user_id,source,file_name,created,report,created_at) VALUES(?,?,?,?,?,?)",
                                   (uid, UMZ_SOURCE, _txt(st.get("name"), 200), json.dumps({**run.created, "src": run.src}), json.dumps(report), iso(now_utc())))
                imp_prune(c, uid)
            c.commit()
            run.written = []  # committed: the files belong to their rows now
            for fn in run.after:  # 2.574.0 (#4556): umz_more._conn_tell
                fn(c)
            shared = []
            try:
                shared = umz_share(c, run, uid, data, opts["people"], opts["can_invite"], umz_salt(man))
            except Exception as e:  # noqa: BLE001 -- the import stays (and can be undone); the sharing is reported
                c.heal() or c.rollback()
                print(f"account import of user {uid}: sharing failed: {type(e).__name__}", flush=True)
                run.warning(N_("Sharing with the selected people failed. Share the projects by hand."))
            names = {}
            for p in data.get("people", []):  # the new account ids of the mapped people -> their names from the file
                o = _oid(p.get("user_id"))
                if o in people:
                    names[people[o]] = _txt(p.get("name"), 100)
            umz_fix_people(c, run, uid, names)
            if iid_db or run.created.get("org_joins"):  # 2.360.2 M (#2561): org_joins, made by the sharing, after the import was recorded
                from .orgimport import oi_prints
                run.created["prints"] = oi_prints(c, run.created)  # 2.506.0 (#4299): the state the undo compares with, now that all is written
                # 2.506.0 (#4299): + src, this update lost it: the next import of the file took everything over a second time. And
                # a run that only invited people (nothing new, the rest already here) gets its record, or the undo cannot withdraw them
                done = json.dumps({**run.created, "src": run.src})
                if iid_db:
                    c.execute("UPDATE imports SET created=? WHERE id=?", (done, iid_db))
                else:
                    iid_db = insert_id(c, "INSERT INTO imports(user_id,source,file_name,created,report,created_at) VALUES(?,?,?,?,?,?)",
                                       (uid, UMZ_SOURCE, _txt(st.get("name"), 200), done, json.dumps(report), iso(now_utc())))
            bump(c)
            c.commit()
        finally:
            zf.close()
        result = {"created": run.stats, "people": shared, "import_id": iid_db,
                  "undo_until": iso(umz_undo_until(now_utc())) if iid_db else None,
                  "warnings": run.warnings()}  # 2.448.0 (#3765): key + values, umz_view translates; 2.531.0 (#4317) F4: the must ones first
        if run.stopped == "quota":
            result["stopped"] = [N_("Your storage is full: some files were left out, everything else came over. The import can be undone.")]
        _set(uid, iid, state="stopped" if run.stopped else "done", result=result, progress=None)
        print(f"account import of user {uid}: {run.stats.get('tasks', 0)} tasks", flush=True)
    except UmzBad as e:
        c.rollback()
        umz_unwrite(run)  # 2.362.4 (#3100)
        from .orgimport import oi_drop_empty_pb
        oi_drop_empty_pb(c, run, uid)  # 2.137.1 review (#2399): also when the file turns out bad while writing
        _set(uid, iid, state="invalid", error=[e.text, *e.args_])
    except Exception as e:  # noqa: BLE001 -- the state says it failed; never content in the message
        try:
            c.rollback()
        except Exception:  # noqa: BLE001 -- rollback after an error: the failed state counts
            pass
        umz_unwrite(run)
        from .orgimport import oi_drop_empty_pb
        oi_drop_empty_pb(c, run, uid)  # 2.137.1 (#2399): the personal office made for this run, if it stayed empty
        print(f"account import of user {uid} failed: {type(e).__name__}", flush=True)
        _set(uid, iid, state="failed", error=[N_("The import failed. Nothing was imported. Please try again later or ask the server admin (server log).")])
    finally:
        try:
            p = os.path.join(_dir(uid, iid), "upload.bin")
            if (_st(uid, iid) or {}).get("state") in ("done", "stopped", "failed") and os.path.exists(p):
                os.remove(p)  # the upload is gone as soon as the run is over
        except OSError:
            pass
        _L.rej = None  # 2.531.0 (#4317) F11: a failed run's thread counts nothing more
        c.close()
        with _UMI_LOCK:
            _UMI.pop(int(uid), None)


def umz_room(c, uid, files):
    """#3470: the files of the export (their unpacked sizes: what the import writes) must fit my storage and the server's disk,
    else UmzBad with what they need and what is free (the upload only counted its packed size)."""
    need = sum(zi.file_size for p, (zi, _s) in files.items() if p.startswith("files/"))
    if not need:
        return
    info = quota_info(c, uid)
    if info and info["limit"] and info["used"] + need > info["limit"]:
        raise UmzBad(N_("Your storage is too small for the files of this export: they need {0}, {1} are free. Free up space or ask for more storage, then upload the file again."),
                     fmt_bytes(need), fmt_bytes(max(0, info["limit"] - info["used"])))
    if not umz_space_ok(ATT_DIR, need):
        raise UmzBad(N_("There is not enough space on the server for the import. Please ask the server admin."))


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
        umz_room(c, uid, files)  # #3470: before the preview, never halfway through the run
        pv = umz_preview(c, uid, man, data, can_invite)
        c.rollback()
        _set(uid, iid, state="preview", preview=pv, export_id=pv["export_id"], src=pv["src"])
    except UmzBad as e:
        _set(uid, iid, state="invalid", error=[e.text, *e.args_])
        try:
            os.remove(os.path.join(_dir(uid, iid), "upload.bin"))
        except OSError:
            pass
    except Exception as e:  # noqa: BLE001
        print(f"account import check of user {uid} failed: {type(e).__name__}", flush=True)
        _set(uid, iid, state="invalid", error=[N_("The file could not be read.")])
    finally:
        c.close()
        with _UMI_LOCK:
            _UMI.pop(int(uid), None)


def _buffered(path, key, size):
    return io.BufferedReader(UmzReader(path, key, size), UMZ_BLOCK)


def umz_org_head(path, key, size):
    """The header of an encrypted organisation export (orgexport.py ox_header), None for anything else."""
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
    h = umz_org_head(path, key, size)
    hh = hashlib.sha256(OX_MAGIC + h["_raw"] + h["_head"]).digest()
    try:
        w = base64.b64decode(h["wrapped_fk"])
        prefix = base64.b64decode(h["nonce_prefix"])
        block = int(h["block"])
        if isinstance(okey, tuple):  # 2.138.0 C (#1972): core/orgcrypt.py rck_parse; a recovery key opens the header's copy
            try:
                okey = rck_resolve(okey, int(h["org_id"]), h.get("recovery_wrapped"))
            except OrgCryptError:
                raise UmzWrongKey() from None
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
        _set(uid, iid, state="invalid", error=[e.text, *e.args_])
        return
    except Exception as e:  # noqa: BLE001
        print(f"account import unlock of user {uid} failed: {type(e).__name__}", flush=True)
        _set(uid, iid, state="invalid", error=[N_("The file could not be read.")])
        return
    finally:
        with _UMI_LOCK:
            _UMI.pop(int(uid), None)


def umz_slots_guard(uid, busy, qc):
    """2.370.3 (#2760): the check before a step of an import is queued (under the queue lock "umz:import"): 409 while one of
    the person's runs, 429 when UMZ_PARALLEL imports wait or run on the server (account and knowledge import together)."""
    if busy(uid, qc):
        raise Denied(409, tr("An import is already running"))
    if bgj_active(UMZ_IMPORT_KINDS, c=qc) >= UMZ_PARALLEL:
        raise Denied(429, tr("Too many imports are running on this server right now. Please try again in a few minutes."))


def umz_settle(busy, uid):
    """2.308.0 (#3261): the worker publishes its state (key, preview, done) and then still closes its file and connections:
    the person's next step right after it waits (at most UMZ_SETTLE_S s) for that end instead of answering "already
    running". 2.370.3 (#2760): the end is the queue row's end (any process)."""
    end = time.monotonic() + UMZ_SETTLE_S
    while busy(uid) and time.monotonic() < end:
        time.sleep(0.05)


def umz_work(uid, fn, *args):
    """2.370.3 (#2760): a step in the thread of its queue row; known in this process while it runs (_UMI)."""
    with _UMI_LOCK:
        t = _UMI.get(int(uid))
        if t and t.is_alive():  # review 2: a step taken again while the first still runs here: never two at once
            raise RuntimeError("import step still running in this process")
        _UMI[int(uid)] = threading.current_thread()
    try:
        fn(uid, *args)
    finally:
        if os.environ.get("KALMIDO_TEST") == "1" and os.environ.get("KALMIDO_TEST_UMZ_END_DELAY"):  # tests only (#3261)
            time.sleep(float(os.environ["KALMIDO_TEST_UMZ_END_DELAY"]))


@bgj_fn("umz:check", long=True)  # the check only reads the upload and builds the preview: run again after a lost run
def umz_check_row(uid, iid, can_invite):
    umz_work(uid, umz_check, iid, can_invite)


@bgj_fn("umz:unlock", tries=1, long=True)  # replaces the upload with its opened ZIP: never twice
def umz_unlock_row(uid, iid, okey, can_invite):
    umz_work(uid, umz_unlock, iid, tuple(okey), can_invite)


@bgj_fn("umz:import", tries=1, long=True)  # writes into the account: a lost run says "interrupted", never a second run
def umz_import_row(uid, iid, opts):
    umz_work(uid, umz_run, iid, opts)


_UMZ_KIND_OF = {"umz_check": "umz:check", "umz_unlock": "umz:unlock", "umz_run": "umz:import"}


def _thread(uid, fn, *args, iid=None, state=None):
    """2.370.3 (#2760): the step as a queue row (the worker runs it). state (review 4): the step's state (checking / running),
    written under the queue lock right before the row, so no process sees it without its row; meanwhile the waiting of this
    process is not "interrupted" either (_UMI_START)."""
    with _UMI_LOCK:
        _UMI_START[int(uid)] = _UMI_START.get(int(uid), 0) + 1

    def guard(qc):
        umz_slots_guard(uid, _busy, qc)
        if state:
            _set(uid, iid, **state)
    try:
        umz_settle(_busy, uid)
        bgj_add(_UMZ_KIND_OF[fn.__name__], uid, *args, user_id=uid, lock="umz:import", guard=guard)
    finally:
        with _UMI_LOCK:
            _UMI_START[int(uid)] -= 1
            if not _UMI_START[int(uid)]:
                _UMI_START.pop(int(uid))


def umz_undo_parts(c, cr, plan, since, uid):
    """2.455.0 (#3469): the rows umz_part recorded. 2.506.0 (#4299): the ones unchanged since the import -> how many stay.
    2.516.0 (#4366): sprints, rules and portal tickets like the tasks only in a list uid may still write (one moved into a list of
    others since, or whose list uid lost the right to, stays)."""
    kept = 0
    for table, key in reversed(cr.get("parts") or []):
        if table == "task_links":
            r = c.execute("SELECT created_at, section_at FROM task_links WHERE task_id=? AND list_id=?", (int(key[0]), int(key[1]))).fetchone()
            if r and (imp_undo_after(r["created_at"], since) or imp_undo_after(r["section_at"], since)):
                kept += 1
                continue
            c.execute("DELETE FROM task_links WHERE task_id=? AND list_id=?", (int(key[0]), int(key[1])))
        elif table in ("sprints", "list_rules", "portal_tickets") and plan.goes(table, int(key)):
            r = c.execute(f"SELECT list_id FROM {table} WHERE id=?", (int(key),)).fetchone()
            if r is None or list_role(c, r["list_id"], uid) not in WRITE_ROLES:  # 2.516.0 (#4366)
                kept += r is not None
                continue
            if table == "sprints":  # tasks.sprint_id has no foreign key
                c.execute("UPDATE tasks SET sprint_id=NULL, sprint_at=NULL WHERE sprint_id=?", (int(key),))
            c.execute(f"DELETE FROM {table} WHERE id=?", (int(key),))
    return kept


def umz_undo_books(c, uid, bids):
    """2.370.4 (#3089) M6: the address books bids of uid into the trash like op_book_delete (birthday tasks to the trash, the
    clients' contact persons unlinked until a restore); restore and the purge after the trash days as there."""
    for bid in bids:
        if not c.execute("SELECT 1 FROM books WHERE id=? AND owner_id=? AND deleted_at IS NULL", (bid, uid)).fetchone():
            continue
        live = [x[0] for x in c.execute("SELECT id FROM contacts WHERE book_id=? AND deleted_at IS NULL", (bid,)).fetchall()]
        from ..newsletter.sync import NWL_BLOCKED, nls_keep  # review N1: the unsubscriptions outlive the book (as op_book_delete)
        nls_keep(c, [r[0] for r in c.execute(f"SELECT id FROM contacts WHERE book_id=? AND nl_status IN ({','.join('?' * len(NWL_BLOCKED))})",
                                             (bid, *NWL_BLOCKED))])
        bk_occ_drop(c, uid, live)
        ctt_unlink(c, live)
        c.execute("UPDATE books SET deleted_at=? WHERE id=?", (iso_ms(now_utc()), bid))


def umz_undo_tasks(c, uid, cr):
    """The run's tasks: only still writable ones (in its own lists the user is the owner). 2.585.0 (#4350): also for the preview."""
    mine = []
    ids = [int(x) for x in cr.get("tasks") or []]
    for i in range(0, len(ids), 500):
        part = ids[i:i + 500]
        q = ",".join("?" * len(part))
        for t in c.execute(f"SELECT id, list_id FROM tasks WHERE id IN ({q}) AND created_by=? AND tt_id ILIKE 'kalmido:%'", part + [uid]).fetchall():
            if list_role(c, t["list_id"], uid) in WRITE_ROLES:
                mine.append(t["id"])
    return mine


# 2.611.0 (#4866): the area of what an undo deletes for good, for the tables of the account import itself (oi_undo_preview)
_UMZ_GONE_AREAS = {"habits": N_("Habits"), "filters": N_("Filters"), "templates": N_("Templates"), "template_files": N_("Templates"),
                   "time_entries": N_("Time entries"), "bookmarks": N_("Bookmarks"), "sprints": N_("Sprints"), "list_rules": N_("Rules"),
                   "ev_cals": N_("Calendars"), "pomos": N_("Focus sessions"), "view_layouts": N_("Saved arrangements"),
                   "list_layouts": N_("Saved arrangements"), "journal": N_("Journal"),
                   # 2.765.0 (#3965): a folder's playbooks and the household budget rows (umz_more)
                   "playbooks": N_("Playbooks"), "budget_cats": N_("Household budget"), "budget_entries": N_("Household budget"),
                   "budget_recurring": N_("Household budget")}


def _umz_there(c, uid, cr):
    """2.611.0 (#4866): {(table, key)} of the rows run cr recorded that are still there and its undo may delete for good: by id
    (the plan's rows - the account import's own and the areas' -, calendars, mailboxes), the more rows (umz_more_there), the
    placements of tasks in other lists and the journal days. Taken before and after the undo's statements, the difference is what
    went for good (rows put into a trash are still there). Table names only from fixed lists, never from the record."""
    from .orgimport import oi_tables
    from .umz_more import umz_more_there
    from .umz_undoplan import undo_rows
    names = oi_tables() | {"habits", "filters", "templates", "template_files", "time_entries", "bookmarks", "sprints", "list_rules",
                           "portal_tickets", "ev_cals", "hub_mailboxes"}
    want = {t: set(v) for t, v in undo_rows(cr).items() if t in names}
    for t in ("ev_cals", "hub_mailboxes"):
        want.setdefault(t, set()).update(int(x) for x in cr.get(t) or [])
    out = umz_more_there(c, uid, cr)
    for table, ids in want.items():
        ids = sorted(ids)
        for i in range(0, len(ids), 500):
            p = ids[i:i + 500]
            out.update((table, x[0]) for x in c.execute(f"SELECT id FROM {table} WHERE id IN ({','.join('?' * len(p))})", p).fetchall())
    links = {(int(k[0]), int(k[1])) for t, k in cr.get("parts") or [] if t == "task_links" and isinstance(k, list) and len(k) == 2}
    tids = sorted({x[0] for x in links})
    for i in range(0, len(tids), 500):
        p = tids[i:i + 500]
        out.update(("task_links", (x[0], x[1])) for x in c.execute(
            f"SELECT task_id, list_id FROM task_links WHERE task_id IN ({','.join('?' * len(p))})", p).fetchall() if (x[0], x[1]) in links)
    days = [d for d in cr.get("journal") or [] if isinstance(d, str)]
    for i in range(0, len(days), 500):
        p = days[i:i + 500]
        out.update(("journal", str(x[0])) for x in c.execute(f"SELECT day FROM journal WHERE user_id=? AND day IN ({','.join('?' * len(p))})",
                                                             [uid] + p).fetchall())
    return out


def _umz_undo_rows(c, uid, r):
    """2.611.0 (#4866): the database part of the undo of account import r, shared by umz_undo and its preview (umz_undo_preview runs
    it in a savepoint and rolls it back): everything its numbers come from, so the preview counts exactly like the undo. Neither
    commits nor touches files nor settings. -> (answer, cr, template file paths, area rows removed)."""
    cr = json.loads(r["created"] or "{}")
    since = parse_iso(r["created_at"])
    from .orgimport import oi_undo, oi_undo_final, oi_undo_numbers_kept, oi_undo_plan, oi_undo_preview
    there = _umz_there(c, uid, cr)
    plan = oi_undo_plan(c, cr, since)  # 2.506.0 (#4299): before anything goes: only what is unchanged since and has nothing new below it
    final = oi_undo_final(plan, _UMZ_GONE_AREAS)  # 2.593.0 (#4864): what stays with a finalised document of the import
    nums = len(oi_undo_numbers_kept(c, cr, plan))  # 2.593.0 (#4864, review F7): their office's number counters stay too (oi_undo)
    if nums:
        final.append({"what": N_("Number ranges"), "count": nums})
    n_oi, kept_rows = oi_undo(c, uid, cr, since, plan)  # 2.137.0 (#2344): the areas first (they point at the lists and tasks)
    kept_rows += umz_undo_parts(c, cr, plan, since, uid)  # 2.455.0 (#3469)
    from .umz_more import umz_more_undo
    kept_rows += umz_more_undo(c, uid, cr, since, plan)  # 2.363.4 (#3127): bookmarks, focus sessions, arrangements, bells
    tpl_paths = umz_undo_templates(c, uid, cr, plan)  # 2.464.0 (#3865)
    own_lists = [int(x) for x in cr.get("lists") or []]
    back, kept = imp_undo_split(c, uid, umz_undo_tasks(c, uid, cr), since, cr.get("time_entries") or [])
    n_lists, kept_lists, went = imp_undo_lists(c, uid, own_lists, back, since)
    imp_undo_trash(c, [i for i in back if i not in went], back, r["id"])
    kept_cals = kept_books = 0
    for table, col in (("habits", "user_id"), ("filters", "user_id"), ("templates", "owner_id"), ("ev_cals", "owner_id"),
                       ("books", "owner_id"), ("time_entries", "user_id")):
        part = [int(x) for x in cr.get(table) or []]
        if table not in ("ev_cals", "books"):  # 2.506.0 (#4299)
            part = [x for x in part if plan.goes(table, x)]
        if table in ("ev_cals", "books"):  # 2.272.0 C (#3027): only a calendar / address book nothing was added to or changed in
            sub, mem = ("events", "cal_id") if table == "ev_cals" else ("contacts", "book_id")
            rk = "evcal" if table == "ev_cals" else "address_book"  # 2.924.0 (#5069): shared = a share of its node (no member table)
            go = []
            for x in part:
                rows = c.execute(f"SELECT created_at, updated_at FROM {sub} WHERE {mem}=?", (x,)).fetchall()
                # 2.516.0 (#4366): + its own changed_at (cal_touch / book_touch): an own event / contact moved in since keeps its
                # created_at and updated_at, only the calendar / address book it went to says so
                ch = c.execute(f"SELECT changed_at FROM {table} WHERE id=?", (x,)).fetchone()
                if any(imp_undo_after(y["created_at"], since) or imp_undo_after(y["updated_at"], since) for y in rows) \
                        or (ch is not None and imp_undo_after(ch["changed_at"], since)) \
                        or c.execute("SELECT 1 FROM fs_shares s JOIN fs_nodes n ON n.id=s.node_id WHERE n.kind='ref' AND n.ref_kind=? "
                                     "AND n.ref_id=? AND COALESCE(s.user_id, s.agent_id, 0)!=?", (rk, x, uid)).fetchone():
                    if c.execute(f"SELECT 1 FROM {table} WHERE id=? AND {col}=?", (x, uid)).fetchone():
                        kept_cals += table == "ev_cals"
                        kept_books += table == "books"
                    continue
                go.append(x)
            part = go
        if table == "time_entries" and kept:  # the entries of a task that stays stay with it
            part = [x["id"] for i in range(0, len(part), 500) for x in c.execute(
                f"SELECT id, task_id FROM time_entries WHERE id IN ({','.join('?' * len(part[i:i + 500]))})", part[i:i + 500]).fetchall()
                if x["task_id"] not in kept]
        if table == "books":  # 2.370.4 (#3089) M6: an imported address book goes to the trash with its contacts (op_book_delete)
            umz_undo_books(c, uid, part)
            continue
        for i in range(0, len(part), 500):
            p = part[i:i + 500]
            # 2.272.0 F (#3027, review M6): a time entry billed since is part of an invoice's basis and stays
            c.execute(f"DELETE FROM {table} WHERE id IN ({','.join('?' * len(p))}) AND {col}=?"
                      + (" AND billed_doc_id IS NULL" if table == "time_entries" else ""), p + [uid])
    for day in cr.get("journal") or []:
        j = c.execute("SELECT updated_at FROM journal WHERE user_id=? AND day=?", (uid, day)).fetchone()
        if j and imp_undo_after(j["updated_at"], since):  # 2.506.0 (#4299): written on since the import
            kept_rows += 1
            continue
        c.execute("DELETE FROM journal WHERE user_id=? AND day=?", (uid, day))
    for x in cr.get("journal_add") or []:  # 2.531.0 (#4317) F7: the entry added below a day here, cut off while not written on since
        if not (isinstance(x, list) and len(x) == 4 and isinstance(x[0], str) and isinstance(x[1], int)):
            continue
        j = c.execute("SELECT day, text, mood, mood_enc, updated_at FROM journal WHERE user_id=? AND day=?", (uid, x[0])).fetchone()
        if not j or ts_canon(j["updated_at"]) != ts_canon(x[3]):  # 2.1095.0 (#5306): TIMESTAMPTZ reads canonically, x[3] was written as iso_ms
            kept_rows += bool(j)
            continue
        cur = jr_open(c, uid, j)
        st, sm, se = jr_seal(c, uid, (cur.get("text") or "")[:x[1]], cur.get("mood"))
        c.execute("UPDATE journal SET text=?, mood=?, mood_enc=?, updated_at=? WHERE user_id=? AND day=? AND updated_at=?",
                  (st, sm, se, x[2], uid, x[0], x[3]))
    for mid in cr.get("hub_mailboxes") or []:  # 2.144.5 B (#2410): a mailbox the import set up (not changed since: no password yet)
        # 2.144.5 A2 (#2410, review R7): + still error "password" (saving it in the settings clears that, even without a password)
        gone = c.execute("DELETE FROM hub_mailboxes WHERE id=? AND created_by=? AND secret='' AND error='password'", (int(mid), uid)).rowcount
        if not gone and c.execute("SELECT 1 FROM hub_mailboxes WHERE id=? AND created_by=?", (int(mid), uid)).fetchone():
            kept_rows += 1  # 2.533.0 (#4318) F20: a mailbox set up since (password saved) stays and is counted, not left out silently
    kept_rows += plan.kept_n  # final after undo_trash (oi_undo): a folder that could not go into the trash stays
    out = {"tasks": len(back), "lists": n_lists, "sections": 0, "kept_lists": kept_lists, "kept_tasks": len(kept),
           "kept_cals": kept_cals, "kept_books": kept_books, "kept_rows": kept_rows, "trash_rows": plan.trashed, "trash": True,
           "for_good": umz_areas_tr(oi_undo_preview(there - _umz_there(c, uid, cr), _UMZ_GONE_AREAS)),
           "kept_final": umz_areas_tr(final), "kept_final_docs": len(plan.final)}  # 2.593.0 (#4864): inside kept_rows
    return out, cr, tpl_paths, n_oi


def umz_undo(c, uid, r):
    """Undo of an account import (called by importers.imp_undo after its own checks): everything the run created.
    2.272.0 C (#3027): tasks and lists go into the trash (restorable) instead of being deleted, and only what nobody touched
    since the import: changed tasks, tasks with comments / files / time entries / subtasks added since and lists with such
    tasks, other people's tasks or new project files stay; calendars and address books only go when nothing changed in them.
    2.611.0 (#4866): the rows in _umz_undo_rows (its preview runs the same), here the settings, invitations, commit and files."""
    out, cr, tpl_paths, n_oi = _umz_undo_rows(c, uid, r)
    from .orgimport import oi_undo_files
    cur = usettings(c, uid)
    for k, v in (cr.get("settings") or {}).items():
        if k in UMZ_SETTINGS_ALL and isinstance(v, dict) and cur.get(k) == v.get("new"):  # 2.363.4 (#3127): + the allow list
            uset(c, uid, k, v.get("old") if v.get("old") is not None else "")
    for oid, who in cr.get("org_joins") or []:  # 2.360.2 M (#2561): an invitation not accepted yet goes with the import
        c.execute("DELETE FROM org_joins WHERE org_id=? AND user_id=? AND created_by=?", (int(oid), int(who), uid))
        ojn_drop_later(c, int(oid), int(who), uid)
    c.execute("UPDATE imports SET undone_at=? WHERE id=?", (iso(now_utc()), r["id"]))
    bump(c)
    c.commit()
    oi_undo_files(cr)  # 2.272.0 C (#3027): the files of the tasks stay with them in the trash (the trash run deletes them)
    unlink_files(tpl_paths)  # 2.464.0 (#3865)
    print("account import undo", r["id"], "user", uid, "tasks", out["tasks"], "kept", out["kept_tasks"], "area rows", n_oi,
          "kept rows", out["kept_rows"], "into the trash", out["trash_rows"], flush=True)
    return out


def umz_undo_preview(c, uid, iid):
    """2.585.0 (#4350): what the undo of account import iid would do now, nothing changed (the dialog shows
    it before the confirm, after 30 days the person has worked with the data): the last moment (undo_until), what goes for
    good by area, how many tasks / files, pages, tables and clients go into a trash and how many entries stay. The same
    checks as imp_undo first (own import, not undone, inside the window, oi_undo_check: admin, nothing finalised or locked)."""
    r = c.execute("SELECT * FROM imports WHERE id=? AND user_id=? AND source=?", (iid, uid, UMZ_SOURCE)).fetchone()
    if not r:
        raise Denied(404)
    if r["undone_at"]:
        raise Denied(409, tr("This import was already undone"))
    since = parse_iso(r["created_at"])
    until = umz_undo_until(since)
    if now_utc() > until:
        raise Denied(409, tr("An account import can only be undone within {0} days", ACCOUNT_IMPORT_UNDO_DAYS))
    from .orgimport import oi_undo_check
    oi_undo_check(c, uid, json.loads(r["created"] or "{}"), r["created_at"])
    # 2.611.0 (#4866): the undo itself in a savepoint, rolled back: its numbers are the preview's (no second way of counting)
    write_lock(c, f"imp-undo:{int(iid)}")  # review 2.611: the probe and the real undo (importers.imp_undo) never run side by side
    got = []
    real = c.__dict__.get("commit"), c.__dict__.get("rollback")

    def refuse():
        raise RuntimeError("the undo preview must not end the transaction")
    c.commit = c.rollback = refuse  # a helper that commits would make the preview the undo: refused, the savepoint rolls back
    try:
        with c.savepoint():
            got.append(_umz_undo_rows(c, uid, r)[0])
            raise _UmzDryRun
    except _UmzDryRun:
        pass
    finally:
        for k, v in zip(("commit", "rollback"), real):
            if v is None:
                c.__dict__.pop(k, None)
            else:
                setattr(c, k, v)
    p = got[0]
    return {"id": r["id"], "at": r["created_at"], "undo_until": iso(until), "for_good": p["for_good"], "trash_tasks": p["tasks"],
            "trash_rows": p["trash_rows"], "kept_tasks": p["kept_tasks"], "kept_rows": p["kept_rows"], "lists": p["lists"],
            "kept_lists": p["kept_lists"], "kept_cals": p["kept_cals"], "kept_books": p["kept_books"],
            # 2.593.0 (#4864): the finalised documents stay with their client, files ... (named by area, inside kept_rows)
            "kept_final": p["kept_final"], "kept_final_docs": p["kept_final_docs"]}


class _UmzDryRun(Exception):
    """2.611.0 (#4866): ends the preview's savepoint (rolled back)."""


# ---------------------------------------------------------------- routes (people only)
def _view(uid, iid, st):
    lost = False
    if st.get("state") in ("checking", "running") and not _busy(uid):
        st = _st(uid, iid) or st  # 2.307.1 (CI): the thread may have written its last state and ended after st was read
        # #3506: the second look only after that fresh read; a row ending between two looks at an old st said "interrupted"
        lost = st.get("state") in ("checking", "running") and not _busy(uid) and int(uid) not in _UMI_START
    out = {"id": iid, "state": st.get("state"), "size": st.get("size"), "received": st.get("received"), "name": st.get("name", "")}
    if lost:
        out["state"] = "failed"
        out["error"] = tr("The import was interrupted. Please start it again.")
    if st.get("state") == "key" and st.get("key_error"):
        out["error"] = tr("The recovery key does not open this export. Attempts left: {0}", UMZ_KEY_TRIES - int(st.get("tries") or 0))
    for k in ("preview", "error", "progress", "result"):
        if st.get(k) is not None and k not in out:
            out[k] = st[k]
    if "error" in out:  # 2.448.0 (#3765): translated for who asks; a state written before keeps its text
        out["error"] = tr_stored(out["error"])
    if out.get("preview"):  # 2.454.0 (#3808)
        pv = out["preview"]
        out["preview"] = {**pv, "not_taken": umz_areas_tr(pv.get("not_taken")), "taken_areas": umz_areas_tr(pv.get("taken_areas"))}
    if out.get("result"):
        res = out["result"]
        out["result"] = {**res, "warnings": [{**x, "text": tr_stored(x["text"])} for x in res.get("warnings") or []]}
        if res.get("stopped"):
            out["result"]["stopped"] = tr_stored(res["stopped"])
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
        try:
            _thread(uid, umz_check, iid, bool(g.user["is_admin"]), iid=iid, state={"state": "checking"})
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


@app.get("/api/imports/<int:iid>/undo-plan")
def umz_undo_plan_get(iid):
    """2.585.0 (#4350): what the undo of my account import iid would take back (umz_undo_preview), people only."""
    umz_person()
    if hit_limit(f"import:{me()}", IMPORT_RATE, 600):  # 2.585.0 (#4350, review 2): the plan reads every imported row, rate limited like a preview
        raise Denied(429, tr("Too many imports, please wait a few minutes"))
    return jsonify(umz_undo_preview(db(), me(), iid))


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
    # 2.269.0 D (#3046): this export imported by now (another tab, another upload of the same file) -> 409 unless the
    # person saw the preview's warning and goes on anyway (again: true); importing it twice by mistake creates nothing.
    # 2.362.3 (#3098): the same source, and going on takes over only what the chosen target does not have yet
    if b.get("again") is not True and umz_earlier(c, uid, st.get("src") or "", st.get("export_id") or ""):
        c.rollback()
        return err(tr("This export was imported already. Confirm that you want to import it again: what is already in the selected place is skipped."), 409)
    tg = b.get("target", "private")
    org = None
    if tg != "private":
        if not isinstance(tg, int) or isinstance(tg, bool):
            return err(tr("Invalid value: {0}", "target"))
        _need_org_admin(c, tg)  # 404 not a member, 403 not its admin: never into somebody else's organisation
        org = tg
    picks = {}
    for em, v in (b.get("people") or {}).items() if isinstance(b.get("people"), dict) else ():
        e = umz_pkey(em)
        if e and isinstance(v, dict):
            picks[e] = {"share": v.get("share") is True, "invite": v.get("invite") is True, "email": _email(v.get("email"))
                        or (_email(em) if "@" in str(em) else ""), "login": _txt(v.get("login"), 64)}  # 2.278.0 B (#3094): a user name
            if "role" in v:  # 2.278.0 A (#3095): the role the admin confirmed (unknown = member; none sent = the file's)
                picks[e]["role"] = umz_role(v["role"])
    c.rollback()
    try:
        _thread(uid, umz_run, iid, {"org": org, "people": picks, "can_invite": bool(g.user["is_admin"])}, iid=iid,
                state={"state": "running", "progress": {"done": 0, "total": 1}, "target": org})
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
    try:
        okey = rck_parse(body().get("recovery_key"))  # 2.138.0 C (#1972): ("secret" | "key", 32 bytes), umz_org_decrypt
    except ValueError:
        return err(tr("This is not a recovery key (52 characters A-Z and 2-7, in groups of 4)."))
    try:
        _thread(uid, umz_unlock, iid, okey, bool(g.user["is_admin"]), iid=iid, state={"state": "checking"})
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
    bgj_drop(UMZ_KINDS, user_id=uid)  # 2.370.3 (review 6): a step still waiting for the worker can be cancelled
    if st.get("state") in ("checking", "running") and _busy(uid):
        return err(tr("An import is already running"), 409)
    _drop(uid, iid)
    return jsonify(ok=True)

