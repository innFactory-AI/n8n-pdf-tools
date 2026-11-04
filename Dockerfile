FROM python:3.14-slim AS deps
COPY requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --root-user-action=ignore --prefix=/install -r /tmp/requirements.lock

FROM python:3.14-slim
ARG VERSION=dev
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin app
COPY --from=deps /install /usr/local
WORKDIR /srv
COPY app ./app

ENV APP_VERSION=${VERSION} \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    WORKERS=2
USER 10001
EXPOSE 8080
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers ${WORKERS} --no-access-log --timeout-graceful-shutdown 30"]
