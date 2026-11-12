<!-- Kalmido help, Dutch (2.1072.0, #5820). One block per "How to" section of docs/*.md: the key and the fingerprint (src)
of the English text it was translated from. **Bold** = the label exactly as the interface shows it.
Check: python3 tools/check_userhelp.py. -->

<!-- help: files#how-to-set-up-a-scan-inbox src=64eddd039b -->
## Een scan-inbox instellen

Een scan-inbox stuurt nieuwe scans uit een map op je computer meteen naar je documenten.

1. Open **Instellingen** > **Integraties** en ga naar **Documenten: inboxen**.
2. Download onder **Mapbewaker** het programma voor je computer (Mac of Windows).
3. Open **Nieuwe scan-inbox**, vul een **Naam** in, kies de map bij **In map** en tik op **Inbox maken**.
4. Kalmido toont de **Installatiecode** alleen deze ene keer. Tik op **Kopiëren**, start het programma, plak de code en kies
   de map die bewaakt moet worden.

Daarna: elk nieuw bestand in die map wordt geüpload, gelezen en in je documenten gezet. Je vindt de inbox op dezelfde plek
terug om de map te wijzigen, hem een jaar te verlengen of in te trekken. Alleen jij maakt een scan-inbox, nooit een agent.

<!-- help: files#how-to-add-documents-and-find-them-again src=75bd3485cd -->
## Documenten toevoegen en terugvinden

1. Open **Bestanden** > **Documenten**.
2. Tik op **Documenten toevoegen** en kies pdf's of foto's, of sleep ze op de pagina. Op de telefoon fotografeert
   **Scannen** een brief.
3. Typ een woord in **Zoeken in de documenten…**; de zoekfunctie vindt ook woorden in de brieven.

Daarna: Kalmido leest elk document en vult datum, bedrag en afzender in. Waar het niet zeker van is, wacht in
**Te controleren**: open het, verbeter wat niet klopt en tik op **Gecontroleerd** (of **Alles overnemen** voor de voorstellen).

<!-- help: files#how-to-share-a-folder src=2b0b00ac10 -->
## Een map delen

1. Open **Bestanden** en het menu **Meer** (⋯) van de map, dan **Delen…**.
2. Kies bij **Delen met …** een persoon, een groep of een agent.
3. Kies **Mag bekijken** of **Mag bewerken**, tik op **Toevoegen** en dan op **Klaar**.

Daarna: de persoon ziet de map en alles erin, ook wat later wordt toegevoegd. Alleen de eigenaar kan een map delen.

<!-- help: agent-setup#how-to-create-your-personal-agent src=c5dbd2659a -->
## Je persoonlijke agent aanmaken

Een agent is een assistent (bijvoorbeeld Claude) die met een eigen account in Kalmido werkt en alleen ziet wat je met hem deelt.

1. Open **Instellingen** > **Agents** en het tabblad **Instellen**.
2. Vul onder **Je persoonlijke agents** de **Weergavenaam** en de andere twee velden in en tik op **Agent aanmaken**.
3. Kies in het venster dat opent je **Computer** en de **Projectmap** en tik op **Opdracht maken**.
4. Tik op **Kopiëren**, open de Terminal op die computer, plak de opdracht en druk op Enter. Dan **Klaar**.

Daarna: de agent staat onder **Je persoonlijke agents**. Hij ziet nog niets: geef hem een project of een map. De opdracht werkt
één keer en maar een paar minuten; **Instellen** in de rij van de agent maakt een nieuwe.

<!-- help: agent-setup#how-to-give-an-agent-access-to-a-project-or-folder src=2e7c802506 -->
## Een agent toegang geven tot een project of map

Een project:

1. Open het menu (⋯) van het project en kies **Agent…**.
2. Kies onder **Agents** de agent en bevestig met **Delen**.

Een map in Bestanden of Kennis:

1. Open het menu (⋯) van de map en kies **Delen…**.
2. Kies bij **Delen met …** de agent, **Mag bekijken** of **Mag bewerken**, tik op **Toevoegen** en dan op **Klaar**.

Daarna: de agent werkt in dat project of die map, en alleen daar. Elke toegang van een agent staat in de geschiedenis; een
vergrendelde map wordt nooit met een agent gedeeld.

<!-- help: agent-setup#how-to-approve-what-an-agent-asks-for src=c440cd682e -->
## Goedkeuren wat een agent vraagt

1. Heeft een agent je ja nodig, dan verschijnt een kaart "… wacht op je" (in Vandaag en bij Agents).
2. Tik op **Goedkeuren** of **Afwijzen**. Bij een voorstel eerst **Het voorstel bekijken**.

Daarna: de agent gaat verder met wat je hebt goedgekeurd; een afgewezen stap gebeurt niet.

<!-- help: office#how-to-write-a-quotation src=8abb747cdd -->
## Een offerte schrijven

1. Open **Kantoor** > **Offertes** en tik op **Nieuwe offerte**. Het concept opent meteen.
2. Kies de **Klant**.
3. Voeg regels toe met **Dienst toevoegen**.
4. Is alles klaar, tik dan op **Vastleggen**. Daarna veranderen nummer, regels en bedragen niet meer.
5. Tik op **Versturen** om hem te mailen, of op **PDF downloaden**.

Daarna: de offerte staat in de lijst. Markeer hem als verzonden en later als **Geaccepteerd** of afgewezen; van een
geaccepteerde offerte maak je in één stap de factuur. Een concept bekijk je met **Voorbeeld**.

<!-- help: office#how-to-turn-a-quotation-into-an-invoice src=b1c09e308f -->
## Van een offerte een factuur maken

1. Open de geaccepteerde offerte en tik op **Factuur maken**.
2. Kies de **Soort factuur** en bevestig.
3. Controleer de factuur, tik op **Vastleggen** en dan op **Versturen**.

Een factuur zonder offerte: **Kantoor** > **Facturen** > **Nieuwe factuur**.

Daarna: de factuur krijgt haar nummer bij het vastleggen, zonder gaten. Ze blijft open tot er een betaling is vastgelegd.

<!-- help: office#how-to-record-a-payment src=c83bb01e09 -->
## Een betaling vastleggen

1. Open de vastgelegde factuur en tik op **Betaling vastleggen**.
2. Controleer datum en bedrag en tik op **Vastleggen**.

Of via het afschrift: **Kantoor** > **Bank** > **Bankafschrift importeren** en neem het voorstel over met **Overnemen**.

Daarna: de factuur staat als betaald (of deels betaald). Alleen een beheerder van de organisatie legt betalingen vast.

<!-- help: tasks#how-to-add-a-task-with-a-date src=c89121e185 -->
## Een taak met datum toevoegen

1. Tik onderaan het project in **Taak toevoegen…** (op de telefoon: de +-knop).
2. Schrijf de taak zoals je denkt, bijvoorbeeld "Tandarts bellen morgen 15u", of kies de datum.
3. Druk op Enter.

Daarna: de taak komt in het open project (of in de **Mand**) met haar datum en verschijnt die dag in **Vandaag**. Om de datum
te wijzigen open je de taak en tik je op de datum: **Vandaag**, **Morgen**, **Volgende week** of een dag in de kalender.

<!-- help: tasks#how-to-make-a-task-repeat src=7fb71b25d1 -->
## Een taak laten herhalen

Een terugkerende taak komt vanzelf terug: elke dag, elke week of volgens je eigen regel.

1. Open de taak en tik op de datum.
2. Kies onder **Herhaling** bijvoorbeeld **Dagelijks**, of **Aangepast…** voor een eigen regel.
3. Tik op **Klaar**.

Daarna: als je de taak afvinkt, verschijnt de volgende met de volgende datum.

<!-- help: tasks#how-to-assign-a-task-or-share-a-project src=26bbda819e -->
## Een taak toewijzen of een project delen

1. Project delen: het menu (⋯) > **Delen…**, kies de persoon bij **Delen met …**, een rol (bijvoorbeeld **Lid**) en tik op
   **Toevoegen**.
2. Taak toewijzen: open de taak, tik op **Toewijzen** en kies de persoon.

Daarna: de persoon ziet het project en krijgt de taak. Je kunt alleen mensen uit het project toewijzen.

<!-- help: calendar#how-to-create-an-event src=a00f1c721d -->
## Een afspraak maken

1. Open **Agenda** en tik op **Afspraak** (op de telefoon: de +-knop).
2. Vul **Titel**, **Begint** en **Eindigt** in en zo nodig **Herhaling**.
3. Tik op **Opslaan**.

Daarna: de afspraak staat in de agenda en op je telefoon, als die verbonden is.

<!-- help: calendar#how-to-subscribe-to-another-calendar src=a8d8302f42 -->
## Op een andere agenda abonneren

1. Open **Agenda** > **Agenda's** > **Abonnementen…** (of **Instellingen** > **Integraties** > **Agenda's**).
2. Tik op **Agenda toevoegen**.
3. Plak de link van de agenda en tik op **Toevoegen**. Voor een account kies je **CalDAV-account** en **Agenda's zoeken**.

Daarna: de afspraken verschijnen in je agenda, alleen te lezen en alleen voor jou.

<!-- help: calendar#how-to-show-kalmido-on-your-phone src=e055eae2f6 -->
## Kalmido op je telefoon zien

1. Open **Agenda** > **Agenda's** > **Op de telefoon…** (of **Instellingen** > **Integraties** > **Agenda-apps (CalDAV)**).
2. Tik op **Nieuw app-wachtwoord** en neem server, gebruikersnaam en wachtwoord over in de agenda-instellingen van je telefoon.

Daarna: je afspraken en taken met datum verschijnen in de agenda van de telefoon. Gebruik daar het app-wachtwoord, nooit je
Kalmido-wachtwoord.
