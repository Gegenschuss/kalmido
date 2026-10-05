"""Home & life: "Read later" from Karakeep (a person's own connection: bookmarks -> tasks of a reading list, archive back)."""
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from ..core.i18n import N_, tr
from ..core.db import iso, now_utc, parse_iso
from ..core.access import Denied, list_role, WRITE_ROLES
from ..accounts.login import seal, unseal
from ..tasks.validation import as_int, TITLE_MAX
from ..personal.timetrack import BadInput
from ..life.model import _dump, life_list, need_life


# ---------------------------------------------------------------- 2.22.0 (#663): Karakeep
# Off by default (module "reading"). A person connects their own Karakeep (URL + API key, like a personal Paperless
# connection): the key is sealed with the server key (associated data = the person), never shown again, and only ever
# sent to that host (no redirects, the SSRF guard of the calendar subscriptions: public addresses only, internal hosts
# only where an admin allowed them). A sync (by hand, else about every hour in the background) adds every bookmark that
# is not archived (optionally only those of one Karakeep list) as a task of the person's reading list (title + link);
# a ticked bookmark task is archived in Karakeep (switchable). A bookmark comes in once: deleting its task does not bring
# it back. Agents have no connection.
KK_PAGE, KK_PAGES = 100, 5
KK_ARCHIVE_MAX = 50
KK_EVERY = 3600            # s between background syncs of one connection
KK_TIMEOUT = 15
KK_MAX_BYTES = 5 * 1024 * 1024
KK_TOKEN_MAX = 400


class KkError(Exception):
    pass


def _purpose(uid):
    return f"kk:{int(uid)}"


def kk_row(c, uid):
    return c.execute("SELECT * FROM kk_conns WHERE user_id=?", (uid,)).fetchone()


def kk_public(c, uid):
    """The connection as the person sees it: never the key, only whether it is set."""
    r = kk_row(c, uid)
    if not r:
        return {"connected": False}
    return {"connected": True, "url": r["url"], "token_set": bool(r["token"]), "list_id": r["list_id"], "source": r["source"],
            "archive": bool(r["archive"]), "synced_at": r["synced_at"], "error": r["error"]}


def _no_agent(c, uid):
    from ..agents.core import is_agent
    u = c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not u or is_agent(u):
        raise Denied(403, tr("An agent has no Karakeep connection"))


def kk_norm_url(u):
    from ..calendars.subscriptions import cal_norm_url
    u = cal_norm_url(u)
    if not u or not u.lower().startswith(("http://", "https://")):
        return None
    p = urllib.parse.urlsplit(u)
    if p.query or p.fragment or p.username or p.password:
        return None
    u = u.rstrip("/")
    for tail in ("/api/v1", "/api"):
        if u.lower().endswith(tail):
            u = u[:-len(tail)]
    return u


