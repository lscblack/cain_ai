import pytest_asyncio

from app.intelligence.geo import extract_coords


def test_extract_coords_from_meta():
    assert extract_coords(None, {"lat": -1.95, "lon": 30.06}) == (-1.95, 30.06)
    assert extract_coords(None, {"latitude": "40.7", "longitude": "-74.0"}) == (40.7, -74.0)


def test_extract_coords_from_value():
    assert extract_coords("-1.9500,30.0600", None) == (-1.95, 30.06)


def test_extract_coords_invalid():
    assert extract_coords("not coords", None) is None
    assert extract_coords(None, {"lat": 999, "lon": 0}) is None


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_map_points(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "Geo"}, headers=auth_headers)).json()
    cid = case["id"]
    await client.post(
        f"/investigations/{cid}/entities",
        json={"type": "location", "value": "Kigali", "metadata": {"lat": -1.95, "lon": 30.06}},
        headers=auth_headers,
    )
    await client.post(
        f"/investigations/{cid}/entities",
        json={"type": "phone", "value": "+250788123456"},  # no coords
        headers=auth_headers,
    )
    r = await client.get(f"/investigations/{cid}/map", headers=auth_headers)
    body = r.json()
    assert body["count"] == 1
    assert body["points"][0]["lat"] == -1.95


async def test_timeline_sorted(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "T"}, headers=auth_headers)).json()
    cid = case["id"]
    await client.post(f"/investigations/{cid}/entities", json={"type": "phone", "value": "+250788123456"}, headers=auth_headers)
    await client.post(
        f"/investigations/{cid}/evidence",
        json={"type": "phone", "source_url": "https://example.com/p"},
        headers=auth_headers,
    )
    r = await client.get(f"/investigations/{cid}/timeline", headers=auth_headers)
    body = r.json()
    assert body["count"] >= 2
    ats = [e["at"] for e in body["events"]]
    assert ats == sorted(ats)
