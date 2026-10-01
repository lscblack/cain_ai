import pytest_asyncio

from app.providers.registry import registry


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_phone_requires_auth(client):
    assert (await client.post("/intelligence/phone", json={"number": "+250788123456"})).status_code == 401


async def test_phone_analysis(client, auth_headers):
    r = await client.post(
        "/intelligence/phone", json={"number": "+250788123456"}, headers=auth_headers
    )
    assert r.status_code == 200
    a = r.json()["analysis"]
    assert a["valid"] is True
    assert a["country_code"] == 250
    assert a["region"] == "RW"
    assert "0788123456" in a["variants"]


async def test_phone_finds_local_entity_by_variant(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "C"}, headers=auth_headers)).json()
    # stored in national form; query in E.164 should still match via variants
    await client.post(
        f"/investigations/{case['id']}/entities",
        json={"type": "phone", "value": "0788123456"},
        headers=auth_headers,
    )
    r = await client.post(
        "/intelligence/phone", json={"number": "+250788123456"}, headers=auth_headers
    )
    body = r.json()
    assert len(body["local_entity_matches"]) == 1


async def test_phone_invalid_number(client, auth_headers):
    r = await client.post("/intelligence/phone", json={"number": "nonsense"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["analysis"]["parsed"] is False


async def test_phone_provider_registered_and_healthy():
    provider = registry.get("local_phone")
    assert provider is not None
    health = await provider.health_check()
    assert health.healthy is True
