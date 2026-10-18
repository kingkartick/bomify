"""
SQLite-backed storage for signups and their payment/provisioning state.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from app.config import settings


class Base(DeclarativeBase):
    pass


class SignupStatus(str, enum.Enum):
    PENDING = "pending"  # order created, awaiting payment
    PAID = "paid"  # payment verified, waiting to provision
    PROVISIONING = "provisioning"
    ACTIVE = "active"  # stack running; credentials shown on the signup page
    FAILED = "failed"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Signup(Base):
    __tablename__ = "signups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    public_id: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    company_name: Mapped[str] = mapped_column(String(100))
    contact_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), index=True)
    phone: Mapped[str] = mapped_column(String(20), default="")
    plan_id: Mapped[str] = mapped_column(String(50))
    amount: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3))

    razorpay_order_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    razorpay_payment_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[SignupStatus] = mapped_column(
        Enum(SignupStatus, values_callable=lambda x: [e.value for e in x]),
        default=SignupStatus.PENDING,
    )
    slug: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, unique=True, nullable=True)
    app_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    admin_username: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Initial admin password, shown on the payer's signup page (looked up by public_id)
    pending_password: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


engine = create_engine(
    settings.BILLING_DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
