// 2.207.0 B (#2763): a small rotating log in the settings folder (log.txt + log.1.txt, together at most 1 MB).
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"
)

const logMax = 512 * 1024

type Logger struct {
	mu   sync.Mutex
	path string
	echo bool
}

func newLogger(dir string, echo bool) *Logger {
	return &Logger{path: filepath.Join(dir, "log.txt"), echo: echo}
}

func (l *Logger) Printf(format string, a ...any) {
	if l == nil {
		return
	}
	line := time.Now().Format("2006-01-02 15:04:05 ") + fmt.Sprintf(format, a...) + "\n"
	l.mu.Lock()
	defer l.mu.Unlock()
	if l.echo {
		fmt.Fprint(os.Stderr, line)
	}
	if st, err := os.Stat(l.path); err == nil && st.Size()+int64(len(line)) > logMax {
		_ = os.Rename(l.path, filepath.Join(filepath.Dir(l.path), "log.1.txt"))
	}
	f, err := os.OpenFile(l.path, os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		return
	}
	_, _ = f.WriteString(line)
	_ = f.Close()
}
