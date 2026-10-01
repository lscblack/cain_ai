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


async def test_bare_domain_accepted(client, auth_headers):
    r = await client.post("/sources", json={"name": "Bare", "base_url": "example.com"}, headers=auth_headers)
    assert r.status_code == 201
    assert r.json()["base_url"].startswith("https://")


async def test_bulk_csv_add(client, auth_headers):
    csv = "name,base_url,max_depth,max_pages\nAlpha,8.8.8.8,1,10\nBeta,https://1.1.1.1/,2,20\nGamma,http://127.0.0.1/"
    r = await client.post("/sources/bulk", json={"csv": csv}, headers=auth_headers)
    assert r.status_code == 201
    body = r.json()
    assert len(body["created"]) == 2          # Alpha + Beta
    assert len(body["errors"]) == 1           # Gamma (SSRF loopback) rejected
    names = {s["name"] for s in body["created"]}
    assert names == {"Alpha", "Beta"}


async def test_edit_source(client, auth_headers):
    sid = (await client.post("/sources", json={"name": "Old", "base_url": "https://8.8.8.8/"}, headers=auth_headers)).json()["id"]
    r = await client.patch(f"/sources/{sid}", json={"name": "New", "max_depth": 3, "schedule": "daily", "priority": "high"}, headers=auth_headers)
    assert r.status_code == 200
    b = r.json()
    assert b["name"] == "New" and b["max_depth"] == 3 and b["schedule"] == "daily" and b["priority"] == "high"


async def test_seed_defaults(client, auth_headers):
    r = await client.post("/sources/seed-defaults", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["created"] > 100  # the curated list
    listing = (await client.get("/sources", headers=auth_headers)).json()
    assert any(s["domain"] == "github.com" for s in listing)
    assert any(s["domain"] == "ktpress.rw" for s in listing)
    # re-seed is idempotent (dedup by domain)
    r2 = await client.post("/sources/seed-defaults", headers=auth_headers)
    assert r2.json()["created"] == 0


async def test_bulk_update_all(client, auth_headers):
    await client.post("/sources", json={"name": "A", "base_url": "https://8.8.8.8/"}, headers=auth_headers)
    await client.post("/sources", json={"name": "B", "base_url": "https://1.1.1.1/"}, headers=auth_headers)
    r = await client.post("/sources/bulk-update", json={"max_depth": 3, "max_pages": 200, "schedule": "daily"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["updated"] == 2
    listing = (await client.get("/sources", headers=auth_headers)).json()
    assert all(s["max_depth"] == 3 and s["max_pages"] == 200 and s["schedule"] == "daily" for s in listing)


async def test_bulk_update_requires_field(client, auth_headers):
    r = await client.post("/sources/bulk-update", json={}, headers=auth_headers)
    assert r.status_code == 400


async def test_crawl_all_schedules(client, auth_headers):
    await client.post("/sources", json={"name": "A", "base_url": "https://8.8.8.8/"}, headers=auth_headers)
    await client.post("/sources", json={"name": "B", "base_url": "https://1.1.1.1/"}, headers=auth_headers)
    r = await client.post("/sources/crawl-all", headers=auth_headers)
    assert r.status_code == 202
    assert r.json()["scheduled"] == 2


async def test_crawl_all_empty(client, auth_headers):
    r = await client.post("/sources/crawl-all", headers=auth_headers)
    assert r.status_code == 202
    assert r.json()["scheduled"] == 0
