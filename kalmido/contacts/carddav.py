"""CardDAV server: every address book a person sees as a collection of vCards (iOS / macOS Contacts, DAVx5, Thunderbird)."""
import email.utils
import hashlib
import json
import re
import threading
import time
import urllib.parse
from datetime import timezone

from flask import request, Response

from ..core.config import APP_NAME
from ..core.db import gsetting, parse_iso
from ..core.access import collab_all
from ..calendars.caldav import (
    _el, _privs, _xe, A_, CR_, CS_, D_, dav_body, dav_common, dav_href, dav_multistatus, dav_principal_href, dav_propfind_req,
    dav_response, dav_xml, DAV_MAX_BODY, DAV_NAME_RE, DavError, dav_color, dav_report_props,
)
from ..personal.timetrack import BadInput
from ..contacts.model import (
    contact_store, contacts_on, my_book_ids, parse_vcard, render_vcard,
)

# 2.21.0 (#658): /dav/addressbooks/<user>/ is the address book home (RFC 6352), b<id>/ one address book, <name>.vcf one
# contact. Same login (app passwords), rate limits, sync-collection (dav_sync2, coll b<id>) and ETag rules as the CalDAV
# part; /.well-known/carddav leads to /dav/. Contacts that are groups (Apple's KIND group cards) are kept as they came.
_CACHE, _LOCK = {}, threading.Lock()
AB_REPORTS = ("<D:supported-report><D:report><CR:addressbook-query/></D:report></D:supported-report>"
              "<D:supported-report><D:report><CR:addressbook-multiget/></D:report></D:supported-report>"
              "<D:supported-report><D:report><D:sync-collection/></D:report></D:supported-report>")


def ab_home_href(u):
    return dav_href("addressbooks", u["username"], coll=True)


def ab_books(c, u):
    if not contacts_on(c, u["id"]):
        return {}
    ids = my_book_ids(c, u["id"])
    if not ids:
        return {}
    q = ",".join("?" * len(ids))
    return {f"b{r['id']}": {"key": f"b{r['id']}", "id": r["id"], "name": r["name"], "color": r["color"], "role": ids[r["id"]]}
            for r in c.execute(f"SELECT * FROM books WHERE id IN ({q}) ORDER BY owner_id!=?, id", [*ids, u["id"]])}


def _etag(text):
    return '"' + hashlib.sha1(text.encode("utf-8"), usedforsecurity=False).hexdigest()[:24] + '"'


class AbColl:
    def __init__(self, book, members):
        self.book, self.members = book, members
        h = hashlib.sha1(usedforsecurity=False)
        for n in sorted(members):
            h.update(f"{n}\0{members[n][1]}\n".encode("utf-8"))
        self.hash = h.hexdigest()[:20]
        self.token = f"urn:kalmido:sync:{book['key']}-{self.hash}"
        self.ctag = '"' + self.hash + '"'

    def state(self):
        return {n: m[1] for n, m in self.members.items()}


def ab_coll(c, u, book):
    key = (u["id"], book["key"], gsetting(c, "version"), book["name"], book["role"], collab_all())
    now = time.monotonic()
    with _LOCK:
        hit = _CACHE.get(key)
        if hit and hit[0] > now:
            return hit[1]
    members = {}
    for r in c.execute("SELECT * FROM contacts WHERE book_id=? ORDER BY id", (book["id"],)):
        try:
            text = render_vcard(r)
        except (ValueError, TypeError, KeyError) as e:
            print("carddav: skipping contact", r["id"], e, flush=True)
            continue
        members[r["href"]] = (r["id"], _etag(text), text, r)
    ac = AbColl(book, members)
    with _LOCK:
        if len(_CACHE) > 64:
            for k in sorted(_CACHE, key=lambda k: _CACHE[k][0])[:16]:
                _CACHE.pop(k, None)
        _CACHE[key] = (now + 60, ac)
    return ac


def sync_save(c, u, ac):
    from ..events.dav import sync_save as _save
    return _save(c, u, _Shim(ac))


class _Shim:  # the event collections' sync-token storage works for address books too (dav_sync2, coll b<id>)
    def __init__(self, ac):
        self.coll, self.hash, self.token, self._ac = {"key": ac.book["key"]}, ac.hash, ac.token, ac

    def state(self):
        return self._ac.state()


def _privs_of(role):
    return _privs(["read", "write", "write-content", "bind", "unbind"]) if role in ("owner", "edit") else _privs(["read"])


def props_home(u):
    return {**dav_common(u), D_ + "resourcetype": "<D:collection/>", D_ + "displayname": _xe(APP_NAME),
            D_ + "owner": f"<D:href>{_xe(dav_principal_href(u))}</D:href>", D_ + "current-user-privilege-set": _privs(["read"]),
            CR_ + "addressbook-home-set": f"<D:href>{_xe(ab_home_href(u))}</D:href>"}


