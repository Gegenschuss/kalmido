"""2.469.0 (#3459): online payment of invoices: a pay link in the invoice mail, the PDF (link + QR) and the customer portal; the
provider tells the payment by webhook and it lands on the invoice through the same code as a payment recorded by hand.

The office's own account at the provider (Kalmido never takes money and charges nothing): office_payonline holds, per office area
(an organisation's office or the personal office of a person without one), the provider, the secret key and the webhook secret,
sealed with the area's key (orgcrypt FIELDS; never sent back, only "set"). Off until set up. POL_PROVIDERS names the providers, an
adapter class stands behind each (POL_ADAPTERS, today Stripe Checkout); a second provider is one more class.

Pay link: office_pay_links, one long random token per invoice (sealed, looked up by its SHA-256); off = the invoice's switch.
GET /s/pay/<token> shows the bare minimum (company, number, open amount), POST /s/pay/<token>/go computes the open amount from the
database and starts a checkout at the provider: a row in office_pay_sessions first, so amount and invoice stand in our own
database; a credit note, a cancelled, paid, draft or trial document never gets a session.
The finalised PDF is frozen: finalising notes the link in the sender snapshot like the GiroCode decision (ledger.ofx_finalize,
pol_freeze), the document is rendered from that alone. No connection at finalising = no link in that PDF, mail and portal still
offer it. XRechnung / ZUGFeRD carry nothing of this.

Webhook: POST /api/hooks/pay/<token> (the token names the office area, office_payonline.hook_hash). The signature over the raw body
is checked with the area's webhook secret before anything of the body is read. office_pay_events takes every event once (unique
index), a retry of the provider answers 200. Amount and invoice come from the session row found by the provider's session id
within the area, never from the event's metadata; an amount or currency that differs is held. Events may come in any order: a
refund before its payment waits (state wait) and runs when the payment is booked.
Booking: invoices.inv_pay_add (method online, office_payments.online_ref unique = one payment once) and invoices.inv_pay_del.
Refunds and lost disputes are kept as the highest amount told, pol_sync brings the payment to what is left: reverses it and books
the rest as a new payment (the books know whole reversals only). What cannot be booked (paid meanwhile, month locked, cancelled) is
never lost: the event stays held, the session keeps the money in view, the area's admins are told once (integ_tell, their
notification settings) and see it in the settings with Try again / Done.

Payouts: the provider's collective transfer to the bank is no payment: bank.py kind "payout" marks the booking (no office_payments
row, so nothing counts twice), pol_bank_hit suggests it instead of invoices. Matching one fetches the provider's fees of that payout
and files them as one receipt (a text document with its amount, paid that day): the expense in the books. No subscriptions."""
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import time
import urllib.parse
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import g, jsonify, redirect, request

from ..accounts.session import _accept_lang, client_ip, rate_ip
from ..api.common import hit_limit
from ..calendars.subscriptions import CalError, cal_allow_parse, cal_http
from ..collab.integfail import integ_org_admins, integ_tell
from ..core.access import Denied, acx_anon_bind
from ..core.config import APP_NAME, PUBLIC_URL, TZ, app
from ..core.db import body, bump, db, err, iso, local_now, now_utc
from ..core.errors import BadInput
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import insert_id, system_ctx, write_lock
from ..lists.public import PUB_BAD_LIMIT, PUB_CSP, pub_gone, pub_html, pub_limited, public_links_on
from ..notify.alerts import _env_int, aa_count
from .calc import dec, dstr, fmt_money, money
from .doclang import doc_lg
from .docs import _j, doc_row
from .invoices import _ofr_pay, inv_money_fields, inv_paid_map, inv_pay_add, inv_pay_del
from .ledger import ofx_company, ofx_locked, ofx_log
from .model import office_ctx, pb_owner
from .rights import ofr_admin_or

POL_TIMEOUT = 15
POL_MAX_BYTES = 1024 * 1024
POL_HOOK_MAX = 256 * 1024         # one event of the provider
POL_HOOK_PER_MIN = 300            # events per office area
POL_BAD_PER_MIN = 30              # unknown tokens / wrong signatures per address
POL_TOLERANCE = 300               # seconds a signature's time may differ (replay window)
POL_VIEW_RATE = 60                # pages per address and minute
POL_GO_RATE = _env_int("KALMIDO_PAYONLINE_GO_RATE", 10)  # checkouts started per address and minute
POL_GO_LINK_HOUR = 20             # checkouts started per link and hour
POL_REUSE_S = 20 * 60             # the same amount within this time goes back to the open checkout
POL_EXPIRE_S = 60 * 60            # a checkout ends after this time
POL_ALLOW_ENV = os.environ.get("KALMIDO_PAYONLINE_ALLOW_HOSTS", "")  # tests: the stand-in provider
POL_STRIPE_URL = os.environ.get("KALMIDO_PAYONLINE_STRIPE_URL", "").strip().rstrip("/") or "https://api.stripe.com"
POL_PROVIDERS = {"stripe": {"name": "Stripe"}}
POL_ZERO_DEC = frozenset(("JPY", "KRW", "CLP", "VND"))  # currencies without minor units
POL_BOOKED = ("paid", "part_refund", "refunded")  # the session's money is on the invoice (or went back)
POL_HOLD = {"over": N_("The amount is more than what is open on the invoice"), "closed": N_("The invoice is paid or cancelled"),
            "locked": N_("The month is locked"), "mismatch": N_("The provider reports another amount than the checkout")}
POL_AMOUNT_RE = re.compile(r"\d+(?:[.,]\d+)*")
POL_WHY = {"The payment exceeds the open amount": "over", "Payments go on finalised, open invoices only": "closed"}
POL_TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{30,64}")
POL_LOG_FIELDS = ("provider", "enabled")


class PolError(Exception):
    """A provider call failed; code only, never a key or an answer of the provider in a text."""
    def __init__(self, code):
        super().__init__(code)
        self.code = code


