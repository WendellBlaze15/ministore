"""Customer order routes."""
from flask import Blueprint, render_template, abort

from app.utils.auth import login_required, current_user
from app.services.supabase_client import get_service_client

bp = Blueprint("orders", __name__)


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

    try:
        order_resp = (
            svc.table("orders")
            .select("*")
            .eq("id", order_id)
            .single()
            .execute()
        )
        order = order_resp.data
    except Exception:
        order = None

    if not order:
        abort(404)
    if order["user_id"] != user["id"] and user.get("role") != "admin":
        abort(403)

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

    return render_template("orders/track.html", order=order, items=items)
