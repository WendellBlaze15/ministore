"""End-to-end OTP password reset flow.

- Creates a throwaway user with a known initial password
- Sends a real OTP code via SMTP
- Pulls the latest code_hash from the DB to verify by hashing back from
  every code in the search space (only 1M possibilities — fast enough for a test)
- Submits /auth/reset with the recovered code and a new password
- Signs in with the new password to prove it really changed
- Cleans up
"""
from __future__ import annotations
import os, sys, secrets, time
from dotenv import load_dotenv
load_dotenv()
sys.path.insert(0, ".")

from supabase import create_client
from app import create_app
from app.utils.security import hash_token

c = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
c_anon = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_ANON_KEY"])

flask_app = create_app()
fc = flask_app.test_client()

EMAIL = f"otp-e2e+{secrets.token_hex(3)}@papierlab.test"
OLD_PWD = "OldPassword123!"
NEW_PWD = "NewPassword456!"

print(f"\n=== Create user {EMAIL} ===")
created = c.auth.admin.create_user({
    "email": EMAIL, "password": OLD_PWD, "email_confirm": True,
    "user_metadata": {"full_name": "OTP Tester"},
})
uid = (created.user if hasattr(created, "user") else created).id
print(f"  uid: {uid}")
time.sleep(0.4)

print(f"\n=== POST /auth/forgot ===")
r = fc.post("/auth/forgot", json={"email": EMAIL})
print(f"  status={r.status_code} body={r.get_json()}")
assert r.status_code == 200, r.get_data(as_text=True)

print(f"\n=== Fetch the latest code_hash from DB & brute-force find the code ===")
rows = c.table("password_reset_codes").select("code_hash").ilike("email", EMAIL).order("created_at", desc=True).limit(1).execute().data
assert rows, "no code was issued — SMTP probably failed silently"
code_hash = rows[0]["code_hash"]

with flask_app.app_context():
    found = None
    for n in range(10**6):
        candidate = str(n).zfill(6)
        if hash_token(f"otp:{candidate}") == code_hash:
            found = candidate
            break
    assert found, "code hash didn't match any 6-digit code (HMAC key mismatch?)"
print(f"  recovered code: {found}")

print(f"\n=== POST /auth/reset with code + new password ===")
r = fc.post("/auth/reset", json={
    "email": EMAIL, "code": found,
    "new_password": NEW_PWD, "confirm_password": NEW_PWD,
})
print(f"  status={r.status_code} body={r.get_json()}")
assert r.status_code == 200, r.get_data(as_text=True)

print(f"\n=== Sign in with OLD password (should fail) ===")
try:
    c_anon.auth.sign_in_with_password({"email": EMAIL, "password": OLD_PWD})
    print("  [!!] old password still works")
    sys.exit(1)
except Exception as e:
    print(f"  [ok] old password rejected: {e.__class__.__name__}")

print(f"\n=== Sign in with NEW password (should succeed) ===")
sess = c_anon.auth.sign_in_with_password({"email": EMAIL, "password": NEW_PWD})
print(f"  [ok] new password works, got access_token ({len(sess.session.access_token)} chars)")

print(f"\n=== Cleanup ===")
c.auth.admin.delete_user(uid)
print("  [ok] test user removed")
print("\nOTP password reset flow is fully working.")