def props_book(c, u, book, ac_fn):
    p = {**dav_common(u), D_ + "resourcetype": "<D:collection/><CR:addressbook/>", D_ + "displayname": _xe(book["name"]),
         D_ + "owner": f"<D:href>{_xe(dav_principal_href(u))}</D:href>",
         CR_ + "supported-address-data": '<CR:address-data-type content-type="text/vcard" version="3.0"/>'
                                         '<CR:address-data-type content-type="text/vcard" version="4.0"/>',
         CR_ + "max-resource-size": str(DAV_MAX_BODY), D_ + "supported-report-set": AB_REPORTS,
         D_ + "current-user-privilege-set": _privs_of(book["role"]), CS_ + "getctag": lambda: _xe(ac_fn().ctag),
         D_ + "sync-token": lambda: _xe(sync_save(c, u, ac_fn())), CR_ + "addressbook-description": _xe(book["name"])}
    col = dav_color(book["color"])
    if col:
        p[A_ + "calendar-color"] = col
    return p


def props_member(u, m, role, version=None):
    cid, et, text, r = m
    if version and version != r["version"]:
        text = render_vcard({**dict(r), "version": version})
    return {**dav_common(u), D_ + "resourcetype": "", D_ + "getetag": _xe(et), D_ + "getcontenttype": "text/vcard; charset=utf-8",
            D_ + "getlastmodified": email.utils.format_datetime(parse_iso(r["updated_at"]).astimezone(timezone.utc), usegmt=True),
            D_ + "getcontentlength": str(len(text.encode("utf-8"))), CR_ + "address-data": _xe(text),
            D_ + "current-user-privilege-set": _privs_of(role), D_ + "owner": f"<D:href>{_xe(dav_principal_href(u))}</D:href>"}


def ab_path(p, u):
    """-> (kind, book key, name): abroot | abhome | book | card."""
    parts = [x for x in p.split("/") if x]
    if len(parts) == 1:
        return "abroot", None, None
    if parts[1].lower() != u["username"] or len(parts) > 4:
        raise DavError(404, "Not found")
    if len(parts) == 2:
        return "abhome", None, None
    if not re.fullmatch(r"b\d{1,12}", parts[2]):
        raise DavError(404, "Not found")
    if len(parts) == 3:
        return "book", parts[2], None
    if not DAV_NAME_RE.fullmatch(parts[3]):
        raise DavError(404, "Not found")
    return "card", parts[2], parts[3]


def _want_version(root):
    for el in root.iter(CR_ + "address-data"):
        v = el.get("version")
        if v in ("3.0", "4.0"):
            return v
    return None


def card_now(c, book, name):
    r = c.execute("SELECT * FROM contacts WHERE book_id=? AND href=?", (book["id"], name)).fetchone()
    if not r:
        return None
    text = render_vcard(r)
    return r, _etag(text), text


def _match(text, root):
    """addressbook-query filter: prop-filter + text-match (contains / equals / starts-with / ends-with), anyof / allof."""
    filt = root.find(CR_ + "filter")
    if filt is None:
        return True
    tests = []
    for pf in filt.findall(CR_ + "prop-filter"):
        name = pf.get("name", "").upper()
        vals = []
        for ln in text.replace("\r\n ", "").split("\r\n"):
            head = ln.split(":", 1)[0].split(";", 1)[0].split(".")[-1].upper()
            if head == name and ":" in ln:
                vals.append(ln.split(":", 1)[1].lower())
        if pf.find(CR_ + "is-not-defined") is not None:
            tests.append(not vals)
            continue
        tms = pf.findall(CR_ + "text-match")
        if not tms:
            tests.append(bool(vals))
            continue
        sub = []
        for tm in tms:
            t, how, neg = (tm.text or "").lower(), tm.get("match-type", "contains"), tm.get("negate-condition") == "yes"
            hit = any((v == t) if how == "equals" else v.startswith(t) if how == "starts-with" else v.endswith(t) if how == "ends-with"
                      else (t in v) for v in vals)
            sub.append(hit != neg)
        tests.append(all(sub) if pf.get("test") == "allof" else any(sub))
    if not tests:
        return True
    return all(tests) if filt.get("test") == "allof" else any(tests)


