"""2.642.0 (#4772): the customer link of a sign-off for clients without an account, on the approval links of
office/signoff.py (kind video; no table and no token way of its own) and the customer page of videos/review.py.

- Several live links per sign-off (each with its own expiry, each switched off on its own); at most VDL_LIVE_MAX at once.
- show_old (ticked when the link is made): the client may also open the older versions (?v=<n>), read-only: their player and
  the client's comments there with the team's answers; comments and the decision only on the newest version.
- A new version carries a decided link on (vdl_carry): the decided record stays untouched (name, time, the signer's data =
  the history), a new open record of the same link takes over the token; the client sees the new version at the same URL.
  The undo of "New version" (it has no comments yet) takes the carried record back (vdl_uncarry).
- The client types the name once: a cookie scoped to the link's own path (HttpOnly, SameSite Strict) fills the name in the
  comment form and the decision form; it holds only that name.
Nothing here shows the task, the project, other sign-offs or contacts: the page reads the one review of the link."""
import base64
import html

from flask import request

from ..core.db import iso, now_utc, parse_iso
from ..core.i18n import tr
from ..core.pg import insert_id

VDL_LIVE_MAX = 10          # live client links per sign-off at once
VDL_COOKIE = "kgn"         # the client's name on this link (path = the link)
VDL_NAME_MAX = 120
VDL_COOKIE_DAYS = 180


def vdl_live(s, now=None):
    return s["state"] == "open" and not s["revoked_at"] and not (s["expires_at"] and parse_iso(s["expires_at"]) <= (now or now_utc()))


def vdl_live_count(c, r):
    rows = c.execute("SELECT state, revoked_at, expires_at FROM office_signoffs WHERE video_id=? AND kind='video' AND org_id IS NOT DISTINCT FROM ? "
                     "AND state='open' AND revoked_at IS NULL", (r["id"], r["org_id"])).fetchall()
    now = now_utc()
    return sum(1 for s in rows if vdl_live(s, now))


def vdl_carry(c, r, nid):
    """A new version nid of review r: each decided link of it that still runs (not switched off, not expired) goes on with
    the same token as a new open record; the decided one keeps its data and gets a token hash nobody can look up. The
    caller holds the review's write lock and commits. -> the number carried on."""
    now = now_utc()
    rows = c.execute("SELECT * FROM office_signoffs WHERE video_id=? AND kind='video' AND org_id IS NOT DISTINCT FROM ? "
                     "AND state IN ('accepted', 'declined') AND revoked_at IS NULL AND token_hash NOT LIKE 'carried:%' ORDER BY id",
                     (r["id"], r["org_id"])).fetchall()
    ts, n = iso(now), 0
    for s in rows:
        if s["expires_at"] and parse_iso(s["expires_at"]) <= now:
            continue
        c.execute("UPDATE office_signoffs SET token_hash=? WHERE id=?", (f"carried:{s['id']}:{s['token_hash']}", s["id"]))
        insert_id(c, "INSERT INTO office_signoffs(org_id, kind, video_id, title, token_hash, token, expires_at, state, doc_hash, created_by, "
                     "created_at, show_old, carried_from, carried_ver) VALUES(?,?,?,?,?,?,?,'open',?,?,?,?,?,?)",
                  (s["org_id"], "video", r["id"], (r["title"] or "")[:300], s["token_hash"], s["token"], s["expires_at"], s["doc_hash"],
                   s["created_by"], ts, s["show_old"] or 0, s["id"], nid))
        n += 1
    return n


def vdl_uncarry(c, vid, nid):
    """The undo of version nid: a link it carried on and that is still open and on gives the token back to its decided
    record (the client sees that decision again); one switched off meanwhile stays off. The caller commits."""
    rows = c.execute("SELECT id, token_hash, carried_from FROM office_signoffs WHERE video_id=? AND kind='video' AND carried_ver=? "
                     "AND state='open' AND revoked_at IS NULL AND carried_from IS NOT NULL", (vid, nid)).fetchall()
    for s in rows:
        c.execute("DELETE FROM office_signoffs WHERE id=?", (s["id"],))
        c.execute("UPDATE office_signoffs SET token_hash=? WHERE id=? AND token_hash=?",
                  (s["token_hash"], s["carried_from"], f"carried:{s['carried_from']}:{s['token_hash']}"))
    return len(rows)


# ---------------------------------------------------------------- the customer page
def vdl_shown(c, s, versions):
    """(the version to show, is it an older one) for link s: ?v=<n> only when the link shows the older versions."""
    newest = versions[-1]
    want = request.args.get("v") or ""
    if not (s["show_old"] and want.isdigit() and len(want) < 7):
        return newest, False
    for v in versions[:-1]:
        if v["n"] == int(want):
            return v, True
    return newest, False


def vdl_old_shown(c, s):
    from .review import vdr_versions
    vs = vdr_versions(c, s["video_id"]) if s["video_id"] else []
    return bool(vs) and vdl_shown(c, s, vs)[1]


def vdl_nav(versions, shown, lg, token, prefix):
    """The version list of a link that shows the older versions (newest last in the data, first on the page)."""
    e = html.escape
    items = []
    for v in reversed(versions):
        label = tr("Version {0}", v["n"], lg=lg)
        if v is versions[-1]:
            label += " · " + tr("newest", lg=lg)
        if v["id"] == shown["id"]:
            items.append(f'<li><b aria-current="page">{e(label)}</b></li>')
        else:
            href = f"{prefix}{e(token)}" + ("" if v is versions[-1] else f"?v={v['n']}")
            items.append(f'<li><a href="{href}">{e(label)}</a></li>')
    return f'<nav class="vdr-vers" aria-label="{e(tr("Versions", lg=lg))}"><ul>{"".join(items)}</ul></nav>'


def vdl_old_note(lg, token, prefix):
    e = html.escape
    return (f'<p class="vdr-hint">{e(tr("This is an older version. Comments and the decision belong to the newest version.", lg=lg))} '
            f'<a href="{prefix}{e(token)}">{e(tr("Go to the newest version", lg=lg))}</a></p>')


def vdl_name():
    """The client's name remembered on this link ('' = none)."""
    raw = request.cookies.get(VDL_COOKIE) or ""
    if not raw or len(raw) > 4 * VDL_NAME_MAX:
        return ""
    try:
        v = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return ""
    v = " ".join("".join(ch for ch in v if ord(ch) >= 32).split())
    return v[:VDL_NAME_MAX] if len(v) >= 2 else ""


def vdl_name_set(resp, token, prefix, name):
    """Remembers the name for this link only (its path); nothing else is stored on the client's device."""
    if len(name or "") < 2:
        return resp
    secure = request.is_secure or request.headers.get("X-Forwarded-Proto", "") == "https"
    val = base64.urlsafe_b64encode(name[:VDL_NAME_MAX].encode("utf-8")).decode().rstrip("=")
    resp.set_cookie(VDL_COOKIE, val, max_age=VDL_COOKIE_DAYS * 86400, httponly=True, samesite="Strict", secure=secure, path=prefix + token)
    return resp
