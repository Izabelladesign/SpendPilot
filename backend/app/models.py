"""SQLAlchemy persistence models for SP-002.

The API layer serializes these snake_case model fields into the camelCase
contract documented in ``docs/api-contract.md``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid4())


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TaskStatus(StrEnum):
    REQUESTED = "REQUESTED"
    RESEARCHING = "RESEARCHING"
    PLANNING = "PLANNING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PaymentStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_RECONCILIATION = "PENDING_RECONCILIATION"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    tasks: Mapped[list[Task]] = relationship(back_populates="user")
    budgets: Mapped[list[Budget]] = relationship(back_populates="owner")


class Agent(TimestampMixin, Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200))
    agent_type: Mapped[str] = mapped_column(String(100))
    external_reference: Mapped[str | None] = mapped_column(String(255), unique=True)
    tasks: Mapped[list[Task]] = relationship(back_populates="agent")


class Budget(TimestampMixin, Base):
    __tablename__ = "budgets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    owner_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(200))
    currency: Mapped[str] = mapped_column(String(3))
    total: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    spent: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    reserved: Mapped[Decimal] = mapped_column(Numeric(18, 2), default=Decimal("0"))
    owner: Mapped[User] = relationship(back_populates="budgets")
    tasks: Mapped[list[Task]] = relationship(back_populates="budget")
    reservations: Mapped[list[BudgetReservation]] = relationship(back_populates="budget")


class Provider(TimestampMixin, Base):
    __tablename__ = "providers"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    service_description: Mapped[str | None] = mapped_column(Text)
    endpoint: Mapped[str | None] = mapped_column(String(500))
    payment_recipient: Mapped[str | None] = mapped_column(String(255), unique=True)
    is_approved: Mapped[bool] = mapped_column(default=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    tasks: Mapped[list[Task]] = relationship(back_populates="selected_provider")
    purchase_requests: Mapped[list[PurchaseRequest]] = relationship(back_populates="provider")
    payments: Mapped[list[Payment]] = relationship(back_populates="provider")


class Task(TimestampMixin, Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    agent_id: Mapped[str | None] = mapped_column(ForeignKey("agents.id"), index=True)
    budget_id: Mapped[str | None] = mapped_column(ForeignKey("budgets.id"), index=True)
    selected_provider_id: Mapped[str | None] = mapped_column(ForeignKey("providers.id"))
    objective: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal | None] = mapped_column(Numeric(18, 4))
    quality_target: Mapped[str | None] = mapped_column(Text)
    constraints: Mapped[list[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(32), default=TaskStatus.REQUESTED.value, index=True)
    output: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    failure_reason: Mapped[str | None] = mapped_column(Text)
    user: Mapped[User] = relationship(back_populates="tasks")
    agent: Mapped[Agent | None] = relationship(back_populates="tasks")
    budget: Mapped[Budget | None] = relationship(back_populates="tasks")
    selected_provider: Mapped[Provider | None] = relationship(back_populates="tasks")
    purchase_requests: Mapped[list[PurchaseRequest]] = relationship(back_populates="task")
    events: Mapped[list[AgentEvent]] = relationship(back_populates="task")
    approvals: Mapped[list[Approval]] = relationship(back_populates="task")
    shopping_items: Mapped[list[ShoppingItem]] = relationship(back_populates="task")


class PurchaseRequest(TimestampMixin, Base):
    __tablename__ = "purchase_requests"
    __table_args__ = (UniqueConstraint("task_id", "idempotency_key"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id"), index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255))
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    decision: Mapped[str] = mapped_column(String(32))
    decision_reason: Mapped[str] = mapped_column(Text)
    task: Mapped[Task] = relationship(back_populates="purchase_requests")
    provider: Mapped[Provider] = relationship(back_populates="purchase_requests")
    reservation: Mapped[BudgetReservation | None] = relationship(
        back_populates="purchase_request", uselist=False
    )
    payment: Mapped[Payment | None] = relationship(back_populates="purchase_request", uselist=False)
    approval: Mapped[Approval | None] = relationship(
        back_populates="purchase_request", uselist=False
    )


class BudgetReservation(TimestampMixin, Base):
    __tablename__ = "budget_reservations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    budget_id: Mapped[str] = mapped_column(ForeignKey("budgets.id"), index=True)
    purchase_request_id: Mapped[str] = mapped_column(
        ForeignKey("purchase_requests.id"), unique=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    status: Mapped[str] = mapped_column(String(32), default="ACTIVE")
    budget: Mapped[Budget] = relationship(back_populates="reservations")
    purchase_request: Mapped[PurchaseRequest] = relationship(back_populates="reservation")


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    purchase_request_id: Mapped[str] = mapped_column(
        ForeignKey("purchase_requests.id"), unique=True
    )
    provider_id: Mapped[str] = mapped_column(ForeignKey("providers.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    status: Mapped[str] = mapped_column(String(32), default=PaymentStatus.PENDING.value, index=True)
    transaction_reference: Mapped[str | None] = mapped_column(String(255), unique=True)
    task: Mapped[Task] = relationship()
    purchase_request: Mapped[PurchaseRequest] = relationship(back_populates="payment")
    provider: Mapped[Provider] = relationship(back_populates="payments")


class AgentEvent(TimestampMixin, Base):
    __tablename__ = "agent_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    message: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    task: Mapped[Task] = relationship(back_populates="events")


class Approval(TimestampMixin, Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    purchase_request_id: Mapped[str] = mapped_column(
        ForeignKey("purchase_requests.id"), unique=True
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    currency: Mapped[str] = mapped_column(String(3))
    vendor: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)
    reason: Mapped[str] = mapped_column(Text)
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task: Mapped[Task] = relationship(back_populates="approvals")
    purchase_request: Mapped[PurchaseRequest] = relationship(back_populates="approval")


class ShoppingItem(TimestampMixin, Base):
    __tablename__ = "shopping_items"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    merchant: Mapped[str | None] = mapped_column(String(200))
    url: Mapped[str | None] = mapped_column(String(1000))
    price: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    currency: Mapped[str | None] = mapped_column(String(3))
    availability: Mapped[str | None] = mapped_column(String(100))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    task: Mapped[Task] = relationship(back_populates="shopping_items")
