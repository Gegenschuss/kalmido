"""2.117.0 B (#2283): more samples for the document templates (letters next to the three contract samples of doctpl.DT_STARTERS).

Shipped in the code only (never written into the database ahead): "Use sample" makes an own, freely editable template of
one in the current office area (organisation or private). Each sample: kind (a key of doctpl.DT_KINDS), whether documents
from it can be signed, whether it is a legal text (the picker says to have it checked) and the text in German and English;
2.449.0 (#3768): fr / es / it / nl live in doctpl_samples_<lang>.py and join by sample_langs. Only the variables of doctpl.DT_VARS; what no variable
knows (an invoice number, a date of notice) stays as [placeholder] in square brackets for the user to fill in. The PDF
already prints the letterhead and the client's address field, so the letters start with their subject line. Neutral
texts without names, firms or addresses; no legal advice."""
from . import doctpl_samples_es, doctpl_samples_fr, doctpl_samples_it, doctpl_samples_nl

# 2.449.0 (#3768): the translated samples; the ones here tell the picker "machine translated, check before use" (their text says so too)
SAMPLE_LANGS = {"fr": doctpl_samples_fr, "es": doctpl_samples_es, "it": doctpl_samples_it, "nl": doctpl_samples_nl}
SAMPLE_MT = ("nda", "privacy_dpa", "privacy_info", "privacy_consent")


def sample_langs(starters, part="SAMPLES"):
    """2.449.0 (#3768): adds the translated (name, text) of each language to a table of samples (in place) and returns it."""
    for lg, mod in SAMPLE_LANGS.items():
        for k, tx in getattr(mod, part).items():
            if k in starters:
                starters[k][lg] = tx
    return starters


