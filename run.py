"""Supervise the private Cobalt backend and one StreamSave web process."""
import os
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

load_dotenv()


def cobalt_environment(settings):
    from app.cobalt import api_url
    url = api_url(settings.cobalt_api_url)
    parsed = urlsplit(url)
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} or parsed.scheme != "http" or parsed.path != "/":
        raise RuntimeError("Bundled Cobalt requires an HTTP localhost API URL without a path prefix.")
    env = os.environ.copy()
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("Bundled Cobalt needs the FFmpeg program installed.")
    env.pop("FREEBIND_CIDR", None)
    env.pop("API_INSTANCE_COUNT", None)
    env.update(API_URL=url, API_PORT=str(parsed.port or 9000), API_LISTEN_ADDRESS=parsed.hostname, FFMPEG_BIN=ffmpeg,
               DURATION_LIMIT=str(settings.max_duration), FORCE_LOCAL_PROCESSING="never",
               RATELIMIT_MAX="120", TUNNEL_RATELIMIT_MAX="120", CORS_WILDCARD="0")
    # Cobalt and FFmpeg must be able to reach internal streams directly.
    env["NO_PROXY"] = ",".join(filter(None, [env.get("NO_PROXY", ""), "127.0.0.1", "localhost", "::1"]))
    return env


def stop_process(proc, grace=8):
    if proc is None:
        return
    if os.name == "nt":
        if proc.poll() is None:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                           capture_output=True, timeout=5, check=False)
    else:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=grace)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            proc.kill()
    finally:
        if os.name != "nt":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        if proc.poll() is None:
            proc.wait(timeout=3)


def main():
    from app import __version__
    from app.cobalt import CobaltClient, MediaError
    from app.config import Settings
    settings = Settings.from_env()
    stopped = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_args: stopped.set())
    cobalt = web = None
    source = os.getenv("COBALT_SOURCE_DIR", "").strip()
    bundled = os.getenv("COBALT_BUNDLED", "true" if source else "false").lower() == "true"
    try:
        if not shutil.which("ffprobe"):
            raise RuntimeError("FFprobe is missing. Build the provided Dockerfile or follow README.md.")
        if bundled:
            folder = Path(source).resolve() if source else None
            if folder is None or not (folder / "src/cobalt.js").is_file() or not shutil.which("node"):
                raise RuntimeError("Bundled Cobalt is missing. Build the provided Dockerfile or complete the native setup in README.md.")
            cobalt = subprocess.Popen(["node", "src/cobalt.js"], cwd=folder, env=cobalt_environment(settings),
                                      stdin=subprocess.DEVNULL, start_new_session=os.name != "nt")
        client = CobaltClient(settings)
        deadline = time.monotonic() + 30
        while True:
            if stopped.is_set():
                return 0
            if cobalt is not None and cobalt.poll() is not None:
                raise RuntimeError("Cobalt exited before startup completed. Check the preceding Cobalt log.")
            try:
                info = client.info(timeout=min(2, max(.1, deadline - time.monotonic())))
                break
            except MediaError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Cobalt did not become ready. Check COBALT_API_URL and the backend's installation.") from None
                stopped.wait(.2)
        port = int(os.getenv("PORT", "8000"))
        host = os.getenv("HOST", "0.0.0.0")
        if not 1024 <= port <= 65535:
            raise RuntimeError("PORT must be between 1024 and 65535.")
        browser_url = os.getenv("PUBLIC_URL") or f"http://localhost:{port}"
        print(f"StreamSave {__version__} | Cobalt {info['cobalt']['version']} | single worker", flush=True)
        print(f"Open {browser_url}. Ctrl+C stops both services.", flush=True)
        arguments = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port),
                     "--workers", "1", "--proxy-headers",
                     "--forwarded-allow-ips", os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1")]
        web = subprocess.Popen(arguments, stdin=subprocess.DEVNULL, start_new_session=os.name != "nt")
        while not stopped.wait(.2):
            if cobalt is not None and cobalt.poll() is not None:
                raise RuntimeError("Cobalt stopped unexpectedly; StreamSave is stopping so the host can restart it.")
            if web.poll() is not None:
                return web.returncode or 1
        return 0
    except (RuntimeError, ValueError, OSError, MediaError) as exc:
        print(f"Startup failed: {exc}", file=sys.stderr, flush=True)
        return 1
    finally:
        # Let the web process cancel active work before taking Cobalt down.
        stop_process(web)
        stop_process(cobalt)


if __name__ == "__main__":
    sys.exit(main())
