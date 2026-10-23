// 2.207.0 B (#2763): macOS - "open", the system language from AppleLocale, the LaunchAgent for the autostart.
package main

import (
	"html"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
)

const launchLabel = "com.kalmido.folderwatcher"

func openURL(u string) error    { return exec.Command("open", u).Start() }
func openFolder(p string) error { return exec.Command("open", p).Start() }
func exeName() string           { return "kalmido-folder-watcher" }
func autostartWhere() string    { return "LaunchAgent " + launchLabel }
func plistPath() (string, error) {
	h, err := os.UserHomeDir()
	return filepath.Join(h, "Library", "LaunchAgents", launchLabel+".plist"), err
}

func systemLang() string {
	out, err := exec.Command("defaults", "read", "-g", "AppleLocale").Output()
	if err == nil {
		return strings.TrimSpace(string(out))
	}
	return envLang()
}

func autostartActive() bool {
	p, err := plistPath()
	if err != nil {
		return false
	}
	_, err = os.Stat(p)
	return err == nil
}

// autostartWrite writes the LaunchAgent (start at login, restart only after a crash).
func autostartWrite(exe string) error {
	p, err := plistPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	x := html.EscapeString(exe)
	plist := `<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>` + launchLabel + `</string>
  <key>ProgramArguments</key><array><string>` + x + `</string><string>--background</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
`
	return writeFileAtomic(p, []byte(plist), 0o644)
}

// autostartEnable writes the LaunchAgent and loads it, which also starts the installed copy now.
func autostartEnable(exe string) error {
	if err := autostartWrite(exe); err != nil {
		return err
	}
	p, _ := plistPath()
	dom := "gui/" + strconv.Itoa(os.Getuid())
	_ = exec.Command("launchctl", "bootout", dom+"/"+launchLabel).Run()
	if exec.Command("launchctl", "bootstrap", dom, p).Run() != nil {
		if err := exec.Command("launchctl", "load", "-w", p).Run(); err != nil {
			return startDetached(exe, "--background")
		}
	}
	return nil
}

// autostartDisable removes the LaunchAgent file; a running copy keeps running until "Quit" (exit 0 = no restart).
func autostartDisable() error {
	p, err := plistPath()
	if err != nil {
		return err
	}
	if err := os.Remove(p); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

// autostartUnload takes the job out of launchd (last step of the uninstall, it also ends this process if launchd runs it).
func autostartUnload() {
	_ = exec.Command("launchctl", "bootout", "gui/"+strconv.Itoa(os.Getuid())+"/"+launchLabel).Run()
}

// removeSelfLater: on the Mac a running program file can simply be deleted.
func removeSelfLater(path string) { _ = os.Remove(path) }
