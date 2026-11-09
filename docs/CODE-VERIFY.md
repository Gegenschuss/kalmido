# Checking the code your browser runs

Kalmido is a web app: every time you open it, your browser gets its code (scripts, styles, the app page, the texts) from the
server you use. This page explains how to check that this code is the published code of a version, and where the limits
of such a check are.

*Kurz auf Deutsch:* Unter *Einstellungen > Hilfe > Code prüfen* zeigt Kalmido die Version und einen Hash des Codes, den
dieser Browser bekommen hat. Denselben Wert findest du in der Datei `SHA256SUMS` der GitHub-Veröffentlichung dieser Version
in der Zeile `web-manifest-X.Y.Z.json`. Gleich = dein Browser hat den veröffentlichten Code (soweit er im Browser liegt).
Die Anzeige kommt vom selben Server wie der Code: Sie erkennt Fehler und Ausrutscher, nicht einen Betreiber, der gezielt
täuscht. Dafür ist der Weg von Hand unten da, auf einem Gerät und mit Werkzeugen, die nicht vom Server kommen.

## What a release publishes

Since 2.742.0 every weekly release on GitHub carries `web-manifest-X.Y.Z.json`: the full SHA-256 of every file the browser
gets from that version, exactly as the server sends it (scripts and styles without comments, the rendered app page, the
language parts). The release workflow builds it twice from the tagged source and stops on any difference; since 2.761.0 it
is signed with a GitHub build attestation (`gh attestation verify web-manifest-X.Y.Z.json -R github.com/Gegenschuss/kalmido`).
The SHA-256 of the manifest file itself stands in the release's `SHA256SUMS`.

A server answers `GET /api/code-manifest` (no sign-in) with the same bytes, computed from what it really sends. Only one
version per week gets a release; for any other version you can build the manifest from the tag yourself:

```
git clone https://github.com/Gegenschuss/kalmido && cd kalmido && git checkout vX.Y.Z
python3 tools/web_manifest.py -o web-manifest-X.Y.Z.json
sha256sum web-manifest-X.Y.Z.json
```

## The check in the app (Settings > Help > Check code)

*Check code* loads the server's manifest, hashes every file of it that lies in the app's offline store of this browser
(the service worker's cache, the bytes this browser was given) and puts its own hash in place of the server's. It writes
the result in the same form as the release file and shows the SHA-256 of it, with the version, *Copy hash* and a link to the
release of that version. Nothing is fetched from GitHub; you compare by eye or with the copied value:

1. Press *Check code*, then *Copy hash*.
2. Open the release (the link next to it), download `SHA256SUMS` and find the line `web-manifest-X.Y.Z.json`.
3. The same hash: every file this browser holds is the published one. Another hash: the section names the files that
   differ from the server's list; if none differs, the server's list itself is not the published one.

Files that are not in this browser (modules you never opened, other languages) are named *not checked*: for them the
server's value is used.

**The limit, said plainly:** this display comes from the same server as the code. It catches mistakes and slips (a wrong
build, a file changed by hand, an incomplete update), not an operator who means to deceive: such a server could also send a
check page that lies. For that, check from outside, with tools that do not come from the server (below).

## The warning of the service worker

The app's service worker keeps the version and the content hash of every file it stores. When the server later sends other
hashes under the same version (the code changed without a new version), the app shows the hint *The app's code changed
without a new version* with a way to *Check code*. The browser always loads the service worker itself from the server (it
cannot be pinned), so this warning has the same limit as the check page.

## The manual way (from outside)

On a computer, without trusting anything the server says about itself:

1. Note the version (Settings > Help).
2. Fetch the files and hash them with your own tools, for example:
   ```
   curl -s https://your-server/static/js/core.js | sha256sum
   curl -s https://your-server/api/code-manifest -o served.json && sha256sum served.json
   ```
   or in the browser: developer tools > Network, save a response, then `sha256sum` on the saved file.
3. Compare each hash with the entry of that file in `web-manifest-X.Y.Z.json` of the release (or the one you built from the
   tag), and the hash of `served.json` with the line in `SHA256SUMS`.
4. Optional: `gh attestation verify web-manifest-X.Y.Z.json -R github.com/Gegenschuss/kalmido` shows that the release
   workflow of this repository built the manifest from the tagged commit.

A server behind a sign-in proxy may ask for the sign-in first; `/api/code-manifest`, `/sw.js` and `/static/` answer without
a Kalmido session.
