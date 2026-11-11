"""2.148.0 C (#2472): the procedure documentation (Verfahrensdokumentation, GoBD) of an office area, prefilled.

The outline follows GoBD Rz. 151 ff. and the AWV sample: 1 general description, 2 user documentation, 3 technical system
documentation, 4 operating documentation, 5 internal control system. Each section has fields; a field may carry a
prefilled text ("auto", made from the office settings and what the office holds: company, members with their role, number
schemes, cash books, bank imports, locked months, DATEV, backups, encryption) and the area's own text ("own"). The fixed
sentences about Kalmido only say what the code does; what Kalmido cannot know (legal form, server location, where backups
are kept, restore tests) is a gap "[ ... fill in ]" the view marks. Names and roles of members only, never mail addresses.

Stored in the core's obj_versions (2.977.0, #5282, stage Q7b: kind "procdoc" on the area's head row in office_procdocs; was a
row of office_procdocs per version): every save is a new version (number per area, 1, 2, ...) with the own texts AND the prefilled
texts of that moment (data, JSON, encrypted at rest like the other office free texts), so an old version reads as it was.
The current view = the prefilled texts of now + the own texts of the latest version. Markdown and PDF of the current state
or of a version carry the version, its date and the company.

The template texts are document content in German and English; other app languages get English. 2.449.0 (#3768): GoBD is
German law, so only an office on the German pack is offered it (pd_offered); an area that already has versions keeps them.
Reading: everybody with office access (members, read-only, accounting); saving: the area's admin (office_org admin=True:
accounting / read-only answer 403 on writes). A person without an organisation is the admin of the personal office.
Agents never reach it (office_gate)."""
import json
import re

from flask import Response, jsonify, request

from ..core.config import APP_VERSION, app
from ..core.db import db, gsetting, iso, now_utc
from ..core.access import Denied
from ..core.i18n import N_, lang, tr
from ..core.orgcrypt import OrgCryptError, oc_dec_fields, oc_dec_k, oc_enc_fields, oc_enc_k, oc_is_enc, oc_key
from ..core.pg import insert_id, table_columns, table_exists, write_lock
from ..core.objversions import (OBJV_CTX, obj_version_add, obj_version_free_no, obj_version_last, obj_version_no,  # 2.977.0 (#5282)
                                obj_version_old_ts)
from ..core import objhooks  # 2.977.0 (#5282): the start hook pd_retire
from ..notify.alerts import aa_now  # 2.977.0 (#5282): the admins' alert of pd_retire
from ..core.kernretire import KERN_RETIRE_LOCK, kern_retire_floor, kern_retire_rows  # 2.977.0 (#5282)
from ..personal.timetrack import BadInput
from .model import office_gate, office_org, office_role, office_settings, ofx_name1, pb_owner
from .pdf import pdf_paper_ns  # 2.357.0 A (#3156): the office's paper size
from ..core.pg import system_ctx  # 2.369.5 (#2517): pulled up from functions; 2.977.0 (#5282): + pd_retire
from .ledger import ofx_company, ofx_log  # 2.369.5 (#2517): pulled up from functions
from .packs import office_pack  # 2.369.5 (#2517): pulled up from functions
from .periodlock import pl_label, pl_through  # 2.369.5 (#2517): pulled up from functions

PD_TEXT_MAX = 20000  # characters of one own text
PD_VERSIONS_MAX = 500
PD_KIND = "procdoc"  # 2.977.0 (#5282, stage Q7b): the kind of the versions in obj_versions (ref_id = the area's head row)
PD_GAP = {"de": "[ ... ausfüllen ]", "en": "[ ... to fill in ]"}
PD_NO_VERSION = N_("This version does not exist")
# 2.977.0 (#5282, Fable review F3 / F4): an area whose old versions wait for the move (pd_retire: its key is missing now)
PD_WAITING = N_("The procedure documentation of this office still waits for its move to the new storage (its key is missing). Try again after the next start.")

# the outline: section key -> (number, title de, title en, fields); field = (key, title de, title en, need own text)
PD_OUTLINE = (
    ("general", "1", "Allgemeine Beschreibung", "General description", (
        ("company", "Unternehmen", "Company", True),
        ("organisation", "Organisation und Verantwortliche", "Organisation and responsibilities", True),
        ("software", "Eingesetzte Software", "Software in use", True))),
    ("user", "2", "Anwenderdokumentation", "User documentation", (
        ("receipts", "Belegfluss der Eingangsbelege", "Flow of incoming receipts", False),
        ("invoices", "Rechnungsausgang", "Outgoing invoices", False),
        ("numbers", "Nummernkreise", "Number ranges", False),
        ("cashbook", "Kassenbuch", "Cash book", False),
        ("bank", "Bankabgleich", "Bank reconciliation", False),
        ("periods", "Festschreiben der Zeiträume", "Locking of periods", False),
        ("advisor", "Übergabe an den Steuerberater", "Hand-over to the tax advisor", False))),
    ("tech", "3", "Technische Systemdokumentation", "Technical system documentation", (
        ("system", "Server und Datenbank", "Server and database", True),
        ("encryption", "Verschlüsselung", "Encryption", False),
        ("log", "Protokollierung", "Logging", False))),
    ("ops", "4", "Betriebsdokumentation", "Operating documentation", (
        ("backup", "Datensicherung", "Backup", True),
        ("restore", "Wiederherstellung", "Restore", True),
        ("retention", "Aufbewahrung", "Retention", False),
        ("access", "Zugriff und Anmeldung", "Access and sign-in", False))),
    ("ics", "5", "Internes Kontrollsystem", "Internal control system", (
        ("roles", "Rollen und Rechte", "Roles and rights", False),
        ("controls", "Kontrollen", "Controls", False))),
)
PD_FIELDS = tuple(f[0] for s in PD_OUTLINE for f in s[4])
PD_ROLE_NAMES = {"admin": ("Admin", "Admin"), "member": ("Mitglied", "Member"), "readonly": ("Nur lesen", "Read-only"),
                 "accounting": ("Buchhaltung", "Accounting"), "guest": ("Gast", "Guest")}
