FROM python:3.14-slim AS deps
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --root-user-action=ignore --prefix=/install -r /tmp/requirements.lock

# n8n community node, packed exactly as for its GitHub release. The runtime image carries it unpacked
# under /opt/n8n-node so a deployment can copy it into n8n (init container) without npm or internet.
FROM node:22-slim AS n8n-node
WORKDIR /src
COPY n8n-node/package.json n8n-node/package-lock.json ./
RUN npm ci --no-audit --no-fund --ignore-scripts
COPY n8n-node/ ./
RUN npm run build && npm pack --silent \
    && mkdir /out && tar xzf n8n-nodes-*.tgz -C /out --strip-components=1

FROM python:3.14-slim
ARG VERSION=dev
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=deps /install /usr/local
WORKDIR /srv
COPY app ./app
COPY --from=n8n-node /out /opt/n8n-node

ENV APP_VERSION=${VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    WORKERS=2
USER 10001
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WORKERS} --no-access-log --timeout-graceful-shutdown 30"]
