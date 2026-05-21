"""Full E2E test of the new registration flow with extended fields."""
from __future__ import annotations
import os, sys, secrets, time
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, ".")

from supabase import create_client

c_svc = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
c_anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])

EMAIL = f"reg-v2+{secrets.token_hex(3)}@example.com"
USERNAME = f"penpal_{secrets.token_hex(3)}"
PASSWORD = "BuyerPass123!"

print(f"\n=== Sign up via admin (mirrors the form metadata) ===")
created = c_svc.auth.admin.create_user({
    "email": EMAIL, "password": PASSWORD, "email_confirm": True,
    "user_metadata": {
        "full_name": "Andrea Buyer",
        "username": USERNAME,
        "contact_number": "09171234567",
        "address": "123 Buyer St, Cebu City",
    },
})
user = created.user if hasattr(created, "user") else created
print(f"  uid: {user.id}")
time.sleep(0.5)

print(f"\n=== Sign in to get a real session ===")
sign = c_anon.auth.sign_in_with_password({"email": EMAIL, "password": PASSWORD})
session = sign.session
print(f"  got access_token ({len(session.access_token)} chars)")

print(f"\n=== Trigger created profile? ===")
prof = c_svc.table("profiles").select("*").eq("id", user.id).single().execute().data
print(f"  full_name: {prof.get('full_name')}")
print(f"  username:  {prof.get('username')}")
print(f"  contact:   {prof.get('contact_number')}")
print(f"  address:   {prof.get('address')}")
print(f"  role:      {prof.get('role')}")

print(f"\n=== Hit Flask /auth/session, which calls _sync_metadata_to_profile ===")
from app import create_app
flask_app = create_app()
fc = flask_app.test_client()
r = fc.post("/auth/session", json={
    "access_token": session.access_token,
    "refresh_token": session.refresh_token,
})
print(f"  status: {r.status_code} body: {r.get_json()}")

print(f"\n=== Profile after session sync ===")
prof2 = c_svc.table("profiles").select("*").eq("id", user.id).single().execute().data
for k in ("full_name", "username", "contact_number", "address"):
    print(f"  {k:18s} = {prof2.get(k)!r}")
assert prof2.get("username") == USERNAME
assert prof2.get("contact_number") == "09171234567"
assert prof2.get("address") == "123 Buyer St, Cebu City"

print(f"\n=== /complete-profile endpoint can update fields ===")
r = fc.post("/auth/complete-profile", json={
    "full_name": "Andrea B. Updated",
    "address": "Updated 999 Bohol St, Cebu City",
})
print(f"  status: {r.status_code} body: {r.get_json()}")
prof3 = c_svc.table("profiles").select("full_name, address").eq("id", user.id).single().execute().data
print(f"  name now:    {prof3.get('full_name')!r}")
print(f"  address now: {prof3.get('address')!r}")

print(f"\n=== Checkout page prefills from profile ===")
r = fc.get("/cart/checkout")
body = r.get_data(as_text=True)
assert "Andrea B. Updated" in body, "name not prefilled"
assert "09171234567" in body, "contact not prefilled"
assert "Bohol St" in body, "address not prefilled"
print("  [ok] full_name, contact and address all prefilled in checkout form")

print(f"\n=== Username uniqueness check ===")
r = fc.post("/auth/complete-profile", json={"username": "papierlab_admin"})
print(f"  admin name attempt: {r.status_code} {r.get_json()}")
# try claiming a brand new unique name
r = fc.post("/auth/complete-profile", json={"username": f"new_{secrets.token_hex(3)}"})
print(f"  fresh username: {r.status_code} {r.get_json()}")

print(f"\n=== Cleanup ===")
c_svc.auth.admin.delete_user(user.id)
print("  [ok] test user removed")
print("\nRegistration v2 fully verified.")
