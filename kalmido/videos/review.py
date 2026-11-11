"""2.99.1 A (#1959): video sign-off with comments at a timecode (tables video_reviews / video_versions; the comments: 2.981.0
#5273 rows of the comments' core obj_comments, kind 'video', read here in their old shape through VDC).

Kalmido stores no video: a review holds links only -- Vimeo, YouTube (also unlisted, youtu.be), a direct video file over
https (MP4 / WebM / MOV, e.g. a Nextcloud / NAS / Dropbox file link); anything else is a "link without time control" (it
opens in a new tab, its comments carry no timecode). 2.633.0 (#4777): audio likewise -- a direct audio file over https (MP3,
M4A / AAC, WAV, OGG / Opus, FLAC; provider "audio", recognised by the file name, nothing fetched) in the browser's <audio> player.
Each new link is a new version (v1, v2 ...); the comments stay at their version. A review hangs at a task, a project list or a client (after a move to the other workspace: at nothing).
Security: only https; the provider is recognised here (host whitelist) and the video id checked strictly -- the embed URL
is built from the id, never from the pasted URL (vdr_embed). The app loads no script of a provider: the player is driven
through its postMessage protocol (static/js/videorev.js, static/pubvideo.js). Rights like the neighbours: who sees the
task / list (full roles) / client sees and comments the review (viewers may comment, like task comments); changing it,
new versions, the customer link, moving and deleting need the right to write there. Agents: not through these routes
(their API: videos/v1.py, part C); private = owner_id. Texts are stored plain like the task comments.
The customer link is an approval link of office/signoff.py (kind video): the customer page shows the newest version, the
customer's own comments and the team's answers to them (the team's other comments stay internal), takes comments with a
timecode (POST /s/q/<token>/comments) and "Approve" / "Request changes".
Functions for the agents' API (part C): vdr_need, vdr_dict, vdr_rows, vdr_comment_add, vdr_parse."""
import csv
import hashlib
import hmac
import html
import io
import re
from urllib.parse import parse_qs, quote, urlencode, urlsplit, urlunsplit

from flask import Response, jsonify, redirect, request

from ..core.config import app, PUBLIC_URL
from ..collab.comments import lang_of, push_later  # 2.367.5 (#2980); 2.370.3 (#2760): push_later
from ..core.access import Denied, FULL_ROLES, WRITE_ROLES, acx_org_ok, list_role, need_feat, task_visible  # 2.623.0 (#4765): need_feat
from ..office.signoff import sig_people  # 2.266.0 (#2965)
from .vdlink import VDL_LIVE_MAX, vdl_carry, vdl_live_count, vdl_name, vdl_name_set, vdl_nav, vdl_old_note, vdl_shown, vdl_uncarry  # 2.642.0 (#4772)
from ..core.db import body, db, err, iso, now_utc
from ..core.retention import ret_on, ret_trash_days  # 2.272.0 A (#3026); 2.549.0 (#4536): ret_trash_days
from ..core.i18n import N_, csv_dialect, tr
from ..core.pg import insert_id, write_lock
from ..accounts.session import _accept_lang, me, rate_ip
from ..accounts.login import auth_key
from ..core.errors import BadInput
from ..api.common import hit_limit  # 2.149.0 G (#2517): pulled up from functions
from ..team.clients import client_rows  # 2.369.5 (#2517): pulled up from functions
from ..office.model import office_role  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgroles import need_org_say, org_sees_all, org_writes  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgs import is_org_admin, user_orgs  # 2.369.5 (#2517): pulled up from functions; 2.549.0 (#4536): user_orgs
from ..collab.comments import user_names  # 2.369.5 (#2517): pulled up from functions
from ..core.serializers import csv_cell  # 2.369.5 (#2517): pulled up from functions
from ..office.signoff import sig_create, sig_expiry, sig_public, SIG_PREFIX, sig_lang, sig_open  # 2.369.5 (#2517): pulled up from functions
from ..lists.public import public_links_on, pub_gone, pub_headers, pub_html, pub_limited  # 2.369.5 (#2517): pulled up from functions
from ..accounts.orgout import oo_denied, oo_into_note, org_out, org_out_ok  # 2.369.5 (#2517): pulled up from functions
from ..accounts.spacemove import smv_answer, smv_refuse_agent, smv_same, smv_target  # 2.369.5 (#2517): pulled up from functions
from .vdmedia import vdm_body, vdm_files_ok, vdm_has_files, vdm_marks, vdm_media, vdm_need_movable, vdm_pos, vdm_pos_dict, vdm_pos_text, vdm_send, vdm_version_row  # 2.641.0 (#4769)
from .vdmedia import vdm_pub_send  # 2.658.0 (#5015)
from .vdmedia import vdm_pub_pos, vdm_pub_stage  # 2.764.0 (#5040)
from ..core.writes import obj_restore, obj_trash  # 2.947.0 (#5367): the core's trash (videos/vdkern.py)
from ..core.access import live_sql, trash_sql  # 2.947.0 (#5367); 2.981.0 (#5273): live_sql
from ..core.objcomments import ocm_add, ocm_edit, ocm_kind, ocm_restore, ocm_trash, ocm_video_cols as vdc_cols  # 2.981.0 (#5273): the comments' core
from ..core.objparts import part_write  # 2.981.0 (#5273): the lock of a comment (done)

VDR_URL_MAX, VDR_TITLE_MAX, VDR_BODY_MAX, VDR_NAME_MAX = 2000, 200, 2000, 120
VDR_AT_MAX = 86400.0                     # a timecode lies within 24 hours
VDR_PUB_RATE, VDR_PUB_HOUR = 10, 60      # customer comments per client address and minute / per link and hour
VDR_MEDIA_LINK_RATE = 600               # 2.658.0 (Fable review): requests for one link's audio file per minute over all addresses
VDR_MEDIA_RATE = 240                     # 2.658.0 (#5015): requests for the customer page's audio file per client address and minute (seeking = ranges)
VDR_STATES = ("open", "approved", "changes")
VDR_KIND = "video_review"  # 2.947.0 (#5367): the kind of the core's trash (videos/vdkern.py)
VDR_FILE_RE = re.compile(r"\.(mp4|m4v|webm|mov)$", re.I)
# 2.633.0 (#4777): audio over a direct https link -- recognised by the file name only (Kalmido fetches no foreign URL), played by
# the browser's own <audio> element (no script, no SoundCloud / Spotify); comments at a second like a video file
VDR_AUDIO_RE = re.compile(r"\.(mp3|m4a|aac|wav|ogg|oga|opus|flac)$", re.I)
VDR_YT_RE = re.compile(r"[A-Za-z0-9_-]{11}")
VDR_VIMEO_RE = re.compile(r"[0-9]{1,12}")
VDR_VIMEO_H_RE = re.compile(r"[0-9a-f]{6,20}")
VDR_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be", "youtube-nocookie.com", "www.youtube-nocookie.com"}
VDR_VIMEO_HOSTS = {"vimeo.com", "www.vimeo.com", "player.vimeo.com"}
VDR_FRAME = {"youtube": "https://www.youtube-nocookie.com", "vimeo": "https://player.vimeo.com"}  # the player origins (CSP frame-src)
VDR_HTTPS = N_("Please paste a link that starts with https://")
VDR_NO_TIME = N_("This link has no time control: it opens in a new tab, comments get no timecode.")
VDR_NONE = N_("Kalmido stores no videos: paste a link from Vimeo, YouTube (also unlisted) or a direct video file (MP4, WebM, MOV) over https.")
VDC_KIND = "video"  # 2.981.0 (#5273, stage Q4b): the comments of a review are rows of obj_comments (ref_id = the review)


VDC = f"(SELECT {vdc_cols()} FROM obj_comments k WHERE k.kind='{VDC_KIND}') video_comments"  # read like the old table
VDC_SEL = "SELECT * FROM " + VDC  # + " WHERE ..." (the old table's columns)


# ---------------------------------------------------------------- links: provider, embed URL
def vdr_parse(raw):
    """A pasted link -> {url, provider, embed_id}; BadInput for anything but a clean https URL. Providers: vimeo, youtube
    (the video id checked by a strict pattern), file (the path ends in a video file name), audio (2.633.0 #4777: the path ends
    in an audio file name), link (no time control)."""
    url = raw.strip() if isinstance(raw, str) else ""
    if not url or len(url) > VDR_URL_MAX or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
        raise BadInput(tr(VDR_HTTPS))
    try:
        u = urlsplit(url)
        host = (u.hostname or "").lower()
        port = u.port
    except ValueError:
        raise BadInput(tr(VDR_HTTPS)) from None
    if u.scheme.lower() != "https" or not host or u.username or u.password or "\\" in url:
        raise BadInput(tr(VDR_HTTPS))
    seg = [s for s in u.path.split("/") if s]
    q = parse_qs(u.query)
    if host in VDR_YT_HOSTS and port in (None, 443):  # 2.99.1 review L6: an explicit :443 is the same host
        vid = ""
        if host.endswith("youtu.be"):
            vid = seg[0] if seg else ""
        elif seg[:1] == ["watch"]:
            vid = (q.get("v") or [""])[0]
        elif len(seg) >= 2 and seg[0] in ("embed", "shorts", "live", "v"):
            vid = seg[1]
        if VDR_YT_RE.fullmatch(vid):
            return {"url": url, "provider": "youtube", "embed_id": vid}
    if host in VDR_VIMEO_HOSTS and port in (None, 443):
        ids = [i for i, s in enumerate(seg) if VDR_VIMEO_RE.fullmatch(s)]
        if ids and (host != "player.vimeo.com" or seg[:1] == ["video"]):
            i = ids[0]
            if "video" in seg[:-1] and VDR_VIMEO_RE.fullmatch(seg[seg.index("video") + 1]):  # review L6: /showcase/1/video/2 -> 2
                i = seg.index("video") + 1
            h = (q.get("h") or [""])[0] or (seg[i + 1] if i + 1 < len(seg) else "")
            return {"url": url, "provider": "vimeo", "embed_id": seg[i] + (":" + h if VDR_VIMEO_H_RE.fullmatch(h) else "")}
    kind = "file" if VDR_FILE_RE.search(u.path) else "audio" if VDR_AUDIO_RE.search(u.path) else ""
    if kind:
        if host == "dropbox.com" or host.endswith(".dropbox.com"):  # a Dropbox share page (dl=0) -> the file itself (raw=1)
            qs = [(k, v) for k, vs in q.items() for v in vs if k not in ("dl", "raw")] + [("raw", "1")]
            url = urlunsplit((u.scheme, u.netloc, u.path, urlencode(qs), ""))
        return {"url": url, "provider": kind, "embed_id": ""}
    return {"url": url, "provider": "link", "embed_id": ""}


