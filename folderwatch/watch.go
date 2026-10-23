// 2.207.0 B (#2763): watching the inbox folders (polling every 3 s, only files directly in the folder) and the upload
// rounds with their backoff.
package main

import (
	"errors"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	pollEvery   = 3 * time.Second
	stableFor   = 4 * time.Second
	blockedWait = 30 * time.Minute
	eventsKept  = 20
)

var backoffSteps = []time.Duration{30 * time.Second, time.Minute, 2 * time.Minute, 5 * time.Minute, 10 * time.Minute, 30 * time.Minute}

// State of an inbox as the status page shows it.
type State string

const (
	StReady   State = "ready"
	StOffline State = "offline" // waits for the network / the server
	StBlocked State = "blocked" // the target refuses for now (403, 409, 413)
	StPaused  State = "paused"  // 401: key invalid or revoked
	StNoDir   State = "nodir"   // the folder is missing
)

// Event is one line of the recent list.
type Event struct {
	File   string
	At     time.Time
	OK     bool
	Moved  bool
	Reason string
}

type seenFile struct {
	size  int64
	mod   time.Time
	since time.Time
	polls int
}

type inboxRun struct {
	state   State
	msg     string
	next    time.Time
	step    int
	seen    map[string]*seenFile
	waiting []string
	tooBig  map[string]bool
	events  []Event
}

// Engine runs the rounds for all inboxes of a Store.
type Engine struct {
	store   *Store
	journal *Journal
	log     *Logger
	now     func() time.Time
	upload  func(base, key, path string) Result
	move    func(path, dir string) (string, error)

	mu   sync.Mutex
	runs map[string]*inboxRun
	kick chan struct{}
}

func newEngine(store *Store, log *Logger) *Engine {
	return &Engine{
		store:   store,
		journal: openJournal(filepath.Join(store.dir, "journal.json")),
		log:     log,
		now:     time.Now,
		upload:  uploadFile,
		move:    moveInto,
		runs:    map[string]*inboxRun{},
		kick:    make(chan struct{}, 1),
	}
}

func (e *Engine) run(id string) *inboxRun {
	r := e.runs[id]
	if r == nil {
		r = &inboxRun{state: StReady, seen: map[string]*seenFile{}, tooBig: map[string]bool{}}
		e.runs[id] = r
	}
	return r
}

// Loop polls until stop is closed.
func (e *Engine) Loop(stop <-chan struct{}) {
	t := time.NewTicker(pollEvery)
	defer t.Stop()
	for {
		e.Round()
		select {
		case <-stop:
			return
		case <-t.C:
		case <-e.kick:
		}
	}
}

// Kick asks for a round now.
func (e *Engine) Kick() {
	select {
	case e.kick <- struct{}{}:
	default:
	}
}

// Retry clears the waiting time (also of a paused inbox: the key is tried once more).
func (e *Engine) Retry(id string) {
	e.mu.Lock()
	r := e.run(id)
	r.next = time.Time{}
	if r.state == StPaused || r.state == StBlocked {
		r.state = StReady
	}
	r.tooBig = map[string]bool{}
	e.mu.Unlock()
	e.Kick()
}

// Forget drops the run state of a removed inbox.
func (e *Engine) Forget(id string) {
	e.mu.Lock()
	delete(e.runs, id)
	e.mu.Unlock()
}

// Round handles every inbox once.
func (e *Engine) Round() {
	for _, in := range e.store.Snapshot().Inboxes {
		e.roundInbox(in)
	}
}

func (e *Engine) roundInbox(in *Inbox) {
	now := e.now()
	ready := e.scan(in, now)
	e.mu.Lock()
	r := e.run(in.ID)
	hold := r.state == StPaused || now.Before(r.next)
	e.mu.Unlock()
	for _, name := range ready {
		if hold {
			return
		}
		hold = e.handle(in, name)
	}
}

// scan lists the folder, updates the stability bookkeeping and returns the names that are ready (oldest first).
func (e *Engine) scan(in *Inbox, now time.Time) []string {
	ents, err := os.ReadDir(in.Folder)
	e.mu.Lock()
	defer e.mu.Unlock()
	r := e.run(in.ID)
	if err != nil {
		if r.state != StNoDir {
			e.log.Printf("[%s] folder not readable: %v", in.Name, err)
		}
		r.state, r.msg, r.waiting = StNoDir, in.Folder, nil
		return nil
	}
	if r.state == StNoDir {
		r.state, r.msg = StReady, ""
	}
	type cand struct {
		name string
		mod  time.Time
	}
	var ready []cand
	present := map[string]bool{}
	r.waiting = r.waiting[:0]
	for _, de := range ents {
		name := de.Name()
		if !de.Type().IsRegular() || ignoredName(name) {
			continue
		}
		info, err := de.Info()
		if err != nil {
			continue
		}
		present[name] = true
		r.waiting = append(r.waiting, name)
		s := r.seen[name]
		if s == nil || s.size != info.Size() || !s.mod.Equal(info.ModTime()) {
			r.seen[name] = &seenFile{size: info.Size(), mod: info.ModTime(), since: now, polls: 1}
			continue
		}
		s.polls++
		if info.Size() == 0 || s.polls < 2 || now.Sub(s.since) < stableFor || r.tooBig[name] {
			continue
		}
		if in.MaxMB > 0 && info.Size() > int64(in.MaxMB)<<20 {
			r.tooBig[name] = true
			r.addEvent(Event{File: name, At: now, Reason: "too_big"})
			continue
		}
		ready = append(ready, cand{name, info.ModTime()})
	}
	for name := range r.seen {
		if !present[name] {
			delete(r.seen, name)
			delete(r.tooBig, name)
		}
	}
	sort.Slice(ready, func(i, j int) bool { return ready[i].mod.Before(ready[j].mod) })
	out := make([]string, len(ready))
	for i, c := range ready {
		out[i] = c.name
	}
	return out
}

