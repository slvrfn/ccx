# syntax=docker/dockerfile:1.7
# The official image is the authoritative OpenCode version. Its Alpine/musl
# runtime cannot use all Graphify/PyMilvus binary wheels, so use the same official
# npm release in a glibc runtime. See docs/architecture.md for this explicit deviation.
ARG OPENCODE_IMAGE=ghcr.io/anomalyco/opencode:2.1.2
FROM ${OPENCODE_IMAGE} AS opencode-release
RUN opencode --version | cut -d" " -f2 > /opencode-version

FROM node:22.14.0-bookworm-slim AS node
FROM ghcr.io/astral-sh/uv:0.6.14 AS uv
FROM python:3.12.10-slim-bookworm AS runtime
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=opencode-release /opencode-version /tmp/opencode-version
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
 && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
 && apt-get update && apt-get install -y --no-install-recommends \
      git ripgrep ca-certificates build-essential \
 && rm -rf /var/lib/apt/lists/*
ARG GRAPHIFY_VERSION=0.9.83
ARG CLAUDE_CONTEXT_VERSION=0.1.15
ARG CCX_UID=1000
ARG CCX_GID=1000
WORKDIR /opt/ccx
COPY src/ccx/assets/package.json src/ccx/assets/package-lock.json ./
RUN test "$CLAUDE_CONTEXT_VERSION" = "0.1.15" \
 && npm ci --omit=dev \
 && npm install -g "@opencode/cli@$(cat /tmp/opencode-version)" \
 && test "$(opencode --version)" = "opencode $(cat /tmp/opencode-version)"
COPY src/ccx/assets/requirements-container.txt ./
RUN test "$GRAPHIFY_VERSION" = "0.9.83" \
 && uv venv /opt/venv \
 && uv pip install --python /opt/venv/bin/python --require-hashes -r requirements-container.txt
ENV PATH="/opt/venv/bin:${PATH}" PYTHONPATH=/opt/ccx \
    PYTHONUNBUFFERED=1 HOME=/home/ccx NODE_ENV=production
COPY src/ccx /opt/ccx/ccx
# UID/GID mapping prevents root-owned files in the host repository.
RUN test "$CCX_UID" -ne 0 && test "$CCX_GID" -ne 0 \
 && (getent group "$CCX_GID" || groupadd -g "$CCX_GID" ccx) \
 && useradd --uid "$CCX_UID" --gid "$CCX_GID" --create-home --home-dir /home/ccx ccx \
 && mkdir -p /workspace /home/ccx/.ccx /home/ccx/.context \
 && chown -R "$CCX_UID:$CCX_GID" /home/ccx
USER ccx
WORKDIR /workspace
ENTRYPOINT []
CMD ["opencode"]