# ---------------------------------------------------------------- amounts
def pol_minor(amount, cur):
    """A decimal amount -> the provider's whole minor units."""
    m = Decimal(1) if (cur or "").upper() in POL_ZERO_DEC else Decimal(100)
    return int((dec(amount) * m).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def pol_major(minor, cur):
    return money(Decimal(int(minor)) / (Decimal(1) if (cur or "").upper() in POL_ZERO_DEC else Decimal(100)))


# ---------------------------------------------------------------- the provider
class PolStripe:
    """Stripe Checkout: form-encoded API with the office's secret key as bearer. Payment methods are chosen in the office's Stripe
    account (card, SEPA direct debit, PayPal, Apple / Google Pay), so nothing here names them. Webhook: Stripe-Signature, t=<time>,
    v1=<HMAC-SHA256 of "<time>.<raw body>" with the endpoint's secret>."""
    name = "Stripe"
    checkout_host = "checkout.stripe.com"
    marks = ("stripe",)  # how its payouts read in a bank statement

    def __init__(self, key):
        self.key = key

    def _call(self, method, path, form=None, idem=None):
        h = {"Authorization": f"Bearer {self.key}", "Accept": "application/json"}
        data = None
        if form is not None:
            data = urllib.parse.urlencode(form).encode()
            h["Content-Type"] = "application/x-www-form-urlencoded"
        if idem:
            h["Idempotency-Key"] = idem
        try:
            st, _h, raw, _u = cal_http(POL_STRIPE_URL + path, method=method, body=data, headers=h, allow=frozenset(cal_allow_parse(POL_ALLOW_ENV)[0]),
                                       max_bytes=POL_MAX_BYTES, timeout=POL_TIMEOUT, deadline=POL_TIMEOUT * 2)
        except CalError as e:
            raise PolError("auth" if getattr(e, "code", "") == "auth" else "http") from None
        if st in (401, 403):
            raise PolError("auth")
        if st >= 300:
            raise PolError("http")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise PolError("answer") from None

    def check(self):
        self._call("GET", "/v1/balance")

    def create(self, sid, amount_minor, cur, title, back_ok, back_no, until):
        """(session id, address of the checkout) of a new one-off checkout; sid = our row (the idempotency key)."""
        j = self._call("POST", "/v1/checkout/sessions", {
            "mode": "payment", "client_reference_id": str(sid), "success_url": back_ok, "cancel_url": back_no, "expires_at": str(until),
            "line_items[0][quantity]": "1", "line_items[0][price_data][currency]": cur.lower(),
            "line_items[0][price_data][unit_amount]": str(amount_minor), "line_items[0][price_data][product_data][name]": title[:200],
            "payment_intent_data[description]": title[:200]}, idem=f"kalmido-pay-{sid}")
        ext, url = j.get("id"), j.get("url")
        if not isinstance(ext, str) or not isinstance(url, str):
            raise PolError("answer")
        p = urllib.parse.urlsplit(url)
        if p.scheme != "https" or p.hostname != self.checkout_host:  # the customer goes nowhere else
            raise PolError("answer")
        return ext, url

    def expire(self, ext):
        self._call("POST", f"/v1/checkout/sessions/{urllib.parse.quote(ext, safe='')}/expire", {})

    def payout_fees(self, ext):
        """The fees (minor units) of the bookings of payout ext."""
        fee, after = 0, ""
        for _ in range(50):
            j = self._call("GET", f"/v1/balance_transactions?limit=100&payout={urllib.parse.quote(ext, safe='')}{after}")
            rows = j.get("data") if isinstance(j.get("data"), list) else []
            fee += sum(int(x.get("fee") or 0) for x in rows if isinstance(x, dict) and x.get("type") != "payout")
            if not j.get("has_more") or not rows:
                return fee
            after = "&starting_after=" + urllib.parse.quote(str(rows[-1].get("id") or ""), safe="")
        raise PolError("answer")

    @staticmethod
    def verify(raw, headers, secret, now=None):
        """True when the Stripe-Signature of the raw body is good and at most POL_TOLERANCE old (or ahead)."""
        ts, sigs = None, []
        for part in (headers.get("Stripe-Signature") or "").split(","):
            k, _, v = part.strip().partition("=")
            if k == "t" and v.isdigit():
                ts = int(v)
            elif k == "v1":
                sigs.append(v)
        if ts is None or not sigs or abs((now or time.time()) - ts) > POL_TOLERANCE:
            return False
        want = hmac.new(secret.encode(), f"{ts}.".encode() + raw, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(want, s) for s in sigs)

    @staticmethod
    def event(raw):
        """The event of a checked body in neutral words: {id, kind, ref, pay_ref, amount, currency, day}, None = not of interest,
        ValueError = no event. kind: paid | pending | failed | expired | refund | dispute | dispute_back | payout. ref = the
        checkout's id (paid .. expired), the payment's (refund, dispute), the payout's (payout)."""
        ev = json.loads(raw.decode("utf-8"))
        o = ((ev.get("data") or {}).get("object") if isinstance(ev, dict) else None) or None
        t, eid = (ev.get("type"), ev.get("id")) if isinstance(ev, dict) else (None, None)
        if not isinstance(o, dict) or not isinstance(t, str) or not isinstance(eid, str) or not 0 < len(eid) <= 200:
            raise ValueError("event")
        when = ev.get("created")
        out = {"id": eid, "day": _day_of(when), "currency": str(o.get("currency") or "").upper()}
        if t == "checkout.session.completed":
            kind = "paid" if o.get("payment_status") in ("paid", "no_payment_required") else "pending"
        elif t == "checkout.session.async_payment_succeeded":
            kind = "paid"
        elif t in ("checkout.session.async_payment_failed", "checkout.session.expired"):
            kind = "failed" if t.endswith("failed") else "expired"
        elif t == "charge.refunded":
            return {**out, "kind": "refund", "ref": _id(o.get("payment_intent")), "pay_ref": "", "amount": _int(o.get("amount_refunded"))}
        elif t in ("charge.dispute.funds_withdrawn", "charge.dispute.funds_reinstated"):
            kind = "dispute" if t.endswith("withdrawn") else "dispute_back"
            return {**out, "kind": kind, "ref": _id(o.get("payment_intent")), "pay_ref": "", "amount": _int(o.get("amount"))}
        elif t == "payout.paid":
            return {**out, "kind": "payout", "ref": _id(o.get("id")), "pay_ref": "", "amount": _int(o.get("amount")),
                    "day": _day_of(o.get("arrival_date")) or out["day"]}
        else:
            return None
        return {**out, "kind": kind, "ref": _id(o.get("id")), "pay_ref": _id(o.get("payment_intent")), "amount": _int(o.get("amount_total"))}


POL_ADAPTERS = {"stripe": PolStripe}


def _id(v):
    if isinstance(v, dict):
        v = v.get("id")
    return v if isinstance(v, str) and len(v) <= 200 else ""


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else 0


def _day_of(ts):
    """A Unix time -> the local ISO day ('' when it is none), never after today."""
    today = local_now().date().isoformat()
    if not isinstance(ts, int) or isinstance(ts, bool):
        return today
    try:
        d = datetime.fromtimestamp(ts, TZ).date().isoformat()
    except (OverflowError, OSError, ValueError):
        return today
    return min(d, today)


# ---------------------------------------------------------------- the connection of an office area
def pol_conf(c, oid):
    """The connection of area oid with its secrets opened (for the server's own use, never for an answer)."""
    r = c.execute("SELECT * FROM office_payonline WHERE org_id=?", (oid,)).fetchone()
    d = {"provider": "", "enabled": 0, "secret_key": "", "webhook_secret": "", "hook_token": "", "hook_hash": ""}
    if r:
        x = oc_dec_fields(c, oid, "office_payonline", r)
        d.update({k: x[k] for k in d})
    return d


def pol_adapter(conf):
    k = POL_ADAPTERS.get(conf["provider"])
    return k(conf["secret_key"]) if k and conf["secret_key"] else None


def pol_ready(c, oid, conf=None):
    """Set up and switched on: the pay link is offered."""
    conf = conf or pol_conf(c, oid)
    return bool(conf["enabled"] and conf["provider"] in POL_ADAPTERS and conf["secret_key"] and conf["webhook_secret"] and public_links_on(c))


def pol_hook_url(tok):
    return f"{PUBLIC_URL.rstrip('/')}/api/hooks/pay/{tok}"


def pol_held(c, oid, did=None):
    """The events waiting for a person: [{id, kind, reason, text, amount, currency, doc_id, number, day}]."""
    q = ("SELECT e.*, s.doc_id, s.currency, d.number FROM office_pay_events e LEFT JOIN office_pay_sessions s ON s.id=e.session_id AND s.org_id=e.org_id "
         "LEFT JOIN office_docs d ON d.id=s.doc_id AND d.org_id=e.org_id WHERE e.org_id=? AND e.state='held'")
    args = [oid]
    if did is not None:
        q += " AND s.doc_id=?"
        args.append(did)
    return [{"id": r["id"], "kind": r["kind"], "reason": r["reason"], "text": tr(POL_HOLD.get(r["reason"]) or N_("unknown")),
             "amount": dstr(pol_major(r["amount_minor"], r["currency"])) if r["currency"] else "", "currency": r["currency"] or "",
             "doc_id": r["doc_id"], "number": r["number"] or "", "day": r["occurred"]}
            for r in c.execute(q + " ORDER BY e.id DESC LIMIT 50", args).fetchall()]


def pol_public(c, oid, admin):
    """The settings' view: never a secret, only "set"; the webhook address (it holds a token) for admins."""
    conf = pol_conf(c, oid)
    out = {"provider": conf["provider"], "enabled": bool(conf["enabled"]), "key_set": bool(conf["secret_key"]), "webhook_secret_set": bool(conf["webhook_secret"]),
           "ready": pol_ready(c, oid, conf), "can_edit": bool(admin), "providers": [{"id": k, "name": v["name"]} for k, v in POL_PROVIDERS.items()]}
    if admin:
        out["webhook_url"] = pol_hook_url(conf["hook_token"]) if conf["hook_token"] else ""
        out["held"] = pol_held(c, oid)
        out["payouts"] = [{"id": r["id"], "day": r["day"], "amount": dstr(pol_major(r["amount_minor"], r["currency"])), "currency": r["currency"],
                           "fee": dstr(pol_major(r["fee_minor"], r["currency"])), "booked": bool(r["node_id"])}
                          for r in c.execute("SELECT * FROM office_pay_payouts WHERE org_id=? ORDER BY day DESC, id DESC LIMIT 10", (oid,)).fetchall()]
    return out


def _secret_in(b, k):
    v = b.get(k)
    if v is not None and not isinstance(v, str):
        raise BadInput(tr("Invalid value: {0}", k))
    v = (v or "").strip()
    if len(v) > 2000:
        raise BadInput(tr("Invalid value: {0}", k))
    return v


def pol_new_hook():
    tok = "kpw_" + secrets.token_urlsafe(32)
    return tok, hashlib.sha256(tok.encode()).hexdigest()


def pol_write(c, oid, uid, new):
    enc = oc_enc_fields(c, oid, "office_payonline", {k: new[k] for k in ("secret_key", "webhook_secret", "hook_token")})
    c.execute("INSERT INTO office_payonline(org_id, provider, enabled, secret_key, webhook_secret, hook_token, hook_hash, updated_by, updated_at) "
              "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(org_id) DO UPDATE SET provider=excluded.provider, enabled=excluded.enabled, "
              "secret_key=excluded.secret_key, webhook_secret=excluded.webhook_secret, hook_token=excluded.hook_token, "
              "hook_hash=excluded.hook_hash, updated_by=excluded.updated_by, updated_at=excluded.updated_at",
              (oid, new["provider"], new["enabled"], enc["secret_key"], enc["webhook_secret"], enc["hook_token"], new["hook_hash"], uid, iso(now_utc())))


def pol_save(c, oid, uid, b):
    """PUT body {provider?, enabled?, secret_key?, webhook_secret?}. An empty secret keeps the stored one, a new provider drops both
    (a key only ever goes to where it was entered for). Switching on needs both."""
    bad = set(b) - {"provider", "enabled", "secret_key", "webhook_secret"}
    if bad:
        raise BadInput(tr("Invalid value: {0}", sorted(bad)[0]))
    cur = pol_conf(c, oid)
    new = dict(cur)
    if "provider" in b:
        v = str(b["provider"] or "").strip()
        if v and v not in POL_PROVIDERS:
            raise BadInput(tr("Invalid value: {0}", "provider"))
        new["provider"] = v
    if new["provider"] != cur["provider"]:
        new["secret_key"], new["webhook_secret"], new["enabled"] = "", "", 0
    key, sec = _secret_in(b, "secret_key"), _secret_in(b, "webhook_secret")
    new["secret_key"], new["webhook_secret"] = key or new["secret_key"], sec or new["webhook_secret"]
    if "enabled" in b:
        new["enabled"] = 1 if b["enabled"] in (1, True, "1", "true") else 0
    if new["enabled"] and not (new["provider"] and new["secret_key"] and new["webhook_secret"]):
        raise Denied(409, tr("Enter the key and the webhook secret first"))
    if new["provider"] and not new["hook_token"]:
        new["hook_token"], new["hook_hash"] = pol_new_hook()
    pol_write(c, oid, uid, new)
    ofx_log(c, oid, "payonline_setup", target="settings", detail={**{k: new[k] for k in POL_LOG_FIELDS}, "key_set": bool(new["secret_key"]),
                                                                  **({"key_changed": 1} if key else {}), **({"secret_changed": 1} if sec else {})})


# ---------------------------------------------------------------- the pay link of an invoice
def pol_link(c, oid, did, create=True):
    """The link row of document did (with its token opened), made on the first need; None with create=False while there is none."""
    r = c.execute("SELECT * FROM office_pay_links WHERE org_id=? AND doc_id=?", (oid, did)).fetchone()
    if not r and create:
        tok = secrets.token_urlsafe(32)
        c.execute("INSERT INTO office_pay_links(org_id, doc_id, token, token_hash, created_at) VALUES(?,?,?,?,?) ON CONFLICT(doc_id) DO NOTHING",
                  (oid, did, oc_enc_fields(c, oid, "office_pay_links", {"token": tok})["token"], hashlib.sha256(tok.encode()).hexdigest(), iso(now_utc())))
        r = c.execute("SELECT * FROM office_pay_links WHERE org_id=? AND doc_id=?", (oid, did)).fetchone()
    return oc_dec_fields(c, oid, "office_pay_links", r) if r else None


def pol_url(link):
    return f"{PUBLIC_URL.rstrip('/')}/s/pay/{link['token']}"


def pol_payable(c, oid, r):
    """'open' (with the open Decimal), 'paid' or None (no pay link at all): (state, amount). Finalised invoices only; never a credit
    note, a reminder, a draft, a trial or a cancelled document."""
    if r["kind"] != "invoice" or not ofx_locked(r) or r["trial"] or r["status"] in ("draft", "cancelled"):
        return None, None
    a = dec(inv_money_fields(r, inv_paid_map(c, oid, [r["id"]]))["open"])
    return ("open", money(a)) if r["status"] != "paid" and a > 0 else ("paid", Decimal(0))


def pol_freeze(c, oid, r):
    """ledger.ofx_finalize, before the snapshot is written: the address the invoice's PDF prints, or None."""
    if r["kind"] != "invoice" or r["trial"] or not pol_ready(c, oid):
        return None
    link = pol_link(c, oid, r["id"])
    return None if link["off"] else pol_url(link)


def pol_active_url(c, oid, r, create=True):
    """The address to offer now (mail, portal, document view): set up, switched on for the invoice, something open; else None.
    create: a link is made when there is none yet; the caller commits."""
    if r["kind"] != "invoice" or not pol_ready(c, oid) or pol_payable(c, oid, r)[0] != "open":
        return None
    link = pol_link(c, oid, r["id"], create)
    return pol_url(link) if link and not link["off"] else None


def pol_mail_text(c, oid, r, text, lg):
    """invoices.inv_send: the mail's text with the pay link (unchanged without one)."""
    url = pol_active_url(c, oid, r)
    if not url or url in text:
        return text
    return f"{text}\n\n{tr('You can pay this invoice online: {0}|mail', url, lg=lg)}"


def pol_doc_extra(c, oid, d, admin):
    """doc_public of a single invoice: pay_online {ready, on, url (admins), held (admins)}; nothing while the office has no connection."""
    if d.get("kind") != "invoice":
        return
    ready = pol_ready(c, oid)
    link = pol_link(c, oid, d["id"], create=False)
    if not ready and not link:
        return
    r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (d["id"], oid)).fetchone()
    out = {"ready": ready, "on": not (link and link["off"])}
    if admin:
        out["url"] = pol_active_url(c, oid, r, create=False) or ""  # a GET makes no link: PUT .../pay-online does
        out["held"] = pol_held(c, oid, d["id"])
    d["pay_online"] = out


