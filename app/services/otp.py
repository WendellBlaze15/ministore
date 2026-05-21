"""Password-reset OTP service.

Flow:
1. Customer enters their email on /auth/forgot.
2. We generate a 6-digit code, hash it with HMAC-SHA256 keyed on
   FLASK_SECRET_KEY, and insert a row into ``password_reset_codes``.
3. We email the plain code via SMTP. Only the hash lives in the DB.
4. The customer enters the code on /auth/reset.
5. We verify by hashing the submitted code and comparing constant-time
   against the latest unused row for that email.
6. On success we update the Supabase Auth password via the admin API
   and mark the row used.

We don't reveal whether an email exists (to prevent enumeration), but
we DO send the email only if the user actually has an account.
"""
from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import current_app

from app.services.email import send_email, render_otp_email
from app.services.supabase_client import get_service_client
from app.utils.security import hash_token

# Tuning knobs
CODE_LENGTH = 6
EXPIRES_MINUTES = 10
MAX_ATTEMPTS = 5
COOLDOWN_SECONDS = 60  # don't re-issue more often than this per email


def _generate_code() -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(CODE_LENGTH))


def _hash_code(code: str) -> str:
    return hash_token(f"otp:{code}")


def _user_exists(email: str) -> bool:
    svc = get_service_client()
    if not svc:
        return False
    try:
        rows = (
            svc.table("profiles")
            .select("id")
            .ilike("email", email.strip())
            .limit(1)
            .execute()
        ).data or []
        return bool(rows)
    except Exception:
        return False


def request_reset_code(email: str) -> tuple[bool, str]:
    """Issue (and email) a new OTP. Returns (ok, friendly_message).

    For privacy we ALWAYS return the same neutral message in routes —
    callers should not branch on this return value to leak existence info.
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return False, "Please enter a valid email address."

    svc = get_service_client()
    if not svc:
        return False, "Server isn't fully configured yet."

    # Cooldown to prevent floods.
    try:
        latest = (
            svc.table("password_reset_codes")
            .select("created_at")
            .ilike("email", email)
            .is_("used_at", None)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        if latest:
            created = datetime.fromisoformat(latest[0]["created_at"].replace("Z", "+00:00"))
            if (datetime.now(timezone.utc) - created).total_seconds() < COOLDOWN_SECONDS:
                return True, "If that email is registered, a code is already on its way."
    except Exception:
        pass

    if not _user_exists(email):
        # Don't issue a code, but pretend success.
        return True, "If that email is registered, we just sent a 6-digit code."

    code = _generate_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=EXPIRES_MINUTES)
    try:
        svc.table("password_reset_codes").insert({
            "email": email,
            "code_hash": _hash_code(code),
            "expires_at": expires_at.isoformat(),
        }).execute()
    except Exception as exc:
        current_app.logger.warning("Could not store reset code: %s", exc)
        return False, "Could not start the reset. Please try again."

    text, html = render_otp_email(code, EXPIRES_MINUTES)
    ok, info = send_email(
        to=email,
        subject="Your Papier Lab password reset code 🌸",
        text_body=text,
        html_body=html,
    )
    if not ok:
        # The code is in the DB but we couldn't email it. Hide the SMTP
        # error from the user but log it for the admin.
        current_app.logger.error("OTP email failed for %s: %s", email, info)
        return False, "Email service hiccup. Please try again in a minute."

    return True, "If that email is registered, we just sent a 6-digit code."


def verify_and_consume(email: str, code: str) -> tuple[bool, Optional[str], str]:
    """Verify an OTP. On success returns (True, user_id, "ok"); otherwise
    (False, None, friendly_error). Increments attempts on each failure.
    """
    email = (email or "").strip().lower()
    code = (code or "").strip()
    if not email or not code or not code.isdigit() or len(code) != CODE_LENGTH:
        return False, None, "Please enter the 6-digit code we sent."

    svc = get_service_client()
    if not svc:
        return False, None, "Server isn't fully configured yet."

    try:
        rows = (
            svc.table("password_reset_codes")
            .select("id, code_hash, attempts, expires_at, used_at")
            .ilike("email", email)
            .is_("used_at", None)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
    except Exception as exc:
        current_app.logger.warning("OTP lookup failed: %s", exc)
        return False, None, "Could not verify the code. Try again."

    if not rows:
        return False, None, "No active code for that email. Please request a new one."

    row = rows[0]
    row_id = row["id"]
    expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        return False, None, "This code has expired. Please request a new one."

    attempts = int(row.get("attempts") or 0)
    if attempts >= MAX_ATTEMPTS:
        try:
            svc.table("password_reset_codes").update({"used_at": datetime.now(timezone.utc).isoformat()}).eq("id", row_id).execute()
        except Exception:
            pass
        return False, None, "Too many wrong attempts. Please request a new code."

    if not hmac.compare_digest(row["code_hash"], _hash_code(code)):
        try:
            svc.table("password_reset_codes").update({"attempts": attempts + 1}).eq("id", row_id).execute()
        except Exception:
            pass
        return False, None, "That code didn't match. Please try again."

    # Look up the Supabase Auth user id for this email
    try:
        profile = (
            svc.table("profiles")
            .select("id")
            .ilike("email", email)
            .limit(1)
            .execute()
        ).data or []
    except Exception as exc:
        current_app.logger.warning("profile lookup failed: %s", exc)
        profile = []
    if not profile:
        return False, None, "We couldn't find your account anymore. Please register."

    try:
        svc.table("password_reset_codes").update({
            "used_at": datetime.now(timezone.utc).isoformat(),
            "attempts": attempts + 1,
        }).eq("id", row_id).execute()
    except Exception:
        pass

    return True, profile[0]["id"], "ok"


def reset_password(user_id: str, new_password: str) -> tuple[bool, str]:
    """Set a new password for the given user via the Supabase Admin API."""
    if not user_id:
        return False, "Missing user."
    if not new_password or len(new_password) < 8:
        return False, "Use at least 8 characters for the new password."

    svc = get_service_client()
    if not svc:
        return False, "Server isn't fully configured yet."

    try:
        svc.auth.admin.update_user_by_id(user_id, {"password": new_password})
        return True, "Password updated. You can sign in now."
    except Exception as exc:
        current_app.logger.warning("admin update password failed: %s", exc)
        return False, "Could not update your password. Please try again."