def ab_report(c, u, book, raw):
    root = dav_xml(raw)
    want = dav_report_props(root)
    ver = _want_version(root)
    ac = ab_coll(c, u, book)
    base = ("addressbooks", u["username"], book["key"])
    role = book["role"]
    if root.tag == CR_ + "addressbook-multiget":
        pre = urllib.parse.unquote(dav_href(*base, coll=True))
        items = []
        for h in root.findall(D_ + "href"):
            rh = (h.text or "").strip()
            if rh:
                path = urllib.parse.unquote(urllib.parse.urlsplit(rh).path)
                items.append((rh, path, path.rsplit("/", 1)[-1]))

        def gen():
            for rh, path, name in items:
                m = ac.members.get(name) if path.startswith(pre) else None
                if m is None:
                    yield f"<D:response><D:href>{_xe(rh)}</D:href><D:status>HTTP/1.1 404 Not Found</D:status></D:response>"
                else:
                    yield dav_response(dav_href(*base, name), want, props_member(u, m, role, ver))
        return dav_multistatus(gen())
    if root.tag == CR_ + "addressbook-query":
        lim = root.find(CR_ + "limit")
        n = None
        if lim is not None:
            nr = lim.find(CR_ + "nresults")
            n = int(nr.text) if nr is not None and (nr.text or "").strip().isdigit() else None
        hits = [(nm, m) for nm, m in ac.members.items() if _match(m[2], root)]
        if n is not None:
            hits = hits[:n]
        return dav_multistatus(dav_response(dav_href(*base, nm), want, props_member(u, m, role, ver)) for nm, m in hits)
    if root.tag == D_ + "sync-collection":
        from ..events.dav import sync_load
        te = root.find(D_ + "sync-token")
        tok = (te.text or "").strip() if te is not None else ""
        lvl = root.find(D_ + "sync-level")
        if lvl is not None and (lvl.text or "").strip() not in ("1", ""):
            raise DavError(403, "Only sync-level 1", "<D:number-of-matches-within-limits/>")
        old = None
        if tok:
            old = sync_load(c, u, book["key"], tok)
            if old is None:
                raise DavError(403, "Unknown sync-token", "<D:valid-sync-token/>")
        sync_save(c, u, ac)
        new = ac.state()
        changed = [nm for nm in ac.members if old is None or old.get(nm) != new[nm]]
        gone = [nm for nm in (old or {}) if nm not in new]

        def gen():
            for nm in changed:
                yield dav_response(dav_href(*base, nm), want, props_member(u, ac.members[nm], role, ver))
            for nm in gone:
                yield f"<D:response><D:href>{_xe(dav_href(*base, nm))}</D:href><D:status>HTTP/1.1 404 Not Found</D:status></D:response>"
        return dav_multistatus(gen(), f"<D:sync-token>{_xe(ac.token)}</D:sync-token>")
    raise DavError(403, "Unsupported report", "<D:supported-report/>")


def ab_put(c, u, book, name):
    if book["role"] not in ("owner", "edit"):
        raise DavError(403, "Read only", "<D:need-privileges/>")
    ct = (request.content_type or "text/vcard").lower()
    if "vcard" not in ct and "directory" not in ct:
        raise DavError(415, "Expected text/vcard", "<CR:supported-address-data/>")
    raw = dav_body()
    if len(raw) > DAV_MAX_BODY:
        raise DavError(413, "Too large", "<CR:max-resource-size/>")
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise DavError(400, "The contact must be UTF-8") from None
    try:
        v = parse_vcard(text)
    except BadInput as e:
        raise DavError(400, str(e), "<CR:valid-address-data/>") from None
    except (ValueError, TypeError, KeyError, IndexError):
        raise DavError(400, "The contact could not be read", "<CR:valid-address-data/>") from None
    if not v["uid"]:
        raise DavError(400, "UID missing", "<CR:valid-address-data/>")
    have = card_now(c, book, name)
    inm, im = request.headers.get("If-None-Match", "").strip(), request.headers.get("If-Match", "").strip()
    if have and inm == "*":
        raise DavError(412, "The resource exists already")
    if im and (not have or (im != "*" and have[1] not in [x.strip() for x in im.split(",")])):
        raise DavError(412, "The resource was changed meanwhile")
    f = {k: (json.dumps(v[k], ensure_ascii=False) if isinstance(v[k], list) else v[k]) for k in
         ("kind", "fn", "given", "family", "middle", "prefix", "suffix", "nickname", "org", "dept", "title", "emails", "phones",
          "addresses", "urls", "bday", "anniversary", "note", "groups", "photo")}
    if have:
        if v["uid"] != have[0]["uid"]:
            if c.execute("SELECT 1 FROM contacts WHERE book_id=? AND uid=? AND id!=?", (book["id"], v["uid"], have[0]["id"])).fetchone():
                raise DavError(403, "This UID exists already", "<CR:no-uid-conflict/>")
            f["uid"] = v["uid"]
        contact_store(c, u["id"], book["id"], f, cid=have[0]["id"], extra=v["extra"], version=v["version"])
        c.commit()
        return Response(status=204)
    dup = c.execute("SELECT href FROM contacts WHERE book_id=? AND uid=?", (book["id"], v["uid"])).fetchone()
    if dup:
        href = dav_href("addressbooks", u["username"], book["key"], dup[0])
        raise DavError(403, "This UID exists already", f"<CR:no-uid-conflict><D:href>{_xe(href)}</D:href></CR:no-uid-conflict>")
    contact_store(c, u["id"], book["id"], f, uid_=v["uid"], href=name, extra=v["extra"], version=v["version"])
    c.commit()
    r = Response(status=201)
    r.headers["Location"] = dav_href("addressbooks", u["username"], book["key"], name)
    return r


