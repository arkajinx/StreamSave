from pathlib import Path
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_source_offer_excludes_secrets_and_downloads(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    (root / "app").mkdir()
    (root / "app/main.py").write_text("print('source')")
    (root / "app/.env.secret.json").write_text('{"key":"very-secret"}')
    (root / "app/credentials.json").write_text('{"key":"very-secret"}')
    (root / ".env").write_text("COBALT_API_KEY=very-secret")
    (root / ".env.example").write_text("COBALT_API_KEY=")
    (root / "data").mkdir()
    (root / "data/private.mp4").write_bytes(b"private-media")
    (root / "LICENSE").write_text("license")
    from scripts.source_bundle import make_bundle
    output = make_bundle(root, tmp_path / "offer.zip")
    with ZipFile(output) as archive:
        names = archive.namelist()
        assert "StreamSave/app/main.py" in names
        assert "StreamSave/.env.example" in names
        assert not any("private" in name or name.endswith("/.env") for name in names)
        assert not any("secret" in name or "credentials" in name for name in names)
    monkeypatch.setenv("SOURCE_ARCHIVE", str(output))
    application = create_app(Settings(download_dir=tmp_path / "downloads", min_free_bytes=1))
    with TestClient(application) as client:
        response = client.get("/source")
        assert response.status_code == 200
        assert response.content == output.read_bytes()
        assert "attachment" in response.headers["content-disposition"]
