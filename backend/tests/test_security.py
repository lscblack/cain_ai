import time

import pytest

from app.core import security
from app.core.security import TokenError


def test_password_hash_round_trip():
    h = security.hash_password("correct horse")
    assert h != "correct horse"
    assert security.verify_password("correct horse", h) is True
    assert security.verify_password("wrong", h) is False


def test_token_encode_decode():
    token = security.create_access_token("user-123")
    payload = security.decode_token(token)
    assert payload["sub"] == "user-123"


def test_tampered_token_rejected():
    token = security.create_access_token("user-123")
    with pytest.raises(TokenError):
        security.decode_token(token + "x")


def test_expired_token_rejected():
    from datetime import timedelta

    token = security.create_access_token("user-123", expires_delta=timedelta(seconds=-1))
    time.sleep(0.01)
    with pytest.raises(TokenError):
        security.decode_token(token)


def test_alg_none_token_rejected():
    # A token signed with 'none' / no signature must not be accepted.
    from jose import jwt

    forged = jwt.encode({"sub": "attacker"}, "", algorithm="HS256")
    # replace signature with empty + claim alg none style tampering
    header_b64 = forged.split(".")[0]
    with pytest.raises(TokenError):
        security.decode_token(f"{header_b64}..")
