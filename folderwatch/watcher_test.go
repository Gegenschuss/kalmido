// 2.207.0 B (#2763): tests of the folder watcher (run in the Docker build stage: go vet + go test).
package main

import (
	"encoding/base64"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

func mkCode(t *testing.T, u, key, name string) string {
	t.Helper()
	b, _ := json.Marshal(map[string]string{"url": u, "key": key, "name": name})
	return codePrefix + base64.RawURLEncoding.EncodeToString(b)
}

func TestDecodeCode(t *testing.T) {
	c, err := decodeCode("  " + mkCode(t, "https://example.com/", "abk_x1", "Belege") + "\n")
	if err != nil || c.URL != "https://example.com" || c.Key != "abk_x1" || c.Name != "Belege" {
		t.Fatalf("decode: %+v %v", c, err)
	}
	if _, err := decodeCode(mkCode(t, "http://127.0.0.1:3040", "abk_x", "")); err != nil {
		t.Fatalf("local http must pass: %v", err)
	}
	for _, bad := range []string{
		mkCode(t, "http://example.com", "abk_x", "n"),
		mkCode(t, "https://example.com", "", "n"),
		mkCode(t, "ftp://example.com", "abk_x", "n"),
		"kalmido-scan:2:abc", "kalmido-scan:1:@@@", "abk_plain",
	} {
		if _, err := decodeCode(bad); err == nil {
			t.Errorf("accepted %q", bad)
		}
	}
	// a code split over lines (mail clients) still works
	code := mkCode(t, "https://example.com", "abk_y", "Scans")
	if _, err := decodeCode(code[:20] + "\n" + code[20:]); err != nil {
		t.Errorf("wrapped code: %v", err)
	}
}

func TestIgnoredName(t *testing.T) {
	for _, n := range []string{".DS_Store", ".hidden.pdf", "~$brief.docx", "scan.pdf.tmp", "a.PART", "x.crdownload", "y.download", "desktop.ini", "Thumbs.db"} {
		if !ignoredName(n) {
			t.Errorf("%s should be ignored", n)
		}
	}
	for _, n := range []string{"scan.pdf", "Beleg 2026.jpg", "tmp.pdf"} {
		if ignoredName(n) {
			t.Errorf("%s should be watched", n)
		}
	}
}

func TestUniqueName(t *testing.T) {
	d := t.TempDir()
	if got := uniqueName(d, "a.pdf"); got != filepath.Join(d, "a.pdf") {
		t.Fatal(got)
	}
	os.WriteFile(filepath.Join(d, "a.pdf"), []byte("1"), 0o644)
	os.WriteFile(filepath.Join(d, "a (2).pdf"), []byte("1"), 0o644)
	if got := uniqueName(d, "a.pdf"); got != filepath.Join(d, "a (3).pdf") {
		t.Fatal(got)
	}
}

func TestServerMessage(t *testing.T) {
	if m := serverMessage([]byte(`{"error": {"code": "forbidden", "message": "Ordner gesperrt"}}`)); m != "Ordner gesperrt" {
		t.Error(m)
	}
	if m := serverMessage([]byte(`{"error": "zu gross"}`)); m != "zu gross" {
		t.Error(m)
	}
	if m := serverMessage([]byte(`<html>bad gateway</html>`)); m != "" {
		t.Error(m)
	}
}

// fakeKalmido answers like the server; status is the next answer for an upload.
type fakeKalmido struct {
	mu      sync.Mutex
	status  int
	body    string
	uploads []string
	srv     *httptest.Server
	t       *testing.T
}

func newFake(t *testing.T) *fakeKalmido {
	f := &fakeKalmido{status: 201, t: t}
	f.srv = httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer abk_test" || !strings.HasPrefix(r.UserAgent(), "kalmido-folder-watcher/") {
			w.WriteHeader(401)
			return
		}
		switch r.URL.Path {
		case "/api/v1/documents/upload-target":
			w.Write([]byte(`{"name": "Belege", "target": "Eigene Dokumente / Belege", "max_mb": 1}`))
		case "/api/v1/documents":
			if r.ContentLength <= 0 {
				t.Errorf("no Content-Length")
			}
			mf, fh, err := r.FormFile("file")
			if err != nil {
				t.Errorf("multipart: %v", err)
				w.WriteHeader(400)
				return
			}
			b, _ := io.ReadAll(mf)
			f.mu.Lock()
			f.uploads = append(f.uploads, fh.Filename+"="+string(b))
			st, body := f.status, f.body
			f.mu.Unlock()
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(st)
			if body == "" && st == 201 {
				body = `{"id": 7, "name": "` + fh.Filename + `"}`
			}
			w.Write([]byte(body))
		default:
			w.WriteHeader(404)
		}
	}))
	t.Cleanup(f.srv.Close)
	return f
}

