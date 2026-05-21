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


def _resolve_role(email: str, metadata: dict, existing_role: Optional[str]) -> str:
    """Resolve the user's effective role.

    Precedence:
      1. ``user_metadata.role == 'admin'``      -> admin (set by an admin)
      2. Email matches ``ADMIN_EMAIL`` env var   -> admin (initial bootstrap)
      3. Existing role on the profile row        -> keep it (admins set via SQL)
      4. Default                                 -> 'customer'
    """
    if (metadata or {}).get("role") == "admin":
        return "admin"
    admin_email = (current_app.config.get("ADMIN_EMAIL") or "").lower()
    if admin_email and (email or "").lower() == admin_email:
        return "admin"
    if existing_role in ("admin", "customer"):
        return existing_role
    return "customer"


def _fetch_existing_profile(user_id: str) -> dict:
    svc = get_service_client()
    if not svc:
        return {}
    try:
        rows = (
            svc.table("profiles")
            .select("role, full_name, email, username, contact_number, address")
            .eq("id", user_id)
            .limit(1)
            .execute()
        ).data or []
        return rows[0] if rows else {}
    except Exception:
        return {}


def store_user_in_session(user_obj: dict, access_token: str, refresh_token: str) -> None:
    """Persist Supabase user + tokens to the Flask session.

    Also mirrors any registration metadata (username, contact_number,
    address) into the public.profiles row on first sign-in.
    """
    metadata = user_obj.get("user_metadata") or {}
    email = user_obj.get("email") or ""
    user_id = user_obj.get("id") or ""

    existing = _fetch_existing_profile(user_id)
    role = _resolve_role(email, metadata, existing.get("role"))

    name = (
        existing.get("full_name")
        or metadata.get("full_name")
        or (email.split("@")[0] if email else "Friend")
    )

    session.permanent = True
    session["user"] = {
        "id": user_id,
        "email": email,
        "name": name,
        "role": role,
    }
    session["access_token"] = access_token
    session["refresh_token"] = refresh_token

    # Sync registration metadata (full_name + username + contact_number + address)
    # into the profile row. Idempotent: only fills empty fields, never overwrites
    # data the user might have edited later.
    try:
        _sync_metadata_to_profile(user_id, existing, metadata)
    except Exception:  # pragma: no cover - best-effort
        pass


def _sync_metadata_to_profile(user_id: str, existing: dict, metadata: dict) -> None:
    if not user_id or not metadata:
        return
    svc = get_service_client()
    if not svc:
        return

    patch = {}
    full_name = (metadata.get("full_name") or "").strip()
    username = (metadata.get("username") or "").strip()
    contact = (metadata.get("contact_number") or "").strip()
    address = (metadata.get("address") or "").strip()

    if full_name and not (existing.get("full_name") or "").strip():
        patch["full_name"] = full_name[:120]
    if username and not (existing.get("username") or "").strip():
        patch["username"] = username[:40]
    if contact and not (existing.get("contact_number") or "").strip():
        patch["contact_number"] = contact[:32]
    if address and not (existing.get("address") or "").strip():
        patch["address"] = address[:500]

    if patch:
        try:
            svc.table("profiles").update(patch).eq("id", user_id).execute()
        except Exception as exc:
            current_app.logger.warning("metadata sync failed: %s", exc)


def clear_user_session() -> None:
    for key in ("user", "access_token", "refresh_token"):
        session.pop(key, None)


def ensure_profile_row(user_id: str, email: str, full_name: str, role: str) -> None:
    """Mirror the auth user into our ``profiles`` table (idempotent).

    Only writes fields that actually need updating, so we don't trample
    a user-edited full_name or a manually-set role.
    """
    svc = get_service_client()
    if not svc or not user_id:
        return
    try:
        existing = (
            svc.table("profiles")
            .select("id, email, full_name, role")
            .eq("id", user_id)
            .limit(1)
            .execute()
        ).data or []
        if existing:
            current = existing[0]
            patch = {}
            if (current.get("email") or "") != (email or ""):
                patch["email"] = email
            if not (current.get("full_name") or "") and full_name:
                patch["full_name"] = full_name
            if role == "admin" and current.get("role") != "admin":
                patch["role"] = "admin"
            if patch:
                svc.table("profiles").update(patch).eq("id", user_id).execute()
            return
        svc.table("profiles").insert(
            {
                "id": user_id,
                "email": email,
                "full_name": full_name,
                "role": role,
            }
        ).execute()
    except Exception as exc:  # pragma: no cover - best-effort sync
        current_app.logger.warning("ensure_profile_row failed: %s", exc)
