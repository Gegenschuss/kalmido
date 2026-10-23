# Kalmido folder watcher

A small program for Mac, Windows and Linux that watches one or more folders on your computer (for example the folder
your scanner software saves into) and uploads every finished file into Kalmido as a document. One file per platform,
no installation, Go standard library only.

## Use

1. In Kalmido open Settings > Documents > Folder watcher, create an inbox and copy its setup code.
2. Start the program (double-click). A local page opens in the browser; paste the code, pick the folder.
3. With autostart on, the program copies itself into its settings folder and starts at every login. Double-clicking it
   again opens the page: status, recent uploads, retry, remove an inbox, quit, uninstall.

Uploaded files move into the subfolder "Uploaded" ("Hochgeladen" in German), files Kalmido does not accept into
"Not uploaded". Without network the files stay and are retried later. Hidden and temporary files are ignored; a file
counts as finished when its size and time stay the same for at least four seconds.

Settings (`config.json`, mode 0600), the duplicate guard journal and a small log live in
`~/Library/Application Support/Kalmido Folder Watcher` (Mac), `%APPDATA%\Kalmido Folder Watcher` (Windows) or
`$XDG_CONFIG_HOME/kalmido-folder-watcher` (Linux).

## Security

- The key of an inbox can only upload documents into one target (private space or organisation, optionally a folder);
  it cannot read anything. Revoke it in Kalmido at any time.
- The page listens on 127.0.0.1 only, under a random secret path; it checks the Host header and accepts form posts only
  from itself (no cross-site requests, no DNS rebinding).
- The server address must use https (plain http only for this computer).

## Unsigned builds

The files are not signed with an Apple or Microsoft certificate.

- macOS: the first start is blocked. Open System Settings > Privacy & Security and choose "Open Anyway" (or right-click
  the file > Open). Keep the watched folder outside Documents / Desktop to avoid an extra permission prompt.
- Windows: SmartScreen may warn about an unknown publisher; choose "More info" > "Run anyway".

Compare the download with `SHA256SUMS` next to it.

## Build

The Kalmido `Dockerfile` builds, tests and packs all files (`go vet`, `go test`, then `cmd/pack`). By hand:

```sh
go test ./...
CGO_ENABLED=0 GOOS=darwin GOARCH=arm64 go build -trimpath -ldflags "-s -w -X main.version=dev" -o kalmido-folder-watcher .
CGO_ENABLED=0 GOOS=windows GOARCH=amd64 go build -trimpath -ldflags "-s -w -H windowsgui -X main.version=dev" -o kalmido-folder-watcher.exe .
```

`kalmido-folder-watcher --once --config <file>` runs one upload round without the page and the autostart (scripts, tests).
