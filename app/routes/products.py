"""Shop and product detail routes."""
from __future__ import annotations

from flask import Blueprint, render_template, request, abort

from app.services.supabase_client import get_anon_client

bp = Blueprint("products", __name__)


CATEGORIES = [
    ("all", "All"),
    ("bookmarks", "Bookmarks"),
    ("keychains", "Keychains"),
    ("polaroids", "Polaroid Prints"),
    ("crafts", "Crafts"),
]


@bp.route("/")
def shop():
    q = (request.args.get("q") or "").strip()
    category = (request.args.get("category") or "all").strip()
    sort = (request.args.get("sort") or "new").strip()

    products = []
    client = get_anon_client()
    if client:
        try:
            query = (
                client.table("products")
                .select("id, name, slug, price, category, cover_image, stock, is_featured, created_at")
                .eq("is_active", True)
            )
            if category and category != "all":
                query = query.eq("category", category)
            if q:
                query = query.ilike("name", f"%{q}%")

            if sort == "price_asc":
                query = query.order("price", desc=False)
            elif sort == "price_desc":
                query = query.order("price", desc=True)
            else:
                query = query.order("created_at", desc=True)

            resp = query.limit(60).execute()
            products = resp.data or []
        except Exception:
            products = []

    return render_template(
        "shop.html",
        products=products,
        categories=CATEGORIES,
        active_category=category,
        q=q,
        sort=sort,
    )


@bp.route("/product/<slug>")
def detail(slug: str):
    client = get_anon_client()
    if not client:
        abort(503)

    try:
        resp = (
            client.table("products")
            .select("*")
            .eq("slug", slug)
            .eq("is_active", True)
            .single()
            .execute()
        )
        product = resp.data
    except Exception:
        product = None

    if not product:
        abort(404)

    images = []
    try:
        images_resp = (
            client.table("product_images")
            .select("url, position")
            .eq("product_id", product["id"])
            .order("position", desc=False)
            .execute()
        )
        images = images_resp.data or []
    except Exception:
        images = []

    if not images and product.get("cover_image"):
        images = [{"url": product["cover_image"], "position": 0}]

    related = []
    try:
        rel_resp = (
            client.table("products")
            .select("id, name, slug, price, cover_image")
            .eq("is_active", True)
            .eq("category", product["category"])
            .neq("id", product["id"])
            .limit(4)
            .execute()
        )
        related = rel_resp.data or []
    except Exception:
        related = []

    return render_template("product_detail.html", product=product, images=images, related=related)
