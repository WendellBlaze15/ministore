"""Customer account area: profile, orders, tracking, wishlist, settings."""
from __future__ import annotations

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort, current_app, session

from app.utils.auth import login_required, current_user
from app.utils.security import require_same_origin
from app.utils.helpers import allowed_image, safe_filename
from app.services.supabase_client import get_service_client, get_anon_client

bp = Blueprint("account", __name__)


def _upload_avatar(svc, user_id: str, file) -> str | None:
    """Upload an avatar to the Supabase storage bucket and return its public URL.
    Returns None on failure. The bucket is reused from the product-images
    config to avoid extra setup."""
    if not file or not file.filename:
        return None
    if not allowed_image(file.filename):
        return None
    bucket = current_app.config.get("SUPABASE_STORAGE_BUCKET", "product-images")
    path = f"avatars/{user_id}/{safe_filename(file.filename)}"
    try:
        data_bytes = file.read()
        # Ensure bucket exists (best-effort, same as products).
        try:
            buckets = svc.storage.list_buckets() or []
            names = {getattr(b, "name", None) or (b.get("name") if isinstance(b, dict) else None) for b in buckets}
            if bucket not in names:
                svc.storage.create_bucket(bucket, options={"public": True})
        except Exception:
            pass
        svc.storage.from_(bucket).upload(
            path=path,
            file=data_bytes,
            file_options={"content-type": file.mimetype or "image/jpeg"},
        )
        return svc.storage.from_(bucket).get_public_url(path)
    except Exception as exc:
        current_app.logger.warning("avatar upload failed: %s", exc)
        return None


def _profile(svc, user_id: str) -> dict:
    if not svc:
        return {}
    try:
        return (svc.table("profiles").select("*").eq("id", user_id).single().execute()).data or {}
    except Exception:
        return {}


