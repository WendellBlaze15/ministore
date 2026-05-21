"""Application configuration loaded from environment variables."""
import os


def _is_production() -> bool:
    env = (os.environ.get("FLASK_ENV") or "").lower()
    if env == "production":
        return True
    # Vercel sets this automatically in deployed environments.
    return os.environ.get("VERCEL_ENV", "").lower() == "production"


class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

    # Supabase
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")
    SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY", "")
    SUPABASE_STORAGE_BUCKET = os.environ.get("SUPABASE_STORAGE_BUCKET", "product-images")

    ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "")
    APP_URL = os.environ.get("APP_URL", "http://localhost:5000")

    # Upload limits (8 MB)
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024
    ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "webp", "gif"}

    # Session cookie hardening
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _is_production()  # HTTPS-only in production
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 14  # 14 days

    IS_PRODUCTION = _is_production()
