"""Bounded HTTP client for an operator-owned Cobalt instance."""
import asyncio
from contextlib import suppress
import json
import logging
import re
import ssl
import time
from urllib.parse import urlsplit

import httpx

LOGGER = logging.getLogger(__name__)
JSON_LIMIT = 256 * 1024


class MediaError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def check_deadline(deadline, cancel=None, guard=None):
    if cancel is not None and cancel.is_set():
        raise MediaError("Download cancelled.", 409)
    if time.monotonic() >= deadline:
        raise MediaError("The download service took too long. Try a shorter video or a smaller output.", 504)
    if guard:
        guard()


async def monitored(coroutine, deadline, cancel=None, guard=None):
    """Cancel stalled network reads without cutting valid extraction short."""
    task = asyncio.create_task(coroutine)
    try:
        while True:
            check_deadline(deadline, cancel, guard)
            done, _pending = await asyncio.wait({task}, timeout=0.1)
            if done:
                check_deadline(deadline, cancel, guard)
                return await task
    finally:
        if not task.done():
            task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task


def upstream_error(code):
    messages = {
        "youtube.login": ("YouTube refused this server's request with a bot check. The operator needs to check this host's YouTube access.", 502),
        "content.video.private": ("This video requires restricted access and is not supported.", 400),
        "content.video.age": ("This video requires restricted access and is not supported.", 400),
        "content.video.live": ("Live and upcoming streams are not supported. Use a completed video.", 400),
        "content.video.unavailable": ("This video is unavailable or restricted in this server's location.", 400),
        "content.video.region": ("This video is unavailable in this server's location.", 400),
        "content.too_long": ("This video exceeds the server's duration limit. Choose a shorter video.", 400),
        "youtube.no_matching_format": ("The selected output is unavailable. Try another quality or audio output.", 400),
        "youtube.no_session_tokens": ("Cobalt's configured YouTube session service is unavailable. Ask the operator to check its setup.", 503),
        "youtube.token_expired": ("Cobalt's YouTube session expired. Ask the operator to check its setup.", 503),
        "youtube.decipher": ("Cobalt could not read YouTube's player. Ask the operator to check for a Cobalt update.", 502),
        "youtube.api_error": ("YouTube refused the download service's request. Try another authorized video.", 502),
        "fetch.rate": ("The download service is busy or rate-limited. Try again in a minute.", 429),
        "rate_exceeded": ("The download service is busy. Try again in a minute.", 429),
        "fetch.fail": ("The download service could not retrieve this video from YouTube. Try again later.", 502),
    }
    suffix = code.removeprefix("error.api.") if isinstance(code, str) else ""
    if suffix.startswith("auth."):
        return MediaError("Cobalt authentication failed. Ask the operator to check its API key.", 503)
    message, status = messages.get(suffix, ("The download service could not provide this media. Try another authorized video.", 502))
    return MediaError(message, status)


