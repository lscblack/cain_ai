import pytest_asyncio


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _new_case(client, headers, name="Subject 001"):
    r = await client.post("/investigations", json={"name": name}, headers=headers)
    assert r.status_code == 201
    return r.json()


async def test_requires_auth(client):
    assert (await client.get("/investigations")).status_code == 401
    assert (await client.post("/investigations", json={"name": "x"})).status_code == 401


async def test_create_assigns_case_code(client, auth_headers):
    case = await _new_case(client, auth_headers)
    assert case["code"].startswith("CASE-")
    assert case["name"] == "Subject 001"
    assert case["status"] == "open"

    case2 = await _new_case(client, auth_headers, name="Subject 002")
    # sequential codes
    assert case2["code"] != case["code"]


async def test_get_and_list_with_counts(client, auth_headers):
    case = await _new_case(client, auth_headers)
    detail = (await client.get(f"/investigations/{case['id']}", headers=auth_headers)).json()
    assert detail["entity_count"] == 0
    assert detail["evidence_count"] == 0
    listing = (await client.get("/investigations", headers=auth_headers)).json()
    assert any(i["id"] == case["id"] for i in listing)


async def test_missing_investigation_404(client, auth_headers):
    import uuid

    r = await client.get(f"/investigations/{uuid.uuid4()}", headers=auth_headers)
    assert r.status_code == 404


async def test_patch_investigation(client, auth_headers):
    case = await _new_case(client, auth_headers)
    r = await client.patch(
        f"/investigations/{case['id']}",
        json={"status": "archived", "name": "Renamed"},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "archived"
    assert r.json()["name"] == "Renamed"


async def test_add_entity_and_list(client, auth_headers):
    case = await _new_case(client, auth_headers)
    r = await client.post(
        f"/investigations/{case['id']}/entities",
        json={"type": "phone", "value": "+250788123456", "label": "contact"},
        headers=auth_headers,
    )
    assert r.status_code == 201
    assert r.json()["type"] == "phone"
    ents = (await client.get(f"/investigations/{case['id']}/entities", headers=auth_headers)).json()
    assert len(ents) == 1


async def test_add_evidence_requires_provenance_url(client, auth_headers):
    case = await _new_case(client, auth_headers)
    # non-http scheme rejected
    bad = await client.post(
        f"/investigations/{case['id']}/evidence",
        json={"type": "url", "source_url": "ftp://example.com/x"},
        headers=auth_headers,
    )
    assert bad.status_code == 422

    good = await client.post(
        f"/investigations/{case['id']}/evidence",
        json={
            "type": "phone",
            "source_url": "https://example.com/contact",
            "confidence": 0.8,
            "band": "potential_match",
        },
        headers=auth_headers,
    )
    assert good.status_code == 201
    assert good.json()["collected_at"] is not None


async def test_relationship_requires_entities_in_case(client, auth_headers):
    case = await _new_case(client, auth_headers)
    other = await _new_case(client, auth_headers, name="Other")

    e1 = (
        await client.post(
            f"/investigations/{case['id']}/entities",
            json={"type": "phone", "value": "+250788111111"},
            headers=auth_headers,
        )
    ).json()
    e2 = (
        await client.post(
            f"/investigations/{case['id']}/entities",
            json={"type": "email", "value": "a@b.com"},
            headers=auth_headers,
        )
    ).json()
    e_other = (
        await client.post(
            f"/investigations/{other['id']}/entities",
            json={"type": "email", "value": "c@d.com"},
            headers=auth_headers,
        )
    ).json()

    # entity from another case rejected
    bad = await client.post(
        f"/investigations/{case['id']}/relationships",
        json={
            "source_entity_id": e1["id"],
            "target_entity_id": e_other["id"],
            "rel_type": "appears_with",
            "source_url": "https://example.com/page",
        },
        headers=auth_headers,
    )
    assert bad.status_code == 400

    good = await client.post(
        f"/investigations/{case['id']}/relationships",
        json={
            "source_entity_id": e1["id"],
            "target_entity_id": e2["id"],
            "rel_type": "appears_with",
            "source_url": "https://example.com/page",
        },
        headers=auth_headers,
    )
    assert good.status_code == 201


async def test_graph_isolated_per_case_and_delete_cascades(client, auth_headers):
    case = await _new_case(client, auth_headers)
    e1 = (
        await client.post(
            f"/investigations/{case['id']}/entities",
            json={"type": "phone", "value": "+250788222222"},
            headers=auth_headers,
        )
    ).json()
    e2 = (
        await client.post(
            f"/investigations/{case['id']}/entities",
            json={"type": "email", "value": "x@y.com"},
            headers=auth_headers,
        )
    ).json()
    await client.post(
        f"/investigations/{case['id']}/relationships",
        json={
            "source_entity_id": e1["id"],
            "target_entity_id": e2["id"],
            "rel_type": "appears_with",
            "source_url": "https://example.com/page",
        },
        headers=auth_headers,
    )

    graph = (await client.get(f"/investigations/{case['id']}/graph", headers=auth_headers)).json()
    assert len(graph["nodes"]) == 2
    assert len(graph["edges"]) == 1

    # delete cascades
    d = await client.delete(f"/investigations/{case['id']}", headers=auth_headers)
    assert d.status_code == 204
    assert (await client.get(f"/investigations/{case['id']}", headers=auth_headers)).status_code == 404
