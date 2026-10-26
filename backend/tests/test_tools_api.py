"""Tools API: inventory, execution auth/denial, targets, findings, install flow."""
from __future__ import annotations

import pytest_asyncio


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "sec@example.com", "password": "supersecret1"})
    login = await client.post("/auth/login", json={"email": "sec@example.com", "password": "supersecret1"})
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


async def test_inventory_reflects_real_host(client, auth_headers):
    r = await client.get("/tools/inventory", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    by_name = {t["name"]: t for t in data["tools"]}
    assert by_name["dig"]["installed"] is True
    assert by_name["dig"]["version"]
    assert data["counts"]["installed"] >= 1
    # the builtin OSV tool is always "installed"
    assert by_name["osv"]["installed"] is True


async def test_inventory_requires_auth(client):
    assert (await client.get("/tools/inventory")).status_code == 401


async def test_active_scan_denied_when_auto_authorize_off(client, auth_headers, monkeypatch):
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "tool_auto_authorize_targets", False)

    r = await client.post("/tools/execute", json={
        "operation": "nmap.service_scan", "params": {"target": "scanme.nmap.org", "ports": "80"}
    }, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "denied" and body["reason"] == "target_not_authorized"
    # a denied attempt is still recorded in execution history
    hist = (await client.get("/tools/executions", headers=auth_headers)).json()
    assert any(h["operation"] == "nmap.service_scan" for h in hist)


async def test_auto_authorize_adds_target_from_url(client, auth_headers, monkeypatch):
    # auto-authorize is on by default; a URL target should be normalized to its
    # host, added to the authorized list, and the scan should NOT be denied.
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "tool_auto_authorize_targets", True)

    r = await client.post("/tools/execute", json={
        "operation": "nmap.service_scan", "params": {"target": "https://127.0.0.1/", "ports": "1-3"}
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json().get("reason") != "target_not_authorized"
    # 127.0.0.1 (host extracted from the URL) is now authorized
    targets = (await client.get("/tools/targets", headers=auth_headers)).json()
    assert any(t["target"] == "127.0.0.1" for t in targets)


async def test_invalid_arguments_rejected(client, auth_headers):
    r = await client.post("/tools/execute", json={
        "operation": "dns.records", "params": {"domain": "not a domain; rm -rf /"}
    }, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["status"] == "error"
    assert "invalid" in (r.json().get("error") or "").lower()


async def test_targets_crud_then_authorized(client, auth_headers):
    add = await client.post("/tools/targets", json={"target": "127.0.0.1", "scope": "active", "note": "self"}, headers=auth_headers)
    assert add.status_code == 201
    tid = add.json()["id"]
    lst = (await client.get("/tools/targets", headers=auth_headers)).json()
    assert any(t["id"] == tid for t in lst)
    # now the authorization gate passes (execution may still fail for other reasons,
    # but it must NOT be denied as unauthorized)
    r = await client.post("/tools/execute", json={
        "operation": "nmap.service_scan", "params": {"target": "127.0.0.1", "ports": "1-10"}
    }, headers=auth_headers)
    assert r.json().get("reason") != "target_not_authorized"
    d = await client.delete(f"/tools/targets/{tid}", headers=auth_headers)
    assert d.status_code == 204


async def test_install_plan_for_installed_package(client, auth_headers):
    r = await client.post("/tools/install/plan", json={"capability": "nmap"}, headers=auth_headers)
    assert r.status_code == 200
    plan = r.json()
    assert plan["package"] == "nmap"
    assert plan["already_installed"] is True


async def test_install_request_reject_then_cannot_approve(client, auth_headers):
    req = await client.post("/tools/install/requests", json={"package": "sslscan", "reason": "tls audit"}, headers=auth_headers)
    assert req.status_code == 201
    rid = req.json()["request"]["id"]
    assert req.json()["request"]["status"] == "pending"
    rej = await client.post(f"/tools/install/requests/{rid}/reject", headers=auth_headers)
    assert rej.status_code == 200 and rej.json()["status"] == "rejected"
    # approving a rejected request is refused
    appr = await client.post(f"/tools/install/requests/{rid}/approve", headers=auth_headers)
    assert appr.status_code == 409


async def test_install_approve_reports_honest_outcome(client, auth_headers, monkeypatch):
    """The approve endpoint must report an honest terminal state and never mark
    a tool installed unless the real helper succeeded. We stub the privileged
    step (so no sudo/pkexec is spawned in tests) to simulate a failed install
    and assert nothing is faked."""
    import app.api.tools as tools_api

    async def fake_perform(package, reinstall=False):
        return {"ok": False, "status": "error", "exit_code": 1, "error": "exit 1",
                "log": "simulated helper failure", "sudo_needs_password": True}

    monkeypatch.setattr(tools_api.install_mod, "perform_install", fake_perform)

    req = await client.post("/tools/install/requests", json={"package": "kai-nonexistent-tool", "reason": "tls audit"}, headers=auth_headers)
    rid = req.json()["request"]["id"]
    appr = await client.post(f"/tools/install/requests/{rid}/approve", headers=auth_headers)
    assert appr.status_code == 200
    body = appr.json()
    # helper failed → must be 'failed', never faked as installed
    assert body["request"]["status"] == "failed"
    assert body["outcome"]["sudo_needs_password"] is True
    assert body["verify"]["installed"] is False


async def test_install_now_non_apt_tool_is_refused(client, auth_headers):
    r = await client.post("/tools/install/now", json={"capability": "subfinder"}, headers=auth_headers)
    assert r.status_code == 422 and "not apt" in r.json()["detail"]


async def test_install_now_unknown_package_never_reaches_helper(client, auth_headers, monkeypatch):
    import app.api.tools as tools_api

    async def boom(*a, **k):  # must not be called
        raise AssertionError("privileged helper called for an unavailable package")

    monkeypatch.setattr(tools_api.install_mod, "perform_install", boom)
    r = await client.post("/tools/install/now", json={"package": "kai-nonexistent-tool"}, headers=auth_headers)
    assert r.status_code == 422 and "not available" in r.json()["detail"]


async def test_install_now_reinstall_passes_flag_and_verifies(client, auth_headers, monkeypatch):
    import app.api.tools as tools_api
    seen = {}

    async def plan(pkg):
        return {"ok": True, "package": pkg, "already_installed": True, "available": True}

    async def perform(package, reinstall=False):
        seen["reinstall"] = reinstall
        return {"ok": True, "status": "ok", "exit_code": 0, "error": None, "log": "ok"}

    monkeypatch.setattr(tools_api.install_mod, "plan_install", plan)
    monkeypatch.setattr(tools_api.install_mod, "perform_install", perform)
    # without reinstall an already-installed tool is a no-op (no privileged call)
    r = await client.post("/tools/install/now", json={"capability": "dig"}, headers=auth_headers)
    assert r.json()["outcome"]["status"] == "already_installed" and "reinstall" not in seen
    r = await client.post("/tools/install/now", json={"capability": "dig", "reinstall": True}, headers=auth_headers)
    assert r.status_code == 200 and seen["reinstall"] is True
    assert r.json()["request"]["status"] == "installed"  # dig really is on the host


async def test_install_batch_single_privileged_call_and_skips(client, auth_headers, monkeypatch):
    import app.api.tools as tools_api
    calls = []

    async def plan(pkg):
        return {"ok": True, "package": pkg, "already_installed": False, "available": pkg != "kai-missing"}

    async def many(packages, reinstall=False, timeout=600):
        calls.append(list(packages))
        return {"ok": True, "status": "ok", "exit_code": 0, "error": None, "log": ""}

    monkeypatch.setattr(tools_api.install_mod, "plan_install", plan)
    monkeypatch.setattr(tools_api.install_mod, "perform_install_many", many)
    r = await client.post("/tools/install/batch",
                          json={"capabilities": ["nmap", "subfinder", "nope-tool"]}, headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert len(calls) == 1 and "nmap" in calls[0]            # one polkit prompt
    reasons = {s["tool"]: s["reason"] for s in body["skipped"]}
    assert "subfinder" in reasons and "nope-tool" in reasons  # non-apt / unknown skipped, reported
