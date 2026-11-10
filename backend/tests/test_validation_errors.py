"""App-wide request-validation behaviour.

A literal NaN/Infinity in a JSON body used to 500: FastAPI's default 422 handler echoes the
offending `input`, and encoding a NaN back out fails. A global handler returns a scrubbed 422
instead. These tests pin that on a NON-geoint endpoint, so the fix stays app-wide.
"""
import math


async def test_nan_body_returns_422_not_500(client, auth_headers):
    # `name` must be a string; sending NaN is both wrong-typed and non-serialisable if echoed.
    r = await client.post("/investigations", json={"name": math.nan}, headers=auth_headers)
    assert r.status_code == 422, r.text
    body = r.json()
    assert "detail" in body and isinstance(body["detail"], list)
    # scrubbed shape: loc/msg/type present, raw echoed input dropped
    assert all("input" not in e for e in body["detail"])


async def test_infinity_body_returns_422_not_500(client, auth_headers):
    r = await client.post("/investigations", json={"name": math.inf}, headers=auth_headers)
    assert r.status_code == 422, r.text


async def test_ordinary_validation_still_422(client, auth_headers):
    # a plain missing-field error must still be a clean 422 with the scrubbed shape
    r = await client.post("/investigations", json={}, headers=auth_headers)
    assert r.status_code == 422, r.text
    assert isinstance(r.json()["detail"], list)
