"""2.154.0 B (#1960): e-invoices over the Peppol network, through the office's own account at a Peppol access point
provider (Kalmido is no access point and charges nothing: the provider bills its customer directly).

Peppol ids "<scheme>:<id>" (scheme = an ICD / EAS code such as 0088 GLN, 0208 Belgian enterprise number, 9930 German VAT
id, 0204 Leitweg-ID): the sender's in office_peppol.sender_id (an organisation's office or the personal office of a person
without one), the recipient's in clients.peppol_id. pep_id_clean checks the format (known codes, check digits of 0088,
0208, 0192); pep_id_suggest proposes one from a VAT id where it is unambiguous (DE -> 9930:DE..., BE -> 0208:<number>).

The connection (office_peppol, one row per office area; admins of the area, without an organisation the person): provider
(storecove | custom = an own endpoint that speaks the small protocol of docs/OFFICE.md), its URL (custom), the account id
(Storecove: the legal entity), test mode, the API key sealed with the server key (accounts/login.py seal, the purpose
names the area; never sent back, only "set"; a new provider or URL drops it unless a new key comes along). Requests go
through calendars/subscriptions.py cal_http: the SSRF guard (no internal address unless the host is allowed like a
calendar), a time limit, no redirect to another host with the key. Without a provider nothing is offered.

Sending (POST /api/office/docs/<id>/peppol): a finalised invoice / credit note, e-invoices on, the connection set up, a
Peppol id at both ends; the recipient is looked up first (reachable in the network). The UBL (office/einvoice.py
ein_ubl_build: Peppol BIS Billing 3.0, XRechnung UBL for a document in the XRechnung format) goes to the provider, one row
in office_peppol_sends records it (status sending -> sent -> delivered | rejected | error, the provider's reference, the
message of a failure), the office log has peppol_send / peppol_status. Never twice: a document with a send that is not
failed or rejected answers 409; after a failure or a rejection "send again" is a new row. The status is fetched when the
document's Peppol view opens or on "refresh" (no polling in the background). Agents never send (office_gate refuses
their tokens); they read the status in the document (doc_public "peppol"). Receiving invoices is not part of 2.154."""
import base64
import hashlib
import json
import os
import re
import urllib.parse
import uuid

from flask import jsonify, request

from ..core.config import app
from ..core.db import body, bump, db, iso, now_utc
from ..core.i18n import N_, tr
from ..core.access import Denied
from ..personal.timetrack import BadInput
from .model import office_feature, office_gate, office_org, office_role, pb_cl_sql

PEP_ICD = frozenset((
    "0002 0007 0009 0037 0060 0088 0096 0097 0106 0130 0135 0142 0147 0151 0154 0158 0170 0183 0184 0188 0190 0191 0192 0193 "
    "0194 0195 0196 0198 0199 0200 0201 0202 0203 0204 0205 0208 0209 0210 0211 0212 0213 0215 0216 0217 0218 0219 0220 0221 "
    "0225 0230 0235 0240 9901 9910 9913 9914 9915 9918 9919 9920 9922 9923 9924 9925 9926 9927 9928 9929 9930 9931 9932 9933 "
    "9934 9935 9936 9937 9938 9939 9940 9941 9942 9943 9944 9945 9946 9947 9948 9949 9950 9951 9952 9953 9957 9959").split())
PEP_FORMAT = {"0088": r"\d{13}", "0208": r"[01]\d{9}", "0192": r"\d{9}", "0007": r"\d{10}", "0060": r"\d{9}", "0009": r"\d{14}",
              "0002": r"\d{9}", "0106": r"\d{8}", "0190": r"\d{20}", "0151": r"\d{11}", "9930": r"DE\d{9}", "9925": r"BE[01]\d{9}",
              "9944": r"NL\d{9}B\d{2}", "9914": r"ATU\d{8}", "9957": r"FR[0-9A-Z]{2}\d{9}",
              "0204": r"\d{2,12}(-[0-9A-Z]{1,30})?-\d{2}"}
PEP_PROVIDERS = {"storecove": {"name": "Storecove", "url": "https://api.storecove.com/api/v2", "account": True},
                 "custom": {"name": N_("Own endpoint (URL)"), "url": "", "account": False}}
