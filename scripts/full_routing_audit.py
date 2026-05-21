"""Comprehensive routing/connection audit covering customer + admin sidebars."""
from __future__ import annotations
import os, sys, io
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, ".")
# Force UTF-8 on Windows console so we can print Tagalog/emoji needles.
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import requests

BASE = "http://127.0.0.1:5000"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "papierlab8@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
assert ADMIN_PASSWORD, "Set ADMIN_PASSWORD env var"

# ---- public pages (no auth) ----
print("\n=== A. PUBLIC (no auth) ===")
public = [
    "/", "/about", "/shop/", "/auth/login", "/auth/register",
    "/auth/forgot", "/auth/reset",
    "/api/ph-address/regions/",
    "/api/ph-address/regions/070000000/provinces/",
    "/api/ph-address/regions/070000000/cities-municipalities/",
    "/api/ph-address/regions/130000000/cities-municipalities/",
]
for path in public:
    r = requests.get(f"{BASE}{path}", timeout=10, allow_redirects=False)
    print(f"  [{'ok ' if r.status_code in (200, 302) else '!!'}] {r.status_code}  {path}")

# ---- protected (must redirect to /auth/login when not signed in) ----
print("\n=== B. PROTECTED routes redirect when not signed in ===")
protected = ["/cart/checkout", "/orders/", "/account/", "/account/profile",
             "/account/orders", "/account/tracking", "/account/wishlist",
             "/admin/", "/admin/products", "/admin/orders", "/admin/customers",
             "/admin/messages", "/admin/reports", "/admin/settings"]
for path in protected:
    r = requests.get(f"{BASE}{path}", timeout=10, allow_redirects=False)
    ok = r.status_code in (302, 303)
    print(f"  [{'ok ' if ok else '!!'}] {r.status_code}  {path}  -> {r.headers.get('Location')}")

# ---- admin login ----
print("\n=== C. ADMIN end-to-end (login -> every admin page) ===")
s = requests.Session()
r = s.post(f"{BASE}/auth/login",
           data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
           headers={"Origin": BASE, "Referer": f"{BASE}/auth/login"},
           allow_redirects=False)
assert r.status_code in (302, 303), f"login failed -> {r.status_code} {r.text[:200]}"
admin_pages = [
    "/admin/", "/admin/products", "/admin/products/new",
    "/admin/orders", "/admin/customers",
    "/admin/messages", "/admin/chats", "/admin/reports", "/admin/settings",
]
for path in admin_pages:
    r = s.get(f"{BASE}{path}", timeout=10, allow_redirects=False)
    ok = r.status_code == 200
    print(f"  [{'ok ' if ok else '!!'}] {r.status_code}  {path}")

print("\n=== D. ADMIN dashboard renders sidebar with all expected links ===")
r = s.get(f"{BASE}/admin/")
needles = ["📊 Dashboard", "🛍️ Products", "＋ Add product", "📦 Orders", "💌 Customers",
          "💬 Messages", "📈 Reports", "⚙️ Settings"]
for n in needles:
    print(f"  [{'ok ' if n in r.text else '!!'}] sidebar shows: {n}")

# ---- customer end-to-end ----
print("\n=== E. CUSTOMER end-to-end (register -> sidebar pages) ===")
import secrets
EMAIL = f"audit+{secrets.token_hex(3)}@example.com"
form = {
    "full_name": "Audit Buyer", "email": EMAIL, "username": "",
    "contact_number": "09171234567",
    "region": "NCR", "province": "", "city": "City of Manila", "barangay": "Barangay 1",
    "address": "1 Test St.",
    "password": "BuyerPass123!", "confirm_password": "BuyerPass123!",
}
cs = requests.Session()
r = cs.post(f"{BASE}/auth/register", data=form,
            headers={"Origin": BASE, "Referer": f"{BASE}/auth/register"},
            allow_redirects=False)
assert r.status_code in (302, 303), f"register failed: {r.status_code} {r.text[:200]}"
customer_pages = ["/account/", "/account/profile", "/account/orders",
                  "/account/tracking", "/account/wishlist", "/orders/", "/cart/"]
for path in customer_pages:
    r = cs.get(f"{BASE}{path}", timeout=10, allow_redirects=False)
    print(f"  [{'ok ' if r.status_code == 200 else '!!'}] {r.status_code}  {path}")

r = cs.get(f"{BASE}/account/")
needles = ["Overview", "Profile", "My orders", "Track order", "Wishlist", "Chat", "Cart"]
print("\n  Customer sidebar items:")
for n in needles:
    print(f"  [{'ok ' if n in r.text else '!!'}] sidebar shows: {n}")

# ---- cleanup ----
print("\n=== F. Cleanup test buyer ===")
from supabase import create_client
svc = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
prof = svc.table("profiles").select("id").ilike("email", EMAIL).single().execute().data
svc.auth.admin.delete_user(prof["id"])
print("  [ok] cleanup done")

print("\nROUTING AUDIT COMPLETE.")
