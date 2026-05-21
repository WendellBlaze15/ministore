"""Supabase client helpers.

We expose two flavours of client:

* ``get_anon_client()`` - uses the anon/public key. Safe to use on behalf of a
  visitor; respects Row Level Security policies.
* ``get_service_client()`` - uses the service_role key. Bypasses RLS and must
  only be used in trusted server contexts (admin operations).
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from flask import current_app
from supabase import create_client, Client


@lru_cache(maxsize=1)
def get_anon_client() -> Optional[Client]:
    url = current_app.config.get("SUPABASE_URL")
    key = current_app.config.get("SUPABASE_ANON_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


@lru_cache(maxsize=1)
def get_service_client() -> Optional[Client]:
    url = current_app.config.get("SUPABASE_URL")
    key = current_app.config.get("SUPABASE_SERVICE_KEY")
    if not url or not key:
        return None
    return create_client(url, key)


def get_user_client(access_token: str) -> Optional[Client]:
    """Return a client authenticated as a specific user (for RLS-protected ops)."""
    url = current_app.config.get("SUPABASE_URL")
    key = current_app.config.get("SUPABASE_ANON_KEY")
    if not url or not key:
        return None
    client = create_client(url, key)
    client.postgrest.auth(access_token)
    return client
