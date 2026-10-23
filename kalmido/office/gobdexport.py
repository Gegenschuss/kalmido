"""2.148.0 A (#2471): the export for a tax auditor (GoBD "Datenträgerüberlassung", Z3 access): one ZIP with the booking data
of a period as CSV tables plus index.xml in the description standard of the GDPdU (read by the auditors' software;
2.188.0 A (#2498): the official DTD gdpdu-01-03-2019.dtd, version 1.6, from gdpdudtd.py lies next to index.xml).
Tables: bookings (the lines of the DATEV batch, input side included), invoices / credit notes,
their positions, payments, receipts, cash book, clients, opening balances, the office log and (2.187.0 B, #2476) the log of
the office rights.

CSV: UTF-8, ';', CRLF, text in double quotes, decimal comma, dates DD.MM.YYYY, no header line (the columns are in
index.xml). Only finalised documents; drafts are no bookings. Admins (and the accounting role) of the office area."""
import csv
import io
import json
import zipfile
from datetime import date
from xml.sax.saxutils import escape

from flask import Response, request

from ..core.config import app
from ..core.i18n import tr
from ..core.db import db
from ..core.orgcrypt import oc_dec_fields
from ..personal.timetrack import BadInput
from .calc import dec, money
from .model import office_gate, office_org, office_settings, pb_cl_sql
from .ledger import ofx_company, ofx_log
from .gdpdudtd import GX_DTD, GX_DTD_NAME
from .rights import ofr_log_rows

GX_MAX_DAYS = 11 * 366  # one call covers at most eleven years (ten years of keeping + the current one)
GX_RIGHTS_MAX = 100000  # 2.187.0 B (#2476): the rows of the rights log read for the export (changes of rights are rare)

A, N, D = "a", "n", "d"  # column types: alphanumeric, numeric (2 places), date


def _d(s):
    s = (s or "")[:10]
    return f"{s[8:10]}.{s[5:7]}.{s[:4]}" if len(s) == 10 and s[4] == "-" else ""


def _n(v):
    if v in (None, ""):
        return ""
    return f"{money(dec(v, '0')):.2f}".replace(".", ",")


def _j(v):
    try:
        x = json.loads(v or "{}")
        return x if isinstance(x, dict) else {}
    except (TypeError, ValueError):
        return {}


