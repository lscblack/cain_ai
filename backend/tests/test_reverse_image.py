import types

import app.providers.reverse_image as rimod
from app.providers.reverse_image import SerpApiReverseImage


def _settings_with(key: str):
    return types.SimpleNamespace(serpapi_api_key=key)


async def test_unavailable_without_key(monkeypatch):
    monkeypatch.setattr(rimod, "get_settings", lambda: _settings_with(""))
    p = SerpApiReverseImage()
    health = await p.health_check()
    assert health.healthy is False
    assert health.configured is False
    assert await p.search({"image_url": "https://x/y.jpg"}) == []


async def test_search_with_mocked_http(monkeypatch):
    monkeypatch.setattr(rimod, "get_settings", lambda: _settings_with("test-key"))

    async def fake_get(url, params):
        assert params["api_key"] == "test-key"
        return {
            "visual_matches": [
                {"link": "https://news.example/story", "thumbnail": "https://cdn/1.jpg", "title": "A"},
            ]
        }

    p = SerpApiReverseImage(http_get=fake_get)
    assert (await p.health_check()).healthy is True
    results = await p.search({"image_url": "https://x/y.jpg", "engine": "yandex"})
    assert len(results) == 1
    assert results[0]["source_url"] == "https://news.example/story"
    assert results[0]["provider"] == "serpapi_reverse_image"
