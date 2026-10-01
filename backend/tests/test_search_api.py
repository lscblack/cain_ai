import pytest_asyncio


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_search_requires_auth(client):
    assert (await client.get("/search?q=test")).status_code == 401


async def test_search_detects_type(client, auth_headers):
    r = await client.get("/search?q=%2B250788123456", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["detected_type"] == "phone"

    r2 = await client.get("/search?q=alice@example.com", headers=auth_headers)
    assert r2.json()["detected_type"] == "email"


async def test_search_finds_entity_across_cases(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "C1"}, headers=auth_headers)).json()
    await client.post(
        f"/investigations/{case['id']}/entities",
        json={"type": "phone", "value": "+250788123456"},
        headers=auth_headers,
    )
    r = await client.get("/search?q=%2B250788123456", headers=auth_headers)
    body = r.json()
    assert body["detected_type"] == "phone"
    assert len(body["entity_matches"]) == 1
    assert body["entity_matches"][0]["value"] == "+250788123456"


async def test_search_finds_evidence_by_source_url(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "C2"}, headers=auth_headers)).json()
    await client.post(
        f"/investigations/{case['id']}/evidence",
        json={"type": "url", "source_url": "https://example.com/leak-page"},
        headers=auth_headers,
    )
    r = await client.get("/search?q=leak-page", headers=auth_headers)
    body = r.json()
    assert len(body["evidence_matches"]) == 1


async def test_search_no_matches(client, auth_headers):
    r = await client.get("/search?q=nothinghere12345", headers=auth_headers)
    body = r.json()
    assert body["entity_matches"] == []
    assert body["evidence_matches"] == []