def vdr_embed(v, origin=None):
    """The player URL of a version (vimeo / youtube: built from the checked id; file / audio: the file link itself), or None."""
    p, e = v["provider"], v["embed_id"] or ""
    if p == "youtube" and VDR_YT_RE.fullmatch(e):
        return (f"{VDR_FRAME['youtube']}/embed/{e}?enablejsapi=1&rel=0&playsinline=1"
                + (f"&origin={quote(origin, safe='')}" if origin else ""))
    if p == "vimeo":
        vid, _, h = e.partition(":")
        if VDR_VIMEO_RE.fullmatch(vid) and (not h or VDR_VIMEO_H_RE.fullmatch(h)):
            return f"{VDR_FRAME['vimeo']}/video/{vid}?" + (f"h={h}&" if h else "") + "dnt=1&playsinline=1"
    if p in ("file", "audio"):  # 2.633.0 (#4777): audio
        if p == "audio" and v["file_name"]:  # 2.658.0 (#5015): an audio file of the file store -> the route of its bytes (None: gone)
            return f"/api/videos/{v['review_id']}/versions/{v['id']}/file" if v["file_id"] else None
        return v["url"]
    return None


def vdr_at(v):
    """A timecode from the client: seconds (number) or "h:mm:ss" / "mm:ss" text -> seconds (one decimal) | None; BadInput."""
    if v in (None, ""):
        return None
    if isinstance(v, bool):
        raise BadInput(tr("Invalid value: {0}", "at_sec"))
    if isinstance(v, str):
        s = v.strip()
        if not re.fullmatch(r"\d{1,5}(:\d{1,2}){0,2}(\.\d)?", s):
            raise BadInput(tr("Invalid value: {0}", "at_sec"))
        n = 0.0
        for part in s.split(":"):
            n = n * 60 + float(part)
        v = n
    if not isinstance(v, (int, float)) or v != v or v < 0 or v > VDR_AT_MAX:
        raise BadInput(tr("Invalid value: {0}", "at_sec"))
    return round(float(v), 1)


def vdr_tc(sec):
    """Seconds -> "mm:ss" / "h:mm:ss" (the exports and the customer page)."""
    if sec is None:
        return ""
    s = int(sec)
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}" if s >= 3600 else f"{s // 60:02d}:{s % 60:02d}"


def vdr_clean(v, mx):
    v = "".join(ch for ch in (v if isinstance(v, str) else "").replace("\r", "") if ch == "\n" or ord(ch) >= 32)
    return v.strip()[:mx]


# ---------------------------------------------------------------- rights
def vdr_is_agent(c, uid):
    r = c.execute("SELECT kind FROM users WHERE id=?", (uid,)).fetchone()
    return bool(r) and (r["kind"] or "user") == "agent"


def vdr_client_ok(c, uid, cid):
    return any(x["id"] == cid for x in client_rows(c, uid))


def rg4_client_write(c, uid, cid):
    """2.122.4 A (#2215 L9): change / delete / customer link of a review at a client, like the office's own routes: an
    organisation's client needs an office role there (admin | member), a private client is its creator's (seeing the
    client alone, e.g. an instance admin's overview, is not enough)."""
    cl = c.execute("SELECT org_id, created_by FROM clients WHERE id=?", (cid,)).fetchone()
    if not cl:
        return False
    return office_role(c, uid, cl["org_id"]) in ("admin", "member") if cl["org_id"] else cl["created_by"] == uid


def vdr_may(c, uid, r, write=False, api=False):
    """May person uid see (write: change) review r? The task / list / client it hangs at decides, else the workspace.
    2.99.1 C (#1959): api = the REST API (videos/v1.py): an agent there sees only reviews at a task / list shared with it."""
    if not uid or not acx_org_ok(c, uid, r["org_id"]):
        return False
    if vdr_is_agent(c, uid) and not (api and (r["task_id"] or r["list_id"])):
        return False
    if not vdm_files_ok(c, uid, r["id"]):  # 2.641.0 (#4769): who may not see a file of an image / PDF version sees no review
        return False
    if r["task_id"]:
        t = c.execute("SELECT deleted_at FROM tasks WHERE id=?", (r["task_id"],)).fetchone()
        return bool(t) and not t["deleted_at"] and task_visible(c, r["task_id"], uid, write=write, full=True)
    if r["list_id"]:
        return list_role(c, r["list_id"], uid) in (WRITE_ROLES if write else FULL_ROLES)
    if r["client_id"]:
        return vdr_client_ok(c, uid, r["client_id"]) and (not write or rg4_client_write(c, uid, r["client_id"]))
    if r["org_id"] is None:
        return r["owner_id"] == uid
    return org_sees_all(c, uid, r["org_id"]) and (not write or org_writes(c, uid, r["org_id"]))  # 2.143.0 A (#2151)


def vdr_need(c, vid, write=False, deleted=False):
    """The review row for the person; 404 when they may not see it (or it is (not) in the trash), 403 read-only."""
    r = c.execute("SELECT * FROM video_reviews WHERE id=?", (vid,)).fetchone() if isinstance(vid, int) and 0 < vid < 2 ** 62 else None
    uid = me()
    if not r or bool(r["deleted_at"]) != deleted or not vdr_may(c, uid, r):
        raise Denied(404)
    if write and not vdr_may(c, uid, r, write=True):
        raise Denied(403)
    return r


def vdr_target(c, uid, b):
    """(org_id, task_id, list_id, client_id) of a new review's place {task_id | list_id | client_id}; the person must be
    allowed to write there (a client: see it); a list with the lock (end-to-end) is refused (its texts are encrypted)."""
    keys = [k for k in ("task_id", "list_id", "client_id") if b.get(k) not in (None, "", 0)]
    if len(keys) != 1 or isinstance(b[keys[0]], bool) or not isinstance(b[keys[0]], int):
        raise BadInput(tr("Invalid value: {0}", "task_id / list_id / client_id"))
    k, i = keys[0], b[keys[0]]
    if k == "task_id":
        t = c.execute("SELECT t.list_id, t.deleted_at, l.org_id, l.e2e FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=?", (i,)).fetchone()
        if not t or t["deleted_at"] or not task_visible(c, i, uid, full=True):
            raise Denied(404)
        if not task_visible(c, i, uid, write=True):
            raise Denied(403)
        if t["e2e"] is not None:
            raise Denied(409, tr("Not available in a locked project"))
        return t["org_id"], i, None, None
    if k == "list_id":
        l = c.execute("SELECT org_id, e2e FROM lists WHERE id=?", (i,)).fetchone()
        role = list_role(c, i, uid) if l else None
        if role not in FULL_ROLES:
            raise Denied(404)
        if role not in WRITE_ROLES:
            raise Denied(403)
        if l["e2e"] is not None:
            raise Denied(409, tr("Not available in a locked project"))
        return l["org_id"], None, i, None
    if not vdr_client_ok(c, uid, i):
        raise Denied(404)
    if not rg4_client_write(c, uid, i):  # 2.122.4 A (#2215 L9)
        raise Denied(403)
    return c.execute("SELECT org_id FROM clients WHERE id=?", (i,)).fetchone()["org_id"], None, None, i


# ---------------------------------------------------------------- reading
def vdr_versions(c, vid):
    return c.execute("SELECT * FROM video_versions WHERE review_id=? ORDER BY n", (vid,)).fetchall()


def vdr_version_dict(v):
    # 2.641.0 (#4769): kind video | image | pdf; an image / PDF: its file of the file store and the route of its bytes
    kind = v["kind"] or "video"
    d = {"id": v["id"], "n": v["n"], "url": v["url"], "provider": v["provider"], "embed": vdr_embed(v) if kind == "video" else None,
         "timed": kind == "video" and v["provider"] != "link", "created_at": v["created_at"], "kind": kind}
    if kind != "video" or v["file_name"]:  # 2.658.0 (#5015): + an audio file of the file store (kind video, provider audio)
        d.update(file_id=v["file_id"], file_no=v["file_no"], file_name=v["file_name"], mime=v["mime"],
                 content=f"/api/videos/{v['review_id']}/versions/{v['id']}/file" if v["file_id"] else None)
    return d


def vdr_comments(c, vid, version_id=None, public=False):
    """The live comments of review vid (one version or all), oldest timecode first; public = only the customers' comments
    and the answers to them (the customer page)."""
    rows = c.execute(VDC_SEL + " WHERE review_id=? AND deleted_at IS NULL" + (" AND version_id=?" if version_id else "")
                     + " ORDER BY at_sec NULLS LAST, page NULLS FIRST, id", (vid, version_id) if version_id else (vid,)).fetchall()
    if public:
        ext = {x["id"] for x in rows if x["ext_name"] and not x["parent_id"]}
        rows = [x for x in rows if x["id"] in ext or x["parent_id"] in ext]
    return rows


# 2.122.4 A (#2217): the customer's decision is stored neutral (a control character no comment input keeps, vdr_clean) and
# put into the reader's language when shown; comments stored before stay as they are
RG4_DEC = "\x1edec:"
RG4_DEC_TEXT = {"accepted": N_("Approved|video"), "declined": N_("Changes requested")}


def rg4_dec_store(st, reason):
    return f"{RG4_DEC}{st}\x1e{reason or ''}"


def rg4_dec_text(body, lg=None):
    """A comment's text for reading: a stored decision in the reader's language (lg: the customer page), else unchanged."""
    if not (body or "").startswith(RG4_DEC):
        return body
    st, _, reason = body[len(RG4_DEC):].partition("\x1e")
    text = tr(RG4_DEC_TEXT.get(st, RG4_DEC_TEXT["declined"]), lg=lg)
    return f"{text}: {reason}" if reason else text


def vdr_comment_dict(x, names, marks=None):
    return {"id": x["id"], "version_id": x["version_id"], "parent_id": x["parent_id"], "at_sec": x["at_sec"], "body": rg4_dec_text(x["body"]),
            "author_id": x["author_id"], "author": x["ext_name"] or names.get(x["author_id"]) or "", "customer": bool(x["ext_name"]),
            "done": bool(x["done"]), "created_at": x["created_at"], "edited_at": x["edited_at"],  # 2.981.0 (#5273): the version of an edit
            # 2.641.0 (#4769): the place {t} | {x, y} | {page, x?, y?} and the number of its point on the image / page
            "pos": vdm_pos_dict(x), "page": x["page"], "mark": (marks or {}).get(x["id"])}


def vdr_space_key(oid):
    return f"org:{oid}" if oid else "private"


def vdr_full(c, uid, r):
    """The signer's e-mail / address / device only for the review's creator, the org admin or the private owner
    (2.99.1 review M1, like sig_offer_list: office admins only)."""
    if r["created_by"] == uid:
        return True
    return bool(is_org_admin(c, uid, r["org_id"])) if r["org_id"] else r["owner_id"] == uid


def vdr_dict(c, r, uid, full=False, signoffs=True):
    """A review for the app: place, state, versions, open comments; full = with the comments and the approval links
    (signoffs=False: never built, the agents' API)."""
    vs = vdr_versions(c, r["id"])
    n_open = c.execute(f"SELECT COUNT(*) FROM obj_comments WHERE kind='{VDC_KIND}' AND ref_id=? AND {live_sql()} AND state IS NULL "
                       "AND parent_id IS NULL", (r["id"],)).fetchone()[0]
    d = {"id": r["id"], "title": r["title"], "state": r["state"], "org_id": r["org_id"], "space": vdr_space_key(r["org_id"]),
         "task_id": r["task_id"], "list_id": r["list_id"], "client_id": r["client_id"], "created_by": r["created_by"],
         "created_at": r["created_at"], "updated_at": r["updated_at"], "deleted": bool(r["deleted_at"]),
         "versions": [vdr_version_dict(v) for v in vs], "version": vs[-1]["n"] if vs else 0, "open_comments": n_open,
         "can_write": vdr_may(c, uid, r, write=True), "kind": (vs[-1]["kind"] or "video") if vs else "video"}  # 2.641.0 (#4769)
    if full:
        cm = vdr_comments(c, r["id"])
        names = user_names(c, [x["author_id"] for x in cm])
        mk = vdm_marks(cm)  # 2.641.0 (#4769)
        d["comments"] = [vdr_comment_dict(x, names, mk) for x in cm]
        if d["can_write"] and signoffs:
            # 2.122.4 A (#2215 L3): the records keep their review across a move; only those of its current workspace show
            # 2.642.0 (#4772): several live links: the running ones first, then the newest records
            rows = c.execute("SELECT * FROM office_signoffs WHERE video_id=? AND kind='video' AND org_id IS NOT DISTINCT FROM ? "
                             "ORDER BY (state='open' AND revoked_at IS NULL) DESC, id DESC LIMIT 40", (r["id"], r["org_id"])).fetchall()
            adm = vdr_full(c, uid, r)
            d["signoffs"] = [sig_public(c, s, adm) for s in rows]
        else:
            d["signoffs"] = []
    return d


def vdr_rows(c, uid, task_id=None, list_id=None, client_id=None):
    """The live reviews at a task / list / client that uid sees (newest first)."""
    col, i = ("task_id", task_id) if task_id else ("list_id", list_id) if list_id else ("client_id", client_id)
    rows = c.execute(f"SELECT * FROM video_reviews WHERE {col}=? AND deleted_at IS NULL ORDER BY id DESC LIMIT 100", (i,)).fetchall()
    return [r for r in rows if vdr_may(c, uid, r)]


def vdr_touch(c, vid):
    c.execute("UPDATE video_reviews SET updated_at=? WHERE id=?", (iso(now_utc()), vid))


def vdr_version_add(c, r, link, uid):
    n = (c.execute("SELECT MAX(n) FROM video_versions WHERE review_id=?", (r["id"],)).fetchone()[0] or 0) + 1
    # 2.641.0 (#4769): + the medium and, for an image / PDF, its file of the file store (vdmedia.vdm_media)
    return insert_id(c, "INSERT INTO video_versions(review_id, org_id, n, url, provider, embed_id, created_by, created_at, kind, file_id, file_no, "
                        "file_name, mime, uploaded) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                     (r["id"], r["org_id"], n, link["url"], link["provider"], link["embed_id"], uid, iso(now_utc()), link.get("kind") or "video",
                      link.get("file_id"), link.get("file_no"), link.get("file_name") or "", link.get("mime") or "",
                      1 if link.get("uploaded") else 0))  # 2.662.0 (#5041): an upload of the sign-off follows the review's rights


