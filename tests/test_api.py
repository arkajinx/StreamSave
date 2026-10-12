import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.media import MediaError
from tests.test_media import sample_info


@pytest.fixture
def application(tmp_path, monkeypatch):
    import app.jobs as jobs
    monkeypatch.setattr(jobs, "inspect_video", lambda *_args, **_kwargs: sample_info())
    def download(_url, choice, folder, _limit, _timeout, cancel, progress, guard, **_settings):
        guard()
        progress("progress:500|1000|NA|100|5|18")
        path = folder / ("media." + choice["container"])
        path.write_bytes(b"test media fixture")
        return path
    monkeypatch.setattr(jobs, "download_media", download)
    import app.main as main
    monkeypatch.setattr(main, "health_report", lambda *_args: {"status":"ok", "dependencies":{"cobalt_api":True,"ffprobe":True}, "versions":{"app":"2.0.0","cobalt":"fixture-api"}})
    return create_app(Settings(download_dir=tmp_path / "downloads", min_free_bytes=1, file_ttl=2))


def inspect(client):
    response = client.post("/api/inspect", json={"url": "https://youtu.be/BaW_jenozKc"})
    assert response.status_code == 200, response.text
    return response.json()


def create_job(client, preview):
    response = client.post("/api/jobs", json={"inspection_id": preview["inspection_id"], "option_id": "mp4-360", "authorized": True})
    assert response.status_code == 202, response.text
    return response.json()["id"]


