"""2.55.0 E (#1455): the adapters of the newsletter services -- one small interface, three services.

    a = nwl_adapter(kind, url, secret, allow)
    a.check()                         -> None (raises NwlError: auth | network | redirect | answer | http ...)
    a.lists()                         -> [{"id": str, "name": str}]
    a.create_list(name, doi)          -> {"id", "name"}
    a.members(list_id)                -> {email: {"ref": str, "name": str, "state": active | pending | unsub | bounce}}
    a.add(list_id, email, name, confirmed, known=None) -> (state, ref)  never subscribes an address the service blocks
    a.rename(list_id, ref, email, name)
    a.remove(list_id, ref, email)

Kalmido never sends mail itself: the service sends, runs the double opt-in, the unsubscribe link and the bounces; members()
is how unsubscriptions, bounces and confirmed opt-ins come back. listmonk is tested against a real container (6.2.0);
Brevo and CleverReach follow their public API documentation and are NOT tested against the real services (the app shows
them as a preview). Every request goes through the SSRF guard of the calendar subscriptions (public addresses; an
internal host only when an admin allowed it), without redirects, with a timeout and a size limit."""
import base64
import json
import urllib.error
import urllib.parse
import urllib.request

NWL_KINDS = ("listmonk", "brevo", "cleverreach")
NWL_PREVIEW = ("brevo", "cleverreach")  # untested against the real service
NWL_DEFAULT_URL = {"brevo": "https://api.brevo.com", "cleverreach": "https://rest.cleverreach.com"}
NWL_TIMEOUT = 20
NWL_JSON_MAX = 16 * 1024 * 1024
NWL_PAGE = 500
NWL_PAGES = 400  # pages per list at most (200 000 addresses)


class NwlError(Exception):
    """A failure talking to the service: code + a short detail (an HTTP status); never access data or content."""
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, str(detail)[:20]

    def stored(self):
        return self.code + (":" + self.detail if self.detail else "")


class _Base:
    kind = ""

    def __init__(self, url, secret, allow):
        self.url = url.rstrip("/")
        self.secret = secret if isinstance(secret, dict) else {}
        self.allow = allow

    def _headers(self):
        return {}

    def _req(self, method, path, data=None, headers=None, form=False, ok404=False):
        """JSON request -> (status, parsed answer). 404 with ok404 -> (404, None)."""
        from ..calendars.subscriptions import CalError, _cal_opener
        hdr = {"Accept": "application/json", "User-Agent": "Kalmido"}
        hdr.update(headers if headers is not None else self._headers())
        body = None
        if data is not None:
            if form:
                body = urllib.parse.urlencode(data).encode()
                hdr["Content-Type"] = "application/x-www-form-urlencoded"
            else:
                body = json.dumps(data).encode()
                hdr["Content-Type"] = "application/json"
        req = urllib.request.Request(self.url + path, data=body, headers=hdr, method=method)
        try:
            with _cal_opener(self.allow).open(req, timeout=NWL_TIMEOUT) as resp:
                raw = resp.read(NWL_JSON_MAX + 1)
                if len(raw) > NWL_JSON_MAX:
                    raise NwlError("answer")
                status = resp.status
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read(65536) if e.fp else b""
            e.close()
            if status == 404 and ok404:
                return 404, None
            if status in (401, 403):
                raise NwlError("auth", status) from None
            if 300 <= status < 400:
                raise NwlError("redirect", status) from None
            if status == 409:
                return 409, None
            if status == 429:
                raise NwlError("rate", status) from None
            raise NwlError("http", status) from None
        except urllib.error.URLError as e:
            raise NwlError(e.reason.code if isinstance(e.reason, CalError) else "network") from None
        except CalError as e:
            raise NwlError(e.code) from None
        except (TimeoutError, OSError):
            raise NwlError("network") from None
        if not raw.strip():
            return status, None
        try:
            return status, json.loads(raw)
        except ValueError:
            raise NwlError("answer") from None


def _as_list(v):
    return v if isinstance(v, list) else []


def _s(v):
    return "" if v is None else str(v)


