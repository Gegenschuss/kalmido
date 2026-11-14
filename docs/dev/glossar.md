# Hauswörter (deutsche Oberfläche)

Ein Wort hat genau eine Bedeutung, eine Sache genau einen Namen. Gilt für Listen/Projekte (#5441),
Kalender (#5467), Büro (#5454) und Wissen (#6091). Neue Texte halten sich daran; abweichende Alt-Texte werden beim
Anfassen angeglichen. Geändert wird die Übersetzung in `static/i18n/de.json`; ein Schlüssel mit zwei
Bedeutungen bekommt einen Kontext (`Event|calendar`, `People|event`).

| Sache | Hauswort | Nicht verwenden |
|---|---|---|
| Eintrag im Kalender | Termin | Ereignis, Event |
| Ereignis in Benachrichtigungen/Agenten | Ereignis | (dort richtig, kein Termin) |
| Von außen eingebundener Kalender (ICS) | Abonnierter Kalender | Abo, Kalender-Abo, Kalender-Abonnement |
| Eigener Export-Link des Kalenders | Kalender-Link | Kalender-Abo, Öffentlicher Kalender-Link |
| Rolle lesend / schreibend (Kalender, in Sätzen) | kann ansehen / kann bearbeiten | Nur lesen |
| Rolle lesend in Projekten/Organisationen (Auswahl neben Admin/Mitglied) | Nur ansehen | Nur lesen, Betrachter |
| Zustand ohne Schreibrecht | nur ansehen | nur lesen |
| Frei/Belegt | belegt | beschäftigt |
| Eigene Wiederholung | Eigene… | Benutzerdefiniert |
| Zusage zu einem Termin | Zusagen / Vielleicht / Ablehnen; Status Zugesagt | Annehmen |
| Teilnehmende am Termin | Gästeliste | Personen |
| Gruppe der Seitenleiste für Projekte | Projekte | Listen |
| Aufgabe ohne Abschnitt | Ohne Abschnitt | Nicht zugeordnet |
| Aufgabe ohne Zuständige | Ohne Zuständige | Nicht zugeordnet |
| Aufgabe selbst nehmen | Selbst übernehmen | Übernehmen |
| Vorschlag/Einstellung anwenden | Übernehmen | |
| Board-Zeilen | Gruppieren nach | Zeilen, Swimlanes |
| Block der Projektseite mit Durchlauf-/Zykluszeit | Durchlauf | Fluss, Flow |
| Teil „Projekt bearbeiten“ mit Projekttyp, Tickets, Sprints, Feldern | Was das Projekt kann | Projekt-Funktionen |
| Teil „Projekt bearbeiten“ mit Formularen, Software, Webhooks, Regeln | Formulare, Regeln & Anbindungen | Formulare & Software |
| Eigenschaften ohne eigene Abweichung | Wie vom Projekttyp vorgegeben | Wie der Projekttyp |
| Entfernen mit Rückgängig | Löschen (Papierkorb: „In den Papierkorb“) | Entfernen, Gelöscht/Archiviert für dasselbe |
| Neues Element | Hinzufügen (in Listen mit Feld: „hinzufügen“, mit Knopf: „anlegen“ nur für Konten/Projekte) | übernehmen |
| Bereich mit den Seiten (Seitenleiste, Titel, Pfad) | Wissen | Wissensseiten, Wiki |
| Eine Seite darin | Seite (quer über Bereiche: Seite unter Wissen) | Wissensseite |
| Privat / Organisation unter Wissen | Arbeitsbereich | Bereich, Wissensbereich |
| Alle Seiten eines Arbeitsbereichs für einen Agenten | alle Seiten (teilen) | gesamter Wissensbereich |
| Gespeicherter Stand einer Seite, Konfliktseite | Version | Fassung |
| Stichwort einer Seite (#…) | Schlagwort | Tag |
| Nur dieses Gerät bearbeitet nicht | Bearbeiten sperren (dieses Gerät) | Nur ansehen (das ist die Rolle) |
| Darstellung der Seiten | Lesestil, Stil „Schlicht“ | Lese-Stil, Klar |
| Im Browser verschlüsselter Arbeitsbereich | verschlüsselt (im Browser) | Ende-zu-Ende, gesperrt |
| Markdown-Feld / ZIP-Export | Als reinen Text bearbeiten / Alle Seiten herunterladen, aus einem Archiv importieren | Markdown, ZIP |

Fachwörter (Kanban, Swimlanes, WIP, Backlog) stehen nur dort, wo die Funktion eingeschaltet ist: die Ansicht
„Kanban“ erscheint nur mit dem Modul Kanban, WIP-Grenzen nur an Spalten mit Grenze, Backlog nur mit Sprints und als Abschnitt im Software-Projekt.
„Mindmap“ und „Zeitstrahl“ gelten als Alltagswörter (#5481).
Technikwörter (ICS, iCal, CalDAV, Basis-URL, „Erlaubte interne Hosts“, IANA-Zonen) nur in den
Einstellungen für Fortgeschrittene.

Rollen (#5481, 2.831): die Leserolle in Projekten und Organisationen heißt „Nur ansehen“, im Kalender in Sätzen
„kann ansehen“; „Nur lesen“ gibt es in der deutschen Oberfläche der Listen nicht mehr.
