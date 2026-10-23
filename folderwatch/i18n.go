// 2.207.0 B (#2763): the page texts, German and English (the system language picks; anything else = English).
package main

import (
	"fmt"
	"os"
	"strings"
)

func envLang() string {
	for _, k := range []string{"LC_ALL", "LC_MESSAGES", "LANG"} {
		if v := os.Getenv(k); v != "" {
			return v
		}
	}
	return ""
}

// pickLang: "de" for a German system language, else "en". KALMIDO_LANG overrides.
func pickLang(sys string) string {
	if v := os.Getenv("KALMIDO_LANG"); v != "" {
		sys = v
	}
	if strings.HasPrefix(strings.ToLower(strings.TrimSpace(sys)), "de") {
		return "de"
	}
	return "en"
}

var texts = map[string][2]string{ // key -> {de, en}
	"app":             {"Kalmido Ordner-Wächter", "Kalmido Folder watcher"},
	"st_ready":        {"Bereit", "Ready"},
	"st_offline":      {"Wartet auf Netz", "Waiting for the network"},
	"st_blocked":      {"Wartet - Kalmido lehnt gerade ab", "Waiting - Kalmido refuses for now"},
	"st_paused":       {"Angehalten", "Paused"},
	"st_nodir":        {"Ordner nicht gefunden", "Folder not found"},
	"paused_hint":     {"Schlüssel ungültig oder widerrufen - neuen Code in Kalmido erzeugen.", "Key invalid or revoked - create a new code in Kalmido."},
	"next_try":        {"Nächster Versuch um %s.", "Next try at %s."},
	"folder":          {"Ordner", "Folder"},
	"target":          {"Ziel", "Target"},
	"inbox":           {"Eingang", "Inbox"},
	"waiting":         {"Wartende Dateien", "Waiting files"},
	"none_waiting":    {"Keine wartenden Dateien.", "No waiting files."},
	"recent":          {"Letzte Vorgänge", "Recent activity"},
	"none_recent":     {"Noch nichts hochgeladen.", "Nothing uploaded yet."},
	"ev_ok":           {"hochgeladen", "uploaded"},
	"ev_rejected":     {"nicht angenommen, liegt in „%s“: %s", "not accepted, moved to \"%s\": %s"},
	"ev_err":          {"nicht hochgeladen: %s", "not uploaded: %s"},
	"too_big":         {"zu groß (höchstens %d MB), bleibt liegen", "too large (at most %d MB), left in place"},
	"btn_open":        {"Ordner öffnen", "Open folder"},
	"btn_retry":       {"Jetzt erneut versuchen", "Retry now"},
	"btn_remove":      {"Eingang entfernen", "Remove inbox"},
	"btn_add":         {"Eingang hinzufügen", "Add inbox"},
	"btn_quit":        {"Beenden", "Quit"},
	"btn_cancel":      {"Abbrechen", "Cancel"},
	"btn_check":       {"Prüfen", "Check"},
	"btn_save":        {"Einrichten", "Set up"},
	"btn_as_on":       {"Autostart einschalten", "Turn on autostart"},
	"btn_as_take":     {"Diese Version im Hintergrund weiterlaufen lassen", "Keep this version running in the background"},
	"btn_as_off":      {"Autostart ausschalten", "Turn off autostart"},
	"btn_uninstall":   {"Deinstallieren", "Uninstall"},
	"run_bg":          {"Läuft im Hintergrund. Erneuter Doppelklick öffnet diese Seite.", "Runs in the background. Double-click the program again to open this page."},
	"run_fg":          {"Läuft, solange dieses Programm geöffnet ist. Mit Autostart läuft es nach jedem Anmelden im Hintergrund.", "Runs while this program is open. With autostart it runs in the background after every login."},
	"autostart":       {"Mit dem Rechner starten", "Start with the computer"},
	"add_title":       {"Eingang einrichten", "Set up an inbox"},
	"add_intro":       {"In Kalmido unter Einstellungen > Dokumente > Ordner-Wächter einen Eingang anlegen und den Einrichtungscode hier einfügen. Jeder Eingang hat einen eigenen Ordner, z. B. je Scanner-Profil.", "In Kalmido, create an inbox under Settings > Documents > Folder watcher and paste its setup code here. Every inbox has its own folder, e.g. one per scanner profile."},
	"code":            {"Einrichtungscode", "Setup code"},
	"err_code":        {"Das ist kein gültiger Einrichtungscode.", "This is not a valid setup code."},
	"err_insecure":    {"Die Server-Adresse muss mit https:// beginnen.", "The server address must start with https://."},
	"err_net":         {"Kalmido ist gerade nicht erreichbar: %s", "Kalmido cannot be reached right now: %s"},
	"err_refused":     {"Kalmido lehnt ab: %s", "Kalmido refuses: %s"},
	"err_dup":         {"Dieser Eingang ist schon eingerichtet.", "This inbox is set up already."},
	"err_folder":      {"Der Ordner lässt sich nicht anlegen: %s", "The folder cannot be created: %s"},
	"err_folder_use":  {"Diesen Ordner beobachtet schon ein anderer Eingang.", "Another inbox watches this folder already."},
	"err_folder_rel":  {"Bitte einen vollständigen Pfad zu einem eigenen Ordner angeben (nicht der Benutzerordner selbst).", "Please enter a full path to a folder of its own (not your home folder itself)."},
	"folder_here":     {"Ordner auf diesem Rechner", "Folder on this computer"},
	"folder_hint":     {"Wird angelegt, falls nötig. Das Scanner-Profil (z. B. ScanSnap) so einstellen, dass es in diesen Ordner speichert. Hochgeladene Dateien wandern in den Unterordner „%s“.", "Created when needed. Point your scanner profile (e.g. ScanSnap) at this folder. Uploaded files move into the subfolder \"%s\"."},
	"folder_hint_mac": {"Bewusst nicht unter Dokumente oder Schreibtisch: dort fragt macOS zuerst nach einer Erlaubnis.", "Deliberately not inside Documents or Desktop: macOS asks for a permission there first."},
	"as_check":        {"Mit dem Rechner starten (empfohlen)", "Start with the computer (recommended)"},
	"n_saved":         {"Eingerichtet. Neue Dateien im Ordner landen in Kalmido.", "Set up. New files in the folder go to Kalmido."},
	"n_removed":       {"Eingang entfernt. Die Dateien im Ordner sind noch da.", "Inbox removed. The files in the folder are still there."},
	"n_retry":         {"Wird erneut versucht.", "Retrying."},
	"n_as_off":        {"Autostart ist aus.", "Autostart is off."},
	"n_err":           {"Das ging nicht: %s", "That did not work: %s"},
	"handover":        {"Läuft gleich im Hintergrund weiter. Diese Seite lädt sich neu.", "Continues in the background in a moment. This page reloads."},
	"remove_q":        {"Eingang „%s“ entfernen? Die Dateien im Ordner bleiben liegen. Den Schlüssel in Kalmido widerrufen: Einstellungen > Dokumente.", "Remove the inbox \"%s\"? The files in the folder stay. Revoke its key in Kalmido: Settings > Documents."},
	"uninstall_q":     {"Ordner-Wächter deinstallieren? Autostart, Einstellungen und Schlüssel werden von diesem Rechner entfernt; die Ordner mit deinen Dateien bleiben. Die Schlüssel in Kalmido widerrufen: Einstellungen > Dokumente.", "Uninstall the folder watcher? Autostart, settings and keys are removed from this computer; the folders with your files stay. Revoke the keys in Kalmido: Settings > Documents."},
	"quit_done":       {"Beendet. Dieses Fenster kann geschlossen werden.", "Stopped. You can close this window."},
	"uninstall_done":  {"Deinstalliert. Dieses Fenster kann geschlossen werden.", "Uninstalled. You can close this window."},
	"version":         {"Version %s", "Version %s"},
	"settings_at":     {"Einstellungen und Protokoll: %s", "Settings and log: %s"},
	"dir_uploaded":    {"Hochgeladen", "Uploaded"},
	"dir_rejected":    {"Nicht hochgeladen", "Not uploaded"},
	"con_running":     {"Kalmido Ordner-Wächter läuft. Einrichtung und Status: %s", "Kalmido Folder watcher is running. Setup and status: %s"},
	"con_handover":    {"Läuft jetzt im Hintergrund weiter. Dieses Fenster kann geschlossen werden.", "Now runs on in the background. You can close this window."},
	"con_stopped":     {"Beendet.", "Stopped."},
	"scans":           {"Kalmido Scans", "Kalmido Scans"},
}

// T returns the text for key in lang, formatted with args when given.
func T(lang, key string, args ...any) string {
	t, ok := texts[key]
	if !ok {
		return key
	}
	s := t[1]
	if lang == "de" {
		s = t[0]
	}
	if len(args) > 0 {
		return fmt.Sprintf(s, args...)
	}
	return s
}
