"""Admin dashboard, product/order/chat management."""
from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app

from app.utils.auth import admin_required, current_user
from app.utils.helpers import slugify, allowed_image, safe_filename
from app.utils.security import require_same_origin
from app.services.supabase_client import get_service_client

bp = Blueprint("admin", __name__)


ORDER_STATUSES = ["pending", "preparing", "shipped", "delivered", "cancelled"]
CATEGORIES = ["bookmarks", "keychains", "polaroids", "crafts"]


# ---------------- Dashboard ----------------

@bp.route("/")
@admin_required
def dashboard():
    svc = get_service_client()
    metrics = {
        "total_orders": 0,
        "pending_orders": 0,
        "revenue_30d": 0.0,
        "revenue_all": 0.0,
        "active_products": 0,
        "low_stock": 0,
        "customers": 0,
        "open_chats": 0,
    }
    recent_orders = []
    revenue_series = []

    if svc:
        try:
            orders = (
                svc.table("orders")
                .select("id, status, total, created_at, full_name")
                .order("created_at", desc=True)
                .limit(500)
                .execute()
            ).data or []
        except Exception:
            orders = []

        metrics["total_orders"] = len(orders)
        metrics["pending_orders"] = sum(1 for o in orders if o["status"] == "pending")
        metrics["revenue_all"] = sum(float(o["total"]) for o in orders if o["status"] != "cancelled")
        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        metrics["revenue_30d"] = sum(
            float(o["total"])
            for o in orders
            if o["status"] != "cancelled"
            and _to_dt(o["created_at"]) and _to_dt(o["created_at"]) >= cutoff
        )
        recent_orders = orders[:8]

        revenue_series = _build_revenue_series(orders, days=14)

        try:
            products = (
                svc.table("products").select("id, stock, is_active").execute()
            ).data or []
            metrics["active_products"] = sum(1 for p in products if p.get("is_active"))
            metrics["low_stock"] = sum(1 for p in products if (p.get("stock") or 0) <= 3)
        except Exception:
            pass

        try:
            customers = (
                svc.table("profiles").select("id", count="exact").eq("role", "customer").execute()
            )
            metrics["customers"] = customers.count or 0
        except Exception:
            pass

        try:
            chats = (svc.table("chats").select("id", count="exact").execute())
            metrics["open_chats"] = chats.count or 0
        except Exception:
            pass

    return render_template(
        "admin/dashboard.html",
        metrics=metrics,
        recent_orders=recent_orders,
        revenue_series=revenue_series,
    )


def _to_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _build_revenue_series(orders, days=14):
    today = datetime.now(timezone.utc).date()
    buckets = {(today - timedelta(days=i)): 0.0 for i in range(days)}
    for o in orders:
        if o["status"] == "cancelled":
            continue
        dt = _to_dt(o["created_at"])
        if not dt:
            continue
        day = dt.date()
        if day in buckets:
            buckets[day] += float(o["total"])
    ordered = sorted(buckets.items())
    return [{"day": d.strftime("%b %d"), "value": round(v, 2)} for d, v in ordered]


# ---------------- Products ----------------

@bp.route("/products")
@admin_required
def products():
    svc = get_service_client()
    items = []
    if svc:
        try:
            items = (
                svc.table("products")
                .select("id, name, slug, price, stock, category, cover_image, is_active, is_featured, created_at")
                .order("created_at", desc=True)
                .execute()
            ).data or []
        except Exception:
            items = []
    return render_template("admin/products.html", products=items, categories=CATEGORIES)


@bp.route("/products/new", methods=["GET", "POST"])
@admin_required
@require_same_origin
def product_new():
    if request.method == "POST":
        return _save_product(None)
    return render_template("admin/product_form.html", product=None, categories=CATEGORIES)


@bp.route("/products/<product_id>/edit", methods=["GET", "POST"])
@admin_required
@require_same_origin
def product_edit(product_id):
    svc = get_service_client()
    if request.method == "POST":
        return _save_product(product_id)

    product = None
    if svc:
        try:
            product = (
                svc.table("products").select("*").eq("id", product_id).single().execute()
            ).data
        except Exception:
            product = None
    if not product:
        flash("Product not found.", "error")
        return redirect(url_for("admin.products"))
    return render_template("admin/product_form.html", product=product, categories=CATEGORIES)


@bp.route("/products/<product_id>/delete", methods=["POST"])
@admin_required
@require_same_origin
def product_delete(product_id):
    svc = get_service_client()
    if svc:
        try:
            svc.table("products").delete().eq("id", product_id).execute()
            flash("Product deleted.", "success")
        except Exception as exc:
            flash(f"Could not delete: {exc}", "error")
    return redirect(url_for("admin.products"))


