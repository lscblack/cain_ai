import io
import pathlib

import pytest
import pytest_asyncio

from app.intelligence.face.service import get_face_engine

FIXTURES = pathlib.Path(__file__).parent / "fixtures"
FACE1 = FIXTURES / "face1.jpg"
FACE2 = FIXTURES / "face2.jpg"

engine_available = get_face_engine().available()
requires_engine = pytest.mark.skipif(not engine_available, reason="face engine/model unavailable")


def _two_face_jpeg() -> bytes:
    """Compose face1 and face2 side by side into a single image with two faces."""
    from PIL import Image

    a = Image.open(FACE1).convert("RGB")
    b = Image.open(FACE2).convert("RGB")
    h = max(a.height, b.height)
    a = a.resize((int(a.width * h / a.height), h))
    b = b.resize((int(b.width * h / b.height), h))
    canvas = Image.new("RGB", (a.width + b.width, h), (255, 255, 255))
    canvas.paste(a, (0, 0))
    canvas.paste(b, (a.width, 0))
    buf = io.BytesIO()
    canvas.save(buf, format="JPEG")
    return buf.getvalue()


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


def test_detected_face_to_dict_extra():
    """to_dict surfaces age/sex only when include_extra is requested."""
    from app.intelligence.face.engine import DetectedFace

    f = DetectedFace(
        bbox=[1, 2, 3, 4], det_score=0.9, embedding=[0.0] * 512, quality=0.8,
        extra={"age": 42, "sex": "M", "ignored": "x"},
    )
    base = f.to_dict()
    assert "age" not in base and "sex" not in base
    full = f.to_dict(include_extra=True)
    assert full["age"] == 42
    assert full["sex"] == "M"
    assert "ignored" not in full  # only known demographic fields are exposed


@requires_engine
async def test_detect_returns_age_sex(client, auth_headers):
    with open(FACE1, "rb") as f:
        r = await client.post(
            "/intelligence/face/detect",
            files={"file": ("face1.jpg", f, "image/jpeg")},
            headers=auth_headers,
        )
    assert r.status_code == 200
    face = r.json()["faces"][0]
    assert "age" in face
    assert "sex" in face


@requires_engine
async def test_detect_multiple_faces(client, auth_headers):
    r = await client.post(
        "/intelligence/face/detect",
        files={"file": ("two.jpg", _two_face_jpeg(), "image/jpeg")},
        headers=auth_headers,
    )
    assert r.status_code == 200
    assert r.json()["faces_detected"] >= 2


@requires_engine
async def test_search_face_index_selects_face(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "FI"}, headers=auth_headers)).json()
    # index only face1 (Lincoln)
    with open(FACE1, "rb") as f:
        await client.post(
            "/intelligence/face/detect",
            files={"file": ("face1.jpg", f, "image/jpeg")},
            data={"investigation_id": case["id"]},
            headers=auth_headers,
        )
    two = _two_face_jpeg()

    def best_sim(body):
        m = body.get("matches") or []
        return m[0]["similarity"] if m else 0.0

    r0 = await client.post(
        "/intelligence/face/search",
        files={"file": ("q.jpg", two, "image/jpeg")},
        data={"face_index": 0},
        headers=auth_headers,
    )
    r1 = await client.post(
        "/intelligence/face/search",
        files={"file": ("q.jpg", two, "image/jpeg")},
        data={"face_index": 1},
        headers=auth_headers,
    )
    assert r0.status_code == 200 and r1.status_code == 200
    # the two indices address different faces, exactly one of which is Lincoln
    assert r0.json()["query_face"]["bbox"] != r1.json()["query_face"]["bbox"]
    sims = [best_sim(r0.json()), best_sim(r1.json())]
    assert max(sims) > 0.9  # Lincoln side strongly matches the indexed face
    assert min(sims) < 0.5  # the other side does not


@requires_engine
async def test_search_face_index_out_of_range(client, auth_headers):
    with open(FACE1, "rb") as f:
        r = await client.post(
            "/intelligence/face/search",
            files={"file": ("q.jpg", f, "image/jpeg")},
            data={"face_index": 9},
            headers=auth_headers,
        )
    assert r.status_code == 200
    assert r.json()["detail"] == "face_index_out_of_range"
    assert r.json()["matches"] == []


@requires_engine
async def test_frame_returns_details_and_is_ephemeral(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "Live"}, headers=auth_headers)).json()
    with open(FACE1, "rb") as f:
        await client.post(
            "/intelligence/face/detect",
            files={"file": ("face1.jpg", f, "image/jpeg")},
            data={"investigation_id": case["id"]},
            headers=auth_headers,
        )
    before = (await client.get("/intelligence/face/index-list", headers=auth_headers)).json()["total"]

    with open(FACE1, "rb") as f:
        r = await client.post(
            "/intelligence/face/frame",
            files={"file": ("frame.jpg", f, "image/jpeg")},
            data={"match": "true"},
            headers=auth_headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["faces_detected"] >= 1
    face = body["faces"][0]
    for key in ("bbox", "age", "sex", "quality", "det_score"):
        assert key in face
    # match ran against the gallery and found the indexed Lincoln face
    assert face["match"] is not None
    assert face["match"]["similarity"] > 0.9

    # frame processing persists nothing
    after = (await client.get("/intelligence/face/index-list", headers=auth_headers)).json()["total"]
    assert after == before


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
async def test_search_match_has_report_fields(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "Rpt"}, headers=auth_headers)).json()
    with open(FACE1, "rb") as f:
        await client.post(
            "/intelligence/face/detect",
            files={"file": ("face1.jpg", f, "image/jpeg")},
            data={"investigation_id": case["id"]},
            headers=auth_headers,
        )
    with open(FACE1, "rb") as f:
        r = await client.post(
            "/intelligence/face/search",
            files={"file": ("q.jpg", f, "image/jpeg")},
            headers=auth_headers,
        )
    m = r.json()["matches"][0]
    # Report-card fields the UI renders, present even when empty.
    for key in ("names", "emails", "phones", "usernames", "titles", "orgs", "locations",
                "age", "sex", "source_url", "description", "crop_url"):
        assert key in m


