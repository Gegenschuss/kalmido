<!-- Kalmido help, German (2.1086.0, #5820). One block per "How to" section of docs/*.md: the key and the fingerprint (src)
of the English text it was translated from. **Bold** = the label exactly as the German interface shows it.
Check: python3 tools/check_userhelp.py (prints the current src of a changed English section). -->

<!-- help: files#how-to-set-up-a-scan-inbox src=b33c638618 -->
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

<!-- help: files#how-to-add-documents-and-find-them-again src=4520b96808 -->
## Dokumente hinzufügen und wiederfinden

1. Öffne **Dateien** > **Dokumente**.
2. Tippe auf **Dokumente hinzufügen** und wähle PDFs oder Fotos aus - oder zieh sie einfach auf die Seite. Am Handy
   fotografiert **Scannen** einen Brief ab.
3. Gib ein Wort in **In den Dokumenten suchen…** ein - die Suche findet auch Wörter im Brief selbst.

Was dann passiert: Kalmido liest jedes Dokument und trägt Datum, Betrag und Absender ein. Wo es sich nicht sicher ist, wartet
das Dokument unter **Zu prüfen**: öffne es, korrigiere, was nicht stimmt, und tippe auf **Geprüft**
(oder **Alle übernehmen** für die Vorschläge).

<!-- help: files#how-to-share-a-folder src=f6f99fa88e -->
## Einen Ordner teilen

1. Öffne **Dateien** und das Menü **Mehr** (⋯) des Ordners, dann **Teilen…**.
2. Wähle bei **Teilen mit…** eine Person, eine Gruppe oder einen Agenten.
3. Wähle **Darf ansehen** oder **Darf bearbeiten**, tippe auf **Hinzufügen** und dann auf **Fertig**.

Was dann passiert: Die Person sieht den Ordner mit allem, was darin liegt - auch mit dem, was später dazukommt. Am Ordner
steht, mit wem er geteilt ist. Teilen kann nur, wem der Ordner gehört.

<!-- help: agent-setup#how-to-create-your-personal-agent src=55f8406267 -->
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

<!-- help: agent-setup#how-to-give-an-agent-access-to-a-project-or-folder src=aaf357fa82 -->
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

<!-- help: agent-setup#how-to-approve-what-an-agent-asks-for src=dfbe19a2e9 -->
## Freigeben, worum ein Agent bittet

1. Braucht ein Agent dein Ja, erscheint eine Karte „… wartet auf dich“ (in Heute und im Bereich Agenten).
2. Tippe auf **Freigeben** oder **Ablehnen**. Bei einem Vorschlag erst auf **Vorschlag prüfen** und die Änderungen ansehen.

Was dann passiert: Der Agent macht mit dem weiter, was du freigegeben hast; ein abgelehnter Schritt passiert nicht.

<!-- help: office#how-to-write-a-quotation src=c3eae76ef0 -->
## Ein Angebot schreiben

1. Öffne **Büro** > **Angebote** und tippe auf **Neues Angebot**. Der Entwurf öffnet sich sofort.
2. Wähle im Feld **Kunde** den Kunden.
3. Füge mit **Leistung hinzufügen** Zeilen hinzu - aus deiner Liste der Leistungen oder als freie Zeile.
4. Ist alles fertig, tippe auf **Festschreiben**. Danach ändern sich Nummer, Zeilen und Beträge nicht mehr.
5. Tippe auf **Senden**, um es per E-Mail zu schicken, oder auf **PDF herunterladen**.

Was dann passiert: Das Angebot steht in der Liste. Markiere es als versendet und später als **Angenommen** oder abgelehnt -
aus einem angenommenen Angebot wird mit einem Schritt die Rechnung. Einen Entwurf siehst du dir mit **Vorschau** an (mit
dem Vermerk ENTWURF).

<!-- help: office#how-to-turn-a-quotation-into-an-invoice src=faeae491ab -->
## Aus einem Angebot eine Rechnung machen

1. Öffne das angenommene Angebot und tippe auf **Rechnung erstellen**.
2. Wähle die **Rechnungsart** (ganze Rechnung, Abschlags- oder Schlussrechnung) und bestätige.
3. Prüfe die Rechnung, tippe auf **Festschreiben** und dann auf **Senden**.

Eine Rechnung ohne Angebot: **Büro** > **Rechnungen** > **Neue Rechnung**, dann eine leere Rechnung, eine aus Zeiteinträgen
oder eine aus einem Angebot.

Was dann passiert: Die Rechnung bekommt ihre Nummer beim Festschreiben - lückenlos. Sie bleibt offen, bis eine Zahlung
erfasst ist.

<!-- help: office#how-to-record-a-payment src=6663fe7a8c -->
## Eine Zahlung erfassen

1. Öffne die festgeschriebene Rechnung und tippe auf **Zahlung erfassen**.
2. Prüfe Datum und Betrag und tippe auf **Erfassen**.

Oder der Kontoauszug erledigt das: **Büro** > **Bank** > **Kontoauszug importieren**, dann den Vorschlag, der zur Rechnung
passt, mit **Übernehmen** bestätigen.

Was dann passiert: Die Rechnung gilt als bezahlt (oder als teilweise bezahlt, mit dem offenen Rest). Zahlungen erfasst nur
ein Admin der Organisation.

<!-- help: tasks#how-to-add-a-task-with-a-date src=8a3685b666 -->
## Eine Aufgabe mit Datum anlegen

1. Tippe unten im Projekt in **Aufgabe hinzufügen…** (am Handy: auf den Plus-Knopf).
2. Schreib die Aufgabe so, wie du denkst, zum Beispiel „Zahnarzt anrufen morgen 15 Uhr“. Wörter wie heute und morgen werden
   zum Datum; oder wähle es über das Datumsfeld.
3. Drück die Eingabetaste.

Was dann passiert: Die Aufgabe landet im offenen Projekt (oder im **Eingang**) mit ihrem Datum und erscheint an diesem Tag in
**Heute**. Um das Datum später zu ändern, öffne die Aufgabe und tippe auf ihr Datum: **Heute**, **Morgen**,
**Nächste Woche** oder ein Tag im Kalender.

<!-- help: tasks#how-to-make-a-task-repeat src=b22f5f0a3c -->
## Eine Aufgabe wiederholen lassen

Eine wiederkehrende Aufgabe kommt von selbst wieder - jeden Tag, jede Woche oder nach deiner eigenen Regel.

1. Öffne die Aufgabe und tippe auf ihr Datum.
2. Wähle unter **Wiederholung** zum Beispiel **Täglich**, wöchentlich oder monatlich - oder **Eigene…** für eine eigene Regel.
3. Tippe auf **Fertig**.

Was dann passiert: Hakst du die Aufgabe ab, erscheint die nächste mit dem nächsten Datum. Du kannst es auch gleich mit
eintippen, zum Beispiel „Blumen gießen jeden Montag“.

<!-- help: tasks#how-to-assign-a-task-or-share-a-project src=d8a87df384 -->
## Eine Aufgabe zuweisen oder ein Projekt teilen

1. Projekt teilen: Öffne sein Menü (⋯) > **Teilen…**, wähle die Person bei **Teilen mit…**, eine Rolle (zum Beispiel
   **Mitglied**) und tippe auf **Hinzufügen**.
2. Aufgabe zuweisen: Öffne die Aufgabe, tippe auf **Zuweisen** und wähle die Person.

Was dann passiert: Die Person sieht das Projekt und bekommt die Aufgabe in ihre eigene Liste. Zuweisen kann man nur Personen,
die im Projekt sind.

<!-- help: calendar#how-to-create-an-event src=5f4ebe03b3 -->
## Einen Termin anlegen

1. Öffne **Kalender** und tippe auf **Termin** (am Handy: auf den Plus-Knopf). Oder zieh in der Wochen- oder Tagesansicht
   über eine freie Zeit.
2. Fülle **Titel**, **Beginn** und **Ende** aus und, wenn nötig, **Wiederholung** und Erinnerungen.
3. Tippe auf **Speichern**.

Was dann passiert: Der Termin steht im Kalender und auf deinem Handy, wenn es verbunden ist (siehe „Kalmido auf dem Handy
zeigen“).

<!-- help: calendar#how-to-subscribe-to-another-calendar src=9f0cf2e56c -->
## Einen anderen Kalender abonnieren

1. Öffne **Kalender** > **Kalender** > **Abonnierte Kalender…** (oder **Einstellungen** > **Integrationen** > **Kalender**).
2. Tippe auf **Kalender hinzufügen**.
3. Füge den Link des Kalenders ein (Google, iCloud und Outlook bieten einen an) und tippe auf **Hinzufügen**. Für ein
   Kalenderkonto wähle stattdessen **CalDAV-Konto** und **Kalender suchen**.

Was dann passiert: Seine Termine erscheinen in deinem Kalender und in Heute - nur zum Ansehen und nur für dich sichtbar;
Kalmido holt sie regelmäßig neu.

<!-- help: calendar#how-to-show-kalmido-on-your-phone src=73923b0417 -->
## Kalmido auf dem Handy zeigen

1. Öffne **Kalender** > **Kalender** > **Auf dem Handy…** (oder **Einstellungen** > **Integrationen** > **Kalender-Apps (CalDAV)**).
2. Tippe auf **Neues App-Passwort** und übernimm Serveradresse, Benutzername und Passwort in die Kalender-Einstellungen
   deines Handys.

Was dann passiert: Deine Termine und Aufgaben mit Datum erscheinen im Kalender des Handys, und Änderungen gehen in beide
Richtungen. Nimm dort das App-Passwort, nie dein Kalmido-Passwort.

<!-- help: wiki#how-to-write-a-knowledge-page src=122a76cda7 -->
## Eine Seite unter Wissen schreiben

1. Öffne in der Seitenleiste **Wissen** und tippe auf **Neue Seite**.
2. Gib den Namen der Seite bei **Name** ein. Ein `/` macht Ordner: „Abläufe/Checkliste“ landet im Ordner *Abläufe*.
3. Schreibe den Text. Mit `[[` verlinkst du eine andere Seite.

Was dann passiert: Die Seite speichert von selbst und steht im Baum links. Unter jeder Seite zeigt **Verlinkt von**, welche
Seiten auf sie verweisen.

<!-- help: wiki#how-to-share-a-page-read-only src=f589cec1bf -->
## Eine Seite nur zum Lesen teilen

1. Öffne die Seite, öffne ihr Menü (⋯) und wähle **Teilen…**.
2. Für eine Person: wähle sie unter **Person wählen…** (oder tippe eine E-Mail-Adresse) und tippe auf **Hinzufügen**.
3. Für Leute ohne Konto: wähle **Öffentlichen Link erstellen**, setze nach Wunsch **Gültig bis** und kopiere den Link.

Was dann passiert: Die Person liest diese Seite (oder den ganzen Ordner mit *Ordner teilen…*) und sonst nichts von deinen
Seiten; der Link öffnet eine schlichte Seite ohne Anmeldung. **Ausschalten** beendet einen Link sofort.

<!-- help: wiki#how-to-bring-back-an-earlier-version-of-a-page src=f736215a16 -->
## Eine frühere Version einer Seite zurückholen

1. Öffne die Seite, öffne ihr Menü (⋯) und wähle **Verlauf**.
2. Wähle in der Liste eine Version: Kalmido zeigt, was sich vom aktuellen Text unterscheidet.
3. Tippe auf **Wiederherstellen**.

Was dann passiert: Der alte Text wird als neue Version wieder zum aktuellen, es geht also nichts verloren; das
Zurückholen lässt sich rückgängig machen.

<!-- help: sheets#how-to-make-a-table-with-a-formula src=b8056fbeac -->
## Eine Tabelle mit Formel anlegen

1. Öffne **Tabellen**, tippe auf **Neue Tabelle**, gib einen Namen ein und tippe auf **Erstellen**.
2. Tippe auf **Spalte hinzufügen** und **Zeile hinzufügen**, bis das Raster passt, und trage die Werte in die Zellen ein.
3. Beginne eine Zelle mit `=`, zum Beispiel `=B2*C2` (Stunden mal Satz) oder `=SUMME(C2:C9)`.

Was dann passiert: Die Zelle zeigt das Ergebnis und rechnet neu, wenn sich ein Wert ändert; die Tabelle speichert von selbst.

<!-- help: sheets#how-to-share-one-table src=e19d1eba08 -->
## Eine Tabelle teilen

1. Öffne die Tabelle, öffne ihr Menü und wähle **Teilen…**.
2. Wähle unter **Teilen mit…** eine Person oder einen Agenten, dann **Darf ansehen** oder **Darf bearbeiten** und tippe auf **Hinzufügen**.

Was dann passiert: Die Person sieht nur diese Tabelle, nicht den Rest deines Arbeitsbereichs; sie findet sie unter
**Mit mir geteilt**. **Nicht mehr teilen** beendet das sofort.

<!-- help: team#how-to-write-to-a-colleague-in-the-team-chat src=d14fa10beb -->
## Im Team-Chat jemandem schreiben

1. Öffne **Team-Chat** und tippe auf **Neue Nachricht**.
2. Wähle die Person (oder **Neuer Kanal** für einen Kanal).
3. Tippe die Nachricht und tippe auf **Senden**.

Was dann passiert: Die Person bekommt die Nachricht samt Benachrichtigung; du siehst, wann sie sie gelesen hat. Jedes
Projekt, das du teilst, hat außerdem einen eigenen Chat.

<!-- help: team#how-to-pin-a-message-or-answer-in-a-thread src=d57b9f4728 -->
## Eine Nachricht anheften oder im Thread antworten

1. Öffne das Menü einer Nachricht (am Handy: gedrückt halten).
2. Wähle **Anheften**, damit eine wichtige Nachricht oben im Gespräch sichtbar bleibt, oder **Im Strang antworten**, um zu antworten,
   ohne das Hauptgespräch zu füllen.

Was dann passiert: Angeheftete Nachrichten bleiben in der Leiste über den Nachrichten (höchstens fünf je Gespräch); ein
Thread zeigt die Antworten auf diese eine Nachricht, und seine Beteiligten werden benachrichtigt.

<!-- help: budget#how-to-start-a-household-budget src=1116c1b0a8 -->
## Ein Haushaltsbudget anlegen

1. Öffne **Budget** (im Bereich **Zuhause**, einzuschalten unter *Einstellungen > Module*) und tippe auf **Budget anlegen**.
2. Tippe auf **Neuer Posten**, fülle **Betrag**, das Datum und **Was** aus, wähle eine Kategorie und tippe auf **Speichern**.

Was dann passiert: Der Monat zeigt, was du **Eingegangen** und **Ausgegeben** hast und was **Übrig** ist; die Kategorien zeigen die
Ausgaben gegen den Plan. Jede Änderung lässt sich rückgängig machen.

<!-- help: budget#how-to-add-rent-and-other-recurring-entries src=cd197ab4f2 -->
## Miete und andere wiederkehrende Posten eintragen

1. Öffne im Budget das Menü (⋯), wähle **Wiederkehrende Posten** und dann **Neuer wiederkehrender Posten**.
2. Trage ein, was es ist und den Betrag, wähle bei **Wie oft** monatlich, vierteljährlich oder jährlich und tippe auf **Speichern**.

Was dann passiert: Der Posten erscheint unter **Offen in diesem Monat**, sobald er fällig ist. Kalmido bucht ihn nie von selbst:
tippe auf **Gebucht**, wenn das Geld wirklich abgegangen (oder eingegangen) ist.

<!-- help: budget#how-to-import-a-bank-statement-into-the-budget src=45308584bc -->
## Einen Kontoauszug ins Budget einlesen

Kalmido hat keinen Zugriff auf deine Bank: Du lädst die Datei selbst herunter.

1. Lade bei deiner Bank den CSV- (oder CAMT-)Export deines Kontoauszugs herunter.
2. Öffne im Budget das Menü (⋯), wähle **CSV-Datei importieren** und die Datei unter **Dateien wählen**.
3. Prüfe, welche Spalte Datum, Betrag und Text enthält, und bestätige.

Was dann passiert: Die neuen Buchungen landen im Budget; was schon drin ist, wird nicht doppelt. **Diesen Import rückgängig machen** nimmt
den ganzen Import zurück.

<!-- help: home#how-to-make-a-shopping-list src=c52a018554 -->
## Eine Einkaufsliste anlegen

1. Öffne **Zuhause**; ohne Liste bietet es **Einkaufsliste** an. Tippe darauf.
2. Trage Artikel ein wie eine Aufgabe; „2 l Milch“ und „Milch“ zählen als derselbe Artikel.

Was dann passiert: Die Artikel werden nach Supermarkt-Bereichen sortiert (einmal verschoben, geht der nächste von selbst
dorthin), und alle, mit denen du die Liste teilst, haken beim Einkaufen live ab.

<!-- help: home#how-to-sort-projects-into-folders src=9e6ec9656c -->
## Projekte in Ordner sortieren

1. Öffne in der Seitenleiste das Menü (⋯) eines Projekts und wähle **In Ordner verschieben…**.
2. Wähle einen Ordner oder tippe auf **Neuer Ordner…** und gib ihm einen Namen.

Was dann passiert: Das Projekt steht in der Seitenleiste in diesem Ordner. Du kannst Projekte auch zwischen Ordnern
ziehen und einen ganzen Ordner auf einmal teilen (siehe „Einen Ordner mit Leuten teilen“).

<!-- help: team#how-to-share-a-folder-with-people src=d68cfe0773 -->
## Einen Ordner mit Leuten teilen

1. Öffne in der Seitenleiste das Menü (⋯) eines Ordners und wähle **Ordner teilen…**.
2. Wähle unter **Teilen mit…** eine Person und tippe auf **Hinzufügen**. Für Agenten gibt es im selben Dialog den Teil **Agenten**.

Was dann passiert: Alle Projekte im Ordner sind mit ihr geteilt, auch später hinzugefügte. **Nicht mehr teilen** beendet es
sofort wieder. Ein einzelnes Projekt teilst du genauso über sein eigenes Menü.

<!-- help: team#how-to-give-people-without-an-account-a-public-link src=5c9b76a147 -->
## Leuten ohne Konto einen öffentlichen Link geben

1. Öffne den Dialog **Teilen…** des Projekts oder Ordners und such **Öffentlicher Link**.
2. Setze **Gültig bis**, wenn der Link ablaufen soll, kopiere ihn mit **Link kopieren** und schick ihn weiter.

Was dann passiert: Wer den Link hat, kann das Projekt lesen - ohne Anmeldung, nur lesend, ohne Kommentare, Zuständige oder
Dateien. **Ausschalten** beendet den Link sofort.