def _ensure_bucket(svc, bucket: str) -> None:
    """Create the product images bucket on first use (idempotent)."""
    try:
        buckets = svc.storage.list_buckets() or []
        names = {getattr(b, "name", None) or (b.get("name") if isinstance(b, dict) else None) for b in buckets}
        if bucket in names:
            return
        svc.storage.create_bucket(bucket, options={"public": True})
    except Exception:  # pragma: no cover — best effort
        pass


def _save_product(product_id):
    svc = get_service_client()
    if not svc:
        flash("Server not configured.", "error")
        return redirect(url_for("admin.products"))

    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Product name is required.", "error")
        return redirect(request.url)

    price = float(request.form.get("price") or 0)
    stock = int(request.form.get("stock") or 0)
    description = (request.form.get("description") or "").strip()
    category = (request.form.get("category") or "crafts").strip().lower()
    customizable = bool(request.form.get("customizable"))
    is_active = bool(request.form.get("is_active"))
    is_featured = bool(request.form.get("is_featured"))
    slug = slugify(request.form.get("slug") or name)

    cover_url = request.form.get("cover_image") or None

    file = request.files.get("image_file")
    if file and file.filename:
        if not allowed_image(file.filename):
            flash("Unsupported image type.", "error")
            return redirect(request.url)
        bucket = current_app.config.get("SUPABASE_STORAGE_BUCKET", "product-images")
        path = safe_filename(file.filename)
        try:
            _ensure_bucket(svc, bucket)
            data_bytes = file.read()
            svc.storage.from_(bucket).upload(
                path=path,
                file=data_bytes,
                file_options={"content-type": file.mimetype or "image/jpeg"},
            )
            cover_url = svc.storage.from_(bucket).get_public_url(path)
        except Exception as exc:
            flash(f"Image upload failed: {exc}", "error")
            return redirect(request.url)

    payload = {
        "name": name[:140],
        "slug": slug,
        "description": description[:2000],
        "price": price,
        "stock": stock,
        "category": category,
        "customizable": customizable,
        "is_active": is_active,
        "is_featured": is_featured,
    }
    if cover_url:
        payload["cover_image"] = cover_url

    try:
        if product_id:
            svc.table("products").update(payload).eq("id", product_id).execute()
            flash("Product updated.", "success")
        else:
            svc.table("products").insert(payload).execute()
            flash("Product added!", "success")
    except Exception as exc:
        flash(f"Could not save: {exc}", "error")
        return redirect(request.url)

    return redirect(url_for("admin.products"))


# ---------------- Orders ----------------

@bp.route("/orders")
@admin_required
def orders():
    status = request.args.get("status") or "all"
    svc = get_service_client()
    items = []
    if svc:
        try:
            query = (
                svc.table("orders")
                .select("id, full_name, contact_number, status, total, created_at, payment_method, user_id")
                .order("created_at", desc=True)
            )
            if status and status != "all":
                query = query.eq("status", status)
            items = (query.limit(200).execute()).data or []
        except Exception:
            items = []
    return render_template("admin/orders.html", orders=items, status=status, statuses=ORDER_STATUSES)


@bp.route("/orders/<order_id>")
@admin_required
def order_detail(order_id):
    svc = get_service_client()
    order = None
    items = []
    if svc:
        try:
            order = (svc.table("orders").select("*").eq("id", order_id).single().execute()).data
            items = (svc.table("order_items").select("*").eq("order_id", order_id).execute()).data or []
        except Exception:
            pass
    if not order:
        flash("Order not found.", "error")
        return redirect(url_for("admin.orders"))
    return render_template("admin/order_detail.html", order=order, items=items, statuses=ORDER_STATUSES)


@bp.route("/orders/<order_id>/status", methods=["POST"])
@admin_required
@require_same_origin
def order_set_status(order_id):
    status = (request.form.get("status") or "").strip()
    if status not in ORDER_STATUSES:
        flash("Invalid status.", "error")
        return redirect(url_for("admin.order_detail", order_id=order_id))
    svc = get_service_client()
    if svc:
        try:
            svc.table("orders").update({"status": status}).eq("id", order_id).execute()
            flash(f"Status updated to {status}.", "success")
        except Exception as exc:
            flash(f"Could not update: {exc}", "error")
    return redirect(url_for("admin.order_detail", order_id=order_id))


# ---------------- Customers ----------------

@bp.route("/customers")
@admin_required
def customers():
    svc = get_service_client()
    rows = []
    if svc:
        try:
            rows = (
                svc.table("profiles")
                .select("id, email, full_name, role, created_at")
                .order("created_at", desc=True)
                .execute()
            ).data or []
        except Exception:
            rows = []
    return render_template("admin/customers.html", customers=rows)


# ---------------- Chats ----------------