def vdr_comment_add(c, r, uid, b, ext_name=None):
    """A comment {body, version_id?, at_sec?, parent_id?} on review r (checked: the version is the review's, a reply answers a
    top-level comment of the same version and carries no timecode of its own, a link without time control none) -> id."""
    if not ext_name:  # 2.607.0 (#4549): a guest / read-only person of the review's organisation only reads (the client's page: as before)
        need_org_say(c, uid, r["org_id"], lambda: vdr_may(c, uid, r, write=True))
    text = vdr_clean(b.get("body"), VDR_BODY_MAX)
    if not text:
        raise BadInput(tr("Please write a comment."))
    vs = {v["id"]: v for v in vdr_versions(c, r["id"])}
    ver = b.get("version_id")
    if ver in (None, ""):
        ver = max(vs, key=lambda k: vs[k]["n"]) if vs else None
    if isinstance(ver, bool) or ver not in vs:
        raise BadInput(tr("Invalid value: {0}", "version_id"))
    at, page, px, py = vdm_pos(vs[ver]["kind"] or "video", b, vdr_at)  # 2.641.0 (#4769): {t} | {x, y} | {page, x, y}
    par = b.get("parent_id")
    if par not in (None, "", 0):
        p = c.execute(VDC_SEL + " WHERE id=? AND review_id=? AND deleted_at IS NULL",
                      (par if isinstance(par, int) and not isinstance(par, bool) else -1, r["id"])).fetchone()
        if not p or p["parent_id"]:  # one level of answers
            raise BadInput(tr("Invalid value: {0}", "parent_id"))
        par, ver, at, page, px, py = p["id"], p["version_id"], None, None, None, None
    else:
        par = None
    if vs[ver]["provider"] == "link":
        at = None
    cid = ocm_add(c, VDC_KIND, r["id"], None if ext_name else uid, text, ext_name=ext_name, parent_id=par, org_id=r["org_id"],
                  anchor={"version_id": ver, "t": at, "page": page, "x": px, "y": py})  # 2.981.0 (#5273): the comments' core
    vdr_touch(c, r["id"])
    return cid


def vdr_reload(c, vid):
    return c.execute("SELECT * FROM video_reviews WHERE id=?", (vid,)).fetchone()


# ---------------------------------------------------------------- routes of the app
@app.get("/api/videos")
def vdr_list():
    """?task_id= | list_id= | client_id= -> the reviews there (with versions and counts)."""
    c, uid = db(), me()
    a = {k: request.args.get(k, type=int) for k in ("task_id", "list_id", "client_id")}
    if sum(1 for v in a.values() if v) != 1:
        return err(tr("Invalid value: {0}", "task_id / list_id / client_id"))
    return jsonify(reviews=[vdr_dict(c, r, uid) for r in vdr_rows(c, uid, **a)])


@app.post("/api/videos")
def vdr_create():
    """{title?, url, task_id | list_id | client_id} -> a new review with its first version."""
    c, uid = db(), me()
    if vdr_is_agent(c, uid):
        raise Denied(404)  # 2.99.1 C (#1959): like every other route of the app for agents (their API: videos/v1.py, no creating)
    # 2.623.0 (#4765): the module Approval off (Settings > Modules, the person's own switch, also without an organisation) = no
    # new review (409 like every module); the existing ones stay readable, keep their versions and comments, restore from the trash
    need_feat("videos")
    b = vdm_body()  # 2.641.0 (#4769): JSON {url | file_id} or a multipart upload (file)
    oid, tid, lid, cid = vdr_target(c, uid, b)
    link = vdm_media(c, uid, oid, b, vdr_parse)
    title = vdr_clean(b.get("title"), VDR_TITLE_MAX) or (link.get("file_name") or tr("Video"))[:VDR_TITLE_MAX]
    ts = iso(now_utc())
    vid = insert_id(c, "INSERT INTO video_reviews(org_id, owner_id, task_id, list_id, client_id, title, state, created_by, created_at, updated_at) "
                       "VALUES(?,?,?,?,?,?,'open',?,?,?)", (oid, None if oid else uid, tid, lid, cid, title, uid, ts, ts))
    r = vdr_reload(c, vid)
    vdr_version_add(c, r, link, uid)
    c.commit()
    return jsonify(vdr_dict(c, vdr_reload(c, vid), uid, full=True))


@app.get("/api/videos/<int:vid>")
def vdr_get(vid):
    c, uid = db(), me()
    return jsonify(vdr_dict(c, vdr_need(c, vid), uid, full=True))


