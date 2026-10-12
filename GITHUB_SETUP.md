# Update your GitHub repository

Extract the ZIP. Open the **StreamSave** folder and upload its contents to the root of your existing StreamSave repository. Replace files with the same names.

The repository root should include:

~~~text
app/
static/
scripts/
tests/
docs/
.github/
Dockerfile
railway.json
render.yaml
compose.yaml
run.py
cobalt.lock.json
requirements.txt
requirements.lock.txt
requirements-dev.txt
README.md
LICENSE
NOTICE.md
~~~

Upload the project contents, rather than the ZIP file. Include the provided .env.example and .github/workflows/ci.yml; your file picker may hide dot-prefixed names.

If using Git locally, place the extracted contents in your existing checkout, then inspect and commit the changes:

~~~sh
git status
git add .
git commit -m "Use self-hosted Cobalt for StreamSave downloads"
git push
~~~

Keep .env, API keys, cookies, .venv/, vendor/, node_modules/ and downloaded files out of the repository. The supplied .gitignore covers the usual local paths.

The CI workflow runs Python and dashboard DOM tests, then builds and smoke-tests the Docker image. It does not test YouTube from GitHub Actions.

After your commit appears on GitHub, follow [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md) or [DEPLOY_DOCKER.md](DEPLOY_DOCKER.md).
