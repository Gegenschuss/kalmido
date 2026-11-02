"""2.449.0 (#3768): the samples in Dutch, translated when they were built (Kalmido never calls a language model). Same keys,
variables and [[optional parts]] as the English samples; the legal samples say on their second line that the translation
must be checked. SAMPLES = doctpl.DT_STARTERS + doctpl_samples.DMA_SAMPLES, BLOCKS = lettermail.LTB_STARTERS."""

SAMPLES = {
    "contract": ("Overeenkomst van opdracht", """# Overeenkomst van opdracht

Tussen {{company.name}}[[, {{company.address}}]] (opdrachtnemer)
en {{client.name}}[[, {{client.address}}]] (opdrachtgever)

## 1. Onderwerp
De opdrachtnemer verleent diensten aan de opdrachtgever[[ in het project {{project.title}}]][[ volgens offerte {{offer.number}}]][[ van {{offer.date}}]].

## 2. Vergoeding
De vergoeding volgt uit de offerte[[ en bedraagt {{offer.net}} excl. btw]]. Facturen zijn betaalbaar binnen {{payment.days}} dagen zonder aftrek.

## 3. Medewerking
De opdrachtgever verstrekt de benodigde documenten en informatie tijdig.[[ Contactpersoon bij de opdrachtgever: {{client.contact}}.]]

## 4. Gebruiksrechten
De gebruiksrechten gaan in de overeengekomen omvang over na volledige betaling.

## 5. Slotbepalingen
Wijzigingen en aanvullingen moeten schriftelijk gebeuren. Is een bepaling ongeldig, dan blijft de rest van de overeenkomst geldig.

Datum: {{today}}"""),
    "confirmation": ("Opdrachtbevestiging", """# Opdrachtbevestiging

Geachte heer, mevrouw,

hartelijk dank voor uw opdracht. Wij bevestigen de opdracht[[ volgens onze offerte {{offer.number}}]][[ van {{offer.date}}]][[ voor het project {{project.title}}]].

- Opdrachtgever: {{client.name}}
- Contactpersoon: {{client.contact}}
- Opdrachtbedrag: {{offer.net}} excl. btw

De voorwaarden van de offerte zijn van toepassing. Controleer de gegevens en laat het ons weten als iets niet klopt.

Met vriendelijke groet
{{company.name}}"""),
    "nda": ("Geheimhoudingsovereenkomst", """# Geheimhoudingsovereenkomst

[Machinaal vertaald, vóór gebruik controleren: verwijder daarna deze regel.]

Tussen {{company.name}}[[, {{company.address}}]]
en {{client.name}}[[, {{client.address}}]]

## 1. Vertrouwelijke informatie
Vertrouwelijk is alle informatie die een partij in het kader van de samenwerking[[ in het project {{project.title}}]] aan de andere partij verstrekt en die als vertrouwelijk is aangemerkt of herkenbaar vertrouwelijk is.

## 2. Verplichtingen
De partijen gebruiken vertrouwelijke informatie alleen voor het project, geven haar niet door aan derden en beschermen haar met redelijke zorg.

## 3. Uitzonderingen
De verplichtingen gelden niet voor informatie die openbaar is, die een partij al rechtmatig kende of die zij wettelijk moet bekendmaken.

## 4. Duur
Deze overeenkomst geldt vanaf {{today}} en eindigt drie jaar na het einde van de samenwerking."""),
    "letter": ("Begeleidende brief", """# [Onderwerp]

Geachte heer, mevrouw,

[Uw tekst]

Neem gerust contact met ons op als u vragen heeft.

Met vriendelijke groet
{{company.name}}"""),
    "reminder": ("Betalingsherinnering", """# Betalingsherinnering

Geachte heer, mevrouw,

misschien is het aan uw aandacht ontsnapt: wij hebben de betaling van factuur [factuurnummer] van [factuurdatum] ter hoogte van [bedrag] nog niet ontvangen.

Maak het openstaande bedrag uiterlijk [datum] over op de rekening die op de factuur staat. Heeft u inmiddels betaald, dan kunt u deze brief als niet verzonden beschouwen.

Met vriendelijke groet
{{company.name}}"""),
    "dunning": ("Aanmaning", """# Aanmaning

Geachte heer, mevrouw,

ondanks onze betalingsherinnering van [datum van de herinnering] staat factuur [factuurnummer] van [factuurdatum] ter hoogte van [bedrag] nog open.

Voldoe het openstaande bedrag uiterlijk [termijn]. Na afloop van deze termijn behouden wij ons verdere stappen voor.

Heeft u inmiddels betaald, dan kunt u deze brief als niet verzonden beschouwen.

Met vriendelijke groet
{{company.name}}"""),
    "termination": ("Opzegging", """# Opzegging van de overeenkomst [overeenkomst / overeenkomstnummer]

Geachte heer, mevrouw,

hierbij zeggen wij de bovengenoemde overeenkomst met inachtneming van de opzegtermijn op per [datum], subsidiair per de eerstvolgende mogelijke datum.

Bevestig ons schriftelijk de ontvangst van deze opzegging en de einddatum van de overeenkomst.

Met vriendelijke groet
{{company.name}}

{{today}}"""),
    "authority": ("Volmacht", """# Volmacht

{{client.name}}
{{client.address}}

machtigt hierbij

{{company.name}}
{{company.address}}

om in het project {{project.title}} namens de volmachtgever de volgende handelingen te verrichten:

- [handeling 1]
- [handeling 2]

Deze volmacht geldt van {{today}} tot [datum] en kan op elk moment worden ingetrokken. Ondervolmacht is [niet] toegestaan."""),
    "handover": ("Overdrachtsprotocol", """# Overdrachtsprotocol

Project: {{project.title}}
Overdracht van {{company.name}} aan {{client.name}}
Contactpersoon: {{client.contact}}
Datum: {{today}}

## Overgedragen
- [voorwerp / levering 1]
- [voorwerp / levering 2]

## Staat en opmerkingen
[staat, ontbrekende delen, open punten]

## Bevestiging
De opdrachtgever bevestigt de ontvangst van de bovengenoemde prestaties in de beschreven staat."""),
    "credit": ("Begeleidende brief bij creditnota", """# Uw creditnota [creditnotanummer]

Geachte heer, mevrouw,

bijgaand ontvangt u onze creditnota [creditnotanummer] van {{today}} ter hoogte van [bedrag] voor factuur [factuurnummer] in het project {{project.title}}.

Wij [maken het bedrag vóór de datum over op uw rekening / verrekenen het bedrag met de volgende factuur].

Met vriendelijke groet
{{company.name}}"""),
    "privacy_dpa": ("Verwerkersovereenkomst", """# Verwerkersovereenkomst

[Voorbeeldtekst, geen juridisch advies. Machinaal vertaald, vóór gebruik controleren: pas de tekst aan de opdracht aan en verwijder deze regel.]

Tussen {{client.name}}, {{client.address}} (verwerkingsverantwoordelijke)
en {{company.name}}, {{company.address}} (verwerker)

## 1. Onderwerp en duur
De verwerker verwerkt persoonsgegevens namens de verwerkingsverantwoordelijke voor de volgende diensten: [diensten]. De duur volgt de looptijd van de onderliggende opdracht.

## 2. Aard en doel van de verwerking
[aard en doel, bijv. opslag, onderhoud, analyse]

## 3. Soorten gegevens en betrokkenen
- Soorten persoonsgegevens: [bijv. contactgegevens, contractgegevens]
- Categorieën betrokkenen: [bijv. klanten, werknemers]

## 4. Instructies
De verwerker verwerkt de gegevens uitsluitend op gedocumenteerde instructie van de verwerkingsverantwoordelijke (art. 28 lid 3 onder a AVG).

## 5. Vertrouwelijkheid
De personen die de gegevens mogen verwerken, zijn tot vertrouwelijkheid verplicht (art. 28 lid 3 onder b AVG).

## 6. Beveiliging van de verwerking
De verwerker treft de technische en organisatorische maatregelen van art. 32 AVG: [maatregelen of bijlage].

## 7. Subverwerkers
Andere verwerkers worden alleen ingeschakeld met voorafgaande toestemming van de verwerkingsverantwoordelijke (art. 28 lid 2 en 4 AVG). Momenteel: [geen / lijst].

## 8. Bijstand
De verwerker staat de verwerkingsverantwoordelijke bij met verzoeken van betrokkenen en met de verplichtingen van art. 32 tot en met 36 AVG (art. 28 lid 3 onder e en f AVG).

## 9. Wissing en teruggave
Na afloop van de diensten worden de gegevens naar keuze van de verwerkingsverantwoordelijke gewist of teruggegeven, tenzij bewaring wettelijk verplicht is (art. 28 lid 3 onder g AVG).

## 10. Bewijs en audits
De verwerker stelt de informatie beschikbaar die nodig is om naleving aan te tonen en maakt audits mogelijk (art. 28 lid 3 onder h AVG).

## 11. Melding van inbreuken
De verwerker meldt een inbreuk in verband met persoonsgegevens zonder onredelijke vertraging nadat hij daarvan kennis heeft genomen (art. 33 lid 2 AVG).

Datum: {{today}}"""),
    "privacy_info": ("Privacyverklaring", """# Privacyverklaring

[Voorbeeldtekst, geen juridisch advies. Machinaal vertaald, vóór gebruik controleren: vul de tekst aan en verwijder deze regel.]

Informatie op grond van art. 13 en 14 AVG voor {{client.name}}

## 1. Verwerkingsverantwoordelijke
{{company.name}}, {{company.address}}

## 2. Doeleinden en rechtsgronden
Wij verwerken uw gegevens om een overeenkomst met u voor te bereiden en uit te voeren (art. 6 lid 1 onder b AVG), om te voldoen aan wettelijke verplichtingen zoals bewaarplichten (art. 6 lid 1 onder c AVG) en voor zover u toestemming heeft gegeven (art. 6 lid 1 onder a AVG).

## 3. Categorieën gegevens
[bijv. naam, adres, contactgegevens, contract- en factuurgegevens]

## 4. Ontvangers
[bijv. belastingadviseur, hostingprovider als verwerker]

## 5. Doorgifte aan derde landen
[geen / details]

## 6. Bewaartermijn
Wij bewaren uw gegevens zolang dat voor deze doeleinden nodig is en daarna voor zover wettelijke bewaartermijnen gelden: [termijnen].

## 7. Uw rechten
- Inzage, rectificatie, wissing en beperking van de verwerking (art. 15 tot en met 18 AVG)
- Overdraagbaarheid van gegevens (art. 20 AVG) en bezwaar (art. 21 AVG)
- Intrekking van een toestemming op elk moment met werking voor de toekomst (art. 7 lid 3 AVG)
- Klacht bij een toezichthoudende autoriteit voor gegevensbescherming (art. 77 AVG)

## 8. Verstrekking van gegevens
De gegevens die voor de overeenkomst nodig zijn, hebben wij nodig om de overeenkomst te sluiten en uit te voeren. [functionaris voor gegevensbescherming, indien aangesteld]

Stand van zaken: {{today}}"""),
    "privacy_consent": ("Toestemming voor gegevensverwerking", """# Toestemming voor gegevensverwerking

[Voorbeeldtekst, geen juridisch advies. Machinaal vertaald, vóór gebruik controleren: pas de tekst aan en verwijder deze regel.]

{{client.name}}, vertegenwoordigd door {{client.contact}}, geeft toestemming dat {{company.name}} de volgende persoonsgegevens verwerkt:

- Gegevens: [gegevens]
- Doel: [doel]

## Vrijwilligheid en intrekking
De toestemming is vrijwillig. Zij kan op elk moment zonder opgaaf van redenen worden ingetrokken met werking voor de toekomst (art. 7 lid 3 AVG), bijvoorbeeld per e-mail aan [e-mailadres]. De intrekking laat de rechtmatigheid van de verwerking daarvóór onverlet.

Meer informatie staat in onze privacyverklaring.

Datum: {{today}}"""),
}

BLOCKS = {
    "cancel": ("Opzegging", "hierbij zeg ik de bovengenoemde overeenkomst met inachtneming van de opzegtermijn op per de eerstvolgende mogelijke datum. "
                            "Bevestig mij schriftelijk de opzegging en de datum waarop zij ingaat."),
    "objection": ("Bezwaar", "hierbij maak ik bezwaar tegen uw besluit van [datum], kenmerk [kenmerk]. De gronden dien ik afzonderlijk in. "
                             "Bevestig mij de ontvangst van deze brief."),
    "reminder": ("Betalingsherinnering", "misschien is het aan uw aandacht ontsnapt: het bedrag van [bedrag] van onze factuur [nummer] van [datum] staat nog open. "
                                         "Maak het uiterlijk [datum] over. Heeft u al betaald, dan kunt u deze brief als niet verzonden beschouwen."),
    "extension": ("Verzoek om uitstel", "ik verzoek u de termijn van [datum] te verlengen tot [datum], omdat mij nog documenten ontbreken. "
                                        "Bij voorbaat dank voor uw begrip."),
}