@app.patch("/api/videos/<int:vid>")
def vdr_patch(vid):
    """{title?, state? (open | approved | changes)}."""
    c, uid = db(), me()
    r = vdr_need(c, vid, write=True)
    b = body()
    b = b if isinstance(b, dict) else {}
    if "title" in b:
        t = vdr_clean(b.get("title"), VDR_TITLE_MAX)
        if not t:
            return err(tr("Invalid value: {0}", "title"))
        c.execute("UPDATE video_reviews SET title=? WHERE id=?", (t, vid))
    if "state" in b:
        if b["state"] not in VDR_STATES:
            return err(tr("Invalid value: {0}", "state"))
        c.execute("UPDATE video_reviews SET state=? WHERE id=?", (b["state"], vid))
    vdr_touch(c, vid)
    c.commit()
    return jsonify(vdr_dict(c, vdr_reload(c, r["id"]), uid, full=True))


@app.delete("/api/videos/<int:vid>")
def vdr_delete(vid):
    """To the trash (deleted_at; restore = the undo); its open customer link stops at once. 2.947.0 (#5367): the core's
    trash (obj_trash; step=False: the app's undo is the restore route with its place check)."""
    c, uid = db(), me()
    vdr_need(c, vid, write=True)
    ts = obj_trash(c, uid, VDR_KIND, vid, step=False)["deleted_at"]
    c.execute("UPDATE office_signoffs SET revoked_at=? WHERE video_id=? AND state='open' AND revoked_at IS NULL", (ts, vid))
    c.commit()
    return jsonify(ok=True)


@app.get("/api/videos/trash")
def vdr_trash():
    """2.549.0 (#4536): the reviews in the video trash the person may see (their own, the organisation's ones they see, those
    at a task / project / client they see; the same vdr_may as restore) -> {reviews: [{id, title, org_id, space, task_id,
    list_id, client_id, deleted_at, version, can_restore}], trash_days, purge_on}. The trash section of the app (trashui.js)."""
    c, uid = db(), me()
    if vdr_is_agent(c, uid):
        raise Denied(404)  # like the other routes of the app for agents
    # a private review without a place is only its owner's; the rest is checked one by one (vdr_may, the tenant boundary first)
    # 2.549.0 (#4536, review): organisation rows only of the person's own organisations, and no LIMIT before the check -
    # on a hosted instance other tenants' rows could have pushed the own ones out (the trash is pruned, so it stays small)
    orgs = [int(o) for o in user_orgs(c, uid)]
    org_sql = f"org_id IN ({','.join('?' * len(orgs))})" if orgs else "1=0"
    rows = c.execute(f"SELECT * FROM video_reviews WHERE {trash_sql()} AND (" + org_sql + " OR (org_id IS NULL AND (owner_id=? "
                     "OR created_by=? OR task_id IS NOT NULL OR list_id IS NOT NULL OR client_id IS NOT NULL))) ORDER BY deleted_at DESC, id DESC",
                     (*orgs, uid, uid)).fetchall()
    out = []
    for r in rows:
        if len(out) >= 200:
            break
        if not vdr_may(c, uid, r):
            continue
        vs = vdr_versions(c, r["id"])
        out.append({"id": r["id"], "title": r["title"], "org_id": r["org_id"], "space": vdr_space_key(r["org_id"]),
                    "task_id": r["task_id"], "list_id": r["list_id"], "client_id": r["client_id"], "deleted_at": r["deleted_at"],
                    "version": vs[-1]["n"] if vs else 0, "can_restore": vdr_may(c, uid, r, write=True)})
    return jsonify(reviews=out, trash_days=ret_trash_days(), purge_on=bool(ret_on("trash")))


@app.post("/api/videos/<int:vid>/restore")
def vdr_restore(vid):
    """Back from the trash. 2.549.0 (#4536): {list_id?} = a review without a place (its task / project / client was deleted
    for good, videos/vdrescue.py) goes into this project of its own workspace (the person may write there, not locked):
    a review always has a place in the app again. Without it the review comes back where it hangs now (the undo)."""
    c, uid = db(), me()
    vdr_need(c, vid, deleted=True)
    r = vdr_reload(c, vid)
    if not vdr_may(c, uid, r, write=True):
        raise Denied(403)
    b = body()
    lid = b.get("list_id") if isinstance(b, dict) else None
    if lid not in (None, "", 0):
        if r["task_id"] or r["list_id"] or r["client_id"]:
            raise Denied(409, tr("Invalid value: {0}", "list_id"))  # it has a place: it goes back there
        o, _t, lid, _k = vdr_target(c, uid, {"list_id": lid})
        if (o or None) != (r["org_id"] or None):
            raise Denied(409, tr("Invalid value: {0}", "list_id"))  # another workspace: that is "Move to another workspace"
        c.execute("UPDATE video_reviews SET list_id=? WHERE id=?", (lid, vid))
    obj_restore(c, uid, VDR_KIND, vid, step=False)  # 2.947.0 (#5367): the core's trash
    c.commit()
    return jsonify(vdr_dict(c, vdr_reload(c, vid), uid, full=True))


@app.post("/api/videos/<int:vid>/versions")
def vdr_version_new(vid):
    """{url} -> a new version (the next number); the comments of the older ones stay at them."""
    c, uid = db(), me()
    r = vdr_need(c, vid, write=True)
    link = vdm_media(c, uid, r["org_id"], vdm_body(), vdr_parse)  # 2.641.0 (#4769): {url} | {file_id} | an upload (file)
    write_lock(c, f"video_review_{int(vid)}")
    nid = vdr_version_add(c, r, link, uid)
    vdl_carry(c, r, nid)  # 2.642.0 (#4772): a decided client link goes on at the same URL with the new version
    if r["state"] != "open":
        c.execute("UPDATE video_reviews SET state='open' WHERE id=?", (vid,))
    vdr_touch(c, vid)
    c.commit()
    return jsonify(dict(vdr_dict(c, vdr_reload(c, vid), uid, full=True), new_version=nid))


@app.get("/api/videos/<int:vid>/versions/<int:nid>/file")
def vdr_version_file(vid, nid):
    """2.641.0 (#4769): the image / PDF of a version (?dl=1: as a download) for who sees the review AND its file (vdmedia)."""
    c = db()
    r = vdr_need(c, vid)
    return vdm_send(c, vdm_version_row(c, r["id"], nid))


@app.delete("/api/videos/<int:vid>/versions/<int:nid>")
def vdr_version_del(vid, nid):
    """Takes back the NEWEST version (the undo of "New version"), while it has no comments and is not the only one."""
    c, uid = db(), me()
    vdr_need(c, vid, write=True)
    write_lock(c, f"video_review_{int(vid)}")  # 2.642.0 (#4772, review): serialised with a client's decision and a new version
    vs = vdr_versions(c, vid)
    if len(vs) < 2 or vs[-1]["id"] != nid:
        raise Denied(409, tr("Only the newest version can be removed"))
    if c.execute(VDC_SEL + " WHERE review_id=? AND version_id=? AND deleted_at IS NULL LIMIT 1", (vid, nid)).fetchone():
        raise Denied(409, tr("This version already has comments"))
    # 2.981.0 (#5273): the comments of the version in the trash go with it (was ON DELETE CASCADE of video_comments.version_id)
    c.execute(f"DELETE FROM obj_comments WHERE kind='{VDC_KIND}' AND ref_id=? AND CAST(anchor->>'version_id' AS BIGINT)=?", (vid, nid))
    vdl_uncarry(c, vid, nid)  # 2.642.0 (#4772): before the version goes (its links carried on give the token back)
    c.execute("DELETE FROM video_versions WHERE id=? AND review_id=?", (nid, vid))
    vdr_touch(c, vid)
    c.commit()
    return jsonify(vdr_dict(c, vdr_reload(c, vid), uid, full=True))


def vdc_web_add(c, r, uid, b):
    """A person's comment on review r (the app's route and the core's generic one) -> id."""
    par = b.get("parent_id")
    if isinstance(par, int) and not isinstance(par, bool):  # 2.360.0 D (#2496): as in v1 -- the customer page shows this answer
        p = c.execute(VDC_SEL + " WHERE id=? AND review_id=? AND deleted_at IS NULL", (par, r["id"])).fetchone()
        if p and p["ext_name"] and not vdr_may(c, uid, r, write=True):
            raise Denied(403, tr("Only people who may change the review answer the client"))
    return vdr_comment_add(c, r, uid, b)


@app.post("/api/videos/<int:vid>/comments")
def vdr_comment_new(vid):
    """{body, version_id?, at_sec?, parent_id?}: everybody who sees the review may comment (like task comments)."""
    c, uid = db(), me()
    r = vdr_need(c, vid)
    b = body()
    cid = vdc_web_add(c, r, uid, b if isinstance(b, dict) else {})
    c.commit()
    return jsonify(dict(vdr_dict(c, vdr_reload(c, vid), uid, full=True), comment_id=cid))


def vdr_comment_row(c, r, cid, deleted=False):
    x = c.execute(VDC_SEL + " WHERE id=? AND review_id=?", (cid, r["id"])).fetchone()
    if not x or bool(x["deleted_at"]) != deleted:
        raise Denied(404)
    return x


def vdc_set_done(c, x, done):
    """2.981.0 (#5273): comment x (a row of VDC) done / open again, under the comment's lock (core/objparts.py, comment-<id>)."""
    part_write(c, "comment", x["id"], {}, read=lambda c, i: x)
    c.execute("UPDATE obj_comments SET state=? WHERE id=? AND kind=?", ("done" if done else None, x["id"], VDC_KIND))


