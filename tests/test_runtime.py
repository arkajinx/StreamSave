import os
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path

import pytest

from app.config import Settings


def test_bundled_environment_uses_private_api_and_matching_limits(tmp_path, monkeypatch):
    import run
    settings = replace(Settings(download_dir=tmp_path), cobalt_api_url="http://127.0.0.1:9100/", max_duration=1200)
    monkeypatch.setenv("API_URL", "https://untrusted.example")
    monkeypatch.setattr(run.shutil, "which", lambda name: "/usr/bin/ffmpeg" if name == "ffmpeg" else None)
    env = run.cobalt_environment(settings)
    assert env["API_URL"] == "http://127.0.0.1:9100/"
    assert env["API_PORT"] == "9100"
    assert env["API_LISTEN_ADDRESS"] == "127.0.0.1"
    assert env["DURATION_LIMIT"] == "1200"
    assert env["FORCE_LOCAL_PROCESSING"] == "never"
    assert "FREEBIND_CIDR" not in env
    assert env["FFMPEG_BIN"] == "/usr/bin/ffmpeg"


def test_bundled_cobalt_cannot_be_pointed_at_external_host(tmp_path):
    import run
    settings = replace(Settings(download_dir=tmp_path), cobalt_api_url="https://api.example/")
    with pytest.raises(RuntimeError, match="localhost"):
        run.cobalt_environment(settings)


@pytest.mark.skipif(os.name == "nt", reason="Unix process-group supervision")
def test_stopping_child_also_stops_descendants(tmp_path):
    import run
    heartbeat = tmp_path / "heartbeat"
    child_code = f"import time; from pathlib import Path; time.sleep(1); Path({str(heartbeat)!r}).write_text('leaked'); time.sleep(10)"
    parent_code = "import subprocess,sys,time; subprocess.Popen([sys.executable,'-c'," + repr(child_code) + "]); time.sleep(20)"
    proc = subprocess.Popen([sys.executable, "-c", parent_code], start_new_session=True)
    try:
        time.sleep(.15)
        run.stop_process(proc, grace=.1)
        time.sleep(1)
        assert not heartbeat.exists()
        assert proc.poll() is not None
    finally:
        if proc.poll() is None:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