PD_EINV = {"zugferd": "ZUGFeRD", "xrechnung": "XRechnung", "none": "-", "": "-"}


def pd_offered(c, oid, s=None):
    """2.449.0 (#3768): the German pack, or an area that saved versions before it changed its pack."""
    s = s if s is not None else office_settings(c, oid)
    return (s.get("pack") or "DE").upper() == "DE" or bool(c.execute("SELECT 1 FROM obj_versions WHERE kind=? AND org_id=? LIMIT 1", (PD_KIND, oid)).fetchone())  # 2.977.0 (#5282)


def _ctx(admin=False):
    c = db()
    uid = office_gate(c)
    oid = office_org(c, uid, admin=admin)
    if not pd_offered(c, oid):
        raise Denied(404)
    return c, uid, oid


def _lg(v=None):
    v = (v or lang() or "en").lower()
    return "de" if v.startswith("de") else "en"


def _yn(L, v):
    return ("ja" if v else "nein") if L == "de" else ("yes" if v else "no")


def _members(c, oid):
    """[(name, role)] of the office area: a personal office = its owner (admin); names and roles only."""
    owner = pb_owner(c, oid)
    with system_ctx(c):  # membership structure (names and roles of the area's people, nothing else)
        if owner is not None:
            rows = c.execute("SELECT display_name, username, 'admin' AS role FROM users WHERE id=?", (owner,)).fetchall()
        else:
            rows = c.execute("SELECT u.display_name, u.username, m.role FROM org_members m JOIN users u ON u.id=m.user_id "
                             "WHERE m.org_id=? AND COALESCE(m.role, '')<>'guest' ORDER BY lower(COALESCE(NULLIF(u.display_name, ''), u.username))", (oid,)).fetchall()
    return [((r["display_name"] or r["username"] or "").strip(), r["role"] or "member") for r in rows]


def _count(c, sql, args):
    r = c.execute(sql, args).fetchone()
    return int(r[0] or 0) if r else 0


