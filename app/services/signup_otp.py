from __future__ import annotations

import hmac
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from flask import current_app

from app.services.email import send_email
from app.services.supabase_client import get_service_client
from app.utils.security import hash_token

CODE_LENGTH = 6
EXPIRES_MINUTES = 15
MAX_ATTEMPTS = 5
COOLDOWN_SECONDS = 45


def _generate_code() -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(CODE_LENGTH))


def _hash_code(code: str) -> str:
    return hash_token(f"signup:{code}")


def _render_signup_email(code: str, minutes: int) -> tuple[str, str]:
    text = (
        f"Welcome to Papier Lab! 🌸\n\n"
        f"Your verification code is: {code}\n"
        f"It expires in {minutes} minutes.\n\n"
        f"If you didn't sign up, ignore this email.\n— Papier Lab"
    )
    html = f"""
    <div style="font-family:'Segoe UI',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:32px;background:linear-gradient(160deg,#ffe3ec,#fff7f9);border-radius:24px;color:#5b2c4a">
      <h1 style="font-family:'Playfair Display',serif;color:#c43a7a;margin:0 0 12px">Welcome to Papier Lab 🌸</h1>
      <p style="font-size:15px;line-height:1.6">Thanks for joining the pen-pals! To activate your account, enter this 6-digit code on the verification page:</p>
      <div style="background:white;border-radius:18px;padding:24px;text-align:center;letter-spacing:14px;font-size:32px;font-weight:700;color:#c43a7a;margin:20px 0">{code}</div>
      <p style="font-size:13px;color:#94598a">This code expires in <b>{minutes} minutes</b>. If you didn't try to sign up, just ignore this email.</p>
      <p style="font-size:13px;color:#94598a;margin-top:18px">— with love, Papier Lab</p>
    </div>
    """
    return text, html


def issue_signup_code(user_id: str, email: str) -> tuple[bool, str]:
    email = (email or "").strip().lower()
    if not user_id or not email or "@" not in email:
        return False, "Please provide a valid email."

    svc = get_service_client()
    if not svc:
        return False, "Server is not configured yet."

    try:
        latest = (
            svc.table("signup_codes")
            .select("created_at")
            .eq("user_id", user_id)
            .is_("used_at", None)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
        if latest:
            created = datetime.fromisoformat(latest[0]["created_at"].replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - created).total_seconds()
            if elapsed < COOLDOWN_SECONDS:
                wait = int(COOLDOWN_SECONDS - elapsed)
                return False, f"Please wait {wait}s before requesting another code."
    except Exception:
        pass

    code = _generate_code()
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=EXPIRES_MINUTES)

    try:
        svc.table("signup_codes").insert({
            "user_id": user_id,
            "email": email,
            "code_hash": _hash_code(code),
            "expires_at": expires_at.isoformat(),
        }).execute()
    except Exception as exc:
        current_app.logger.warning("issue_signup_code insert failed: %s", exc)
        return False, "Could not start verification. Please try again."

    text, html = _render_signup_email(code, EXPIRES_MINUTES)
    ok, info = send_email(
        to=email,
        subject="Your Papier Lab verification code 🌸",
        text_body=text,
        html_body=html,
    )
    if not ok:
        current_app.logger.error("signup OTP email failed for %s: %s", email, info)
        return False, "Could not send the verification email. Please try again."

    return True, "We sent a 6-digit code to your email. Check your inbox 💌"


def verify_signup_code(email: str, code: str) -> tuple[bool, Optional[str], str]:
    email = (email or "").strip().lower()
    code = (code or "").strip()

    if not email or not code or not code.isdigit() or len(code) != CODE_LENGTH:
        return False, None, "Please enter the 6-digit code we emailed you."

    svc = get_service_client()
    if not svc:
        return False, None, "Server is not configured yet."

    try:
        rows = (
            svc.table("signup_codes")
            .select("id, user_id, code_hash, attempts, expires_at, used_at")
            .ilike("email", email)
            .is_("used_at", None)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        ).data or []
    except Exception as exc:
        current_app.logger.warning("signup OTP lookup failed: %s", exc)
        return False, None, "Could not verify the code. Please try again."

    if not rows:
        return False, None, "No active code for that email. Please request a new one."

    row = rows[0]
    row_id = row["id"]
    expires_at = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
    if datetime.now(timezone.utc) > expires_at:
        return False, None, "This code expired. Please request a new one."

    attempts = int(row.get("attempts") or 0)
    if attempts >= MAX_ATTEMPTS:
        try:
            svc.table("signup_codes").update({
                "used_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", row_id).execute()
        except Exception:
            pass
        return False, None, "Too many wrong attempts. Please request a new code."

    if not hmac.compare_digest(row["code_hash"], _hash_code(code)):
        try:
            svc.table("signup_codes").update({"attempts": attempts + 1}).eq("id", row_id).execute()
        except Exception:
            pass
        return False, None, "That code didn't match. Please try again."

    try:
        svc.table("signup_codes").update({
            "used_at": datetime.now(timezone.utc).isoformat(),
            "attempts": attempts + 1,
        }).eq("id", row_id).execute()
    except Exception:
        pass

    try:
        svc.auth.admin.update_user_by_id(row["user_id"], {"email_confirm": True})
    except Exception as exc:
        current_app.logger.warning("email_confirm flip failed: %s", exc)
        return False, None, "Verification saved, but Supabase update failed. Please contact admin."

    return True, row["user_id"], "Account verified! You can sign in now. 🌸"
