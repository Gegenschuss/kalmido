"""2.616.0 (#2473): the direct bank fetch over FinTS (PIN/TAN) of a bank account of the office -- no account service in
between. The statements the bank sends (CAMT.052 / .053, else MT940) go through exactly the way of the file import
(office/bank.py bnk_parse / bnk_import_of: duplicates, the bank rules, the matching, the take-back).

Off until the server has a FinTS product registration number (KALMIDO_FINTS_PRODUCT_ID, given by the Deutsche Kreditwirtschaft
to whoever runs the instance; it never belongs in a public repository) and the library python-fints is installed (imported
only when a fetch runs). Then GET /api/office/bank/fints says on, else off with a code (no_product_id | no_library) and every
other route answers 503 with that code.

A fetch is a dialog with the bank, held in the memory of this process only (waitress runs one process): start (account,
login name, PIN, period) -> maybe the choice of the TAN method -> maybe the approval (in the banking app = decoupled, polled;
or a TAN typed in) -> the statements -> the preview of the file import -> the import. A dialog belongs to the person and the
office area that started it (anybody else: 404), lives FNT_TTL seconds after its last step (at most FNT_MAX_AGE), and is
closed and forgotten at its end, on cancel and on expiry (a background timer sweeps at the expiry itself). The PIN and a TAN are never stored, logged, sent back, put in an
error text, an event or the audit; the login name and the server address may be remembered per account (the PIN never),
once the bank has sent the statements; a new server address is written to the office log.
After a refusal of the bank (wrong PIN / login, locked access) nothing is tried again by itself, and FNT_FAIL_MAX refusals
per account within FNT_FAIL_WINDOW seconds stop new starts for that account for the rest of the window (the bank locks the
access after a few wrong PINs).

The bank server is talked to through calendars/subscriptions.cal_http (https only, every hop through the SSRF guard: no
internal address, no redirect to another host). Rights: those of the file import (office_ctx_admin: the admins of the office
area, the person in a personal office); agents and kids 403 (office_gate): an agent never handles a PIN.
Tests: KALMIDO_TEST=1 + KALMIDO_TEST_FINTS_FAKE=1 swaps the bank for _FakeBank (no network)."""
import base64
import importlib.util
import logging
import os
import re
import secrets
import threading
import time
from datetime import date, timedelta

from flask import jsonify, request

from ..core.config import app
from ..core.db import body, bump, iso, local_now, now_utc
from ..core.errors import BadInput, Denied
from ..core.i18n import N_, tr
from ..core.orgcrypt import oc_dec_fields, oc_enc_fields
from ..core.pg import write_lock
from ..core import stmtfiles as sf
from ..calendars.subscriptions import CalError, cal_http
from .model import office_ctx_admin as _ctx
from .bankacc import BKA_TABLE, bka_seed
from . import bank as bnk
from .ledger import ofx_log

# 2.616.0 (#2473, Fable finding 3): the library's log (client._log_response names the bank's answer texts and parameters, its
# debug output accounts and amounts) says nothing on this server -- set once here, not per bank object
logging.getLogger("fints").setLevel(logging.CRITICAL + 1)

FNT_ENV = "KALMIDO_FINTS_PRODUCT_ID"
FNT_TTL = 300  # seconds a dialog lives after its last step
FNT_MAX_AGE = 900  # seconds a dialog lives at most
FNT_DIALOGS_MAX = 40  # open dialogs of the process
FNT_BUSY_MAX = 4  # dialogs talking to a bank at the same moment (each holds a server thread while it waits)
FNT_FAIL_MAX = 2  # refusals of the bank per account ...
FNT_FAIL_WINDOW = 3600  # ... in this many seconds stop new starts
FNT_STARTS_MAX = 10  # starts per person ...
FNT_STARTS_WINDOW = 600  # ... in this many seconds
FNT_DAYS_MAX = 730  # the longest period of one fetch
FNT_DAYS_DEFAULT = 90  # an account without bookings: the last 90 days (most banks give them without a TAN)
FNT_POLL_MIN = 2.0  # seconds between two status questions to the bank (decoupled approval)
FNT_HTTP_TIMEOUT = 60
FNT_HTTP_MAX = 30 * 1024 * 1024
FNT_STEP_MAX = 240  # 2.616.0 (Fable finding 2): seconds one step may talk to the bank in all (below FNT_TTL: no expiry mid-step)
FNT_STEP_HOPS = 50  # requests to the bank within one step (the touchdowns of a long statement)
FNT_STEP_BYTES = bnk.BNK_UNPACKED_MAX  # bytes the bank may send within one step, all answers together
FNT_SWEEP = 60  # 2.616.0 (Fable finding 1): the background sweep runs at the latest after this many seconds
LOGIN_MAX = 64
SERVER_MAX = 300
_PIN_MAX = 64
_TAN_MAX = 64

# the readable messages per code (the answer carries the code too; never a text of the bank library)
FNT_MSG = {
    "no_product_id": N_("The bank fetch is not set up on this server (FinTS product registration missing)."),
    "no_library": N_("The bank fetch is not available on this server (the FinTS library is missing)."),
    "pin": N_("The bank refused the sign-in. Please check the sign-in name and the PIN. Kalmido does not try again by itself."),
    "locked": N_("The bank has locked the online access for now. Please unlock it with your bank first."),
    "wait": N_("The bank refused the sign-in several times. Please wait an hour or check the details with your bank."),
    "busy": N_("Too many bank fetches at once. Please try again in a moment."),
    "too_many": N_("Too many bank fetches. Please wait a few minutes."),
    "connection": N_("The bank's FinTS server cannot be reached. Please check the server address."),
    "blocked": N_("This server address is not allowed (only https addresses on the internet)."),
    "unsupported": N_("The bank does not offer the statement over FinTS for this account."),
    "no_account": N_("The bank does not list this IBAN for this sign-in name."),
    "tan_method": N_("This TAN method cannot be used here (e.g. a flicker code). Please select another one."),
    "bank": N_("The bank answered with an error. Please try again later."),
    "too_large": N_("The bank sent more than one fetch may take. Please select a shorter period."),
    "expired": N_("The bank connection has ended (time out). Please start again."),
    "state": N_("This step does not fit the state of the bank connection."),
}


