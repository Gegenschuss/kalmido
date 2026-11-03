# Third-party notices

## Geist and Geist Mono fonts

The interface fonts in `static/fonts/` (`Geist-Variable.woff2`, `GeistMono-Variable.woff2`, from the
[`geist`](https://www.npmjs.com/package/geist) package 1.7.2, [vercel/geist-font](https://github.com/vercel/geist-font))
are Copyright (c) 2023 Vercel, in collaboration with basement.studio, and licensed under the
SIL Open Font License, Version 1.1. The full license text ships next to the fonts as `static/fonts/OFL.txt`.
They are served by Kalmido itself; the browser never loads fonts from a third party.

## Atkinson Hyperlegible font

The optional interface font in `static/fonts/` (`AtkinsonHyperlegible-Regular.woff2`, `-Bold`, `-Italic`,
`-BoldItalic`, latin subset from the [`@fontsource/atkinson-hyperlegible`](https://www.npmjs.com/package/@fontsource/atkinson-hyperlegible)
package 5.3.0) is Copyright 2020 Braille Institute of America, Inc., and licensed under the SIL Open Font License,
Version 1.1. The full license text ships next to the fonts as `static/fonts/OFL-AtkinsonHyperlegible.txt`.
It is only downloaded when chosen under Settings > Appearance, and served by Kalmido itself.

## pdf.js (PDF preview)

The in-app PDF preview (2.48.0) uses [pdf.js](https://mozilla.github.io/pdf.js/) by the Mozilla Foundation, from the
[`pdfjs-dist`](https://www.npmjs.com/package/pdfjs-dist) package 6.4.299, licensed under the Apache License, Version 2.0.
Unchanged copies of `legacy/build/pdf.min.mjs` and `legacy/build/pdf.worker.min.mjs` (the build for older browsers) ship in `static/vendor/pdfjs/` together with the
full license text (`LICENSE`) and a `README` with the source and checksums. They are served by Kalmido itself and only
loaded when a PDF is opened; the browser never loads them from a third party.

## KaTeX and Mermaid (formulas and diagrams in knowledge pages)

Formulas in knowledge pages (2.382.0) are typeset by [KaTeX](https://katex.org/) (Copyright Khan Academy and other
contributors, MIT License), from the [`katex`](https://www.npmjs.com/package/katex) package 0.19.1: unchanged copies of
`dist/katex.min.js`, `dist/katex.min.css` and the `woff2` fonts ship in `static/vendor/katex/`.
Diagrams are drawn by [Mermaid](https://mermaid.js.org/) (Copyright Knut Sveidqvist and contributors, MIT License), from the
[`mermaid`](https://www.npmjs.com/package/mermaid) package 12.2.0: an unchanged copy of `dist/mermaid.min.js` (which bundles
its own dependencies with their notices) ships in `static/vendor/mermaid/`.
Both folders hold the full license text (`LICENSE`) and a `README` with the source and checksums. They are served by
Kalmido itself and only loaded when a page has a formula or a diagram; the browser never loads them from a third party.

## Python packages (installed at build time, not bundled)

- Flask (BSD-3-Clause)
- Werkzeug (BSD-3-Clause)
- waitress (ZPL 2.1)
- python-dateutil (Apache-2.0 / BSD-3-Clause)
- tzdata (Apache-2.0)
- cryptography (Apache-2.0 / BSD-3-Clause)
- icalendar (BSD-2-Clause)
- recurring-ical-events (LGPL-3.0-or-later), used unmodified as an installed library; source:
  [niccokunzmann/python-recurring-ical-events](https://github.com/niccokunzmann/python-recurring-ical-events)
- x-wr-timezone (LGPL-3.0-or-later), dependency of recurring-ical-events, used unmodified; source:
  [niccokunzmann/x-wr-timezone](https://github.com/niccokunzmann/x-wr-timezone)
- click (BSD-3-Clause), dependency of x-wr-timezone
- Pillow (MIT-CMU / HPND), profile photos (resize, orientation, metadata removal)
- pypdf (BSD-3-Clause), reads the text layer of PDF attachments for agents and the briefing field
- xlrd (BSD-3-Clause), reads old Excel files (.xls) in the legacy import of the office (2.185.0)
- psycopg, psycopg-binary and psycopg-pool (LGPL-3.0-only), the PostgreSQL driver, used unmodified as installed libraries;
  source: [psycopg/psycopg](https://github.com/psycopg/psycopg) and [psycopg/psycopg-pool](https://github.com/psycopg/psycopg-pool).
  psycopg-binary bundles libpq (PostgreSQL License) and OpenSSL (Apache-2.0)
- webauthn (BSD-3-Clause), passkeys
- cbor2 (MIT), passkey data
- segno (BSD-3-Clause), QR codes
- pyasn1 and pyasn1-modules (BSD-2-Clause), pyOpenSSL (Apache-2.0), dependencies of webauthn
- typing-extensions (PSF-2.0)
- brotli (MIT), packs JS and CSS ahead of time while the image is built, not part of the image itself
- Dependencies installed along with the above: Jinja2, MarkupSafe, itsdangerous, blinker, cffi, pycparser, six (BSD-3-Clause / MIT)

The version of every package is pinned in the `Dockerfile`; each package carries its license file in the image.

## System packages in the image (Debian)

The published image is based on Debian and installs, among others, poppler-utils (GPL-2.0 / GPL-3.0), tesseract-ocr
(Apache-2.0), libzbar0t64 (LGPL-2.1), postgresql-client-17 (PostgreSQL License) and openssh-client (BSD). Their license
texts are in the image under `/usr/share/doc/<package>/copyright`, the sources at [sources.debian.org](https://sources.debian.org).

## Optional embedding service kalmido-embed (embed/, 2.59.0)

Built only with `docker compose --profile embed`; not part of the Kalmido image.

- multilingual-e5-small by intfloat (Liang Wang et al.), MIT License ([intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small)),
  as the int8 ONNX export and tokenizer of [Xenova/multilingual-e5-small](https://huggingface.co/Xenova/multilingual-e5-small),
  downloaded at build time at a fixed revision (SHA-256 checked)
- ONNX Runtime (MIT), runs the model on the CPU
- Hugging Face tokenizers (Apache-2.0)
- NumPy (BSD-3-Clause)

## Liberation Sans font (PDF documents)

The PDF writer of the office module embeds Liberation Sans Regular and Bold (`kalmido/office/fonts/LiberationSans-*.ttf`,
Digitized data Copyright (c) 2010 Google Corporation, Copyright (c) 2012 Red Hat, Inc., with Reserved Font Name Liberation),
licensed under the SIL Open Font License, Version 1.1. The full license text ships next to the fonts as
`kalmido/office/fonts/LICENSE-LiberationSans.txt`. The fonts are embedded unchanged (no subsetting) into every PDF/A-3 file.

## sRGB ICC profile (PDF/A output intent)

`kalmido/office/fonts/sRGB2014.icc` is the sRGB v2 profile of the International Color Consortium (Copyright International
Color Consortium, 2015): "This profile is made available by the International Color Consortium, and may be copied,
distributed, embedded, made, used, and sold without restriction. Altered versions of this profile shall have the original
identification and copyright information removed and shall not be misrepresented as the original profile." It is embedded
unchanged as the output intent of every PDF/A-3 file.

## Go standard library and runtime (folder watcher, folderwatch/, 2.207.0)

The folder watcher downloads (`/app/folderwatch/`, built from `folderwatch/`) are Go programs that use only the Go
standard library. Each file contains the Go runtime and standard library, Copyright 2009 The Go Authors, BSD 3-Clause
License. The full license text ships next to the downloads as `/app/folderwatch/LICENSE-Go.txt` (copied unchanged from
the Go toolchain of the build) and is at [go.dev/LICENSE](https://go.dev/LICENSE).
