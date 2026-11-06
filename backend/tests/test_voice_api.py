"""Voice API: consent, ownership, validation, deletion and access rules. No model runs here
(see scripts/kai_voice_verify.py for real inference)."""
from __future__ import annotations

import io
import struct
import uuid
import wave

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import create_access_token, hash_password
from app.database.models.audit import AuditLog
from app.database.models.user import User
from app.database.models.voice import (
    ASSET_GENERATION, GEN_COMPLETED, PROFILE_READY, VoiceAsset, VoiceGeneration, VoiceProfile,
)
from app.voice.services import VoiceCloningService, get_tts_queue
from app.voice.storage import VoiceStorageService


def wav_bytes(seconds: float = 1.0) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(struct.pack("<h", 100) * int(16000 * seconds))
    return buffer.getvalue()


CONSENT = {"consent_confirmed": "true", "consent_basis": "own_voice"}


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(get_settings(), "voice_home", str(tmp_path))
    monkeypatch.setattr(get_settings(), "voice_allow_remote", False)
    # Background work needs real models; here we only assert it was asked for.
    scheduled: list = []
    monkeypatch.setattr(VoiceCloningService, "schedule", classmethod(lambda cls, pid, model: scheduled.append(pid)))
    monkeypatch.setattr(type(get_tts_queue()), "submit", lambda self, gid: scheduled.append(gid))
    return scheduled