class FintsError(Exception):
    """A dialog ends with code (FNT_MSG); never carries a text of the bank or the library."""

    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _test():
    return os.environ.get("KALMIDO_TEST") == "1"


def fnt_fake():
    """The stand-in bank: test containers only (both switches)."""
    return _test() and os.environ.get("KALMIDO_TEST_FINTS_FAKE") == "1"


def fnt_product_id():
    return (os.environ.get(FNT_ENV) or "").strip()


def fnt_off():
    """None = the fetch is on, else the code why not (no_product_id | no_library)."""
    if not fnt_product_id():
        return "no_product_id"
    if not fnt_fake() and importlib.util.find_spec("fints") is None:
        return "no_library"
    return None


def _fail(code, status=409, **more):
    raise Denied(status, tr(FNT_MSG[code]), {"code": code, **more})


def _need_on():
    off = fnt_off()
    if off:
        _fail(off, 503)


# ---------------------------------------------------------------- the bank (behind one small interface)
class _Need:
    """The bank asks for an approval: decoupled (in the banking app, polled) or a TAN typed in (challenge text, maybe an image)."""

    def __init__(self, decoupled, challenge="", image=None):
        self.decoupled, self.challenge, self.image = bool(decoupled), str(challenge or "")[:2000], image


class _Done:
    """The statements: [(fmt camt | mt940, text)]."""

    def __init__(self, statements):
        self.statements = statements


def _plain(html_text):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", str(html_text or ""))).strip()


class _RealBank:
    """python-fints (FinTS 3.0 PIN/TAN). Every method may raise FintsError; nothing of the library leaves this class."""

    def __init__(self, blz, login, pin, server, product_id):
        from fints import client as fc  # noqa: PLC0415  the library only when a fetch runs
        from fints import exceptions as fe  # noqa: PLC0415
        self.fc, self.fe = fc, fe
        self.server = server
        try:
            self.c = fc.FinTS3PinTanClient(blz, login, pin, server, product_id=product_id)
            self.c.connection = _Conn(server)
        except Exception:  # noqa: BLE001  no text of the library (it may name what it got)
            raise FintsError("bank") from None
        self.stage, self.pending, self.entered, self.iban, self.frm, self.to = None, None, False, "", None, None

    def begin(self):
        """A new step: its own budget of time, requests and bytes (_Conn)."""
        conn = getattr(self.c, "connection", None) if self.c is not None else None
        if isinstance(conn, _Conn):
            conn.begin()

    def _call(self, fn, *a):
        fe = self.fe
        try:
            return fn(*a)
        except FintsError:
            raise
        except fe.FinTSClientPINError:
            raise FintsError("pin") from None
        except fe.FinTSClientTemporaryAuthError:
            raise FintsError("locked") from None
        except fe.FinTSConnectionError:
            raise FintsError("connection") from None
        except fe.FinTSUnsupportedOperation:
            raise FintsError("unsupported") from None
        except NotImplementedError:
            raise FintsError("tan_method") from None
        except Exception:  # noqa: BLE001  everything else of the bank or the library: one code, no text
            raise FintsError("bank") from None

    def mechanisms(self):
        def run():
            self.c.fetch_tan_mechanisms()
            return [{"id": str(k), "name": _plain(getattr(v, "name", "") or k)[:80]} for k, v in self.c.get_tan_mechanisms().items() if str(k) != "999"]
        return self._call(run)

    def set_mechanism(self, mid):
        self._call(self.c.set_tan_mechanism, mid)

    def _media(self):
        """A TAN medium where the bank wants one named: the first one it lists (Annahme: one device per login is the usual case)."""
        if self.c.is_tan_media_required() and not self.c.selected_tan_medium:
            got = self.c.get_tan_media()
            media = got[1] if isinstance(got, tuple) and len(got) > 1 else []
            if media:
                self.c.set_tan_medium(media[0])

    def run(self, iban, frm, to):
        self.iban, self.frm, self.to, self.stage = iban, frm, to, "init"
        return self._call(self._go, _NONE)

    def tan(self, value):
        def run():
            r = self.c.send_tan(self.pending, value or "")
            if isinstance(r, self.fc.NeedTANResponse):
                return self._need(r)
            self.pending = None
            return self._go(r)
        if self.pending is None:
            raise FintsError("state")
        return self._call(run)

    def _need(self, r):
        self.pending = r
        if not r.decoupled and getattr(r, "challenge_hhduc", None) and not getattr(r, "challenge_matrix", None):
            raise FintsError("tan_method")  # a flicker code (chipTAN optic) cannot be shown here
        img = None
        mx = getattr(r, "challenge_matrix", None)
        if mx and isinstance(mx, tuple) and str(mx[0]).startswith("image/") and len(mx[1]) < 200000:
            img = "data:" + re.sub(r"[^a-z/+.-]", "", str(mx[0]).lower()) + ";base64," + base64.b64encode(mx[1]).decode()
        return _Need(r.decoupled, _plain(r.challenge_html or r.challenge), img)

    def _go(self, res):
        fc = self.fc
        if self.stage == "init":
            if res is _NONE:
                self._media()
                self.c.__enter__()
                self.entered = True
                if self.c.init_tan_response:
                    return self._need(self.c.init_tan_response)
            self.stage, res = "accounts", _NONE
        if self.stage == "accounts":
            if res is _NONE:
                res = self.c.get_sepa_accounts()
                if isinstance(res, fc.NeedTANResponse):
                    return self._need(res)
            acc = next((a for a in res or () if (a.iban or "").replace(" ", "").upper() == self.iban), None)
            if acc is None:
                raise FintsError("no_account")
            self.acc, self.stage, res = acc, "tx", _NONE
        if self.stage == "tx":
            if res is _NONE:
                res = self._fetch()
                if isinstance(res, fc.NeedTANResponse):
                    return self._need(res)
            return _Done(self._texts(res))
        raise FintsError("state")

    def _fetch(self):
        """CAMT (HKCAZ) when the bank offers it, else MT940 (HKKAZ) as the raw text (the library's own MT940 path parses it
        into objects; the file import reads the text itself, so the raw statement is taken from the same touchdown loop)."""
        c, fe = self.c, self.fe
        try:
            c._find_highest_supported_command(self.fc.HKCAZ1)
            self.fmt = "camt"
            return c.get_transactions_xml(self.acc, self.frm, self.to)
        except fe.FinTSUnsupportedOperation:
            pass
        self.fmt = "mt940"
        hkkaz = c._find_highest_supported_command(self.fc.HKKAZ5, self.fc.HKKAZ6, self.fc.HKKAZ7)
        acc = self.acc
        return c._fetch_with_touchdowns(
            c._get_dialog(),
            lambda td: hkkaz(account=hkkaz._fields["account"].type.from_sepa_account(acc), all_accounts=False,
                             date_start=self.frm, date_end=self.to, touchdown_point=td),
            lambda resps: "".join(seg.statement_booked.decode("iso-8859-1") for seg in resps),
            "HIKAZ")

    def _texts(self, res):
        if self.fmt == "camt":
            booked = res[0] if isinstance(res, tuple) else res
            return [("camt", b.decode("utf-8", "replace") if isinstance(b, bytes) else str(b)) for b in booked or () if b]
        return [("mt940", res)] if isinstance(res, str) and res.strip() else []

    def close(self):
        try:
            if self.entered:
                self.entered = False
                self.c.__exit__(None, None, None)
        except Exception:  # noqa: BLE001,S110  the end of the dialog is best effort
            pass
        self.c = None


