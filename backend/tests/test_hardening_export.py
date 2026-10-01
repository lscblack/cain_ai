import pytest_asyncio


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_security_headers_present(client):
    r = await client.get("/health")
    assert r.headers.get("x-content-type-options") == "nosniff"
    assert r.headers.get("x-frame-options") == "DENY"
    assert r.headers.get("referrer-policy") == "no-referrer"


async def test_login_rate_limited(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    # 10 allowed within window; the 11th should be 429
    statuses = []
    for _ in range(12):
        r = await client.post("/auth/login", json={"email": "op@example.com", "password": "wrong"})
        statuses.append(r.status_code)
    assert 429 in statuses


async def test_export_json_and_csv(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "X"}, headers=auth_headers)).json()
    cid = case["id"]
    await client.post(
        f"/investigations/{cid}/evidence",
        json={"type": "phone", "source_url": "https://example.com/p"},
        headers=auth_headers,
    )
    j = await client.get(f"/investigations/{cid}/export?format=json", headers=auth_headers)
    assert j.status_code == 200
    assert j.json()["investigation"]["code"] == case["code"]
    assert len(j.json()["evidence"]) == 1

    c = await client.get(f"/investigations/{cid}/export?format=csv", headers=auth_headers)
    assert c.status_code == 200
    assert "source_url" in c.text
    assert "example.com/p" in c.text