def kk_set(c, uid, b):
    """{url?, token?, list_id? (a reading list; null = the default one), source? (a Karakeep list id, '' = all),
    archive? (bool)} -> the connection (created with url + token)."""
    need_life(c, uid, "reading")
    _no_agent(c, uid)
    unknown = sorted(set(b) - {"url", "token", "list_id", "source", "archive"})
    if unknown:
        raise BadInput(tr("Unknown field: {0}", ", ".join(unknown)[:200]))
    r = kk_row(c, uid)
    url = kk_norm_url(b["url"]) if "url" in b else (r["url"] if r else None)
    if not url:
        raise BadInput(tr("Invalid value: {0}", "URL"))
    tok = r["token"] if r else ""
    if "token" in b:
        t = b["token"]
        if not isinstance(t, str) or not t.strip() or len(t.strip()) > KK_TOKEN_MAX or any(ord(ch) < 33 for ch in t.strip()):
            raise BadInput(tr("Invalid value: {0}", tr("API key")))
        tok = seal(c, _purpose(uid), t.strip())
    if not tok:
        raise BadInput(tr("Please enter the API key"))
    lid = r["list_id"] if r else None
    if "list_id" in b:
        lid = None if b["list_id"] in (None, "") else as_int(b["list_id"], "list_id", 1)
        if lid and (list_role(c, lid, uid) not in WRITE_ROLES or
                    c.execute("SELECT life FROM lists WHERE id=?", (lid,)).fetchone()[0] != "reading"):
            raise BadInput(tr("Choose one of your “Read later” lists"))
    src = r["source"] if r else ""
    if "source" in b:
        src = b["source"] or ""
        if not isinstance(src, str) or (src and not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", src)):
            raise BadInput(tr("Invalid value: {0}", "source"))
    arch = r["archive"] if r else 1
    if "archive" in b:
        if not isinstance(b["archive"], bool):
            raise BadInput(tr("Invalid value: {0}", "archive"))
        arch = 1 if b["archive"] else 0
    if r:
        c.execute("UPDATE kk_conns SET url=?, token=?, list_id=?, source=?, archive=?, error='' WHERE user_id=?", (url, tok, lid, src, arch, uid))
    else:
        c.execute("INSERT INTO kk_conns(user_id,url,token,list_id,source,archive,created_at) VALUES(?,?,?,?,?,?,?)",
                  (uid, url, tok, lid, src, arch, iso(now_utc())))
    return kk_public(c, uid)


def kk_delete(c, uid):
    """Removes the connection (the key goes; the tasks stay)."""
    c.execute("DELETE FROM kk_conns WHERE user_id=?", (uid,))


def kk_req(c, r, path, method="GET", body=None):
    """One request to the person's Karakeep (the key only goes to that host)."""
    from ..calendars.subscriptions import _cal_opener, cal_allow, CalError
    try:
        key = unseal(c, _purpose(r["user_id"]), r["token"])
    except Exception:  # noqa: BLE001  (another server key, damaged)
        key = ""
    if not key:
        raise KkError("key")
    hdr = {"Authorization": f"Bearer {key}", "Accept": "application/json"}
    data = None
    if body is not None:
        hdr["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(r["url"] + "/api/v1" + path, data=data, headers=hdr, method=method)
    try:
        with _cal_opener(cal_allow(c)).open(req, timeout=KK_TIMEOUT) as resp:
            raw = resp.read(KK_MAX_BYTES + 1)
            if len(raw) > KK_MAX_BYTES:
                raise KkError("too_large")
            return json.loads(raw or b"null")
    except urllib.error.HTTPError as e:
        e.close()
        raise KkError("auth" if e.code in (401, 403) else "redirect" if 300 <= e.code < 400 else f"http {e.code}") from None
    except urllib.error.URLError as e:
        raise KkError(e.reason.code if isinstance(e.reason, CalError) else "network") from None
    except CalError as e:
        raise KkError(e.code) from None
    except (OSError, ValueError):
        raise KkError("network") from None


KK_ERR = {"key": N_("The API key is not set (or the server key changed): enter it again"),
          "auth": N_("Karakeep refused the API key"), "network": N_("Karakeep could not be reached"),
          "redirect": N_("Karakeep answered with a redirect: check the address")}


def kk_err_text(code):
    return tr(KK_ERR[code]) if code in KK_ERR else tr("Karakeep: {0}", code)


def _bm_title_url(bm):
    ct = bm.get("content") or {}
    url = ct.get("url") if ct.get("type") == "link" and isinstance(ct.get("url"), str) else ""
    title = bm.get("title") or ct.get("title") or url or (ct.get("text") or "")[:120] or ct.get("fileName") or ""
    return (str(title).strip() or tr("Bookmark"))[:TITLE_MAX], (url[:2000] if url.lower().startswith(("http://", "https://")) else "")


def kk_sync(c, uid):
    """Bookmarks -> tasks, ticked ones -> archived in Karakeep. {added, archived}; the error is stored in the connection
    (and raised as BadInput for a request)."""
    from ..life.model import _insert
    r = kk_row(c, uid)
    if not r:
        raise BadInput(tr("Karakeep is not connected"))
    added = archived = 0
    try:
        lid = r["list_id"] if r["list_id"] and list_role(c, r["list_id"], uid) in WRITE_ROLES else None
        if not lid:
            lid = life_list(c, uid, "reading")
            c.execute("UPDATE kk_conns SET list_id=? WHERE user_id=?", (lid, uid))
        seen = {(json.loads(x[0]) or {}).get("bid") for x in c.execute(
            "SELECT fam FROM tasks WHERE created_by=? AND fam LIKE '%\"kind\":\"bookmark\"%'", (uid,))}
        cursor = None
        base = f"/lists/{r['source']}/bookmarks" if r["source"] else "/bookmarks"
        for _ in range(KK_PAGES):
            q = {"archived": "false", "limit": str(KK_PAGE), "includeContent": "false"}
            if cursor:
                q["cursor"] = cursor
            page = kk_req(c, r, base + "?" + urllib.parse.urlencode(q)) or {}
            for bm in page.get("bookmarks") or []:
                bid = str(bm.get("id") or "")
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", bid) or bid in seen or bm.get("archived"):
                    continue
                title, url = _bm_title_url(bm)
                _insert(c, uid, lid, title, url=url or None, fam={"kind": "bookmark", "src": "karakeep", "bid": bid})
                seen.add(bid)
                added += 1
            cursor = page.get("nextCursor")
            if not cursor:
                break
        if r["archive"]:
            for t in c.execute("""SELECT id, fam FROM tasks WHERE created_by=? AND status=2 AND fam LIKE '%"kind":"bookmark"%'
                                  AND fam NOT LIKE '%"arch":1%' LIMIT ?""", (uid, KK_ARCHIVE_MAX)).fetchall():
                f = json.loads(t["fam"])
                try:
                    kk_req(c, r, f"/bookmarks/{f['bid']}", "PATCH", {"archived": True})
                except KkError as e:
                    if not str(e).startswith("http 404"):
                        raise
                f["arch"] = 1
                c.execute("UPDATE tasks SET fam=? WHERE id=?", (_dump(f), t["id"]))
                archived += 1
        c.execute("UPDATE kk_conns SET synced_at=?, error='' WHERE user_id=?", (iso(now_utc()), uid))
    except KkError as e:
        c.execute("UPDATE kk_conns SET synced_at=?, error=? WHERE user_id=?", (iso(now_utc()), str(e)[:40], uid))
        c.commit()
        raise BadInput(kk_err_text(str(e))) from None
    return {"added": added, "archived": archived, "list_id": lid}


def kk_lists(c, uid):
    """The person's Karakeep lists (to pick one as the source)."""
    r = kk_row(c, uid)
    if not r:
        raise BadInput(tr("Karakeep is not connected"))
    try:
        j = kk_req(c, r, "/lists") or {}
    except KkError as e:
        raise BadInput(kk_err_text(str(e))) from None
    return [{"id": str(x.get("id")), "name": str(x.get("name") or "")[:100], "icon": str(x.get("icon") or "")[:8]}
            for x in j.get("lists") or [] if re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(x.get("id") or ""))]


def _wd_reading(c, users, S, LG, now):
    """Watchdog: the oldest due connection (one per tick, so a slow server never holds the watchdog up long)."""
    for r in c.execute("SELECT * FROM kk_conns ORDER BY COALESCE(synced_at, '') LIMIT 5").fetchall():
        uid = r["user_id"]
        if uid not in users or "reading" not in (S[uid].get("features") or "").split(","):
            continue
        if r["synced_at"] and (now_utc() - parse_iso(r["synced_at"])).total_seconds() < KK_EVERY:
            continue
        try:
            kk_sync(c, uid)
            c.commit()
        except BadInput:
            pass  # stored in the connection
        break
