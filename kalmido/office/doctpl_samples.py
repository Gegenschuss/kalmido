"""2.117.0 B (#2283): more samples for the document templates (letters next to the three contract samples of doctpl.DT_STARTERS).

Shipped in the code only (never written into the database ahead): "Use sample" makes an own, freely editable template of
one in the current office area (organisation or private). Each sample: kind (a key of doctpl.DT_KINDS), whether documents
from it can be signed, whether it is a legal text (the picker says to have it checked) and the text in German and English
(the other app languages get the English one, see doctpl.dt_lang). Only the variables of doctpl.DT_VARS; what no variable
knows (an invoice number, a date of notice) stays as [placeholder] in square brackets for the user to fill in. The PDF
already prints the letterhead and the client's address field, so the letters start with their subject line. Neutral
texts without names, firms or addresses; no legal advice."""

DMA_SAMPLES = {
    "letter": {"kind": "other", "sign": 0, "legal": 0,
               "de": ("Anschreiben", """# [Betreff]

Sehr geehrte Damen und Herren,

[Ihr Text]

Bei Fragen erreichen Sie uns jederzeit.

Mit freundlichen Grüßen
{{company.name}}"""),
               "en": ("Cover letter", """# [Subject]

Dear Sir or Madam,

[Your text]

Please do not hesitate to contact us if you have any questions.

Kind regards
{{company.name}}""")},
    "reminder": {"kind": "other", "sign": 0, "legal": 0,
                 "de": ("Zahlungserinnerung", """# Zahlungserinnerung

Sehr geehrte Damen und Herren,

sicher ist es Ihrer Aufmerksamkeit entgangen: Für die Rechnung [Rechnungsnummer] vom [Rechnungsdatum] über [Betrag] haben wir noch keinen Zahlungseingang festgestellt.

Bitte überweisen Sie den offenen Betrag bis zum [Datum] auf das in der Rechnung genannte Konto. Haben Sie inzwischen bezahlt, betrachten Sie dieses Schreiben bitte als gegenstandslos.

Mit freundlichen Grüßen
{{company.name}}"""),
                 "en": ("Payment reminder", """# Payment reminder

Dear Sir or Madam,

perhaps it has escaped your attention: we have not yet received payment for invoice [invoice number] of [invoice date] amounting to [amount].

Please transfer the open amount by [date] to the account stated on the invoice. If you have paid in the meantime, please disregard this letter.

Kind regards
{{company.name}}""")},
    "dunning": {"kind": "other", "sign": 0, "legal": 1,
                "de": ("Mahnung", """# Mahnung

Sehr geehrte Damen und Herren,

trotz unserer Zahlungserinnerung vom [Datum der Erinnerung] ist die Rechnung [Rechnungsnummer] vom [Rechnungsdatum] über [Betrag] noch offen.

Bitte begleichen Sie den offenen Betrag bis spätestens [Frist]. Nach Ablauf der Frist behalten wir uns weitere Schritte vor.

Haben Sie inzwischen bezahlt, betrachten Sie dieses Schreiben bitte als gegenstandslos.

Mit freundlichen Grüßen
{{company.name}}"""),
                "en": ("Dunning letter", """# Dunning letter

Dear Sir or Madam,

despite our payment reminder of [date of the reminder], invoice [invoice number] of [invoice date] amounting to [amount] is still open.

Please settle the open amount by [deadline] at the latest. After this deadline we reserve the right to take further steps.

If you have paid in the meantime, please disregard this letter.

Kind regards
{{company.name}}""")},
    "termination": {"kind": "other", "sign": 0, "legal": 1,
                    "de": ("Kündigung", """# Kündigung des Vertrags [Vertrag / Vertragsnummer]

Sehr geehrte Damen und Herren,

hiermit kündigen wir den oben genannten Vertrag fristgerecht zum [Datum], hilfsweise zum nächstmöglichen Termin.

Bitte bestätigen Sie uns den Eingang dieser Kündigung und das Vertragsende schriftlich.

Mit freundlichen Grüßen
{{company.name}}

{{today}}"""),
                    "en": ("Notice of termination", """# Termination of the contract [contract / contract number]

Dear Sir or Madam,

we hereby give notice to terminate the above contract with effect from [date], or alternatively at the next possible date.

Please confirm in writing the receipt of this notice and the end of the contract.

Kind regards
{{company.name}}

{{today}}""")},
    "authority": {"kind": "other", "sign": 1, "legal": 1,
                  "de": ("Vollmacht", """# Vollmacht

{{client.name}}
{{client.address}}

bevollmächtigt hiermit

{{company.name}}
{{company.address}}

im Projekt {{project.title}} folgende Handlungen im Namen des Vollmachtgebers vorzunehmen:

- [Handlung 1]
- [Handlung 2]

Die Vollmacht gilt ab {{today}} bis [Datum] und kann jederzeit widerrufen werden. Eine Untervollmacht ist [nicht] erlaubt."""),
                  "en": ("Power of attorney", """# Power of attorney

{{client.name}}
{{client.address}}

hereby authorises

{{company.name}}
{{company.address}}

to carry out the following acts on behalf of the principal in the project {{project.title}}:

- [act 1]
- [act 2]

This power of attorney applies from {{today}} until [date] and can be revoked at any time. Sub-delegation is [not] permitted.""")},
    "handover": {"kind": "other", "sign": 1, "legal": 0,
                 "de": ("Übergabeprotokoll", """# Übergabeprotokoll

Projekt: {{project.title}}
Übergabe von {{company.name}} an {{client.name}}
Ansprechpartner: {{client.contact}}
Datum: {{today}}

## Übergeben
- [Gegenstand / Lieferung 1]
- [Gegenstand / Lieferung 2]

## Zustand und Anmerkungen
[Zustand, fehlende Teile, offene Punkte]

## Bestätigung
Der Auftraggeber bestätigt den Erhalt der oben genannten Leistungen in dem beschriebenen Zustand."""),
                 "en": ("Handover record", """# Handover record

Project: {{project.title}}
Handed over by {{company.name}} to {{client.name}}
Contact person: {{client.contact}}
Date: {{today}}

## Handed over
- [item / delivery 1]
- [item / delivery 2]

## Condition and remarks
[condition, missing parts, open points]

## Confirmation
The client confirms receipt of the services listed above in the condition described.""")},
    "credit": {"kind": "other", "sign": 0, "legal": 0,
               "de": ("Gutschrift-Anschreiben", """# Ihre Gutschrift [Gutschriftnummer]

Sehr geehrte Damen und Herren,

anbei erhalten Sie unsere Gutschrift [Gutschriftnummer] vom {{today}} über [Betrag] zur Rechnung [Rechnungsnummer] im Projekt {{project.title}}.

Den Betrag [überweisen wir bis zum Datum auf Ihr Konto / verrechnen wir mit der nächsten Rechnung].

Mit freundlichen Grüßen
{{company.name}}"""),
               "en": ("Credit note cover letter", """# Your credit note [credit note number]

Dear Sir or Madam,

please find enclosed our credit note [credit note number] of {{today}} amounting to [amount] for invoice [invoice number] in the project {{project.title}}.

We will [transfer the amount to your account by the date / offset the amount against the next invoice].

Kind regards
{{company.name}}""")},
}