class _Tbl:
    def __init__(self, url, name, desc, cols, key=1):
        self.url, self.name, self.desc, self.cols, self.key = url, name, desc, cols, key
        self.buf = io.StringIO()
        self.w = csv.writer(self.buf, delimiter=";", quotechar='"', quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
        self.n = 0

    def add(self, *vals):
        out = []
        for (cn, ct), v in zip(self.cols, vals):
            if ct == N:
                out.append(_n(v))
            elif ct == D:
                out.append(_d(v))
            else:
                v = str(v if v is not None else "").replace("\r", " ").replace("\n", " ").replace("\t", " ")
                out.append("'" + v if v[:1] in ("=", "+", "-", "@") else v)  # no formula when a spreadsheet opens it
        self.w.writerow(out)
        self.n += 1

    def xml(self, frm, to):
        cols = []
        for i, (cn, ct) in enumerate(self.cols):
            tag = "VariablePrimaryKey" if i < self.key else "VariableColumn"
            typ = ("<Numeric><Accuracy>2</Accuracy></Numeric>" if ct == N else
                   "<Date><Format>DD.MM.YYYY</Format></Date>" if ct == D else "<AlphaNumeric/>")
            cols.append(f"        <{tag}><Name>{escape(cn)}</Name>{typ}</{tag}>")
        return ("    <Table>\n"
                f"      <URL>{escape(self.url)}</URL>\n      <Name>{escape(self.name)}</Name>\n"
                f"      <Description>{escape(self.desc)}</Description>\n"
                f"      <Validity><Range><From>{_d(frm)}</From><To>{_d(to)}</To></Range><Format>DD.MM.YYYY</Format></Validity>\n"
                "      <UTF8/>\n      <DecimalSymbol>,</DecimalSymbol>\n      <DigitGroupingSymbol>.</DigitGroupingSymbol>\n"
                "      <VariableLength>\n        <ColumnDelimiter>;</ColumnDelimiter>\n        <RecordDelimiter>&#13;&#10;</RecordDelimiter>\n"
                "        <TextEncapsulator>\"</TextEncapsulator>\n" + "\n".join(cols) + "\n      </VariableLength>\n    </Table>\n")


def gx_tables(c, oid, frm, to):
    """The tables of the export for [frm, to] (ISO days)."""
    from .datev import dx_rows
    from .books import bk_receipts
    s = office_settings(c, oid)
    out = []

    t = _Tbl("bookings.csv", "Buchungen", "Buchungszeilen wie im DATEV-Buchungsstapel (Ausgang, Zahlungen, Eingang)",
             [("Zeile", A), ("Belegdatum", D), ("Belegnummer", A), ("Buchungstext", A), ("Umsatz", N), ("Soll/Haben", A),
              ("Konto", A), ("Gegenkonto", A), ("BU-Schluessel", A), ("Waehrung", A)])
    hints = []
    for i, r in enumerate(dx_rows(c, oid, frm, to, s=s, inside=True, hints_out=hints), 1):
        t.add(i, r.get("_date") or "", r.get("Belegfeld 1", ""), r.get("Buchungstext", ""),
              (r.get("Umsatz (ohne Soll/Haben-Kz)") or "").replace(",", "."), r.get("Soll/Haben-Kennzeichen", ""), r.get("Konto", ""),
              r.get("Gegenkonto (ohne BU-Schlüssel)", ""), r.get("BU-Schlüssel", ""), r.get("WKZ Umsatz", ""))
    out.append(t)

    docs = c.execute("SELECT d.*, cl.name AS cl_name, cl.customer_no AS cl_no FROM office_docs d LEFT JOIN clients cl ON cl.id=d.client_id "
                     "WHERE d.org_id=? AND d.kind IN ('invoice','credit') AND d.locked_at IS NOT NULL AND d.date>=? AND d.date<=? "
                     "ORDER BY d.date, d.number", (oid, frm, to)).fetchall()
    t = _Tbl("invoices.csv", "Rechnungen", "Festgeschriebene Rechnungen und Gutschriften",
             [("ID", A), ("Art", A), ("Nummer", A), ("Datum", D), ("Kunde", A), ("Kundennummer", A), ("Netto", N), ("Steuer", N),
              ("Brutto", N), ("Waehrung", A), ("Status", A), ("Festgeschrieben", D), ("Storno_von", A)])
    for r in docs:
        tt = _j(r["totals"])
        t.add(r["id"], r["kind"], r["number"], r["date"], r["cl_name"] or "", r["cl_no"] or "", tt.get("net"), tt.get("tax_total"),
              tt.get("gross"), r["currency"], r["status"], r["locked_at"], r["cancels_id"] or "")
    out.append(t)

    t = _Tbl("positions.csv", "Positionen", "Positionen der Rechnungen und Gutschriften",
             [("ID", A), ("Rechnung_ID", A), ("Bezeichnung", A), ("Menge", N), ("Einheit", A), ("Einzelpreis", N), ("Steuersatz", N),
              ("Netto", N), ("Steuer", N)])
    ids = [r["id"] for r in docs]
    for k in range(0, len(ids), 500):
        part = ids[k:k + 500]
        q = ",".join("?" * len(part))
        for it in c.execute(f"SELECT * FROM office_doc_items WHERE doc_id IN ({q}) ORDER BY doc_id, sort, id", part).fetchall():
            it = oc_dec_fields(c, oid, "office_doc_items", it)
            t.add(it["id"], it["doc_id"], it["title"], it["qty"], it["unit"], it["rate"], it.get("tax_pct"), it.get("net"), it.get("tax_amount"))
    out.append(t)

    t = _Tbl("payments.csv", "Zahlungen", "Zahlungseingaenge auf Rechnungen",
             [("ID", A), ("Rechnung_ID", A), ("Rechnungsnummer", A), ("Datum", D), ("Betrag", N), ("Zahlart", A)])
    for r in c.execute("SELECT p.*, d.number FROM office_payments p JOIN office_docs d ON d.id=p.doc_id WHERE p.org_id=? AND p.date>=? "
                       "AND p.date<=? ORDER BY p.date, p.id", (oid, frm, to)).fetchall():
        t.add(r["id"], r["doc_id"], r["number"], r["date"], r["amount"], r["method"])
    out.append(t)

    t = _Tbl("receipts.csv", "Belege", "Eingangsbelege (Belegfach) nach Belegdatum",
             [("Beleg_ID", A), ("Belegdatum", D), ("Bezahlt_am", D), ("Brutto", N), ("USt_Satz", A), ("Netto", N), ("USt", N),
              ("Kategorie", A), ("Datei", A)])
    for r in bk_receipts(c, oid, frm, to, uid=0, by="doc"):
        t.add(r["node_id"], r["doc_date"] or r["date"], r["paid_at"] or "", r["amount"], r["vat_pct"] or "", r["net"], r["vat"],
              r["category"], r["title"])
    out.append(t)

    t = _Tbl("cashbook.csv", "Kassenbuch", "Kassenbuchungen aller Kassen",
             [("ID", A), ("Kasse", A), ("Nr", A), ("Datum", D), ("Richtung", A), ("Betrag", N), ("USt_Satz", A), ("Text", A),
              ("Kategorie", A), ("Storno_von", A)])
    for r in c.execute("SELECT e.*, b.name AS book FROM office_cash_entries e JOIN office_cashbooks b ON b.id=e.book_id WHERE e.org_id=? "
                       "AND e.day>=? AND e.day<=? ORDER BY e.book_id, e.no", (oid, frm, to)).fetchall():
        e = oc_dec_fields(c, oid, "office_cash_entries", r)
        t.add(e["id"], e["book"], e["no"], e["day"], e["dir"], e["amount"], e["vat_pct"] or "", e["text"], e["category"], e["storno_of"] or "")
    out.append(t)

    t = _Tbl("clients.csv", "Kunden", "Kunden des Bueros", [("ID", A), ("Kundennummer", A), ("Name", A), ("Anschrift", A), ("USt_IdNr", A)])
    for r in c.execute(f"SELECT * FROM clients WHERE {pb_cl_sql(c, oid)} ORDER BY id").fetchall():  # a personal office: its owner's
        r = oc_dec_fields(c, oid, "clients", r)
        t.add(r["id"], r.get("customer_no") or "", r["name"], r.get("address") or "", r.get("vat_id") or "")
    out.append(t)

    t = _Tbl("opening_balances.csv", "Eroeffnungsbestaende", "Eroeffnungsbestaende aus dem DATEV-Import",
             [("ID", A), ("Jahr", A), ("Konto", A), ("Bezeichnung", A), ("Betrag", N), ("Soll/Haben", A)])
    for r in c.execute("SELECT * FROM office_opening_balances WHERE org_id=? AND year>=? AND year<=? ORDER BY year, account, id",
                       (oid, int(frm[:4]), int(to[:4]))).fetchall():
        t.add(r["id"], r["year"], r["account"], r["label"], r["amount"], r["side"])
    out.append(t)

    t = _Tbl("log.csv", "Protokoll", "Aenderungsprotokoll des Bueros (GoBD), ohne Inhalte der Aenderungen",
             [("ID", A), ("Zeitpunkt", A), ("Person", A), ("Aktion", A), ("Ziel", A), ("Dokument_ID", A)])
    for r in c.execute("SELECT l.id, l.at, l.action, l.target, l.doc_id, u.display_name, u.username FROM office_doc_log l "
                       "LEFT JOIN users u ON u.id=l.user_id WHERE l.org_id=? AND l.at>=? AND l.at<? ORDER BY l.id",
                       (oid, frm, _next_day(to))).fetchall():
        t.add(r["id"], r["at"], r["display_name"] or r["username"] or "", r["action"], r["target"], r["doc_id"] or "")
    out.append(t)

    # 2.187.0 B (#2476): every change of the office rights (groups, memberships) with the state before and after
    t = _Tbl("rights_log.csv", "Rechteprotokoll", "Aenderungen der Buero-Zugriffsrechte (Gruppen und Zuordnungen), vorher und nachher",
             [("ID", A), ("Zeitpunkt", A), ("Geaendert_von", A), ("Betroffene_Person", A), ("Gruppe", A), ("Aktion", A), ("Vorher", A),
              ("Nachher", A)])
    hi = _next_day(to)
    for r in reversed(ofr_log_rows(c, oid, limit=GX_RIGHTS_MAX)):
        if frm <= (r["at"] or "") < hi:
            t.add(r["id"], r["at"], r["by_name"], r["user_name"], r["group"], r["action"],
                  json.dumps(r["before"], ensure_ascii=False, sort_keys=True) if r["before"] is not None else "",
                  json.dumps(r["after"], ensure_ascii=False, sort_keys=True) if r["after"] is not None else "")
    out.append(t)
    return out


def _next_day(d):
    from datetime import timedelta
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def gx_zip(c, oid, frm, to):
    tables = gx_tables(c, oid, frm, to)
    co = ofx_company(c, oid) or {}
    name = (co.get("name") or "").strip() or "Kalmido"
    loc = " ".join(x for x in ((co.get("zip") or "").strip(), (co.get("city") or "").strip()) if x)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE DataSet SYSTEM "' + GX_DTD_NAME + '">\n<DataSet>\n  <Version>1.0</Version>\n'
           f"  <DataSupplier><Name>{escape(name)}</Name><Location>{escape(loc)}</Location>"
           f"<Comment>{escape(f'Kalmido, Zeitraum {_d(frm)} - {_d(to)}')}</Comment></DataSupplier>\n"
           f"  <Media>\n    <Name>{escape(f'Kalmido {frm} {to}')}</Name>\n" + "".join(t.xml(frm, to) for t in tables) + "  </Media>\n</DataSet>\n")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("index.xml", xml)
        z.writestr(GX_DTD_NAME, GX_DTD.encode("utf-8"))  # 2.188.0 A (#2498)
        for t in tables:
            z.writestr(t.url, t.buf.getvalue().encode("utf-8"))
    return buf.getvalue(), {t.url: t.n for t in tables}


