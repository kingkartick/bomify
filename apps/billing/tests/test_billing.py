"""
Billing service tests — Razorpay is stubbed at the HTTP boundary; Docker is stubbed.

Run from apps/billing:  python -m pytest tests -v
"""

import hashlib
import hmac
import json
import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp())
os.environ.update(
    BILLING_DATABASE_URL=f"sqlite:///{TMP / 'billing.db'}",
    RAZORPAY_KEY_ID="rzp_test_key",
    RAZORPAY_KEY_SECRET="key_secret",
    RAZORPAY_WEBHOOK_SECRET="hook_secret",
    DEPLOY_DIR=str(TMP),
    PUBLIC_HOST="203.0.113.10",
    CLIENT_PORT_START="8081",
    CLIENT_PORT_END="8083",
    BILLING_ADMIN_TOKEN="ops-token",
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app import main, provisioner, razorpay  # noqa: E402
from app.db import SessionLocal, Signup, SignupStatus  # noqa: E402

SIGNUP = {
    "plan_id": "standard",
    "company_name": "Acme Industries",
    "contact_name": "Ravi Kumar",
    "email": "Ravi@Acme.example",
    "phone": "+91 98765 43210",
}


def sign(secret: str, message: bytes) -> str:
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


@pytest.fixture()
def env(monkeypatch):
    """Stub Razorpay/Docker and record what the provisioner did."""
    calls = {"orders": [], "stacks": [], "captures": []}
    # payment_id -> payment entity as Razorpay would return it; tests may override
    payments = {}
    calls["payments"] = payments
    counter = iter(range(1, 1000))

    def fake_create_order(amount, currency, receipt, notes):
        calls["orders"].append(amount)
        return {"id": f"order_{next(counter)}", "amount": amount, "currency": currency}

    def fake_fetch_payment(payment_id):
        return dict(payments[payment_id])

    def fake_capture_payment(payment_id, amount, currency):
        calls["captures"].append(payment_id)
        payments[payment_id]["status"] = "captured"
        return dict(payments[payment_id])

    def fake_create_stack(signup, password):
        calls["stacks"].append((signup.slug, signup.port, password))
        (TMP / f".env.{signup.slug}").write_text(f"WEB_PORT={signup.port}\n")

    monkeypatch.setattr(razorpay, "create_order", fake_create_order)
    monkeypatch.setattr(razorpay, "fetch_payment", fake_fetch_payment)
    monkeypatch.setattr(razorpay, "capture_payment", fake_capture_payment)
    monkeypatch.setattr(provisioner, "create_stack", fake_create_stack)
    monkeypatch.setattr(provisioner, "wait_until_healthy", lambda port: None)

    with TestClient(main.app) as client:
        yield client, calls

    for f in TMP.glob(".env.*"):
        f.unlink()
    with SessionLocal.begin() as db:
        db.query(Signup).delete()


def create_order(client, **overrides):
    resp = client.post("/api/orders", json={**SIGNUP, **overrides})
    assert resp.status_code == 201, resp.text
    return resp.json()


def checkout_success(client, order, payment_id="pay_1", secret="key_secret", payments=None):
    if payments is not None:
        payments.setdefault(payment_id, {
            "id": payment_id, "order_id": order["order_id"], "amount": order["amount"], "status": "captured",
        })
    return client.post(
        "/api/verify",
        json={
            "razorpay_order_id": order["order_id"],
            "razorpay_payment_id": payment_id,
            "razorpay_signature": sign(secret, f"{order['order_id']}|{payment_id}".encode()),
        },
    )


def webhook(client, body: dict, secret="hook_secret"):
    raw = json.dumps(body).encode()
    return client.post(
        "/api/webhooks/razorpay",
        content=raw,
        headers={"X-Razorpay-Signature": sign(secret, raw), "Content-Type": "application/json"},
    )


def test_config_exposes_plans_and_key(env):
    client, _ = env
    data = client.get("/api/config").json()
    assert data["razorpay_key_id"] == "rzp_test_key"
    assert data["plans"][0]["id"] == "standard"
    assert client.get("/").status_code == 200


def test_order_rejects_unknown_plan_and_unsafe_text(env):
    client, _ = env
    assert client.post("/api/orders", json={**SIGNUP, "plan_id": "nope"}).status_code == 400
    assert client.post("/api/orders", json={**SIGNUP, "company_name": "Acme $(rm -rf)"}).status_code == 422
    assert client.post("/api/orders", json={**SIGNUP, "email": "not-an-email"}).status_code == 422


def test_full_flow_provisions_and_shows_login(env):
    client, calls = env
    order = create_order(client)
    assert calls["orders"] == [499900]
    assert client.get(f"/api/signups/{order['signup_id']}").json()["status"] == "pending"

    resp = checkout_success(client, order, payments=calls["payments"])
    assert resp.status_code == 200, resp.text

    status = client.get(f"/api/signups/{order['signup_id']}").json()
    assert status["status"] == "active"
    assert status["app_url"] == "http://203.0.113.10:8081"

    (slug, port, password), = calls["stacks"]
    assert (status["username"], status["password"]) == ("admin", password)
    assert (slug, port) == ("acmeindustries", 8081)
    assert password.isalnum() and len(password) == 14

    with SessionLocal() as db:
        s = db.query(Signup).one()
        assert s.razorpay_payment_id == "pay_1"


def test_bad_checkout_signature_rejected(env):
    client, calls = env
    order = create_order(client)
    assert checkout_success(client, order, secret="wrong", payments=calls["payments"]).status_code == 400
    assert client.get(f"/api/signups/{order['signup_id']}").json()["status"] == "pending"
    assert calls["stacks"] == []


def test_webhook_and_checkout_provision_only_once(env):
    client, calls = env
    order = create_order(client)
    event = {
        "event": "payment.captured",
        "payload": {"payment": {"entity": {"id": "pay_9", "order_id": order["order_id"]}}},
    }
    assert webhook(client, event).status_code == 200
    assert checkout_success(client, order, payment_id="pay_9", payments=calls["payments"]).status_code == 200
    assert webhook(client, {**event, "event": "order.paid",
                            "payload": {**event["payload"], "order": {"entity": {"id": order["order_id"]}}}}
                   ).status_code == 200
    assert len(calls["stacks"]) == 1


def test_webhook_bad_signature_and_unrelated_events(env):
    client, calls = env
    order = create_order(client)
    event = {"event": "payment.captured",
             "payload": {"payment": {"entity": {"id": "p", "order_id": order["order_id"]}}}}
    assert webhook(client, event, secret="forged").status_code == 400
    assert webhook(client, {"event": "payment.failed", "payload": {}}).json() == {"status": "ignored"}
    assert calls["stacks"] == []


def test_slug_and_port_avoid_existing_clients(env):
    client, calls = env
    # A client added by hand with add-client.sh already uses this slug and port 8081
    (TMP / ".env.acmeindustries").write_text("WEB_PORT=8081\n")
    checkout_success(client, create_order(client), payment_id="pay_a", payments=calls["payments"])
    checkout_success(client, create_order(client), payment_id="pay_b", payments=calls["payments"])
    assert [(s, p) for s, p, _ in calls["stacks"]] == [("acmeindustries2", 8082), ("acmeindustries3", 8083)]


def test_failure_is_recorded_and_retry_reuses_stack(env, monkeypatch):
    client, calls = env

    def never_healthy(port):
        raise TimeoutError("stack never became healthy")

    monkeypatch.setattr(provisioner, "wait_until_healthy", never_healthy)
    order = create_order(client)
    checkout_success(client, order, payments=calls["payments"])
    status = client.get(f"/api/signups/{order['signup_id']}").json()
    assert status["status"] == "failed" and status["password"] is None

    admin = {"Authorization": "Bearer ops-token"}
    assert client.get("/api/admin/signups").status_code == 401
    rows = client.get("/api/admin/signups", headers=admin).json()
    assert "never became healthy" in rows[0]["error"]

    monkeypatch.setattr(provisioner, "wait_until_healthy", lambda port: None)
    assert client.post(f"/api/admin/signups/{rows[0]['id']}/retry", headers=admin).status_code == 200
    assert client.get(f"/api/signups/{order['signup_id']}").json()["status"] == "active"
    # Same slug/port/password as the first attempt, not a second stack
    assert calls["stacks"][0] == calls["stacks"][1]
    assert client.get(f"/api/signups/{order['signup_id']}").json()["password"] == calls["stacks"][0][2]
    assert client.post(f"/api/admin/signups/{rows[0]['id']}/retry", headers=admin).status_code == 409


def test_interrupted_provisioning_resumes_on_startup(env):
    client, calls = env
    order = create_order(client)
    with SessionLocal.begin() as db:
        s = db.query(Signup).one()
        s.status = SignupStatus.PROVISIONING  # e.g. container restarted mid-provision
    provisioner.resume_pending()
    for t in __import__("threading").enumerate():
        if t.name != "MainThread" and t.daemon:
            t.join(timeout=5)
    assert client.get(f"/api/signups/{order['signup_id']}").json()["status"] == "active"


def test_authorized_payment_is_captured_before_provisioning(env):
    client, calls = env
    order = create_order(client)
    calls["payments"]["pay_auth"] = {
        "id": "pay_auth", "order_id": order["order_id"], "amount": order["amount"], "status": "authorized",
    }
    assert checkout_success(client, order, payment_id="pay_auth").status_code == 200
    assert calls["captures"] == ["pay_auth"]
    assert client.get(f"/api/signups/{order['signup_id']}").json()["status"] == "active"


@pytest.mark.parametrize("override", [
    {"status": "failed"},
    {"amount": 100},
    {"order_id": "order_other"},
])
def test_payment_not_matching_order_is_rejected(env, override):
    client, calls = env
    order = create_order(client)
    calls["payments"]["pay_bad"] = {
        "id": "pay_bad", "order_id": order["order_id"], "amount": order["amount"], "status": "captured",
        **override,
    }
    assert checkout_success(client, order, payment_id="pay_bad").status_code == 400
    assert client.get(f"/api/signups/{order['signup_id']}").json()["status"] == "pending"
    assert calls["stacks"] == []


def test_orders_refused_before_payment_when_full(env, monkeypatch):
    client, calls = env
    monkeypatch.setattr(provisioner.settings, "MAX_CLIENTS", 2)
    (TMP / ".env.manual").write_text("WEB_PORT=8081\n")  # one client added by hand
    checkout_success(client, create_order(client), payments=calls["payments"])
    resp = client.post("/api/orders", json=SIGNUP)
    assert resp.status_code == 503
    assert calls["orders"] == [499900]  # no Razorpay order created for the refused signup


def test_api_docs_not_public(env):
    client, _ = env
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404
