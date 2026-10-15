"""
Credential email delivery over SMTP.
"""

import smtplib
from email.message import EmailMessage

from app.config import settings


def _send(msg: EmailMessage) -> None:
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER
    if settings.SMTP_USE_SSL:
        server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
    else:
        server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=30)
        server.starttls()
    with server:
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.send_message(msg)


def send_ops_alert(subject: str, body: str) -> None:
    if not settings.OPS_ALERT_EMAIL:
        return
    msg = EmailMessage()
    msg["Subject"] = f"[{settings.PRODUCT_NAME} billing] {subject}"
    msg["To"] = settings.OPS_ALERT_EMAIL
    msg.set_content(body)
    _send(msg)


def send_credentials(
    to: str, contact_name: str, company_name: str, url: str, username: str, password: str
) -> None:
    product = settings.PRODUCT_NAME
    msg = EmailMessage()
    msg["Subject"] = f"Your {product} workspace is ready"
    msg["To"] = to
    msg.set_content(
        f"""Hi {contact_name},

Thank you for your payment. The {product} workspace for {company_name} is now active.

  Login URL: {url}
  Username:  {username}
  Password:  {password}

Please sign in and change this password from the Users page as soon as possible.

— The {product} team
"""
    )
    _send(msg)