class _Conn:
    """The library's HTTPS connection, through cal_http (SSRF guard, no redirect to another host, size and time limits).
    2.616.0 (Fable finding 2): per step (begin) at most FNT_STEP_HOPS requests, FNT_STEP_BYTES bytes of answers together and
    FNT_STEP_MAX seconds in all -- a hostile "bank" with endless touchdowns or huge answers holds no thread and fills no memory.
    http / msg_cls: test containers only (POST /api/test/fints/conn)."""

    def __init__(self, url, http=None, msg_cls=None):
        if msg_cls is None:
            from fints.message import FinTSInstituteMessage as msg_cls  # noqa: PLC0415,N813
        self.url, self.msg_cls, self.http = url, msg_cls, http or cal_http
        self.begin()

    def begin(self, until=None):
        self.hops, self.bytes, self.until = 0, 0, until if until is not None else time.monotonic() + FNT_STEP_MAX

    def send(self, msg):
        if self.hops >= FNT_STEP_HOPS:
            raise FintsError("too_large")
        left = self.until - time.monotonic()
        if left <= 0:
            raise FintsError("connection")
        self.hops += 1
        try:
            status, _h, data, _u = self.http(self.url, "POST", base64.b64encode(msg.render_bytes()), {"Content-Type": "text/plain"},
                                             max_bytes=max(1, min(FNT_HTTP_MAX, FNT_STEP_BYTES - self.bytes)),
                                             timeout=min(FNT_HTTP_TIMEOUT, left), until=min(time.monotonic() + FNT_HTTP_TIMEOUT + 30, self.until))
        except CalError as x:
            if x.code == "too_large":
                raise FintsError("too_large") from None
            raise FintsError("blocked" if x.code in ("blocked", "redirect", "config") else "connection") from None
        self.bytes += len(data or b"")
        if self.bytes > FNT_STEP_BYTES:
            raise FintsError("too_large")
        if not 200 <= status <= 299:
            raise FintsError("connection")
        return self.msg_cls(segments=base64.b64decode(data.decode("iso-8859-1")))


_NONE = object()