def vdc_change(c, r, x, uid, b, wr):
    """2.981.0 (#5273): comment x of review r changed by uid (wr = may change the review): done (its author or wr) under the
    comment's lock, body (its author only) through the core's edit: lock comment-<id> and, with expect_updated_at (edited_at
    or created_at of the comment), 409 with the comment when it changed meanwhile (B3: was written over without either)."""
    mine = x["author_id"] == uid
    if mine and ("done" in b or "body" in b):  # 2.607.0 (#4549): a guest / read-only person of the review's
        need_org_say(c, uid, r["org_id"], lambda: wr)  # organisation only reads -- asked before anything is written (review)
    if "done" in b:
        if not (mine or wr):
            raise Denied(403)
        vdc_set_done(c, x, b["done"])
    if "body" in b:
        if not mine:
            raise Denied(403)
        t = vdr_clean(b.get("body"), VDR_BODY_MAX)
        if not t:
            raise BadInput(tr("Please write a comment."))
        ocm_edit(c, x["id"], uid, {**b, "body": t}, public=lambda c, row: vdr_comment_dict(
            c.execute(VDC_SEL + " WHERE id=?", (row["id"],)).fetchone(), user_names(c, [row["user_id"]])))
    vdr_touch(c, r["id"])


@app.patch("/api/videos/<int:vid>/comments/<int:cid>")
def vdr_comment_patch(vid, cid):
    """{done?: bool} (who may write the review or wrote the comment), {body?, expect_updated_at?} (only its author; 409 with
    the comment when it changed since, 2.981.0 #5273)."""
    c, uid = db(), me()
    r = vdr_need(c, vid)
    x = vdr_comment_row(c, r, cid)
    b = body()
    b = b if isinstance(b, dict) else {}
    vdc_change(c, r, x, uid, b, vdr_may(c, uid, r, write=True))
    c.commit()
    return jsonify(vdr_dict(c, vdr_reload(c, vid), uid, full=True))


@app.delete("/api/videos/<int:vid>/comments/<int:cid>")
def vdr_comment_del(vid, cid):
    """Its author or who may write the review (the core's rule: 'manage' on the review); into the core's trash with its
    answers (2.981.0 #5273: the text kept in obj_comment_trash, gone for good after the trash period; restore = the undo)."""
    c, uid = db(), me()
    r = vdr_need(c, vid)
    vdr_comment_row(c, r, cid)
    ocm_trash(c, cid, uid)
    c.commit()
    return jsonify(vdr_dict(c, vdr_reload(c, vid), uid, full=True))


@app.post("/api/videos/<int:vid>/comments/<int:cid>/restore")
def vdr_comment_restore(vid, cid):
    c, uid = db(), me()
    r = vdr_need(c, vid)
    vdr_comment_row(c, r, cid, deleted=True)
    if not ocm_restore(c, cid, uid):  # nothing kept (the trash run was quicker)
        raise Denied(404)
    c.commit()
    return jsonify(vdr_dict(c, vdr_reload(c, vid), uid, full=True))


def vdr_export_rows(c, r, version_id=None):
    """[(version, timecode, name, text, done, answer)] of the review's comments (answers right after their comment)."""
    cm = vdr_comments(c, r["id"], version_id)
    names = user_names(c, [x["author_id"] for x in cm])
    ns = {v["id"]: v["n"] for v in vdr_versions(c, r["id"])}
    top = [x for x in cm if not x["parent_id"]]
    mk, out = vdm_marks(cm), []  # 2.641.0 (#4769): an image / PDF comment: page and point number instead of the timecode
    for x in sorted(top, key=lambda x: (ns.get(x["version_id"], 0), x["at_sec"] is None, x["at_sec"] or 0, x["page"] or 0, x["id"])):
        for y in [x] + [k for k in cm if k["parent_id"] == x["id"]]:
            out.append((f"v{ns.get(y['version_id'], '')}", vdr_tc(x["at_sec"]) or vdm_pos_text(x, mk.get(x["id"])), y["ext_name"] or names.get(y["author_id"]) or "",
                        rg4_dec_text(y["body"]), bool(x["done"]), y is not x))  # 2.122.4 A (#2217)
    return out


def vdr_csv_cell(s):
    return csv_cell(s)


