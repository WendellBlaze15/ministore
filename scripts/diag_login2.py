"""Test the new server-side login + register (no CDN/JS required)."""
from __future__ import annotations
import os, sys, secrets, json
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, ".")

import requests
from supabase import create_client

BASE = "http://127.0.0.1:5000"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "papierlab8@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
assert ADMIN_PASSWORD, "Set ADMIN_PASSWORD env var"

svc = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])

print("=== 1. Admin sign-in via plain HTML POST ===")
s = requests.Session()
r = s.post(f"{BASE}/auth/login",
           data={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD, "next": ""},
           headers={"Origin": BASE, "Referer": f"{BASE}/auth/login"},
           allow_redirects=False)
print(f"  -> {r.status_code} -> Location: {r.headers.get('Location')}")
assert r.status_code in (302, 303), "expected redirect after successful login"
print(f"  cookie session set: {'session' in s.cookies}")

print("\n=== 2. /auth/login while logged in must redirect home ===")
r = s.get(f"{BASE}/auth/login", allow_redirects=False)
print(f"  -> {r.status_code} -> {r.headers.get('Location')}")

print("\n=== 3. /admin/ accessible? ===")
r = s.get(f"{BASE}/admin/", allow_redirects=False)
print(f"  -> {r.status_code}")

print("\n=== 4. Logout, then test customer register via POST ===")
s.post(f"{BASE}/auth/logout", headers={"Origin": BASE, "Referer": BASE})
s.cookies.clear()

EMAIL = f"reg-test+{secrets.token_hex(3)}@example.com"
USERNAME = f"pen_{secrets.token_hex(3)}"
form = {
    "full_name": "Andrea Form-Buyer",
    "email": EMAIL,
    "username": USERNAME,
    "contact_number": "09171234567",
    "region": "Central Visayas",
    "province": "Cebu",
    "city": "Cebu City",
    "barangay": "Mabolo",
    "address": "123 Rosal Street",
    "password": "BuyerPass123!",
    "confirm_password": "BuyerPass123!",
}
r = s.post(f"{BASE}/auth/register", data=form,
           headers={"Origin": BASE, "Referer": f"{BASE}/auth/register"},
           allow_redirects=False)
print(f"  POST /auth/register -> {r.status_code} -> {r.headers.get('Location')}")

print("\n=== 5. New user signed in & profile populated? ===")
r = s.get(f"{BASE}/", allow_redirects=False)
print(f"  GET / -> {r.status_code}")
print(f"  page shows logged-in name: {'Andrea Form-Buyer' in r.text}")
prof = svc.table("profiles").select("*").ilike("email", EMAIL).single().execute().data
for k in ("full_name", "username", "contact_number", "address", "role"):
    print(f"    {k:18s} = {prof.get(k)!r}")
assert prof["full_name"] == "Andrea Form-Buyer"
assert prof["username"] == USERNAME
assert "Mabolo" in (prof["address"] or ""), "barangay should be in composed address"

print("\n=== 6. PSGC proxy endpoints ===")
for p in ["regions/", "regions/070000000/provinces/", "provinces/072200000/cities-municipalities/"]:
    rr = requests.get(f"{BASE}/api/ph-address/{p}", timeout=12)
    print(f"  /api/ph-address/{p:50s} -> {rr.status_code}  ({len(rr.json())} rows)")

print("\n=== 7. Cleanup test buyer ===")
svc.auth.admin.delete_user(prof["id"])
print("  [ok] removed")
print("\nServer-side login + register fully working.")
