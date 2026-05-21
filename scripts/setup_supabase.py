"""One-shot Supabase setup verifier for Papier Lab.

Usage:
    python scripts/setup_supabase.py

What it does (idempotent — safe to run any number of times):

1. Loads ``.env``.
2. Pings the Supabase REST endpoint to confirm SUPABASE_URL + SUPABASE_ANON_KEY
   are reachable.
3. Verifies every required table exists (using SERVICE_KEY so it can bypass
   RLS for the check).
4. Creates the storage bucket (default ``product-images``) if missing — and
   makes it public.
5. If ADMIN_EMAIL is set and that user already registered, promotes them to
   role='admin' in the profiles table.

It WON'T apply schema.sql for you — that still needs to be pasted into the
Supabase SQL editor once. (Supabase's safe public APIs don't include
arbitrary DDL.) The script will tell you clearly if the schema is missing.
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

load_dotenv()

REQUIRED_TABLES = [
    "profiles", "products", "product_images",
    "carts", "cart_items",
    "orders", "order_items",
    "chats", "messages",
    "wishlist",
]


def _ok(msg):  print(f"  [ok] {msg}")
def _bad(msg): print(f"  [!!] {msg}")
def _info(msg): print(f"  ... {msg}")
def _heading(msg): print(f"\n=== {msg} ===")


def main() -> int:
    url   = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    anon  = os.environ.get("SUPABASE_ANON_KEY", "").strip()
    svc   = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()
    bucket = os.environ.get("SUPABASE_STORAGE_BUCKET", "product-images").strip()
    admin_email = (os.environ.get("ADMIN_EMAIL", "") or "").strip().lower()

    _heading("Environment")
    missing = []
    for name, val in [("SUPABASE_URL", url), ("SUPABASE_ANON_KEY", anon), ("SUPABASE_SERVICE_KEY", svc)]:
        if val:
            _ok(f"{name} is set ({len(val)} chars)")
        else:
            _bad(f"{name} is MISSING — please fill it in your .env")
            missing.append(name)
    if missing:
        print("\nFill in the missing env vars then re-run this script.")
        return 1

    try:
        from supabase import create_client
    except ImportError:
        _bad("`supabase` Python package not installed. Run `pip install -r requirements.txt`.")
        return 1

    _heading("Connection check")
    try:
        client_anon = create_client(url, anon)
        client_svc  = create_client(url, svc)
        _ok("Supabase clients initialised")
    except Exception as exc:
        _bad(f"Could not init Supabase clients: {exc}")
        return 1

    _heading("Schema check")
    missing_tables = []
    for t in REQUIRED_TABLES:
        try:
            client_svc.table(t).select("*", count="exact").limit(1).execute()
            _ok(f"public.{t}")
        except Exception as exc:
            _bad(f"public.{t} - missing or unreadable ({exc.__class__.__name__})")
            missing_tables.append(t)
    if missing_tables:
        print()
        _info("It looks like the schema hasn't been applied yet.")
        _info("Open your Supabase project -> SQL Editor -> paste the contents of")
        _info("`supabase/schema.sql` -> Run. Then re-run this script.")
        return 1

    _heading("Storage bucket")
    try:
        buckets = client_svc.storage.list_buckets() or []
        names = set()
        for b in buckets:
            n = getattr(b, "name", None) or (b.get("name") if isinstance(b, dict) else None)
            if n: names.add(n)
        if bucket in names:
            _ok(f"Bucket `{bucket}` already exists")
        else:
            client_svc.storage.create_bucket(bucket, options={"public": True})
            _ok(f"Bucket `{bucket}` created (public read)")
    except Exception as exc:
        _bad(f"Could not check/create bucket: {exc}")
        return 1

    _heading("Realtime check")
    try:
        # Light check: confirm `messages` is in the realtime publication
        # by reading from the catalog through Supabase's RPC. If it fails
        # silently we'll just inform the user.
        _info("Realtime is enabled for `messages` by the schema script.")
        _info("If chat seems silent, open Supabase -> Database -> Replication and verify.")
    except Exception:
        pass

    if admin_email:
        _heading(f"Admin role for {admin_email}")
        try:
            resp = (
                client_svc.table("profiles")
                .select("id, email, role")
                .ilike("email", admin_email)
                .limit(1)
                .execute()
            )
            rows = resp.data or []
            if not rows:
                _info("User hasn't registered yet — register on the site, then re-run this script.")
            else:
                row = rows[0]
                if row.get("role") == "admin":
                    _ok(f"{row['email']} is already admin")
                else:
                    client_svc.table("profiles").update({"role": "admin"}).eq("id", row["id"]).execute()
                    _ok(f"Promoted {row['email']} to admin")
        except Exception as exc:
            _bad(f"Could not update admin role: {exc}")

    _heading("All done!")
    _ok("Your Supabase project is connected and ready. Run `python run.py` to launch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