@app.get("/api/videos/<int:vid>/export")
def vdr_export(vid):
    """?version_id= &format=csv|text: the comments for the cut (timecode hh:mm:ss, name, text, done)."""
    c = db()
    r = vdr_need(c, vid)
    ver = request.args.get("version_id", type=int)
    rows = vdr_export_rows(c, r, ver)
    if request.args.get("format") == "text":
        lines = [f"{r['title']}"]
        for v, tc, name, text, done, ans in rows:
            lines.append(("    > " if ans else f"[{'x' if done else ' '}] {v} {tc or '--:--'} ") + f"{name}: {' '.join(text.split())}")
        return jsonify(text="\n".join(lines))
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=csv_dialect()[0])  # 2.368.2 (#2984)
    w.writerow([tr("Version"), tr("Timecode"), tr("Name"), tr("Comment"), tr("Done"), tr("Answer")])
    for v, tc, name, text, done, ans in rows:
        w.writerow([v, tc, vdr_csv_cell(name), vdr_csv_cell(text), tr("Yes") if done else "", tr("Yes") if ans else ""])
    fn = re.sub(r"[^A-Za-z0-9_-]+", "-", r["title"]).strip("-")[:60] or "video"
    return Response("﻿" + buf.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{fn}-comments.csv"', "Cache-Control": "no-store"})


# ---------------------------------------------------------------- the customer link (office/signoff.py, kind video)
def vdr_sig_hash(r):
    """What an approval link of review r covers: the review (a new version keeps the link; the decision names the version)."""
    return hashlib.sha256(f"video:{r['id']}".encode()).hexdigest()


@app.post("/api/videos/<int:vid>/signoff")
def vdr_sig_new(vid):
    """{expires: YYYY-MM-DD | null, show_old?: bool} -> a customer link of the review. 2.642.0 (#4772): several live links
    (VDL_LIVE_MAX), the others keep running; show_old = the client may open the older versions too."""
    c, uid = db(), me()
    r = vdr_need(c, vid, write=True)
    if not public_links_on(c, "signoff"):
        return err(tr("Public links are switched off on this server"), 409)
    vs = vdr_versions(c, vid)
    if not vs:
        return err(tr("Invalid value: {0}", "url"), 409)
    # 2.764.0 (#5040): images / PDFs too (2.641.0 #4769 had refused them: "The client link is for videos only")
    b = body()
    try:
        exp = sig_expiry((b if isinstance(b, dict) else {}).get("expires"))
    except BadInput as x:
        return err(str(x))
    write_lock(c, f"office_signoff_video_{int(vid)}")
    if vdl_live_count(c, r) >= VDL_LIVE_MAX:  # 2.642.0 (#4772)
        return err(tr("At most {0} client links at once: switch one off first", VDL_LIVE_MAX), 409)
    row, tok = sig_create(c, r["org_id"], "video", r["title"], vdr_sig_hash(r), uid, exp, video_id=vid)
    if (b if isinstance(b, dict) else {}).get("show_old") is True:  # 2.642.0 (#4772): ticked when the link is made
        c.execute("UPDATE office_signoffs SET show_old=1 WHERE id=?", (row["id"],))
        row = c.execute("SELECT * FROM office_signoffs WHERE id=?", (row["id"],)).fetchone()
    c.commit()
    return jsonify(sig_public(c, row, vdr_full(c, uid, r)))


@app.post("/api/videos/<int:vid>/signoffs/<int:sid>/revoke")
def vdr_sig_revoke(vid, sid):
    c, uid = db(), me()
    r = vdr_need(c, vid, write=True)
    s = c.execute("SELECT * FROM office_signoffs WHERE id=? AND video_id=? AND kind='video' AND org_id IS NOT DISTINCT FROM ?",
                  (sid, vid, r["org_id"])).fetchone()  # 2.122.4 A (#2215 L3): never one of the old workspace
    if not s:
        raise Denied(404)
    if not s["revoked_at"]:  # 2.642.0 (#4772, review): a decided link too - it then stops and does not go on with a new version
        c.execute("UPDATE office_signoffs SET revoked_at=? WHERE id=?", (iso(now_utc()), sid))
        c.commit()
    return jsonify(sig_public(c, c.execute("SELECT * FROM office_signoffs WHERE id=?", (sid,)).fetchone(), vdr_full(c, uid, r)))


def vdr_sig_row(c, s):
    """The live review of approval link s (None: gone / in the trash)."""
    r = c.execute("SELECT * FROM video_reviews WHERE id=?", (s["video_id"],)).fetchone() if s["video_id"] else None
    if r and r["client_id"] and c.execute("SELECT 1 FROM clients WHERE id=? AND deleted_at IS NOT NULL", (r["client_id"],)).fetchone():
        return None  # 2.272.0 F (#3029, review M2): a client in the trash approves nothing (like the portal)
    return r if r and not r["deleted_at"] else None


def vdr_sig_valid(c, s):
    if not c.execute("SELECT 1 FROM users WHERE id=? AND disabled=0", (s["created_by"],)).fetchone():
        return False  # 2.666.0 (#5112): a disabled account's approval link is void (as the list links, signoff.py sig_check)
    r = vdr_sig_row(c, s)
    vs = vdr_versions(c, r["id"]) if r else []
    return bool(r) and vdr_sig_hash(r) == s["doc_hash"] and bool(vs)  # 2.764.0 (#5040): images / PDFs too (2.641.0 #4769: videos only)


def vdr_sig_newest(c, s):
    vs = vdr_versions(c, s["video_id"])
    return vs[-1] if vs else None


def vdr_sig_decided(c, s, st, version, name, reason, lg):
    """The customer decided: the review's state follows (approved | changes) and the decision stands in the comments of
    the version shown (with the reason), so the team reads it next to the other notes."""
    c.execute("UPDATE video_reviews SET state=?, updated_at=? WHERE id=?", ("approved" if st == "accepted" else "changes", iso(now_utc()), s["video_id"]))
    text = rg4_dec_store(st, reason)  # 2.122.4 A (#2217): neutral, shown in the reader's language (was the customer's)
    ocm_add(c, VDC_KIND, s["video_id"], None, text, ext_name=name, org_id=s["org_id"], anchor={"version_id": version["id"]},
            state="done" if st == "accepted" else None)  # 2.981.0 (#5273): the comments' core


def vdr_pub_key(c, s):
    return hmac.new(auth_key(c), f"vdrc:{s['id']}:{s['token_hash']}".encode(), hashlib.sha256).hexdigest()


def vdr_player_html(v, origin, title, lg=None, token=None):
    """The player of a version (no script of the provider), or the plain link. 2.240.0 D (#2886): the customer page never loads a
    player by itself -- a placeholder with the question comes first; static/js/pubvideo.js builds the iframe / <video> from data-src
    after the click (nothing is remembered across visits)."""
    e = html.escape
    if v["provider"] == "audio" and v["file_name"]:  # 2.658.0 (#5015): an audio file of the file store, served by this server
        if not (v["file_id"] and token):  # through the link only (vdr_pub_media): no third party, so no question first
            return ""
        return (f'<div class="vdr-player vdr-aud" data-prov="audio"><audio src="{e(SIG_PREFIX + token)}/media" controls preload="metadata" '
                f'aria-label="{e(title)}"></audio></div>')
    src = vdr_embed(v, origin)
    if v["provider"] in ("youtube", "vimeo") and src:
        who = {"youtube": "YouTube", "vimeo": "Vimeo"}[v["provider"]]
        data = f'data-prov="{v["provider"]}" data-origin="{VDR_FRAME[v["provider"]]}"'
    elif v["provider"] in ("file", "audio") and src:  # 2.633.0 (#4777): audio -> an <audio> element (static/js/pubvideo.js)
        who = urlsplit(src).hostname or ""
        data = f'data-prov="{v["provider"]}"'
    else:
        return ""
    aud = v["provider"] == "audio"
    return (f'<div class="vdr-player{" vdr-aud" if aud else ""}" {data} data-src="{e(src)}" data-title="{e(title)}"><div class="vdr-gate">'
            '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="M6 4L16 10L6 16Z"/></svg>'
            f'<p>{e(tr("Loading the audio sends data (such as your IP address) to {0}.", who, lg=lg) if aud else tr("Loading the video sends data (such as your IP address) to {0}.", who, lg=lg))}</p>'
            f'<button type="button" class="btn" data-vdr-load>{e(tr("Load audio", lg=lg) if aud else tr("Load video", lg=lg))}</button>'
            # 2.240.0 D2 (#2886): without JavaScript the page offers the plain link
            f'<noscript><p><a href="{e(v["url"])}" target="_blank" rel="noopener noreferrer">{e(tr("Open the audio", lg=lg) if aud else tr("Open the video", lg=lg))}</a></p></noscript>'
            '</div></div>')


def vdr_sig_csp(c, s):
    """2.764.0 (#5040): what the customer page's CSP (office/signoff.py SIG_VIDEO_CSP) needs on top for a PDF version: the
    page fetches the PDF from its own media route and pdf.js reads it in its worker (both from this server only)."""
    vs = vdr_versions(c, s["video_id"]) if s["video_id"] else []
    return "; connect-src 'self'; worker-src 'self'" if vs and vdl_shown(c, s, vs)[0]["kind"] == "pdf" else ""


def vdr_sig_media_src(token, prefix, v, old):
    """The customer page's media route of version v (?v=<n> for an older one the link shows, vdr_pub_media)."""
    return f"{prefix}{token}/media" + (f"?v={int(v['n'])}" if old else "")


def vdr_sig_html(c, s, lg, token, prefix):
    """The head of the customer page: title, the newest version's player, its time line, the comments and the comment form.
    2.764.0 (#5040): an image / PDF version shows its file with the numbered points; the client sets a point (pubvideo.js)."""
    e = html.escape
    r, vs = vdr_sig_row(c, s), vdr_versions(c, s["video_id"])
    v, old = vdl_shown(c, s, vs)  # 2.642.0 (#4772): an older version only on a link that shows them (read-only)
    gname = vdl_name()  # the name the client typed before on this link
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(PUBLIC_URL))
    media = (v["kind"] or "video") in ("image", "pdf")  # 2.764.0 (#5040)
    player = "" if media else vdr_player_html(v, origin, r["title"], lg, token)
    if player and v["provider"] == "audio" and old:  # 2.764.0 (#5040): an older version's audio through ?v= (was always the newest's)
        player = player.replace(f'src="{e(SIG_PREFIX + token)}/media"', f'src="{e(vdr_sig_media_src(token, SIG_PREFIX, v, old))}"')
    if not player and v["provider"] == "audio" and v["file_name"]:  # 2.658.0 (#5015): the file left the file store
        player = f'<p class="vdr-hint">{e(tr("The file of this version is no longer in the file store.", lg=lg))}</p>'
    if not player and not media:
        player = (f'<p class="vdr-hint">{e(tr(VDR_NO_TIME, lg=lg))}</p><p><a class="btn" href="{e(v["url"])}" target="_blank" '
                  f'rel="noopener noreferrer nofollow">{e(tr("Open the video", lg=lg))}</a></p>')
    cm = vdr_comments(c, r["id"], v["id"], public=True)
    names = user_names(c, [x["author_id"] for x in cm])
    # 2.764.0 (#5040): the points' numbers as in the app (counted over every comment of the version, vdm_marks)
    allm = vdm_marks(vdr_comments(c, r["id"], v["id"])) if media else {}
    kids = {}
    for x in cm:
        if x["parent_id"]:
            kids.setdefault(x["parent_id"], []).append(x)

    def one(x, reply=False):
        who = x["ext_name"] or names.get(x["author_id"]) or ""
        at = "" if reply or x["at_sec"] is None else f'<a class="vdr-at" href="#t={int(x["at_sec"])}" data-at="{x["at_sec"]}">{e(vdr_tc(x["at_sec"]))}</a> '
        if media and not reply and (x["id"] in allm or x["page"]):  # 2.764.0 (#5040): "p. 2 · 3" -> its page and point
            lbl = " · ".join(t for t in (tr("p. {0}|page", x["page"], lg=lg) if x["page"] else "", str(allm.get(x["id"], ""))) if t)
            at = f'<a class="vdr-at vdr-pt" href="#vdr-stage" data-id="{x["id"]}" data-page="{x["page"] or ""}">{e(lbl)}</a> '
        return (f'<li class="vdr-c{" done" if x["done"] else ""}">{at}<b>{e(who)}</b> <span class="vdr-b">{e(rg4_dec_text(x["body"], lg))}</span>'
                + (f'<ul class="vdr-re">{"".join(one(k, True) for k in kids[x["id"]])}</ul>' if x["id"] in kids else "") + "</li>")
    top = [x for x in cm if not x["parent_id"]]
    marks = "".join(f'<span class="vdr-mk" data-at="{x["at_sec"]}" title="{e(vdr_tc(x["at_sec"]))}"></span>' for x in top if x["at_sec"] is not None)
    sent = request.args.get("sent") == "1"
    timed = not media and v["provider"] != "link"
    if media:  # 2.764.0 (#5040): the file and its points; the next point's number as in the app (points of the version + 1)
        player = vdm_pub_stage(v, vdr_sig_media_src(token, SIG_PREFIX, v, old), lg, top, allm, len(allm) + 1)
    form = (f'<form method="post" action="{prefix}{e(token)}/comments" class="fform vdrf" id="vdr-f">'
            f'<input type="hidden" name="f" value="{vdr_pub_key(c, s)}"><input type="hidden" name="v" value="{v["id"]}">'
            f'<label for="vd-name">{e(tr("Your name|public", lg=lg))}</label><input id="vd-name" name="name" maxlength="{VDR_NAME_MAX}" autocomplete="name" value="{e(gname)}" required>'
            + (f'<label for="vd-at">{e(tr("At (mm:ss, optional)", lg=lg))}</label><input id="vd-at" name="at" inputmode="numeric" maxlength="10" '
               f'placeholder="00:00" pattern="[0-9:.]*">' if timed else "")
            # 2.764.0 (#5040): the point set by a tap on the image / page (pubvideo.js); empty = a comment without a point
            + ('<input type="hidden" name="px" id="vd-px"><input type="hidden" name="py" id="vd-py"><input type="hidden" name="pg" id="vd-pg">'
               f'<p class="vdr-ptst" id="vd-pt" hidden><span></span> <button type="button" class="btn sec" data-pt-clear>{e(tr("without point", lg=lg))}</button></p>'
               if media else "")
            + f'<label for="vd-text">{e(tr("Comment", lg=lg))}</label><textarea id="vd-text" name="text" rows="3" maxlength="{VDR_BODY_MAX}" required></textarea>'
            f'<button type="submit">{e(tr("Send comment", lg=lg))}</button></form>')
    if old:  # 2.642.0 (#4772): an older version takes no comment (and the page no decision, office/signoff.sig_page)
        form = vdl_old_note(lg, token, prefix)
    return (f'<header><h1>{e(r["title"])}</h1><p class="sub">{e(tr("Version {0}", v["n"], lg=lg))} · {e(tr("Approval requested", lg=lg))}</p></header>'
            + (vdl_nav(vs, v, lg, token, prefix) if s["show_old"] and len(vs) > 1 else "")
            + player + (f'<div class="vdr-tl" aria-hidden="true">{marks}</div>' if timed and marks else "")
            + f'<section class="vdr-cms"><h2>{e(tr("Comments", lg=lg))}</h2>'
            + (f'<p class="ok" role="status">{e(tr("Thank you, your comment has arrived.", lg=lg))}</p>' if sent else "")
            + (f'<ul class="vdr-list">{"".join(one(x) for x in top)}</ul>' if top else f'<p class="sub">{e(tr("No comments yet.", lg=lg))}</p>')
            + form + "</section>"
            + ('<script src="/static/js/pdfview.js" defer></script>' if media and v["kind"] == "pdf" else "")  # 2.764.0 (#5040): pdf.js as in the app
            + '<script src="/static/js/pubvideo.js" defer></script>')


