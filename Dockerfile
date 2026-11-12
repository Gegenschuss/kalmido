# 2.207.0 B (#2763): the folder watcher (folderwatch/, Go standard library only) for Mac / Windows / Linux - built once
# natively on the build machine (also for a multi-platform image), tested, packed; Settings > Documents offers the files
# 2.168.5: ${BUILDPLATFORM:-linux/amd64} and no RUN --mount - the classic builder (Docker without buildx, e.g. a
# staging host) knows neither; BuildKit (release, multi-platform) still sets BUILDPLATFORM itself, so the default stays unused
FROM --platform=${BUILDPLATFORM:-linux/amd64} golang:1.27-alpine@sha256:fa3d596898d9f126af7c01d14ee7597bab3f39cccf392ef36b69fe77cd681f18 AS folderwatch
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-trimpath
WORKDIR /src
COPY folderwatch/ .
COPY VERSION /VERSION
RUN set -e; go vet ./...; go test ./...; v="$(cat /VERSION)"; \
    mkdir -p /out /build; go build -buildvcs=false -o /build/pack ./cmd/pack; \
    b() { GOOS="$1" GOARCH="$2" go build -buildvcs=false -ldflags "-s -w -buildid= -X main.version=$v $4" -o "$3" .; }; \
    b darwin arm64 /build/mac-arm64; b darwin amd64 /build/mac-amd64; \
    b windows amd64 /out/kalmido-folder-watcher-windows.exe "-H windowsgui"; \
    b linux amd64 /out/kalmido-folder-watcher-linux-amd64; b linux arm64 /out/kalmido-folder-watcher-linux-arm64; \
    /build/pack checksign /build/mac-arm64; \
    /build/pack zip /build/mac-arm64 /out/kalmido-folder-watcher-mac-arm64.zip kalmido-folder-watcher; \
    /build/pack zip /build/mac-amd64 /out/kalmido-folder-watcher-mac-amd64.zip kalmido-folder-watcher; \
    cp "$(go env GOROOT)/LICENSE" /out/LICENSE-Go.txt; \
    chmod 0644 /out/*; chmod 0755 /out/kalmido-folder-watcher-linux-*; /build/pack sums /out

# 2.360.3 (#2915): base images by digest (the tag stays readable), kept current with tools/pins.py --update
# 2.442.0 (#2808): JS / CSS packed ahead of time (gzip, brotli) on the build machine, the app sends them by Accept-Encoding
FROM --platform=${BUILDPLATFORM:-linux/amd64} python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54 AS staticpack
COPY tools/requirements.static.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock
COPY static /src/static
COPY kalmido/core/strip.py tools/pack_static.py /src/tools/
RUN python /src/tools/pack_static.py /src/static /out

FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
# 2.37.0: pg_dump/pg_restore for the in-app backup (Debian 13 ships PostgreSQL 17)
# 2.143.0 B (#2152): + openssh-client (sftp) for the off-site backup target
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 openssh-client && rm -rf /var/lib/apt/lists/*
# 2.48.0 (#1111): OCR -- text recognition of scanned documents (German / English), page previews, QR codes (archive numbers)
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-ita tesseract-ocr-spa tesseract-ocr-nld poppler-utils libzbar0t64 && rm -rf /var/lib/apt/lists/*
# 2.360.3 (#2915): every package with its version and hashes, also what the direct ones pull in (tools/requirements.in + .lock)
COPY tools/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock && rm /tmp/requirements.lock
# 2.630.0 (#4671): the image libraries inside the Pillow wheel (libjpeg-turbo, zlib-ng, libtiff, libwebp, freetype, openjpeg,
# lcms2) are at least the versions of WHEEL_MIN in tools/pins.py, else the build stops here
COPY tools/pins.py /tmp/pins.py
RUN python /tmp/pins.py --wheels && rm /tmp/pins.py
# 2.554.0 (#4169): pip itself is not needed at runtime (CMD, HEALTHCHECK and the app never call it) and carries known holes: removed after the last pip call
RUN python -m pip uninstall -y pip
WORKDIR /app
# 2.380 G (#3390): + the hashes of the agent starter files (mcp/starter_sha256.txt, tools/starter_sha.py); the pattern lets a
# checkout without mcp/ build too (then the agent setup gets no hashes and checks nothing, as before)
# 2.488.0 (#3363): + mcp/kalmido_mcp.py, the tool table of the hosted MCP access (agents/mcpremote.py loads it; without it /mcp
# answers 503)
COPY app.py VERSION mcp/starter_sha256.tx[t] mcp/kalmido_mcp.p[y] /app/
COPY kalmido /app/kalmido
COPY static /app/static
# 2.1050.0 (#5819): the user documentation (docs/*.md, not docs/dev/) - agents search and read it (api/helpdocs.py)
COPY docs/*.md /app/docs/
COPY --from=staticpack /out/ /app/static_packed/
# 2.207.0 B (#2763): the folder watcher downloads (KALMIDO_FOLDERWATCH_DIR overrides the folder)
COPY --from=folderwatch /out/ /app/folderwatch/
# 2.182.0 (#2715): run as uid/gid 1000 also without the Compose "user:" line (own manifests, k8s, docker run); the
# data and key folders belong to it, so a fresh named volume mounted there is writable. HOME=/tmp: the only writable
# place besides the volumes when the root filesystem is read-only (docker-compose.yml, #2716).
RUN groupadd -g 1000 kalmido && useradd -u 1000 -g 1000 -M -d /tmp -s /usr/sbin/nologin kalmido \
    && mkdir -p /data /secret && chown 1000:1000 /data /secret
USER 1000:1000
EXPOSE 3040
# 2.360.0 A (#2496): docker ps shows healthy / unhealthy also without the Compose file (python3 is in the image, no curl);
# the same check as docker-compose.yml (which overrides it there)
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=3 \
    CMD ["python3", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/api/health' % os.environ.get('PORT', '3040'), timeout=5)"]
CMD ["python", "app.py"]