def pd_auto(c, oid, L):
    """{field: the prefilled text} in language L ("de" | "en"), from the settings and what the office holds."""
    gap = PD_GAP[L]
    t = (lambda de, en: de if L == "de" else en)  # noqa: E731
    s = office_settings(c, oid)
    co = ofx_company(c, oid)
    pack = office_pack(s.get("pack") or "") or {}
    personal = pb_owner(c, oid) is not None
    out = {}

    # 1 general
    name = ofx_name1(co.get("name") or (s.get("company") or {}).get("name")) or gap
    addr = ", ".join(x for x in (co.get("street"), " ".join(y for y in (co.get("zip"), co.get("city")) if y), co.get("country")) if x) or gap
    lines = [t("Firma: ", "Company: ") + name, t("Anschrift: ", "Address: ") + addr,
             t("Länderpaket: ", "Country pack: ") + ((pack.get("name") if L == "de" else pack.get("name_en")) or s.get("pack") or gap),
             t("Rechtsform und Gegenstand des Unternehmens: ", "Legal form and business purpose: ") + gap]
    if co.get("register_court") or co.get("register_no"):
        lines.append(t("Handelsregister: ", "Commercial register: ") + " ".join(x for x in (co.get("register_court"), co.get("register_no")) if x))
    if co.get("managing_directors"):
        lines.append(t("Geschäftsführung / Inhaber: ", "Management / owner: ") + co["managing_directors"].replace("\n", ", "))
    lines.append(t("Steuernummer hinterlegt: ", "Tax number on file: ") + _yn(L, co.get("tax_number")) + "; "
                 + t("USt-IdNr. hinterlegt: ", "VAT id on file: ") + _yn(L, co.get("vat_id")))
    lines.append(t("Kleinunternehmerregelung: ", "Small business scheme: ") + _yn(L, s.get("small_business")) + "; "
                 + t("Umsatzsteuer nach ", "VAT on ") + (t("vereinnahmten Entgelten (Ist)", "payment received (cash basis)") if s.get("vat_basis") != "soll"
                                                       else t("vereinbarten Entgelten (Soll)", "invoicing (accrual basis)")))
    out["company"] = "\n".join(lines)
    mem = _members(c, oid)
    rn = lambda r: PD_ROLE_NAMES.get(r, (r, r))[0 if L == "de" else 1]  # noqa: E731
    head = (t("Persönliches Büro einer Person ohne Organisation; sie ist zugleich Admin.",
              "Personal office of a person without an organisation; the person is its admin.") if personal
            else t("Büro der Organisation mit {0} Mitgliedern:", "Office of the organisation with {0} members:").format(len(mem)))
    out["organisation"] = "\n".join([head] + [f"- {n or '-'} ({rn(r)})" for n, r in mem]
                                    + [t("Verantwortlich für die Buchführung, Steuerberatung: ", "Responsible for bookkeeping, tax advisor: ") + gap])
    out["software"] = "\n".join([
        t(f"Kalmido {APP_VERSION} (selbst betriebener Aufgabenmanager mit Büro-Bereich: Angebote, Rechnungen, Belege, Bankabgleich, "
          "Kassenbuch, Auswertungen). Bedienung im Browser oder als installierte Web-App.",
          f"Kalmido {APP_VERSION} (self-hosted task manager with an office area: quotations, invoices, receipts, bank reconciliation, "
          "cash book, reports). Used in the browser or as an installed web app."),
        t("Weitere Software (z. B. Online-Banking, Lohn, Steuerberater-Programm): ", "Other software (e.g. online banking, payroll, the tax advisor's program): ") + gap])

    # 2 user documentation
    rx = [t("1. Eingang: Hochladen in der App, Teilen vom Handy, Mail an die Dokumenten-Adresse oder Ablegen im Eingangsordner. "
            "Die Datei wird unverändert im Bereich Dokumente gespeichert.",
            "1. Intake: upload in the app, share from the phone, mail to the documents address or put into the inbox folder. "
            "The file is stored unchanged in the documents area."),
          t("2. Erkennung: Texterkennung liest Datum und Betrag; Kategorie und Projekt werden vorgeschlagen, eine Person bestätigt sie.",
            "2. Recognition: text recognition reads date and amount; category and project are suggested, a person confirms them."),
          t("3. Abgleich: Der Bankabgleich ordnet Kontobewegungen den Belegen und Rechnungen zu und setzt den Zahltag; "
            "Barzahlungen gehen ins Kassenbuch.",
            "3. Matching: the bank reconciliation matches bank bookings with receipts and invoices and sets the payment day; "
            "cash payments go into the cash book."),
          t("4. Übergabe: Buchungsstapel im DATEV-Format oder CSV an den Steuerberater (siehe Abschnitt Übergabe).",
            "4. Hand-over: booking batch in DATEV format or CSV to the tax advisor (see the section hand-over).")]
    if s.get("datev_email"):
        rx.append(t("Eine Adresse des DATEV-Belegpostfachs ist hinterlegt; Rechnungen gehen dorthin ", "A DATEV document inbox address is on file; invoices go there ")
                  + (t("automatisch.", "automatically.") if s.get("datev_auto") else t("auf Knopfdruck.", "at the press of a button.")))
    out["receipts"] = "\n".join(rx)
    out["invoices"] = "\n".join([
        t("Angebot -> Rechnung (oder Abschlags-/Schlussrechnung) -> Finalisieren -> Versand per Mail oder als PDF.",
          "Quotation -> invoice (or progress / final invoice) -> finalise -> sending by mail or as PDF."),
        t("Beim Finalisieren werden Nummer, Absender, Empfänger, Positionen und Steuersätze eingefroren; danach sind Kopf, Positionen, "
          "Nummer und Löschen gesperrt. Korrekturen nur über eine Rechnungskorrektur bzw. Stornorechnung.",
          "Finalising freezes number, sender, recipient, positions and tax rates; afterwards the head, the positions, the number and "
          "deleting are blocked. Corrections only by a credit note / cancellation invoice."),
        t("E-Rechnungsformat: ", "E-invoice format: ") + PD_EINV.get(s.get("einvoice_format") or "", s.get("einvoice_format") or "-") + "; "
        + t("Zahlungsziel: ", "Payment term: ") + str(s.get("payment_days") or 0) + t(" Tage", " days")])
    num = pack.get("numbering") or {}
    labels = (("offer", "Angebote", "Quotations", "offer_scheme"), ("invoice", "Rechnungen", "Invoices", "invoice_scheme"),
              ("credit", "Rechnungskorrekturen", "Credit notes", "credit_scheme"), ("reminder", "Mahnungen", "Reminders", "reminder_scheme"),
              ("delivery", "Lieferscheine", "Delivery notes", "delivery_scheme"))
    out["numbers"] = "\n".join([f"- {t(de, en)}: {s.get(k) or num.get(kind) or '-'}" for kind, de, en, k in labels] + [
        t("Nummern werden fortlaufend je Nummernkreis vergeben und sind je Büro eindeutig.",
          "Numbers are given in sequence per number range and are unique per office.")])
    books = _count(c, "SELECT COUNT(*) FROM office_cashbooks WHERE org_id=? AND archived=0", (oid,))
    out["cashbook"] = (t(f"{books} Kassenbuch/Kassenbücher in Gebrauch. ", f"{books} cash book(s) in use. ") if books
                       else t("Kein Kassenbuch angelegt. ", "No cash book set up. ")) + t(
        "Einträge werden je Kasse lückenlos nummeriert und nie gelöscht; Rücknahme nur per Gegenbuchung (Storno). "
        "Der Tagesabschluss schreibt alle Einträge bis zu diesem Tag fest; Änderungen davor werden protokolliert.",
        "Entries are numbered without gaps per cash box and never deleted; taking one back only by a counter entry (cancellation). "
        "The day closing freezes every entry up to that day; changes before it are logged.")
    imps = _count(c, "SELECT COUNT(*) FROM office_bank_imports WHERE org_id=? AND undone_at IS NULL", (oid,))
    out["bank"] = t(f"Kontoauszüge werden als CSV oder CAMT eingelesen ({imps} Einlesungen bisher). Jede Bewegung wird einer Rechnung, "
                    "einem Beleg oder einer Kategorie zugeordnet; doppelte Bewegungen werden beim Einlesen erkannt.",
                    f"Bank statements are read as CSV or CAMT ({imps} imports so far). Each booking is matched with an invoice, a receipt "
                    "or a category; duplicate bookings are recognised on import.")
    thr = pl_through(c, oid)
    out["periods"] = "\n".join([
        (t("Festgeschrieben bis einschließlich ", "Locked up to and including ") + pl_label(thr)) if thr
        else t("Noch kein Monat festgeschrieben.", "No month locked yet."),
        t("Festschreiben gilt pro Monat und lässt sich nicht zurücknehmen. In einem festgeschriebenen Monat lehnt Kalmido jede Änderung "
          "mit Datum ab; Korrekturen werden in einem offenen Monat gebucht (z. B. Rechnungskorrektur mit heutigem Datum).",
          "Locking works per month and cannot be taken back. In a locked month Kalmido refuses every change with a date in it; "
          "corrections are booked in an open month (e.g. a credit note dated today).")])
    dx = s.get("datev_extf") or {}
    out["advisor"] = "\n".join([
        t("Export des Buchungsstapels im DATEV-Format (EXTF) und als CSV; Einnahmen-Überschuss-Rechnung als CSV/PDF.",
          "Export of the booking batch in DATEV format (EXTF) and as CSV; income/expense statement as CSV/PDF."),
        t("Beraternummer hinterlegt: ", "Advisor number on file: ") + _yn(L, dx.get("advisor_no")) + "; "
        + t("Mandantennummer hinterlegt: ", "Client number on file: ") + _yn(L, dx.get("client_no")) + "; "
        + t("Kontenrahmen: ", "Chart of accounts: ") + str(dx.get("chart") or "SKR03")])

    # 3 technical
    out["system"] = "\n".join([
        t("Kalmido läuft als Server-Anwendung (Python) mit einer PostgreSQL-Datenbank; Dateien liegen im Dateispeicher des Servers.",
          "Kalmido runs as a server application (Python) with a PostgreSQL database; files are kept in the server's file store."),
        t("Betreiber und Standort des Servers, Zugang (HTTPS): ", "Operator and location of the server, access (HTTPS): ") + gap])
    from ..core.orgcrypt import oc_active
    if oc_active(c):
        # 2.188.0 B (#2498): operator settings shown as yes/no only, no details
        out["encryption"] = t("Verschlüsselung der Büro-Daten im Ruhezustand: ja (laut Betreiber).",
                              "Encryption of office data at rest: yes (according to the operator).")
    else:
        out["encryption"] = t("Verschlüsselung der Büro-Daten im Ruhezustand: nein (laut Betreiber).",
                              "Encryption of office data at rest: no (according to the operator).")
    out["log"] = t("Das Büro-Protokoll hält fest, wer wann welche Dokumente und Stammdaten geändert oder exportiert hat, bei Änderungen mit "
                   "dem Wert davor und danach. Kassenbuch und Fahrtenbuch führen eigene Änderungsprotokolle. Das Protokoll sehen nur Admins. "
                   # 2.531.0 (#4497): the promise of the hash chain (office/chain.py)
                   "Festgeschriebene Rechnungen, Gutschriften, Mahnungen und Lieferscheine sind je Nummernkreis in einer Hash-Kette "
                   "verbunden (SHA-256 über den Hash des vorigen Dokuments und die unveränderlichen Daten des Dokuments); die Prüfung "
                   "„Kette intakt“ im Büro-Protokoll rechnet sie neu und nennt das erste abweichende Dokument.",
                   "The office log records who changed or exported which documents and master data when, for changes with the value "
                   "before and after. Cash book and logbook keep their own change logs. Only admins see the log. "
                   "Finalised invoices, credit notes, reminders and delivery notes are linked per number series in a hash chain "
                   "(SHA-256 over the hash of the document before and the document's unchangeable data); the check \"Chain intact\" "
                   "in the office log recomputes it and names the first document that differs.")

    # 4 operating
    from ..admin.backup import BK_ON_ENV
    if BK_ON_ENV and gsetting(c, "bk_on") == "1":
        out["backup"] = t("Automatische Sicherung: ja (laut Betreiber).", "Automatic backup: yes (according to the operator).")
    else:
        out["backup"] = t("Automatische Sicherung: nein (laut Betreiber); Sicherung nach Angabe des Betreibers: ",
                          "Automatic backup: no (according to the operator); backup as stated by the operator: ") + gap
    out["backup"] += "\n" + t("Aufbewahrungsort der Sicherungskopien (außer Haus): ", "Where the backup copies are kept (off-site): ") + gap
    out["restore"] = t("Ein Administrator der Instanz kann eine Sicherung über die Verwaltung wieder einspielen. Letzter Wiederherstellungstest "
                       "(Datum, Ergebnis): ", "An administrator of the instance can restore a backup in the administration. Last restore test "
                       "(date, result): ") + gap
    keep = (t("Buchungsbelege 8 Jahre (seit 2025), Bücher, Jahresabschlüsse und Inventare 10 Jahre, Handels- und Geschäftsbriefe 6 Jahre "
              "(§ 147 AO, § 257 HGB), jeweils ab Ende des Kalenderjahres.",
              "Booking receipts 8 years (since 2025), books, annual accounts and inventories 10 years, business letters 6 years "
              "(section 147 AO, section 257 HGB), each from the end of the calendar year.") if (s.get("pack") or "DE").upper() == "DE"
            else t("Aufbewahrungsfristen des Landes: ", "Retention periods of the country: ") + gap)
    out["retention"] = "\n".join([keep, t(
        "Finalisierte Rechnungen und Rechnungskorrekturen lassen sich in Kalmido nicht löschen; Kasseneinträge werden nie gelöscht; genehmigte "
        "Bewirtungsbelege bleiben 8 Jahre nach Ende ihres Jahres erhalten.",
        "Finalised invoices and credit notes cannot be deleted in Kalmido; cash entries are never deleted; approved entertainment "
        "receipts are kept for 8 years after the end of their year.")])
    out["access"] = "\n".join([
        t("Jede Person meldet sich mit eigenem Konto an. Zweiter Faktor für alle Konten mit Passwort vorgeschrieben (laut Einstellung des Betreibers): ",
          "Every person signs in with their own account. Second factor required for all accounts with a password (as set by the operator): ") + _yn(L, gsetting(c, "twofa_required") == "1") + ".",
        t("KI-Agenten und Kinderkonten haben keinen Zugriff auf das Büro.", "AI agents and kid accounts have no access to the office.")])

    # 5 internal control system
    out["roles"] = "\n".join([
        t("- Admin: verwaltet Einstellungen, Stammdaten, Festschreiben und diese Dokumentation.",
          "- Admin: manages settings, master data, locking of periods and this documentation."),
        t("- Mitglied: schreibt Angebote, Rechnungen und Belege; ändert keine Einstellungen.",
          "- Member: writes quotations, invoices and receipts; changes no settings."),
        t("- Buchhaltung: liest und exportiert das Büro, lädt Belege hoch.", "- Accounting: reads and exports the office, uploads receipts."),
        t("- Nur lesen: sieht, ändert nichts. Gäste sehen das Büro nicht.", "- Read-only: sees, changes nothing. Guests do not see the office.")]
        + ([t("Persönliches Büro: die Inhaberin bzw. der Inhaber hat alle Rechte allein.", "Personal office: the owner holds all rights alone.")]
           if personal else []))
    out["controls"] = "\n".join([
        t("- Finalisieren von Rechnungen (danach unveränderbar), Festschreiben pro Monat, Tagesabschluss im Kassenbuch.",
          "- Finalising invoices (unchangeable afterwards), locking per month, day closing in the cash book."),
        t("- Bewirtungsbelege werden abgeschlossen; jedes Abschließen und jede Rücknahme wird mit Person und Zeit protokolliert.",
          "- Entertainment receipts are approved; every approval and its undoing is logged with person and time."),
        t("- Protokoll aller Änderungen und Exporte (Abschnitt Protokollierung).", "- Log of all changes and exports (section logging)."),
        t("Weitere Kontrollen (z. B. Vier-Augen-Prinzip bei Zahlungen, monatliche Abstimmung): ",
          "Further controls (e.g. four-eyes principle for payments, monthly reconciliation): ") + gap])
    return out


