// 2.207.0 B (#2763): the local setup and status page. Only on 127.0.0.1, under a secret path (/s/<secret>/), the Host
// header must be exactly 127.0.0.1:<port>, every POST carries the secret as a form field and must come from this page.
package main

import (
	"crypto/hmac"
	"crypto/sha256"
	"crypto/subtle"
	"encoding/hex"
	"html/template"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"
	"time"
)

const defaultPort = 47807

// Page is the local web page of one running instance.
type Page struct {
	store  *Store
	eng    *Engine
	log    *Logger
	lang   string
	secret string
	port   int
	// hooks of the program (main.go): quit, uninstall, autostart on with handover
	quit        func()
	uninstall   func()
	autostart   func(on bool) (handover bool, err error)
	isInstalled func() bool
}

func (p *Page) base() string { return "/s/" + p.secret + "/" }
func (p *Page) URL() string  { return "http://127.0.0.1:" + strconv.Itoa(p.port) + p.base() }

const pageCSP = "default-src 'none'; style-src 'unsafe-inline'; img-src data:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"

// ServeHTTP checks host, secret and origin before anything else.
func (p *Page) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h := w.Header()
	h.Set("Content-Security-Policy", pageCSP)
	h.Set("X-Frame-Options", "DENY")
	h.Set("Referrer-Policy", "no-referrer")
	h.Set("Cache-Control", "no-store")
	h.Set("X-Content-Type-Options", "nosniff")
	if r.URL.Path == "/hello" && r.Method == http.MethodGet && r.Host == "127.0.0.1:"+strconv.Itoa(p.port) {
		p.hello(w, r) // 2.306.0 D3 (#2875): another start asks whether this is our instance without sending the secret
		return
	}
	if !p.allowed(r) {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	sub := strings.TrimPrefix(r.URL.Path, p.base())
	if r.Method == http.MethodPost {
		if err := r.ParseForm(); err != nil || !p.secretOK(r.PostForm.Get("t")) || !p.sameOrigin(r) {
			http.Error(w, "forbidden", http.StatusForbidden)
			return
		}
		p.post(w, r, sub)
		return
	}
	if r.Method != http.MethodGet && r.Method != http.MethodHead {
		http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
		return
	}
	switch sub {
	case "":
		if len(p.store.Snapshot().Inboxes) == 0 && r.URL.Query().Get("n") == "" {
			p.render(w, &view{Page: "add"})
			return
		}
		p.render(w, &view{Page: "status", Notice: p.notice(r.URL.Query())})
	case "add":
		p.render(w, &view{Page: "add"})
	case "remove":
		in := p.inbox(r.URL.Query().Get("id"))
		if in == nil {
			p.redirect(w, r, "")
			return
		}
		p.render(w, &view{Page: "confirm", Question: T(p.lang, "remove_q", in.Name), Action: "remove", ID: in.ID, Button: T(p.lang, "btn_remove")})
	case "uninstall":
		p.render(w, &view{Page: "confirm", Question: T(p.lang, "uninstall_q"), Action: "uninstall", Button: T(p.lang, "btn_uninstall")})
	case "ping":
		w.Header().Set("Content-Type", "text/plain; charset=utf-8")
		_, _ = w.Write([]byte("kalmido-folder-watcher " + version))
	default:
		http.Error(w, "not found", http.StatusNotFound)
	}
}

// helloProof: the answer to a start's challenge n -- proves knowing the page secret without revealing it (2.306.0 D3, #2875).
// 2.306.0 (#2875): bound to the port the instance listens on, so a listener on another port cannot pass on the answer.
func helloProof(secret string, port int, n string) string {
	m := hmac.New(sha256.New, []byte(secret))
	m.Write([]byte("kalmido-folder-watcher-hello|" + strconv.Itoa(port) + "|" + n))
	return hex.EncodeToString(m.Sum(nil))
}

