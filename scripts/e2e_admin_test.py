"""Verify the admin promotion flow.

Creates a test user with the same email as ADMIN_EMAIL, signs them in
through Flask, and confirms their profile role becomes 'admin'.
"""
from __future__ import annotations
import os, sys, time, secrets
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client

url = os.environ["SUPABASE_URL"]
anon = os.environ["SUPABASE_ANON_KEY"]
svc = os.environ["SUPABASE_SERVICE_KEY"]

c_svc = create_client(url, svc)
c_anon = create_client(url, anon)

# Temporarily override ADMIN_EMAIL to a test address we will create + delete.
TEST_ADMIN = f"e2e-admin+{secrets.token_hex(3)}@papierlab.test"
os.environ["ADMIN_EMAIL"] = TEST_ADMIN

print(f"\n=== ADMIN_EMAIL set to {TEST_ADMIN} for this test ===")

print("\n=== Create the would-be admin user ===")
created = c_svc.auth.admin.create_user({
    "email": TEST_ADMIN,
    "password": "AdminPass123!",
    "email_confirm": True,
    "user_metadata": {"full_name": "The Boss"},
})
user = created.user if hasattr(created, "user") else created
uid = user.id
print(f"  user id: {uid}")

time.sleep(0.5)
p = c_svc.table("profiles").select("role,full_name").eq("id", uid).single().execute().data
print(f"  profile after signup: role={p['role']}, name={p['full_name']}")
assert p["role"] == "customer", "fresh signup should default to customer"

print("\n=== Sign in & hit /auth/session ===")
sign = c_anon.auth.sign_in_with_password({"email": TEST_ADMIN, "password": "AdminPass123!"})

sys.path.insert(0, ".")
from app import create_app
app = create_app()
fc = app.test_client()
resp = fc.post("/auth/session", json={
    "access_token": sign.session.access_token,
    "refresh_token": sign.session.refresh_token,
})
print(f"  /auth/session status: {resp.status_code}, body: {resp.get_json()}")

print("\n=== Profile after admin sign-in ===")
p = c_svc.table("profiles").select("role,full_name,email").eq("id", uid).single().execute().data
print(f"  role: {p['role']}")
print(f"  name: {p['full_name']}")
assert p["role"] == "admin", f"expected admin, got {p['role']}"
print("  [ok] admin promotion worked")

print("\n=== Can the admin reach /admin/ ? ===")
r = fc.get("/admin/")
print(f"  /admin/ status: {r.status_code}")
assert r.status_code == 200, "admin should be allowed in"
print("  [ok] admin dashboard accessible")

print("\n=== Cleanup ===")
c_svc.auth.admin.delete_user(uid)
print("  [ok] test admin deleted")
print("\nAll admin checks passed.")