# ---------------------------------------------------------------- booking
def _session(c, oid, provider, col, ref):
    return c.execute(f"SELECT * FROM office_pay_sessions WHERE org_id=? AND provider=? AND {col}=? ORDER BY id DESC LIMIT 1", (oid, provider, ref)).fetchone() if ref else None


def _reread(c, oid, s):
    return c.execute("SELECT * FROM office_pay_sessions WHERE id=? AND org_id=?", (s["id"], oid)).fetchone()


def _set(c, s, **kw):
    kw["updated_at"] = iso(now_utc())
    c.execute(f"UPDATE office_pay_sessions SET {', '.join(k + '=?' for k in kw)} WHERE id=? AND org_id=?", (*kw.values(), s["id"], s["org_id"]))


def _ev_state(c, eid, state, reason="", sid=None):
    c.execute("UPDATE office_pay_events SET state=?, reason=?, session_id=COALESCE(?, session_id) WHERE id=?", (state, reason, sid, eid))


def _why(e):
    """Why the invoices' code refused a booking -> a key of POL_HOLD (by the text's key, never by a translated text)."""
    return POL_WHY.get((getattr(e, "stored", None) or ("",))[0], "locked")


def _book_day(c, oid, day):
    """A payment lands on its day; in a locked month on today (only finished months are locked)."""
    from .periodlock import period_need_open
    try:
        period_need_open(c, oid, day)
        return day
    except Denied:
        return local_now().date().isoformat()


