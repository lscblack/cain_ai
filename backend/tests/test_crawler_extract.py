from app.crawlers.extract import extract_image_urls, extract_links, path_allowed
from app.intelligence.face.dedup import (
    average_hash,
    hamming_distance,
    is_near_duplicate,
    sha256_bytes,
)

HTML = """
<html><body>
  <img src="/images/a.jpg">
  <img src='https://cdn.example.com/b.png' >
  <img srcset="/images/c-small.webp 480w, /images/c-large.webp 1024w">
  <a href="/news/story-1">Story</a>
  <a href="https://other.com/x">external</a>
  <a href="mailto:x@y.com">mail</a>
  <a href="#frag">frag</a>
</body></html>
"""


def test_extract_images_resolves_and_filters():
    imgs = extract_image_urls(HTML, "https://example.com/page")
    assert "https://example.com/images/a.jpg" in imgs
    assert "https://cdn.example.com/b.png" in imgs
    assert any("c-small.webp" in u for u in imgs)


def test_extract_links_same_host_only():
    links = extract_links(HTML, "https://example.com/page")
    assert "https://example.com/news/story-1" in links
    assert all("other.com" not in u for u in links)
    assert all("mailto" not in u for u in links)


def test_path_allowed_rules():
    assert path_allowed("https://e.com/news/x", ["/news"], []) is True
    assert path_allowed("https://e.com/admin/x", ["/news"], []) is False
    assert path_allowed("https://e.com/news/secret", [], ["/news/secret"]) is False
    assert path_allowed("https://e.com/anything", [], []) is True


def test_sha256_and_phash():
    assert sha256_bytes(b"abc") == sha256_bytes(b"abc")
    assert sha256_bytes(b"abc") != sha256_bytes(b"abd")


def test_phash_on_bad_bytes_returns_none():
    assert average_hash(b"not an image") is None


def test_hamming_and_near_dup():
    assert hamming_distance("ffff", "ffff") == 0
    assert hamming_distance("ffff", "fffe") == 1
    assert is_near_duplicate("ffff", "fffe", threshold=5) is True
    assert is_near_duplicate("0000", "ffff", threshold=5) is False