func (r *inboxRun) addEvent(ev Event) {
	r.events = append([]Event{ev}, r.events...)
	if len(r.events) > eventsKept {
		r.events = r.events[:eventsKept]
	}
}

// handle uploads (or only moves) one ready file; true = stop this round for the inbox.
func (e *Engine) handle(in *Inbox, name string) bool {
	path := filepath.Join(in.Folder, name)
	if !canOpenExclusive(path) {
		return false // still in use by the scanner software, next round
	}
	sha, size, err := fileSHA256(path)
	if err != nil {
		return false
	}
	if e.journal.Has(in.ID, sha, size) {
		e.moveAfterUpload(in, name, sha, size)
		return false
	}
	res := e.upload(in.URL, in.Key, path)
	now := e.now()
	e.mu.Lock()
	r := e.run(in.ID)
	switch res.Out {
	case OutOK:
		r.state, r.msg, r.step, r.next = StReady, "", 0, time.Time{}
		e.mu.Unlock()
		e.log.Printf("[%s] uploaded %s (document %d)", in.Name, name, res.ID)
		e.journal.Add(in.ID, sha, size, name)
		e.moveAfterUpload(in, name, sha, size)
		return false
	case OutReject:
		e.mu.Unlock()
		e.log.Printf("[%s] not accepted %s: %s", in.Name, name, res.Msg)
		_, err := e.move(path, filepath.Join(in.Folder, in.RejectedDir))
		e.mu.Lock()
		r.addEvent(Event{File: name, At: now, Reason: res.Msg, Moved: err == nil})
		delete(r.seen, name)
		e.mu.Unlock()
		return false
	case OutPaused:
		r.state, r.msg = StPaused, res.Msg
		r.addEvent(Event{File: name, At: now, Reason: res.Msg})
		e.log.Printf("[%s] paused, key refused: %s", in.Name, res.Msg)
	case OutBlocked:
		r.state, r.msg, r.next = StBlocked, res.Msg, now.Add(blockedWait)
		r.addEvent(Event{File: name, At: now, Reason: res.Msg})
		e.log.Printf("[%s] target refused %s: %s (next try in 30 min)", in.Name, name, res.Msg)
	default:
		wait := backoffSteps[min(r.step, len(backoffSteps)-1)]
		if res.RetryAfter > wait {
			wait = min(res.RetryAfter, backoffSteps[len(backoffSteps)-1])
		}
		r.step++
		r.state, r.msg, r.next = StOffline, res.Msg, now.Add(wait)
		e.log.Printf("[%s] upload of %s failed: %s (next try in %s)", in.Name, name, res.Msg, wait)
	}
	e.mu.Unlock()
	return true
}

func (e *Engine) moveAfterUpload(in *Inbox, name, sha string, size int64) {
	_, err := e.move(filepath.Join(in.Folder, name), filepath.Join(in.Folder, in.UploadedDir))
	e.mu.Lock()
	r := e.run(in.ID)
	if err != nil {
		e.mu.Unlock()
		e.log.Printf("[%s] uploaded %s but could not move it yet: %v", in.Name, name, err)
		return
	}
	r.addEvent(Event{File: name, At: e.now(), OK: true, Moved: true})
	delete(r.seen, name)
	e.mu.Unlock()
	e.journal.Done(in.ID, sha, size)
}

// moveInto moves a file into dir (created when missing); an existing name gets " (2)", " (3)" ...
func moveInto(path, dir string) (string, error) {
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	dst := uniqueName(dir, filepath.Base(path))
	if err := os.Rename(path, dst); err != nil {
		return "", err
	}
	return dst, nil
}

func uniqueName(dir, name string) string {
	ext := filepath.Ext(name)
	stem := strings.TrimSuffix(name, ext)
	if stem == "" {
		stem, ext = name, ""
	}
	cand := filepath.Join(dir, name)
	for i := 2; ; i++ {
		if _, err := os.Lstat(cand); errors.Is(err, os.ErrNotExist) {
			return cand
		}
		cand = filepath.Join(dir, stem+" ("+strconv.Itoa(i)+")"+ext)
	}
}

// ignoredName: hidden files, office lock files and the usual partial-download / temp names.
func ignoredName(name string) bool {
	l := strings.ToLower(name)
	if strings.HasPrefix(l, ".") || strings.HasPrefix(l, "~$") || l == "desktop.ini" || l == "thumbs.db" {
		return true
	}
	for _, s := range []string{".tmp", ".part", ".crdownload", ".download", ".partial"} {
		if strings.HasSuffix(l, s) {
			return true
		}
	}
	return false
}

// InboxView is the status of one inbox for the page.
type InboxView struct {
	In      Inbox
	State   State
	Msg     string
	Next    time.Time
	Waiting []string
	Events  []Event
}

func (e *Engine) View(in *Inbox) InboxView {
	e.mu.Lock()
	defer e.mu.Unlock()
	r := e.run(in.ID)
	v := InboxView{In: *in, State: r.state, Msg: r.msg, Next: r.next}
	v.Waiting = append(v.Waiting, r.waiting...)
	v.Events = append(v.Events, r.events...)
	return v
}
