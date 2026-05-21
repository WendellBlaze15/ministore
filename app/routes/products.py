"""Shop and product detail routes."""
from __future__ import annotations

from flask import Blueprint, render_template, request, abort, redirect, url_for, flash, current_app, session

from app.services.supabase_client import get_anon_client, get_service_client
from app.utils.auth import login_required, current_user
from app.utils.security import require_same_origin
from app.utils.helpers import allowed_image, safe_filename

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

    # Pull reviews — public, ordered by newest. We join in the reviewer's
    # display name + avatar so we can render the card without an N+1.
    reviews: list[dict] = []
    existing_review = None
    me = current_user()
    try:
        svc = get_service_client() or client
        rev_rows = (
            svc.table("product_reviews")
            .select("id, user_id, rating, body, image_url, created_at")
            .eq("product_id", product["id"])
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        ).data or []

        if rev_rows:
            user_ids = list({r["user_id"] for r in rev_rows if r.get("user_id")})
            profs = (
                svc.table("profiles").select("id, full_name, avatar_url")
                .in_("id", user_ids).execute()
            ).data or [] if user_ids else []
            by_id = {p["id"]: p for p in profs}
            for r in rev_rows:
                p = by_id.get(r.get("user_id"), {})
                r["full_name"] = p.get("full_name") or "Friend"
                r["avatar_url"] = p.get("avatar_url")
                if me and r["user_id"] == me["id"]:
                    existing_review = r
            reviews = rev_rows
    except Exception as exc:
        # Reviews table may not exist yet (migration 009 not applied).
        # Render the page without reviews instead of crashing.
        current_app.logger.info("reviews fetch skipped: %s", exc)

    return render_template(
        "product_detail.html",
        product=product, images=images, related=related,
        reviews=reviews, existing_review=existing_review,
    )


# ---------------- Product reviews ----------------

@bp.route("/product/<product_id>/review", methods=["POST"])
@login_required
@require_same_origin
def submit_review(product_id: str):
    """Buyer-side: post or replace your review for this product. Accepts
    an optional photo via either the gallery picker or the camera capture
    (Chrome on mobile)."""
    user = current_user()
    svc = get_service_client()
    if not svc:
        flash("Server not configured.", "error")
        return redirect(request.referrer or url_for("products.shop"))

    try:
        rating = int(request.form.get("rating") or 0)
    except ValueError:
        rating = 0
    if rating < 1 or rating > 5:
        flash("Please pick a rating from 1 to 5 stars.", "error")
        return redirect(request.referrer or url_for("products.shop"))

    body = (request.form.get("body") or "").strip()[:800]

    # Either input might carry the file — whichever has one wins.
    image_file = request.files.get("image") or request.files.get("image_cam")
    image_url = None
    if image_file and image_file.filename:
        if not allowed_image(image_file.filename):
            flash("Photo must be JPG, PNG or WebP.", "error")
            return redirect(request.referrer or url_for("products.shop"))
        bucket = current_app.config.get("SUPABASE_STORAGE_BUCKET", "product-images")
        path = f"reviews/{product_id}/{safe_filename(image_file.filename)}"
        try:
            try:
                buckets = svc.storage.list_buckets() or []
                names = {getattr(b, "name", None) or (b.get("name") if isinstance(b, dict) else None) for b in buckets}
                if bucket not in names:
                    svc.storage.create_bucket(bucket, options={"public": True})
            except Exception:
                pass
            svc.storage.from_(bucket).upload(
                path=path, file=image_file.read(),
                file_options={"content-type": image_file.mimetype or "image/jpeg"},
            )
            image_url = svc.storage.from_(bucket).get_public_url(path)
        except Exception as exc:
            current_app.logger.warning("review image upload failed: %s", exc)
            flash("Could not upload your photo, but your review was saved.", "info")

    record = {
        "product_id": product_id,
        "user_id": user["id"],
        "rating": rating,
        "body": body,
    }
    if image_url:
        record["image_url"] = image_url

    try:
        # Upsert so re-submitting overwrites the buyer's previous review.
        svc.table("product_reviews").upsert(record, on_conflict="product_id,user_id").execute()
        flash("Thanks for the review! 🌸", "success")
    except Exception as exc:
        current_app.logger.warning("review save failed: %s", exc)
        flash(f"Could not save review: {exc}", "error")

    return redirect(request.referrer or url_for("products.shop"))


@bp.route("/product/<product_id>/review/delete", methods=["POST"])
@login_required
@require_same_origin
def delete_review(product_id: str):
    user = current_user()
    svc = get_service_client()
    if svc:
        try:
            svc.table("product_reviews").delete().eq("product_id", product_id).eq("user_id", user["id"]).execute()
            flash("Your review was removed.", "success")
        except Exception as exc:
            flash(f"Could not remove: {exc}", "error")
    return redirect(request.referrer or url_for("products.shop"))
