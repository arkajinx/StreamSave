# Deployment

StreamSave 2.0 uses a private bundled Cobalt backend and one Python web process.

- [Railway: GitHub deployment and trial setup](DEPLOY_RAILWAY.md)
- [Hosted Docker platforms / Linux Docker server](DEPLOY_DOCKER.md)
- [Update your GitHub repository](GITHUB_SETUP.md)
- [Verification and current limits](VERIFICATION.md)

The image's command is python run.py. The launcher starts Cobalt before the web server and stops both together. Expose the provider's PORT, use /api/health for readiness, and keep one replica.

Code availability, successful deployment and working YouTube access are separate checks. Test a completed file on the chosen host before sharing the site.
