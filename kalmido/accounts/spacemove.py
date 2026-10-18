"""2.96.0 (#1941): the shared rules for moving data between the private space and an organisation (both ways).

Every kind of data that moves between workspaces (files and folders, wiki pages, tables ...) has its own route
(POST …/move-space, {dry: 1} = only the check) but the same rules, kept here:
- the target: smv_target -- "private" / None / "" / 0 = the private space, else an organisation the person is a member of
  (409 otherwise; never a hidden personal office, never somebody else's organisation);
- agents never move data between workspaces (an agent belongs to ONE workspace, agents.org_id; 403);
- the person needs the right to write in the source (the module's own check) AND in the target (member of the organisation;
  the private space is always the person's own);
- the answer of a dry run: smv_answer(notes, block, **extra) = {notes: [text], block: text | None, …} -- the dialog
  (static/js/spacemove.js) lists the notes and refuses while block is set.
Without an organisation there is no other workspace: the routes answer 409 (smv_target) and the client hides the action.
"""
from flask import g, has_request_context

from ..core.access import Denied
from ..core.i18n import tr
from .orgs import user_orgs

SMV_MAX = 2000  # objects per move (a folder with everything in it counts its content)


def smv_refuse_agent():
    """Agents never move data across the boundary of their workspace (403)."""
    u = getattr(g, "user", None) if has_request_context() else None
    if u is not None and "kind" in u.keys() and u["kind"] == "agent":
        raise Denied(403, tr("Agents cannot move data to another workspace"))


def smv_target(c, uid, v):
    """The target workspace a client sent: None = private, else the id of an organisation uid is a member of (409)."""
    if v in (None, "", 0, "0", "private"):
        return None
    s = str(v)
    if s.startswith("org:"):
        s = s[4:]
    try:
        oid = int(s)
    except (TypeError, ValueError):
        raise Denied(400, tr("Invalid value: {0}", "to")) from None
    if oid not in user_orgs(c, uid):
        raise Denied(409, tr("You are not a member of this organisation"))
    return oid


def smv_same(src_org, to):
    """409 when source and target are the same workspace (nothing to move)."""
    if (src_org or None) == (to or None):
        raise Denied(409, tr("This is already in that workspace"))


def smv_answer(notes=(), block=None, **extra):
    """The answer of a dry run (and the base of a real move's answer)."""
    out = {"notes": [n for n in notes if n], "block": block or None}
    out.update(extra)
    return out
