// 2.207.0 B (#2763): the settings file (inboxes with their keys, mode 0600) and the program's own folder.
package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"runtime"
	"sync"
)

// Inbox is one watched folder bound to one upload key (one setup code).
type Inbox struct {
	ID          string `json:"id"`
	Name        string `json:"name"`
	URL         string `json:"url"`
	Key         string `json:"key"`
	Target      string `json:"target"`
	MaxMB       int    `json:"max_mb"`
	Folder      string `json:"folder"`
	UploadedDir string `json:"uploaded_dir"`
	RejectedDir string `json:"rejected_dir"`
}

// Config is the content of config.json.
type Config struct {
	Inboxes   []*Inbox `json:"inboxes"`
	Autostart bool     `json:"autostart"`
}

// Store reads and writes config.json; dir also holds the journal, the log, the page secret and the installed copy.
type Store struct {
	mu   sync.Mutex
	path string
	dir  string
	cfg  Config
}

// defaultConfigDir: mac ~/Library/Application Support/Kalmido Folder Watcher, Windows %APPDATA%\Kalmido Folder Watcher,
// Linux $XDG_CONFIG_HOME/kalmido-folder-watcher.
func defaultConfigDir() (string, error) {
	base, err := os.UserConfigDir()
	if err != nil {
		return "", err
	}
	if runtime.GOOS == "darwin" || runtime.GOOS == "windows" {
		return filepath.Join(base, "Kalmido Folder Watcher"), nil
	}
	return filepath.Join(base, "kalmido-folder-watcher"), nil
}

func openStore(path string) (*Store, error) {
	s := &Store{path: path, dir: filepath.Dir(path)}
	if err := os.MkdirAll(s.dir, 0o700); err != nil {
		return nil, err
	}
	b, err := os.ReadFile(path)
	if errors.Is(err, os.ErrNotExist) {
		return s, nil
	}
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal(b, &s.cfg); err != nil {
		return nil, err
	}
	for _, in := range s.cfg.Inboxes {
		in.fillDefaults()
	}
	return s, nil
}

func (in *Inbox) fillDefaults() {
	if in.ID == "" {
		in.ID = randomHex(6)
	}
	if in.UploadedDir == "" {
		in.UploadedDir = "Uploaded"
	}
	if in.RejectedDir == "" {
		in.RejectedDir = "Not uploaded"
	}
}

// Snapshot returns a copy of the settings (the inboxes copied too).
func (s *Store) Snapshot() Config {
	s.mu.Lock()
	defer s.mu.Unlock()
	c := Config{Autostart: s.cfg.Autostart}
	for _, in := range s.cfg.Inboxes {
		cp := *in
		c.Inboxes = append(c.Inboxes, &cp)
	}
	return c
}

// Update changes the settings under the lock and saves them.
func (s *Store) Update(fn func(c *Config)) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	fn(&s.cfg)
	b, err := json.MarshalIndent(&s.cfg, "", "  ")
	if err != nil {
		return err
	}
	return writeFileAtomic(s.path, b, 0o600)
}

// writeFileAtomic writes <path>.new and renames it over path.
func writeFileAtomic(path string, b []byte, mode os.FileMode) error {
	tmp := path + ".new"
	if err := os.WriteFile(tmp, b, mode); err != nil {
		return err
	}
	_ = os.Chmod(tmp, mode)
	if err := os.Rename(tmp, path); err != nil {
		_ = os.Remove(tmp)
		return err
	}
	return nil
}

func randomHex(n int) string {
	b := make([]byte, n)
	if _, err := rand.Read(b); err != nil {
		panic(err)
	}
	return hex.EncodeToString(b)
}