# ---------------------------------------------------------------- versions
def _pd_ver(r):
    """A row of obj_versions as the code before 2.977 read a row of office_procdocs (data = the sealed JSON text)."""
    return {"id": r["id"], "version": r["no"], "data": r["body"], "created_by": r["created_by"], "created_at": r["created_at"]}


def _row_data(c, oid, r):
    d = oc_dec_fields(c, oid, "obj_versions", {"body": r["data"]})  # sealed with the context obj_versions.body (OBJV_CTX)
    try:
        v = json.loads(d.get("body") or "{}")
    except ValueError:
        v = {}
    return v if isinstance(v, dict) else {}


def pd_head(c, oid, make=False):
    """2.977.0 (#5282): the id of the head row of area oid's procedure documentation (None: none yet); make: create it (the
    caller holds the lock office_procdoc_<oid>)."""
    r = c.execute("SELECT id FROM office_procdocs WHERE org_id=? ORDER BY id DESC LIMIT 1", (oid,)).fetchone()
    if r or not make:
        return r[0] if r else None
    return insert_id(c, "INSERT INTO office_procdocs(org_id) VALUES(?)", (oid,))


def pd_waiting(c, oid):
    """2.977.0 (#5282, Fable review F3 / F4): True while old version rows of area oid wait in office_procdocs (pd_retire kept
    them: the area's key is missing). No new version then (its number would come before the old ones) and no transfer of the
    office (the old rows would move unsealed or be taken for an empty head)."""
    if "version" not in table_columns(c, "office_procdocs"):
        return False
    return c.execute("SELECT 1 FROM office_procdocs WHERE org_id=? AND version IS NOT NULL LIMIT 1", (oid,)).fetchone() is not None


