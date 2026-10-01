import pytest_asyncio


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_correlations_suggests_co_occurrence(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "C"}, headers=auth_headers)).json()
    cid = case["id"]
    e1 = (await client.post(f"/investigations/{cid}/entities", json={"type": "phone", "value": "+250788123456"}, headers=auth_headers)).json()
    e2 = (await client.post(f"/investigations/{cid}/entities", json={"type": "email", "value": "a@b.com"}, headers=auth_headers)).json()
    url = "https://example.com/contact"
    await client.post(f"/investigations/{cid}/evidence", json={"type": "phone", "source_url": url, "entity_id": e1["id"]}, headers=auth_headers)
    await client.post(f"/investigations/{cid}/evidence", json={"type": "email", "source_url": url, "entity_id": e2["id"]}, headers=auth_headers)

    r = await client.get(f"/investigations/{cid}/correlations", headers=auth_headers)
    assert r.status_code == 200
    suggestions = r.json()["suggestions"]
    assert len(suggestions) == 1
    assert suggestions[0]["rel_type"] == "co_observed_on"
    assert suggestions[0]["source_url"] == url


async def test_correlations_excludes_existing_relationship(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "C"}, headers=auth_headers)).json()
    cid = case["id"]
    e1 = (await client.post(f"/investigations/{cid}/entities", json={"type": "phone", "value": "+250788123456"}, headers=auth_headers)).json()
    e2 = (await client.post(f"/investigations/{cid}/entities", json={"type": "email", "value": "a@b.com"}, headers=auth_headers)).json()
    url = "https://example.com/contact"
    await client.post(f"/investigations/{cid}/evidence", json={"type": "phone", "source_url": url, "entity_id": e1["id"]}, headers=auth_headers)
    await client.post(f"/investigations/{cid}/evidence", json={"type": "email", "source_url": url, "entity_id": e2["id"]}, headers=auth_headers)
    await client.post(f"/investigations/{cid}/relationships", json={"source_entity_id": e1["id"], "target_entity_id": e2["id"], "rel_type": "co_observed_on", "source_url": url}, headers=auth_headers)

    r = await client.get(f"/investigations/{cid}/correlations", headers=auth_headers)
    assert r.json()["suggestions"] == []
