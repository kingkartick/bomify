"""
Billing service configuration — read from environment variables.
"""

import json

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Plan(BaseModel):
    id: str
    name: str
    amount: int  # smallest currency unit (paise for INR)
    currency: str = "INR"
    description: str = ""


DEFAULT_PLANS = [
    {
        "id": "standard",
        "name": "Standard",
        "amount": 499900,
        "currency": "INR",
        "description": "Full QuadStack workspace: sales, purchases, production, inventory, dispatch.",
    }
]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    PRODUCT_NAME: str = "QuadStack"

    # SQLite file holding signups/payments (mount a volume in production)
    BILLING_DATABASE_URL: str = "sqlite:///./billing.db"

    # Razorpay (Dashboard -> Account & Settings -> API Keys / Webhooks)
    RAZORPAY_KEY_ID: str = ""
    RAZORPAY_KEY_SECRET: str = ""
    RAZORPAY_WEBHOOK_SECRET: str = ""
    RAZORPAY_API_URL: str = "https://api.razorpay.com/v1"

    # JSON list of plans; see DEFAULT_PLANS for the shape
    BILLING_PLANS: str = json.dumps(DEFAULT_PLANS)

    # Provisioning
    DEPLOY_DIR: str = "/srv/bomify"  # repo checkout containing deploy/add-client.sh
    PUBLIC_HOST: str = "localhost"  # host/IP clients use to reach their app
    APP_URL_TEMPLATE: str = "http://{host}:{port}"
    HEALTHCHECK_HOST: str = "host.docker.internal"
    CLIENT_PORT_START: int = 8081
    CLIENT_PORT_END: int = 8180
    # Client stacks this server can run (~600-800 MB RAM each); signups are refused
    # before payment once reached. Counts stacks added by hand with add-client.sh too,
    # but not the main .env.prod stack on port 80.
    MAX_CLIENTS: int = 10
    PROVISION_TIMEOUT_SECONDS: int = 300
    CLIENT_ADMIN_USERNAME: str = "admin"

    # SMTP for credential emails
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_SSL: bool = False  # True for port 465; otherwise STARTTLS
    # Operator address alerted when provisioning fails (optional)
    OPS_ALERT_EMAIL: str = ""

    # Bearer token for the /admin endpoints (empty disables them)
    BILLING_ADMIN_TOKEN: str = ""

    @property
    def plans(self) -> dict[str, Plan]:
        return {p["id"]: Plan(**p) for p in json.loads(self.BILLING_PLANS)}


settings = Settings()
