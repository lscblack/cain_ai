import httpx
import pytest

from app.api import geoint


@pytest.fixture(autouse=True)
def _clear_cache():
    geoint._ELEV_CACHE.clear()


async def test_elevation_requires_auth(client):
    r = await client.get("/geoint/elevation", params={"points": "0,0"})
    assert r.status_code == 401


async def test_elevation_ok(client, auth_headers, monkeypatch):
    async def fake(points):
        return [100.0, None]

    monkeypatch.setattr(geoint, "_fetch_opentopo", fake)
    r = await client.get("/geoint/elevation", params={"points": "0,0|1,1"}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert len(body["results"]) == 2
    assert body["results"][0] == {"lat": 0.0, "lon": 0.0, "elevation_m": 100.0}
    assert body["results"][1]["elevation_m"] is None


async def test_elevation_malformed_points(client, auth_headers):
    for bad in ("not-a-coord", "", "1,2|x", "91,0", "0,181"):
        r = await client.get("/geoint/elevation", params={"points": bad}, headers=auth_headers)
        assert r.status_code == 422, bad


async def test_elevation_upstream_failure_is_handled(client, auth_headers, monkeypatch):
    async def boom(points):
        raise httpx.HTTPError("down")

    monkeypatch.setattr(geoint, "_fetch_opentopo", boom)
    r = await client.get("/geoint/elevation", params={"points": "0,0"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is False
    assert r.json()["reason"]


async def test_elevation_malformed_upstream_payload_is_handled(client, auth_headers, monkeypatch):
    class FakeResp:
        status_code = 200

        def json(self):
            return {"results": ["not-a-dict"]}

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, *a, **k):
            return FakeResp()

    monkeypatch.setattr(geoint.httpx, "AsyncClient", FakeClient)
    r = await client.get("/geoint/elevation", params={"points": "0,0"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["ok"] is False