STORECOVE_URL = os.environ.get("KALMIDO_PEPPOL_STORECOVE_URL", "").strip() or PEP_PROVIDERS["storecove"]["url"]  # tests: a stub
# Storecove names its receiver schemes; the ICD codes they stand for (the rest goes as the ICD code)
SC_SCHEME = {"9930": "DE:VAT", "0204": "DE:LWID", "0208": "BE:EN", "9925": "BE:VAT", "0088": "GLN", "0106": "NL:KVK", "0190": "NL:OINO",
             "9944": "NL:VAT", "0192": "NO:ORG", "0007": "SE:ORGNR", "0009": "FR:SIRET", "0002": "FR:SIRENE", "9914": "AT:VAT",
             "0184": "DK:DIGST", "0151": "AU:ABN", "0060": "DUNS"}
PEP_STATES = ("sending", "sent", "delivered", "rejected", "error")
PEP_LIVE = ("sending", "sent", "delivered")  # a send in one of these blocks another one (unique index office_peppol_sends_live)
PEP_TIMEOUT = 20
PEP_STALE_MIN = 15
PEP_MAX_BYTES = 1024 * 1024
PEP_ERR = {"config": N_("The Peppol connection is not set up completely"),
           "auth": N_("The provider refused the API key"),
           "not_found": N_("The provider does not know this document or account"),
           "timeout": N_("The provider did not answer in time"),
           "network": N_("The provider cannot be reached"),
           "tls": N_("The provider's certificate is not valid"),
           "redirect": N_("The provider sent a redirect that is not followed"),
           "http": N_("The provider answered with an error"),
           "answer": N_("The provider's answer could not be read"),
           "unreachable": N_("The recipient cannot receive e-invoices over the Peppol network"),
           "too_large": N_("The provider's answer is too large")}
PEP_NEED = {"feature": N_("E-invoices are switched off in this office"),
               "kind": N_("Only finalised invoices and credit notes go over the Peppol network"),
               "setup": N_("Set up the Peppol connection in the office settings (your own account at a Peppol access point provider)"),
               "key": N_("The API key of the Peppol provider is missing"),
               "sender": N_("Your own Peppol ID is missing (office settings)"),
               "client": N_("The document has no client"),
               "receiver": N_("The client has no Peppol ID"),
               "reference": N_("Peppol needs a buyer reference, an order number or a customer number (client or document)")}


class PepError(Exception):
    """A provider failure: code (a PEP_ERR key) + a short detail (an HTTP status, the provider's own words cut short)."""
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, str(detail or "")[:300]

    def text(self, lg=None):
        return tr(PEP_ERR.get(self.code) or PEP_ERR["http"], lg=lg) + (f" ({self.detail})" if self.detail else "")


# ---------------------------------------------------------------- Peppol ids
def _mod97_be(n):
    return 97 - int(n[:8]) % 97 == int(n[8:])


def _gln_ok(n):
    s = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(n[:12]))
    return (10 - s % 10) % 10 == int(n[12])


def _no_org_ok(n):
    s = sum(int(d) * w for d, w in zip(n[:8], (3, 2, 7, 6, 5, 4, 3, 2)))
    k = 11 - s % 11
    return (0 if k == 11 else k) == int(n[8]) and k != 10


def pep_id_clean(v):
    """'<scheme>:<id>' -> the normalised id ('' for empty); BadInput for an unknown scheme or a wrong id of a known one.
    Accepts the participant form "iso6523-actorid-upis::0088:..." and spaces; letters of VAT-based ids upper case."""
    s = re.sub(r"\s+", "", str(v or ""))
    if not s:
        return ""
    s = re.sub(r"(?i)^iso6523-actorid-upis::", "", s)
    m = re.fullmatch(r"(\d{4}):([A-Za-z0-9._\-:/]{1,80})", s)
    if not m or m.group(1) not in PEP_ICD:
        raise BadInput(tr("Invalid Peppol ID: use scheme:number, e.g. 0088:4000001000005 or 9930:DE123456789"))
    sch, ident = m.group(1), m.group(2)
    if sch in ("9930", "9925", "9944", "9914", "9957", "0204"):
        ident = ident.upper()
    fmt = PEP_FORMAT.get(sch)
    ok = re.fullmatch(fmt, ident) if fmt else True
    if ok and sch == "0208":
        ok = _mod97_be(ident)
    elif ok and sch == "0088":
        ok = _gln_ok(ident)
    elif ok and sch == "0192":
        ok = _no_org_ok(ident)
    if not ok:
        raise BadInput(tr("Invalid Peppol ID: the number does not fit scheme {0}", sch))
    return f"{sch}:{ident}"


