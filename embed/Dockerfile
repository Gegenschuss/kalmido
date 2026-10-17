# kalmido-embed (2.59.0, #1375): the optional text embedding service for "Related tasks" (docker compose --profile embed).
# The model is downloaded once while building (fixed revision, SHA-256 checked); the running container needs no network.
FROM python:3.12-slim
RUN pip install --no-cache-dir onnxruntime==1.31.0 tokenizers==0.23.3 numpy==2.5.4
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
# the model's name is stored with every vector: another file / model = everything computed again
ENV EMBED_MODEL=multilingual-e5-small-int8 EMBED_THREADS=1 EMBED_DIM=384 EMBED_POOLING=mean EMBED_PREFIX_QUERY="query: " EMBED_PREFIX_PASSAGE="passage: "
RUN useradd --system --uid 10090 --no-create-home embed
COPY server.py /app/server.py
USER embed
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health', timeout=4)"
CMD ["python3", "/app/server.py"]
