"""Customer order routes."""
from flask import Blueprint, render_template, abort, request, jsonify, redirect, url_for, flash

from app.utils.auth import login_required, current_user
from app.utils.security import require_same_origin
from app.services.supabase_client import get_service_client

bp = Blueprint("orders", __name__)


def _fetch_user_order(svc, order_id: str, user):
    """Helper: load an order ensuring it belongs to the current user (or admin)."""
    try:
        order = (
            svc.table("orders")
            .select("*")
            .eq("id", order_id)
            .single()
            .execute()
        ).data
    except Exception:
        return None
    if not order:
        return None
    if order["user_id"] != user["id"] and user.get("role") != "admin":
        return None
    return order


@bp.route("/")
@login_required
def my_orders():
    user = current_user()
    svc = get_service_client()
    orders = []
    if svc:
        try:
            resp = (
                svc.table("orders")
                .select("id, status, total, created_at, payment_method")
                .eq("user_id", user["id"])
                .order("created_at", desc=True)
                .execute()
            )
            orders = resp.data or []
        except Exception:
            orders = []
    return render_template("orders/list.html", orders=orders)


@bp.route("/<order_id>")
@login_required
def track(order_id: str):
    user = current_user()
    svc = get_service_client()
    if not svc:
        abort(503)

    order = _fetch_user_order(svc, order_id, user)
    if not order:
        abort(404)

    try:
        items_resp = (
            svc.table("order_items")
            .select("*")
            .eq("order_id", order_id)
            .execute()
        )
        items = items_resp.data or []
    except Exception:
        items = []

    review = None
    try:
        rev_rows = (
            svc.table("order_reviews")
            .select("*")
            .eq("order_id", order_id)
            .limit(1)
            .execute()
        ).data or []
        review = rev_rows[0] if rev_rows else None
    except Exception:
        review = None

    return render_template(
        "orders/track.html",
        order=order,
        items=items,
        review=review,
    )


@bp.route("/<order_id>/cancel", methods=["POST"])
@login_required
@require_same_origin
def cancel(order_id: str):
    """Customer can cancel their order while it's still pending."""
    user = current_user()
    svc = get_service_client()
    if not svc:
        abort(503)

    order = _fetch_user_order(svc, order_id, user)
    if not order:
        abort(404)

    if order["status"] != "pending":
        flash("Sorry, this order can't be cancelled anymore — we've already started crafting.", "error")
        return redirect(url_for("orders.track", order_id=order_id))

    try:
        svc.table("orders").update({"status": "cancelled"}).eq("id", order_id).execute()
        flash("Your order was cancelled. We'll see you again soon! 🌸", "success")
    except Exception:
        flash("Could not cancel the order. Please try again.", "error")

    return redirect(url_for("orders.track", order_id=order_id))


@bp.route("/<order_id>/reorder", methods=["POST"])
@login_required
@require_same_origin
def reorder(order_id: str):
    """Return the list of products from a past order so the JS cart can pre-fill."""
    user = current_user()
    svc = get_service_client()
    if not svc:
        return jsonify({"ok": False, "error": "Server unavailable."}), 503

    order = _fetch_user_order(svc, order_id, user)
    if not order:
        return jsonify({"ok": False, "error": "Order not found."}), 404

    try:
        items = (
            svc.table("order_items")
            .select("product_id, name, unit_price, quantity, customization")
            .eq("order_id", order_id)
            .execute()
        ).data or []
    except Exception:
        return jsonify({"ok": False, "error": "Could not load items."}), 500

    # Filter to still-active products
    pids = [it["product_id"] for it in items if it.get("product_id")]
    active = set()
    if pids:
        try:
            prods = (
                svc.table("products")
                .select("id, is_active, stock")
                .in_("id", pids)
                .execute()
            ).data or []
            active = {p["id"] for p in prods if p.get("is_active")}
        except Exception:
            pass

    cart_payload = [
        {
            "product_id": it["product_id"],
            "name": it.get("name"),
            "price": float(it.get("unit_price") or 0),
            "quantity": int(it.get("quantity") or 1),
            "customization": it.get("customization") or "",
        }
        for it in items
        if it.get("product_id") in active
    ]

    if not cart_payload:
        return jsonify({"ok": False, "error": "None of these items are still available."}), 400

    return jsonify({"ok": True, "items": cart_payload})


@bp.route("/<order_id>/review", methods=["POST"])
@login_required
@require_same_origin
def submit_review(order_id: str):
    """Buyer leaves a rating + comment for a delivered order."""
    user = current_user()
    svc = get_service_client()
    if not svc:
        abort(503)

    order = _fetch_user_order(svc, order_id, user)
    if not order:
        abort(404)

    if order["status"] != "delivered":
        flash("You can leave a review once your order is delivered. 💌", "error")
        return redirect(url_for("orders.track", order_id=order_id))

    try:
        rating = int(request.form.get("rating") or 0)
    except (TypeError, ValueError):
        rating = 0
    rating = max(1, min(5, rating))
    comment = (request.form.get("comment") or "").strip()[:1000]

    try:
        svc.table("order_reviews").upsert(
            {
                "order_id": order_id,
                "user_id": user["id"],
                "rating": rating,
                "comment": comment,
            },
            on_conflict="order_id",
        ).execute()
        flash("Thank you for the review! 🌸", "success")
    except Exception:
        flash("Could not save the review. Please try again.", "error")

    return redirect(url_for("orders.track", order_id=order_id))
