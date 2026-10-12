# StreamSave 2.0 design

Goal: retain the user's external-hosted StreamSave dashboard and arka@jinx credit while replacing yt-dlp with Cobalt.

One Docker container runs a private Cobalt API on loopback:9000 and a single FastAPI service on PORT. A supervisor starts Cobalt, waits for API readiness, starts uvicorn and stops both process groups on termination or child failure. System FFmpeg handles Cobalt media processing.

The link endpoint accepts only canonical individual YouTube URLs. A Cobalt MP4 preflight checks video access; optional YouTube oEmbed metadata supplies title/channel. The documented API does not enumerate formats or expose duration, so the dashboard presents explicit export presets, labels video quality Up to, and omits unknown duration. Cobalt's duration limit matches the app's configuration.

Jobs request a fresh signed Cobalt tunnel for the selected server-issued preset. All requests demand server processing and tunnelling. The wrapper accepts only the configured origin's /tunnel endpoint, sends operator API keys only to POST processing requests and follows no redirects. Async I/O is monitored for cancellation, absolute deadlines and disk limits, including stalled headers/bodies.

File bytes are bounded while streamed into a partial file. A full FFprobe packet scan checks the actual media container, audio/video presence, codec, duration and error output. Only validated results are renamed and exposed through owner-only file routes. Failed/cancelled jobs remove their temporary files.

Source is offered under AGPL-3.0, with original Cobalt source/attribution. The source archive uses an allowlist, excludes environment/media/hidden paths and excludes nested JSON/YAML runtime data.

Hosting examples: Railway trial and a portable Docker server. Readiness does not imply successful YouTube access, and no provider, public API, paid proxy, home-PC backend or hosted deployment is created by the ZIP update.
