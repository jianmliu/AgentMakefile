FROM python:3.11-slim AS builder
WORKDIR /build
COPY pyproject.toml setup.cfg ./
COPY src/ ./src/
# install into a prefix so we can copy just the installed tree
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /install /usr/local
# /data is the corpus root: memory units + evidence JSONL live here.
# Mount a named volume at /data for persistence across restarts.
VOLUME ["/data"]
EXPOSE 8092
# AGENTMF_TOKEN is injected at runtime via --env-file / environment:
# agentmf serve --token reads it from the env var below.
ENV AGENTMF_PORT=8092 \
    AGENTMF_ROOT=/data
CMD ["sh", "-c", "agentmf serve --root $AGENTMF_ROOT --port $AGENTMF_PORT ${AGENTMF_TOKEN:+--token $AGENTMF_TOKEN}"]
