"""GitHub webhook signature verification and delivery replay guard."""

import hashlib
import hmac
from collections import deque


def verify_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Constant-time check of X-Hub-Signature-256 against the raw body.

    An unset secret rejects everything: a deployment that forgot to
    configure the secret must fail closed, not open.
    """
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature_header.removeprefix("sha256="), expected)


class RecentDeliveries:
    """Bounded memory of recent X-GitHub-Delivery ids (replay guard).

    In-memory is sufficient: the api runs single-instance, and the worker's
    (repo, pr, head_sha) idempotency check is the durable second layer.
    """

    def __init__(self, maxlen: int = 1000):
        self._order: deque[str] = deque(maxlen=maxlen)
        self._ids: set[str] = set()

    def seen(self, delivery_id: str) -> bool:
        if delivery_id in self._ids:
            return True
        if len(self._order) == self._order.maxlen:
            self._ids.discard(self._order[0])
        self._order.append(delivery_id)
        self._ids.add(delivery_id)
        return False