class Listmonk(_Base):
    """listmonk >= 4 (API user + token: Authorization: token user:token). Tested against 6.2.0."""
    kind = "listmonk"

    def _headers(self):
        return {"Authorization": f"token {self.secret.get('user', '')}:{self.secret.get('token', '')}"}

    @staticmethod
    def _data(ans):
        if not isinstance(ans, dict):
            raise NwlError("answer")
        return ans.get("data")

    def check(self):
        _, ans = self._req("GET", "/api/health")
        if self._data(ans) is not True:
            raise NwlError("answer")

    def lists(self):
        _, ans = self._req("GET", "/api/lists?minimal=true&per_page=all")
        d = self._data(ans)
        rows = d.get("results") if isinstance(d, dict) else d
        return [{"id": _s(r.get("id")), "name": _s(r.get("name"))} for r in _as_list(rows) if isinstance(r, dict) and r.get("id")]

    def create_list(self, name, doi):
        _, ans = self._req("POST", "/api/lists", {"name": name, "type": "private", "optin": "double" if doi else "single",
                                                  "description": "Kalmido"})
        d = self._data(ans)
        if not isinstance(d, dict) or not d.get("id"):
            raise NwlError("answer")
        return {"id": _s(d["id"]), "name": _s(d.get("name"))}

    def _bounced(self):
        out, page = set(), 1
        while page <= NWL_PAGES:
            _, ans = self._req("GET", f"/api/bounces?per_page={NWL_PAGE}&page={page}")
            d = self._data(ans) or {}
            rows = _as_list(d.get("results") if isinstance(d, dict) else None)
            out |= {_s(r.get("email")).lower() for r in rows if isinstance(r, dict)}
            if len(rows) < NWL_PAGE:
                break
            page += 1
        return out

    def _state(self, sub, lid, bounced=None):
        if sub.get("status") == "blocklisted":
            if bounced is None:
                bounced = self._bounced()
            return "bounce" if _s(sub.get("email")).lower() in bounced else "unsub"
        for li in _as_list(sub.get("lists")):
            if isinstance(li, dict) and _s(li.get("id")) == _s(lid):
                st = li.get("subscription_status")
                return "unsub" if st == "unsubscribed" else "pending" if st == "unconfirmed" else "active"
        return ""  # not on the list

    def members(self, lid):
        out, page, bounced = {}, 1, None
        while page <= NWL_PAGES:
            _, ans = self._req("GET", f"/api/subscribers?list_id={int(lid)}&per_page={NWL_PAGE}&page={page}")
            d = self._data(ans) or {}
            rows = _as_list(d.get("results") if isinstance(d, dict) else None)
            for r in rows:
                if not isinstance(r, dict) or not r.get("email"):
                    continue
                if r.get("status") == "blocklisted" and bounced is None:
                    bounced = self._bounced()
                st = self._state(r, lid, bounced)
                if st:
                    out[_s(r["email"]).lower()] = {"ref": _s(r.get("id")), "name": _s(r.get("name")), "state": st}
            if len(rows) < NWL_PAGE:
                break
            page += 1
        return out

    def _find(self, email):
        q = urllib.parse.quote(f"subscribers.email='{email}'")  # the address is checked (no quotes) before it gets here
        _, ans = self._req("GET", f"/api/subscribers?per_page=1&query={q}")
        rows = _as_list((self._data(ans) or {}).get("results"))
        return rows[0] if rows and isinstance(rows[0], dict) else None

    def add(self, lid, email, name, confirmed, known=None):
        st, ans = self._req("POST", "/api/subscribers", {"email": email, "name": name or email, "status": "enabled",
                                                         "lists": [int(lid)], "preconfirm_subscriptions": bool(confirmed)})
        if st != 409:
            d = self._data(ans)
            if not isinstance(d, dict) or not d.get("id"):
                raise NwlError("answer")
            return ("active" if confirmed else "pending"), _s(d["id"])
        sub = self._find(email)  # the address is known to the service already (another list, an earlier run)
        if not sub:
            raise NwlError("answer")
        state = self._state(sub, lid)
        if sub.get("status") == "blocklisted" or state == "unsub":
            return state, _s(sub.get("id"))  # blocked / unsubscribed at the service: never subscribed again
        if state in ("active", "pending"):
            return state, _s(sub.get("id"))
        # listmonk's "add" would also re-subscribe an unsubscribed address -- checked above, so it only adds new ones
        self._req("PUT", "/api/subscribers/lists", {"ids": [int(sub["id"])], "action": "add", "target_list_ids": [int(lid)],
                                                    "status": "confirmed" if confirmed else "unconfirmed"})
        if not confirmed:
            self._req("POST", f"/api/subscribers/{int(sub['id'])}/optin", {})
        if name and sub.get("name") != name:
            self.rename(lid, sub["id"], email, name)
        return ("active" if confirmed else "pending"), _s(sub.get("id"))

    def rename(self, lid, ref, email, name):
        _, ans = self._req("GET", f"/api/subscribers/{int(ref)}")
        sub = self._data(ans)
        if not isinstance(sub, dict):
            return
        # a PUT replaces the lists: without them listmonk drops every subscription, so the current ones go along
        # (their statuses stay as they are, also "unsubscribed")
        ids = [int(li["id"]) for li in _as_list(sub.get("lists")) if isinstance(li, dict) and li.get("id")]
        self._req("PUT", f"/api/subscribers/{int(ref)}", {"email": sub.get("email") or email, "name": name or email,
                                                         "status": sub.get("status") or "enabled", "lists": ids,
                                                         "attribs": sub.get("attribs") or {}, "preconfirm_subscriptions": False})

    def remove(self, lid, ref, email):
        if ref:
            self._req("PUT", "/api/subscribers/lists", {"ids": [int(ref)], "action": "remove", "target_list_ids": [int(lid)]})


