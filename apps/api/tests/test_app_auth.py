import time

import httpx
import jwt
import pytest
import respx
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from prcrew.github.app_auth import InstallationTokens, make_app_jwt


@pytest.fixture(scope="module")
def keypair():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption()).decode()
    pub = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo).decode()
    return pem, pub


def test_jwt_claims_and_signature(keypair):
    pem, pub = keypair
    now = 1_700_000_000.0
    token = make_app_jwt("12345", pem, now=now)
    claims = jwt.decode(token, pub, algorithms=["RS256"], options={"verify_exp": False})
    assert claims["iss"] == "12345"
    assert claims["iat"] == int(now) - 60
    assert claims["exp"] == int(now) + 540


@respx.mock
def test_token_fetch_and_cache(keypair):
    pem, _ = keypair
    route = respx.post("https://api.github.com/app/installations/111/access_tokens").mock(
        return_value=httpx.Response(201, json={
            "token": "ghs_abc", "expires_at": "2100-01-01T00:00:00Z"}))
    tokens = InstallationTokens("12345", pem)
    assert tokens.token(111) == "ghs_abc"
    assert tokens.token(111) == "ghs_abc"
    assert route.call_count == 1
    auth = route.calls[0].request.headers["authorization"]
    assert auth.startswith("Bearer ey")  # the App JWT, not a PAT


@respx.mock
def test_token_refreshed_near_expiry(keypair):
    pem, _ = keypair
    soon = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60))
    route = respx.post("https://api.github.com/app/installations/111/access_tokens").mock(
        return_value=httpx.Response(201, json={"token": "ghs_new", "expires_at": soon}))
    tokens = InstallationTokens("12345", pem)
    tokens.token(111)
    tokens.token(111)  # 60s left < 5 min margin -> refetch
    assert route.call_count == 2
