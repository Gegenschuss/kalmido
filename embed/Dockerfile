# kalmido-embed (2.59.0, #1375): the optional text embedding service for "Related tasks" (docker compose --profile embed).
# The model is downloaded once while building (fixed revision, SHA-256 checked); the running container needs no network.
FROM python:3.12-slim
RUN pip install --no-cache-dir onnxruntime==1.31.0 tokenizers==0.23.3 numpy==2.5.4
# the model: multilingual-e5-small (MIT), its ONNX export and tokenizer from the model's own repository
ARG EMBED_REPO=intfloat/multilingual-e5-small
ARG EMBED_REV=614241f622f53c4eeff9890bdc4f31cfecc418b3
ARG EMBED_ONNX=onnx/model.onnx
ARG EMBED_ONNX_SHA256=ca456c06b3a9505ddfd9131408916dd79290368331e7d76bb621f1cba6bc8665
ARG EMBED_TOK=onnx/tokenizer.json
ARG EMBED_TOK_SHA256=0b44a9d7b51c3c62626640cda0e2c2f70fdacdc25bbbd68038369d14ebdf4c39
COPY fetch_model.py /tmp/fetch_model.py
RUN EMBED_REPO=${EMBED_REPO} EMBED_REV=${EMBED_REV} EMBED_ONNX=${EMBED_ONNX} EMBED_ONNX_SHA256=${EMBED_ONNX_SHA256} \
    EMBED_TOK=${EMBED_TOK} EMBED_TOK_SHA256=${EMBED_TOK_SHA256} python3 /tmp/fetch_model.py && rm /tmp/fetch_model.py
ENV EMBED_MODEL=${EMBED_REPO} EMBED_DIM=384 EMBED_POOLING=mean EMBED_PREFIX_QUERY="query: " EMBED_PREFIX_PASSAGE="passage: "
RUN useradd --system --uid 10090 --no-create-home embed
COPY server.py /app/server.py
USER embed
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=4)"
CMD ["python3", "/app/server.py"]
