// 2.207.0 B (#2763): the packing step of the Docker build stage - deterministic zips with an executable entry (the Mac
// files keep their exec bit), SHA256SUMS, and the check that a darwin/arm64 file carries the ad-hoc code signature
// (without it Apple chips refuse to start it at all).
//
//	pack zip <src> <dst.zip> <name in zip>
//	pack checksign <mach-o file>
//	pack sums <dir>                    writes <dir>/SHA256SUMS over all other files
package main

import (
	"archive/zip"
	"crypto/sha256"
	"debug/macho"
	"encoding/hex"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"time"
)

const lcCodeSignature = 0x1d

// fixed time for every zip entry, so the same input gives the same bytes
var zipTime = time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)

func main() {
	if len(os.Args) < 3 {
		usage()
	}
	var err error
	switch os.Args[1] {
	case "zip":
		if len(os.Args) != 5 {
			usage()
		}
		err = zipOne(os.Args[2], os.Args[3], os.Args[4])
	case "checksign":
		err = checkSign(os.Args[2])
	case "sums":
		err = writeSums(os.Args[2])
	default:
		usage()
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "pack:", err)
		os.Exit(1)
	}
}

func usage() {
	fmt.Fprintln(os.Stderr, "usage: pack zip <src> <dst.zip> <name> | checksign <file> | sums <dir>")
	os.Exit(2)
}

func zipOne(src, dst, name string) error {
	in, err := os.Open(src)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	zw := zip.NewWriter(out)
	h := &zip.FileHeader{Name: name, Method: zip.Deflate, Modified: zipTime}
	h.SetMode(0o755)
	w, err := zw.CreateHeader(h)
	if err == nil {
		_, err = io.Copy(w, in)
	}
	if err == nil {
		err = zw.Close()
	}
	if cerr := out.Close(); err == nil {
		err = cerr
	}
	return err
}

// hasCodeSignature: a Mach-O file with an LC_CODE_SIGNATURE load command.
func hasCodeSignature(f *macho.File) bool {
	for _, l := range f.Loads {
		raw := l.Raw()
		if len(raw) >= 4 && f.ByteOrder.Uint32(raw[:4]) == lcCodeSignature {
			return true
		}
	}
	return false
}

func checkSign(path string) error {
	f, err := macho.Open(path)
	if err != nil {
		return err
	}
	defer f.Close()
	if !hasCodeSignature(f) {
		return fmt.Errorf("%s: no LC_CODE_SIGNATURE (an Apple chip would refuse to start it)", path)
	}
	fmt.Println(filepath.Base(path) + ": code signature present")
	return nil
}

func writeSums(dir string) error {
	ents, err := os.ReadDir(dir)
	if err != nil {
		return err
	}
	var names []string
	for _, e := range ents {
		if e.Type().IsRegular() && e.Name() != "SHA256SUMS" {
			names = append(names, e.Name())
		}
	}
	sort.Strings(names)
	var out []byte
	for _, n := range names {
		f, err := os.Open(filepath.Join(dir, n))
		if err != nil {
			return err
		}
		h := sha256.New()
		_, err = io.Copy(h, f)
		f.Close()
		if err != nil {
			return err
		}
		out = append(out, hex.EncodeToString(h.Sum(nil))+"  "+n+"\n"...)
	}
	return os.WriteFile(filepath.Join(dir, "SHA256SUMS"), out, 0o644)
}
