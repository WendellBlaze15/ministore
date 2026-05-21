"""Reproduce exactly what the browser does at /auth/login and /auth/register.

If this works but the browser doesn't, the issue is purely a browser/CDN/JS
problem (esm.sh blocked, network, console error). If this fails, we know
the server- or Supabase-side is the culprit."""
from __future__ import annotations
import os, sys, json
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, ".")

import requests
from supabase import create_client

BASE = "http://127.0.0.1:5000"
ANON_URL  = os.environ["SUPABASE_URL"]
ANON_KEY  = os.environ["SUPABASE_ANON_KEY"]
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "papierlab8@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")
if not ADMIN_PASSWORD:
    print("[!!] Set ADMIN_PASSWORD env var or in .env to run this test.")
    sys.exit(1)

print("=== A. Server hands out the login page with env injected? ===")
r = requests.get(f"{BASE}/auth/login")
print(f"  GET /auth/login -> {r.status_code}")
needle_url = 'SUPABASE_URL: "' + ANON_URL
print(f"  Page contains SUPABASE_URL: {needle_url in r.text}")
print(f"  Page contains anon key:     {ANON_KEY[:24] in r.text}")
print(f"  Loads supabase.js module:   {'/static/js/supabase.js' in r.text}")

print("\n=== B. Sign in via Supabase Auth REST (mirrors signInWithPassword) ===")
auth_url = f"{ANON_URL}/auth/v1/token?grant_type=password"
hdr = {"apikey": ANON_KEY, "Content-Type": "application/json"}
res = requests.post(auth_url, headers=hdr,
                    json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
print(f"  POST /auth/v1/token -> {res.status_code}")
if res.status_code != 200:
    print("  body:", res.text[:400])
    sys.exit(1)
session = res.json()
print(f"  got access_token ({len(session['access_token'])} chars)")
print(f"  user.email = {session['user']['email']}")
print(f"  email_confirmed_at = {session['user'].get('email_confirmed_at')}")

print("\n=== C. Hand the token to /auth/session (server-side verify) ===")
s = requests.Session()
r = s.post(f"{BASE}/auth/session",
           json={"access_token": session["access_token"],
                 "refresh_token": session["refresh_token"]},
           headers={"Origin": BASE, "Referer": f"{BASE}/auth/login"})
print(f"  -> {r.status_code} body: {r.text[:200]}")

print("\n=== D. Hit / with the session cookie ===")
r = s.get(f"{BASE}/")
print(f"  GET / -> {r.status_code}, length={len(r.text)}")
print(f"  page mentions 'Sign in'?  {'Sign in' in r.text}")
print(f"  page mentions 'Admin'?    {'Admin' in r.text}")
print(f"  page mentions logged-in name?  {ADMIN_EMAIL.split('@')[0] in r.text or 'My orders' in r.text}")

print("\n=== E. /auth/login while logged in must redirect ===")
r = s.get(f"{BASE}/auth/login", allow_redirects=False)
print(f"  GET /auth/login -> {r.status_code} (302 = good)")

print("\n=== F. Supabase admin user actually exists & email_confirmed? ===")
svc = create_client(ANON_URL, os.environ["SUPABASE_SERVICE_KEY"])
list_resp = svc.auth.admin.list_users()
admins = [u for u in list_resp if (getattr(u, 'email', '') or '').lower() == ADMIN_EMAIL.lower()]
if not admins:
    print(f"  [!!] admin user NOT found in auth.users")
else:
    a = admins[0]
    print(f"  admin id: {a.id}")
    print(f"  email_confirmed_at: {a.email_confirmed_at}")
    print(f"  last_sign_in_at:    {a.last_sign_in_at}")
print("\nDone.")
