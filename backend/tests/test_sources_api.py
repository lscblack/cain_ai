import pytest_asyncio


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_sources_requires_auth(client):
    assert (await client.get("/sources")).status_code == 401


async def test_create_rejects_ssrf_base_url(client, auth_headers):
    # literal loopback -> blocked, no DNS needed
    r = await client.post(
        "/sources", json={"name": "bad", "base_url": "http://127.0.0.1/"}, headers=auth_headers
    )
    assert r.status_code == 422


async def test_create_and_list_source(client, auth_headers):
    # literal public IP avoids DNS in tests
    r = await client.post(
        "/sources",
        json={"name": "Pub", "base_url": "https://8.8.8.8/", "max_depth": 1, "max_pages": 5},
        headers=auth_headers,
    )
    assert r.status_code == 201
    assert r.json()["domain"] == "8.8.8.8"
    assert r.json()["status"] == "idle"

    listing = (await client.get("/sources", headers=auth_headers)).json()
    assert len(listing) == 1


async def test_source_stats_zero_initially(client, auth_headers):
    sid = (
        await client.post(
            "/sources", json={"name": "Pub", "base_url": "https://8.8.8.8/"}, headers=auth_headers
        )
    ).json()["id"]
    stats = (await client.get(f"/sources/{sid}/stats", headers=auth_headers)).json()
    assert stats["pages"] == 0
    assert stats["images"] == 0
    assert stats["faces"] == 0


async def test_delete_source(client, auth_headers):
    sid = (
        await client.post(
            "/sources", json={"name": "Pub", "base_url": "https://8.8.8.8/"}, headers=auth_headers
        )
    ).json()["id"]
    assert (await client.delete(f"/sources/{sid}", headers=auth_headers)).status_code == 204
    assert (await client.get(f"/sources/{sid}/stats", headers=auth_headers)).status_code == 404
