from __future__ import annotations
import os, sys, io, json
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, ".")
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import requests
from supabase import create_client

BASE = "http://127.0.0.1:5000"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "papierlab8@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
assert ADMIN_PASSWORD, "Set ADMIN_PASSWORD"

errors = []

def probe(session, method, path, **kw):
    url = f"{BASE}{path}"
    try:
        r = session.request(method, url, allow_redirects=False, timeout=15,
                            headers={"Origin": BASE, "Referer": BASE, **kw.pop("headers", {})},
                            **kw)
        ok = r.status_code < 400 or r.status_code in (302, 303, 401, 403)
        if not ok:
            errors.append((method, path, r.status_code, r.text[:200]))
        return r
    except Exception as exc:
        errors.append((method, path, "EXC", str(exc)))
        class _Err:
            status_code = 999
            text = str(exc)
            headers = {}
        return _Err()

print("\n=== PUBLIC pages ===")
public = requests.Session()
for p in ["/", "/about", "/contact", "/shop/", "/shop/?category=bookmarks",
         "/auth/login", "/auth/register", "/auth/forgot", "/auth/reset",
         "/auth/verify", "/auth/verify?email=test@example.com",
         "/api/ph-address/regions/",
         "/api/ph-address/regions/070000000/provinces/",
         "/api/ph-address/regions/130000000/cities-municipalities/"]:
    r = probe(public, "GET", p)
    print(f"  GET  {p:60s} -> {r.status_code}")

print("\n=== Product detail pages ===")
svc = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
prods = (svc.table("products").select("slug").execute()).data or []
for p in prods:
    r = probe(public, "GET", f"/shop/product/{p['slug']}")
    print(f"  GET  /shop/product/{p['slug']:38s} -> {r.status_code}")

print("\n=== ADMIN session ===")
admin = requests.Session()
r = admin.post(f"{BASE}/auth/login", data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
               headers={"Origin": BASE, "Referer": f"{BASE}/auth/login"},
               allow_redirects=False)
assert r.status_code in (302, 303), f"admin login fail: {r.status_code}"

admin_pages = ["/admin/", "/admin/products", "/admin/products/new",
               "/admin/orders", "/admin/orders?status=pending", "/admin/customers",
               "/admin/messages", "/admin/chats", "/admin/reports", "/admin/settings"]
for p in admin_pages:
    r = probe(admin, "GET", p)
    print(f"  GET  {p:60s} -> {r.status_code}")

orders_list = (svc.table("orders").select("id").limit(2).execute()).data or []
for o in orders_list:
    r = probe(admin, "GET", f"/admin/orders/{o['id']}")
    print(f"  GET  /admin/orders/{o['id'][:8]}…  -> {r.status_code}")

products_list = (svc.table("products").select("id").limit(2).execute()).data or []
for p in products_list:
    r = probe(admin, "GET", f"/admin/products/{p['id']}/edit")
    print(f"  GET  /admin/products/{p['id'][:8]}…/edit -> {r.status_code}")

print("\n=== CUSTOMER session ===")
admin.post(f"{BASE}/auth/logout", headers={"Origin": BASE})
cust = requests.Session()
r = cust.post(f"{BASE}/auth/login",
              data={"email": "andrea.demo@papierlab.shop", "password": "DemoBuyer123!"},
              headers={"Origin": BASE, "Referer": f"{BASE}/auth/login"}, allow_redirects=False)
assert r.status_code in (302, 303)

cust_pages = ["/account/", "/account/profile", "/account/orders", "/account/tracking",
              "/account/wishlist", "/orders/", "/cart/", "/cart/checkout", "/chat/"]
for p in cust_pages:
    r = probe(cust, "GET", p)
    print(f"  GET  {p:60s} -> {r.status_code}")

cust_orders = (svc.table("orders").select("id").eq(
    "user_id",
    next(u.id for u in svc.auth.admin.list_users() if (getattr(u, "email", "") or "").lower() == "andrea.demo@papierlab.shop"),
).limit(2).execute()).data or []
for o in cust_orders:
    r = probe(cust, "GET", f"/orders/{o['id']}")
    print(f"  GET  /orders/{o['id'][:8]}…  -> {r.status_code}")

print("\n=== POST endpoints (CSRF same-origin enforced) ===")
# Use a real product UUID for wishlist + a real chat UUID for chat/send
real_prod = (svc.table("products").select("id").limit(1).execute()).data[0]["id"]
andrea_id = next(u.id for u in svc.auth.admin.list_users() if (getattr(u, "email", "") or "").lower() == "andrea.demo@papierlab.shop")
real_chat = (svc.table("chats").select("id").eq("user_id", andrea_id).limit(1).execute()).data[0]["id"]

posts = [
    ("/auth/complete-profile", {"contact_number": "09171111111"}),
    ("/account/wishlist/toggle", {"product_id": real_prod}),
    ("/chat/send", {"chat_id": real_chat, "body": "audit ping 🌸"}),
]
for path, payload in posts:
    r = probe(cust, "POST", path, json=payload)
    print(f"  POST {path:60s} -> {r.status_code}")

print("\n=== RESULTS ===")
if errors:
    print(f"  Found {len(errors)} server errors:")
    for m, p, s, t in errors:
        print(f"    [!!] {m} {p} -> {s}")
        print(f"         {t[:160]}")
    sys.exit(1)
else:
    print("  CLEAN — no WSGI / HTTP errors anywhere.")