@app.get("/s/q/<token>/media")
def vdr_pub_media(token):
    """2.658.0 (#5015): the audio file of the file store that the link's page plays -- only the newest version's file (the one
    the page shows), only while the link is open (sig_open: not revoked, not expired, the review there; state open = not
    decided) and only while the file may be read (vdmedia.vdm_pub_send). Everything else: the answer of an unknown link."""
    c = db()
    # 2.658.0 (Fable review): per address AND per link, so many addresses cannot pull one (large, sealed) file without end
    if hit_limit("vdrm:" + rate_ip(), VDR_MEDIA_RATE) or hit_limit("vdrml:" + str(token)[:64], VDR_MEDIA_LINK_RATE):
        return pub_limited(_accept_lang())
    s, bad = sig_open(c, token)
    if bad:
        return bad
    # 2.764.0 (#5040): the file of the version the page shows (vdl_shown: ?v=<n> only on a link that shows the older ones,
    # else the newest) -- audio, image or PDF; never a version of another review (versions of this link's review only)
    vs = vdr_versions(c, s["video_id"]) if s["kind"] == "video" and s["state"] == "open" and s["video_id"] else []
    resp = vdm_pub_send(c, vdl_shown(c, s, vs)[0], s) if vs else None
    if resp is None:
        return pub_gone(sig_lang(c, s))
    if resp == "too_big":  # 2.773.0 (#5330): a large sealed file only signed in -- a defined answer without the content
        return vdr_pub_too_big(sig_lang(c, s))
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    resp.headers["Referrer-Policy"] = "no-referrer"
    return resp


def vdr_pub_too_big(lg):
    """2.773.0 (#5330): the answer of the media route for a sealed file above vdmedia.VDM_PUB_SEALED_MB: 413, no content."""
    t = tr("File too large for the link", lg=lg)
    r = pub_html(t, f'<div class="msg"><h1>{html.escape(t)}</h1>'
                 f'<p>{html.escape(tr("This file can only be opened signed in. Please ask the sender for it.", lg=lg))}</p></div>', lg, 413)
    r.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    r.headers["Referrer-Policy"] = "no-referrer"
    return r


@app.post("/s/q/<token>/comments")
def vdr_pub_comment(token):
    """A customer's comment through the approval link (name >= 2 characters, a text, an optional timecode) while it is open."""
    c = db()
    s, bad = sig_open(c, token)
    if bad:
        return bad
    lg, ip = sig_lang(c, s), rate_ip()
    if s["kind"] != "video":
        return pub_gone(lg)
    if request.headers.get("Sec-Fetch-Site", "") == "cross-site" or not hmac.compare_digest(request.form.get("f") or "", vdr_pub_key(c, s)):
        return pub_html(tr("Not allowed", lg=lg), f'<div class="msg"><h1>{html.escape(tr("Not allowed", lg=lg))}</h1></div>', lg, 403)
    if s["state"] != "open":
        return redirect(SIG_PREFIX + token, 303)
    if hit_limit("vdrc:" + ip, VDR_PUB_RATE) or hit_limit(f"vdrcl:{s['id']}", VDR_PUB_HOUR, 3600):
        return pub_limited(lg)
    r, v = vdr_sig_row(c, s), vdr_sig_newest(c, s)
    name = " ".join(vdr_clean(request.form.get("name"), VDR_NAME_MAX).split())
    text = vdr_clean(request.form.get("text"), VDR_BODY_MAX)
    back = f'<a class="btn" href="{SIG_PREFIX}{html.escape(token)}#vdr-f">{html.escape(tr("Back", lg=lg))}</a>'
    if len(name) < 2 or not text:
        return pub_html(tr("Please type your name and a comment.", lg=lg),
                        f'<div class="msg"><p class="err">{html.escape(tr("Please type your name and a comment.", lg=lg))}</p>{back}</div>', lg, 400)
    if str(v["id"]) != (request.form.get("v") or ""):
        return pub_html(tr("There is a newer version. Please look at it first.", lg=lg),
                        f'<div class="msg"><p class="err">{html.escape(tr("There is a newer version. Please look at it first.", lg=lg))}</p>{back}</div>', lg, 409)
    kind = v["kind"] or "video"
    try:
        if kind == "video":
            b = {"body": text, "version_id": v["id"], "at_sec": vdr_at(request.form.get("at") or None)}
        else:  # 2.764.0 (#5040): a point on the image / the PDF page (vdm_pos checks it as for the app)
            b = dict(vdm_pub_pos(kind, request.form), body=text, version_id=v["id"])
            vdm_pos(kind, b, vdr_at)
    except BadInput:  # 2.99.1 review L8: say it instead of dropping the time
        bad_at = tr("Invalid value: {0}", tr("Timecode", lg=lg) if kind == "video" else tr("Point|place", lg=lg), lg=lg)
        return pub_html(bad_at, f'<div class="msg"><p class="err">{html.escape(bad_at)}</p>{back}</div>', lg, 400)
    vdr_comment_add(c, r, None, b, ext_name=name)
    push = vdr_pub_notify(c, s, r, name, text)
    c.commit()
    print("video review customer comment", r["id"], flush=True)
    push_later(push)  # 2.370.2 (#2779): through the maintenance gate; 2.370.3 (#2760): a queue row
    return vdl_name_set(pub_headers(redirect(f"{SIG_PREFIX}{token}?sent=1#vdr-f", 303)), token, SIG_PREFIX, name)  # 2.642.0 (#4772)


VDR_PUSHED = {}  # review id -> time of the last customer-comment push (per process)


def vdr_pub_notify(c, s, r, name, text):
    """Push to the link's creator like the decisions (notification switch "signoff" since 2.266.0, was "approval"), at most one per review and 10 minutes."""
    import time  # 2.99.1 review L4: one push per review and 10 minutes (counting comments swallowed all while they kept coming)
    if time.time() - VDR_PUSHED.get(r["id"], 0) < 600:
        return None
    lid = vdr_list_of(c, r)
    sends = []
    for uid in sig_people(c, s["org_id"], s["created_by"], lid):  # 2.266.0 (#2965): never an ex-member / deactivated account
        try:
            from ..collab.news import notif_ok
            from ..core.db import usettings
            st = usettings(c, uid)
            if notif_ok(c, uid, st, "signoff", "push", lid):
                sends.append((uid, st))
        except Exception:  # noqa: BLE001
            continue
    if not sends:
        return None
    VDR_PUSHED[r["id"]] = time.time()
    click = vdr_click(r)
    click = click if click.startswith("http") else f"{PUBLIC_URL}/{click}"  # 2.266.0 (#2965): ntfy needs an absolute link
    sc = f"l:{lid}" if lid else f"o:{s['org_id']}"  # 2.240.0 B2 (#2867): the channels follow the list / the office
    return [(uid, tr("Comment from the client", lg=lang_of(st)), f"{name}: {text[:200]}", {"prio": "4", "click": click, "scope": sc})
            for uid, st in sends]  # 2.370.3 (#2760): collab.comments.push_later


def vdr_list_of(c, r):
    """The list a review belongs to (the mute switch of a list), or None."""
    if r["list_id"]:
        return r["list_id"]
    if r["task_id"]:
        x = c.execute("SELECT list_id FROM tasks WHERE id=?", (r["task_id"],)).fetchone()
        return x[0] if x else None
    return None


def vdr_click(r):
    """Where a push about review r opens the app."""
    return f"#t/{r['task_id']}" if r["task_id"] else f"#l/{r['list_id']}" if r["list_id"] else f"#client/{r['client_id']}" if r["client_id"] else "#"


# ---------------------------------------------------------------- to the other workspace (accounts/spacemove.py rules)
VDR_ONLY = N_("Only who created this video sign-off or an admin of the organisation can move it out of it")