async def _user(session, email: str) -> tuple[User, dict]:
    user = User(email=email, password_hash=hash_password("not-used-here-123"))
    session.add(user)
    await session.commit()
    return user, {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@pytest_asyncio.fixture
async def alice(db_session):
    return await _user(db_session, "alice@example.test")


@pytest_asyncio.fixture
async def bob(db_session):
    return await _user(db_session, "bob@example.test")


async def _create(client, headers, name="My voice", data=None, content=None, filename="v.wav"):
    return await client.post(
        "/voice/profiles", headers=headers,
        data={"name": name, **(CONSENT if data is None else data)},
        files={"file": (filename, content if content is not None else wav_bytes(), "audio/wav")},
    )


async def test_every_route_requires_authentication(client):
    for method, path in [
        ("get", "/voice/profiles"), ("get", f"/voice/profiles/{uuid.uuid4()}"),
        ("get", "/voice/generations"), ("get", "/voice/models"), ("get", "/voice/hardware"),
        ("get", "/voice/conversion/status"), ("get", f"/voice/profiles/{uuid.uuid4()}/reference/audio"),
    ]:
        assert (await getattr(client, method)(path)).status_code == 401, path


@pytest.mark.parametrize("header", ["cf-connecting-ip", "x-forwarded-for", "forwarded"])
async def test_proxied_requests_are_refused_by_default(client, alice, header):
    _, headers = alice
    response = await client.get("/voice/profiles", headers={**headers, header: "203.0.113.9"})
    assert response.status_code == 403
    assert response.json()["detail"] == "voice_local_only"


async def test_proxied_requests_work_only_when_explicitly_allowed(client, alice, monkeypatch):
    _, headers = alice
    monkeypatch.setattr(get_settings(), "voice_allow_remote", True)
    response = await client.get("/voice/profiles", headers={**headers, "cf-connecting-ip": "203.0.113.9"})
    assert response.status_code == 200


@pytest.mark.parametrize("data,detail", [
    ({}, "consent_required"),
    ({"consent_confirmed": "false", "consent_basis": "own_voice"}, "consent_required"),
    ({"consent_confirmed": "true"}, "consent_required"),
    ({"consent_confirmed": "true", "consent_basis": "found_online"}, "consent_required"),
    ({"consent_confirmed": "true", "consent_basis": "permission"}, "consent_subject_required"),
])
async def test_profile_requires_consent(client, alice, data, detail, db_session):
    _, headers = alice
    response = await _create(client, headers, data=data)
    assert response.status_code == 422
    assert response.json()["detail"] == detail
    assert (await db_session.execute(select(VoiceProfile))).first() is None


async def test_create_records_consent_stores_audio_and_schedules_cloning(client, alice, db_session, tmp_path, _isolated):
    user, headers = alice
    response = await client.post(
        "/voice/profiles", headers=headers,
        data={"name": "Maria", "consent_confirmed": "true", "consent_basis": "permission", "consent_subject": "Maria K."},
        files={"file": ("v.wav", wav_bytes(), "audio/wav")},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "processing" and body["is_default"] is True
    assert body["consent_subject"] == "Maria K." and body["consent_at"]
    assert "rel_path" not in str(body) and str(tmp_path) not in str(body)
    assert _isolated == [uuid.UUID(body["id"])]

    asset = (await db_session.execute(select(VoiceAsset))).scalars().one()
    stored = VoiceStorageService().resolve(asset.rel_path)
    assert stored.read_bytes() == wav_bytes() and stored.stat().st_mode & 0o077 == 0
    assert str(user.id) in asset.rel_path

    audit = (await db_session.execute(select(AuditLog).where(AuditLog.action == "voice.profile_created"))).scalars().one()
    assert audit.detail["consent_subject"] == "Maria K."


async def test_upload_validation(client, alice):
    _, headers = alice
    bad = await _create(client, headers, content=b"\x7fELF" + b"\x00" * 200)
    assert (bad.status_code, bad.json()["detail"]) == (415, "unsupported_audio_format")
    empty = await _create(client, headers, content=b"")
    assert (empty.status_code, empty.json()["detail"]) == (422, "empty_audio_file")


async def test_upload_size_limit(client, alice, monkeypatch, tmp_path):
    _, headers = alice
    monkeypatch.setattr(get_settings(), "voice_upload_max_mb", 1)
    response = await _create(client, headers, content=wav_bytes(40))
    assert (response.status_code, response.json()["detail"]) == (413, "audio_file_too_large")
    assert not list((tmp_path / "tmp").glob("*/*"))  # the partial upload is gone


async def test_duplicate_name_conflict(client, alice):
    _, headers = alice
    assert (await _create(client, headers, name="Same")).status_code == 201
    assert (await _create(client, headers, name="Same")).json()["detail"] == "voice_name_taken"


async def test_one_users_voices_are_invisible_to_another(client, alice, bob):
    _, alice_h = alice
    _, bob_h = bob
    profile_id = (await _create(client, alice_h, name="Private")).json()["id"]

    assert (await client.get("/voice/profiles", headers=bob_h)).json()["profiles"] == []
    for method, path, kwargs in [
        ("get", f"/voice/profiles/{profile_id}", {}),
        ("get", f"/voice/profiles/{profile_id}/reference/audio", {}),
        ("patch", f"/voice/profiles/{profile_id}", {"json": {"name": "Stolen"}}),
        ("delete", f"/voice/profiles/{profile_id}", {}),
        ("post", f"/voice/profiles/{profile_id}/clone", {"json": {}}),
    ]:
        response = await getattr(client, method)(path, headers=bob_h, **kwargs)
        assert response.status_code == 404, path
    generate = await client.post("/voice/tts/generate", headers=bob_h, json={"profile_id": profile_id, "text": "hello"})
    assert generate.status_code == 404
    assert (await client.get(f"/voice/profiles/{profile_id}", headers=alice_h)).json()["name"] == "Private"


async def test_generated_audio_is_private(client, alice, bob, db_session):
    user, alice_h = alice
    _, bob_h = bob
    profile_id = uuid.UUID((await _create(client, alice_h)).json()["id"])
    generation = VoiceGeneration(user_id=user.id, profile_id=profile_id, text="hi", status=GEN_COMPLETED)
    db_session.add(generation)
    await db_session.commit()
    for suffix in ("", "/audio"):
        assert (await client.get(f"/voice/generations/{generation.id}{suffix}", headers=bob_h)).status_code == 404
    assert (await client.delete(f"/voice/generations/{generation.id}", headers=bob_h)).status_code == 404
    assert (await client.post(f"/voice/generations/{generation.id}/cancel", headers=bob_h)).status_code == 404
    assert (await client.get("/voice/generations", headers=bob_h)).json()["generations"] == []
    assert len((await client.get("/voice/generations", headers=alice_h)).json()["generations"]) == 1


async def test_rename_search_and_single_default(client, alice):
    _, headers = alice
    first = (await _create(client, headers, name="First")).json()
    second = (await _create(client, headers, name="Second")).json()
    assert first["is_default"] and not second["is_default"]

    renamed = await client.patch(f"/voice/profiles/{second['id']}", headers=headers, json={"name": "Narrator", "is_default": True})
    assert renamed.json()["name"] == "Narrator" and renamed.json()["is_default"]
    profiles = (await client.get("/voice/profiles", headers=headers)).json()["profiles"]
    assert [p["name"] for p in profiles if p["is_default"]] == ["Narrator"]
    found = (await client.get("/voice/profiles?q=narr", headers=headers)).json()["profiles"]
    assert [p["name"] for p in found] == ["Narrator"]
    # LIKE metacharacters are literal.
    assert (await client.get("/voice/profiles?q=%25", headers=headers)).json()["profiles"] == []


async def test_replacing_a_recording_needs_consent_again_and_keeps_the_old_file(client, alice, db_session):
    _, headers = alice
    profile_id = (await _create(client, headers)).json()["id"]
    refused = await client.put(
        f"/voice/profiles/{profile_id}/reference", headers=headers, files={"file": ("n.wav", wav_bytes(2), "audio/wav")},
    )
    assert refused.json()["detail"] == "consent_required"
    accepted = await client.put(
        f"/voice/profiles/{profile_id}/reference", headers=headers, data=CONSENT,
        files={"file": ("n.wav", wav_bytes(2), "audio/wav")},
    )
    assert accepted.status_code == 200
    assets = (await db_session.execute(select(VoiceAsset).where(VoiceAsset.kind == "source"))).scalars().all()
    assert sorted(a.active for a in assets) == [False, True]
    assert len({a.rel_path for a in assets}) == 2
    assert all(VoiceStorageService().resolve(a.rel_path).exists() for a in assets)


async def test_delete_removes_recording_derived_audio_and_rows(client, alice, db_session):
    user, headers = alice
    other = (await _create(client, headers, name="Keep")).json()["id"]
    profile_id = uuid.UUID((await _create(client, headers, name="Delete me")).json()["id"])
    storage = VoiceStorageService()
    source = (await db_session.execute(select(VoiceAsset).where(VoiceAsset.profile_id == profile_id))).scalars().one()
    source_path = storage.resolve(source.rel_path)
    generation = VoiceGeneration(user_id=user.id, profile_id=profile_id, text="x", status=GEN_COMPLETED)
    db_session.add(generation)
    await db_session.flush()
    speech = storage.generation_dir(user.id, generation.id) / "speech.wav"
    speech.write_bytes(wav_bytes())
    db_session.add(VoiceAsset(user_id=user.id, generation_id=generation.id, kind=ASSET_GENERATION, rel_path=storage.rel(speech)))
    await db_session.commit()

    response = await client.delete(f"/voice/profiles/{profile_id}", headers=headers)
    assert response.status_code == 200 and response.json()["generations_deleted"] == 1
    assert not source_path.exists() and not speech.exists()
    generation_id = generation.id
    db_session.expire_all()
    assert await db_session.get(VoiceProfile, profile_id) is None
    assert await db_session.get(VoiceGeneration, generation_id) is None
    remaining = (await db_session.execute(select(VoiceAsset))).scalars().all()
    assert [str(a.profile_id) for a in remaining] == [other]
    assert (await client.get(f"/voice/profiles/{other}", headers=headers)).status_code == 200


async def test_generate_validates_and_requires_ready_voice(client, alice, db_session):
    _, headers = alice
    profile_id = (await _create(client, headers)).json()["id"]
    not_ready = await client.post("/voice/tts/generate", headers=headers, json={"profile_id": profile_id, "text": "hi"})
    assert (not_ready.status_code, not_ready.json()["detail"]) == (409, "voice_not_ready")

    profile = await db_session.get(VoiceProfile, uuid.UUID(profile_id))
    profile.status = PROFILE_READY
    await db_session.commit()
    blank = await client.post("/voice/tts/generate", headers=headers, json={"profile_id": profile_id, "text": "   "})
    assert blank.json()["detail"] == "text_required"
    long = await client.post("/voice/tts/generate", headers=headers, json={"profile_id": profile_id, "text": "a" * 20001})
    assert long.json()["detail"] == "text_too_long"
    fast = await client.post("/voice/tts/generate", headers=headers, json={"profile_id": profile_id, "text": "x", "speed": 9})
    assert fast.status_code == 422
    ok = await client.post("/voice/tts/generate", headers=headers, json={"profile_id": profile_id, "text": "hello"})
    assert ok.status_code == 202 and ok.json()["status"] == "queued"


async def test_rate_limit_applies_to_generation(client, alice, monkeypatch, db_session):
    _, headers = alice
    monkeypatch.setattr(get_settings(), "voice_rate_limit_per_min", 1)
    profile_id = (await _create(client, headers)).json()["id"]
    profile = await db_session.get(VoiceProfile, uuid.UUID(profile_id))
    profile.status = PROFILE_READY
    await db_session.commit()
    body = {"profile_id": profile_id, "text": "hello"}
    assert (await client.post("/voice/tts/generate", headers=headers, json=body)).status_code == 202
    assert (await client.post("/voice/tts/generate", headers=headers, json=body)).status_code == 429


async def test_unknown_model_action(client, alice):
    _, headers = alice
    response = await client.post("/voice/models/not-a-model", headers=headers, json={"action": "install"})
    assert response.status_code == 404
    assert (await client.post("/voice/models/qwen3-tts-0.6b", headers=headers, json={"action": "rm -rf"})).status_code == 422


def _ws_client():
    from starlette.testclient import TestClient

    from app.main import create_app

    app = create_app()
    app.router.on_startup.clear()
    return TestClient(app)


def test_websocket_rejects_missing_token_without_touching_models():
    with _ws_client().websocket_connect("/voice/conversion/ws") as ws:
        ws.send_json({"type": "hello", "token": "not-a-real-token", "profile_id": str(uuid.uuid4())})
        assert ws.receive_json() == {"type": "error", "code": "not_authenticated"}


def test_websocket_refuses_tunnelled_connections(monkeypatch):
    monkeypatch.setattr(get_settings(), "voice_allow_remote", False)
    with _ws_client().websocket_connect("/voice/conversion/ws", headers={"cf-connecting-ip": "203.0.113.9"}) as ws:
        assert ws.receive_json()["code"] == "voice_local_only"


def test_websocket_refuses_a_foreign_origin():
    with _ws_client().websocket_connect("/voice/conversion/ws", headers={"origin": "https://evil.example"}) as ws:
        assert ws.receive_json()["code"] == "voice_local_only"