def sample_text(v, lg):
    """2.449.0 (#3768): (name, text) of a sample in lg; a language without its own text takes the English one."""
    return v.get(lg) or v["en"]


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
               "de": ("Rechnungskorrektur-Anschreiben", """# Ihre Rechnungskorrektur [Rechnungskorrekturnummer]

Sehr geehrte Damen und Herren,

anbei erhalten Sie unsere Rechnungskorrektur [Rechnungskorrekturnummer] vom {{today}} über [Betrag] zur Rechnung [Rechnungsnummer] im Projekt {{project.title}}.

Den Betrag [überweisen wir bis zum Datum auf Ihr Konto / verrechnen wir mit der nächsten Rechnung].

Mit freundlichen Grüßen
{{company.name}}"""),
               "en": ("Credit note cover letter", """# Your credit note [credit note number]

Dear Sir or Madam,

please find enclosed our credit note [credit note number] of {{today}} amounting to [amount] for invoice [invoice number] in the project {{project.title}}.

We will [transfer the amount to your account by the date / offset the amount against the next invoice].

Kind regards
{{company.name}}""")},
    # 2.154.0 C (#2192): the data protection sheets of a client (office/privacy.py makes them from the client card). The
    # first line in brackets says what they are; a text with [placeholders] opens in the editor before it is finished
    "privacy_dpa": {"kind": "other", "sign": 1, "legal": 1,
                    "de": ("Vertrag zur Auftragsverarbeitung (AVV)", """# Vertrag zur Auftragsverarbeitung

[Mustertext, keine Rechtsberatung: vor der Verwendung prüfen, an den Auftrag anpassen und diese Zeile löschen.]

Zwischen {{client.name}}, {{client.address}} (Verantwortlicher)
und {{company.name}}, {{company.address}} (Auftragsverarbeiter)

## 1. Gegenstand und Dauer
Der Auftragsverarbeiter verarbeitet personenbezogene Daten im Auftrag des Verantwortlichen für folgende Leistungen: [Leistungen]. Die Dauer richtet sich nach der Laufzeit des zugrunde liegenden Auftrags.

## 2. Art und Zweck der Verarbeitung
[Art und Zweck, z. B. Speicherung, Pflege, Auswertung]

## 3. Art der Daten und Kreis der Betroffenen
- Arten personenbezogener Daten: [z. B. Kontaktdaten, Vertragsdaten]
- Kategorien betroffener Personen: [z. B. Kundinnen und Kunden, Beschäftigte]

## 4. Weisungen
Der Auftragsverarbeiter verarbeitet die Daten nur auf dokumentierte Weisung des Verantwortlichen (Art. 28 Abs. 3 lit. a DSGVO).

## 5. Vertraulichkeit
Die zur Verarbeitung befugten Personen sind zur Vertraulichkeit verpflichtet (Art. 28 Abs. 3 lit. b DSGVO).

## 6. Sicherheit der Verarbeitung
Der Auftragsverarbeiter trifft die technischen und organisatorischen Maßnahmen nach Art. 32 DSGVO: [Maßnahmen oder Anlage].

## 7. Unterauftragsverarbeiter
Weitere Auftragsverarbeiter werden nur mit vorheriger Genehmigung des Verantwortlichen eingesetzt (Art. 28 Abs. 2 und 4 DSGVO). Derzeit: [keine / Liste].

## 8. Unterstützung
Der Auftragsverarbeiter unterstützt den Verantwortlichen bei Anfragen betroffener Personen und bei den Pflichten nach Art. 32 bis 36 DSGVO (Art. 28 Abs. 3 lit. e und f DSGVO).

## 9. Löschung und Rückgabe
Nach Ende der Leistungen werden die Daten nach Wahl des Verantwortlichen gelöscht oder zurückgegeben, soweit keine Pflicht zur Speicherung besteht (Art. 28 Abs. 3 lit. g DSGVO).

## 10. Nachweise und Überprüfungen
Der Auftragsverarbeiter stellt die nötigen Informationen zum Nachweis bereit und ermöglicht Überprüfungen (Art. 28 Abs. 3 lit. h DSGVO).

## 11. Meldung von Verletzungen
Der Auftragsverarbeiter meldet eine Verletzung des Schutzes personenbezogener Daten unverzüglich, nachdem sie ihm bekannt wurde (Art. 33 Abs. 2 DSGVO).

Datum: {{today}}"""),
                    "en": ("Data processing agreement (DPA)", """# Data processing agreement

[Sample text, no legal advice: check it before use, adapt it to the order and delete this line.]

Between {{client.name}}, {{client.address}} (controller)
and {{company.name}}, {{company.address}} (processor)

## 1. Subject and duration
The processor processes personal data on behalf of the controller for the following services: [services]. The duration follows the term of the underlying order.

## 2. Nature and purpose of the processing
[nature and purpose, e.g. storage, maintenance, analysis]

## 3. Types of data and data subjects
- Types of personal data: [e.g. contact data, contract data]
- Categories of data subjects: [e.g. customers, employees]

## 4. Instructions
The processor processes the data only on documented instructions from the controller (Art. 28(3)(a) GDPR).

## 5. Confidentiality
Persons authorised to process the data are committed to confidentiality (Art. 28(3)(b) GDPR).

## 6. Security of processing
The processor takes the technical and organisational measures of Art. 32 GDPR: [measures or annex].

## 7. Sub-processors
Other processors are engaged only with the prior authorisation of the controller (Art. 28(2) and (4) GDPR). Currently: [none / list].

## 8. Assistance
The processor assists the controller with requests of data subjects and with the obligations of Art. 32 to 36 GDPR (Art. 28(3)(e) and (f) GDPR).

## 9. Deletion and return
After the end of the services the data is deleted or returned at the choice of the controller, unless storage is required by law (Art. 28(3)(g) GDPR).

## 10. Evidence and audits
The processor makes available the information needed to demonstrate compliance and allows for audits (Art. 28(3)(h) GDPR).

## 11. Notification of breaches
The processor notifies a personal data breach without undue delay after becoming aware of it (Art. 33(2) GDPR).

Date: {{today}}""")},
    "privacy_info": {"kind": "other", "sign": 0, "legal": 1,
                     "de": ("Datenschutzhinweise", """# Datenschutzhinweise

[Mustertext, keine Rechtsberatung: vor der Verwendung prüfen, ergänzen und diese Zeile löschen.]

Informationen nach Art. 13 und 14 DSGVO für {{client.name}}

## 1. Verantwortlicher
{{company.name}}, {{company.address}}

## 2. Zwecke und Rechtsgrundlagen
Wir verarbeiten Ihre Daten, um einen Vertrag mit Ihnen vorzubereiten und zu erfüllen (Art. 6 Abs. 1 lit. b DSGVO), um gesetzliche Pflichten zu erfüllen, etwa Aufbewahrungspflichten (Art. 6 Abs. 1 lit. c DSGVO), und soweit Sie eingewilligt haben (Art. 6 Abs. 1 lit. a DSGVO).

## 3. Kategorien von Daten
[z. B. Name, Anschrift, Kontaktdaten, Vertrags- und Rechnungsdaten]

## 4. Empfänger
[z. B. Steuerberatung, Dienstleister für Hosting als Auftragsverarbeiter]

## 5. Übermittlung in Drittländer
[keine / Angaben]

## 6. Speicherdauer
Wir speichern Ihre Daten, solange es für die genannten Zwecke nötig ist, und darüber hinaus, soweit gesetzliche Aufbewahrungsfristen bestehen: [Fristen].

## 7. Ihre Rechte
- Auskunft, Berichtigung, Löschung und Einschränkung der Verarbeitung (Art. 15 bis 18 DSGVO)
- Datenübertragbarkeit (Art. 20 DSGVO) und Widerspruch (Art. 21 DSGVO)
- Widerruf einer Einwilligung jederzeit mit Wirkung für die Zukunft (Art. 7 Abs. 3 DSGVO)
- Beschwerde bei einer Datenschutz-Aufsichtsbehörde (Art. 77 DSGVO)

## 8. Bereitstellung
Die für den Vertrag nötigen Daten brauchen wir, um den Vertrag zu schließen und zu erfüllen. [Datenschutzbeauftragte Person, falls benannt]

Stand: {{today}}"""),
                     "en": ("Privacy information", """# Privacy information

[Sample text, no legal advice: check it before use, complete it and delete this line.]

Information under Art. 13 and 14 GDPR for {{client.name}}

## 1. Controller
{{company.name}}, {{company.address}}

## 2. Purposes and legal bases
We process your data to prepare and perform a contract with you (Art. 6(1)(b) GDPR), to meet legal obligations such as retention duties (Art. 6(1)(c) GDPR) and where you have given your consent (Art. 6(1)(a) GDPR).

## 3. Categories of data
[e.g. name, address, contact data, contract and billing data]

## 4. Recipients
[e.g. tax adviser, hosting provider as processor]

## 5. Transfers to third countries
[none / details]

## 6. Storage period
We keep your data as long as it is needed for these purposes and beyond that where legal retention periods apply: [periods].

## 7. Your rights
- Access, rectification, erasure and restriction of processing (Art. 15 to 18 GDPR)
- Data portability (Art. 20 GDPR) and objection (Art. 21 GDPR)
- Withdrawal of a consent at any time with effect for the future (Art. 7(3) GDPR)
- Complaint to a data protection supervisory authority (Art. 77 GDPR)

## 8. Provision of data
We need the data required for the contract to conclude and perform it. [data protection officer, if appointed]

As of: {{today}}""")},
    "privacy_consent": {"kind": "other", "sign": 1, "legal": 1,
                        "de": ("Einwilligung in die Datenverarbeitung", """# Einwilligung in die Datenverarbeitung

[Mustertext, keine Rechtsberatung: vor der Verwendung prüfen, anpassen und diese Zeile löschen.]

{{client.name}}, vertreten durch {{client.contact}}, willigt ein, dass {{company.name}} folgende personenbezogene Daten verarbeitet:

- Daten: [Daten]
- Zweck: [Zweck]

## Freiwilligkeit und Widerruf
Die Einwilligung ist freiwillig. Sie kann jederzeit ohne Angabe von Gründen mit Wirkung für die Zukunft widerrufen werden (Art. 7 Abs. 3 DSGVO), zum Beispiel per E-Mail an [E-Mail-Adresse]. Die Rechtmäßigkeit der Verarbeitung bis zum Widerruf bleibt davon unberührt.

Weitere Informationen stehen in unseren Datenschutzhinweisen.

Datum: {{today}}"""),
                        "en": ("Consent to data processing", """# Consent to data processing

[Sample text, no legal advice: check it before use, adapt it and delete this line.]

{{client.name}}, represented by {{client.contact}}, consents to {{company.name}} processing the following personal data:

- Data: [data]
- Purpose: [purpose]

## Voluntariness and withdrawal
The consent is voluntary. It can be withdrawn at any time without giving reasons with effect for the future (Art. 7(3) GDPR), for example by e-mail to [e-mail address]. Withdrawal does not affect the lawfulness of the processing before it.

More information is given in our privacy information.

Date: {{today}}""")},
    # 2.385.0 (#2293): three film samples, only offered while the area has the industry pack Film & Video on (pack: film,
    # doctpl.dt_sample_on); neutral texts, the first line says to have them checked
    "film_permit": {"kind": "other", "sign": 1, "legal": 1, "pack": "film",
                    "de": ("Drehgenehmigung", """# Drehgenehmigung

[Mustertext, keine Rechtsberatung: vor der Verwendung prüfen, anpassen und diese Zeile löschen.]

{{client.name}}
{{client.address}}
vertreten durch {{client.contact}}

erlaubt

{{company.name}}
{{company.address}}

für das Projekt {{project.title}} Film- und Fotoaufnahmen an folgendem Ort:

- Ort: [Adresse, Bereich, Räume]
- Drehtage: [Datum] von [Uhrzeit] bis [Uhrzeit], Ausweichtermin [Datum]
- Umfang: [Anzahl Personen im Team, Fahrzeuge, Technik, Strom, Parkflächen]
- Aufbau und Abbau: [Zeiten]

## Auflagen
- Zugänge, Wege und Rettungswege bleiben frei; Anweisungen der Ansprechperson vor Ort ([Name, Telefon]) werden befolgt.
- Der Ort wird im vorgefundenen Zustand zurückgegeben; Schäden werden sofort gemeldet.
- [weitere Auflagen, zum Beispiel Ruhezeiten, keine Aufnahmen von Personen ohne deren Einwilligung]

## Nutzung der Aufnahmen
Die Aufnahmen dürfen für [Zweck, Medien, Gebiet, Dauer] genutzt werden. Der Ort wird [nicht] namentlich genannt.

## Entgelt und Versicherung
Entgelt: [Betrag oder unentgeltlich]. {{company.name}} hat eine Haftpflichtversicherung für die Dreharbeiten [Versicherer, Deckungssumme].

Behördliche Genehmigungen (zum Beispiel für öffentlichen Grund) holt [wer] ein; diese Erlaubnis ersetzt sie nicht.

Datum: {{today}}"""),
                    "en": ("Filming permission", """# Filming permission

[Sample text, no legal advice: check it before use, adapt it and delete this line.]

{{client.name}}
{{client.address}}
represented by {{client.contact}}

permits

{{company.name}}
{{company.address}}

to film and take photographs for the project {{project.title}} at the following location:

- Location: [address, area, rooms]
- Shoot days: [date] from [time] to [time], alternative date [date]
- Scope: [crew size, vehicles, equipment, power, parking]
- Set-up and strike: [times]

## Conditions
- Entrances, paths and emergency exits stay clear; the instructions of the contact on site ([name, phone]) are followed.
- The location is handed back in the condition it was found in; any damage is reported at once.
- [further conditions, e.g. quiet hours, no recordings of people without their consent]

## Use of the recordings
The recordings may be used for [purpose, media, territory, period]. The location is [not] named.

## Fee and insurance
Fee: [amount or free of charge]. {{company.name}} holds liability insurance for the shoot [insurer, sum insured].

Official permits (e.g. for public ground) are obtained by [who]; this permission does not replace them.

Date: {{today}}""")},
    "film_location": {"kind": "contract", "sign": 1, "legal": 1, "pack": "film",
                      "de": ("Location-Vertrag", """# Location-Vertrag

[Mustertext, keine Rechtsberatung: vor der Verwendung prüfen, anpassen und diese Zeile löschen.]

zwischen {{client.name}}, {{client.address}} (Überlassende Seite)
und {{company.name}}, {{company.address}} (Produktion)

## 1. Gegenstand
Die überlassende Seite stellt der Produktion für das Projekt {{project.title}} folgenden Ort für Film- und Fotoaufnahmen zur Verfügung: [Adresse, Räume, Außenflächen, mitbenutzte Einrichtung].

## 2. Zeitraum
Vorbereitung und Aufbau: [Datum, Uhrzeit]
Drehtage: [Datum, Uhrzeit von bis]
Abbau und Rückgabe: [Datum, Uhrzeit]
Verschiebt sich der Dreh (zum Beispiel wegen Wetter), gilt nach Absprache [Ausweichtermin].

## 3. Entgelt
Die Produktion zahlt [Betrag] [zuzüglich Umsatzsteuer] für den gesamten Zeitraum, fällig [Zahlungsziel]. Zusätzliche Tage: [Betrag je Tag]. Nebenkosten (Strom, Reinigung): [inklusive / nach Aufwand].

## 4. Zustand und Rückgabe
Der Zustand des Ortes wird vor Beginn festgehalten [Übergabeprotokoll, Fotos]. Veränderungen (Möbel umstellen, Dekoration, Befestigungen) nur nach Absprache; die Produktion stellt den ursprünglichen Zustand bis zur Rückgabe wieder her.

## 5. Haftung und Versicherung
Die Produktion haftet für Schäden, die sie, ihr Team oder ihre Dienstleister verursachen. Sie hat eine Haftpflichtversicherung [Versicherer, Deckungssumme]. Für Wertgegenstände der überlassenden Seite gilt: [Regelung].

## 6. Nutzung der Aufnahmen
Die Produktion darf die Aufnahmen des Ortes zeitlich, räumlich und inhaltlich [unbeschränkt / beschränkt auf …] nutzen. Name und Adresse des Ortes werden [nicht] genannt.

## 7. Rücktritt
Sagt eine Seite ab, gilt: [Fristen, Ausfallentgelt].

## 8. Schluss
Änderungen bedürfen der Textform. Ist eine Bestimmung unwirksam, bleibt der Vertrag im Übrigen wirksam.

Datum: {{today}}"""),
                      "en": ("Location agreement", """# Location agreement

[Sample text, no legal advice: check it before use, adapt it and delete this line.]

between {{client.name}}, {{client.address}} (owner)
and {{company.name}}, {{company.address}} (production)

## 1. Subject
The owner provides the production with the following location for filming and photography for the project {{project.title}}: [address, rooms, outdoor areas, furnishings used].

## 2. Period
Preparation and set-up: [date, time]
Shoot days: [date, time from to]
Strike and handback: [date, time]
If the shoot is postponed (e.g. due to weather), [alternative date] applies by agreement.

## 3. Fee
The production pays [amount] [plus VAT] for the whole period, due [payment term]. Additional days: [amount per day]. Utilities (power, cleaning): [included / at cost].

## 4. Condition and handback
The condition of the location is recorded before the start [handover record, photos]. Changes (moving furniture, set dressing, fixings) only by agreement; the production restores the original condition by the handback.

## 5. Liability and insurance
The production is liable for damage caused by it, its crew or its contractors. It holds liability insurance [insurer, sum insured]. For valuables of the owner: [arrangement].

## 6. Use of the recordings
The production may use the recordings of the location [without limitation / limited to …] in time, territory and content. The name and address of the location are [not] stated.

## 7. Cancellation
If one party cancels: [notice periods, cancellation fee].

## 8. Final provisions
Changes must be made in text form. Should a provision be invalid, the rest of the agreement remains valid.

Date: {{today}}""")},
    "film_release": {"kind": "contract", "sign": 1, "legal": 1, "pack": "film",
                     "de": ("Model-Release", """# Model-Release (Einwilligung in Bild- und Tonaufnahmen)

[Mustertext, keine Rechtsberatung: vor der Verwendung prüfen, anpassen und diese Zeile löschen.]

Ich, {{client.name}}, {{client.address}}, willige ein, dass {{company.name}} im Projekt {{project.title}} Bild- und Tonaufnahmen von mir macht und nutzt.

## Aufnahmen
- Datum und Ort: [Datum, Ort]
- Art: [Foto, Video, Ton]
- Rolle: [zum Beispiel Darstellerin, Interviewpartner, Komparse]

## Nutzungsumfang
- Zweck: [zum Beispiel Werbefilm für …, Dokumentation, Social Media]
- Medien: [Internet, TV, Kino, Print, Messe]
- Gebiet und Dauer: [Gebiet], [Dauer]
- Bearbeitung: Die Aufnahmen dürfen geschnitten, bearbeitet und mit anderen Inhalten verbunden werden, ohne den Sinn zu entstellen.
- Namensnennung: [ja / nein]

## Vergütung
[Betrag oder unentgeltlich]. Weitere Ansprüche aus der Nutzung im vereinbarten Umfang bestehen nicht.

## Datenschutz und Widerruf
Die Aufnahmen und die Angaben dieser Erklärung werden zur Herstellung und Auswertung des Projekts verarbeitet. Die Einwilligung ist freiwillig. Ein Widerruf ist an [E-Mail-Adresse] möglich und gilt für die Zukunft; bereits veröffentlichte oder fertiggestellte Produktionen bleiben davon [unberührt / betroffen, Regelung]. Mehr dazu in unseren Datenschutzhinweisen.

[Bei Minderjährigen: Einwilligung der Sorgeberechtigten, Name und Unterschrift.]

Datum: {{today}}"""),
                     "en": ("Model release", """# Model release (consent to image and sound recordings)

[Sample text, no legal advice: check it before use, adapt it and delete this line.]

I, {{client.name}}, {{client.address}}, consent to {{company.name}} making and using image and sound recordings of me in the project {{project.title}}.

## Recordings
- Date and place: [date, place]
- Type: [photo, video, sound]
- Role: [e.g. actor, interviewee, extra]

## Scope of use
- Purpose: [e.g. commercial for …, documentary, social media]
- Media: [internet, TV, cinema, print, trade fair]
- Territory and period: [territory], [period]
- Editing: the recordings may be cut, edited and combined with other content without distorting their meaning.
- Credit: [yes / no]

## Fee
[amount or free of charge]. No further claims arise from the use within the agreed scope.

## Data protection and withdrawal
The recordings and the details of this declaration are processed to produce and exploit the project. The consent is voluntary. It can be withdrawn by writing to [e-mail address] with effect for the future; productions already published or completed remain [unaffected / affected, arrangement]. More in our privacy information.

[For minors: consent of the parents or guardians, name and signature.]

Date: {{today}}""")},
}
sample_langs(DMA_SAMPLES)
