# Deploy on a hosted Docker server

Run this on a hosted Linux server or Docker platform. The server runs independently of your computer.

## Hosted Docker platforms

Connect the GitHub repository and choose Dockerfile deployment. Build context is the project root; Dockerfile path is Dockerfile. Use the image's default command, python run.py.

Expose only the StreamSave port (default 8000, or the provider's PORT). Set readiness path to /api/health. Use one instance/replica, HTTPS ingress and the public deployment variables from [DEPLOY_RAILWAY.md](DEPLOY_RAILWAY.md).

The bundled Cobalt backend listens only on loopback:9000 inside the container. COBALT_API_URL must remain http://127.0.0.1:9000/. A separate public Cobalt URL is unnecessary.

A small initial service should have approximately 1 GB RAM and enough temporary disk for the configured limits; larger files/concurrency need more resources. These are starting resource settings, not a throughput guarantee.

## Linux server with Docker Compose

Copy or clone the repository onto your hosted server, then run:

~~~sh
docker compose up -d --build
docker compose logs --tail=80 streamsave
~~~

The included compose.yaml binds port 8000 to **127.0.0.1 on the server**, so it can be placed behind your HTTPS reverse proxy.

Configure your reverse proxy to forward your domain to http://127.0.0.1:8000. In compose.yaml, set SECURE_COOKIES=true and add PUBLIC_URL with your exact HTTPS origin. Configure TRUSTED_PROXY_IPS for the reverse proxy you control. Recreate the service after changing the environment:

~~~sh
docker compose up -d
~~~

Verify /api/health, then inspect and download a video using the public dashboard. The server must be able to reach YouTube and its media endpoints.

Stop the service when needed:

~~~sh
docker compose down
~~~

Downloads and jobs are temporary. The launcher stops the web process and Cobalt together, including their active media subprocesses.

## Rebuild/update Cobalt

The source commit is pinned in Dockerfile and cobalt.lock.json. For a future update, update both to a verified compatible commit, rebuild, and run the contract tests plus a real-host download before using it.

This project uses Cobalt's supported public API schema with server processing. It does not use somebody else's protected public endpoint. Original Cobalt source: https://github.com/imputnet/cobalt.
