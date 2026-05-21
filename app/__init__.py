"""Flask application factory for Papier Lab."""
from __future__ import annotations

import os
from flask import Flask
from dotenv import load_dotenv

load_dotenv()


def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder="static",
        template_folder="templates",
    )

    from .config import Config

    app.config.from_object(Config)

    # Make selected Supabase values available to all templates (for the
    # browser-side Supabase JS client). The service key is NEVER exposed.
    @app.context_processor
    def inject_globals():
        from flask import request, session
        endpoint = (request.endpoint or "") if request else ""
        # Hide the public footer on the post-login dashboards (admin or
        # customer account areas). Buyers only see the studio chrome once
        # they've signed in.
        in_app_area = any(endpoint.startswith(prefix) for prefix in (
            "admin.", "account.", "orders.", "chat.", "cart.",
        ))
        signed_in = bool((session or {}).get("user"))
        hide_footer = bool(signed_in and in_app_area)
        return {
            "SUPABASE_URL": app.config.get("SUPABASE_URL", ""),
            "SUPABASE_ANON_KEY": app.config.get("SUPABASE_ANON_KEY", ""),
            "APP_NAME": "Papier Lab",
            "APP_TAGLINE": "handmade with love, wrapped in pink",
            "HIDE_FOOTER": hide_footer,
            "IN_APP_AREA": in_app_area,
        }

    # Register blueprints
    from .routes.main import bp as main_bp
    from .routes.auth import bp as auth_bp
    from .routes.products import bp as products_bp
    from .routes.cart import bp as cart_bp
    from .routes.orders import bp as orders_bp
    from .routes.chat import bp as chat_bp
    from .routes.admin import bp as admin_bp
    from .routes.account import bp as account_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(products_bp, url_prefix="/shop")
    app.register_blueprint(cart_bp, url_prefix="/cart")
    app.register_blueprint(orders_bp, url_prefix="/orders")
    app.register_blueprint(chat_bp, url_prefix="/chat")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(account_bp, url_prefix="/account")

    # Friendly error pages
    from .routes.errors import register_error_handlers

    register_error_handlers(app)

    return app