def pep_id_suggest(vat_id):
    """A Peppol id from a VAT id where it is unambiguous: DE -> 9930:DE<9 digits>, BE -> 0208:<enterprise number>; else ''."""
    v = re.sub(r"[\s.\-]", "", str(vat_id or "")).upper()
    for cand in ((f"9930:{v}" if re.fullmatch(r"DE\d{9}", v) else ""), (f"0208:{v[2:]}" if re.fullmatch(r"BE[01]\d{9}", v) else "")):
        if cand:
            try:
                return pep_id_clean(cand)
            except BadInput:
                return ""
    return ""


# ---------------------------------------------------------------- the connection of an office area
def _purpose(oid):
    return f"office-peppol:{int(oid)}"


def pep_conf(c, oid):
    """The connection row of office area oid as a dict (empty values when there is none); secret = the sealed key."""
    r = c.execute("SELECT * FROM office_peppol WHERE org_id=?", (oid,)).fetchone()
    d = {"provider": "", "endpoint_url": "", "account": "", "sandbox": 1, "sender_id": "", "secret": "", "check_state": "", "checked_at": None}
    if r:
        d.update({k: r[k] for k in d if k in r.keys()})
    return d


def pep_key(c, oid, conf):
    from ..accounts.login import unseal
    if not conf.get("secret"):
        return ""
    try:
        return unseal(c, _purpose(oid), conf["secret"])
    except Exception:  # noqa: BLE001 -- another server key / a broken value: as if none were set
        return ""


def _company_vat(c, oid):
    from .ledger import ofx_company
    return (ofx_company(c, oid) or {}).get("vat_id") or ""


def pep_public(c, oid, admin):
    conf = pep_conf(c, oid)
    out = {"provider": conf["provider"], "endpoint_url": conf["endpoint_url"], "account": conf["account"], "sandbox": int(conf["sandbox"] or 0),
           "sender_id": conf["sender_id"], "key_set": bool(conf["secret"]), "check_state": conf["check_state"],
           "check_text": tr(PEP_ERR[conf["check_state"]]) if conf["check_state"] in PEP_ERR else "", "checked_at": conf["checked_at"],
           "ready": bool(conf["provider"] and conf["secret"] and conf["sender_id"]), "can_edit": bool(admin),
           "sender_suggest": "" if conf["sender_id"] else pep_id_suggest(_company_vat(c, oid)),
           "providers": [{"id": k, "name": tr(v["name"]), "needs_url": not v["url"], "needs_account": v["account"]} for k, v in PEP_PROVIDERS.items()]}
    return out


def _url_ok(c, u):
    """https (http only for a host the admin allowed like a calendar host, e.g. a bridge in the own network)."""
    p = urllib.parse.urlsplit(u)
    if p.scheme not in ("http", "https") or not p.hostname or p.username or p.password or p.query or p.fragment:
        return False
    if p.scheme == "https":
        return True
    from ..calendars.subscriptions import cal_allow, cal_host_allowed
    try:
        port = p.port or 80
    except ValueError:
        return False
    return cal_host_allowed(cal_allow(c), p.hostname, port)


def pep_save(c, oid, uid, b):
    """PUT body {provider?, endpoint_url?, account?, sandbox?, sender_id?, api_key?} -> the stored row. An empty api_key keeps
    the stored key -- unless the provider or the URL changes: a key only ever goes to where it was entered for."""
    from ..accounts.login import seal
    known = {"provider", "endpoint_url", "account", "sandbox", "sender_id", "api_key"}
    bad = set(b) - known
    if bad:
        raise BadInput(tr("Invalid value: {0}", sorted(bad)[0]))
    cur = pep_conf(c, oid)
    new = dict(cur)
    if "provider" in b:
        v = str(b["provider"] or "").strip()
        if v and v not in PEP_PROVIDERS:
            raise BadInput(tr("Invalid value: {0}", "provider"))
        new["provider"] = v
    if "endpoint_url" in b:
        v = str(b["endpoint_url"] or "").strip().rstrip("/")
        if v and (len(v) > 300 or not _url_ok(c, v)):
            raise BadInput(tr("Invalid value: {0}", "endpoint_url"))
        new["endpoint_url"] = v
    if "account" in b:
        v = str(b["account"] or "").strip()
        if len(v) > 80 or (v and not re.fullmatch(r"[A-Za-z0-9._\-]+", v)):
            raise BadInput(tr("Invalid value: {0}", "account"))
        new["account"] = v
    if "sandbox" in b:
        new["sandbox"] = 1 if b["sandbox"] in (1, True, "1", "true") else 0
    if "sender_id" in b:
        new["sender_id"] = pep_id_clean(b["sender_id"])
    if new["provider"] != "custom":
        new["endpoint_url"] = ""
    moved = new["provider"] != cur["provider"] or new["endpoint_url"] != cur["endpoint_url"]
    key = b.get("api_key")
    if key is not None and not isinstance(key, str):
        raise BadInput(tr("Invalid value: {0}", "api_key"))
    key = (key or "").strip()
    if len(key) > 2000:
        raise BadInput(tr("Invalid value: {0}", "api_key"))
    if key:
        new["secret"] = seal(c, _purpose(oid), key)
    elif moved or not new["provider"]:
        new["secret"] = ""
    if new != cur:
        new["check_state"], new["checked_at"] = "", None
    ts = iso(now_utc())
    c.execute("INSERT INTO office_peppol(org_id, provider, endpoint_url, account, sandbox, sender_id, secret, check_state, checked_at, updated_by, updated_at) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(org_id) DO UPDATE SET provider=excluded.provider, endpoint_url=excluded.endpoint_url, "
              "account=excluded.account, sandbox=excluded.sandbox, sender_id=excluded.sender_id, secret=excluded.secret, "
              "check_state=excluded.check_state, checked_at=excluded.checked_at, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
              (oid, new["provider"], new["endpoint_url"], new["account"], new["sandbox"], new["sender_id"], new["secret"], new["check_state"],
               new["checked_at"], uid, ts))
    from .ledger import ofx_log
    ofx_log(c, oid, "peppol_setup", target="settings", detail={k: new[k] for k in ("provider", "endpoint_url", "account", "sandbox", "sender_id")}
            | {"key_set": bool(new["secret"]), **({"key_changed": 1} if key else {})})
    return new