def pd_latest(c, oid):
    h = pd_head(c, oid)
    r = obj_version_last(c, PD_KIND, h) if h else None
    return _pd_ver(r) if r else None


def pd_version_row(c, oid, version):
    h = pd_head(c, oid)
    r = obj_version_no(c, PD_KIND, h, version) if h else None
    if r is None:
        raise Denied(404, tr(PD_NO_VERSION))
    return _pd_ver(r)


def _user_name(c, uid):
    u = c.execute("SELECT display_name, username FROM users WHERE id=?", (uid,)).fetchone() if uid else None
    return (u["display_name"] or u["username"]) if u else ""


def _own_clean(v):
    if not isinstance(v, dict):
        raise BadInput(tr("Invalid value: {0}", "own"))
    out = {}
    for k, x in v.items():
        if k not in PD_FIELDS:
            raise BadInput(tr("Invalid value: {0}", k))
        if x is None:
            x = ""
        if not isinstance(x, str) or len(x) > PD_TEXT_MAX:
            raise BadInput(tr("Invalid value: {0}", k))
        x = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", x.replace("\r\n", "\n")).strip()
        if x:
            out[k] = x
    return out


def pd_state(c, uid, oid, version=None, L=None):
    """The document: the current state (prefilled now + own texts of the latest version) or a saved version as it was."""
    latest = pd_latest(c, oid)
    if version:
        r = pd_version_row(c, oid, version)
        d = _row_data(c, oid, r)
        L = d.get("lang") if d.get("lang") in PD_GAP else "de"
        auto, own, app_v = d.get("auto") or {}, d.get("own") or {}, d.get("app_version") or ""
    else:
        r = latest
        L = _lg(L)
        d = _row_data(c, oid, r) if r else {}
        auto, own, app_v = pd_auto(c, oid, L), d.get("own") or {}, APP_VERSION
    gap = PD_GAP[L]
    sections, gaps = [], 0
    for key, no, de, en, fields in PD_OUTLINE:
        fs = []
        for i, (fk, fde, fen, need) in enumerate(fields, 1):
            a, o = str(auto.get(fk) or ""), str(own.get(fk) or "")
            open_ = not o and (need or gap in a)
            gaps += 1 if open_ else 0
            fs.append({"key": fk, "no": f"{no}.{i}", "title": fde if L == "de" else fen, "auto": a, "own": o, "need": int(need), "gap": int(open_)})
        sections.append({"key": key, "no": no, "title": de if L == "de" else en, "fields": fs})
    s = office_settings(c, oid)
    company = ofx_name1(ofx_company(c, oid).get("name") or (s.get("company") or {}).get("name"))
    return {"version": latest["version"] if latest else 0, "viewing": int(version or 0), "lang": L, "gap_marker": gap,
            "saved_at": r["created_at"] if r else "", "saved_by": _user_name(c, r["created_by"]) if r else "",
            "app_version": app_v, "company": company, "can_edit": int(office_role(c, uid, oid) == "admin"), "gaps": gaps,
            "sections": sections}


