from app.providers import geo


async def test_aircraft_parse_states():
    states = [
        ["abc123", "RWD101 ", "Rwanda", None, None, 30.06, -1.95, 1000, False, 220.0],
        ["bad", None, None, None, None, None, None],  # no coords -> skipped
    ]
    pts = await geo.fetch_aircraft(_states=states)
    assert len(pts) == 1
    assert pts[0]["kind"] == "aircraft"
    assert pts[0]["lat"] == -1.95 and pts[0]["lon"] == 30.06
    assert pts[0]["label"] == "RWD101"


async def test_webcams_parse(monkeypatch):
    import app.providers.geo as g
    monkeypatch.setattr(g, "get_settings", lambda: type("S", (), {"windy_webcams_api_key": "k", "windy_webcams_countries": "RW"})())

    async def fake_get(url, params, headers):
        assert headers["x-windy-api-key"] == "k"
        return {"webcams": [{"title": "Kigali Cam", "location": {"latitude": -1.95, "longitude": 30.06, "city": "Kigali", "country": "RW"}, "urls": {"detail": "https://x"}}]}

    pts = await g.fetch_webcams(["RW"], _json_get=fake_get)
    assert len(pts) == 1 and pts[0]["kind"] == "cctv" and pts[0]["label"] == "Kigali Cam"


async def test_fires_parse_csv(monkeypatch):
    import app.providers.geo as g
    monkeypatch.setattr(g, "get_settings", lambda: type("S", (), {"firms_map_key": "k"})())
    csv_text = "latitude,longitude,bright_ti4,acq_date,acq_time,confidence,frp\n-1.9,30.0,320,2026-10-01,1200,n,5.1\n"
    pts = await g.fetch_fires(_csv_text=csv_text)
    assert len(pts) == 1 and pts[0]["kind"] == "satellite_fire"
    assert pts[0]["lat"] == -1.9


async def test_vessels_parse_messages(monkeypatch):
    import app.providers.geo as g
    monkeypatch.setattr(g, "get_settings", lambda: type("S", (), {"aisstream_api_key": "k"})())
    msgs = [
        {"MetaData": {"MMSI": 123, "ShipName": "KAI TEST ", "latitude": -1.9, "longitude": 30.0}},
        {"MetaData": {"MMSI": 123, "ShipName": "KAI TEST", "latitude": -1.91, "longitude": 30.01}},  # dedup same mmsi
        {"MetaData": {"latitude": None, "longitude": None}},  # skipped
    ]
    pts = await g.fetch_vessels((-3, 29, 0, 31), _messages=msgs)
    assert len(pts) == 1
    assert pts[0]["kind"] == "vessel" and pts[0]["label"] == "KAI TEST"


async def test_unconfigured_returns_empty(monkeypatch):
    import app.providers.geo as g
    monkeypatch.setattr(g, "get_settings", lambda: type("S", (), {
        "opensky_client_id": "", "opensky_client_secret": "",
        "windy_webcams_api_key": "", "windy_webcams_countries": "",
        "firms_map_key": "", "aisstream_api_key": "",
    })())
    assert await g.fetch_aircraft() == []
    assert await g.fetch_webcams() == []
    assert await g.fetch_fires() == []
    assert await g.fetch_vessels((-3, 29, 0, 31)) == []
