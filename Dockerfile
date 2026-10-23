# 2.207.0 B (#2763): the folder watcher (folderwatch/, Go standard library only) for Mac / Windows / Linux - built once
# natively on the build machine (also for a multi-platform image), tested, packed; Settings > Documents offers the files
FROM --platform=$BUILDPLATFORM golang:1.27-alpine AS folderwatch
ENV CGO_ENABLED=0 GOTOOLCHAIN=local GOPROXY=off GOFLAGS=-trimpath
WORKDIR /src
COPY folderwatch/ .
COPY VERSION /VERSION
RUN --mount=type=cache,target=/root/.cache/go-build set -e; go vet ./...; go test ./...; v="$(cat /VERSION)"; \
    mkdir -p /out /build; go build -buildvcs=false -o /build/pack ./cmd/pack; \
    b() { GOOS="$1" GOARCH="$2" go build -buildvcs=false -ldflags "-s -w -buildid= -X main.version=$v $4" -o "$3" .; }; \
    b darwin arm64 /build/mac-arm64; b darwin amd64 /build/mac-amd64; \
    b windows amd64 /out/kalmido-folder-watcher-windows.exe "-H windowsgui"; \
    b linux amd64 /out/kalmido-folder-watcher-linux-amd64; b linux arm64 /out/kalmido-folder-watcher-linux-arm64; \
    /build/pack checksign /build/mac-arm64; \
    /build/pack zip /build/mac-arm64 /out/kalmido-folder-watcher-mac-arm64.zip kalmido-folder-watcher; \
    /build/pack zip /build/mac-amd64 /out/kalmido-folder-watcher-mac-amd64.zip kalmido-folder-watcher; \
    chmod 0644 /out/*; chmod 0755 /out/kalmido-folder-watcher-linux-*; /build/pack sums /out

FROM python:3.12-slim
# 2.37.0: pg_dump/pg_restore for the in-app backup (Debian 13 ships PostgreSQL 17)
# 2.143.0 B (#2152): + openssh-client (sftp) for the off-site backup target
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 openssh-client && rm -rf /var/lib/apt/lists/*
# 2.48.0 (#1111): OCR -- text recognition of scanned documents (German / English), page previews, QR codes (archive numbers)
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-ita tesseract-ocr-spa tesseract-ocr-nld poppler-utils libzbar0t64 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir flask==3.1.3 werkzeug==3.1.9 waitress==3.0.2 python-dateutil==2.9.0 cryptography==50.0.1 icalendar==7.3.0 recurring-ical-events==3.8.2 x-wr-timezone==2.0.1 click==8.5.0 segno==1.6.6 webauthn==3.0.1 cbor2==6.1.4 pyasn1==0.6.4 pyasn1-modules==0.4.2 pyOpenSSL==26.4.0 typing-extensions==4.16.0 pillow==13.0.0 pi-heif==1.4.0 pypdf==6.21.2 xlrd==2.0.2 psycopg[binary]==3.3.6 psycopg-pool==3.3.3 tzdata
WORKDIR /app
COPY app.py VERSION /app/
COPY kalmido /app/kalmido
COPY static /app/static
# 2.207.0 B (#2763): the folder watcher downloads (KALMIDO_FOLDERWATCH_DIR overrides the folder)
COPY --from=folderwatch /out/ /app/folderwatch/
# 2.182.0 (#2715): run as uid/gid 1000 also without the Compose "user:" line (own manifests, k8s, docker run); the
# data and key folders belong to it, so a fresh named volume mounted there is writable. HOME=/tmp: the only writable
# place besides the volumes when the root filesystem is read-only (docker-compose.yml, #2716).
RUN groupadd -g 1000 kalmido && useradd -u 1000 -g 1000 -M -d /tmp -s /usr/sbin/nologin kalmido \
    && mkdir -p /data /secret && chown 1000:1000 /data /secret
USER 1000:1000
EXPOSE 3040
CMD ["python", "app.py"]
