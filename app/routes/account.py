"""Customer account area: profile, orders, tracking, wishlist."""
from __future__ import annotations

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash, abort, current_app

from app.utils.auth import login_required, current_user
from app.utils.security import require_same_origin
from app.services.supabase_client import get_service_client

bp = Blueprint("account", __name__)


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

    try:
        svc.table("profiles").update(patch).eq("id", user["id"]).execute()
    except Exception as exc:
        flash(f"Could not save: {exc}", "error")
        return redirect(url_for("account.profile"))

    if full_name:
        from flask import session
        u = dict(session.get("user") or {}); u["name"] = full_name
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


_UUID_RE = __import__("re").compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


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
