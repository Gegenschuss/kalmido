// 2.207.0 B (#2763): Kalmido folder watcher - watches folders on this computer (e.g. where a ScanSnap saves its scans)
// and uploads every finished file into Kalmido with an upload-only key. One file per platform, standard library only.
//
//	kalmido-folder-watcher                  start (or open the page of the running instance) and open the page
//	kalmido-folder-watcher --background     start without opening the page (autostart)
//	kalmido-folder-watcher --once --config F one upload round for the inboxes in F, then exit (tests, scripts)
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"net/http"
	"os"
	"os/signal"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"syscall"
	"time"
)

var version = "dev"

func main() {
	once := flag.Bool("once", false, "one upload round, then exit (no page, no autostart)")
	background := flag.Bool("background", false, "do not open the page in the browser")
	cfgPath := flag.String("config", "", "path of config.json (default: the settings folder of this system)")
	showVersion := flag.Bool("version", false, "print the version")
	flag.Parse()
	if *showVersion {
		fmt.Println("kalmido-folder-watcher", version)
		return
	}
	path := *cfgPath
	if path == "" {
		dir, err := defaultConfigDir()
		if err != nil {
			fail(err)
		}
		path = filepath.Join(dir, "config.json")
	}
	store, err := openStore(path)
	if err != nil {
		fail(err)
	}
	if *once {
		os.Exit(runOnce(store))
	}
	os.Exit(runService(store, *background))
}

func fail(err error) {
	fmt.Fprintln(os.Stderr, "kalmido-folder-watcher:", err)
	os.Exit(1)
}

// runOnce: polls until the stability window is over, prints one line per inbox; exit 0 = nothing left waiting.
func runOnce(store *Store) int {
	eng := newEngine(store, newLogger(store.dir, true))
	for i := 0; i < 4; i++ {
		if i > 0 {
			time.Sleep(stableFor/2 + 100*time.Millisecond)
		}
		eng.Round()
	}
	code := 0
	for _, in := range store.Snapshot().Inboxes {
		v := eng.View(in)
		up, bad := 0, 0
		for _, e := range v.Events {
			if e.OK {
				up++
			} else {
				bad++
			}
		}
		fmt.Printf("inbox %q: state=%s uploaded=%d failed=%d waiting=%d %s\n", in.Name, v.State, up, bad, len(v.Waiting), v.Msg)
		if v.State != StReady || len(v.Waiting) > 0 || bad > 0 {
			code = 2
		}
	}
	return code
}

// installedPath: the copy of the program the autostart runs (inside the settings folder, so tidying Downloads breaks nothing).
func installedPath(store *Store) string { return filepath.Join(store.dir, "bin", exeName()) }

func isInstalledCopy(store *Store) bool {
	exe, err := os.Executable()
	if err != nil {
		return false
	}
	if r, err := filepath.EvalSymlinks(exe); err == nil {
		exe = r
	}
	return samePath(exe, installedPath(store))
}

// installSelf copies the running program to installedPath (write .new, rename).
func installSelf(store *Store) (string, error) {
	dst := installedPath(store)
	if isInstalledCopy(store) {
		return dst, nil
	}
	exe, err := os.Executable()
	if err != nil {
		return "", err
	}
	if err := os.MkdirAll(filepath.Dir(dst), 0o700); err != nil {
		return "", err
	}
	src, err := os.Open(exe)
	if err != nil {
		return "", err
	}
	defer src.Close()
	tmp := dst + ".new"
	out, err := os.OpenFile(tmp, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o755)
	if err != nil {
		return "", err
	}
	if _, err := io.Copy(out, src); err != nil {
		out.Close()
		os.Remove(tmp)
		return "", err
	}
	if err := out.Close(); err != nil {
		return "", err
	}
	_ = os.Remove(dst)
	if err := os.Rename(tmp, dst); err != nil {
		return "", err
	}
	return dst, nil
}

// pageSecret: kept in the settings folder, so the page address stays the same when the autostart copy takes over.
func pageSecret(store *Store) string {
	p := filepath.Join(store.dir, "page-secret")
	if b, err := os.ReadFile(p); err == nil {
		if s := strings.TrimSpace(string(b)); len(s) == 48 {
			return s
		}
	}
	s := randomHex(24)
	_ = writeFileAtomic(p, []byte(s), 0o600)
	return s
}

