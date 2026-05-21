"""Deep audit of the Supabase project state. Read-only — safe to run."""
from __future__ import annotations
import os, sys
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client

url = os.environ["SUPABASE_URL"]
anon = os.environ["SUPABASE_ANON_KEY"]
svc = os.environ["SUPABASE_SERVICE_KEY"]

c_svc = create_client(url, svc)
c_anon = create_client(url, anon)

print("=== Key format ===")
print(f"  anon  key starts with: {anon[:25]}... ({len(anon)} chars)")
print(f"  svc   key starts with: {svc[:25]}... ({len(svc)} chars)")

print("\n=== Table row counts (via service role) ===")
for t in ["profiles","products","product_images","carts","cart_items",
          "orders","order_items","chats","messages","wishlist"]:
    try:
        r = c_svc.table(t).select("*", count="exact").limit(0).execute()
        print(f"  {t:20s} {r.count} rows")
    except Exception as e:
        print(f"  {t:20s} ERROR: {e}")

print("\n=== Anon SELECT respects RLS (should only see active products) ===")
try:
    r = c_anon.table("products").select("name,is_active", count="exact").execute()
    print(f"  anon sees {r.count} products (RLS check)")
except Exception as e:
    print(f"  anon SELECT failed: {e}")

print("\n=== Storage buckets ===")
try:
    buckets = c_svc.storage.list_buckets() or []
    for b in buckets:
        name = getattr(b, "name", None) or (b.get("name") if isinstance(b,dict) else None)
        public = getattr(b, "public", None) if hasattr(b, "public") else (b.get("public") if isinstance(b,dict) else None)
        print(f"  {name} (public={public})")
except Exception as e:
    print(f"  list_buckets failed: {e}")

print("\n=== Realtime publication check (messages should be in supabase_realtime) ===")
try:
    # We can't easily query pg_publication via the REST API, so we infer by
    # subscribing and listing tables via the function. Best-effort.
    print("  (skipped — verify in Supabase UI: Database -> Replication)")
except Exception as e:
    print(f"  realtime check failed: {e}")

print("\n=== Auth users (existing accounts) ===")
try:
    page = c_svc.auth.admin.list_users()
    users = page if isinstance(page, list) else getattr(page, "users", None) or []
    print(f"  {len(users)} user(s)")
    for u in users[:5]:
        uid = getattr(u, "id", None) or (u.get("id") if isinstance(u, dict) else None)
        email = getattr(u, "email", None) or (u.get("email") if isinstance(u, dict) else None)
        print(f"    - {email}  ({uid})")
except Exception as e:
    print(f"  list_users failed: {e}")
