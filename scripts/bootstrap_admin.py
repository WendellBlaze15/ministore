"""Bootstrap the admin account and verify the OTP migration.

- Confirms ``password_reset_codes`` table exists (created by
  ``supabase/migrations/003_otp.sql``).
- Creates (or updates) the admin user with the credentials in .env:
  ADMIN_EMAIL / ADMIN_PASSWORD (read once, NOT stored anywhere on disk).
- Promotes that user to role='admin' in the profiles table.

Idempotent — re-run any time. It will only RESET the admin's password
if you pass --reset-password.
"""
from __future__ import annotations
import os, sys, argparse
from dotenv import load_dotenv

load_dotenv()

ADMIN_EMAIL = (os.environ.get("ADMIN_EMAIL") or "").strip().lower()
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "").strip()

if not ADMIN_EMAIL or "@" not in ADMIN_EMAIL:
    print("[!!] ADMIN_EMAIL not set in .env"); sys.exit(1)

parser = argparse.ArgumentParser()
parser.add_argument("--password", help="Admin password (or set ADMIN_PASSWORD env var)")
parser.add_argument("--reset-password", action="store_true", help="Force-reset password if user exists")
args = parser.parse_args()

password = args.password or ADMIN_PASSWORD
if not password:
    print("[!!] No password provided. Pass --password='...' or set ADMIN_PASSWORD."); sys.exit(1)

from supabase import create_client

url = os.environ["SUPABASE_URL"]
svc = os.environ["SUPABASE_SERVICE_KEY"]
c = create_client(url, svc)

print(f"=== Bootstrap admin: {ADMIN_EMAIL} ===")

# 1. Check OTP table is in place
print("\n[1/3] Checking password_reset_codes table…")
try:
    c.table("password_reset_codes").select("id", count="exact").limit(0).execute()
    print("  [ok] password_reset_codes table exists")
except Exception as exc:
    print(f"  [!!] missing — apply supabase/migrations/003_otp.sql first ({exc.__class__.__name__})")
    sys.exit(1)

# 2. Find or create the auth user
print("\n[2/3] Auth user…")
existing = None
try:
    page = c.auth.admin.list_users()
    users = page if isinstance(page, list) else getattr(page, "users", None) or []
    for u in users:
        em = (getattr(u, "email", None) or "").lower()
        if em == ADMIN_EMAIL:
            existing = u
            break
except Exception as exc:
    print(f"  [!!] could not list users: {exc}")
    sys.exit(1)

if existing is None:
    try:
        created = c.auth.admin.create_user({
            "email": ADMIN_EMAIL,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"full_name": "Papier Lab Admin", "role": "admin"},
        })
        existing = created.user if hasattr(created, "user") else created
        print(f"  [ok] created auth user {ADMIN_EMAIL}")
    except Exception as exc:
        print(f"  [!!] create_user failed: {exc}")
        sys.exit(1)
else:
    print(f"  [ok] auth user already exists ({existing.id})")
    if args.reset_password:
        try:
            c.auth.admin.update_user_by_id(existing.id, {"password": password, "email_confirm": True})
            print("  [ok] password reset")
        except Exception as exc:
            print(f"  [!!] password reset failed: {exc}")

uid = existing.id

# 3. Make sure the profile row exists and role=admin
print("\n[3/3] Profile row…")
try:
    rows = c.table("profiles").select("*").eq("id", uid).limit(1).execute().data or []
    if not rows:
        c.table("profiles").insert({
            "id": uid,
            "email": ADMIN_EMAIL,
            "full_name": "Papier Lab Admin",
            "role": "admin",
        }).execute()
        print("  [ok] profile created with role=admin")
    else:
        cur = rows[0]
        patch = {}
        if cur.get("role") != "admin": patch["role"] = "admin"
        if not cur.get("full_name"):   patch["full_name"] = "Papier Lab Admin"
        if (cur.get("email") or "").lower() != ADMIN_EMAIL:
            patch["email"] = ADMIN_EMAIL
        if patch:
            c.table("profiles").update(patch).eq("id", uid).execute()
            print(f"  [ok] profile updated: {patch}")
        else:
            print("  [ok] profile already correct")
except Exception as exc:
    print(f"  [!!] profile sync failed: {exc}")
    sys.exit(1)

print(f"\nAll done. Sign in at /auth/login with {ADMIN_EMAIL}.")