def _book(c, oid, s, minor, ref, day):
    p = c.execute("SELECT id FROM office_payments WHERE org_id=? AND online_ref=?", (oid, ref)).fetchone()
    if p:
        return p["id"]
    label = POL_PROVIDERS.get(s["provider"], {}).get("name") or s["provider"]
    return inv_pay_add(c, oid, None, s["doc_id"], {"date": _book_day(c, oid, day), "amount": dstr(pol_major(minor, s["currency"])), "method": "online",
                                                   "note": f"{label} {s['payment_ref']}".strip()}, online_ref=ref)


def pol_on_paid(c, oid, conf, eid, ev):
    s = _session(c, oid, conf["provider"], "ext_id", ev["ref"])
    if not s:  # a checkout of another system on the same account
        return
    write_lock(c, f"office_doc_{int(s['doc_id'])}")  # the order of the hand payment: the document, then its payments
    s = _reread(c, oid, s)
    if ev["pay_ref"] and not s["payment_ref"]:
        _set(c, s, payment_ref=ev["pay_ref"])
        s = _reread(c, oid, s)
    _ev_state(c, eid, "done", sid=s["id"])
    if s["state"] in POL_BOOKED:
        return
    if ev["kind"] == "pending":  # a direct debit: the money follows days later
        _set(c, s, state="pending")
        return
    if ev["amount"] != s["amount_minor"] or (ev["currency"] and ev["currency"] != s["currency"]):
        _set(c, s, state="received")
        return pol_hold(c, oid, eid, s, "mismatch")
    try:
        with c.savepoint():
            pid = _book(c, oid, s, s["amount_minor"], f"{s['provider']}:{s['payment_ref'] or s['ext_id']}", ev["day"])
            _set(c, s, state="paid", payment_id=pid)
            s = _reread(c, oid, s)
            if s["refunded_minor"] or s["disputed_minor"]:  # told while the money was held: the invoice gets what is left
                pol_sync(c, oid, s, eid)
    except (Denied, BadInput) as e:
        _set(c, s, state="received")
        return pol_hold(c, oid, eid, s, _why(e))
    pol_wake(c, oid, conf, s)


