FROM python:3.12-slim
# 2.37.0: pg_dump/pg_restore for the in-app backup (Debian 13 ships PostgreSQL 17)
# 2.143.0 B (#2152): + openssh-client (sftp) for the off-site backup target
RUN apt-get update && apt-get install -y --no-install-recommends postgresql-client-17 openssh-client && rm -rf /var/lib/apt/lists/*
# 2.48.0 (#1111): OCR -- text recognition of scanned documents (German / English), page previews, QR codes (archive numbers)
RUN apt-get update && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-deu tesseract-ocr-eng tesseract-ocr-fra tesseract-ocr-ita tesseract-ocr-spa tesseract-ocr-nld poppler-utils libzbar0t64 && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir flask==3.1.3 werkzeug==3.1.9 waitress==3.0.2 python-dateutil==2.9.0 cryptography==50.0.1 icalendar==7.3.0 recurring-ical-events==3.8.2 x-wr-timezone==2.0.1 click==8.5.0 segno==1.6.6 webauthn==3.0.1 cbor2==6.1.4 pyasn1==0.6.4 pyasn1-modules==0.4.2 pyOpenSSL==26.4.0 typing-extensions==4.16.0 pillow==13.0.0 pi-heif==1.4.0 pypdf==6.21.2 psycopg[binary]==3.3.6 psycopg-pool==3.3.3 tzdata
WORKDIR /app
COPY app.py VERSION /app/
COPY kalmido /app/kalmido
COPY static /app/static
# 2.182.0 (#2715): run as uid/gid 1000 also without the Compose "user:" line (own manifests, k8s, docker run); the
# data and key folders belong to it, so a fresh named volume mounted there is writable. HOME=/tmp: the only writable
# place besides the volumes when the root filesystem is read-only (docker-compose.yml, #2716).
RUN groupadd -g 1000 kalmido && useradd -u 1000 -g 1000 -M -d /tmp -s /usr/sbin/nologin kalmido \
    && mkdir -p /data /secret && chown 1000:1000 /data /secret
USER 1000:1000
EXPOSE 3040
CMD ["python", "app.py"]
