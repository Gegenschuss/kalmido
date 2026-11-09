# Hauswörter (deutsche Oberfläche)

Ein Wort hat genau eine Bedeutung, eine Sache genau einen Namen. Gilt für Listen/Projekte (#5441),
Kalender (#5467) und Büro (#5454). Neue Texte halten sich daran; abweichende Alt-Texte werden beim
Anfassen angeglichen. Geändert wird die Übersetzung in `static/i18n/de.json`; ein Schlüssel mit zwei
Bedeutungen bekommt einen Kontext (`Event|calendar`, `People|event`).

| Sache | Hauswort | Nicht verwenden |
|---|---|---|
| Eintrag im Kalender | Termin | Ereignis, Event |
| Ereignis in Benachrichtigungen/Agenten | Ereignis | (dort richtig, kein Termin) |
| Von außen eingebundener Kalender (ICS) | Abonnierter Kalender | Abo, Kalender-Abo, Kalender-Abonnement |
| Eigener Export-Link des Kalenders | Kalender-Link | Kalender-Abo, Öffentlicher Kalender-Link |
| Rolle lesend / schreibend | kann ansehen / kann bearbeiten | Nur lesen (im Kalender) |
| Zustand ohne Schreibrecht | nur ansehen | nur lesen (im Kalender) |
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
| Entfernen mit Rückgängig | Löschen (Papierkorb: „In den Papierkorb“) | Entfernen, Gelöscht/Archiviert für dasselbe |
| Neues Element | Hinzufügen (in Listen mit Feld: „hinzufügen“, mit Knopf: „anlegen“ nur für Konten/Projekte) | übernehmen |

Fachwörter (Kanban, Swimlanes, WIP, Backlog) stehen nur dort, wo die Funktion eingeschaltet ist.
Technikwörter (ICS, iCal, CalDAV, Basis-URL, „Erlaubte interne Hosts“, IANA-Zonen) nur in den
Einstellungen für Fortgeschrittene.

Offen: Rollen in Projekten/Organisationen heißen noch „Nur lesen“ (Test p2364_c_admin_ui); mit Büro #5454
gemeinsam entscheiden, ob sie auf „kann ansehen“ gehen.