# ---------------------------------------------------------------- the providers (adapters)
def _http(c, url, method="GET", data=None, headers=None):
    """(status, json or text) through the SSRF guard of the calendars (a 404 is (404, None))."""
    from ..calendars.subscriptions import CalError, cal_allow, cal_http
    try:
        st, _h, raw, _u = cal_http(url, method=method, body=data, headers=headers or {}, allow=cal_allow(c), max_bytes=PEP_MAX_BYTES,
                                   timeout=PEP_TIMEOUT, deadline=PEP_TIMEOUT * 2)
    except CalError as e:
        if e.code == "not_found":
            return 404, None
        raise PepError(e.code if e.code in PEP_ERR else "http", e.detail) from None
    try:
        return st, json.loads(raw.decode("utf-8")) if raw.strip() else {}
    except (UnicodeDecodeError, ValueError):
        raise PepError("answer") from None


class _Adapter:
    """send(ubl, sender_id, receiver_id, ref) -> {provider_id, status}; status(provider_id) -> {status, message};
    lookup(receiver_id) -> True / False; check() -> None or PepError."""
    def __init__(self, c, conf, key):
        self.c, self.conf, self.key = c, conf, key


class StorecoveAdapter(_Adapter):
    """Storecove API v2 (public OpenAPI description): Bearer key, POST /document_submissions with the raw UBL (parsed by
    Storecove, legalEntityId = the account), POST /discovery/receives, GET /document_submissions/<guid>/evidence/sending
    (there once the document went out), GET /legal_entities/<id> for the connection test. Test mode = a key of the
    provider's sandbox account (same address)."""
    def _h(self):
        return {"Authorization": "Bearer " + self.key, "Accept": "application/json", "Content-Type": "application/json"}

    @staticmethod
    def _rid(pid):
        sch, ident = pid.split(":", 1)
        return SC_SCHEME.get(sch, sch), ident

    def check(self):
        if not str(self.conf.get("account") or "").isdigit():
            raise PepError("config")
        _http(self.c, f"{STORECOVE_URL}/legal_entities/{self.conf['account']}", headers=self._h())

    def lookup(self, receiver_id):
        sch, ident = self._rid(receiver_id)
        st, j = _http(self.c, f"{STORECOVE_URL}/discovery/receives", "POST", json.dumps(
            {"documentTypes": ["invoice"], "network": "peppol", "metaScheme": "iso6523-actorid-upis", "scheme": sch, "identifier": ident}).encode(), self._h())
        return isinstance(j, dict) and j.get("code") == "OK"

    def send(self, ubl, sender_id, receiver_id, ref):
        if not str(self.conf.get("account") or "").isdigit():
            raise PepError("config")
        sch, ident = self._rid(receiver_id)
        doc = {"legalEntityId": int(self.conf["account"]), "idempotencyGuid": ref,
               "routing": {"eIdentifiers": [{"scheme": sch, "id": ident}], "emails": []},
               "document": {"documentType": "invoice", "rawDocumentData": {"document": base64.b64encode(ubl).decode(), "parse": True, "parseStrategy": "ubl"}}}
        st, j = _http(self.c, f"{STORECOVE_URL}/document_submissions", "POST", json.dumps(doc).encode(), self._h())
        if not isinstance(j, dict) or not j.get("guid"):
            raise PepError("answer")
        return {"provider_id": str(j["guid"])[:80], "status": "sent"}

    def status(self, provider_id):
        st, j = _http(self.c, f"{STORECOVE_URL}/document_submissions/{urllib.parse.quote(provider_id, safe='')}/evidence/sending", headers=self._h())
        if st == 404 or not isinstance(j, dict):
            return {"status": "sent", "message": ""}
        return {"status": "delivered", "message": ""}


