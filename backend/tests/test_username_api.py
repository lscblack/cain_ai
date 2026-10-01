import pytest_asyncio

from app.api.usernames import get_username_fetcher


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


@pytest_asyncio.fixture
async def fake_fetch(client):
    """Override the username HTTP fetcher with a deterministic fake."""

    async def fetch(url: str):
        if "github.com" in url:
            return 200
        if "gitlab.com" in url:
            return 404
        return None

    client.app.dependency_overrides[get_username_fetcher] = lambda: fetch
    return fetch


async def test_username_requires_auth(client):
    r = await client.post("/intelligence/username", json={"username": "someone"})
    assert r.status_code == 401


async def test_username_rejects_invalid(client, auth_headers, fake_fetch):
    r = await client.post("/intelligence/username", json={"username": "a"}, headers=auth_headers)
    assert r.status_code == 422


async def test_username_presence(client, auth_headers, fake_fetch):
    r = await client.post(
        "/intelligence/username",
        json={"username": "osintuser", "platforms": ["github", "gitlab"]},
        headers=auth_headers,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["found_count"] == 1
    by = {h["platform"]: h for h in body["results"]}
    assert by["github"]["status"] == "found"
    assert by["gitlab"]["status"] == "not_found"


async def test_username_finds_local_entity(client, auth_headers, fake_fetch):
    case = (await client.post("/investigations", json={"name": "C"}, headers=auth_headers)).json()
    await client.post(
        f"/investigations/{case['id']}/entities",
        json={"type": "username", "value": "osintuser"},
        headers=auth_headers,
    )
    r = await client.post(
        "/intelligence/username",
        json={"username": "osintuser", "platforms": ["github"]},
        headers=auth_headers,
    )
    assert len(r.json()["local_entity_matches"]) == 1
