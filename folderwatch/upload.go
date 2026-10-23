// 2.207.0 B (#2763): the two calls of an upload key - GET /api/v1/documents/upload-target and POST /api/v1/documents
// (multipart field "file", streamed from disk with an exact Content-Length).
package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"mime/multipart"
	"net/http"
	"net/textproto"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

// Outcome of one call, the handling follows the table of the interface.
type Outcome int

const (
	OutOK      Outcome = iota
	OutRetry           // network, 429, 5xx: leave the file, back off
	OutPaused          // 401: key invalid or revoked, the inbox stops
	OutBlocked         // 403, 409, 413 and other refusals: leave the file, retry every 30 minutes
	OutReject          // 400, 415: the file is not acceptable, move it to "Not uploaded"
)

// Result of a call: the outcome, the server's message (or the network error) and an optional Retry-After.
type Result struct {
	Out        Outcome
	Status     int
	Msg        string
	RetryAfter time.Duration
	ID         int64
	Name       string
}

// Target is the answer of upload-target.
type Target struct {
	Name   string `json:"name"`
	Target string `json:"target"`
	MaxMB  int    `json:"max_mb"`
}

// No redirects: the key goes only to the address of the setup code (a 3xx answer counts as blocked).
var httpClient = &http.Client{Timeout: 30 * time.Minute,
	CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}

func userAgent() string { return "kalmido-folder-watcher/" + version }

func classify(code int) Outcome {
	switch {
	case code == http.StatusOK || code == http.StatusCreated:
		return OutOK
	case code == http.StatusUnauthorized:
		return OutPaused
	case code == http.StatusBadRequest || code == http.StatusUnsupportedMediaType:
		return OutReject
	case code == http.StatusTooManyRequests || code >= 500:
		return OutRetry
	default:
		return OutBlocked
	}
}

// serverMessage reads {"error": {"code": "...", "message": "..."}} or {"error": "..."} (or a short text) from an answer.
func serverMessage(body []byte) string {
	var e struct {
		Error json.RawMessage `json:"error"`
	}
	if json.Unmarshal(body, &e) == nil && len(e.Error) > 0 {
		var s string
		if json.Unmarshal(e.Error, &s) == nil && s != "" {
			return s
		}
		var o struct {
			Code    string `json:"code"`
			Message string `json:"message"`
		}
		if json.Unmarshal(e.Error, &o) == nil {
			if o.Message != "" {
				return o.Message
			}
			if o.Code != "" {
				return o.Code
			}
		}
	}
	s := strings.TrimSpace(string(body))
	if strings.HasPrefix(s, "<") || len(s) > 200 {
		return ""
	}
	return s
}

func retryAfter(h http.Header) time.Duration {
	if n, err := strconv.Atoi(strings.TrimSpace(h.Get("Retry-After"))); err == nil && n > 0 {
		return time.Duration(n) * time.Second
	}
	return 0
}

func doRequest(req *http.Request, key string) (Result, []byte) {
	req.Header.Set("Authorization", "Bearer "+key)
	req.Header.Set("User-Agent", userAgent())
	req.Header.Set("Accept", "application/json")
	resp, err := httpClient.Do(req)
	if err != nil {
		return Result{Out: OutRetry, Msg: err.Error()}, nil
	}
	defer resp.Body.Close()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 64*1024))
	r := Result{Out: classify(resp.StatusCode), Status: resp.StatusCode, RetryAfter: retryAfter(resp.Header)}
	if r.Out != OutOK {
		r.Msg = serverMessage(body)
		if r.Msg == "" {
			r.Msg = "HTTP " + strconv.Itoa(resp.StatusCode)
		}
	}
	return r, body
}

// fetchTarget checks a key and returns where its uploads land.
func fetchTarget(base, key string) (Target, Result) {
	var t Target
	if err := checkServerURL(base); err != nil {
		return t, Result{Out: OutBlocked, Msg: err.Error()}
	}
	req, err := http.NewRequest(http.MethodGet, base+"/api/v1/documents/upload-target", nil)
	if err != nil {
		return t, Result{Out: OutBlocked, Msg: err.Error()}
	}
	r, body := doRequest(req, key)
	if r.Out == OutOK && json.Unmarshal(body, &t) != nil {
		r = Result{Out: OutBlocked, Status: r.Status, Msg: "unexpected answer"}
	}
	return t, r
}

var errChanged = errors.New("file changed while uploading")

// uploadFile sends one file. The body is the multipart prefix, the file itself and the closing boundary, so the
// file is never read into memory and the request has an exact Content-Length.
func uploadFile(base, key, path string) Result {
	if err := checkServerURL(base); err != nil {
		return Result{Out: OutBlocked, Msg: err.Error()}
	}
	f, err := os.Open(path)
	if err != nil {
		return Result{Out: OutRetry, Msg: err.Error()}
	}
	defer f.Close()
	st, err := f.Stat()
	if err != nil {
		return Result{Out: OutRetry, Msg: err.Error()}
	}
	var head bytes.Buffer
	mw := multipart.NewWriter(&head)
	name := filepath.Base(path)
	ct := mime.TypeByExtension(strings.ToLower(filepath.Ext(name)))
	if ct == "" {
		ct = "application/octet-stream"
	}
	h := make(textproto.MIMEHeader)
	h.Set("Content-Disposition", fmt.Sprintf(`form-data; name="file"; filename="%s"`, escapeQuotes(name)))
	h.Set("Content-Type", ct)
	if _, err := mw.CreatePart(h); err != nil {
		return Result{Out: OutBlocked, Msg: err.Error()}
	}
	tail := "\r\n--" + mw.Boundary() + "--\r\n"
	size := st.Size()
	body := io.MultiReader(bytes.NewReader(head.Bytes()), &exactReader{r: f, left: size}, strings.NewReader(tail))
	req, err := http.NewRequest(http.MethodPost, base+"/api/v1/documents", body)
	if err != nil {
		return Result{Out: OutBlocked, Msg: err.Error()}
	}
	req.ContentLength = int64(head.Len()) + size + int64(len(tail))
	req.Header.Set("Content-Type", mw.FormDataContentType())
	r, rb := doRequest(req, key)
	if r.Out == OutOK {
		var d struct {
			ID   int64  `json:"id"`
			Name string `json:"name"`
		}
		_ = json.Unmarshal(rb, &d)
		r.ID, r.Name = d.ID, d.Name
	}
	return r
}

// exactReader yields exactly left bytes of r, an error when the file got shorter meanwhile.
type exactReader struct {
	r    io.Reader
	left int64
}

func (e *exactReader) Read(p []byte) (int, error) {
	if e.left <= 0 {
		return 0, io.EOF
	}
	if int64(len(p)) > e.left {
		p = p[:e.left]
	}
	n, err := e.r.Read(p)
	e.left -= int64(n)
	if err == io.EOF && e.left > 0 {
		return n, errChanged
	}
	if err == io.EOF {
		err = nil
	}
	return n, err
}

var quoteEscaper = strings.NewReplacer("\\", "\\\\", `"`, "\\\"", "\r", "", "\n", "")

func escapeQuotes(s string) string { return quoteEscaper.Replace(s) }
