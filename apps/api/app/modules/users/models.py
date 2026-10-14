"""
User SQLAlchemy models — Users table with module-based access control.
"""

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Module(str, enum.Enum):
    DASHBOARD = "dashboard"
    SALES = "sales"
    PURCHASES = "purchases"
    PRODUCTION = "production"
    INVENTORY = "inventory"
    DISPATCH = "dispatch"
    PARTIES = "parties"
    COPILOT = "copilot"
    USERS = "users"
    SETTINGS = "settings"


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )
    full_name: Mapped[str] = mapped_column(String(100), nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    module_accesses: Mapped[list["UserModuleAccess"]] = relationship(
        "UserModuleAccess",
        back_populates="user",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    @property
    def modules(self) -> list[Module]:
        return [a.module for a in self.module_accesses]

    @property
    def module_permissions(self) -> list[Module]:
        return self.modules

    def __repr__(self) -> str:
        return f"<User {self.username}>"


class UserModuleAccess(Base):
    __tablename__ = "user_module_access"
    __table_args__ = (UniqueConstraint("user_id", "module"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    module: Mapped[Module] = mapped_column(
        Enum(Module, values_callable=lambda x: [e.value for e in x]),
        nullable=False,
    )

    user: Mapped["User"] = relationship("User", back_populates="module_accesses")