def _span():
    y = date.today().year - 1
    a = (request.args.get("from") or f"{y}-01-01").strip()
    b = (request.args.get("to") or f"{y}-12-31").strip()
    try:
        da, db_ = date.fromisoformat(a), date.fromisoformat(b)
    except ValueError:
        raise BadInput(tr("Invalid value: {0}", "from / to"))
    if db_ < da:
        raise BadInput(tr("The end lies before the start"))
    if (db_ - da).days > GX_MAX_DAYS:
        raise BadInput(tr("The period is too long (at most {0} years)", 11))
    return da.isoformat(), db_.isoformat()


@app.get("/api/office/gobd/export")
def gx_export_get():
    """Admin: ?from=YYYY-MM-DD&to=YYYY-MM-DD (default: the previous calendar year) -> the ZIP for the tax auditor;
    ?check=1 -> {from, to, counts} only."""
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=True)
    frm, to = _span()
    if request.args.get("check") == "1":
        return {"from": frm, "to": to, "counts": {t.url: t.n for t in gx_tables(c, oid, frm, to)}}
    data, counts = gx_zip(c, oid, frm, to)
    ofx_log(c, oid, "export", target="gobd", detail={"from": frm, "to": to, "counts": counts})
    c.commit()
    fname = f"GoBD_Export_{frm.replace('-', '')}_{to.replace('-', '')}.zip"
    return Response(data, mimetype="application/zip", headers={"Content-Disposition": f'attachment; filename="{fname}"'})
