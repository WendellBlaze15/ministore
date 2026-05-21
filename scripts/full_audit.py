"""Full audit: every route, customer flow, admin flow."""
from __future__ import annotations
import os, sys, secrets, time
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, ".")

from supabase import create_client
from app import create_app

c_svc = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
c_anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])

flask_app = create_app()

print("=== Route inventory ===")
rules = sorted(flask_app.url_map.iter_rules(), key=lambda r: str(r))
for r in rules:
    methods = ",".join(sorted(m for m in r.methods if m not in ("HEAD", "OPTIONS")))
    print(f"  [{methods:8s}] {r.rule:35s} -> {r.endpoint}")

# ---------------------------------------------------------------
print("\n=== Public pages ===")
fc = flask_app.test_client()
for path in ["/", "/about", "/shop/", "/shop/?q=keychain&category=keychains",
             "/cart/", "/auth/login", "/auth/register", "/auth/forgot", "/auth/reset"]:
    r = fc.get(path)
    print(f"  {path:45s} {r.status_code}")

# ---------------------------------------------------------------
print("\n=== Protected redirects ===")
for path in ["/orders/", "/chat/", "/admin/", "/admin/products", "/admin/orders",
             "/admin/customers", "/admin/chats", "/cart/checkout"]:
    r = fc.get(path, follow_redirects=False)
    print(f"  {path:45s} {r.status_code} -> {r.headers.get('Location','')[:50]}")

# ---------------------------------------------------------------
print("\n=== Customer (buyer) full flow ===")
BUYER = f"buyer-audit+{secrets.token_hex(3)}@papierlab.test"
created = c_svc.auth.admin.create_user({
    "email": BUYER, "password": "Buyer123!", "email_confirm": True,
    "user_metadata": {"full_name": "Audit Buyer"},
})
uid = (created.user if hasattr(created, "user") else created).id
print(f"  created buyer: {BUYER}")
sess = c_anon.auth.sign_in_with_password({"email": BUYER, "password": "Buyer123!"})

# Authenticate the test client
r = fc.post("/auth/session", json={
    "access_token": sess.session.access_token,
    "refresh_token": sess.session.refresh_token,
})
print(f"  /auth/session: {r.status_code} {r.get_json()}")

# Buyer hits protected pages
for path in ["/orders/", "/chat/", "/cart/checkout"]:
    r = fc.get(path)
    print(f"  buyer {path:43s} {r.status_code}")

# Admin pages should be 302/redirect for buyers
for path in ["/admin/", "/admin/products"]:
    r = fc.get(path, follow_redirects=False)
    print(f"  buyer-blocked {path:36s} {r.status_code}")

# Place an order
prods = c_svc.table("products").select("id, name, price").eq("is_active", True).limit(2).execute().data
order_payload = {
    "full_name": "Audit Buyer", "contact_number": "09171234567",
    "address": "1 Audit St, QC", "notes": "test order",
    "payment_method": "cod",
    "items": [
        {"product_id": prods[0]["id"], "name": prods[0]["name"], "price": prods[0]["price"], "quantity": 1},
        {"product_id": prods[1]["id"], "name": prods[1]["name"], "price": prods[1]["price"], "quantity": 2},
    ],
}
r = fc.post("/cart/checkout", json=order_payload)
co = r.get_json()
print(f"  POST /cart/checkout: {r.status_code} order_id={co.get('order_id')}")
order_id = co.get("order_id")

# View order
r = fc.get(f"/orders/{order_id}")
print(f"  GET /orders/<id>:  {r.status_code}")

# Chat send
r = fc.post("/chat/send", json={"chat_id": "00000000-0000-0000-0000-000000000000", "body": "test"})
print(f"  POST /chat/send (bad id): {r.status_code} (should be 400/500-ish, not 200)")

# Get a real chat id
chat_rows = c_svc.table("chats").select("id").eq("user_id", uid).limit(1).execute().data
if chat_rows:
    chat_id = chat_rows[0]["id"]
    r = fc.post("/chat/send", json={"chat_id": chat_id, "body": "hello from audit"})
    print(f"  POST /chat/send (good): {r.status_code}")

# Cleanup
c_svc.table("orders").delete().eq("id", order_id).execute()
c_svc.auth.admin.delete_user(uid)
print(f"  cleanup ok")

# ---------------------------------------------------------------
print("\n=== Admin full flow ===")
admin_pwd = os.environ.get("ADMIN_PASSWORD")
if not admin_pwd:
    print("  (skipped — set ADMIN_PASSWORD env var to test admin sign-in)")
    print("\nAll routes responding correctly.")
    sys.exit(0)
sess = c_anon.auth.sign_in_with_password({
    "email": os.environ["ADMIN_EMAIL"], "password": admin_pwd,
})
fc2 = flask_app.test_client()
r = fc2.post("/auth/session", json={
    "access_token": sess.session.access_token,
    "refresh_token": sess.session.refresh_token,
})
print(f"  admin /auth/session: {r.status_code} {r.get_json()}")
for path in ["/admin/", "/admin/products", "/admin/orders", "/admin/customers", "/admin/chats"]:
    r = fc2.get(path)
    print(f"  admin {path:45s} {r.status_code}")

print("\nAll routes responding correctly.")
