"""Admin dashboard, product/order/chat management."""
from __future__ import annotations

import io
import os
from datetime import datetime, timedelta, timezone

from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app, session

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


@bp.route("/api/analytics")
@admin_required
def analytics_json():
    """Real-time analytics feed for Chart.js dashboards. Polled by the
    admin overview + reports pages every 30 seconds."""
    svc = get_service_client()
    if not svc:
        return jsonify({"ok": False}), 500

    try:
        orders = (
            svc.table("orders")
            .select("id, status, total, created_at")
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        ).data or []
    except Exception:
        orders = []

    try:
        order_items = (
            svc.table("order_items")
            .select("name, quantity, unit_price")
            .execute()
        ).data or []
    except Exception:
        order_items = []

    try:
        products = (svc.table("products").select("category").execute()).data or []
    except Exception:
        products = []

    try:
        customers = (svc.table("profiles").select("id", count="exact").eq("role", "customer").execute()).count or 0
    except Exception:
        customers = 0

    # Revenue line — last 14 days
    revenue = _build_revenue_series(orders, days=14)

    # Status donut
    status_count: dict[str, int] = {}
    for o in orders:
        status_count[o["status"]] = status_count.get(o["status"], 0) + 1

    # Category pie
    by_cat: dict[str, int] = {}
    for p in products:
        c = (p.get("category") or "other").lower()
        by_cat[c] = by_cat.get(c, 0) + 1

    # Top sellers bar
    rank: dict[str, dict] = {}
    for it in order_items:
        name = it.get("name", "?")
        row = rank.setdefault(name, {"name": name, "qty": 0, "rev": 0.0})
        q = int(it.get("quantity") or 0)
        row["qty"] += q
        row["rev"] += q * float(it.get("unit_price") or 0)
    top = sorted(rank.values(), key=lambda r: r["qty"], reverse=True)[:6]

    return jsonify({
        "ok": True,
        "ts": datetime.now(timezone.utc).isoformat(),
        "revenue": revenue,
        "status": status_count,
        "categories": by_cat,
        "top_sellers": top,
        "totals": {
            "orders": len(orders),
            "customers": customers,
            "revenue_all": round(sum(float(o["total"]) for o in orders if o["status"] != "cancelled"), 2),
            "revenue_30d": round(sum(
                float(o["total"]) for o in orders
                if o["status"] != "cancelled" and _to_dt(o["created_at"])
                and _to_dt(o["created_at"]) >= datetime.now(timezone.utc) - timedelta(days=30)
            ), 2),
        },
    })


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


def _iso(value):
    """Normalize datetimes / strings to a stable ISO string."""
    if not value:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


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


# ---------------- Users management ----------------

@bp.route("/users")
@admin_required
def users():
    """Full user management — every auth user with role, verified state,
    last sign-in, order count, and per-row delete/promote actions."""
    svc = get_service_client()
    rows: list[dict] = []
    if svc:
        try:
            auth_users = svc.auth.admin.list_users() or []
        except Exception as exc:
            current_app.logger.warning("admin list_users failed: %s", exc)
            auth_users = []

        try:
            profiles = (
                svc.table("profiles").select("id, email, full_name, role, created_at, contact_number, avatar_url").execute()
            ).data or []
        except Exception:
            # avatar_url column may not exist yet — retry without it
            try:
                profiles = (
                    svc.table("profiles").select("id, email, full_name, role, created_at, contact_number").execute()
                ).data or []
            except Exception:
                profiles = []
        profile_by_id = {p["id"]: p for p in profiles}

        try:
            orders = (
                svc.table("orders").select("user_id, total, status").execute()
            ).data or []
        except Exception:
            orders = []
        order_count: dict[str, int] = {}
        order_spend: dict[str, float] = {}
        for o in orders:
            uid = o.get("user_id")
            if not uid:
                continue
            order_count[uid] = order_count.get(uid, 0) + 1
            if o.get("status") != "cancelled":
                order_spend[uid] = order_spend.get(uid, 0.0) + float(o.get("total") or 0)

        for u in auth_users:
            uid = u.id
            p = profile_by_id.get(uid, {})
            rows.append({
                "id": uid,
                "email": u.email,
                "full_name": p.get("full_name") or (getattr(u, "user_metadata", {}) or {}).get("full_name") or "",
                "role": p.get("role") or "customer",
                "contact_number": p.get("contact_number") or "",
                "avatar_url": p.get("avatar_url") or "",
                "email_confirmed": bool(getattr(u, "email_confirmed_at", None)),
                "created_at": _iso(getattr(u, "created_at", None) or p.get("created_at")),
                "last_sign_in_at": _iso(getattr(u, "last_sign_in_at", None)),
                "orders": order_count.get(uid, 0),
                "spend": round(order_spend.get(uid, 0.0), 2),
            })

        # newest first
        rows.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    summary = {
        "total": len(rows),
        "admins": sum(1 for r in rows if r["role"] == "admin"),
        "customers": sum(1 for r in rows if r["role"] != "admin"),
        "unverified": sum(1 for r in rows if not r["email_confirmed"]),
    }
    return render_template("admin/users.html", users=rows, summary=summary)


