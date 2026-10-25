"""Seed deterministic demo records for local development."""

from decimal import Decimal

from app.database import SessionLocal
from app.models import Budget, User


def seed() -> None:
    with SessionLocal.begin() as db:
        user = db.query(User).filter_by(email="demo@spendpilot.local").one_or_none()
        if user is None:
            user = User(email="demo@spendpilot.local", display_name="SpendPilot Demo")
            db.add(user)
            db.flush()
        existing_budget = (
            db.query(Budget)
            .filter_by(owner_id=user.id, name="Demo operations budget")
            .one_or_none()
        )
        if existing_budget is None:
            db.add(
                Budget(
                    owner_id=user.id,
                    name="Demo operations budget",
                    currency="USD",
                    total=Decimal("500.00"),
                )
            )


if __name__ == "__main__":
    seed()
