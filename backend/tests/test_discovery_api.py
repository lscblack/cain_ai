import json

import pytest_asyncio

from app.discovery.engine import INVESTIGATIONS_KEY, _run_key


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def _seed_run(fake_redis, run_id="abc123", names=("Jane Doe",)):
    state = {"id": run_id, "status": "done", "names": list(names), "approved": 3, "progress": 100}
    await fake_redis.set(_run_key(run_id), json.dumps(state))
    await fake_redis.lpush(INVESTIGATIONS_KEY, run_id)


async def test_delete_discovery_requires_auth(client):
    assert (await client.delete("/discovery/investigations/abc123")).status_code == 401


async def test_delete_discovery_removes_case(client, auth_headers, fake_redis):
    await _seed_run(fake_redis, "run777")
    # it shows up in the listing
    listing = (await client.get("/discovery/investigations", headers=auth_headers)).json()
    assert any(r["id"] == "run777" for r in listing["investigations"])

    # delete it
    resp = await client.delete("/discovery/investigations/run777", headers=auth_headers)
    assert resp.status_code == 204

    # gone from redis (both the run record and the list entry)
    assert await fake_redis.get(_run_key("run777")) is None
    assert "run777" not in [
        (v.decode() if isinstance(v, bytes) else v)
        for v in await fake_redis.lrange(INVESTIGATIONS_KEY, 0, -1)
    ]
    # and gone from the listing
    listing = (await client.get("/discovery/investigations", headers=auth_headers)).json()
    assert not any(r["id"] == "run777" for r in listing["investigations"])


async def test_delete_discovery_unknown_is_noop(client, auth_headers):
    # deleting a non-existent case is harmless (idempotent)
    resp = await client.delete("/discovery/investigations/nope", headers=auth_headers)
    assert resp.status_code == 204
