"""Public pages: home + misc."""
from flask import Blueprint, render_template

from app.services.supabase_client import get_anon_client

bp = Blueprint("main", __name__)


CATEGORIES = [
    {"slug": "bookmarks", "name": "Bookmarks", "emoji": "🔖", "blurb": "cute paper companions for every book lover"},
    {"slug": "keychains", "name": "Keychains", "emoji": "🗝️", "blurb": "tiny charms that travel everywhere with you"},
    {"slug": "polaroids", "name": "Polaroid Prints", "emoji": "📸", "blurb": "memories printed in soft pastel frames"},
    {"slug": "crafts", "name": "Handmade Crafts", "emoji": "🌸", "blurb": "one-of-a-kind handmade goodies"},
]


@bp.route("/")
def home():
    products = []
    client = get_anon_client()
    if client:
        try:
            resp = (
                client.table("products")
                .select("id, name, slug, price, category, cover_image, is_featured")
                .eq("is_active", True)
                .order("is_featured", desc=True)
                .order("created_at", desc=True)
                .limit(8)
                .execute()
            )
            products = resp.data or []
        except Exception:
            products = []

    return render_template("home.html", categories=CATEGORIES, featured=products)


@bp.route("/about")
def about():
    return render_template("about.html")