@bp.route("/users/<user_id>/delete", methods=["POST"])
@admin_required
@require_same_origin
def user_delete(user_id):
    me = current_user() or {}
    if me.get("id") == user_id:
        flash("You can't delete your own admin account from here.", "error")
        return redirect(url_for("admin.users"))

    svc = get_service_client()
    if not svc:
        flash("Server not configured.", "error")
        return redirect(url_for("admin.users"))

    # Capture the email BEFORE we delete so we can ban it from re-registering.
    deleted_email = ""
    try:
        existing = (svc.table("profiles").select("email").eq("id", user_id).single().execute()).data
        if existing and existing.get("email"):
            deleted_email = existing["email"].lower().strip()
    except Exception:
        pass
    if not deleted_email:
        try:
            raw = svc.auth.admin.get_user_by_id(user_id)
            u = getattr(raw, "user", None) or raw
            deleted_email = (getattr(u, "email", "") or "").lower().strip()
        except Exception:
            pass

    try:
        # Best-effort cascade — most of these have on-delete-cascade in the
        # schema but we delete explicitly so partial RLS configurations
        # can't block the auth.admin.delete_user step below.
        for tbl, col in (
            ("wishlists",  "user_id"),
            ("messages",   "sender_id"),
            ("chats",      "user_id"),
            ("product_reviews", "user_id"),
            ("order_reviews",   "user_id"),
            ("profiles",   "id"),
        ):
            try:
                svc.table(tbl).delete().eq(col, user_id).execute()
            except Exception as exc:
                current_app.logger.info("delete cleanup %s skipped: %s", tbl, exc)

        svc.auth.admin.delete_user(user_id, should_soft_delete=False)

        # Verify the auth user is really gone so we don't leave the admin
        # thinking the delete succeeded when it didn't.
        still_exists = False
        try:
            res = svc.auth.admin.get_user_by_id(user_id)
            still_exists = res is not None and getattr(res, "user", None) is not None
        except Exception:
            still_exists = False
        if still_exists:
            flash("Supabase reported success but the user is still listed — please refresh.", "error")
            return redirect(url_for("admin.users"))

        # Ban the email so the buyer can't simply re-register with the same
        # address and "come back". Admins can lift this from the Users page.
        if deleted_email:
            try:
                svc.table("banned_emails").upsert(
                    {"email": deleted_email,
                     "reason": "removed by admin",
                     "banned_by": me.get("id")},
                    on_conflict="email",
                ).execute()
            except Exception as exc:
                current_app.logger.info("banned_emails write skipped: %s", exc)

        flash(f"User deleted{' and email blocked from re-registration' if deleted_email else ''}.", "success")
    except Exception as exc:
        current_app.logger.warning("admin delete user failed: %s", exc)
        flash(f"Could not delete user: {exc}", "error")
    return redirect(url_for("admin.users"))


@bp.route("/users/banned", methods=["GET"])
@admin_required
def banned_emails():
    """List of emails blocked from re-registering, with un-ban form."""
    svc = get_service_client()
    rows = []
    if svc:
        try:
            rows = (
                svc.table("banned_emails").select("email, reason, banned_at")
                .order("banned_at", desc=True).execute()
            ).data or []
        except Exception:
            rows = []
    return render_template("admin/banned_emails.html", banned=rows)


@bp.route("/users/banned/<path:email>/unban", methods=["POST"])
@admin_required
@require_same_origin
def unban_email(email: str):
    svc = get_service_client()
    if svc:
        try:
            svc.table("banned_emails").delete().eq("email", email.lower().strip()).execute()
            flash(f"{email} can register again.", "success")
        except Exception as exc:
            flash(f"Could not unban: {exc}", "error")
    return redirect(url_for("admin.banned_emails"))


