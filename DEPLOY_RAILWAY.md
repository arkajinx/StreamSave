# Deploy StreamSave 2.0 on Railway

This deploys StreamSave and its private Cobalt backend together from your GitHub repository. Railway builds the Docker image remotely.

## 1. Update GitHub

Extract the ZIP and upload the **contents of the StreamSave folder** into the root of your repository, replacing existing files. The root should contain Dockerfile, railway.json, requirements.lock.txt, run.py, app/ and static/. Follow [GITHUB_SETUP.md](GITHUB_SETUP.md) for the full list.

## 2. Check trial eligibility

Sign in to https://railway.com with your GitHub account and use the Free Trial if it is available to you. Railway documents a no-card trial with $5 credit for up to 30 days. Afterward its Free plan provides $1 of monthly credit.

Connect GitHub for account verification. You need **Full Trial** outbound network access for this downloader. Limited Trial networking may stop the app from reaching YouTube. If the account is not eligible, this project cannot change that restriction.

Official references: [trial](https://docs.railway.com/pricing/free-trial), [pricing FAQ](https://docs.railway.com/pricing/faqs), [plan limits](https://docs.railway.com/pricing/plans).

## 3. Create the service

1. Select **New Project → Deploy from GitHub repo**.
2. Authorize the repository and select your StreamSave repo/branch.
3. Set the root directory to the directory containing Dockerfile. Leave it empty if you uploaded the project files at the repository root.
4. Railway should detect Dockerfile. The included railway.json configures the Dockerfile path, /api/health readiness check and restart policy.
5. Keep the Docker image's default command: **python run.py**.
6. Use one replica. Background jobs are stored in memory.

You do not need a second Cobalt service or an API-provider account. The included Cobalt API is private inside the container.

Official reference: [Dockerfile deployment](https://docs.railway.com/builds/dockerfiles).

## 4. Add service variables

Add these in the service's **Variables** page:

| Variable | Value |
| --- | --- |
| HOST | 0.0.0.0 |
| PORT | 8000 |
| SECURE_COOKIES | true |
| MAX_CONCURRENT_DOWNLOADS | 1 |
| MAX_DURATION_SECONDS | 1800 |
| MAX_FILE_MB | 150 |
| MAX_STORAGE_MB | 512 |
| MIN_FREE_MB | 64 |
| TRUSTED_PROXY_IPS | * |

The forwarded-header setting above is for Railway's ingress. On a self-managed server, trust only your own reverse proxy.

Keep these included Docker defaults:

| Variable | Value |
| --- | --- |
| COBALT_BUNDLED | true |
| COBALT_SOURCE_DIR | /opt/cobalt |
| COBALT_API_URL | http://127.0.0.1:9000/ |

Leave COBALT_API_KEY empty. The built-in API is not publicly exposed. No YTDLP_PROXY, yt-dlp plugin setting or YOUTUBE_TEST_URL is used in this version.

## 5. Generate your public URL

In **Settings → Networking → Public Networking**, select **Generate Domain** and target port **8000**.

Copy the HTTPS origin, for example https://YOUR-ASSIGNED-DOMAIN.up.railway.app, and set:

~~~dotenv
PUBLIC_URL=https://YOUR-ASSIGNED-DOMAIN.up.railway.app
~~~

Redeploy after saving. Use your actual assigned hostname, without a path or trailing slash.

Official reference: [public networking](https://docs.railway.com/networking/public-networking).

## 6. Verify the deployed host

1. Open https://YOUR-ASSIGNED-DOMAIN/api/health.
2. Confirm status=ok, versions.app=2.0.0 and a Cobalt version.
3. Open the homepage directly, paste your video link and click Check link.
4. Select MP3 128 kbps for a small first test, confirm authorization and prepare the download.
5. Save the file and play it. Then test an MP4 output.
6. Check that the footer shows arka@jinx and Source & license.

The health check deliberately does not contact YouTube. Both extraction and media transfer must work from this new host.

## If deployment fails

- **No Dockerfile detected:** check the repository root, the capital D in Dockerfile and the service's root directory.
- **Cobalt did not become ready:** check the build/start logs. Use the included Dockerfile and python run.py; starting uvicorn directly skips Cobalt supervision.
- **503 at /api/health:** check whether Cobalt or FFprobe is missing/unreachable.
- **Use this app from its own website:** PUBLIC_URL must match the exact URL you opened. Open the assigned HTTPS hostname directly.
- **Bot check / unavailable media:** YouTube refused that host or video; a successful deployment does not change YouTube's access rules.
- **Incomplete or invalid media:** the tunnel failed or returned a damaged file. It is rejected instead of being offered as a successful download.
- **Service stopped:** review your trial/free credit balance and plan/network limits.

Temporary downloads vanish on redeploy/restart. A volume is not needed for the trial. Avoid scaling replicas until jobs and sessions have shared storage.
