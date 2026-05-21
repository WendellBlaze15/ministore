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

    # Pre-check: does this email even exist? If not, we tell the user clearly
    # (instead of the generic "invalid email or password") so they can fix it.
    try:
        from app.services.supabase_client import get_service_client
        existing = _email_exists(get_service_client(), email)
    except Exception:
        existing = True  # fall back to letting Supabase decide
    if not existing:
        return _auth_error(
            "We don't have an account for that email yet. Try a different email or create a new account.",
            template="auth/login.html", next=next_url, http=400, email=email,
        )

    try:
        result = supa.auth.sign_in_with_password({"email": email, "password": password})
    except Exception as exc:
        current_app.logger.info("sign_in_with_password failed: %s", exc)
        msg_low = str(exc).lower()
        if "email" in msg_low and ("confirm" in msg_low or "not confirmed" in msg_low):
            if not is_json:
                flash("Your email isn't verified yet. Enter the 6-digit code we sent you.", "info")
                return redirect(url_for("auth.verify", email=email))
            return jsonify({"ok": False, "error": "email_not_verified",
                            "redirect": url_for("auth.verify", email=email)}), 400
        msg = "Wrong password. Please try again or use 'Forgot password'."
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


def _email_exists(svc, email: str) -> bool:
    """Robust check: look in profiles, then verify via auth admin API.

    Returns True if any account already exists for this email.
    """
    if not svc or not email:
        return False
    email = email.strip().lower()
    try:
        rows = (svc.table("profiles").select("id").ilike("email", email)
                  .limit(1).execute()).data or []
        if rows:
            return True
    except Exception:
        pass
    # Profiles row may be missing if confirmation never happened — fall back
    # to the Supabase auth admin list (small projects only).
    try:
        users = svc.auth.admin.list_users() or []
        return any((getattr(u, "email", "") or "").lower() == email for u in users)
    except Exception:
        return False


@bp.route("/check-email", methods=["POST"])
def check_email():
    """Inline AJAX check — does this email already have an account?

    Used by the register form to flag duplicates as soon as the user moves
    focus away from the email input. Never reveals partial info — always
    returns a small JSON payload.
    """
    from app.services.supabase_client import get_service_client

    data = request.get_json(silent=True) or request.form
    email = (data.get("email") or "").strip().lower()
    if not email or "@" not in email:
        return jsonify({"ok": True, "exists": False})

    svc = get_service_client()
    exists = _email_exists(svc, email)
    return jsonify({
        "ok": True,
        "exists": exists,
        "login_url": url_for("auth.login", email=email) if exists else None,
        "forgot_url": url_for("auth.forgot", email=email) if exists else None,
    })


@bp.route("/register", methods=["POST"])
def register_post():
    from app.services.supabase_client import get_service_client
    from app.services.signup_otp import issue_signup_code

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
    agree_terms = data.get("agree_terms")
    agreed = str(agree_terms).lower() in ("1", "true", "on", "yes") if agree_terms else False

    if not (full_name and email and contact_number and password):
        return _auth_error("Please fill in name, email, contact number and password.",
                            template="auth/register.html", http=400)
    if not agreed:
        return _auth_error("Please agree to our Privacy Policy and Terms to continue.",
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

    # Block re-registration of emails the admin has removed from the
    # studio. This is what fixes the "deleted user keeps coming back"
    # report — once banned, the same address can't slip back in.
    try:
        banned = (svc.table("banned_emails").select("email").eq("email", email).limit(1).execute()).data or []
    except Exception:
        banned = []
    if banned:
        return _auth_error(
            "This email is no longer accepted by the studio. "
            "Please contact us if you think this is a mistake.",
            template="auth/register.html", http=403,
        )

    composed_parts = [p for p in (address, barangay, city, province, region) if p]
    composed_address = ", ".join(composed_parts) if composed_parts else ""

    metadata = {
        "full_name": full_name, "username": username,
        "contact_number": contact_number,
        "address": composed_address,
        "region": region, "province": province, "city": city, "barangay": barangay,
    }

    # Pre-check: reject duplicate emails BEFORE we hit create_user so we can
    # offer a clean redirect to login.
    if _email_exists(svc, email):
        flash("That email is already registered. Please sign in or reset your password.", "error")
        if is_json:
            return jsonify({
                "ok": False,
                "error": "Email already registered.",
                "redirect": url_for("auth.login", email=email),
            }), 409
        return redirect(url_for("auth.login", email=email))

    if username:
        try:
            dup = (svc.table("profiles").select("id").ilike("username", username)
                    .limit(1).execute()).data or []
            if dup:
                return _auth_error("That username is already taken.",
                                    template="auth/register.html", http=400)
        except Exception:
            pass

    try:
        created = svc.auth.admin.create_user({
            "email": email, "password": password,
            "email_confirm": False, "user_metadata": metadata,
        })
        new_user = getattr(created, "user", None) or created
    except Exception as exc:
        msg = str(exc)
        current_app.logger.info("admin.create_user failed: %s", exc)
        if any(kw in msg.lower() for kw in ("already", "registered", "exists")):
            flash("That email is already registered. Please sign in or reset your password.", "error")
            if is_json:
                return jsonify({"ok": False, "error": "Email already registered.",
                                "redirect": url_for("auth.login", email=email)}), 409
            return redirect(url_for("auth.login", email=email))
        return _auth_error(msg, template="auth/register.html", http=400)

    try:
        svc.table("profiles").update({
            "full_name": full_name,
            "username": username or None,
            "contact_number": contact_number,
            "address": composed_address,
        }).eq("id", new_user.id).execute()
    except Exception as exc:
        current_app.logger.warning("post-register profile patch failed: %s", exc)

    ok, message = issue_signup_code(new_user.id, email)
    if not ok:
        try:
            svc.auth.admin.delete_user(new_user.id)
        except Exception:
            pass
        return _auth_error(message, template="auth/register.html", http=400)

    if is_json:
        return jsonify({"ok": True, "redirect": url_for("auth.verify", email=email)})
    flash(message, "success")
    return redirect(url_for("auth.verify", email=email))


@bp.route("/verify", methods=["GET"])
def verify():
    return render_template("auth/verify.html", prefill_email=request.args.get("email", ""))


@bp.route("/verify", methods=["POST"])
@require_same_origin
def verify_post():
    from app.services.signup_otp import verify_signup_code
    from app.services.supabase_client import get_anon_client

    data = request.get_json(silent=True) if request.is_json else request.form
    email = (data.get("email") or "").strip()
    code = (data.get("code") or "").strip()
    password = data.get("password") or ""

    ok, user_id, msg = verify_signup_code(email, code)
    if not ok:
        return jsonify({"ok": False, "error": msg}), 400

    if not password:
        return jsonify({"ok": True, "message": msg, "redirect": url_for("auth.login")})

    anon = get_anon_client()
    try:
        result = anon.auth.sign_in_with_password({"email": email, "password": password})
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
            full_name=sess_user.get("name", ""), role=sess_user.get("role", "customer"),
        )
        target = url_for("admin.dashboard") if sess_user.get("role") == "admin" else url_for("main.home")
        return jsonify({"ok": True, "message": msg, "redirect": target})
    except Exception as exc:
        current_app.logger.warning("post-verify sign_in failed: %s", exc)
        return jsonify({"ok": True, "message": msg, "redirect": url_for("auth.login")})