def abdav(m, c, u, p):
    kind, key, name = ab_path(p, u)
    want_props = None
    if m == "PROPFIND":
        want_props = dav_propfind_req(dav_body())
        deep = request.headers.get("Depth", "1").strip().lower() in ("1", "infinity")
    if kind in ("abroot", "abhome"):
        if m == "PROPFIND":
            out = [dav_response(ab_home_href(u) if kind == "abhome" else dav_href("addressbooks", coll=True), want_props, props_home(u))]
            if deep:
                if kind == "abroot":
                    out.append(dav_response(ab_home_href(u), want_props, props_home(u)))
                else:
                    for b in ab_books(c, u).values():
                        out.append(dav_response(dav_href("addressbooks", u["username"], b["key"], coll=True), want_props,
                                                props_book(c, u, b, lambda b=b: ab_coll(c, u, b))))
            return dav_multistatus(out)
        if m == "REPORT":
            return dav_multistatus([])
        if m in ("GET", "HEAD"):
            return Response(f"{APP_NAME} CardDAV\n", 200, content_type="text/plain; charset=utf-8")
        raise DavError(403, "Create address books in the app", "<D:resource-must-be-null/>")
    book = ab_books(c, u).get(key)
    if not book:
        raise DavError(404, "Not found")
    if m == "PROPFIND":
        if kind == "book":
            ac = ab_coll(c, u, book)
            first = dav_response(dav_href("addressbooks", u["username"], key, coll=True), want_props, props_book(c, u, book, lambda: ac))

            def gen():
                yield first
                if deep:
                    for nm, mm in ac.members.items():
                        yield dav_response(dav_href("addressbooks", u["username"], key, nm), want_props, props_member(u, mm, book["role"]))
            return dav_multistatus(gen())
        have = card_now(c, book, name)
        if not have:
            raise DavError(404, "Not found")
        return dav_multistatus([dav_response(dav_href("addressbooks", u["username"], key, name), want_props,
                                             props_member(u, (have[0]["id"], have[1], have[2], have[0]), book["role"]))])
    if m == "REPORT":
        if kind != "book":
            raise DavError(403, "Only on an address book", "<D:supported-report/>")
        return ab_report(c, u, book, dav_body())
    if m in ("GET", "HEAD"):
        if kind != "card":
            return Response(f"{APP_NAME} CardDAV\n", 200, content_type="text/plain; charset=utf-8")
        have = card_now(c, book, name)
        if not have:
            raise DavError(404, "Not found")
        r = Response("" if m == "HEAD" else have[2], 200, content_type="text/vcard; charset=utf-8")
        r.headers["ETag"] = have[1]
        r.headers["Last-Modified"] = email.utils.format_datetime(parse_iso(have[0]["updated_at"]).astimezone(timezone.utc), usegmt=True)
        if m == "HEAD":
            r.headers["Content-Length"] = str(len(have[2].encode("utf-8")))
        return r
    if m == "PUT":
        if kind != "card":
            raise DavError(405, "PUT works on a contact inside an address book")
        return ab_put(c, u, book, name)
    if m == "DELETE":
        if kind != "card":
            raise DavError(403, "Address books are deleted in the app")
        if book["role"] not in ("owner", "edit"):
            raise DavError(403, "Read only", "<D:need-privileges/>")
        have = card_now(c, book, name)
        if not have:
            raise DavError(404, "Not found")
        im = request.headers.get("If-Match", "").strip()
        if im and im != "*" and have[1] not in [x.strip() for x in im.split(",")]:
            raise DavError(412, "The resource was changed meanwhile")
        from ..contacts.model import book_touch
        from ..core.db import bump
        c.execute("DELETE FROM contacts WHERE id=?", (have[0]["id"],))
        book_touch(c, book["id"])
        bump(c)
        c.commit()
        return Response(status=204)
    if m == "PROPPATCH":
        root = dav_xml(dav_body())
        names = [x.tag for s_ in root for pr in s_ if pr.tag == D_ + "prop" for x in pr if isinstance(x.tag, str)]
        href = dav_href("addressbooks", u["username"], key, *([name] if name else []), coll=not name)
        return dav_multistatus([f"<D:response><D:href>{_xe(href)}</D:href><D:propstat><D:prop>{''.join(_el(n) for n in names)}"
                                "</D:prop><D:status>HTTP/1.1 403 Forbidden</D:status></D:propstat></D:response>"])
    raise DavError(405, "Method not allowed")
