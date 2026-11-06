"""2.577.0 C (#4466): named document addresses (doc_mail rows with an aid) next to the general one.

A documents space (a person's own documents or an organisation's) has the general address (doc_mail aid '' -- "General",
docs/maillink.py ml_token_new; the area sorting of #4433 applies to it) and up to DMN_MAX named ones of each person: a
name ("Bank statements"), a fixed target folder below the documents folder (NULL = the documents folder itself), fixed
tags, active on / off. Same plus address scheme (integrations/mail.py MAIL_TOKEN_RE), the hourly budget per address
(maillink.py ml_budget, counted on the row by its token). A new token (renew) makes the old address invalid at once.

Every delivery is checked with the person's rights at that moment (docs/ingest.py docs_mail_import -> dmn_dest): the
target folder gone / in the trash / locked / no longer editable for the person -> the document lands in the documents
folder of the space (the inbox of the area) with the tag GONE_TAG, and the address shows the reason in the settings.
The settings routes: docs/mailnamed.py."""
import json
import secrets

from ..core.errors import Denied
from ..core.i18n import N_, lang, tr
from ..files.fslock import fl_is_locked
from ..files.store import fs_chain, fs_deleted, fs_role
from . import store as S

DMN_MAX = 20          # named addresses per person and documents space
DMN_NAME_MAX = 60
DMN_TAGS_MAX = 10
DMN_TAG_MAX = 40
GENERAL = N_("General")
GONE_MSG = N_("The target folder is no longer open to you: documents land in the documents folder")
GONE_TAG = N_("Target folder unavailable")
OFF_MSG = N_("Switched off: e-mails to this address are refused")


def dmn_token():
    """A new address token (the shape of maillink.py ml_token_new: 'd' + 19 characters, plus address safe)."""
    return "d" + secrets.token_urlsafe(14).replace("-", "x").replace("_", "y")


def dmn_tags(raw):
    """The tags of an address from a request ([names] or "a, b") -> a clean list; ValueError on a wrong type."""
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        raw = raw.split(",")
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        raise ValueError("tags")
    out = []
    for x in raw:
        t = " ".join(x.replace(",", " ").split())[:DMN_TAG_MAX]
        if t and t.casefold() not in {o.casefold() for o in out}:
            out.append(t)
    if len(out) > DMN_TAGS_MAX:
        raise ValueError("tags")
    return out


def dmn_row_tags(r):
    try:
        t = json.loads(r["tags"] or "[]")
    except (ValueError, TypeError):
        return []
    return [str(x) for x in t if isinstance(x, str)] if isinstance(t, list) else []


def dmn_folder(c, uid, oid, pid):
    """(folder id | None, readable path) of target folder pid of the documents space oid (None: uid's own) with uid's
    rights now; Denied 409 when it is gone, in the trash, outside the documents folder, locked or not editable for uid.
    pid falsy or the documents folder itself -> (None, "")."""
    if not pid:
        return None, ""
    root = S.root_id(c, S.doc_ws(oid, uid))
    if root and int(pid) == int(root):
        return None, ""
    chain = fs_chain(c, int(pid))
    n = chain[0] if chain else None
    ok = (n is not None and root and n["kind"] == "folder" and not fs_deleted(chain) and n["org_id"] == oid
          and (oid or n["owner_id"] == uid) and any(x["id"] == root for x in chain[1:]))
    if not ok or fl_is_locked(c, int(pid)) or fs_role(c, int(pid), uid, chain=chain) not in ("owner", "edit"):
        raise Denied(409, tr(GONE_MSG))
    k = next(i for i, x in enumerate(chain) if x["id"] == root)
    return int(pid), " / ".join(x["name"] for x in reversed(chain[:k]))


def dmn_dest(c, r):
    """For docs_mail_import: where a mail to doc_mail row r goes -> (parent id | None, tags, gone). Only for a named row
    (aid set); call after the membership check. gone = the target folder is not reachable now (the documents folder
    instead, tagged GONE_TAG in the person's language)."""
    tags = dmn_row_tags(r)
    try:
        pid, _p = dmn_folder(c, r["user_id"], r["org_id"], r["target_folder"])
        return pid, tags, False
    except Denied:
        t = tr(GONE_TAG, lg=lang(c, r["user_id"]))
        return None, tags + ([t] if t not in tags else []), True
