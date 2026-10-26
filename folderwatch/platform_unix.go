//go:build !windows

// 2.207.0 B (#2763): what Mac and Linux share - a plain open as the "is it free" check, detached start.
package main

import (
	"os"
	"os/exec"
	"syscall"
)

// canOpenExclusive: on Mac/Linux there is no share mode; the size/time stability check does the real work.
func canOpenExclusive(path string) bool {
	f, err := os.Open(path)
	if err != nil {
		return false
	}
	_ = f.Close()
	return true
}

func startDetached(exe string, args ...string) error {
	c := exec.Command(exe, args...)
	c.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
	if err := c.Start(); err != nil {
		return err
	}
	return c.Process.Release()
}

func hideWindow(c *exec.Cmd) {}

// lockFile: an exclusive flock on the open file (released when the process ends). 2.306.0 (#2875): one engine per
// settings folder, also next to an older copy that does not answer /hello.
func lockFile(path string) (*os.File, error) {
	f, err := os.OpenFile(path, os.O_RDWR|os.O_CREATE, 0o600)
	if err != nil {
		return nil, err
	}
	if err := syscall.Flock(int(f.Fd()), syscall.LOCK_EX|syscall.LOCK_NB); err != nil {
		_ = f.Close()
		if err == syscall.EWOULDBLOCK || err == syscall.EAGAIN {
			return nil, errLocked
		}
		return nil, err
	}
	return f, nil
}
