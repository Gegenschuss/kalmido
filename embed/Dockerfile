# kalmido-embed (2.59.0, #1375): the optional text embedding service for "Related tasks" (docker compose --profile embed).
# The model is downloaded once while building (fixed revision, SHA-256 checked); the running container needs no network.
# 2.360.3 (#2915): the base image by digest, every package with version and hashes (requirements.in + .lock, tools/pins.py --update)
FROM python:3.12-slim@sha256:4840d514c583a4d3d8cad3940e68dee6f0f6f3635c12fcd0a3d74c21a5b93a54
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock && rm /tmp/requirements.lock
# the model: multilingual-e5-small (intfloat, MIT) as the int8 ONNX export of Xenova/multilingual-e5-small (118 MB; measured
# 2.59.0: as good as fp32 / larger models on our task data, ~0.15 s per task on a small 4-core CPU with one thread)
ARG EMBED_REPO=Xenova/multilingual-e5-small
ARG EMBED_REV=761b726dd34fb83930e26aab4e9ac3899aa1fa78
ARG EMBED_ONNX=onnx/model_quantized.onnx
ARG EMBED_ONNX_SHA256=f80102d3f2a1229f387d3c81909990d8945513e347b0eab049f7de3c6f98c193
ARG EMBED_TOK=tokenizer.json
ARG EMBED_TOK_SHA256=0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39
COPY fetch_model.py /tmp/fetch_model.py
RUN EMBED_REPO=${EMBED_REPO} EMBED_REV=${EMBED_REV} EMBED_ONNX=${EMBED_ONNX} EMBED_ONNX_SHA256=${EMBED_ONNX_SHA256} \
    EMBED_TOK=${EMBED_TOK} EMBED_TOK_SHA256=${EMBED_TOK_SHA256} python3 /tmp/fetch_model.py && rm /tmp/fetch_model.py
# 2.554.0 (#4169): pip itself is not needed at runtime and carries known holes: removed after the last pip call
RUN python -m pip uninstall -y pip
# the model's name is stored with every vector: another file / model = everything computed again
ENV EMBED_MODEL=multilingual-e5-small-int8 EMBED_THREADS=1 EMBED_DIM=384 EMBED_POOLING=mean EMBED_PREFIX_QUERY="query: " EMBED_PREFIX_PASSAGE="passage: "
RUN useradd --system --uid 10090 --no-create-home embed
COPY server.py /app/server.py
USER embed
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=4)"
CMD ["python3", "/app/server.py"]