// hello: GET /hello?n=<64 hex> -> "kalmido-folder-watcher <version> <proof>"; nothing else is told without the secret.
func (p *Page) hello(w http.ResponseWriter, r *http.Request) {
	n := r.URL.Query().Get("n")
	if _, err := hex.DecodeString(n); err != nil || len(n) != 64 {
		http.Error(w, "not found", http.StatusNotFound)
		return
	}
	w.Header().Set("Content-Type", "text/plain; charset=utf-8")
	_, _ = w.Write([]byte("kalmido-folder-watcher " + version + " " + helloProof(p.secret, p.port, n)))
}

// allowed: right Host (no DNS rebinding) and the secret path prefix.
func (p *Page) allowed(r *http.Request) bool {
	if r.Host != "127.0.0.1:"+strconv.Itoa(p.port) {
		return false
	}
	if !strings.HasPrefix(r.URL.Path, "/s/") {
		return false
	}
	rest := r.URL.Path[3:]
	i := strings.IndexByte(rest, '/')
	if i < 0 {
		return false
	}
	return p.secretOK(rest[:i])
}

func (p *Page) secretOK(s string) bool {
	return len(s) == len(p.secret) && subtle.ConstantTimeCompare([]byte(s), []byte(p.secret)) == 1
}

// sameOrigin: a browser sends Origin / Sec-Fetch-Site with a form POST; both must point at this page.
func (p *Page) sameOrigin(r *http.Request) bool {
	if o := r.Header.Get("Origin"); o != "" && o != "http://127.0.0.1:"+strconv.Itoa(p.port) {
		return false
	}
	if s := r.Header.Get("Sec-Fetch-Site"); s != "" && s != "same-origin" && s != "none" {
		return false
	}
	return true
}

func (p *Page) inbox(id string) *Inbox {
	for _, in := range p.store.Snapshot().Inboxes {
		if in.ID == id {
			return in
		}
	}
	return nil
}

func (p *Page) redirect(w http.ResponseWriter, r *http.Request, notice string, extra ...string) {
	q := url.Values{}
	if notice != "" {
		q.Set("n", notice)
	}
	if len(extra) > 0 {
		q.Set("e", extra[0])
	}
	u := p.base()
	if len(q) > 0 {
		u += "?" + q.Encode()
	}
	http.Redirect(w, r, u, http.StatusSeeOther)
}

func (p *Page) notice(q url.Values) string {
	switch n := q.Get("n"); n {
	case "saved", "removed", "retry", "as_off":
		return T(p.lang, "n_"+n)
	case "err":
		return T(p.lang, "n_err", q.Get("e"))
	}
	return ""
}

func (p *Page) post(w http.ResponseWriter, r *http.Request, sub string) {
	f := r.PostForm
	switch sub {
	case "check", "save":
		p.postAdd(w, r, sub == "save")
	case "retry":
		p.eng.Retry(f.Get("id"))
		p.redirect(w, r, "retry")
	case "open":
		if in := p.inbox(f.Get("id")); in != nil {
			_ = openFolder(in.Folder)
		}
		p.redirect(w, r, "")
	case "remove":
		id := f.Get("id")
		err := p.store.Update(func(c *Config) {
			out := c.Inboxes[:0]
			for _, in := range c.Inboxes {
				if in.ID != id {
					out = append(out, in)
				}
			}
			c.Inboxes = out
		})
		p.eng.Forget(id)
		if err != nil {
			p.redirect(w, r, "err", err.Error())
			return
		}
		p.log.Printf("inbox %s removed", id)
		p.redirect(w, r, "removed")
	case "autostart":
		on := f.Get("on") == "1"
		handover, err := p.autostart(on)
		if err != nil {
			p.redirect(w, r, "err", err.Error())
			return
		}
		if handover {
			p.render(w, &view{Page: "done", Message: T(p.lang, "handover"), Reload: true})
			return
		}
		if on {
			p.redirect(w, r, "")
		} else {
			p.redirect(w, r, "as_off")
		}
	case "quit":
		p.render(w, &view{Page: "done", Message: T(p.lang, "quit_done")})
		go p.quit()
	case "uninstall":
		p.render(w, &view{Page: "done", Message: T(p.lang, "uninstall_done")})
		go p.uninstall()
	default:
		http.Error(w, "not found", http.StatusNotFound)
	}
}

