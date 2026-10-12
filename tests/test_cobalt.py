"""Exercise the Cobalt HTTP contract with an owned media fixture, without YouTube."""
import json
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import media
from app.config import Settings
from app.main import create_app

VIDEO = "https://www.youtube.com/watch?v=BaW_jenozKc"


@pytest.fixture
def cobalt_server(monkeypatch):
    state = {"posts": [], "gets": [], "error": None, "status": "tunnel",
             "stream": b"fixture", "stream_type": "video/mp4", "stream_status": 200,
             "omit_length": False, "tunnel": None, "body": None, "api_status": 200,
             "delay": 0, "release": threading.Event()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, status, body, kind="application/json"):
            self.send_response(status)
            if kind:
                self.send_header("Content-Type", kind)
            if not state["omit_length"]:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            state["gets"].append((self.path, self.headers.get("Authorization")))
            if self.path == "/":
                body = {"cobalt": {"version": "11.7.1", "services": ["youtube"]},
                        "git": {"commit": "test-commit"}}
                self.send(state["api_status"], json.dumps(body).encode())
            elif self.path.startswith("/tunnel?"):
                self.send(state["stream_status"], state["stream"], state["stream_type"])
            else:
                self.send(404, b"{}")

        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["posts"].append((payload, self.headers.get("Authorization")))
            state["release"].wait(timeout=state["delay"])
            if state["body"] is not None:
                self.send(200, state["body"])
                return
            if state["error"]:
                self.send(400, json.dumps({"status": "error", "error": {"code": state["error"]}}).encode())
                return
            ext = payload.get("audioFormat", "mp3") if payload["downloadMode"] == "audio" else "mp4"
            response = {"status": state["status"], "filename": "Fixture." + ext,
                        "url": state["tunnel"] or state["url"] + "tunnel?id=private-token"}
            self.send(200, json.dumps(response).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    state["url"] = f"http://127.0.0.1:{server.server_port}/"
    monkeypatch.setenv("COBALT_API_URL", state["url"])
    monkeypatch.setenv("COBALT_API_KEY", "operator-secret")
    thread.start()
    yield state
    state["release"].set()
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_preview_handles_unknown_duration_without_inventing_formats(tmp_path, monkeypatch):
    import app.jobs as jobs
    monkeypatch.setattr(jobs, "inspect_video", lambda *_args, **_kwargs: {
        "id": "BaW_jenozKc", "title": "Fixture", "duration": None, "channel": "Creator"})
    application = create_app(Settings(download_dir=tmp_path, min_free_bytes=1))
    with TestClient(application) as client:
        response = client.post("/api/inspect", json={"url": VIDEO})
        assert response.status_code == 200, response.text
        preview = response.json()
        assert preview["duration"] is None
        assert preview["options_are_presets"] is True
        assert {x["bitrate"] for x in preview["options"] if x["kind"] == "audio"} == {128, 256, 320}
        assert all(x["label"].startswith("Up to") for x in preview["options"] if x["kind"] == "video")
        assert all("cobalt" not in x and "selector" not in x for x in preview["options"])


def test_inspection_uses_private_cobalt_and_never_exposes_tunnel(cobalt_server, monkeypatch):
    # Metadata decoration is optional and must not depend on a second public service.
    monkeypatch.setattr(media, "fetch_metadata", lambda *_args, **_kwargs: {}, raising=False)
    info = media.inspect_video(VIDEO, timeout=2)
    assert info["id"] == "BaW_jenozKc"
    assert info["duration"] is None
    payload, auth = cobalt_server["posts"][0]
    assert payload["url"] == VIDEO
    assert payload["alwaysProxy"] is True
    assert payload["localProcessing"] == "disabled"
    assert payload["downloadMode"] == "auto"
    assert auth == "Api-Key operator-secret"
    assert "private-token" not in json.dumps(info)
    assert "operator-secret" not in json.dumps(info)


@pytest.mark.parametrize("code, message, status", [
    ("error.api.youtube.login", "bot check", 502),
    ("error.api.content.video.private", "restricted", 400),
    ("error.api.content.video.age", "restricted", 400),
    ("error.api.content.video.live", "Live", 400),
    ("error.api.content.too_long", "duration", 400),
    ("error.api.rate_exceeded", "busy", 429),
    ("error.api.auth.key.missing", "API key", 503),
    ("error.api.youtube.no_session_tokens", "session", 503),
])
def test_cobalt_error_codes_have_actionable_messages(cobalt_server, code, message, status):
    cobalt_server["error"] = code
    with pytest.raises(media.MediaError, match=message) as result:
        media.inspect_video(VIDEO, timeout=2)
    assert result.value.status == status
    assert "operator-secret" not in str(result.value)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:1/tunnel?id=secret", "https://evil.example/tunnel?id=secret",
    "file:///etc/passwd", "http://user:password@127.0.0.1:9000/tunnel",
])
def test_foreign_tunnel_urls_are_rejected(cobalt_server, url):
    cobalt_server["tunnel"] = url
    with pytest.raises(media.MediaError, match="tunnel"):
        media.inspect_video(VIDEO, timeout=2)


