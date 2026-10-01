from sqlalchemy import select

from app.database.models.audit import AuditLog


async def _register(client, email="op@example.com", password="supersecret1"):
    return await client.post("/auth/register", json={"email": email, "password": password})


async def test_registration_status_open_then_closed(client):
    r = await client.get("/auth/registration-status")
    assert r.json()["registration_open"] is True
    await _register(client)
    r = await client.get("/auth/registration-status")
    assert r.json()["registration_open"] is False


async def test_register_first_then_second_denied(client):
    r = await _register(client)
    assert r.status_code == 201
    assert "access_token" in r.json()

    r2 = await _register(client, email="other@example.com")
    assert r2.status_code == 403
    assert r2.json()["detail"] == "registration_closed"


async def test_login_success_and_wrong_password(client):
    await _register(client)
    good = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    assert good.status_code == 200
    token = good.json()["access_token"]
    assert token

    bad = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "wrong"}
    )
    assert bad.status_code == 401
    assert bad.json()["detail"] == "invalid_credentials"


async def test_me_requires_valid_token(client):
    await _register(client)
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    token = login.json()["access_token"]

    assert (await client.get("/auth/me")).status_code == 401
    assert (
        await client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    ).status_code == 401

    ok = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert ok.status_code == 200
    assert ok.json()["email"] == "op@example.com"


async def test_audit_rows_written(client, db_session):
    await _register(client)
    await client.post("/auth/login", json={"email": "op@example.com", "password": "supersecret1"})
    await client.post("/auth/login", json={"email": "op@example.com", "password": "nope"})

    rows = (await db_session.execute(select(AuditLog))).scalars().all()
    actions = {r.action for r in rows}
    assert "operator.register" in actions
    assert "operator.login" in actions
    assert "operator.login_failed" in actions


async def test_local_identifier_accepted(client):
    r = await client.post(
        "/auth/register", json={"email": "operator@local", "password": "supersecret1"}
    )
    assert r.status_code == 201
    login = await client.post(
        "/auth/login", json={"email": "operator@local", "password": "supersecret1"}
    )
    token = login.json()["access_token"]
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "operator@local"


async def test_invalid_identifier_rejected(client):
    r = await client.post(
        "/auth/register", json={"email": "has space", "password": "supersecret1"}
    )
    assert r.status_code == 422