def _version_arg():
    v = request.args.get("version") or ""
    if v in ("", "0"):
        return None
    if not v.isdigit() or len(v) > 9:
        raise BadInput(tr("Invalid value: {0}", "version"))
    return int(v)


@app.get("/api/office/procdoc")
def pd_get():
    """?version=N (default: the current state) &lang=de|en -> pd_state."""
    c, uid, oid = _ctx(admin=True)  # 2.237.0 A (#2861): like the other bookkeeping pages (members before the groups: admins only)
    return jsonify(pd_state(c, uid, oid, _version_arg(), request.args.get("lang")))


@app.put("/api/office/procdoc")
def pd_put():
    """The area's admin: {own: {field: text}, lang?, base?: the version the editor started from (409 when a newer one was
    saved meanwhile)} -> a new version (the prefilled texts of now stored with it) -> pd_state of the new state."""
    c, uid, oid = _ctx(admin=True)
    b = request.get_json(silent=True) or {}
    if not isinstance(b, dict):
        raise BadInput(tr("Invalid value: {0}", "body"))
    own = _own_clean(b.get("own") or {})
    L = _lg(b.get("lang"))
    write_lock(c, f"office_procdoc_{int(oid)}")
    if pd_waiting(c, oid):  # 2.977.0 (#5282, Fable review F4)
        raise Denied(409, tr(PD_WAITING))
    head = pd_head(c, oid, make=True)  # 2.977.0 (#5282)
    latest = pd_latest(c, oid)
    n = (latest["version"] if latest else 0) + 1
    base = b.get("base")
    if base is not None and (not isinstance(base, int) or base != n - 1):
        raise Denied(409, tr("Someone saved a newer version meanwhile. Reload to see it."))
    data = json.dumps({"own": own, "auto": pd_auto(c, oid, L), "lang": L, "app_version": APP_VERSION}, ensure_ascii=False)
    row = oc_enc_fields(c, oid, "obj_versions", {"body": data})  # 2.977.0 (#5282): a version of the core, number n
    obj_version_add(c, PD_KIND, head, oid, None, "", row["body"], len(data.encode("utf-8")), uid, iso(now_utc()))
    ofx_log(c, oid, "procdoc", target="procdoc", detail={"version": n, "fields": sorted(own)})
    c.commit()
    return jsonify(pd_state(c, uid, oid, None, L))


