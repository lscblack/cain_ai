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


async def test_evidence_bogus_geometry_422_no_write(client, auth_headers, inv_id):
    bad = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Bogus", "coordinates": []}, "properties": {}}]}
    r = await client.post("/geoint/evidence", json=_body(inv_id, annotations=bad), headers=auth_headers)
    assert r.status_code == 422
    assert await _features(client, auth_headers, inv_id) == []


async def test_evidence_null_geometry_allowed(client, auth_headers, inv_id):
    fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": None, "properties": {}}]}
    r = await client.post("/geoint/evidence", json=_body(inv_id, annotations=fc), headers=auth_headers)
    assert r.status_code == 201, r.text


async def test_evidence_bogus_entity_400_no_write(client, auth_headers, inv_id):
    r = await client.post("/geoint/evidence", json=_body(inv_id, entity_id=str(uuid.uuid4())),
                          headers=auth_headers)
    assert r.status_code == 400, r.text
    assert await _features(client, auth_headers, inv_id) == []


def _fc(geometry):
    return {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": geometry, "properties": {}}]}


_RING = [[30.0, -1.9], [30.1, -1.9], [30.1, -1.8], [30.0, -1.9]]

BAD_GEOMETRIES = [
    {"type": "Point", "coordinates": []},
    {"type": "Point", "coordinates": [30.0]},
    {"type": "Point", "coordinates": ["a", "b"]},
    {"type": "Point", "coordinates": [None, 1]},
    {"type": "Point", "coordinates": [float("nan"), 1.0]},
    {"type": "Point", "coordinates": [30.0, 123.0]},          # lat out of range
    {"type": "Point", "coordinates": [True, False]},          # bools are not coordinates
    {"type": "LineString", "coordinates": [[30.0, -1.9]]},    # needs >= 2 positions
    {"type": "LineString", "coordinates": [[30.0, -1.9], "x"]},
    {"type": "Polygon", "coordinates": [[[30.0, -1.9], [30.1, -1.9], [30.0, -1.9]]]},  # < 4 positions
    {"type": "Polygon", "coordinates": [[[30.0, -1.9], [30.1, -1.9], [30.1, -1.8], [30.5, -1.5]]]},  # not closed
    {"type": "Polygon", "coordinates": []},
    {"type": "GeometryCollection", "geometries": [{"type": "Point", "coordinates": []}]},
]

GOOD_GEOMETRIES = [
    {"type": "Point", "coordinates": [30.0, -1.9]},
    {"type": "Point", "coordinates": [190.0, 10.0]},          # Leaflet does not wrap lng past the antimeridian
    {"type": "Point", "coordinates": [30.0, -1.9, 1500.0]},   # optional altitude
    {"type": "LineString", "coordinates": [[30.0, -1.9], [30.1, -1.8]]},
    {"type": "Polygon", "coordinates": [_RING]},
    {"type": "MultiPoint", "coordinates": [[30.0, -1.9], [31.0, -2.0]]},
    {"type": "GeometryCollection", "geometries": [{"type": "Point", "coordinates": [30.0, -1.9]}]},
]


@pytest.mark.parametrize("geometry", BAD_GEOMETRIES)
async def test_evidence_malformed_coordinates_422_no_write(client, auth_headers, inv_id, geometry):
    r = await client.post("/geoint/evidence", json=_body(inv_id, annotations=_fc(geometry)), headers=auth_headers)
    assert r.status_code == 422, r.text
    assert await _features(client, auth_headers, inv_id) == []


@pytest.mark.parametrize("geometry", GOOD_GEOMETRIES)
async def test_evidence_valid_coordinates_201(client, auth_headers, inv_id, geometry):
    r = await client.post("/geoint/evidence", json=_body(inv_id, annotations=_fc(geometry)), headers=auth_headers)
    assert r.status_code == 201, r.text
