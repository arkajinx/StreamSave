"""Validate real final-file contents independently of the download service."""
import pytest
import subprocess
from app.media import MediaError, probe_media
from tests.test_cobalt import owned_files


def test_html_cannot_be_offered_as_video(tmp_path):
    path=tmp_path / "media.mp4"
    path.write_bytes(b"<html>blocked</html>")
    with pytest.raises(MediaError, match="valid media"):
        probe_media(path,{"kind":"video","container":"mp4"},1800)


def test_wrong_container_cannot_be_disguised_as_mp4(tmp_path,owned_files):
    path=tmp_path / "media.mp4"
    path.write_bytes(owned_files["mp3"])
    with pytest.raises(MediaError, match="valid media"):
        probe_media(path,{"kind":"video","container":"mp4"},1800)


def test_duration_limit_is_checked_on_actual_completed_file(tmp_path,owned_files):
    path=tmp_path / "media.mp4"
    path.write_bytes(owned_files["mp4"])
    with pytest.raises(MediaError, match="duration limit"):
        probe_media(path,{"kind":"video","container":"mp4"},.1)


def test_truncated_fragmented_mp4_is_rejected(tmp_path, owned_files):
    source = tmp_path / "source.mp4"
    source.write_bytes(owned_files["mp4"])
    fragmented = tmp_path / "fragmented.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(source), "-c", "copy",
                    "-movflags", "faststart+frag_keyframe+empty_moov", "-y", str(fragmented)],
                   check=True, timeout=15)
    probe_media(fragmented, {"kind":"video","container":"mp4"}, 1800)
    data = fragmented.read_bytes()
    # The valid moov header remains, so a metadata-only probe accepts this.
    damaged = tmp_path / "damaged.mp4"
    damaged.write_bytes(data[:int(len(data)*.5)])
    with pytest.raises(MediaError, match="valid media"):
        probe_media(damaged, {"kind":"video","container":"mp4"}, 1800)