class CustomAdapter(_Adapter):
    """An own endpoint (a bridge to any access point; protocol in docs/OFFICE.md): Bearer key; GET <url>/check;
    GET <url>/participants/<scheme>:<id> -> {reachable}; POST <url>/documents (the UBL, X-Peppol-Sender / -Receiver,
    Idempotency-Key, X-Peppol-Test) -> {id, status, message}; GET <url>/documents/<id> -> {status, message}."""
    def _h(self, extra=None):
        return {"Authorization": "Bearer " + self.key, "Accept": "application/json", **(extra or {})}

    def _base(self):
        u = str(self.conf.get("endpoint_url") or "")
        if not u:
            raise PepError("config")
        return u

    def check(self):
        _http(self.c, self._base() + "/check", headers=self._h())

    def lookup(self, receiver_id):
        st, j = _http(self.c, self._base() + "/participants/" + urllib.parse.quote(receiver_id, safe=":"), headers=self._h())
        return st != 404 and isinstance(j, dict) and bool(j.get("reachable"))

    def send(self, ubl, sender_id, receiver_id, ref):
        st, j = _http(self.c, self._base() + "/documents", "POST", ubl, self._h({
            "Content-Type": "application/xml", "X-Peppol-Sender": sender_id, "X-Peppol-Receiver": receiver_id, "Idempotency-Key": ref,
            "X-Peppol-Test": "1" if self.conf.get("sandbox") else "0"}))
        if not isinstance(j, dict) or not j.get("id"):
            raise PepError("answer")
        return {"provider_id": str(j["id"])[:80], "status": _state(j.get("status"), "sent"), "message": str(j.get("message") or "")[:300]}

    def status(self, provider_id):
        st, j = _http(self.c, self._base() + "/documents/" + urllib.parse.quote(provider_id, safe=""), headers=self._h())
        if st == 404 or not isinstance(j, dict):
            raise PepError("not_found")
        return {"status": _state(j.get("status"), "sent"), "message": str(j.get("message") or "")[:300]}


ADAPTERS = {"storecove": StorecoveAdapter, "custom": CustomAdapter}


def _state(v, dflt):
    v = str(v or "").lower()
    return v if v in ("sent", "delivered", "rejected", "error") else dflt


def pep_adapter(c, oid, conf=None):
    conf = conf or pep_conf(c, oid)
    key = pep_key(c, oid, conf)
    if conf["provider"] not in ADAPTERS or not key:
        raise PepError("config")
    return ADAPTERS[conf["provider"]](c, conf, key)


# ---------------------------------------------------------------- documents
def _client_pid(c, oid, client_id):
    if not client_id:
        return None
    r = c.execute(f"SELECT id, peppol_id, vat_id FROM clients WHERE id=? AND {pb_cl_sql(c, oid)}", (client_id,)).fetchone()
    return r


def pep_profile(model):
    """UBL profile of a document: XRechnung UBL for a document in the XRechnung format, else Peppol BIS Billing 3.0."""
    return "xrechnung" if (model.get("einvoice_format") or "") == "xrechnung" else "peppol"


def pep_ubl(c, oid, r, conf=None, receiver_id=None):
    """(UBL bytes, profile) of finalised document row r with the Peppol ids of the connection and the client."""
    from .einvoice import ein_ubl_build
    from .pdfweb import _model
    conf = conf or pep_conf(c, oid)
    model = _model(c, oid, r["id"])
    if receiver_id is None:
        cl = _client_pid(c, oid, r["client_id"])
        receiver_id = (cl["peppol_id"] if cl is not None else "") or ""
    prof = pep_profile(model)
    return ein_ubl_build(model, prof, sender_id=conf.get("sender_id") or "", receiver_id=receiver_id), prof


