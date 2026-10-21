"""2.144.3 B (#2054): the GiroCode (EPC QR code, EPC069-12 version 002) on invoices and reminders.

gcq_payload builds the code's text: BCD / 002 / 1 (UTF-8) / SCT / BIC (optional) / name of the payee (max 70) / IBAN /
EUR amount / no purpose / no structured reference / the document number as the unstructured remittance (max 140). Only
for EUR, a valid IBAN of the sender (the office's bank details) and an open amount above 0 -- else None and no code.
gcq_model is called by invoices.inv_render: the setting "girocode" (office settings, default on) decides for drafts; a
finalised document keeps the decision frozen in its sender snapshot (ledger.ofx_finalize notes "girocode"), so a
document finalised before 2.144.3 never gets one when rendered again (GoBD: the archived PDF stays as it was).
gcq_matrix turns the text into the module matrix (segno, error correction M, UTF-8); pdf.py draws it as filled
rectangles (vectors only, no image, no transparency: PDF/A-3 of ZUGFeRD stays valid). The e-invoice XML is unchanged."""
import re
from decimal import Decimal, InvalidOperation

GCQ_NAME_MAX = 70
GCQ_REF_MAX = 140
GCQ_AMOUNT_MAX = Decimal("999999999.99")
GCQ_BIC_RE = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")


def _clean(v, n):
    return re.sub(r"\s+", " ", str(v or "")).strip()[:n]


def gcq_payload(name, iban, bic, amount, ref, currency="EUR"):
    """The EPC QR text or None when no code may be printed (not EUR, no valid IBAN, no name, amount not in 0.01 ..
    999999999.99)."""
    from .ledger import _iban_ok
    if (currency or "").upper() != "EUR":
        return None
    iban = re.sub(r"\s+", "", str(iban or "")).upper()
    if not iban or not _iban_ok(iban):
        return None
    name = _clean(name, GCQ_NAME_MAX)
    if not name:
        return None
    try:
        amt = Decimal(str(amount)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if amt <= 0 or amt > GCQ_AMOUNT_MAX:
        return None
    bic = re.sub(r"\s+", "", str(bic or "")).upper()
    if not GCQ_BIC_RE.match(bic):
        bic = ""
    els = ["BCD", "002", "1", "SCT", bic, name, iban, f"EUR{amt}", "", "", _clean(ref, GCQ_REF_MAX)]
    while els[-1] == "":  # EPC069-12: unused trailing elements are left out (a draft has no number yet)
        els.pop()
    out = "\n".join(els)
    return out if len(out.encode("utf-8")) <= 331 else None  # EPC069-12: at most 331 bytes


def gcq_matrix(payload):
    """[[bool, ...], ...] the dark modules of the QR code of payload (no quiet zone), error correction M."""
    import segno
    qr = segno.make(payload, error="m", boost_error=False, micro=False, encoding="utf-8")
    return [[bool(v) for v in row] for row in qr.matrix]


def gcq_model(r, m, s, snd=None):
    """Sets m["payment"]["girocode"] (the EPC text) when the document gets one: invoice = its gross, reminder = the open
    amounts plus the fee (its total); credit notes never. snd = the decrypted sender snapshot of a finalised document."""
    pay = m.get("payment")
    if not isinstance(pay, dict) or r["kind"] not in ("invoice", "reminder"):
        return m
    from .ledger import ofx_locked
    if ofx_locked(r):
        on = bool(isinstance(snd, dict) and snd.get("girocode"))
    else:
        on = bool(int((s or {}).get("girocode", 1) or 0))
    if not on:
        return m
    tot = m.get("totals") or {}
    code = gcq_payload((m.get("sender_fields") or {}).get("name") or "", pay.get("iban"), pay.get("bic"), tot.get("gross") or 0,
                       r["number"] or "", r["currency"])
    if code:
        pay["girocode"] = code
    return m


GCQ_SIZE = 76.0  # about 2.7 cm: the code itself (EPC: at least 2 x 2 cm read well with banking apps)
GCQ_LABELS = {"de": ("GiroCode", "Mit Banking-App scannen"), "en": ("GiroCode", "Scan with banking app")}


def gcq_block_h():
    """The height pdf.py reserves next to the payment text: the code plus its two label lines."""
    return GCQ_SIZE + 22


def gcq_draw(p, x, y, payload, lang, color="#000000", color2="#4b515c"):
    """Draws the code of payload with its top left corner at (x, y) on page p (pdf.py page: y from the top), the label
    below. One filled rectangle per horizontal run of dark modules (vectors only)."""
    rows = gcq_matrix(payload)
    n = len(rows) or 1
    mod = GCQ_SIZE / n
    for i, row in enumerate(rows):
        j = 0
        while j < n:
            if not row[j]:
                j += 1
                continue
            k = j
            while k < n and row[k]:
                k += 1
            p.rect(x + j * mod, y + i * mod, (k - j) * mod + 0.02, mod + 0.02, color)  # +0.02: no hairline gaps between rows
            j = k
    t1, t2 = GCQ_LABELS.get(lang) or GCQ_LABELS["de"]
    p.text(x, y + GCQ_SIZE + 4, t1, 7, True, color2, align="c", width=GCQ_SIZE)
    p.text(x, y + GCQ_SIZE + 12.5, t2, 6.2, False, color2, align="c", width=GCQ_SIZE)
