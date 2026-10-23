// 2.207.0 B (#2763): the duplicate guard - files that were uploaded but could not be moved away yet (locked by another
// program). Such a file is only moved on the next round, never uploaded a second time.
package main

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"io"
	"os"
	"sync"
	"time"
)

type journalEntry struct {
	Inbox string    `json:"inbox"`
	SHA   string    `json:"sha256"`
	Size  int64     `json:"size"`
	Name  string    `json:"name"`
	At    time.Time `json:"at"`
}

// Journal keeps at most journalMax entries; one older than journalAge is dropped (the file was surely handled by then).
type Journal struct {
	mu      sync.Mutex
	path    string
	entries []journalEntry
}

const (
	journalMax = 500
	journalAge = 30 * 24 * time.Hour
)

func openJournal(path string) *Journal {
	j := &Journal{path: path}
	if b, err := os.ReadFile(path); err == nil {
		_ = json.Unmarshal(b, &j.entries)
	}
	return j
}

func (j *Journal) save() {
	cut := time.Now().Add(-journalAge)
	keep := j.entries[:0]
	for _, e := range j.entries {
		if e.At.After(cut) {
			keep = append(keep, e)
		}
	}
	if len(keep) > journalMax {
		keep = keep[len(keep)-journalMax:]
	}
	j.entries = keep
	if b, err := json.Marshal(j.entries); err == nil {
		_ = writeFileAtomic(j.path, b, 0o600)
	}
}

// Has: this content was uploaded through this inbox and still waits to be moved.
func (j *Journal) Has(inbox, sha string, size int64) bool {
	j.mu.Lock()
	defer j.mu.Unlock()
	for _, e := range j.entries {
		if e.Inbox == inbox && e.SHA == sha && e.Size == size {
			return true
		}
	}
	return false
}

func (j *Journal) Add(inbox, sha string, size int64, name string) {
	j.mu.Lock()
	defer j.mu.Unlock()
	j.entries = append(j.entries, journalEntry{Inbox: inbox, SHA: sha, Size: size, Name: name, At: time.Now()})
	j.save()
}

// Done: the file is moved away, the entry can go.
func (j *Journal) Done(inbox, sha string, size int64) {
	j.mu.Lock()
	defer j.mu.Unlock()
	out := j.entries[:0]
	for _, e := range j.entries {
		if !(e.Inbox == inbox && e.SHA == sha && e.Size == size) {
			out = append(out, e)
		}
	}
	j.entries = out
	j.save()
}

func fileSHA256(path string) (string, int64, error) {
	f, err := os.Open(path)
	if err != nil {
		return "", 0, err
	}
	defer f.Close()
	h := sha256.New()
	n, err := io.Copy(h, f)
	if err != nil {
		return "", 0, err
	}
	return hex.EncodeToString(h.Sum(nil)), n, nil
}
