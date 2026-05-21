"""Authentication routes.

The browser handles the actual Supabase sign-in via the JS SDK (so realtime &
RLS work seamlessly). After a successful sign-in, JS POSTs the session tokens
to ``/auth/session``.

⚠️ Security: we never trust the ``user`` field from the browser. We always
re-verify the access token with Supabase before storing anything in the Flask
session cookie. Otherwise an attacker could POST a fake user payload.
"""
from __future__ import annotations

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, current_app, session

from app.utils.auth import (
    store_user_in_session,
    clear_user_session,
    ensure_profile_row,
    current_user,
)
from app.services.supabase_client import get_anon_client
from app.utils.security import require_same_origin

bp = Blueprint("auth", __name__)


@bp.route("/login")
def login():
    if current_user():
        return redirect(url_for("main.home"))
    return render_template("auth/login.html", next=request.args.get("next", ""))


@bp.route("/register")
def register():
    if current_user():
        return redirect(url_for("main.home"))
    return render_template("auth/register.html")


@bp.route("/forgot", methods=["GET"])
def forgot():
    return render_template("auth/forgot.html", prefill_email=request.args.get("email", ""))


@bp.route("/forgot", methods=["POST"])
@require_same_origin
def forgot_post():
    from app.services.otp import request_reset_code

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    ok, message = request_reset_code(email)
    status = 200 if ok else 400
    return jsonify({"ok": ok, "message": message}), status


@bp.route("/reset", methods=["GET"])
def reset():
    return render_template("auth/reset.html", prefill_email=request.args.get("email", ""))


@bp.route("/reset", methods=["POST"])
@require_same_origin
def reset_post():
    from app.services.otp import verify_and_consume, reset_password

    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip()
    code = (data.get("code") or "").strip()
    new_password = data.get("new_password") or ""
    confirm = data.get("confirm_password") or ""

    if new_password != confirm:
        return jsonify({"ok": False, "error": "Passwords don't match."}), 400

    ok, user_id, msg = verify_and_consume(email, code)
    if not ok:
        return jsonify({"ok": False, "error": msg}), 400

    ok2, msg2 = reset_password(user_id, new_password)
    if not ok2:
        return jsonify({"ok": False, "error": msg2}), 400
    return jsonify({"ok": True, "message": msg2})


@bp.route("/session", methods=["POST"])
@require_same_origin
def create_session():
    """Verify the Supabase access token, then store the user in our session.

    The token verification ensures the request can't be forged with a fake
    user payload — we always go back to Supabase to ask "who is this token?".
    """
    data = request.get_json(silent=True) or {}
    access_token = (data.get("access_token") or "").strip()
    refresh_token = (data.get("refresh_token") or "").strip()

    if not access_token:
        return jsonify({"ok": False, "error": "Missing access_token"}), 400

    supa = get_anon_client()
    if supa is None:
        return jsonify({"ok": False, "error": "Server is not configured for Supabase yet."}), 500

    try:
        user_resp = supa.auth.get_user(access_token)
    except Exception as exc:
        current_app.logger.warning("get_user failed: %s", exc)
        return jsonify({"ok": False, "error": "Invalid or expired session."}), 401

    user = getattr(user_resp, "user", None)
    if not user or not getattr(user, "id", None):
        return jsonify({"ok": False, "error": "Invalid session."}), 401

    verified_user = {
        "id": user.id,
        "email": user.email,
        "user_metadata": getattr(user, "user_metadata", None) or {},
    }
    store_user_in_session(verified_user, access_token, refresh_token)

    sess_user = current_user() or {}
    ensure_profile_row(
        user_id=sess_user.get("id", ""),
        email=sess_user.get("email", ""),
        full_name=sess_user.get("name", ""),
        role=sess_user.get("role", "customer"),
    )
    return jsonify({"ok": True, "role": sess_user.get("role")})


@bp.route("/logout", methods=["POST", "GET"])
def logout():
    clear_user_session()
    if request.method == "POST":
        return jsonify({"ok": True})
    flash("You're signed out. See you soon! 💌", "success")
    return redirect(url_for("main.home"))


@bp.route("/complete-profile", methods=["POST"])
@require_same_origin
def complete_profile():
    """Persist the extra registration fields (username, contact, address) to
    the ``profiles`` row of the current signed-in user."""
    from app.services.supabase_client import get_service_client

    user = current_user()
    if not user:
        return jsonify({"ok": False, "error": "Not signed in"}), 401

    data = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()[:120]
    username = (data.get("username") or "").strip()[:40]
    contact_number = (data.get("contact_number") or "").strip()[:32]
    address = (data.get("address") or "").strip()[:500]

    svc = get_service_client()
    if not svc:
        return jsonify({"ok": False, "error": "Server not configured."}), 500

    patch = {}
    if full_name:
        patch["full_name"] = full_name
    if username:
        try:
            # Reject duplicate usernames (case-insensitive).
            dup = (
                svc.table("profiles")
                .select("id")
                .ilike("username", username)
                .neq("id", user["id"])
                .limit(1)
                .execute()
            ).data or []
            if dup:
                return jsonify({"ok": False, "error": "That username is taken."}), 400
        except Exception:
            pass
        patch["username"] = username
    if contact_number:
        patch["contact_number"] = contact_number
    if address:
        patch["address"] = address

    if not patch:
        return jsonify({"ok": True, "message": "Nothing to update."})

    try:
        svc.table("profiles").update(patch).eq("id", user["id"]).execute()
    except Exception as exc:
        current_app.logger.warning("complete_profile failed: %s", exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    # Refresh in-session display name if needed.
    if "full_name" in patch:
        sess_user = dict(session.get("user") or {})
        sess_user["name"] = patch["full_name"]
        session["user"] = sess_user

    return jsonify({"ok": True})
