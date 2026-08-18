import hashlib
import hmac

from prcrew.github.webhooks import RecentDeliveries, verify_signature

SECRET = "test-webhook-secret"


def sign(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_valid_signature_accepted():
    body = b'{"action": "opened"}'
    assert verify_signature(SECRET, body, sign(body)) is True


def test_wrong_secret_rejected():
    body = b'{"action": "opened"}'
    assert verify_signature(SECRET, body, sign(body, "wrong")) is False


def test_tampered_body_rejected():
    assert verify_signature(SECRET, b'{"a": 2}', sign(b'{"a": 1}')) is False


def test_missing_or_malformed_header_rejected():
    assert verify_signature(SECRET, b"x", None) is False
    assert verify_signature(SECRET, b"x", "sha1=abc") is False
    assert verify_signature("", b"x", sign(b"x", "")) is False  # unset secret: reject


def test_delivery_dedupe():
    d = RecentDeliveries(maxlen=2)
    assert d.seen("g1") is False
    assert d.seen("g1") is True
    assert d.seen("g2") is False
    assert d.seen("g3") is False   # evicts g1
    assert d.seen("g1") is False   # g1 forgotten after eviction