@requires_engine
async def test_connections_links_co_located_people(client, auth_headers):
    """Two DIFFERENT people indexed from the same source page are connected."""
    case = (await client.post("/investigations", json={"name": "Conn"}, headers=auth_headers)).json()
    page = "https://example.com/group-photo"
    ids = []
    for fx in (FACE1, FACE2):  # Lincoln + Einstein = two different people
        with open(fx, "rb") as f:
            r = await client.post(
                "/intelligence/face/detect",
                files={"file": (fx.name, f, "image/jpeg")},
                data={"investigation_id": case["id"], "source_url": page},
                headers=auth_headers,
            )
        ids.extend(r.json()["stored_face_ids"])
    assert len(ids) >= 2

    r = await client.get(f"/intelligence/face/{ids[0]}/connections", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    # the other person on the same page is surfaced as a connection, not self
    conn_ids = [c["face_id"] for c in body["connections"]]
    assert ids[0] not in conn_ids
    assert any(fid != ids[0] for fid in conn_ids)
    assert body["count"] >= 1
    top = body["connections"][0]
    assert "co_located" in top["reasons"]
    assert top["source_url"] == page


async def test_connections_404_for_unknown_face(client, auth_headers):
    import uuid as _uuid
    r = await client.get(
        f"/intelligence/face/{_uuid.uuid4()}/connections", headers=auth_headers
    )
    assert r.status_code == 404


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
async def test_discover_unavailable_without_providers(client, auth_headers, monkeypatch):
    # Force the no-provider branch regardless of any configured env keys.
    from app.providers import registry as _reg
    monkeypatch.setattr(_reg.registry, "by_type", lambda t: [])
    with open(FACE1, "rb") as f:
        r = await client.post(
            "/intelligence/face/discover",
            files={"file": ("q.jpg", f, "image/jpeg")},
            headers=auth_headers,
        )
    assert r.status_code == 200
    assert r.json()["available"] is False
    assert r.json()["detail"] == "no_reverse_image_providers_configured"


async def test_index_list_empty(client, auth_headers):
    r = await client.get("/intelligence/face/index-list", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["total"] == 0
    assert r.json()["faces"] == []


async def test_dedupe_empty(client, auth_headers):
    r = await client.post("/intelligence/face/dedupe", headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["removed"] == 0


def _tiny_video(path, *, frames: int = 4, fps: int = 1) -> None:
    """Write a tiny video of the face1 fixture repeated a few times."""
    import cv2

    img = cv2.imread(str(FACE1))
    assert img is not None
    h, w = img.shape[:2]
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
    try:
        for _ in range(frames):
            writer.write(img)
    finally:
        writer.release()


@requires_engine
async def test_search_video(client, auth_headers, tmp_path):
    # index face1 so the sampled frames have something to match against
    case = (await client.post("/investigations", json={"name": "Vid"}, headers=auth_headers)).json()
    with open(FACE1, "rb") as f:
        await client.post(
            "/intelligence/face/detect",
            files={"file": ("face1.jpg", f, "image/jpeg")},
            data={"investigation_id": case["id"]},
            headers=auth_headers,
        )

    vid = tmp_path / "clip.mp4"
    _tiny_video(vid)
    with open(vid, "rb") as vf:
        r = await client.post(
            "/intelligence/face/search/video",
            files={"file": ("clip.mp4", vf, "video/mp4")},
            headers=auth_headers,
        )
    assert r.status_code == 200
    body = r.json()
    assert body["frames_sampled"] > 0
    assert "faces_found" in body
    assert isinstance(body["people"], list)
    # the clip is the same face repeated -> dedup to one person
    assert body["faces_found"] == 1
    person = body["people"][0]
    for key in ("age", "sex", "quality", "frames_seen", "matches"):
        assert key in person
    # the repeated Lincoln face strongly matches the indexed Lincoln face
    assert person["matches"][0]["similarity"] > 0.9


async def test_search_video_rejects_non_video(client, auth_headers):
    with open(FACE1, "rb") as f:
        r = await client.post(
            "/intelligence/face/search/video",
            files={"file": ("face1.jpg", f, "image/jpeg")},
            headers=auth_headers,
        )
    # 415 when engine is up; 503 when it is down — both reject the bad upload
    assert r.status_code in (415, 503)


@requires_engine
async def test_public_compare(client):
    with open(FACE1, "rb") as a, open(FACE1, "rb") as b:
        same = await client.post("/intelligence/face/public/compare",
            files={"file_a": ("a.jpg", a, "image/jpeg"), "file_b": ("b.jpg", b, "image/jpeg")})
    assert same.status_code == 200 and same.json()["comparable"] is True
    assert same.json()["similarity"] > 0.9
    with open(FACE1, "rb") as a, open(FACE2, "rb") as b:
        diff = await client.post("/intelligence/face/public/compare",
            files={"file_a": ("a.jpg", a, "image/jpeg"), "file_b": ("b.jpg", b, "image/jpeg")})
    assert diff.json()["similarity"] < same.json()["similarity"]
