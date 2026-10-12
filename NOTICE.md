# Component notices

**StreamSave — created by arka@jinx.**

StreamSave 2.0 source is offered under GNU AGPL version 3; see LICENSE.

The downloader backend is the **Cobalt API** by imput and contributors:
- Repository: https://github.com/imputnet/cobalt
- Version: 11.7.1
- Source commit: a636575b09de1fc55d9b8cd98cac88f5f2f16b42
- API license: AGPL-3.0
- The API source is unmodified. It is built as a separate Node process and accessed through its documented HTTP API.
- Its original source archive is included in the Docker deployment's /source offer.
- Cobalt's web frontend is not used.

Cobalt uses YouTube.js (MIT) and FFmpeg for media retrieval and processing. The deployment prefers the system FFmpeg package through FFMPEG_BIN. Dependency licenses and copyright notices remain with their packages.

The pinned upstream source, StreamSave source and build files are offered from the dashboard's Source & license link. Local environment files and media are excluded.
