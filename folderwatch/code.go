// 2.207.0 B (#2763): the setup code "kalmido-scan:1:<base64url JSON>" that Kalmido shows once after creating an inbox.
package main

import (
	"encoding/base64"
	"encoding/json"
	"errors"
	"net"
	"net/url"
	"strings"
)

const codePrefix = "kalmido-scan:1:"

// SetupCode is the decoded content of a setup code.
type SetupCode struct {
	URL  string `json:"url"`
	Key  string `json:"key"`
	Name string `json:"name"`
}

var errBadCode = errors.New("bad code")

// decodeCode parses a pasted setup code (surrounding blanks and line breaks inside are tolerated).
func decodeCode(s string) (SetupCode, error) {
	var c SetupCode
	s = strings.Join(strings.Fields(s), "")
	if !strings.HasPrefix(s, codePrefix) {
		return c, errBadCode
	}
	c, err := decodeCodeRaw(s[len(codePrefix):])
	if err != nil {
		return c, err
	}
	c.URL = strings.TrimRight(strings.TrimSpace(c.URL), "/")
	c.Key = strings.TrimSpace(c.Key)
	c.Name = strings.TrimSpace(c.Name)
	if c.Key == "" || strings.ContainsAny(c.Key, " \t\r\n") || checkServerURL(c.URL) != nil {
		return c, errBadCode
	}
	if c.Name == "" {
		c.Name = "Scans"
	}
	return c, nil
}

// decodeCodeRaw decodes the base64url JSON part without any checks.
func decodeCodeRaw(b64 string) (SetupCode, error) {
	var c SetupCode
	raw, err := base64.RawURLEncoding.DecodeString(strings.TrimRight(b64, "="))
	if err != nil || json.Unmarshal(raw, &c) != nil {
		return c, errBadCode
	}
	return c, nil
}

var errInsecureURL = errors.New("insecure url")

// checkServerURL: https only; plain http only for this computer (tests, a local instance).
func checkServerURL(s string) error {
	u, err := url.Parse(s)
	if err != nil || u.Host == "" || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return errBadCode
	}
	switch u.Scheme {
	case "https":
		return nil
	case "http":
		h := u.Hostname()
		if h == "localhost" {
			return nil
		}
		if ip := net.ParseIP(h); ip != nil && ip.IsLoopback() {
			return nil
		}
	}
	return errInsecureURL
}
