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


@bp.route("/login", methods=["GET"])
def login():
    if current_user():
        return redirect(_safe_next(request.args.get("next"), "main.home"))
    return render_template("auth/login.html", next=request.args.get("next", ""))


@bp.route("/login", methods=["POST"])
def login_post():
    """Server-side sign-in. No browser-side Supabase SDK required."""
    from app.services.supabase_client import get_anon_client

    is_json = request.is_json
    data = request.get_json(silent=True) if is_json else request.form
    email = (data.get("email") or "").strip()
    password = data.get("password") or ""
    next_url = (data.get("next") or "").strip()

    if not email or not password:
        return _auth_error("Please enter your email and password.",
                            template="auth/login.html", next=next_url, http=400)

    supa = get_anon_client()
    if supa is None:
        return _auth_error("Server is not configured for Supabase yet.",
                            template="auth/login.html", next=next_url, http=500)

    try:
        result = supa.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        current_app.logger.info("sign_in_with_password failed: %s", exc)
        msg = str(exc)
        if "invalid" in msg.lower() or "email" in msg.lower() and "confirm" in msg.lower():
            msg = "Invalid email or password — or your email isn't confirmed yet."
        return _auth_error(msg, template="auth/login.html", next=next_url, http=400, email=email)

    sess = getattr(result, "session", None)
    user = getattr(result, "user", None)
    if not sess or not user:
        return _auth_error("Could not sign you in. Please try again.",
                            template="auth/login.html", next=next_url, http=400, email=email)

    verified_user = {
        "id": user.id, "email": user.email,
        "user_metadata": getattr(user, "user_metadata", None) or {},
    }
    store_user_in_session(verified_user, sess.access_token, sess.refresh_token)
    sess_user = current_user() or {}
    ensure_profile_row(
        user_id=sess_user.get("id", ""), email=sess_user.get("email", ""),
        full_name=sess_user.get("name", ""), role=sess_user.get("role", "customer"),
    )

    if is_json:
        return jsonify({"ok": True, "role": sess_user.get("role"),
                        "redirect": _safe_next_url(next_url, sess_user.get("role"))})

    flash("Welcome back! 🌸", "success")
    return redirect(_safe_next_url(next_url, sess_user.get("role")))


@bp.route("/register", methods=["GET"])
def register():
    if current_user():
        return redirect(url_for("main.home"))
    return render_template("auth/register.html")


@bp.route("/register", methods=["POST"])
def register_post():
    """Server-side registration. Uses the service-role client so the account
    is created already-confirmed — buyers can sign in immediately, no email
    confirmation round-trip required."""
    from app.services.supabase_client import get_service_client, get_anon_client

    is_json = request.is_json
    data = request.get_json(silent=True) if is_json else request.form

    full_name = (data.get("full_name") or "").strip()[:120]
    email = (data.get("email") or "").strip().lower()
    username = (data.get("username") or "").strip()[:40]
    contact_number = (data.get("contact_number") or "").strip()[:32]
    address = (data.get("address") or "").strip()[:500]
    region = (data.get("region") or "").strip()[:120]
    province = (data.get("province") or "").strip()[:120]
    city = (data.get("city") or "").strip()[:120]
    barangay = (data.get("barangay") or "").strip()[:120]
    password = data.get("password") or ""
    confirm_password = data.get("confirm_password") or ""

    if not (full_name and email and contact_number and password):
        return _auth_error("Please fill in name, email, contact number and password.",
                            template="auth/register.html", http=400)
    if len(password) < 8:
        return _auth_error("Password must be at least 8 characters.",
                            template="auth/register.html", http=400)
    if password != confirm_password:
        return _auth_error("Passwords don't match.",
                            template="auth/register.html", http=400)

    svc = get_service_client()
    if svc is None:
        return _auth_error("Server is not configured for Supabase yet.",
                            template="auth/register.html", http=500)

    # Compose a single readable address string for legacy fields and shipping.
    composed_address_parts = [p for p in (address, barangay, city, province, region) if p]
    composed_address = ", ".join(composed_address_parts) if composed_address_parts else ""

    metadata = {
        "full_name": full_name, "username": username,
        "contact_number": contact_number,
        "address": composed_address,
        "region": region, "province": province, "city": city, "barangay": barangay,
    }

    # 1) Reject obvious duplicate username early.
    if username:
        try:
            dup = (svc.table("profiles").select("id").ilike("username", username)
                    .limit(1).execute()).data or []
            if dup:
                return _auth_error("That username is already taken.",
                                    template="auth/register.html", http=400)
        except Exception:
            pass

    # 2) Create the user already-confirmed so buyers can sign in immediately.
    try:
        created = svc.auth.admin.create_user({
            "email": email, "password": password,
            "email_confirm": True, "user_metadata": metadata,
        })
        new_user = getattr(created, "user", None) or created
    except Exception as exc:
        msg = str(exc)
        current_app.logger.info("admin.create_user failed: %s", exc)
        if "already" in msg.lower() or "registered" in msg.lower() or "exists" in msg.lower():
            msg = "That email is already registered. Try signing in instead."
        return _auth_error(msg, template="auth/register.html", http=400)

    # 3) Sign in to mint a session for the new user.
    anon = get_anon_client()
    try:
        result = anon.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        current_app.logger.warning("post-register sign_in failed: %s", exc)
        return _auth_error("Account created — please sign in to continue.",
                            template="auth/login.html", http=200)

    sess = result.session
    user = result.user
    verified_user = {
        "id": user.id, "email": user.email,
        "user_metadata": getattr(user, "user_metadata", None) or {},
    }
    store_user_in_session(verified_user, sess.access_token, sess.refresh_token)
    sess_user = current_user() or {}
    ensure_profile_row(
        user_id=sess_user.get("id", ""), email=sess_user.get("email", ""),
        full_name=full_name, role=sess_user.get("role", "customer"),
    )

    # Patch the rest of the profile fields now.
    try:
        svc.table("profiles").update({
            "username": username or None,
            "contact_number": contact_number,
            "address": composed_address,
        }).eq("id", new_user.id).execute()
    except Exception as exc:
        current_app.logger.warning("post-register profile patch failed: %s", exc)

    if is_json:
        return jsonify({"ok": True, "redirect": url_for("main.home")})
    flash("Welcome to Papier Lab! 🌸", "success")
    return redirect(url_for("main.home"))


def _safe_next(value: str | None, fallback_endpoint: str) -> str:
    """Sanitize a next-url to avoid open-redirect attacks."""
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    return url_for(fallback_endpoint)


def _safe_next_url(value: str | None, role: str | None) -> str:
    if value and value.startswith("/") and not value.startswith("//"):
        return value
    if role == "admin":
        return url_for("admin.dashboard")
    return url_for("main.home")


def _auth_error(message: str, template: str, http: int = 400, **render_kwargs):
    """Return either JSON {ok:false} or re-render the form with a flash."""
    if request.is_json or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"ok": False, "error": message}), http
    flash(message, "error")
    return render_template(template, **render_kwargs), http


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