class _FakeBank:
    """The stand-in bank of the test containers. Login name: 'decoupled' -> approval in the app (the first status question
    still waits, the second is approved); 'tan' -> a TAN (123456); 'mech' -> two TAN methods to choose first; else no approval.
    PIN 'wrong' -> the bank refuses the sign-in; 'locked' -> the access is locked. The statement: CAMT.053 with two bookings on
    the last day of the period (the same ones on every fetch, so a second fetch finds them again)."""

    def __init__(self, blz, login, pin, server, product_id):
        self.login, self.pin, self.polls, self.pending, self.mech = login, pin, 0, None, None

    def begin(self):
        pass

    def mechanisms(self):
        if self.pin == "wrong":
            raise FintsError("pin")
        if self.pin == "locked":
            raise FintsError("locked")
        return [{"id": "921", "name": "pushTAN 2.0"}, {"id": "942", "name": "mobile TAN"}] if self.login == "mech" else [{"id": "921", "name": "pushTAN 2.0"}]

    def set_mechanism(self, mid):
        self.mech = mid

    def run(self, iban, frm, to):
        self.iban, self.frm, self.to = iban, frm, to
        if self.login == "decoupled":
            self.pending = "decoupled"
            return _Need(True, "Please confirm the fetch in your banking app")
        if self.login == "tan":
            self.pending = "tan"
            return _Need(False, "Please enter the TAN from your device")
        return _Done(self._statements())

    def tan(self, value):
        if self.pending == "decoupled":
            self.polls += 1
            return _Need(True, "Please confirm the fetch in your banking app") if self.polls < 2 else _Done(self._statements())
        if self.pending == "tan":
            if value != "123456":
                raise FintsError("pin")
            return _Done(self._statements())
        raise FintsError("state")

    def _statements(self):
        self.pending = None
        d = self.to.isoformat()
        e = lambda amt, ind, nm, rmt, ref: (  # noqa: E731
            f"<Ntry><Amt Ccy=\"EUR\">{amt}</Amt><CdtDbtInd>{ind}</CdtDbtInd><Sts>BOOK</Sts><BookgDt><Dt>{d}</Dt></BookgDt><ValDt><Dt>{d}</Dt></ValDt>"
            f"<NtryDtls><TxDtls><Refs><EndToEndId>{ref}</EndToEndId></Refs><RltdPties><{'Dbtr' if ind == 'CRDT' else 'Cdtr'}><Nm>{nm}</Nm></{'Dbtr' if ind == 'CRDT' else 'Cdtr'}></RltdPties>"
            f"<RmtInf><Ustrd>{rmt}</Ustrd></RmtInf></TxDtls></NtryDtls></Ntry>")
        xml = ('<?xml version="1.0" encoding="UTF-8"?><Document xmlns="urn:iso:std:iso:20022:tech:xsd:camt.053.001.02"><BkToCstmrStmt>'
               f'<GrpHdr><MsgId>FAKE-{d}</MsgId><CreDtTm>{d}T12:00:00</CreDtTm></GrpHdr><Stmt><Id>FAKE-{d}</Id><Acct><Id><IBAN>{self.iban}</IBAN></Id></Acct>'
               + e("119.00", "CRDT", "Fake Customer GmbH", "Invoice R-FAKE-1", "FINTS-FAKE-1")
               + e("23.80", "DBIT", "Fake Supplier AG", "Order 4711", "FINTS-FAKE-2")
               + "</Stmt></BkToCstmrStmt></Document>")
        return [("camt", xml)]

    def close(self):
        self.pin = None


# 2.616.0 (#2473, Fable finding 6): the inner parts of python-fints _RealBank uses beyond its public interface (a new
# version may rename them; GET /api/test/fints/lib in the test containers lists what is missing, so a bump shows in the CI)
_LIB_CLIENT = ("_find_highest_supported_command", "_fetch_with_touchdowns", "_get_dialog", "get_transactions_xml", "get_sepa_accounts",
               "fetch_tan_mechanisms", "get_tan_mechanisms", "set_tan_mechanism", "is_tan_media_required", "get_tan_media",
               "set_tan_medium", "send_tan", "__enter__", "__exit__")
_LIB_OBJECT = ("connection", "init_tan_response", "selected_tan_medium")
_LIB_EXC = ("FinTSClientPINError", "FinTSClientTemporaryAuthError", "FinTSConnectionError", "FinTSUnsupportedOperation")


def fnt_lib_missing():
    """The parts of the installed python-fints _RealBank needs that are not there ([] = all there; None = not installed)."""
    if importlib.util.find_spec("fints") is None:
        return None
    from fints import client as fc, exceptions as fe, message as fm  # noqa: PLC0415
    miss = [f"FinTS3PinTanClient.{n}" for n in _LIB_CLIENT if not callable(getattr(fc.FinTS3PinTanClient, n, None))]
    miss += [f"client.{n}" for n in ("HKCAZ1", "HKKAZ5", "HKKAZ6", "HKKAZ7", "NeedTANResponse") if not hasattr(fc, n)]
    miss += [f"exceptions.{n}" for n in _LIB_EXC if not hasattr(fe, n)]
    miss += [] if hasattr(fm, "FinTSInstituteMessage") else ["message.FinTSInstituteMessage"]
    for n in ("HKKAZ5", "HKKAZ6", "HKKAZ7"):
        try:
            if not callable(getattr(fc, n)._fields["account"].type.from_sepa_account):
                miss.append(f"{n}._fields[account].type.from_sepa_account")
        except Exception:  # noqa: BLE001
            miss.append(f"{n}._fields[account].type.from_sepa_account")
    try:  # no network: the constructor only keeps its arguments
        cl = fc.FinTS3PinTanClient("12345678", "test", "test", "https://fints.invalid/", product_id="TEST")
        miss += [f"FinTS3PinTanClient().{n}" for n in _LIB_OBJECT if not hasattr(cl, n)]
    except Exception as x:  # noqa: BLE001
        miss.append(f"FinTS3PinTanClient(): {type(x).__name__}")
    return miss


def _bank(blz, login, pin, server):
    return (_FakeBank if fnt_fake() else _RealBank)(blz, login, pin, server, fnt_product_id())


# ---------------------------------------------------------------- the dialogs (memory of this process only)
_DLG = {}
_LOCK = threading.Lock()
_BUSY = threading.BoundedSemaphore(FNT_BUSY_MAX)
_FAILS = {}  # (oid, account id) -> [monotonic times of refusals]
_STARTS = {}  # uid -> [monotonic times of starts]
_SHIFT = [0.0]  # test containers: seconds added to the clock of the dialogs (POST /api/test/fints/age)