@app.get("/api/office/procdoc/versions")
def pd_versions():
    """The saved versions, newest first: [{version, created_at, created_by}] (names only)."""
    c, uid, oid = _ctx(admin=True)  # 2.237.0 A (#2861)
    h = pd_head(c, oid)  # 2.977.0 (#5282): the versions of the core
    rows = c.execute("SELECT no AS version, created_by, created_at FROM obj_versions WHERE kind=? AND ref_id=? ORDER BY no DESC LIMIT ?",
                     (PD_KIND, h, PD_VERSIONS_MAX)).fetchall() if h else []
    names = {}
    out = []
    for r in rows:
        if r["created_by"] not in names:
            names[r["created_by"]] = _user_name(c, r["created_by"])
        out.append({"version": r["version"], "created_at": r["created_at"], "created_by": names[r["created_by"]]})
    return jsonify(items=out)


# ---- 2.977.0 (#5282, stage Q7b): the old version rows of office_procdocs -> obj_versions at the start, then the columns go ----
PD_OLD_COLS = ("version", "data", "created_by", "created_at")
PD_RETIRE_LABEL = "procedure documentation, stage Q7b (#5282)"
PD_RETIRE_WAITS = N_("Procedure documentation clean-up waits: {0} old versions in {1} cannot be opened now (the key of their office is missing), the old columns stay. See the server log.")
PD_RETIRE_WHY = ("cannot be opened now (the key of their office is missing) -- they stay there, nothing dropped; the next start "
                 "tries again (core/migrations.d/5282_a.py)")


def pd_move_old(c):
    """Every old version row of office_procdocs (version set) into obj_versions kind "procdoc": ref_id = the head of its area
    (the area's newest row, which stays), its number kept where it is free, the sealed JSON opened with the context
    office_procdocs.data and sealed again with obj_versions.body (the same key), created_by (an account that is gone: NULL),
    created_at as TIMESTAMPTZ. All of an area or nothing: an area with a text that cannot be opened now moves nothing (its
    rows stay for the next start). A moved row gets version NULL at once (idempotent). -> {"moved": n, "kept": m}."""
    now, out = iso(now_utc()), {"moved": 0, "kept": 0}
    people = {r[0] for r in c.execute("SELECT DISTINCT u.id FROM users u JOIN office_procdocs p ON p.created_by=u.id")}
    for (oid,) in c.execute("SELECT DISTINCT org_id FROM office_procdocs WHERE version IS NOT NULL ORDER BY org_id").fetchall():
        rows = c.execute("SELECT id, version, data, created_by, created_at FROM office_procdocs WHERE org_id=? AND version IS NOT NULL "
                         "ORDER BY version, id", (oid,)).fetchall()
        key, moved = None, []
        try:
            for r in rows:
                v = r["data"] or "{}"
                if oc_is_enc(v):
                    key = key or oc_key(c, oid, create=False)
                    plain = oc_dec_k(key, oid, "office_procdocs.data", v)
                    moved.append((r, oc_enc_k(key, oid, OBJV_CTX, plain), len(plain.encode("utf-8"))))
                else:
                    moved.append((r, v, len(v.encode("utf-8"))))
        except (OrgCryptError, TypeError, ValueError):
            print(f"{PD_RETIRE_LABEL}: the {len(rows)} old version(s) of office area {oid} stay in office_procdocs -- {PD_RETIRE_WHY}",
                  flush=True)
            out["kept"] += len(rows)
            continue
        head = c.execute("SELECT MAX(id) FROM office_procdocs WHERE org_id=?", (oid,)).fetchone()[0]
        for r, body, size in moved:
            at = obj_version_old_ts(r["created_at"], now)
            c.execute("INSERT INTO obj_versions(kind,ref_id,no,org_id,owner_id,title,body,size,created_by,created_at,updated_at,source) "
                      "VALUES(?,?,?,?,NULL,'',?,?,?,?,?,'')",
                      (PD_KIND, head, obj_version_free_no(c, PD_KIND, head, r["version"]), oid, body, size,
                       r["created_by"] if r["created_by"] in people else None, at, at))
            c.execute("UPDATE office_procdocs SET version=NULL WHERE id=?", (r["id"],))
            out["moved"] += 1
    return out


def _pd_left(c):
    return c.execute("SELECT COUNT(*) FROM office_procdocs WHERE version IS NOT NULL").fetchone()[0]


def _pd_prune(c):
    """The rows besides the heads (the newest row of each area); their versions are in obj_versions on the head."""
    return c.execute("DELETE FROM office_procdocs p WHERE EXISTS (SELECT 1 FROM office_procdocs x WHERE x.org_id=p.org_id AND x.id>p.id)").rowcount


def _pd_alert(n, tables):
    aa_now("storage", "kern5282:" + ",".join(tables), PD_RETIRE_WAITS, (int(n), ", ".join(tables)))


def pd_retire(c):
    """2.977.0 (#5282, core/objhooks.START, every start until done): pd_move_old, then the start check, the rows besides the
    heads and the columns PD_OLD_COLS (core/kernretire.py kern_retire_rows: the back limit rises), one head per area (unique
    index). {} once the columns are gone (a catalog read)."""
    if not table_exists(c, "office_procdocs") or "data" not in table_columns(c, "office_procdocs"):
        return {}
    with system_ctx(c):  # every office area's documentation; nothing is handed to a person
        write_lock(c, KERN_RETIRE_LOCK)
        if "data" not in table_columns(c, "office_procdocs"):  # another process did it meanwhile
            return {}
        # the new code writes heads (org_id only) while old rows wait for a key: the old columns must not refuse them
        c.execute("ALTER TABLE office_procdocs ALTER COLUMN version DROP NOT NULL, ALTER COLUMN created_at DROP NOT NULL")
        out = pd_move_old(c)
        if out["moved"]:  # the data left the old columns: an older image must not start before the drop
            kern_retire_floor(c)
        out.update(kern_retire_rows(c, "office_procdocs", PD_OLD_COLS, _pd_left, PD_RETIRE_LABEL, prune=_pd_prune, alert=_pd_alert,
                                    why=PD_RETIRE_WHY,
                                    alter=("CREATE UNIQUE INDEX IF NOT EXISTS office_procdocs_org ON office_procdocs(org_id)",)))
    return out