func (f *fakeKalmido) set(st int, body string) {
	f.mu.Lock()
	f.status, f.body = st, body
	f.mu.Unlock()
}

func (f *fakeKalmido) count() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.uploads)
}

type rig struct {
	eng    *Engine
	folder string
	clock  time.Time
	in     *Inbox
}

func newRig(t *testing.T, base string) *rig {
	t.Helper()
	dir := t.TempDir()
	store, err := openStore(filepath.Join(dir, "cfg", "config.json"))
	if err != nil {
		t.Fatal(err)
	}
	r := &rig{folder: filepath.Join(dir, "in"), clock: time.Date(2026, 10, 23, 10, 0, 0, 0, time.UTC)}
	os.MkdirAll(r.folder, 0o755)
	r.in = &Inbox{Name: "Belege", URL: base, Key: "abk_test", Target: "Eigene Dokumente / Belege", Folder: r.folder,
		UploadedDir: "Hochgeladen", RejectedDir: "Nicht hochgeladen"}
	r.in.fillDefaults()
	store.Update(func(c *Config) { c.Inboxes = append(c.Inboxes, r.in) })
	r.eng = newEngine(store, nil)
	r.eng.now = func() time.Time { return r.clock }
	return r
}

// settle: three rounds over 5 s - enough for the stability check.
func (r *rig) settle() {
	for i := 0; i < 3; i++ {
		r.eng.Round()
		r.clock = r.clock.Add(2500 * time.Millisecond)
	}
}

