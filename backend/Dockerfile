# See docs/06-deployment-and-environments.md §2a — the embedding model is downloaded
# once here, at build time, and baked into the image so the runtime container never
# needs to reach Hugging Face (blocked on the corporate network).

FROM python:3.12-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential && rm -rf /var/lib/apt/lists/*

# CPU-only torch — the default PyPI wheel pulls ~2GB of CUDA libraries we'll never use
# (prod runs CPU-only, see docs/06-deployment-and-environments.md §1). Must install this
# before requirements.txt so sentence-transformers' torch dependency resolves to it
# instead of pulling the CUDA build from PyPI.
RUN pip install --no-cache-dir torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

ENV EMBEDDING_MODEL_ID=BAAI/bge-large-en-v1.5
ENV EMBEDDING_LOCAL_MODEL_PATH=/opt/models/bge-large-en-v1.5
ENV HF_HOME=/opt/models/bge-large-en-v1.5

COPY scripts/download_embedding_model.py .

# Uses the Docker BuildKit secret mount so HUGGING_FACE_TOKEN is never cached into an
# image layer or left readable in the final image — see docs/06 §2a. Build with:
#   docker build --secret id=hf_token,env=HUGGING_FACE_TOKEN .
RUN --mount=type=secret,id=hf_token,env=HF_TOKEN \
    python download_embedding_model.py

FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /opt/models /opt/models

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

ENV EMBEDDING_LOCAL_MODEL_PATH=/opt/models/bge-large-en-v1.5
ENV HF_HOME=/opt/models/bge-large-en-v1.5
# Fail fast on a missing-model bug instead of silently hanging on a blocked network
# call — see docs/06-deployment-and-environments.md §2a.
ENV HF_HUB_OFFLINE=1

EXPOSE 8000

COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh
# The entrypoint owns the startup command (reads HOST/PORT itself), no CMD needed.
ENTRYPOINT ["/docker-entrypoint.sh"]