def _now():
    return time.monotonic() + _SHIFT[0]


class _Dialog:
    def __init__(self, uid, oid, acct, conn, frm, to):
        self.id = secrets.token_urlsafe(24)
        self.uid, self.oid, self.acct, self.conn, self.frm, self.to = uid, oid, acct, conn, frm, to
        self.born = self.seen = _now()
        self.state, self.mechanisms, self.need, self.statements, self.polled = "new", [], None, [], 0.0
        self.remember = None  # (login, server) to keep at the account once the sign-in worked
        self.lock = threading.Lock()

    def expired(self, t=None):
        t = _now() if t is None else t
        return t - self.seen > FNT_TTL or t - self.born > FNT_MAX_AGE


def _close(d):
    conn, d.conn, d.statements, d.need = d.conn, None, [], None
    if conn is not None:
        threading.Thread(target=conn.close, daemon=True, name="fints-close").start()  # the bank's dialog end may take a while


def _sweep():
    """Expired dialogs go (called under _LOCK). 2.616.0 (#2473, Fable re-check): a dialog in a running step (its lock held)
    stays until the step is over -- the step is bounded by FNT_STEP_MAX, and closing the bank client under it would end the
    step with "bank" instead of a clean result; the next tick takes it."""
    t = _now()
    for k in [k for k, d in _DLG.items() if d.expired(t) and not d.lock.locked()]:
        _close(_DLG.pop(k))


_TICK = {"timer": None}


def _sweep_delay():
    """Seconds to the next expiry of an open dialog (at most FNT_SWEEP; test containers: KALMIDO_TEST_FINTS_SWEEP caps it)."""
    t, cap = _now(), FNT_SWEEP
    if _test():
        try:
            cap = min(cap, float(os.environ.get("KALMIDO_TEST_FINTS_SWEEP") or cap))
        except ValueError:
            pass
    nxt = min((max(5.0, min(d.seen + FNT_TTL, d.born + FNT_MAX_AGE) - t) if d.lock.locked()
               else min(d.seen + FNT_TTL, d.born + FNT_MAX_AGE) - t for d in _DLG.values()), default=cap)
    return max(0.5, min(cap, nxt + 0.5))


def _arm():
    """2.616.0 (#2473, Fable finding 1): the background sweep -- an expired dialog (the PIN in its bank object, the open bank
    dialog) goes at its expiry, not only with the next FinTS request. One daemon timer while a dialog is open (under _LOCK)."""
    tm = _TICK["timer"]
    if _DLG and (tm is None or not tm.is_alive()):
        tm = threading.Timer(_sweep_delay(), _tick)
        tm.daemon, tm.name = True, "fints-sweep"
        _TICK["timer"] = tm
        tm.start()


def _tick():
    with _LOCK:
        _TICK["timer"] = None
        _sweep()
        _arm()


def _drop(d):
    with _LOCK:
        if _DLG.get(d.id) is d:
            del _DLG[d.id]
    _close(d)


def _dialog(did, uid, oid):
    """The open dialog did of uid in office area oid -- anybody else's or an expired one: 404."""
    with _LOCK:
        _sweep()
        d = _DLG.get(str(did))
        if d is None or d.uid != uid or d.oid != oid:
            raise Denied(404, tr(FNT_MSG["expired"]), {"code": "expired"})
        d.seen = _now()
        return d


def _window(store, key, window):
    t = _now()
    xs = [x for x in store.get(key, ()) if t - x < window]
    store[key] = xs
    return xs


def _step(d, fn):
    """One step that talks to the bank: one at a time per dialog, at most FNT_BUSY_MAX at once. A FintsError ends the dialog
    (no step is tried again by itself); a refusal of the bank counts for the account."""
    if not _BUSY.acquire(blocking=False):
        _fail("busy", 503)
    try:
        if not d.lock.acquire(blocking=False):
            _fail("busy", 409)
        try:
            if d.conn is None:
                _fail("expired", 404)
            d.conn.begin()
            res = fn()
        finally:
            d.lock.release()
    except FintsError as x:
        if x.code in ("pin", "locked"):
            with _LOCK:
                _window(_FAILS, (d.oid, d.acct["id"]), FNT_FAIL_WINDOW).append(_now())
        _drop(d)
        print(f"fints: the bank fetch of office {d.oid} ended: {x.code}", flush=True)  # the code only, never a text of the bank
        _fail(x.code, 502 if x.code in ("connection", "bank", "too_large") else 409)
    finally:
        _BUSY.release()
    d.seen = _now()
    return res


def _apply(d, res):
    if isinstance(res, _Need):
        d.state, d.need = ("decoupled" if res.decoupled else "tan"), res
    elif isinstance(res, _Done):
        d.state, d.need, d.statements = "preview", None, res.statements
        _close_conn(d)
    else:
        raise FintsError("state")


def _close_conn(d):
    """The statements are in: the bank dialog ends (and the PIN with it); the dialog stays for the preview and the import."""
    conn, d.conn = d.conn, None
    if conn is not None:
        threading.Thread(target=conn.close, daemon=True, name="fints-close").start()


def _files(d):
    fs = sf.StmtFiles(bnk._LIMITS)
    names = []
    for i, (fmt, text) in enumerate(d.statements, 1):
        name = f"FinTS {d.acct['label']} {d.frm.isoformat()}" + (f" ({i})" if len(d.statements) > 1 else "") + (".xml" if fmt == "camt" else ".sta")
        fs.add(name, text.encode("utf-8"))
        names.append(name)
    fs.labels = [tr("Bank fetch {0}: {1} – {2}", d.acct["label"], d.frm.isoformat(), d.to.isoformat())[:200]]
    return fs


