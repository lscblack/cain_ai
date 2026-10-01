import pytest_asyncio


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_powerup_requires_auth(client):
    assert (await client.get("/powerup/providers")).status_code == 401


async def test_powerup_lists_providers(client, auth_headers):
    r = await client.get("/powerup/providers", headers=auth_headers)
    assert r.status_code == 200
    providers = r.json()["providers"]
    names = {p["name"] for p in providers}
    assert {"local_phone", "local_email", "public_username", "serpapi_reverse_image"} <= names
    # local providers are healthy; serpapi unconfigured
    by = {p["name"]: p for p in providers}
    assert by["local_phone"]["healthy"] is True
    assert by["serpapi_reverse_image"]["configured"] is False
    # no secrets leaked
    for p in providers:
        assert "api_key" not in p and "key" not in {k.lower() for k in p}
