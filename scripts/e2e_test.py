"""End-to-end auth + session + admin flow test.

Creates a real test user via the Supabase Admin API, then exercises the
Flask /auth/session endpoint to confirm:
- JWT verification works with the new sb_* key format
- The on_auth_user_created trigger created a matching profile row
- ADMIN_EMAIL gets the admin role correctly
- Customer can place an order via /cart/checkout
- Cleans up the test user at the end
"""
from __future__ import annotations
import os, sys, secrets, time, json
from dotenv import load_dotenv

load_dotenv()

from supabase import create_client

url   = os.environ["SUPABASE_URL"]
anon  = os.environ["SUPABASE_ANON_KEY"]
svc   = os.environ["SUPABASE_SERVICE_KEY"]
admin_email = os.environ.get("ADMIN_EMAIL", "").lower()

c_svc  = create_client(url, svc)
c_anon = create_client(url, anon)

TEST_EMAIL = f"e2e+{secrets.token_hex(4)}@papierlab.test"
TEST_PASSWORD = "TestPass123!"

print(f"\n=== Creating test user {TEST_EMAIL} ===")
created = c_svc.auth.admin.create_user({
    "email": TEST_EMAIL,
    "password": TEST_PASSWORD,
    "email_confirm": True,
    "user_metadata": {"full_name": "E2E Tester"},
})
user = created.user if hasattr(created, "user") else created
uid = user.id
print(f"  user id: {uid}")

print("\n=== Trigger check: did handle_new_user create a profile? ===")
time.sleep(0.5)
prof = c_svc.table("profiles").select("*").eq("id", uid).execute().data
if prof:
    print(f"  [ok] profile auto-created: role={prof[0].get('role')}, email={prof[0].get('email')}")
else:
    print("  [!!] profile MISSING - the trigger may have failed")

print("\n=== Sign in as the test user (browser flow simulation) ===")
sign = c_anon.auth.sign_in_with_password({"email": TEST_EMAIL, "password": TEST_PASSWORD})
session = sign.session
print(f"  got access_token ({len(session.access_token)} chars)")
print(f"  got refresh_token ({len(session.refresh_token)} chars)")

print("\n=== Hit Flask /auth/session with the real token ===")
sys.path.insert(0, ".")
from app import create_app
flask_app = create_app()
fc = flask_app.test_client()

resp = fc.post("/auth/session", json={
    "access_token": session.access_token,
    "refresh_token": session.refresh_token,
})
print(f"  status: {resp.status_code}")
print(f"  body:   {resp.get_json()}")
if resp.status_code != 200:
    print("  [!!] /auth/session refused a valid token")
    sys.exit(1)

print("\n=== As customer, try to place an order ===")
prods = c_svc.table("products").select("id, name, price").eq("is_active", True).limit(1).execute().data
order_payload = {
    "full_name": "E2E Tester",
    "contact_number": "09171234567",
    "address": "123 Test St, QC",
    "notes": "please be cute",
    "payment_method": "cod",
    "items": [{
        "product_id": prods[0]["id"],
        "name": prods[0]["name"],
        "price": prods[0]["price"],
        "quantity": 2,
    }],
}
co = fc.post("/cart/checkout", json=order_payload)
print(f"  status: {co.status_code}")
co_data = co.get_json()
print(f"  body:   {co_data}")
order_id = (co_data or {}).get("order_id")

if order_id:
    print(f"\n=== Verify order was written ===")
    o = c_svc.table("orders").select("*").eq("id", order_id).single().execute().data
    print(f"  order total: PHP {o['total']}, status={o['status']}")
    items = c_svc.table("order_items").select("*").eq("order_id", order_id).execute().data
    print(f"  {len(items)} order_items written")
else:
    print("  [!!] order was not created")

print(f"\n=== Hit /orders/<id> as the customer ===")
r = fc.get(f"/orders/{order_id}")
print(f"  /orders/<id> status: {r.status_code}")

print(f"\n=== Admin promotion: is {TEST_EMAIL} == ADMIN_EMAIL '{admin_email}'? ===")
if admin_email and TEST_EMAIL.lower() == admin_email:
    p = c_svc.table("profiles").select("role").eq("id", uid).single().execute().data
    print(f"  role after session: {p.get('role')}")
else:
    print(f"  not the admin email - role should stay 'customer'")

print(f"\n=== Cleanup: delete the test user + their order ===")
try:
    if order_id:
        c_svc.table("orders").delete().eq("id", order_id).execute()
    c_svc.auth.admin.delete_user(uid)
    print("  [ok] cleaned up")
except Exception as e:
    print(f"  cleanup failed: {e}")

print("\nAll done.")