def pol_wake(c, oid, conf, s):
    """The refunds and disputes that came before the session's payment."""
    for w in c.execute("SELECT * FROM office_pay_events WHERE org_id=? AND provider=? AND ref=? AND state='wait' ORDER BY id",
                       (oid, conf["provider"], s["payment_ref"])).fetchall():
        pol_on_back(c, oid, conf, w["id"], {"kind": w["kind"], "ref": w["ref"], "amount": w["amount_minor"]})


def pol_on_back(c, oid, conf, eid, ev):
    """A refund / a dispute won or lost: the highest amount told counts, so doubled or swapped events change nothing."""
    s = _session(c, oid, conf["provider"], "payment_ref", ev["ref"])
    if not s or s["state"] not in POL_BOOKED + ("received",):
        return _ev_state(c, eid, "wait", sid=s["id"] if s else None)  # the payment has not arrived yet
    write_lock(c, f"office_doc_{int(s['doc_id'])}")
    s = _reread(c, oid, s)
    if ev["kind"] == "refund":
        _set(c, s, refunded_minor=min(max(s["refunded_minor"], ev["amount"]), s["amount_minor"]))
    else:
        _set(c, s, disputed_minor=min(ev["amount"], s["amount_minor"]) if ev["kind"] == "dispute" else 0)
    s = _reread(c, oid, s)
    _ev_state(c, eid, "done", sid=s["id"])
    if s["state"] == "received":  # never on the invoice: a refund of all of it ends the waiting
        if s["refunded_minor"] + s["disputed_minor"] >= s["amount_minor"]:
            _set(c, s, state="refunded")
            c.execute("UPDATE office_pay_events SET state='done', reason='refunded' WHERE org_id=? AND session_id=? AND state='held'", (oid, s["id"]))
        return None
    try:
        with c.savepoint():
            pol_sync(c, oid, s, eid)
    except (Denied, BadInput) as e:
        return pol_hold(c, oid, eid, s, _why(e))
    return None


def pol_sync(c, oid, s, eid):
    """The session's payment on the invoice comes to what is left of it: a whole reversal, then what stays as a new payment."""
    left = max(s["amount_minor"] - s["refunded_minor"] - s["disputed_minor"], 0)
    p = None
    if s["payment_id"]:
        p = c.execute("SELECT p.* FROM office_payments p WHERE p.id=? AND p.org_id=? AND NOT EXISTS (SELECT 1 FROM office_payments x WHERE x.reverses_id=p.id AND x.org_id=p.org_id)",
                      (s["payment_id"], oid)).fetchone()
    if s["payment_id"] and not p:  # a person reversed it by hand: their booking stands
        return _set(c, s, state="paid" if left == s["amount_minor"] else "part_refund" if left else "refunded")
    has = pol_minor(p["amount"], s["currency"]) if p else 0
    state = "paid" if left == s["amount_minor"] else "part_refund" if left else "refunded"
    if left == has:
        return _set(c, s, state=state)
    if p:
        inv_pay_del(c, oid, s["doc_id"], p["id"], note=POL_PROVIDERS.get(s["provider"], {}).get("name") or s["provider"], uid=None)
    pid = _book(c, oid, s, left, f"{s['provider']}:{s['payment_ref']}:{eid}", local_now().date().isoformat()) if left else None
    return _set(c, s, state=state, payment_id=pid)


def pol_hold(c, oid, eid, s, reason):
    """Money the books cannot take as it came: kept in view, the area's admins hear it once."""
    _ev_state(c, eid, "held", reason, s["id"])
    r = c.execute("SELECT number FROM office_docs WHERE id=? AND org_id=?", (s["doc_id"], oid)).fetchone()
    owner = pb_owner(c, oid)
    integ_tell(c, [owner] if owner else integ_org_admins(c, oid), "payonline", (r["number"] if r else "") or f"#{s['doc_id']}", POL_HOLD[reason],
               click="office/invoices/" + str(int(s["doc_id"])))


def pol_on_payout(c, oid, conf, ev):
    if ev["ref"]:
        c.execute("INSERT INTO office_pay_payouts(org_id, provider, ext_id, amount_minor, currency, day, created_at) VALUES(?,?,?,?,?,?,?) "
                  "ON CONFLICT(org_id, provider, ext_id) DO NOTHING", (oid, conf["provider"], ev["ref"], ev["amount"], ev["currency"], ev["day"], iso(now_utc())))


def pol_apply(c, oid, conf, eid, ev):
    k = ev["kind"]
    if k in ("paid", "pending"):
        pol_on_paid(c, oid, conf, eid, ev)
    elif k in ("refund", "dispute", "dispute_back"):
        pol_on_back(c, oid, conf, eid, ev)
    elif k == "payout":
        pol_on_payout(c, oid, conf, ev)
    else:  # failed | expired: only while nothing came in
        s = _session(c, oid, conf["provider"], "ext_id", ev["ref"])
        if s and s["state"] in ("new", "open", "pending"):
            _set(c, s, state=k)


