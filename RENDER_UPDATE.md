# StreamSave 2.0 migration

This release replaces the old yt-dlp runtime with private self-hosted Cobalt. New-host deployment instructions are in [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md) and [DEPLOY_DOCKER.md](DEPLOY_DOCKER.md).

If you choose to test the existing Render service, replace the repository contents, keep the Docker runtime and use its default command python run.py. Readiness remains /api/health. Remove old custom start-command probes and yt-dlp-specific environment settings.

The included render.yaml is an optional configuration example. It does not fix or guarantee Render's YouTube network access. The previously running Render service has not been changed by producing this ZIP.
