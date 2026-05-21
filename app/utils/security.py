"""Small security helpers — CSRF / Origin guard and secure hashing.

We use HMAC-SHA256 (constant-time compare) for any one-off token hashing
we need on the server. Supabase Auth already handles password hashing
(bcrypt with per-user salt) so we never see raw passwords here.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from urllib.parse import urlparse

from flask import request, current_app, jsonify
from functools import wraps


def sha256_hex(value: str, *, salt: str = "") -> str:
    """Deterministic SHA-256 hash (hex). For non-secret hashing only —
    e.g. rate-limit keys, idempotency hashes. Use ``hash_token`` for secrets."""
    h = hashlib.sha256()
    h.update((salt + value).encode("utf-8"))
    return h.hexdigest()


def hash_token(value: str) -> str:
    """HMAC-SHA256 of `value` keyed with the app secret. Suitable for hashing
    refresh tokens or session identifiers before storing them at rest."""
    key = (current_app.config.get("SECRET_KEY") or "").encode("utf-8")
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()


def constant_time_eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a or "", b or "")


def random_token(n_bytes: int = 32) -> str:
    return secrets.token_urlsafe(n_bytes)


def _same_origin(url: str) -> bool:
    if not url:
        return False
    try:
        u = urlparse(url)
        host = (request.host or "").lower()
        return (u.hostname or "").lower() == host.split(":")[0]
    except Exception:
        return False


def require_same_origin(view):
    """Reject state-changing requests whose Origin/Referer doesn't match us.

    This blocks the classic cross-site form-post CSRF on our JSON endpoints
    even though we don't ship a full token-based CSRF system. Pair with
    SameSite=Lax cookies (already enabled) for defense in depth.
    """

    @wraps(view)
    def wrapper(*args, **kwargs):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return view(*args, **kwargs)

        origin = request.headers.get("Origin", "")
        referer = request.headers.get("Referer", "")

        # In dev (no HTTPS), be lenient so localhost works smoothly.
        if not current_app.config.get("IS_PRODUCTION"):
            return view(*args, **kwargs)

        if not (_same_origin(origin) or _same_origin(referer)):
            return jsonify({"ok": False, "error": "Cross-origin request blocked."}), 403

        return view(*args, **kwargs)

    return wrapper
