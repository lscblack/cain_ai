import pathlib

import pytest
import pytest_asyncio

from app.intelligence.face.service import get_face_engine

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
FACE1 = FIXTURES / "face1.jpg"
FACE2 = FIXTURES / "face2.jpg"

engine_available = get_face_engine().available()
requires_engine = pytest.mark.skipif(not engine_available, reason="face engine/model unavailable")


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_face_status_requires_auth(client):
    assert (await client.get("/intelligence/face/status")).status_code == 401


async def test_face_status(client, auth_headers):
    r = await client.get("/intelligence/face/status", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "buffalo_l"
    assert "available" in body


@requires_engine
async def test_detect_real_face(client, auth_headers):
    with open(FACE1, "rb") as f:
        r = await client.post(
            "/intelligence/face/detect",
            files={"file": ("face1.jpg", f, "image/jpeg")},
            headers=auth_headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["faces_detected"] >= 1
    assert body["faces"][0]["embedding_dim"] == 512


@requires_engine
async def test_compare_same_and_different(client, auth_headers):
    with open(FACE1, "rb") as a, open(FACE1, "rb") as b:
        same = await client.post(
            "/intelligence/face/compare",
            files={"file_a": ("a.jpg", a, "image/jpeg"), "file_b": ("b.jpg", b, "image/jpeg")},
            headers=auth_headers,
        )
    assert same.status_code == 200
    assert same.json()["comparable"] is True
    assert same.json()["similarity"] > 0.9  # identical image

    with open(FACE1, "rb") as a, open(FACE2, "rb") as b:
        diff = await client.post(
            "/intelligence/face/compare",
            files={"file_a": ("a.jpg", a, "image/jpeg"), "file_b": ("b.jpg", b, "image/jpeg")},
            headers=auth_headers,
        )
    assert diff.json()["similarity"] < same.json()["similarity"]


@requires_engine
async def test_search_1_to_n(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "Faces"}, headers=auth_headers)).json()
    # index face1 under the investigation
    with open(FACE1, "rb") as f:
        await client.post(
            "/intelligence/face/detect",
            files={"file": ("face1.jpg", f, "image/jpeg")},
            data={"investigation_id": case["id"], "source_url": "https://example.com/p"},
            headers=auth_headers,
        )
    # search with the same face -> should find it as a strong match
    with open(FACE1, "rb") as f:
        r = await client.post(
            "/intelligence/face/search",
            files={"file": ("q.jpg", f, "image/jpeg")},
            headers=auth_headers,
        )
    body = r.json()
    assert body["query_face"] is not None
    assert len(body["matches"]) >= 1
    assert body["matches"][0]["similarity"] > 0.9
    assert body["matches"][0]["band"] in ("potential_match", "strong_similarity")

    # search with a different face -> no strong match to face1
    with open(FACE2, "rb") as f:
        r2 = await client.post(
            "/intelligence/face/search",
            files={"file": ("q.jpg", f, "image/jpeg")},
            headers=auth_headers,
        )
    top = r2.json()["matches"]
    assert all(m["similarity"] < 0.5 for m in top)


@requires_engine
async def test_search_stream_sse(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "S"}, headers=auth_headers)).json()
    with open(FACE1, "rb") as f:
        await client.post(
            "/intelligence/face/detect",
            files={"file": ("f.jpg", f, "image/jpeg")},
            data={"investigation_id": case["id"]},
            headers=auth_headers,
        )
    with open(FACE1, "rb") as f:
        resp = await client.post(
            "/intelligence/face/search/stream",
            files={"file": ("q.jpg", f, "image/jpeg")},
            headers=auth_headers,
        )
    assert resp.status_code == 200
    body = resp.text
    assert "event: stage" in body
    assert "image_received" in body
    assert "faces_detected" in body
    assert "event: result" in body


@requires_engine
async def test_discover_unavailable_without_providers(client, auth_headers):
    with open(FACE1, "rb") as f:
        r = await client.post(
            "/intelligence/face/discover",
            files={"file": ("q.jpg", f, "image/jpeg")},
            headers=auth_headers,
        )
    assert r.status_code == 200
    assert r.json()["available"] is False
    assert r.json()["detail"] == "no_reverse_image_providers_configured"
