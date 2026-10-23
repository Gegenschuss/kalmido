//go:build !darwin && !windows

// 2.207.0 B (#2763): Linux and other unix systems - xdg-open, LANG, an XDG autostart entry.
package main

import (
	"os"
	"os/exec"
	"path/filepath"
	"strings"
)

func openURL(u string) error    { return exec.Command("xdg-open", u).Start() }
func openFolder(p string) error { return exec.Command("xdg-open", p).Start() }
func exeName() string           { return "kalmido-folder-watcher" }
func systemLang() string        { return envLang() }
func autostartWhere() string    { return "~/.config/autostart/kalmido-folder-watcher.desktop" }

func desktopPath() (string, error) {
	d, err := os.UserConfigDir()
	return filepath.Join(d, "autostart", "kalmido-folder-watcher.desktop"), err
}

func autostartActive() bool {
	p, err := desktopPath()
	if err != nil {
		return false
	}
	_, err = os.Stat(p)
	return err == nil
}

func autostartWrite(exe string) error {
	p, err := desktopPath()
	if err != nil {
		return err
	}
	if err := os.MkdirAll(filepath.Dir(p), 0o755); err != nil {
		return err
	}
	q := `"` + strings.NewReplacer(`\`, `\\\\`, `"`, `\\"`, "`", "\\\\`", "$", `\\$`).Replace(exe) + `"`
	entry := "[Desktop Entry]\nType=Application\nName=Kalmido Folder Watcher\nExec=" + q + " --background\nNoDisplay=true\nX-GNOME-Autostart-enabled=true\n"
	return writeFileAtomic(p, []byte(entry), 0o644)
}

func autostartEnable(exe string) error {
	if err := autostartWrite(exe); err != nil {
		return err
	}
	return startDetached(exe, "--background")
}

func autostartDisable() error {
	p, err := desktopPath()
	if err != nil {
		return err
	}
	if err := os.Remove(p); err != nil && !os.IsNotExist(err) {
		return err
	}
	return nil
}

func autostartUnload()            {}
func removeSelfLater(path string) { _ = os.Remove(path) }