def completed(client, job_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        result = client.get(f"/api/jobs/{job_id}")
        if result.status_code == 200 and result.json()["status"] in {"ready", "failed", "cancelled"}:
            return result.json()
        time.sleep(0.01)
    pytest.fail("Background job did not finish")


def test_download_lifecycle_and_owner_isolation(application):
    with TestClient(application) as owner:
        preview = inspect(owner)
        assert preview["title"] == "A test / title"
        assert all("selector" not in option for option in preview["options"])
        job_id = create_job(owner, preview)
        result = completed(owner, job_id)
        assert result["status"] == "ready"
        response = owner.get(f"/api/jobs/{job_id}/file")
        assert response.content == b"test media fixture"
        assert "attachment" in response.headers["content-disposition"]
        outsider = TestClient(application)
        outsider.get("/api/config")
        assert outsider.get(f"/api/jobs/{job_id}").status_code == 404
        assert outsider.get(f"/api/jobs/{job_id}/file").status_code == 404
        assert outsider.delete(f"/api/jobs/{job_id}").status_code == 404


def test_authorization_and_selection_are_required(application):
    with TestClient(application) as client:
        preview = inspect(client)
        assert client.post("/api/jobs", json={"inspection_id": preview["inspection_id"], "option_id": "mp4-360", "authorized": False}).status_code == 400
        assert client.post("/api/jobs", json={"inspection_id": preview["inspection_id"], "option_id": "--exec=touch", "authorized": True}).status_code == 400


def test_metadata_is_scoped_to_inspecting_browser(application):
    with TestClient(application) as owner:
        preview = inspect(owner)
        stranger = TestClient(application)
        assert stranger.post("/api/jobs", json={"inspection_id": preview["inspection_id"], "option_id": "mp4-360", "authorized": True}).status_code == 404


def test_inspection_expires_and_returns_clear_error(application):
    with TestClient(application) as client:
        preview = inspect(client)
        application.state.manager.inspections[preview["inspection_id"]].created -= 1000
        assert client.post("/api/jobs", json={"inspection_id": preview["inspection_id"], "option_id": "mp4-360", "authorized": True}).status_code == 410


def test_files_and_metadata_are_deleted_after_expiry(application):
    with TestClient(application) as client:
        job_id = create_job(client, inspect(client))
        assert completed(client, job_id)["status"] == "ready"
        manager = application.state.manager
        job = manager.jobs[job_id]
        output = job.path
        job.finished -= 3
        manager.cleanup()
        assert not output.exists()
        assert client.get(f"/api/jobs/{job_id}").status_code == 404


def test_upstream_failure_is_explicit(application, monkeypatch):
    import app.jobs as jobs
    def blocked(*_args, **_kwargs):
        raise MediaError("YouTube refused this request.", 502)
    monkeypatch.setattr(jobs, "inspect_video", blocked)
    with TestClient(application) as client:
        response = client.post("/api/inspect", json={"url": "https://youtu.be/BaW_jenozKc"})
        assert response.status_code == 502
        assert response.json()["detail"] == "YouTube refused this request."


def test_cross_origin_mutations_are_rejected(application):
    with TestClient(application) as client:
        response = client.post("/api/inspect", json={"url": "https://youtu.be/BaW_jenozKc"}, headers={"Origin": "https://evil.example"})
        assert response.status_code == 403


def test_rate_limit_bounds_inspections(tmp_path, monkeypatch):
    import app.jobs as jobs
    monkeypatch.setattr(jobs, "inspect_video", lambda *_args, **_kwargs: sample_info())
    app = create_app(Settings(download_dir=tmp_path, max_requests_per_minute=1, min_free_bytes=1))
    with TestClient(app) as client:
        assert client.post("/api/inspect", json={"url": "https://youtu.be/BaW_jenozKc"}).status_code == 200
        assert client.post("/api/inspect", json={"url": "https://youtu.be/BaW_jenozKc"}).status_code == 429


def test_long_videos_are_rejected(application, monkeypatch):
    import app.jobs as jobs
    info = sample_info()
    info["duration"] = 7200
    monkeypatch.setattr(jobs, "inspect_video", lambda *_args, **_kwargs: info)
    with TestClient(application) as client:
        response = client.post("/api/inspect", json={"url": "https://youtu.be/BaW_jenozKc"})
        assert response.status_code == 400
        assert "60 minutes" in response.json()["detail"]


def test_cancellation_stops_work_and_cleans_files(application, monkeypatch):
    import app.jobs as jobs
    def waiting(_url, _choice, folder, _limit, _timeout, cancel, _progress, _guard, **_settings):
        (folder / "unfinished.part").write_bytes(b"partial")
        cancel.wait(timeout=3)
        raise MediaError("Download cancelled.", 409)
    monkeypatch.setattr(jobs, "download_media", waiting)
    with TestClient(application) as client:
        job_id = create_job(client, inspect(client))
        assert client.delete(f"/api/jobs/{job_id}").status_code == 200
        assert completed(client, job_id)["status"] == "cancelled"
        assert not (application.state.manager.settings.download_dir / job_id).exists()


def test_resource_guard_fails_oversized_job(application, monkeypatch):
    import app.jobs as jobs
    def too_large(_url, _choice, folder, _limit, _timeout, _cancel, _progress, guard, **_settings):
        with (folder / "huge.part").open("wb") as handle:
            handle.truncate(application.state.manager.settings.max_file_bytes * 3)
        guard()
        pytest.fail("Guard did not enforce job storage limit")
    monkeypatch.setattr(jobs, "download_media", too_large)
    with TestClient(application) as client:
        job_id = create_job(client, inspect(client))
        result = completed(client, job_id)
        assert result["status"] == "failed"
        assert "size limit" in result["error"]
        assert not (application.state.manager.settings.download_dir / job_id).exists()


def test_health_and_static_security_headers(application):
    import importlib.metadata
    with TestClient(application) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        versions = health.json()["versions"]
        assert versions["cobalt"] == "fixture-api"
        assert "yt_dlp" not in versions
        assert versions["app"]
        assert "COBALT_API_KEY" not in health.text
        assert "httponly" in health.headers["set-cookie"].lower()
        response = client.get("/api/config")
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["cache-control"] == "no-store"


def test_invalid_range_releases_file_and_allows_cleanup(application):
    with TestClient(application) as client:
        job_id = create_job(client, inspect(client))
        assert completed(client, job_id)["status"] == "ready"
        assert client.get(f"/api/jobs/{job_id}/file", headers={"Range": "bytes=99999-"}).status_code == 416
        manager = application.state.manager
        assert manager.jobs[job_id].readers == 0
        assert client.delete(f"/api/jobs/{job_id}").status_code == 200


def test_reset_frees_queue_slot_without_waiting_for_ttl(application):
    from dataclasses import replace
    application.state.manager.settings = replace(application.state.manager.settings, max_jobs=1)
    with TestClient(application) as client:
        preview = inspect(client)
        first = create_job(client, preview)
        assert completed(client, first)["status"] == "ready"
        response = client.post("/api/jobs", json={"inspection_id": preview["inspection_id"], "option_id": "mp4-360", "authorized": True})
        assert response.status_code == 429
        assert client.delete(f"/api/jobs/{first}").status_code == 200
        second = create_job(client, preview)
        assert second != first
        assert completed(client, second)["status"] == "ready"


def test_oversized_json_body_is_rejected(application):
    with TestClient(application) as client:
        assert client.post("/api/inspect", content=b"x" * 5000, headers={"Content-Type": "application/json"}).status_code == 413


def test_static_app_is_served_with_local_assets(application):
    with TestClient(application) as client:
        response = client.get("/")
        assert response.status_code == 200
        assert 'id="video-url"' in response.text
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/static/styles.css").status_code == 200


def test_queued_cancellation_is_immediate(tmp_path, monkeypatch):
    from threading import Event
    import app.jobs as jobs
    application = create_app(Settings(download_dir=tmp_path / "downloads", max_concurrent=1, min_free_bytes=1))
    monkeypatch.setattr(jobs, "inspect_video", lambda *_args, **_kwargs: sample_info())
    running, release = Event(), Event()
    def occupied(_url, choice, folder, _limit, _timeout, cancel, _progress, _guard, **_settings):
        running.set()
        release.wait(timeout=3)
        if cancel.is_set():
            raise MediaError("Download cancelled.", 409)
        path = folder / ("media." + choice["container"])
        path.write_bytes(b"test fixture")
        return path
    monkeypatch.setattr(jobs, "download_media", occupied)
    with TestClient(application) as client:
        preview = inspect(client)
        first = create_job(client, preview)
        assert running.wait(timeout=1)
        queued = create_job(client, preview)
        assert client.get(f"/api/jobs/{queued}").json()["status"] == "queued"
        try:
            response = client.delete(f"/api/jobs/{queued}")
            assert response.json()["status"] == "cancelled"
            assert client.get(f"/api/jobs/{first}").json()["status"] == "downloading"
        finally:
            release.set()