def _preview(c, d):
    if not d.statements:
        return {"fmt": "camt", "rows": [], "count": 0, "dup_count": 0, "pending_count": 0, "skipped": 0, "skipped_rows": [],
                "files": 0, "file_errors": [], "skipped_files": [], "camt052": False}
    return bnk.bnk_preview_of(c, d.oid, {}, _files(d))


def _out(c, d, **more):
    a = d.acct
    out = {"id": d.id, "state": d.state, "account": {"id": a["id"], "label": a["label"], "iban_tail": a["iban"][-4:]},
           "from": d.frm.isoformat(), "to": d.to.isoformat(), "expires_in": max(0, int(FNT_TTL - (_now() - d.seen)))}
    if d.state == "mechanism":
        out["mechanisms"] = d.mechanisms
    if d.need is not None:
        out["challenge"] = d.need.challenge
        if d.need.image:
            out["image"] = d.need.image
    if d.state == "preview":
        out["preview"] = _preview(c, d)
    return {"dialog": out, **more}


# ---------------------------------------------------------------- the accounts
def _blz(iban):
    """The German bank code inside a German IBAN ('' for any other: FinTS is a German standard)."""
    return iban[4:12] if re.fullmatch(r"DE\d{20}", iban or "") else ""


def _acct(c, oid, rid):
    if isinstance(rid, bool) or not isinstance(rid, int):
        raise BadInput(tr("Invalid value: {0}", "account_id"))
    r = c.execute(f"SELECT * FROM {BKA_TABLE} WHERE id=? AND org_id=? AND archived=0", (rid, oid)).fetchone()
    if r is None:
        raise Denied(404)
    return oc_dec_fields(c, oid, BKA_TABLE, r)


def _since(c, oid):
    """The first day of a fetch by default: the day of the newest booking of the office area (its day again: the duplicates are
    found), else FNT_DAYS_DEFAULT days back. The bookings carry no account, so this is the newest of the area."""
    r = c.execute("SELECT MAX(day) FROM office_bank_tx WHERE org_id=? AND deleted_at IS NULL AND day<>''", (oid,)).fetchone()
    today = local_now().date()
    try:
        d = date.fromisoformat(r[0]) if r and r[0] else None
    except ValueError:
        d = None
    return max(d, today - timedelta(days=FNT_DAYS_MAX)) if d else today - timedelta(days=FNT_DAYS_DEFAULT)


def _acct_out(c, uid, oid, r):
    out = {"id": r["id"], "label": r["label"], "iban_tail": (r["iban"] or "")[-4:], "blz": _blz(r["iban"] or ""),
           "is_default": bool(r["is_default"]), "login": r.get("fints_login") or "", "server": r.get("fints_server") or "",
           "ok": bool(_blz(r["iban"] or ""))}
    by = r.get("fints_server_by")
    if out["server"] and by and by != uid:  # 2.616.0 (Fable finding 4): the address was set last by somebody else
        u = c.execute("SELECT display_name, username FROM users WHERE id=?", (by,)).fetchone()
        out["server_changed"] = {"by": (u["display_name"] or u["username"]) if u else "", "at": r.get("fints_server_at") or ""}
    return out


def fnt_server_clean(v):
    """A FinTS server address: https, a host name, no user / password, at most SERVER_MAX characters (the SSRF guard checks the
    addresses it resolves to at every request)."""
    import urllib.parse  # noqa: PLC0415
    s = str(v or "").strip()
    if not s:
        return ""
    p = urllib.parse.urlsplit(s)
    try:
        p.port  # noqa: B018  a wrong port raises
    except ValueError:
        raise BadInput(tr(FNT_MSG["blocked"])) from None
    if len(s) > SERVER_MAX or p.scheme != "https" or not p.hostname or p.username or p.password or p.fragment or re.search(r"\s", s):
        raise BadInput(tr(FNT_MSG["blocked"]))
    return s


def _login_clean(v):
    s = str(v or "").strip() if isinstance(v, (str, int)) and not isinstance(v, bool) else None
    if not s or len(s) > LOGIN_MAX or re.search(r"[\x00-\x1f]", s):
        raise BadInput(tr("Invalid value: {0}", tr("Sign-in name")))
    return s


def _secret(v, n, what):
    """A PIN / TAN: a string, never echoed in the message."""
    if not isinstance(v, str) or not v or len(v) > n or re.search(r"[\x00-\x1f]", v):
        raise BadInput(tr("Invalid value: {0}", what))
    return v


def _body():
    """The JSON object of a request (anything else: 400, never a 500)."""
    b = body()
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid data"))
    return b


def _day(v, what):
    if v in (None, ""):
        return None
    if not isinstance(v, str) or not bnk.DATE_RE.match(v):
        raise BadInput(tr("Invalid value: {0}", what))
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", what)) from None


