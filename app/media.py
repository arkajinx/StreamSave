"""YouTube-only validation, Cobalt export presets, and final media validation."""
import json
import re
import shutil
import ssl
import subprocess
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx

from . import __version__
from .cobalt import CobaltClient, MediaError
from .config import Settings

VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


def canonical_url(raw: str) -> str:
    raw = raw.strip()
    if not raw or len(raw) > 2048 or any(ord(c) < 32 for c in raw):
        raise MediaError("Paste a valid YouTube video link.")
    if "://" not in raw:
        raw = "https://" + raw
    try:
        url = urlsplit(raw)
        if url.scheme not in {"https", "http"} or url.username or url.password or url.port is not None:
            raise ValueError
        host = (url.hostname or "").lower()
        if host in {"youtu.be", "www.youtu.be"}:
            pieces = url.path.strip("/").split("/")
            video_id = pieces[0] if len(pieces) == 1 else ""
        elif host in YOUTUBE_HOSTS:
            if url.path == "/watch":
                ids = parse_qs(url.query).get("v", [])
                video_id = ids[0] if len(ids) == 1 else ""
            else:
                pieces = url.path.strip("/").split("/")
                video_id = pieces[1] if len(pieces) == 2 and pieces[0] in {"shorts", "embed", "live"} else ""
        else:
            video_id = ""
        if not VIDEO_ID.fullmatch(video_id):
            raise ValueError
    except (ValueError, UnicodeError):
        raise MediaError("Use a YouTube video, Shorts, or youtu.be link. Playlists and other sites are not supported.") from None
    return f"https://www.youtube.com/watch?v={video_id}"


def number(value) -> float:
    try:
        result = float(value or 0)
        return result if 0 < result < float("inf") else 0
    except (ValueError, TypeError):
        return 0


def format_options(_info: dict) -> list[dict]:
    # Export presets, not a claim that every resolution exists for this video.
    video = [{"id": f"mp4-{height}", "kind": "video", "container": "mp4", "height": height,
              "label": f"Up to {height}p", "estimated_bytes": None}
             for height in (1080, 720, 480, 360, 240, 144)]
    audio = [{"id": f"mp3-{bitrate}", "kind": "audio", "container": "mp3", "bitrate": bitrate,
              "label": f"MP3 · {bitrate} kbps", "estimated_bytes": None}
             for bitrate in (128, 256, 320)]
    return video + audio


def fetch_metadata(url, timeout=3):
    """Optional title/channel decoration; oEmbed is not a media backend."""
    try:
        with httpx.Client(verify=ssl.create_default_context(), trust_env=False, timeout=min(3, timeout),
                          follow_redirects=False) as client:
            with client.stream("GET", "https://www.youtube.com/oembed",
                               params={"url": url, "format": "json"},
                               headers={"Accept-Encoding": "identity"}) as response:
                if response.status_code != 200:
                    return {}
                data = bytearray()
                deadline = time.monotonic() + min(3, timeout)
                for block in response.iter_bytes():
                    data.extend(block)
                    if len(data) > 64 * 1024 or time.monotonic() >= deadline:
                        return {}
                result = json.loads(data)
                if isinstance(result, dict):
                    return {"title": str(result.get("title") or "")[:500],
                            "channel": str(result.get("author_name") or "")[:250]}
    except (httpx.HTTPError, ValueError, UnicodeError):
        pass
    return {}


def inspect_video(url: str, timeout: int = 45, *, settings: Settings | None = None) -> dict:
    settings = settings or Settings.from_env()
    url = canonical_url(url)
    started = time.monotonic()
    prepared = CobaltClient(settings).prepare(url, {"kind": "video", "container": "mp4", "height": 360}, timeout)
    remaining = max(0.01, timeout - (time.monotonic() - started))
    metadata = fetch_metadata(url, timeout=min(3, remaining)) if remaining > 0.1 else {}
    video_id = parse_qs(urlsplit(url).query)["v"][0]
    fallback_title = Path(prepared["filename"].replace("\\", "/")).stem[:500]
    return {"id": video_id, "title": metadata.get("title") or fallback_title or "YouTube video",
            "channel": metadata.get("channel") or "", "duration": None}


def health_report(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    dependencies = {"cobalt_api": False, "ffprobe": shutil.which("ffprobe") is not None}
    versions = {"app": __version__, "cobalt": None, "cobalt_commit": None}
    detail = None
    try:
        info = CobaltClient(settings).info(timeout=2)
        dependencies["cobalt_api"] = True
        versions["cobalt"] = info["cobalt"]["version"][:80]
        git = info.get("git")
        if isinstance(git, dict) and isinstance(git.get("commit"), str):
            versions["cobalt_commit"] = git["commit"][:80]
    except MediaError as exc:
        detail = str(exc)
    if not dependencies["ffprobe"]:
        detail = "The server needs FFprobe to validate completed downloads. See README.md."
    ready = all(dependencies.values())
    result = {"status": "ok" if ready else "setup_required", "dependencies": dependencies, "versions": versions}
    if detail:
        result["detail"] = detail
    return result


def probe_media(path: Path, choice: dict, max_duration: int, timeout=15):
    if not shutil.which("ffprobe"):
        raise MediaError("The server needs FFprobe to validate downloads. Ask the operator to complete setup.", 503)
    try:
        result = subprocess.run(["ffprobe", "-v", "error", "-protocol_whitelist", "file,pipe", "-count_packets",
                                 "-show_streams", "-show_format", "-of", "json", str(path)],
                                capture_output=True, timeout=timeout, check=False)
        if result.returncode or result.stderr or len(result.stdout) > 512 * 1024:
            raise ValueError
        info = json.loads(result.stdout)
        streams = info["streams"]
        duration = number(info["format"].get("duration"))
        audio = [s for s in streams if s.get("codec_type") == "audio"]
        video = [s for s in streams if s.get("codec_type") == "video" and not s.get("disposition", {}).get("attached_pic")]
        names = info["format"].get("format_name", "").split(",")
        if not duration or not audio:
            raise ValueError
        if choice["kind"] == "video" and (not video or "mp4" not in names):
            raise ValueError
        if choice["kind"] == "audio" and (video or "mp3" not in names or audio[0].get("codec_name") != "mp3"):
            raise ValueError
    except subprocess.TimeoutExpired:
        raise MediaError("Media validation took too long. Try a smaller output.", 504) from None
    except (OSError, ValueError, KeyError, TypeError):
        raise MediaError("The download service did not return a complete, valid media file.", 502) from None
    if duration > max_duration:
        raise MediaError("This video exceeds the server's duration limit. Choose a shorter video.")