@bp.route("/users/<user_id>/role", methods=["POST"])
@admin_required
@require_same_origin
def user_set_role(user_id):
    me = current_user() or {}
    if me.get("id") == user_id:
        flash("You can't change your own role here.", "error")
        return redirect(url_for("admin.users"))

    new_role = (request.form.get("role") or "customer").strip().lower()
    if new_role not in ("admin", "customer"):
        flash("Invalid role.", "error")
        return redirect(url_for("admin.users"))

    svc = get_service_client()
    if not svc:
        flash("Server not configured.", "error")
        return redirect(url_for("admin.users"))

    try:
        svc.table("profiles").update({"role": new_role}).eq("id", user_id).execute()
        # Mirror the role in user_metadata so future JWTs carry it.
        try:
            svc.auth.admin.update_user_by_id(user_id, {"user_metadata": {"role": new_role}})
        except Exception:
            pass
        flash(f"Role updated to {new_role}.", "success")
    except Exception as exc:
        flash(f"Could not update role: {exc}", "error")
    return redirect(url_for("admin.users"))


@bp.route("/users/<user_id>/verify", methods=["POST"])
@admin_required
@require_same_origin
def user_force_verify(user_id):
    """Force-mark an account as email-verified — useful when a buyer can't
    receive the OTP for any reason."""
    svc = get_service_client()
    if not svc:
        flash("Server not configured.", "error")
        return redirect(url_for("admin.users"))
    try:
        svc.auth.admin.update_user_by_id(user_id, {"email_confirm": True})
        flash("Email manually marked as verified.", "success")
    except Exception as exc:
        flash(f"Could not verify: {exc}", "error")
    return redirect(url_for("admin.users"))


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
        patch = {}
        if full_name: patch["full_name"] = full_name
        if contact:   patch["contact_number"] = contact

        # Avatar upload (same bucket as product images).
        avatar_file = request.files.get("avatar")
        if avatar_file and avatar_file.filename:
            from app.utils.helpers import allowed_image, safe_filename
            if not allowed_image(avatar_file.filename):
                flash("Avatar must be JPG/PNG/WebP.", "error")
                return redirect(url_for("admin.settings"))
            bucket = current_app.config.get("SUPABASE_STORAGE_BUCKET", "product-images")
            path = f"avatars/{user['id']}/{safe_filename(avatar_file.filename)}"
            try:
                _ensure_bucket(svc, bucket)
                svc.storage.from_(bucket).upload(
                    path=path, file=avatar_file.read(),
                    file_options={"content-type": avatar_file.mimetype or "image/jpeg"},
                )
                patch["avatar_url"] = svc.storage.from_(bucket).get_public_url(path)
            except Exception as exc:
                flash(f"Avatar upload failed: {exc}", "error")

        if svc and user and patch:
            try:
                svc.table("profiles").update(patch).eq("id", user["id"]).execute()
                flash("Settings saved.", "success")
                # Mirror identity into session.
                u = dict(session.get("user") or {})
                if patch.get("full_name"):  u["name"] = patch["full_name"]
                if patch.get("avatar_url"): u["avatar_url"] = patch["avatar_url"]
                session["user"] = u
            except Exception as exc:
                # Re-try without avatar_url if column missing.
                if "avatar_url" in patch and "avatar_url" in str(exc).lower():
                    patch.pop("avatar_url", None)
                    try:
                        if patch:
                            svc.table("profiles").update(patch).eq("id", user["id"]).execute()
                        flash("Saved, but avatars aren't enabled yet. Run migration 008.", "info")
                    except Exception as exc2:
                        flash(f"Could not save: {exc2}", "error")
                else:
                    flash(f"Could not save: {exc}", "error")
        return redirect(url_for("admin.settings"))

    return render_template("admin/settings.html", profile=profile)