// postAdd: step 1 checks the code against Kalmido, step 2 (save) also creates the folder and stores the inbox.
func (p *Page) postAdd(w http.ResponseWriter, r *http.Request, save bool) {
	f := r.PostForm
	v := &view{Page: "add", Code: strings.TrimSpace(f.Get("code"))}
	c, err := decodeCode(v.Code)
	if err != nil {
		v.Error = T(p.lang, "err_code")
		if u := codeURL(v.Code); u != "" && checkServerURL(u) == errInsecureURL {
			v.Error = T(p.lang, "err_insecure")
		}
		p.render(w, v)
		return
	}
	for _, in := range p.store.Snapshot().Inboxes {
		if in.Key == c.Key {
			v.Error = T(p.lang, "err_dup")
			p.render(w, v)
			return
		}
	}
	t, res := fetchTarget(c.URL, c.Key)
	switch res.Out {
	case OutOK:
	case OutPaused:
		v.Error = T(p.lang, "paused_hint")
	case OutRetry:
		v.Error = T(p.lang, "err_net", res.Msg)
	default:
		v.Error = T(p.lang, "err_refused", res.Msg)
	}
	if v.Error != "" {
		p.render(w, v)
		return
	}
	if t.Name == "" {
		t.Name = c.Name
	}
	v.Step2, v.InboxName, v.Target = true, t.Name, t.Target
	v.Folder = strings.TrimSpace(f.Get("folder"))
	if v.Folder == "" {
		v.Folder = suggestedFolder(t.Name)
	}
	v.Autostart = !save || f.Get("autostart") == "1"
	if !save {
		p.render(w, v)
		return
	}
	folder, ok := cleanFolder(v.Folder)
	ferr := ""
	if !ok {
		ferr = T(p.lang, "err_folder_rel")
	}
	if ferr == "" {
		for _, in := range p.store.Snapshot().Inboxes {
			if samePath(in.Folder, folder) {
				ferr = T(p.lang, "err_folder_use")
			}
		}
	}
	if ferr == "" {
		if err := os.MkdirAll(folder, 0o755); err != nil {
			ferr = T(p.lang, "err_folder", err.Error())
		}
	}
	if ferr != "" {
		v.Error = ferr
		p.render(w, v)
		return
	}
	in := &Inbox{Name: t.Name, URL: c.URL, Key: c.Key, Target: t.Target, MaxMB: t.MaxMB, Folder: folder,
		UploadedDir: T(p.lang, "dir_uploaded"), RejectedDir: T(p.lang, "dir_rejected")}
	in.fillDefaults()
	if err := p.store.Update(func(c *Config) { c.Inboxes = append(c.Inboxes, in) }); err != nil {
		v.Error = T(p.lang, "n_err", err.Error())
		p.render(w, v)
		return
	}
	p.log.Printf("inbox %s (%s) set up: %s -> %s", in.ID, in.Name, in.Folder, in.Target)
	p.eng.Kick()
	if v.Autostart {
		handover, err := p.autostart(true)
		if err != nil {
			p.redirect(w, r, "err", err.Error())
			return
		}
		if handover {
			p.render(w, &view{Page: "done", Message: T(p.lang, "n_saved") + " " + T(p.lang, "handover"), Reload: true})
			return
		}
	}
	p.redirect(w, r, "saved")
}