def pep_missing(c, oid, r, conf=None):
    """What stops sending document row r (list of PEP_NEED keys, empty = ready)."""
    from .ledger import ofx_locked
    conf = conf or pep_conf(c, oid)
    out = []
    if not office_feature(c, oid, "docs.einvoice"):
        out.append("feature")
    if r["kind"] not in ("invoice", "credit") or not ofx_locked(r) or r["status"] == "cancelled":  # 2.154.0 E (#1960): no cancelled ones
        out.append("kind")
    if not conf["provider"]:
        out.append("setup")
    elif not conf["secret"]:
        out.append("key")
    if not conf["sender_id"]:
        out.append("sender")
    cl = _client_pid(c, oid, r["client_id"])
    if cl is None:
        out.append("client")
    elif not cl["peppol_id"]:
        out.append("receiver")
    return out


def _send_public(x):
    return {"id": x["id"], "status": x["status"], "status_text": tr(PEP_STATUS_TXT.get(x["status"], x["status"])), "message": x["message"] or "",
            "receiver_id": x["receiver_id"], "provider": x["provider"], "provider_ref": x["provider_ref"], "profile": x["profile"],
            "created_at": x["created_at"], "updated_at": x["updated_at"], "checked_at": x["checked_at"]}


PEP_STATUS_TXT = {"sending": N_("Sending"), "sent": N_("Sent over Peppol"), "delivered": N_("Delivered over Peppol"),
                  "rejected": N_("Rejected by the recipient"), "error": N_("Peppol sending failed")}


def pep_sends(c, oid, did):
    return [dict(x) for x in c.execute("SELECT * FROM office_peppol_sends WHERE org_id=? AND doc_id=? ORDER BY id DESC", (oid, did))]


def pep_doc_extra(c, oid, d):
    """doc_public: the newest Peppol send of an invoice / credit note ({status, status_text, message, at} or None) --
    also what an agent reads (API v1 documents)."""
    if d.get("kind") not in ("invoice", "credit") or not d.get("id"):
        return
    x = c.execute("SELECT * FROM office_peppol_sends WHERE org_id=? AND doc_id=? ORDER BY id DESC LIMIT 1", (oid, d["id"])).fetchone()
    d["peppol"] = {"status": x["status"], "status_text": tr(PEP_STATUS_TXT.get(x["status"], x["status"])), "message": x["message"] or "",
                   "at": x["updated_at"]} if x else None


def pep_view(c, oid, uid, r):
    conf = pep_conf(c, oid)
    cl = _client_pid(c, oid, r["client_id"])
    miss = pep_missing(c, oid, r, conf)
    sends = pep_sends(c, oid, r["id"])
    live = next((x for x in sends if x["status"] in PEP_LIVE), None)
    return {"configured": bool(conf["provider"]), "missing": [{"key": k, "text": tr(PEP_NEED[k])} for k in miss],
            "receiver_id": (cl["peppol_id"] if cl is not None else "") or "", "client_id": r["client_id"],
            "receiver_suggest": pep_id_suggest(cl["vat_id"]) if cl is not None and not cl["peppol_id"] else "",
            "sandbox": int(conf["sandbox"] or 0), "provider_name": tr(PEP_PROVIDERS[conf["provider"]]["name"]) if conf["provider"] in PEP_PROVIDERS else "",
            "can_send": not miss and live is None, "can_retry": not miss and live is None and bool(sends),
            "sends": [_send_public(x) for x in sends]}


def pep_refresh(c, oid, did):
    """Fetches the status of the newest send still on its way (sent); errors are kept in its message, never raised. A send
    stuck in "sending" for PEP_STALE_MIN minutes (the server stopped between the record and the answer) becomes an error
    that says so, so "send again" is possible after a look at the provider."""
    from datetime import timedelta
    ts = iso(now_utc())
    stale = c.execute("UPDATE office_peppol_sends SET status='error', message=?, updated_at=? WHERE org_id=? AND doc_id=? AND status='sending' "
                      "AND updated_at<? RETURNING id", (tr("Sending was interrupted; check with the provider before sending again"), ts, oid, did,
                                                        iso(now_utc() - timedelta(minutes=PEP_STALE_MIN)))).fetchall()
    x = c.execute("SELECT * FROM office_peppol_sends WHERE org_id=? AND doc_id=? AND status='sent' ORDER BY id DESC LIMIT 1", (oid, did)).fetchone()
    if not x or not x["provider_ref"]:
        return bool(stale)
    try:
        conf = pep_conf(c, oid)
        if conf["provider"] != x["provider"]:
            raise PepError("config")
        st = pep_adapter(c, oid, conf).status(x["provider_ref"])
    except PepError as e:
        c.execute("UPDATE office_peppol_sends SET checked_at=?, message=? WHERE id=?", (ts, e.text(), x["id"]))
        return True
    c.execute("UPDATE office_peppol_sends SET status=?, message=?, checked_at=?, updated_at=? WHERE id=?",
              (st["status"], st.get("message") or "", ts, ts if st["status"] != x["status"] else x["updated_at"], x["id"]))
    if st["status"] != x["status"]:
        from .ledger import ofx_log
        ofx_log(c, oid, "peppol_status", doc_id=did, detail={"status": st["status"], **({"message": st["message"]} if st.get("message") else {})})
    return True