@app.post("/api/hooks/pay/<token>")
def pol_hook(token):
    """The provider's webhook of one office area: no cookie, no login; the token names the area, the signature is the credential.
    200 once an event is taken (also a duplicate or one of no interest); a person fixes what could not be booked, so never a
    repeat of the provider for that."""
    c = db()
    request.max_content_length = POL_HOOK_MAX
    if (request.content_length or 0) > POL_HOOK_MAX:
        return err(tr("The request is too large (at most {0} KB)", POL_HOOK_MAX // 1024), 413)
    h = hashlib.sha256(token.encode()).hexdigest() if token and len(token) <= 200 else ""
    with system_ctx(c):  # resolve the token (one row by its hash) across organisations, then act inside exactly that area
        r = c.execute("SELECT org_id FROM office_payonline WHERE hook_hash=?", (h,)).fetchone() if h else None
    if not r:
        aa_count("security", "hookin", client_ip())
        if hit_limit(f"polu:{client_ip()}", POL_BAD_PER_MIN):
            return err(tr("Too many attempts, please wait a few minutes"), 429)
        return err(tr("unknown"), 404)
    oid = r["org_id"]
    if hit_limit(f"polh:{oid}", POL_HOOK_PER_MIN):
        return err(tr("Too many attempts, please wait a few minutes"), 429)
    acx_anon_bind(c, oid)
    conf = pol_conf(c, oid)
    ad = POL_ADAPTERS.get(conf["provider"])
    raw = request.get_data(cache=True) or b""
    if ad is None or not conf["webhook_secret"] or not ad.verify(raw, request.headers, conf["webhook_secret"]):
        aa_count("security", "hookin", client_ip())
        if hit_limit(f"polu:{client_ip()}", POL_BAD_PER_MIN):
            return err(tr("Too many attempts, please wait a few minutes"), 429)
        return err(tr("Invalid signature"), 400)
    try:
        ev = ad.event(raw)
    except (ValueError, UnicodeDecodeError, AttributeError, TypeError):
        return err(tr("Invalid data"), 400)
    if ev is None:
        return jsonify(ok=True, ignored=True)
    n = c.execute("INSERT INTO office_pay_events(org_id, provider, event_id, kind, ref, amount_minor, occurred, created_at) VALUES(?,?,?,?,?,?,?,?) "
                  "ON CONFLICT(org_id, provider, event_id) DO NOTHING RETURNING id",
                  (oid, conf["provider"], ev["id"], ev["kind"], ev["ref"], ev["amount"], ev["day"], iso(now_utc()))).fetchone()
    if not n:
        c.rollback()
        return jsonify(ok=True, duplicate=True)
    pol_apply(c, oid, conf, n["id"], ev)
    bump(c)
    c.commit()
    return jsonify(ok=True)


# ---------------------------------------------------------------- the public pay page
def pol_page_headers(resp, ad=None):
    """The form's redirect leads to the provider's checkout: form-action names that host."""
    if ad is not None:
        resp.headers["Content-Security-Policy"] = PUB_CSP.replace("form-action 'self'", f"form-action 'self' https://{ad.checkout_host}")
    return resp


def pol_find(c, token):
    """(link row with org, invoice row, connection) of a live pay link -- bound as nobody to exactly its office area -- or None."""
    if not POL_TOKEN_RE.fullmatch(token or "") or not public_links_on(c):
        return None
    with system_ctx(c):  # resolve the token (one row by its hash) across organisations
        link = c.execute("SELECT * FROM office_pay_links WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not link:
        return None
    oid = link["org_id"]
    try:
        acx_anon_bind(c, oid)  # nobody, inside exactly the area of this invoice (a retired organisation: 404)
    except Denied:
        return None
    owner = pb_owner(c, oid)
    if owner is not None:
        from .portaldocs import kp_area
        if not kp_area(c, None, owner):
            return None
    conf = pol_conf(c, oid)
    r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (link["doc_id"], oid)).fetchone()
    if link["off"] or not r or not pol_ready(c, oid, conf):
        return None
    return link, r, conf


def _company(c, oid, r):
    snd = oc_dec_fields(c, oid, "office_docs", r).get("sender")
    f = (_j(snd, {}).get("fields") if snd else None) or ofx_company(c, oid)
    return (str(f.get("name") or "").split("\n")[0]).strip() or APP_NAME


def pol_form(c, oid, r, token, amount, lg, error=None, back=None):
    e = html.escape
    cur = r["currency"] or "EUR"
    head = f'<h1>{e(tr("Invoice {0}|pay page", r["number"] or "", lg=lg))}</h1><p>{e(_company(c, oid, r))}</p>'
    txt = fmt_money(amount, r["lang"] or lg, cur)
    note = {"ok": tr("Thank you. The payment is being processed; it shows here as soon as the provider confirms it.", lg=lg),
            "no": tr("The payment was cancelled. Nothing was charged.", lg=lg)}.get(back)
    return (f'<div class="msg">{head}<p>{e(tr("Amount outstanding: {0}|pay page", txt, lg=lg))}</p>'
            + (f'<p class="sub" role="status">{e(note)}</p>' if note else "")
            + f'<form method="post" action="/s/pay/{e(token)}/go" class="fform"><button type="submit">{e(tr("Pay now", lg=lg))}</button>'
            f'<details><summary>{e(tr("Pay part of it", lg=lg))}</summary><label for="pol-part">{e(tr("Amount in {0}", cur, lg=lg))}</label>'
            f'<input id="pol-part" name="amount" inputmode="decimal" maxlength="14" autocomplete="off"></details>'
            + (f'<p class="err" role="alert">{e(error)}</p>' if error else "") + '</form></div>')


def pol_answer(c, oid, r, token, conf, lg, error=None, code=200, back=None):
    st, amount = pol_payable(c, oid, r)
    title = tr("Pay invoice", lg=lg)
    if st is None:
        return pub_gone(lg)
    if st == "paid":
        return pub_html(title, f'<div class="msg"><h1>{html.escape(tr("This invoice is paid", lg=lg))}</h1>'
                               f'<p>{html.escape(tr("Thank you. You can close this page.", lg=lg))}</p></div>', lg, 200)
    return pol_page_headers(pub_html(title, pol_form(c, oid, r, token, amount, lg, error, back), lg, code), POL_ADAPTERS[conf["provider"]])


def pol_rate_bad():
    return hit_limit("polbad:" + rate_ip(), PUB_BAD_LIMIT)


@app.get("/s/pay/<token>")
def pol_page(token):
    """The pay page of a link: the same "not available" for unknown, switched off, cancelled and draft ones."""
    c = db()
    lg = _accept_lang()
    if hit_limit("polv:" + rate_ip(), POL_VIEW_RATE):
        return pub_limited(lg)
    f = pol_find(c, token)
    if not f:
        return pub_limited(lg) if pol_rate_bad() else pub_gone(lg)
    _link, r, conf = f
    return pol_answer(c, r["org_id"], r, token, conf, doc_lg(r["lang"]), back=request.args.get("back"))


def _part(v, open_):
    """The amount the customer typed (empty = all that is open), None when it is no amount between 0 and open."""
    v = (v or "").strip().replace(" ", "")
    if not v:
        return open_
    if not POL_AMOUNT_RE.fullmatch(v):
        return None
    head, sep, tail = re.match(r"^(.*)([.,])(\d+)$", v).groups() if re.search(r"[.,]", v) else (v, "", "")
    # the last mark decides, in either language: 1.234,56 and 1,234.56; three digits behind it are a group, not cents (1.500)
    whole, cents = (head + tail, "0") if len(tail) == 3 else (head, tail or "0")
    a = money(Decimal(re.sub(r"\D", "", whole) + "." + cents))
    return a if 0 < a <= open_ else None


@app.post("/s/pay/<token>/go")
def pol_go(token):
    """Starts the checkout: the open amount from the database at this moment, the invoice's currency; then to the provider."""
    c = db()
    lg = _accept_lang()
    if hit_limit("polg:" + rate_ip(), POL_GO_RATE):
        return pub_limited(lg)
    f = pol_find(c, token)
    if not f:
        return pub_limited(lg) if pol_rate_bad() else pub_gone(lg)
    link, r, conf = f
    oid, did = r["org_id"], r["id"]
    lg = doc_lg(r["lang"])
    if hit_limit(f"polgl:{link['id']}", POL_GO_LINK_HOUR, 3600):
        return pub_limited(lg)
    write_lock(c, f"office_doc_{int(did)}")  # never in between a payment by hand
    r = c.execute("SELECT * FROM office_docs WHERE id=? AND org_id=?", (did, oid)).fetchone()
    st, open_ = pol_payable(c, oid, r)
    if st != "open":
        return pol_answer(c, oid, r, token, conf, lg)
    amount = _part(request.form.get("amount"), open_)
    if amount is None:
        return pol_answer(c, oid, r, token, conf, lg, tr("Enter an amount up to what is open", lg=lg), 400)
    cur = (r["currency"] or "EUR").upper()
    minor = pol_minor(amount, cur)
    ad = pol_adapter(conf)
    since = iso(now_utc() - timedelta(seconds=POL_REUSE_S))
    same = c.execute("SELECT url FROM office_pay_sessions WHERE org_id=? AND doc_id=? AND state='open' AND amount_minor=? AND currency=? AND created_at>=? AND url<>'' "
                     "ORDER BY id DESC LIMIT 1", (oid, did, minor, cur, since)).fetchone()
    if same:  # pressed again: the checkout that is open, never a second one to pay
        c.rollback()
        return redirect(same["url"], 303)
    old = [x["ext_id"] for x in c.execute("SELECT ext_id FROM office_pay_sessions WHERE org_id=? AND doc_id=? AND state='open' AND ext_id<>''", (oid, did)).fetchall()]
    ts = iso(now_utc())
    sid = insert_id(c, "INSERT INTO office_pay_sessions(org_id, doc_id, provider, amount_minor, currency, state, created_at, updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (oid, did, conf["provider"], minor, cur, "new", ts, ts))
    c.execute("UPDATE office_pay_sessions SET state='expired', updated_at=? WHERE org_id=? AND doc_id=? AND state='open'", (ts, oid, did))
    c.commit()  # nothing is held during the calls to the provider
    base = f"{PUBLIC_URL.rstrip('/')}/s/pay/{token}"
    try:
        for x in old:  # best effort: a checkout still open elsewhere; one paid anyway is booked or held by the webhook
            try:
                ad.expire(x)
            except PolError:
                pass
        ext, url = ad.create(sid, minor, cur, tr("Invoice {0}|pay page", r["number"] or "", lg=lg), f"{base}?back=ok", f"{base}?back=no", int(time.time()) + POL_EXPIRE_S)
    except PolError as e:
        app.logger.warning("online payment: checkout failed: %s", e.code)
        c.execute("UPDATE office_pay_sessions SET state='failed', updated_at=? WHERE id=? AND org_id=?", (iso(now_utc()), sid, oid))
        c.commit()
        return pol_answer(c, oid, r, token, conf, lg, tr("Paying online does not work right now. Please try again later.", lg=lg), 502)
    c.execute("UPDATE office_pay_sessions SET ext_id=?, url=?, state='open', updated_at=? WHERE id=? AND org_id=?", (ext, url, iso(now_utc()), sid, oid))
    c.commit()
    return redirect(url, 303)


# ---------------------------------------------------------------- payouts in the bank reconciliation
def pol_bank_info(c, oid):
    """What the bank list needs: {payouts, marks, name} of an office with a connection, else None."""
    r = c.execute("SELECT provider FROM office_payonline WHERE org_id=? AND provider<>''", (oid,)).fetchone()
    k = POL_ADAPTERS.get(r["provider"]) if r else None
    if not k:
        return None
    used = {x[0] for x in c.execute("SELECT match_id FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind='payout' AND match_id IS NOT NULL", (oid,))}
    rows = [x for x in c.execute("SELECT * FROM office_pay_payouts WHERE org_id=? ORDER BY day DESC, id DESC LIMIT 200", (oid,)).fetchall() if x["id"] not in used]
    return {"payouts": rows, "marks": k.marks, "name": k.name}


def pol_bank_hit(t, info, norm):
    """The suggestion "collective payout" for open booking t (money in): a payout known with this amount, or the provider's name in
    the booking; it replaces the invoice suggestions (booked online already). None = no such booking."""
    if not info or t["amount"] <= 0:
        return None
    label = tr("Collective payout {0}", info["name"])
    for p in info["payouts"]:
        if (p["currency"] or "").upper() == t["currency"] and pol_major(p["amount_minor"], p["currency"]) == t["amount"]:
            return {"kind": "payout", "id": p["id"], "label": label, "amount": dstr(t["amount"]), "reason": tr("same amount")}
    text = f" {norm(t['counterpart'] or '')} {norm(t['purpose'] or '')} "
    if any(f" {m} " in text for m in info["marks"]):
        return {"kind": "payout", "id": 0, "label": label, "amount": dstr(t["amount"]), "reason": tr("name matches")}
    return None


def pol_bank_match(c, oid, uid, t, mid):
    """bank.py kind payout: the booking is the provider's collective transfer. No payment (the invoices were paid by the webhook), so
    nothing counts twice; with its payout known the fees become one receipt. Returns (payout id or None, the fees' receipt id or None)."""
    if t["amount"] <= 0:
        raise Denied(409, tr("Only money received can be a payout"))
    if not mid:
        return None, None
    p = c.execute("SELECT * FROM office_pay_payouts WHERE id=? AND org_id=?", (mid, oid)).fetchone()
    if not p:
        raise Denied(404)
    if c.execute("SELECT 1 FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND match_kind='payout' AND match_id=? LIMIT 1", (oid, mid)).fetchone():
        raise Denied(409, tr("This payout is matched with another booking"))
    return mid, pol_fee_book(c, oid, uid, p)


def pol_fee_book(c, oid, uid, p):
    """The provider's fees of payout row p as one receipt of the office (never twice): the books count receipts as expenses."""
    from ..docs.ingest import docs_ingest
    from ..docs.store import doc_ws
    from ..receipts.suggest import rc_set
    from .books import bk_receipt_set_paid
    if p["node_id"]:
        return p["node_id"]
    conf = pol_conf(c, oid)
    ad = pol_adapter(conf) if conf["provider"] == p["provider"] else None
    if ad is None:
        return None
    try:
        fee = ad.payout_fees(p["ext_id"])
    except PolError as e:
        app.logger.warning("online payment: fees of a payout not read: %s", e.code)
        return None
    c.execute("UPDATE office_pay_payouts SET fee_minor=? WHERE id=? AND org_id=?", (fee, p["id"], oid))
    if fee <= 0:
        return None
    cur, amount = p["currency"] or "EUR", dstr(pol_major(fee, p["currency"]))
    owner = pb_owner(c, oid)
    text = tr("Fees of {0}, payout {1} of {2}: {3} {4}", ad.name, p["ext_id"], p["day"], amount, cur)
    nid = docs_ingest(c, uid, None if owner else oid, f"{p['provider']}-fees-{p['day']}-{p['id']}.txt", text.encode(), "text/plain", source="payonline",
                      meta={"date": p["day"], "amount": amount, "currency": cur, "sender": ad.name, "text": text, "ext_id": f"payonline:{p['provider']}:{p['ext_id']}"})
    node = c.execute("SELECT id, org_id FROM fs_nodes WHERE id=?", (nid,)).fetchone()
    rc_set(c, node, doc_ws(None, owner) if owner else doc_ws(oid, None), None, "", uid, keep=True)
    try:
        bk_receipt_set_paid(c, oid, nid, p["day"])
    except Denied:  # a locked month: the receipt counts by its document date
        pass
    c.execute("UPDATE office_pay_payouts SET node_id=? WHERE id=? AND org_id=?", (nid, p["id"], oid))
    return nid


# ---------------------------------------------------------------- routes of the office
def _admin():
    c, uid, oid = office_ctx(admin=True)
    if not ofr_admin_or(c, uid, oid, "offers", "manage"):
        raise Denied(403)
    return c, uid, oid


@app.get("/api/office/payonline")
def pol_get():
    """The connection of the office area (never a key: key_set, webhook_secret_set); webhook_url, held, payouts for its admins."""
    c, uid, oid = office_ctx()
    return jsonify(pol_public(c, oid, ofr_admin_or(c, uid, oid, "offers", "manage")))  # who may write (_admin) sees what they would change


@app.put("/api/office/payonline")
def pol_put():
    """{provider?, enabled?, secret_key?, webhook_secret?} (admins; without an organisation the person)."""
    c, uid, oid = _admin()
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    pol_save(c, oid, uid, b)
    bump(c)
    c.commit()
    return jsonify(pol_public(c, oid, True))


@app.post("/api/office/payonline/check")
def pol_check():
    """Tries the stored key at the provider -> {ok, code?}."""
    c, _uid, oid = _admin()
    ad = pol_adapter(pol_conf(c, oid))
    if ad is None:
        raise Denied(409, tr("Enter the key and the webhook secret first"))
    try:
        ad.check()
    except PolError as e:
        return jsonify(ok=False, code=e.code)
    return jsonify(ok=True)


@app.post("/api/office/payonline/rotate")
def pol_rotate():
    """A new webhook address (the old one stops at once); enter it at the provider."""
    c, uid, oid = _admin()
    conf = pol_conf(c, oid)
    if not conf["provider"]:
        raise Denied(409, tr("Choose a provider first"))
    conf["hook_token"], conf["hook_hash"] = pol_new_hook()
    pol_write(c, oid, uid, conf)
    ofx_log(c, oid, "payonline_setup", target="settings", detail={"hook_rotated": 1})
    bump(c)
    c.commit()
    return jsonify(pol_public(c, oid, True))


def _held(c, oid, eid):
    r = c.execute("SELECT * FROM office_pay_events WHERE id=? AND org_id=? AND state='held'", (eid, oid)).fetchone()
    if not r:
        raise Denied(404)
    return r


@app.post("/api/office/payonline/events/<int:eid>/retry")
def pol_retry(eid):
    """Books a held event again (the month open again, the invoice open again); it may stay held. A reported difference stays."""
    c, _uid, oid = _admin()
    r = _held(c, oid, eid)
    if r["reason"] == "mismatch":
        raise Denied(409, tr(POL_HOLD["mismatch"]))
    conf = pol_conf(c, oid)
    s = c.execute("SELECT * FROM office_pay_sessions WHERE id=? AND org_id=?", (r["session_id"], oid)).fetchone()
    if not s:
        raise Denied(404)
    ev = {"kind": r["kind"], "ref": r["ref"], "amount": r["amount_minor"], "pay_ref": "", "currency": "", "day": r["occurred"]}
    if r["kind"] == "paid":
        pol_on_paid(c, oid, conf, eid, ev)
    else:
        pol_on_back(c, oid, conf, eid, ev)
    bump(c)
    c.commit()
    return jsonify(pol_public(c, oid, True))


@app.post("/api/office/payonline/events/<int:eid>/done")
def pol_done(eid):
    """A person dealt with a held event themselves (refunded at the provider, booked by hand)."""
    c, _uid, oid = _admin()
    r = _held(c, oid, eid)
    c.execute("UPDATE office_pay_events SET state='done', reason=? WHERE id=? AND org_id=?", ("dismissed", eid, oid))
    s = c.execute("SELECT * FROM office_pay_sessions WHERE id=? AND org_id=?", (r["session_id"], oid)).fetchone()
    if s and r["kind"] == "paid":  # nothing will book it now: what waited for this payment ends here too
        pol_wake(c, oid, pol_conf(c, oid), s)
    ofx_log(c, oid, "payonline_held_done", target="settings", detail={"event": eid, "reason": r["reason"]})
    bump(c)
    c.commit()
    return jsonify(pol_public(c, oid, True))


@app.put("/api/office/docs/<int:did>/pay-online")
def pol_switch(did):
    """{on} the invoice's switch: off = its link shows "not available" and no new checkout starts (a printed link included). A
    finalised invoice may be switched: the document stays as it is. Who may book payments may switch."""
    c, uid, oid = office_ctx()
    r = doc_row(c, oid, did)
    if not _ofr_pay(c, uid, oid):
        raise Denied(403, tr("Only an admin of this organisation can record payments"))
    if r["kind"] != "invoice":
        raise Denied(409, tr("Only invoices can be paid online"))
    b = body()
    on = isinstance(b, dict) and b.get("on") in (1, True, "1", "true")
    pol_link(c, oid, did)
    c.execute("UPDATE office_pay_links SET off=? WHERE org_id=? AND doc_id=?", (0 if on else 1, oid, did))
    ofx_log(c, oid, "payonline_switch", doc_id=did, detail={"on": on})
    bump(c)
    c.commit()
    d = {"kind": "invoice", "id": did}
    pol_doc_extra(c, oid, d, True)
    return jsonify(d["pay_online"])
