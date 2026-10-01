async def test_health_liveness(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_readiness_ok(client):
    r = await client.get("/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert body["db"] == "up"
    assert body["redis"] == "up"


async def test_readiness_reports_redis_down(client, fake_redis):
    async def boom():
        raise ConnectionError("redis down")

    fake_redis.ping = boom  # type: ignore[assignment]

    r = await client.get("/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    assert body["redis"] == "down"
    assert body["db"] == "up"


async def test_root_metadata(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert r.json()["name"] == "KAI"