def pep_send(c, oid, uid, r, again=False):
    """Sends finalised document row r over the provider (see the module text). 409 with the reason when something is
    missing or the document went already; the provider's failure is recorded (status error) and answered as 502."""
    from .ledger import ofx_log
    conf = pep_conf(c, oid)
    miss = pep_missing(c, oid, r, conf)
    if miss:
        raise Denied(409, tr(PEP_NEED[miss[0]]))
    sends = pep_sends(c, oid, r["id"])
    if any(x["status"] in PEP_LIVE for x in sends):
        raise Denied(409, tr("This document went over the Peppol network already"))
    if sends and not again:
        raise Denied(409, tr("The last attempt failed; send it again on purpose"))
    cl = _client_pid(c, oid, r["client_id"])
    receiver = cl["peppol_id"]
    try:
        ubl, prof = pep_ubl(c, oid, r, conf, receiver)
    except BadInput as e:
        raise Denied(409, str(e)) from None
    from .einvoice import ein_ubl_check
    if prof == "peppol" and any("R003" in f for f in ein_ubl_check(ubl)):
        raise Denied(409, tr(PEP_NEED["reference"]))
    ad = pep_adapter(c, oid, conf)
    try:
        reach = ad.lookup(receiver)
    except PepError as e:
        raise Denied(502, e.text()) from None
    if not reach:
        raise Denied(409, tr(PEP_ERR["unreachable"]) + f" ({receiver})")
    ts = iso(now_utc())
    sha = hashlib.sha256(ubl).hexdigest()
    # 2.154.0 E (#1960): a retry after a timeout / network error keeps the idempotency key of the failed send when the
    # provider never confirmed it and the XML is the same, so a send that did arrive is not delivered twice.
    last = sends[0] if sends else None
    ref = (last["idem"] if again and last and last["status"] == "error" and not last["provider_ref"] and last["xml_sha256"] == sha
           and last["idem"] else str(uuid.uuid4()))
    from ..core.pg import IntegrityError, insert_id
    try:
        sid = insert_id(c, "INSERT INTO office_peppol_sends(org_id, doc_id, provider, provider_ref, sender_id, receiver_id, profile, xml_sha256, status, "
                        "message, idem, created_by, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (oid, r["id"], conf["provider"], "", conf["sender_id"], receiver, prof, sha, "sending", "", ref, uid, ts, ts))
    except IntegrityError:  # the unique index: a second request at the same time
        c.rollback()
        raise Denied(409, tr("This document went over the Peppol network already")) from None
    c.commit()  # the row stands before anything goes out: a crash never leaves a sent document without its record
    try:
        res = ad.send(ubl, conf["sender_id"], receiver, ref)
    except PepError as e:
        c.execute("UPDATE office_peppol_sends SET status='error', message=?, updated_at=? WHERE id=?", (e.text(), iso(now_utc()), sid))
        ofx_log(c, oid, "peppol_send", doc_id=r["id"], detail={"status": "error", "receiver_id": receiver, "message": e.text()})
        c.commit()
        raise Denied(502, e.text()) from None
    ts = iso(now_utc())
    c.execute("UPDATE office_peppol_sends SET status=?, provider_ref=?, message=?, updated_at=? WHERE id=?",
              (res["status"], res["provider_id"], res.get("message") or "", ts, sid))
    if res["status"] in PEP_LIVE:
        c.execute("UPDATE office_docs SET status=CASE WHEN status IN ('issued') THEN 'sent' ELSE status END, sent_at=COALESCE(sent_at, ?), updated_at=? "
                  "WHERE id=? AND org_id=?", (ts, ts, r["id"], oid))
        from ..integrations.webhooks import who_note
        who_note("invoice.sent", "invoice", r["id"])
    ofx_log(c, oid, "peppol_send", doc_id=r["id"], detail={"status": res["status"], "receiver_id": receiver, "profile": prof,
                                                           "provider": conf["provider"], **({"test": 1} if conf["sandbox"] else {})})
    return sid


# ---------------------------------------------------------------- routes
def _ctx(admin=False):
    c = db()
    uid = office_gate(c)
    return c, uid, office_org(c, uid, admin=admin)


@app.get("/api/office/peppol")
def pep_get():
    """The Peppol connection of the office area (never the key: key_set); can_edit for its admins."""
    c, uid, oid = _ctx()
    return jsonify(pep_public(c, oid, office_role(c, uid, oid) == "admin"))


@app.put("/api/office/peppol")
def pep_put():
    """{provider?, endpoint_url?, account?, sandbox?, sender_id?, api_key?} (admins; without an organisation the person)."""
    c, uid, oid = _ctx(admin=True)
    if office_role(c, uid, oid) != "admin":
        raise Denied(403)
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    pep_save(c, oid, uid, b)
    bump(c)
    c.commit()
    return jsonify(pep_public(c, oid, True))


@app.post("/api/office/peppol/check")
def pep_check_post():
    """Tests the connection with the stored key (nothing is sent): {ok, check_state, check_text}."""
    c, uid, oid = _ctx(admin=True)
    if office_role(c, uid, oid) != "admin":
        raise Denied(403)
    state = "ok"
    try:
        pep_adapter(c, oid).check()
    except PepError as e:
        state = e.code
    c.execute("UPDATE office_peppol SET check_state=?, checked_at=? WHERE org_id=?", (state, iso(now_utc()), oid))
    c.commit()
    out = pep_public(c, oid, True)
    out["ok"] = state == "ok"
    return jsonify(out)


def _doc(c, oid, did):
    from .docs import doc_row
    return doc_row(c, oid, did)


@app.get("/api/office/docs/<int:did>/ubl")
def pep_ubl_get(did):
    """The UBL e-invoice of a finalised invoice / credit note (Peppol BIS Billing 3.0, XRechnung UBL for the XRechnung
    format) with the Peppol ids when they are set, else the e-mail addresses. 409 for drafts and other kinds."""
    from .ledger import ofx_locked, ofx_log
    from .model import office_need_feature
    from .pdfweb import _file_response, epdf_name
    c, uid, oid = _ctx()
    r = _doc(c, oid, did)
    if r["kind"] not in ("invoice", "credit") or not ofx_locked(r) or r["status"] == "cancelled":
        raise Denied(409, tr("The e-invoice XML exists for finalised invoices and credit notes only."))
    office_need_feature(c, oid, "docs.einvoice")
    data, _prof = pep_ubl(c, oid, r)
    ofx_log(c, oid, "ubl", doc_id=did, dedupe_min=10)
    c.commit()
    return _file_response(data, epdf_name(r) + "-ubl.xml", "application/xml")


@app.get("/api/office/docs/<int:did>/peppol")
def pep_doc_get(did):
    """The Peppol state of a document: what is missing, the client's id (or a suggestion from its VAT id), the sends.
    ?refresh=1 fetches the status of a send still on its way from the provider first."""
    c, uid, oid = _ctx()
    r = _doc(c, oid, did)
    if r["kind"] not in ("invoice", "credit"):
        raise Denied(409, tr(PEP_NEED["kind"]))
    if request.args.get("refresh") == "1" and pep_refresh(c, oid, did):
        c.commit()
    return jsonify(pep_view(c, oid, uid, r))


@app.post("/api/office/docs/<int:did>/peppol/lookup")
def pep_lookup_post(did):
    """Asks the provider whether the client's Peppol id can receive invoices: {reachable, receiver_id}."""
    c, uid, oid = _ctx()
    r = _doc(c, oid, did)
    cl = _client_pid(c, oid, r["client_id"])
    if cl is None or not cl["peppol_id"]:
        raise Denied(409, tr(PEP_NEED["receiver" if cl is not None else "client"]))
    try:
        ok = pep_adapter(c, oid).lookup(cl["peppol_id"])
    except PepError as e:
        raise Denied(502 if e.code != "config" else 409, e.text()) from None
    return jsonify(reachable=bool(ok), receiver_id=cl["peppol_id"])


@app.post("/api/office/docs/<int:did>/peppol")
def pep_send_post(did):
    """{again?: 1} sends the finalised invoice / credit note over the Peppol network (people only; never an agent).
    201 the Peppol view; 409 with the reason when something is missing or it went already; 502 when the provider failed."""
    c, uid, oid = _ctx()
    r = _doc(c, oid, did)
    b = body() or {}
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    pep_send(c, oid, uid, r, again=b.get("again") in (1, True, "1"))
    bump(c)
    c.commit()
    return jsonify(pep_view(c, oid, uid, _doc(c, oid, did))), 201