// codeURL digs the server address out of a code that failed the checks (to tell an http:// address apart).
func codeURL(s string) string {
	s = strings.Join(strings.Fields(s), "")
	if !strings.HasPrefix(s, codePrefix) {
		return ""
	}
	c, err := decodeCodeRaw(s[len(codePrefix):])
	if err != nil {
		return ""
	}
	return strings.TrimRight(c.URL, "/")
}

func suggestedFolder(name string) string {
	home, err := os.UserHomeDir()
	if err != nil {
		home = "."
	}
	return filepath.Join(home, "Kalmido Scans", safeFolderName(name))
}

// safeFolderName keeps a name usable as one folder on every system.
func safeFolderName(s string) string {
	s = strings.Map(func(r rune) rune {
		if r < 32 || strings.ContainsRune(`<>:"/\|?*`, r) {
			return '-'
		}
		return r
	}, strings.TrimSpace(s))
	s = strings.Trim(s, ". ")
	if s == "" {
		return "Scans"
	}
	return s
}

// cleanFolder: "~" expanded, absolute path required.
func cleanFolder(s string) (string, bool) {
	if s == "~" || strings.HasPrefix(s, "~/") || strings.HasPrefix(s, `~\`) {
		if h, err := os.UserHomeDir(); err == nil {
			s = filepath.Join(h, s[1:])
		}
	}
	if !filepath.IsAbs(s) {
		return "", false
	}
	s = filepath.Clean(s)
	// not the home folder itself or a drive root: every file there would be uploaded and moved
	if h, err := os.UserHomeDir(); err == nil && samePath(s, h) || filepath.Dir(s) == s {
		return "", false
	}
	return s, true
}

func samePath(a, b string) bool {
	a, b = filepath.Clean(a), filepath.Clean(b)
	if runtime.GOOS == "windows" || runtime.GOOS == "darwin" {
		return strings.EqualFold(a, b)
	}
	return a == b
}

// view is the data of one rendered page.
type view struct {
	Page                         string
	Notice, Error                string
	Code, InboxName, Target      string
	Folder                       string
	Step2, Autostart             bool
	Question, Action, ID, Button string
	Message                      string
	Reload                       bool
	// filled by render
	L, T, Base string
	Inboxes    []InboxView
	AutoOn     bool
	Installed  bool
	Mac        bool
	Version    string
	Dir        string
	UpDir      string
}

func (p *Page) render(w http.ResponseWriter, v *view) {
	v.L, v.T, v.Base, v.Version, v.Dir = p.lang, p.secret, p.base(), version, p.store.dir
	v.Mac = runtime.GOOS == "darwin"
	v.UpDir = T(p.lang, "dir_uploaded")
	if v.Page == "status" {
		for _, in := range p.store.Snapshot().Inboxes {
			v.Inboxes = append(v.Inboxes, p.eng.View(in))
		}
		v.AutoOn, v.Installed = autostartActive(), p.isInstalled()
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	if err := pageTmpl.Execute(w, v); err != nil {
		p.log.Printf("page: %v", err)
	}
}

var pageTmpl = template.Must(template.New("page").Funcs(template.FuncMap{
	"t":     func(lang, key string, args ...any) string { return T(lang, key, args...) },
	"clock": func(t time.Time) string { return t.Local().Format("15:04") },
	"when": func(t time.Time) string {
		if y, m, d := t.Local().Date(); time.Now().Year() == y && time.Now().Month() == m && time.Now().Day() == d {
			return t.Local().Format("15:04:05")
		}
		return t.Local().Format("02.01. 15:04")
	},
	"future": func(t time.Time) bool { return t.After(time.Now()) },
	"evtext": func(lang string, in Inbox, e Event) string {
		switch {
		case e.OK:
			return T(lang, "ev_ok")
		case e.Reason == "too_big":
			return T(lang, "too_big", in.MaxMB)
		case e.Moved:
			return T(lang, "ev_rejected", in.RejectedDir, e.Reason)
		}
		return T(lang, "ev_err", e.Reason)
	},
}).Parse(pageHTML))