def api_url(value):
    try:
        parsed = urlsplit(value)
        if (not value or len(value) > 2048 or any(ord(c) < 33 or ord(c) == 127 for c in value)
                or parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or (parsed.port is not None and parsed.port < 1)
                or (parsed.scheme == "http" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"})):
            raise ValueError
    except (ValueError, UnicodeError):
        raise MediaError("The server's COBALT_API_URL is invalid. Use HTTPS, or HTTP on localhost.", 503) from None
    return value.rstrip("/") + "/"


def origin(value):
    parsed = urlsplit(value)
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


class CobaltClient:
    def __init__(self, settings):
        self.url = api_url(settings.cobalt_api_url)
        self.key = settings.cobalt_api_key
        if any(ord(c) < 33 or ord(c) == 127 for c in self.key) or len(self.key) > 256:
            raise MediaError("The server's COBALT_API_KEY setting is invalid.", 503)

    def http_client(self, timeout):
        return httpx.AsyncClient(verify=ssl.create_default_context(), trust_env=False,
                                 follow_redirects=False,
                                 timeout=httpx.Timeout(min(timeout, 5), read=None, connect=min(timeout, 5)))

    def _json(self, method, timeout, payload=None, cancel=None, guard=None):
        deadline = time.monotonic() + timeout
        check_deadline(deadline, cancel, guard)
        headers = {"Accept": "application/json", "Accept-Encoding": "identity"}
        if method == "POST" and self.key:
            headers["Authorization"] = "Api-Key " + self.key

        async def request():
            async with self.http_client(timeout) as client:
                async with client.stream(method, self.url, json=payload, headers=headers) as response:
                    data = bytearray()
                    async for block in response.aiter_bytes():
                        check_deadline(deadline, cancel, guard)
                        data.extend(block)
                        if len(data) > JSON_LIMIT:
                            raise MediaError("The download service returned too much data.", 502)
                    check_deadline(deadline, cancel, guard)
                    if response.status_code == 429:
                        raise MediaError("The download service is busy. Try again in a minute.", 429)
                    if 300 <= response.status_code < 400:
                        raise MediaError("Cobalt returned an unexpected response. Check its API URL.", 503)
                    if "application/json" not in response.headers.get("content-type", "").lower():
                        raise MediaError("Cobalt returned an invalid response. Check its API URL.", 502)
                    try:
                        result = json.loads(data)
                    except (ValueError, UnicodeError):
                        raise MediaError("Cobalt returned an invalid JSON response.", 502) from None
                    if not isinstance(result, dict):
                        raise MediaError("Cobalt returned an invalid response.", 502)
                    if result.get("status") == "error":
                        error = result.get("error")
                        code = error.get("code", "") if isinstance(error, dict) else ""
                        if isinstance(code, str) and re.fullmatch(r"[a-zA-Z0-9_.]{1,120}", code):
                            LOGGER.warning("Cobalt request failed: %s", code)
                        raise upstream_error(code)
                    if response.status_code >= 400:
                        raise MediaError("The Cobalt download service is unavailable. Try again later.", 503)
                    return result
        try:
            return asyncio.run(monitored(request(), deadline, cancel, guard))
        except httpx.TimeoutException:
            check_deadline(deadline, cancel)
            raise MediaError("Cobalt did not respond in time. Try again later.", 504) from None
        except httpx.HTTPError:
            check_deadline(deadline, cancel)
            raise MediaError("The download service could not be reached. Ask the operator to check Cobalt.", 503) from None

    def info(self, timeout=2):
        result = self._json("GET", timeout)
        info = result.get("cobalt")
        if (not isinstance(info, dict) or not isinstance(info.get("version"), str)
                or not isinstance(info.get("services"), list)):
            raise MediaError("This server is not a compatible Cobalt instance.", 503)
        if "youtube" not in info["services"]:
            raise MediaError("YouTube is disabled in this Cobalt instance.", 503)
        return result

    def prepare(self, url, choice, timeout, cancel=None, guard=None):
        payload = {"url": url, "alwaysProxy": True, "localProcessing": "disabled",
                   "filenameStyle": "pretty", "youtubeVideoCodec": "h264", "youtubeVideoContainer": "mp4"}
        if choice.get("kind") == "video" and choice.get("container") == "mp4" and choice.get("height") in {144, 240, 360, 480, 720, 1080}:
            payload.update(downloadMode="auto", videoQuality=str(choice["height"]))
        elif choice.get("kind") == "audio" and choice.get("container") == "mp3" and choice.get("bitrate") in {128, 256, 320}:
            payload.update(downloadMode="audio", audioFormat="mp3", audioBitrate=str(choice["bitrate"]))
        else:
            raise MediaError("Select one of the supported output settings.")
        result = self._json("POST", timeout, payload, cancel, guard)
        if result.get("status") != "tunnel":
            raise MediaError("Cobalt returned an unsupported response. Server processing must be enabled.", 503)
        tunnel = result.get("url")
        try:
            parsed = urlsplit(tunnel)
            expected_path = urlsplit(self.url).path.rstrip("/") + "/tunnel"
            if (not isinstance(tunnel, str) or len(tunnel) > 8192
                    or any(ord(c) < 33 or ord(c) == 127 for c in tunnel)
                    or parsed.username or parsed.password or parsed.fragment
                    or origin(tunnel) != origin(self.url) or parsed.path != expected_path or not parsed.query):
                raise ValueError
        except (ValueError, TypeError, UnicodeError, AttributeError):
            raise MediaError("Cobalt returned an invalid download tunnel. Ask the operator to check its API_URL.", 502) from None
        filename = result.get("filename")
        if (not isinstance(filename, str) or len(filename) > 600
                or any(ord(c) < 32 for c in filename)
                or not filename.lower().endswith("." + choice["container"])):
            raise MediaError("Cobalt could not provide the selected output format. Choose another setting.", 502)
        return {"url": tunnel, "filename": filename}

    def download(self, url, choice, folder, max_bytes, timeout, cancel, progress, guard):
        deadline = time.monotonic() + timeout
        check_deadline(deadline, cancel, guard)
        progress("stage:Preparing the selected output")
        prepared = self.prepare(url, choice, min(timeout, 45), cancel, guard)
        path = folder / ("media." + choice["container"] + ".part")

        async def stream_file():
            remaining = max(0.1, deadline - time.monotonic())
            async with self.http_client(remaining) as client:
                # Keys never accompany signed tunnel requests. Redirects are
                # deliberately rejected instead of exposing internal network access.
                async with client.stream("GET", prepared["url"], headers={"Accept-Encoding": "identity"}) as response:
                    check_deadline(deadline, cancel, guard)
                    if response.status_code == 429:
                        raise MediaError("The download service is busy. Try again in a minute.", 429)
                    if response.status_code != 200:
                        raise MediaError("The download stream failed or expired. Check the video link again.", 502)
                    # Cobalt's FFmpeg streams omit Content-Type; validate their
                    # actual container/codecs with FFprobe before offering a file.
                    content_type = response.headers.get("content-type", "application/octet-stream").lower()
                    if not content_type.startswith(("video/", "audio/", "application/octet-stream")):
                        raise MediaError("The download service did not return a media file.", 502)
                    try:
                        total = int(response.headers.get("content-length", "0"))
                        estimate = max(0, int(response.headers.get("estimated-content-length", "0")))
                        if total < 0:
                            raise ValueError
                    except ValueError:
                        raise MediaError("The download stream returned an invalid size.", 502) from None
                    if total > max_bytes:
                        raise MediaError("This download exceeds the file-size limit. Choose a smaller output.")
                    downloaded = 0
                    start = time.monotonic()
                    with path.open("wb") as handle:
                        async for block in response.aiter_bytes():
                            check_deadline(deadline, cancel, guard)
                            downloaded += len(block)
                            if downloaded > max_bytes:
                                raise MediaError("This download exceeds the file-size limit. Choose a smaller output.")
                            handle.write(block)
                            speed = downloaded / max(0.01, time.monotonic() - start)
                            eta = max(0, round(((total or estimate) - downloaded) / speed)) if total or estimate else 0
                            progress(f"progress:{downloaded}|{total}|{estimate}|{speed}|{eta}|media")
                    if not downloaded or (total and downloaded != total):
                        raise MediaError("The download service returned an incomplete media file.", 502)
            check_deadline(deadline, cancel, guard)
            return path
        try:
            return asyncio.run(monitored(stream_file(), deadline, cancel, guard))
        except httpx.TimeoutException:
            path.unlink(missing_ok=True)
            check_deadline(deadline, cancel)
            raise MediaError("The download stream stalled. Try again later.", 504) from None
        except httpx.HTTPError:
            path.unlink(missing_ok=True)
            check_deadline(deadline, cancel)
            raise MediaError("The download stream was interrupted. Check the video link again.", 502) from None
        except Exception:
            path.unlink(missing_ok=True)
            raise