objhooks.START.append(("kern5282_procdocs", False, pd_retire))  # 2.977.0 (#5282): every start until the old columns are gone


# ---------------------------------------------------------------- export
def _head(d):
    L = d["lang"]
    t = (lambda de, en: de if L == "de" else en)  # noqa: E731
    day = (d["saved_at"] or iso(now_utc()))[:10] if d["viewing"] else iso(now_utc())[:10]
    ver = (t(f"Version {d['viewing']} vom {day}", f"Version {d['viewing']} of {day}") if d["viewing"]
           else t(f"Version {d['version']}, Stand {day}", f"Version {d['version']}, state of {day}") if d["version"]
           else t(f"Stand {day}, noch keine Version gespeichert", f"State of {day}, no version saved yet"))
    return (t("Verfahrensdokumentation", "Procedure documentation"),
            [x for x in (d["company"], ver, f"Kalmido {d['app_version']}" if d["app_version"] else "") if x])


def _body_text(f, gap):
    parts = [x for x in (f["auto"], f["own"]) if x]
    if f["gap"] and not f["own"] and gap not in f["auto"]:
        parts.append(gap)
    return "\n\n".join(parts)


def pd_markdown(d):
    title, head = _head(d)
    out = [f"# {title}", ""] + [f"{x}  " for x in head] + [""]
    for s in d["sections"]:
        out += [f"## {s['no']} {s['title']}", ""]
        for f in s["fields"]:
            out += [f"### {f['no']} {f['title']}", "", _body_text(f, d["gap_marker"]), ""]
    return "\n".join(out).rstrip() + "\n"


def pd_pdf(d, paper=None):
    from .pdf import A4_H, A4_W, C_INK2, C_RULE, _Page, pdf_wrap, pdf_write
    ppr = pdf_paper_ns(paper)  # 2.357.0 A (#3156): the office's paper size (None = A4)
    A4_H, A4_W, _Page = ppr.A4_H, ppr.A4_W, ppr._Page
    title, head = _head(d)
    x0, x1 = 56, A4_W - 56
    w = x1 - x0
    pages, st = [], {"pg": None, "y": 0}

    def page():
        st["pg"] = _Page()
        pages.append(st["pg"])
        st["y"] = 56

    def need(h):
        if st["pg"] is None or st["y"] + h > A4_H - 56:
            page()

    def para(text, size, bold=False, color=None, after=4):
        lh = size * 1.42
        for raw in str(text).split("\n"):
            for ln in pdf_wrap(raw, size, w, bold) or [""]:
                need(lh)
                if color:
                    st["pg"].text(x0, st["y"], ln, size, bold, color)
                else:
                    st["pg"].text(x0, st["y"], ln, size, bold)
                st["y"] += lh
        st["y"] += after

    page()
    para(title, 16, bold=True, after=6)
    for x in head:
        para(x, 9, color=C_INK2, after=0)
    st["y"] += 10
    for s in d["sections"]:
        need(60)
        para(f"{s['no']} {s['title']}", 13, bold=True, after=2)
        st["pg"].line(x0, st["y"], x1, st["y"], color=C_RULE)
        st["y"] += 8
        for f in s["fields"]:
            need(40)
            para(f"{f['no']} {f['title']}", 10, bold=True, after=2)
            para(_body_text(f, d["gap_marker"]), 9, after=10)
    return pdf_write(pages, {}, title=title, author=d["company"] or "")


def _fname(d, ext):
    base = "verfahrensdokumentation" if d["lang"] == "de" else "procedure-documentation"
    return f"{base}-v{d['viewing'] or d['version']}.{ext}"


@app.get("/api/office/procdoc.md")
def pd_md():
    """?version=N&lang=de|en -> the document as Markdown (head: company, version, date, Kalmido version)."""
    c, uid, oid = _ctx(admin=True)  # 2.237.0 A (#2861)
    d = pd_state(c, uid, oid, _version_arg(), request.args.get("lang"))
    ofx_log(c, oid, "export", target="procdoc", detail={"what": "md", "version": d["viewing"] or d["version"]}, dedupe_min=5)
    c.commit()
    return Response(pd_markdown(d), mimetype="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(d, "md")}"', "Cache-Control": "no-store"})


@app.get("/api/office/procdoc.pdf")
def pd_pdf_get():
    """?version=N&lang=de|en -> the document as PDF."""
    c, uid, oid = _ctx(admin=True)  # 2.237.0 A (#2861)
    d = pd_state(c, uid, oid, _version_arg(), request.args.get("lang"))
    data = pd_pdf(d, office_settings(c, oid).get("paper"))  # 2.357.0 A (#3156)
    ofx_log(c, oid, "export", target="procdoc", detail={"what": "pdf", "version": d["viewing"] or d["version"]}, dedupe_min=5)
    c.commit()
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{_fname(d, "pdf")}"', "Cache-Control": "no-store"})