class Brevo(_Base):
    """Brevo API v3 (header api-key). Written after the public documentation; NOT tested against the real service."""
    kind = "brevo"

    def _headers(self):
        return {"api-key": self.secret.get("token", "")}

    def check(self):
        _, ans = self._req("GET", "/v3/account")
        if not isinstance(ans, dict):
            raise NwlError("answer")

    def lists(self):
        out, off = [], 0
        for _ in range(NWL_PAGES):
            _, ans = self._req("GET", f"/v3/contacts/lists?limit=50&offset={off}")
            rows = _as_list((ans or {}).get("lists"))
            out += [{"id": _s(r.get("id")), "name": _s(r.get("name"))} for r in rows if isinstance(r, dict) and r.get("id")]
            if len(rows) < 50:
                break
            off += 50
        return out

    def create_list(self, name, doi):
        _, ans = self._req("GET", "/v3/contacts/folders?limit=50&offset=0")
        folders = [f for f in _as_list((ans or {}).get("folders")) if isinstance(f, dict) and f.get("id")]
        fid = next((f["id"] for f in folders if f.get("name") == "Kalmido"), None)
        if fid is None:
            _, f = self._req("POST", "/v3/contacts/folders", {"name": "Kalmido"})
            fid = (f or {}).get("id")
        _, ans = self._req("POST", "/v3/contacts/lists", {"name": name, "folderId": fid})
        if not isinstance(ans, dict) or not ans.get("id"):
            raise NwlError("answer")
        return {"id": _s(ans["id"]), "name": name}

    def _blocked(self):
        """Blocked addresses with their reason: hardBounce -> bounce, anything else -> unsub."""
        out, off = {}, 0
        for _ in range(NWL_PAGES):
            _, ans = self._req("GET", f"/v3/smtp/blockedContacts?limit=100&offset={off}")
            rows = _as_list((ans or {}).get("contacts"))
            for r in rows:
                if isinstance(r, dict) and r.get("email"):
                    code = (r.get("reason") or {}).get("code") if isinstance(r.get("reason"), dict) else ""
                    out[_s(r["email"]).lower()] = "bounce" if code == "hardBounce" else "unsub"
            if len(rows) < 100:
                break
            off += 100
        return out

    def _state(self, r, lid, blocked):
        email = _s(r.get("email")).lower()
        if r.get("emailBlacklisted"):
            return blocked.get(email, "unsub")
        if int(lid) in [int(x) for x in _as_list(r.get("listUnsubscribed")) if str(x).isdigit()]:
            return "unsub"
        return "active"

    def members(self, lid):
        out, off, blocked = {}, 0, None
        for _ in range(NWL_PAGES):
            _, ans = self._req("GET", f"/v3/contacts/lists/{int(lid)}/contacts?limit={NWL_PAGE}&offset={off}")
            rows = _as_list((ans or {}).get("contacts"))
            for r in rows:
                if not isinstance(r, dict) or not r.get("email"):
                    continue
                if r.get("emailBlacklisted") and blocked is None:
                    blocked = self._blocked()
                at = r.get("attributes") if isinstance(r.get("attributes"), dict) else {}
                out[_s(r["email"]).lower()] = {"ref": _s(r.get("id")), "state": self._state(r, lid, blocked or {}),
                                               "name": " ".join(x for x in (_s(at.get("FIRSTNAME")), _s(at.get("LASTNAME"))) if x)}
            if len(rows) < NWL_PAGE:
                break
            off += NWL_PAGE
        return out

    @staticmethod
    def _names(name):
        first, _, last = (name or "").partition(" ")
        return {"FIRSTNAME": first, "LASTNAME": last}

    def add(self, lid, email, name, confirmed, known=None):
        st, r = self._req("GET", f"/v3/contacts/{urllib.parse.quote(email)}", ok404=True)
        if st != 404 and isinstance(r, dict):
            state = self._state(r, lid, self._blocked() if r.get("emailBlacklisted") else {})
            if state in ("unsub", "bounce"):
                return state, _s(r.get("id"))
        # updateEnabled: an existing contact only gets the list (emailBlacklisted is not sent, so it stays as it is)
        self._req("POST", "/v3/contacts", {"email": email, "attributes": self._names(name), "listIds": [int(lid)], "updateEnabled": True})
        return "active", _s(r.get("id")) if isinstance(r, dict) else ""

    def rename(self, lid, ref, email, name):
        self._req("PUT", f"/v3/contacts/{urllib.parse.quote(email)}", {"attributes": self._names(name)})

    def remove(self, lid, ref, email):
        self._req("POST", f"/v3/contacts/lists/{int(lid)}/contacts/remove", {"emails": [email]})


