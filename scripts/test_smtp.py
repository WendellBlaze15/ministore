"""Smoke test the SMTP setup by sending a real OTP test email."""
from __future__ import annotations
import os, sys
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, ".")

from app import create_app
app = create_app()
with app.app_context():
    from app.services.email import send_email, render_otp_email

    to = os.environ.get("SMTP_USERNAME", "")
    if not to:
        print("[!!] SMTP_USERNAME not set"); sys.exit(1)

    text, html = render_otp_email("123456", 10)
    print(f"Sending test email to {to}…")
    ok, info = send_email(
        to=to,
        subject="[Papier Lab SMTP test] hello from your shop 🌸",
        text_body=text,
        html_body=html,
    )
    if ok:
        print("[ok]", info)
        print("Check the inbox. The full OTP password reset flow is wired up.")
    else:
        print("[!!]", info)
        sys.exit(1)