@bp.route("/")
@login_required
def index():
    """Account overview page — summary of orders + quick stats."""
    user = current_user()
    svc = get_service_client()
    profile = _profile(svc, user["id"])
    orders = []
    active_order = None
    total_spent = 0.0
    orders_count = 0
    if svc:
        try:
            orders = (
                svc.table("orders")
                .select("id, status, total, created_at, payment_method")
                .eq("user_id", user["id"])
                .order("created_at", desc=True)
                .limit(5)
                .execute()
            ).data or []
        except Exception:
            pass
        try:
            all_orders = (
                svc.table("orders")
                .select("id, status, total")
                .eq("user_id", user["id"])
                .execute()
            ).data or []
            orders_count = len(all_orders)
            total_spent = sum(float(o.get("total") or 0) for o in all_orders)
        except Exception:
            pass
        try:
            in_flight = (
                svc.table("orders")
                .select("id, status, total, created_at")
                .eq("user_id", user["id"])
                .in_("status", ["pending", "preparing", "shipped"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            ).data or []
            active_order = in_flight[0] if in_flight else None
        except Exception:
            pass

    wishlist_count = 0
    if svc:
        try:
            wishlist_count = (
                svc.table("wishlists").select("id", count="exact")
                .eq("user_id", user["id"]).execute()
            ).count or 0
        except Exception:
            pass

    return render_template(
        "account/index.html",
        profile=profile, recent_orders=orders, wishlist_count=wishlist_count,
        active_order=active_order, total_spent=total_spent,
        orders_count=orders_count,
    )


@bp.route("/profile", methods=["GET"])
@login_required
def profile():
    user = current_user()
    svc = get_service_client()
    return render_template("account/profile.html", profile=_profile(svc, user["id"]))


@bp.route("/profile", methods=["POST"])
@login_required
@require_same_origin
def profile_save():
    user = current_user()
    svc = get_service_client()
    if not svc:
        flash("Server not configured.", "error")
        return redirect(url_for("account.profile"))

    data = request.form
    full_name = (data.get("full_name") or "").strip()[:120]
    username = (data.get("username") or "").strip()[:40]
    contact_number = (data.get("contact_number") or "").strip()[:32]
    address = (data.get("address") or "").strip()[:500]

    patch: dict[str, object] = {}
    if full_name: patch["full_name"] = full_name
    if username:
        try:
            dup = (
                svc.table("profiles").select("id").ilike("username", username)
                .neq("id", user["id"]).limit(1).execute()
            ).data or []
            if dup:
                flash("That username is already taken.", "error")
                return redirect(url_for("account.profile"))
        except Exception:
            pass
        patch["username"] = username
    if contact_number: patch["contact_number"] = contact_number
    patch["address"] = address  # allow clearing

    # Optional avatar upload.
    avatar_file = request.files.get("avatar")
    if avatar_file and avatar_file.filename:
        url = _upload_avatar(svc, user["id"], avatar_file)
        if url:
            patch["avatar_url"] = url
        else:
            flash("Could not upload avatar (please use JPG/PNG/WebP).", "error")

    try:
        svc.table("profiles").update(patch).eq("id", user["id"]).execute()
    except Exception as exc:
        # If avatar_url column doesn't exist yet, retry without it.
        if "avatar_url" in patch and "avatar_url" in str(exc).lower():
            patch.pop("avatar_url", None)
            try:
                svc.table("profiles").update(patch).eq("id", user["id"]).execute()
                flash("Saved, but avatars aren't enabled yet. Run migration 008.", "info")
            except Exception as exc2:
                flash(f"Could not save: {exc2}", "error")
                return redirect(url_for("account.profile"))
        else:
            flash(f"Could not save: {exc}", "error")
            return redirect(url_for("account.profile"))

    # Mirror identity changes into the session so navbar/sidebar update.
    u = dict(session.get("user") or {})
    if full_name: u["name"] = full_name
    if patch.get("avatar_url"): u["avatar_url"] = patch["avatar_url"]
    session["user"] = u

    flash("Profile updated. 🌸", "success")
    return redirect(url_for("account.profile"))


@bp.route("/orders")
@login_required
def orders():
    """Full customer order history — uses the existing orders blueprint logic."""
    user = current_user()
    svc = get_service_client()
    rows = []
    if svc:
        try:
            rows = (
                svc.table("orders")
                .select("id, status, total, created_at, payment_method, full_name")
                .eq("user_id", user["id"])
                .order("created_at", desc=True)
                .execute()
            ).data or []
        except Exception:
            pass
    return render_template("account/orders.html", orders=rows)


@bp.route("/tracking")
@login_required
def tracking():
    """Lightweight tracking landing page that lets the buyer paste a code
    or pick from their orders list."""
    user = current_user()
    svc = get_service_client()
    active = []
    if svc:
        try:
            active = (
                svc.table("orders")
                .select("id, status, total, created_at")
                .eq("user_id", user["id"])
                .neq("status", "delivered")
                .neq("status", "cancelled")
                .order("created_at", desc=True)
                .execute()
            ).data or []
        except Exception:
            pass
    return render_template("account/tracking.html", active_orders=active)


# -------------------- Wishlist --------------------

@bp.route("/wishlist")
@login_required
def wishlist():
    user = current_user()
    svc = get_service_client()
    items = []
    if svc:
        try:
            rows = (
                svc.table("wishlists").select("product_id, created_at")
                .eq("user_id", user["id"]).order("created_at", desc=True).execute()
            ).data or []
            pids = [r["product_id"] for r in rows if r.get("product_id")]
            if pids:
                prods = (
                    svc.table("products").select("id, name, slug, price, cover_image, stock, is_active")
                    .in_("id", pids).execute()
                ).data or []
                by_id = {p["id"]: p for p in prods}
                items = [by_id[pid] for pid in pids if pid in by_id]
        except Exception as exc:
            current_app.logger.warning("wishlist load failed: %s", exc)
    return render_template("account/wishlist.html", items=items)


# -------------------- Settings + security --------------------

@bp.route("/settings", methods=["GET"])
@login_required
def settings():
    user = current_user()
    svc = get_service_client()
    return render_template("account/settings.html", profile=_profile(svc, user["id"]))


@bp.route("/settings/password-otp", methods=["POST"])
@login_required
@require_same_origin
def request_password_otp():
    """Send a 6-digit OTP to the signed-in user's email, then redirect them
    to /auth/reset (the existing reset page) so they can paste the code and
    set a new password. This replaces the old current-password flow with a
    safer email-verified one (matching the buyer's expectation in the UI)."""
    from app.services.otp import request_reset_code

    user = current_user()
    if not user:
        return redirect(url_for("auth.login"))

    ok, message = request_reset_code(user["email"])
    if ok:
        flash(message, "success")
        return redirect(url_for("auth.reset", email=user["email"]))
    flash(message or "Could not send a reset code right now.", "error")
    return redirect(url_for("account.settings"))


@bp.route("/settings/delete", methods=["POST"])
@login_required
@require_same_origin
def delete_account():
    """Soft-confirmed delete: the user must type their email to confirm."""
    user = current_user()
    typed = (request.form.get("confirm_email") or "").strip().lower()
    if typed != (user["email"] or "").lower():
        flash("Type your full email to confirm deletion.", "error")
        return redirect(url_for("account.settings"))

    svc = get_service_client()
    if svc is None:
        flash("Server is not configured.", "error")
        return redirect(url_for("account.settings"))
    try:
        svc.auth.admin.delete_user(user["id"])
    except Exception as exc:
        current_app.logger.warning("delete_account failed: %s", exc)
        flash("Could not delete your account. Please contact us in chat.", "error")
        return redirect(url_for("account.settings"))

    session.clear()
    flash("Your account has been deleted. We'll miss you 💌", "success")
    return redirect(url_for("main.home"))


_UUID_RE = __import__("re").compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


@bp.route("/wishlist/ids", methods=["GET"])
@login_required
def wishlist_ids():
    """Return the product_ids the current user has wishlisted. Lets
    product cards paint the filled heart on first paint without making
    one request per card."""
    user = current_user()
    svc = get_service_client()
    if not svc:
        return jsonify({"ok": True, "ids": []})
    try:
        rows = (
            svc.table("wishlists").select("product_id")
            .eq("user_id", user["id"]).execute()
        ).data or []
        return jsonify({"ok": True, "ids": [r["product_id"] for r in rows if r.get("product_id")]})
    except Exception:
        return jsonify({"ok": True, "ids": []})


@bp.route("/wishlist/toggle", methods=["POST"])
@login_required
@require_same_origin
def wishlist_toggle():
    user = current_user()
    data = request.get_json(silent=True) or request.form
    product_id = (data.get("product_id") or "").strip()
    if not product_id or not _UUID_RE.match(product_id):
        return jsonify({"ok": False, "error": "Invalid product."}), 400

    svc = get_service_client()
    if not svc:
        return jsonify({"ok": False, "error": "Server not configured."}), 500

    try:
        existing = (
            svc.table("wishlists").select("id")
            .eq("user_id", user["id"]).eq("product_id", product_id)
            .limit(1).execute()
        ).data or []
        if existing:
            svc.table("wishlists").delete().eq("id", existing[0]["id"]).execute()
            return jsonify({"ok": True, "saved": False})
        svc.table("wishlists").insert({"user_id": user["id"], "product_id": product_id}).execute()
        return jsonify({"ok": True, "saved": True})
    except Exception as exc:
        current_app.logger.warning("wishlist_toggle failed: %s", exc)
        return jsonify({"ok": False, "error": "Could not update wishlist. Please try again."}), 500