@bp.route("/reviews")
@admin_required
def reviews():
    """Admin view of every product review with buyer info + photo."""
    svc = get_service_client()
    rows: list[dict] = []
    if svc:
        try:
            rev = (
                svc.table("product_reviews")
                .select("id, product_id, user_id, rating, body, image_url, created_at")
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            ).data or []
            pids = list({r["product_id"] for r in rev if r.get("product_id")})
            uids = list({r["user_id"] for r in rev if r.get("user_id")})

            products = (
                svc.table("products").select("id, name, slug, cover_image")
                .in_("id", pids).execute()
            ).data or [] if pids else []
            profiles = (
                svc.table("profiles").select("id, full_name, email, avatar_url")
                .in_("id", uids).execute()
            ).data or [] if uids else []
            prod_by_id = {p["id"]: p for p in products}
            prof_by_id = {p["id"]: p for p in profiles}

            for r in rev:
                r["product"] = prod_by_id.get(r.get("product_id"), {})
                r["author"] = prof_by_id.get(r.get("user_id"), {})
            rows = rev
        except Exception as exc:
            current_app.logger.info("admin reviews load skipped: %s", exc)

    summary = {
        "total": len(rows),
        "five_star": sum(1 for r in rows if int(r.get("rating") or 0) == 5),
        "with_photos": sum(1 for r in rows if r.get("image_url")),
    }
    if rows:
        avg = sum(int(r.get("rating") or 0) for r in rows) / max(1, len(rows))
    else:
        avg = 0
    summary["average"] = round(avg, 2)
    return render_template("admin/reviews.html", reviews=rows, summary=summary)


@bp.route("/reviews/<review_id>/delete", methods=["POST"])
@admin_required
@require_same_origin
def review_delete(review_id):
    svc = get_service_client()
    if svc:
        try:
            svc.table("product_reviews").delete().eq("id", review_id).execute()
            flash("Review removed.", "success")
        except Exception as exc:
            flash(f"Could not remove review: {exc}", "error")
    return redirect(url_for("admin.reviews"))


@bp.route("/settings/password-otp", methods=["POST"])
@admin_required
@require_same_origin
def settings_password_otp():
    """Send a 6-digit OTP to the admin's email and redirect to the existing
    /auth/reset page where they paste the code and set a new password."""
    from app.services.otp import request_reset_code

    user = current_user() or {}
    email = (user.get("email") or "").lower()
    if not email:
        return redirect(url_for("admin.settings"))

    ok, message = request_reset_code(email)
    if ok:
        flash(message, "success")
        return redirect(url_for("auth.reset", email=email))
    flash(message or "Could not send a reset code right now.", "error")
    return redirect(url_for("admin.settings"))


@bp.route("/users/<user_id>/view")
@admin_required
def user_view(user_id):
    """Full read-only view of a buyer + their orders + chat link. Replaces
    the riskier role-toggle button so admins can't accidentally demote
    themselves or promote a stranger to admin."""
    svc = get_service_client()
    if not svc:
        flash("Server not configured.", "error")
        return redirect(url_for("admin.users"))

    profile = {}
    auth_user = None
    try:
        profile = (svc.table("profiles").select("*").eq("id", user_id).single().execute()).data or {}
    except Exception:
        pass
    try:
        auth_user = svc.auth.admin.get_user_by_id(user_id)
    except Exception:
        auth_user = None

    orders = []
    try:
        orders = (
            svc.table("orders").select("*").eq("user_id", user_id)
            .order("created_at", desc=True).limit(100).execute()
        ).data or []
    except Exception:
        pass

    wishlist_count = 0
    try:
        wishlist_count = (
            svc.table("wishlists").select("id", count="exact").eq("user_id", user_id).execute()
        ).count or 0
    except Exception:
        pass

    chat_id = None
    try:
        rows = (svc.table("chats").select("id").eq("user_id", user_id).limit(1).execute()).data or []
        chat_id = rows[0]["id"] if rows else None
    except Exception:
        pass

    total_spent = sum(float(o.get("total") or 0) for o in orders if o.get("status") != "cancelled")
    raw_user = getattr(auth_user, "user", None) or auth_user
    created_at = _iso(getattr(raw_user, "created_at", None) or profile.get("created_at"))
    last_sign_in = _iso(getattr(raw_user, "last_sign_in_at", None))
    email_confirmed = bool(getattr(raw_user, "email_confirmed_at", None))

    return render_template(
        "admin/user_view.html",
        profile=profile,
        user_id=user_id,
        orders=orders,
        wishlist_count=wishlist_count,
        chat_id=chat_id,
        total_spent=total_spent,
        created_at=created_at,
        last_sign_in=last_sign_in,
        email_confirmed=email_confirmed,
        email=(profile.get("email") or (getattr(raw_user, "email", "") if raw_user else "")),
    )