@bp.route("/chats")
@bp.route("/messages")
@admin_required
def messages():
    svc = get_service_client()
    rows = []
    if svc:
        try:
            rows = (
                svc.table("chats")
                .select("id, user_id, created_at")
                .order("created_at", desc=True)
                .execute()
            ).data or []
            user_ids = [r["user_id"] for r in rows if r.get("user_id")]
            profiles_by_id = {}
            if user_ids:
                profs = (
                    svc.table("profiles")
                    .select("id, full_name, email")
                    .in_("id", user_ids)
                    .execute()
                ).data or []
                profiles_by_id = {p["id"]: p for p in profs}

            # Attach last message snippet + unread count for each chat.
            try:
                msgs = (
                    svc.table("messages")
                    .select("chat_id, body, sender_role, seen, created_at")
                    .order("created_at", desc=True)
                    .limit(1000)
                    .execute()
                ).data or []
                last_by_chat: dict[str, dict] = {}
                unread_by_chat: dict[str, int] = {}
                for m in msgs:
                    cid = m.get("chat_id")
                    if not cid: continue
                    if cid not in last_by_chat:
                        last_by_chat[cid] = m
                    if m.get("sender_role") == "customer" and not m.get("seen"):
                        unread_by_chat[cid] = unread_by_chat.get(cid, 0) + 1
                for r in rows:
                    r["profiles"] = profiles_by_id.get(r.get("user_id")) or {}
                    r["last_message"] = last_by_chat.get(r["id"]) or {}
                    r["unread"] = unread_by_chat.get(r["id"], 0)
            except Exception:
                for r in rows:
                    r["profiles"] = profiles_by_id.get(r.get("user_id")) or {}
                    r["last_message"] = {}
                    r["unread"] = 0
        except Exception:
            rows = []
    return render_template("admin/messages.html", chats=rows)


# ---------------- Reports ----------------

@bp.route("/reports")
@admin_required
def reports():
    svc = get_service_client()
    metrics: dict = {"total_revenue": 0.0, "total_orders": 0, "best_sellers": [], "by_category": {}, "by_status": {}, "by_month": []}
    if svc:
        try:
            orders = (
                svc.table("orders").select("id, total, status, created_at").execute()
            ).data or []
            metrics["total_orders"] = len(orders)
            metrics["total_revenue"] = sum(float(o["total"]) for o in orders if o["status"] != "cancelled")
            by_status: dict[str, int] = {}
            by_month: dict[str, float] = {}
            for o in orders:
                by_status[o["status"]] = by_status.get(o["status"], 0) + 1
                dt = _to_dt(o["created_at"])
                if dt and o["status"] != "cancelled":
                    key = dt.strftime("%Y-%m")
                    by_month[key] = by_month.get(key, 0) + float(o["total"])
            metrics["by_status"] = by_status
            metrics["by_month"] = [{"month": k, "value": round(v, 2)} for k, v in sorted(by_month.items())[-12:]]

            items = (
                svc.table("order_items").select("product_id, name, quantity, unit_price").execute()
            ).data or []
            ranking: dict[str, dict] = {}
            for it in items:
                key = it.get("product_id") or it.get("name", "Unknown")
                row = ranking.setdefault(key, {"name": it.get("name", "Unknown"), "qty": 0, "revenue": 0.0})
                qty = int(it.get("quantity") or 0)
                row["qty"] += qty
                row["revenue"] += qty * float(it.get("unit_price") or 0)
            best = sorted(ranking.values(), key=lambda r: r["qty"], reverse=True)[:10]
            metrics["best_sellers"] = best

            prods = (svc.table("products").select("category, stock").execute()).data or []
            by_cat: dict[str, int] = {}
            for p in prods:
                by_cat[p.get("category", "other")] = by_cat.get(p.get("category", "other"), 0) + 1
            metrics["by_category"] = by_cat
        except Exception as exc:
            current_app.logger.warning("reports failed: %s", exc)

    return render_template("admin/reports.html", m=metrics)


# ---------------- Settings ----------------

@bp.route("/settings", methods=["GET", "POST"])
@admin_required
@require_same_origin
def settings():
    user = current_user()
    svc = get_service_client()
    profile = {}
    if svc and user:
        try:
            profile = (svc.table("profiles").select("*").eq("id", user["id"]).single().execute()).data or {}
        except Exception:
            pass

    if request.method == "POST":
        full_name = (request.form.get("full_name") or "").strip()[:120]
        contact = (request.form.get("contact_number") or "").strip()[:32]
        if svc and user and (full_name or contact):
            patch = {}
            if full_name: patch["full_name"] = full_name
            if contact:   patch["contact_number"] = contact
            try:
                svc.table("profiles").update(patch).eq("id", user["id"]).execute()
                flash("Settings saved.", "success")
            except Exception as exc:
                flash(f"Could not save: {exc}", "error")
        return redirect(url_for("admin.settings"))

    return render_template("admin/settings.html", profile=profile)