class CleverReach(_Base):
    """CleverReach REST v3 (OAuth client credentials -> bearer token). Written after the public documentation; NOT tested
    against the real service. Lists are "groups", receivers are deactivated on unsubscription."""
    kind = "cleverreach"

    def __init__(self, url, secret, allow):
        super().__init__(url, secret, allow)
        self._tok = None

    def _headers(self):
        if self._tok is None:
            basic = base64.b64encode(f"{self.secret.get('user', '')}:{self.secret.get('token', '')}".encode()).decode()
            _, ans = self._req("POST", "/oauth/token.php", {"grant_type": "client_credentials"}, form=True,
                               headers={"Authorization": f"Basic {basic}"})
            tok = (ans or {}).get("access_token") if isinstance(ans, dict) else None
            if not tok:
                raise NwlError("auth")
            self._tok = str(tok)
        return {"Authorization": f"Bearer {self._tok}"}

    def check(self):
        self._req("GET", "/v3/groups.json")

    def lists(self):
        _, ans = self._req("GET", "/v3/groups.json")
        return [{"id": _s(r.get("id")), "name": _s(r.get("name"))} for r in _as_list(ans) if isinstance(r, dict) and r.get("id")]

    def create_list(self, name, doi):
        _, ans = self._req("POST", "/v3/groups.json", {"name": name})
        if not isinstance(ans, dict) or not ans.get("id"):
            raise NwlError("answer")
        return {"id": _s(ans["id"]), "name": _s(ans.get("name") or name)}

    @staticmethod
    def _state(r):
        if r.get("bounced") not in (None, 0, "0", False):
            return "bounce"
        if r.get("deactivated") not in (None, 0, "0", False):
            return "unsub"
        return "active" if r.get("activated") not in (None, 0, "0", False) else "pending"

    def members(self, lid):
        out = {}
        for page in range(NWL_PAGES):
            _, ans = self._req("GET", f"/v3/groups.json/{int(lid)}/receivers?pagesize={NWL_PAGE}&page={page}")
            rows = _as_list(ans)
            for r in rows:
                if isinstance(r, dict) and r.get("email"):
                    ga = r.get("global_attributes") if isinstance(r.get("global_attributes"), dict) else {}
                    out[_s(r["email"]).lower()] = {"ref": _s(r.get("id")), "state": self._state(r),
                                                   "name": " ".join(x for x in (_s(ga.get("firstname")), _s(ga.get("lastname"))) if x)}
            if len(rows) < NWL_PAGE:
                break
        return out

    def add(self, lid, email, name, confirmed, known=None):
        import time
        first, _, last = (name or "").partition(" ")
        now = int(time.time())
        self._req("POST", f"/v3/groups.json/{int(lid)}/receivers/upsert",
                  [{"email": email, "registered": now, "activated": now if confirmed else 0, "source": "Kalmido",
                    "global_attributes": {"firstname": first, "lastname": last}}])
        return ("active" if confirmed else "pending"), ""

    def rename(self, lid, ref, email, name):
        first, _, last = (name or "").partition(" ")
        self._req("POST", f"/v3/groups.json/{int(lid)}/receivers/upsert",
                  [{"email": email, "global_attributes": {"firstname": first, "lastname": last}}])

    def remove(self, lid, ref, email):
        self._req("DELETE", f"/v3/groups.json/{int(lid)}/receivers/{urllib.parse.quote(email)}", ok404=True)


_CLS = {"listmonk": Listmonk, "brevo": Brevo, "cleverreach": CleverReach}


def nwl_adapter(kind, url, secret, allow):
    if kind not in _CLS:
        raise NwlError("kind")
    return _CLS[kind](url or NWL_DEFAULT_URL.get(kind, ""), secret, allow)
