import pytest
from app.media import MediaError, canonical_url


@pytest.mark.parametrize("url", [
    "https://youtu.be/BaW_jenozKc?t=3",
    "https://www.youtube.com/watch?v=BaW_jenozKc&list=PLanything",
    "https://m.youtube.com/shorts/BaW_jenozKc",
    "youtube.com/embed/BaW_jenozKc",
])
def test_supported_links_become_single_canonical_video(url):
    assert canonical_url(url) == "https://www.youtube.com/watch?v=BaW_jenozKc"



@pytest.mark.parametrize("url", [
    "http://127.0.0.1/watch?v=BaW_jenozKc", "file:///etc/passwd",
    "https://youtube.com.evil.example/watch?v=BaW_jenozKc",
    "https://youtube.com@evil.example/watch?v=BaW_jenozKc",
    "https://evil.example@youtube.com/watch?v=BaW_jenozKc",
    "https://www.youtube.com:8080/watch?v=BaW_jenozKc",
    "https://youtube.com/playlist?list=123", "https://youtube.com/watch?v=123",
    "https://youtu.be/BaW_jenozKc/extra", "https://youtube.com/watch?v=BaW_jenozKc&v=aaaaaaaaaaa",
    "https://youtube.com/watch?v=BaW_jenozKc\n--exec=touch", "--exec=touch /tmp/anything",
])
def test_rejects_non_video_urls(url):
    with pytest.raises(MediaError):
        canonical_url(url)



def sample_info():
    return {"id":"BaW_jenozKc","title":"A test / title","duration":9,"channel":"Test channel"}
