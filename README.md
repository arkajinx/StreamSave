# StreamSave 2.0 — Cobalt edition

A standalone YouTube video/audio downloader created by **arka@jinx**.

Paste a video link, choose an MP4 quality or MP3 bitrate, prepare the file, then save it. The existing StreamSave dashboard is retained. Cobalt handles YouTube extraction and media processing; Python serves the dashboard, owns the queue and validates downloads.

**Start here:** [Deploy on Railway](DEPLOY_RAILWAY.md). Railway builds the supplied Dockerfile directly from GitHub. The image includes Cobalt, Node, FFmpeg, FFprobe and the Python app.

## What changed

- yt-dlp and its JavaScript/PO-token plugins are replaced by a self-hosted Cobalt API.
- One Docker image starts both services. StreamSave listens on the hosting provider's PORT; Cobalt listens only on localhost:9000 inside that container.
- MP4 requests offer maximum qualities of 144p, 240p, 360p, 480p, 720p and 1080p. MP3 export bitrates are 128, 256 and 320 kbps.
- Cobalt's API does not return the old yt-dlp format list. Choices are export presets, labelled **Up to**. The source may provide a lower resolution. Increasing MP3 export bitrate cannot improve the original recording.
- Title/channel information comes from optional public YouTube oEmbed metadata, with the Cobalt filename as a fallback. Duration is omitted from the preview because the API does not return it.
- Cobalt rejects videos exceeding the configured duration limit before transfer. FFprobe checks the actual completed file's duration, container, audio/video streams and packet integrity before it becomes available.
- Cancellation, owner-only jobs, size/disk/time limits and automatic expiration are retained.
- The footer keeps **arka@jinx**, credits Cobalt and links to the deployed source-code offer.

## Deploy

| Method | Guide |
| --- | --- |
| GitHub → Railway, using its trial for an initial test | [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md) |
| A hosted Linux server or another Docker platform | [DEPLOY_DOCKER.md](DEPLOY_DOCKER.md) |
| Update your existing GitHub repository | [GITHUB_SETUP.md](GITHUB_SETUP.md) |

Code is free. Hosting and bandwidth are separate. Railway's trial includes $5 for up to 30 days, then its Free plan provides $1 credit per month. Full outbound networking depends on account verification. The trial is a way to test a new host, not an unlimited free production service. See Railway's [trial](https://docs.railway.com/pricing/free-trial) and [plans](https://docs.railway.com/pricing/plans).

A healthy /api/health response verifies Cobalt/FFprobe availability, **not YouTube access**. Test both a link inspection and a completed download on the deployed host. A different extractor does not guarantee that YouTube accepts every server.

## Local Docker test

From this folder:

~~~sh
docker compose up --build
~~~

Open http://localhost:8000. Stopping the container stops both services. Downloads are temporary; restarting the app discards in-memory jobs. Use one instance and one Python worker.

## Native development

Requires Python 3.12+, Node 24+, Git, FFmpeg and FFprobe. Cobalt uses native Node dependencies; Windows may need the corresponding C++ build tools if a prebuilt package is unavailable. The native setup has been checked on Linux; the Windows installation has not been executed here.

Install Cobalt once:

~~~sh
git clone https://github.com/imputnet/cobalt.git vendor/cobalt
git -C vendor/cobalt checkout a636575b09de1fc55d9b8cd98cac88f5f2f16b42
npx --yes pnpm@9.6.0 --dir vendor/cobalt --filter "@imput/cobalt-api..." install --prod --frozen-lockfile
~~~

**Windows PowerShell:**

~~~powershell
$env:COBALT_SOURCE_DIR = (Resolve-Path .\vendor\cobalt\api).Path
$env:COBALT_BUNDLED = "true"
powershell -ExecutionPolicy Bypass -File .\start.ps1
~~~

**Linux/macOS:**

~~~sh
export COBALT_SOURCE_DIR="$PWD/vendor/cobalt/api"
export COBALT_BUNDLED=true
bash start.sh
~~~

The launcher uses your installed system FFmpeg through the supported FFMPEG_BIN setting. It checks that Cobalt is ready before starting the dashboard and supervises both processes. Set optional overrides in .env by copying [.env.example](.env.example); environment variables take priority.

An operator-owned external Cobalt API can also be used by setting COBALT_BUNDLED=false, COBALT_API_URL to its HTTPS base URL, and COBALT_API_KEY if that operator provided one. Configure its DURATION_LIMIT to match StreamSave's MAX_DURATION_SECONDS and allow server processing. This project does not depend on an undocumented public Cobalt endpoint.

## Configuration

See [.env.example](.env.example) for all settings. Typical public deployment values:

~~~dotenv
HOST=0.0.0.0
SECURE_COOKIES=true
MAX_CONCURRENT_DOWNLOADS=1
MAX_DURATION_SECONDS=1800
MAX_FILE_MB=150
MAX_STORAGE_MB=512
MIN_FREE_MB=64
~~~

Set PUBLIC_URL to the exact assigned HTTPS origin. Keep COBALT_API_URL at http://127.0.0.1:9000/ for the bundled image. API keys belong in the host's secrets settings.

## Tests

~~~sh
python -m pip install -r requirements.lock.txt -r requirements-dev.txt
python -m pytest -q
~~~

Optional dashboard DOM checks:

~~~sh
npm install --no-save --prefix /tmp/streamsave-ui jsdom@30.1.2
STREAMSAVE_JSDOM=/tmp/streamsave-ui/node_modules/jsdom node tests/ui-smoke.cjs
~~~

The tests use an owned, generated media fixture and a local Cobalt-contract server. They do not claim live YouTube availability. Current checks and their limits are recorded in [VERIFICATION.md](VERIFICATION.md).

## Source and credits

StreamSave's source is provided under [AGPL-3.0](LICENSE). Cobalt's API is AGPL-3.0 and is pinned to the version/commit in [cobalt.lock.json](cobalt.lock.json). The Docker image includes the original Cobalt source archive and the StreamSave source offer, available at /source. [NOTICE.md](NOTICE.md) records the component credits. Cobalt's web frontend is not copied into this project.

Use the app for media you are authorized to download. StreamSave is not affiliated with YouTube.
