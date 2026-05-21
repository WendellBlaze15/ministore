"""Tiny SMTP wrapper for transactional emails (OTP, etc.).

We use Python's stdlib ``smtplib`` + ``email.message`` so there are zero
extra dependencies. Gmail is the default target — set ``SMTP_*`` env vars
and we'll connect via STARTTLS on port 587.
"""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

from flask import current_app


def send_email(
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> tuple[bool, str]:
    """Send an email via SMTP. Returns (ok, info_or_error)."""
    cfg = current_app.config

    host = cfg.get("SMTP_HOST", "")
    user = cfg.get("SMTP_USERNAME", "")
    pwd = cfg.get("SMTP_PASSWORD", "")

    if not (host and user and pwd):
        return False, "SMTP not configured (set SMTP_HOST/USERNAME/PASSWORD)."

    # Gmail app passwords are 16 chars and are displayed with spaces; strip
    # them out so paste-from-Google works without surprises.
    pwd = pwd.replace(" ", "")

    msg = EmailMessage()
    msg["From"] = formataddr((cfg.get("SMTP_FROM_NAME", "Papier Lab"), cfg.get("SMTP_FROM_EMAIL", user)))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text_body)
    if html_body:
        msg.add_alternative(html_body, subtype="html")

    port = int(cfg.get("SMTP_PORT", 587))
    use_tls = bool(cfg.get("SMTP_USE_TLS", True))

    try:
        if port == 465:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=ctx, timeout=15) as s:
                s.login(user, pwd)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=15) as s:
                s.ehlo()
                if use_tls:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                s.login(user, pwd)
                s.send_message(msg)
        return True, "sent"
    except smtplib.SMTPAuthenticationError as exc:
        current_app.logger.warning("SMTP auth failed: %s", exc)
        return False, "SMTP authentication failed. Check the Gmail App Password."
    except Exception as exc:
        current_app.logger.warning("SMTP send failed: %s", exc)
        return False, f"Could not send email: {exc.__class__.__name__}"


def render_otp_email(code: str, expires_minutes: int) -> tuple[str, str]:
    """Returns (plain_text, html) for the OTP email."""
    text = (
        "Hi from Papier Lab!\n\n"
        f"Your password reset code is:  {code}\n\n"
        f"This code expires in {expires_minutes} minutes. If you didn't "
        "request a password reset, you can ignore this email.\n\n"
        "— Papier Lab"
    )
    html = f"""\
<!DOCTYPE html>
<html><body style="margin:0;padding:0;background:#fff5f8;font-family:'Helvetica Neue',Arial,sans-serif;color:#2a1b25;">
  <table width="100%" cellpadding="0" cellspacing="0" style="padding:32px 16px;">
    <tr><td align="center">
      <table width="480" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:24px;
            border:1px solid #f8d6e3;box-shadow:0 18px 40px -22px rgba(236,79,138,.25);overflow:hidden;">
        <tr><td style="background:linear-gradient(135deg,#ffd2e1,#ffe2d1);padding:28px 32px;">
          <div style="font-family:Georgia,serif;font-size:22px;font-weight:700;color:#c5366d;">
            🌸 Papier Lab
          </div>
          <div style="color:#7a6470;font-size:14px;margin-top:4px;">password reset code</div>
        </td></tr>
        <tr><td style="padding:32px;">
          <p style="margin:0 0 14px;font-size:16px;">Hi friend,</p>
          <p style="margin:0 0 22px;font-size:15px;color:#4a3540;line-height:1.55;">
            Use the code below to reset your Papier Lab password. It expires in
            <b>{expires_minutes} minutes</b> — if you didn't ask for this, just ignore the email.
          </p>
          <div style="text-align:center;margin:22px 0;">
            <div style="display:inline-block;font-family:'Courier New',monospace;font-size:34px;letter-spacing:10px;
                        font-weight:700;color:#c5366d;background:#ffe9f0;padding:18px 28px;border-radius:18px;
                        border:1px dashed #ffb1cb;">
              {code}
            </div>
          </div>
          <p style="margin:18px 0 0;font-size:13px;color:#7a6470;">
            Stay cute,<br>The Papier Lab studio 🎀
          </p>
        </td></tr>
        <tr><td style="background:#fff1f6;padding:16px 32px;font-size:12px;color:#7a6470;text-align:center;">
          You're receiving this because someone requested a password reset for your account.
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""
    return text, html