@bp.route("/verify/resend", methods=["POST"])
@require_same_origin
def verify_resend():
    from app.services.signup_otp import issue_signup_code
    from app.services.supabase_client import get_service_client

    data = request.get_json(silent=True) if request.is_json else request.form
    email = (data.get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "error": "Please provide your email."}), 400

    svc = get_service_client()
    if not svc:
        return jsonify({"ok": False, "error": "Server not configured."}), 500

    try:
        users = svc.auth.admin.list_users()
    except Exception:
        users = []
    match = None
    for u in users:
        if (getattr(u, "email", "") or "").lower() == email:
            match = u
            break
    if not match:
        return jsonify({"ok": True, "message": "If that email is pending, a new code is on its way."})

    if getattr(match, "email_confirmed_at", None):
        return jsonify({"ok": False, "error": "This account is already verified. Please sign in."}), 400

    ok, msg = issue_signup_code(match.id, email)
    return jsonify({"ok": ok, "message": msg, "error": None if ok else msg})


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
    """Send the 6-digit OTP, then redirect to /auth/reset with the email
    pre-filled. Supports both plain HTML POST (preferred) and JSON.
    """
    from app.services.otp import request_reset_code

    is_json = request.is_json
    data = request.get_json(silent=True) if is_json else request.form
    email = (data.get("email") or "").strip().lower()

    ok, message = request_reset_code(email)

    if is_json:
        status = 200 if ok else 400
        return jsonify({"ok": ok, "message": message,
                        "redirect": url_for("auth.reset", email=email)}), status

    if ok:
        flash(message, "success")
        return redirect(url_for("auth.reset", email=email))
    flash(message, "error")
    return redirect(url_for("auth.forgot", email=email))


@bp.route("/reset", methods=["GET"])
def reset():
    return render_template("auth/reset.html", prefill_email=request.args.get("email", ""))


@bp.route("/reset", methods=["POST"])
@require_same_origin
def reset_post():
    """Verify the OTP + set a new password. Supports plain HTML POST or JSON."""
    from app.services.otp import verify_and_consume, reset_password

    is_json = request.is_json
    data = request.get_json(silent=True) if is_json else request.form
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    new_password = data.get("new_password") or ""
    confirm = data.get("confirm_password") or ""

    if new_password != confirm:
        msg = "Passwords don't match."
        if is_json:
            return jsonify({"ok": False, "error": msg}), 400
        flash(msg, "error")
        return redirect(url_for("auth.reset", email=email))

    ok, user_id, msg = verify_and_consume(email, code)
    if not ok:
        if is_json:
            return jsonify({"ok": False, "error": msg}), 400
        flash(msg, "error")
        return redirect(url_for("auth.reset", email=email))

    ok2, msg2 = reset_password(user_id, new_password)
    if not ok2:
        if is_json:
            return jsonify({"ok": False, "error": msg2}), 400
        flash(msg2, "error")
        return redirect(url_for("auth.reset", email=email))

    if is_json:
        return jsonify({"ok": True, "message": msg2,
                        "redirect": url_for("auth.login")})
    flash("Password updated. Sign in with your new password ✨", "success")
    return redirect(url_for("auth.login"))


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