def _remember(c, uid, oid, aid, login, server):
    """The login name (sealed) and the server of the account, when they changed (the PIN never). 2.616.0 (#2473, Fable finding
    4): only once the bank has sent the statements (the sign-in worked), and a new server address goes into the office log
    (the address only, never the login name) with who set it and when (the dialog of the others shows that)."""
    write_lock(c, f"{BKA_TABLE}_{int(oid)}")  # the lock of the bank accounts' own edits (bankacc.py)
    r = c.execute(f"SELECT * FROM {BKA_TABLE} WHERE id=? AND org_id=? AND archived=0", (aid, oid)).fetchone()
    if r is None:
        return
    a = oc_dec_fields(c, oid, BKA_TABLE, r)
    old = a.get("fints_server") or ""
    if (a.get("fints_login") or "") == login and old == server:
        return
    enc, at = oc_enc_fields(c, oid, BKA_TABLE, {"fints_login": login}), iso(now_utc())
    if old != server:
        c.execute(f"UPDATE {BKA_TABLE} SET fints_login=?, fints_server=?, fints_server_by=?, fints_server_at=?, updated_at=? WHERE id=? AND org_id=?",
                  (enc["fints_login"], server, uid, at, at, aid, oid))
        ofx_log(c, oid, "update", target="bank_account", detail={"id": aid, "fints_server": {"before": old, "after": server}})
    else:
        c.execute(f"UPDATE {BKA_TABLE} SET fints_login=?, updated_at=? WHERE id=? AND org_id=?", (enc["fints_login"], at, aid, oid))
    bump(c)
    c.commit()


def _settle(c, d):
    """After a step: the statements are in -> the sign-in worked -> the login name and the server stay with the account."""
    if d.state == "preview" and d.remember:
        login, server = d.remember
        d.remember = None
        _remember(c, d.uid, d.oid, d.acct["id"], login, server)


# ---------------------------------------------------------------- routes
@app.get("/api/office/bank/fints")
def fnt_status():
    """{on, code (why off), accounts: [{id, label, iban_tail, blz, login, server, ok (a German IBAN)}], since}. Also when off
    (the client shows the button switched off with the reason)."""
    c, uid, oid = _ctx()
    off = fnt_off()
    if bka_seed(c, oid):  # the company's account, as the bank accounts' own list makes it
        c.commit()
    rows = c.execute(f"SELECT * FROM {BKA_TABLE} WHERE org_id=? AND archived=0 ORDER BY is_default DESC, sort, id", (oid,)).fetchall()
    return jsonify(on=off is None, code=off, message=tr(FNT_MSG[off]) if off else "",
                   accounts=[_acct_out(c, uid, oid, oc_dec_fields(c, oid, BKA_TABLE, r)) for r in rows], since=_since(c, oid).isoformat(),
                   ttl=FNT_TTL)


@app.post("/api/office/bank/fints/start")
def fnt_start():
    """{account_id, login, pin, server, from?, to?, remember? (default true: login + server stay with the account), mechanism?}
    -> 201 {dialog: {id, state mechanism | decoupled | tan | preview, ...}}. The PIN lives in the dialog's memory only."""
    c, uid, oid = _ctx()
    _need_on()
    b = _body()
    a = _acct(c, oid, b.get("account_id"))
    blz = _blz(a["iban"] or "")
    if not blz:
        raise BadInput(tr("The bank fetch needs a German IBAN at the bank account"))
    login = _login_clean(b.get("login"))
    pin = _secret(b.get("pin"), _PIN_MAX, "PIN")
    server = fnt_server_clean(b.get("server") if b.get("server") is not None else a.get("fints_server"))
    if not server:
        raise BadInput(tr("Please enter the address of the bank's FinTS server"))
    today = local_now().date()
    frm, to = _day(b.get("from"), "from") or _since(c, oid), _day(b.get("to"), "to") or today
    to = min(to, today)
    if frm > to or (to - frm).days > FNT_DAYS_MAX:
        raise BadInput(tr("The period may be at most {0} days and must not end before it starts", FNT_DAYS_MAX))
    with _LOCK:
        _sweep()
        if len(_window(_FAILS, (oid, a["id"]), FNT_FAIL_WINDOW)) >= FNT_FAIL_MAX:
            _fail("wait", 429)
        starts = _window(_STARTS, uid, FNT_STARTS_WINDOW)
        if len(starts) >= FNT_STARTS_MAX:
            _fail("too_many", 429)
        old = [d for d in _DLG.values() if d.uid == uid and d.oid == oid and d.acct["id"] == a["id"]]
        for d in old:  # one open dialog per person and account: a new start ends the old one
            _DLG.pop(d.id, None)
            _close(d)
        if len(_DLG) >= FNT_DIALOGS_MAX:
            _fail("busy", 503)
        starts.append(_now())
        d = _Dialog(uid, oid, a, None, frm, to)
        _DLG[d.id] = d
        _arm()
    if b.get("remember", True) is not False:
        d.remember = (login, server)  # stored only once the bank has sent the statements (_settle)
    try:
        d.conn = _bank(blz, login, pin, server)
    except FintsError as x:
        _drop(d)
        _fail(x.code, 502)
    del pin
    want = b.get("mechanism")

    def first():
        ms = d.conn.mechanisms()
        d.mechanisms = ms
        if len(ms) > 1 and not (isinstance(want, str) and any(m["id"] == want for m in ms)):
            d.state = "mechanism"
            return
        if ms:
            d.conn.set_mechanism(want if isinstance(want, str) and any(m["id"] == want for m in ms) else ms[0]["id"])
        _apply(d, d.conn.run(a["iban"], frm, to))
    _step(d, first)
    _settle(c, d)
    return jsonify(_out(c, d)), 201


@app.post("/api/office/bank/fints/<did>/mechanism")
def fnt_mechanism(did):
    """{id}: the TAN method of a dialog in the state mechanism -> {dialog}."""
    c, uid, oid = _ctx()
    _need_on()
    d = _dialog(did, uid, oid)
    mid = _body().get("id")
    if d.state != "mechanism":
        _fail("state")
    if not isinstance(mid, str) or not any(m["id"] == mid for m in d.mechanisms):
        raise BadInput(tr("Invalid value: {0}", "id"))

    def go():
        d.conn.set_mechanism(mid)
        _apply(d, d.conn.run(d.acct["iban"], d.frm, d.to))
    _step(d, go)
    _settle(c, d)
    return jsonify(_out(c, d))


