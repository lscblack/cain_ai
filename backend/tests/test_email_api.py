import pytest_asyncio


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_email_requires_auth(client):
    r = await client.post("/intelligence/email", json={"email": "a@b.com", "check_dns": False})
    assert r.status_code == 401


async def test_email_analysis_without_dns(client, auth_headers):
    r = await client.post(
        "/intelligence/email",
        json={"email": "John.Doe99@example.com", "check_dns": False},
        headers=auth_headers,
    )
    assert r.status_code == 200
    a = r.json()["analysis"]
    assert a["valid_format"] is True
    assert a["local"] == "john.doe99"
    assert a["dns_checked"] is False
    assert "john" in a["derived_usernames"]
    assert a["gravatar_url"].startswith("https://www.gravatar.com/avatar/")


async def test_email_invalid_format(client, auth_headers):
    r = await client.post(
        "/intelligence/email", json={"email": "bogus", "check_dns": False}, headers=auth_headers
    )
    # schema allows the string; analysis reports invalid format
    assert r.status_code == 200
    assert r.json()["analysis"]["valid_format"] is False


async def test_email_finds_local_entity(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "C"}, headers=auth_headers)).json()
    await client.post(
        f"/investigations/{case['id']}/entities",
        json={"type": "email", "value": "target@example.com"},
        headers=auth_headers,
    )
    r = await client.post(
        "/intelligence/email",
        json={"email": "target@example.com", "check_dns": False},
        headers=auth_headers,
    )
    assert len(r.json()["local_entity_matches"]) == 1
