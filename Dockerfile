# One deployable image: private Cobalt + StreamSave, with only port 8000 public.
FROM node:24-bookworm-slim AS cobalt-build
RUN apt-get update \
    && apt-get install -y --no-install-recommends git python3 build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src/cobalt
RUN git init \
    && git remote add origin https://github.com/imputnet/cobalt.git \
    && git fetch --depth=1 origin a636575b09de1fc55d9b8cd98cac88f5f2f16b42 \
    && git checkout --detach FETCH_HEAD
RUN npm install --global pnpm@9.6.0 \
    && pnpm --filter '@imput/cobalt-api...' install --prod --frozen-lockfile \
    && pnpm --filter @imput/cobalt-api deploy --prod /prod/cobalt \
    && cp -a .git /prod/cobalt/.git \
    && cp LICENSE /prod/cobalt/LICENSE \
    && git archive --format=tar.gz --output=/prod/cobalt-source.tar.gz HEAD

FROM python:3.12-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000 \
    HOST=0.0.0.0 \
    DOWNLOAD_DIR=/app/data/downloads \
    COBALT_BUNDLED=true \
    COBALT_SOURCE_DIR=/opt/cobalt \
    COBALT_API_URL=http://127.0.0.1:9000/ \
    FFMPEG_BIN=/usr/bin/ffmpeg \
    MAX_CONCURRENT_DOWNLOADS=1 \
    SOURCE_ARCHIVE=/opt/streamsave-source.zip

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates libstdc++6 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 streamsave \
    && mkdir -p /app/data/downloads \
    && chown -R streamsave:streamsave /app
COPY --from=cobalt-build /usr/local/bin/node /usr/local/bin/node
COPY --from=cobalt-build /prod/cobalt /opt/cobalt
COPY --from=cobalt-build /prod/cobalt-source.tar.gz /opt/cobalt-source.tar.gz
WORKDIR /app
COPY requirements.txt requirements.lock.txt ./
RUN python -m pip install -r requirements.lock.txt
# Source is offered to users of the deployed application as well as on GitHub.
COPY . /tmp/streamsave-source
RUN python /tmp/streamsave-source/scripts/source_bundle.py \
      --project /tmp/streamsave-source --cobalt-archive /opt/cobalt-source.tar.gz \
      --output /opt/streamsave-source.zip \
    && rm -rf /tmp/streamsave-source
COPY --chown=streamsave:streamsave app ./app
COPY --chown=streamsave:streamsave static ./static
COPY --chown=streamsave:streamsave scripts ./scripts
COPY --chown=streamsave:streamsave run.py LICENSE NOTICE.md cobalt.lock.json ./
USER streamsave

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:'+os.getenv('PORT','8000')+'/api/health',timeout=4)" || exit 1
CMD ["python", "run.py"]
