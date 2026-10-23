// 2.207.0 B (#2763): the zips are deterministic and keep the exec bit; SHA256SUMS lists every file.
package main

import (
	"archive/zip"
	"bytes"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestZipDeterministicExecutable(t *testing.T) {
	d := t.TempDir()
	src := filepath.Join(d, "bin")
	os.WriteFile(src, []byte("binary"), 0o700)
	a, b := filepath.Join(d, "a.zip"), filepath.Join(d, "b.zip")
	if err := zipOne(src, a, "kalmido-folder-watcher"); err != nil {
		t.Fatal(err)
	}
	if err := zipOne(src, b, "kalmido-folder-watcher"); err != nil {
		t.Fatal(err)
	}
	x, _ := os.ReadFile(a)
	y, _ := os.ReadFile(b)
	if !bytes.Equal(x, y) {
		t.Fatal("zip not deterministic")
	}
	r, err := zip.OpenReader(a)
	if err != nil {
		t.Fatal(err)
	}
	defer r.Close()
	if len(r.File) != 1 || r.File[0].Name != "kalmido-folder-watcher" || r.File[0].Mode().Perm() != 0o755 {
		t.Fatalf("entry %+v", r.File)
	}
}

func TestSums(t *testing.T) {
	d := t.TempDir()
	os.WriteFile(filepath.Join(d, "b"), []byte("b"), 0o644)
	os.WriteFile(filepath.Join(d, "a"), []byte("a"), 0o644)
	if err := writeSums(d); err != nil {
		t.Fatal(err)
	}
	s, _ := os.ReadFile(filepath.Join(d, "SHA256SUMS"))
	lines := strings.Split(strings.TrimSpace(string(s)), "\n")
	if len(lines) != 2 || !strings.HasSuffix(lines[0], "  a") || !strings.HasPrefix(lines[0], "ca978112ca1bbdcafac231b39a23dc4da786eff8147c4e72b9807785afee48bb") {
		t.Fatalf("%q", s)
	}
}