@pytest.mark.parametrize("status", ["redirect", "local-processing", "picker"])
def test_unsupported_responses_do_not_escape_server_processing(cobalt_server, status):
    cobalt_server["status"] = status
    with pytest.raises(media.MediaError, match="response|processing"):
        media.inspect_video(VIDEO, timeout=2)


def test_cobalt_json_is_bounded(cobalt_server):
    cobalt_server["body"] = json.dumps({"data": "x" * 300_000}).encode()
    with pytest.raises(media.MediaError, match="too much"):
        media.inspect_video(VIDEO, timeout=2)


@pytest.fixture(scope="module")
def owned_files(tmp_path_factory):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("The owned fixture requires FFmpeg and FFprobe")
    root = tmp_path_factory.mktemp("owned")
    video = root / "owned.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x90:r=10",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "1",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-y", str(video)],
                   check=True, timeout=20)
    audio = root / "owned.mp3"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-vn", "-b:a", "128k", "-y", str(audio)],
                   check=True, timeout=20)
    return {"mp4": video.read_bytes(), "mp3": audio.read_bytes()}


@pytest.mark.parametrize("option_id, container", [("mp4-720", "mp4"), ("mp3-256", "mp3")])
def test_real_streamed_file_is_validated_and_saved(cobalt_server, owned_files, tmp_path, option_id, container):
    from app.jobs import download_media
    choice = next(x for x in media.format_options({}) if x["id"] == option_id)
    cobalt_server["stream"] = owned_files[container]
    cobalt_server["stream_type"] = "video/mp4" if container == "mp4" else "audio/mpeg"
    lines = []
    output = download_media(VIDEO, choice, tmp_path, 1_000_000, 10,
                            threading.Event(), lines.append, lambda: None)
    assert output.name == "media." + container
    assert output.read_bytes() == owned_files[container]
    payload, _auth = cobalt_server["posts"][0]
    assert payload["downloadMode"] == ("auto" if container == "mp4" else "audio")
    if container == "mp3":
        assert payload["audioFormat"] == "mp3" and payload["audioBitrate"] == "256"
    assert any(x.startswith("progress:") for x in lines)
    assert any(x[0].startswith("/tunnel?") for x in cobalt_server["gets"])
    # API keys belong on POST requests only, never on signed tunnel downloads.
    assert all(auth is None for path, auth in cobalt_server["gets"] if path.startswith("/tunnel"))


@pytest.mark.parametrize("omit_length", [False, True])
def test_size_limit_applies_to_known_and_unknown_stream_lengths(cobalt_server, tmp_path, omit_length):
    from app.jobs import download_media
    cobalt_server["stream"] = b"x" * 10000
    cobalt_server["omit_length"] = omit_length
    choice = next(x for x in media.format_options({}) if x["id"] == "mp4-360")
    with pytest.raises(media.MediaError, match="size limit"):
        download_media(VIDEO, choice, tmp_path, 100, 10, threading.Event(), lambda _line: None, lambda: None)
    assert not list(tmp_path.glob("media.*"))


def test_cancelled_download_never_requests_a_tunnel(cobalt_server, tmp_path):
    from app.jobs import download_media
    cancel = threading.Event()
    cancel.set()
    choice = next(x for x in media.format_options({}) if x["id"] == "mp4-360")
    with pytest.raises(media.MediaError, match="cancelled"):
        download_media(VIDEO, choice, tmp_path, 1000, 2, cancel, lambda _line: None, lambda: None)
    assert not cobalt_server["posts"]