// pingInstance: is our own program answering on that port with that secret?
func pingInstance(port int, secret string) bool {
	c := &http.Client{Timeout: 2 * time.Second}
	resp, err := c.Get("http://127.0.0.1:" + strconv.Itoa(port) + "/s/" + secret + "/ping")
	if err != nil {
		return false
	}
	defer resp.Body.Close()
	b, _ := io.ReadAll(io.LimitReader(resp.Body, 256))
	return resp.StatusCode == http.StatusOK && strings.HasPrefix(string(b), "kalmido-folder-watcher")
}

func runService(store *Store, background bool) int {
	log := newLogger(store.dir, false)
	secret := pageSecret(store)
	port := defaultPort
	var ln net.Listener
	var err error
	tries := 1
	if background {
		tries = 15 // the copy that takes over waits for the old instance to let the port go
	}
	for i := 0; i < tries; i++ {
		ln, err = net.Listen("tcp", "127.0.0.1:"+strconv.Itoa(port))
		if err == nil {
			break
		}
		if pingInstance(port, secret) {
			if background {
				return 0
			}
			_ = openURL("http://127.0.0.1:" + strconv.Itoa(port) + "/s/" + secret + "/")
			return 0
		}
		if i+1 < tries {
			time.Sleep(time.Second)
		}
	}
	if err != nil {
		// another program holds the port: a free one, the page opens there
		log.Printf("port %d busy (%v), using a free port", port, err)
		if ln, err = net.Listen("tcp", "127.0.0.1:0"); err != nil {
			log.Printf("no local port: %v", err)
			return 1
		}
		port = ln.Addr().(*net.TCPAddr).Port
	}
	lang := pickLang(systemLang())
	eng := newEngine(store, log)
	stop := make(chan struct{})
	var stopOnce sync.Once
	srv := &http.Server{ReadHeaderTimeout: 10 * time.Second}
	shutdown := func() {
		stopOnce.Do(func() {
			close(stop)
			ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
			defer cancel()
			_ = srv.Shutdown(ctx)
		})
	}
	exitCode := 0
	var after func()
	page := &Page{store: store, eng: eng, log: log, lang: lang, secret: secret, port: port}
	page.isInstalled = func() bool { return isInstalledCopy(store) }
	page.quit = func() {
		time.Sleep(300 * time.Millisecond)
		log.Printf("quit from the page")
		shutdown()
	}
	page.uninstall = func() {
		time.Sleep(300 * time.Millisecond)
		log.Printf("uninstall from the page")
		_ = autostartDisable()
		after = func() { uninstallFiles(store) }
		shutdown()
	}
	page.autostart = func(on bool) (bool, error) {
		if !on {
			err := autostartDisable()
			if err == nil {
				_ = store.Update(func(c *Config) { c.Autostart = false })
				log.Printf("autostart off")
			}
			return false, err
		}
		dst, err := installSelf(store)
		if err != nil {
			return false, err
		}
		_ = store.Update(func(c *Config) { c.Autostart = true })
		if isInstalledCopy(store) {
			return false, autostartWrite(dst)
		}
		// hand over to the installed copy: this instance stops, the autostart entry starts the copy
		log.Printf("autostart on, handing over to %s", dst)
		go func() {
			time.Sleep(time.Second)
			after = func() {
				if err := autostartEnable(dst); err != nil {
					log.Printf("autostart: %v", err)
				} else if !background {
					fmt.Println(T(lang, "con_handover"))
				}
			}
			shutdown()
		}()
		return true, nil
	}
	srv.Handler = page
	sig := make(chan os.Signal, 1)
	signal.Notify(sig, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sig
		shutdown()
	}()
	go eng.Loop(stop)
	log.Printf("started %s on %s", version, ln.Addr())
	if !background {
		fmt.Println(T(lang, "con_running", page.URL()))
		_ = openURL(page.URL())
	}
	if err := srv.Serve(ln); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Printf("page: %v", err)
		exitCode = 1
	}
	shutdown()
	if after != nil {
		after()
	}
	log.Printf("stopped")
	if !background && after == nil {
		fmt.Println(T(lang, "con_stopped"))
	}
	return exitCode
}

// uninstallFiles removes the installed copy and the settings folder (keys, journal, log), then unloads the autostart.
func uninstallFiles(store *Store) {
	exe := installedPath(store)
	for _, n := range []string{"config.json", "journal.json", "page-secret", "log.txt", "log.1.txt"} {
		_ = os.Remove(filepath.Join(store.dir, n))
	}
	removeSelfLater(exe)
	_ = os.Remove(filepath.Dir(exe))
	_ = os.Remove(store.dir)
	autostartUnload()
}