func (r *rig) write(t *testing.T, name, content string) {
	t.Helper()
	if err := os.WriteFile(filepath.Join(r.folder, name), []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
}

func exists(p string) bool { _, err := os.Stat(p); return err == nil }

func TestUploadMovesFile(t *testing.T) {
	f := newFake(t)
	r := newRig(t, f.srv.URL)
	r.write(t, "scan.pdf", "%PDF-1.4 hello")
	r.write(t, ".DS_Store", "x")
	r.write(t, "empty.pdf", "")
	r.eng.Round()
	if f.count() != 0 {
		t.Fatal("uploaded before the file was stable")
	}
	r.clock = r.clock.Add(2 * time.Second)
	r.eng.Round()
	if f.count() != 0 {
		t.Fatal("uploaded after less than 4 s")
	}
	r.clock = r.clock.Add(3 * time.Second)
	r.eng.Round()
	if f.count() != 1 || f.uploads[0] != "scan.pdf=%PDF-1.4 hello" {
		t.Fatalf("uploads %v", f.uploads)
	}
	if exists(filepath.Join(r.folder, "scan.pdf")) || !exists(filepath.Join(r.folder, "Hochgeladen", "scan.pdf")) {
		t.Fatal("not moved into Hochgeladen")
	}
	if !exists(filepath.Join(r.folder, "empty.pdf")) || !exists(filepath.Join(r.folder, ".DS_Store")) {
		t.Fatal("empty / hidden file touched")
	}
	v := r.eng.View(r.in)
	if v.State != StReady || len(v.Events) != 1 || !v.Events[0].OK {
		t.Fatalf("view %+v", v)
	}
	// same name again -> "scan (2).pdf"
	r.write(t, "scan.pdf", "second")
	r.settle()
	if !exists(filepath.Join(r.folder, "Hochgeladen", "scan (2).pdf")) {
		t.Fatal("name clash not resolved")
	}
}

func TestGrowingFileWaits(t *testing.T) {
	f := newFake(t)
	r := newRig(t, f.srv.URL)
	for i := 0; i < 4; i++ {
		r.write(t, "big.pdf", strings.Repeat("x", 10+i))
		r.eng.Round()
		r.clock = r.clock.Add(3 * time.Second)
	}
	if f.count() != 0 {
		t.Fatal("uploaded while still growing")
	}
	r.settle()
	if f.count() != 1 {
		t.Fatal("not uploaded once stable")
	}
}

func TestUnauthorizedPauses(t *testing.T) {
	f := newFake(t)
	r := newRig(t, f.srv.URL)
	f.set(401, `{"error": {"code": "unauthorized", "message": "key revoked"}}`)
	r.write(t, "a.pdf", "a")
	r.settle()
	if f.count() != 1 {
		t.Fatalf("uploads %d", f.count())
	}
	v := r.eng.View(r.in)
	if v.State != StPaused || !exists(filepath.Join(r.folder, "a.pdf")) {
		t.Fatalf("not paused: %+v", v)
	}
	r.clock = r.clock.Add(time.Hour)
	r.settle()
	if f.count() != 1 {
		t.Fatal("a paused inbox kept uploading")
	}
	f.set(201, "")
	r.eng.Retry(r.in.ID)
	r.settle()
	if f.count() != 2 || !exists(filepath.Join(r.folder, "Hochgeladen", "a.pdf")) {
		t.Fatal("retry after a new key did not upload")
	}
}

func TestServerErrorBacksOff(t *testing.T) {
	f := newFake(t)
	r := newRig(t, f.srv.URL)
	f.set(503, `{"error": "maintenance"}`)
	r.write(t, "a.pdf", "a")
	r.settle()
	if f.count() != 1 {
		t.Fatalf("uploads %d", f.count())
	}
	v := r.eng.View(r.in)
	if v.State != StOffline || v.Msg != "maintenance" || !exists(filepath.Join(r.folder, "a.pdf")) {
		t.Fatalf("view %+v", v)
	}
	r.clock = v.Next.Add(-time.Second)
	r.eng.Round()
	if f.count() != 1 {
		t.Fatal("retried before the backoff was over")
	}
	r.clock = v.Next.Add(time.Second)
	r.eng.Round()
	if f.count() != 2 {
		t.Fatal("no retry after the backoff")
	}
	if w := r.eng.View(r.in).Next.Sub(r.clock); w < 59*time.Second || w > time.Minute {
		t.Fatalf("second backoff step %s, want 1 min", w)
	}
	// network gone: also "later"
	r2 := newRig(t, "http://127.0.0.1:1")
	r2.write(t, "b.pdf", "b")
	r2.settle()
	if s := r2.eng.View(r2.in).State; s != StOffline {
		t.Fatalf("network error state %s", s)
	}
}

func TestBlockedWaits30Min(t *testing.T) {
	f := newFake(t)
	r := newRig(t, f.srv.URL)
	f.set(403, `{"error": {"code": "forbidden", "message": "target not allowed"}}`)
	r.write(t, "a.pdf", "a")
	r.settle()
	v := r.eng.View(r.in)
	if v.State != StBlocked || v.Next.Sub(r.clock) < 25*time.Minute || !exists(filepath.Join(r.folder, "a.pdf")) {
		t.Fatalf("view %+v", v)
	}
}

func TestRejectedMovesAside(t *testing.T) {
	f := newFake(t)
	r := newRig(t, f.srv.URL)
	f.set(415, `{"error": {"code": "unsupported", "message": "file type not accepted"}}`)
	r.write(t, "a.exe", "MZ")
	r.settle()
	if !exists(filepath.Join(r.folder, "Nicht hochgeladen", "a.exe")) {
		t.Fatal("not moved into Nicht hochgeladen")
	}
	v := r.eng.View(r.in)
	if v.State != StReady || len(v.Events) != 1 || v.Events[0].Reason != "file type not accepted" {
		t.Fatalf("view %+v", v)
	}
}

func TestTooBigStaysLocal(t *testing.T) {
	f := newFake(t)
	r := newRig(t, f.srv.URL)
	r.eng.store.Update(func(c *Config) { c.Inboxes[0].MaxMB = 1 })
	r.write(t, "huge.pdf", strings.Repeat("x", 1<<20+1))
	r.settle()
	r.settle()
	if f.count() != 0 || !exists(filepath.Join(r.folder, "huge.pdf")) {
		t.Fatal("too large file was sent")
	}
	if ev := r.eng.View(r.in).Events; len(ev) != 1 || ev[0].Reason != "too_big" {
		t.Fatalf("events %+v", ev)
	}
}

func TestNoDoubleUploadWhenMoveFails(t *testing.T) {
	f := newFake(t)
	r := newRig(t, f.srv.URL)
	// moving fails (e.g. the scanner software still holds the file)
	r.eng.move = func(path, dir string) (string, error) { return "", os.ErrPermission }
	r.write(t, "a.pdf", "content")
	r.settle()
	if f.count() != 1 || !exists(filepath.Join(r.folder, "a.pdf")) {
		t.Fatalf("uploads %d", f.count())
	}
	r.settle()
	r.settle()
	if f.count() != 1 {
		t.Fatalf("uploaded again: %d", f.count())
	}
	r.eng.move = moveInto
	r.settle()
	if f.count() != 1 || !exists(filepath.Join(r.folder, "Hochgeladen", "a.pdf")) {
		t.Fatal("not moved after the folder was free")
	}
	// the journal entry is gone: the same content later is a new upload
	r.write(t, "b.pdf", "content")
	r.settle()
	if f.count() != 2 {
		t.Fatalf("new file with known content not uploaded: %d", f.count())
	}
}

func TestFetchTarget(t *testing.T) {
	f := newFake(t)
	tg, res := fetchTarget(f.srv.URL, "abk_test")
	if res.Out != OutOK || tg.Target != "Eigene Dokumente / Belege" || tg.MaxMB != 1 {
		t.Fatalf("%+v %+v", tg, res)
	}
	if _, res := fetchTarget(f.srv.URL, "abk_wrong"); res.Out != OutPaused {
		t.Fatalf("wrong key: %+v", res)
	}
	if _, res := fetchTarget("http://example.com", "abk_test"); res.Out == OutOK {
		t.Fatal("plain http to a remote host accepted")
	}
}

func testPage(t *testing.T) (*Page, *rig) {
	f := newFake(t)
	r := newRig(t, f.srv.URL)
	p := &Page{store: r.eng.store, eng: r.eng, lang: "de", secret: strings.Repeat("ab", 24), port: defaultPort,
		isInstalled: func() bool { return false }}
	return p, r
}

func doReq(p *Page, method, host, path string, form url.Values, hdr map[string]string) *httptest.ResponseRecorder {
	var body io.Reader
	if form != nil {
		body = strings.NewReader(form.Encode())
	}
	req := httptest.NewRequest(method, "http://"+host+path, body)
	req.Host = host
	if form != nil {
		req.Header.Set("Content-Type", "application/x-www-form-urlencoded")
	}
	for k, v := range hdr {
		req.Header.Set(k, v)
	}
	w := httptest.NewRecorder()
	p.ServeHTTP(w, req)
	return w
}

func TestPageGuards(t *testing.T) {
	p, r := testPage(t)
	host := "127.0.0.1:47807"
	base := p.base()
	if w := doReq(p, "GET", host, base, nil, nil); w.Code != 200 || !strings.Contains(w.Body.String(), "Belege") {
		t.Fatalf("status page %d", w.Code)
	}
	if w := doReq(p, "GET", "evil.example:47807", base, nil, nil); w.Code != 404 {
		t.Fatalf("foreign Host header: %d", w.Code)
	}
	if w := doReq(p, "GET", "localhost:47807", base, nil, nil); w.Code != 404 {
		t.Fatalf("other Host spelling: %d", w.Code)
	}
	if w := doReq(p, "GET", host, "/s/"+strings.Repeat("cd", 24)+"/", nil, nil); w.Code != 404 {
		t.Fatalf("wrong secret: %d", w.Code)
	}
	if w := doReq(p, "GET", host, "/", nil, nil); w.Code != 404 {
		t.Fatalf("root: %d", w.Code)
	}
	form := url.Values{"id": {r.in.ID}}
	if w := doReq(p, "POST", host, base+"retry", form, nil); w.Code != 403 {
		t.Fatalf("POST without the secret field: %d", w.Code)
	}
	form.Set("t", p.secret)
	if w := doReq(p, "POST", host, base+"retry", form, map[string]string{"Origin": "https://evil.example"}); w.Code != 403 {
		t.Fatalf("POST from a foreign origin: %d", w.Code)
	}
	if w := doReq(p, "POST", host, base+"retry", form, map[string]string{"Sec-Fetch-Site": "cross-site"}); w.Code != 403 {
		t.Fatalf("cross-site POST: %d", w.Code)
	}
	if w := doReq(p, "POST", host, base+"retry", form, map[string]string{"Origin": "http://127.0.0.1:47807", "Sec-Fetch-Site": "same-origin"}); w.Code != 303 {
		t.Fatalf("own POST: %d", w.Code)
	}
	if w := doReq(p, "GET", host, base+"ping", nil, nil); w.Code != 200 || !strings.HasPrefix(w.Body.String(), "kalmido-folder-watcher") {
		t.Fatal("ping")
	}
	if h := doReq(p, "GET", host, base, nil, nil).Header(); !strings.Contains(h.Get("Content-Security-Policy"), "frame-ancestors 'none'") || h.Get("Referrer-Policy") != "no-referrer" {
		t.Fatal("security headers missing")
	}
}

func TestPageAddInbox(t *testing.T) {
	p, r := testPage(t)
	r.eng.store.Update(func(c *Config) { c.Inboxes = nil })
	host, base := "127.0.0.1:47807", p.base()
	p.autostart = func(on bool) (bool, error) { return false, nil }
	if w := doReq(p, "GET", host, base, nil, nil); !strings.Contains(w.Body.String(), "Einrichtungscode") {
		t.Fatal("empty settings should show the setup form")
	}
	bad := url.Values{"t": {p.secret}, "code": {"nonsense"}}
	if w := doReq(p, "POST", host, base+"check", bad, nil); !strings.Contains(w.Body.String(), "kein gültiger Einrichtungscode") {
		t.Fatal("bad code not reported")
	}
	insecure := url.Values{"t": {p.secret}, "code": {mkCode(t, "http://example.com", "abk_test", "x")}}
	if w := doReq(p, "POST", host, base+"check", insecure, nil); !strings.Contains(w.Body.String(), "muss mit https://") {
		t.Fatal("http address not reported")
	}
	code := mkCode(t, r.in.URL, "abk_test", "Belege")
	w := doReq(p, "POST", host, base+"check", url.Values{"t": {p.secret}, "code": {code}}, nil)
	if !strings.Contains(w.Body.String(), "Eigene Dokumente / Belege") || !strings.Contains(w.Body.String(), "Kalmido Scans") {
		t.Fatalf("step 2 missing target / folder suggestion: %s", w.Body.String())
	}
	folder := filepath.Join(t.TempDir(), "Scans", "Belege")
	w = doReq(p, "POST", host, base+"save", url.Values{"t": {p.secret}, "code": {code}, "folder": {folder}}, nil)
	if w.Code != 303 {
		t.Fatalf("save: %d %s", w.Code, w.Body.String())
	}
	c := p.store.Snapshot()
	if len(c.Inboxes) != 1 || c.Inboxes[0].Folder != folder || c.Inboxes[0].UploadedDir != "Hochgeladen" || !exists(folder) {
		t.Fatalf("inbox not stored: %+v", c.Inboxes)
	}
	st, _ := os.Stat(p.store.path)
	if st.Mode().Perm() != 0o600 {
		t.Fatalf("config mode %v", st.Mode().Perm())
	}
	if w := doReq(p, "POST", host, base+"check", url.Values{"t": {p.secret}, "code": {code}}, nil); !strings.Contains(w.Body.String(), "schon eingerichtet") {
		t.Fatal("duplicate code accepted")
	}
	w = doReq(p, "POST", host, base+"remove", url.Values{"t": {p.secret}, "id": {c.Inboxes[0].ID}}, nil)
	if w.Code != 303 || len(p.store.Snapshot().Inboxes) != 0 {
		t.Fatal("remove failed")
	}
}

func TestSafeFolderName(t *testing.T) {
	if s := safeFolderName(`Belege/2026: "neu"`); s != "Belege-2026- -neu-" {
		t.Fatal(s)
	}
	if s := safeFolderName(" .. "); s != "Scans" {
		t.Fatal(s)
	}
}
