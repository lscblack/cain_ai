import uuid

import pytest

FC = {"type": "FeatureCollection", "features": [
    {"type": "Feature", "geometry": {"type": "Point", "coordinates": [30.0, -1.9]}, "properties": {}}]}


def _body(inv_id, **over):
    b = {"investigation_id": str(inv_id), "annotations": FC, "layer_id": "gibs_modis_truecolor",
         "dates": ["2024-01-01"], "bounds": {"n": 0, "s": -2, "e": 31, "w": 29},
         "provider_url": "https://gibs.earthdata.nasa.gov/"}
    b.update(over)
    return b


@pytest.fixture
async def inv_id(client, auth_headers):
    r = await client.post("/investigations", json={"name": "geo"}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _features(client, auth_headers, inv_id):
    m = await client.get(f"/investigations/{inv_id}/map", headers=auth_headers)
    assert m.status_code == 200, m.text
    return m.json()["features"]


async def test_evidence_written_once(client, auth_headers, inv_id):
    r = await client.post("/geoint/evidence", json=_body(inv_id), headers=auth_headers)
    assert r.status_code == 201, r.text
    assert r.json()["type"] == "geoint"
    assert len(await _features(client, auth_headers, inv_id)) == 1


async def test_evidence_bad_investigation_404(client, auth_headers):
    r = await client.post("/geoint/evidence", json=_body(uuid.uuid4()), headers=auth_headers)
    assert r.status_code == 404


async def test_evidence_bad_geojson_422_no_write(client, auth_headers, inv_id):
    r = await client.post("/geoint/evidence",
                          json=_body(inv_id, annotations={"type": "NotAFC"}), headers=auth_headers)
    assert r.status_code == 422
    assert await _features(client, auth_headers, inv_id) == []


async def test_evidence_requires_auth(client, inv_id):
    r = await client.post("/geoint/evidence", json=_body(inv_id))
    assert r.status_code == 401


async def test_evidence_bad_provider_url_422(client, auth_headers, inv_id):
    r = await client.post("/geoint/evidence",
                          json=_body(inv_id, provider_url="http://x/"), headers=auth_headers)
    assert r.status_code == 422
