"""Public pages: home, about, PSGC address proxy."""
from __future__ import annotations

import time
import urllib.parse
import urllib.request

from flask import Blueprint, render_template, jsonify, abort

from app.services.supabase_client import get_anon_client

bp = Blueprint("main", __name__)

# In-process cache for the PSGC proxy. The dataset rarely changes so we
# happily serve a stale-ish copy to keep the registration form snappy.
_PSGC_CACHE: dict[str, tuple[float, list]] = {}
_PSGC_TTL_SECONDS = 60 * 60 * 24  # 24 hours
_PSGC_BASE = "https://psgc.gitlab.io/api"


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


@bp.route("/contact")
def contact():
    return render_template("contact.html")


@bp.route("/help/shipping")
def shipping():
    return render_template("help/shipping.html")


@bp.route("/help/custom-orders")
def custom_orders():
    return render_template("help/custom_orders.html")


@bp.route("/help/faq")
def faq():
    return render_template("help/faq.html")


@bp.route("/privacy")
def privacy():
    return render_template("help/privacy.html")


# ---------------------------------------------------------------------------
# PSGC address proxy — exposes a slim subset to the browser:
#   GET /api/ph-address/regions/
#   GET /api/ph-address/regions/<code>/provinces/
#   GET /api/ph-address/regions/<code>/cities-municipalities/
#   GET /api/ph-address/provinces/<code>/cities-municipalities/
#   GET /api/ph-address/cities-municipalities/<code>/barangays/
# ---------------------------------------------------------------------------
ALLOWED_PSGC_PATHS = (
    "regions/",
    "regions/{code}/provinces/",
    "regions/{code}/cities-municipalities/",
    "provinces/{code}/cities-municipalities/",
    "cities-municipalities/{code}/barangays/",
)


def _fetch_psgc(path: str):
    now = time.time()
    cached = _PSGC_CACHE.get(path)
    if cached and (now - cached[0]) < _PSGC_TTL_SECONDS:
        return cached[1]
    url = f"{_PSGC_BASE}/{path}"
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "PapierLab/1.0"})
    with urllib.request.urlopen(req, timeout=8) as resp:
        import json
        data = json.loads(resp.read().decode("utf-8"))
    slim = [{"code": r.get("code"), "name": r.get("name")} for r in data if r.get("code") and r.get("name")]
    _PSGC_CACHE[path] = (now, slim)
    return slim


def _valid_code(code: str) -> bool:
    return code.isdigit() and 9 <= len(code) <= 10


@bp.route("/api/ph-address/regions/")
def ph_regions():
    return jsonify(_fetch_psgc("regions/"))


@bp.route("/api/ph-address/regions/<code>/provinces/")
def ph_provinces(code):
    if not _valid_code(code): abort(400)
    return jsonify(_fetch_psgc(f"regions/{code}/provinces/"))


@bp.route("/api/ph-address/regions/<code>/cities-municipalities/")
def ph_region_cities(code):
    if not _valid_code(code): abort(400)
    return jsonify(_fetch_psgc(f"regions/{code}/cities-municipalities/"))


@bp.route("/api/ph-address/provinces/<code>/cities-municipalities/")
def ph_cities(code):
    if not _valid_code(code): abort(400)
    return jsonify(_fetch_psgc(f"provinces/{code}/cities-municipalities/"))


@bp.route("/api/ph-address/cities-municipalities/<code>/barangays/")
def ph_barangays(code):
    if not _valid_code(code): abort(400)
    return jsonify(_fetch_psgc(f"cities-municipalities/{code}/barangays/"))