@app.post("/api/videos/<int:vid>/move-space")
def vdr_move_space(vid):
    """{to, place, dry, undo?}: the review with its versions and comments to the private space / an organisation, into a
    project list `place` there (required: a review always has a place in the app; the undo puts it back to its old place). Agents never (403),
    the target an organisation of the person (409), the right to write the review and, out of an organisation, its creator
    or that organisation's admin (403); a private one only its owner. The task / project / client it hangs at stays in the
    old workspace: the review is taken off it (named by the dry run). Its approval links stay in the old workspace with
    their protocol (signer data sealed with that workspace's key; an open one stops). undo = the id of the space_moves row of
    the move being taken back (the same person, the way back): the place and the links come back where they fit."""
    import json
    smv_refuse_agent()
    c, uid = db(), me()
    r = vdr_need(c, vid, write=True)
    vdm_need_movable(c, vid)  # 2.641.0 (#4769): its files stay in their workspace (the tenant boundary)
    write_lock(c, f"video_review_{int(vid)}")  # 2.122.4 (#2215): a customer decision does not land in the old workspace mid-move
    b = body()
    b = b if isinstance(b, dict) else {}
    to = smv_target(c, uid, b.get("to"))
    smv_same(r["org_id"], to)
    if r["org_id"] is None and r["created_by"] != uid and r["owner_id"] != uid:
        raise Denied(403, tr(VDR_ONLY))
    # 2.361.2 B (#2923): out of an organisation only its admin, or the creator into the private space with a released request
    deny = None if org_out_ok(c, r["org_id"], to, "video", vid) else oo_denied(c, r["org_id"], to, "video", vid)
    if deny and not b.get("dry"):
        raise deny
    place = "task_id" if r["task_id"] else "list_id" if r["list_id"] else "client_id" if r["client_id"] else None
    sigs = c.execute("SELECT id, state, revoked_at, expires_at FROM office_signoffs WHERE video_id=?", (vid,)).fetchall()
    live = [s["id"] for s in sigs if s["state"] == "open" and not s["revoked_at"]]
    notes = [{"task_id": tr("The video sign-off is no longer attached to its task"), "list_id": tr("The video sign-off is no longer attached to its project"),
              "client_id": tr("The video sign-off is no longer attached to its client")}.get(place, ""),
             tr("Every member of the organisation can then open it") if to else "",
             tr("The client link stops; its record stays in the old workspace") if live else
             (tr("The client's decision stays recorded in the old workspace") if sigs else ""),
             oo_into_note(c, r["org_id"], to)]  # 2.361.2 B (#2923): the way back
    dest = None
    if b.get("place") not in (None, "", 0):
        try:
            pl = int(b.get("place"))
        except (TypeError, ValueError):
            raise Denied(400, tr("Invalid value: {0}", "place")) from None
        o, _t, dest, _k = vdr_target(c, uid, {"list_id": pl})
        if (o or None) != (to or None):
            raise Denied(409, tr("Invalid value: {0}", "place"))
    block = None if dest or b.get("undo") else tr("Select a project in the target workspace")
    if deny:  # 2.361.2 B (#2923): the dry run; the creator can ask an admin (out_request)
        return jsonify(smv_answer(notes, deny.text(), count=1, **(deny.data or {})))
    if b.get("dry") or block:
        return jsonify(smv_answer(notes, block, count=1))
    back = None
    if b.get("undo") not in (None, "", 0):
        u = b.get("undo")
        if isinstance(u, bool) or not isinstance(u, int):
            raise Denied(400, tr("Invalid value: {0}", "undo"))
        x = c.execute("SELECT * FROM space_moves WHERE id=? AND kind='video' AND obj_id=? AND by_id=?", (u, vid, uid)).fetchone()
        if x and (x["from_org"] or None) == (to or None) and (x["to_org"] or None) == (r["org_id"] or None):
            try:
                back = json.loads(x["detail"] or "{}")
            except ValueError:
                back = {}
    ts = iso(now_utc())
    new = {"task_id": None, "list_id": dest, "client_id": None}
    if not dest and back and back.get("place") in new and isinstance(back.get("place_id"), int):
        try:  # the old place again, while it lies in the target and the person may still write there
            o, *ids = vdr_target(c, uid, {back["place"]: back["place_id"]})
            if (o or None) == (to or None):
                new = dict(zip(("task_id", "list_id", "client_id"), ids))
        except (Denied, BadInput):
            pass
    if not any(new.values()):  # 2.99.1 review L2: the old place no longer fits -> a project in the target, no review at nothing
        return jsonify(smv_answer(notes, tr("Select a project in the target workspace"), count=1))
    org_out(c, r["org_id"], to, "video", r["title"], obj=vid)  # 2.361.2 B (#2923): logged, admins told, release used
    c.execute("UPDATE video_reviews SET org_id=?, owner_id=?, task_id=?, list_id=?, client_id=?, updated_at=?, brought_by=? WHERE id=?",
              (to, None if to else uid, new["task_id"], new["list_id"], new["client_id"], ts, uid if to and not r["org_id"] else None, vid))  # 2.365.1 (#3395): accounts/orgback.py
    c.execute("UPDATE video_versions SET org_id=? WHERE review_id=?", (to, vid))
    c.execute(f"UPDATE obj_comments SET org_id=? WHERE kind='{VDC_KIND}' AND ref_id=?", (to, vid))  # 2.981.0 (#5273)
    if live:
        c.execute(f"UPDATE office_signoffs SET revoked_at=? WHERE id IN ({','.join('?' * len(live))})", [ts, *live])
    # 2.122.4 A (#2215 L3): the records keep video_id (were emptied and vanished from every list); the lists filter by workspace
    revived = 0
    if back and back.get("sigs"):
        ids = [i for i in back["sigs"] if isinstance(i, int) and not isinstance(i, bool)][:200]
        if ids:
            revived = c.execute(f"UPDATE office_signoffs SET video_id=? WHERE id IN ({','.join('?' * len(ids))}) AND (video_id IS NULL "
                                "OR video_id=?) AND kind='video' AND org_id IS NOT DISTINCT FROM ?", [vid, *ids, vid, to]).rowcount  # 2.122.4 A (#2215 L3)
    detail = {"place": place, "place_id": r[place] if place else None, "sigs": [s["id"] for s in sigs]}
    mid = insert_id(c, "INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES('video',?,?,?,?,?,?)",
                    (vid, r["org_id"], to, uid, ts, json.dumps(detail)))
    c.commit()
    return jsonify(smv_answer(notes, None, ok=True, move_id=mid, from_space=vdr_space_key(r["org_id"]), space=vdr_space_key(to),
                              review=vdr_dict(c, vdr_reload(c, vid), uid, full=True), revived=revived))


def vdr_home(c, r, uid):
    """2.365.1 (#3395): review r goes back into uid's private space with their leaving (accounts/orgback.py): what
    vdr_move_space does without the dialog. Its place: its task / project when that went back too, else the person's inbox
    (a review always has a place; False without one: it stays). The caller commits."""
    import json
    if vdm_has_files(c, r["id"]):
        return False  # 2.641.0 (#4769): images / PDFs stay with their files in the organisation
    write_lock(c, f"video_review_{int(r['id'])}")  # as the route: a customer decision does not land in the old workspace mid-move
    place = "task_id" if r["task_id"] else "list_id" if r["list_id"] else "client_id" if r["client_id"] else None
    new = {"task_id": None, "list_id": None, "client_id": None}
    q = "SELECT 1 FROM tasks t JOIN lists l ON l.id=t.list_id WHERE t.id=? AND l.org_id IS NULL AND l.owner_id=?" if place == "task_id" else \
        "SELECT 1 FROM lists WHERE id=? AND org_id IS NULL AND owner_id=?" if place == "list_id" else None
    if q and c.execute(q, (r[place], uid)).fetchone():
        new[place] = r[place]
    else:
        new["list_id"] = (c.execute("SELECT id FROM lists WHERE owner_id=? AND is_inbox=1 AND org_id IS NULL ORDER BY id LIMIT 1", (uid,)).fetchone() or [None])[0]
        if not new["list_id"]:
            return False
    vid, ts = r["id"], iso(now_utc())
    sigs = c.execute("SELECT id, state, revoked_at FROM office_signoffs WHERE video_id=?", (vid,)).fetchall()
    live = [s["id"] for s in sigs if s["state"] == "open" and not s["revoked_at"]]
    c.execute("UPDATE video_reviews SET org_id=NULL, owner_id=?, task_id=?, list_id=?, client_id=?, updated_at=?, brought_by=NULL WHERE id=?",
              (uid, new["task_id"], new["list_id"], new["client_id"], ts, vid))
    c.execute("UPDATE video_versions SET org_id=NULL WHERE review_id=?", (vid,))
    c.execute(f"UPDATE obj_comments SET org_id=NULL WHERE kind='{VDC_KIND}' AND ref_id=?", (vid,))  # 2.981.0 (#5273)
    if live:
        c.execute(f"UPDATE office_signoffs SET revoked_at=? WHERE id IN ({','.join('?' * len(live))})", [ts, *live])
    c.execute("INSERT INTO space_moves(kind,obj_id,from_org,to_org,by_id,at,detail) VALUES('video',?,?,NULL,?,?,?)",
              (vid, r["org_id"], uid, ts, json.dumps({"place": place, "place_id": r[place] if place else None, "sigs": [s["id"] for s in sigs]})))
    return True


# 2.981.0 (#5273): vdr_trash_prune is gone -- a comment in the trash is a row of obj_comments, deleted after the trash period by
# the core's run with every other comment (files/trashpurge.py, its kept text with it)


def _vdc_trash(c, cid, ts):
    """The answers of a comment go into the trash with it (the same time; they were deleted with it by ON DELETE CASCADE)."""
    for (i,) in c.execute(f"SELECT id FROM obj_comments WHERE kind='{VDC_KIND}' AND parent_id=? AND {live_sql()}", (int(cid),)).fetchall():
        c.execute("INSERT INTO obj_comment_trash(comment_id, body, mentions) SELECT id, body, mentions FROM obj_comments WHERE id=? "
                  "ON CONFLICT(comment_id) DO UPDATE SET body=excluded.body, mentions=excluded.mentions", (i,))
        c.execute("UPDATE obj_comments SET body='', mentions='{}', deleted_at=? WHERE id=?", (ts, i))


def _vdc_restore(c, cid, ts):
    """... and come back with it (only those of that same time)."""
    for (i,) in c.execute(f"SELECT id FROM obj_comments WHERE kind='{VDC_KIND}' AND parent_id=? AND deleted_at=?", (int(cid), ts)).fetchall():
        ocm_restore(c, i, None, check=False)


def _vdc_people(c, rid):
    return set()  # a review comment mentions nobody (a token becomes "@name")


def _vdc_patch(c, rid, cid, uid, b):
    r = vdr_need(c, rid)
    vdc_change(c, r, vdr_comment_row(c, r, cid), uid, b, vdr_may(c, uid, r, write=True))


# 2.981.0 (#5273): the generic routes of core/objcmtweb.py (/api/obj/video/<review>/comments, /api/obj/comments/<cid>)
VDC_WEB = {"read": lambda c, rid, uid: vdr_need(c, rid), "add": lambda c, rid, uid, b: vdc_web_add(c, vdr_need(c, rid), uid, b),
           "patch": _vdc_patch, "out": lambda c, rid, uid: vdr_dict(c, vdr_reload(c, rid), uid, full=True),
           "changed": vdr_touch}
ocm_kind(VDC_KIND, obj=VDR_KIND, people=_vdc_people, sealed=lambda c, rid: False, sealed_in=lambda c, rid, t: (t, []),
         text_max=lambda t: VDR_BODY_MAX, trash=_vdc_trash, restore=_vdc_restore, web=VDC_WEB)
