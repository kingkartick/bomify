"""
Minimal Razorpay client: order creation and signature verification.
"""

import hashlib
import hmac

import httpx

from app.config import settings


def create_order(amount: int, currency: str, receipt: str, notes: dict) -> dict:
    """Create a Razorpay order; returns the order entity (contains `id`)."""
    resp = httpx.post(
        f"{settings.RAZORPAY_API_URL}/orders",
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
        json={
            "amount": amount,
            "currency": currency,
            "receipt": receipt,
            "notes": notes,
            "payment_capture": 1,
        },
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_payment(payment_id: str) -> dict:
    resp = httpx.get(
        f"{settings.RAZORPAY_API_URL}/payments/{payment_id}",
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def capture_payment(payment_id: str, amount: int, currency: str) -> dict:
    """Capture an authorized payment (needed when auto-capture is off on the account)."""
    resp = httpx.post(
        f"{settings.RAZORPAY_API_URL}/payments/{payment_id}/capture",
        auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET),
        json={"amount": amount, "currency": currency},
        timeout=20,
    )
    resp.raise_for_status()
    return resp.json()


def _hmac_hex(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_payment_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Checkout handler signature: HMAC_SHA256(order_id|payment_id, key_secret)."""
    if not settings.RAZORPAY_KEY_SECRET:
        return False
    expected = _hmac_hex(settings.RAZORPAY_KEY_SECRET, f"{order_id}|{payment_id}".encode())
    return hmac.compare_digest(expected, signature)


def verify_webhook_signature(body: bytes, signature: str) -> bool:
    """Webhook signature: HMAC_SHA256(raw_body, webhook_secret)."""
    if not settings.RAZORPAY_WEBHOOK_SECRET:
        return False
    expected = _hmac_hex(settings.RAZORPAY_WEBHOOK_SECRET, body)
    return hmac.compare_digest(expected, signature)
