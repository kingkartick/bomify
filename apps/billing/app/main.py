"""
Billing service — public signup + Razorpay payment + automatic client provisioning.

Flow:
  1. Signup page calls POST /api/orders -> Razorpay order is created, signup stored as PENDING.
  2. Razorpay Checkout collects payment; the page posts the result to POST /api/verify.
     The Razorpay webhook (POST /api/webhooks/razorpay) is the fallback if the browser closes.
  3. Either path marks the signup PAID and starts provisioning in the background:
     client stack is created, health-checked, and the login is emailed. Status -> ACTIVE.
  4. The page polls GET /api/signups/{public_id} to show progress.
"""

import hmac
import json
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app import provisioner, razorpay
from app.config import settings
from app.db import SessionLocal, Signup, SignupStatus, init_db

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("billing")

STATIC_DIR = Path(__file__).parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    provisioner.resume_pending()
    yield


# Public-facing service: don't publish the API schema (it lists the admin endpoints)
app = FastAPI(
    title=f"{settings.PRODUCT_NAME} Billing",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

# Values end up in a docker compose env file, so keep them to safe characters
SAFE_TEXT = r"^[A-Za-z0-9][A-Za-z0-9 .,&()\-]*$"


class OrderRequest(BaseModel):
    plan_id: str
    company_name: str = Field(..., min_length=2, max_length=100, pattern=SAFE_TEXT)
    contact_name: str = Field(..., min_length=2, max_length=100, pattern=SAFE_TEXT)
    email: str = Field(..., max_length=255, pattern=r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")
    phone: str = Field("", max_length=20, pattern=r"^[0-9+\- ]*$")


class OrderResponse(BaseModel):
    signup_id: str
    order_id: str
    key_id: str
    amount: int
    currency: str


class VerifyRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


class SignupStatusResponse(BaseModel):
    signup_id: str
    status: SignupStatus
    email: str
    app_url: str | None = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mark_paid(order_id: str, payment_id: str | None) -> Signup | None:
    """PENDING -> PAID for this order. Idempotent; returns the signup if known."""
    with SessionLocal.begin() as db:
        db.execute(
            update(Signup)
            .where(Signup.razorpay_order_id == order_id, Signup.status == SignupStatus.PENDING)
            .values(
                status=SignupStatus.PAID,
                razorpay_payment_id=payment_id,
                paid_at=datetime.now(timezone.utc),
            )
        )
        return db.scalar(select(Signup).where(Signup.razorpay_order_id == order_id))


def _status_response(s: Signup) -> SignupStatusResponse:
    return SignupStatusResponse(
        signup_id=s.public_id,
        status=s.status,
        email=s.email,
        app_url=s.app_url if s.status == SignupStatus.ACTIVE else None,
    )


def require_billing_admin(authorization: str = Header("")) -> None:
    token = settings.BILLING_ADMIN_TOKEN
    if not token or not hmac.compare_digest(authorization.encode(), f"Bearer {token}".encode()):
        raise HTTPException(status_code=401, detail="Unauthorized")


# ---------------------------------------------------------------------------
# Public endpoints
# ---------------------------------------------------------------------------


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def public_config():
    """Everything the signup page needs to render plans and open Razorpay Checkout."""
    return {
        "product_name": settings.PRODUCT_NAME,
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "plans": [p.model_dump() for p in settings.plans.values()],
    }


@app.post("/api/orders", response_model=OrderResponse, status_code=201)
def create_order(body: OrderRequest):
    plan = settings.plans.get(body.plan_id)
    if plan is None:
        raise HTTPException(status_code=400, detail="Unknown plan")
    # Refuse before taking money rather than failing to provision after
    if not provisioner.has_capacity():
        log.error("Signup refused: server at client capacity")
        raise HTTPException(
            status_code=503,
            detail="We're not accepting new signups right now. Please contact us.",
        )

    public_id = uuid.uuid4().hex
    try:
        order = razorpay.create_order(
            amount=plan.amount,
            currency=plan.currency,
            receipt=public_id[:40],
            notes={"signup_id": public_id, "company": body.company_name, "email": body.email},
        )
    except httpx.HTTPError as exc:
        log.error("Razorpay order creation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Payment gateway unavailable, please retry")

    with SessionLocal.begin() as db:
        db.add(
            Signup(
                public_id=public_id,
                company_name=body.company_name.strip(),
                contact_name=body.contact_name.strip(),
                email=body.email.strip().lower(),
                phone=body.phone.strip(),
                plan_id=plan.id,
                amount=plan.amount,
                currency=plan.currency,
                razorpay_order_id=order["id"],
            )
        )
    return OrderResponse(
        signup_id=public_id,
        order_id=order["id"],
        key_id=settings.RAZORPAY_KEY_ID,
        amount=plan.amount,
        currency=plan.currency,
    )


@app.post("/api/verify", response_model=SignupStatusResponse)
def verify_payment(body: VerifyRequest, background: BackgroundTasks):
    """Called by the signup page after Razorpay Checkout succeeds."""
    if not razorpay.verify_payment_signature(
        body.razorpay_order_id, body.razorpay_payment_id, body.razorpay_signature
    ):
        raise HTTPException(status_code=400, detail="Payment signature verification failed")

    with SessionLocal() as db:
        pending = db.scalar(select(Signup).where(Signup.razorpay_order_id == body.razorpay_order_id))
    if pending is None:
        raise HTTPException(status_code=404, detail="Signup not found for this order")

    # The signature only proves authorization; make sure the money is actually captured,
    # otherwise Razorpay auto-refunds it after a few days while the client keeps the app.
    try:
        payment = razorpay.fetch_payment(body.razorpay_payment_id)
        if payment.get("status") == "authorized":
            payment = razorpay.capture_payment(payment["id"], pending.amount, pending.currency)
    except httpx.HTTPError as exc:
        log.error("Razorpay payment check failed: %s", exc)
        # The webhook will still confirm it; the page keeps polling
        raise HTTPException(status_code=502, detail="Could not confirm payment yet")
    if (
        payment.get("status") != "captured"
        or payment.get("order_id") != body.razorpay_order_id
        or payment.get("amount") != pending.amount
    ):
        log.error("Payment %s not acceptable: %s", body.razorpay_payment_id, payment.get("status"))
        raise HTTPException(status_code=400, detail="Payment was not completed")

    signup = _mark_paid(body.razorpay_order_id, body.razorpay_payment_id)
    if signup is None:
        raise HTTPException(status_code=404, detail="Signup not found for this order")
    background.add_task(provisioner.provision, signup.id)
    return _status_response(signup)


@app.post("/api/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    background: BackgroundTasks,
    x_razorpay_signature: str = Header(""),
):
    """Server-to-server confirmation; covers payments where the browser never returned."""
    body = await request.body()
    if not razorpay.verify_webhook_signature(body, x_razorpay_signature):
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    event = json.loads(body)
    payload = event.get("payload", {})
    payment = payload.get("payment", {}).get("entity", {})
    if event.get("event") == "order.paid":
        order_id = payload.get("order", {}).get("entity", {}).get("id")
    elif event.get("event") == "payment.captured":
        order_id = payment.get("order_id")
    else:
        return {"status": "ignored"}

    if order_id:
        signup = _mark_paid(order_id, payment.get("id"))
        if signup is not None:
            background.add_task(provisioner.provision, signup.id)
    return {"status": "ok"}


@app.get("/api/signups/{public_id}", response_model=SignupStatusResponse)
def signup_status(public_id: str):
    with SessionLocal() as db:
        signup = db.scalar(select(Signup).where(Signup.public_id == public_id))
    if signup is None:
        raise HTTPException(status_code=404, detail="Signup not found")
    return _status_response(signup)


# ---------------------------------------------------------------------------
# Operator endpoints (Authorization: Bearer $BILLING_ADMIN_TOKEN)
# ---------------------------------------------------------------------------


@app.get("/api/admin/signups", dependencies=[Depends(require_billing_admin)])
def admin_list_signups():
    with SessionLocal() as db:
        rows = db.scalars(select(Signup).order_by(Signup.id.desc()).limit(200)).all()
    return [
        {
            "id": s.id,
            "company_name": s.company_name,
            "email": s.email,
            "plan_id": s.plan_id,
            "amount": s.amount,
            "status": s.status,
            "slug": s.slug,
            "port": s.port,
            "app_url": s.app_url,
            "razorpay_order_id": s.razorpay_order_id,
            "razorpay_payment_id": s.razorpay_payment_id,
            "error": s.error,
            "created_at": s.created_at,
            "activated_at": s.activated_at,
        }
        for s in rows
    ]


@app.post("/api/admin/signups/{signup_id}/retry", dependencies=[Depends(require_billing_admin)])
def admin_retry(signup_id: int, background: BackgroundTasks):
    """Re-run provisioning for a FAILED signup (e.g. after fixing SMTP settings)."""
    with SessionLocal.begin() as db:
        result = db.execute(
            update(Signup)
            .where(Signup.id == signup_id, Signup.status == SignupStatus.FAILED)
            .values(status=SignupStatus.PAID)
        )
    if result.rowcount != 1:
        raise HTTPException(status_code=409, detail="Only failed signups can be retried")
    background.add_task(provisioner.provision, signup_id)
    return {"status": "retrying"}


# ---------------------------------------------------------------------------
# Signup page
# ---------------------------------------------------------------------------


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC_DIR / "index.html")
