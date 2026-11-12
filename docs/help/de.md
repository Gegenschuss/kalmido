<!-- Kalmido help, German (2.1072.0, #5820). One block per "How to" section of docs/*.md: the key and the fingerprint (src)
of the English text it was translated from. **Bold** = the label exactly as the German interface shows it.
Check: python3 tools/check_userhelp.py (prints the current src of a changed English section). -->

<!-- help: files#how-to-set-up-a-scan-inbox src=64eddd039b -->
## Scan-Eingang einrichten

Ein Scan-Eingang schickt neue Scans aus einem Ordner auf deinem Computer (oder von deinem Scanner) direkt in deine Dokumente.

1. Öffne **Einstellungen** > **Integrationen** und scrolle zu **Dokumente: Eingänge**.
2. Lade unter **Ordner-Wächter** das Programm für deinen Computer herunter (Mac oder Windows).
3. Öffne **Neuer Scan-Eingang**, gib im Feld **Name** einen Namen ein, wähle den Ordner bei **In Ordner** und tippe auf
   **Scan-Eingang anlegen**.
4. Kalmido zeigt den **Einrichtungscode** nur dieses eine Mal. Tippe auf **Kopieren**, starte das Programm, füge den Code ein
   und wähle den Ordner, der beobachtet werden soll.

Was dann passiert: Jede neue Datei in diesem Ordner wird hochgeladen, gelesen und in deine Dokumente einsortiert; das
Programm legt sie danach in den Unterordner „Uploaded“. Den Eingang findest du an derselben Stelle wieder - dort kannst du
den Ordner ändern, ihn um ein Jahr verlängern oder ihn widerrufen. Einen Scan-Eingang legst nur du an, nie ein Agent.

<!-- help: files#how-to-add-documents-and-find-them-again src=75bd3485cd -->
## Dokumente hinzufügen und wiederfinden

1. Öffne **Dateien** > **Dokumente**.
2. Tippe auf **Dokumente hinzufügen** und wähle PDFs oder Fotos aus - oder zieh sie einfach auf die Seite. Am Handy
   fotografiert **Scannen** einen Brief ab.
3. Gib ein Wort in **In den Dokumenten suchen…** ein - die Suche findet auch Wörter im Brief selbst.

Was dann passiert: Kalmido liest jedes Dokument und trägt Datum, Betrag und Absender ein. Wo es sich nicht sicher ist, wartet
das Dokument unter **Zu prüfen**: öffne es, korrigiere, was nicht stimmt, und tippe auf **Geprüft**
(oder **Alle übernehmen** für die Vorschläge).

<!-- help: files#how-to-share-a-folder src=2b0b00ac10 -->
## Einen Ordner teilen

1. Öffne **Dateien** und das Menü **Mehr** (⋯) des Ordners, dann **Teilen…**.
2. Wähle bei **Teilen mit…** eine Person, eine Gruppe oder einen Agenten.
3. Wähle **Darf ansehen** oder **Darf bearbeiten**, tippe auf **Hinzufügen** und dann auf **Fertig**.

Was dann passiert: Die Person sieht den Ordner mit allem, was darin liegt - auch mit dem, was später dazukommt. Am Ordner
steht, mit wem er geteilt ist. Teilen kann nur, wem der Ordner gehört.

<!-- help: agent-setup#how-to-create-your-personal-agent src=c5dbd2659a -->
## Deinen persönlichen Agenten anlegen

Ein Agent ist ein Assistent (zum Beispiel Claude), der mit einem eigenen Konto in Kalmido arbeitet und nur sieht, was du mit
ihm teilst.

1. Öffne **Einstellungen** > **Agenten** und den Reiter **Einrichten**.
2. Fülle unter **Deine persönlichen Agenten** das Feld **Anzeigename** und die beiden anderen Felder aus und tippe auf
   **Agent anlegen**.
3. Wähle im Fenster, das sich öffnet, deinen **Computer** und den **Projektordner** und tippe auf **Befehl erzeugen**.
4. Tippe auf **Kopieren**, öffne auf diesem Computer das Terminal, füge den Befehl ein und drücke die Eingabetaste. Dann
   **Fertig**.

Was dann passiert: Der Agent steht unter **Deine persönlichen Agenten**. Er sieht noch nichts - gib ihm ein Projekt oder einen
Ordner (siehe „Einem Agenten Zugriff auf ein Projekt oder einen Ordner geben“). Der Befehl gilt nur einmal und nur wenige
Minuten; **Einrichten** in der Zeile des Agenten erzeugt einen neuen.

<!-- help: agent-setup#how-to-give-an-agent-access-to-a-project-or-folder src=2e7c802506 -->
## Einem Agenten Zugriff auf ein Projekt oder einen Ordner geben

Ein Projekt:

1. Öffne das Menü (⋯) des Projekts und wähle **Agent…**.
2. Wähle unter **Agenten** den Agenten und bestätige mit **Teilen**.

Ein Ordner in Dateien oder Wissen:

1. Öffne das Menü (⋯) des Ordners und wähle **Teilen…**.
2. Wähle bei **Teilen mit…** den Agenten, dann **Darf ansehen** oder **Darf bearbeiten**, tippe auf **Hinzufügen** und
   dann auf **Fertig**.

Was dann passiert: Der Agent arbeitet in diesem Projekt oder Ordner - und nur dort. Jeder Zugriff eines Agenten steht im
Verlauf des Ordners; einen gesperrten Ordner kann man nie mit einem Agenten teilen.

<!-- help: agent-setup#how-to-approve-what-an-agent-asks-for src=c440cd682e -->
## Freigeben, worum ein Agent bittet

1. Braucht ein Agent dein Ja, erscheint eine Karte „… wartet auf dich“ (in Heute und im Bereich Agenten).
2. Tippe auf **Freigeben** oder **Ablehnen**. Bei einem Vorschlag erst auf **Vorschlag prüfen** und die Änderungen ansehen.

Was dann passiert: Der Agent macht mit dem weiter, was du freigegeben hast; ein abgelehnter Schritt passiert nicht.

<!-- help: office#how-to-write-a-quotation src=8abb747cdd -->
## Ein Angebot schreiben

1. Öffne **Büro** > **Angebote** und tippe auf **Neues Angebot**. Der Entwurf öffnet sich sofort.
2. Wähle im Feld **Kunde** den Kunden.
3. Füge mit **Leistung hinzufügen** Zeilen hinzu - aus deiner Liste der Leistungen oder als freie Zeile.
4. Ist alles fertig, tippe auf **Festschreiben**. Danach ändern sich Nummer, Zeilen und Beträge nicht mehr.
5. Tippe auf **Senden**, um es per E-Mail zu schicken, oder auf **PDF herunterladen**.

Was dann passiert: Das Angebot steht in der Liste. Markiere es als versendet und später als **Angenommen** oder abgelehnt -
aus einem angenommenen Angebot wird mit einem Schritt die Rechnung. Einen Entwurf siehst du dir mit **Vorschau** an (mit
dem Vermerk ENTWURF).

<!-- help: office#how-to-turn-a-quotation-into-an-invoice src=b1c09e308f -->
## Aus einem Angebot eine Rechnung machen

1. Öffne das angenommene Angebot und tippe auf **Rechnung erstellen**.
2. Wähle die **Rechnungsart** (ganze Rechnung, Abschlags- oder Schlussrechnung) und bestätige.
3. Prüfe die Rechnung, tippe auf **Festschreiben** und dann auf **Senden**.

Eine Rechnung ohne Angebot: **Büro** > **Rechnungen** > **Neue Rechnung**, dann eine leere Rechnung, eine aus Zeiteinträgen
oder eine aus einem Angebot.

Was dann passiert: Die Rechnung bekommt ihre Nummer beim Festschreiben - lückenlos. Sie bleibt offen, bis eine Zahlung
erfasst ist.

<!-- help: office#how-to-record-a-payment src=c83bb01e09 -->
## Eine Zahlung erfassen

1. Öffne die festgeschriebene Rechnung und tippe auf **Zahlung erfassen**.
2. Prüfe Datum und Betrag und tippe auf **Erfassen**.

Oder der Kontoauszug erledigt das: **Büro** > **Bank** > **Kontoauszug importieren**, dann den Vorschlag, der zur Rechnung
passt, mit **Übernehmen** bestätigen.

Was dann passiert: Die Rechnung gilt als bezahlt (oder als teilweise bezahlt, mit dem offenen Rest). Zahlungen erfasst nur
ein Admin der Organisation.

<!-- help: tasks#how-to-add-a-task-with-a-date src=c89121e185 -->
## Eine Aufgabe mit Datum anlegen

1. Tippe unten im Projekt in **Aufgabe hinzufügen…** (am Handy: auf den Plus-Knopf).
2. Schreib die Aufgabe so, wie du denkst, zum Beispiel „Zahnarzt anrufen morgen 15 Uhr“. Wörter wie heute und morgen werden
   zum Datum; oder wähle es über das Datumsfeld.
3. Drück die Eingabetaste.

Was dann passiert: Die Aufgabe landet im offenen Projekt (oder im **Eingang**) mit ihrem Datum und erscheint an diesem Tag in
**Heute**. Um das Datum später zu ändern, öffne die Aufgabe und tippe auf ihr Datum: **Heute**, **Morgen**,
**Nächste Woche** oder ein Tag im Kalender.

<!-- help: tasks#how-to-make-a-task-repeat src=7fb71b25d1 -->
## Eine Aufgabe wiederholen lassen

Eine wiederkehrende Aufgabe kommt von selbst wieder - jeden Tag, jede Woche oder nach deiner eigenen Regel.

1. Öffne die Aufgabe und tippe auf ihr Datum.
2. Wähle unter **Wiederholung** zum Beispiel **Täglich**, wöchentlich oder monatlich - oder **Eigene…** für eine eigene Regel.
3. Tippe auf **Fertig**.

Was dann passiert: Hakst du die Aufgabe ab, erscheint die nächste mit dem nächsten Datum. Du kannst es auch gleich mit
eintippen, zum Beispiel „Blumen gießen jeden Montag“.

<!-- help: tasks#how-to-assign-a-task-or-share-a-project src=26bbda819e -->
## Eine Aufgabe zuweisen oder ein Projekt teilen

1. Projekt teilen: Öffne sein Menü (⋯) > **Teilen…**, wähle die Person bei **Teilen mit…**, eine Rolle (zum Beispiel
   **Mitglied**) und tippe auf **Hinzufügen**.
2. Aufgabe zuweisen: Öffne die Aufgabe, tippe auf **Zuweisen** und wähle die Person.

Was dann passiert: Die Person sieht das Projekt und bekommt die Aufgabe in ihre eigene Liste. Zuweisen kann man nur Personen,
die im Projekt sind.

<!-- help: calendar#how-to-create-an-event src=a00f1c721d -->
## Einen Termin anlegen

1. Öffne **Kalender** und tippe auf **Termin** (am Handy: auf den Plus-Knopf). Oder zieh in der Wochen- oder Tagesansicht
   über eine freie Zeit.
2. Fülle **Titel**, **Beginn** und **Ende** aus und, wenn nötig, **Wiederholung** und Erinnerungen.
3. Tippe auf **Speichern**.

Was dann passiert: Der Termin steht im Kalender und auf deinem Handy, wenn es verbunden ist (siehe „Kalmido auf dem Handy
zeigen“).

<!-- help: calendar#how-to-subscribe-to-another-calendar src=a8d8302f42 -->
## Einen anderen Kalender abonnieren

1. Öffne **Kalender** > **Kalender** > **Abonnierte Kalender…** (oder **Einstellungen** > **Integrationen** > **Kalender**).
2. Tippe auf **Kalender hinzufügen**.
3. Füge den Link des Kalenders ein (Google, iCloud und Outlook bieten einen an) und tippe auf **Hinzufügen**. Für ein
   Kalenderkonto wähle stattdessen **CalDAV-Konto** und **Kalender suchen**.

Was dann passiert: Seine Termine erscheinen in deinem Kalender und in Heute - nur zum Ansehen und nur für dich sichtbar;
Kalmido holt sie regelmäßig neu.

<!-- help: calendar#how-to-show-kalmido-on-your-phone src=e055eae2f6 -->
## Kalmido auf dem Handy zeigen

1. Öffne **Kalender** > **Kalender** > **Auf dem Handy…** (oder **Einstellungen** > **Integrationen** > **Kalender-Apps (CalDAV)**).
2. Tippe auf **Neues App-Passwort** und übernimm Serveradresse, Benutzername und Passwort in die Kalender-Einstellungen
   deines Handys.

Was dann passiert: Deine Termine und Aufgaben mit Datum erscheinen im Kalender des Handys, und Änderungen gehen in beide
Richtungen. Nimm dort das App-Passwort, nie dein Kalmido-Passwort.
