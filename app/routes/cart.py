"""Cart routes.

The cart is intentionally simple:
* For guests, items live in localStorage (managed by ``static/js/cart.js``).
* For signed-in users we *also* mirror the cart to the ``carts`` /
  ``cart_items`` tables so it persists across devices.

The Flask side mostly renders the cart and checkout pages; the JS layer is
responsible for keeping the cart up to date.
"""
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash

from app.utils.auth import login_required, current_user
from app.utils.security import require_same_origin
from app.services.supabase_client import get_service_client, get_anon_client

bp = Blueprint("cart", __name__)


@bp.route("/")
def view():
    return render_template("cart.html")


@bp.route("/checkout")
@login_required
def checkout():
    user = current_user()
    prefill = {"full_name": user.get("name") or "", "contact_number": "", "address": ""}
    svc = get_service_client()
    if svc:
        try:
            rows = (
                svc.table("profiles")
                .select("full_name, contact_number, address")
                .eq("id", user["id"])
                .limit(1)
                .execute()
            ).data or []
            if rows:
                p = rows[0]
                prefill["full_name"] = p.get("full_name") or prefill["full_name"]
                prefill["contact_number"] = p.get("contact_number") or ""
                prefill["address"] = p.get("address") or ""
        except Exception:
            pass
    return render_template("checkout.html", user=user, prefill=prefill)


@bp.route("/checkout", methods=["POST"])
@login_required
@require_same_origin
def place_order():
    """Create an order from the posted cart payload."""
    user = current_user()
    payload = request.get_json(silent=True) or {}

    items = payload.get("items") or []
    if not items:
        return jsonify({"ok": False, "error": "Your cart is empty."}), 400

    required = ["full_name", "contact_number", "address", "payment_method"]
    for key in required:
        if not (payload.get(key) or "").strip():
            return jsonify({"ok": False, "error": f"Missing field: {key}"}), 400

    svc = get_service_client()
    if not svc:
        return jsonify({"ok": False, "error": "Server not configured."}), 500

    product_ids = [it.get("product_id") for it in items if it.get("product_id")]
    prod_map = {}
    if product_ids:
        try:
            prods = (
                svc.table("products")
                .select("id, name, price, stock, is_active")
                .in_("id", product_ids)
                .execute()
            ).data or []
            prod_map = {p["id"]: p for p in prods}
        except Exception as exc:
            return jsonify({"ok": False, "error": f"Could not load products: {exc}"}), 500

    subtotal = 0.0
    clean_items = []
    for it in items:
        pid = it.get("product_id")
        qty = int(it.get("quantity") or 1)
        prod = prod_map.get(pid)
        if not prod or not prod.get("is_active"):
            return jsonify({"ok": False, "error": "One of the items is no longer available."}), 400
        if qty < 1:
            qty = 1
        if prod.get("stock") is not None and qty > prod["stock"]:
            return jsonify({"ok": False, "error": f"Only {prod['stock']} left for {prod['name']}."}), 400
        unit = float(prod["price"])
        subtotal += unit * qty
        clean_items.append(
            {
                "product_id": pid,
                "name": prod["name"],
                "unit_price": unit,
                "quantity": qty,
                "customization": (it.get("customization") or "").strip()[:500],
            }
        )

    shipping_fee = 0.0 if subtotal >= 1500 else 80.0
    total = subtotal + shipping_fee

    try:
        order_resp = svc.table("orders").insert(
            {
                "user_id": user["id"],
                "full_name": payload["full_name"].strip()[:120],
                "contact_number": payload["contact_number"].strip()[:32],
                "address": payload["address"].strip()[:500],
                "notes": (payload.get("notes") or "").strip()[:500],
                "payment_method": payload["payment_method"],
                "subtotal": subtotal,
                "shipping_fee": shipping_fee,
                "total": total,
                "status": "pending",
            }
        ).execute()
        order = (order_resp.data or [None])[0]
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Could not create order: {exc}"}), 500

    if not order:
        return jsonify({"ok": False, "error": "Order creation failed."}), 500

    try:
        svc.table("order_items").insert(
            [{**it, "order_id": order["id"]} for it in clean_items]
        ).execute()
    except Exception as exc:
        return jsonify({"ok": False, "error": f"Could not save items: {exc}"}), 500

    return jsonify({"ok": True, "order_id": order["id"]})