def test_non_media_response_is_not_offered_as_a_download(cobalt_server, tmp_path):
    from app.jobs import download_media
    cobalt_server["stream"] = b"<html>YouTube error</html>"
    cobalt_server["stream_type"] = "text/html"
    choice = next(x for x in media.format_options({}) if x["id"] == "mp4-360")
    with pytest.raises(media.MediaError, match="media"):
        download_media(VIDEO, choice, tmp_path, 1000, 2, threading.Event(), lambda _line: None, lambda: None)
    assert not list(tmp_path.glob("media.*"))


def test_valid_media_without_content_type_is_verified_by_ffprobe(cobalt_server, owned_files, tmp_path):
    from app.jobs import download_media
    cobalt_server["stream"] = owned_files["mp3"]
    cobalt_server["stream_type"] = None
    choice = next(x for x in media.format_options({}) if x["id"] == "mp3-128")
    output = download_media(VIDEO, choice, tmp_path, 1_000_000, 5,
                            threading.Event(), lambda _line: None, lambda: None)
    assert output.read_bytes() == owned_files["mp3"]


def test_health_reports_cobalt_not_legacy_extractor(cobalt_server, tmp_path):
    application = create_app(Settings.from_env())
    with TestClient(application) as client:
        response = client.get("/api/health")
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["versions"]["cobalt"] == "11.7.1"
        assert result["dependencies"]["cobalt_api"] is True
        assert "yt_dlp" not in result["versions"]
        assert "operator-secret" not in response.text
        assert cobalt_server["url"] not in response.text


def test_health_is_unready_if_cobalt_is_unreachable(cobalt_server):
    cobalt_server["api_status"] = 503
    application = create_app(Settings.from_env())
    with TestClient(application) as client:
        response = client.get("/api/health")
        assert response.status_code == 503
        assert response.json()["status"] == "setup_required"


def test_preflight_may_take_longer_than_five_seconds_within_deadline(cobalt_server, monkeypatch):
    monkeypatch.setattr(media, "fetch_metadata", lambda *_args, **_kwargs: {})
    cobalt_server["delay"] = 5.2
    assert media.inspect_video(VIDEO, timeout=8)["id"] == "BaW_jenozKc"


def test_cancel_interrupts_pending_preflight_promptly(cobalt_server, tmp_path):
    from app.jobs import download_media
    cobalt_server["delay"] = 5
    cancel = threading.Event()
    timer = threading.Timer(0.15, cancel.set)
    timer.start()
    started = time.monotonic()
    choice = next(x for x in media.format_options({}) if x["id"] == "mp4-360")
    try:
        with pytest.raises(media.MediaError, match="cancelled"):
            download_media(VIDEO, choice, tmp_path, 1000, 8, cancel, lambda _line: None, lambda: None)
        assert time.monotonic() - started < 1.5
    finally:
        timer.cancel()
        cobalt_server["release"].set()


def test_real_http_contract_through_complete_app(cobalt_server, owned_files, monkeypatch, tmp_path):
    from dataclasses import replace
    monkeypatch.setattr(media, "fetch_metadata", lambda *_args, **_kwargs: {"title": "Owned fixture", "channel": "Test"})
    cobalt_server["stream"] = owned_files["mp4"]
    settings = replace(Settings.from_env(), download_dir=tmp_path, min_free_bytes=1)
    application = create_app(settings)
    with TestClient(application) as client:
        preview = client.post("/api/inspect", json={"url": VIDEO}).json()
        response = client.post("/api/jobs", json={"inspection_id": preview["inspection_id"],
                                                "option_id": "mp4-360", "authorized": True})
        assert response.status_code == 202, response.text
        job_id = response.json()["id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            job = client.get("/api/jobs/" + job_id).json()
            if job["status"] in {"ready", "failed"}:
                break
            time.sleep(0.02)
        assert job["status"] == "ready", job
        assert client.get(job["file_url"]).content == owned_files["mp4"]
        assert len(cobalt_server["posts"]) == 2  # preflight, then a fresh tunnel
        assert client.head("/").status_code == 200
