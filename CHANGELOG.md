# Changelog

## 2.0.0 — 12 October 2026

- Replace yt-dlp with the self-hosted Cobalt 11.7.1 API.
- Bundle private Cobalt and StreamSave in one Docker deployment.
- Supervise backend/web processes and shut down their media descendants.
- Use system FFmpeg through FFMPEG_BIN and validate final files with FFprobe.
- Support MP4 maximum-quality presets and MP3 128/256/320 kbps exports.
- Hide unknown preview duration and label quality choices accurately.
- Reject unexpected/foreign tunnels, redirects, oversized streams and damaged files.
- Retain per-browser jobs, cancellation, expiration, request/storage/time limits.
- Keep arka@jinx credit and add Cobalt/source/license attribution.
- Add Railway configuration, deployment guides and CI tests.

## Previous releases

The supplied project used yt-dlp. Its old proxy/PO-token configuration and extractor-specific tests no longer apply to the Cobalt runtime.