@app.post("/api/office/bank/fints/<did>/tan")
def fnt_tan(did):
    """{tan}: the TAN of a dialog in the state tan -> {dialog}. A wrong TAN ends the dialog (no second try by itself)."""
    c, uid, oid = _ctx()
    _need_on()
    d = _dialog(did, uid, oid)
    tan = _secret(_body().get("tan"), _TAN_MAX, "TAN")
    if d.state != "tan":
        _fail("state")
    _step(d, lambda: _apply(d, d.conn.tan(tan)))
    _settle(c, d)
    return jsonify(_out(c, d))


@app.post("/api/office/bank/fints/<did>/poll")
def fnt_poll(did):
    """The state of an approval in the banking app (decoupled) -> {dialog}: still decoupled, or preview once approved. Asks the
    bank at most every FNT_POLL_MIN seconds (in between the answer is the state as it is)."""
    c, uid, oid = _ctx()
    _need_on()
    d = _dialog(did, uid, oid)
    if d.state == "decoupled" and (fnt_fake() or _now() - d.polled >= FNT_POLL_MIN):
        d.polled = _now()
        _step(d, lambda: _apply(d, d.conn.tan(None)))
        _settle(c, d)
    return jsonify(_out(c, d))


@app.post("/api/office/bank/fints/<did>/import")
def fnt_import(did):
    """The statements of a dialog in the state preview into the bookings, through the file import (duplicates, rules, the
    take-back) -> 201 {import, count, dup_count, ...}; the dialog ends."""
    c, uid, oid = _ctx()
    _need_on()
    d = _dialog(did, uid, oid)
    if d.state != "preview":
        _fail("state")
    if not d.lock.acquire(blocking=False):
        _fail("busy", 409)
    try:
        if not d.statements:
            raise BadInput(tr("Nothing to import"))
        res = bnk.bnk_import_of(c, uid, oid, {}, _files(d))
    finally:
        d.lock.release()
    _drop(d)
    return jsonify(res), 201


@app.delete("/api/office/bank/fints/<did>")
def fnt_cancel(did):
    """Ends a dialog (the bank's dialog too); the PIN is forgotten. An unknown / expired one: ok as well."""
    c, uid, oid = _ctx()
    with _LOCK:
        d = _DLG.get(str(did))
        if d is None or d.uid != uid or d.oid != oid:
            return jsonify(ok=True)
        _DLG.pop(d.id, None)
    _close(d)
    return jsonify(ok=True)


if _test():  # test containers only (tests/start.sh)
    @app.post("/api/test/fints/age")
    def _fnt_test_age():
        """{seconds}: the dialogs' clock runs on by that much (expiry without waiting)."""
        b = request.get_json(silent=True) or {}
        _SHIFT[0] += float(b.get("seconds") or 0)
        return jsonify(ok=True, open=len(_DLG))

    @app.get("/api/test/fints/open")
    def _fnt_test_open():
        """The open dialogs, without the sweep of a FinTS request (Fable finding 1: the background sweep alone ends them)."""
        with _LOCK:
            tm = _TICK["timer"]
            return jsonify(open=len(_DLG), armed=bool(tm is not None and tm.is_alive()))

    @app.post("/api/test/fints/hold")
    def _fnt_test_hold():
        """Fable re-check: {id, on}: the dialog's step lock is held (on) or let go, as by a running step; then {sweep: true}
        runs the sweep once -> {open: dialogs left}."""
        b = request.get_json(silent=True) or {}
        d = _DLG.get(str(b.get("id") or ""))
        if d is not None and "on" in b:
            if b["on"]:
                d.lock.acquire(blocking=False)
            elif d.lock.locked():
                d.lock.release()
        if b.get("sweep"):
            with _LOCK:
                _sweep()
        return jsonify(open=len(_DLG))

    @app.get("/api/test/fints/lib")
    def _fnt_test_lib():
        """Fable finding 6: the inner parts of the installed python-fints (missing: [] = all there, null = not installed)."""
        return jsonify(missing=fnt_lib_missing(), level=logging.getLogger("fints.client").getEffectiveLevel())

    @app.post("/api/test/fints/conn")
    def _fnt_test_conn():
        """Fable finding 2: the limits of _Conn against a stand-in bank server. {size: bytes per answer, count: answers wanted,
        late: true = the time of the step is up} -> {sent: requests made, code: the FintsError or null}."""
        b = request.get_json(silent=True) or {}
        size, count = int(b.get("size") or 10), int(b.get("count") or 1)

        def http(url, method, data, headers, max_bytes=None, timeout=None, until=None):
            if size > max_bytes:
                raise CalError("too_large")
            return 200, {}, b"QUFB" * (size // 4), url  # base64 of "AAA..."

        class _Msg:
            def render_bytes(self):
                return b"HNHBK:1:3+"
        cn = _Conn("https://fints.example.com/", http=http, msg_cls=lambda segments: segments)
        if b.get("late"):
            cn.begin(until=time.monotonic() - 1)
        sent = 0
        try:
            for _ in range(count):
                cn.send(_Msg())
                sent += 1
        except FintsError as x:
            return jsonify(sent=sent, code=x.code, hops=cn.hops, bytes=cn.bytes)
        return jsonify(sent=sent, code=None, hops=cn.hops, bytes=cn.bytes)
