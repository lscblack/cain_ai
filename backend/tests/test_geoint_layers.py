async def test_layers_requires_auth(client):
    r = await client.get("/geoint/layers")
    assert r.status_code == 401


async def test_layers_catalogue_shape(client, auth_headers):
    r = await client.get("/geoint/layers", headers=auth_headers)
    assert r.status_code == 200
    layers = r.json()["layers"]
    assert len(layers) >= 5
    for l in layers:
        assert l["url_template"] and l["attribution"]
        assert l["kind"] in ("base", "overlay")
    dated = [l for l in layers if l["dated"]]
    assert dated and all("{Time}" in l["url_template"] for l in dated)


async def test_layers_leak_no_secret(client, auth_headers):
    r = await client.get("/geoint/layers", headers=auth_headers)
    body = r.text.lower()
    assert "api_key" not in body and "tomtom" not in body
