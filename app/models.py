"""SQLAlchemy 2.0 ORM models using the mapped_column declarative style."""

from __future__ import annotations

import enum
from datetime import date, datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class BillingCycleModel(str, enum.Enum):
    weekly = "weekly"
    monthly = "monthly"
    yearly = "yearly"


class SubscriptionStatus(str, enum.Enum):
    active = "active"
    cancelled = "cancelled"


class ChargeStatus(str, enum.Enum):
    pending = "pending"
    settled = "settled"
    failed = "failed"


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    cost: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="GBP", nullable=False)
    billing_cycle: Mapped[BillingCycleModel] = mapped_column(
        Enum(BillingCycleModel), nullable=False
    )
    next_billing_date: Mapped[date] = mapped_column(nullable=False)
    category: Mapped[str] = mapped_column(
        String(100), default="uncategorised", nullable=False
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus), default=SubscriptionStatus.active, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    charges: Mapped[list[Charge]] = relationship(
        "Charge", back_populates="subscription", cascade="all, delete-orphan"
    )


class Charge(Base):
    __tablename__ = "charges"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id"), nullable=False, index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    charged_on: Mapped[date] = mapped_column(nullable=False)
    status: Mapped[ChargeStatus] = mapped_column(
        Enum(ChargeStatus), default=ChargeStatus.pending, nullable=False
    )

    subscription: Mapped[Subscription] = relationship(
        "Subscription", back_populates="charges"
    )
