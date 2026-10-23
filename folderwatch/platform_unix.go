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
