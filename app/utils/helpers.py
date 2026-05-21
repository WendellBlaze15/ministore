"""Small helper utilities used across the app."""
from __future__ import annotations

import re
import uuid
from datetime import datetime
from typing import Iterable

from flask import current_app


def slugify(value: str) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "item"


def allowed_image(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in current_app.config["ALLOWED_IMAGE_EXTS"]


def safe_filename(filename: str) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "jpg"
    return f"{uuid.uuid4().hex}.{ext}"


def format_php(amount) -> str:
    try:
        return f"₱{float(amount):,.2f}"
    except (TypeError, ValueError):
        return "₱0.00"


def human_dt(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value
    return value.strftime("%b %d, %Y · %I:%M %p")


def chunk(seq: Iterable, size: int):
    bucket = []
    for item in seq:
        bucket.append(item)
        if len(bucket) >= size:
            yield bucket
            bucket = []
    if bucket:
        yield bucket
