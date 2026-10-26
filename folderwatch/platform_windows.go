// 2.207.0 B (#2763): Windows - the browser via url.dll, the UI language from kernel32 (no cgo), an exclusive open
// as the "scanner is done" check, the autostart in HKCU\...\Run through reg.exe.
package main

import (
	"os"
	"os/exec"
	"syscall"
)

const (
	runKey          = `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
	runValue        = "Kalmido Folder Watcher"
	createNoWindow  = 0x08000000
	detachedProcess = 0x00000008
)

func hideWindow(c *exec.Cmd) {
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow}
}

func run(name string, args ...string) error {
	c := exec.Command(name, args...)
	hideWindow(c)
	return c.Run()
}

func openURL(u string) error {
	c := exec.Command("rundll32", "url.dll,FileProtocolHandler", u)
	hideWindow(c)
	return c.Start()
}

func openFolder(p string) error { return exec.Command("explorer", p).Start() }
func exeName() string           { return "kalmido-folder-watcher.exe" }
func autostartWhere() string    { return runKey }

func systemLang() string {
	if p, err := syscall.LoadDLL("kernel32.dll"); err == nil {
		if f, err := p.FindProc("GetUserDefaultUILanguage"); err == nil {
			id, _, _ := f.Call()
			switch id & 0x3ff { // primary language id
			case 0x07:
				return "de"
			case 0x09:
				return "en"
			}
			return "other"
		}
	}
	return envLang()
}

// canOpenExclusive: share mode 0 fails while the scanner software still holds the file.
func canOpenExclusive(path string) bool {
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return false
	}
	h, err := syscall.CreateFile(p, syscall.GENERIC_READ, 0, nil, syscall.OPEN_EXISTING, syscall.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		return false
	}
	_ = syscall.CloseHandle(h)
	return true
}

func startDetached(exe string, args ...string) error {
	c := exec.Command(exe, args...)
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow | detachedProcess}
	if err := c.Start(); err != nil {
		return err
	}
	return c.Process.Release()
}

func autostartActive() bool {
	return run("reg", "query", runKey, "/v", runValue) == nil
}

func autostartWrite(exe string) error {
	return run("reg", "add", runKey, "/v", runValue, "/t", "REG_SZ", "/d", `"`+exe+`" --background`, "/f")
}

func autostartEnable(exe string) error {
	if err := autostartWrite(exe); err != nil {
		return err
	}
	return startDetached(exe, "--background")
}

func autostartDisable() error {
	if !autostartActive() {
		return nil
	}
	return run("reg", "delete", runKey, "/v", runValue, "/f")
}

func autostartUnload() {}

// removeSelfLater: Windows cannot delete a running program file; a hidden cmd deletes it a few seconds after the exit.
func removeSelfLater(path string) {
	if os.Remove(path) == nil {
		return
	}
	c := exec.Command("cmd")
	c.SysProcAttr = &syscall.SysProcAttr{HideWindow: true, CreationFlags: createNoWindow | detachedProcess,
		CmdLine: `cmd /c ping -n 4 127.0.0.1 >nul & del /f /q "` + path + `"`}
	_ = c.Start()
}

// lockFile: the file opened without write sharing (released when the process ends). 2.306.0 (#2875): one engine per
// settings folder, also next to an older copy that does not answer /hello.
func lockFile(path string) (*os.File, error) {
	p, err := syscall.UTF16PtrFromString(path)
	if err != nil {
		return nil, err
	}
	h, err := syscall.CreateFile(p, syscall.GENERIC_READ|syscall.GENERIC_WRITE, syscall.FILE_SHARE_READ, nil,
		syscall.OPEN_ALWAYS, syscall.FILE_ATTRIBUTE_NORMAL, 0)
	if err != nil {
		if err == syscall.Errno(32) { // ERROR_SHARING_VIOLATION
			return nil, errLocked
		}
		return nil, err
	}
	return os.NewFile(uintptr(h), path), nil
}
