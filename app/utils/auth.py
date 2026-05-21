"""Authentication helpers and decorators.

Supabase Auth is the source of truth for users. After the browser completes
sign-in, the Supabase JS client POSTs the access/refresh tokens to
``/auth/session`` which we store in the Flask session cookie. From then on the
server can identify the current user via :func:`current_user`.
"""
from __future__ import annotations

from functools import wraps
from typing import Optional

from flask import session, redirect, url_for, flash, request, current_app

from app.services.supabase_client import get_service_client


def current_user() -> Optional[dict]:
    """Return the logged-in user dict (id, email, role) or None."""
    return session.get("user")


def is_admin() -> bool:
    user = current_user()
    return bool(user and user.get("role") == "admin")


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            flash("Please sign in to continue.", "info")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not current_user():
            return redirect(url_for("auth.login", next=request.path))
        if not is_admin():
            flash("Admin access required.", "error")
            return redirect(url_for("main.home"))
        return view(*args, **kwargs)

    return wrapper


def store_user_in_session(user_obj: dict, access_token: str, refresh_token: str) -> None:
    """Persist Supabase user + tokens to the Flask session.

    Role resolution priority:
      1. ``user_metadata.role`` set in Supabase (e.g. "admin")
      2. Email matches ``ADMIN_EMAIL`` env var -> admin
      3. Otherwise -> customer
    """
    metadata = user_obj.get("user_metadata") or {}
    email = user_obj.get("email", "")
    role = metadata.get("role")
    if not role:
        admin_email = (current_app.config.get("ADMIN_EMAIL") or "").lower()
        role = "admin" if admin_email and email.lower() == admin_email else "customer"

    session.permanent = True
    session["user"] = {
        "id": user_obj.get("id"),
        "email": email,
        "name": metadata.get("full_name") or email.split("@")[0],
        "role": role,
    }
    session["access_token"] = access_token
    session["refresh_token"] = refresh_token


def clear_user_session() -> None:
    for key in ("user", "access_token", "refresh_token"):
        session.pop(key, None)


def ensure_profile_row(user_id: str, email: str, full_name: str, role: str) -> None:
    """Mirror the auth user into our ``profiles`` table (idempotent)."""
    svc = get_service_client()
    if not svc:
        return
    try:
        svc.table("profiles").upsert(
            {
                "id": user_id,
                "email": email,
                "full_name": full_name,
                "role": role,
            },
            on_conflict="id",
        ).execute()
    except Exception as exc:  # pragma: no cover - best-effort sync
        current_app.logger.warning("ensure_profile_row failed: %s", exc)
